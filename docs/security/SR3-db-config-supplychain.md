# SR3 - Persistence, configuration, infra and supply chain

Reviewer: Security Reviewer #3. Date: 2026-10-16. Milestone 1 data core.
Scope: `backend/app/config.py`, `app/db/**`, `app/services/**`, `backend/alembic/**`, `alembic.ini`,
`docker-compose.yml`, `docker/postgres/init/**`, `Makefile`, `.gitignore`, `backend/.env.example`,
`README.md`, `backend/pyproject.toml`, `backend/requirements.lock`, `data/**` and the code that
parses it. `app/pipeline` and `app/cli` were skipped, except for reading the YAML parsers that load
`data/**` (`pipeline/customers.py`, `pipeline/scopes.py`) and the CLI error handler, which the
brief asked about. A second pass should cover the rest.

## 1. Summary

Overall risk for M1 (local CLI, loopback-only Postgres): **Low**. I found no critical or high
issue, no SQL injection, no secret leak and no known CVE in the lockfile.

Two gates matter before the hosted Supabase demo (SR3-01, SR3-02, SR3-03). Today they are inert
because nothing is deployed. The security baseline in `docs/ARCHITECTURE.md` section 4 ("No default
passwords outside dev") and the README password advice are not enforced or are ineffective as
written.

What is solid: every query is bound-parameter SQLAlchemy, every upsert sits on a unique
constraint, services never commit, `SecretStr` holds across 17 leak probes, the advisory-lock
migration serialisation works, and the dependency lock is clean (pip-audit with the PyPI and OSV
databases: 0 vulnerabilities in 83 pinned packages).

Method: static reading, then PoCs. PoCs that write data ran on a throwaway
`pgvector/pgvector:pg16` container I started and removed (`sr3-poc-pg`, 127.0.0.1:55432). The dev
DB `tamtam` and the test DB `tamtam_test` were only queried read-only (version, roles, pg_hba, TLS
status). No repo file was modified except this report.

## 2. Findings

| ID | Severity | Status | Title |
|---|---|---|---|
| SR3-01 | Medium (pre-demo gate) | likely | Supabase hosting: tables in `public` with no RLS / no REVOKE from `anon`/`authenticated` |
| SR3-02 | Low | confirmed by PoC | TLS is neither enforced nor documented for the hosted DB (`sslmode` defaults to `prefer`) |
| SR3-03 | Low | confirmed by PoC | Dev credentials unguarded: `Settings.environment` is dead config; README password advice is a no-op on an existing volume |
| SR3-04 | Low | confirmed by PoC | Test fixtures trust `TEST_DATABASE_URL` blindly (no `_test` / not-equal-to-dev guard) |
| SR3-05 | Low | confirmed by PoC | A human `confirm` of a known customer can be silently overwritten (lost update) |
| SR3-06 | Low | DB side confirmed; trigger likely | NUL / lone surrogate in LLM-derived JSON makes the profile unsaveable (poison pill, repeated LLM spend) |
| SR3-07 | Low | confirmed | `.gitignore` misses `.env.*` variants, `.envrc`, key/cert files and dumps |
| SR3-08 | Low | confirmed | Supply-chain hygiene: lock without hashes, dev and runtime mixed, floating Docker tag |
| SR3-09 | Info | confirmed by PoC | Flush/retention readiness: company delete cascades and silently unlinks confirmed customers; no purge path |
| SR3-10 | Info | confirmed / theoretical | Config hardening: unvalidated endpoint URLs, `extra="ignore"`, password in `-x db_url`, no timeouts |
| SR3-11 | Info | confirmed by PoC | Input limits exist only at the YAML/CLI edge (service layer accepts any URL scheme, no size cap on `icp load`, `k` unbounded) |

---

### SR3-01 - Supabase hosting: no RLS, no REVOKE for the Data API roles
- Severity: **Medium**, as a gate for the hosted demo. Nothing is deployed, so there is no live exposure.
  Supabase's own linter rates "RLS disabled in public" as an error.
- Status: likely. This is platform behaviour (default privileges on `public` for `anon` /
  `authenticated` when the Data API is on). I have no Supabase instance to test. Confirmed in
  this repo: no RLS or REVOKE statement exists anywhere.
- Where: `backend/alembic/versions/0001_initial.py` (all tables created in `public`, no
  `ENABLE ROW LEVEL SECURITY`, no `REVOKE`), `backend/.env.example:17`, `docs/DECISIONS.md` F4
  ("used as plain Postgres").
- Description: the app talks to Supabase as a plain Postgres client, so RLS is invisible to it. The
  Data API (PostgREST) still publishes `public` tables to anyone holding the project URL and the
  `anon` key. That key is public by design, and any later front end or leaked screenshot reveals it.
  The tables hold profiles, evidence quotes, customer notes and eval reports.
- Exploit scenario: the demo ships, the anon key and project URL appear in a front-end bundle or
  a screenshot, and `GET /rest/v1/known_customer` returns every row (writes too, if grants allow).
- Fix: add migration `0002_lockdown`. Enable RLS on every table including `alembic_version`, and
  revoke access from the API roles only when they exist, so local Postgres still works:
  ```sql
  DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
      REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
      ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
    END IF; END $$;
  ALTER TABLE <each table> ENABLE ROW LEVEL SECURITY;  -- no policies = deny all for API roles
  ```
  The app's `postgres` role bypasses RLS. Also switch off the Data API in the dashboard and add
  a test that every `Base.metadata` table has `relrowsecurity`. Put the `vector` extension in the
  `extensions` schema.
- PoC: none possible locally. Evidence by `grep -rn -i "row level\|revoke\|grant" backend/alembic` (no hit).

### SR3-02 - TLS not enforced or documented for the hosted database
- Severity: Low. It needs an active network attacker, but the payload is the DB password and all data.
- Status: confirmed by PoC.
- Where: `backend/app/db/session.py:32` (`create_engine(resolved, pool_pre_ping=True)`, no
  `connect_args`), `backend/.env.example:17` and `README.md` (Supabase advice shows a URL with no `sslmode`).
- Description: libpq's default `sslmode=prefer` falls back to clear text. The PoC connects to the
  local server with no `sslmode` and `pg_stat_ssl.ssl = false`, with no warning. `sslmode=require` is
  rejected only because the local server lacks TLS. `require` still skips certificate verification;
  only `verify-full` with the Supabase CA stops a MITM.
- Exploit scenario: a demo operator on public Wi-Fi runs `tt db upgrade` against Supabase. An
  on-path attacker strips the TLS negotiation and reads the credentials.
- Fix: document `?sslmode=verify-full&sslrootcert=<supabase CA>` (at least `require`) in
  `.env.example` and README. Add a startup check (see SR3-03) that rejects a non-loopback host
  without `sslmode` in `require|verify-ca|verify-full`. Tell users to URL-encode special characters
  in the password. For the transaction pooler (port 6543) set `prepare_threshold=None` in `connect_args`
  (psycopg3 server-side prepared statements break there; this is an availability note).
- PoC: `scratchpad/sec3/poc9_env_guard_and_tls.py`

### SR3-03 - Dev credentials unguarded; `environment` is dead; README password advice ineffective
- Severity: Low today (the default host is `localhost` and the port is loopback-bound). It becomes
  Medium if the compose file is ever widened. `docs/ARCHITECTURE.md` section 4 claims "No default
  passwords outside dev", but nothing enforces it.
- Status: confirmed by PoC.
- Where: `backend/app/config.py:32` (`environment: Literal["dev","test","demo"]`, never read
  anywhere in `app/`), `config.py:36-40` (defaults `tamtam:tamtam`), `docker-compose.yml:10-11`,
  `README.md:65`, `config.py:96-102`.
- Description:
  1. `ENVIRONMENT=demo` with no `DATABASE_URL` runs happily with `tamtam:tamtam`. Nothing checks
     `.environment`.
  2. The README says to "set `POSTGRES_PASSWORD` (and `DATABASE_URL`)" for anything shared.
     Postgres images apply `POSTGRES_PASSWORD` only on first initialisation of the volume. PoC10
     starts a container on an existing volume with a new password: the old password is accepted
     and the new one refused. Anyone who follows the README after the first `make db-up` believes
     the DB is hardened and it is not.
  3. The app and the tests connect as the bootstrap superuser (`rolsuper = t`, checked read-only).
     Any future injection bug would have maximum impact. No injection exists today.
  4. The `.env` permission check only logs a warning, even with `ENVIRONMENT=demo` (PoC8: 0640, 0604,
     0644 and 0660 warn, a 0644 file still loads the key).
  5. The in-container `pg_hba.conf` has `trust` for 127.0.0.1/::1 (image default). Host
     connections arrive via the Docker bridge and hit `scram-sha-256`, as the wrong-password PoC shows.
     This is OK, but it should be known.
- Fix: in `Settings`, add a validator: when `environment != "dev"`, reject a `database_url` whose
  password is `tamtam` or whose host is localhost, require `sslmode` (SR3-02), and fail on an
  open `.env` (exit instead of warn). Print the target `host/dbname` (never the password) before
  `tt db upgrade` and other write commands. Fix the README: change the password with
  `ALTER ROLE ... PASSWORD` or recreate the volume (`docker compose down -v`). Create a
  non-superuser app role for the demo and document it.
- PoC: `poc9_env_guard_and_tls.py`, `poc10_password_change_noop.py`, `poc8_env_perm_warning.py`

### SR3-04 - Test fixtures trust `TEST_DATABASE_URL` blindly
- Severity: Low. It needs a misconfiguration, but the effect is destructive.
- Status: confirmed by PoC (import only; no connection is made).
- Where: `backend/tests/conftest.py:29-30`
- Description: conftest copies `TEST_DATABASE_URL` into `DATABASE_URL` for the whole session,
  which is good. It never checks that this URL differs from the real `DATABASE_URL`, targets a
  loopback host, or has a name ending in `_test`. If `TEST_DATABASE_URL` (env or `backend/.env`)
  points at `tamtam` or a Supabase URL, `engine` runs `alembic upgrade head` there. In addition,
  `tests/db/test_cli.py:98` deletes the ICP `tamtam-default` (which sets `scope.icp_profile_id` to
  NULL for every scope that used it, silently removing its goals), `test_session.py` commits rows,
  and `test_migrations.py:104/124` runs `CREATE/DROP DATABASE`. The PoC shows conftest accepting the
  dev database name and rewriting `DATABASE_URL` to it.
- Exploit scenario: a developer copies the Supabase string into both URL variables "to test against
  the real thing". `make test-integration` deletes the production default ICP.
- Fix: in conftest, `pytest.exit` unless the database name ends with `_test` and the host is loopback
  (opt-out only via an explicit `ALLOW_REMOTE_TEST_DB=1`), and unless the URL differs from the
  non-test `DATABASE_URL`.
- PoC: `scratchpad/sec3/poc14_test_db_guard.py`

### SR3-05 - Lost update: a human confirmation can be overwritten by `set_match`
- Severity: Low. A single-user CLI, and the current caller uses short sessions, so the window is one
  round trip. The invariant stated in the module docstring ("a human confirmation is never undone
  by automatic matching") is still violated, and it corrupts the eval ground truth.
- Status: confirmed by PoC (two variants).
- Where: `backend/app/services/known_customers.py:76-80` (`_require`), `:99-102` (the check),
  `:102-110` (UPDATE without a guard).
- Description: the CONFIRMED check reads `customer.match_status` from a plain SELECT, then writes
  with an unconditional UPDATE and no row lock. (A) In a long-lived session, SQLAlchemy returns the
  identity-mapped object with its stale status (`expire_on_commit=False`), so a confirmation
  committed elsewhere in the meantime is not seen at all. (B) With a fresh session, a commit that
  lands between the SELECT and the UPDATE (READ COMMITTED) is overwritten. PoC result: the row ends
  `candidate` / `not_found` with the human's `registry_id` still set.
- Exploit scenario: `tt customers import` runs while someone confirms a customer in another shell. The customer silently
  drops out of the leave-one-out ground truth, and n_customers_used shrinks without any error.
- Fix: select with `.with_for_update()` and `execution_options(populate_existing=True)` in
  `_require` (or do `UPDATE ... WHERE id=:id AND match_status <> 'confirmed' RETURNING`). Add a
  two-connection test.
- PoC: `scratchpad/sec3/poc3_lost_update_confirm.py` (needs the throwaway DB, see section 6)

### SR3-06 - NUL / lone surrogate in LLM output makes a profile unsaveable
- Severity: Low. It is a robustness and cost issue, not data exposure.
- Status: DB behaviour confirmed by PoC. That an injected page can make the LLM emit `\u0000` is likely but untested here.
- Where: `backend/app/services/profiles.py:64-65,70` (`data`, `evidence`, `icp_reasons` go to JSONB
  as the model returned them). `pages.py` strips NUL from the excerpt but nothing else is cleaned
  at the persistence boundary. (`profile_text` is cleaned upstream by `sanitize_text`.)
- Description: Postgres rejects `\u0000` in JSONB and text, and lone surrogates in JSON. PoC:
  `save_extraction` raises `DataError` for NUL in `profile.data`, in an evidence quote and in
  `icp_reasons`, and for a lone surrogate in `data`. The pipeline isolates the company
  (`pipeline/steps.py:450`), but no row is written, so every refresh calls the LLM again for that company.
- Exploit scenario: a hostile site prompt-injects "put the NUL character in one_liner". That company is permanently
  unprofilable and costs one LLM call per run.
- Fix: run a recursive scrub (drop `\x00` and lone surrogates) over `data`, `evidence` and
  `icp_reasons` in `save_extraction`, reusing `sanitize_text`.
- PoC: `poc4_sql_and_input_handling.py` (section C), `poc5_like_surrogate_scope.py`

### SR3-07 - `.gitignore` gaps
- Severity: Low (no secret is present today; no commit exists yet).
- Status: confirmed with `git check-ignore`.
- Where: `.gitignore:1-5`
- Description: only `.env` and `*.env` are ignored. NOT ignored: `.env.local`, `.env.production`,
  `.env.demo`, `.env.test`, `.env.dev`, `.env.backup`, `.envrc`, `*.pem`, `*.key`, `service-account.json`,
  `*.dump` / `*.sql` backups, `.claude/settings.local.json`. `.env.local` is the standard name for
  Vite and the Supabase CLI, which M2 will use. Confirmed OK: `.env`, `backend/.env`, `reports/`
  (any depth), `*.pdf` (except `docs/**`), `node_modules/`, `.venv/`.
- Fix: add `.env.*` with `!.env.example` after it, `.envrc`, `*.pem`, `*.key`, `*.dump`,
  `service-account*.json`, `.claude/settings.local.json`.
- PoC: command in section 5.

### SR3-08 - Supply-chain hygiene
- Severity: Low. The pip-audit result is clean (section 4).
- Status: confirmed.
- Where: `backend/requirements.lock`, `backend/pyproject.toml`, `docker-compose.yml:6`
- Description:
  1. No hashes (pip-audit itself warns). A compromised index or mirror cannot be detected.
  2. The lock is a flat `pip freeze` that mixes runtime and dev tools (pytest, mypy, ruff, respx,
     types-PyYAML) and has no header saying how it was generated.
  3. README offers two installs: `pip install -e ".[dev]"` resolves floating lower bounds
     (`sqlalchemy>=2.0.30`, `typer>=0.12`, ...) at install time and can differ from the lock;
     `pip install -r requirements.lock` does not install the project, so `tt` is missing.
  4. `pgvector/pgvector:pg16` is a mutable tag. Digest pulled on this machine:
     `sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`.
  5. Two HTTP stacks are installed (httpx 0.28.1 / httpcore 1.0.9 for the crawler, httpx2 2.13.1 pulled in by
     `anthropic` and `mcp`). Worth a note for the crawler reviewers; not a finding here.
- Fix: generate `requirements.lock` and a separate `requirements-dev.lock` with
  `uv pip compile --generate-hashes` (or pip-tools), install with `--require-hashes`, and add the
  generation command as a header. Pin the Docker image by digest (`image: pgvector/pgvector:pg16@sha256:...`).
  Run pip-audit in CI.
- PoC: `poc11_lock_graph.py`, `pip_audit*.json`

### SR3-09 - Flush / retention readiness and personal data (info)
- Severity: Info. No delete path exists in M1; this is the checklist for when "flush" lands.
- Status: confirmed by PoC.
- Where: `backend/app/db/models.py:143,156,183` (CASCADE from `company`), `:217`
  (`known_customer.company_id` SET NULL), `:75` (`scope.icp_profile_id` SET NULL).
- Description:
  - `DELETE FROM company` removes profile, pages and scope links, and sets
    `known_customer.company_id` to NULL while `match_status` stays `confirmed` (PoC6). Leave-one-out
    then drops that customer and reports it as "no confirmed match", which is wrong. `last_viewed_at` / `touch_viewed`
    exist for eviction, but nothing yet protects "user-touched" rows.
  - Future watchlist / notes tables must not hang off `company` with CASCADE. Without a pin flag, any eviction
    keyed only on `last_viewed_at` will delete them.
  - Personal data that can land in the DB without a filter: `web_page.excerpt` (300 chars of
    meta description or page text, may contain names, emails, phones), evidence quotes (200 chars verbatim in
    `company_profile.evidence`), LLM `data` and `keywords`, and free-text `error` fields
    (`llm_call.error` 500 chars, `pipeline_run.error` 4000 chars). Sole traders and officers are
    excluded at the connector (`est_entrepreneur_individuel=false`, `dirigeants` dropped), and the
    committed fixtures and `data/**` contain company data only (checked).
  - Retention: TTL settings only mark rows stale; nothing deletes. `llm_call`, `pipeline_run` and
    `eval_run` grow without bound against the 500 MB cap (`tt stats db` only reports).
- Fix: when flush is built, delete only rows with `NOT EXISTS` on `known_customer`, watchlist and
  notes, use `ON DELETE RESTRICT` for user-owned tables, and add a purge job for
  `llm_call` / `pipeline_run` / `web_page` older than N days. Optionally redact emails and phone
  numbers from excerpts before storing.
- PoC: `poc6_cascade_flush.py`

### SR3-10 - Config hardening (info)
- Severity: Info.
- Status: confirmed / theoretical (noted per item).
- Where: `config.py:29,88`, `alembic/env.py:30-35`, `db/session.py:32`.
- Items:
  - `tamtam_mcp_url` (and `fr_api_base_url`, `wikidata_sparql_url`) are plain strings. An `http://`
    value sends the bearer token in clear text. Validate `https` for any endpoint that carries a secret. Theoretical (operator-controlled).
  - `extra="ignore"` hides typos: a misspelt `DATABASE_URL` silently falls back to the local dev DB.
    Confirmed by reading; the `.env.example` test checks only the template.
  - `alembic -x db_url=...` (documented in `env.py` and `alembic.ini`) puts the password in `ps` output
    and shell history. Prefer the environment variable.
  - No `connect_timeout`, `statement_timeout` or `lock_timeout` on the engine: a stalled pooler hangs a command, and
    the future API has no query budget. conftest uses `connect_timeout=3`; the app does not.
  - Compose: no `cap_drop`, `no-new-privileges` or `read_only`. Fine for local dev.

### SR3-11 - Input limits only at the YAML/CLI edge (info)
- Severity: Info (defense in depth). Every writer I could find validates today.
- Status: confirmed by PoC.
- Where: `models.py:113,116,120,223` (URL columns are bare `Text`), `services/companies.py:25`
  (`upsert_company`), `domain/schemas.py` (`KnownCustomerSeed`), `cli/icp.py:36`,
  `services/icp.py:45`, `services/lookalike.py:86-113`.
- Description:
  - The services and DB accept any URL scheme: `javascript:`, `file:`, `data:` and
    `http://169.254.169.254/` were all stored (PoC4 D). Today every writer filters first
    (`wikidata.clean_website_url`, `_check_seed` requires http(s), the crawler runs `validate_url` at fetch time,
    and the FR connector sets `website_url=None`). The M2 API/UI or MCP server will be a new writer, and a UI that
    renders `source_url` as an `href` would be a stored-XSS sink.
  - `tt icp load` has no size cap (the customers and scope parsers cap at 1 MB and 200 KB). A 20 MB `name` was
    accepted in 4.7 s (PoC12).
  - Deeply nested YAML (about 10 KB) raises `RecursionError`, which none of the three parsers catches. The CLI prints
    a traceback. No secret appears: the locked Typer 0.27.3 does not show locals by default. `pyproject.toml` allows
    `typer>=0.12`, and I did not test older releases, so set `pretty_exceptions_show_locals=False` explicitly.
  - `find_lookalikes(k=...)` has no upper bound at the service level (the CLI caps `--k` at 200). An M2 endpoint must cap it.
  - `KnownCustomerSeed` and `ScopeQuery` lack `extra="forbid"`. The pipeline rejects unknown keys by hand, so the
    gap is only for non-YAML callers.
- Fix: add a `CHECK (website_url ~ '^https?://')` style constraint or an `HttpUrl` validator at
  the schema level, a size cap and `RecursionError` handling in `icp load`, and `le=` bounds on `k`.
- PoC: `poc4_sql_and_input_handling.py` (section D), `poc12_yaml_inputs.py`, `poc13_yaml_entrypoints.py`

---

## 3. Verified OK (checked, no finding)

SQL and queries
- Every statement is SQLAlchemy Core/ORM with bound parameters. The only raw SQL is `SET LOCAL hnsw.iterative_scan = strict_order`
  (constant, `lookalike.py:59`), `SELECT pg_advisory_xact_lock(:id)` (bound, `env.py:66`) and the constant
  `CREATE EXTENSION` in the migration. No `literal_column`, `.op(`, f-string SQL or `.format` SQL in `app/` or `alembic/`.
  `ruff --select S,B` passes on `app/services`, `app/db`, `config.py`, `alembic`.
- Injection payloads (`x'; DROP TABLE company; --`) through `search_by_name`, `get_by_registry_id`,
  `get_known_customer`, `confirm` and a bad `scope_id` were treated as data or rejected by the UUID type; the table survived (PoC4/5).
  LIKE wildcards `%`, `_` and `\` are escaped correctly (`_like_escape`).
- Vector inputs: the query vector is a bound parameter (`embedding_1`), `LIMIT` is bound, ORDER BY is the fixed distance
  label. `save_embedding` checks dimension 768 and finiteness. `SET LOCAL hnsw.iterative_scan`: `off` before, `strict_order` after the
  helper, `off` again after the transaction ends; failure on old pgvector is absorbed by the savepoint. (Test DB runs pgvector 0.8.7.)
- JSONB values are bound and serialised by the driver, never concatenated.

Transactions and integrity
- Services never commit or roll back. The only `commit` is `session_scope` (`db/session.py:72`). `DbUsageRecorder` opens its own
  `session_scope` on purpose (documented) so usage rows survive a rollback.
- Upserts are race-safe: `ON CONFLICT` on `uq_company_country_registry`, `icp_profile.slug`, `known_customer.name`,
  `scope_company` PK. `create_scope` checks then inserts, but the `name` unique constraint backstops it
  (a race gives `IntegrityError`, not a duplicate). `import_seeds` never resets match state.
- Alembic advisory lock: two concurrent `alembic upgrade head` on an empty DB: one ran the migration, the other waited and did nothing (PoC7).
  `tt db upgrade` cannot downgrade (`base`, `-1` and ranges are no-ops or rejected).

Secrets and config
- `SecretStr` covers every secret (`database_url`, `test_database_url`, `gemini_api_key`, `anthropic_api_key`,
  `tamtam_mcp_token`). 17 probes found no leak: Settings repr/str/`model_dump`/`model_dump_json`, Engine repr,
  OperationalError, malformed URLs (bad port, wrong driver, bogus `sslmode`), `current_revision`, logging at DEBUG, alembic
  output, CLI tracebacks, and the pytest skip text (PoC1, PoC2, `race_*.txt`).
- `.env` is gitignored; `.env.example` has no values for secret keys (a test enforces it) and lists every
  Settings field. The permission warning fires for any group/other bit (`0640`, `0604`, `0644`, `0660`) and not for `0600`/`0700`.
- No secrets in the working tree (pattern scan for AIza / sk- / ghp_ / AKIA / PRIVATE KEY / JWT shapes; test files only hold
  obvious dummies). `git log` is empty, so no history to clean. Fixtures contain business names only; no officers.
- Tests cannot reach the dev DB under the default configuration: `DATABASE_URL` is forced to the test URL before any
  settings read, and `monkeypatch.undo()` restores that value (see SR3-04 for the misconfiguration case).

Infra
- Postgres is published on `127.0.0.1:5433` only (`docker inspect`: `127.0.0.1:5433->5432`); host connections are
  `scram-sha-256` (wrong password refused). Healthcheck uses `$$` correctly. The init dir is mounted `:ro`.
  `01-init.sql` is constant SQL with no secrets and runs once on an empty volume.
- `make db-down` keeps the volume. `make db-reset-test` is hard-coded to database `tamtam_test`, runs through `docker compose exec`, and
  cannot touch `tamtam` or a hosted DB.

Input parsing
- `yaml.safe_load` is the only loader (`services/icp.py`, `pipeline/customers.py`, `pipeline/scopes.py`);
  `!!python/object` and `!!python/name` tags are rejected (PoC12). Alias bombs do not expand (PoC12).
- `parse_icp_yaml` rejects unknown criteria keys; `ScopeSpec` uses `extra="forbid"`; the customer parser checks keys by
  hand, requires http(s) `source_url`, validates the SIREN with Luhn, caps files at 1 MB / 200 KB, and collects all errors.
  Shipped `data/**` files all validate (PoC13).

Supply chain
- `tldextract` never fetches at runtime: `suffix_list_urls=()`, `cache_dir=None` (`crawler/extract.py:109`), and no
  `~/.cache/python-tldextract` exists. No other library in the lock fetches data at import or startup.
- No typosquats or orphans: all 83 locked packages are either declared in `pyproject.toml` or required by another locked
  package (`psycopg-binary` is the `[binary]` extra). The unusual names are legitimate: `httpx2` / `httpcore2`
  (pydantic/httpx2, required by `anthropic` and `mcp`), `librt` and `ast-serialize` (mypyc, required by `mypy`), `annotated-doc` (required by `typer`),
  `mcp-types` (required by `mcp`). PyPI metadata checked for authors and first-upload dates.
  `pip check` is clean, and the installed venv equals the lock exactly.

## 4. pip-audit summary

- Tool: `pip-audit 2.10.1` in a throwaway venv (`scratchpad/sec3/venv`).
- `pip-audit -r backend/requirements.lock --no-deps --disable-pip` against the PyPI JSON service: **No known vulnerabilities found** (83 packages).
- Same run with `-s osv`: **No known vulnerabilities found**.
- Warnings only: "fully hash your pinned dependencies" (SR3-08).
- Raw output: `scratchpad/sec3/pip_audit.json`, `pip_audit_osv.json` (run date 2026-10-16). No CVEs, so there are no fixed versions to report.

## 5. Reproduction notes

Scratchpad: `/private/tmp/claude-501/-Users-a1234-Documents-GitHub/09ecc94a-9687-4eaa-8fb7-441ce6fde086/scratchpad/sec3/`
Run PoCs with `backend/.venv/bin/python <poc>`. PoC3, 4, 5, 6, 7 need the throwaway database:

```bash
docker run --rm -d --name sr3-poc-pg -e POSTGRES_PASSWORD=poc -e POSTGRES_USER=poc -e POSTGRES_DB=poc \
  -p 127.0.0.1:55432:5432 pgvector/pgvector:pg16      # stop with: docker stop sr3-poc-pg
```

| PoC | Covers |
|---|---|
| `poc1_secret_leak_probe.py`, `poc1_traceback_*.txt` | SR3 verified-OK: no secret leak (17 probes) |
| `poc2_skip_message_probe.py` | pytest skip text never contains the password |
| `poc3_lost_update_confirm.py` | SR3-05 |
| `poc4_sql_and_input_handling.py`, `poc5_like_surrogate_scope.py` | SQL injection (none), SR3-06, SR3-11 |
| `poc6_cascade_flush.py` | SR3-09 |
| `poc7_alembic_race.sh`, `race_a.txt`, `race_b.txt` | advisory lock OK, no URL in alembic logs |
| `poc8_env_perm_warning.py` | `.env` permission warning (SR3-03) |
| `poc9_env_guard_and_tls.py` | SR3-02, SR3-03 |
| `poc10_password_change_noop.py` | SR3-03 (README advice no-op) |
| `poc11_lock_graph.py` | SR3-08 (orphans, dev tools in lock) |
| `poc12_yaml_inputs.py`, `poc13_yaml_entrypoints.py` | YAML safety, SR3-11 |
| `poc14_test_db_guard.py` | SR3-04 |

`.gitignore` check for SR3-07:
`for f in .env.local backend/.env.production backend/.env.demo .envrc creds.pem backup.dump; do git check-ignore -q "$f" || echo "NOT ignored: $f"; done`

## 6. Not covered (second pass)

`app/pipeline/**` (apart from the two YAML parsers and `import_customers` flow read for SR3-05/06), `app/cli/**`
(apart from `_common.py` error handling and `icp.py`), connectors, crawler, LLM and enrichment code (SR1/SR2 scope), and anything
involving a live Supabase instance (SR3-01 and SR3-02 should be re-tested once it exists).
