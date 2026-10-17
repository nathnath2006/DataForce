# SR8 - Frontend and npm supply chain review

Scope: `frontend/` (Vite 8, React 19.3, TS 7), built `dist/`, `package-lock.json`. Application code was not changed.

## Findings

| ID | Severity | file:line | Issue | Repro | Suggested fix |
|---|---|---|---|---|---|
| SR8-01 | low | frontend/src/pages/Settings.tsx (REASONS[reason ?? ""] ?? ...) | The `reason` query param indexes a plain object. `reason=__proto__` returns Object.prototype, which `??` does not replace, so React throws "Objects are not valid as a React child". There is no error boundary, so the SPA blanks. This is a crafted-link nuisance only (no injection, no data leak). `reason=constructor` returns a function, which React ignores. | Node check: `typeof REASONS["__proto__"] === "object"`. Open `/w/<slug>/settings?tamtam=error&reason=__proto__` (not browser-run; derived from the code and the Node check). | Use `Object.hasOwn(REASONS, reason)` or a `Map`. Add a top-level error boundary. |
| SR8-02 | low | frontend/src/lib.ts:31-40 | `isSafeAuthorizeUrl` compares origin only. It accepts `https://user:pw@<issuer>/x` and any path or query. This is harmless for navigation, but it also lets credentials in the URL through. | Node test: returns true for `https://user:pw@auth.tamtam.ai/x`. | Also require `!u.username && !u.password`. Optionally require the path to match the discovered authorization endpoint. |
| SR8-03 | info | frontend/src/pages/Settings.tsx:29 | The issuer used for the check comes from the same backend that supplies `authorize_url`. This is acceptable because the backend is the trust root. A tampered or compromised backend defeats the check. | n/a | Have the backend pin the issuer. Already displayed to the user. |
| SR8-04 | info | frontend/src/pages/ContactDetail.tsx:~85-90 | A paid enrich sends `max_credits = estimate` taken from the displayed state, and `confirm_paid = paid`. If pricing changes between display and confirm, the backend ceiling is the only guard. | Code reading. | Keep the server-side `max_credits` enforcement (backend review). |

No finding at medium or above. Each of the low findings was checked with a Node repro or code reading. No browser was driven.

## Confirmed protections

- **XSS sinks**: no `dangerouslySetInnerHTML`, `innerHTML`, `eval`, `new Function`, `window.open`, or `href=` / `<a>` built from data. The account `domain` renders as text only. The only navigation is `window.location.assign(authorize_url)`, after the check.
- **authorize_url check**: tested with a Node replica of the check.
  - Rejected: `https://auth.tamtam.ai@evil.com/x`, the backslash trick, `//evil.com`, `javascript:`, a lookalike subdomain suffix, a percent-encoded dot, and a null, missing or empty issuer (all false).
  - Mixed case is normalised by `URL` and accepted only when it is the same origin.
  - Both URLs must be https.
- **Untrusted text** (errors, notes, comments, names, tool descriptions, `last_error`, and the `?tamtam=` / `reason=` params) is rendered through React text nodes. `?tamtam=` is compared to fixed strings, and `reason` goes through a whitelist (apart from SR8-01).
- **CSP vs dist**: `dist/index.html` has no inline script, no inline style and no `style` attributes. It has one external module script and one stylesheet. There is no source map and no `sourceMappingURL`. The single-chunk build has no inline modulepreload polyfill. The live server sends the CSP plus nosniff, no-referrer and X-Frame-Options DENY.
- **Mutations**: all non-GET requests go through `request()` in `api.ts`, which sets `X-DataForce: 1`, `credentials: same-origin` and a JSON body. Origin is browser-supplied.
- **Confirm dialogs**: a paid enrich opens the Confirm dialog (button disabled while busy). Destructive deletes use `Confirm`. Enter in a modal focuses only the Close or Confirm buttons, and there is no form-submit path. `confirm_paid` is true only when the estimate is above 0, and the free path skips the dialog by design.
- **localStorage**: only the "acting as" user id, per workspace slug. It is validated against the loaded user list (`actingValid`), so a tampered value is ignored. Storage access is wrapped in try/catch.
- **Secrets**: the dist bundle holds no key-like strings (grep for sk_/pk_/Bearer found nothing).
- **Vite dev server**: bound to 127.0.0.1, `strictPort`, proxy `/api` to loopback with `changeOrigin: false`, `server.fs` left at the strict default, `build.sourcemap: false`.

## Dependencies

- Exact pins (`save-exact=true`) and `ignore-scripts=true` in `.npmrc`.
- 7 direct packages and 93 total in the lockfile. All 93 have `resolved` and `integrity` fields, and all resolved URLs use registry.npmjs.org.
- `npm audit`: 0 vulnerabilities.
- The only install script is the optional darwin-only `fsevents@2.3.3` (`hasInstallScript`), and it is neutralised by ignore-scripts.
- Version ages (as of 2026-10-17), from `npm view time`:

| Package | Published | Age |
|---|---|---|
| react 19.3.0 | 2026-09-09 | 38 days |
| react-dom 19.3.0 | 2026-09-09 | 38 days |
| react-router 8.4.0 | 2026-09-15 | 32 days |
| vite 8.3.2 | 2026-10-01 | 16 days |
| vitest 5.0.3 | 2026-09-30 | 17 days |
| typescript 7.0.2 | 2026-07-08 | 101 days |
| @vitejs/plugin-react 6.1.1 | 2026-08-28 | 50 days |

I did not check the age of @types/*. Every package checked is real and at least 2 weeks old.

## Residual risks

- SR8-01 and SR8-02 as above.
- Transitive dependencies are not individually age-checked (93 packages).
- I did not run `npm ci`, the tests or a browser run. The dist and the Node replica were checked statically.
- Server-side enforcement (Origin check, credit ceiling, `author_id` validation) belongs to the backend reviews.
