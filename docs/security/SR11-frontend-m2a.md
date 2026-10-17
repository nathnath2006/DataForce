# SR11: M2a frontend and npm supply chain

Scope: frontend/ (flows, companies, assistant, settings, theme, lazy editor), dist/, package-lock.json. No application code changed.

## Findings

| ID | Severity | File:line | Issue | Repro | Suggested fix |
|----|----------|-----------|-------|-------|---------------|
| SR11-01 | Low | src/flows/FlowEditor.tsx:97-106 | Leave guard covers tab close (beforeunload) and clicks on `a[href]` only. Browser Back/Forward (popstate) and programmatic navigation are not guarded, so unsaved flow edits can be lost silently. Data-loss only, not a security break. | Edit a node, press browser Back. | Use a data router with `useBlocker`, or push a history sentinel and handle popstate. |
| SR11-02 | Info | src/main.tsx:21 | Error boundary uses a full-page `<a href="/">`. Static string, no data. | n/a | None. |

No finding at medium or above.

## Confirmed protections

- XSS sinks: grep of src/ finds no `dangerouslySetInnerHTML`, `innerHTML`, `insertAdjacent`, `eval`, `new Function` or `window.open`. The only `<a href>` is the static `/`. The only location assignment is Settings.tsx:27, guarded by `isSafeAuthorizeUrl` (https and TamTam issuer host).
- AI answers: `parseAnswer` (src/assistant/refs.ts) only splits on `/\[([FDCNM]\d{1,4})\]/`. The result is plain data, rendered as React text nodes in `<span class="chip">` (AskPanel.tsx:17, 67). The model cannot inject markup, links or attributes. The chip `title` is the regex-constrained ref. Unknown refs are styled differently.
- Registry results, node labels, column names, pivot headers and chart axis labels are all rendered as React text. The SVG `<text>` and `<title>` elements in Charts.tsx hold only text children (`fmtCell` and labels). React escapes these, with no attribute built from data.
- Handle `style={{top}}` is computed from the index only.
- CSP and dist: `dist/index.html` has no inline script or style. Both bundles contain no `<style` or `createElement("style")`. The `.innerHTML` hits are generic d3-selection methods that xyflow does not call with data. xyflow v12 ships a static stylesheet, emitted as `FlowEditor-*.css` and loaded as a same-origin `<link>` by Vite's lazy-chunk loader, which is allowed by `style-src 'self'`. React and xyflow set `style` via the CSSOM (`el.style.x=`), which CSP does not block. The live server sends the expected CSP and `nosniff`. I did not exercise the editor in a browser, so this rests on source and bundle inspection.
- No source maps: there are no `.map` files and no `sourceMappingURL` in dist. No secrets were found in dist.
- Uploads: flowApi.ts:9-15 sends FormData with the headers `X-DataForce: 1` and `Accept` only. The browser sets the Content-Type boundary. Other mutations go through src/api.ts, which sets `X-DataForce`.
- Secrets: the AI key field (Settings.tsx:162) is `type=password` with `autoComplete=off`. It is never prefilled, the server returns only a `configured` flag, and `setKey("")` runs after a save. The DB password (ConnectionsPanel.tsx:65-88) starts as "", is sent only when typed, uses `autoComplete=new-password`, and is cleared after save. The modal unmounts on done.
- localStorage: only the theme (`light|dark`, validated on read, anything else gives "system") and the acting-as user id per workspace. All access is wrapped in try/catch. No tokens or data are stored.
- Supply chain:
  - `.npmrc` has `ignore-scripts=true` and `save-exact=true`. package.json pins exact versions.
  - Runtime direct dependencies: @xyflow/react 12.12.0, react, react-dom, react-router.
  - @xyflow/react adds about 25 runtime packages. `npm ls --omit=dev` shows 52 tree lines. They are @xyflow/system 0.0.83, zustand 4.5.7, classcat 5.0.5, the d3-* modules (3.0.x, from 2021-2022), use-sync-external-store 1.7.0, and the @types packages.
  - Release dates: @xyflow/react 12.12.0 and @xyflow/system 0.0.83 were published 2026-09-24, 23 days before today. use-sync-external-store 1.7.0 was published 2026-09-09. The rest are far older. All are at least 2 weeks old.
  - The lockfile has 113 `resolved` entries, all from registry.npmjs.org, and 113 integrity hashes.
  - The only `hasInstallScript` entry is fsevents, which is dev-only, optional and darwin-only. It is inert because of ignore-scripts.
  - `npm audit` reports 0 vulnerabilities.

## Residual risks

- xyflow is a new, large third-party surface that runs in the same origin. The CSP (no inline script, `connect-src 'self'`) and loopback-only serving limit the impact. Its 12.12.0 and 0.0.83 releases are only about 3 weeks old, so re-audit when upgrading and keep exact pins.
- The dev-only fsevents install script is skipped only while `.npmrc` is respected. CI must not override it.
- Server-supplied `authorize_url` is trusted only up to the host check. Keep `isSafeAuthorizeUrl` tests in place.
- Browser rendering of the lazy editor was not exercised end to end here.

## Resolution (tech lead, 2026-10-17)

| ID | Status | What changed |
|---|---|---|
| SR11-01 | Fixed | `FlowEditor.tsx`: while there are unsaved changes, a guard history entry is pushed and `popstate` asks for confirmation. Back/Forward then confirms like tab close and in-app links do. |
| SR11-02 | Accepted | The static `<a href="/">` in the error boundary carries no data. |

Also in the same pass:
- The xyflow canvas follows the app theme (`colorMode` from `useThemeChoice`, not only the OS setting).
- Port labels are drawn outside the node.
- Dates without a time ("last interaction", deal events) are shown without a spurious "02:00".
- A duplicated settings heading was removed.
