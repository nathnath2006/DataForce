# Backend and data performance audit

Lens: where the backend and the data layer hurt first as data grows. Measured, not guessed.
Read-only on the repo. Scripts are in the session scratchpad (`.../scratchpad/audit/`), not in the repo.

## Method and machine

- Machine: Apple M2, 8 cores, 8 GB RAM, macOS. Python 3.13 venv, PostgreSQL 16.15 + pgvector in Docker (`dataforce-db`, port 5433), `shared_buffers=128MB`, `work_mem=4MB`. Numbers are indicative (one laptop, warm cache, best of 2-3 runs).
- Dev app (`http://127.0.0.1:8800`, workspace `test-data`: 122 accounts, 755 contacts, 350 deals, about 250 meetings): GET only.
- Scaled data: test DB (`dataforce_test`), workspaces `perf-1x`, `perf-10x`, `perf-57x`, built with `app.demo.generator` + `load_dataset` (the generator caps at 20 000 deals, so the top size is 57x, not 100x).

| Workspace | Deals | Accounts | Contacts | Meetings | Chunks (workspace) |
|---|---|---|---|---|---|
| perf-1x | 350 | 122 | 771 | 160 | 1 750 |
| perf-10x | 3 500 | 1 225 | 7 970 | 1 600 | 17 792 |
| perf-57x | 20 000 | 7 000 | 45 659 | 9 143 | 100 482 |

- Endpoints were driven in-process with FastAPI `TestClient` (same code, same DB, no network). Services were timed directly. `EXPLAIN (ANALYZE, BUFFERS)` on the hot queries.
- Caveat: all three workspaces live in the same tables, so a "1x" query on an unindexed `workspace_id` scans all tenants' rows. That is the real multi-tenant behaviour (see PERF-B-02), but it means 1x numbers in the shared test DB are higher than on a DB holding only one small workspace.
- One run was discarded: a first pass of the GETs ran while the 57x loader was running and showed `/companies` at 1 s; re-run on a quiet machine it is 26 ms. Always measure on a quiet machine.
- Cleanup: the three `perf-*` workspaces were deleted at the end (the test DB is empty again).

## Top hotspots (summary)

| Id | What | 1x | 10x | 57x | Effort |
|---|---|---|---|---|---|
| PERF-B-01 | Stats scan: bootstrap loops over every row | 1.1-1.7 s | 10.9 s | 55.7 s | M |
| PERF-B-03 | Org proposals for the whole workspace: regex compiled per account | 1.9 s | 20.3 s | 162 s | S-M |
| PERF-B-02 | No `workspace_id` index on `contact`, `document`, `document_chunk`, `run`... | 6 ms | 22 ms | 75 to 114 ms (deep page) | S |
| PERF-B-04 | Workspace delete / bulk delete (unindexed FKs) | 14 s | over 60 s (timeout) | over 60 s | S |
| PERF-B-05 | DB connection held during LLM calls (pool 5+10) | not measured | | | S |

## Endpoint timings

### Dev app, 1x (GET, wall time including HTTP)

All main GET endpoints are fast: 4 to 120 ms.

| Endpoint | Time |
|---|---|
| accounts (default limit 200) | 33 ms (57 KB) |
| accounts?limit=100 | 14 ms |
| contacts?limit=100 | 21 ms |
| deals?limit=100 | 29 ms |
| companies | 55 ms |
| account detail | 17 ms |
| account org-chart | 66 ms |
| account documents | 8 ms |
| documents (page of 50) | 59 ms |
| quality | 33 ms |
| stats/pipeline | 16 ms |
| stats/scan/latest | 21 ms (63 KB) |
| themes/latest | 117 ms (slowest, PERF-B-08) |
| flows, flows/catalog | 12 ms, 8 ms |
| titles/review | 9 ms |
| lookup?q=a | 16 ms |

### Scaled, in-process GET (best of 3, ms)

| Endpoint | 1x | 10x | 57x |
|---|---|---|---|
| accounts (default 200) | 12.6 | 13.9 | 25.0 |
| accounts?limit=1000 | 12.1 | 44.4 | 45.4 |
| accounts offset near the end | 9.3 | 8.7 | 11.3 |
| contacts?limit=50 | 24.0 | 22.3 | 28.6 |
| contacts?limit=1000 | 59 | 62 | 82 |
| contacts offset near the end | 20.5 | 28.8 | 114.1 |
| contacts?q=ma | 18.6 | 29.4 | 78.8 |
| deals?limit=1000 | 13.8 | 37.6 | 45.6 |
| deals offset near the end | 5.8 | 6.8 | 18.9 |
| deals?q=ar | 6.7 | 9.6 | 28.9 |
| companies | 13.2 | 25.6 | 39.3 |
| lookup?q=a | 16.6 | 27.5 | 45.6 |
| account org-chart | 8.7 | 12.3 | 13.2 |
| documents (page 50) | 18.4 | 23.2 | 24.3 |
| documents?limit=200 | 31.3 | 41.7 | 46.4 |
| documents deep page (offset 7000) | 12.7 | 14.6 | 44.1 |
| quality | 13.9 | 28.8 | 71.1 |
| stats/pipeline | 6.8 | 9.2 | 11.8 |
| stats/scan/latest | 15.6 | 8.8 | 15.1 |
| themes/latest | 67.4 | 151.7 | 223.6 |
| titles/review | 14.0 | 15.9 | 46.6 |

Verdict: list and detail GETs scale acceptably up to 57x. They degrade linearly with the size of the whole table (seq scans), not catastrophically. The write-side and compute paths below are the problem.

### Heavy paths (in-process, seconds)

| Path | 1x | 10x | 57x | Note |
|---|---|---|---|---|
| `stats.scan()` pure (2000 resamples) | 1.1-1.7 | 10.9 | 55.7 | PERF-B-01 |
| `load_deal_rows` (SQL) | 0.03 | 0.06 | 0.22 | fine |
| `org_proposals.propose` one account | 0.03 | 0.03 | 0.05 | fine |
| `org_proposals.propose` whole workspace (rule + meeting, no AI) | 1.92 | 20.3 | 162.4 | PERF-B-03 |
| `run_themes` (k=12) | 0.30 | 1.74 | 5.41 | capped at 20 000 chunks and 20 000 sentences, so bounded |
| `themes_of_run` | 0.05 | 0.10 | 0.20 | N+1 per theme (PERF-B-08) |
| `build_context(company)` | 0.04 | 0.18 | 0.28 | PERF-B-07 (quadratic cap loop, bounded) |
| flow: dataset deals, 2 stats, group, split | 0.10 | 0.36 | 1.61 | fine; stats median block 36 ms, 271 ms, 1289 ms |
| `load_crm_table` all 7 tables | under 0.1 each | under 0.7 | under 1.5 | fine; deal_theme_flags 0.66 s and 1.46 s |
| `quality_report` | 0.02-0.03 | 0.03-0.04 | 0.03-0.09 | fine |
| `add_document`, 4 900 turns, 1.6 MB | | | 0.68 s | fine, 0.14 ms per turn |
| PDF child process (blank page) | 111 ms | | | spawn + pypdf import |

## Findings

### PERF-B-01 Stats scan is O(resamples x rows x comparisons) and runs on a request thread
- Where: `app/stats/intervals.py:52` (`_boot_medians`), called from `app/stats/engine.py:132` (`_compare`, 93 comparisons, 286 bootstrap calls) and `engine.py:195` (`scan`). Entry points: `POST /w/{ws}/stats/scan` (`app/api/routes/stats.py:41`), MCP `run_scan` (`app/agent/tools.py:717`), `compare_groups`.
- Measure: 1.1-1.7 s at 350 deals, 10.9 s at 3 500, 55.7 s at 20 000 deals. 93 findings and 32 groups at every size, so the output stays the same size while the cost grows linearly. cProfile at 1x: 87% in `_boot_medians`, of which 0.81 s is `ndarray.partition` (the median of a `(m, n)` fancy-indexed matrix, `values[idx]` with `rng.integers(0, n, size=(m, n))`).
- Cause: a classical percentile bootstrap that materialises resamples x n indices and takes `np.median` of each row. Also `engine.py:231` builds `rest` as a list comprehension per group (O(groups x rows), minor).
- Side effects: while the scan ran in a thread, other GETs stayed at p50 4 ms (numpy releases the GIL), so it does not freeze the server, but it holds one threadpool thread and one DB session for the whole time, and the MCP path holds a process-wide `_SCAN_LOCK` meanwhile. At 57x the request would also exceed the default `db_statement_timeout_ms` window for no good reason (the timeout is per statement, so it does not fire, but the HTTP client will time out).
- Fix: (a) compute the bootstrap CI of a median analytically from order statistics: after sorting, the bootstrap median's rank is distributed as a binomial draw, so a CI costs O(n log n) once plus O(resamples log n) instead of O(resamples x n); for the difference of two medians draw ranks independently per side. (b) Short of that: cap the bootstrap sample (for example resample from at most 5 000 rows), or drop `stats_bootstrap_resamples` adaptively. (c) Move the scan to a background job (the `Run` row already exists: start the run, return 202, poll `GET /stats/scan/latest`). Effort: M for (a), S for (b), M for (c).

### PERF-B-02 Missing indexes: `workspace_id` is not indexed on the big tables
- Where: `app/db/models.py`. Present: `ix_account_ws_name`, `ix_deal_ws_stage`, `ix_contact_account`, `ix_document_account`, `ix_document_chunk_document`. Absent:
  - `contact(workspace_id, full_name, id)` (list order and quality);
  - `document(workspace_id, meeting_date)` (documents list, `count_documents`);
  - `document_chunk(workspace_id)` and a trigram index on `document_chunk.text`;
  - `run(workspace_id, kind, started_at DESC)`;
  - `theme_assignment(workspace_id)` and `note(workspace_id)` (small today).
- Measure (57x, EXPLAIN ANALYZE, with the candidate indexes created inside a rolled-back transaction):

| Query | Before | After |
|---|---|---|
| contacts, page at offset 42 000 (sort of 42 050 rows) | 74.5 ms (114-129 ms sort inside) | 8.3 ms |
| contacts, first page | 6.0 ms | 0.03 ms |
| documents list (ws, `meeting_date DESC`) | 1.6 ms (sort 19 ms) | 0.02 ms |
| latest scan or theme run for a workspace | 2.6 ms | 0.01 ms |
| MCP `_prune` | 1.9 ms | 0.01 ms |
| `search_text` ILIKE `%budget%` over chunks | 46 ms (and 214-263 ms through the MCP tool, which also counts and orders) | 3.0 ms with `pg_trgm` GIN (the extension was creatable) |

- Cause: every workspace-scoped query seq-scans all tenants' rows and sorts. Cost is proportional to the whole table, so a small workspace pays for a big neighbour. `Run` is the worst: it stores JSONB scan reports (about 60 KB each) and every MCP call does a `DELETE ... OFFSET 5000` prune plus every page load calls "latest run" (`app/api/routes/stats.py:20`, `app/services/themes.py:53`, `app/flows/sources/crm.py:_latest_run_id`). Run table in my test: 65 290 rows, 11 MB; MCP `record_call` (two inserts + prune) 7 ms there, growing linearly with the total number of runs.
- Fix: one Alembic migration adding the indexes above plus `CREATE EXTENSION pg_trgm` and a GIN trigram index on `document_chunk.text`, `contact.full_name`, `contact.title`, `account.name`, `account.domain` (these power the `ilike '%q%'` search that today seq-scans: contacts?q=ma is 78.8 ms at 57x). Effort: S.

### PERF-B-03 Org proposals for a whole workspace: regex recompiled for every account
- Where: `app/orgchart/meetings.py:446` (`_compile`, `lru_cache(maxsize=256)` keyed on `(src, names_key)`) called from `extract` (`meetings.py:487`) once per pattern per account (41 patterns); caller `app/services/org_proposals.py:180` (`propose`, loop at line 224) and route `POST /w/{ws}/orgchart/propose`.
- Measure: whole workspace 1.9 s (122 accounts), 20.3 s (1 225), 162 s (7 000), about 16-23 ms per account. cProfile at 10x: 31 647 `re.compile` calls, 42 s of 62 s profiled time, about 1.3 ms each. The cache key contains the account's contact names, so it never hits across accounts, and 256 slots are far fewer than 41 x accounts. About 6.5 SQL statements per account (7 918 statements for 1 225 accounts, 5.6 s of lock waits in `_lock_org_chart` in the profile).
- Side effects: the loop is pure Python, so it holds the GIL: probe GETs went from p50 4.7 ms to 18.5 ms (max 110 ms) during the 10x run. One transaction for the entire loop, one `pg_advisory_xact_lock` per account (7 000 locks held at 57x; it passed here, but `max_locks_per_transaction=64` x `max_connections=100` is the shared limit, so this is a latent "out of shared memory" risk) and rows locked for minutes. The route is sync, so the client waits 20 s to 160 s.
- Fix: (a) compile each pattern once with a generic name capture (`(?P<name>[\w'-]+(?:\s+[\w'-]+){0,3})`) and look the match up in the alias dict, or pre-filter a chunk with a cheap keyword test before compiling anything; most chunks match nothing. (b) Skip accounts without documents before taking the lock and querying (for rules the lock is needed, for meetings it is not). (c) Batch by account groups and commit per batch; run as a background job with progress. Effort: S for (a) and (b), M for (c).

### PERF-B-04 Workspace and bulk deletion is very slow
- Where: `app/services/workspaces.py:41` (`delete_workspace`, cascade), FKs without an index: `contact.reports_to_id`, `contact.reports_to_proposal_id`, `document_chunk.contact_id`, `document_chunk.user_id`, `deal.owner_id`, `org_proposal.manager_id` / `run_id` / `decided_by_id`, `document.created_by_id` (`app/db/models.py`).
- Measure: `delete_workspace('perf-1x')` took 14.4 s (the table held 54 000 contacts) and hit the 60 s statement timeout for 10x and 57x. A manual leaf-first delete with the timeout disabled took 85 s (10x) and 227 s (57x). By contrast a single `erase_contact` or `erase_account` is fast: 0.06-0.14 s at 57x, so GDPR 1-click erasure is fine.
- Cause (likely, not isolated by an EXPLAIN of the trigger queries): each deleted parent row fires FK checks (`SET NULL` / `CASCADE`) that scan the referencing table when the referencing column has no index. Cost is rows deleted x referencing table size.
- Fix: add the missing FK indexes (partial `WHERE col IS NOT NULL` for the nullable ones). Effort: S. Impact is on demo reset (`dataforce demo ... --replace`), tests and any tenant offboarding, not on the hot read path.

### PERF-B-05 A DB connection is held for the whole LLM call, with a small pool
- Where: `app/api/routes/ai.py:161` (`ask`: `build_context` opens the transaction, then `asyncio.run(...)` of the LLM call, `db.commit()` only afterwards); `app/api/routes/themes.py:75` (`run_themes` with an AI namer); `app/org_ai` pass inside `propose`. Engine: `app/db/session.py:get_engine` uses the SQLAlchemy default pool (5 + 10 overflow, 30 s wait), uvicorn runs one worker with the default 40-thread pool (`app/cli/ui.py:53`).
- Measure: not measured (inferred from the code and defaults). `llm_timeout_s` is 60 s, so one slow call pins a connection for up to a minute. Fifteen concurrent asks (the limit is 60 per hour per workspace, not per second) would exhaust the pool and every other request would queue up to 30 s then fail.
- Fix: end the read transaction before calling the provider (`db.commit()` or `db.rollback()` right after `build_context`/`require_credential`), or build the context into plain data and close the session. Optionally raise `pool_size` / set `pool_timeout` and make the LLM endpoints `async` with a worker thread for the DB part only. Effort: S.

### PERF-B-06 Document lists load full transcript text
- Where: `app/api/routes/documents.py:136` (`list_documents`), `:116` (`account_documents`), `:125` (`company_documents`): `select(Document)` pulls `Document.text` for each row, and `_outs` (line 30) never uses it. `_outs` also reads one row per chunk to compute speakers.
- Measure: invisible on the demo (average transcript 1.5 KB, max 2.7 KB): 18-24 ms for a page of 50, 31-46 ms for 200. Real transcripts reach the 1 000 000-character limit (`transcript_max_chars`), so a page of 200 can move tens of MB from PostgreSQL to Python for a response of about 150 KB. The `/documents` page is therefore the first list endpoint that will degrade with real data.
- Fix: `select(Document).options(defer(Document.text))` (or `load_only` of the columns `DocumentOut` uses), add `n_chunks` and the speaker list as SQL aggregates restricted to the page. Effort: S.

### PERF-B-07 Assistant context: render-per-removal loop
- Where: `app/assistant/context.py:480` (`_apply_cap`): `size()` calls `ctx.render()` on the full context for every dropped item, and each render sanitises all items (`app/llm/untrusted.py:49`, 10 378 `sanitize_text` calls in one build).
- Measure: `build_context(company)` 0.04 s (8 accounts), 0.18 s (60 accounts), 0.28 s (264 accounts); about 359 full renders for 280 items at 10x (0.46 s of 0.65 s profiled). Bounded by the caps (`MAX_DEALS` 200, `MAX_CONTACTS` 300, `MAX_MEETINGS` 100, notes and comments 200 each), so it plateaus below about 1 s. The SQL is also fine (10 statements, 80 ms), but deals and contacts are loaded unbounded (`context.py:323`, `:340`) before being sliced to 200 and 300 in Python: for a company with 264 accounts that is about 1 300 deals and 1 700 contacts fetched for 500 shown.
- Fix: keep a running size (sum of rendered item lengths, subtract on drop) instead of re-rendering; add `.limit(MAX_DEALS)` / `.limit(MAX_CONTACTS)` after ranking in SQL. Effort: S.

### PERF-B-08 N+1 per theme in `themes_of_run`, slowest GET on the dev app
- Where: `app/services/themes.py:222` (`themes_of_run`): one query per theme for the top excerpts (about 13 themes), plus a count query that joins all assignments; used by `GET /themes/latest` and the MCP `get_themes`.
- Measure: 117 ms on the dev app (the slowest main GET); 67 / 152 / 224 ms at 1x / 10x / 57x; 18 SQL statements (163 ms of 215 ms at 57x). MCP `get_themes` 40 / 171 / 212 ms. Bounded because `run_themes` caps at 20 000 chunks, but it re-runs the same aggregation on every page view of the themes tab.
- Fix: one window-function query (`row_number() over (partition by theme_id order by weight desc)`) for the top excerpts, and store the counts on the `theme` row (they are already saved at run time; they are recomputed only so a deleted document stops counting). Effort: S-M.

### PERF-B-09 `deal_theme_flags` is a deals x themes cross product, silently capped
- Where: `app/flows/sources/crm.py:_deal_theme_flags_query` (join on `Theme.run_id == latest run`, correlated EXISTS per row), `load_crm_table` `.limit(max_rows + 1)`.
- Measure: 45 500 rows (10x, 0.66 s, 29 MB), 200 000 rows at 57x (1.46 s, 129 MB), which is the 200 000 row cap (`flow_max_rows`), so `capped` is set and 60 000 rows are cut. Memory scales with deals x themes; every downstream block copies the frame. Not urgent, but it is the largest in-memory frame a user can ask for.
- Fix: aggregate in SQL (one row per deal x theme only where mentioned, or a pivot), or lower the cap for this table and say so in the UI. Effort: S.

### PERF-B-10 Smaller items
- `GET /w/{ws}/titles/review` (`app/services/titles.py:220`) sorts every contact of the workspace by a `CASE` expression to return `limit` rows: 14 / 16 / 47 ms at 1x / 10x / 57x. A partial index on `(workspace_id) WHERE title_flag IS NOT NULL OR title_function='unknown'` fixes it (S).
- `GET /quality` (`app/services/quality.py`): four independent aggregate scans, no cache: 14 / 29 / 71 ms. Fine now; it will want the PERF-B-02 indexes or a short TTL cache past 500 000 contacts.
- Every list endpoint runs a separate `COUNT(*)` with the same filter (`accounts.py:76`, `contacts.py:207`, `deals.py:148`): 5 ms at 45 659 contacts. Fine; offset paging costs 114 ms at offset 42 000 without the index (74 ms in EXPLAIN), 8 ms with it. Keyset paging is only needed if deep offsets become a use case.
- `app/demo/generator.py:generate`: 0.1 s (350), 4.3 s (3 500), 161 s (20 000 deals): superlinear (about quadratic). Demo only, but it limits benchmarking; look for a list `.index()` / `in` scan in `build_transcripts`.
- PDF import (`app/transcripts/importer.py:86`): a new `python -I` child per file, 111 ms startup on a blank page. Hard timeout (30 s) and memory limit are good; it blocks one request thread during extraction. Fine for upload sizes allowed.
- Flow `stats` block (`app/flows/blocks/stats.py`, bootstrap for medians): 36 ms / 271 ms / 1 289 ms per block at 1x / 10x / 57x, same root cause as PERF-B-01.

## What is fine

- List and detail GETs: 4-80 ms up to 57x; `accounts`, `deals`, `companies`, `lookup`, `org-chart`, `account documents` do not scale with workspace size for the page sizes used. Pages are bounded (`le=1000`, documents `le=200`), no endpoint returns an unbounded list.
- Aggregates are exact SQL and grouped: `contact_extras`, `deal_names`, `company_stats`, the CRM table loaders (`app/flows/sources/crm.py` says "no N+1", and it is true: all seven tables load in under 1.5 s at 57x, 45 659 contacts in 0.26 s).
- Theme discovery is bounded by design: `MAX_CHUNKS`/`MAX_UNITS` 20 000 and a 20 s preparation budget; 5.4 s and 452 MB RSS at 100 000 chunks.
- Transcript chunking and import: 0.14 ms per turn, 0.68 s for a 1.6 MB transcript with 4 900 turns; the 5 000 chunk cap per document is sensible.
- Process model: flow runs have a semaphore (`flow_max_concurrent_runs=2`), a wall-clock timeout and short-lived worker sessions; the scan thread did not starve other requests (numpy releases the GIL: probe p50 stayed at 4.3 ms during an 11 s scan); the PDF child process has a hard timeout and RLIMIT where supported; the MCP server has a 30 s statement timeout, a size guard on results and a prune of its audit runs.
- Caches: the only in-memory state is the assistant rate-limit deque (per workspace, evicted by window) and an `lru_cache` of compiled regexes (bounded, but ineffective: PERF-B-03). No unbounded dict growth found.
- `erase_contact` / `erase_account` (GDPR 1-click): 0.06-0.14 s at 57x.
- Quality endpoint, pipeline summary, latest scan: single indexed or lightly scanned queries; all under 75 ms at 57x.
- `statement_timeout` (60 s) and `lock_timeout` (15 s) are set on every transaction, so a bad query cannot run forever.

## Suggested order

1. PERF-B-02 (one migration, S): cuts the deep-page, search and "latest run" costs and removes the neighbour penalty.
2. PERF-B-03 (regex compile + skip empty accounts, S): 162 s to a few seconds.
3. PERF-B-01 (analytic median bootstrap or a cap, M): 56 s to under 2 s.
4. PERF-B-05 and PERF-B-06 (S): remove the pool starvation risk and the transcript text over-fetch before real data arrives.
5. PERF-B-04, 07, 08, 09, 10 as maintenance.
