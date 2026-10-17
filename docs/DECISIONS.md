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
  - about 200 deals with planted effects;
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
- **Measured reliability [build, 2026-10-17, after the fix pass]:**
  - Two independent 100-seed sweeps were run, on seeds 1000–1099 and 3000–3099, at 500 bootstrap resamples.
  - Detection of each planted effect: inbound win rate 93–96%; enterprise and SMB cycle 99–100%; enterprise and SMB amount 97–99%.
  - Planted datasets with a false positive: 0–1%.
  - Planted datasets where the check fails: 8–10%. Almost all of these are a *missed* planted effect, mostly inbound, because about 55 inbound deals is close to the minimum for a verdict. They are not false alarms.
  - Noise datasets with any verified finding: 1%.
  - **How to read it.** The engine errs on the side of silence: about 1 run in 10 misses a real effect, and about 1 in 100 shows a spurious one. The BH correction keeps the expected *share* of false findings among the reported ones at 5% or below. It does not promise "never a false finding", so the product never says that.
  - The committed tests assert these rates on 50 fixed seeds, so they are deterministic and never flaky.
  - The first draft of this section claimed "about 3%". That figure came from a lenient checker and was corrected.
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

## H. Open
1. Confirm whether the minimal CRM scope is enough (the note says "to confirm").
2. TamTam MCP: a real account and token, and its tool list, to replace the assumptions.
3. LLM key: the PO adds `GEMINI_API_KEY` to `backend/.env`. M1 doesn't need it; M2 (title classification, theme naming) does.
