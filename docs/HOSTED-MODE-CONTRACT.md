# Hosted mode contract (2026-10-20)

Goal: the same code runs **locally** (today's behaviour, unchanged) or **hosted** on Google Cloud Run
behind Google's HTTPS front end, with the database on Supabase. `docs/HOSTING-PLAN.md` §2 rows 2–6b.

**One switch:** the setting `PUBLIC_ORIGIN` (e.g. `https://dataforce-abc123-ew.a.run.app`).
Empty (default) = local mode, exactly as today. Set = hosted mode. Never infer "hosted" from anything
else (not `UI_HOST`, not the `Host` header).

## 1. Settings (`backend/app/config.py`)
- `public_origin: str = ""`. When set it must be a bare `https://host[:port]` origin (validator; no
  path, query, userinfo). An `http://` value is refused, even on loopback.
- `allowed_hosts: list[str] = []`: extra `Host` header values accepted in hosted mode (e.g. a custom
  domain). The host of `public_origin` is always allowed.
- `trust_proxy: bool = False`: read `X-Forwarded-For` / `X-Forwarded-Proto` (Cloud Run's front end is
  the only way into the container). Only honoured in hosted mode.
- Helper `is_hosted(settings) -> bool`. In hosted mode `ui_allowed_origins` is **replaced** by
  `[public_origin]` (an effective-origins helper, not a mutation of the user's value).
- The existing `ui_host` loopback validator stays (local mode only binds loopback).

## 2. Behaviour in hosted mode
| Area | Local (unchanged) | Hosted |
|---|---|---|
| `Host` allow-list (`app/api/security.py`) | loopback names on UI / Vite port | host of `public_origin` + `allowed_hosts` only |
| Origin check for unsafe methods | `ui_allowed_origins` | `public_origin` only |
| Security headers | as today | + `Strict-Transport-Security: max-age=31536000; includeSubDomains` |
| Session cookie (`routes/auth.py set_cookie`) | as today | always `Secure` |
| OAuth browser cookies (`routes/connectors.py`, `routes/mailbox.py`) | as today | `Secure` |
| Empty passwords / demo sign-in chips | allowed for demo-only reps on loopback | **never** (`app/auth/access.py`: `is_loopback` → false when hosted; `/auth/status` returns no `demo_logins`) |
| TamTam callback (`connectors/oauth.py redirect_uri_for`) | loopback logic | `{public_origin}/api/connectors/tamtam/callback` |
| Gmail / Outlook callbacks (`connectors/mailbox/google.py`, `microsoft.py`) | as today | `{public_origin}/api/mailbox/callback` |
| Password reset link in the log (`routes/auth.py forgot`) | `http://{ui_host}:{ui_port}` | `{public_origin}/reset?token=…` |
| Client IP for rate limits (`request.client`) | socket peer | first `X-Forwarded-For` hop **as set by uvicorn's proxy-headers handling** when `trust_proxy` (see §3) |

Audit every other use of `is_loopback`, `ui_host`, `ui_port`, `127.0.0.1` and `request.client` in
`backend/app` and route it through the helpers. Local mode must stay byte-for-byte the same behaviour
(existing tests must pass untouched).

## 3. `dataforce serve` (new CLI command, `backend/app/cli/serve.py`)
- Binds `0.0.0.0` on `$PORT` (default 8080), **one worker**, uvicorn `proxy_headers=False`.
  *Changed after the security review:* uvicorn with `forwarded_allow_ips="*"` takes the **first**
  `X-Forwarded-For` entry, which the client controls (rate limits bypassed). Our
  `ForwardedClientMiddleware` (hosted + `TRUST_PROXY` only) takes the entry `TRUST_PROXY_HOPS`
  (default 1) from the right, the one Cloud Run's front end appends, and sets the scheme to https.
- Refuses to start (clear message, exit code 1) unless: `public_origin` is set and https;
  `dataforce_secret_key` is set; the database URL uses TLS when its host is not loopback (existing
  check); `environment` is `demo` (`dev` and `test` relax the credential and endpoint checks).
- Same access-log query-string filter and `reap_stale_runs_at_startup()` as `dataforce ui`.
- Never runs migrations (they run as a separate job before a deploy).
- `dataforce ui` is unchanged (still loopback, still refuses `ENVIRONMENT=demo`).

## 4. Health
`GET /api/health` also runs `SELECT 1` with a short timeout (2 s). OK → 200 as today, plus
`"database": "ok"`. Failure → **503** `{"ok": false, "database": "unavailable", …}`. No error text,
no host or URL in the body or the log line. Stays public (no login) and cheap.

## 5. Container (`Dockerfile` + `.dockerignore` at the repo root)
- Stage 1 `node:22-slim`: `npm ci` and `npm run build` in `frontend/`.
- Stage 2 `python:3.13-slim`: `pip install --no-cache-dir --require-hashes -r backend/requirements.lock`,
  then the backend package without dependencies (`pip install --no-deps .` in `backend/`); copy
  `frontend/dist` from stage 1 to `/app/frontend/dist` (the default `ui_dist_dir` relative to the
  backend). Non-root user, `WORKDIR /app/backend`, `ENV PORT=8080 PYTHONUNBUFFERED=1`,
  `CMD ["dataforce", "serve"]`. Alembic files included so the same image can run
  `alembic upgrade head` as a Cloud Run job.
- `.dockerignore`: `.git`, `**/node_modules`, `**/.venv`, `**/__pycache__`, `frontend/dist`,
  `backend/.env*` except `.env.example`, `notebooks`, `data`, `backend/eval`, `backend/tests`,
  `docs`, `*.dump`. **No secret may enter the image.**
- `make image` target: `docker build -t dataforce:local .`.

## 6. Known limits to document (HOSTING-PLAN §2 / §4)
- Cloud Run's default billing gives CPU **only during requests**: background work (the test-workspace
  fill thread, flow runs past their request) may stall between requests. The onboarding page polls
  every 700 ms, which keeps it going while the page is open. Option: `--no-cpu-throttling`
  (instance-based billing) — not by default.
- One instance (`--max-instances 1`): in-memory rate limits and the fill registry are per process.

## 7. Tests
- Settings validation (`public_origin` http refused, path refused, empty = local).
- Middleware: hosted Host allow-list, Origin = public_origin only, HSTS present only when hosted.
- Cookies `Secure` in hosted mode (session + both OAuth cookies).
- Empty password refused and no demo chips in hosted mode, even with `UI_HOST=127.0.0.1`.
- Callback URLs (TamTam, Gmail, Outlook) and the reset link use `public_origin`.
- `serve` refusals (each precondition) without binding a port; health 200 / 503 with a stub DB.
- Pip install in the image is editable (`-e .`): settings find `alembic.ini` and `../frontend/dist`
  relative to the source tree.
- Container: `docker build` succeeds; the image runs `dataforce --help` as a non-root user; no
  `.env` inside (`docker run --rm dataforce:local sh -c 'ls -a /app/backend'`).

## 8. Ownership
- **Backend builder:** everything under `backend/` (§1–4, §7 backend tests).
- **Packaging builder:** `Dockerfile`, `.dockerignore`, the `make image` target in `Makefile`,
  `docs/HOSTING-PLAN.md` (§2 table states, §3.4 commands matching §3–5, §6 limits). Must not edit
  `backend/` or `frontend/`.
