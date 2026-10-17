"""Pure synthetic CRM generator with a known ground truth. No DB, no I/O, no network.

`generate(variant, seed, n_deals)` is deterministic: same arguments, identical output.

Power check (why the planted effects are detectable with the default gates at n_deals=350, i.e.
about 255-265 closed deals; gates: n >= 30, >= 10 wins and >= 10 losses, CI half-width <= 15 pts or
<= 30% relative, Benjamini-Hochberg FDR 5%):

* inbound win rate 70% vs rest ~27%: about 90 closed inbound deals, ~63 wins; Wilson half-width
  ~ +-9 pts (< 15); difference ~43 pts, SE ~ 5.5 pts, z ~ 7, p ~ 1e-10, far below any BH cut-off
  for the ~100 comparisons of a scan. (A 45% vs 30% effect gives z ~ 2.4 even at 350: NOT
  reliably detectable, hence the larger planted effect.) At the former 200 deals: ~55 closed
  inbound, half-width +-12, z ~ 5.5.
* segment -> cycle: medians 110 / 60 / 30 days, log-normal sigma 0.35. The smallest group
  (enterprise, 25% of ~260 closed = ~65) has a median CI of about +-10% (< 30%); the three groups
  are separated by factors 1.8-3.7, i.e. > 10 sigma. (At 200: ~41 closed, +-13%.)
* segment -> amount: medians 60k / 20k / 8k EUR, sigma 0.5; enterprise median CI about +-15%
  (< 30%); factors 2.5-7.5 between groups. (At 200: +-19%.)
* referral (win rate 60%) is capped at 25 closed deals (< 30): it must come out "not verified".
* side effect of the extra power: more real-but-not-required findings (e.g. outbound low) and
  more chances for a chance finding in a null cell; see docs/DECISIONS.md section E.

The unit tests re-check the realised numbers for seed 42.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal

import numpy as np

from app.demo import names as N
from app.demo.models import (
    DemoAccount,
    DemoComment,
    DemoCompany,
    DemoContact,
    DemoDataset,
    DemoDeal,
    DemoNote,
    DemoUser,
)
from app.domain.enums import (
    DealStage,
    Dimension,
    LeadSource,
    Metric,
    RecordSource,
    Segment,
    UserRole,
)
from app.domain.schemas import GroundTruth, PlantedEffect

# Fixed "today" so that the dataset does not depend on the wall clock (determinism).
REFERENCE_DATE = date(2026, 10, 1)
HISTORY_DAYS = 730  # 24 months

N_REPS = 6
MIN_DEALS, MAX_DEALS = 50, 20_000
CLOSED_SHARE = 0.80
MAX_REFERRAL_CLOSED = 25  # keeps the planted small group under the min-n gate of 30

LEAD_MIX: dict[LeadSource, float] = {
    LeadSource.INBOUND: 0.35,
    LeadSource.OUTBOUND: 0.40,
    LeadSource.REFERRAL: 0.15,
    LeadSource.PARTNER: 0.05,
    LeadSource.EVENT: 0.05,
}
SEGMENT_MIX: dict[Segment, float] = {
    Segment.SMB: 0.40,
    Segment.MIDMARKET: 0.35,
    Segment.ENTERPRISE: 0.25,
}

WIN_RATE_PLANTED: dict[LeadSource, float] = {
    LeadSource.INBOUND: 0.70,
    LeadSource.OUTBOUND: 0.12,
    LeadSource.REFERRAL: 0.60,
    LeadSource.PARTNER: 0.30,
    LeadSource.EVENT: 0.30,
}
WIN_RATE_NOISE = 0.30
CYCLE_MEDIAN: dict[Segment, float] = {
    Segment.SMB: 30.0,
    Segment.MIDMARKET: 60.0,
    Segment.ENTERPRISE: 110.0,
}
CYCLE_SIGMA = 0.35
AMOUNT_MEDIAN: dict[Segment, float] = {
    Segment.SMB: 8_000.0,
    Segment.MIDMARKET: 20_000.0,
    Segment.ENTERPRISE: 60_000.0,
}
AMOUNT_SIGMA = 0.5
# Noise variant: one distribution for everybody.
NOISE_CYCLE_MEDIAN, NOISE_CYCLE_SIGMA = 60.0, 0.6
NOISE_AMOUNT_MEDIAN, NOISE_AMOUNT_SIGMA = 20_000.0, 1.0

MISSING_LEAD_SOURCE = 0.08
MISSING_AMOUNT = 0.05
MISSING_CLOSED_ON = 0.03
MISSING_ACCOUNT_FIELD = 0.05
MISSING_TITLE = 0.05
OUTLIER_SHARE = 0.02

DEAL_KINDS = ["Licence", "Renouvellement", "Expansion", "Pilot", "Platform"]


def _quota[T](rng: np.random.Generator, n: int, mix: dict[T, float]) -> list[T]:
    """Exactly-proportioned labels (largest remainder), shuffled."""
    labels = list(mix)
    raw = [mix[k] * n for k in labels]
    counts = [int(x) for x in raw]
    order = sorted(range(len(labels)), key=lambda i: raw[i] - counts[i], reverse=True)
    for i in order[: n - sum(counts)]:
        counts[i] += 1
    out: list[T] = [lab for lab, c in zip(labels, counts, strict=True) for _ in range(c)]
    perm = rng.permutation(len(out))
    return [out[i] for i in perm]


def _balanced_owners(
    rng: np.random.Generator,
    owners: list[str],
    segs: list[Segment],
    leads: list[LeadSource],
) -> list[str]:
    """Owners spread evenly inside every (segment, lead source) cell, so that the owner is
    independent of both drivers (segment -> cycle/amount, lead source -> win rate)."""
    out = [""] * len(segs)
    cells: dict[tuple[Segment, LeadSource], list[int]] = {}
    for i, key in enumerate(zip(segs, leads, strict=True)):
        cells.setdefault(key, []).append(i)
    offset = int(rng.integers(len(owners)))  # carries over so the cell remainders do not pile up
    for key in sorted(cells, key=lambda k: (str(k[0]), str(k[1]))):
        idx = cells[key]
        for j in rng.permutation(len(idx)):
            out[idx[int(j)]] = owners[offset % len(owners)]
            offset += 1
    return out


def _pick[T](rng: np.random.Generator, items: list[T]) -> T:
    return items[int(rng.integers(len(items)))]


def _noisy_title(rng: np.random.Generator, role: str) -> str | None:
    if rng.random() < MISSING_TITLE:
        return None
    title = _pick(rng, N.ROLE_TITLES[role])
    r = rng.random()
    if r < 0.10:
        title = title.upper()
    elif r < 0.20:
        title = title.lower()
    if rng.random() < 0.06 and len(title) > 4:  # typo: swap two adjacent letters
        i = int(rng.integers(1, len(title) - 2))
        title = title[:i] + title[i + 1] + title[i] + title[i + 2 :]
    if rng.random() < 0.05:
        title = f" {title} "
    return title


def _employee_count(rng: np.random.Generator, segment: Segment) -> int:
    if segment is Segment.SMB:
        return int(rng.integers(8, 50))
    if segment is Segment.MIDMARKET:
        return int(rng.integers(50, 1000))
    return int(rng.integers(1000, 20_000))


def _segment_for(n: int) -> Segment:
    return Segment.SMB if n < 50 else Segment.MIDMARKET if n < 1000 else Segment.ENTERPRISE


def _build_accounts(rng: np.random.Generator, n_accounts: int) -> list[DemoAccount]:
    segments = _quota(rng, n_accounts, SEGMENT_MIX)
    used: set[str] = set()
    accounts: list[DemoAccount] = []
    seen_in_segment: dict[Segment, int] = {s: 0 for s in Segment}
    industries = [N.INDUSTRIES[int(j)] for j in rng.permutation(len(N.INDUSTRIES))]
    regions = [N.REGIONS[int(j)] for j in rng.permutation(len(N.REGIONS))]
    for i, seg in enumerate(segments):
        # Balanced within each segment: with ~70 accounts, random industry/region would be
        # accidentally confounded with the segment (which drives cycle and amount).
        k = seen_in_segment[seg]
        seen_in_segment[seg] += 1
        name = f"{_pick(rng, N.COMPANY_PREFIXES)} {_pick(rng, N.COMPANY_SUFFIXES)}"
        if name in used:  # pool exhausted for big datasets: disambiguate
            name = f"{name} {i}"
        used.add(name)
        emp = _employee_count(rng, seg)
        slug = name.lower().replace(" ", "-").replace("é", "e").replace("É", "e")
        accounts.append(
            DemoAccount(
                key=f"acc{i:03d}",
                name=name,
                domain=f"{slug}.example",
                industry=None
                if rng.random() < MISSING_ACCOUNT_FIELD
                else industries[k % len(industries)],
                segment=_segment_for(emp),
                employee_count=emp,
                region=None if rng.random() < MISSING_ACCOUNT_FIELD else regions[k % len(regions)],
                country="FR",
                source=RecordSource.DEMO,
            )
        )
    return accounts


def _build_contacts(rng: np.random.Generator, accounts: list[DemoAccount]) -> list[DemoContact]:
    used: set[str] = set()
    contacts: list[DemoContact] = []
    for acc in accounts:
        k = int(rng.integers(4, 10))  # 4..9
        keys: list[str] = []
        for j, (role, parent) in enumerate(N.ORG_TEMPLATE[:k]):
            full = f"{_pick(rng, N.FIRST_NAMES)} {_pick(rng, N.LAST_NAMES)}"
            if full in used:  # pool exhausted for big datasets: add a middle initial
                full = (
                    f"{full.split(' ', 1)[0]} {chr(65 + len(used) % 26)}. {full.split(' ', 1)[1]}"
                )
                while full in used:
                    full += "x"
            used.add(full)
            key = f"{acc.key}-c{j}"
            keys.append(key)
            contacts.append(
                DemoContact(
                    key=key,
                    account_key=acc.key,
                    full_name=full,
                    title=_noisy_title(rng, role),
                    reports_to_key=None if parent is None else keys[parent],
                )
            )
    return contacts


def _build_notes(
    rng: np.random.Generator,
    contacts: list[DemoContact],
    accounts: list[DemoAccount],
    users: list[DemoUser],
) -> tuple[list[DemoNote], list[DemoComment]]:
    notes: list[DemoNote] = []
    for i in range(40):
        c = _pick(rng, contacts)
        notes.append(
            DemoNote(
                key=f"note{i:03d}",
                contact_key=c.key,
                author_key=_pick(rng, users).key,
                body=_pick(rng, N.NOTE_BODIES),
            )
        )
    for i, idx in enumerate(rng.choice(40, size=4, replace=False)):
        orig = notes[int(idx)]
        notes.append(
            DemoNote(
                key=f"note{40 + i:03d}",
                contact_key=orig.contact_key,
                author_key=orig.author_key,
                body=orig.body + " (corrigé / corrected)",
                corrects_key=orig.key,
            )
        )
    comments: list[DemoComment] = []
    for i in range(18):
        a = _pick(rng, accounts)
        comments.append(
            DemoComment(
                key=f"cmt{i:03d}",
                account_key=a.key,
                author_key=_pick(rng, users).key,
                body=_pick(rng, N.COMMENT_BODIES),
            )
        )
    for i, idx in enumerate(rng.choice(18, size=2, replace=False)):
        orig = comments[int(idx)]
        comments.append(
            DemoComment(
                key=f"cmt{18 + i:03d}",
                account_key=orig.account_key,
                author_key=orig.author_key,
                body=orig.body + " (mis à jour / updated)",
                corrects_key=orig.key,
            )
        )
    return notes, comments


def _ground_truth(
    variant: Literal["planted", "noise"], seed: int, ds_counts: tuple[int, int, int]
) -> GroundTruth:
    n_acc, n_con, n_deals = ds_counts
    if variant == "noise":
        return GroundTruth(
            variant="noise",
            seed=seed,
            n_accounts=n_acc,
            n_contacts=n_con,
            n_deals=n_deals,
            planted=[],
            null_dimensions=list(Dimension),
            null_cells=[(d, m) for d in Dimension for m in Metric],
            small_groups=[],
            notes=[
                "Every metric is independent of every dimension: no verified finding is expected."
            ],
        )
    planted = [
        PlantedEffect(
            dimension=Dimension.LEAD_SOURCE, group="inbound", metric=Metric.WIN_RATE,
            direction="higher", magnitude="+40 pts win rate (70% vs ~27%)",
        ),
        PlantedEffect(
            dimension=Dimension.SEGMENT, group="enterprise", metric=Metric.CYCLE_DAYS,
            direction="higher", magnitude="median ~110 days vs 60 (midmarket) / 30 (smb)",
        ),
        PlantedEffect(
            dimension=Dimension.SEGMENT, group="smb", metric=Metric.CYCLE_DAYS,
            direction="lower", magnitude="median ~30 days",
        ),
        PlantedEffect(
            dimension=Dimension.SEGMENT, group="enterprise", metric=Metric.DEAL_AMOUNT,
            direction="higher", magnitude="median ~60k EUR vs 20k (midmarket) / 8k (smb)",
        ),
        PlantedEffect(
            dimension=Dimension.SEGMENT, group="smb", metric=Metric.DEAL_AMOUNT,
            direction="lower", magnitude="median ~8k EUR",
        ),
    ]  # fmt: skip
    return GroundTruth(
        variant="planted",
        seed=seed,
        n_accounts=n_acc,
        n_contacts=n_con,
        n_deals=n_deals,
        planted=planted,
        null_dimensions=[Dimension.INDUSTRY, Dimension.REGION, Dimension.OWNER],
        # Cells with no planted dependence. Win rate depends on lead source only; cycle and amount
        # on segment only; the amount band is a function of the amount (so it tracks segment:
        # amount_band x cycle_days is NOT null). Industry/region/owner are balanced within segment
        # (owner also within lead source).
        null_cells=[
            (d, m) for d in (Dimension.INDUSTRY, Dimension.REGION, Dimension.OWNER) for m in Metric
        ]
        + [
            (Dimension.SEGMENT, Metric.WIN_RATE),
            (Dimension.LEAD_SOURCE, Metric.CYCLE_DAYS),
            (Dimension.LEAD_SOURCE, Metric.DEAL_AMOUNT),
            (Dimension.AMOUNT_BAND, Metric.WIN_RATE),
        ],
        small_groups=[(Dimension.LEAD_SOURCE, "referral")],
        notes=[
            "outbound win rate is ~12% (low) but not required (win count at the gate edge).",
            "referral win rate is ~60% on fewer than 30 closed deals: must stay 'not verified'.",
            "amount_band is derived from the amount: it tracks segment by construction.",
        ],
    )


def _date_notes(seed: int, notes: list[DemoNote], comments: list[DemoComment]) -> None:
    """Give notes and comments realistic past dates (the year before REFERENCE_DATE), so
    "last interaction" means something. A separate RNG stream: every other row of the dataset
    stays identical to what the seed produced before dates existed."""
    rng = np.random.default_rng([seed, 102])
    end = datetime.combine(REFERENCE_DATE, time(18, 0), tzinfo=UTC)
    for rows in (notes, comments):
        when: dict[str, datetime] = {}
        for row in rows:
            if row.corrects_key is None:
                at = end - timedelta(
                    days=int(rng.integers(1, 365)), minutes=int(rng.integers(0, 600))
                )
            else:  # a correction comes a few days after the version it corrects
                at = min(end, when[row.corrects_key] + timedelta(days=int(rng.integers(1, 15))))
            row.created_at = at
            when[row.key] = at


def _build_companies(seed: int, accounts: list[DemoAccount]) -> tuple[list[DemoCompany], dict]:
    """Group accounts by name family (first word) into companies. A separate RNG stream, so the
    CRM data and the ground truth are identical with or without companies. No SIREN."""
    rng = np.random.default_rng([seed, 101])
    families: dict[str, list[DemoAccount]] = {}
    for a in accounts:
        families.setdefault(a.name.split()[0], []).append(a)
    companies: list[DemoCompany] = []
    link: dict[str, str] = {}
    for i, (word, members) in enumerate(sorted(families.items())):
        city, postal = _pick(rng, N.CITIES)
        number = int(rng.integers(1, 120))
        key = f"co{i:03d}"
        companies.append(
            DemoCompany(
                key=key,
                name=f"{word} {_pick(rng, N.LEGAL_FORMS)}",
                address_line=f"{number} {_pick(rng, N.STREETS)}",
                postal_code=postal,
                city=city,
            )
        )
        for a in members:
            link[a.key] = key
    return companies, link


def generate(variant: Literal["planted", "noise"], seed: int, n_deals: int = 350) -> DemoDataset:
    if variant not in ("planted", "noise"):
        raise ValueError(f"unknown variant {variant!r}")
    if not MIN_DEALS <= n_deals <= MAX_DEALS:
        raise ValueError(f"n_deals must be between {MIN_DEALS} and {MAX_DEALS}, got {n_deals}")
    rng = np.random.default_rng(seed)
    planted = variant == "planted"

    users = [
        DemoUser(
            key=f"rep{i}",
            display_name=f"{_pick(rng, N.FIRST_NAMES)} {N.LAST_NAMES[i * 5 % len(N.LAST_NAMES)]}",
            email=f"rep{i}@demo.example",
            role=UserRole.ADMIN if i == 0 else UserRole.USER,
        )
        for i in range(N_REPS)
    ]
    accounts = _build_accounts(rng, max(12, round(n_deals * 0.35)))
    contacts = _build_contacts(rng, accounts)
    notes, comments = _build_notes(rng, contacts, accounts, users)

    by_segment: dict[Segment, list[DemoAccount]] = {s: [] for s in Segment}
    for a in accounts:
        assert a.segment is not None
        by_segment[a.segment].append(a)

    seg_of_deal = _quota(rng, n_deals, SEGMENT_MIX)
    lead_of_deal = _quota(rng, n_deals, LEAD_MIX)
    owner_of_deal = _balanced_owners(rng, [u.key for u in users], seg_of_deal, lead_of_deal)
    closed = [bool(rng.random() < CLOSED_SHARE) for _ in range(n_deals)]
    # Guard: the planted small group must stay under the min-n gate.
    ref_closed = [i for i in range(n_deals) if closed[i] and lead_of_deal[i] is LeadSource.REFERRAL]
    for i in ref_closed[MAX_REFERRAL_CLOSED:]:
        closed[i] = False

    deals: list[DemoDeal] = []
    next_in_seg = {s: int(rng.integers(0, 1000)) for s in Segment}
    for i in range(n_deals):
        seg, lead = seg_of_deal[i], lead_of_deal[i]
        # always draw the same random numbers so both variants consume the stream alike
        u_win, u_miss_lead, u_miss_amt, u_miss_close, u_out = (rng.random() for _ in range(5))
        z_cycle, z_amount = float(rng.normal()), float(rng.normal())
        if planted:
            p_win = WIN_RATE_PLANTED[lead]
            cycle = CYCLE_MEDIAN[seg] * float(np.exp(CYCLE_SIGMA * z_cycle))
            amount = AMOUNT_MEDIAN[seg] * float(np.exp(AMOUNT_SIGMA * z_amount))
        else:
            p_win = WIN_RATE_NOISE
            cycle = NOISE_CYCLE_MEDIAN * float(np.exp(NOISE_CYCLE_SIGMA * z_cycle))
            amount = NOISE_AMOUNT_MEDIAN * float(np.exp(NOISE_AMOUNT_SIGMA * z_amount))
        if u_out < OUTLIER_SHARE:
            amount *= 5
        cycle_days = min(HISTORY_DAYS, max(3, round(cycle)))  # fits the history window
        pool = by_segment[seg] or accounts
        account = pool[next_in_seg[seg] % len(pool)]
        next_in_seg[seg] += 1

        if closed[i]:
            won = u_win < p_win
            stage = DealStage.CLOSED_WON if won else DealStage.CLOSED_LOST
            days_ago = int(rng.integers(cycle_days, HISTORY_DAYS + 1))
            created = REFERENCE_DATE - timedelta(days=days_ago)
            closed_on: date | None = created + timedelta(days=cycle_days)
            if u_miss_close < MISSING_CLOSED_ON:
                closed_on = None
            lost_reason = None if won else _pick(rng, N.LOST_REASONS)
        else:
            stage = DealStage(
                _pick(rng, ["prospecting", "qualification", "proposal", "negotiation"])
            )
            created = REFERENCE_DATE - timedelta(days=int(rng.integers(0, 200)))
            closed_on, lost_reason = None, None

        deals.append(
            DemoDeal(
                key=f"deal{i:04d}",
                account_key=account.key,
                owner_key=owner_of_deal[i],
                name=f"{account.name} - {_pick(rng, DEAL_KINDS)}",
                amount_eur=None
                if u_miss_amt < MISSING_AMOUNT
                else Decimal(f"{round(amount, 2):.2f}"),
                stage=stage,
                lead_source=None if u_miss_lead < MISSING_LEAD_SOURCE else lead,
                created_on=created,
                closed_on=closed_on,
                lost_reason=lost_reason,
            )
        )

    truth = _ground_truth(variant, seed, (len(accounts), len(contacts), len(deals)))
    companies, account_company = _build_companies(seed, accounts)
    _date_notes(seed, notes, comments)
    return DemoDataset(
        users=users, accounts=accounts, contacts=contacts, deals=deals, notes=notes,
        comments=comments, ground_truth=truth, companies=companies,
        account_company=account_company,
    )  # fmt: skip
