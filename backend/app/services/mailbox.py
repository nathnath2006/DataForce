"""Mailbox (Gmail, Outlook): connect, sync metadata, suggest deals, link on demand.

Privacy rules (the PO's standing rule: third-party personal data kept to a minimum):
* read-only scopes; metadata first; the last N days, at most M messages per sync;
* only candidate emails are stored (a participant is a known contact email, or the non-webmail
  domain of an account); the matching runs in memory; unrelated emails are never written;
* a body is fetched only when a person links an email, converted to text, capped, and stored
  only as the activity body;
* tokens, the client secret and the account address are sealed (connectors/crypto.py); nothing
  here logs an address, a subject, a body or a token; errors are fixed strings.
DB access is sync and short (thread pool); network access is async; no transaction is open
across a network call.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.schemas_mailbox import (
    MailboxConnectionOut,
    MailboxCounts,
    MailboxMessageOut,
    MailboxStatusOut,
    MailboxSyncResultOut,
)
from app.auth import visibility
from app.auth.viewer import Viewer
from app.config import Settings
from app.connectors import oauth, store
from app.connectors.crypto import key_configured, seal, unseal
from app.connectors.mailbox import PROVIDERS, base
from app.db.models import (
    Account,
    Activity,
    Contact,
    ContactChannel,
    Deal,
    MailboxConnection,
    MailboxMessage,
    OAuthPending,
    Workspace,
)
from app.domain.enums import OPEN_STAGES, RunStatus
from app.enrichment.errors import EnrichmentConfigError, EnrichmentError
from app.flows.blocks.domain import extract_domain, is_free
from app.services import activities, limits, runs
from app.services._common import require, require_deal
from app.services.errors import InvalidInputError, NotFoundError

log = logging.getLogger(__name__)

RUN_KIND = "mailbox_sync"
MAX_CODE_CHARS = 2048
MAX_STATE_CHARS = 256
LIST_CAP = 100
EXPIRY_SKEW = timedelta(seconds=60)

# Scoring weights (a transparent, deterministic rule; the sum is 100).
W_CONTACT, W_DOMAIN, W_SUBJECT, W_RECENT = 45, 25, 25, 5

# Fixed reasons of the callback redirect.
DENIED, EXPIRED, INVALID_STATE = "denied", "expired", "invalid_state"
EXCHANGE_FAILED, SERVER_ERROR = "exchange_failed", "server_error"

_STOPWORDS = frozenset(
    "re fw fwd the and for with from your our you are was has have this that will not but new "
    "de la le les des du un une et pour avec sur dans par que qui est nous vous votre notre "
    "meeting call email mail follow update".split()
)
_WORD = re.compile(r"[^\W_]{3,}", re.UNICODE)


class NeedsReconnect(EnrichmentConfigError):
    """The provider no longer accepts the stored grant (or none is stored): reconnect."""


def tokens_of(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.casefold()) if w not in _STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


# --- connection rows, client credentials, status ------------------------------------------------


def _provider(name: str):
    if name not in PROVIDERS:
        raise NotFoundError("unknown mailbox provider")
    return PROVIDERS[name]


def get_connection(db: Session, ws_id: uuid.UUID, provider: str) -> MailboxConnection | None:
    return db.scalar(
        select(MailboxConnection).where(
            MailboxConnection.workspace_id == ws_id, MailboxConnection.provider == provider
        )
    )


def _ensure_connection(db: Session, ws_id: uuid.UUID, provider: str) -> MailboxConnection:
    conn = get_connection(db, ws_id, provider)
    if conn is None:
        conn = MailboxConnection(workspace_id=ws_id, provider=provider, status="configured")
        db.add(conn)
        db.flush()
    return conn


def _env_client(settings: Settings, provider: str) -> tuple[str | None, str | None]:
    if provider == "gmail":
        cid, secret = settings.mailbox_google_client_id, settings.mailbox_google_client_secret
    else:
        cid = settings.mailbox_microsoft_client_id
        secret = settings.mailbox_microsoft_client_secret
    return cid or None, (secret.get_secret_value() if secret else None) or None


def client_source(settings: Settings, conn: MailboxConnection | None, provider: str) -> str | None:
    if conn is not None and conn.client_id:
        return "settings"
    return "env" if _env_client(settings, provider)[0] else None


def resolve_client(
    settings: Settings, conn: MailboxConnection | None, provider: str
) -> tuple[str, str | None]:
    """(client id, client secret): the one entered in Settings wins over the environment."""
    if conn is not None and conn.client_id:
        secret = unseal(conn.client_secret_enc, settings) if conn.client_secret_enc else None
        return conn.client_id, secret
    cid, secret = _env_client(settings, provider)
    if not cid:
        raise EnrichmentConfigError(
            f"no {PROVIDERS[provider].LABEL} OAuth client is set: enter its client id in Settings"
        )
    return cid, secret


def save_client(
    db: Session,
    settings: Settings,
    ws_id: uuid.UUID,
    provider: str,
    client_id: str,
    client_secret: str | None,
) -> None:
    _provider(provider)
    secret_enc = (
        seal(client_secret.strip(), settings) if client_secret and client_secret.strip() else None
    )
    conn = _ensure_connection(db, ws_id, provider)
    conn.client_id = client_id.strip()
    conn.client_secret_enc = secret_enc
    db.flush()


def _counts(db: Session, conn_id: uuid.UUID) -> MailboxCounts:
    rows = db.execute(
        select(
            MailboxMessage.state,
            MailboxMessage.suggested_deal_id.is_(None),
            func.count(),
        )
        .where(MailboxMessage.connection_id == conn_id)
        .group_by(MailboxMessage.state, MailboxMessage.suggested_deal_id.is_(None))
    )
    out = MailboxCounts()
    for state, no_deal, n in rows:
        if state == "suggested":
            if no_deal:
                out.unmatched += n
            else:
                out.suggested += n
        else:
            setattr(out, state, getattr(out, state) + n)
    return out


def status_view(db: Session, settings: Settings, ws: Workspace) -> MailboxStatusOut:
    settings = limits.effective_settings(db, settings, ws.id)
    views: list[MailboxConnectionOut] = []
    for name, mod in PROVIDERS.items():
        conn = get_connection(db, ws.id, name)
        source = client_source(settings, conn, name)
        status = conn.status if conn is not None else "not_configured"
        if status == "configured" and source is None:
            status = "not_configured"
        email = None
        if conn is not None and conn.account_email_enc and key_configured(settings):
            try:
                email = unseal(conn.account_email_enc, settings)
            except EnrichmentError:
                email = None
        views.append(
            MailboxConnectionOut(
                provider=name,  # type: ignore[arg-type]
                label=mod.LABEL,
                status=status,  # type: ignore[arg-type]
                client_source=source,  # type: ignore[arg-type]
                secret_key_configured=key_configured(settings),
                account_email=email,
                redirect_uri=mod.redirect_uri(settings),
                last_sync_at=conn.last_sync_at if conn else None,
                last_error=conn.last_error if conn else None,
                counts=_counts(db, conn.id) if conn else MailboxCounts(),
            )
        )
    return MailboxStatusOut(
        connections=views,
        lookback_days=settings.mailbox_lookback_days,
        max_messages=settings.mailbox_max_messages,
    )


# --- OAuth: connect and callback ----------------------------------------------------------------


async def start_connect(
    db: Session, settings: Settings, ws_id: uuid.UUID, provider: str, host: str | None
) -> tuple[str, str]:
    """(authorize_url, browser_secret); the secret goes into the `df_oauth_mb` cookie."""
    mod = _provider(provider)
    seal("probe", settings)  # no key -> EnrichmentConfigError with the hint

    def prepare() -> tuple[str, str | None]:
        conn = _ensure_connection(db, ws_id, provider)
        creds = resolve_client(settings, conn, provider)
        db.commit()
        return creds

    client_id, client_secret = await run_in_threadpool(prepare)
    redirect = mod.redirect_uri(settings, host)
    state = oauth.new_state()
    verifier, challenge = oauth.new_pkce()
    browser_secret = secrets.token_urlsafe(32)
    url = mod.authorize_url(
        settings, client_id=client_id, redirect=redirect, state=state, challenge=challenge
    )

    def save() -> None:
        store.purge_expired_pending(db)
        db.execute(
            delete(OAuthPending).where(
                OAuthPending.workspace_id == ws_id, OAuthPending.provider == provider
            )
        )
        db.add(
            OAuthPending(
                workspace_id=ws_id,
                provider=provider,
                state_hash=store.sha256_hex(state),
                browser_hash=store.sha256_hex(browser_secret),
                code_verifier_enc=seal(verifier, settings),
                issuer=mod.NAME,
                resource="mailbox",
                client_id=client_id,
                client_secret_enc=seal(client_secret, settings) if client_secret else None,
                redirect_uri=redirect,
                expires_at=datetime.now(UTC) + store.PENDING_TTL,
            )
        )
        db.commit()

    await run_in_threadpool(save)
    return url, browser_secret


@dataclass(frozen=True)
class CallbackResult:
    reason: str | None
    slug: str | None


async def finish_callback(
    db: Session,
    settings: Settings,
    *,
    state: str | None,
    code: str | None,
    error: str | None,
    browser_cookie: str | None,
) -> CallbackResult:
    if not state or len(state) > MAX_STATE_CHARS:
        return CallbackResult(INVALID_STATE, None)

    def take() -> tuple[Any, str | None]:
        pending = store.take_pending(db, state)
        slug = None
        if pending is not None:
            slug = db.scalar(select(Workspace.slug).where(Workspace.id == pending.workspace_id))
        db.commit()  # the flow is spent whatever happens next
        return pending, slug

    pending, slug = await run_in_threadpool(take)
    if pending is None or pending.provider not in PROVIDERS or pending.resource != "mailbox":
        return CallbackResult(INVALID_STATE, None)
    if pending.expires_at < datetime.now(UTC):
        return CallbackResult(EXPIRED, slug)
    # The cookie binds the flow to the browser that started it. Outlook's redirect is on
    # `localhost` (the only loopback host Entra accepts), a different cookie origin than
    # 127.0.0.1: for it a missing cookie is tolerated (the single-use state and PKCE remain),
    # but a cookie that is present must match.
    if browser_cookie:
        if not hmac.compare_digest(store.sha256_hex(browser_cookie), pending.browser_hash):
            return CallbackResult(INVALID_STATE, slug)
    elif pending.provider != "outlook":
        return CallbackResult(INVALID_STATE, slug)
    if error:
        return CallbackResult(DENIED if error == "access_denied" else SERVER_ERROR, slug)
    if not code or len(code) > MAX_CODE_CHARS:
        return CallbackResult(EXCHANGE_FAILED, slug)
    mod = PROVIDERS[pending.provider]
    try:
        verifier = unseal(pending.code_verifier_enc, settings)
        secret = unseal(pending.client_secret_enc, settings) if pending.client_secret_enc else None
        async with oauth.new_client() as client:
            tokens = await mod.exchange_code(
                client,
                settings,
                client_id=pending.client_id,
                client_secret=secret,
                code=code,
                verifier=verifier,
                redirect=pending.redirect_uri,
            )
            email = await mod.account_email(client, tokens.access_token)

        def save() -> None:
            _lock(db, pending.workspace_id, pending.provider)
            conn = _ensure_connection(db, pending.workspace_id, pending.provider)
            conn.status = "connected"
            conn.account_email_enc = seal(email, settings)
            conn.access_token_enc = seal(tokens.access_token, settings)
            conn.refresh_token_enc = (
                seal(tokens.refresh_token, settings) if tokens.refresh_token else None
            )
            conn.token_expires_at = tokens.expires_at
            conn.last_error = None
            db.commit()

        await run_in_threadpool(save)
    except EnrichmentConfigError:
        return CallbackResult(SERVER_ERROR, slug)
    except EnrichmentError:
        return CallbackResult(EXCHANGE_FAILED, slug)
    except Exception as exc:  # noqa: BLE001 - the browser gets a fixed code, the log a class name
        log.error("mailbox callback failed (%s)", type(exc).__name__)
        db.rollback()
        return CallbackResult(SERVER_ERROR, slug)
    return CallbackResult(None, slug)


_LOCK_NS = 7_461_220_011


def _lock(db: Session, ws_id: uuid.UUID, provider: str) -> None:
    db.execute(
        select(
            func.pg_advisory_xact_lock(func.hashtextextended(f"{ws_id}:mb:{provider}", _LOCK_NS))
        )
    )


# --- tokens -------------------------------------------------------------------------------------


@dataclass
class _Grant:
    conn_id: uuid.UUID
    provider: str
    access: str
    refresh: str | None
    expires_at: datetime | None
    client_id: str
    client_secret: str | None
    own_email: str | None


def _load_grant(db: Session, settings: Settings, ws_id: uuid.UUID, provider: str) -> _Grant:
    conn = get_connection(db, ws_id, provider)
    if conn is None or conn.status != "connected" or not conn.access_token_enc:
        db.rollback()
        raise NeedsReconnect(f"{PROVIDERS[provider].LABEL} is not connected: reconnect it")
    try:
        client_id, client_secret = resolve_client(settings, conn, provider)
        grant = _Grant(
            conn.id,
            provider,
            unseal(conn.access_token_enc, settings),
            unseal(conn.refresh_token_enc, settings) if conn.refresh_token_enc else None,
            conn.token_expires_at,
            client_id,
            client_secret,
            unseal(conn.account_email_enc, settings) if conn.account_email_enc else None,
        )
    except EnrichmentError:
        conn.status = "needs_reconnect"
        conn.last_error = "the stored credentials cannot be read; reconnect"
        db.commit()
        raise NeedsReconnect(conn.last_error) from None
    db.rollback()
    return grant


def mark_needs_reconnect(db: Session, ws_id: uuid.UUID, provider: str, message: str) -> None:
    conn = get_connection(db, ws_id, provider)
    if conn is not None:
        conn.status = "needs_reconnect"
        conn.access_token_enc = None
        conn.refresh_token_enc = None
        conn.token_expires_at = None
        conn.last_error = message
        db.commit()


async def access_grant(db: Session, settings: Settings, ws_id: uuid.UUID, provider: str) -> _Grant:
    """The connection's grant with a fresh access token. A refresh token that the provider
    rotated is saved before it is used; `invalid_grant` marks the connection for reconnection."""
    grant = await run_in_threadpool(_load_grant, db, settings, ws_id, provider)
    if not oauth.needs_refresh(grant.expires_at):
        return grant
    if not grant.refresh:
        await run_in_threadpool(
            mark_needs_reconnect, db, ws_id, provider, "the session expired; reconnect"
        )
        raise NeedsReconnect("the session expired; reconnect")
    mod = PROVIDERS[provider]
    try:
        async with oauth.new_client() as client:
            tokens = await mod.refresh(
                client,
                settings,
                client_id=grant.client_id,
                client_secret=grant.client_secret,
                refresh_token=grant.refresh,
            )
    except oauth.InvalidGrant:
        msg = "the provider revoked or expired the access; reconnect"
        await run_in_threadpool(mark_needs_reconnect, db, ws_id, provider, msg)
        raise NeedsReconnect(msg) from None

    def save() -> None:
        _lock(db, ws_id, provider)
        conn = get_connection(db, ws_id, provider)
        if conn is not None and conn.status == "connected":
            conn.access_token_enc = seal(tokens.access_token, settings)
            conn.refresh_token_enc = seal(tokens.refresh_token or grant.refresh or "", settings)
            conn.token_expires_at = tokens.expires_at
        db.commit()

    await run_in_threadpool(save)
    grant.access, grant.refresh, grant.expires_at = (
        tokens.access_token,
        tokens.refresh_token or grant.refresh,  # Google does not rotate: keep the old one
        tokens.expires_at,
    )
    return grant


# --- in-memory matching and scoring -------------------------------------------------------------


@dataclass
class _DealInfo:
    id: uuid.UUID
    account_id: uuid.UUID
    name_tokens: set[str]
    created_on: Any


@dataclass
class MatchIndex:
    """Everything the matching needs, built once per sync and held only in memory."""

    own_email: str | None
    contact_by_email: dict[str, tuple[uuid.UUID, uuid.UUID]] = field(default_factory=dict)
    account_by_domain: dict[str, uuid.UUID] = field(default_factory=dict)
    account_name: dict[uuid.UUID, str] = field(default_factory=dict)
    account_tokens: dict[uuid.UUID, set[str]] = field(default_factory=dict)
    deals_by_account: dict[uuid.UUID, list[_DealInfo]] = field(default_factory=dict)


def build_index(
    db: Session, settings: Settings, ws_id: uuid.UUID, own_email: str | None
) -> MatchIndex:
    idx = MatchIndex(own_email=own_email.lower() if own_email else None)
    for acc_id, name, domain in db.execute(
        select(Account.id, Account.name, Account.domain).where(Account.workspace_id == ws_id)
    ):
        idx.account_name[acc_id] = name
        idx.account_tokens[acc_id] = tokens_of(name)
        d = extract_domain(domain) if domain else None
        if d and not is_free(d):
            idx.account_by_domain.setdefault(d, acc_id)
    rows = db.execute(
        select(ContactChannel.value_enc, ContactChannel.contact_id, Contact.account_id)
        .join(Contact, Contact.id == ContactChannel.contact_id)
        .where(ContactChannel.workspace_id == ws_id, ContactChannel.kind == "email")
    )
    for value_enc, contact_id, account_id in rows:
        try:
            addr = base.clean_addr(unseal(value_enc, settings))
        except EnrichmentError:
            continue
        if addr:
            idx.contact_by_email.setdefault(addr, (contact_id, account_id))
    for deal in db.execute(
        select(Deal.id, Deal.account_id, Deal.name, Deal.created_on).where(
            Deal.workspace_id == ws_id, Deal.stage.in_([s.value for s in OPEN_STAGES])
        )
    ):
        idx.deals_by_account.setdefault(deal.account_id, []).append(
            _DealInfo(deal.id, deal.account_id, tokens_of(deal.name), deal.created_on)
        )
    return idx


@dataclass
class Scored:
    deal_id: uuid.UUID | None
    score: int | None
    reasons: list[str]


def candidate_accounts(idx: MatchIndex, meta: base.MessageMeta) -> dict[uuid.UUID, dict[str, Any]]:
    """{account id: {roles of its contacts, domain matched}} for the message's participants,
    leaving out the mailbox owner. Empty: not a candidate, nothing is stored."""
    found: dict[uuid.UUID, dict[str, Any]] = {}
    roles = (("From", [meta.sender]), ("To", meta.to), ("Cc", meta.cc))
    for role, addrs in roles:
        for addr in addrs:
            if addr == idx.own_email:
                continue
            hit = idx.contact_by_email.get(addr)
            if hit is not None:
                info = found.setdefault(hit[1], {"roles": [], "domain": None})
                if role not in info["roles"]:
                    info["roles"].append(role)
            domain = extract_domain(addr)
            if domain and not is_free(domain) and domain in idx.account_by_domain:
                info = found.setdefault(
                    idx.account_by_domain[domain], {"roles": [], "domain": None}
                )
                info["domain"] = domain
    return found


def score_message(
    idx: MatchIndex,
    meta: base.MessageMeta,
    found: dict[uuid.UUID, dict[str, Any]],
    *,
    now: datetime,
    lookback_days: int,
    threshold: int,
) -> Scored:
    subject_tokens = tokens_of(meta.subject)
    age_days = max(0.0, (now - meta.sent_at).total_seconds() / 86400) if meta.sent_at else 99.0
    recent = round(W_RECENT * max(0.0, 1 - age_days / lookback_days))
    best: tuple[int, Any, _DealInfo, list[str]] | None = None
    for account_id, info in found.items():
        account = idx.account_name.get(account_id, "")
        for deal in idx.deals_by_account.get(account_id, []):
            reasons: list[str] = []
            score = 0
            if info["roles"]:
                score += W_CONTACT
                reasons.append(f"{'/'.join(info['roles'])}: a contact of {account}")
            if info["domain"]:
                score += W_DOMAIN
                reasons.append(f"An address is on {info['domain']} ({account}'s domain)")
            names = deal.name_tokens | idx.account_tokens.get(account_id, set())
            shared = sorted(subject_tokens & names)
            points = round(W_SUBJECT * min(1.0, 2 * jaccard(subject_tokens, names)))
            if shared and points:
                score += points
                reasons.append("Subject mentions " + ", ".join(f"'{w}'" for w in shared[:4]))
            if recent and score:
                score += recent
                reasons.append(f"Recent ({int(age_days)} days ago)")
            key = (score, deal.created_on)
            if best is None or key > (best[0], best[1]):
                best = (score, deal.created_on, deal, reasons)
    if best is not None and best[0] >= threshold:
        return Scored(best[2].id, best[0], best[3])
    names = ", ".join(sorted({idx.account_name.get(a, "") for a in found})[:3])
    return Scored(None, best[0] if best else None, [f"Matches {names}; no open deal fits well"])


def _store_page(
    db: Session,
    settings: Settings,
    ws_id: uuid.UUID,
    conn_id: uuid.UUID,
    idx: MatchIndex,
    page: list[base.MessageMeta],
) -> tuple[int, int, int]:
    """Upsert the candidates of one page. Returns (candidates, new, suggested). Idempotent:
    an existing row is only re-scored while it is still `suggested`."""
    settings = limits.effective_settings(db, settings, ws_id)
    now = datetime.now(UTC)
    ids = [m.id for m in page]
    existing = {
        r.provider_message_id: r
        for r in db.scalars(
            select(MailboxMessage).where(
                MailboxMessage.connection_id == conn_id,
                MailboxMessage.provider_message_id.in_(ids),
            )
        )
    }
    candidates = new = suggested = 0
    for meta in page:
        if meta.sent_at is None:
            continue
        found = candidate_accounts(idx, meta)
        if not found:
            continue  # unrelated: never stored
        candidates += 1
        scored = score_message(
            idx,
            meta,
            found,
            now=now,
            lookback_days=settings.mailbox_lookback_days,
            threshold=settings.mailbox_suggest_threshold,
        )
        row = existing.get(meta.id)
        if row is None:
            db.add(
                MailboxMessage(
                    workspace_id=ws_id,
                    connection_id=conn_id,
                    provider_message_id=meta.id[:300],
                    thread_id=meta.thread_id,
                    from_addr=meta.sender,
                    to_addrs=meta.to,
                    cc_addrs=meta.cc,
                    sent_at=meta.sent_at,
                    subject=(meta.subject or "(no subject)")[:300],
                    snippet=meta.snippet[:200],
                    suggested_deal_id=scored.deal_id,
                    score=scored.score,
                    reasons=scored.reasons,
                    state="suggested",
                )
            )
            new += 1
        elif row.state == "suggested":
            row.suggested_deal_id, row.score, row.reasons = (
                scored.deal_id,
                scored.score,
                scored.reasons,
            )
        if scored.deal_id is not None:
            suggested += 1
    db.commit()
    return candidates, new, suggested


# --- sync ---------------------------------------------------------------------------------------


async def sync(
    db: Session, settings: Settings, ws_id: uuid.UUID, provider: str | None = None
) -> MailboxSyncResultOut:
    settings = limits.effective_settings(db, settings, ws_id)
    names = [provider] if provider else list(PROVIDERS)

    def start() -> tuple[uuid.UUID, list[str]]:
        connected = [
            n
            for n in names
            if (c := get_connection(db, ws_id, n)) is not None and c.status == "connected"
        ]
        run = runs.start_run(db, RUN_KIND, ws_id, {"providers": connected})
        db.commit()
        return run.id, connected

    run_id, connected = await run_in_threadpool(start)
    if provider and not connected:
        await run_in_threadpool(_fail_run, db, ws_id, run_id, "not connected")
        raise NeedsReconnect(f"{PROVIDERS[provider].LABEL} is not connected: reconnect it")
    totals = {"fetched": 0, "candidates": 0, "new": 0, "suggested": 0}
    errors: list[str] = []
    since = datetime.now(UTC) - timedelta(days=settings.mailbox_lookback_days)
    for name in connected:
        mod = PROVIDERS[name]
        try:
            grant = await access_grant(db, settings, ws_id, name)
            idx = await run_in_threadpool(build_index, db, settings, ws_id, grant.own_email)
            await run_in_threadpool(db.rollback)
            remaining = settings.mailbox_max_messages
            async with oauth.new_client() as client:
                async for page in mod.list_messages(
                    client, grant.access, since=since, limit=settings.mailbox_max_messages
                ):
                    page = page[:remaining]
                    remaining -= len(page)
                    c, n, s = await run_in_threadpool(
                        _store_page, db, settings, ws_id, grant.conn_id, idx, page
                    )
                    totals["fetched"] += len(page)
                    totals["candidates"] += c
                    totals["new"] += n
                    totals["suggested"] += s
                    if remaining <= 0:
                        break
            await run_in_threadpool(_record_sync, db, ws_id, name, None)
        except base.Unauthorized:
            msg = "the provider rejected the access; reconnect"
            await run_in_threadpool(mark_needs_reconnect, db, ws_id, name, msg)
            errors.append(f"{mod.LABEL}: {msg}")
        except NeedsReconnect as exc:
            errors.append(f"{mod.LABEL}: {exc}")
        except EnrichmentError as exc:
            await run_in_threadpool(_record_sync, db, ws_id, name, str(exc)[:300])
            errors.append(f"{mod.LABEL}: {exc}")
        except Exception as exc:  # noqa: BLE001
            log.error("mailbox sync failed (%s)", type(exc).__name__)
            db.rollback()
            await run_in_threadpool(_record_sync, db, ws_id, name, "the sync failed")
            errors.append(f"{mod.LABEL}: the sync failed")

    def finish() -> None:
        status = (
            RunStatus.FAILED
            if errors and len(errors) == len(connected)
            else RunStatus.PARTIAL
            if errors
            else RunStatus.SUCCEEDED
        )
        # Counts only: no address, subject or snippet reaches the run history.
        runs.finish_run(db, run_id, status, {**totals, "errors": len(errors)}, ws_id=ws_id)
        db.commit()

    await run_in_threadpool(finish)
    return MailboxSyncResultOut(run_id=run_id, errors=errors, **totals)


def _fail_run(db: Session, ws_id: uuid.UUID, run_id: uuid.UUID, error: str) -> None:
    runs.finish_run(db, run_id, RunStatus.FAILED, None, error, ws_id=ws_id)
    db.commit()


def _record_sync(db: Session, ws_id: uuid.UUID, provider: str, error: str | None) -> None:
    conn = get_connection(db, ws_id, provider)
    if conn is not None:
        if error is None:
            conn.last_sync_at = datetime.now(UTC)
        conn.last_error = error
        db.commit()


# --- listing, link, ignore, unlink --------------------------------------------------------------


def message_out(db: Session, msg: MailboxMessage, provider: str) -> MailboxMessageOut:
    return MailboxMessageOut(
        id=msg.id,
        provider=provider,  # type: ignore[arg-type]
        from_addr=msg.from_addr,
        to_addrs=msg.to_addrs,
        cc_addrs=msg.cc_addrs,
        sent_at=msg.sent_at,
        subject=msg.subject,
        snippet=msg.snippet,
        state=msg.state,  # type: ignore[arg-type]
        suggested_deal_id=msg.suggested_deal_id,
        score=msg.score,
        reasons=msg.reasons,
        linked_activity_id=msg.linked_activity_id,
    )


def list_messages(
    db: Session,
    ws_id: uuid.UUID,
    *,
    deal_id: uuid.UUID | None = None,
    state: str | None = None,
    q: str | None = None,
    unmatched: bool = False,
    limit: int = 50,
    viewer: Viewer | None = None,
) -> list[MailboxMessageOut]:
    """Candidates, newest first. `deal_id` with no state: the emails suggested for that deal.
    `q` searches the subject (and the snippet); `unmatched` keeps those with no suggested deal."""
    from app.services._common import LIKE_ESCAPE, like_contains

    stmt = select(MailboxMessage, MailboxConnection.provider).join(
        MailboxConnection, MailboxConnection.id == MailboxMessage.connection_id
    )
    # a rep sees only the emails suggested for or linked to a deal they own
    stmt = stmt.where(
        MailboxMessage.workspace_id == ws_id,
        *visibility.conds(visibility.in_deals(viewer, MailboxMessage.suggested_deal_id)),
    )
    if deal_id is not None:
        require_deal(db, ws_id, deal_id, viewer)
        stmt = stmt.where(MailboxMessage.suggested_deal_id == deal_id)
        if state is None:
            stmt = stmt.where(MailboxMessage.state == "suggested")
    if state is not None:
        stmt = stmt.where(MailboxMessage.state == state)
    if unmatched:
        stmt = stmt.where(MailboxMessage.suggested_deal_id.is_(None))
    if q and q.strip():
        pattern = like_contains(q.strip()[:100])
        stmt = stmt.where(
            or_(
                MailboxMessage.subject.ilike(pattern, escape=LIKE_ESCAPE),
                MailboxMessage.snippet.ilike(pattern, escape=LIKE_ESCAPE),
            )
        )
    stmt = stmt.order_by(MailboxMessage.sent_at.desc(), MailboxMessage.id).limit(
        min(max(limit, 1), LIST_CAP)
    )
    return [message_out(db, m, p) for m, p in db.execute(stmt)]


def _require_message(
    db: Session, ws_id: uuid.UUID, message_id: uuid.UUID, viewer: Viewer | None = None
) -> MailboxMessage:
    msg = require(db, MailboxMessage, ws_id, message_id)
    if viewer is not None and not viewer.sees_everything:
        if msg.suggested_deal_id is None:
            raise NotFoundError("mailbox_message not found in this workspace")
        visibility.check_deal(db, viewer, msg.suggested_deal_id)
    return msg


def ignore_message(
    db: Session, ws_id: uuid.UUID, message_id: uuid.UUID, viewer: Viewer | None = None
) -> MailboxMessageOut:
    msg = _require_message(db, ws_id, message_id, viewer)
    if msg.state == "linked":
        raise InvalidInputError("the email is linked: unlink it first")
    msg.state = "ignored"
    db.flush()
    return message_out(db, msg, db.get(MailboxConnection, msg.connection_id).provider)


def unlink_message(
    db: Session, ws_id: uuid.UUID, message_id: uuid.UUID, viewer: Viewer | None = None
) -> MailboxMessageOut:
    """A linked email: its activity is deleted and the email goes back to `suggested`. An
    ignored email is restored."""
    msg = _require_message(db, ws_id, message_id, viewer)
    if msg.state == "linked" and msg.linked_activity_id is not None:
        act = activities.get_activity(db, ws_id, msg.linked_activity_id)
        if act is not None and act.source == "mailbox":
            activities.delete_activity(db, ws_id, act.id, viewer)
    msg.linked_activity_id = None
    msg.state = "suggested"
    db.flush()
    return message_out(db, msg, db.get(MailboxConnection, msg.connection_id).provider)


def external_ref(provider_message_id: str) -> str:
    if len(provider_message_id) <= 200:
        return provider_message_id
    return "sha256:" + store.sha256_hex(provider_message_id)


@dataclass
class _LinkPlan:
    provider: str
    provider_message_id: str
    existing: MailboxMessageOut | None = None


def _plan_link(
    db: Session,
    ws_id: uuid.UUID,
    message_id: uuid.UUID,
    deal_id: uuid.UUID,
    viewer: Viewer | None = None,
):
    msg = _require_message(db, ws_id, message_id, viewer)
    deal = require_deal(db, ws_id, deal_id, viewer)
    if deal.stage not in {s.value for s in OPEN_STAGES}:
        raise InvalidInputError("emails can only be linked to an open deal")
    provider = db.get(MailboxConnection, msg.connection_id).provider
    if msg.state == "linked":
        act = (
            activities.get_activity(db, ws_id, msg.linked_activity_id)
            if msg.linked_activity_id
            else None
        )
        if act is not None and act.deal_id == deal_id:
            return _LinkPlan(provider, msg.provider_message_id, message_out(db, msg, provider))
        raise InvalidInputError("the email is already linked to another deal: unlink it first")
    return _LinkPlan(provider, msg.provider_message_id)


def _finish_link(
    db: Session,
    settings: Settings,
    ws_id: uuid.UUID,
    message_id: uuid.UUID,
    deal_id: uuid.UUID,
    body: str,
    viewer: Viewer | None = None,
) -> MailboxMessageOut:
    msg = _require_message(db, ws_id, message_id, viewer)
    deal = require_deal(db, ws_id, deal_id, viewer)
    conn = db.get(MailboxConnection, msg.connection_id)
    own = None
    if conn.account_email_enc:
        try:
            own = unseal(conn.account_email_enc, settings)
        except EnrichmentError:
            own = None
    ref = external_ref(msg.provider_message_id)
    act = db.scalar(
        select(Activity).where(
            Activity.workspace_id == ws_id,
            Activity.source == "mailbox",
            Activity.external_ref == ref,
        )
    )
    if act is None:
        participants = _participants(db, settings, ws_id, deal.account_id, msg, own)
        try:
            with db.begin_nested():
                act = activities.create_activity(
                    db,
                    ws_id,
                    deal.account_id,
                    kind="email",
                    occurred_at=msg.sent_at,
                    subject=msg.subject or "(no subject)",
                    direction="outbound" if own and msg.from_addr == own.lower() else "inbound",
                    body=body or None,
                    deal_id=deal.id,
                    participant_ids=participants,
                    source="mailbox",
                    external_ref=ref,
                    check_future=False,
                )
        except IntegrityError:
            act = db.scalar(
                select(Activity).where(
                    Activity.workspace_id == ws_id,
                    Activity.source == "mailbox",
                    Activity.external_ref == ref,
                )
            )
            if act is None:
                raise
    msg.state, msg.linked_activity_id, msg.suggested_deal_id = "linked", act.id, deal.id
    db.flush()
    return message_out(db, msg, conn.provider)


def _participants(
    db: Session,
    settings: Settings,
    ws_id: uuid.UUID,
    account_id: uuid.UUID,
    msg: MailboxMessage,
    own: str | None,
) -> list[uuid.UUID]:
    """Contacts of the deal's account whose known email is on the message."""
    addrs = {msg.from_addr, *msg.to_addrs, *msg.cc_addrs} - ({own.lower()} if own else set())
    found: list[uuid.UUID] = []
    rows = db.execute(
        select(ContactChannel.value_enc, ContactChannel.contact_id)
        .join(Contact, Contact.id == ContactChannel.contact_id)
        .where(
            ContactChannel.workspace_id == ws_id,
            ContactChannel.kind == "email",
            Contact.account_id == account_id,
        )
    )
    for value_enc, contact_id in rows:
        try:
            addr = base.clean_addr(unseal(value_enc, settings))
        except EnrichmentError:
            continue
        if addr in addrs and contact_id not in found:
            found.append(contact_id)
    return found


async def link_message(
    db: Session,
    settings: Settings,
    ws_id: uuid.UUID,
    message_id: uuid.UUID,
    deal_id: uuid.UUID,
    viewer: Viewer | None = None,
) -> MailboxMessageOut:
    """Fetch the body now (the only time it is read) and log the email as an activity."""
    plan = await run_in_threadpool(_plan_link, db, ws_id, message_id, deal_id, viewer)
    await run_in_threadpool(db.rollback)
    if plan.existing is not None:
        return plan.existing
    grant = await access_grant(db, settings, ws_id, plan.provider)
    try:
        async with oauth.new_client() as client:
            body = await PROVIDERS[plan.provider].fetch_body(
                client, grant.access, plan.provider_message_id
            )
    except base.Unauthorized:
        msg = "the provider rejected the access; reconnect"
        await run_in_threadpool(mark_needs_reconnect, db, ws_id, plan.provider, msg)
        raise NeedsReconnect(msg) from None

    def save() -> MailboxMessageOut:
        out = _finish_link(db, settings, ws_id, message_id, deal_id, body, viewer)
        db.commit()
        return out

    return await run_in_threadpool(save)


# --- disconnect, erasure ------------------------------------------------------------------------


async def disconnect(db: Session, settings: Settings, ws_id: uuid.UUID, provider: str) -> None:
    """Forget the tokens (revoked at the provider on a best-effort basis) and every email that
    is not linked. Linked emails stay as activities: they are CRM data now."""
    mod = _provider(provider)

    def snapshot() -> str | None:
        conn = get_connection(db, ws_id, provider)
        token = None
        sealed = conn and (conn.refresh_token_enc or conn.access_token_enc)
        if sealed:
            try:
                token = unseal(sealed, settings)
            except EnrichmentError:
                token = None
        db.rollback()
        return token

    token = await run_in_threadpool(snapshot)
    if token:
        try:
            async with oauth.new_client() as client:
                async with asyncio.timeout(10):
                    await mod.revoke(client, token)
        except Exception as exc:  # noqa: BLE001 - disconnecting must not depend on the provider
            log.info("mailbox token revocation skipped (%s)", type(exc).__name__)

    def wipe() -> None:
        conn = get_connection(db, ws_id, provider)
        if conn is not None:
            db.execute(
                delete(MailboxMessage).where(
                    MailboxMessage.connection_id == conn.id, MailboxMessage.state != "linked"
                )
            )
            conn.status = "configured"
            conn.access_token_enc = conn.refresh_token_enc = conn.account_email_enc = None
            conn.token_expires_at = None
            conn.last_error = None
        db.execute(
            delete(OAuthPending).where(
                OAuthPending.workspace_id == ws_id, OAuthPending.provider == provider
            )
        )
        db.commit()

    await run_in_threadpool(wipe)


def purge_for_contact(session: Session, ws_id: uuid.UUID, contact: Contact) -> int:
    """GDPR: delete the stored email metadata in which the erased contact's known email appears
    (as sender, recipient or cc). Runs in the caller's transaction."""
    addrs: list[str] = []
    for (value_enc,) in session.execute(
        select(ContactChannel.value_enc).where(
            ContactChannel.workspace_id == ws_id,
            ContactChannel.contact_id == contact.id,
            ContactChannel.kind == "email",
        )
    ):
        try:
            addr = base.clean_addr(unseal(value_enc))
        except EnrichmentError:
            continue
        if addr:
            addrs.append(addr)
    if not addrs:
        return 0
    cond = [MailboxMessage.from_addr.in_(addrs)]
    for a in addrs:
        cond += [MailboxMessage.to_addrs.contains([a]), MailboxMessage.cc_addrs.contains([a])]
    result = session.execute(
        delete(MailboxMessage)
        .where(MailboxMessage.workspace_id == ws_id, or_(*cond))
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0
