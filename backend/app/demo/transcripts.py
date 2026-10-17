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
ORG_STATEMENT_SHARE = 0.55  # of contacts with a removed link whose account has meetings
HIT_WEIGHT = 2.5
N_DECOYS = 5
SIGNAL_P = {"champion": 0.30, "blocker": 0.15, "decision_maker": 0.25}

THEME_TEXT: dict[str, dict[str, list[str]]] = {
    "price_objection": {
        "fr": [
            "Honnêtement, votre offre est trop chère par rapport à ce que nous avions prévu.",
            "Le prix reste un sujet : pouvez-vous faire une remise sur la première année ?",
            "Notre budget est limité, il faudrait revoir le prix à la baisse.",
            "Pour {n} utilisateurs, le tarif me paraît trop élevé, c'est trop cher.",
            "Quel est le coût total sur trois ans avec {n} licences ?",
            "Une réduction de volume est-elle possible si nous prenons {n} postes ?",
            "Le budget alloué à ce projet ne couvre pas le tarif que vous proposez.",
            "Votre concurrent est moins cher, pouvez-vous améliorer votre prix ?",
            "Le coût par utilisateur pose problème à notre direction financière.",
            "Nous attendons une remise plus importante avant de signer.",
            "Le tarif du module {mod} est trop cher pour ce que nous en ferons.",
        ],
        "en": [
            "Frankly, the pricing is too expensive compared with what we had planned.",
            "Price is still an issue: could you offer a discount on the first year?",
            "Our budget is tight, so the pricing would need to come down.",
            "For {n} users the cost looks too high, it is simply too expensive.",
            "What is the total cost over three years with {n} seats?",
            "Is a volume discount possible if we take {n} licences?",
            "The budget set aside for this project does not cover your pricing.",
            "Another vendor is cheaper, can you improve your price?",
            "The per-seat cost is a problem for our finance director.",
            "We need a bigger discount before we can sign anything.",
            "The price of the {mod} add-on is too expensive for what we would use.",
        ],
    },
    "integration_need": {
        "fr": [
            "Il nous faut une intégration native avec Salesforce, sinon ce sera compliqué.",
            "Est-ce que votre API et le connecteur HubSpot sont disponibles aujourd'hui ?",
            "Nous voulons une sync automatique avec notre CRM via l'API.",
            "Le connecteur Salesforce couvre-t-il les objets personnalisés de notre CRM ?",
            "Notre équipe {team} exige une intégration avec HubSpot avant tout déploiement.",
            "Comment fonctionne la synchronisation bidirectionnelle des contacts avec l'API ?",
            "Nous avons besoin d'un connecteur pour notre ERP, est-ce prévu ?",
            "La sync avec Salesforce se fait-elle en temps réel ou par lots ?",
            "Pouvez-vous documenter l'API pour que nos développeurs préparent l'intégration ?",
            "Sans connecteur HubSpot, {n} utilisateurs devront ressaisir leurs données.",
        ],
        "en": [
            "We need a native integration with Salesforce, otherwise it will be hard.",
            "Are your API and the HubSpot connector available today?",
            "We want an automatic sync with our CRM through the API.",
            "Does the Salesforce connector cover the custom objects in our CRM?",
            "Our {team} team requires an integration with HubSpot before any rollout.",
            "How does the two-way contact sync work through the API?",
            "We need a connector for our ERP, is that on the roadmap?",
            "Is the Salesforce sync real time or batch?",
            "Could you document the API so our developers can prepare the integration?",
            "Without a HubSpot connector, {n} users would have to re-enter their data.",
        ],
    },
    "security_gdpr": {
        "fr": [
            "Notre DPO demande des garanties RGPD sur l'hébergement des données.",
            "La sécurité est essentielle : avez-vous un rapport SOC 2 ?",
            "Où se fait l'hébergement et comment gérez-vous le RGPD ?",
            "Les données doivent rester hébergées en Europe, c'est une exigence de sécurité.",
            "Pouvez-vous nous transmettre votre certification SOC 2 et votre politique RGPD ?",
            "Notre RSSI veut auditer la sécurité de la plateforme avant le déploiement.",
            "Le chiffrement des données et la sécurité des accès sont-ils conformes au RGPD ?",
            "Avec {n} utilisateurs, nous devons une conformité RGPD irréprochable.",
            "Quel est le niveau d'hébergement proposé et où sont situés les serveurs ?",
            "Nous remplissons un questionnaire de sécurité fournisseur, pouvez-vous le compléter ?",
        ],
        "en": [
            "Our DPO wants GDPR guarantees about where the data is hosted.",
            "Security is essential for us: do you have a SOC 2 report?",
            "Where does the hosting happen and how do you handle GDPR?",
            "The data must stay hosted in Europe, it is a security requirement.",
            "Can you send us your SOC 2 certification and your GDPR policy?",
            "Our CISO wants to audit the platform security before the rollout.",
            "Are data encryption and access security compliant with GDPR?",
            "With {n} users, our GDPR compliance has to be flawless.",
            "What hosting options do you offer and where are the servers located?",
            "We are filling in a vendor security questionnaire, can you complete it?",
        ],
    },
    "competitor_vendara": {
        "fr": [
            "Nous regardons aussi Vendara, qui nous a fait une démonstration la semaine dernière.",
            "Vendara propose une offre similaire, comment vous différenciez-vous ?",
            "Un de nos collègues préfère Vendara pour son interface.",
            "Qu'avez-vous de mieux que Vendara sur le module {mod} ?",
            "Vendara nous a promis une mise en route rapide, qu'en est-il chez vous ?",
            "Nous avons comparé votre solution à Vendara et l'écart est mince.",
            "L'équipe {team} a déjà testé Vendara pendant deux semaines.",
            "Vendara est présent dans notre secteur depuis longtemps, que répondez-vous ?",
        ],
        "en": [
            "We are also looking at Vendara, who gave us a demo last week.",
            "Vendara has a similar offer, how do you differentiate yourselves?",
            "One of our colleagues prefers Vendara for its interface.",
            "What do you do better than Vendara on the {mod}?",
            "Vendara promised us a quick start, how does that compare with you?",
            "We compared your solution with Vendara and the gap is small.",
            "The {team} team already trialled Vendara for two weeks.",
            "Vendara has been in our industry for a long time, what is your answer?",
        ],
    },
    "timing_freeze": {
        "fr": [
            "Il y a un gel des budgets chez nous, donc pas avant le prochain trimestre.",
            "Le gel des budgets nous empêche d'avancer, ce sera pas avant le prochain trimestre.",
            "Avec le gel des budgets décidé par la direction, tout est suspendu.",
            "Nous ne pourrons rien signer, pas avant le prochain trimestre au mieux.",
            "Le gel des budgets touche aussi l'équipe {team}, il faudra patienter.",
            "Reparlons-en après le gel des budgets, pas avant le prochain trimestre.",
            "Le projet est décalé : gel des budgets jusqu'à nouvel ordre.",
            "Tant que le gel des budgets dure, nous ne lancerons pas {n} licences.",
        ],
        "en": [
            "We have a budget freeze, so nothing can happen before next quarter.",
            "The budget freeze blocks us for now, let's talk again next quarter.",
            "With the budget freeze announced by management, everything is on hold.",
            "We cannot sign anything, not before next quarter at best.",
            "The budget freeze also hits the {team} team, so we will have to wait.",
            "Let's pick this up after the budget freeze, probably next quarter.",
            "The project is pushed back: budget freeze until further notice.",
            "As long as the budget freeze lasts, we will not launch {n} licences.",
        ],
    },
}

_DAYS = {
    "fr": ["lundi", "mardi", "mercredi", "jeudi", "vendredi"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
}
_MONTHS = {
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "septembre", "octobre"],
    "en": ["January", "February", "March", "April", "May", "June", "September", "October"],
}
_TEAMS = {
    "fr": ["commerciale", "support", "finance", "RH", "logistique", "marketing", "data", "achats"],
    "en": ["sales", "support", "finance", "HR", "logistics", "marketing", "data", "procurement"],
}
_MODULES = {
    "fr": [
        "tableau de bord",
        "module de reporting",
        "éditeur de workflows",
        "calendrier partagé",
        "application mobile",
        "moteur de relances",
        "gestion des contacts",
        "assistant de saisie",
    ],
    "en": [
        "home overview",
        "reporting module",
        "workflow editor",
        "shared calendar",
        "mobile app",
        "reminder engine",
        "contact manager",
        "data entry assistant",
    ],
}
_CITIES = [
    "Lyon",
    "Lille",
    "Nantes",
    "Bordeaux",
    "Toulouse",
    "Strasbourg",
    "Londres",
    "Dublin",
    "Berlin",
    "Madrid",
    "Boston",
    "Austin",
]
_VERBS = {
    "fr": ["tester", "présenter", "valider", "documenter", "planifier", "partager", "relire"],
    "en": ["test", "present", "validate", "document", "plan", "share", "review"],
}
_OBJECTS = {
    "fr": [
        "la maquette",
        "le plan de déploiement",
        "la liste des participants",
        "le calendrier",
        "le compte rendu",
        "la démonstration",
        "le périmètre du pilote",
        "le support de formation",
    ],
    "en": [
        "the mockup",
        "the rollout plan",
        "the attendee list",
        "the schedule",
        "the minutes",
        "the demo",
        "the pilot scope",
        "the training material",
    ],
}

# Slot-filled neutral templates: {day} {date} {team} {mod} {n} {city} {verb} {obj}.
NEUTRAL_REP = {
    "fr": [
        "Bonjour à tous, merci d'avoir pris le temps de nous retrouver {day}.",
        "Bonjour, ravi de vous voir, nous avons une heure devant nous.",
        "Je propose de commencer par l'ordre du jour de notre rendez-vous.",
        "Au programme : un tour du {mod}, vos questions, puis les prochaines étapes.",
        "Je vous montre le {mod}, tel qu'il est utilisé par l'équipe {team} d'un client.",
        "Dans la démo, je vais {verb} {obj} avec vous.",
        "Pour vos {n} utilisateurs, nous pouvons démarrer par un pilote à {city}.",
        "Très bien, je note vos remarques et je vous envoie un compte rendu {day}.",
        "Merci pour ces précisions, cela m'aide à préparer {obj}.",
        "Parfait, nous convenons d'un prochain point le {date}.",
        "Je reviens vers vous {day} avec {obj}.",
        "Nous pouvons organiser une session de formation à {city} pour l'équipe {team}.",
        "Le {mod} est disponible dès la première semaine de déploiement.",
        "Je partage mon écran pour {verb} {obj} ensemble.",
        "Je vous propose une visio le {date} pour {verb} {obj}.",
    ],
    "en": [
        "Hello everyone, thank you for making the time on {day}.",
        "Hi all, good to see you, we have an hour together.",
        "Let me start with the agenda for today's meeting.",
        "On the agenda: a tour of the {mod}, your questions, then next steps.",
        "I will show you the {mod}, as used by the {team} team of another customer.",
        "During the demo, I will {verb} {obj} with you.",
        "For your {n} users, we could begin with a pilot in {city}.",
        "Great, I will note your remarks and send a written summary on {day}.",
        "Thanks for the details, that helps me prepare {obj}.",
        "Perfect, let's agree on a follow-up call on {date}.",
        "I will come back to you on {day} with {obj}.",
        "We can run a training session in {city} for the {team} team.",
        "The {mod} is available from the first week of the rollout.",
        "Let me share my screen so we can {verb} {obj} together.",
        "I suggest a video call on {date} to {verb} {obj}.",
    ],
}
NEUTRAL_CONTACT = {
    "fr": [
        "Bonjour, merci pour l'invitation.",
        "Bonjour à tous, content d'être là {day}.",
        "Oui, c'est bien noté de notre côté.",
        "D'accord, pouvez-vous nous renvoyer {obj} après la réunion ?",
        "Très bien, nous reviendrons vers vous avec nos questions d'ici {day}.",
        "Merci, à la semaine prochaine alors, ou le {date} si cela vous convient.",
        "Le {mod} a l'air clair, l'équipe {team} devrait s'y retrouver.",
        "Nous sommes environ {n} personnes à {city} concernées par ce sujet.",
        "Pouvez-vous nous montrer le {mod} sur un cas concret ?",
        "Je vais {verb} {obj} avec mes collègues de l'équipe {team}.",
        "Combien de temps faut-il pour former {n} personnes au {mod} ?",
        "Notre site de {city} pourrait servir de pilote.",
        "Est-ce que le {mod} fonctionne aussi sur mobile ?",
        "Nous avons un comité interne le {date}, je vous tiens au courant.",
        "Pouvez-vous nous envoyer {obj} avant {day} ?",
        "C'est intéressant, surtout pour l'équipe {team}.",
        "Qui sera notre interlocuteur après la signature ?",
        "Nous pourrions {verb} {obj} la semaine prochaine.",
    ],
    "en": [
        "Hello, thanks for the invitation.",
        "Hi everyone, glad to be here on {day}.",
        "Yes, that is noted on our side.",
        "Okay, could you send us {obj} after the meeting?",
        "Sounds good, we will come back to you with our questions by {day}.",
        "Thanks, see you next week then, or on {date} if that suits you.",
        "The {mod} looks clear, the {team} team should find their way around it.",
        "About {n} people in {city} are concerned by this topic.",
        "Could you show us the {mod} on a real case?",
        "I will {verb} {obj} with my colleagues in the {team} team.",
        "How long does it take to train {n} people on the {mod}?",
        "Our {city} office could serve as the pilot.",
        "Does the {mod} also work on mobile?",
        "We have an internal committee on {date}, I will keep you posted.",
        "Could you send us {obj} before {day}?",
        "That is interesting, especially for the {team} team.",
        "Who will be our contact after signature?",
        "We could {verb} {obj} next week.",
    ],
}


_TAILS = {
    "fr": [
        " d'ici le {date}",
        " pour l'équipe {team}",
        " côté {city}",
        " avec nos {n} utilisateurs",
        " dès {day}",
        " autour du {mod}",
        " pour le {date}",
        " si possible avant {day}",
    ],
    "en": [
        " by {date}",
        " for the {team} team",
        " on the {city} side",
        " with our {n} users",
        " from {day}",
        " around the {mod}",
        " for {date}",
        " ideally before {day}",
    ],
}


def _neutral(rng: np.random.Generator, table: dict[str, list[str]], lang: str) -> str:
    """One neutral sentence from slot-filled templates."""
    template = _pick(rng, table[lang])
    if rng.random() < 0.75:
        template = template[:-1] + _pick(rng, _TAILS[lang]) + template[-1]
    return template.format(
        day=_pick(rng, _DAYS[lang]),
        date=_date_text(rng, lang),
        team=_pick(rng, _TEAMS[lang]),
        mod=_pick(rng, _MODULES[lang]),
        n=int(rng.integers(6, 2000)),
        city=_pick(rng, _CITIES),
        verb=_pick(rng, _VERBS[lang]),
        obj=_pick(rng, _OBJECTS[lang]),
    )


def _date_text(rng: np.random.Generator, lang: str) -> str:
    day, month = int(rng.integers(1, 29)), _pick(rng, _MONTHS[lang])
    return f"{day} {month}" if lang == "fr" else f"{month} {day}"


def _themed(rng: np.random.Generator, theme: str, lang: str) -> str:
    return _pick(rng, THEME_TEXT[theme][lang]).format(
        n=int(rng.integers(8, 480)),
        team=_pick(rng, _TEAMS[lang]),
        mod=_pick(rng, _MODULES[lang]),
    )


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
        free = [i for i in slots if i not in placed] or slots  # avoid gluing when possible
        placed.setdefault(_pick(rng, free), []).append(sentence)
    lines: list[str] = []
    for i in range(n_turns):
        if i % 2 == 0:
            parts = [_neutral(rng, NEUTRAL_REP, m.lang) for _ in range(int(rng.integers(1, 3)))]
            lines.append(f"{rep}: {' '.join(parts)}")
        else:
            who = names[m.speakers[(i // 2) % len(m.speakers)]]
            sentences = list(placed.get(i, []))
            n_extra = int(rng.integers(1, 3)) if not sentences else int(rng.integers(0, 2))
            sentences += [_neutral(rng, NEUTRAL_CONTACT, m.lang) for _ in range(n_extra)]
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
    # Accounts with removed links are favoured so that more org statements can be placed.
    hit = {c.account_key for c in contacts if c.key in removed}

    def _sample(pool: list[DemoDeal], size: int) -> list[DemoDeal]:
        w = np.array([HIT_WEIGHT if d.account_key in hit else 1.0 for d in pool])
        return [
            pool[int(i)] for i in rng.choice(len(pool), size=size, replace=False, p=w / w.sum())
        ]

    chosen = _sample(closed, n_closed)
    if n_open:
        chosen += _sample(opened, n_open)
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
                m.payloads.append((None, _themed(rng, theme, m.lang)))
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
