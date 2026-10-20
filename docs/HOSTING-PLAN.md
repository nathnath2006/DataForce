# Hosting plan: backend on Supabase + a free host

Status: **recommendation, nothing below is built yet** (2026-10-20). For the PO to accept or change.
It follows `docs/DECISIONS.md` §H and §K: the app runs locally, with no login, until M3b brings login
**and then** hosting. Hosting without login would expose every workspace to anyone with the address.

Free-plan terms below were checked from memory on 2026-10-20 and change often: confirm them on each
provider's pricing page before step 5.

## 1. Recommendation in one table

| Piece | Recommended (free) | Free alternative | Why |
|---|---|---|---|
| Database | **Supabase**, EU region (Frankfurt), plain Postgres + `vector` | Neon (EU), also free Postgres with pgvector | Already planned (§F2, F5); the migrations already lock out Supabase's public API roles. |
| Python API + UI | **Render**, free web service, Frankfurt, from a Dockerfile | **Koyeb** free instance (Frankfurt); **Google Cloud Run** (europe-west, free monthly quota) | FastAPI already serves the built frontend: one service, one origin, nothing to configure for CORS or cookies. |
| Frontend | Served by the API service (same origin) | Netlify, proxying `/api/*` to the API | One origin keeps the strict CSP, the Origin checks and the session cookie simple. Netlify stays a static preview. |
| Secrets | The host's environment variables | – | Never in git, never in Supabase. |

Fly.io no longer has a free plan for new accounts; Vercel / Netlify functions cannot run this backend
(long requests, pandas / scikit-learn, one process holding in-memory limits).

## 2. What changes, and what does not

Already fine for hosting:
- **Database URL guards** (`backend/app/config.py`): a non-local host must use TLS; `ENVIRONMENT=demo`
  refuses default or weak passwords.
- **Supabase lockdown** (`0002_lockdown`): RLS on every table and no access for `anon` / `authenticated`.
- **Files are stored in the database** (`LargeBinary`), not on disk: a free host's disk is wiped on each
  restart, so this is what we want (but it counts against the 500 MB, see §6).
- **Sealed secrets**: AI keys, TamTam tokens and enriched emails / mobiles are encrypted with
  `DATAFORCE_SECRET_KEY` before they reach the database.

Must change (in this order, see §3):
1. **Login** (M3b) — nothing else can be hosted before it.
2. **The server refuses to run hosted**: `dataforce ui` stops when `ENVIRONMENT=demo`, binds to
   127.0.0.1 and only accepts loopback `Host` headers (`backend/app/api/security.py`).
3. **TamTam sign-in** builds an `http://` callback URL (`backend/app/connectors/oauth.py`,
   `redirect_uri_for`): it must become `https://<public origin>/api/connectors/tamtam/callback`.
4. **In-memory limits** (assistant questions per hour, AI calls per day, flow slots) reset on every
   restart and are per process. Fine with one instance; they move to the database with admin-editable caps.

## 3. Action plan

Each step is one pull request, reviewable on its own. Effort is for one developer.

### Step 1 — Database on Supabase, app still local (½ day, can start now)
Detailed steps were given in chat; in short:
1. Create the project in the EU region; enable the `vector` extension (Database → Extensions).
2. Create a dedicated role (SQL Editor): `create role dataforce_app login password '…';`
   `grant usage, create on schema public to dataforce_app;`.
3. Put the **session pooler** URL (port 5432, user `dataforce_app.<project-ref>`) in `backend/.env` with
   `?sslmode=verify-full&sslrootcert=<Supabase CA>` (at least `sslmode=require`); `chmod 600 backend/.env`.
4. `make migrate`, then optionally `make testdata`.
5. Supabase → Advisors → Security: expect no finding on DataForce tables (re-tests SR3-01 / SR3-02,
   never tested on a real instance).

Done when: `make ui` works against Supabase and the advisor is clean.

### Step 2 — Login, invite-only (M3b) (4–6 days)
- **Users**: email + password, invite-only (an admin creates an invite link; no public sign-up).
  Password hashing with `hashlib.scrypt` from the standard library (no new dependency), per-user salt.
- **Sessions**: a `session` table (hashed token, user, expiry, last seen); cookie `HttpOnly`, `Secure`,
  `SameSite=Lax`, host-only. Logout deletes the row. Idle and absolute expiry.
- **Roles and membership**: `admin` / `user` (the enum exists) and a user ↔ workspace table. Every route
  checks membership; admin routes check the role. "Acting as" goes away: the author is the signed-in user.
- **Keep** the custom `X-DataForce` header and the Origin check on every change (CSRF), JSON-only bodies,
  the CSP.
- **Abuse**: login rate limit per email and per IP, constant-time comparison, same answer for an unknown
  email and a wrong password.
- **Settings > You**: change password (current password required; other sessions are signed out).
- Migration `0008_auth`, tests for isolation (a user never sees a workspace they are not a member of).

Done when: every API route returns 401 without a session and 404 for another workspace's ids.

### Step 3 — Make the server hostable (1–2 days)
- New settings: `PUBLIC_ORIGIN` (for example `https://dataforce.onrender.com`), `ALLOWED_HOSTS`,
  `TRUST_PROXY` (read `X-Forwarded-Proto` / `-For` from the host's proxy only).
- New command `dataforce serve`: binds `0.0.0.0:$PORT`, one worker, refuses to start unless login is
  on, `ENVIRONMENT=demo`, a secret key is set and the database URL uses TLS. `dataforce ui` stays local.
- Security headers: add `Strict-Transport-Security` when hosted; keep the rest.
- `redirect_uri_for` uses `PUBLIC_ORIGIN` (https) when hosted.
- `GET /api/health` (no data, no auth) for the host's health check.
- A `Dockerfile` (Python 3.13 slim, `pip install --require-hashes`, frontend built in a first stage,
  non-root user) and a `render.yaml` blueprint. Migrations run as a one-off job before each deploy,
  never at startup.

Done when: the Docker image runs locally with `ENVIRONMENT=demo` against Supabase, behind https.

### Step 4 — Admin-controlled caps (1–2 days)
- A `workspace_setting` table (name, value, updated by, updated at) holding overrides of the allow-listed
  limits shown on the Admin page today (`_LIMITS` in `backend/app/api/routes/admin.py`).
- Each limit has a **hard ceiling in code** that an override can never exceed (cost guard), and the
  `.env` value stays the default.
- The per-hour / per-day counters move to the database, so they survive restarts.
- Admin page: the limits become editable for admins; every change is logged (who, when, old, new).

### Step 5 — Deploy (½ day)
1. Render → New → Blueprint from the repository (or a Web Service from the Dockerfile), region Frankfurt.
2. Environment variables: `ENVIRONMENT=demo`, `DATABASE_URL` (Supabase, TLS), `DATAFORCE_SECRET_KEY`
   (generate with `dataforce secrets init`, then copy; **keep a copy offline**: losing it means every
   sealed value is unreadable), `PUBLIC_ORIGIN`, `ALLOWED_HOSTS`. AI keys stay per workspace in the UI.
3. Run the migration job, create the first admin with a one-off command (`dataforce users create-admin`).
4. Netlify: either retire it, or make it proxy `/api/*` to the Render URL (`[[redirects]] … status = 200`)
   and set `PUBLIC_ORIGIN` to the Netlify origin. One origin only, never both.

### Step 6 — Security review and checks (1 day)
- A new report `docs/security/SR18-hosting.md`: login, sessions, membership isolation, proxy headers,
  OAuth callback, the admin caps, and the deployed headers (securityheaders-style check).
- Re-run the Supabase security advisor; confirm `anon` and `authenticated` cannot read any table with the
  project's anon key.

### Later — per-person mailbox
Needs step 2. Each user connects their own Gmail / Outlook (read-only OAuth), only emails with CRM
contact addresses are kept and filed under contact, account and deal, AI suggestions carry the AI badge
and stay suggestions until accepted, and disconnecting deletes the token and the copied emails.

## 4. Order and total

| Step | Effort | Blocks hosting |
|---|---|---|
| 1. Supabase database, local app | ½ day | no (do it now) |
| 2. Login (M3b) | 4–6 days | **yes** |
| 3. Hostable server | 1–2 days | **yes** |
| 4. Admin caps | 1–2 days | no |
| 5. Deploy | ½ day | – |
| 6. Security review | 1 day | **yes** |

About 8–12 working days in total; steps 1 and 4 can run in parallel with the others.

## 5. Running costs

€0 on the free plans, with these limits:
- **Supabase free**: 500 MB database, 2 projects, the project **pauses after about a week without
  activity** (resume from the dashboard), no downloadable backups on the free plan.
- **Render free**: 512 MB memory, the service **sleeps after about 15 minutes idle** (the next visit waits
  up to a minute), a monthly cap on running hours.
- **Koyeb free**: one small instance (512 MB) that scales to zero when idle.
- **Cloud Run**: a free monthly quota of requests and CPU time; needs a Google Cloud billing account.

## 6. Risks and how to handle them

| Risk | Handling |
|---|---|
| 512 MB is tight: pandas, scipy and scikit-learn load ~250–350 MB, a large flow can go past it | One worker; keep `FLOW_MAX_ROWS` low on the free plan; move to a 1–2 GB plan if runs get killed. |
| Uploads count against the 500 MB database | Keep `UPLOAD_MAX_BYTES` small; the Admin page already shows usage against `DB_QUOTA_MB=500`. |
| No backups on Supabase free | `pg_dump` from your computer before each migration and on a schedule; upgrade when real data arrives. |
| Losing `DATAFORCE_SECRET_KEY` | Store it in a password manager; without it, AI keys, tokens and enriched values must be re-entered. |
| Cold starts (free hosts sleep) | Acceptable for a demo; a paid instance or a keep-alive is not worth it before real users. |
| Real customer data on free plans | Free plans are fine for synthetic data. Before real data: a paid Supabase plan (backups), a DPA with each provider, and EU regions only. |

## 7. Decisions needed from the PO

1. Accept Render (or pick Koyeb / Cloud Run) and Supabase EU.
2. One origin served by the API (recommended), or Netlify proxying `/api/*`.
3. Login scope: invite-only email + password as planned, or also Google / Microsoft sign-in.
4. Whether synthetic data only is hosted first (recommended), real data after the review and a paid plan.
