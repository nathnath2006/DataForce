"""TamTam connector routes (docs/UI-CONTRACT.md section 3, agent B).

The callback is the only route reached by a redirect from another site, so it carries no body
and no Origin: it is guarded by the single-use state, the `df_oauth` cookie, PKCE and `iss`
(see app.connectors.tamtam.finish_callback), and always answers 303 to a fixed relative path.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from app.api.deps import AppSettings, CurrentWorkspace, Db
from app.api.schemas import ConnectorOut, ConnectStart
from app.connectors import tamtam

router = APIRouter()

COOKIE_NAME = "df_oauth"
COOKIE_PATH = "/api/connectors"
COOKIE_MAX_AGE_S = 600


@router.get("/w/{ws}/connectors/tamtam", response_model=ConnectorOut, tags=["connectors"])
def get_tamtam(db: Db, ws: CurrentWorkspace, settings: AppSettings) -> ConnectorOut:
    return tamtam.status_view(db, settings, ws)


@router.post("/w/{ws}/connectors/tamtam/connect", response_model=ConnectStart, tags=["connectors"])
async def connect_tamtam(
    request: Request, db: Db, ws: CurrentWorkspace, settings: AppSettings, response: Response
) -> ConnectStart:
    url, browser_secret = await tamtam.start_connect(
        db, settings, ws.id, request.headers.get("host")
    )
    response.set_cookie(
        COOKIE_NAME,
        browser_secret,
        max_age=COOKIE_MAX_AGE_S,
        path=COOKIE_PATH,
        httponly=True,
        samesite="lax",
    )
    return ConnectStart(authorize_url=url)


@router.get("/connectors/tamtam/callback", include_in_schema=False)
async def tamtam_callback(request: Request, db: Db, settings: AppSettings) -> RedirectResponse:
    # Raw query access: an odd or oversized parameter must still end in the fixed 303, never in
    # a validation error that could echo it.
    params = request.query_params
    result = await tamtam.finish_callback(
        db,
        settings,
        state=params.get("state"),
        code=params.get("code"),
        iss=params.get("iss"),
        error=params.get("error"),
        browser_cookie=request.cookies.get(COOKIE_NAME),
    )
    base = f"/w/{quote(result.slug, safe='')}/settings" if result.slug else "/"
    query = "tamtam=connected" if result.reason is None else f"tamtam=error&reason={result.reason}"
    redirect = RedirectResponse(f"{base}?{query}", status_code=303)
    redirect.delete_cookie(COOKIE_NAME, path=COOKIE_PATH)
    return redirect


@router.post("/w/{ws}/connectors/tamtam/check", response_model=ConnectorOut, tags=["connectors"])
async def check_tamtam(db: Db, ws: CurrentWorkspace, settings: AppSettings) -> ConnectorOut:
    await tamtam.run_check(db, settings, ws.id)
    return await run_in_threadpool(tamtam.status_view, db, settings, ws)


@router.delete("/w/{ws}/connectors/tamtam", status_code=204, tags=["connectors"])
async def disconnect_tamtam(db: Db, ws: CurrentWorkspace, settings: AppSettings) -> Response:
    await tamtam.disconnect(db, settings, ws.id)
    return Response(status_code=204)
