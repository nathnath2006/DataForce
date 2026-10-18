# M2b independent methods review

Reviewer: independent, read-only. No application code or database was changed. Scripts and data: `/private/tmp/claude-501/-Users-a1234-Documents-GitHub/09ecc94a-9687-4eaa-8fb7-441ce6fde086/scratchpad/methods/` (`titles_test.py`, `themes_data.py`, `themes_test.py`, `org_test.py`, `meet_test.py`). Wilson 95 % CIs from `app.stats.intervals.wilson`. All labels are my own; they are judgement calls and a few are debatable.

## Verdicts

| Method | Verdict |
|---|---|
| Titles (dictionary) | Ratified with caveats |
| Org-chart rules | Ratified with caveats |
| Meeting statements | Ratified with caveats (precision claim not generalisable; recall is the honest number) |
| Themes, known lexicon | Not ratified as an accuracy claim. Usable only as "keyword hits, exploratory", and the demo F1 must not be quoted as generalisable |
| Themes, discovered (NMF) | Not tested here (no held-out labels). Ratified only as "exploratory" |

## 1. Titles, held-out

153 titles after removing 26 of my 179 that were in `ROLE_TITLES` (so the set is truly held out). 127 are in the taxonomy; 24 are out-of-taxonomy (legal, customer success, project, design...); 2 are deliberately ambiguous.

| Measure | Result |
|---|---|
| Function accuracy, all 153 (out-of-taxonomy and ambiguous count as right when the dictionary abstains) | 116/153 = 75.8 % [68.5, 81.9] |
| Seniority accuracy, all 153 | 132/153 = 86.3 % [79.9, 90.8] |
| In-taxonomy function accuracy | 90/127 = 70.9 % [62.4, 78.1] |
| Unknown function (flagged "unknown title") | 63/153 = 41 % |
| Coverage in-taxonomy (answered) | 90/127 = 70.9 % |
| Function accuracy when it answers | 90/90 = 100 % [95.9, 100] |
| Seniority accuracy when it answers | 87/90 = 96.7 % [90.7, 98.9] |
| Confident-wrong function | 0 of 153 (no out-of-taxonomy title got a function) |
| Flag rate | 63/153 = 41 % (every unknown is flagged) |

So the demo 99.6 % does not generalise as a coverage figure: roughly 30 % of real in-taxonomy titles fall to the AI or to "unknown". It does generalise as precision: when the dictionary answers it is almost always right and it abstains rather than guesses. That is the right failure mode.

Gaps found (all abstain, none wrong):
- Spelled-out "Chief Financial Officer", "Chief Revenue Officer", "Chief Product Officer", "Chief Information Security Officer" are unknown, though "CFO" and "Chief Marketing Officer" work. Only the CMO and CEO spellings were in the demo. "CRO" is unknown.
- Missing vocabulary: product (Product Manager/Owner/Head of Product, Directeur Produit), purchasing (Acheteur, Buyer, Procurement, Achats), Trésorier, Paie, Solutions Engineer, Community Manager, SEO, Demand Generation, Sales Ops, Scrum Master, Country Manager, Directeur Régional, Directeur de Compte, Chargé de Clientèle, Directeur d'Usine/de Site, Responsable Informatique, Ingénieur Logiciel, Responsable Partenariats (my labels; `Head of Product` as "tech" is arguable).
- Seniority errors when answered (3 of 90): "Directrice des Ressources Humaines" gives c_level (the `drh` rule overreaches to the spelled-out form; it is a Head), "Account Manager"/"Key Account Manager" give manager (I labelled individual; contract says `manager` keyword wins), "Country Manager France" gives manager.
- Seniority is returned even where the function is unknown (e.g. "Chargé de Clientèle" unknown/individual path); fine.

## 2. Themes (known lexicon), held-out

225 sentences I wrote without reading the demo templates: 161 theme sentences (about 20 per theme) and 64 neutral or tricky. Sentence level, one sentence per call to `match_known`. Note: competitor-name detection (Vendara, Acme) needs at least 3 documents, so it cannot fire on a single sentence; the competitor recall below therefore understates the corpus-level behaviour for named competitors.

| Theme | TP | FP | FN | Precision [95 % CI] | Recall [95 % CI] |
|---|---|---|---|---|---|
| price | 11 | 6 | 10 | 0.65 [0.41, 0.83] | 0.52 [0.32, 0.72] |
| competitor | 9 | 2 | 11 | 0.82 [0.52, 0.95] | 0.45 [0.26, 0.66] |
| security | 13 | 2 | 7 | 0.87 [0.62, 0.96] | 0.65 [0.43, 0.82] |
| integration | 14 | 4 | 6 | 0.78 [0.55, 0.91] | 0.70 [0.48, 0.85] |
| timing | 7 | 2 | 13 | 0.78 [0.45, 0.94] | 0.35 [0.18, 0.57] |
| legal | 9 | 3 | 11 | 0.75 [0.47, 0.91] | 0.45 [0.26, 0.66] |
| onboarding | 8 | 1 | 12 | 0.89 [0.57, 0.98] | 0.40 [0.22, 0.61] |
| support | 7 | 4 | 13 | 0.64 [0.35, 0.85] | 0.35 [0.18, 0.57] |

Neutral sentences: 19 of 64 triggered a theme = 29.7 % [19.9, 41.8]. The neutral set is adversarial by design (lexical traps), so this is an upper bound, not a field rate. False positives: "Budget meeting", "Le coût de la vie", "expensive-looking suit", "cost-averaged", "budget photo" (price); "integration of the two companies", "intégration de stagiaires" (explicitly in the brief), "Import of coffee", "exporter ce fichier en PDF" (integration); "I support your decision", "support de présentation" (support); "compétition en athlétisme", "competitive football" (competitor); "contrat de travail", "legal background" (legal); "sécurité routière", "secure building" (security); "timeline LinkedIn", "delay on the train" (timing).

Sentences carrying any known theme that were caught at all: 81/161 = 50 %. Typical misses are paraphrase without keywords ("the licence fees are steep", "Le devis dépasse", "Where are the servers located?", "Revenez vers nous dans six mois", "Will you train our staff", "Do you have a help centre").

Conclusion: the 0.82 to 0.98 demo F1 values are demo-vocabulary figures. On independently written sentences F1 is roughly 0.4 to 0.7 per theme, driven by recall of 35 to 70 %. Precision of 65 to 89 % with wide CIs. Keyword themes are a lower bound of mentions with known false positives; the UI wording ("found by matching sales keywords") is correct, but an accuracy number should not be quoted. Because misses are not random (a prospect who objects politely on price may use none of the keywords), the "mentioned" flag is a noisy exposure, which biases any theme-vs-outcome association towards zero but is not a safe one-sided bias if reps' phrasing differs between won and lost deals.

## 3. Org rules, 10 hand-built charts

Manager-link decisions over 39 non-root contacts (root and externals not counted):

| Outcome | Count |
|---|---|
| Correct (proposes the true manager) | 23 |
| Wrong (confident, wrong manager) | 3 |
| Ambiguous, true manager among candidates | 2 |
| Abstain | 11 |

Wrong cases, all rank-based structural assumptions:
- Chart 8 (skip level): a Sales Director who really reports to the CEO is sent to the VP Sales above them (R2). The rule cannot know; plausible in real orgs with co-existing VP and Director.
- Chart 9 (flat IT): engineers and an analyst reporting to a DSI are sent to the Tech Lead (manager) instead (R2 nearest level above).

Correct and abstain behaviour checked: two heads of sales give ambiguity (not a guess) for the AE and SDR below them; a COO with ops reports resolves; matrix organisation resolves by function; no CEO gives abstain for the top sales head and a chain for the rest; two executive c-levels (co-founder + CEO) give no root and all dependents abstain; unknown-title contacts abstain (Head of Product, Product Manager, Customer Success); a flat SMB with no one above abstains for everyone. The rules abstain rather than guess where they have no signal, but they do guess whenever a unique person of higher rank exists in the same function, even when the real manager is elsewhere. Precision on my charts: 23/26 = 88.5 % [71.0, 96.0] of confident proposals; recall 23/39 = 59.0 % [43.4, 72.9]. Demo 95 % precision / 81 % recall is consistent with demo structure (a clean function ladder) and is optimistic for real orgs. Since all proposals need user acceptance, this is acceptable.

Meeting statements, 40 hand-written paraphrases and traps (qualitative, not for CIs): the regexes hit the canonical phrases and nothing else. Missed paraphrases: "I report directly to Paul", "I'm reporting to Paul", "Je dépends de Paul", "Je suis rattachée à Paul", "Paul has the final say", "I'm going to sponsor this". False positives: "If I report to Paul, he will say no", "I'll push it to Friday" / "I'll push this button" (champion), "Je vais porter ça à la direction" (champion), "Paul has the decision letter". Negations tested ("I don't report to Paul", "Paul is not against it", "Paul n'est pas contre") were correctly not extracted. Precision 100 % on the demo is a property of the templates; recall 44 % is honest and likely higher than reality on spontaneous speech. Signals are proposals only, which contains the risk.

## 4. Claims audit

| Place | Finding |
|---|---|
| `MeetingsPage.tsx` known theme tag and text | OK: "known theme, found by keywords", "A mention is not a cause". |
| Discovered topics | OK: "Exploratory ... Topics describe, they do not prove". Contract §7.2 required it on every card. |
| Titles AI | OK: `llm` source shows a warn badge and the flag "classified by AI (confidence X): check". |
| `DECISIONS.md` L262-264 table | OVERSTATES: quotes 99.6 %, 99.7 %, 95 %, 81 %, 100 %, 44 % with no statement that they are measured on the synthetic demo whose vocabulary the dictionary and lexicon were tuned on, and `ROLE_TITLES` is both the training source and the test. Should say "on synthetic demo, in-sample". |
| Theme F1 claims (0.82 to 0.98) | Same problem; not generalisable (see section 2). |
| Template "Themes vs win rate" | Wording describes an association; UI must keep "A mention is not a cause" near the result, not only on the theme card. The result table in Flows is generic and will show p, q and "verified" status without that caveat. |
| `deal_theme_flags` description in contract | Does not say mentions are customer-side keywords. |
| Contract title taxonomy | Contract promises "executive ... president" etc. but coverage of common titles is about 70 %; the UI toolbar rightly says unknown go to AI. |

## 5. Statistics

- `deal_theme_flags` (`app/flows/sources/crm.py` L399-436): `mentioned = case((has_meeting, assigned), else_=None)`. A deal with no meeting yields null, not False. Confirmed. `has_meeting` is also exposed. The stats block drops rows with a missing group or outcome and reports `excluded_missing` (blocks/stats.py L180). OK.
- Double counting: `assigned` is an `EXISTS`, so a deal with several meetings still gives one row per (deal, theme). Not double-counted. But a deal with more meetings has more chances to mention a theme; lost deals in the demo are given more... unchecked here; in real data meetings-per-deal is a confounder (longer sales cycles, bigger deals). Not controlled.
- Only customer-side chunks are used by default (`speakers: customer`), and only if the speaker matched a contact; unmatched speakers drop out silently, so exposure is under-measured and differs by transcript format.
- The theme is discovered (or keyword-selected) on the same deals, then tested against outcome on the same deals. This is exploratory selection; the p-value is not valid as a confirmatory test. No caveat is shown.
- Multiple testing: each theme is a separate flow with its own `stats` block. BH inside a block covers only that block's groups (two: mentioned true and false, which are mirror images of one comparison). There is no correction across 8 known plus about 8 discovered themes. With 16 themes, about 0.8 false positives at alpha 0.05 are expected.
- Selection of closed deals only is correct (open deals have unknown outcomes), but note meetings dated near close can be caused by the outcome (reverse timing): a late "pricing" call may follow a decision to lose.

## 6. Issues

| # | Severity | Issue | Fix |
|---|---|---|---|
| 1 | should-fix | Accuracy claims in `DECISIONS.md` L262-264 and the build report are in-sample on the demo and read as general. | Rewrite as "synthetic demo, in-sample; held-out (docs/review/M2b-methods-review.md): titles 71 % coverage / 100 % precision when answering; themes recall 35 to 70 %, precision 64 to 89 %". Never quote F1 in product UI. |
| 2 | should-fix | Title coverage: "Chief Financial Officer"/"Chief Revenue/Product/Information Security Officer", "CRO", product, purchasing, treasury and common sales variants are unknown. | Add a generic `chief ... officer` rule (function by the middle word, seniority c_level), add `product`, `purchasing/achats/procurement/buyer`, `tresorier`, `country manager`, `directeur regional`. Add a held-out title fixture to `tests/titles` to prevent regression. |
| 3 | should-fix | "Directrice des Ressources Humaines" gives c_level (drh rule) but is a Head. Account Manager gives manager. | Limit c_level to the abbreviation `drh`/`daf`/`dsi` forms unless "directeur general"; make `account manager` individual. Decide and document. |
| 4 | should-fix | Known-theme lexicon false positives on neutral words: "integration" (HR), "support" (verb/slide), "coût de la vie", "competitive", "legal background", "budget meeting". | Document the miss/FP trade-off, and show the matched keyword and sentence on every hit (excerpts already do). Consider requiring a theme to appear in 2 or more chunks of a document before counting it as mentioned. |
| 5 | should-fix | Theme-vs-win-rate flow shows p, q and verified status without exploratory or multiple-testing context. | Show a banner on any flow built from `deal_theme_flags`: "theme chosen from the same data; each theme tested separately, no correction across themes; association, not cause". Optionally add an "all themes" flow (group_by theme) so BH covers the full set. |
| 6 | should-fix | Meetings-per-deal and customer-only speaker matching are uncontrolled exposure confounders. | Expose `n_meetings` in `deal_theme_flags` so users can filter or adjust; warn when unmatched speakers exceed a share. |
| 7 | note | `stats` with a two-level `mentioned` compares each group to the rest; the two rows are mirror images and q is computed on two tests. | Report one comparison for binary groups. |
| 8 | note | Org rules R2/R3 guess a unique higher rank in function (skip-levels, flat teams give wrong proposals). They are proposals needing acceptance, so acceptable. | Keep wording "suggested". Optionally lower confidence when the manager is two ranks above. |
| 9 | note | Meeting regexes are narrow and a few false positives exist (conditional "If I report to", "I'll push it to Friday"). | Keep as proposals; add negative-context tests; add paraphrase patterns only with tests. |
| 10 | note | Competitor-name detection needs at least 3 documents; recall on small sets is limited by design. | Document. |
| 11 | note | Discovered NMF topics were not evaluated here (no labelled data). | Treated as exploratory only. |

No blockers. The M2b UI wording is largely honest; the exposure is in documentation figures and the missing exploratory/multiplicity caveat on the flow result.
