# DataForce decision log

Every choice behind the build, with its reason. **[PO]** marks a decision made by the product
owner. **[build]** marks one made by the tech lead during the build. **[assumption]** marks
something that still needs confirming.

## 0. Pivot (2026-10-17) [PO]
- **Why:** TamTam has far better data sources than we could build, which makes the lookalike tool (v1) redundant. TamTam doesn't operate at the CRM level, and that's where we can add value.
- **New concept:** DataForce, an analysis workspace for sales and marketing teams. They analyse their data in the tool instead of exporting it. It sits on a minimal CRM: accounts, contacts, deals, notes and comments.
- **Sources:**
  - CRM data entered in the tool;
  - TamTam through a connector (read inside the ecosystem; paid enrichment only on an explicit click; a fake provider by default);
  - meeting transcripts imported by the rep as PDF or MD. There is no recording in v1, and MP3 needs a transcription step later.
- **Analyses:**
  - deal statistics with confidence intervals and "not verified" gates;
  - meeting themes and objections, counted in code and named by the LLM with quoted excerpts;
  - an account org chart built from meetings and contacts. It's first-hand (champion, blocker), which complements TamTam's public signals.
- **"AI friendly"** means an access layer (MCP + API) whose tools return exact results (SQL aggregates). RAG is used only for free text (notes, transcripts).
- **v1 code [PO]:**
  - Deleted: the crawler, the SIRENE and Wikidata connectors, the website resolver, lookalike scoring and the leave-one-out eval. The v1 security review of the crawler (SR1) went with them.
  - Kept: the infra, the hardened config and DB session, the services pattern, the LLM layer and the TamTam MCP client.
- **Name [PO]:** DataForce. The folder `tamtam-lookalike` was renamed `DataForce`.

## A. Rules kept from v1 [PO]
| # | Rule | Why |
|---|---|---|
| A1 | The LLM never calculates. It only explains computed facts and cites them. | Numbers must be reproducible and auditable. |
| A2 | Not enough evidence means **"not verified"**, shown with the reasons. It's never presented as a fact. | Trust: a salesperson must be able to rely on what is shown. |
| A3 | An org-chart link always keeps its source excerpt. Nothing is inferred without proof. | Same as A2. |
| A4 | The stack doesn't change: FastAPI + React/TS, PostgreSQL + pgvector, one services layer, a swappable LLM interface, auth, secrets in env, admin. | Continuity. |

## B. CRM scope [PO]
- **In:**
  - accounts;
  - contacts (title + "reports to");
  - deals;
  - notes (on a person) and comments (on a company);
  - imported documents (transcripts as PDF or MD, M2).
- **Out of v1:** custom pipelines, drag-and-drop/Kanban, activities and tasks, custom fields, CSV import.
- **Notes and comments are append-only [PO, 2026-10-17].** A correction is a new line that points at the line it corrects, and a delete is a soft delete. A database trigger enforces this, so it holds even if application code has a bug. The one exception is GDPR erasure of a person or company: it hard-deletes their notes through an explicit "erasure" flag **[build]**. The right to erasure takes precedence over the history.
- **Third-party personal data is kept to a strict minimum:** name, title, company and source. There's no email or phone, and deletion is one click. **[PO]**
- **Every table carries a `workspace_id` [build].** One workspace holds one team's data, and each demo dataset is its own workspace. The tool can then be opened to TamTam clients later without a schema rewrite, and the planted and noise datasets can live side by side.
- **Fixed pipeline stages [build]:** prospecting → qualification → proposal → negotiation → closed won / closed lost.

## C. Org chart (M2) [PO]
- A link can have 3 origins, each shown differently:
  - **manual** "reports to": certain, drawn as a solid line;
  - **rule** (same company + normalised titles): dashed, labelled "inferred by rule" with the rule and both titles shown;
  - **meeting** (proposed from a transcript, with the quoted excerpt).
- A rule or meeting link is never shown as fact until a user validates it.
- **Titles** are normalised to a function plus a seniority level using an FR/EN dictionary. An unknown title is classified once by the LLM, then cached and flagged.
- **Ambiguous cases** (several heads, several levels) are never guessed: the contact is linked to the function group, or the case is flagged.
- The M1 schema already has `title_function`, `title_seniority` and `reports_to_id`, and the database refuses self-links. The services refuse cycles **[build]**.

## D. Stats engine (M1)
| # | Decision | Why |
|---|---|---|
| D1 | Metrics: **win rate** (closed deals), **cycle length** (median days from creation to close, for closed deals with both dates) and **deal amount** (median EUR). **[build]** | These are the questions a sales manager asks first. Medians resist outliers. |
| D2 | Dimensions: lead source, segment, industry, region, owner (the rep) and amount band. **[build]** | These are the attributes the minimal CRM holds. |
| D3 | 95% CIs: **Wilson** for rates, **Newcombe's hybrid score** for rate differences, **percentile bootstrap** (2,000 resamples, seeded) for medians and median differences. **[PO, defaults]** | Wilson and Newcombe are reliable at small n. The bootstrap makes no distribution assumption. |
| D4 | **"Not verified" gates [PO, 2026-10-17]:** a group stat fails when n < 30 deals, or for a win rate when wins < 10 or losses < 10, or when the CI half-width exceeds ±15 points (rates) or ±30% of the estimate (medians). Every failure gives a reason. All thresholds are in config. | Avoids presenting small-sample noise as insight. |
| D5 | **Comparisons are group vs rest:** Fisher's exact test (rates) and Mann-Whitney U (cycle and amount), with **Benjamini-Hochberg FDR at 5%** across the whole scan. A finding is verified only when both sides pass the gates, q < 0.05 and the CI of the difference excludes 0. **[PO, defaults]** | A scan runs dozens of tests. Without FDR control it would "find" effects in pure noise. |
| D6 | Missing values are counted and excluded per dimension. "(missing)" is never a group. **[build]** | Missingness is a data-quality fact, not a segment. |
| D7 | "Not verified" ≠ "no effect". The report says so. **[build]** | So a gate isn't read as a negative result. |
| D8 | Exact aggregates (counts and sums by stage) come from SQL, with no CI. **[build]** | These are facts. The AI access layer returns them as they are. |
| D9 | "Both sides pass the gates" (D5) includes the CI-width gate on the group **and** on the rest. Each failure is labelled "group:" or "rest:". **[build, from the stats ratification]** | The first version only checked sample sizes on the two sides, which was looser than D5. |
| D10 | Rows are validated once before any analysis. Duplicate deals are counted once. A close date before the creation date is excluded from the cycle, but the win or loss still counts. A negative or non-finite amount counts as missing. Every exclusion is counted in the report. Gates fail closed on any NaN or infinite value, and thresholds are validated, so a NaN threshold is refused. **[build, from security review SR5]** | Bad data must never turn into a "verified" finding. Repeating the same rows four times used to produce one. |

## E. Synthetic demo data [PO]
- **Synthetic with a known ground truth, announced as such in the README and the notebook:**
  - 350 deals with planted effects (decided by the PO; the first build used 200);
  - companies with full org charts;
  - realistic noise and missing values;
  - FR and EN titles.
- **The engine must find what was planted AND answer "not verified" on a pure-noise variant.**
- **Planted effects [build]:**
  - lead source → win rate (inbound about 70%, outbound about 12%, partner/event about 30%);
  - segment → cycle length (median about 30 / 60 / 110 days for SMB / mid-market / enterprise);
  - segment → deal amount (median about 8k / 20k / 60k EUR, plus 2% outliers at ×5);
  - a **small group** (referral, high win rate but capped at 25 closed deals, under the 30 gate) that must stay "not verified".
- **Effect sizes were raised during the build [build, 2026-10-17].**
  - The first draft had inbound at 45% against a rest of about 30%. At about 170 closed deals that gap is not detectable (z ≈ 1.9 before FDR correction).
  - We raised the effect size and left the gates you approved unchanged.
  - The seed-42 dataset has 200 deals, 168 of them closed. Inbound is 32 wins out of 54 (59%), with raw Fisher p ≈ 0.0035, and it is still verified after BH. Outbound has 9 wins, so the "≥ 10 wins" gate stops it.
- **Null dimensions** (no effect anywhere): industry, region, owner.
  - Industry and region are balanced within each segment. With about 70 accounts, a random draw can otherwise correlate them with segment, and some seeds showed a false positive on a "null" dimension.
- **The answer key lists every "null cell" [build, after the stats ratification].**
  - A null cell is a (dimension, metric) pair where the generator plants no dependence, e.g. industry × anything, or segment × win rate.
  - A verified finding is a false positive if it sits in a null cell, on a small group, or on a planted group in the wrong direction.
  - Other verified findings are real side effects of the planted ones. Examples: the outbound win rate is lower because inbound is higher; small deals close faster because SMB does. They are listed apart, never counted as errors and never silently dropped.
  - The first checker only looked at the null dimensions, so it missed most false positives.
- **Measured reliability at 350 deals [build, 2026-10-17, PO decision: 350 deals instead of 200]:**
  - One 100-seed sweep per variant, seeds 1000-1099, 500 bootstrap resamples, in memory (no database). About 254 deals are closed on average.
  - Detection of each planted effect: 100% for all five (inbound win rate, enterprise and SMB cycle, enterprise and SMB amount). No planted dataset missed an effect.
  - Planted datasets with a false positive (null cell, wrong direction or small group): 8%. Causes: segment x win rate 4, lead source x cycle or amount 2, owner x cycle 1, region x cycle 1, inbound x amount 1 (one dataset had two).
  - Planted datasets where the check fails: 8%. All of them are these false positives; none is a miss. The referral small group was never verified.
  - Noise datasets with any verified finding: 4%.
  - Every planted dataset also shows real side findings that are not required (for example outbound win rate low); they are listed, never counted as errors.
  - **How to read it.** More data removed the misses but did not remove chance findings: with more real effects verified per scan, BH at 5% FDR lets through an occasional spurious one. The engine can still be wrong, in both directions; it never claims otherwise.
  - Seed 42, the dev-database demo: planted passes (5 of 5 found, 4 side findings, referral not verified). Noise seed 42 is one of the 4%: it shows one spurious verified finding (owner rep4 x cycle days, q = 0.028). It is kept as an honest example; a test pins it.
  - The committed tests assert these rates on 50 fixed seeds (1000-1049: 4 false-positive datasets, 4 failed checks, 2 noisy), so they are deterministic and never flaky.
- **Previously, at 200 deals [build, 2026-10-17, after the fix pass]:**
  - Two independent 100-seed sweeps (seeds 1000-1099 and 3000-3099, 500 resamples): inbound win rate 93-96%; enterprise and SMB cycle 99-100%; enterprise and SMB amount 97-99%; planted datasets with a false positive 0-1%; planted datasets where the check fails 8-10% (almost all a missed inbound effect, about 55 closed inbound deals); noise datasets with any verified finding 1%.
  - Seed 42 had 168 closed deals; inbound 32 wins of 54 (59%), raw Fisher p about 0.0035, verified after BH.
  - An earlier draft of this section claimed "about 3%". That came from a lenient checker and was corrected.
- A public dataset may come later, for the stats part only.

## F. Technical choices kept from v1 [build]
- **F1:** sync SQLAlchemy 2.0 + psycopg3, with async only for network I/O.
- **F2:** local Docker `pgvector/pgvector:pg16` pinned by digest and bound to 127.0.0.1:5433. Supabase (EU) for the hosted demo, used as plain Postgres.
- **F3:** Gemini is the main LLM and Anthropic the swap proof, behind one `generate_structured` interface. Fake providers are the default in tests and demos.
- **F4:** config hardening:
  - TLS is required for remote DBs;
  - dev credentials are refused outside dev;
  - token endpoints must use https;
  - an open `.env` is an error outside dev;
  - DB statement and lock timeouts.
- **F5:** RLS on every table, with no access for Supabase's public API roles.
- **F6:** hashed lock files (pip-compile).
- **F7:** the TamTam MCP client:
  - remote HTTP + OAuth bearer at `api.tamtam.ai/mcp`;
  - tool names discovered at runtime from an allow-list;
  - a paid guard with a per-call credit ceiling;
  - credit costs (mobile ≈ 10, email ≈ 1) are an **[assumption]** taken from the brief.

## G. Build order (about 3 weeks, adjusted to real time) [PO]
- **M1 (week 1):** the synthetic generator, the minimal CRM schema and services, and the stats engine with gates, shown in a notebook.
- **M2 (week 2):** title normalisation and org-chart rules; transcript import (PDF/MD) and theme analysis with quoted excerpts.
- **M3 (week 3):** a minimal React UI, the MCP server, the TamTam connector (fake by default), auth and the demo.
- If time runs out, cut meeting analysis first. Keep the org chart, because it complements TamTam. The UI or the TamTam connector come next.

## H. M1b: local UI and TamTam connect (2026-10-17) [PO + build]
- **The PO tests the CRM in a web UI [PO].** Part of the M3 UI was pulled forward: the CRM screens, a
  read-only analysis page and a settings page. Spec and ownership: `docs/UI-CONTRACT.md`.
- **TamTam is connected from the UI over MCP [PO].** No token is copied by hand. TamTam publishes
  standard MCP OAuth metadata (checked 2026-10-17): authorization server `https://api.tamtam.ai`,
  dynamic client registration, PKCE S256, public client, refresh tokens. "Connect TamTam" runs that
  flow; *Check connection* lists the tools the server really offers (this replaces our guess of
  the tool list).
- **Local only, no login before M3 [build].** The app listens on 127.0.0.1 and refuses other
  bind addresses. Another website cannot drive it: Host allow-list (DNS rebinding), an allowed
  Origin plus a custom header on every change, JSON-only bodies, a strict CSP. Any program already
  running on the computer can use it; login and hosting come with M3.
- **One TamTam connection per workspace [build].** It matches the multi-tenant model (a workspace
  is a team). Demo workspaces never use TamTam: their people are fictional, so enrichment there is
  always the fake provider and spends nothing. To try TamTam, the PO creates a real workspace.
- **Secrets at rest [build].** Tokens, the PKCE verifier and enriched emails / mobiles are sealed
  with a Fernet key (`DATAFORCE_SECRET_KEY`), which `make ui` writes into `backend/.env` (0600) and
  never prints. Losing the key means reconnecting TamTam and losing stored enriched values; there is
  no key rotation yet.
- **Enriched contact data [PO rule, build detail].** The `contact` row stays at the strict minimum.
  An email / mobile exists only after an explicit, confirmed (paid) click, in a separate
  `contact_channel` table, sealed, with a one-click delete; erasing the contact deletes it. The
  server refuses a paid lookup above the credit estimate the user accepted, while another lookup for
  the same contact is running, or for a value already stored.
- **Demo size 350 [PO].** See section E for what changed in the measured reliability.

## I. M2a: flows, Company 360, AI assistant, theme (2026-10-17) [PO + build]
Spec and ownership: `docs/M2A-CONTRACT.md`. The original M2 items (title normalisation, inferred
org chart, transcript themes) move to M2b.
- **Analysis is a drag-and-drop flow editor [PO].** It works like Dataiku or Blender nodes.
  - Dataset blocks read the CRM tables, an uploaded CSV / Excel file, or a read-only PostgreSQL
    connection [PO choice].
  - The blocks are filter, sort, columns, group, join, **pivot**, stats test, chart,
    train/test split, linear and logistic regression, and k-means [PO choice, including the ML
    blocks].
  - The M1b scan page stays reachable as "Quick scan".
- **Numbers still come from code [build].**
  - Every block runs in pandas, scikit-learn or scipy, and charts are aggregated server-side.
  - There is no expression language: computed columns are structured operations, with no
    `eval`, no pickle and no persisted models.
- **"Not verified" extends to models [build].**
  - A regression is verified only if, on the test set, n ≥ the gate and the R² CI is above 0.
  - A classifier is verified only if n ≥ the gate, each class has enough rows, the AUC CI is
    above 0.5 and the accuracy CI is above the majority-class baseline.
  - Coefficients are labelled "associations, not causes".
  - Clusters are always "exploratory".
- **External data stays read-only [build].**
  - PostgreSQL queries run in READ ONLY transactions, one statement, with a row cap and a
    timeout.
  - TLS is required off-loopback, and the password is sealed.
  - Uploads are stored in the database, so they are backed up and erased with the workspace.
    They are capped at 20 MB, and xlsx files are checked for zip bombs.
- **Companies group accounts [PO: Company 360 + registry].**
  - One search box answers "have we already dealt with them?". The last interaction is the
    latest deal, note or comment.
  - The public French registry (recherche-entreprises.api.gouv.fr, free, no key) is searched
    **only when the user clicks**.
  - The managers' list (personal data) is never read, and protected addresses are dropped.
  - Registry companies are stored only when the user adds them.
  - Demo companies are synthetic and have no SIREN, so they cannot collide with real ones.
- **Demo history has dates [build].** Demo notes and comments are dated over the past year, so
  "last interaction" means something. The note services accept the original date of imported
  history; it is checked and can never be in the future. A separate random stream generates the
  dates, so deals and every calibration number are unchanged.
- **AI model in Settings [PO].**
  - The provider is Gemini or Anthropic, chosen per workspace. The key is typed into
    DataForce's own Settings page, stored sealed, and never shown back or logged.
  - The old rule "never paste the key" means never paste it *in a chat* with an assistant.
- **The Ask panel answers about one account or company [PO].**
  - The facts come from code and are cited (`[F3]`, `[D2]`, `[N5]`). Notes are wrapped as
    untrusted text.
  - Numbers absent from the facts are flagged "unverified", and quotes are verified.
  - The panel says what is sent to the provider: CRM names, titles, deals and notes, never the
    enriched emails or mobiles.
  - Questions and answers are not stored.
- **Theme [PO].** The user can pick System, Light or Dark; the choice is remembered in the
  browser.
- **Noise demo seed [PO].** The noise demo uses seed 1, which verifies nothing. Seed 42 remains
  documented as one of the ~4% chance cases.

## J. M2b: titles, org-chart proposals, meetings and themes (2026-10-17) [build, per §B/§C]
Spec: `docs/M2B-CONTRACT.md`.

**Titles.**
- A French/English dictionary maps each title to a function and a seniority. It expands
  abbreviations, repairs typos, and flags ambiguous and missing titles.
- Only titles it does not know go to the workspace's AI model: the title text alone, once, then
  cached and flagged "classified by AI". There is a per-run and a per-day cap.
- A manual classification always wins.

**Org-chart proposals.** Rules and meetings may only *suggest*; a person accepts or rejects.
- Rules work on normalised titles inside one account: the next level up in the same function,
  then the CEO. They abstain when several managers fit and list the candidates instead.
- Meeting statements ("I report to X", "c'est X qui signe", "je vais pousser le dossier") are
  found by fixed FR/EN patterns. The exact sentence is kept, checked against the transcript.
- Accepted links keep their origin and evidence.

**Transcripts.**
- PDF, Markdown or text, on an account and optionally a deal.
- Only the cleaned text is kept. PDF reading runs in a separate process with a time and memory
  limit.

**Themes: known sales themes by keywords, discovery for the rest** [build, after measurement].
- Unsupervised topic modelling alone (TF-IDF + NMF) returned conversational filler and people's
  names on realistic text: planted-theme F1 0.38–0.69.
- So, as for titles, a FR/EN catalog of common sales themes (price, competitor, security,
  integration, timing, legal, onboarding, support) is matched per sentence by code, with exact
  quotes.
- Competitor names are detected when they recur near competitor cues.
- Discovery runs only on the remaining sentences, with names masked. Its topics are
  "exploratory", and only those are named by the AI.
- Everything runs locally: transcript text never leaves the computer for theme analysis.

**Themes and outcomes.**
- Flows get `deal_theme_flags`, one row per deal and theme. `mentioned` is *unknown*, not
  false, for a deal without a meeting.
- A "Themes vs win rate" template runs the stats block with the usual gates.
- On the demo, the planted price-objection effect is verified: 16.7 % vs 57.1 % win rate.
- A mention is an association, not a cause. Each theme is tested on its own (no correction
  across themes), so it is a screening step.

**GDPR erasure.**
- Erasing a contact also redacts their turns and their name in transcripts and in proposal
  excerpts, with same-length placeholders so offsets stay valid.
- Mentions in other people's notes remain (M1 residual).

**Measured** (`docs/review/M2b-methods-review.md`). The demo numbers are *in-sample*: the
generator, dictionary and keywords share their vocabulary, so they flatter. The independent
held-out tests used the reviewer's own titles, sentences and org charts:

| Method | Demo (seed 42, in-sample) | Held-out (reviewer) | Verdict |
|---|---|---|---|
| Titles | 99.6 % function, 99.7 % seniority | 75.8 % function, 86.3 % seniority. 41 % left unknown or flagged; when it answers, 90 of 90 correct | ratified with caveats |
| Org rules | 95 % precision, 81 % recall | 88.5 % precision, 59 % recall; abstains rather than guesses | ratified with caveats |
| Meeting links and signals | 100 % precision, 44 % recall; signals 74 of 74 | narrow recall on paraphrases, a few false positives (fixed after review) | ratified with caveats |
| Known themes | F1 0.82–0.98 | precision 0.64–0.89, recall 0.35–0.70 | exploratory only, no accuracy claim |

The review's should-fix items (title vocabulary gaps, lexicon false positives, conditional
statements, the screening caveat on "Themes vs win rate") were fixed afterwards. The held-out
set has therefore been seen and is no longer clean: a fresh one is needed for the next
measurement.

**Independent transcripts, set 1 (2026-10-18)** (`backend/eval/meetings/`).
- 15 FR/EN meetings were written by a separate agent from account briefs only, without the
  code, and imported through the upload API into `test-data`. Figures carry Wilson 95 %
  intervals.
- **Speakers** matched to a contact or rep: 95 % [86, 98] (56/59).
- **Known themes** per meeting: precision 74 % [60, 84], recall 83 % [69, 91].
  - Security, integration and price recall: 100 %.
  - Misfires: lateness to the call read as timing; an internal event's budget read as price; a
    passing "contract" read as legal; "versus last year" read as competitor.
- **Meeting org statements.**
  - Reports-to: **0 of 13**. The fixed patterns ("je reporte à", "I report to", "mon manager
    est X") miss common wordings such as "rattachée à X", "I work under X", "X, mon N+1, …" and
    "My boss, X, …".
  - Signals: precision 100 % (15/15), recall 44 % [29, 61].
- So the meeting patterns were fitted to the demo's wording. Set 1 was then used to broaden the
  patterns and the lexicon, so it is no longer held-out.
- **Set 2** was written afterwards the same way, from 15 other accounts. It measures the
  broadened rules on text they were not fitted to.

  | Set 2, 15 unseen meetings | Before | After broadening |
  |---|---|---|
  | Known themes, precision / recall | 68 % / 50 % | 72 % [57, 83] / 67 % [53, 79] |
  | Reports-to, links missing from the CRM | 1 of 10 | **1 of 10** |
  | Signals, recall | 2 of 20 | 7 of 20 (35 % [18, 57]) |
  | False statements or signals | 0 | 0 |

  For comparison, set 1 after broadening reached 8 of 9 links, 32 of 34 signals and themes at
  95 % / 88 %. Those figures are fitted to set 1, so they are not a measure of quality.
- **Conclusion.** The meeting patterns are precise but do not generalise: each new wording
  needs a new rule. Org suggestions from meetings therefore have low recall on real speech. The
  quotes are exact and a person still accepts every link.
- A scorer flaw was found and fixed on the way. The workspace's own synthetic meetings already
  state many of the same links, and a proposal keeps only the first quote. So the scorer now
  runs the app's extraction code on the set's transcripts only.
- **Set 3** was written the same way from 15 more accounts and is kept outside the repo until the
  AI pass is measured on it. With the broadened patterns only:
  - themes reach precision 89 % [76, 96] and recall 85 % [71, 93];
  - reports-to: **0 of 12**;
  - signals: 8 of 27, with none false. Four "false" signals were true statements the writer
    left out of the key; the key was corrected and the corrections are marked.

**Opt-in AI pass for meeting org statements** [PO, 2026-10-18] (`docs/ORG-AI-CONTRACT.md`).
- The PO chose this over keeping rules only.
- Off by default per workspace. Patterns run first.
- It sends only candidate speaker turns and the account's contact names, wrapped as data, to
  the workspace's model.
- Code keeps a finding only when:
  - its quote is an exact slice of the transcript;
  - the names resolve to one contact each;
  - a reports-to manager is named in the turn;
  - it is not hypothetical, already true, cyclic or rejected.
- Findings stay suggestions tagged "found by AI".
- **Measured live on held-out set 3 (2026-10-19)** with the PO's saved model (Gemini 3.5 Flash):
  15 calls, 0 failed. Verification dropped 12 of the model's findings.

  | Set 3, 15 unseen meetings | Patterns only | Patterns + AI pass |
  |---|---|---|
  | Reports-to, links missing from the CRM | 0 of 12 | **4 of 12**, all 4 correct |
  | Signals found (writer's key) | 8 of 27 | **23 of 27** |
  | Signals, precision after a hand check | 8 of 8 | **30 of 30** |

  - The 7 signals scored "false" were all true statements the writer had left out of the key
    ("je freine des quatre fers", "it's my signature on the PO", …). They were checked by
    hand and added to `key.json`, marked `added_by`.
  - Because those additions come from what the systems found, signal recall on the corrected
    key (30 of 34) is optimistic. The writer's key gives 23 of 27.
- **Where reports-to is still lost.** The AI pass keeps a link only when the manager is named
  in the same speaker turn and in the quote shown. Statements that name the manager earlier, or
  only through a pronoun, are dropped on purpose, and the candidate filter skips some wordings
  ("go to bat for this"). Raising recall further means relaxing one of these guards: a decision
  for the PO, not a tuning step. Set 3 has now been seen.
- **Guards relaxed by the PO (2026-10-19).**
  - A manager named anywhere earlier in the meeting now counts; the evidence then carries a
    second exact quote, where the manager was named.
  - The candidate filter is wider: more stance cues, and the first person with a stance word.
  - Measured on **set 4**, 14 meetings written afterwards from accounts no set had used, with a
    key that records incidental statements. 14 Gemini calls; verification dropped 12 findings.

  | Set 4, 14 unseen meetings | Patterns only | Patterns + relaxed AI pass |
  |---|---|---|
  | Reports-to (links missing from the CRM) | 1 of 16 | **14 of 16**, all correct |
  | Signals | 5 of 34 | **17 of 34**, all correct |
  | Known themes, precision / recall | — | 79 % / 84 % |

  - Six of the 16 reports-to statements used a pronoun, with the manager named turns earlier:
    the case the relaxation was for.
  - Signal recall stays at about half on this set: the misses are mostly blockers and decision
    makers phrased indirectly.
  - Set 4 is now seen.
- **Security review SR17** (2026-10-19) found that a "manager named earlier" mention could be a
  speaker label, sit in a hypothetical or negated sentence, or lie hundreds of turns back.
  - The mention now passes the same guards as the statement and lies within 40 turns; the
    second quote is capped at 300 characters.
  - Re-measured on set 4 (already seen, so this measures the cost, not quality): reports-to
    **11 of 16** (was 14), signals 17 of 34, everything still correct.
  - Part of the drop may be model variance between runs. The 40-turn window and the guard on
    the mention sentence are the knobs if recall matters more.

## K. Open
1. CRM scope, TamTam, AI key: as in M2a (the PO is testing).
2. Themes on real transcripts: the keyword catalog is generic sales vocabulary. It has been
   measured on synthetic meetings, the methods reviewer's held-out sentences and three
   independently written sets (§J), never on real calls.
3. M3b: login (email + password, invite-only) and hosting.

## L. M3a: MCP server for AI assistants (2026-10-18) [PO + build]
Spec: `docs/M3A-CONTRACT.md`. The PO chose to start M3 with the MCP server and agent API;
login and hosting come next (M3b).

**Shape.**
- `dataforce mcp --workspace SLUG` is a local stdio server. The assistant (Claude Desktop,
  Claude Code…) starts it. There is no network port, and one process serves one workspace.
- 14 read-only tools cover the overview, companies, accounts, deals, pipeline, group
  comparison, scan, flows, meetings, themes and text search.
- Every result is an envelope:
  - `computed_by = "code"`;
  - counts are tagged `exact_count`;
  - statistics keep their *verified* / *not verified* status and reasons;
  - `untrusted_fields` lists the customer text.

**Safety.**
- **Read-only.** Read tools run in READ ONLY transactions. The scan and flow tools write only
  their own run rows.
- **Isolation.** No tool takes a workspace argument; ids from another workspace give "not
  found".
- **What is never returned.** Contact channel values (enriched emails and mobiles), sealed
  secrets, connection passwords and AI keys.
- **Customer text is data.** The server instructions say so, and notes, transcripts and other
  free text come back in `*_untrusted` fields.
- **Limits and audit.** Caps and paging, a 30 s statement timeout, and one audited
  `agent_call` run per call, holding no row data.

**Security review** (`docs/security/SR14-m3a.md`): 0 high, 2 medium, 4 low.
- Medium:
  - names, labels and flow column headers reached the assistant as plain fields;
  - a saved PostgreSQL connection that points at DataForce's own database could expose sealed
    values through a flow.
- Low: response size, scan rate, the timeout after commit, and per-row queries.
- All are fixed; the resolution is in the report.
- A PostgreSQL connection to the application database is now refused, which also matters for
  hosting (M3b).

**Not in M3a.** No write tools, no network transport and no login: anyone who can run programs
on this computer can already read the database.
