"""Flatten a DemoDataset into stats-engine rows without any DB (tests, notebooks, quick checks)."""

from __future__ import annotations

from app.demo.models import DemoDataset
from app.stats.rows import DealRow, won_from_stage


def deal_rows(ds: DemoDataset) -> list[DealRow]:
    acc = {a.key: a for a in ds.accounts}
    rows: list[DealRow] = []
    for d in ds.deals:
        a = acc[d.account_key]
        rows.append(
            DealRow(
                id=d.key,
                won=won_from_stage(d.stage),
                stage=str(d.stage),
                lead_source=None if d.lead_source is None else str(d.lead_source),
                segment=None if a.segment is None else str(a.segment),
                industry=a.industry,
                region=a.region,
                owner=d.owner_key,
                amount=None if d.amount_eur is None else float(d.amount_eur),
                created_on=d.created_on,
                closed_on=d.closed_on,
            )
        )
    return rows
