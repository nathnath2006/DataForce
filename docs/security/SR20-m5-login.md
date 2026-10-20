# SR20 - M5 login and visibility

Scope: the M5 login, sessions, members API and row-visibility code (contract: `docs/M5-LOGIN-AND-UI-CONTRACT.md`), reviewed 2026-10-20. Result: 1 high, 2 medium, 3 low, all fixed. Tests are in `backend/tests/auth/test_sr20.py`.

## SR20-1 (high) A workspace admin could take over the superadmin
- **Where:** `app/api/routes/users.py`, `reset_password`, `disable_member`, `enable_member`, `update_member`.
- **Failure:** a workspace admin (not superadmin) could POST `/members/{superadmin_id}/password` and then sign in as the superadmin. Disable, enable and rename (display_name is global) reached users of other workspaces the same way.
- **Fix:** `_may_manage`. A non-superadmin may touch only a user who is not a superadmin and has no membership in another workspace. Otherwise 403. A superadmin may still do everything.
- **Test:** `test_workspace_admin_cannot_take_over_a_superadmin_or_foreign_user`.

## SR20-2 (medium) Deal-level rows leaked on shared accounts
- **Where:** `services/activities.py` (`list_activities`, `require_activity`), `services/tasks.py` (`list_tasks`, `require_task`), `services/timeline.py` (activity, task and document items), `services/documents.py` and `routes/documents.py`.
- **Failure:** rep A and rep B each own a deal on account S. B's activity and task (deal_id = B's deal) showed to A in the lists and the timeline, and A could edit them by id.
- **Fix:** a row with a `deal_id` is visible only if that deal is visible (`visibility.deal_gate`, `check_row_deal`). Account-level rows follow the account. `account_or_deal` and `check_row_account` now test the deal first. The same gate covers documents with a deal (lists, count, `require_document`, timeline).
- **Already correct:** stage events (filtered by `in_deals`) and mailbox messages (filtered by the suggested deal).
- **Test:** `test_deal_level_rows_of_another_rep_are_hidden` (lists, timeline, PATCH, and the admin still sees all).

## SR20-3 (medium) Setup race
- **Where:** `routes/auth.py`, `setup`.
- **Failure:** `admin_exists` then insert with no lock, so two parallel setups could both create a superadmin.
- **Fix:** `pg_advisory_xact_lock(SETUP_LOCK_KEY)` before the check, in the same transaction as the insert.
- **Test:** `test_setup_runs_under_an_advisory_lock` (lock taken before the check; second setup is 403).

## SR20-4 (low) Saved models were not scoped
- **Where:** `routes/saved_models.py`, `services/saved_models.py` (`list_models`, `require_model`, `rename_model`).
- **Fix:** a rep sees and renames only models with `created_by_id` = their CRM identity (404 otherwise). The admin and *see all* members see all.
- **Test:** `test_saved_models_are_scoped_to_their_creator`.

## SR20-5 (low) Unlink bypassed delete_own
- **Where:** `services/mailbox.py`, `unlink_message`.
- **Fix:** the linked activity is deleted with the viewer, so `require_delete` applies.
- **Test:** `test_unlink_needs_delete_own`.

## SR20-6 (low) The rate limiter grew without bound
- **Where:** `auth/ratelimit.py`.
- **Fix:** at most 10,000 keys. Expired windows are dropped on access and when the cap is hit, then the oldest window is evicted. The lockout rule (10 per email, 50 per client per 15 minutes) is unchanged.
- **Test:** `test_rate_limiter_is_bounded_and_drops_expired`.

## Resolution

| Finding | Severity | Status | Test |
|---|---|---|---|
| SR20-1 | high | fixed | `test_workspace_admin_cannot_take_over_a_superadmin_or_foreign_user` |
| SR20-2 | medium | fixed | `test_deal_level_rows_of_another_rep_are_hidden` |
| SR20-3 | medium | fixed | `test_setup_runs_under_an_advisory_lock` |
| SR20-4 | low | fixed | `test_saved_models_are_scoped_to_their_creator` |
| SR20-5 | low | fixed | `test_unlink_needs_delete_own` |
| SR20-6 | low | fixed | `test_rate_limiter_is_bounded_and_drops_expired` |

## Passed
- Every `/api` path is 401 without a session, path tricks included.
- The CSRF guard covers login, setup and logout.
- Non-members get 404 everywhere.
- Reps get 403 on admin routes.
- Login errors are generic, with a dummy hash.
- The empty-password rule (loopback, non-admin, all memberships demo).
- Tokens are 256-bit and stored as hashes only. Cookie flags are set, expiry is 14 and 30 days, sessions end on disable or reset, and each login gets a fresh token.
- Own-data reads are scoped: accounts, deals, contacts, notes, companies, stats, quality, documents, themes, and the viz, flow and score loaders.
- File and Postgres sources are admin-only.
- `owner_id` and `author_id` are rejected in bodies.
- `may_delete` is applied on every delete route.
- The members API is closed to reps, and there is no self-demotion.
- Hashes are never returned.
