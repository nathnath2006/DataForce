"""Mailbox routes (Gmail, Outlook): connect, sync, candidate emails, link to deals (M4 phase 2).

The callback is reached by a redirect from the provider: it carries no body and no Origin, is
guarded by the single-use state, PKCE and the `df_oauth_mb` cookie, and always answers 303 to a
fixed relative path.
"""

from __future__ import annotations

from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from app.api.deps import AppSettings, CurrentViewer, CurrentWorkspace, Db
from app.api.schemas_mailbox import (
    MailboxClientIn,
    MailboxConnectOut,
    MailboxLinkIn,
    MailboxMessageOut,
    MailboxStatusOut,
    MailboxSyncIn,
    MailboxSyncResultOut,
    MessageState,
    Provider,
)
from app.auth.visibility import require_admin
from app.services import mailbox as svc

router = APIRouter(tags=["mailbox"])

COOKIE_NAME = "df_oauth_mb"
COOKIE_PATH = "/api/mailbox"
COOKIE_MAX_AGE_S = 600


@router.get("/w/{ws}/mailbox", response_model=MailboxStatusOut)
def mailbox_status(
    db: Db, ws: CurrentWorkspace, settings: AppSettings, viewer: CurrentViewer
) -> MailboxStatusOut:
    require_admin(viewer)
    return svc.status_view(db, settings, ws)


@router.put("/w/{ws}/mailbox/{provider}/client", response_model=MailboxStatusOut)
def set_client(
    provider: Provider,
    body: MailboxClientIn,
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    viewer: CurrentViewer,
) -> MailboxStatusOut:
    require_admin(viewer)
    svc.save_client(db, settings, ws.id, provider, body.client_id, body.client_secret)
    db.commit()
    return svc.status_view(db, settings, ws)


@router.post("/w/{ws}/mailbox/{provider}/connect", response_model=MailboxConnectOut)
async def connect(
    provider: Provider,
    request: Request,
    response: Response,
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    viewer: CurrentViewer,
) -> MailboxConnectOut:
    require_admin(viewer)
    url, browser_secret = await svc.start_connect(
        db, settings, ws.id, provider, request.headers.get("host")
    )
    response.set_cookie(
        COOKIE_NAME,
        browser_secret,
        max_age=COOKIE_MAX_AGE_S,
        path=COOKIE_PATH,
        httponly=True,
        samesite="lax",
    )
    return MailboxConnectOut(authorize_url=url)


@router.get("/mailbox/callback", include_in_schema=False)
async def callback(request: Request, db: Db, settings: AppSettings) -> RedirectResponse:
    params = request.query_params
    result = await svc.finish_callback(
        db,
        settings,
        state=params.get("state"),
        code=params.get("code"),
        error=params.get("error"),
        browser_cookie=request.cookies.get(COOKIE_NAME),
    )
    base = f"/w/{quote(result.slug, safe='')}/settings" if result.slug else "/"
    query = (
        "mailbox=connected" if result.reason is None else f"mailbox=error&reason={result.reason}"
    )
    redirect = RedirectResponse(f"{base}?{query}", status_code=303)
    redirect.delete_cookie(COOKIE_NAME, path=COOKIE_PATH)
    return redirect


@router.post("/w/{ws}/mailbox/sync", response_model=MailboxSyncResultOut)
async def sync(
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    viewer: CurrentViewer,
    body: MailboxSyncIn | None = None,
) -> MailboxSyncResultOut:
    require_admin(viewer)
    return await svc.sync(db, settings, ws.id, body.provider if body else None)


@router.delete("/w/{ws}/mailbox/{provider}", status_code=204)
async def disconnect(
    provider: Provider, db: Db, ws: CurrentWorkspace, settings: AppSettings, viewer: CurrentViewer
) -> Response:
    require_admin(viewer)
    await svc.disconnect(db, settings, ws.id, provider)
    return Response(status_code=204)


@router.get("/w/{ws}/mailbox/messages", response_model=list[MailboxMessageOut])
def list_messages(
    db: Db,
    ws: CurrentWorkspace,
    viewer: CurrentViewer,
    deal_id: UUID | None = None,
    state: MessageState | None = None,
    q: str | None = Query(default=None, max_length=100),
    unmatched: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[MailboxMessageOut]:
    return svc.list_messages(
        db,
        ws.id,
        deal_id=deal_id,
        state=state,
        q=q,
        unmatched=unmatched,
        limit=limit,
        viewer=viewer,
    )


@router.post("/w/{ws}/mailbox/messages/{message_id}/link", response_model=MailboxMessageOut)
async def link(
    message_id: UUID,
    body: MailboxLinkIn,
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    viewer: CurrentViewer,
) -> MailboxMessageOut:
    return await svc.link_message(db, settings, ws.id, message_id, body.deal_id, viewer)


@router.post("/w/{ws}/mailbox/messages/{message_id}/ignore", response_model=MailboxMessageOut)
def ignore(
    message_id: UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> MailboxMessageOut:
    out = svc.ignore_message(db, ws.id, message_id, viewer)
    db.commit()
    return out


@router.post("/w/{ws}/mailbox/messages/{message_id}/unlink", response_model=MailboxMessageOut)
async def unlink(
    message_id: UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> MailboxMessageOut:
    def run() -> MailboxMessageOut:
        out = svc.unlink_message(db, ws.id, message_id, viewer)
        db.commit()
        return out

    return await run_in_threadpool(run)
