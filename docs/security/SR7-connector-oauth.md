# SR7: TamTam OAuth connector, secrets and paid enrichment

Scope: `backend/app/connectors/*`, `api/routes/{connectors,enrichment}.py`, `services/channels.py`,
`cli/secrets.py`, the token path in `enrichment/tamtam_mcp.py`, config, models, migration 0004, tests.
Method: code review plus probe tests (respx and the test client, test DB; no external host contacted,
`backend/.env` not read). Probe file: scratchpad `sr7_probe.py`. Existing suite: 189 tests pass.
No application code was changed.

## Findings

| ID | Sev | Location | Issue | Repro | Suggested fix |
|----|-----|----------|-------|-------|---------------|
| SR7-01 | low | `connectors/tamtam.py:299-370` (`access_token`), `store.py:48` (`update_tokens`) | Refresh vs reconnect race. The per-workspace lock covers only `access_token`; `finish_callback` and `disconnect` do not take it. A refresh in flight when the user reconnects writes the OLD session's tokens over the new credential (and revives a credential after disconnect only if the row still exists). Window is up to the 10 s token call. | Probe `test_refresh_vs_reconnect`: token endpoint overwrites the credential mid-refresh; final stored access token is the stale one. | Take the same lock in callback save/disconnect, or make `update_tokens` conditional on `connected_at` / a version column read at snapshot time. |
| SR7-02 | low | `api/routes/enrichment.py:74-94`, `tamtam_mcp.py:351-358` | No idempotency or in-flight guard on paid lookups. Double-click or repeat on a contact that already has the channel spends again. The charge also comes from a fixed assumed price table; a server reporting 500 credits is only flagged `anomalous` after the spend (max_credits and the ceiling are checked against the estimate, not the real bill). | Probe `test_double`: two POSTs with `max_credits=1`, tool returns `credits_used=500`; both reach the tool (calls == 2), both 200 with `anomalous` true. | Per-contact in-flight lock; refuse or warn when the requested kind already exists unless an explicit `refresh` flag; keep the UI disabled while pending. Cumulative spend cap per workspace/day as defence in depth. |
| SR7-03 | low | `api/routes/connectors.py:36-44`, `oauth.py:219` | The cookie is host-only and the redirect URI is hard-coded to `127.0.0.1`. If the UI is opened as `localhost:8800` (an allowed Host and Origin), the cookie is stored for `localhost` but the callback arrives at `127.0.0.1`, so it is never sent and every connect ends `invalid_state` (fail closed, but confusing). Same for the Vite port 5173 dev flow. | Probe `test_localhost_cookie`: connect with Host/Origin `localhost:8800` gets a host-only `df_oauth`, redirect_uri is `127.0.0.1`. Browser consequence inferred from cookie semantics, not run in a browser. | Derive the redirect URI from the request Host (if allow-listed) or tell the user to use 127.0.0.1; show a specific message for `invalid_state`. |
| SR7-04 | low | `store.py:147-157`, `tamtam.py:182-190` | `take_pending` is a select then delete, not atomic (`DELETE ... RETURNING`). Two concurrent callbacks with the same state could both read the row; the second code exchange fails at the AS (code single use), so impact is a wasted request. Not reproduced under real concurrency. | Code inspection. | `DELETE ... RETURNING` in one statement. |
| SR7-05 | info | `cli/secrets.py:53-62` | `secrets init` follows a symlinked `.env` (writes through it and chmods the target to 0600). It is a fixed path under the repo, so only a local attacker who already controls the repo dir could exploit it. An existing empty `DATAFORCE_SECRET_KEY=` line is not replaced: a second line is appended (duplicate; last wins and loads fine). Append is a single small write, no partial-write risk observed. | Probe `test_symlink`, `test_empty_line`. | `O_NOFOLLOW`, refuse symlinks; replace an empty key line. |
| SR7-06 | info | `oauth.py:65-102` | Response cap counts decoded bytes per chunk; a gzip response is decompressed per network chunk before the 64 KB check, so one chunk can briefly inflate beyond 64 KB (bounded by chunk size and the 10 s timeout). | Code inspection. | Send `Accept-Encoding: identity` on OAuth calls. |
| SR7-07 | info | `tamtam.py:124-131` | A stored `client_id` is reused if the redirect URI matches, without checking it was registered at the current issuer. Only matters if the issuer allow-list is edited to a second server. | Code inspection. | Compare `cred.issuer == meta.issuer` before reuse. |
| SR7-08 | info | `connectors/crypto.py` | Single Fernet key, no MultiFernet/rotation. Key change makes every credential and channel unreadable (handled: `UnsealError`, "[unreadable...]" marker, user can delete or reconnect). | `test_crypto`, `test_channels`. | Optional: support a previous key for rotation. |

No critical, high or medium findings.

## Confirmed protections

- State: `secrets.token_urlsafe(32)`, only its SHA-256 stored (unique), single use (deleted before any check, even on failure), TTL 10 min checked on callback, one pending per workspace, expired rows purged on each start. Length-capped (256) on input.
- Browser binding: separate 256-bit secret in `df_oauth` (HttpOnly, SameSite=Lax, Path=/api/connectors, Max-Age 600), only its hash stored, compared with `hmac.compare_digest`, cleared on every callback answer. Lax cookies are sent on the top-level GET redirect back from TamTam. Missing or wrong cookie gives `invalid_state` (probe `test_wrong_cookie_consumes`). A cross-site attacker cannot read the state, so code injection and login CSRF (storing the attacker's account) fail; the callback also needs a pending row created by the victim's own POST, which requires the allowed Origin plus `X-DataForce` header (security middleware). Secure flag is absent, acceptable for http loopback.
- PKCE: S256 only, 64-byte verifier, metadata must advertise S256, verifier sealed in the pending row, sent only to the token endpoint.
- Mix-up: the issuer must be in the allow-list (default one origin), metadata `issuer` must equal it, endpoints must be https on the issuer's origin (no userinfo, fragment, other host or port), `iss` compared to the pending issuer, required when RFC 9207 is advertised, and discovery is re-run and re-checked at callback and refresh.
- Redirects: the callback always answers 303 to a fixed relative path (`/w/<quoted slug>/settings` or `/`) with a fixed reason code from a closed set; nothing from the query reaches the URL. Outbound requests never follow redirects (3xx is an error).
- SSRF/limits: 10 s overall timeout via `asyncio.timeout`, 64 KB cap (Content-Length and streamed), JSON object required, RecursionError caught, token and `expires_in` validated (finite, bounded), `token_type` must be bearer.
- Resource indicator (RFC 8707) sent on authorize, code exchange and refresh; stored resource must match the configured MCP URL at use.
- Secrets hygiene: error strings are fixed; server text goes through `safe_server_text` with the token masked before reaching `last_error`; unexpected exceptions log only the class name; tests assert no token, code, verifier, key or channel value in responses or logs. Tokens, client secret and verifier are sealed; only hashes of state and cookie are stored.
- Refresh: per-workspace asyncio lock serializes concurrent refreshes in the one process (one refresh, the second reuses the new token); rotated refresh token replaces the old one; `invalid_grant` marks the credential `expired` with a fixed message; failed unseal marks `error`; DB transactions are not held across network calls.
- Bearer token destination: only the configured MCP URL (https enforced; http only loopback in dev/test); the MCP client refuses redirects (SR2); token endpoint/revoke receive tokens only at same-origin endpoints of the allow-listed issuer. Check runs `list_tools` only.
- Workspace isolation: every query filters on workspace id; probe `test_cross_ws` shows workspace B cannot see or delete A's credential (404 or not_connected, A stays connected); channel delete requires matching workspace and contact (tests exist).
- Paid guard: demo workspaces always use the fake provider (zero traffic, even with a connected credential); `confirm_paid` is a StrictBool (`"true"`, `1` refused); `max_credits` required, bounded 0-1000, no NaN/inf; server estimate above `max_credits` or above the per-call ceiling is refused before any traffic; `want` has min length 1; unknown tools priced at the ceiling in the provider.
- Channels: sealed at rest, deduplicated, hard delete, `ON DELETE CASCADE` from contact and workspace, values not logged, undecryptable rows stay deletable. Tables have RLS on and no Data API privileges.
- `secrets init`: key from `Fernet.generate_key()`, created with 0600 and re-chmodded, never printed, refuses to overwrite an existing key (env or file), `--if-missing` is idempotent, newline handled before append.

## Residual risks

- Credit price is an assumption (`pricing.assumed`): the real cost is only known after the call. Ceiling and `max_credits` bound the estimate, not the bill (SR7-02).
- No authentication before M3: anything able to send the Origin plus `X-DataForce` headers from the loopback UI can trigger a paid lookup or disconnect; the Host/Origin middleware is the control.
- Cookies are not port-isolated: another local web app on `127.0.0.1` could set or read `df_oauth` (HttpOnly protects against scripts in the page only).
- Each connect without an existing credential registers a new client at the AS (registration spam if clicked repeatedly or after failures).
- Sealing key lives in `backend/.env` next to the DB URL; losing it loses all tokens and channels (by design, recovery is reconnect).
- `last_error` and tool descriptions are server-influenced text (sanitised, capped, token-masked), and the substring "authentication rejected" in a server error can flip the credential to `expired`.

## Not verifiable without a real TamTam account

- Real AS behaviour: whether it advertises RFC 9207 `iss`, supports DCR with `token_endpoint_auth_method=none`, rotates refresh tokens, honours the `resource` parameter, and what `invalid_grant` looks like in practice.
- Actual metadata paths (the code appends `/.well-known/oauth-authorization-server` to the issuer; path-bearing issuers per RFC 8414 would differ) and whether TamTam's issuer origin equals `https://api.tamtam.ai`.
- Real tool names, annotations, per-call credit prices and the reported `credits_used` units.
- Browser behaviour of the cookie across the real cross-site redirect (reasoned from SameSite=Lax semantics, tests use the test client).

## Resolution

| ID | Status | Reason |
|----|--------|--------|
| SR7-01 | Fixed | `store.lock_connector` takes a transaction-level advisory lock on (workspace, provider), as `_lock_org_chart` does. Callback save, disconnect and the refresh write all take it, so they run one after the other across processes. `update_tokens` is conditional on the `connected_at` and access token the refresh started from; if a reconnect, another refresh or a disconnect got there first, the refresh drops its tokens and the stored credential is used (a disconnected one is not revived). The network call itself is still not under a database lock (no transaction is held across it). |
| SR7-02 | Fixed | `channels.lookup_guard` holds a session-level `pg_try_advisory_lock` on (workspace, contact) on its own connection, released in `finally`; a second request gets 409 `conflict`, "a lookup for this contact is already running", with no traffic. A paid lookup for a kind the contact already has is refused with 409 `conflict` and the message to delete the stored value first (no new request field). Demo workspaces (fake provider) are not guarded. Anomalous-cost flagging is unchanged. Not done: the cumulative per-day spend cap (defence in depth, needs a model or setting change). |
| SR7-03 | Fixed | The redirect URI is built from the request Host, accepted only for 127.0.0.1, localhost or [::1] on the UI or Vite port (anything else falls back to 127.0.0.1 on the UI port). A stored client is re-registered when its `redirect_uri` differs. Tested for `localhost:8800`, `127.0.0.1:8800` and `127.0.0.1:5173`. |
| SR7-04 | Fixed | `take_pending` is one `delete().returning()` statement. |
| SR7-05 | Fixed | `secrets init` refuses a symlinked `.env`, replaces an empty `DATAFORCE_SECRET_KEY=` line (also `""`), and writes through a 0600 temp file (`O_EXCL`, `O_NOFOLLOW`) plus `os.replace`. |
| SR7-06 | Fixed | OAuth HTTP calls send `Accept-Encoding: identity`, so the 64 KB cap counts the real bytes. |
| SR7-07 | Fixed | A stored `client_id` is reused only when both the issuer and the redirect URI match. |
| SR7-08 | Accepted | Documentation only, no rotation now. A key change is handled (`UnsealError`, unreadable marker, reconnect). `MultiFernet` with a previous key remains an option when rotation is needed. |
