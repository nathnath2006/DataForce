# Hosting DataForce online: Supabase + Google Cloud Run (free tiers)

**Status (2026-10-20):**
- **Database: done.** Supabase project `tiluyxvscirxgvwqlaqb` in **eu-west-1 (Ireland)**, schema migrated
  with Alembic as the `dataforce_app` role, synthetic `test-data` loaded (16 MB), advisors checked (§3.1).
  The app still runs on the PO's computer, pointed at Supabase.
- **Login and own-data visibility exist** (M5). The admin-editable caps are being built (wave 3).
- **Hosted mode: done** (§2, 2026-10-20), tested in a local container against Supabase.
- **Deployed 2026-10-20:** https://dataforce-239133496698.europe-west1.run.app (Cloud Run `dataforce`,
  project `gen-lang-client-0115533966`, europe-west1, revision `dataforce-00001`, image `app:6c2169c`).
  Runs as service account `dataforce-run`, which can read only the two secrets. The Netlify site
  redirects every path there. Still to confirm live: the client address used by the sign-in rate limits.
- **Updated 2026-10-20 evening:** revision `dataforce-00002` (image `app:4b61f2b`, M6 and the public demo),
  Supabase at `0015_demo`. Email through Gmail SMTP (`SMTP_USERNAME`, `MAIL_FROM`, secret
  `dataforce-smtp-password`). Cloud Run jobs: `dataforce-demo-reset` (`dataforce demo reset`, about 5 min) and
  `dataforce-migrate` (`alembic upgrade head`, run before a deploy that needs a migration). Cloud Scheduler:
  `dataforce-demo-nightly` at 04:00 Europe/Paris (service account `dataforce-scheduler`, allowed to run that job
  only) and `dataforce-keep-awake` at 09:00. Artifact Registry keeps the last 2 images.

Free-plan terms change often. They were checked on 2026-10-20 from the sources in §6; confirm them
on each provider's page before deploying.

## 1. The shape

| Piece | Where (free) | Notes |
|---|---|---|
| Database | **Supabase**, EU region **eu-west-1 (Ireland)**, plain Postgres + the `vector` extension | 500 MB; the project pauses after about a week without activity (§4) |
| API, UI and the CLI jobs | **Google Cloud Run**, region `europe-west1` (Belgium, a tier-1 price region, close to Ireland) | One container serves the API **and** the built frontend: one origin, so the cookie, CSP and Origin checks stay simple |
| Secrets | **Google Secret Manager** | `DATAFORCE_SECRET_KEY` and `DATABASE_URL`; never in git, never in the image |
| One-off scripts (migrations, user creation, demo backfills) | Your computer, pointed at Supabase; or a **Cloud Run job** | Same image, a different command |
| Frontend preview | Netlify (already set up) | Becomes optional: retire it, or make it proxy `/api/*` to Cloud Run (one origin only, §3.6) |

Cloud Run gives 1 GiB of memory on the free allowance. That suits pandas and scikit-learn better
than hosts capped at 512 MB.

## 2. Before hosting: the code changes (*hosted mode*)

Today the app decides it is "on this computer" from its own `UI_HOST` setting. Behind Cloud Run's
proxy that would be wrong:
- empty demo passwords and the one-click demo accounts would be open to anyone;
- cookies would lack `Secure`.

So hosting needs these changes, all in code, each with tests:

| # | Change | State |
|---|---|---|
| 1 | Login, sessions, roles, own-data visibility | **done** (M5) |
| 2 | Settings `PUBLIC_ORIGIN` (e.g. `https://dataforce-xxxx.a.run.app`; empty = local mode, the only switch), `ALLOWED_HOSTS`, `TRUST_PROXY=1`: the client address for the sign-in rate limits is the **last** `X-Forwarded-For` entry, the one Cloud Run's front end appends (`TRUST_PROXY_HOPS`, default 1); entries the client wrote are ignored | **done 2026-10-20** |
| 3 | When `PUBLIC_ORIGIN` is https: cookies always `Secure`; **no empty passwords and no demo chips**, whatever `UI_HOST` says; HSTS header | **done 2026-10-20** |
| 4 | Command `dataforce serve`: binds `0.0.0.0:$PORT`, one worker. It refuses to start unless the secret key is set, the database URL uses TLS, `PUBLIC_ORIGIN` is https and `ENVIRONMENT=demo`. `dataforce ui` stays local. Migrations never run at start | **done 2026-10-20** |
| 5 | OAuth callbacks built from `PUBLIC_ORIGIN`: TamTam, Gmail, Outlook | **done 2026-10-20** |
| 6 | `Dockerfile` and `.dockerignore`: first stage builds `frontend/`, then Python 3.13 slim with `pip install --require-hashes`; non-root user; `dataforce serve` as the command; Alembic included. `make image` builds it locally as `dataforce:local` | **done 2026-10-20** (tested in hosted mode against Supabase) |
| 6b | `GET /api/health` also runs `SELECT 1` against the database. Cloud Run's health check and the keep-awake job (§4) then count as database activity; answers 503 when the database is down; one probe per 5 s per process, whatever the call rate | **done 2026-10-20** |
| 7 | Admin-editable caps (AI calls, assistant rate, flow limits…) | in progress (wave 3) |
| 8 | Password reset links: today they go to the server log. On Cloud Run that is *Logs Explorer*, readable by the project owner only. Fine for a start; email comes later. The admin can always reset passwords in People and access. Anyone with log access can use a link within its 15 minutes: give *Logs Viewer* to nobody else and never export these logs | acceptable for now |
| 9 | Rate limits, AI budgets and the test-workspace fill registry live in memory, one copy per instance. Keep **one instance** (`--max-instances 1`); move them to the database before scaling | acceptable with one instance |

## 3. Step by step

### 3.1 Supabase (database) — done 2026-10-20
What was done, in order, so it can be repeated on a new project:
1. supabase.com → **New project** in an EU region (ours: **eu-west-1, Ireland**). Strong database
   password in the password manager.
2. **Database → Extensions** → enable `vector`, schema `extensions` (the default). The app role cannot
   install extensions; migration `0001` then finds it and does nothing.
3. **SQL Editor**, the app's own role (not the `postgres` superuser). Only the SCRAM verifier of the
   password goes to Supabase; the password itself stays in `~/.config/dataforce/supabase-app.pw` (0600):
   ```sql
   create role dataforce_app login password 'SCRAM-SHA-256$4096:…';
   grant usage, create on schema public to dataforce_app;
   grant usage on schema extensions to dataforce_app;
   alter role dataforce_app set search_path = "$user", public, extensions;
   ```
   The last line matters: Supabase sets that search path for `postgres` only, and without it migration
   `0001` cannot find the `vector` type. Checked afterwards: login, no superuser, no `createrole`,
   `createdb` or `bypassrls`, member of no Supabase role.
4. **Connect → Session pooler**: host `aws-0-eu-west-1.pooler.supabase.com`, port **5432**, user
   `dataforce_app.tiluyxvscirxgvwqlaqb`. DataForce's form:
   `postgresql+psycopg://dataforce_app.<ref>:<url-encoded password>@aws-0-eu-west-1.pooler.supabase.com:5432/postgres?sslmode=require`
   (better later: `sslmode=verify-full` with Supabase's CA certificate, from the same panel).
   - The **session** pooler, not the transaction pooler on 6543: DataForce uses prepared statements,
     and Cloud Run reaches Supabase over IPv4, which the pooler provides.
5. Commands run from the computer with `DATABASE_URL` set **for that one process only** (a small
   wrapper reads the password file and URL-encodes it); `backend/.env` keeps pointing at local docker:
   `alembic upgrade head`, `dataforce demo testdata`, `dataforce demo backfill-logins --workspace test-data`,
   `dataforce demo backfill-activities --workspace test-data`, then `make ui`. The first admin was created
   on the setup screen.
6. Result, checked with SQL: 36 tables, all owned by `dataforce_app`, row-level security on all, none
   readable by `anon` or `authenticated`. **Advisors → Security:** 36 × INFO "RLS enabled, no policy"
   (expected: deny-all for the public API; per-user policies are an M3b item) and 2 × WARN "function
   search path mutable" on `enforce_append_only` / `guard_truncate`, fixed by migration `0012_onboarding`.
   **Performance:** unused indexes only (empty database).
7. **Latency:** bulk loads from the computer are slow (test data 6 min, activities 9 min) because every
   row is one round trip to Ireland. Normal pages are lighter; measure again from Cloud Run.

### 3.2 Google Cloud (project, billing guard)
1. console.cloud.google.com → **New project** (e.g. `dataforce`).
2. **Billing**: Cloud Run's free allowance needs a billing account with a card. Immediately create a
   **budget** of €1 with alerts at 50 %, 90 % and 100 %, so any spend is visible at once.
3. Enable the APIs: Cloud Run, Artifact Registry, Cloud Build, Secret Manager.
4. Install the `gcloud` CLI, then:
   ```bash
   gcloud auth login
   gcloud config set project <project-id>
   gcloud config set run/region europe-west1
   ```

### 3.3 Secrets
```bash
printf '%s' '<DATAFORCE_SECRET_KEY from your local backend/.env>' | gcloud secrets create dataforce-secret-key --data-file=-
printf '%s' '<the Supabase URL from 3.1>' | gcloud secrets create dataforce-database-url --data-file=-
```
- **Use the same `DATAFORCE_SECRET_KEY` as locally** if you migrate existing data: it decrypts the
  stored AI keys and tokens. Losing it means re-entering them. Keep a copy offline.
- Give the Cloud Run service account the *Secret Manager Secret Accessor* role on both secrets.

### 3.4 Build and deploy (after §2 is done)
The image runs `dataforce serve` (port 8080, one worker). It refuses to start without `PUBLIC_ORIGIN` (https), `DATAFORCE_SECRET_KEY`, a TLS database URL and `ENVIRONMENT=demo`.

```bash
gcloud artifacts repositories create dataforce --repository-format=docker --location=europe-west1
# `make image` builds the same image locally (dataforce:local) for a test run first.
gcloud builds submit --tag europe-west1-docker.pkg.dev/<project-id>/dataforce/app:$(git rev-parse --short HEAD)
gcloud run deploy dataforce \
  --image europe-west1-docker.pkg.dev/<project-id>/dataforce/app:<tag> \
  --port 8080 --memory 1Gi --cpu 1 --min-instances 0 --max-instances 1 --concurrency 40 \
  --allow-unauthenticated \
  --set-secrets DATAFORCE_SECRET_KEY=dataforce-secret-key:latest,DATABASE_URL=dataforce-database-url:latest \
  --set-env-vars ENVIRONMENT=demo,PUBLIC_ORIGIN=https://<service-url>,ALLOWED_HOSTS=<service-host>,TRUST_PROXY=1
```
- **Why `--allow-unauthenticated`:** DataForce has its own login. Cloud Run's IAM login would block
  browsers.
- **`--max-instances 1`:** keeps the in-memory limits correct (§2, row 9).
- **First deploy:** it prints the service URL. Redeploy once with that URL in `PUBLIC_ORIGIN` and
  `ALLOWED_HOSTS`, or map your own domain.
- **Secrets only through `--set-secrets`:** never put `DATABASE_URL` or the secret key in
  `--set-env-vars` (they would show in the service description and its revisions).
- **`ALLOWED_HOSTS`:** Cloud Run serves two addresses, `<service>-<hash>-ew.a.run.app` and
  `<service>-<project-number>.europe-west1.run.app`. Requests to a host not in `PUBLIC_ORIGIN` or
  `ALLOWED_HOSTS` get 400, so list the second one too if you use it.
- **Rate limits behind the proxy:** after the first deploy, sign in once with a wrong password and
  check in Logs Explorer that the logged client address is your own IP, not Google's. If not, adjust
  `TRUST_PROXY_HOPS`.
- **Database TLS:** `sslmode=require` encrypts but does not check Supabase's certificate. Next step:
  `sslmode=verify-full&sslrootcert=/app/supabase-ca.crt` with Supabase's CA file copied into the image.
- **Health check:** `GET /api/health` (no data, no login); it also queries the database and answers 503 when
  that fails.
- **Known limits:**
  - Cloud Run's default billing gives the container CPU **only while a request is being served**.
    Background work (the test-workspace fill thread, a flow run that outlives its request) can stall
    between requests; the onboarding page polls every 700 ms, which keeps it going while it is open.
    The fix is `--no-cpu-throttling` (instance-based billing); not used by default.
  - One instance only: rate limits and the fill registry are per process.

### 3.5 Migrations and scripts as Cloud Run jobs
The image carries Alembic, so a migration runs from the **same image** as the service, without your computer:
```bash
gcloud run jobs create dataforce-migrate --image <same image> \
  --set-secrets DATABASE_URL=dataforce-database-url:latest,DATAFORCE_SECRET_KEY=dataforce-secret-key:latest \
  --set-env-vars ENVIRONMENT=demo \
  --command alembic --args upgrade,head
gcloud run jobs execute dataforce-migrate --wait
```
Run migrations **before** deploying a new version (update the job to the new image, execute it, then deploy the service), never at container start: `dataforce serve` does not migrate. Other one-off commands (a backfill) are the same job with a different `--command`.

### 3.6 Sign-in callbacks and Netlify
- **TamTam:** nothing to register; the callback becomes `https://<origin>/api/connectors/tamtam/callback`.
- **Gmail:** in Google Cloud → *APIs & Services → Credentials*, create a client of type
  **Web application** (not Desktop) with the authorised redirect URI
  `https://<origin>/api/mailbox/callback`. Keep Testing mode with yourself and your reps as test users.
- **Outlook:** in Entra, add the platform **Web** with the redirect URI
  `https://<origin>/api/mailbox/callback`.
- **Netlify:** either delete the site, or point it at Cloud Run: in `netlify.toml`, change the `/api/*`
  redirect to `https://<cloud-run-url>/api/:splat` with `status = 200`, and set `PUBLIC_ORIGIN` to the
  Netlify origin. **One origin only**, never both.

## 4. Keeping it alive and safe on free plans

| Topic | What to do |
|---|---|
| Supabase pauses after about a week without activity | Normal use keeps it awake. For quiet weeks, a free **Cloud Scheduler** job (3 free jobs per account) calls `GET /api/health` daily. This works once §2 row 6b makes that route query the database; today it does not. Otherwise resume from the dashboard |
| Cold starts (`min-instances 0`) | The first visit after a quiet spell waits a few seconds; acceptable for a demo |
| No downloadable backups on Supabase free | Weekly `pg_dump` from your computer (`pg_dump "<session pooler URL>" -Fc -f dataforce-$(date +%F).dump`), plus one before every migration |
| 500 MB database | The Admin page shows usage against `DB_QUOTA_MB` (set it to 500). Uploads are stored in the database: keep `UPLOAD_MAX_BYTES` small |
| Real customer data | Start with synthetic data only. Before real data: a paid Supabase plan (backups), data-processing agreements with Google and Supabase, and EU regions only |

## 5. Order and effort

| Step | Effort |
|---|---|
| §3.1 Supabase, app still local | **done 2026-10-20** |
| §2 hosted mode, rows 2–6 | 2–3 days, then a security review (cookies, proxy headers, host checks, OAuth callbacks) |
| §3.2–3.4 Google Cloud and the first deploy | half a day |
| §3.6 callbacks, Netlify, Scheduler, backups | half a day |

## 6. Sources (checked 2026-10-20)

- Cloud Run pricing and free tier (tier-1 regions, request-based billing): 2 million requests,
  180,000 vCPU-seconds and 360,000 GiB-seconds per month, per billing account —
  https://cloud.google.com/run/pricing
- Supabase free plan: 2 projects, 500 MB database, pause after about a week of inactivity —
  https://automationatlas.io/answers/supabase-free-tier-limits-2026/ ,
  https://www.jetadmin.io/blog/supabase-pricing-2026-guide-to-plans-limits-and-real-world-costs/
- Earlier version of this plan (Render-based): git history of this file (commit 88dd783).
