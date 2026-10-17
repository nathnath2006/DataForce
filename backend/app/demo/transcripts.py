"""Synthetic meeting transcripts with planted themes, org statements and signals (M2b).

Pure and deterministic. Uses its own RNG stream (`[seed, 104]`) and never touches the CRM rows.
Transcript format: one turn per line, `Name: text`.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from app.demo.models import DemoAccount, DemoContact, DemoDeal, DemoDocument, DemoUser
from app.domain.enums import DealStage, Segment
from app.domain.schemas import MeetingTruth

THEME_IDS = [
    "price_objection",
    "integration_need",
    "security_gdpr",
    "competitor_vendara",
    "timing_freeze",
]

N_MEETINGS = 160  # at 350 deals; scaled with n_deals
CLOSED_SHARE = 0.85
FRENCH_SHARE = 0.60
PRICE_LOST, PRICE_OTHER = 0.65, 0.20
SECURITY_ENTERPRISE, SECURITY_OTHER = 0.50, 0.25
THEME_OTHER_P = {"integration_need": 0.30, "competitor_vendara": 0.20, "timing_freeze": 0.15}
ORG_STATEMENT_SHARE = 0.40
N_DECOYS = 5
SIGNAL_P = {"champion": 0.30, "blocker": 0.15, "decision_maker": 0.25}

THEME_TEXT: dict[str, dict[str, list[str]]] = {
    "price_objection": {
        "fr": [
            "Honnêtement, votre offre est trop chère par rapport à ce que nous avions prévu.",
            "Le prix reste un sujet : pouvez-vous faire une remise sur la première année ?",
            "Notre budget est limité, il faudrait revoir le prix à la baisse.",
            "Avec ce prix, c'est trop cher pour nous, une remise serait nécessaire.",
        ],
        "en": [
            "Frankly, the pricing is too expensive compared with what we had planned.",
            "Price is still an issue: could you offer a discount on the first year?",
            "Our budget is tight, so the pricing would need to come down.",
            "At this price it is too expensive for us, a discount would be needed.",
        ],
    },
    "integration_need": {
        "fr": [
            "Il nous faut une intégration native avec Salesforce, sinon ce sera compliqué.",
            "Est-ce que votre API et le connecteur HubSpot sont disponibles aujourd'hui ?",
            "Nous voulons une sync automatique avec notre CRM via l'API.",
        ],
        "en": [
            "We need a native integration with Salesforce, otherwise it will be hard.",
            "Are your API and the HubSpot connector available today?",
            "We want an automatic sync with our CRM through the API.",
        ],
    },
    "security_gdpr": {
        "fr": [
            "Notre DPO demande des garanties RGPD sur l'hébergement des données.",
            "La sécurité est essentielle : avez-vous un rapport SOC 2 ?",
            "Où se fait l'hébergement et comment gérez-vous le RGPD ?",
        ],
        "en": [
            "Our DPO wants GDPR guarantees about where the data is hosted.",
            "Security is essential for us: do you have a SOC 2 report?",
            "Where does the hosting happen and how do you handle GDPR?",
        ],
    },
    "competitor_vendara": {
        "fr": [
            "Nous regardons aussi Vendara, qui nous a fait une démonstration la semaine dernière.",
            "Vendara propose une offre similaire, comment vous différenciez-vous ?",
        ],
        "en": [
            "We are also looking at Vendara, who gave us a demo last week.",
            "Vendara has a similar offer, how do you differentiate yourselves?",
        ],
    },
    "timing_freeze": {
        "fr": [
            "Il y a un gel des budgets chez nous, donc pas avant le prochain trimestre.",
            "Le gel des budgets nous empêche d'avancer, ce sera pas avant le prochain trimestre.",
        ],
        "en": [
            "We have a budget freeze, so nothing can happen before next quarter.",
            "The budget freeze blocks us for now, let's talk again next quarter.",
        ],
    },
}

NEUTRAL_REP = {
    "fr": [
        "Bonjour à tous, merci d'avoir pris le temps de nous retrouver.",
        "Je propose de commencer par l'ordre du jour de notre rendez-vous.",
        "Très bien, je note vos remarques et je vous envoie un compte rendu.",
        "Merci pour ces précisions, cela m'aide beaucoup.",
        "Parfait, nous convenons d'un prochain point la semaine prochaine.",
    ],
    "en": [
        "Hello everyone, thank you for making the time.",
        "Let me start with the agenda for today's meeting.",
        "Great, I will note your remarks and send a written summary.",
        "Thanks for the details, that helps a lot.",
        "Perfect, let's agree on a follow-up call next week.",
    ],
}
NEUTRAL_CONTACT = {
    "fr": [
        "Bonjour, merci pour l'invitation.",
        "Oui, c'est bien noté de notre côté.",
        "D'accord, pouvez-vous nous renvoyer les documents après la réunion ?",
        "Très bien, nous reviendrons vers vous avec nos questions.",
        "Merci, à la semaine prochaine alors.",
    ],
    "en": [
        "Hello, thanks for the invitation.",
        "Yes, that is noted on our side.",
        "Okay, could you send us the documents after the meeting?",
        "Sounds good, we will come back to you with our questions.",
        "Thanks, see you next week then.",
    ],
}
MEETING_TITLES = {
    "fr": ["Point d'avancement", "Démonstration", "Réunion de cadrage", "Revue de proposition"],
    "en": ["Progress check-in", "Product demo", "Scoping meeting", "Proposal review"],
}

# Sentences matching the M2b extraction patterns exactly (docs/M2B-CONTRACT.md section 4).
ORG_SENTENCE = {
    "fr": ["Je reporte à {n}.", "Mon manager est {n}.", "{n} est mon n+1."],
    "en": ["I report to {n}.", "My manager is {n}.", "{n} is my boss."],
}
DECOY_SENTENCE = {
    "fr": "Je suis sous la responsabilité du conseil d'administration.",
    "en": "I report to our board of directors.",
}
CHAMPION_SENTENCE = {
    "fr": [
        "Je vais porter le projet en interne.",
        "Je vais pousser le dossier auprès de la direction.",
    ],
    "en": ["I'll champion this internally.", "I'll push this with the leadership team."],
}
BLOCKER_SENTENCE = {
    "fr": ["{n} est contre.", "{n} n'est pas convaincu."],
    "en": ["{n} is against.", "{n} is not convinced."],
}
DECISION_SENTENCE = {
    "fr": ["Au final, c'est {n} qui décide.", "En pratique, c'est {n} qui valide."],
    "en": ["In practice, {n} makes the final decision.", "In the end, {n} will make the call."],
}


def _pick[T](rng: np.random.Generator, items: list[T]) -> T:
    return items[int(rng.integers(len(items)))]


class _Meeting:
    def __init__(self, idx: int, deal: DemoDeal, lang: str, speakers: list[str], when: date):
        self.idx = idx
        self.deal = deal
        self.lang = lang
        self.speakers = speakers  # contact keys, 1..3
        self.required: set[str] = set()
        self.when = when
        self.themes: list[str] = []
        self.payloads: list[tuple[str | None, str]] = []  # (contact key | None, sentence)
        self.org: list[tuple[str, str]] = []
        self.signals: list[tuple[str, str]] = []


def _ensure_speaker(m: _Meeting, key: str, rng: np.random.Generator) -> bool:
    if key in m.speakers:
        m.required.add(key)
        return True
    if len(m.speakers) < 3:
        m.speakers.append(key)
    else:
        free = [i for i, s in enumerate(m.speakers) if s not in m.required]
        if not free:
            return False
        m.speakers[_pick(rng, free)] = key
    m.required.add(key)
    return True


def _render(m: _Meeting, rng: np.random.Generator, rep: str, names: dict[str, str]) -> str:
    n_turns = int(rng.integers(6, 17))
    odd = list(range(1, n_turns, 2))
    placed: dict[int, list[str]] = {}
    for speaker, sentence in m.payloads:
        if speaker is None:
            slots = odd
        else:
            slots = [i for i in odd if m.speakers[(i // 2) % len(m.speakers)] == speaker]
        placed.setdefault(_pick(rng, slots), []).append(sentence)
    lines: list[str] = []
    for i in range(n_turns):
        if i % 2 == 0:
            text = NEUTRAL_REP[m.lang][0] if i == 0 else _pick(rng, NEUTRAL_REP[m.lang])
            lines.append(f"{rep}: {text}")
        else:
            who = names[m.speakers[(i // 2) % len(m.speakers)]]
            sentences = placed.get(i) or [_pick(rng, NEUTRAL_CONTACT[m.lang])]
            lines.append(f"{who}: {' '.join(sentences)}")
    return "\n".join(lines) + "\n"


def build_transcripts(
    seed: int,
    *,
    users: list[DemoUser],
    accounts: list[DemoAccount],
    contacts: list[DemoContact],
    deals: list[DemoDeal],
    org: dict[str, str | None],
    removed: set[str],
    reference_date: date,
) -> tuple[list[DemoDocument], list[MeetingTruth], list[str]]:
    """Returns (documents, per-meeting truth, decoy document keys)."""
    rng = np.random.default_rng([seed, 104])
    seg_of = {a.key: a.segment for a in accounts}
    by_acc: dict[str, list[DemoContact]] = {}
    for c in contacts:
        by_acc.setdefault(c.account_key, []).append(c)
    name_of = {c.key: c.full_name for c in contacts}
    rep_name = {u.key: u.display_name for u in users}

    n_target = min(len(deals), round(N_MEETINGS * len(deals) / 350))
    closed = [d for d in deals if d.stage in (DealStage.CLOSED_WON, DealStage.CLOSED_LOST)]
    opened = [d for d in deals if d not in closed]
    n_closed = min(len(closed), round(n_target * CLOSED_SHARE))
    n_open = min(len(opened), n_target - n_closed)
    chosen = [closed[int(i)] for i in rng.choice(len(closed), size=n_closed, replace=False)]
    if n_open:
        chosen += [opened[int(i)] for i in rng.choice(len(opened), size=n_open, replace=False)]
    chosen.sort(key=lambda d: d.key)

    langs = ["fr"] * round(FRENCH_SHARE * len(chosen))
    langs += ["en"] * (len(chosen) - len(langs))
    langs = [langs[int(i)] for i in rng.permutation(len(langs))]

    # Exact-proportion quotas for the two effects that must be measurable.
    def _quota_flags(group: list[int], p: float) -> set[int]:
        take = round(p * len(group))
        return {group[int(i)] for i in rng.permutation(len(group))[:take]}

    lost_idx = [i for i, d in enumerate(chosen) if d.stage is DealStage.CLOSED_LOST]
    other_idx = [i for i in range(len(chosen)) if i not in set(lost_idx)]
    price_set = _quota_flags(lost_idx, PRICE_LOST) | _quota_flags(other_idx, PRICE_OTHER)
    ent_idx = [i for i, d in enumerate(chosen) if seg_of[d.account_key] is Segment.ENTERPRISE]
    non_ent = [i for i in range(len(chosen)) if i not in set(ent_idx)]
    security_set = _quota_flags(ent_idx, SECURITY_ENTERPRISE) | _quota_flags(
        non_ent, SECURITY_OTHER
    )

    meetings: list[_Meeting] = []
    for idx, deal in enumerate(chosen):
        pool = by_acc[deal.account_key]
        k = min(len(pool), int(rng.integers(1, 4)))
        speakers = [pool[int(i)].key for i in rng.choice(len(pool), size=k, replace=False)]
        end = deal.closed_on or reference_date
        span = max(0, (end - deal.created_on).days)
        when = deal.created_on + timedelta(days=int(rng.integers(0, span + 1)))
        m = _Meeting(idx, deal, langs[idx], speakers, when)
        flags = {
            "price_objection": idx in price_set,
            "security_gdpr": idx in security_set,
        }
        for theme in THEME_IDS:  # fixed order and fixed draws
            u = rng.random()
            if flags.get(theme, u < THEME_OTHER_P.get(theme, 0.0)):
                m.themes.append(theme)
                m.payloads.append((None, _pick(rng, THEME_TEXT[theme][m.lang])))
        meetings.append(m)

    by_account: dict[str, list[_Meeting]] = {}
    for m in meetings:
        by_account.setdefault(m.deal.account_key, []).append(m)

    # Org statements: about 40% of the contacts whose manual link was removed.
    for acc_key in sorted(by_account):
        for c in by_acc[acc_key]:
            if c.key not in removed or rng.random() >= ORG_STATEMENT_SHARE:
                continue
            manager = org[c.key]
            assert manager is not None
            options = by_account[acc_key]
            m = options[int(rng.integers(len(options)))]
            if _ensure_speaker(m, c.key, rng):
                sentence = _pick(rng, ORG_SENTENCE[m.lang]).format(n=name_of[manager])
                m.payloads.append((c.key, sentence))
                m.org.append((c.key, manager))

    # Signals, per account with meetings.
    for acc_key in sorted(by_account):
        pool = by_acc[acc_key]
        for kind in ("champion", "blocker", "decision_maker"):
            if rng.random() >= SIGNAL_P[kind]:
                continue
            m = by_account[acc_key][int(rng.integers(len(by_account[acc_key])))]
            target = pool[int(rng.integers(len(pool)))]
            if kind == "champion":
                if not _ensure_speaker(m, target.key, rng):
                    continue
                m.payloads.append((target.key, _pick(rng, CHAMPION_SENTENCE[m.lang])))
            else:
                table = BLOCKER_SENTENCE if kind == "blocker" else DECISION_SENTENCE
                m.payloads.append((None, _pick(rng, table[m.lang]).format(n=target.full_name)))
            m.signals.append((target.key, kind))

    decoys: list[str] = []
    for i in rng.choice(len(meetings), size=min(N_DECOYS, len(meetings)), replace=False):
        m = meetings[int(i)]
        m.payloads.append((None, DECOY_SENTENCE[m.lang]))
        decoys.append(f"doc{m.idx:03d}")

    docs: list[DemoDocument] = []
    truth: list[MeetingTruth] = []
    for m in meetings:
        rep = rep_name[m.deal.owner_key] if m.deal.owner_key else users[0].display_name
        docs.append(
            DemoDocument(
                key=f"doc{m.idx:03d}",
                account_key=m.deal.account_key,
                deal_key=m.deal.key,
                title=f"{_pick(rng, MEETING_TITLES[m.lang])} - {m.deal.name}",
                text=_render(m, rng, rep, name_of),
                meeting_date=m.when,
                language=m.lang,
            )
        )
        truth.append(
            MeetingTruth(
                document_key=f"doc{m.idx:03d}",
                account_key=m.deal.account_key,
                deal_key=m.deal.key,
                themes=m.themes,
                org_statements=m.org,
                signals=m.signals,
            )
        )
    return docs, truth, sorted(decoys)
