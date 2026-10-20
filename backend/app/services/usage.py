"""AI usage per user, model, day and purpose, with an estimated cost.

Cost = tokens x the price the superadmin set for that model (`model_price`). With no price the
cost is null: the page says "set a price" rather than guessing. When a group mixes priced and
unpriced models, the cost covers the priced calls only and `unpriced_calls` says how many are
left out. Calls with no signed-in person (background jobs, CLI) belong to "System".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from app.db.models import LlmCall, ModelPrice, UserAccount, Workspace
from app.services.errors import InvalidInputError

SYSTEM_LABEL = "System"
_MTOK = Decimal(1_000_000)


def prices(db: Session) -> dict[tuple[str, str], ModelPrice]:
    return {(p.provider, p.model): p for p in db.scalars(select(ModelPrice))}


def _cost(p: ModelPrice | None, tin: int, tout: int) -> Decimal | None:
    if p is None:
        return None
    return (Decimal(tin) * p.input_per_mtok_eur + Decimal(tout) * p.output_per_mtok_eur) / _MTOK


def _metrics(base: dict[str, Any], models: dict[tuple, dict[str, int]], price_of) -> dict[str, Any]:
    """Merge the per-model counts of one group into the row the API returns."""
    cost: Decimal | None = None
    priced_calls = 0
    unpriced = 0
    for (provider, model), n in models.items():
        c = _cost(price_of.get((provider, model)), n["in"], n["out"])
        if c is None:
            unpriced += n["calls"]
        else:
            cost = (cost or Decimal(0)) + c
            priced_calls += n["calls"]
    base = dict(base)
    base["cost_eur"] = float(round(cost, 6)) if cost is not None else None
    base["avg_cost_per_call_eur"] = (
        float(round(cost / priced_calls, 6)) if cost is not None and priced_calls else None
    )
    base["unpriced_calls"] = unpriced
    return base


def _day_expr():
    return cast(func.timezone("UTC", LlmCall.created_at), Date)


def _dimension(db: Session, cond: list, dims: list, price_of) -> dict[tuple, dict[str, Any]]:
    """Metrics for every distinct value of `dims` (a list of column expressions)."""
    base = db.execute(
        select(
            *dims,
            func.count().label("calls"),
            func.count().filter(LlmCall.success.is_(False)).label("failures"),
            func.coalesce(func.sum(LlmCall.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(LlmCall.output_tokens), 0).label("output_tokens"),
            func.percentile_cont(0.5).within_group(LlmCall.latency_ms).label("p50"),
        )
        .where(*cond)
        .group_by(*dims)  # no dims = one row for everything
    ).all()
    per_model = db.execute(
        select(
            *dims,
            LlmCall.provider,
            LlmCall.model,
            func.count().label("calls"),
            func.coalesce(func.sum(LlmCall.input_tokens), 0).label("tin"),
            func.coalesce(func.sum(LlmCall.output_tokens), 0).label("tout"),
        )
        .where(*cond)
        .group_by(*dims, LlmCall.provider, LlmCall.model)
    ).all()
    n = len(dims)
    models: dict[tuple, dict[tuple, dict[str, int]]] = {}
    for r in per_model:
        models.setdefault(tuple(r[:n]), {})[(r[n], r[n + 1])] = {
            "calls": r[n + 2],
            "in": int(r[n + 3]),
            "out": int(r[n + 4]),
        }
    out: dict[tuple, dict[str, Any]] = {}
    for r in base:
        key = tuple(r[:n])
        row = {
            "calls": r[n],
            "failures": r[n + 1],
            "input_tokens": int(r[n + 2]),
            "output_tokens": int(r[n + 3]),
            "p50_latency_ms": int(r[n + 4]) if r[n + 4] is not None else None,
        }
        out[key] = _metrics(row, models.get(key, {}), price_of)
    return out


def summary(db: Session, ws_id: uuid.UUID | None, days: int) -> dict[str, Any]:
    """Usage over the last `days` days. `ws_id` None = every workspace (superadmin only; the
    route decides). Returns totals plus by_user, by_model, by_day, by_day_user and by_purpose
    (and by_workspace when `ws_id` is None)."""
    if not 1 <= days <= 365:
        raise InvalidInputError("days must be between 1 and 365")
    since = datetime.now(UTC) - timedelta(days=days)
    cond: list = [LlmCall.created_at >= since]
    if ws_id is not None:
        cond.append(LlmCall.workspace_id == ws_id)
    price_of = prices(db)

    total = _dimension(db, cond, [], price_of)[()]

    users = {
        u.id: u
        for u in db.scalars(select(UserAccount).where(UserAccount.id.in_(_user_ids(db, cond))))
    }

    def user_label(uid: uuid.UUID | None) -> dict[str, Any]:
        u = users.get(uid) if uid else None
        if uid is None:
            return {"user_id": None, "name": SYSTEM_LABEL}
        return {"user_id": uid, "name": u.display_name if u else "Deleted user"}

    by_user = [
        {**user_label(k[0]), **v}
        for k, v in sorted(
            _dimension(db, cond, [LlmCall.user_account_id], price_of).items(),
            key=lambda kv: -kv[1]["calls"],
        )
    ]
    by_model = []
    for k, v in sorted(
        _dimension(db, cond, [LlmCall.provider, LlmCall.model], price_of).items(),
        key=lambda kv: -kv[1]["calls"],
    ):
        p = price_of.get((k[0], k[1]))
        by_model.append(
            {
                "provider": k[0],
                "model": k[1],
                "price_set": p is not None,
                "input_per_mtok_eur": float(p.input_per_mtok_eur) if p else None,
                "output_per_mtok_eur": float(p.output_per_mtok_eur) if p else None,
                **v,
            }
        )
    day = _day_expr().label("day")
    by_day = [{"day": k[0], **v} for k, v in sorted(_dimension(db, cond, [day], price_of).items())]
    by_day_user = [
        {"day": k[0], **user_label(k[1]), **v}
        for k, v in sorted(
            _dimension(db, cond, [day, LlmCall.user_account_id], price_of).items(),
            key=lambda kv: (kv[0][0], str(kv[0][1])),
        )
    ]
    by_purpose = [
        {"purpose": k[0], **v}
        for k, v in sorted(
            _dimension(db, cond, [LlmCall.purpose], price_of).items(),
            key=lambda kv: -kv[1]["calls"],
        )
    ]
    out: dict[str, Any] = {
        "days": days,
        "since": since,
        "totals": total,
        "by_user": by_user,
        "by_model": by_model,
        "by_day": by_day,
        "by_day_user": by_day_user,
        "by_purpose": by_purpose,
    }
    if ws_id is None:
        names = {w.id: w for w in db.scalars(select(Workspace))}
        out["by_workspace"] = [
            {
                "workspace_id": k[0],
                "slug": names[k[0]].slug if k[0] in names else None,
                "name": names[k[0]].name if k[0] in names else None,
                **v,
            }
            for k, v in sorted(
                _dimension(db, cond, [LlmCall.workspace_id], price_of).items(),
                key=lambda kv: -kv[1]["calls"],
            )
        ]
    return out


def _user_ids(db: Session, cond: list):
    return (
        select(LlmCall.user_account_id)
        .where(*cond, LlmCall.user_account_id.is_not(None))
        .distinct()
    )


def set_price(
    db: Session,
    provider: str,
    model: str,
    input_per_mtok_eur: float,
    output_per_mtok_eur: float,
    user_id: uuid.UUID | None,
) -> ModelPrice:
    row = db.scalar(
        select(ModelPrice).where(ModelPrice.provider == provider, ModelPrice.model == model)
    )
    values = {
        "input_per_mtok_eur": Decimal(str(input_per_mtok_eur)),
        "output_per_mtok_eur": Decimal(str(output_per_mtok_eur)),
        "updated_by": user_id,
    }
    if row is None:
        row = ModelPrice(provider=provider, model=model, **values)
        db.add(row)
    else:
        for k, v in values.items():
            setattr(row, k, v)
    db.flush()
    return row


def delete_price(db: Session, price_id: uuid.UUID) -> bool:
    row = db.get(ModelPrice, price_id)
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True


__all__ = ["delete_price", "prices", "set_price", "summary"]
