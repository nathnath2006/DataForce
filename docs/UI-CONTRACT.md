# M1b contract: local web UI, CRM screens, TamTam connect, 350-deal demo

Decided with the product owner on 2026-10-17:

- The demo dataset has **350 deals** (it was 200).
- The PO tests the minimal CRM **in a web UI**: lists, detail pages, create and edit, append-only notes and comments, and a read-only analysis page.
- TamTam is connected **from the UI over MCP** with its OAuth sign-in (a "Connect TamTam" button). Nobody copies a token by hand.
  - TamTam's public metadata, checked on 2026-10-17:
    - `https://api.tamtam.ai/.well-known/oauth-protected-resource/mcp` names the authorization server `https://api.tamtam.ai`.
    - Its metadata lists `/authorize`, `/token` and `/register`, which supports dynamic client registration (RFC 7591).
    - PKCE `S256` is supported. `token_endpoint_auth_methods_supported: ["none"]` means a public client. Grants are `authorization_code` and `refresh_token`.
- Work is committed to git in logical steps (local only, no push).

Everything in M1 still holds (`docs/ARCHITECTURE.md`, `docs/DECISIONS.md`). In particular:

- Numbers come from code.
- "Not verified" is never shown as a fact.
- Personal data is kept to a strict minimum.
- Paid lookups happen only on an explicit click.
- Secrets are never logged.

## 0. Who owns what

The tech lead owns these files. Do not edit them; ask in your report if you need a change.

- `app/config.py`, `app/db/models.py`, `app/domain/*`
- `alembic/versions/0004_connectors.py`
- `app/api/schemas.py`, `app/api/deps.py`, `app/api/errors.py`, `app/api/main.py`
- `tests/api/conftest.py`
- this file

| Agent | Owns (creates or edits) |
|---|---|
| **A: API and CRM** | `app/api/security.py`, `app/api/static.py`, `app/api/routes/{workspaces,crm,notes,stats}.py`, new functions in `app/services/{accounts,contacts,deals,users,workspaces}.py`, `app/cli/ui.py` (+ registering it in `app/cli/__init__.py`), `tests/api/test_{security,static,workspaces,crm,notes,stats}.py`, `tests/services/test_crm_updates.py` |
| **B: connector** | `app/connectors/**` (new package), `app/api/routes/{connectors,enrichment}.py`, `app/services/channels.py`, `app/enrichment/tamtam_mcp.py` (token injection only), `app/enrichment/registry.py`, `app/cli/secrets.py` (+ registering it), `tests/connectors/**`, `tests/api/test_{connectors,enrichment}.py` |
| **C: frontend** | `frontend/**` |
| **D: demo 350** | `app/demo/**`, `tests/demo/**`, `notebooks/M1_engine_demo.ipynb`, section E of `docs/DECISIONS.md` |

Shared files that A and B both register into, `app/cli/__init__.py` and the `Makefile`: add only your own lines.

## 1. How it runs

- `dataforce ui [--port 8800] [--no-build-check]` starts uvicorn on `settings.ui_host:ui_port`.
  - The host is always loopback; `Settings` refuses anything else.
  - It runs `create_app()` with one worker.
  - It refuses to start when `ENVIRONMENT=demo`: there is no login before M3.
  - It prints the URL `http://127.0.0.1:8800`.
- `make ui` runs these steps:
  1. `dataforce secrets init --if-missing`, which writes `DATAFORCE_SECRET_KEY` into `backend/.env` with chmod 600 and never prints it;
  2. `npm ci` and `npm run build` in `frontend/` when `frontend/dist` is missing or older than `frontend/src`;
  3. `dataforce ui`.
- `make ui-dev` runs the API on 8800 plus Vite on 127.0.0.1:5173, with a proxy for `/api` to 8800.
- The built SPA in `frontend/dist` is served by FastAPI at `/`.
  - `/api/**` is never shadowed by the SPA.
  - Unknown non-API paths that do not look like files fall back to `index.html`.
  - `/api/...` 404s stay JSON.

## 2. Security (local app, no login)

Agent A implements this in `security.py`. These guards are what stops another website the user visits from driving the API.

1. **Host allow-list**: the Host header must be `127.0.0.1:<port>`, `localhost:<port>` or `[::1]:<port>`, for the UI port or the Vite port 5173. Anything else gets 400. This blocks DNS rebinding.
2. **State-changing methods** (POST, PUT, PATCH, DELETE) need both:
   - an `Origin` header that is in `settings.ui_allowed_origins`;
   - the header `X-DataForce: 1`.

   Otherwise the response is 403 `forbidden`. No CORS middleware is installed, so cross-origin preflights fail.
3. **Content type**: request bodies must be `application/json`, otherwise 415. Bodies are capped at 256 KB, otherwise 413.
4. **Response headers** on everything:
   - `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`
   - `X-Content-Type-Options: nosniff`
   - `Referrer-Policy: no-referrer`
   - `X-Frame-Options: DENY`
   - `Cache-Control: no-store` on `/api/**`
5. **Isolation**: every route resolves the workspace by slug and passes its id to the services. A row id from another workspace must answer 404, never the row.
6. **No secret ever reaches the browser or the logs**: tokens, client secrets, the PKCE verifier and the Fernet key. Logs carry no note bodies or contact values either.
7. **The OAuth callback** is a GET with no Origin. It is protected by:
   - a single-use, hashed `state` with a 10-minute TTL;
   - the `df_oauth` cookie: HttpOnly, SameSite=Lax, Path=`/api/connectors`, a random value whose hash is stored with the pending row;
   - PKCE;
   - the `iss` check (RFC 9207, when the server sends `iss`).

   After the callback the browser is redirected with a 303 to a fixed relative path. Nothing from the query string is ever reflected.

## 3. API

Every route is under `/api` and answers JSON. The schemas are in `app/api/schemas.py`. Routes take `db: Db` and `ws: CurrentWorkspace` from `app/api/deps.py`. A route that writes calls `db.commit()` before it returns. Exceptions map to HTTP codes through `errors.py`: raise service errors, do not build error bodies by hand.

### Agent A

| Method and path | Body → response | Notes |
|---|---|---|
| GET `/workspaces` | → `list[WorkspaceOut]` | demo workspaces included; ordered with real workspaces first, then by slug |
| POST `/workspaces` | `WorkspaceCreate` → `WorkspaceOut` (201) | always `is_demo=false`; 409 if the slug exists |
| GET `/w/{ws}/users` | → `list[UserOut]` | |
| POST `/w/{ws}/users` | `UserCreate` → `UserOut` (201) | |
| GET `/w/{ws}/accounts?q=&segment=&limit=&offset=` | → `Page[AccountOut]` | `q` is a case-insensitive substring of name or domain (a bound parameter; escape `%` and `_`); limit defaults to 200, maximum 1000 |
| POST `/w/{ws}/accounts` | `AccountCreate` → `AccountOut` (201) | source=manual |
| GET `/w/{ws}/accounts/{id}` | → `AccountOut` | |
| PATCH `/w/{ws}/accounts/{id}` | `AccountUpdate` → `AccountOut` | partial (`model_fields_set`); a null `name` → 422 |
| DELETE `/w/{ws}/accounts/{id}` | → 204 | GDPR erasure (`erase_account`); the UI asks for typed confirmation |
| GET `/w/{ws}/accounts/{id}/org-chart` | → `OrgChartOut` | |
| GET `/w/{ws}/contacts?account_id=&q=&limit=&offset=` | → `Page[ContactOut]` | |
| POST `/w/{ws}/contacts` | `ContactCreate` → `ContactOut` (201) | |
| GET `/w/{ws}/contacts/{id}` | → `ContactOut` | |
| PATCH `/w/{ws}/contacts/{id}` | `ContactUpdate` → `ContactOut` | |
| PUT `/w/{ws}/contacts/{id}/reports-to` | `ReportsToUpdate` → `ContactOut` | `set_reports_to` (cycle, self and cross-account → 422) |
| DELETE `/w/{ws}/contacts/{id}` | → 204 | the 1-click erase; notes and channels cascade |
| GET `/w/{ws}/deals?account_id=&stage=&lead_source=&owner_id=&q=&limit=&offset=` | → `Page[DealOut]` | newest `created_on` first |
| POST `/w/{ws}/deals` | `DealCreate` → `DealOut` (201) | |
| GET `/w/{ws}/deals/{id}` | → `DealOut` | |
| PATCH `/w/{ws}/deals/{id}` | `DealUpdate` → `DealOut` | dates are checked (`closed_on >= created_on`) |
| PUT `/w/{ws}/deals/{id}/stage` | `StageUpdate` → `DealOut` | `set_stage` |
| DELETE `/w/{ws}/deals/{id}` | → 204 | hard delete (deals are not append-only) |
| GET `/w/{ws}/contacts/{id}/notes` | → `list[NoteOut]` | current versions, newest first |
| POST `/w/{ws}/contacts/{id}/notes` | `NoteCreate` → `NoteOut` (201) | |
| POST `/w/{ws}/notes/{id}/correct` | `NoteCorrect` → `NoteOut` (201) | a new row; the original stays |
| DELETE `/w/{ws}/notes/{id}?by_id=` | → `NoteOut` | soft delete |
| GET `/w/{ws}/notes/{id}/history` | → `list[NoteOut]` | oldest first |
| (same five for comments) | `/accounts/{id}/comments`, `/comments/{id}/correct`, `/comments/{id}`, `/comments/{id}/history` | |
| GET `/w/{ws}/stats/pipeline` | → `PipelineOut` | |
| POST `/w/{ws}/stats/scan` | → `ScanOut` | runs `analytics.run_scan` (records a Run) |
| GET `/w/{ws}/stats/scan/latest` | → `ScanOut` | latest succeeded `stats_scan` run; 404 if none |

**New services**, written by A in the same style (session-first, flush without committing, `scrub_text`, workspace-scoped, no string-built SQL):

- `update_account(s, ws, id, changes: dict)` and `update_contact(...)` (name and title only);
- `update_deal(...)`, which checks the owner belongs to the workspace and checks the dates;
- `delete_deal`;
- the list functions gain optional filters, search, limit and offset, and return `(rows, total)`, in new functions so existing callers keep working.

The counts in `AccountOut`, `ContactOut` and `WorkspaceOut` come from SQL aggregates, not from per-row queries.

### Agent B

| Method and path | Body → response | Notes |
|---|---|---|
| GET `/w/{ws}/connectors/tamtam` | → `ConnectorOut` | never contains a token |
| POST `/w/{ws}/connectors/tamtam/connect` | → `ConnectStart` | discovery, client registration if needed, PKCE, pending row, `df_oauth` cookie; 409 `connector_not_configured` if there is no secret key |
| GET `/connectors/tamtam/callback?code=&state=&iss=&error=` | → 303 | redirects to `/w/{slug}/settings?tamtam=connected`, or `?tamtam=error&reason=<fixed code>`, where the code is one of `denied`, `expired`, `invalid_state`, `exchange_failed` or `server_error` |
| POST `/w/{ws}/connectors/tamtam/check` | → `ConnectorOut` | opens an MCP session, refreshes the token if needed, runs `list_tools` only (never `call_tool`), stores the sanitised snapshot |
| DELETE `/w/{ws}/connectors/tamtam` | → 204 | deletes the credential and pending rows; best-effort RFC 7009 revocation if a `revocation_endpoint` is advertised |
| POST `/w/{ws}/contacts/{id}/enrich` | `EnrichRequest` → `EnrichResponse` | see §5 |
| GET `/w/{ws}/contacts/{id}/channels` | → `list[ChannelOut]` | |
| DELETE `/w/{ws}/contacts/{id}/channels/{channel_id}` | → 204 | the 1-click delete of an email or mobile |

## 4. OAuth client (agent B: `app/connectors/oauth.py`, httpx, no new dependency)

- **Discovery**:
  1. Fetch the protected-resource metadata of `settings.tamtam_mcp_url`: path-inserted RFC 9728 URL first, then the root.
  2. Require `resource` to equal the MCP URL, ignoring a trailing slash.
  3. The authorization server must be in `settings.tamtam_oauth_allowed_issuers`.
  4. Fetch its RFC 8414 metadata and require `issuer` to equal it exactly.
  5. Every endpoint must be https on the issuer's origin.
  6. `S256` must be supported.
- **Registration** (RFC 7591):
  - Send `client_name: "DataForce (local)"`, `redirect_uris: [http://127.0.0.1:<ui_port>/api/connectors/tamtam/callback]`, `grant_types: ["authorization_code","refresh_token"]`, `response_types: ["code"]` and `token_endpoint_auth_method: "none"`.
  - Reuse the `client_id` of the workspace's credential when its redirect URI is the same; otherwise register again.
- **Authorize URL**: `response_type=code`, `client_id`, `redirect_uri`, `state` (32 random bytes), `code_challenge` (S256 of a 64-byte verifier) and `resource` (the MCP URL). Send `scope` only if the metadata lists `scopes_supported`.
- **Code exchange and refresh**:
  - Form POST to the token endpoint with the `resource` parameter.
  - `follow_redirects=False`, timeout 10 s, response capped at 64 KB, JSON only.
  - `token_type` must be bearer (case-insensitive).
  - Store `expires_at`.
  - Refresh when less than 60 s is left. A rotated refresh token replaces the old one.
  - `invalid_grant` → status `expired`.
- **Sealing**: `app/connectors/crypto.py` with Fernet from `settings.dataforce_secret_key`, and `seal` / `unseal` helpers. A missing key raises `EnrichmentConfigError`. A key that cannot decrypt (it was rotated) marks the credential `error` and asks the user to reconnect.
- **MCP use**: `TamTamMCPEnrichment` gains a keyword `token: str | None`. When given, it is used instead of `settings.tamtam_mcp_token`, and every existing guard is kept. `app/connectors/tamtam.py` builds it from the stored credential, refreshing first if needed.
- `tests/connectors` use **respx** or a local stub for discovery, registration, token and refresh, including every refusal: a wrong issuer, an off-origin endpoint, http, no S256, a bad `token_type`, an oversized response, a reused or expired state, a missing or wrong cookie, a mismatched `iss`, and an `error=access_denied` callback. Nothing in the tests reaches the network.

## 5. Enrichment (agent B)

- **Demo workspace** (`is_demo`): always the fake provider, whose results are labelled "fake". There is no TamTam traffic and no credits. The people are fictional, and spending real credits on them is refused by design.
- **Other workspaces**:
  - TamTam must be connected, otherwise 409 `connector_not_configured`.
  - `cost = estimate(want)`. When `cost > 0`, the request needs `confirm_paid is True` and `cost <= max_credits`, otherwise 409 `paid_lookup_refused`, before any traffic.
  - The existing per-call ceiling and tool-cost guards still apply.
- **Storage**: each value found is stored in `contact_channel`, sealed, with provider, credits and `raw_tool`. The response returns them unsealed. Values never go into logs or error messages.

## 6. Frontend (agent C)

**Stack**:

- Vite, React and TypeScript (strict), with react-router.
- No UI kit and no CSS framework: plain CSS with variables, light and dark.
- Exact pinned versions, a committed `package-lock.json`, and `.npmrc` with `save-exact=true` and `ignore-scripts=true`. `npm ci` must work with scripts ignored.
- Tests: Vitest for pure logic (org-chart tree, formatting, API error parsing).
- `npm run build`, `npm run typecheck` and `npm test` must pass.

**API client**: `src/api.ts`.

- Typed functions that mirror `app/api/schemas.py`.
- Every mutation sends `X-DataForce: 1` and `Content-Type: application/json`. The browser adds `Origin`.
- Errors are parsed from `{"error": {"code", "message"}}`.

**Rules**:

- No `dangerouslySetInnerHTML`, no `eval`, and no inline scripts (the CSP forbids them).
- Server text (tool descriptions, notes) is rendered as text only.
- `authorize_url` is followed only when it is `https:` and its origin is the issuer shown in `ConnectorOut`.
- External links get `rel="noreferrer noopener"`.

**Screens**: routes `/w/:ws/...`; `/` redirects to the first workspace.

- **Shell**:
  - a workspace switcher, with demo workspaces marked "synthetic" and a "New workspace" dialog;
  - an "acting as" user picker, stored in localStorage and sent as `author_id` or `by_id`, with a note that login arrives in M3;
  - navigation: Accounts, Contacts, Deals, Analysis, Settings.
  - On demo workspaces a permanent banner reads: "Synthetic demo data — generated, no real company or person."
- **Accounts**:
  - the list has search and a segment filter, and columns for name, industry, segment, region, contacts and open deals;
  - a "New account" form;
  - the detail page has editable fields, contacts, the org chart, deals and comments, plus "Erase account" (the user types its name to confirm; the dialog says what cascades).
- **Org chart**: a nested tree. Contacts with no manager are roots; the chart tolerates cycles defensively.
- **Contacts**:
  - the list has search and an account filter;
  - the detail page shows name, title, account, a reports-to selector (same account only), direct reports and notes;
  - an **Enrich** panel shows the mode (fake or TamTam) and the cost estimate from `pricing`. A paid click opens a confirm dialog that states the credits; it sends `confirm_paid: true` and `max_credits` set to the estimate;
  - stored channels are listed, each with a delete button;
  - "Erase contact" asks for confirmation.
- **Notes and comments**:
  - add;
  - correct, which explains that the original stays in the history;
  - delete, a soft delete shown as "deleted";
  - a history drawer;
  - author name and time.
- **Deals**:
  - the list has filters (stage, lead source, owner), shows amount, created and closed dates, and cycle days;
  - create and edit;
  - a stage change control (closing asks for `closed_on`);
  - delete.
- **Analysis**:
  - the pipeline numbers, labelled "exact count";
  - "Run analysis" calls POST scan; the latest scan loads on open;
  - findings are split into **Verified** (direction, difference with its CI, q-value, n) and **Not verified**, which is collapsed by default, never styled as a result, and lists every reason;
  - the gates used, in one line;
  - the overall metrics with their CI and status.
- **Settings → TamTam**:
  - status;
  - "Connect TamTam", "Check connection" (the tool table: name, description as text, read-only and destructive flags, allowed in DataForce or not), "Disconnect";
  - the assumed pricing;
  - the `?tamtam=` result message;
  - a notice when the secret key is missing (`make ui` creates it).

**Look**: clean and dense, like a modern CRM. A left nav, tables with sticky headers, and readable at 1280 px and at 390 px.

## 7. Demo with 350 deals (agent D)

- **Defaults**:
  - `generate()` and the CLI `--n-deals` default to 350; `settings.demo_n_deals` is already 350.
  - Accounts and contacts scale with the existing ratios.
  - The referral group stays capped at 25 closed deals, so it stays "not verified".
- **Re-check the planted design at 350**:
  - Update the generator's power-check docstring.
  - Keep effects detectable, the small group small, and the null cells null.
  - Run the calibration sweep: 100 seeds for each variant, the same method as section E of `docs/DECISIONS.md`.
  - Report how often the planted effects are detected, how often a false positive appears, how often the check fails, and how often anything is verified on the noise variant.
- **Update**:
  - tests that assumed 200;
  - section E of DECISIONS with the new measured numbers, keeping the old ones as "at 200";
  - the notebook, re-executed in place;
  - the README examples.
- **Load into the dev database for the PO**: `demo generate --variant planted --seed 42 --replace` and the same with `--variant noise`.

## 8. Definition of done (every agent)

- `ruff check` and `ruff format --check` are clean.
- The tests you add pass, and so does the full suite: `pytest -m "not live"` with the database up.
- No new runtime dependency without asking the tech lead in your report.
- Your report lists the files you touched, the decisions you made, what you could not do, and anything in a contract file you need changed.
- Do not commit to git: the tech lead commits.
