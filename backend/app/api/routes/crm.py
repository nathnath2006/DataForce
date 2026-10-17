"""Accounts, contacts, the org chart and deals."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api.deps import CurrentWorkspace, Db
from app.api.schemas import (
    AccountCreate,
    AccountOut,
    AccountUpdate,
    ContactCreate,
    ContactOut,
    ContactUpdate,
    DealCreate,
    DealOut,
    DealUpdate,
    OrgChartNode,
    OrgChartOut,
    Page,
    ReportsToUpdate,
    StageUpdate,
)
from app.db.models import Account, Contact, Deal
from app.domain.enums import CLOSED_STAGES, DealStage, LeadSource, Segment
from app.domain.schemas import AccountIn, AccountRead, ContactIn, ContactRead, DealIn, DealRead
from app.services import accounts, contacts, deals
from app.services._common import require_account, require_contact, require_deal

router = APIRouter(tags=["crm"])

Limit = Annotated[int, Query(ge=1, le=1000)]
Offset = Annotated[int, Query(ge=0, le=1_000_000)]
# Search text: at most 200 characters and no control characters (NUL makes Postgres fail).
SearchQ = Annotated[str | None, Query(max_length=200, pattern=r"^[^\x00-\x1f\x7f]*$")]


# --- output builders (counts and names come from grouped queries, never per row) -------------
def _accounts_out(db: Db, ws_id: uuid.UUID, rows: list[Account]) -> list[AccountOut]:
    counts = accounts.account_counts(db, ws_id, [a.id for a in rows])
    out = []
    for a in rows:
        n_contacts, n_deals, n_open = counts[a.id]
        out.append(
            AccountOut(
                **AccountRead.model_validate(a).model_dump(),
                n_contacts=n_contacts,
                n_deals=n_deals,
                n_open_deals=n_open,
            )
        )
    return out


def _contacts_out(db: Db, ws_id: uuid.UUID, rows: list[Contact]) -> list[ContactOut]:
    extras = contacts.contact_extras(db, ws_id, [c.id for c in rows])
    return [ContactOut(**ContactRead.model_validate(c).model_dump(), **extras[c.id]) for c in rows]


def _deals_out(db: Db, ws_id: uuid.UUID, rows: list[Deal]) -> list[DealOut]:
    names = deals.deal_names(db, ws_id, [d.id for d in rows])
    out = []
    for d in rows:
        account_name, owner_name = names[d.id]
        cycle = (d.closed_on - d.created_on).days if d.closed_on else None
        out.append(
            DealOut(
                **DealRead.model_validate(d).model_dump(),
                account_name=account_name,
                owner_name=owner_name,
                is_closed=DealStage(d.stage) in CLOSED_STAGES,
                cycle_days=cycle,
            )
        )
    return out


# --- accounts -------------------------------------------------------------------------------
@router.get("/w/{ws}/accounts", response_model=Page[AccountOut])
def list_accounts(
    db: Db,
    ws: CurrentWorkspace,
    q: SearchQ = None,
    segment: Segment | None = None,
    limit: Limit = 200,
    offset: Offset = 0,
) -> Page[AccountOut]:
    rows, total = accounts.list_accounts_page(
        db, ws.id, q=q, segment=segment.value if segment else None, limit=limit, offset=offset
    )
    return Page(items=_accounts_out(db, ws.id, rows), total=total)


@router.post("/w/{ws}/accounts", response_model=AccountOut, status_code=201)
def create_account(body: AccountCreate, db: Db, ws: CurrentWorkspace) -> AccountOut:
    account = accounts.create_account(db, ws.id, AccountIn(**body.model_dump()))
    db.commit()
    return _accounts_out(db, ws.id, [account])[0]


@router.get("/w/{ws}/accounts/{account_id}", response_model=AccountOut)
def get_account(account_id: uuid.UUID, db: Db, ws: CurrentWorkspace) -> AccountOut:
    return _accounts_out(db, ws.id, [require_account(db, ws.id, account_id)])[0]


@router.patch("/w/{ws}/accounts/{account_id}", response_model=AccountOut)
def update_account(
    account_id: uuid.UUID, body: AccountUpdate, db: Db, ws: CurrentWorkspace
) -> AccountOut:
    changes = body.model_dump(exclude_unset=True)
    account = accounts.update_account(db, ws.id, account_id, changes)
    db.commit()
    return _accounts_out(db, ws.id, [account])[0]


@router.delete("/w/{ws}/accounts/{account_id}", status_code=204)
def erase_account(account_id: uuid.UUID, db: Db, ws: CurrentWorkspace) -> Response:
    accounts.erase_account(db, ws.id, account_id)
    db.commit()
    return Response(status_code=204)


@router.get("/w/{ws}/accounts/{account_id}/org-chart", response_model=OrgChartOut)
def org_chart(account_id: uuid.UUID, db: Db, ws: CurrentWorkspace) -> OrgChartOut:
    account = require_account(db, ws.id, account_id)
    nodes = [
        OrgChartNode(
            id=c.id,
            full_name=c.full_name,
            title=c.title,
            reports_to_id=boss,
            source=c.source,
        )
        for c, boss in contacts.org_chart(db, ws.id, account_id)
    ]
    return OrgChartOut(account_id=account.id, account_name=account.name, nodes=nodes)


# --- contacts -------------------------------------------------------------------------------
@router.get("/w/{ws}/contacts", response_model=Page[ContactOut])
def list_contacts(
    db: Db,
    ws: CurrentWorkspace,
    account_id: uuid.UUID | None = None,
    q: SearchQ = None,
    limit: Limit = 200,
    offset: Offset = 0,
) -> Page[ContactOut]:
    rows, total = contacts.list_contacts_page(
        db, ws.id, account_id=account_id, q=q, limit=limit, offset=offset
    )
    return Page(items=_contacts_out(db, ws.id, rows), total=total)


@router.post("/w/{ws}/contacts", response_model=ContactOut, status_code=201)
def create_contact(body: ContactCreate, db: Db, ws: CurrentWorkspace) -> ContactOut:
    contact = contacts.create_contact(db, ws.id, ContactIn(**body.model_dump()))
    db.commit()
    return _contacts_out(db, ws.id, [contact])[0]


@router.get("/w/{ws}/contacts/{contact_id}", response_model=ContactOut)
def get_contact(contact_id: uuid.UUID, db: Db, ws: CurrentWorkspace) -> ContactOut:
    return _contacts_out(db, ws.id, [require_contact(db, ws.id, contact_id)])[0]


@router.patch("/w/{ws}/contacts/{contact_id}", response_model=ContactOut)
def update_contact(
    contact_id: uuid.UUID, body: ContactUpdate, db: Db, ws: CurrentWorkspace
) -> ContactOut:
    contact = contacts.update_contact(db, ws.id, contact_id, body.model_dump(exclude_unset=True))
    db.commit()
    return _contacts_out(db, ws.id, [contact])[0]


@router.put("/w/{ws}/contacts/{contact_id}/reports-to", response_model=ContactOut)
def set_reports_to(
    contact_id: uuid.UUID, body: ReportsToUpdate, db: Db, ws: CurrentWorkspace
) -> ContactOut:
    contact = contacts.set_reports_to(db, ws.id, contact_id, body.manager_id)
    db.commit()
    return _contacts_out(db, ws.id, [contact])[0]


@router.delete("/w/{ws}/contacts/{contact_id}", status_code=204)
def erase_contact(contact_id: uuid.UUID, db: Db, ws: CurrentWorkspace) -> Response:
    contacts.erase_contact(db, ws.id, contact_id)
    db.commit()
    return Response(status_code=204)


# --- deals ----------------------------------------------------------------------------------
@router.get("/w/{ws}/deals", response_model=Page[DealOut])
def list_deals(
    db: Db,
    ws: CurrentWorkspace,
    account_id: uuid.UUID | None = None,
    stage: DealStage | None = None,
    lead_source: LeadSource | None = None,
    owner_id: uuid.UUID | None = None,
    q: SearchQ = None,
    limit: Limit = 200,
    offset: Offset = 0,
) -> Page[DealOut]:
    rows, total = deals.list_deals_page(
        db,
        ws.id,
        account_id=account_id,
        stage=stage.value if stage else None,
        lead_source=lead_source.value if lead_source else None,
        owner_id=owner_id,
        q=q,
        limit=limit,
        offset=offset,
    )
    return Page(items=_deals_out(db, ws.id, rows), total=total)


@router.post("/w/{ws}/deals", response_model=DealOut, status_code=201)
def create_deal(body: DealCreate, db: Db, ws: CurrentWorkspace) -> DealOut:
    deal = deals.create_deal(db, ws.id, DealIn(**body.model_dump()))
    db.commit()
    return _deals_out(db, ws.id, [deal])[0]


@router.get("/w/{ws}/deals/{deal_id}", response_model=DealOut)
def get_deal(deal_id: uuid.UUID, db: Db, ws: CurrentWorkspace) -> DealOut:
    return _deals_out(db, ws.id, [require_deal(db, ws.id, deal_id)])[0]


@router.patch("/w/{ws}/deals/{deal_id}", response_model=DealOut)
def update_deal(deal_id: uuid.UUID, body: DealUpdate, db: Db, ws: CurrentWorkspace) -> DealOut:
    deal = deals.update_deal(db, ws.id, deal_id, body.model_dump(exclude_unset=True))
    db.commit()
    return _deals_out(db, ws.id, [deal])[0]


@router.put("/w/{ws}/deals/{deal_id}/stage", response_model=DealOut)
def set_stage(deal_id: uuid.UUID, body: StageUpdate, db: Db, ws: CurrentWorkspace) -> DealOut:
    deal = deals.set_stage(db, ws.id, deal_id, body.stage, body.closed_on)
    db.commit()
    return _deals_out(db, ws.id, [deal])[0]


@router.delete("/w/{ws}/deals/{deal_id}", status_code=204)
def delete_deal(deal_id: uuid.UUID, db: Db, ws: CurrentWorkspace) -> Response:
    deals.delete_deal(db, ws.id, deal_id)
    db.commit()
    return Response(status_code=204)
