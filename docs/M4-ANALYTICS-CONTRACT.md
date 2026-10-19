# M4 contract: the analytics suite

Decided with the PO on 2026-10-19.

**Source:** the PO's spec, "CRM Visual Analytics & ML Engine Specification" v1.0, 3 pages.

**Aim:** make Analysis a complete suite: preparation and models in the style of Dataiku, and visual
workbooks in the style of Oracle Analytics DV. Everything already true stays true:

- numbers come from code;
- comparisons and models carry *verified* or *not verified*, and a model is verified only against
  a baseline on held-out data;
- customer text is data;
- workspaces are isolated;
- the UI uses tokens only, in Helvetica, light and dark.

## PO decisions

1. **Activities and stages.**
   - **Stage:** a rep sets where a deal is, and every stage change is recorded with its date.
   - **Activity panel:** on each deal, the rep logs calls, emails and meetings by hand.
   - **Timeline:** these show as a vertical chronology of events, together with the notes,
     meetings, stage changes and tasks.
   - **Mailbox (Gmail and Outlook only):** a mailbox can be connected so that emails are linked to
     open deals by similarity. Manual linking is always possible.
2. **GenAI blocks:** opt-in, like the meeting AI pass. Summaries are labelled AI. Extracted action
   items become *suggested* tasks that quote their sentence, and a person accepts them.
3. **Charts:** Apache ECharts, pinned and integrity-checked, loaded only on analysis pages.
4. **Scoring:** "Run now" only, no scheduler. A scheduler comes with hosting (M3b).

## Information architecture

Analysis becomes four tabs:

| Tab | What | Inspired by |
|---|---|---|
| **Flows** | today's canvas: sources, preparation and model blocks | Dataiku Flow and recipes |
| **Workbooks** | visual canvases: drag fields onto charts, filters, cross-filtering, dashboards, *Explain* | Oracle Analytics DV |
| **Models** | saved models with their metrics and verdicts; "Score now" on the open pipeline | Dataiku Lab |
| **Insights** | today's stats scan: verified findings, not-verified reasons | DataForce's own |

## Spec → blocks (✓ exists, + new, ◐ partly)

| Spec block | State | Notes |
|---|---|---|
| Raw sources (deals, notes, calls) | ◐ | Deals, accounts, contacts, companies, meetings and themes exist. New CRM tables: activities, stage events, tasks. |
| Relational join | ✓ | `join` block, with the join-inflation guard. |
| Fuzzy deduplication | + | Levenshtein and Jaro-Winkler with a threshold. It outputs groups and a master per group. It never merges CRM records; merging is a separate, confirmed CRM action later. |
| Time elapsed and aging | ◐ | `days_between` exists. New: "days since" relative to today, a stagnation flag, and last-activity and last-meeting columns. |
| Weighted forecast | + | amount × stage probability. The probabilities are part of the block's config (defaults 10/20/40/60/100/0 %). |
| Discretize / binning | ✓ | The `bucket` op of the columns block. |
| Account engagement score | + | A weighted formula over activity counts in a window, with a decay or penalty for no touchpoint in N days. Needs activities. |
| Notes summarizer (LLM) | + | Opt-in GenAI. Text goes to the workspace's model, with caps; the output is labelled AI. |
| Action item extractor (LLM) | + | Opt-in GenAI. Suggested tasks, each with the exact sentence as evidence. |
| Deal velocity index | + | Needs stage events: the mean time per stage against the workspace benchmark, giving a fast-track or stagnant flag. |
| Rep touchpoint ratio | + | (meetings × 3) / outreach actions, from activities. |
| Domain email parser | ◐ | Regex domain and a free-webmail list, on any text column. **No MX lookup** (that would be a network call per row), and never on sealed enriched emails. |
| Window lag comparison | + | lag, lead, rolling and rank over a partition and an order (QoQ growth per rep). |
| Opportunity density | ◐ | The ratio op exists; a template adds the scale step. |
| Train/test split | ◐ | Random exists. New: chronological split on a date column. |
| K-means, logistic, linear | ✓ | Verified against baselines on held-out data. |
| SVM / SVR | + | scikit-learn is already a dependency. The same verified-vs-baseline rule applies; RBF and linear kernels. |
| Scoring block | + | Applies a **saved model**, stored as plain parameters (never pickle), to new rows; "Score now" in Models. |
| Reports (self-service) | + | Workbooks, below. |

## Data model (migration 0009, tech lead)

| Table | Columns (all with `workspace_id`, RLS enabled like the others) |
|---|---|
| `deal_stage_event` | deal_id (cascade), from_stage, to_stage, changed_at, changed_by (user, set null), source (manual / import / demo / system) |
| `activity` | account_id (cascade), deal_id (set null), kind (call / email / meeting / other), direction (inbound / outbound / null), occurred_at, subject (≤ 300), body (≤ 10,000, nullable), author_user_id, source (manual / mailbox / import / demo), external_ref (mailbox message id; unique per workspace and source) |
| `activity_participant` | activity_id (cascade), contact_id (cascade): who took part. Erasing a contact removes the link. |
| `task` | deal_id (set null), account_id (cascade, nullable), title (≤ 300), due_on, status (open / done / dismissed), owner_user_id, source (manual / ai_suggested), evidence (jsonb: quote and its origin), done_at |
| `workbook` | name, spec (jsonb: canvases, visualizations, filters, layout), created_by, updated_at |
| `saved_model` | name, flow_id and node_id (provenance), kind (linear / logistic / svm / svr / kmeans), params (jsonb), features (jsonb), metrics (jsonb), status (verified / not_verified / exploratory) |

Mailbox tables (`mailbox_connection`, sealed tokens like TamTam) come with phase 2.

## Workbooks (Oracle DV style, ECharts)

- **Data:**
  - Any CRM table or any flow node output.
  - Queries run **server-side** through `POST /api/w/{ws}/viz/query` (source, fields, aggregations, filters, sort, limit). The server aggregates with pandas on the same loaders and limits as flows, and returns aggregated rows, never the raw table beyond the caps.
- **Building a chart:**
  - Drag fields onto slots: values, category, color, size, rows/columns, filters.
  - Chart types: bar (grouped or stacked), line, area, scatter, pie and donut, heatmap, treemap, funnel (pipeline), KPI tile, table, pivot.
  - A map waits for a French-regions shape file.
- **Canvas:**
  - A grid of visualizations with canvas filters.
  - **Cross-filtering:** clicking a bar or slice filters the other visualizations on the canvas.
  - Several canvases per workbook; save, rename and duplicate; light and dark.
- **Explain** (DV's "Explain", with DataForce's honesty): for a measure and an attribute, run the stats engine and show the verified findings first, with the not-verified ones collapsed with their reasons.
- **Honesty and limits:**
  - Every number shown is exact and comes from the query.
  - Aggregates computed from a capped source say so ("first 200,000 rows").

## Phases and owners

**Phase 1** (parallel, disjoint files):

- **A, activity and pipeline foundation:**
  - services and routes for stage events (set stage with a date), activities (CRUD and participants), tasks (CRUD, accept or dismiss);
  - the deal page: a stage control, an activity panel and a vertical timeline merging stage events, activities, notes, meetings and tasks;
  - the account page timeline;
  - the new CRM tables exposed to flows (`activities`, `stage_events`, `tasks`);
  - synthetic stage histories, activities and tasks in the generator (Test data).
- **C, flow blocks batch 1:**
  - fuzzy dedup, aging and stagnation, weighted forecast, window/lag;
  - chronological split, SVM/SVR, domain parser;
  - templates: "Weighted pipeline forecast", "Stalled deals", "Duplicate accounts", "QoQ growth per rep".
- **D, workbooks:**
  - the Analysis tabs;
  - workbook CRUD, the viz query endpoint, the ECharts builder, the canvas grid, cross-filtering, KPI, table and pivot, and Explain.

**Phase 2:**

- **C2:**
  - deal velocity index, engagement score, touchpoint ratio;
  - saved models with the Models tab and "Score now";
  - the GenAI blocks (opt-in).
- **B, mailbox:**
  - Gmail (Google OAuth) and Outlook (Microsoft Graph), PKCE with a loopback redirect, read-only scopes;
  - metadata first (from, to, date, subject, snippet);
  - a local similarity match to open deals (participants against the account's contacts and domain, plus text similarity to deal and account names);
  - suggested links that the rep confirms, and a manual "link to deal".
  - Bodies are fetched and stored only when an email is linked, and capped.
  - The PO must register an OAuth client with Google and with Microsoft; we provide the steps.

**Phase 3:**

- security reviews (new data, mailbox OAuth, viz query, GenAI);
- a methods review of the new ML (SVM, scoring, chronological split, engagement and velocity formulas);
- README, DECISIONS and the build report.

## Definition of done (every phase)

- tsc, vitest, build, ruff and the full pytest suite are green;
- light and dark checked in the browser;
- no raw hex outside tokens.css;
- erasure and deletion cover every new table that holds people's data;
- no pickle;
- caps on every query;
- a report of at most 200 words per agent.
