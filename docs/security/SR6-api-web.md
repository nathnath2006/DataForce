# SR6 - Local API and web surface (security review)

Scope: `backend/app/api/**`, `app/services/{accounts,contacts,deals,users,workspaces,_common}.py` (plus `_appendonly`, `notes`, `comments` as called), `app/cli/ui.py`, Makefile `ui` / `ui-dev`, `tests/api/`. Spec: `docs/UI-CONTRACT.md` sections 1-3.
Method: code reading, GET-only / refused-request probes against the live server (127.0.0.1:8800, dev DB untouched), and write probes through the test client and test DB (scratchpad `test_sr6_probe.py`, `test_sr6_b.py`). No external host was contacted; `backend/.env` was not read. No application code was changed.

Result: **0 critical, 0 high, 0 medium, 5 low, 5 info.** No CSRF, DNS-rebinding, cross-workspace or traversal bypass was found.

## Findings

| ID | Sev | Location | Issue | Repro | Suggested fix |
|---|---|---|---|---|---|
| SR6-01 | low | `api/routes/crm.py:34-35` (`Offset`), `api/schemas.py` (`AccountCreate.employee_count`), `services/_common.py:21` (`like_contains`) | Unbounded numeric / NUL inputs reach Postgres and fail as a generic 500 `database error` (no leak, nothing committed, but it is an unhandled-input path and a trivial way to spam 500s / error logs). Three triggers: `offset` larger than int8, `employee_count` larger than int4, `q` containing a NUL byte. NUL is stripped on writes (`scrub_text`) but not in `q`. | Live, GET only: `curl "http://127.0.0.1:8800/api/w/demo-planted-42/contacts?q=%00"` and `...contacts?limit=1000&offset=99999999999999999999` both return 500 `{"error":{"code":"internal","message":"database error"}}`. Test client: POST accounts `{"name":"E","employee_count":1000000000000}` returns 500. | `Offset = Query(ge=0, le=1_000_000)`; `employee_count` `le=2_147_483_647`; strip `\x00` from `q` (or `Query(pattern=...)`); same for any other int / date column that has no bound. |
| SR6-02 | low | `api/main.py:34` + `api/errors.py:84` + `api/security.py` | A truly unhandled exception is answered by Starlette's `ServerErrorMiddleware`, which sits OUTSIDE `SecurityMiddleware`: the 500 carries no CSP / X-Frame-Options / nosniff / no-store. `ServerErrorMiddleware` also re-raises after the handler, so uvicorn logs a full traceback including the exception message (can quote a contact name or note text, defeating the "no message" intent of the `log.error("unhandled %s")` line). The traceback part is from Starlette's documented behaviour; not run under real uvicorn. | Test client with a route raising `ValueError("secret contact Jane Doe")`: status 500, `x-frame-options` header absent (other responses have it). | Make the catch-all a middleware inside `SecurityMiddleware` (try/except around `self.app`, send the JSON 500 through `send_with_headers`) and log only the type; or add a `logging.Filter` on `uvicorn.error` that drops `exc_info`. |
| SR6-03 | low | `api/security.py:100-114` (`_refusal`) | Duplicate headers: the guard builds a dict, so the LAST `Host` / `Origin` wins, while Starlette (`request.headers.get`, redirects) uses the first. Parser differential. A browser cannot send duplicate Host/Origin, so it is not exploitable by the stated threat model; a non-browser local process can already call the API directly. | Test client: Host `evil.com` then `127.0.0.1:8800` returns 200; Origin `https://evil.com` then the UI origin on POST returns 201. | Reject requests with more than one Host or Origin header (count them in `scope["headers"]`), or take the first. |
| SR6-04 | low | `api/main.py:21-23` | `/api/docs` is enabled and Swagger UI pulls `swagger-ui-bundle.js` / css from `cdn.jsdelivr.net` (unpinned `@5`) and a favicon from fastapi.tiangolo.com. The page is broken today because the CSP (`script-src 'self'`) blocks it, but it is dead code that invites loosening the CSP (a third-party script on a no-login page that can drive the whole API). `/api/openapi.json` is served without auth (schema only, no data). | `curl -s http://127.0.0.1:8800/api/docs` lists the three https URLs. | Set `docs_url=None` (keep `openapi_url` if wanted) or disable outside a dev flag. |
| SR6-05 | low | `Makefile:72-77` (`ui-dev`) | `trap 'kill 0' INT TERM EXIT` signals the whole process group, not just the two children: it also hits whatever shares the group (a wrapper script, `make ui-dev \| tee`, parent `make`), and the EXIT trap re-fires the kill. `wait` waits for both children, so if the API exits (port busy, bad settings) Vite keeps running on 5173 with a dead proxy and the recipe does not end. My attempt to test this at runtime killed my own tool shell (confirming the group-wide effect), so the leftover-process case is by reading only. | Run `make ui-dev` with port 8800 taken: API exits, Vite stays up. | Track PIDs: `api=$!`, `vite=$!`, `trap 'kill $api $vite 2>/dev/null' INT TERM EXIT`, and `wait -n` (or `wait $api`) so either exit tears down the other. |
| SR6-06 | info | `api/security.py:98-107` | Origin match lowercases the header, so `HTTP://127.0.0.1:8800` is accepted. Harmless (browsers normalise origins; same origin). Rejected correctly: `null`, trailing slash, trailing space, trailing dot, `127.0.0.1.evil.com`, empty. | Test client POST for each value: only the upper-case scheme returned 201. | None needed. |
| SR6-07 | info | `api/routes/connectors.py:48` | The only state-changing GET: `/api/connectors/tamtam/callback` consumes the pending OAuth flow (`db.commit()` in `take`) before the cookie check, then stores a token. It is guarded by an unguessable single-use `state`, the `df_oauth` cookie hash, PKCE and `iss`; a cross-site GET without a valid state spends nothing. It is the documented exception (UI-CONTRACT) and is covered by SR2/SR5 scope. All other GET routes are read-only (checked every `@router.get`). | Read the route list. | None; keep the cookie `SameSite=Lax` / `Secure` review in the connector review. |
| SR6-08 | info | `routes/notes.py:36,81`, `routes/workspaces.py:34`, `routes/crm.py` (org chart) | Notes, comments, users and org-chart lists are unpaginated (bounded only by data volume, a note body is capped at 20 000 chars). No remote DoS since the app is loopback and each request is cheap at personal scale. | n/a | Add `limit` if a contact can realistically hold thousands of notes. |
| SR6-09 | info | `routes/workspaces.py:27-30` | `POST /api/workspaces` has no quota; any caller that passes the guards can create unlimited workspaces. Needs Origin + `X-DataForce`, so not reachable by a website. | n/a | Optional cap. |
| SR6-10 | info | `api/errors.py:47` | `NotFoundError` / `AlreadyExistsError` messages echo the submitted UUID or slug. These are values the caller just sent, in a JSON body with `nosniff`, so no reflected-XSS or leak. 422 messages never echo input (checked below). | n/a | None. |

## Confirmed protections (each verified by a probe)

**Host allow-list (DNS rebinding)**
- Strict exact match on `127.0.0.1|localhost|[::1]` with port 8800 or 5173, compared lowercase (live).
- `Host: 127.0.0.1:8800.` (trailing dot) returns 400.
- `Host: 127.0.0.1:8800, evil.com` returns 400.
- Empty Host: uvicorn answers 400 before the app.
- HTTP/1.0 without a Host header returns 200: curl injected one; the guard would answer 400 on an empty value.
- Absolute-URI request line (`GET http://evil.com/api/health`): uvicorn uses the URI path, so it is a 404, not a bypass.
- `LOCALHOST:8800` is accepted. That is correct, since hostnames are case-insensitive.
- Existing test also refuses `127.0.0.1` without a port and `127.0.0.1.evil.io:8800`.

**CSRF (Origin + X-DataForce)**
- POST/PUT/PATCH/DELETE need an exact allowed Origin and `X-DataForce: 1`.
- Refused with 403: `Origin: null`, trailing slash, trailing dot, suffix-domain, empty, missing Origin.
- Refused with 403: missing or `0` header (existing tests also cover all four methods).
- No CORS middleware: a preflight `OPTIONS` from `https://evil.com` returns 405 with no `access-control-*` headers (live). The custom header therefore cannot be sent cross-site.
- No state-changing GET except the guarded OAuth callback (SR6-07).
- TRACE returns 405.

**Content type and body size**
- A body requires media type exactly `application/json`, with parameters stripped. Accepted: `application/json;charset=utf-8` and upper case. Rejected with 415: `text/plain`, `application/x-www-form-urlencoded`, `application/jsonx`, `application/json, text/plain`, `application/vnd.api+json`, `text/plain;application/json`, and a missing content type.
- A `text/plain` JSON body is refused after the Origin check (live and test client).
- Oversize bodies are refused with 413 by Content-Length and by counting streamed bytes, so chunked bodies without a length are caught: a valid JSON object followed by 300 KB of padding in chunks returns 413 with security headers and creates nothing.
- When the limit trips, `limited_receive` returns `http.disconnect`, FastAPI fails body parsing, and the route never runs. The app's own response is discarded in favour of the 413.
- A route that never reads its body (DELETE with an oversize chunked body) just executes. That is correct: nothing was consumed.
- A non-numeric Content-Length returns 400.

**Security headers**
- CSP, nosniff, no-referrer and X-Frame-Options are on 200, 404, 422, 400 (bad Host), 403, 415, 413, 500 from handled errors, SPA index, static assets and the 404 JSON (live and tests).
- `Cache-Control: no-store` is on all `/api/**` responses.
- Only the unhandled-exception 500 lacks them (SR6-02).

**Static and SPA**
- Live `//etc/passwd`, `/../../etc/passwd` and `/%2e%2e/%2e%2e/etc/passwd` return the 446-byte `index.html`: the path is resolved and `relative_to(dist)` fails, so it falls back to the SPA.
- `/assets/..%2f..%2f..%2fbackend/.env` and `/%2e%2e%2fbackend/.env` return 404.
- Symlinks are resolved before the containment check, so a link inside `dist` pointing outside is refused. This is by code: `Path.resolve()` then `relative_to`. `dist` has no symlinks today.
- Absolute path components (`dist / "/etc/passwd"`) resolve outside and are refused. NUL is refused.
- `/api/**` is never shadowed: unknown API paths return a JSON 404.
- A missing file with an extension returns 404, not the index.

**Cross-workspace access (IDOR), test client with two workspaces**
- Every id route returns 404 from another workspace: accounts, contacts, deals, notes and comments by id (history, correct, delete), org chart.
- `reports-to` with a manager from another workspace returns 404.
- Note `author_id` and delete `by_id` from another workspace return 404.
- Deal `owner_id` from another workspace returns 404 on create and update; `account_id` from another workspace returns 404 on a contact or deal create.
- A note on another workspace's contact returns 404.
- The `owner_id` list filter with a foreign id returns an empty page. Counts and names come from queries that filter on `workspace_id`.
- `get_workspace` validates the slug pattern; a NUL slug gives 422.
- The existing `test_crm.py` and `test_notes.py` already assert these.

**Injection and `like`**
- All SQL uses the ORM and bound parameters.
- `like_contains` escapes `% _ \` with `escape="\\"`. `q=0%_r` matches only the literal `100%_real\x`, not `0xr`.
- `q` is capped at 200 characters (422 above). `limit` is 1..1000 (0 and 1001 give 422). The default is 200.
- NUL in written text is scrubbed (`nul\0x` becomes `nulx`).

**Errors and logs**
- 422 bodies contain the field path and pydantic's message only. Probes with `SECRETVALUE` as an extra-field name, an int value, or a UUID value show no echo of the value; the field name does appear for extra keys (`bogus: Extra inputs...`).
- DB errors become `database error` or `conflict`, with only the exception type logged.
- The uvicorn access-log filter (`app/cli/ui.py`) cuts the query string from `args[2]` (path), so `q`, OAuth `code` and `state` are not logged. The access log then holds only method, path (slug and UUIDs) and status.
- `ui.py` logs the URL and nothing else.

**Binding and transactions**
- `ui_host` is validated as loopback (including via `.env`), the `dataforce ui` banner prints 127.0.0.1, `workers=1`, and `ENVIRONMENT=demo` is refused.
- The live process listens on 127.0.0.1:8800 as spawned by `dataforce ui`.
- `--port` extends the Origin list only with loopback origins.
- `get_db` always rolls back and closes. Routes call `commit()` after the service succeeds and before building the response, so an exception never commits (services only `flush`). Erasure uses `SET LOCAL`-style `set_config(..., true)` and is turned off in `finally`.
- The only other commits are the connector and enrichment routes, outside this scope, and the OAuth `take` that deliberately spends the flow.

## Residual risks

- There is no authentication before M3. Any local process (or another local user, since loopback is shared on a multi-user machine) can set Host, Origin and `X-DataForce` itself and read or delete all CRM data. The guards stop websites, not local software. Document this, and keep `ui_host` loopback-only.
- `GET /api/workspaces` and the list routes return top-level JSON arrays. This is not readable cross-origin (no CORS, Host check), so old JSON-hijacking does not apply to current browsers.
- DNS-rebinding protection depends on the Host check alone: if someone adds a hostname to the allow-list or binds a non-loopback address, every API route is exposed. `ui_host` validation covers the second case.
- Vite dev mode (`make ui-dev`) widens the surface to the dev server (source and `/@fs` serving); it is bound to 127.0.0.1 and covered by the same Host check only for proxied `/api` calls, not for Vite's own routes (the Vite version's `allowedHosts` was not reviewed here).
- Contact names and notes appear in the PII-bearing JSON responses with `no-store`, but are held in browser memory and the dev database. Log hygiene beyond the access-log filter (uvicorn tracebacks, SR6-02) is only partially controlled.
- The OAuth callback (SR6-07) is a cross-site-reachable GET by design.

## Resolution

| ID | Status | Reason |
|---|---|---|
| SR6-01 | fixed | `offset` is `le=1_000_000`; `q` (accounts, contacts, deals lists) is capped at 200 characters and refuses control characters (NUL included) with 422; `employee_count` is bounded (`le=10_000_000`). Other query / path parameters are UUIDs, enums or slugs; body dates are Python `date` (years 1-9999, valid for Postgres) and amounts are bounded decimals, so no further unbounded input reaches SQL. Tests in `tests/api/test_crm.py`. |
| SR6-02 | fixed | `SecurityMiddleware` now wraps the inner app: an unhandled exception is logged by type only and answered with a JSON 500 `internal error` through the header-adding send. The exception no longer propagates, so `ServerErrorMiddleware` and uvicorn log no message or traceback. If the response had already started, the connection just ends. `api/errors.py` is unchanged (its catch-all stays as a second line of defence). |
| SR6-03 | fixed | More than one `Host` header gives 400; more than one `Origin` or `X-DataForce` header gives 403. |
| SR6-04 | fixed | `docs_url=None` (done by the tech lead). |
| SR6-05 | fixed | `make ui-dev` calls `scripts/ui-dev.sh`: it records both child PIDs, kills only those on INT, TERM or exit, and stops both when either exits (polling with `kill -0`, as POSIX sh has no `wait -n`). No `kill 0`. Checked with `sh -n` only. |
| SR6-06 | info, no change | Harmless: browsers normalise origins. |
| SR6-07 | info, no change | Documented exception, guarded by state, cookie and PKCE. |
| SR6-08 | info, no change | Bounded by personal-scale data on loopback. |
| SR6-09 | info, no change | Needs Origin + `X-DataForce`; not reachable from a website. |
| SR6-10 | info, no change | Echoes only values the caller sent, in JSON with `nosniff`. |
