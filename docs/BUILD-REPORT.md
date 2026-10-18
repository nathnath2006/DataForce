# DataForce — build report (M1, M1b, M2a, M2b, M3a)

**Status (18 October 2026):**

| Milestone | What it added | State |
|---|---|---|
| **M1** ("jalon 1") | Data, CRM and statistics engine | complete and ratified |
| **M1b** | A local web interface, "Connect TamTam" over MCP, the 350-deal demo | complete, reviewed and fixed |
| **M2a** | Your feedback: drag-and-drop **analysis flows** with a pivot, statistics and model blocks; a **Companies** tab with the public French registry; an **AI model** in Settings with an **Ask** panel; a **light / dark** theme | complete, reviewed and fixed |
| **M2b** | Job titles normalised; org-chart **suggestions** from titles and from what people said in meetings (a person accepts them); **meeting transcripts** with known sales themes and discovered topics | complete, reviewed (security and methods) and fixed |
| **M3a** | An **MCP server**: Claude Desktop, Claude Code or another AI assistant on this computer queries one workspace read-only and gets exact results. Three **independent transcript tests**. An **opt-in AI pass** for org statements in meetings | complete, reviewed (SR14, SR15) and fixed; the AI pass awaits a live measurement |

Every part was built by Sonnet agents, independently reviewed for security, fixed and re-verified. **1,489 automated tests pass** (1,417 backend, 72 frontend).

**Sources of truth.**

| File | What it holds |
|---|---|
| `docs/DECISIONS.md` | every decision and its reason |
| `docs/ARCHITECTURE.md` | the M1 contract |
| `docs/UI-CONTRACT.md` | the M1b contract |
| `docs/M2A-CONTRACT.md` | the M2a contract |
| `docs/M2B-CONTRACT.md` | the M2b contract |
| `docs/review/M2b-methods-review.md` | the independent, held-out check of the M2b methods |
| `docs/M3A-CONTRACT.md` | the M3a contract (MCP server and agent tools) |
| `docs/ORG-AI-CONTRACT.md` | the contract of the opt-in AI pass on meeting sentences |
| `backend/eval/meetings/` | the independently written transcript sets, their answer keys and the scorer |
| `docs/BUILD-REPORT.md` | the source of this PDF, rendered by `docs/tools/build_pdf.py` |

## 1. In one page

**What DataForce is.** An analysis workspace for sales and marketing teams. The team keeps a *minimal CRM* in DataForce: companies, accounts, people, deals and notes. Then it:

- looks up any company: "have we already dealt with them?";
- builds analyses by wiring blocks on a canvas;
- asks an AI about one account, with the AI's answers checked against the data.

TamTam already has better external data than we could build. So DataForce works at the CRM level, and calls TamTam only when a user explicitly asks for contact details.

**The one rule that shapes everything.** DataForce shows a number as a fact only when the evidence is strong enough. Otherwise it says **"not verified"** and gives the reasons:

- too few deals;
- an interval that is too wide;
- not significant once many comparisons are accounted for;
- for a model: not better than guessing, or tested on its own training data.

The AI never computes numbers. Any number it writes that is not in the data is flagged.

**What is delivered.**

| Piece | What it does |
|---|---|
| Minimal CRM | Workspaces, companies grouping accounts, contacts with "reports to", deals, append-only notes and comments, one-click erasure |
| **Companies (M2a)** | One search box: have we interacted, and when last? A 360 page per company. On request, a lookup in the public French registry (address, SIREN, activity, size), with "Add to CRM" |
| **Analysis flows (M2a)** | Drag-and-drop canvas. Datasets come from the CRM, an uploaded CSV / Excel file or a read-only PostgreSQL database. Blocks: filter, sort, columns, group, join, **pivot**, stats test, chart, train/test split, linear and logistic regression, k-means |
| Statistics engine | Win rate, cycle length and deal size with 95 % confidence intervals and the "not verified" gates, reused by the stats and model blocks |
| **AI model and Ask (M2a)** | Gemini or Anthropic key entered in Settings, stored encrypted. The Ask panel on an account or company answers from its data, cites it, and flags numbers and quotes it cannot back |
| **Job titles (M2b)** | Every title mapped to a function and a seniority by a French / English dictionary; unknown titles optionally classified once by your AI model (title text only), flagged for review |
| **Org-chart suggestions (M2b)** | Managers proposed from titles (same account, next level up) and from meeting sentences ("I report to…"), plus champion / blocker / decision-maker signals, each with its evidence; nothing becomes a fact until a person accepts it |
| **Meetings and themes (M2b)** | Transcripts (PDF, Markdown, text) on accounts and deals; known sales themes found by keywords with exact quotes, other recurring topics discovered; "Themes vs win rate" as a screening flow. All local |
| Connect TamTam (M1b) | Sign in on TamTam's page. The token is encrypted; paid lookups happen only after a confirmed click |
| Synthetic demo | 350 deals with planted effects (seed 42) and a pure-noise twin (seed 1), with companies, a year of dated notes, half the org charts left to rediscover, and 160 meetings with planted themes |
| Command line and notebook | `dataforce …`; a proof notebook run against the answer key |

**Not delivered yet (by plan).**

- M3: the MCP server and API for outside AI agents, login and hosting.

## 2. How it was built

The team works the same way for every milestone:

1. The tech lead (Claude Opus) writes the contracts first: the database model, the shared data types, the API shapes, and a written specification with non-overlapping file ownership.
2. Builder agents (Claude Sonnet, low effort, as requested) work in parallel.
3. Separate reviewer agents can read but not change the code, and must prove each finding.
4. Fixers close the findings with regression tests.
5. The tech lead re-runs everything, opens every screen in a headless browser, and commits in logical steps.

| Round | Build | Ratify (read-only) | Fix |
|---|---|---|---|
| M1 | foundation, generator, stats engine, LLM clean-up, integration | SR4, SR5, statistics ratification | 3 fixers |
| M1b | API and CRM, TamTam connector, frontend, 350-deal demo | SR6 (API), SR7 (OAuth), SR8 (frontend) | 2 fixers + tech lead |
| **M2a** | flow engine, flow API and data sources, companies and registry, AI assistant, flow-editor UI, companies/AI/theme UI | SR9 (flows and data), SR10 (companies and AI), SR11 (frontend) | 3 fixers + tech lead |
| **M2b** | titles, org proposals, transcripts and themes, demo meetings, org/titles UI, meetings UI; then a second and third theme method and realistic demo transcripts | SR12 (backend), SR13 (frontend), an **independent methods review** on held-out data | 2 fixers + tech lead |

**During M2a and M2b** the agents hit usage limits mid-build. They were resumed where they stopped once the limit reset, with no work lost.

**Version control.** Logical commits on `main`, with the tags `m1`, `m1b`, `m2a` and `m2b`, in the private GitHub repository `nathnath2006/DataForce`; new commits are pushed when you ask.

## 3. Product decisions (and why)

| Decision | Why |
|---|---|
| **Not enough evidence → "not verified"**, always with the reasons; "not verified" is *not* "no effect". | A salesperson must be able to rely on whatever is shown as a fact. |
| **The AI never calculates.** Numbers come from code; the AI may only name, explain and cite them. | Numbers must be reproducible and auditable. |
| **Notes and comments are append-only** (a database trigger enforces it), except GDPR erasure. | Trust in what was said about a person, and the right to erasure. |
| **Strict minimum on third parties.** Emails and mobiles exist only after a confirmed TamTam lookup, encrypted, each with a *Delete*. | GDPR data minimisation. |
| **Analysis is a flow of blocks** (M2a, your request), not a fixed report. | Teams ask different questions; a pivot or a model should be two clicks away. |
| **Blocks are configured, never programmed.** There is no formula language, nothing is evaluated as code, and no model is saved. | A formula language and saved models are two classic ways in for attackers. |
| **"Not verified" extends to models.** A model is verified only if, on data it never saw, it beats the "learnt nothing" baseline with its confidence interval. | Most models on small CRM data are noise. The label says so. |
| **External data is read-only.** PostgreSQL runs one statement in a read-only transaction; files are copied into DataForce. | DataForce must never be able to change your systems. |
| **A company groups accounts** (M2a). | One customer often appears as several accounts: branches, subsidiaries. |
| **The public registry is searched only when you click.** The managers' list is never read; protected records are never stored. | Your search text leaves the computer only when you choose. |
| **The AI key is entered in Settings**, encrypted and never shown back. | Simple for you. The old "never paste the key" rule meant never paste it *into a chat*. |
| **The Ask panel says what it sends** (CRM names, titles, deals, notes; never emails or mobiles) and stores nothing. | You decide what goes to Google or Anthropic. |
| **Local only, no login yet.** | Login and hosting are M3. |
| **Titles, links and themes: dictionary first** (M2b). Code with fixed French / English vocabularies does the work; the AI is used only for what the dictionary does not know, and is flagged. | Explainable, cheap, private. The same pattern as the statistics: code computes, the AI names. |
| **Suggestions are never facts** (M2b). A rule or a meeting may only *suggest* a manager or a signal; a person accepts or rejects it. | An org chart is about people; a wrong "reports to" must never appear as certain. |
| **Meeting text stays on the computer** (M2b). Themes are found locally; the AI only names discovered topics, from top words and short excerpts with names masked. | Transcripts are the most sensitive data in the tool. |
| **Erasing a person erases them from transcripts too** (M2b). Their turns and their name are replaced by same-length placeholders. | GDPR erasure must not leave their words behind. |
| **350 demo deals; noise demo on seed 1.** | Your choices. Seed 42 of the noise twin is one of the ~4 % that show a chance finding. |

## 4. How the statistics work (plain language)

**The three questions.**

- *Win rate*: of the closed deals, what share was won?
- *Sales cycle*: days from creation to close, as a median.
- *Deal size*: the median amount.

Medians are used so one giant deal does not distort the picture.

**Confidence intervals.** Every number comes with the range that, 95 times out of 100, contains the true value.

- Rates use Wilson intervals.
- Differences between two rates use Newcombe intervals.
- Medians use a bootstrap with a fixed seed, so results are reproducible.

**The "not verified" gates** (approved by you, all configurable):

| A result is "not verified" when… | Default |
|---|---|
| the group has too few deals | fewer than 30 |
| a win rate rests on too few wins or losses | fewer than 10 of either |
| the range is too wide | more than ±15 points for a rate, ±30 % of the value for a median |

**Comparing groups.**

- Each group is compared with the rest, using Fisher's exact test for rates and Mann-Whitney for days and amounts.
- The Benjamini-Hochberg correction keeps the expected share of false findings at 5 %.
- A finding is **verified** only if both sides pass the gates, the corrected test is significant, and the range of the difference excludes zero.

**Real lines from the demo** (350 deals, seed 42, the same in the stats block of a flow):

| Group vs rest | Question | Result | Verdict |
|---|---|---|---|
| Inbound leads | win rate | 72.5 % vs 24.2 %, +48.4 pts [+35.9, +58.6] | **verified** |
| Enterprise | sales cycle | median 106 vs 41 days | **verified** |
| Referral leads | win rate | 72.0 % vs 39.1 % | not verified: only 25 deals (< 30), only 7 losses |
| Mid-market | deal size | €20,771 vs €15,879 | not verified: q = 0.58, range [−190, +9,921] EUR includes 0 |

**Models (M2a).** A split block keeps a share of the rows aside (25 % by default). The model learns on the rest and is judged only on the rows it never saw.

| Model | Verified only if, on the held-out rows | Example on the demo |
|---|---|---|
| Logistic ("will this deal be won?") | at least 30 rows; enough wins and losses; AUC interval above 0.5; accuracy interval above the "always predict the majority" rate | accuracy 81.5 % [69.2, 89.6] vs baseline 53.7 %; AUC 0.86 [0.74, 0.97]: **verified** |
| Linear ("how large will it be?") | at least 30 rows; R² interval above 0 | R² 0.65 [0.46, …] on amount by segment: **verified** |
| Clustering (k-means) | never: groups describe, they do not prove | 3 groups of accounts, silhouette 0.43: **exploratory** |

**Two traps are caught automatically.**

- Wiring the same rows into both "train" and "test" gives "not verified: test rows may overlap the training rows".
- A join that duplicates rows (one row per contact instead of per deal) gives "not verified: n is inflated".

Coefficients are labelled "associations, not causes".

## 4b. Titles, org chart and meetings (M2b, plain language)

**Titles.**
- "Dir. commercial", "VP Sales" and "Ingénieur d'affaires" become *sales · head*, *sales · vp* and *sales · individual*.
- The dictionary expands abbreviations and repairs typos.
- A title it does not know is either sent once to your AI model (only the title, never the person's name) and flagged "classified by AI", or left "unknown" for you to set.

**Org chart.** For contacts without a manager, the rules look for the next level up in the same function, then the CEO, inside the same account. When two people fit, the rules list both and do not guess. Meeting sentences such as "I report to Soline Pellegrand" or "c'est Quentin qui signe" become suggestions, with the exact sentence as evidence.

**Themes.** We tried pure topic discovery (TF-IDF + NMF) first, and it failed on realistic transcripts: it returned small talk ("next week", "send the documents") and people's names.

The working method is the same as for titles:
1. A French / English catalog of common sales themes (price, competitor, security, integration, timing, legal, onboarding, support) is matched sentence by sentence, with exact quotes.
2. Competitor names are spotted when they recur near words like "similar offer".
3. Discovery then looks only at the remaining sentences. Its topics stay *exploratory*.

**How good is it?** There are two kinds of numbers:
- **In-sample**: on the synthetic demo, whose vocabulary the dictionary shares, so these flatter;
- **Held-out**: from an independent reviewer's own titles, sentences and org charts.

| Method | Demo (in-sample) | Held-out | Verdict |
|---|---|---|---|
| Titles | 99.6 % function, 99.7 % seniority | 75.8 % function, 86.3 % seniority; 41 % left unknown or flagged, but **90 of 90 right when it answers** | ratified with caveats |
| Org rules | 95 % precision, 81 % recall | 88.5 % precision, 59 % recall; abstains rather than guesses | ratified with caveats |
| Meeting links and signals | 100 % precision, 44 % recall; signals 74 of 74 | narrow on paraphrases; a few false positives, fixed | ratified with caveats |
| Known themes | F1 0.82–0.98 | precision 0.64–0.89, recall 0.35–0.70 | **exploratory only**: no accuracy claim |

The review's fixes were applied afterwards, so its held-out set has now been seen. A fresh one is needed for the next measurement.

**Independent transcript tests (18 October).** Each set holds 15 French and English meetings, written by a separate agent that saw only a brief of the accounts (people, titles, true managers) and never the code. Each comes with an answer key: the topics really discussed, who reports to whom, champions, blockers and decision makers, plus decoys that must not count.

| Measure | Set 1, before | Set 2, unseen, after broadening | Set 3, unseen, after broadening |
|---|---|---|---|
| Speakers matched to a person | 95 % | 100 % | 100 % |
| Known themes, precision / recall | 74 % / 83 % | 72 % / 67 % | 89 % / 85 % |
| "Who reports to whom" found | 0 of 9 | 1 of 10 | **0 of 12** |
| Champion, blocker, decision maker found | 15 of 34 | 7 of 20 | 8 of 27 |
| False statements or signals | 0 | 0 | 0 |

What this says:
- The meeting patterns never invented a statement.
- They only recognise wordings someone wrote a rule for. Set 1 was used to broaden them, and the gain did not carry over to sets 2 and 3.
- So you chose an opt-in AI pass:
  - Off by default per workspace.
  - It sends only the sentences that name a contact or contain an org phrase, plus the account's contact names, to your own model.
  - Code keeps a finding only if its quote is word for word in the transcript, the names are contacts of the account, any manager is named in the quote, and it is not hypothetical, negated, already true, circular or rejected.
  - Findings are tagged *found by AI*, and a person still accepts each one.
- Its live accuracy will be measured on set 3 once an AI key is saved on the test workspace.

**Themes and deal outcomes.**
- On the demo, deals whose meetings mention price objections won **16.7 %** of the time, against **57.1 %** for the others: −40.5 points, verified.
- Deals with no meeting are left out, not counted as "no mention".
- This is a screening result:
  - the theme was found on the same meetings;
  - each theme is tested on its own;
  - deals differ in how often, and with whom, they were met.
- The app says so next to the button.

## 4c. Connecting an AI assistant (M3a, plain language)

**What it does.** You add one line to Claude Desktop or Claude Code (*Settings → AI assistants (MCP)* shows it). The assistant can then ask DataForce questions about one workspace:

- the overview and pipeline;
- a company or account;
- deals, with filters;
- group comparisons ("does lead source change the win rate?");
- a saved flow;
- meetings, themes and a text search.

**Why the answers can be trusted.**
- Every number in an answer comes from SQL or the statistics engine, tagged `computed_by: code`.
- Comparisons keep their *verified* / *not verified* label and the reasons, and the assistant is told never to present *not verified* as a fact.

**What it cannot do.**
- It is read-only, bound to one workspace, and has no network port: the assistant starts DataForce itself on this computer.
- It never receives emails, phone numbers, keys or passwords.
- Everything a customer wrote (notes, transcripts, names, titles, column headers) is marked as data, and the assistant is told not to follow instructions inside it.
- Each call is logged under *Recent calls*, without the data.

## 5. The synthetic demo data

**What the generator builds** for a realistic small company:

- 30 companies grouping 122 accounts, with invented addresses in real French cities and no SIREN, so they never collide with real firms;
- 755 contacts with org charts;
- 350 deals;
- a year of dated notes and comments;
- **M2b:** half of the accounts lose their manager links in the CRM, so the true tree stays in the answer key for the rules to rediscover; there are 160 meetings (60 % French), varied enough that 85 % of the customer sentences are distinct. They have planted themes (price objection in 65 % of lost-deal meetings vs 20 % of the others), "I report to…" sentences and champion / blocker / decision-maker signals.

Everything is invented and deterministic: the same seed always gives the same data.

| Kind | In the demo data |
|---|---|
| **Planted** (must be found) | Inbound wins far more often; enterprise deals are slower and larger than SMB deals |
| **Trap** (must stay "not verified") | Referral: a high win rate on at most 25 closed deals |
| **Null** (must find nothing) | Industry, region and owner. The **noise twin** (seed 1) has no effect at all |

**Reliability over 100 random datasets per variant** (350 deals):

- every planted effect was found every time;
- about 8 % of planted datasets and 4 % of noise datasets show one chance finding.

That is the 5 % false-discovery control doing what it promises. Companies and note dates use separate random streams, so adding them changed no deal and no calibration number.

## 6. Architecture and structure

```
 browser: React UI (companies, flows, Ask, settings)        CLI · notebook
      │ JSON on 127.0.0.1 only, request guards
 local API (FastAPI)
  ├─ flow engine (pandas, scikit-learn)
  │    └─ sources: CRM · CSV / Excel · PostgreSQL (read-only)
  ├─ companies ── public registry (api.gouv.fr, on click)
  ├─ Ask assistant ── Gemini / Anthropic (key sealed)
  ├─ TamTam connector (OAuth over MCP)
  └─ services layer (workspace-scoped, no SQL strings) ── PostgreSQL
```

**Size.**

| Part | Lines |
|---|---|
| Backend code | about 16,200 |
| Migrations | 750 |
| Tests | 10,800 |
| Frontend | 4,600 |

**Main folders.**

| Folder | Contents |
|---|---|
| `backend/app/services/` | CRM, companies, files, connections, flows, AI settings, enriched channels |
| `backend/app/stats/` | Intervals, tests, gates (shared with the flow blocks) |
| `backend/app/flows/` | Graph contract, engine, one module per block, data sources |
| `backend/app/registry/`, `backend/app/assistant/` | Public registry client; Ask context, checks and rate limit |
| `backend/app/connectors/`, `backend/app/llm/` | TamTam OAuth; Gemini / Anthropic / fake providers |
| `backend/app/api/` | Routes, request guards, error mapping, hosting of the interface |
| `frontend/src/` | Pages; `flows/` (canvas editor); `companies/`; `assistant/`; theme |

**Data model.**

| Table | Holds |
|---|---|
| `workspace`, `app_user` | one team (or one demo dataset); its members |
| `company` (M2a) | name, SIREN, address, activity, size, source; groups accounts |
| `account`, `contact`, `deal` | the CRM; contacts keep only name, title, reports-to and source |
| `note`, `comment` | append-only free text |
| `run`, `llm_call` | history of scans, generations and flow runs (summaries only); AI usage per workspace |
| `connector_credential`, `oauth_pending`, `contact_channel` | TamTam connection; sign-ins in progress; confirmed emails and mobiles (encrypted) |
| `uploaded_file`, `data_connection`, `flow` (M2a) | CSV/Excel files; PostgreSQL connections (password encrypted); saved flows |
| `llm_credential` (M2a) | the workspace's AI provider, model and encrypted key |
| `title_cache`, `org_proposal` (M2b) | AI title classifications (cached once); suggested links and signals with their evidence and status |
| `document`, `document_chunk`, `theme`, `theme_assignment` (M2b) | transcript text (cleaned, the file itself is not kept) and speaker turns with exact offsets; themes and which turns carry them |

**Technology.**

| Choice | Why |
|---|---|
| Python 3.13, FastAPI, SQLAlchemy 2, PostgreSQL 16 | Mature, typed, one database for everything |
| numpy, scipy, **pandas, scikit-learn, openpyxl** (M2a) | Reference implementations for statistics, tables, models and Excel files |
| React 19 + Vite + TypeScript, **@xyflow/react** for the canvas (M2a) | Small, fast, no UI kit; the canvas is loaded only when a flow is opened |
| **pypdf** in a separate process with a time limit (M2b) | Reads PDF transcripts; a crafted PDF cannot hold the app or exhaust its memory |
| Fernet encryption | Tokens, keys, passwords and enriched values are unreadable in the database and in backups |
| Hashed lock files (pip-tools, `package-lock.json`) | Reproducible, tamper-evident installs |

## 7. Security

**Principles.**

- Local only.
- Another website cannot drive the app: Host allow-list, Origin plus a custom header, strict content-security policy.
- Secrets are encrypted at rest, and never shown, logged or sent to the browser.
- External systems are read-only.
- Text from notes, imports or servers is data, never instructions or HTML.

**Reviews** (read-only reviewers who must prove each finding).

| Review | Scope | Findings | Status |
|---|---|---|---|
| SR4, SR5 (M1) | CRM database, LLM, statistics, demo | 7 medium, 11 low, 7 info | all medium fixed |
| SR6–SR8 (M1b) | local API, TamTam sign-in, frontend | 0 medium, 11 low, 11 info | all low fixed |
| **SR9** (M2a) | flows, uploads, PostgreSQL | **1 high**, 7 medium, 6 low, 1 info | high and every medium fixed with tests; 3 low/info accepted with a reason |
| **SR10** (M2a) | companies, registry, AI assistant | 1 medium, 5 low, 2 info | all 8 fixed with tests |
| **SR11** (M2a) | frontend, npm supply chain | 1 low, 1 info | low fixed |
| **SR12** (M2b) | titles, org proposals, transcripts, PDFs, erasure | **1 high**, 2 medium, 6 low, 3 info | all fixed with tests |
| **SR13** (M2b) | frontend (transcript viewer, suggestions) | 3 low, 1 info | all fixed |
| **Methods review** (M2b) | accuracy of titles, rules, meeting statements and themes on held-out data | no blocker; 6 should-fix | fixed (see section 4b) |
| **SR14** (M3a) | MCP server and agent tools | 2 medium, 4 low, 2 info | all fixed with tests |
| **SR15** (M3a) | opt-in AI pass on meeting sentences | 3 medium, 3 low, 1 info | all fixed with tests |

**The M2a high finding.** A crafted PostgreSQL query could end the read-only transaction and write to the connected database. The cause was a hand-written statement splitter, fooled by `$$` quoting. The query now runs as a *prepared statement*, which the database server itself refuses to split into two commands, whatever the quoting. Regression tests try every quoting trick; a watchdog also cancels any query that runs past its time limit.

**The M2b high finding.** Erasing a contact failed when someone's validated manager link came from a proposal naming them, so the right to erasure was blocked. Erasure now clears those links and proposals first.

**M3a medium findings fixed.**
- **Names reaching the assistant.** Names, titles, labels and flow column headers reached the assistant as ordinary fields, so a customer could plant an instruction in a job title or a CSV header. All customer strings are now declared as data, and flow results never use a customer string as a field name.
- **Flows reaching DataForce's own database.** A flow on a PostgreSQL connection pointed at DataForce's own database could return sealed values and other workspaces' rows. Such connections are now refused when saved and when run, and columns that look like emails, phones or keys are blanked for the assistant.
- **The AI pass: quotes picked to hide meaning.** The model could pick a short quote that hid an "if" or a "not", or that did not name the manager. Checks now run on the whole sentence, and a "reports to" quote must name the manager.
- **The AI pass: daily cap and consent.** Concurrent runs could exceed the daily call cap, now enforced atomically. Changing the AI provider or model kept the switch on; it now switches off, so you consent again for the new provider.

**M2b medium findings fixed.**
- A crafted PDF page held a worker for minutes, because the time budget was only checked between pages. Extraction now runs in a separate process that is stopped at 30 seconds (with a memory cap where the operating system enforces it).
- An erased person's turns and name stayed in transcripts. They are now redacted.

**M2a medium findings fixed.**

- A connection whose server was changed kept the old password and would have sent it to the new server. The password must now be re-entered.
- **Heavy inputs could hog the app.** A huge median comparison or a 80,000-column CSV header could run for minutes. Runs now have a concurrency limit, cooperative time limits inside long blocks, and size checks before parsing.
- A pivot could produce a 20 MB answer. Its view is now capped.
- A model tested on its own training data, or statistics on rows duplicated by a join, could show "verified". Both are now caught.
- The assistant's number check could be fooled ("EUR9999", "twelve", numbers taken from notes). Numbers now count only when they appear in code-computed facts; numbers found only in notes are listed apart.

**Main things the reviews confirmed hold.**

- No route returns or changes another workspace's data.
- Cross-site requests, DNS rebinding and form posts are refused.
- Uploads are accepted only on their own route, with every guard.
- The registry receives your search only on a click (now a guarded POST). It never reads the managers' list, and protected records cannot be stored.
- The AI key never appears in a response, a log or a URL. A website cannot trigger AI calls, and calls are capped at 60 questions per hour per workspace.
- Notes and names cannot break out of the "untrusted text" wrapper sent to the AI.
- The npm dependencies (113 packages) are pinned and integrity-checked, with install scripts disabled.

**Accepted residuals** (written down):

- **No login until M3.** Any program on this computer can use the app.
- **PostgreSQL.** The database role you connect with remains the real boundary: use a read-only role. `sslmode=require` encrypts but does not verify the server certificate; use `verify-full` for remote databases.
- **Timed-out runs.** A run that times out keeps its worker until the current computation step ends. It holds its slot meanwhile, so runs cannot pile up.
- **Encryption key.** One key, kept in `backend/.env`, with no rotation yet. Losing it means re-entering the AI key and reconnecting TamTam.
- **Unverified assumptions.** TamTam's tool list and prices, and live AI answers, are unverified until you connect real accounts.
- **Mentions in other people's notes.** An erased person's name can remain in other people's notes (append-only).
- **Memory cap on macOS.** The PDF memory cap is not enforced on macOS; the time limit is.
- **Untested on real meetings.** Themes and meeting patterns have been measured on three independently written synthetic sets, never on real transcripts.
- **AI pass, live.** The opt-in AI pass has only run against a fake model so far.
- **Assistants read customer text.** Prompt injection toward a connected assistant cannot be excluded entirely. Its tools are read-only and it never sees keys or contact channels.

## 8. Verification results

| Check | Result |
|---|---|
| Backend tests | **1,417 pass**: CRM, statistics, demo, LLM, TamTam, API, flows, sources, companies, registry, assistant, titles, org proposals, transcripts and PDFs, themes, erasure redaction, **the 14 agent tools, the MCP server (including a real stdio session), the AI pass with a fake model, and one regression test per SR14 and SR15 finding** |
| Frontend tests | **72 pass**: everything earlier, plus the AI assistants panel, the *found by AI* tag and the AI switch notice; type check and build clean |
| Lint, migrations | ruff clean; models and migrations identical; dev database at `0007_org_ai` |
| AI assistant, live | the MCP server started from `/` the way Claude Desktop starts it; 14 tools listed; overview, comparison, text search and meetings answered on *Test data*, with customer text only in untrusted fields |
| Independent transcripts | three sets of 15, scored through the running app (section 4b) |
| M2b against the answer key | titles, rule and meeting links, signals, themes and the price-vs-win-rate test scored through the running app on the seed-42 demo (section 4b) |
| End to end, through the running app | one flow using all 12 block types on the demo. Inbound and outbound verified, referral not verified (as in M1); the logistic model verified (AUC 0.85); clusters returned; the leakage and join traps caught |
| Screens | every page opened in a headless browser, in light and dark mode, with no console error; a real registry search for "Dataiku" returned the public record |
| Notebook | re-run: planted seed 42 finds 5 of 5; noise seed 1 verifies nothing out of 93 comparisons |

**Caught during the verification itself.**

- **M2b themes failed twice before working.** First, small talk and people's names came out as themes. Second, the demo transcripts were too repetitive to judge anything: 25 % distinct sentences, now 85 %. The keyword-first method came out of these measurements.
- **The first "themes vs win rate" table counted deals with no meeting as "not mentioned"**, which biased the comparison. Those deals are now left out.
- **An independent reviewer found the demo accuracy flattering**, and the report now shows the held-out numbers next to the demo ones.

- **Every demo company showed "last interaction: today".** The demo notes had no dates. They now carry a year of synthetic history, which needed a checked "original date" option for imported notes.
- **Dates showed a stray "02:00".** Dates are now shown without a time.
- **The canvas stayed light in dark mode.** It now follows the theme switch.
- **The editor's field names drifted from the API on one point** (a connection's last error). The two now match.

## 9. How to run it

```
make db-up                                   # local Postgres
make migrate                                 # schema (after the one-time Python setup, see README)
make testdata                                # the synthetic "Test data" workspace (seed 42)
make ui                                      # then open http://127.0.0.1:8800
backend/.venv/bin/dataforce mcp config --workspace test-data   # snippet for Claude Desktop
```

**Try:**

| Where | What to do |
|---|---|
| **Companies** | type "alder", or search the registry for any French company |
| **Analysis** | *New flow* → a template, then *Run all* and click a block to see its result |
| **Settings → AI model** | paste a Gemini or Anthropic key, *Test*, then *Ask* on a company |
| **Contacts** | *Normalize titles*, then *Review titles* |
| **An account** | *Suggest links* in the org chart; accept or reject with the evidence; upload a transcript under *Meetings* |
| **Meetings** | *Find themes*, then *Test against win rate* on the price theme |
| **Theme** | the button in the header |
| **Claude Desktop / Claude Code** | paste the snippet from *Settings → AI assistants (MCP)*, then ask "what is the win rate by lead source, and which differences are verified?" |
| **Settings → AI model** | tick *Read meeting sentences for org statements*, then *Suggest links* on an account with meetings |

## 10. What comes next

| Milestone | Content |
|---|---|
| **M3b** | Login (email and password, invite-only) and hosting; flow results saved and shared |

**Open questions for you.**

1. **CRM scope.** After trying Companies, accounts and flows: what is missing?
2. **TamTam.** After connecting, does *Check connection* list the tools we expect, and what are your real credit prices?
3. **AI.** After adding your key, are the Ask answers useful? Should the assistant also be able to *run* a flow for you, for example "pivot my deals by segment"?
4. **Blocks.** Which block do you miss most: export to CSV, time series, a decision tree, or a cohort view?
5. **Real transcripts.** Can you share 5–10 real (anonymised) transcripts? They would give the themes, meeting patterns and the AI pass their first real measurement.
6. **AI pass.** Once your key is saved on *Test data*, the AI pass is measured on set 3. Is a "found by AI" suggestion something you would accept after reading its quote?
7. **Assistant.** After connecting Claude Desktop or Claude Code, which questions did it answer well, and which tool was missing?

## Glossary

| Term | Meaning |
|---|---|
| Confidence interval (CI) | The range that most likely contains the true value; narrower with more data |
| Gate | A minimum-evidence rule; failing one makes a result "not verified" |
| FDR | The expected share of reported findings that are false, held at 5 % |
| Train / test split | Keeping some rows aside to judge a model on data it never saw |
| Baseline | What a model that learnt nothing would score; a model must beat it |
| AUC | How well a model ranks wins above losses: 0.5 is a coin toss, 1.0 perfect |
| R² | Share of the variation a regression explains: 0 is nothing |
| In-sample / held-out | Measured on the data the method was built with (flattering) / on new data it never saw (honest) |
| Lexicon | A fixed list of words and phrases per theme, matched by code |
| Pivot | A table with one dimension in rows, another in columns, and a sum or count in each cell |
| SIREN | The 9-digit French company identifier |
| Prepared statement | A query the database checks as one single command before running it |
| MCP | Model Context Protocol: the standard way AI agents call tools |
