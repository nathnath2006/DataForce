"""Row visibility: which workspace rows a `Viewer` may see (docs/M5-LOGIN-AND-UI-CONTRACT.md).

Every helper returns a SQLAlchemy condition or a subquery, or `None` when the viewer sees
everything (the admin and *see all* members), so callers skip the filter and stay cheap:
`stmt.where(*conds(...))` with `none` dropped, or `apply(stmt, cond)`.

Rules:
- a deal is visible when its owner is the viewer's CRM identity;
- an account when the viewer owns it or owns a deal on it;
- contacts, notes, comments, activities, tasks, documents and org proposals follow their account;
- a company when it groups at least one visible account;
- a record nobody owns is visible only to those who see everything;
- a viewer without a CRM identity sees nothing owned.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, false, or_, select
from sqlalchemy.orm import Session

from app.auth.viewer import Viewer
from app.db.models import Account, Comment, Contact, Deal, Note
from app.services.errors import ForbiddenError, NotFoundError


def _mine(column: Any, viewer: Viewer) -> ColumnElement[bool]:
    if viewer.app_user_id is None:
        return false()
    return column == viewer.app_user_id


def deal_ids(viewer: Viewer | None) -> Select | None:
    """Subquery of the deal ids the viewer owns, or None (no filter)."""
    if viewer is None or viewer.sees_everything:
        return None
    return select(Deal.id).where(
        Deal.workspace_id == viewer.workspace_id, _mine(Deal.owner_id, viewer)
    )


def account_ids(viewer: Viewer | None) -> Select | None:
    """Subquery of visible account ids: owned by the viewer, or with a deal the viewer owns."""
    if viewer is None or viewer.sees_everything:
        return None
    owned_deal = select(Deal.account_id).where(
        Deal.workspace_id == viewer.workspace_id, _mine(Deal.owner_id, viewer)
    )
    return select(Account.id).where(
        Account.workspace_id == viewer.workspace_id,
        or_(_mine(Account.owner_id, viewer), Account.id.in_(owned_deal)),
    )


def contact_ids(viewer: Viewer | None) -> Select | None:
    accounts = account_ids(viewer)
    if accounts is None:
        return None
    return select(Contact.id).where(Contact.account_id.in_(accounts))


def company_ids(viewer: Viewer | None) -> Select | None:
    """Companies that group at least one visible account."""
    accounts = account_ids(viewer)
    if accounts is None:
        return None
    return select(Account.company_id).where(
        Account.id.in_(accounts), Account.company_id.is_not(None)
    )


def deals_cond(viewer: Viewer | None) -> ColumnElement[bool] | None:
    return None if viewer is None or viewer.sees_everything else _mine(Deal.owner_id, viewer)


def in_deals(viewer: Viewer | None, column: Any) -> ColumnElement[bool] | None:
    sub = deal_ids(viewer)
    return None if sub is None else column.in_(sub)


def in_accounts(viewer: Viewer | None, column: Any) -> ColumnElement[bool] | None:
    sub = account_ids(viewer)
    return None if sub is None else column.in_(sub)


def in_contacts(viewer: Viewer | None, column: Any) -> ColumnElement[bool] | None:
    sub = contact_ids(viewer)
    return None if sub is None else column.in_(sub)


def in_companies(viewer: Viewer | None, column: Any) -> ColumnElement[bool] | None:
    sub = company_ids(viewer)
    return None if sub is None else column.in_(sub)


def account_or_deal(
    viewer: Viewer | None, account_col: Any, deal_col: Any
) -> ColumnElement[bool] | None:
    """Tasks and the like: visible through the account, or through the deal when there is no
    account."""
    if viewer is None or viewer.sees_everything:
        return None
    return or_(
        and_(deal_col.is_(None), in_accounts(viewer, account_col)),
        in_deals(viewer, deal_col),
    )


def deal_gate(viewer: Viewer | None, deal_col: Any) -> ColumnElement[bool] | None:
    """A row with a deal is visible only if that deal is; a row without one follows its account."""
    sub = deal_ids(viewer)
    return None if sub is None else or_(deal_col.is_(None), deal_col.in_(sub))


def check_row_deal(session: Session, viewer: Viewer | None, deal_id: uuid.UUID | None) -> None:
    """404 when the row is tied to a deal the viewer cannot see."""
    if deal_id is not None:
        check_deal(session, viewer, deal_id)


def note_cond(viewer: Viewer | None) -> ColumnElement[bool] | None:
    return in_contacts(viewer, Note.contact_id)


def comment_cond(viewer: Viewer | None) -> ColumnElement[bool] | None:
    return in_accounts(viewer, Comment.account_id)


def scope_key(viewer: Viewer | None) -> str:
    """Names whose rows a stored result was computed over: "all", or one rep's CRM identity."""
    if viewer is None or viewer.sees_everything:
        return "all"
    return str(viewer.app_user_id)


def conds(*items: ColumnElement[bool] | None) -> list[ColumnElement[bool]]:
    """The non-None conditions, ready for `.where(*conds(...))`."""
    return [c for c in items if c is not None]


# --- by-id checks: a record the viewer may not see is "not found" ---------------------------
def _exists(session: Session, sub: Select | None, model_id_col: Any, row_id: uuid.UUID) -> bool:
    if sub is None:
        return True
    return (
        session.scalar(select(model_id_col).where(model_id_col == row_id, model_id_col.in_(sub)))
        is not None
    )


def can_see_account(session: Session, viewer: Viewer | None, account_id: uuid.UUID) -> bool:
    return _exists(session, account_ids(viewer), Account.id, account_id)


def can_see_deal(session: Session, viewer: Viewer | None, deal_id: uuid.UUID) -> bool:
    return _exists(session, deal_ids(viewer), Deal.id, deal_id)


def can_see_contact(session: Session, viewer: Viewer | None, contact_id: uuid.UUID) -> bool:
    return _exists(session, contact_ids(viewer), Contact.id, contact_id)


def can_see_company(session: Session, viewer: Viewer | None, company_id: uuid.UUID) -> bool:
    from app.db.models import Company

    return _exists(session, company_ids(viewer), Company.id, company_id)


def check_account(session: Session, viewer: Viewer | None, account_id: uuid.UUID) -> None:
    if not can_see_account(session, viewer, account_id):
        raise NotFoundError(f"account {account_id} not found in this workspace")


def check_deal(session: Session, viewer: Viewer | None, deal_id: uuid.UUID) -> None:
    if not can_see_deal(session, viewer, deal_id):
        raise NotFoundError(f"deal {deal_id} not found in this workspace")


def check_contact(session: Session, viewer: Viewer | None, contact_id: uuid.UUID) -> None:
    if not can_see_contact(session, viewer, contact_id):
        raise NotFoundError(f"contact {contact_id} not found in this workspace")


def check_company(session: Session, viewer: Viewer | None, company_id: uuid.UUID) -> None:
    if not can_see_company(session, viewer, company_id):
        raise NotFoundError(f"company {company_id} not found in this workspace")


def check_row_account(
    session: Session, viewer: Viewer | None, account_id: uuid.UUID | None, deal_id: uuid.UUID | None
) -> None:
    """A task or activity: visible through its account, or its deal when it has no account."""
    if viewer is None or viewer.sees_everything:
        return
    if deal_id is not None:
        check_deal(session, viewer, deal_id)
    elif account_id is not None:
        check_account(session, viewer, account_id)
    else:
        raise NotFoundError("not found in this workspace")


# --- rights ---------------------------------------------------------------------------------
def require_admin(viewer: Viewer) -> None:
    """403 for anyone who is not the admin."""
    if not viewer.is_admin:
        raise ForbiddenError("only the administrator can do this")


def require_delete(viewer: Viewer, owner_app_user_id: uuid.UUID | None) -> None:
    """403 unless the admin, or a rep with *delete own* deleting their own record."""
    if not viewer.may_delete(owner_app_user_id):
        raise ForbiddenError("you are not allowed to delete this record")


def apply(stmt: Select, *items: ColumnElement[bool] | None) -> Select:
    return stmt.where(*conds(*items))


def owner_for_create(viewer: Viewer, requested: uuid.UUID | None) -> uuid.UUID | None:
    """The owner of a new deal or account: the viewer by default; only an admin names another."""
    if requested is None or requested == viewer.app_user_id:
        return viewer.app_user_id
    if not viewer.is_admin:
        raise ForbiddenError("only the administrator can assign another owner")
    return requested


def check_owner_change(viewer: Viewer, changes: dict[str, Any], current: uuid.UUID | None) -> None:
    """403 when a non-admin tries to change `owner_id` (an unchanged value is fine)."""
    if "owner_id" in changes and changes["owner_id"] != current and not viewer.is_admin:
        raise ForbiddenError("only the administrator can reassign the owner")
