# ruff: noqa: E501
"""Invented names and titles for the synthetic dataset. Nothing here refers to real people or
companies: surnames are fabricated, company names are made-up compounds, domains use the reserved
`.example` TLD."""

from __future__ import annotations

FIRST_NAMES = [
    "Aurélien", "Maëlle", "Corentin", "Soline", "Basile", "Océane", "Gaspard", "Liora", "Tiphaine",
    "Evrard", "Noémie", "Quentin", "Axelle", "Valère", "Mireille", "Anselme", "Clémence", "Roxane",
    "Odilon", "Jade", "Harriet", "Dexter", "Marlowe", "Ingrid", "Thaddeus", "Wilhelmina", "Bryce",
    "Philippa", "Rowan", "Tabitha", "Lachlan", "Imogen", "Fenwick", "Odette", "Callum", "Rosalind",
]  # fmt: skip

LAST_NAMES = [
    "Valmorin", "Casterel", "Brouvenne", "Dalmasse", "Ferrandaz", "Montbelair", "Quercival", "Tessendre",
    "Lavandrier", "Moriceau-Daul", "Hautecourt", "Sarrenac", "Pellegrand", "Roussevel", "Ankerwood",
    "Thistlegrove", "Bramwell-Ode", "Holloway-Finch", "Merriwick", "Oakenshaw", "Penhallow", "Strathmoor",
    "Wexcombe", "Ardenvale", "Calderwick", "Dunsmoor", "Eastlowe", "Fairbourne", "Greywell", "Hartlemoor",
]  # fmt: skip

COMPANY_PREFIXES = [
    "Valtrio", "Norvane", "Lumeris", "Cobaltis", "Axiora", "Brevena", "Kestrial", "Orvalis", "Planeta",
    "Syndrome", "Tervion", "Ulmaris", "Vestal", "Wavira", "Zephiro", "Alderon", "Belmira", "Cendrix",
    "Dorvane", "Elysor", "Fabrion", "Gravina", "Helvora", "Ixelis", "Jovance", "Kalmera", "Lorvik",
    "Mendara", "Nivelle", "Opaline",
]  # fmt: skip

COMPANY_SUFFIXES = [
    "Systèmes", "Conseil", "Industries", "Logistique", "Digital", "Group", "Labs", "Solutions",
    "Partners", "Énergie", "Santé", "Retail", "Capital", "Technologies",
]  # fmt: skip

INDUSTRIES = [
    "software", "manufacturing", "retail", "finance", "healthcare", "logistics", "energy", "consulting",
]  # fmt: skip

REGIONS = [
    "Île-de-France", "Auvergne-Rhône-Alpes", "Occitanie", "Nouvelle-Aquitaine", "Hauts-de-France",
    "Provence-Alpes-Côte d'Azur", "Grand Est",
]  # fmt: skip

# role -> (parent role, title variants mixing French and English)
ROLE_TITLES: dict[str, list[str]] = {
    "ceo": ["PDG", "Directeur Général", "CEO", "Chief Executive Officer", "Managing Director", "DG"],
    "vp_sales": [
        "Directeur commercial", "Dir. commercial", "VP Sales", "Vice President Sales",
        "Directrice des ventes", "Sales Director",
    ],
    "cmo": ["Directrice marketing", "CMO", "Chief Marketing Officer", "Dir. marketing", "Marketing Director"],
    "cfo": ["DAF", "Directeur administratif et financier", "CFO", "Finance Director", "Dir. financier"],
    "head_sales": ["Responsable des ventes", "Resp. commercial", "Head of Sales", "Sales Manager"],
    "ae": [
        "Account Executive", "Commercial grands comptes", "Ingénieur d'affaires", "Business Developer",
        "Chargé d'affaires",
    ],
    "sdr": ["SDR", "Sales Development Rep", "Business Developer Junior", "Assistant commercial"],
    "marketing": ["Resp. marketing", "Marketing Manager", "Chargée de communication", "Content Manager"],
    "ops": ["Responsable des opérations", "Operations Manager", "Resp. logistique", "Resp. opérations"],
}  # fmt: skip

# Org chart template: (role, index of the parent in this list). A parent always precedes its child,
# so taking the first k entries (k in 4..9) always gives a tree with a single root (the CEO).
ORG_TEMPLATE: list[tuple[str, int | None]] = [
    ("ceo", None),
    ("vp_sales", 0),
    ("cmo", 0),
    ("head_sales", 1),
    ("ae", 3),
    ("cfo", 0),
    ("sdr", 3),
    ("marketing", 2),
    ("ops", 5),
]

NOTE_BODIES = [
    "Premier échange : intéressé par une démo, à relancer après le comité.",
    "Met us at the trade show, wants pricing for the mid-size plan.",
    "Décideur final sur le budget, très sensible au délai de mise en oeuvre.",
    "Prefers email over calls. Follow up next Tuesday.",
    "Contact technique, valide l'intégration avec leur ERP.",
    "Champion interne, pousse le dossier auprès de la direction.",
    "Left a voicemail, no reply yet.",
    "Souhaite une référence client dans le même secteur.",
    "Asked for a security questionnaire before the proposal.",
    "Changement de poste récent, à reconfirmer.",
]  # fmt: skip

COMMENT_BODIES = [
    "Compte stratégique pour le trimestre, priorité haute.",
    "Budget gelé jusqu'en janvier, on garde le contact.",
    "Competitor already in place, renewal in 6 months.",
    "Appel d'offres prévu au printemps.",
    "Good fit for the enterprise plan, legal review pending.",
    "Réorganisation en cours côté client, interlocuteurs à confirmer.",
]  # fmt: skip

LOST_REASONS = [
    "prix",
    "concurrent",
    "pas de budget",
    "timing",
    "no decision",
    "went with competitor",
]

LEGAL_FORMS = ["SAS", "SARL", "SA", "SAS", "SASU"]

# Real French cities with their main postal code; the streets below are invented.
CITIES = [
    ("Paris", "75008"), ("Lyon", "69002"), ("Marseille", "13001"), ("Toulouse", "31000"),
    ("Nantes", "44000"), ("Bordeaux", "33000"), ("Lille", "59000"), ("Strasbourg", "67000"),
    ("Rennes", "35000"), ("Montpellier", "34000"), ("Grenoble", "38000"), ("Dijon", "21000"),
]  # fmt: skip

STREETS = [
    "rue des Tilleuls Fictifs", "avenue du Test", "boulevard de l'Exemple", "rue de la Maquette",
    "impasse des Données", "quai de l'Échantillon", "rue du Prototype", "place de la Démo",
]  # fmt: skip
