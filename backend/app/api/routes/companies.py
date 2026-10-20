"""Companies, the CRM lookup and the public company registry (M2a, agent G)."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Response

from app.api.deps import AppSettings, CurrentViewer, CurrentWorkspace, Db
from app.api.routes.crm import (
    Direction,
    Limit,
    Offset,
    SearchQ,
    _accounts_out,
    _contacts_out,
    _deals_out,
)
from app.api.schemas import AccountOut, Page
from app.api.schemas_companies import (
    AccountCompanyLink,
    ActivityItem,
    Company360,
    CompanyCreate,
    CompanyOut,
    CompanyUpdate,
    FromRegistry,
    LookupOut,
    RegistryCompanyOut,
    RegistrySearchIn,
)
from app.auth.viewer import Viewer
from app.db.models import Company
from app.domain.schemas import AccountIn
from app.registry import client as registry
from app.services import accounts
from app.services import companies as svc
from app.services.errors import AlreadyExistsError, InvalidInputError, NotFoundError

router = APIRouter(tags=["companies"])


def _companies_out(
    db: Db, ws_id: uuid.UUID, rows: list[Company], viewer: Viewer | None = None
) -> list[CompanyOut]:
    stats = svc.company_stats(db, ws_id, [c.id for c in rows], viewer)
    return [CompanyOut.model_validate(c).model_copy(update=stats[c.id]) for c in rows]


def _refuse_protected(record: registry.RegistryCompany) -> None:
    if record.protected:
        raise AlreadyExistsError("this registry record is protected (non-diffusible)")


@router.get("/w/{ws}/lookup", response_model=LookupOut)
def lookup(db: Db, ws: CurrentWorkspace, viewer: CurrentViewer, q: SearchQ = None) -> LookupOut:
    q = (q or "").strip()
    if not q:
        return LookupOut(companies=[], accounts=[], interacted=False)
    rows, _ = svc.list_companies_page(db, ws.id, q=q, limit=20, viewer=viewer)
    companies = _companies_out(db, ws.id, rows, viewer)
    loose = svc.lookup_accounts_without_company(db, ws.id, q, viewer=viewer)
    last = svc.account_last_interaction(db, ws.id, [a.id for a in loose], viewer)
    return LookupOut(
        companies=companies,
        accounts=_accounts_out(db, ws.id, loose, viewer),
        interacted=any(c.interacted for c in companies) or bool(last),
    )


@router.get("/w/{ws}/companies", response_model=Page[CompanyOut])
def list_companies(
    db: Db,
    ws: CurrentWorkspace,
    viewer: CurrentViewer,
    q: SearchQ = None,
    sort: Literal["name", "city", "siren", "category", "size_bracket", "created_at"] | None = None,
    direction: Direction = "asc",
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[CompanyOut]:
    rows, total = svc.list_companies_page(
        db, ws.id, q=q, limit=limit, offset=offset, sort=sort, direction=direction, viewer=viewer
    )
    return Page(
        items=_companies_out(db, ws.id, rows, viewer), total=total, offset=offset, limit=limit
    )


@router.post("/w/{ws}/companies", response_model=CompanyOut, status_code=201)
def create_company(
    body: CompanyCreate, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> CompanyOut:
    company = svc.create_company(db, ws.id, **body.model_dump())
    db.commit()
    return _companies_out(db, ws.id, [company], viewer)[0]


@router.get("/w/{ws}/companies/{company_id}", response_model=Company360)
def get_company(
    company_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> Company360:
    company = svc.require_company(db, ws.id, company_id, viewer)
    parts = svc.company_360_parts(db, ws.id, company_id, viewer)
    return Company360(
        company=_companies_out(db, ws.id, [company], viewer)[0],
        accounts=_accounts_out(db, ws.id, parts["accounts"], viewer),
        contacts=_contacts_out(db, ws.id, parts["contacts"]),
        deals=_deals_out(db, ws.id, parts["deals"]),
        activity=[ActivityItem(**a) for a in parts["activity"]],
    )


@router.patch("/w/{ws}/companies/{company_id}", response_model=CompanyOut)
def update_company(
    company_id: uuid.UUID, body: CompanyUpdate, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> CompanyOut:
    company = svc.update_company(db, ws.id, company_id, body.model_dump(exclude_unset=True), viewer)
    db.commit()
    return _companies_out(db, ws.id, [company], viewer)[0]


@router.delete("/w/{ws}/companies/{company_id}", status_code=204)
def delete_company(
    company_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> Response:
    svc.delete_company(db, ws.id, company_id, viewer)
    db.commit()
    return Response(status_code=204)


@router.put("/w/{ws}/accounts/{account_id}/company", response_model=AccountOut)
def link_account(
    account_id: uuid.UUID,
    body: AccountCompanyLink,
    db: Db,
    ws: CurrentWorkspace,
    viewer: CurrentViewer,
) -> AccountOut:
    account = svc.link_account(db, ws.id, account_id, body.company_id, viewer)
    db.commit()
    return _accounts_out(db, ws.id, [account], viewer)[0]


# --- public registry (explicit user action only) --------------------------------------------
@router.post("/w/{ws}/registry/search", response_model=list[RegistryCompanyOut])
async def registry_search(
    body: RegistrySearchIn, db: Db, ws: CurrentWorkspace, settings: AppSettings
) -> list[RegistryCompanyOut]:
    found = await registry.search(settings, body.q)
    in_crm = svc.find_by_sirens(db, ws.id, [c.siren for c in found])
    return [
        RegistryCompanyOut(**c.model_dump(), in_crm_company_id=in_crm.get(c.siren)) for c in found
    ]


@router.post("/w/{ws}/companies/from-registry", response_model=CompanyOut, status_code=201)
async def from_registry(
    body: FromRegistry, db: Db, ws: CurrentWorkspace, settings: AppSettings, viewer: CurrentViewer
) -> CompanyOut:
    if svc.find_by_sirens(db, ws.id, [body.siren]):
        raise AlreadyExistsError("a company with this SIREN already exists in this workspace")
    record = await registry.fetch_by_siren(settings, body.siren)
    if record is None:
        raise NotFoundError("this SIREN was not found in the company registry")
    _refuse_protected(record)
    company = svc.create_from_registry(db, ws.id, record)
    if body.create_account:
        account = accounts.create_account(
            db, ws.id, AccountIn(name=company.name, country="FR"), owner_id=viewer.app_user_id
        )
        account.company_id = company.id
        db.flush()
    db.commit()
    return _companies_out(db, ws.id, [company], viewer)[0]


@router.post("/w/{ws}/companies/{company_id}/refresh-registry", response_model=CompanyOut)
async def refresh_registry(
    company_id: uuid.UUID,
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    viewer: CurrentViewer,
) -> CompanyOut:
    company = svc.require_company(db, ws.id, company_id, viewer)
    if not company.siren:
        raise InvalidInputError("this company has no SIREN to look up")
    record = await registry.fetch_by_siren(settings, company.siren)
    if record is None:
        raise NotFoundError("this SIREN was not found in the company registry")
    _refuse_protected(record)
    svc.apply_registry(db, company, record)
    db.commit()
    return _companies_out(db, ws.id, [company], viewer)[0]
