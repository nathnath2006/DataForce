# Workspace onboarding contract (2026-10-20)

PO feedback after the first Supabase setup: the first admin landed on a bare "No workspace yet" page
with a small modal, the workspace they created then showed **"Workspace not found"** until a manual
refresh. Wanted instead: right after the first sign-in, a real onboarding where you **choose a test or a
real workspace**, give it a name, and watch a **nice animation** while it is created. Never an error
for a workspace that exists.

Root cause of the "not found": `Home` and `Shell` share the cached `/workspaces` query (fresh for 30 s).
`Home` called `reload()` and navigated at once; `Shell` mounted with the cached empty list, `isFresh`
skipped the refetch, and `!ws` rendered "not found".

Also in this round: Supabase advisor WARN `function_search_path_mutable` on `enforce_append_only()` and
`guard_truncate()`.

## 1. Backend (owner: backend builder)

### 1.1 Migration `0012_onboarding` (revision `"0012_onboarding"`, down `"0011_auth"`)
- `ALTER FUNCTION enforce_append_only() SET search_path = ''` and the same for `guard_truncate()`.
  Both bodies only use built-ins (`current_setting`, `coalesce`, `to_jsonb`, `RAISE`), which live in
  `pg_catalog`, always searched. Downgrade: `ALTER FUNCTION … RESET search_path`.
- `workspace.setup_state` `VARCHAR(16) NULL` with `CHECK (setup_state IN ('preparing'))`.
  NULL = ready. Model column `setup_state: Mapped[str | None]`.
- Note for later: branch `wip/m5-wave3` holds `0012_user_settings`; when it lands it becomes `0013_…`
  with `down_revision = "0012_onboarding"`.

### 1.2 API
`WorkspaceCreate` gains `kind: Literal["real", "test"] = "real"`.
`WorkspaceOut` gains `setup_state: Literal["ready", "preparing"]` (NULL → `"ready"`).

`POST /api/workspaces` (superadmin, unchanged auth):
- `kind="real"`: as today (empty workspace, `is_demo=False`, admin membership, 201).
- `kind="test"`: synthetic workspace filled in the background.
  1. Refuse with **409** if a test fill is already running in this process (one at a time), and with
     **409** if `pg_database_size` is above 80 % of `settings.db_quota_mb` (message says so plainly).
  2. Create the workspace `is_demo=True`, `setup_state='preparing'`, admin membership; **commit**;
     answer **201** with `setup_state="preparing"`.
  3. Start a daemon thread (own session from the app's session factory, never the request session) that
     fills it in **one transaction**: `generate("planted", 42)` → load into the *existing* workspace →
     `backfill_workspace` (stage history, activities, tasks) → `backfill_logins` (rep logins, empty
     password, which only work on loopback) → `setup_state = NULL` → commit.
  4. On any exception: rollback, then in a fresh transaction delete that workspace (it is demo and was
     created by this call), record the failure in the registry, log the exception (never a URL or a
     secret). The error shown to the UI is generic: "Preparing the test workspace failed; nothing was kept."

`GET /api/workspaces/{slug}/setup` (superadmin) →
`{ "state": "ready"|"preparing"|"failed"|"interrupted", "step": str|null, "done": int, "total": int, "error": str|null }`
- `preparing` with the current step from the in-process registry.
- `interrupted`: the row says `preparing` but no job runs in this process (server restarted mid-fill).
- `failed`: from the registry after a failed fill (workspace already deleted; registry entry kept 10 min).
- `ready`: `setup_state` NULL. 404 when neither the workspace nor a registry entry exists.

`DELETE /api/workspaces/{slug}` (superadmin): **only** a demo workspace (`is_demo=True`) and never while
its fill is running (409). 204. Used to clear an interrupted test workspace. A real workspace → 403.

Steps (stable ids, English labels, in order) — `total` = 8:
`workspace` "Creating the workspace", `people` "Adding the sales team", `companies` "Companies and
accounts", `contacts` "Contacts", `deals` "Deals", `meetings` "Notes and meeting transcripts",
`activity` "Stage history, activities and tasks", `logins` "Demo sign-ins".
The loader gets an optional `on_step: Callable[[str], None] | None` and an optional existing
`workspace` (refactor `load_dataset`, CLI behaviour unchanged).

Registry: `app/services/workspace_setup.py`, a dict guarded by a `threading.Lock`. One process, one
instance (hosting plan §2 item 9): documented in the module docstring.

### 1.3 Tests
Unit + integration (existing fixtures): real create unchanged; test create → 201 preparing, status
progresses to ready, counts > 0, rep logins created; 409 when one is running; quota 409; failure path
deletes the workspace and reports `failed`; interrupted; DELETE demo ok / real 403 / running 409;
non-admin 403 on all three; migration up/down on the test DB; functions have `search_path=""`
(`pg_proc.proconfig`). Then `make api-types` (the backend builder owns `frontend/src/openapi.snapshot.json`
and `frontend/src/api.gen.ts`).

## 2. Frontend (owner: frontend builder)

### 2.1 No more false "not found"
- After any workspace creation: `invalidate("/workspaces")` **and** wait until the refetched list
  contains the slug before navigating (helper `refreshWorkspacesUntil(slug)` in `data/`).
- `Shell`: when the slug is missing from a list that has not been refetched since mount, show
  `<Loading />` and force one reload; render "not found" only after a fresh answer confirms it.
  Restyle that state (centered card, "Back to my workspaces"), not a bare `<p>`.

### 2.2 Onboarding (`/welcome`, inside `RequireAuth`, admin only)
- `Home` with zero workspaces: admin → `<Navigate to="/welcome" />`; non-admin → a calm card
  "You are not in a workspace yet. Ask your administrator to add you."
- Full-page layout on the auth look (`AuthShell` / `LavaBackground`), Helvetica, tokens from
  `docs/VISUAL-IDENTITY.md` (blue acts, yellow marks, honest state; quiet/ghost buttons, no blue links).
- Step 1 — two large choice cards:
  - **Test workspace**: "Synthetic companies, deals, meetings and six demo reps, to try every feature.
    Always marked as synthetic." Badge "Synthetic".
  - **Real workspace**: "Empty, for your own data: import CSV or Excel, connect TamTam, add records."
- Step 2 — name (autofocus) + slug (auto from the name, editable under "Advanced"). Back / Create.
- Step 3 — creation screen (§2.3). On `ready`: refresh the list (§2.1), then go to `/w/{slug}/home`.
- The top-bar "New workspace" modal reuses the same chooser + name form; Create opens the same
  creation screen as a full-screen overlay.

### 2.3 The creation animation (own Canvas 2D, no new dependency)
- Ideas from reactbits.dev backgrounds (Micro Slats, Pattern Waves): **ideas only**, React Bits is
  MIT + Commons Clause and uses WebGL libraries. Write our own Canvas 2D.
- Concept: a field of small round dots (the sign-in dot sea) drifts, then **gathers into the workspace
  name** the user typed, letter by letter, as the steps complete (progress = `done / total`); at
  `ready` the name settles crisp with a single soft glint, then the app opens.
- Under it, the honest step list from `GET /setup` (poll every 700 ms): done = check, current = subtle
  pulse, upcoming = muted. Never a fake percentage: progress comes only from the server.
- Real workspace: no polling; the name assembles over ~1.2 s, then opens.
- `prefers-reduced-motion`: no particles; the name fades in and the step list carries the progress.
- `failed`: the dots fall loose, honest message from the server, buttons "Try again" (back to step 2
  with the same choice) and "Choose again". `interrupted`: "The server restarted while preparing" +
  "Remove and start again" (DELETE then step 2).
- Light and dark themes; canvas sized to devicePixelRatio; stops its animation frame on unmount.

### 2.4 Types and tests
- Until `api.gen.ts` is regenerated, declare the new request/response types in
  `frontend/src/onboarding/types.ts` exactly as §1.2. Do not edit `api.gen.ts` or the snapshot.
- Vitest for the pure parts: slugify, step-state mapping, name-to-dot-targets sampling, the
  refresh-until helper. `npm run typecheck`, `npm test`, `npm run lint` (if present) green.

## 3. Security review (after both builders)
Admin-only on the three routes; the thread never uses the request session; no secret or URL in logs
or errors; one fill at a time; quota check; DELETE cannot touch real workspaces or another tenant's
data; the 404/403 split does not leak workspace existence to non-admins; reduced motion respected.
