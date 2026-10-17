# M2b contract: job titles, org-chart proposals, meeting transcripts and themes

This is the "next step" of the plan, `docs/DECISIONS.md` §B and §C, started on 2026-10-17.

- **Titles.** Normalise every contact title to a *function* and a *seniority*. A French/English dictionary does it by code. Only titles it doesn't know go to the AI, once; the result is cached and flagged.
- **Org chart.** A manager link has three origins:
  - **manual**: certain, drawn solid;
  - **rule**: inferred from the same account and normalised titles;
  - **meeting**: proposed from a sentence in a transcript, with the exact excerpt kept.

  Rule and meeting links are **proposals**, never shown as fact until a user accepts them. Ambiguous cases are listed, never guessed. Meetings also yield *champion*, *blocker* and *decision-maker* signals, which are also proposals.
- **Transcripts and themes.**
  - A rep imports meeting transcripts (PDF, Markdown or text) on an account, optionally tied to a deal.
  - Themes and objections are found by **code**, locally: TF-IDF and NMF, with no text leaving the computer.
  - They are counted by code. The AI only **names** them, from their top terms and exact excerpts.
  - Flows can relate themes to deal outcomes through the stats block, with the usual gates.

All earlier rules hold:

- numbers come from code;
- "not verified" is never shown as a fact;
- third-party data is kept to a minimum;
- secrets are sealed or kept in env;
- local only;
- the request guards apply;
- workspace isolation;
- no eval or pickle.

## 0. Who owns what

**Tech lead** (do not edit; ask in your report):

- `app/config.py`, `app/db/models.py`, `app/domain/*`
- `alembic/versions/0006_m2b.py`
- `app/api/{schemas,deps,errors,main}.py`
- `frontend/src/App.tsx`, `frontend/src/api.ts`
- this file

| Agent | Owns |
|---|---|
| **T: titles** | `app/titles/**`; `app/services/titles.py`; the auto-classification hook in `app/services/contacts.py` (create and update only); `app/api/routes/titles.py`; `app/api/schemas_titles.py`; `tests/titles/**`; `tests/api/test_titles.py` |
| **O: org proposals** | `app/orgchart/**`; `app/services/org_proposals.py`; `app/api/routes/orgchart.py`; `app/api/schemas_orgchart.py`; the org-chart endpoint in `app/api/routes/crm.py` (fill the new `OrgChartNode` fields); the `reports_to_proposal_id` reset in `app/services/contacts.py` `set_reports_to` (coordinate with T: T owns create/update, O owns `set_reports_to`); `tests/orgchart/**`; `tests/api/test_orgchart.py` |
| **M: transcripts and themes** | `app/transcripts/**`; `app/themes/**`; `app/services/{documents,themes}.py`; `app/api/routes/{documents,themes}.py`; `app/api/schemas_{documents,themes}.py`; the multipart allow-list in `app/api/security.py` (add the document upload route, keeping every guard); the CRM tables `meetings`, `meeting_themes`, `deal_theme_flags` and the title columns on `contacts` in `app/flows/sources/crm.py` and the catalog; `tests/transcripts/**`; `tests/themes/**`; `tests/api/test_{documents,themes}.py` |
| **D2: demo** | `app/demo/**` (roles truth, removed links, transcripts, the loader calling M's service); `tests/demo/**`; `tests/e2e/**` (only where partial org charts change expectations) |
| **U1: org chart and titles UI** | `frontend/src/orgchart/**`, `frontend/src/titles/**`, `frontend/src/pages/{Contacts,ContactDetail,OrgChart}.tsx` |
| **U2: meetings and themes UI** | `frontend/src/meetings/**`, plus the "Themes vs win rate" template in `frontend/src/flows/FlowsPage.tsx` (only the `TEMPLATES` list). It may read, not edit, the flows API module |

The slots already exist:

- **Routes and nav**: `meetings`.
- **Placeholders**: `src/orgchart/OrgChartPanel.tsx` (used by `AccountDetail`), `src/meetings/MeetingsPanel.tsx` (used by `AccountDetail` and `CompanyDetail`), `src/meetings/MeetingsPage.tsx`.
- **Backend routers**: `routes/{titles,orgchart,documents,themes}.py`.

## 1. Data model (migration 0006, applied)

- **`contact`**: gains `title_source` (dictionary / llm / manual), `title_flag` (text) and `reports_to_proposal_id`. The last is a foreign key to `org_proposal`, set when a validated link came from a proposal; a manual edit clears it.
- **`title_cache`**: `(workspace, normalized_title)` is unique; it holds function, seniority, confidence, provider and model.
- **`org_proposal`**: account, contact, kind, manager (null when ambiguous; `candidates` then lists contact ids), origin, rule, `evidence` (JSON), status (proposed / ambiguous / accepted / rejected), run, decided_at and decided_by.
- **`document`**: account, **deal** (optional), kind=transcript, title, meeting_date, file_name, media_type, sha256, size, **text** (sanitised, the only copy kept), n_chars, language, source, created_by.
- **`document_chunk`**: seq, speaker as written, `contact_id` or `user_id` when matched, `char_start` and `char_end` into `document.text`, and text.
- **`theme`**: run, seq, label, description, kind, named_by (llm / keywords), top_terms, n_chunks, n_documents, n_accounts. **`theme_assignment`**: (theme, chunk, weight).
- **Enums**: `TitleSource`, `ProposalKind`, `ProposalOrigin`, `ProposalStatus`, `ThemeKind`; `RunKind` gains `title_normalize`, `org_rules` and `theme_analysis`.
- **Settings**: `titles_max_llm_calls_per_run`, `transcript_max_bytes` (5 MB), `transcript_max_pages`, `transcript_max_chars`, `themes_default_k` (8).
- **API contract additions** (`app/api/schemas.py`):
  - `ContactRead` gains `title_source` and `title_flag`;
  - `OrgChartNode` gains `title_function`, `title_seniority`, `link_origin`, `link_proposal_id` and `signals`.

## 2. Shared rules

The rules of M2a §2 hold:

- services are session-first and workspace-scoped, with no SQL strings;
- your own `schemas_<area>.py`, with `extra="forbid"` on bodies;
- never log text, names, keys or row data;
- tests never touch the network;
- do not write to the dev DB, and do not stop the server on 8800.

Transcript text is **untrusted**. It reaches the AI only wrapped by `app/llm/untrusted.py`, and it is rendered as text in the browser.

## 3. Titles (T)

**Normaliser** (`app/titles/normalize.py`, a pure function):

1. Lowercase and strip accents.
2. Unify `.`, `-`, `/`, `&` and `,` to spaces, and collapse spaces.
3. Expand abbreviations: `dir`→directeur, `resp`→responsable, `dg`→directeur general, `pdg`→president directeur general, `daf`→directeur administratif et financier, `drh`→directeur ressources humaines, `dsi`→directeur systemes information, `vp`→vice president, `svp`→senior vice president, `sdr`→sales development representative, `bdr`→business development representative, `ae`→account executive, `kam`→key account manager.
4. Fix typos per token: for unknown tokens of 5 or more characters, use the closest vocabulary word (difflib, cutoff 0.85); a token split by a stray space ("accoun texecutive") is retried glued.

The pinned demo typos must all resolve.

**Dictionary** (`app/titles/dictionary.py`): FR and EN keywords to function and seniority.

| Field | Values and keywords |
|---|---|
| **functions** | `executive` (ceo, president, directeur general, founder/fondateur, managing director, gerant); `sales` (commercial, ventes/vente, sales, business developer/development, account executive/manager, ingenieur d affaires, charge d affaires, grands comptes, key account); `marketing` (marketing, cmo, communication, content, growth, brand); `finance` (cfo, financier/finance, daf, comptable/accounting, controle de gestion); `operations` (operations, logistique, supply chain, coo); `tech` (cto, technique, it, dsi, engineering, developpeur/developer, data); `hr` (rh, ressources humaines, hr, talent, recrutement) |
| **seniority** | `c_level` (chief, cxo acronyms, president, directeur general, daf, drh, dsi, founder, managing director); `vp` (vice president, vp); `head` (head of, directeur/directrice/director, *without* general); `manager` (manager, responsable, lead, chef de, team lead); `individual` (executive, ingenieur, charge, assistant, junior, representative, developer, consultant, specialist) |

**Rules.**

- The most specific match wins: "Chief Marketing Officer" is marketing / c_level, not executive.
- Two functions matched (e.g. "Directeur commercial et marketing") leave the function `unknown`, with the flag "ambiguous function: sales, marketing".
- A missing title gives unknown / unknown, with the flag "no title".
- A title with no match goes to the AI, or gets the flag "unknown title".

**AI fallback** (`app/titles/ai.py`):

- One `generate_structured` call per **distinct** unknown normalised title, purpose `title_classification`, schema {function: JobFunction, seniority: Seniority, confidence: low | medium | high}.
- The title is sent wrapped as untrusted text. The provider is the workspace credential (`app/services/llm_settings.py`, and `app/llm/registry.py` builders).
- Results are cached in `title_cache`, `title_source=llm`, with the flag "classified by AI (confidence X): check".
- Calls are capped by `titles_max_llm_calls_per_run`. With no AI configured, the title is left unknown with the flag "unknown title (no AI model configured)".
- Never send a person's name, only the title text.

**Service.**

- `normalize_workspace(session, ws_id, *, use_ai, settings) -> summary` updates every contact except those with `title_source == manual`, and records `Run(title_normalize)`.
- `classify_contact_title(contact)` uses the dictionary only, and is called by the contacts service on create and when `title` changes.

**Endpoints** (under `/api/w/{ws}`):

| Method and path | Body → response |
|---|---|
| POST `/titles/normalize` | {use_ai: bool = true} → {run_id, n_contacts, by_source: {dictionary, llm, manual, unknown}, n_flagged, llm_calls, ai_configured} |
| GET `/titles/review?limit=` | → contacts that are flagged or unknown first: list of {contact_id, full_name, account_id, account_name, title, function, seniority, source, flag} |
| PUT `/contacts/{id}/title-class` | {function, seniority} → the same item; `source` manual, flag cleared |
| GET `/titles/preview?title=` | → {normalized, function, seniority, source: "dictionary" or "none", flag, matched}, dictionary only, never the AI |

**Tests:**

- every `ROLE_TITLES` variant of `app/demo/names.py` maps to the expected class (§6);
- typos;
- ambiguity;
- the cache is used on the second run;
- the call cap;
- no AI configured;
- manual is never overwritten;
- names are never sent to the AI (inspect the fake provider's prompts).

## 4. Org-chart proposals (O)

**Ranks**: c_level 4 > vp 3 > head 2 > manager 1 > individual 0.

The rules run per account and consider contacts that have **no manager link** and a known function and seniority.

| Rule | When | Proposal |
|---|---|---|
| **R0 root** | exactly one executive c_level contact in the account | that contact is the root |
| **R1 `c_level_to_ceo`** | another c_level contact (CFO, CMO, CTO…) | reports to the root |
| **R2 `next_level_in_function`** | a contact of function F, rank r | the contacts of F with the **smallest rank strictly above r**: one → propose; several → ambiguous with the candidates; none → R3 |
| **R3 `senior_to_ceo`** | no one above in F, and rank ≥ head | reports to the root (if there is one) |
| | no one above in F, and rank < head | no proposal |

**Never** propose:

- across accounts;
- a cycle, checked against the manual links and the accepted proposals;
- a pair that was previously rejected;
- for a contact with a manual link.

Evidence for a rule proposal: {contact_title, manager_title, contact_class, manager_class, explanation (a one-line sentence naming the rule)}.

**Meeting extraction** (`app/orgchart/meetings.py`, deterministic regular expressions over chunks whose speaker matched a contact):

| Kind | Patterns |
|---|---|
| reports_to (EN) | "I report to {NAME}", "my (boss\|manager\|line manager) is {NAME}", "{NAME} is my (boss\|manager)" |
| reports_to (FR) | "je reporte à {NAME}", "mon (manager\|n+1\|responsable\|chef) (c'est\|est) {NAME}", "{NAME} est mon (manager\|n+1\|chef\|responsable)", "je suis sous la responsabilité de {NAME}" |
| champion | first person: EN "I'll (push\|champion\|sponsor) (this\|it)", FR "je vais (pousser\|porter\|défendre) (le dossier\|le projet\|ça)" |
| blocker | about {NAME}: EN "{NAME} is (against\|not convinced\|blocking)", FR "{NAME} (bloque\|est contre\|n'est pas convaincu(e)?)" |
| decision_maker | EN "{NAME} (makes\|will make\|has) the (final )?(decision\|call)", FR "c'est {NAME} qui (décide\|valide\|signe\|tranche)" |

- `{NAME}` must resolve to exactly one contact of the same account (full name, first + last, or a unique first name; accent and case insensitive). An unmatched name gives no proposal.
- The speaker is the subject for first-person sentences.
- Evidence: {document_id, chunk_id, excerpt (the exact sentence, a substring of the chunk), speaker, char_start, char_end}. It is verified by comparing it against `document.text[char_start:char_end]`.
- A statement contradicting an existing manual link is still proposed, with `rule="contradicts_current_link"`.

**Endpoints** (under `/api/w/{ws}`):

| Method and path | Body → response | Notes |
|---|---|---|
| POST `/orgchart/propose` | {account_id: uuid \| null, origins: ["rule", "meeting"]} → {run_id, created, by_kind, ambiguous} | a rerun replaces this scope's proposed and ambiguous proposals; accepted and rejected ones are kept |
| GET `/accounts/{id}/org-proposals?status=` | → list of ProposalOut {id, kind, origin, rule, status, contact {id, full_name, title}, manager {…} \| null, candidates [{…}], evidence, created_at, decided_at} | |
| POST `/org-proposals/{id}/accept` | {manager_id?: uuid (required to pick among candidates), by_id?} → ProposalOut | reports_to: goes through `contacts.set_reports_to` (cycle checks) and sets `reports_to_proposal_id`. Signals: the status only |
| POST `/org-proposals/{id}/reject` | {by_id?} → ProposalOut | |

The existing GET `/accounts/{id}/org-chart` fills `link_origin` (manual, or the origin of `reports_to_proposal_id`), `link_proposal_id`, `signals` (accepted signals) and the title class.

**Tests:**

- each rule;
- ambiguity;
- no cycle;
- no cross-account proposal;
- no re-proposal after a rejection;
- a manual link is never overwritten by a run;
- accept and reject;
- every pattern (FR and EN) and an unmatched name;
- excerpt offsets verified;
- workspace isolation.

## 5. Transcripts and themes (M)

**Import.** POST `/api/w/{ws}/accounts/{id}/documents` (multipart: `file`, plus optional `title`, `meeting_date`, `deal_id`; the deal must belong to that account) → `DocumentOut`.

- `.pdf`, `.md`, `.markdown` and `.txt` only; the content is sniffed.
- At most `transcript_max_bytes`.
- **PDF** (pypdf 6.19):
  - refuse encrypted files;
  - at most `transcript_max_pages`;
  - extract page by page with a time budget (30 s) and the char cap.
- **Text**: UTF-8, then Latin-1.
- Remove control characters and lightly strip Markdown syntax (headings, emphasis), **keeping the character offsets of the stored text**.
- The original file is not stored.

**Parsing** (`app/transcripts/parse.py`, pure):

- Speaker turns are lines matching `Name: text`, `**Name**: text`, `[00:12:03] Name: text` or `Name (Company): text`. A line without a speaker continues the current turn.
- Speakers resolve to an account contact (the same name matching as §4) or to an `app_user` (rep, by display name), or stay unmatched.
- **Chunks**: one per turn; turns over 1,200 characters are split at sentence ends. Offsets index `document.text`.
- **Language** (fr / en / mixed): a stop-word ratio heuristic.

**Service.** `add_document(session, ws_id, *, account_id, title, text, meeting_date=None, deal_id=None, file_name=None, media_type=None, size_bytes=None, source="manual", created_by_id=None) -> Document` parses and chunks. The demo loader calls it.

**Other endpoints** (under `/api/w/{ws}`):

| Method and path | Body → response |
|---|---|
| GET `/accounts/{id}/documents` | → DocumentOut list |
| GET `/companies/{id}/documents` | → DocumentOut list (every account of the company) |
| GET `/documents?limit=&offset=` | → `Page[DocumentOut]` |
| GET `/documents/{id}` | → DocumentDetail (adds `text`, the chunks {id, seq, speaker, contact_id, user_id, char_start, char_end} and `chunk_themes` [{chunk_id, theme_id, label}] from the latest run) |
| DELETE `/documents/{id}` | → 204 (hard delete; it is an imported file, not append-only) |

DocumentOut: {id, account_id, account_name, deal_id, title, meeting_date, file_name, n_chars, n_chunks, language, speakers: [{name, contact_id, user_id}], theme_labels (latest run), created_at}.

**Themes.** POST `/themes/run` {k?: 2..30 (default `themes_default_k`), speakers: "customer" (default) or "all", use_ai: bool = true} → ThemeRunOut.

**Method** (`app/themes/discover.py`, pure, deterministic):

- **Input**: chunks whose `contact_id` is set (the customer side), or all chunks when `speakers=all` or when there are no customer chunks. Capped at 20k chunks.
- **Vectorise**: `TfidfVectorizer(strip_accents="unicode", lowercase, ngram_range=(1,2), min_df=2, max_df=0.6, stop_words=` a FR+EN list in code `)`.
- **Factorise**: `NMF(n_components=k, init="nndsvda", random_state=42, max_iter=400)`.
- **Assign**: normalise each row of W to sum to 1; a chunk goes to the argmax theme if its weight is ≥ 0.15, otherwise it stays unassigned. Themes with fewer than 3 chunks are dropped and reported.
- **Describe**: top 10 terms from H. Excerpts: the 3 highest-weight chunks, each cut to the sentence containing the most top terms (an exact substring).
- **Count**: n_chunks, n_documents, n_accounts.
- **Naming**: with the AI configured and `use_ai`, one `generate_structured` call per theme, purpose `theme_naming`, schema {label ≤ 60, description ≤ 240, kind: ThemeKind}. The input is the top terms plus the 3 excerpts wrapped as untrusted. Strip from the output any digits not present in the terms. Otherwise: `label = " · ".join(top 3 terms)`, `named_by=keywords`, kind `other`.
- **Record**: `Run(theme_analysis)`; themes and assignments are stored, and the latest run is the current one.

ThemeOut: {id, seq, label, description, kind, named_by, top_terms, n_chunks, n_documents, n_accounts, excerpts: [{chunk_id, document_id, account_id, account_name, meeting_date, speaker, text}], status: "exploratory"}.

ThemeRunOut: {run_id, created_at, k, n_chunks_used, n_unassigned, dropped_themes, themes}.

GET `/themes/latest` → ThemeRunOut, or 404.

**Flows CRM tables** (add them to the catalog):

| Table | Columns |
|---|---|
| `meetings` | document_id, account_id, account_name, company_name, deal_id, meeting_date, title, n_chunks, language |
| `meeting_themes` | document_id, account_id, account_name, company_name, deal_id, meeting_date, theme, theme_kind, n_chunks: one row per (document, theme) with at least one assigned chunk |
| `deal_theme_flags` | deal_id, deal_name, account_name, segment, lead_source, stage, is_closed, is_won, amount_eur, theme, theme_kind, **mentioned** (bool: one of the deal's documents has a chunk assigned to the theme): one row per (deal, theme of the latest run) |
| `contacts` | gains `title_function` and `title_seniority` |

**Tests:**

- PDF: valid, encrypted, too many pages, too many characters, not a PDF;
- Markdown and Latin-1 text;
- speaker parsing (every format);
- name matching;
- chunk offsets;
- deterministic themes: planted synthetic chunks with distinct vocabularies are recovered;
- keyword naming;
- AI naming with the fake provider: untrusted wrapping, digit stripping;
- the three flows tables;
- workspace isolation;
- erasing a contact keeps the chunks but nulls `contact_id`; erasing an account deletes its documents.

## 6. Demo (D2)

All additions use **separate RNG streams**: `[seed, 103]` for the removed links and `[seed, 104]` for the transcripts. Accounts, deals, the stats ground truth and every M1 calibration number must stay identical; add a test that compares the deal rows.

**Roles truth.**

- `DemoContact` gains `role` (the `ROLE_TITLES` key). It is not loaded into the CRM; it goes in `GroundTruth.m2.roles`.
- Expected classes for evaluation (function, set of accepted seniorities):

| Role | Function | Accepted seniority |
|---|---|---|
| ceo | executive | {c_level} |
| vp_sales | sales | {vp, head} |
| cmo | marketing | {c_level, head} |
| cfo | finance | {c_level, head} |
| head_sales | sales | {head, manager} |
| ae, sdr | sales | {individual} |
| marketing | marketing | {manager, individual} |
| ops | operations | {manager} |

**Removed links.**

- In 50 % of accounts (stream `[seed, 103]`), every non-root contact loses its manual `reports_to` in the CRM.
- The true tree goes in `m2.org` (contact key → manager key), and the affected keys go in `m2.links_removed`.
- The remaining accounts keep their complete trees.

**Transcripts.**

- About 160 meetings, each tied to a deal: mostly closed deals, some open. The meeting date falls between the deal's creation and close dates. Each meeting has 6 to 16 turns between the deal owner (an app user) and 1 to 3 contacts of the account. 60 % are in French and 40 % in English.
- **Planted themes**, with consistent vocabulary:

| Theme id | Vocabulary | Planted effect |
|---|---|---|
| `price_objection` | trop cher, budget, prix, remise, too expensive, pricing, discount | in **65 % of meetings of lost deals** vs 20 % of the others, a stats effect to verify |
| `integration_need` | intégration, Salesforce, HubSpot, API, connecteur, sync | |
| `security_gdpr` | RGPD, sécurité, hébergement, GDPR, security, SOC 2, hosting | twice as frequent in enterprise |
| `competitor_vendara` | "Vendara", an invented competitor | |
| `timing_freeze` | gel des budgets, pas avant le prochain trimestre, budget freeze, next quarter | |

  Each meeting also has neutral turns: agenda, greetings, next steps.
- **Org statements.** For about 40 % of the contacts with a removed link, one meeting has them say "Je reporte à {manager}" / "I report to {manager}", using the true manager. Add 5 decoys naming people who are not contacts ("I report to our board"): they must produce nothing.
- **Signals.** About 30 % of the accounts with meetings have a champion sentence, 15 % a blocker sentence and 25 % a decision-maker sentence, each recorded in `m2.meetings[].signals`.
- **Loader.** Insert the documents through M's `documents.add_document` (`source="demo"`) with `deal_id`.

Update `tests/demo` and `tests/e2e` where the partial org charts change expectations: trees must remain valid.

## 7. Frontend

### 7.1 Org chart and titles (U1)

**`OrgChartPanel`** (replaces the plain tree in `AccountDetail`):

- **Tree styles**:
  - a manual link is solid;
  - a link validated from a proposal is solid, with a small "from rule" or "from meeting" badge; clicking it shows the evidence;
  - **proposed links** are drawn dashed or dotted, labelled "suggested", and never as fact.
- **Signal badges** on nodes: champion, blocker, decision maker (accepted only).
- **"Suggested links" list.** Each item shows: contact → manager, an origin badge, the evidence (rule: both titles and the explanation; meeting: the quoted excerpt as text, with the meeting date and title), and Accept / Reject.
  - Ambiguous items show radio buttons for the candidates.
  - Signal proposals appear in the same list.
- **"Suggest links"** calls POST `/orgchart/propose` for this account.

**Titles.**

- **ContactDetail**: the normalised class (function · seniority), a source badge (dictionary / AI / manual) and the flag. "Change" sets it manually (PUT `title-class`).
- **Contacts list**: function and seniority columns, plus a "flagged only" filter.
- **Toolbar**: "Normalize titles" (POST `/titles/normalize`, with a "use AI for unknown titles" checkbox and an explanation that only the title text is sent) and a "Review titles" view (GET `/titles/review`) with inline manual fixes.

### 7.2 Meetings and themes (U2)

**`MeetingsPanel`** (account or company scope):

- The list: date, title, deal, theme chips and speakers.
- **Upload**: a multipart `fetch` with `X-DataForce: 1` and no manual Content-Type. Fields: file, title, date, an optional deal (the account's deals), and an account picker in company scope.
- **View**: the transcript rendered **as text**, by speaker turn, with a chunk-level theme highlight through CSS classes and a legend.
- Delete, with a confirmation.

**`MeetingsPage`** (nav "Meetings"):

- All meetings, paginated.
- A **Themes** section:
  - "Find themes": choose k, toggle "use AI to name themes" (explaining that only the top words and 3 short excerpts are sent).
  - **Theme cards**: label, kind, a named-by badge, counts labelled "exact count", top terms, and excerpts with their meeting and account. The excerpts are exact quotes from the transcripts.
  - Every card carries the line "Exploratory: themes describe, they do not prove".
  - A **"Test against win rate"** button creates a flow from a new template, "Themes vs win rate (theme X)" (dataset `deal_theme_flags` → filter `theme == X` and `is_closed` → stats group_by `mentioned`, outcome `is_won`, rate), and opens it.

Add that template to `FlowsPage` `TEMPLATES` (parameterised by the theme label).

## 8. Definition of done

As in M2a §8:

- ruff check and format clean, or `npm run typecheck`, `npm test` and `npm run build` for the frontend;
- your tests pass, and so does the full suite (failures in other agents' unfinished files are named);
- the only new dependency is pypdf, already locked;
- a report of at most 200 words;
- **no git commits**.
