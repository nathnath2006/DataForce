# Code audit (2026-10-19): unused code, performance and system pain points

Asked by the PO before the big UI rework and before M3b (login, hosting).

## How it was done

- A board of five Sonnet agents (medium effort) each audited one lens, read-only, with measurements:
  - unused backend code;
  - unused frontend code;
  - backend performance, measured at 1×, 10× and 57× data;
  - frontend performance, with page loads measured in a browser;
  - system and architecture.
- Their reports are in `docs/review/audit/`. Every finding there has an id, evidence and an
  effort. This page consolidates them.
- The tech lead checked the key claims before relying on them:
  - **RLS does nothing today.** The app connects as `dataforce`, which owns the tables. RLS is
    enabled but not forced, and no table has a policy (checked in `pg_class` and
    `pg_policies`).
  - **Missing indexes.** `contact`, `document`, `document_chunk` and `run` have no index on
    `workspace_id`; `run` has only its primary key (checked in `pg_index`).
  - **The four failing tests** the system auditor reported were residue of its own interrupted
    run. A clean full run passes (1,447). The fragility is real: some tests count whole tables
    (SYS-19).
  - **Org-proposal slowness.** The patterns' regex cache is keyed by each account's name list,
    so a whole-workspace run recompiles for every account (PERF-B-03).

## Unused code

The codebase is lean. The frontend has 5 certain items and the backend about 14 certain, most
of them small.

**Removed in this round** (tests green):
- **Backend:**
  - `services/safe_yaml.py`, the only YAML code (DC-B-01);
  - `require_http_url` (DC-B-02);
  - `ErrorBody` and `ErrorResponse` (DC-B-03);
  - the `ConnectorProvider` and `ConnectorStatus` enums (DC-B-04);
  - `assistant.ratelimit.reset` (DC-B-05);
  - `agent._util.iso` (DC-B-06);
  - the settings `db_quota_mb`, `demo_seed` and `demo_n_deals`, also dropped from
    `.env.example` (DC-B-11).
- **Frontend:**
  - `pages/OrgChart.tsx`, superseded by `orgchart/OrgChartPanel.tsx` (DC-F-01);
  - `ancestors()` and its test (DC-F-02);
  - `flowApi.deleteFile` (DC-F-03);
  - the `--accent-text` token (DC-F-04).

**Left for a decision:**
- The **embedding stack**: `GeminiEmbedder`, `FakeEmbedder`, `get_embedder`, the
  `EmbeddingProvider` port, three settings and the `pgvector` dependency, about 150 lines.
  Only tests use it; it was meant for semantic search, which never shipped (DC-B-07, DC-B-13).
  Delete, or build semantic search soon.
- **Test-only services** (`admin.db_size`, `list_runs`, `usage_summary`,
  `delete_channels_for_contact`, the `get_llm` and `get_enrichment_provider` registries): delete
  them with their tests, or expose them in an admin view (DC-B-08 to DC-B-10).
- **`GET /titles/preview`**, which only tests call (DC-B-17, DC-F-11): delete, or keep for the
  title editor of the UI rework.
- **`llm_max_calls_per_run`**, deferred on purpose in M1 (DC-B-11): wire it in or delete it.
- **`pyyaml` and `types-PyYAML`**: now unused. Drop them at the next lock refresh (the locks are
  hashed).

## Pain points, ranked

### 1. Quick wins before the UI rework (small effort, large effect)

| # | What | Why it matters | Source |
|---|---|---|---|
| 1 | **Indexes**: `workspace_id` on `contact`, `document`, `document_chunk` and `run`; foreign-key indexes for cascades (`contact.reports_to_id`, `document_chunk.contact_id`…) | A workspace delete takes 14 s at 1× and times out at 10×. Offset lists 74 ms → 8 ms. Latest run 2.6 ms → 0.01 ms | PERF-B-02, B-04 |
| 2 | **Org proposals**: compile the patterns once per run; skip accounts without meetings | 1.9 s → 20 s → 162 s from 1× to 57× | PERF-B-03 |
| 3 | **Compression and caching**: gzip on responses, `immutable` caching on hashed assets | The main JS goes out raw at 400 kB (117 kB gzipped); a contacts list is 418 kB of JSON | PERF-F-01 |
| 4 | **Re-renders**: memoise the workspace context value | Opening the drawer or the menu re-renders 8,000-node tables | PERF-F-06 |
| 5 | **N+1 queries and heavy payloads**: `themes/latest` (one query per theme); document lists that carry the full transcript text | The slowest GET on the dev app; cost grows with real transcripts | PERF-B-08, B-06 |
| 6 | **Runs stuck as "running"** after a crash: add a reaper at start-up | They stay "running" forever | SYS-05 |
| 7 | **Duplicated rules**: merge them into one module each — the secret and contact redaction regex (agent tools and column profile), the in-memory budget helpers (titles, org AI, assistant), `formatDate` (two versions with different locales) | Two copies drift | SYS-12, DC-F-08, DC-B-18/19 |
| 8 | **Tests that count whole tables**: scope them to their own workspace | They fail on a test DB that is not clean | SYS-19 |

### 2. With the UI rework (structural)

- **Lists:** real server paging and windowed tables instead of `limit=1000`. The 1,000 cap
  silently truncates lists and pickers at 10× (PERF-F-02, F-03, F-12).
- **Data loading:**
  - remove the request waterfalls: every page waits for the workspace list, and detail pages
    chain their requests;
  - cancel requests when the user navigates;
  - add a small cache.

  (PERF-F-04, F-05, F-07)
- **Code splitting:** split the main bundle by route; only the flow editor is split today
  (PERF-F-08).
- **API types:** generate `types.ts` from OpenAPI, with a drift check, before the rework
  multiplies the hand-written types (SYS-13).
- **Layering:**
  - one commit convention for mutating routes;
  - move business logic and raw queries out of the routes;
  - split the largest modules before they grow further.

  (SYS-08, SYS-09, SYS-14)
- **Stats scan:** 1.1 s → 11 s → 56 s from 1× to 57×; the bootstrap runs on a request thread.
  It becomes a background job, plus either a sample cap or an exact order-statistic interval for
  medians. Changing the method needs a statistics ratification like M1's (PERF-B-01).
- **LLM calls:** they hold a database connection for their whole duration, with a pool of 5+10.
  Release the session before calling the model (SYS-06, PERF-B-05).

### 3. Before M3b (login and hosting)

1. **Identity** (SYS-01, SYS-10): a `Principal` dependency, membership and roles; the author and
   owner set by the server, never taken from the request body; proper 401, 403 and 429
   responses.
2. **Enforced isolation** (SYS-02): a non-owner database role, `SET LOCAL app.workspace_id`, real
   policies, and a test that every workspace table has one, plus a cross-tenant test over every
   route.
3. **Shared state** (SYS-04): AI budgets, failure memories, the assistant rate limit and the
   scan lock move to the database. The TamTam token refresh needs a lock: with two workers, the
   rotated refresh token breaks the connection.
4. **Hosting guards** (SYS-03): the Host and Origin lists come from settings; secure cookies;
   TLS and proxy headers; a rate limit on login.
5. **GDPR erasure** (SYS-15): a registry of every table holding derived text, with a test that
   plants a name everywhere and finds none after erasure. Today it misses run arguments and
   results, theme texts and error texts.
6. **Keys** (SYS-11): versioned encryption keys (MultiFernet), bound to the workspace.
7. **Assistants when hosted** (SYS-07): the MCP server is stdio-only and needs a remote story.
8. **Observability** (SYS-18): structured logs and run records an operator can search.

## What the board found fine

- **Workspace scoping:** every service scopes by workspace through one helper, a good seam for
  login.
- **Errors and guards:** the error contract and its privacy-minded handlers; the Origin and
  `X-DataForce` request guard.
- **Timeouts and Postgres:** engine timeouts and prepared statements for PostgreSQL sources.
- **OAuth state:** atomic, so it is safe across workers.
- **Child processes:** PDF parsing in an isolated child process.
- **Agent tools:** read-only, with their untrusted-field envelope.
- **List speed:** list and detail GETs stay at 4–120 ms up to 57×.
- **Frontend hygiene:** no duplicate API calls on any page measured; `tsc` reports no unused
  locals; no dead CSS class.
