# SR4 - CRM data core, append-only DB, services, config and infra (Milestone 1)

Reviewer: Security Reviewer #4 (read-only). Date: 2026-10-17.
Scope: `backend/alembic/versions/0001_initial.py`, `0002_lockdown.py`, `alembic/env.py`, `backend/app/db/*`,
`backend/app/services/*` (except `analytics.py`), `backend/app/config.py`, `backend/app/cli/_common.py`,
`backend/app/cli/db.py`, `docker-compose.yml`, `docker/`, `Makefile`, `backend/.env.example`,
`backend/requirements*.lock`, `backend/pyproject.toml`, `backend/tests/conftest.py`.

Method: static reading, then PoCs against the test database `dataforce_test` only (every write sat in a
transaction that was rolled back, or in a uniquely named workspace that was deleted afterwards; verified
0 leftover rows). `backend/.env` was not read (it does not exist on this machine). No project file was
modified except this report. PoCs: `/private/tmp/claude-501/-Users-a1234-Documents-GitHub/09ecc94a-9687-4eaa-8fb7-441ce6fde086/scratchpad/sr4/poc1.py` to `poc8.py`.

## 1. Summary

Overall: the design holds. The trigger blocks every UPDATE and DELETE path I tried except the ones it allows
on purpose; every service function is workspace-scoped; erasure leaves no CRM row behind; no string-built
SQL; SR3 fixes all still hold. No Critical or High issue. The main gaps are an unguarded TRUNCATE, a
concurrency hole that can fork a correction chain and leave "deleted" text alive, and run / LLM-usage
records that are not workspace-scoped (a gate for M2, harmless for the single-user CLI).

| ID | Severity | Title | Where |
|---|---|---|---|
| SR4-01 | Medium | TRUNCATE on `note` / `comment` (also via `TRUNCATE contact/account/workspace CASCADE`) bypasses the append-only trigger | `0001_initial.py:226-231` |
| SR4-02 | Medium | Concurrent corrections fork a chain: one version becomes invisible and survives a soft delete | `0001_initial.py:191`, `services/_appendonly.py:38-50,93-120,123-143` |
| SR4-03 | Medium (gate for M2) | `run` / `llm_call` services are not workspace-scoped (get/finish by bare id, `list_runs` and `usage_summary` global) | `services/runs.py:52-90`, `services/llm_usage.py:55-72` |
| SR4-04 | Low | `author_id` / `deleted_by_id` can be set to NULL by any UPDATE, not only by the user-delete FK action | `0001_initial.py:53-56,63-68` |
| SR4-05 | Low | Cycle check in `set_reports_to` is racy: two concurrent calls create A to B to A | `services/contacts.py:48-72` |
| SR4-06 | Low | Erasure leaves residue: `run.params/result/error`, `llm_call.error`, free-text mentions in other rows | `services/accounts.py:44-53`, `services/contacts.py:93-102`, `services/runs.py`, `services/llm_usage.py:44` |
| SR4-07 | Low | No DB-level workspace consistency (no composite FKs): the DB accepts cross-workspace references | `0001_initial.py:79-196` |
| SR4-08 | Low | Unhandled DB errors print SQL parameters (note bodies, names) in CLI tracebacks | `cli/_common.py:28-46,72` |
| SR4-09 | Info | Erasure flag is a plain GUC and the table owner (a superuser in dev) can disable the trigger | `0001_initial.py:33-36`, `services/_common.py:57-74` |
| SR4-10 | Info | Migrations have no `lock_timeout`; `ENABLE ROW LEVEL SECURITY` takes ACCESS EXCLUSIVE locks | `alembic/env.py:62-83`, `0002_lockdown.py:49-51` |
| SR4-11 | Info | `make help` is broken (unbalanced quotes) | `Makefile:12-23` |
| SR4-12 | Info | `sslmode=require` does not verify the certificate; `cannot reach the database` text also covers auth / TLS failures | `config.py:117-129`, `cli/_common.py:37-42` |

## 2. Findings

### SR4-01 - TRUNCATE bypasses the append-only trigger (Medium)
- Evidence (`poc1.py`, `poc3.py`): on `dataforce_test`, as the app role, in a rolled-back transaction:
  `truncate note` -> ALLOWED; `truncate contact cascade` -> ALLOWED (empties `note`, and `comment` through `account`).
  The trigger is `BEFORE UPDATE OR DELETE ... FOR EACH ROW` (`0001_initial.py:229`); row triggers never fire
  on TRUNCATE. By contrast `delete from note`, `delete from contact`, `delete from account`,
  `delete from workspace` are all refused without the flag.
- Impact: one statement wipes the whole history of every workspace with no flag and no trace. Reachable by
  any future SQL bug or a careless maintenance script; the "append-only even if application code has a bug"
  promise (DECISIONS B) does not cover it.
- Fix (tested in `poc3.py`, all three TRUNCATE forms are then refused, including `CASCADE` from parent tables):
  ```sql
  CREATE FUNCTION guard_truncate() RETURNS trigger LANGUAGE plpgsql AS $fn$
  BEGIN
    IF coalesce(current_setting('dataforce.erasure', true), '') = 'on' THEN RETURN NULL; END IF;
    RAISE EXCEPTION '% is append-only: TRUNCATE refused', TG_TABLE_NAME;
  END $fn$;
  CREATE TRIGGER trg_note_truncate    BEFORE TRUNCATE ON note    FOR EACH STATEMENT EXECUTE FUNCTION guard_truncate();
  CREATE TRIGGER trg_comment_truncate BEFORE TRUNCATE ON comment FOR EACH STATEMENT EXECUTE FUNCTION guard_truncate();
  ```
  Ship as migration `0003`, drop both in its downgrade. Check `tests/db/test_migrations.py` still passes.
  The test fixtures never use TRUNCATE (they roll back), `make db-reset-test` uses `DROP SCHEMA`, unaffected.

### SR4-02 - Concurrent corrections fork a chain; a hidden version survives soft delete (Medium)
- Evidence (`poc6.py`): nothing prevents two notes with the same `corrects_id` (no unique index; the service
  reads the latest version without locking). Two racing `correct_note` calls both attach to the same row.
  Result with two corrections "fix A" and "fix B" of one note: `current_notes` returns only `['fix B']`
  (`_chains` keeps one child per parent in a dict, `_appendonly.py:40`), and after `delete_note` the row
  "fix A" is still live (`deleted_at IS NULL`) but invisible to every service function.
- Impact: integrity of the audit trail (a correction is silently dropped from `history`) and of deletion
  (text the user "deleted" stays in the DB, un-deleted, and would reappear if the chain logic changes or in a
  raw SQL export / analysis). GDPR erasure is unaffected (cascades by parent id).
- Fix: (a) `CREATE UNIQUE INDEX uq_note_corrects ON note (corrects_id) WHERE corrects_id IS NOT NULL;`
  same for `comment` (the loser gets an IntegrityError: map it to `InvalidInputError("this entry was
  corrected meanwhile, reload")`). (b) In `correct()` and `soft_delete()` lock the head first
  (`session.get(model, id, with_for_update=True)` on the chain root, or `select ... for update` on the
  siblings). (c) Optional hardening: make `soft_delete` update every row with the same parent that is
  reachable through `corrects_id`, via a recursive CTE, instead of the Python-built chain.

### SR4-03 - Runs and LLM usage are not workspace-scoped (Medium, gate for M2)
- Evidence (`poc4.py`): `get_run(session, run_id)` returns any workspace's run; `finish_run` takes a bare
  run id (a run of workspace B can be closed or have its `result` overwritten by whoever holds the id);
  `list_runs(session)` without `ws_id` returns every workspace's runs (the output showed B's run);
  `start_run` accepts `ws_id=None`, creating runs that belong to nobody (and survive `delete_workspace`).
  `llm_call` has no `workspace_id` at all; `usage_summary` aggregates the whole database.
  `run.result` holds the full scan report, `run.params` the request.
- Impact: today a single-user CLI, so Low. When the API/MCP arrives, any user could read another team's
  analysis results or usage. It also contradicts "all writes are workspace-scoped" (ARCHITECTURE 4).
- Fix: give `get_run`, `finish_run`, `list_runs` a mandatory `ws_id` and reject
  `row.workspace_id != ws_id` like `get_scoped` does (keep a clearly named `admin_*` variant if a global view
  is needed). Make `start_run`'s `ws_id` required, and `nullable=False` on `run.workspace_id` in a migration
  unless a global run is a real need. Add `workspace_id` to `llm_call` (or only expose `usage_summary(run_id=...)`
  after checking the run belongs to the workspace).

### SR4-04 - author_id / deleted_by_id can be NULLed by a plain UPDATE (Low)
- Evidence (`poc1.py`): `update note set author_id=NULL where id=:n` -> ALLOWED; also combined with a soft
  delete, and `deleted_by_id -> NULL` after the delete. The trigger permits NULL so that the FK `SET NULL`
  works when a user is deleted, but it cannot tell the two cases apart.
- Impact: whoever can run an UPDATE can erase "who wrote / who deleted this" without trace, which weakens
  the audit value of append-only. `deleted_at` itself cannot be rewritten (verified: undelete, re-delete,
  change `deleted_by_id` to another value are refused; a soft delete may carry any timestamp, including a
  future one, minor).
- Fix (tested in `poc7.py`: direct NULL refused, real `DELETE FROM app_user` still nulls the column): in the
  trigger, replace the author check with
  `IF NEW.author_id IS DISTINCT FROM OLD.author_id AND (NEW.author_id IS NOT NULL OR EXISTS (SELECT 1 FROM app_user WHERE id = OLD.author_id)) THEN RAISE ...`
  and do the same for `deleted_by_id` (the referenced user row is already gone when the FK action runs).
  Optionally also refuse a `deleted_at` more than a minute away from `now()`.

### SR4-05 - Cycle check in set_reports_to is racy (Low)
- Evidence (`poc8.py`): two sessions, `set_reports_to(P -> Q)` and `set_reports_to(Q -> P)`, both uncommitted
  before the other commits (READ COMMITTED). Both succeeded; the DB now holds P reports to Q and Q reports to P.
  The DB only has the self-link CHECK (`ck_contact_not_self`); the cycle check reads a snapshot without a lock
  (`contacts.py:58-66`). Cross-account and self links are refused (verified).
- Impact: a cycle breaks any recursive org-chart traversal (M2: a loop or a stack overflow in the renderer).
  Needs two concurrent writers, so Low.
- Fix: at the top of `set_reports_to` lock the account row (`session.execute(select(Account.id).where(Account.id == contact.account_id).with_for_update())`)
  so edits of one org chart serialise; M2 traversals should still carry a visited-set (the service already does).

### SR4-06 - Erasure residue (Low)
- What is removed (verified in `poc4.py`): `erase_contact` removes the contact row (so `source_ref`), all its
  notes (every version, soft-deleted ones included) and nulls the `reports_to_id` of its reports.
  `erase_account` removes the account, contacts, notes, deals (name, lost reason) and comments. After both
  calls: 0 rows left for the id in `note`, `contact`, `deal`, `comment`; the flag is back to `off`.
- Residue not covered:
  1. `run.params`, `run.result`, `run.error` and `llm_call.error` are never touched by erasure. `run.result`
     holds scan reports; `analytics.py` (not reviewed) must be checked to make sure no contact or account
     name enters it. `llm_call.error` keeps up to 500 chars of provider error text, which "can echo request
     fragments" (comment in `llm_usage.py:43`); `scrub_text` only strips NUL / surrogates.
  2. Free text that names the person in other rows (notes on other contacts, account comments, deal names)
     cannot be found by id; that is inherent, but should be stated in the privacy notice.
  3. Physical copies: dead tuples until VACUUM, WAL and the hosting provider's backups.
- Contact data minimality: holds. Columns are `full_name`, `title`, `title_function`, `title_seniority`,
  `source`, `source_ref`; no email or phone. `source_ref` is unvalidated free text (500 chars): a profile
  URL there is personal data, and `require_http_url` (`validation.py`) is not applied to it.
- Fix: store only the exception class in `llm_call.error` and `run.error` (or the first 100 chars after
  removing quoted text); add a test that a finished scan's `run.result` contains none of the contact or
  account names of its workspace; validate `source_ref` as a URL or a short token; document backup retention.

### SR4-07 - No composite FKs: the DB accepts cross-workspace references (Low, defence in depth)
- Evidence (`poc3.py`): a direct INSERT of a note in workspace A pointing at a contact, author and
  `corrects_id` of workspace B succeeded. Only the service layer prevents it (and it does: 20 cross-workspace
  attempts through the services were all refused, see Verified OK).
- Impact: any future writer that bypasses the services (a loader, an import, M2 code using the ORM directly)
  can mix tenants silently.
- Fix (cheap enough before M2): add `UNIQUE (id, workspace_id)` to `account`, `contact`, `app_user`, `note`,
  `comment`, and replace the child FKs by composite ones, e.g.
  `FOREIGN KEY (contact_id, workspace_id) REFERENCES contact (id, workspace_id)`. This also keeps SET NULL
  semantics only with `ON DELETE SET NULL (column)` (PG 15+; the image is PG16).

### SR4-08 - SQL parameters in unhandled DB errors (Low)
- Evidence (`poc8.py`): the SQLAlchemy exception text contains `[parameters: ...]` with the note body
  (`message has [parameters]: True | has body text: True`). `cli_command` only converts `OperationalError`
  (message deliberately dropped: verified no secret or URL in 4 failure modes, see Verified OK) and
  `ServiceError`. Any other `DBAPIError` (IntegrityError, trigger violation, DataError) reaches Typer as a
  traceback holding the statement and the parameters.
- Impact: personal text lands in the terminal, CI logs or screen shares. The DB URL is not in these messages.
- Fix: in `handle_db_errors` also catch `sqlalchemy.exc.DBAPIError` and print
  `type(exc.orig).__name__` plus the first line of `str(exc.orig)` (the server message, which for the trigger
  is safe); set `create_engine(..., hide_parameters=True)` in `session.py:78`.

### SR4-09 - Erasure flag is a plain GUC; owner can disable the trigger (Info)
- Evidence (`poc1.py`): `SET dataforce.erasure='on'` then `DELETE FROM note` works for any session of the
  role; `ALTER TABLE note DISABLE TRIGGER ...` works for the owner; the role is a superuser in dev
  (`rolsuper = t`; also bypasses RLS, as SR3-03 already noted).
- Judgement: expected and acceptable. The trigger is defence in depth against application bugs, not against
  someone holding the DB credentials. The service side is right: the flag is set with `set_config(..., true)`
  (transaction-local, verified reset to empty after the transaction, and to `off` after the statement),
  only `erasure()` sets it, and `erase_contact`, `erase_account`, `delete_workspace` are the only callers
  (`grep` over `app/`). A failure inside the block (tested with a division by zero) leaves the flag `off`.
- Cheap strengthening if wanted: run the app with a non-owner role (migrations as owner) holding
  `GRANT SELECT, INSERT, DELETE ON note, comment` plus `GRANT UPDATE (deleted_at, deleted_by_id) ON note, comment`
  and no `TRUNCATE`, `TRIGGER` or ownership. That removes both the trigger disabling and every UPDATE of other
  columns at the privilege level. Recommended with the hosted demo (SR3-03 item 3 already proposed a
  non-superuser app role).

### SR4-10 - Migrations without lock_timeout (Info)
- `env.py` sets a connect timeout only (by design, for the HNSW build). `0002_lockdown` runs
  `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` on 10 tables, each needing ACCESS EXCLUSIVE; against a live
  database with an idle-in-transaction session it waits forever and queues other queries behind it.
- Fix: `SET LOCAL lock_timeout = '10s'` at the start of the migration transaction (in `env.py`, after the
  advisory lock), and keep statement_timeout off.
- Downgrade safety: `0002` downgrade disables RLS but does not restore grants (stated, and right).
  `0001` downgrade drops every table with the data (no guard); `dataforce db upgrade` only upgrades
  (verified `bogus` revision gives one clean `error:` line).

### SR4-11 - `make help` fails (Info)
- Evidence: `make help` prints the first lines then `/bin/sh: unexpected EOF while looking for matching '"'`,
  exit 2. Cause: `Makefile:21` (`...UPGRADE=1 to bump)` has no closing quote) and `Makefile:22` ends with `""`.
- Fix: close the quote on the `lock` line and use a single `"` on the `notebook` line.

### SR4-12 - TLS and message precision (Info)
- `sslmode=require` encrypts but does not verify the server certificate; `.env.example` correctly offers
  `verify-full` + `sslrootcert`. Consider also requiring `verify-full` when `ENVIRONMENT=demo` and the host is
  remote.
- `handle_db_errors` says "Is it running?" for any `OperationalError`, including a wrong password or a TLS
  failure; only the exception class is shown. Good for secrecy, slightly misleading. Add a hint to also check
  the credentials and `sslmode`.

## 3. Verified OK

Append-only trigger (`poc1.py`, `poc3.py`, on `dataforce_test`):
- UPDATE of `body`, `created_at`, `contact_id`, `corrects_id`, `workspace_id`, `id` refused; `author_id` to another value refused.
- Soft delete is one-way: un-delete, re-delete (tested with `clock_timestamp()`, an earlier same-transaction `now()` test was invalid) and changing `deleted_by_id` to another value are refused.
- DELETE of a note refused; `DELETE` of contact, account, workspace (all cascade to `note`/`comment`) refused without the flag; only `app_user` deletion goes through, and only as SET NULL.
- `corrects_id` ON DELETE CASCADE is reachable only under the flag. A corrects_id cannot form a cycle (cannot be updated, and the target must exist).
- Flag semantics: transaction-local (empty after the transaction), `off` after the erasure statement, `off` after a failed erasure, back to refusal for a direct DELETE afterwards (`poc4.py`). Only `erasure()` sets it; callers: `erase_contact`, `erase_account`, `delete_workspace`.

Workspace isolation (`poc4.py`, two workspaces A and B, 20 attempts through the services, all refused with `NotFoundError` / `InvalidInputError`):
contact with account of B; `reports_to_id` of B on create and on `set_reports_to`; deal `account_id` and `owner_id` of B; note author of B, note on B's contact; comment on B's account; correct, delete and history of B's note via A; delete by a B user (`deleted_by_id`); `set_stage` on B's deal; `erase_contact` / `erase_account` of B via A; `org_chart` of B's account. `set_reports_to` refuses self link, cycle (sequential) and cross-account link. Every `session.get` goes through `get_scoped` / `_require_row`, and the erase DELETEs also carry `workspace_id` in the WHERE clause. (Exceptions: SR4-03 for runs and LLM usage; SR4-05 for the concurrent cycle.)

GDPR: see SR4-06 for what is removed (contact, notes with all versions, reports_to links, source_ref, account comments, deals, contacts) and what is not.

SQL injection: no raw SQL with user data. The only f-string SQL is in migrations over constant table names (`0001_initial.py:229,236`, `0002_lockdown.py:50,57`, with `noqa: S608`); `admin.py` uses fixed `text()`; `session.py:58` uses driver-bound parameters with ints; `erasure()` binds the value; `env.py` binds the advisory lock id. Services use SQLAlchemy expressions only.

RLS lockdown (`poc3.py`): after `alembic upgrade head`, all 10 tables incl. `alembic_version` have `relrowsecurity = true`; `0002` is a no-op for the REVOKE when `anon`/`authenticated` do not exist (local docker, confirmed: no grants to those roles); the DO block covers tables, sequences and default privileges; the test `test_every_model_table_has_rls_enabled` and `test_lockdown_list_covers_every_model_table` guard future tables. Note: `ALTER DEFAULT PRIVILEGES` without `FOR ROLE` only affects the current role, which is the role that creates the tables, so that is the right scope.

SR3 fixes re-verified (`poc5.py`, CLI runs):
- TLS: a remote host without `sslmode=require|verify-ca|verify-full` refused (`prefer`, none); `?host=evil.com`, `?hostaddr=`, a comma-separated host list and `localhost.evil.com` do not bypass; messages show `host:port/db` only.
- Dev credentials: with `ENVIRONMENT=demo` refused `dataforce:dataforce`, an empty password, `PASSWORD` in any case, and (default URL left unset). Unknown `ENVIRONMENT` (`prod`) fails closed (Literal). Passwords of 8+ chars non-listed are accepted (by design).
- Endpoints: `http://evil.com`, `http://localhost` under `demo`, and URLs with credentials refused.
- Secrets in errors / repr: no password in any ValidationError (`hide_input_in_errors`), invalid URL error never echoes the input, `SecretStr` hides the URL in `repr`, `str` and `model_dump_json`.
- `.env` permission check: logic read in `config.py:296-322` (mode check for group/other bits, error outside dev/test). The file does not exist on this machine, so only the code was reviewed.
- Timeouts: live engine reports `statement_timeout = 1min`, `lock_timeout = 15s` per transaction, also on `SessionLocal` sessions; connect timeout 10 s.
- Docker: port mapping `127.0.0.1:5433->5432` confirmed on the running container; image pinned `@sha256:7b822b0a...` and that digest equals the `RepoDigests` of the local `pgvector/pgvector:pg16` image.
- Locks: `requirements.lock` (64 pins) and `requirements-dev.lock` (81 pins): every pin has `--hash=sha256`, no URL or VCS requirement, and all 64 shared versions are identical. `docs/DECISIONS` / README use `--require-hashes`. (`pip-audit` is not installed in the venv; no CVE scan was run in this review.)
- Test-DB guard in `conftest.py`: name must end `_test`, differ from the dev DB, loopback only unless `ALLOW_REMOTE_TEST_DB=1`; on refusal `DATABASE_URL` is set to an unroutable placeholder.
- `.gitignore` covers `.env`, `.env.*`, `*.env`, `.envrc`, keys, dumps, `.DS_Store`.

CLI helpers: `dataforce db upgrade` run with a distinctive password marker against 4 failing targets (wrong database, closed port, unresolvable host with TLS, correct host) and `alembic -x db_url=...`: the marker never appears in output (0 hits); the CLI prints one `error:` line with the exception class only; `pretty_exceptions_show_locals=False`. `fail(str(exc))` is used only for `ServiceError` messages (ids and fixed text) and alembic `CommandError`.

## 4. Top 3 fixes

1. SR4-01: add the `BEFORE TRUNCATE` guard triggers on `note` and `comment` (migration `0003`, SQL above, tested).
2. SR4-02: unique partial index on `corrects_id` for both tables plus a row lock on the chain head in `correct()` / `soft_delete()`.
3. SR4-03: make `ws_id` mandatory and enforced in `get_run`, `finish_run`, `list_runs`, `start_run`, and scope `usage_summary`, before any M2 API or MCP exposes them.

---

## Resolution (fix pass, 2026-10-17)

Fixed by fix engineer A. The tech lead verified it by re-running the whole suite: 407 tests pass, `alembic check` is clean, and the dev DB is at `0003_hardening`.

| ID | Status | Where | Test |
|---|---|---|---|
| SR4-01 TRUNCATE bypasses append-only | **Fixed.** BEFORE TRUNCATE statement triggers on `note` and `comment` refuse unless the erasure flag is on. | `alembic/versions/0003_hardening.py` | `test_truncate_is_refused` (covers note, comment, contact cascade, account cascade, workspace cascade) |
| SR4-02 concurrent corrections fork a chain | **Fixed.** Unique partial indexes on `corrects_id` (`uq_note_corrects`, `uq_comment_corrects`). The chain is locked `FOR UPDATE` in `correct()` and `soft_delete()`. A race becomes `InvalidInputError("… corrected concurrently, retry")`. | `0003`, `app/services/_appendonly.py`, `app/db/models.py` | `test_second_correction_of_a_version_is_refused_by_the_index`, `test_concurrent_correction_becomes_a_service_error` (simulated, not two live sessions) |
| SR4-03 runs and LLM usage not workspace-scoped | **Fixed.** `start_run` requires a workspace. `get_run(s, ws_id, run_id)` and `list_runs(s, ws_id, …)` are scoped. `llm_call.workspace_id` added. `DbUsageRecorder(…, *, workspace_id)` and `usage_summary(s, ws_id, …)` are scoped. | `0003`, `app/services/runs.py`, `app/services/llm_usage.py` | `test_runs_and_usage_are_workspace_scoped` |
| SR4-04 author ids could be NULLed by any UPDATE | **Fixed.** NULL is only allowed from the FK `ON DELETE SET NULL` action (`pg_trigger_depth() > 1`). | `0003` | `test_author_cannot_be_nulled_by_direct_update` |
| SR4-05 racy cycle check | **Fixed.** Per-account `pg_advisory_xact_lock` before the cycle check in `set_reports_to` and `create_contact`. | `app/services/contacts.py` | `test_reports_to_takes_the_account_advisory_lock` (checks the lock is held; no two-session race test) |
| SR4-06 erasure residue | **Accepted for M1, re-check in M2.** These are not erased: `run.params` / `result` / `error` (scan results hold group labels such as owner names, never contact names), `llm_call.error`, free text naming the person in other rows, `contact.source_ref` if it holds a profile URL, and dead tuples, WAL and backups until rotation. M2 adds a residue sweep when free-text analysis arrives. | none | none |
| SR4-07 no composite workspace FKs | **Accepted.** The services refuse every cross-workspace reference (20 attempts were refused in the review). Composite FKs are an M3 option. | none | none |
| SR4-08 SQL parameters in CLI tracebacks | **Fixed.** Engine `hide_parameters=True`. Any other `SQLAlchemyError` gives one line with the class name only. | `app/db/session.py`, `app/cli/_common.py` | `test_unexpected_db_error_prints_no_parameters` |
| SR4-09 erasure flag is a plain GUC | **Accepted (defence in depth).** M3 should run the app under a non-owner role with column-level UPDATE grants. | none | none |
| SR4-10 migrations have no lock timeout | **Fixed.** `SET LOCAL lock_timeout='15s'`, `statement_timeout='5min'` in migrations. | `alembic/env.py` | no dedicated test |
| SR4-11 `make help` broken | **Fixed.** `--allow-unsafe` added to all lock commands, so `pip` and `setuptools` are now pinned with hashes. Runtime and dev locks were regenerated without upgrades. | `Makefile`, `requirements*.lock` | `make help` runs; repo-hygiene tests |
| SR4-12 misleading DB error, `sslmode=require` does not verify the certificate | **Fixed (message)** / **documented.** `verify-full` with `sslrootcert` is supported and recommended for Supabase in `.env.example`. | `app/cli/_common.py`, `app/config.py` | none |
