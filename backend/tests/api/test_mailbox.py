"""Mailbox (Gmail, Outlook) through the API: connect, sync, suggest, link, disconnect, erasure.
Every provider endpoint is mocked with respx: no network."""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx
from sqlalchemy import select

from app.connectors import crypto
from app.db.models import (
    Activity,
    ContactChannel,
    MailboxConnection,
    MailboxMessage,
    Run,
    Workspace,
)

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)
G_TOKEN = "https://oauth2.googleapis.com/token"  # noqa: S105
G_API = "https://gmail.googleapis.com/gmail/v1/users/me"
MS_TOKEN = "https://login.microsoftonline.com/common/oauth2/v2.0/token"  # noqa: S105
GRAPH = "https://graph.microsoft.com/v1.0"
SECRET_VALUES = ("ACCESS-ONE", "REFRESH-ONE", "ACCESS-TWO", "REFRESH-TWO", "CLIENT-SECRET")
OWN = "me@corp.example"


def _gmail(mid, sender, subject, to=(OWN,), days=1.0, snippet="snip"):
    return {
        "id": mid,
        "threadId": "t-" + mid,
        "internalDate": str(int((NOW - timedelta(days=days)).timestamp() * 1000)),
        "snippet": snippet,
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "To", "value": ", ".join(to)},
                {"name": "Subject", "value": subject},
            ]
        },
    }


def _b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


@pytest.fixture
def setup(client, db_session, api_settings, monkeypatch):
    monkeypatch.setattr(crypto, "get_settings", lambda: api_settings)
    client.post("/api/workspaces", json={"slug": "mb", "name": "MB"})
    ws = "/api/w/mb"
    acme = client.post(f"{ws}/accounts", json={"name": "Acme", "domain": "acme.example"}).json()
    other = client.post(
        f"{ws}/accounts", json={"name": "Globex", "domain": "globex.example"}
    ).json()
    jo = client.post(
        f"{ws}/contacts", json={"account_id": acme["id"], "full_name": "Jo Doe"}
    ).json()
    created = (NOW - timedelta(days=60)).date().isoformat()
    d_exp = client.post(
        f"{ws}/deals",
        json={
            "account_id": acme["id"],
            "name": "Expansion",
            "stage": "proposal",
            "created_on": created,
        },
    ).json()
    d_other = client.post(
        f"{ws}/deals",
        json={
            "account_id": other["id"],
            "name": "Globex pilot",
            "stage": "prospecting",
            "created_on": created,
        },
    ).json()
    ws_row = db_session.scalars(select(Workspace).where(Workspace.slug == "mb")).one()
    db_session.add(
        ContactChannel(
            workspace_id=ws_row.id,
            contact_id=uuid.UUID(jo["id"]),
            kind="email",
            provider="fake",
            value_enc=crypto.seal("Jo@Acme.example", api_settings),
        )
    )
    db_session.commit()
    return {
        "ws": ws,
        "ws_id": ws_row.id,
        "acme": acme,
        "jo": jo,
        "d_exp": d_exp,
        "d_other": d_other,
    }


@pytest.fixture
def mock():
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as m:
        yield m


def _token_reply(access="ACCESS-ONE", refresh="REFRESH-ONE"):
    body = {"access_token": access, "token_type": "Bearer", "expires_in": 3600, "scope": "x"}
    if refresh:
        body["refresh_token"] = refresh
    return httpx.Response(200, json=body)


def connect_gmail(client, s, mock):
    mock.post(G_TOKEN).mock(return_value=_token_reply())
    mock.get("https://openidconnect.googleapis.com/v1/userinfo").mock(
        return_value=httpx.Response(200, json={"email": OWN})
    )
    client.put(
        f"{s['ws']}/mailbox/gmail/client",
        json={"client_id": "gid", "client_secret": "CLIENT-SECRET"},
    )
    url = client.post(f"{s['ws']}/mailbox/gmail/connect").json()["authorize_url"]
    q = parse_qs(urlsplit(url).query)
    r = client.get(
        "/api/mailbox/callback",
        params={"state": q["state"][0], "code": "CODE"},
        follow_redirects=False,
    )
    return url, r


def test_gmail_connect_flow_and_status(client, setup, mock):
    s = setup
    url, r = connect_gmail(client, s, mock)
    q = parse_qs(urlsplit(url).query)
    assert q["redirect_uri"] == ["http://127.0.0.1:8800/api/mailbox/callback"]
    assert q["code_challenge_method"] == ["S256"] and q["client_id"] == ["gid"]
    assert r.status_code == 303 and r.headers["location"] == "/w/mb/settings?mailbox=connected"
    sent = mock.calls[0].request.content.decode()
    assert "code_verifier=" in sent and "client_secret=CLIENT-SECRET" in sent
    status = client.get(f"{s['ws']}/mailbox").json()
    gm = next(c for c in status["connections"] if c["provider"] == "gmail")
    assert gm["status"] == "connected" and gm["account_email"] == OWN
    assert gm["client_source"] == "settings"
    dump = client.get(f"{s['ws']}/mailbox").text
    assert not any(v in dump for v in SECRET_VALUES)


def test_tokens_are_sealed_at_rest(client, setup, mock, db_session):
    connect_gmail(client, setup, mock)
    conn = db_session.scalars(select(MailboxConnection)).one()
    for col in (
        conn.access_token_enc,
        conn.refresh_token_enc,
        conn.client_secret_enc,
        conn.account_email_enc,
    ):
        assert col and not any(v in col for v in SECRET_VALUES) and OWN not in col


def test_callback_needs_valid_state_and_cookie(client, setup, mock):
    s = setup
    r = client.get(
        "/api/mailbox/callback", params={"state": "nope", "code": "c"}, follow_redirects=False
    )
    assert r.headers["location"] == "/?mailbox=error&reason=invalid_state"
    client.put(f"{s['ws']}/mailbox/gmail/client", json={"client_id": "gid"})
    url = client.post(f"{s['ws']}/mailbox/gmail/connect").json()["authorize_url"]
    state = parse_qs(urlsplit(url).query)["state"][0]
    client.cookies.clear()  # another browser: no binding cookie
    r = client.get(
        "/api/mailbox/callback", params={"state": state, "code": "c"}, follow_redirects=False
    )
    assert "reason=invalid_state" in r.headers["location"]
    # single use: the state is spent
    r = client.get(
        "/api/mailbox/callback", params={"state": state, "code": "c"}, follow_redirects=False
    )
    assert r.headers["location"] == "/?mailbox=error&reason=invalid_state"


def test_connect_without_client_is_refused(client, setup):
    r = client.post(f"{setup['ws']}/mailbox/gmail/connect")
    assert r.status_code == 409


def _mock_gmail_inbox(mock, messages, bodies=None):
    by_id = {m["id"]: m for m in messages}

    def listing(request):
        return httpx.Response(200, json={"messages": [{"id": i} for i in by_id]})

    def one(request):
        mid = request.url.path.rsplit("/", 1)[1]
        if request.url.params.get("format") == "full":
            return httpx.Response(
                200,
                json={
                    "payload": {
                        "mimeType": "text/plain",
                        "body": {"data": _b64((bodies or {})[mid])},
                    }
                },
            )
        return httpx.Response(200, json=by_id[mid])

    mock.get(f"{G_API}/messages").mock(side_effect=listing)
    mock.get(url__regex=rf"{G_API}/messages/.+").mock(side_effect=one)


MESSAGES = [
    _gmail("m1", "Jo Doe <jo@acme.example>", "Re: Expansion pricing", days=1),
    _gmail("m2", "Newsletter <news@shop.example>", "Big sale"),
    _gmail("m3", "Pat <pat@globex.example>", "Hello there", days=2),
    _gmail("m4", f"Me <{OWN}>", "Following up", to=("jo@acme.example",), days=3),
    _gmail("m5", "Friend <friend@gmail.com>", "Dinner?"),
]


def test_sync_stores_only_candidates_and_is_idempotent(client, setup, mock, db_session):
    s = setup
    connect_gmail(client, s, mock)
    _mock_gmail_inbox(mock, MESSAGES)
    r1 = client.post(f"{s['ws']}/mailbox/sync").json()
    assert (r1["fetched"], r1["candidates"], r1["new"]) == (5, 3, 3) and r1["errors"] == []
    refs = set(db_session.scalars(select(MailboxMessage.provider_message_id)))
    assert refs == {"m1", "m3", "m4"}  # newsletter and webmail friend never stored
    r2 = client.post(f"{s['ws']}/mailbox/sync").json()
    assert r2["new"] == 0
    assert db_session.scalars(select(MailboxMessage)).all().__len__() == 3
    # the run holds counts only, no address
    run = db_session.scalars(select(Run).where(Run.kind == "mailbox_sync")).first()
    assert run.result["candidates"] == 3 and "@" not in str(run.result) + str(run.params)
    row = db_session.scalars(
        select(MailboxMessage).where(MailboxMessage.provider_message_id == "m1")
    ).one()
    assert str(row.suggested_deal_id) == s["d_exp"]["id"] and row.score >= 70
    assert "From: a contact of Acme" in row.reasons


def test_suggestions_list_for_deal_and_unmatched(client, setup, mock):
    s = setup
    connect_gmail(client, s, mock)
    _mock_gmail_inbox(mock, MESSAGES)
    client.post(f"{s['ws']}/mailbox/sync")
    mine = client.get(f"{s['ws']}/mailbox/messages", params={"deal_id": s["d_exp"]["id"]}).json()
    assert {m["subject"] for m in mine} >= {"Re: Expansion pricing"}
    assert all("@" in m["from_addr"] and "body" not in m for m in mine)
    unmatched = client.get(f"{s['ws']}/mailbox/messages", params={"unmatched": "true"}).json()
    assert all(m["suggested_deal_id"] is None for m in unmatched)
    found = client.get(f"{s['ws']}/mailbox/messages", params={"q": "hello"}).json()
    assert [m["subject"] for m in found] == ["Hello there"]
    assert client.get(f"{s['ws']}/mailbox/messages", params={"q": "%"}).json() == []


def test_link_creates_email_activity_idempotently(client, setup, mock, db_session):
    s = setup
    connect_gmail(client, s, mock)
    _mock_gmail_inbox(mock, MESSAGES, {"m1": "x" * 20_000, "m4": "Hi Jo"})
    client.post(f"{s['ws']}/mailbox/sync")
    rows = {m["subject"]: m for m in client.get(f"{s['ws']}/mailbox/messages").json()}
    m1 = rows["Re: Expansion pricing"]
    r = client.post(
        f"{s['ws']}/mailbox/messages/{m1['id']}/link", json={"deal_id": s["d_exp"]["id"]}
    )
    assert r.status_code == 200 and r.json()["state"] == "linked"
    again = client.post(
        f"{s['ws']}/mailbox/messages/{m1['id']}/link", json={"deal_id": s["d_exp"]["id"]}
    )
    assert again.status_code == 200
    acts = db_session.scalars(select(Activity).where(Activity.source == "mailbox")).all()
    assert len(acts) == 1
    a = acts[0]
    assert a.kind == "email" and a.direction == "inbound" and a.external_ref == "m1"
    assert len(a.body) == 10_000 and a.subject == "Re: Expansion pricing"
    listed = client.get(f"{s['ws']}/deals/{s['d_exp']['id']}/activities").json()
    assert [p["id"] for p in listed[0]["participants"]] == [s["jo"]["id"]]
    # outbound mail: the sender is the connected address
    m4 = rows["Following up"]
    client.post(f"{s['ws']}/mailbox/messages/{m4['id']}/link", json={"deal_id": s["d_exp"]["id"]})
    out = db_session.scalars(select(Activity).where(Activity.external_ref == "m4")).one()
    assert out.direction == "outbound"
    # linking to another deal while linked is refused; unlink then relink elsewhere
    other = client.post(
        f"{s['ws']}/mailbox/messages/{m1['id']}/link", json={"deal_id": s["d_other"]["id"]}
    )
    assert other.status_code == 422


def test_manual_link_to_any_open_deal_and_unlink_ignore(client, setup, mock, db_session):
    s = setup
    connect_gmail(client, s, mock)
    _mock_gmail_inbox(mock, MESSAGES, {"m3": "pat says hi"})
    client.post(f"{s['ws']}/mailbox/sync")
    rows = {m["subject"]: m for m in client.get(f"{s['ws']}/mailbox/messages").json()}
    m3 = rows["Hello there"]
    r = client.post(
        f"{s['ws']}/mailbox/messages/{m3['id']}/link", json={"deal_id": s["d_exp"]["id"]}
    )
    assert r.status_code == 200  # a Globex email, manually attached to an Acme deal
    act = db_session.scalars(select(Activity).where(Activity.external_ref == "m3")).one()
    assert str(act.account_id) == s["acme"]["id"]
    un = client.post(f"{s['ws']}/mailbox/messages/{m3['id']}/unlink").json()
    assert un["state"] == "suggested" and un["linked_activity_id"] is None
    assert db_session.scalars(select(Activity).where(Activity.external_ref == "m3")).first() is None
    ig = client.post(f"{s['ws']}/mailbox/messages/{m3['id']}/ignore").json()
    assert ig["state"] == "ignored"
    client.post(f"{s['ws']}/mailbox/sync")  # a re-sync does not resurrect an ignored email
    assert (
        client.get(f"{s['ws']}/mailbox/messages", params={"state": "ignored"}).json()[0]["id"]
        == m3["id"]
    )
    # a closed deal cannot receive emails
    closed = client.put(
        f"{s['ws']}/deals/{s['d_other']['id']}/stage", json={"stage": "closed_lost"}
    )
    assert closed.status_code == 200
    bad = client.post(
        f"{s['ws']}/mailbox/messages/{m3['id']}/link", json={"deal_id": s["d_other"]["id"]}
    )
    assert bad.status_code == 422


def test_disconnect_keeps_linked_and_drops_the_rest(client, setup, mock, db_session):
    s = setup
    connect_gmail(client, s, mock)
    revoke = mock.post("https://oauth2.googleapis.com/revoke").mock(
        return_value=httpx.Response(200)
    )
    _mock_gmail_inbox(mock, MESSAGES, {"m1": "body"})
    client.post(f"{s['ws']}/mailbox/sync")
    m1 = next(
        m
        for m in client.get(f"{s['ws']}/mailbox/messages").json()
        if m["subject"].startswith("Re:")
    )
    client.post(f"{s['ws']}/mailbox/messages/{m1['id']}/link", json={"deal_id": s["d_exp"]["id"]})
    assert client.delete(f"{s['ws']}/mailbox/gmail").status_code == 204
    assert revoke.called
    conn = db_session.scalars(select(MailboxConnection)).one()
    assert conn.status == "configured" and conn.access_token_enc is None
    assert conn.refresh_token_enc is None and conn.account_email_enc is None
    left = db_session.scalars(select(MailboxMessage)).all()
    assert [m.state for m in left] == ["linked"]
    assert db_session.scalars(select(Activity).where(Activity.source == "mailbox")).all()


def test_revoke_failure_does_not_block_disconnect(client, setup, mock):
    connect_gmail(client, setup, mock)
    mock.post("https://oauth2.googleapis.com/revoke").mock(side_effect=httpx.ConnectError("down"))
    assert client.delete(f"{setup['ws']}/mailbox/gmail").status_code == 204


def test_invalid_grant_marks_needs_reconnect(client, setup, mock, db_session):
    s = setup
    connect_gmail(client, s, mock)
    conn = db_session.scalars(select(MailboxConnection)).one()
    conn.token_expires_at = NOW - timedelta(minutes=5)
    db_session.commit()
    mock.post(G_TOKEN).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    r = client.post(f"{s['ws']}/mailbox/sync").json()
    assert r["errors"] and "reconnect" in r["errors"][0]
    db_session.expire_all()
    conn = db_session.scalars(select(MailboxConnection)).one()
    assert conn.status == "needs_reconnect" and conn.refresh_token_enc is None
    gm = next(
        c
        for c in client.get(f"{s['ws']}/mailbox").json()["connections"]
        if c["provider"] == "gmail"
    )
    assert gm["status"] == "needs_reconnect"
    assert client.post(f"{s['ws']}/mailbox/sync", json={"provider": "gmail"}).status_code == 409


def test_outlook_refresh_rotates_the_refresh_token(client, setup, mock, db_session, api_settings):
    s = setup
    ws = s["ws"]
    mock.post(MS_TOKEN).mock(return_value=_token_reply())
    mock.get(f"{GRAPH}/me").mock(return_value=httpx.Response(200, json={"mail": OWN}))
    client.put(f"{ws}/mailbox/outlook/client", json={"client_id": "mid"})
    url = client.post(f"{ws}/mailbox/outlook/connect").json()["authorize_url"]
    q = parse_qs(urlsplit(url).query)
    assert q["redirect_uri"] == ["http://localhost:8800/api/mailbox/callback"]
    client.cookies.clear()  # the callback is on `localhost`: the 127.0.0.1 cookie is not sent
    r = client.get(
        "/api/mailbox/callback",
        params={"state": q["state"][0], "code": "C"},
        follow_redirects=False,
    )
    assert r.headers["location"] == "/w/mb/settings?mailbox=connected"
    conn = db_session.scalars(select(MailboxConnection)).one()
    conn.token_expires_at = NOW - timedelta(minutes=5)
    db_session.commit()
    mock.post(MS_TOKEN).mock(return_value=_token_reply("ACCESS-TWO", "REFRESH-TWO"))
    graph_msg = {
        "id": "o1",
        "conversationId": "c1",
        "receivedDateTime": (NOW - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "subject": "Expansion kickoff",
        "bodyPreview": "preview",
        "from": {"emailAddress": {"address": "Jo@Acme.example"}},
        "toRecipients": [{"emailAddress": {"address": OWN}}],
        "ccRecipients": [],
    }
    mock.get(f"{GRAPH}/me/messages").mock(
        return_value=httpx.Response(200, json={"value": [graph_msg]})
    )
    assert client.post(f"{ws}/mailbox/sync").json()["new"] == 1
    db_session.expire_all()
    conn = db_session.scalars(select(MailboxConnection)).one()
    assert crypto.unseal(conn.refresh_token_enc, api_settings) == "REFRESH-TWO"
    assert crypto.unseal(conn.access_token_enc, api_settings) == "ACCESS-TWO"
    sent = [c.request for c in mock.calls if c.request.url.path.endswith("/me/messages")]
    assert sent[0].headers["authorization"] == "Bearer ACCESS-TWO"
    # linking an Outlook mail reads the text body once
    mock.get(url__regex=rf"{GRAPH}/me/messages/o1.*").mock(
        return_value=httpx.Response(
            200, json={"body": {"contentType": "html", "content": "<p>Hello <b>Jo</b></p>"}}
        )
    )
    mid = client.get(f"{ws}/mailbox/messages").json()[0]["id"]
    assert (
        client.post(
            f"{ws}/mailbox/messages/{mid}/link", json={"deal_id": s["d_exp"]["id"]}
        ).status_code
        == 200
    )
    act = db_session.scalars(select(Activity).where(Activity.external_ref == "o1")).one()
    assert act.body == "Hello Jo" and act.direction == "inbound"


def test_erasing_a_contact_deletes_their_stored_emails(client, setup, mock, db_session):
    s = setup
    connect_gmail(client, s, mock)
    _mock_gmail_inbox(mock, MESSAGES)
    client.post(f"{s['ws']}/mailbox/sync")
    assert db_session.scalars(select(MailboxMessage)).all().__len__() == 3
    assert client.delete(f"{s['ws']}/contacts/{s['jo']['id']}").status_code == 204
    db_session.expire_all()
    left = {m.provider_message_id for m in db_session.scalars(select(MailboxMessage))}
    assert left == {"m3"}  # only the Globex email, which never involved Jo


def test_workspace_delete_cascades(client, setup, mock, db_session):
    s = setup
    connect_gmail(client, s, mock)
    _mock_gmail_inbox(mock, MESSAGES)
    client.post(f"{s['ws']}/mailbox/sync")
    from app.services import workspaces

    workspaces.delete_workspace(db_session, "mb")
    db_session.expire_all()
    assert db_session.scalars(select(MailboxMessage)).all() == []
    assert db_session.scalars(select(MailboxConnection)).all() == []


def test_nothing_secret_is_logged(client, setup, mock, caplog):
    caplog.set_level(logging.DEBUG)
    connect_gmail(client, setup, mock)
    _mock_gmail_inbox(mock, MESSAGES)
    client.post(f"{setup['ws']}/mailbox/sync")
    text = caplog.text
    assert not any(v in text for v in SECRET_VALUES)
    assert "jo@acme.example" not in text.lower() and "Expansion pricing" not in text
