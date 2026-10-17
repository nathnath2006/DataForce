"""Enrichment and channels over HTTP: demo = fake only, paid guard, sealed storage, deletion."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.db.models import ContactChannel
from app.enrichment import tamtam_mcp
from app.services import workspaces
from tests.api.conftest import TEST_SECRET_KEY
from tests.connectors import conftest as shared
from tests.connectors.conftest import make_contact, seed_credential
from tests.connectors.stubs import ACCESS_1, ACCESS_2, SECRETS
from tests.enrichment.helpers import FakeSession, text_result, tool

# Fixtures shared with tests/connectors (re-exposed so pytest collects them here).
contact, demo_ws, stub, ws = shared.contact, shared.demo_ws, shared.stub, shared.ws

EMAIL = "jane.doe@acme-real.example"
MOBILE = "+33 6 12 34 56 78"


class McpSpy:
    """Replaces the MCP transport: records tokens and calls, serves one canned tool."""

    def __init__(self, monkeypatch, tools=None, result=None):
        self.tokens: list[str] = []
        self.session = FakeSession(
            tools if tools is not None else [tool("enrich_contact", "find")],
            {
                "enrich_contact": result
                or text_result({"email": EMAIL, "mobile": MOBILE, "credits_used": 1})
            },
        )
        spy = self

        @asynccontextmanager
        async def opener(url, token):
            spy.tokens.append(token)
            yield spy.session

        monkeypatch.setattr(tamtam_mcp, "open_http_session", opener)

    @property
    def opened(self) -> int:
        return len(self.tokens)


def url(ws_slug, contact_id, tail="enrich"):
    return f"/api/w/{ws_slug}/contacts/{contact_id}/{tail}"


def body(**kw):
    return {"want": ["email"], "confirm_paid": True, "max_credits": 1, **kw}


# --- demo workspace: fake provider, zero traffic ------------------------------------------------


def test_demo_workspace_always_uses_the_fake_provider_with_zero_traffic(
    client,
    db_session,
    demo_ws,
    stub,
    monkeypatch,
    api_settings,
):
    spy = McpSpy(monkeypatch)
    seed_credential(db_session, demo_ws, api_settings)  # even a connected demo stays fake
    person = make_contact(db_session, demo_ws)
    response = client.post(
        url(demo_ws.slug, person.id), json={"want": ["email", "mobile"], "max_credits": 11}
    )
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["mode"] == "fake" and out["anomalous"] is False
    assert {c["kind"] for c in out["channels"]} == {"email", "mobile"}
    assert all(c["provider"] == "fake" for c in out["channels"])
    email = next(c["value"] for c in out["channels"] if c["kind"] == "email")
    assert email.endswith(".example")  # reserved TLD: never a real mailbox
    assert stub.traffic == 0 and spy.opened == 0


def test_demo_workspace_needs_no_connection(client, db_session, demo_ws, stub, monkeypatch):
    spy = McpSpy(monkeypatch)
    person = make_contact(db_session, demo_ws)
    response = client.post(url(demo_ws.slug, person.id), json={"want": ["email"], "max_credits": 0})
    assert response.status_code == 200 and response.json()["mode"] == "fake"
    assert stub.traffic == 0 and spy.opened == 0


# --- real workspace: connection and the paid guard -----------------------------------------------


def test_not_connected_is_409(client, ws, contact, stub, monkeypatch):
    spy = McpSpy(monkeypatch)
    response = client.post(url(ws.slug, contact.id), json=body())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "connector_not_configured"
    assert spy.opened == 0 and stub.traffic == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"want": ["email"], "max_credits": 1},  # confirm_paid missing
        {"want": ["email"], "confirm_paid": False, "max_credits": 1},
        {"want": ["email"], "confirm_paid": True, "max_credits": 0.5},  # price rose
        {"want": ["mobile"], "confirm_paid": True, "max_credits": 1},
        {"want": ["email", "mobile"], "confirm_paid": True, "max_credits": 10},  # 11 > 10
        {"want": ["email", "mobile"], "confirm_paid": True, "max_credits": 11},  # 11 > ceiling 10
    ],
)
def test_paid_refusals_happen_before_any_traffic(
    client,
    db_session,
    ws,
    contact,
    stub,
    monkeypatch,
    api_settings,
    payload,
):
    spy = McpSpy(monkeypatch)
    seed_credential(db_session, ws, api_settings)
    response = client.post(url(ws.slug, contact.id), json=payload)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "paid_lookup_refused"
    assert spy.opened == 0 and stub.traffic == 0
    assert db_session.scalars(select(ContactChannel)).all() == []


def test_confirm_paid_must_be_boolean_like(
    client,
    db_session,
    ws,
    contact,
    stub,
    monkeypatch,
    api_settings,
):
    spy = McpSpy(monkeypatch)
    seed_credential(db_session, ws, api_settings)
    response = client.post(url(ws.slug, contact.id), json=body(confirm_paid="maybe"))
    assert response.status_code == 422 and spy.opened == 0


def test_a_paid_lookup_stores_sealed_channels_and_returns_them_unsealed(
    client,
    db_session,
    ws,
    contact,
    stub,
    monkeypatch,
    api_settings,
    caplog,
):
    caplog.set_level(logging.DEBUG)
    spy = McpSpy(monkeypatch)
    seed_credential(db_session, ws, api_settings)
    response = client.post(url(ws.slug, contact.id), json=body(want=["email"], max_credits=1))
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["mode"] == "tamtam" and out["credits_used"] == 1.0 and out["anomalous"] is False
    assert [(c["kind"], c["value"], c["provider"]) for c in out["channels"]] == [
        ("email", EMAIL, "tamtam_mcp")
    ]
    assert out["channels"][0]["raw_tool"] == "enrich_contact"
    assert spy.tokens == [ACCESS_1]  # the stored OAuth token, not settings.tamtam_mcp_token
    assert [c[0] for c in spy.session.calls] == ["enrich_contact"]
    raw = db_session.execute(text("select value_enc from contact_channel")).scalar_one()
    assert EMAIL not in raw
    listed = client.get(url(ws.slug, contact.id, "channels")).json()
    assert [(c["kind"], c["value"]) for c in listed] == [("email", EMAIL)]
    # no value, token or key in the app's logs (the test client's own httpx2 lines are the browser)
    logged = "\n".join(r.getMessage() for r in caplog.records if r.name != "httpx2")
    for needle in (EMAIL, MOBILE, ACCESS_1, TEST_SECRET_KEY):
        assert needle not in logged


def test_both_fields_split_the_credits_over_the_rows(
    client, db_session, ws, contact, stub, monkeypatch, api_settings
):
    from app.config import Settings

    McpSpy(monkeypatch, result=text_result({"email": EMAIL, "mobile": MOBILE, "credits_used": 11}))
    seed_credential(db_session, ws, api_settings)
    # raise the ceiling for this test only
    from app.api.deps import get_app_settings

    big = Settings(
        _env_file=None,
        environment="test",
        dataforce_secret_key=api_settings.dataforce_secret_key,
        enrichment_max_credits_per_call=20,
    )
    client.app.dependency_overrides[get_app_settings] = lambda: big
    response = client.post(
        url(ws.slug, contact.id), json=body(want=["email", "mobile"], max_credits=11)
    )
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["credits_used"] == 11.0
    by_kind = {c["kind"]: c for c in out["channels"]}
    assert by_kind["email"]["credits_used"] == pytest.approx(1.0)
    assert by_kind["mobile"]["credits_used"] == pytest.approx(10.0)


def test_nothing_found_stores_nothing(
    client, db_session, ws, contact, stub, monkeypatch, api_settings
):
    McpSpy(monkeypatch, result=text_result({"credits_used": 0}))
    seed_credential(db_session, ws, api_settings)
    out = client.post(url(ws.slug, contact.id), json=body()).json()
    assert out["channels"] == [] and out["credits_used"] == 0
    assert db_session.scalars(select(ContactChannel)).all() == []


def test_an_anomalous_credit_figure_is_flagged(
    client, db_session, ws, contact, stub, monkeypatch, api_settings
):
    McpSpy(monkeypatch, result=text_result({"email": EMAIL, "credits_used": 500}))
    seed_credential(db_session, ws, api_settings)
    out = client.post(url(ws.slug, contact.id), json=body()).json()
    assert out["anomalous"] is True and out["notes"]
    assert EMAIL not in " ".join(out["notes"])


def test_the_token_is_refreshed_before_the_lookup(
    client, db_session, ws, contact, stub, monkeypatch, api_settings
):
    spy = McpSpy(monkeypatch)
    seed_credential(
        db_session, ws, api_settings, token_expires_at=datetime.now(UTC) + timedelta(seconds=10)
    )
    assert client.post(url(ws.slug, contact.id), json=body()).status_code == 200
    assert spy.tokens == [ACCESS_2]


def test_an_expired_connection_is_409_and_sends_nothing_to_tamtam(
    client, db_session, ws, contact, stub, monkeypatch, api_settings
):
    spy = McpSpy(monkeypatch)
    seed_credential(db_session, ws, api_settings, status="expired")
    response = client.post(url(ws.slug, contact.id), json=body())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "connector_not_configured"
    assert spy.opened == 0 and stub.traffic == 0


def test_a_server_without_an_allow_listed_tool_is_a_502_and_calls_nothing(
    client, db_session, ws, contact, stub, monkeypatch, api_settings
):
    spy = McpSpy(monkeypatch, tools=[tool("send_email_to_contact", "mails people")])
    seed_credential(db_session, ws, api_settings)
    response = client.post(url(ws.slug, contact.id), json=body())
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "connector_error"
    assert spy.session.calls == []
    assert ACCESS_1 not in response.text


def test_enrich_unknown_contact_and_other_workspace_are_404(
    client, db_session, ws, contact, stub, monkeypatch, api_settings
):
    import uuid

    McpSpy(monkeypatch)
    seed_credential(db_session, ws, api_settings)
    assert client.post(url(ws.slug, uuid.uuid4()), json=body()).status_code == 404
    other = workspaces.create_workspace(db_session, "other-real", "Other")
    db_session.commit()
    seed_credential(db_session, other, api_settings)
    assert client.post(url("other-real", contact.id), json=body()).status_code == 404


def test_extra_fields_and_bad_amounts_are_rejected(client, ws, contact):
    assert client.post(url(ws.slug, contact.id), json={**body(), "x": 1}).status_code == 422
    assert client.post(url(ws.slug, contact.id), json=body(want=[])).status_code == 422
    assert client.post(url(ws.slug, contact.id), json=body(max_credits=-1)).status_code == 422


# --- channels ------------------------------------------------------------------------------------


def stored(client, db_session, ws, contact, monkeypatch, api_settings):
    McpSpy(monkeypatch)
    seed_credential(db_session, ws, api_settings)
    out = client.post(url(ws.slug, contact.id), json=body()).json()
    return out["channels"][0]["id"]


def test_channel_delete_is_a_one_click_hard_delete(
    client, db_session, ws, contact, stub, monkeypatch, api_settings
):
    channel_id = stored(client, db_session, ws, contact, monkeypatch, api_settings)
    response = client.delete(url(ws.slug, contact.id, f"channels/{channel_id}"))
    assert response.status_code == 204
    assert client.get(url(ws.slug, contact.id, "channels")).json() == []
    assert db_session.execute(text("select count(*) from contact_channel")).scalar_one() == 0
    assert client.delete(url(ws.slug, contact.id, f"channels/{channel_id}")).status_code == 404


def test_channels_are_scoped_to_their_workspace_and_contact(
    client, db_session, ws, contact, stub, monkeypatch, api_settings
):
    channel_id = stored(client, db_session, ws, contact, monkeypatch, api_settings)
    other = workspaces.create_workspace(db_session, "other-real", "Other")
    stranger = make_contact(db_session, other, "John Roe")
    sibling = make_contact(db_session, ws, "Sam Lee")
    path = f"channels/{channel_id}"
    assert client.delete(url("other-real", stranger.id, path)).status_code == 404
    assert client.delete(url(ws.slug, sibling.id, path)).status_code == 404
    assert client.get(url("other-real", contact.id, "channels")).status_code == 404
    assert client.get(url(ws.slug, sibling.id, "channels")).json() == []
    assert len(client.get(url(ws.slug, contact.id, "channels")).json()) == 1


def test_erasing_the_contact_removes_its_channels(
    client, db_session, ws, contact, stub, monkeypatch, api_settings
):
    stored(client, db_session, ws, contact, monkeypatch, api_settings)
    sibling = make_contact(db_session, ws, "Sam Lee")
    assert client.delete(f"/api/w/{ws.slug}/contacts/{contact.id}").status_code == 204
    assert db_session.execute(text("select count(*) from contact_channel")).scalar_one() == 0
    assert client.get(url(ws.slug, contact.id, "channels")).status_code == 404
    assert client.get(url(ws.slug, sibling.id, "channels")).json() == []


def test_no_secret_in_any_enrichment_body(
    client, db_session, ws, contact, stub, monkeypatch, api_settings
):
    McpSpy(monkeypatch)
    seed_credential(db_session, ws, api_settings)
    texts = [
        client.post(url(ws.slug, contact.id), json=body()).text,
        client.get(url(ws.slug, contact.id, "channels")).text,
        client.get(f"/api/w/{ws.slug}/connectors/tamtam").text,
    ]
    for text_ in texts:
        assert not [s for s in (*SECRETS, TEST_SECRET_KEY) if s in text_]
