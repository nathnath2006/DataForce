"""Mailbox providers and matching: parsing, scoring and URL guards. No network."""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from app.config import Settings
from app.connectors import oauth
from app.connectors.mailbox import base, google, microsoft
from app.services import mailbox as svc

NOW = datetime.now(UTC)


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, environment="test")


def test_html_to_text_drops_scripts_and_tags():
    html = (
        "<html><head><style>p{}</style></head><body><p>Hi &amp; bye</p><script>x()</script>"
        "<div>Line<br>two</div></body></html>"
    )
    text = base.html_to_text(html)
    assert "x()" not in text and "p{}" not in text and "<" not in text
    assert "Hi & bye" in text and "Line\ntwo" in text


def test_html_to_text_is_linear_on_unterminated_tags():
    import time

    for hostile in ("<script " * 25_000, "<" * 200_000, "<a " * 200_000):
        t0 = time.monotonic()
        base.html_to_text(hostile)
        assert time.monotonic() - t0 < 2  # the old regexes took 11-15 s on these


def test_address_parsing_lowercases_and_rejects_junk():
    got = base.parse_address_list('"Jo D" <Jo@Acme.example>, bad, x@y, a@b.co, jo@acme.example')
    assert got == ["jo@acme.example", "x@y", "a@b.co"]
    assert "bad" not in got


def test_cap_body():
    assert len(base.cap_body("a" * 50_000)) == 10_000


def test_authorize_urls(settings):
    ch = "CHALLENGE"
    g = google.authorize_url(
        settings,
        client_id="cid",
        redirect="http://127.0.0.1:8800/api/mailbox/callback",
        state="s",
        challenge=ch,
    )
    q = parse_qs(urlsplit(g).query)
    assert q["code_challenge_method"] == ["S256"] and q["code_challenge"] == [ch]
    assert q["scope"] == ["openid email https://www.googleapis.com/auth/gmail.readonly"]
    assert q["access_type"] == ["offline"]
    m = microsoft.authorize_url(
        settings,
        client_id="cid",
        redirect=microsoft.redirect_uri(settings),
        state="s",
        challenge=ch,
    )
    q = parse_qs(urlsplit(m).query)
    assert q["scope"] == ["offline_access Mail.Read User.Read"]
    assert q["redirect_uri"] == ["http://localhost:8800/api/mailbox/callback"]
    assert google.redirect_uri(settings) == "http://127.0.0.1:8800/api/mailbox/callback"


def test_gmail_metadata_parse():
    raw = {
        "id": "m1",
        "threadId": "t1",
        "internalDate": str(int(NOW.timestamp() * 1000)),
        "snippet": "Hello &amp; welcome " + "x" * 400,
        "payload": {
            "headers": [
                {"name": "From", "value": "Jo <jo@acme.example>"},
                {"name": "To", "value": "me@gmail.com, b@acme.example"},
                {"name": "Subject", "value": "Re: Expansion"},
            ]
        },
    }
    meta = google._meta(raw)
    assert meta.sender == "jo@acme.example" and meta.to == ["me@gmail.com", "b@acme.example"]
    assert len(meta.snippet) == 200 and meta.snippet.startswith("Hello & welcome")
    assert google._meta({**raw, "payload": {"headers": []}}) is None


def test_gmail_body_prefers_plain_and_converts_html():
    def part(mime, text):
        data = base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")
        return {"mimeType": mime, "body": {"data": data}}

    plain, markup = [], []
    google._walk(
        {
            "mimeType": "multipart/alternative",
            "parts": [part("text/plain", "plain!"), part("text/html", "<b>h</b>")],
        },
        plain,
        markup,
    )
    assert plain == ["plain!"] and markup == ["<b>h</b>"]


async def test_microsoft_next_link_only_on_graph_origin():
    pages = {
        "first": {"value": [], "@odata.nextLink": "https://evil.example/steal?x=1"},
    }
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as mock:
        mock.get(url__startswith=f"{microsoft.GRAPH}/me/messages").mock(
            return_value=httpx.Response(200, json=pages["first"])
        )
        async with oauth.new_client() as client:
            got = [p async for p in microsoft.list_messages(client, "tok", since=NOW, limit=10)]
        assert got == [[]]
        assert all(c.request.url.host == "graph.microsoft.com" for c in mock.calls)


async def test_401_is_unauthorized():
    with respx.mock(assert_all_mocked=True) as mock:
        mock.get(f"{microsoft.GRAPH}/me").mock(return_value=httpx.Response(401, json={}))
        async with oauth.new_client() as client:
            with pytest.raises(base.Unauthorized):
                await microsoft.account_email(client, "tok")


# --- matching and scoring -----------------------------------------------------------------------


def _index():
    acc, other = uuid.uuid4(), uuid.uuid4()
    d1, d2 = uuid.uuid4(), uuid.uuid4()
    idx = svc.MatchIndex(own_email="me@corp.example")
    idx.contact_by_email["jo@acme.example"] = (uuid.uuid4(), acc)
    idx.account_by_domain["acme.example"] = acc
    idx.account_name[acc] = "Acme"
    idx.account_tokens[acc] = svc.tokens_of("Acme")
    idx.deals_by_account[acc] = [
        svc._DealInfo(d1, acc, svc.tokens_of("Expansion 2026"), NOW.date()),
        svc._DealInfo(d2, acc, svc.tokens_of("Renewal"), NOW.date()),
    ]
    idx.account_name[other] = "Other"
    return idx, acc, d1, d2


def _meta(sender, subject, to=(), days=1):
    return base.MessageMeta(
        id="x",
        thread_id=None,
        sender=sender,
        to=list(to),
        subject=subject,
        sent_at=NOW - timedelta(days=days),
    )


def test_unrelated_and_webmail_are_not_candidates():
    idx, *_ = _index()
    assert svc.candidate_accounts(idx, _meta("friend@gmail.com", "Dinner")) == {}
    idx.account_by_domain["gmail.com"] = uuid.uuid4()  # a free webmail domain is never matched
    assert svc.candidate_accounts(idx, _meta("friend@gmail.com", "Dinner")) == {}
    # the mailbox owner's own address never makes a candidate
    assert svc.candidate_accounts(idx, _meta("me@corp.example", "x", ["friend@gmail.com"])) == {}


def test_scoring_is_deterministic_and_explained():
    idx, acc, d1, d2 = _index()
    meta = _meta("jo@acme.example", "Re: Expansion 2026 pricing")
    found = svc.candidate_accounts(idx, meta)
    a = svc.score_message(idx, meta, found, now=NOW, lookback_days=30, threshold=40)
    b = svc.score_message(idx, meta, found, now=NOW, lookback_days=30, threshold=40)
    assert a == b and a.deal_id == d1
    assert "From: a contact of Acme" in a.reasons
    assert any(r.startswith("Subject mentions") and "'expansion'" in r for r in a.reasons)
    assert a.score >= 70


def test_below_threshold_stays_unmatched():
    idx, *_ = _index()
    meta = _meta("someone@acme.example", "Hello")  # domain only: 25 + recency
    found = svc.candidate_accounts(idx, meta)
    got = svc.score_message(idx, meta, found, now=NOW, lookback_days=30, threshold=40)
    assert got.deal_id is None
