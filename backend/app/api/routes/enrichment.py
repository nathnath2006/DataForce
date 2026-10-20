"""Contact enrichment and stored channels (docs/UI-CONTRACT.md sections 3 and 5, agent B).

Paid guard, in order and before any traffic to TamTam:
  demo workspace      -> the fake provider, always (fictional people; no credits exist);
  anything else       -> TamTam must be connected, `confirm_paid is True` and the server's own
                         estimate must not exceed the `max_credits` the user accepted.
Contact values are never logged or put in an error message.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response
from starlette.concurrency import run_in_threadpool

from app.api.deps import AppSettings, CurrentViewer, CurrentWorkspace, Db
from app.api.schemas import ChannelOut, EnrichRequest, EnrichResponse
from app.auth import visibility
from app.connectors import store, tamtam
from app.db.models import ContactChannel
from app.domain.enums import ChannelKind
from app.domain.schemas import EnrichmentRequest
from app.enrichment.errors import EnrichmentConfigError, PaidLookupRefused
from app.enrichment.fake import FakeEnrichmentProvider
from app.enrichment.tamtam_mcp import DEFAULT_CREDIT_COSTS
from app.services import channels
from app.services._common import require_account, require_contact

router = APIRouter()


def _channel_out(row: ContactChannel, value: str) -> ChannelOut:
    return ChannelOut(
        id=row.id,
        kind=ChannelKind(row.kind),
        value=value,
        provider=row.provider,
        credits_used=float(row.credits_used),
        raw_tool=row.raw_tool,
        fetched_at=row.fetched_at,
    )


@router.post(
    "/w/{ws}/contacts/{contact_id}/enrich", response_model=EnrichResponse, tags=["enrichment"]
)
async def enrich_contact(
    contact_id: uuid.UUID,
    body: EnrichRequest,
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    viewer: CurrentViewer,
) -> EnrichResponse:
    visibility.check_contact(db, viewer, contact_id)
    if ws.is_demo:  # the fake provider is free: no guard needed
        return await _enrich(contact_id, body, db, ws, settings)
    async with channels.lookup_guard(db, ws.id, contact_id):
        return await _enrich(contact_id, body, db, ws, settings)


async def _enrich(
    contact_id: uuid.UUID, body: EnrichRequest, db: Db, ws: CurrentWorkspace, settings: AppSettings
) -> EnrichResponse:
    ws_id, is_demo = ws.id, ws.is_demo
    wants = [k.value for k in dict.fromkeys(body.want)]

    def load() -> tuple[EnrichmentRequest, bool]:
        contact = require_contact(db, ws_id, contact_id)
        account = require_account(db, ws_id, contact.account_id)
        request = EnrichmentRequest(
            full_name=contact.full_name,
            company_name=account.name,
            company_domain=account.domain,
            want=wants,  # type: ignore[arg-type]
        )
        connected = store.get_credential(db, ws_id) is not None
        if not is_demo and connected:
            paid = [w for w in wants if DEFAULT_CREDIT_COSTS.get(w, 0.0) > 0]
            channels.refuse_stored_kinds(db, ws_id, contact_id, paid)
        db.rollback()  # no transaction stays open during the lookup
        return request, connected

    request, connected = await run_in_threadpool(load)

    if is_demo:
        provider = FakeEnrichmentProvider()
        mode = "fake"
    else:
        if not connected:
            raise EnrichmentConfigError("TamTam is not connected for this workspace")
        cost = tamtam.estimate_credits(wants)
        if cost > 0:
            if body.confirm_paid is not True:
                raise PaidLookupRefused(
                    f"this lookup costs about {cost:g} credit(s); confirm_paid is required"
                )
            if cost > body.max_credits:
                raise PaidLookupRefused(
                    f"the lookup is now estimated at {cost:g} credit(s), above the "
                    f"{body.max_credits:g} you accepted; nothing was sent"
                )
            if cost > settings.enrichment_max_credits_per_call:
                raise PaidLookupRefused(
                    f"the lookup is estimated at {cost:g} credit(s), above the per-call ceiling "
                    f"of {settings.enrichment_max_credits_per_call:g}; nothing was sent"
                )
        provider = await tamtam.build_provider(db, settings, ws_id)
        mode = "tamtam"

    # The consent was checked above (or the provider is the fake one: nothing real is spent).
    result = await provider.enrich_contact(request, allow_paid=True)

    found = [
        (kind, value)
        for kind, value in ((ChannelKind.EMAIL, result.email), (ChannelKind.MOBILE, result.mobile))
        if value
    ]
    weights = {k: DEFAULT_CREDIT_COSTS.get(k.value, 0.0) for k, _ in found}
    weight_sum = sum(weights.values())

    def save() -> list[ChannelOut]:
        out: list[ChannelOut] = []
        for kind, value in found:
            share = weights[kind] / weight_sum if weight_sum > 0 else 1 / len(found)
            row = channels.add_channel(
                db,
                ws_id,
                contact_id,
                kind,
                value,
                provider=result.provider,
                credits_used=round(result.credits_used * share, 3),
                raw_tool=result.raw_tool,
                settings=settings,
            )
            out.append(_channel_out(row, value))
        db.commit()
        return out

    stored = await run_in_threadpool(save)
    return EnrichResponse(
        mode=mode,  # type: ignore[arg-type]
        channels=stored,
        credits_used=result.credits_used,
        anomalous=result.anomalous,
        notes=result.notes,
    )


@router.get(
    "/w/{ws}/contacts/{contact_id}/channels",
    response_model=list[ChannelOut],
    tags=["enrichment"],
)
def list_contact_channels(
    contact_id: uuid.UUID,
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    viewer: CurrentViewer,
) -> list[ChannelOut]:
    visibility.check_contact(db, viewer, contact_id)
    rows = channels.list_channels(db, ws.id, contact_id)
    return [_channel_out(r, channels.channel_value(r, settings)) for r in rows]


@router.delete(
    "/w/{ws}/contacts/{contact_id}/channels/{channel_id}", status_code=204, tags=["enrichment"]
)
def delete_contact_channel(
    contact_id: uuid.UUID,
    channel_id: uuid.UUID,
    db: Db,
    ws: CurrentWorkspace,
    viewer: CurrentViewer,
) -> Response:
    visibility.check_contact(db, viewer, contact_id)
    visibility.require_admin(viewer)  # stored emails and mobiles: erasure is admin only
    channels.delete_channel(db, ws.id, contact_id, channel_id)
    db.commit()
    return Response(status_code=204)
