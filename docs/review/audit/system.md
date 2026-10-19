# System and architecture audit (lens: what hurts at M3b and at scale)

Read-only audit. Severity = impact on M3b (login, hosting) or on scale. Effort S/M/L.
Complexity data: `scratchpad/audit/complexity.py` (AST branch count and line count).

## Findings

### SYS-01 No identity anywhere: authorization cannot be layered on without touching every route (high, L)
- Evidence: `api/schemas.py:222,227` (`author_id` is a client-supplied body field, "acting as" user), `api/deps.py:44-52` (the only dependency resolves a workspace by URL slug, no principal), `frontend/src/App.tsx:77-131` (acting-as is a localStorage-backed select), `cli/ui.py:1`.
- Why it hurts: any caller can write notes/comments as any user, set any `owner_id`, and read or write any workspace by changing the slug. `AppUser` is a "sales rep" label (workspace-scoped, `db/models.py:78`), not an account: there are no auth columns, no membership table, no role check anywhere. `UserRole` exists but is never enforced.
- Good news: every route funnels through `CurrentWorkspace` and services take `ws_id`, so a single `Principal` dependency can be added at one place.
- Fix: add `get_principal` -> `CurrentWorkspace` checks membership; replace body `author_id` by `principal.user_id` (keep the field ignored for one release); add `Role` guard dependencies (`RequireAdmin`) for the settings, connectors, AI key, erasure and workspace-delete routes. Decide the account vs `AppUser` split now (global `account`/`login` table plus `membership(workspace, user, role)`), since `app_user.email` is unique only per workspace.

### SYS-02 RLS is declared, not enforced; the app runs as table owner (high, M)
- Evidence: `alembic/versions/0002_lockdown.py:4-5,50` ("the app connects as the table owner, which bypasses RLS"), later migrations `0004:108`, `0005:152`, `0006:180`, `0007:53` enable RLS with no policy. No `FORCE ROW LEVEL SECURITY`, no policy, no `set_config('app.workspace')`.
- Why it hurts: RLS protects only against Supabase anon/authenticated roles hitting PostgREST. Tenant isolation is 100% in service code (`get_scoped`, `services/_common.py:32`). One forgotten `workspace_id` filter is a cross-tenant leak, and nothing backstops it. `workspace_id` FKs are single-column, so the DB also allows e.g. a note on workspace A pointing to a contact of workspace B.
- Fix: for hosting, a non-owner app role + per-transaction `SET LOCAL app.workspace_id` (the `begin` event hook in `db/session.py:52-62` is the right place) + one `USING (workspace_id = current_setting(...)::uuid)` policy per table; add composite `(workspace_id, id)` unique keys for the cross-table FKs that matter (note/comment/deal/document). Add a test that enumerates `Base.metadata` and fails when a table with `workspace_id` has no policy.

### SYS-03 Request guards assume loopback, one origin, no cookies (high, M)
- Evidence: `api/security.py:48-52` (Host allow-list built from `127.0.0.1`/`localhost`/`[::1]` x `ui_port`/5173), `config.py:271-275,356-380` (`ui_host` validated as loopback, `ui_allowed_origins`), `cli/ui.py:54` (`workers=1`), `api/main.py` (no CORS, no session middleware).
- Why it hurts: behind a hosted domain every request is refused (Host). CSRF today is "Origin allow-list + `X-DataForce: 1`" which is reasonable with cookie auth only if the cookie is `SameSite=Lax/Strict` and Origin is enforced for all unsafe methods (it is). But no TLS awareness: no HSTS, no `Secure` cookie, no proxy-header handling (`X-Forwarded-Proto/For`), and the OAuth callback uses a `df_oauth` cookie (`api/routes/connectors.py:24`) with redirect URIs built from the local port (`api/deps.py:get_app_settings` docstring).
- Fix: make allowed hosts/origins settings-driven (`public_base_url`), add HSTS and `Secure` cookies when https, trusted-proxy config, login rate limiting, and keep the CSRF header scheme (it is fine as is, see "fine as is").

### SYS-04 In-process budgets and caches are per process: 2 workers = 2x the caps (high for cost, M)
- Evidence: `services/titles.py:35-37` (`_DAILY`, `_FAILED`), `services/org_ai.py:32-34`, `assistant/ratelimit.py:14-26`, `agent/tools.py:121,658-662` (`_SCAN_LOCK`, "per-process lock"), `connectors/tamtam.py:289,317` (per-process `asyncio.Lock` around OAuth refresh), `services/flows.py:32-41` (run slots), `llm/usage.py:30-47` (LLM concurrency semaphore), `registry/client.py:61` (`_next_slot`, global request spacing), `orgchart/meetings.py:446,569` (`lru_cache`, pure so fine).
- What happens behind 2 workers / 2 machines:
  - Daily AI caps (titles, org AI) and assistant hourly limit: effective cap is N x the setting; a restart resets them to zero, so a crash loop is also a budget reset. The "failure memory" (no retry for 1 h) is lost on restart or sibling worker, so a bad key means repeated paid failing calls.
  - Scan reuse lock: two workers can both start a scan (duplicate `stats_scan` runs); harmless but wasteful.
  - TamTam token refresh: refresh tokens rotate (the code says so). Two workers refreshing at once make the second use an already-rotated refresh token -> `invalid_grant` -> credential marked `expired` and the user has to reconnect. This is a real correctness bug, not just a cap.
  - Flow slots / LLM semaphore: the limit is per process, so DB and provider load scale with workers.
- Fix: the DB already has `llm_call` (every call is a row with workspace, purpose, success, `created_at`). Derive daily budgets and recent-failure checks from it (`count(*) where workspace, purpose, created_at > day start`), replacing `_DAILY`/`_FAILED`/`assistant.ratelimit`. For the refresh race use `SELECT ... FOR UPDATE` on the credential row (or `pg_advisory_xact_lock(hash(ws_id))`). For scan reuse use an advisory lock. Flow slots: count `run` rows with status running and recent heartbeat, or accept per-worker and document it.

### SYS-05 No heartbeat or reaper for runs: a crash leaves `running` forever (medium, S)
- Evidence: `services/flows.py:170-203` commits a `running` row, then the worker may die; only `RunStatus.RUNNING` is written in `services/runs.py:46` and never read to expire anything (grep: no stale-run handling). Same for themes, titles, org proposals, scans.
- Why it hurts: with hosting, deploys and restarts happen daily; UI will show phantom running jobs, and any "is a run in progress" check (e.g. `channels.py:146` lookup lock) will be stuck. Also `run` has no index on `(workspace_id, kind, started_at)` even though scan lookup, theme lookup and the agent prune (`mcp_server/server.py:89-97`, OFFSET 5000 delete on every call) filter on exactly that (`db/models.py:252-269`).
- Fix: `reap_stale_runs()` at startup and on list (running and older than timeout + margin -> `failed`, error "interrupted"); add the composite index; move `_prune` to every Nth call or a scheduled job.

### SYS-06 Sync routes, `asyncio.run` inside threadpool threads, DB session held during LLM calls (medium, M)
- Evidence: `api/routes/ai.py:142,176`, `api/routes/themes.py:58`, `services/titles.py:162` (`asyncio.run(...)` inside sync handlers), `services/titles.py:70-77` (sessionmaker bound to the same connection with savepoint to record usage), `api/deps.py:get_db` (session lives for the request).
- Why it hurts: a title or theme pass holds a pooled connection (and an open transaction, with `statement_timeout` applying only to statements) for the whole LLM round trip; SQLAlchemy default pool is 5+10 (no `pool_size` set in `db/session.py:75-85`) and the default anyio threadpool is 40 threads. With N concurrent users 15 slow AI requests starve every other request. The per-loop semaphore design (`llm/usage.py`) exists only because `asyncio.run` creates fresh loops.
- Fix: before the UI rework, split "read inputs (commit/close)" -> "LLM calls with no session" -> "write results" for the AI services, set pool size explicitly from settings, and move long jobs (themes, titles, org AI, flow runs) behind a small job runner (DB-backed `run` queue) so the UI polls a run id. That also fixes SYS-04/05 naturally.

### SYS-07 stdio MCP has no hosted story (medium, M)
- Evidence: `docs/M3A-CONTRACT.md:8` ("no login and no network listener ... stdio"), `mcp_server/server.py:30-35,145-180` (`workspace` bound at process start, `SessionLocal` with the full owner DB URL), `cli/mcp.py:53` (only place that configures logging).
- Why it hurts: when hosted, each user would need the DB URL on their laptop (impossible/unsafe) or the server must expose MCP over streamable HTTP with per-user tokens that map to a principal and workspace. The tool layer itself (`agent/tools.py`, `Envelope`, `untrusted_fields`) is transport-agnostic and well separated, which is the good part.
- Fix: plan an HTTP MCP endpoint mounted on the same app, auth by personal access token (hashed in DB), principal -> workspace membership, rate limit by principal. Keep stdio for local mode.

### SYS-08 Layering: routes contain business logic and raw queries (medium, M)
- Evidence: `api/routes/crm.py` (261 lines; builders `_accounts_out`, `_deals_out` compute `cycle_days`, `is_closed`, enrich names), `api/routes/documents.py:35-48,120-160` (direct `select(Account...)`, `select(Document)`, `select(DocumentChunk)` in the route), `api/routes/agent.py:20`, `api/routes/stats.py:21` (queries on `Run`), 41 `db.commit()` calls in routes vs 10 in services (see below). `agent/tools.py` imports 8 services and a settings singleton and reaches module-private state (`flows`, `themes`, `analytics`, `org_proposals`).
- Why it hurts: a Principal/authorization layer (SYS-01) and a UI rework both want one place per use case. Today the same read is implemented in the route, in `agent/tools.py` (`workspace_overview`, `get_account`) and in `assistant/context.py` (`build_context`, 223 lines, 59 branches): three read models of "an account" that drift.
- Fix: introduce thin read services (`services/account_view.py`, `services/document_view.py`) used by routes, agent tools and assistant context; routes keep only parsing, auth and status codes.

### SYS-09 Transactions: "services never commit" is true, but the caller convention is ad hoc (medium, S/M)
- Evidence: `api/deps.py:1-5` (route must call `db.commit()` before responding), 41 route commits (`api/routes/crm.py` 11, `notes.py` 6, `data.py` 6, `companies.py` 6, `ai.py` 5 ...), plus services that do commit (`services/flows.py` 4 via `execute`, `services/themes.py` 2, `services/channels.py` 2, `connectors/tamtam.py` 8, `agent/tools.py:1`). Mixed styles: `session_scope()` for CLI, `db.commit()` per route, commit inside services for long jobs.
- Why it hurts: a forgotten commit returns 200 and silently loses the write (the docstring says this is the design trade-off); a route with two commits (e.g. create then update) is not atomic. Adding authz/audit rows later multiplies the risk.
- Fix: make `get_db_tx` (commit on success, rollback on exception) the default for mutating routers (POST/PUT/PATCH/DELETE) and keep explicit commits only in the long-job services (named `*_committing`). Add a lint test: no `db.commit()` in `api/routes` outside whitelisted modules.

### SYS-10 Error mapping is mostly consistent, with semantic misuse (low, S)
- Evidence: `api/errors.py:30-72` maps NotFound/InvalidInput/AlreadyExists/Enrichment/Integrity/SQLAlchemy/HTTP; `assistant/ratelimit.py:26` and `services/channels.py:146` raise `AlreadyExistsError` for "rate limit" and "already running" (HTTP 409 `conflict`); `api/routes/flows.py:106` maps `TooManyRuns` by hand in the route; `TS ErrorCode` (`frontend/src/types.ts:21`) has no `rate_limited`/`unauthorized`/`busy`.
- Why it hurts: UI cannot show "try again in N minutes" vs "name taken"; login needs 401 vs 403; the 429 semantics matter to clients and proxies.
- Fix: add `RateLimitedError` (429, `Retry-After`), `BusyError` (409 `busy`), `UnauthorizedError` (401), and register them centrally; remove per-route mapping.

### SYS-11 Secrets: one global Fernet key, no rotation, no workspace binding (medium, M)
- Evidence: `connectors/crypto.py:21-42` (single `Fernet(secret)`; no `MultiFernet`), `config.py:270,340-351`, `services/llm_settings.py:116-117` (`open_key` unseals with the global key), per-workspace ciphertext only in `llm_credential.api_key_enc`, `connector_credential.*_enc`, enriched channel values.
- Why it hurts: leaking the one key decrypts every tenant; a ciphertext copied from workspace A's row into B's decrypts fine (no AAD / context binding); key rotation requires a re-encrypt migration that does not exist; the same key seals different classes of data (OAuth tokens, API keys, enriched PII).
- Per-workspace handling that is good: keys are sealed at rest, never returned by the API (`SecretStr`, `open_key` only at call time), `validate_key` bounds input.
- Fix: switch to `MultiFernet` (versioned key list) now, store a `key_version` column, and bind ciphertext to `workspace_id` (prepend `ws_id:purpose` inside the plaintext and verify on open). Hosted: key comes from the platform secret store, not `.env`.

### SYS-12 Duplicated rules (medium for drift, S each)
- Redaction of secret/PII columns: `agent/tools.py:123-126` (`_REDACT` regex over column names: password|token|email|phone...) vs `enrichment/tamtam_mcp.py:95-96` (`_EMAIL_RE`, `_PHONE_RE` for values) vs `themes/lexicon.py` and `services/documents.py:253` (transcript redaction) vs the assistant ("never sees e-mails/phones", `mcp_server/server.py:48`). Name-based redaction exists only in the MCP/agent path; the flow results returned by the REST API (`api/routes/flows.py`) need to be checked against the same rule (the comment says SR14-02 "blanked in flow results" but the constant lives in `agent/tools.py`, not in `flows/`).
- Untrusted-text wrapping/sanitising: `llm/untrusted.py`, `llm/quotes.py`, `agent/_util.py` (`clean`), `services/textclean.py` (`scrub_*`), `assistant/context.py`, `orgchart/meeting_ai.py`, `titles/ai.py`, `themes/naming.py`: 8 modules each with their own prompt-assembly. A fix to the sanitiser must be remembered 8 times.
- Caps and budgets: three copies of the daily-budget + failure-TTL machinery (`services/titles.py:30-70`, `services/org_ai.py:27-60`, `assistant/ratelimit.py`) and magic caps scattered in ~40 module constants (`MAX_COLUMNS = 60` and `MAX_THEMES = 100` duplicated in `agent/tools.py:118-119` and `flows/profile.py:18`, `themes/discover.py`).
- Fix: one `app/privacy.py` (column-name predicate, value redactors, used by flows, agent, assistant), one `app/llm/budget.py` (DB-backed, see SYS-04), one `untrusted` prompt builder; shared constants in `config.py` where they are operator-tunable.

### SYS-13 Frontend types by hand; no generation or drift test (medium, S)
- Evidence: `frontend/src/types.ts:1` ("Mirrors backend/app/api/schemas.py and backend/app/domain/schemas.py"), 186 lines; `ErrorCode` union hand-copied from `api/errors.py`; enums (`DEAL_STAGES`, `LEAD_SOURCES`) duplicated from `domain/enums.py`. `/api/openapi.json` is already served (`api/main.py:36`).
- Why it hurts: the UI rework will change many shapes; silent drift shows up as `undefined` at runtime. Auth adds `me`, memberships, 401 flows.
- Fix: generate `types.ts` from the OpenAPI document (`openapi-typescript`) in CI with a "git diff clean" check; at minimum a pytest that compares enum values and the `ErrorCode` set with `types.ts`.

### SYS-14 Complexity hotspots to split before the UI rework (medium, M)
Top by branches / lines (`complexity.py`):
- `assistant/context.py:252 build_context` 223 lines, 59 branches.
- `flows/blocks/model.py:104 run` 171 lines, 39 branches; `flows/blocks/stats.py:32 run` 159/36; `flows/blocks/pivot.py:38 run` 105/43; `flows/engine.py:52 run_graph` 95/33.
- `agent/tools.py` 1346 lines, 31-branch `get_account` (168 lines); the file holds 14 tools, the shared helpers, redaction, scan cache and the registry.
- `services/documents.py:253 redact_contact` 108 lines, 35 branches (GDPR-critical, offset-preserving string surgery).
- `services/themes.py:86 run_themes` 103/29, `services/titles.py:119 normalize_workspace` 99/26, `orgchart/meetings.py` 571, `enrichment/tamtam_mcp.py` 811.
- Frontend: largest files are small (`ConfigForm.tsx` 384, `graph.ts` 318, `App.tsx` 226); 6.7k lines total, so the UI is not the hotspot; the rework is cheap to start but `App.tsx` holds the "acting as" state and routing, which must move into an auth/session provider.
- Fix: split `agent/tools.py` into `agent/tools/{overview,accounts,stats,flows,themes}.py`; make `build_context` a list of section builders; split `redact_contact` into plan (pure, offsets) and apply (DB) so it can be property-tested.

### SYS-15 GDPR erasure is not complete for newer tables (high for compliance, M)
- Evidence: `services/contacts.py:123-164 erase_contact` deletes proposals mentioning the contact, redacts transcripts (`services/documents.py:253`), purges the org-AI cache for the account (`:259`) and cascades notes/channels/chunks/theme assignments through FKs. Not handled:
  - `run.params`/`run.result` JSONB (`db/models.py:252-269`): `agent_call` runs store tool name and args truncated to 200 chars (`mcp_server/server.py:150`, `ARG_TEXT_MAX`), e.g. `search_companies("Jane Doe")`; flow `summarise()` results and theme run results hold cells/quotes. 5000 rows are retained per workspace (`AGENT_CALL_KEEP`).
  - `theme.name`/quotes derived from transcripts: assignments cascade, but theme names, `examples` and run results that quote the erased person's words are not rewritten.
  - `llm_call.error` (text) and `run.error` (`str(exc)` at `services/flows.py:196`, `services/analytics.py:105`): can echo data.
  - `Note` bodies and `Comment` bodies by other authors that mention the person are explicitly out of scope (SR12 resolution) but should be a documented, user-visible limitation.
  - Backups/PITR in hosting.
- Fix: an erasure registry (`ERASURE_SINKS`) that every table holding derived text must register in, plus a test that seeds a name in every sink (runs, themes, proposals, cache, chunks, documents) and asserts zero hits after `erase_contact` and `delete_workspace`. For runs: do not persist free-text args at all (hash or length only) or scrub by name at erasure.

### SYS-16 Data model: cascades and soft delete (medium, S/M)
- Evidence: `app_user` deletion is `SET NULL` on notes/comments/deals (`db/models.py:172,208,215,239,248`), which destroys attribution (an invite-only system needs "deactivated" users, not deleted); notes are append-only with triggers (`services/_appendonly.py`, erasure flag via GUC at `services/_common.py:73`) while `Workspace` delete cascades everything via `erasure()`. No `deleted_at` on any table except note correction fields; no `is_active` on users. `uq_app_user_ws_email` allows many NULL emails, so an email is not an identity.
- Fix: add `is_active`/`deactivated_at` to the user/membership, forbid hard delete of a user with authored rows; in M3b make email the global login key (citext unique) on a new `login` table.

### SYS-17 Migration hygiene (low, S)
- Evidence: 7 revisions (`0001`..`0007`) with hand-rolled `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` loops per migration (copy-paste at 4 places) and a lockdown that only runs REVOKE "when the roles exist". Dev DB and test DB are separate; the test conftest has strong safeguards (`tests/conftest.py:7-116`).
- Why it hurts: easy to forget RLS on the next table (see SYS-02 test). No `downgrade` verification is visible, no check that `alembic upgrade head` equals `Base.metadata` (autogenerate diff).
- Fix: a pytest running `alembic check`/autogenerate diff and the RLS enumeration; a shared `lockdown(table)` helper.

### SYS-18 Observability: operator cannot diagnose much (medium, M)
- Evidence: logging is configured in exactly one place (`cli/mcp.py:53` `basicConfig`); only 11 modules call `logging.getLogger`; `api/security.py:103-105` logs `unhandled <TypeName>` with no traceback, no request id, no route, no workspace, deliberately for privacy; `api/errors.py:62-72` logs the exception class only; no request-id header, no access log fields beyond uvicorn's, no metrics, no health detail (`/api/health` returns `ok`, version, environment, no DB check).
- What an operator cannot answer today: which request produced a 500, which workspace, which statement timed out, why an AI call failed (only `llm_call.error` text with class + http code, which is good), which run was interrupted (SYS-05), per-workspace spend this day (needs SQL on `llm_call`), pool exhaustion, slow endpoints.
- Fix: request-id middleware (also written into `run.params`), JSON logs with `workspace`, `route`, `status`, `duration_ms`, exception class and a safe fingerprint (hash of traceback frames, no values); `/api/health/ready` doing `SELECT 1`; Sentry-style scrubbing hooks off by default; an admin "runs" page driven by `run`.

### SYS-19 Test suite: slow, mostly integration, a few time/sleep risks (medium, S/M)
- Evidence: see "Test suite" below. 44 test files carry the `integration` marker (needs Postgres), `tests/conftest.py`; 8 `sleep` calls and 16 `datetime.now`/`time.time` uses in tests (clock-dependent daily caps `_day()` in `services/titles.py:42-43` use `time.time()` directly, which makes midnight-boundary flakiness possible and prevents freezing time).
- Gaps (by file-name reference count in tests): `services/data_connections.py`, `services/safe_yaml.py`, `services/textclean.py`, `agent/_util.py` have no direct reference (may be covered indirectly), `assistant/ratelimit.py`, `services/llm_usage.py`, `services/quality.py`, `services/org_ai.py`, `services/org_proposals.py` have 1-2 referencing files each; there is no multi-worker/concurrency test for the refresh lock or the scan lock; no test that every route requires workspace scoping (a parametrized "cross-workspace id returns 404" over all routes would be the best M3b safety net).
- Fix: inject a clock (`Clock` protocol or `monkeypatch time`) into the budget code; xdist with per-worker schemas or a template DB; mark and split `unit` vs `integration` so the inner loop is <30 s; add the route-matrix cross-tenant test.

### SYS-20 PDF extraction child process (low-medium, S)
- Evidence: `transcripts/importer.py:92-110` (`subprocess.run([sys.executable, "-I", worker ...], env={}, timeout, memory limit 512 MB)`).
- Behind 2 workers/machines: it is stateless and per call, so it scales; but each request spawns an interpreter on the request thread (blocks a threadpool slot for up to the time budget), `RLIMIT_AS` "where the OS honours it" is not honoured on macOS and varies in containers, no concurrency cap (50 parallel uploads = 50 x 512 MB). In a container, `sys.executable` and the worker path must exist and `env={}` removes `PATH`/locale.
- Fix: a small global semaphore (and ideally DB-based, SYS-04) around the extraction; run as a job; document container memory limits.

### SYS-21 Untrusted content and prompt injection posture is strong but scattered (low, S)
- Evidence: `Envelope.untrusted_fields` (`agent/schemas.py`), `_untrusted` suffix convention (`mcp_server/server.py:46`), `llm/untrusted.py`. Good design; risk is in drift (SYS-12) and in new write tools: M3a is read-only by contract, a hosted MCP with write tools needs a separate approval model.

## Test suite (measured)
Run on the test DB only (`backend/tests/conftest.py` refuses a DB with the dev name).
- Two partial runs (the first full run was killed by me part-way, which may have left rows in the test DB):
  - api + services + db + titles + orgchart: 689 tests in 33 s. Slowest single test 2.0 s (connect-timeout test); everything else under 0.8 s. These dirs are fast.
  - connectors, llm, flows, stats, themes, enrichment, mcp, e2e, agent, assistant, demo, registry, transcripts: 758 tests in 263 s. Time is concentrated in a few statistical calibration tests: `tests/demo/test_engine_truth.py::test_seed_sweep_calibration` 52.5 s, `test_pass_rate_over_20_seeds[noise]` 27.6 s and `[planted]` 27.2 s, `tests/e2e/test_cli_e2e.py::test_noise_false_positives_over_10_seeds` 12 s, `tests/stats/test_engine.py::test_null_false_positive_rate` 5.8 s. About 150 s of the ~300 s total is five to six calibration sweeps.
  - Recommendation: mark sweeps `@pytest.mark.slow` (nightly or pre-release, plus a 3-seed smoke in the default run). That brings the default suite to about 2 minutes without losing the statistical guarantee. No `-n auto`/xdist is configured.
- Isolation fragility: 4 failures appeared after my interrupted run (`tests/services/test_crm.py::test_erase_contact_deletes_notes_and_unlinks_reports` asserts `count(Note) == 1` globally, got 89; `test_erase_account_and_delete_workspace_cascade` asserts 0 notes globally, got 8741; `tests/e2e/test_cli_e2e.py::test_notes_round_trip`; `tests/agent/test_tools.py::test_meetings_and_themes`). Tests that count rows across the whole table depend on an empty DB and on suites cleaning up after themselves; a killed run poisons the next. Fix: scope those assertions by workspace or truncate between sessions (a session-start `TRUNCATE ... CASCADE` fixture on the test DB).


## Fix before M3b (ranked)
1. SYS-01 + SYS-10: `Principal` dependency, membership and roles, server-side author/owner, 401/403/429 errors (design the account vs `AppUser` split first).
2. SYS-02: non-owner DB role + `SET LOCAL app.workspace_id` + real policies, and a test that every `workspace_id` table has one; plus a route-matrix cross-tenant 404 test.
3. SYS-04: move AI budgets, failure memory, assistant limit and scan lock to the DB (derive from `llm_call`), and lock the TamTam refresh with a row/advisory lock (real correctness bug with 2 workers).
4. SYS-03: settings-driven hosts/origins, Secure/SameSite cookies, TLS/proxy headers, login rate limit.
5. SYS-15: erasure registry and an erasure completeness test (runs params/results, themes, errors).
6. SYS-05 + SYS-06: stale-run reaper, `run` index, and take LLM calls out of open DB sessions (pool sizing) before concurrent users arrive.
7. SYS-11: `MultiFernet` with key version and workspace binding before any real tenant secret is stored.
8. SYS-13 + SYS-09: generate `types.ts` from OpenAPI with a CI diff check, and make mutating routes commit via one dependency, before the UI rework multiplies both.

## Fine as is
- Services-never-commit contract, `get_scoped` workspace scoping in every service (a single choke point), and `CurrentWorkspace` as one dependency: good seam for auth.
- The error body contract `{"error": {"code","message"}}` and the privacy-minded handlers (no values echoed, class names only).
- The Origin + `X-DataForce` CSRF scheme and the SecurityMiddleware body-size limits; keep them, just make the allow-lists configurable.
- Engine and pool timeouts via `SET LOCAL` (works behind a transaction pooler), prepared-statement handling for port 6543.
- OAuth pending state: single-use, hashed, taken with one atomic statement (`connectors/store.py:172-180`), so it works across workers.
- Append-only triggers plus the transaction-local erasure flag (`services/_common.py:67-86`).
- PDF parsing in an isolated, time-limited child with `-I` and empty env.
- Read-only agent tools with `SET TRANSACTION READ ONLY`, statement timeout, `untrusted_fields` envelope, and run records for audit.
- The test DB safety net in `tests/conftest.py`.
- `lru_cache` uses in `orgchart/meetings.py` (pure functions) and the per-loop LLM semaphore (correct for its design).
