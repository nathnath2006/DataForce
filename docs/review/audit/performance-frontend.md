# Frontend performance and data flow audit

Scope: frontend/ (React 19, react-router 7, @xyflow/react 12, Vite 8). Measured on http://127.0.0.1:8800, workspace `test-data` (122 accounts, 755 contacts, 350 deals, ~250 meetings), headless Chromium, localhost, cold context per page. Read-only. Scripts: scratchpad/audit/m.py.

## Measurements

### Bundle (`npm run build`, 305 modules, 0.4 s)

| Chunk | Raw | Gzip |
|---|---|---|
| index-*.js (main) | 399.88 kB | 117.43 kB |
| FlowEditor-*.js (lazy) | 220.11 kB | 68.29 kB |
| index-*.css | 21.47 kB | 5.36 kB |
| FlowEditor-*.css | 15.41 kB | 2.56 kB |

Lazy today: FlowEditor only (and with it @xyflow). Everything else (all pages, the meetings, org chart, Results/Charts, ConfigForm) is in the main chunk. On the wire the server sends them uncompressed (see PERF-F-01).

### Requests per page (cold load, first paint to last network finish)

| Page | API calls | Last finish | DOM nodes | Table rows | API bytes |
|---|---|---|---|---|---|
| accounts | 4 | 0.23 s | 1,374 | 122 | 61 kB |
| account detail | 10 | 0.09 s | 214 | 7 | 10 kB |
| company detail | 4 | 0.16 s | 637 | 49 | 42 kB |
| contact detail | 7 | 0.10 s | 120 | 0 | 8 kB |
| deal detail | 5 | 0.08 s | 146 | 6 | 7 kB |
| deals | 3 | 0.40 s | 8,118 | 350 | 191 kB |
| contacts | 4 | 0.13 s | 7,792 | 755 | 478 kB |
| companies | 3 | 0.07 s | 304 | 25 | 14 kB |
| meetings | 4 | 0.12 s | 939 | 25 | 43 kB |
| analysis (list) | 3 | 0.06 s | 77 | 1 | 2 kB |
| flow editor | 5 | 0.46 s | 169 | 0 | 7 kB |
| settings | 6 | 0.08 s | 287 | 14 | 10 kB |

No exact duplicate URL fetched on any page. Times are localhost best case; on a real network each waterfall step adds one RTT.

## Findings

### PERF-F-01 No response compression and no long-lived caching of assets
- Where: backend/app/api/static.py (static serving), uvicorn app (no GZip middleware); evidence below.
- Evidence: `curl -H 'Accept-Encoding: gzip'` returns the main JS with content-length 399,883 (raw, no content-encoding) and `/api/.../contacts?limit=1000` returns 418,169 bytes raw. Hashed assets carry only an ETag, no `Cache-Control: immutable`; index.html has `no-cache` (correct).
- Impact: first load ships 400 kB where 117 kB is possible (3.4x); the contacts list is ~418 kB of JSON that compresses roughly 8-10x. Repeat visits revalidate every asset.
- Fix: add GZip/Brotli middleware (or Starlette `GZipMiddleware`, minimum_size 1 kB) and `Cache-Control: public, max-age=31536000, immutable` for `/assets/*`. Keep `no-store` on /api.
- Effort: S.

### PERF-F-02 List pages fetch limit=1000 and render every row (no paging, no virtualization)
- Where: pages/Contacts.tsx:19-21, pages/Deals.tsx:15-16, pages/Accounts.tsx:18, and the same `limit: 1000` in AccountDetail.tsx:22,24, ContactDetail.tsx:20, DealDetail.tsx:21, Deals.tsx:101, Contacts.tsx:71.
- Evidence: contacts = 755 rows, 7,792 DOM nodes, 478 kB; deals = 350 rows, 8,118 DOM nodes (each row has a stage `<select>` with 8 options), 191 kB, slowest list at 0.40 s. The server caps limit at 1000 (backend/app/api/routes/crm.py:36). Companies and meetings are properly paged (25 per page).
- Impact: render cost and payload scale linearly; see the 10x section.
- Fix: server-side paging (offset/limit already supported) with a pager as in MeetingsPage, or a small windowing hook; replace the per-row stage `<select>` with a cell that becomes a select on focus.
- Effort: M.

### PERF-F-03 Hard 1000 cap silently truncates at 10x
- Where: every `limit: 1000` call above; the dropdown loaders pages/Contacts.tsx:19, Contacts.tsx:71, Deals.tsx:101 (account pickers) and AccountDetail.tsx:131 (`limit: 200` companies).
- Evidence: crm.py:36 `Query(ge=1, le=1000)`. With 1,220 accounts the "All accounts" filter and "New contact/deal" account picker lists only the first 1000. Contacts shows "N of total" so truncation is visible there, but not in the pickers.
- Impact: wrong or unreachable choices (a user cannot select account 1001 for a new deal); no error is raised.
- Fix: use a search-as-you-type combobox (the CompanyDetail.tsx:147 pattern with `limit: 20`) for pickers; page the lists.
- Effort: M.

### PERF-F-04 Page data waits for the shell: workspaces+users waterfall on every navigation to a fresh load
- Where: App.tsx:80-81 (`useLoad(listWorkspaces)`, `useLoad(listUsers)`), App.tsx:94 (`if (wss.loading && !wss.data) return <Loading/>`), so `<Outlet/>` mounts only after /api/workspaces returns.
- Evidence: accounts: /workspaces and /users at 0.12 s, then /quality and /accounts at 0.18 s. Deals: 0.33 s then 0.37 s. Every page has this two-step start.
- Impact: one extra RTT before any page data on each hard load; the list page cannot overlap its fetch with the shell fetch.
- Fix: render the Outlet while `wss` loads (the page only needs `slug`; `useWs` needs `ws`, so pass a slug-only fallback), or fetch the workspace list once and cache it. Also `listWorkspaces` is requested by Shell with deps `[slug]`, so switching workspace refetches the same list.
- Effort: M.

### PERF-F-05 Dependent waterfalls on detail pages
- Where: pages/ContactDetail.tsx:18-21 (contacts of the account wait for the contact), pages/DealDetail.tsx:18-24 (contacts and documents wait for the deal), flows: App.tsx:21-23 lazy chunk then FlowEditor flow fetch then catalog and files (FlowEditor.tsx:97-98).
- Evidence: flow editor 0.46 s to last finish: chunk, then /flows/{id} at 0.37 s, then /catalog and /files at 0.45 s (three sequential steps). Contact detail: sameAcct list at 0.08 after contact at 0.06. Account detail is parallel (good).
- Impact: 2-3 serial round trips per detail view; on 100 ms RTT the flow editor takes about 0.4 s longer than needed.
- Fix: flow editor: start `catalog` and `files` loads from the route wrapper in parallel with the flow, and preload the chunk on hover of the Analysis links (`import()` in onMouseEnter). Contact/deal: add `contact.account_id` to a combined server endpoint, or prefetch.
- Effort: S for the flow editor, M for the rest.

### PERF-F-06 WsContext value recreated on every Shell render, and the whole page tree re-renders with it
- Where: App.tsx:99-101 passes an inline object literal to `WsContext.Provider`. Shell holds `navOpen`, `creating`, `addUser`, `acting`, `drawerOpen` state.
- Evidence: reading; each toggle of the mobile menu, drawer, or acting-as select changes the value identity, so every `useWs()` consumer re-renders, including the 755-row contacts table and 350-row deals table. ScopeProvider (shell/scope.tsx:11) memoizes its value correctly. theme.tsx is not an issue (small).
- Impact: opening the assistant drawer or the mobile nav re-renders the active list page (about 8,000 DOM nodes on contacts and deals).
- Fix: `useMemo` the context value, and wrap the table bodies in `React.memo` rows, or split the nav/drawer state into a child component so Shell itself does not re-render.
- Effort: S.

### PERF-F-07 useLoad has no abort and no cache, so navigation never cancels requests
- Where: ui.tsx:5-24; api.ts:6-30 (`fetch` is called without a `signal`). There is no `AbortController` anywhere in src/.
- Evidence: grep for AbortController returns no hits. Stale responses are discarded with a ticket counter (good for correctness), but the network request still runs to completion and the state update path still deserializes JSON. `loading` also flips to true on every reload so the page shows a spinner flash on refetch only when `data` is null (guarded by `loading && !data` in most pages, fine).
- Impact: fast typing in search boxes (debounced) or quick navigation leaves requests running; with a 1000-row list at 10x each abandoned request is ~0.5-4 MB wasted. No stale-while-revalidate cache, so returning to a list always refetches (accounts 61 kB, contacts 478 kB, deals 191 kB).
- Fix: pass an `AbortSignal` from useLoad through `request()`; add a small keyed cache (or adopt TanStack Query) with 30 s staleness for list endpoints.
- Effort: M.

### PERF-F-08 Main chunk contains every page; only FlowEditor is split
- Where: App.tsx:4-16 static imports; lazy only at App.tsx:21.
- Evidence: main chunk 400 kB raw / 117 kB gzip. Only workspaces/accounts is needed for first paint of most sessions.
- Impact: moderate. The bundle is small by absolute standards; but Settings, Analysis (scan), Meetings (themes, transcript viewer), OrgChartPanel and Results/Charts are rarely used on first load.
- Fix: `lazy()` for Settings, AnalysisPage, MeetingsPage, FlowsPage and the OrgChartPanel; add `build.rollupOptions.output.manualChunks` for react/react-router vendor so app code changes do not invalidate the vendor cache.
- Effort: S.

### PERF-F-09 Org chart and AI settings fetched on every account detail
- Where: orgchart/OrgChartPanel.tsx:125,127 (`proposals` and `aiApi.get`), plus `org-chart` in AccountDetail.tsx:23.
- Evidence: account detail issues 10 API calls, the most of any page, including `/ai` (also fetched again on Settings) and `/connectors/tamtam` on the contact page. All are small (10 kB total).
- Impact: low today; every extra call is counted against the browser's 6 connections per origin on HTTP/1.1 (uvicorn here), so ten parallel calls queue.
- Fix: put `ai` settings in the workspace context (loaded once), or in the keyed cache from PERF-F-07.
- Effort: S.

### PERF-F-10 Flow editor re-derives graph and JSON on every node change
- Where: flows/FlowEditor.tsx:105-106 (`fromFlow(nodes, edges)` then `JSON.stringify([name, graph]) !== saved` per render), FlowEditor.tsx:139 (maps every node on every `results` change), FlowEditor.tsx:127 (`pushState` within the guard effect).
- Evidence: typing a character in the flow name or a config field (ConfigForm `onChange` calls `patch`, replacing `nodes`) re-runs `fromFlow` and a full `JSON.stringify` of the graph. `onSelectionChange` is an inline function so ReactFlow gets a new prop each render. The flow in the workspace has few nodes; at 100 nodes this is still cheap (sub-millisecond to a few ms) but grows linearly, and each keystroke also re-renders all custom nodes since `shown` is rebuilt.
- Impact: low for realistic flows (under 50 nodes); MiniMap with `pannable zoomable` adds per-node render cost.
- Fix: compute `dirty` with a cheap version counter or compare debounced; memoize `onSelectionChange`; `React.memo` the block node component.
- Effort: S.

### PERF-F-11 Dirty-guard effect pushes a history entry each time dirty flips
- Where: flows/FlowEditor.tsx:124-136.
- Evidence: each time `dirty` becomes true the effect calls `history.pushState`; the cleanup removes listeners but does not pop the pushed entry, so save then edit again adds extra history entries and the Back button needs multiple presses.
- Impact: UX and a small history leak per session; listeners themselves are cleaned up correctly.
- Fix: push the guard entry once on mount, or use react-router `useBlocker` (needs a data router).
- Effort: S.

### PERF-F-12 Results tables and transcript viewer rely on server truncation, not on the client
- Where: flows/Results.tsx:55-66 (PreviewTable maps `result.preview`), Results.tsx:72-91 (PivotTable maps all rows), meetings/MeetingsPanel.tsx:85-100 (paged by 200 turns, good).
- Evidence: PreviewTable is bounded by the server preview size; the pivot has `truncatedColumns` but rows are not capped on the client. Transcript viewer builds all turns once with `useMemo` and renders 200 at a time, but "Show more" keeps them all in the DOM (no windowing); a 5 MB transcript (limit) could reach thousands of turns after repeated clicks.
- Impact: low now. A pivot with thousands of rows would render in one go.
- Fix: cap pivot rows in `pivotModel` with a "show more" or virtualize; keep as is for previews.
- Effort: S.

## What is fine

- Lazy loading of the flow editor and its 220 kB canvas library: correct split.
- `useLoad` ignores stale responses through the ticket counter, and deps are explicit; no refetch loops seen (every page makes the same number of calls after 500 ms idle as at idle).
- Search inputs are debounced (`useDebounced` in ui.tsx:129 with timer cleanup).
- Meetings and companies lists use real server-side paging (25 per page); transcript viewer pages turns by 200 and memoizes `buildTurns`.
- `ScopeProvider` value is memoized; `useRegisterScope` clears on unmount.
- No duplicate API URL on any measured page; account detail loads its 5 data sources in parallel.
- Listeners cleaned up: AssistantDrawer keydown, FlowEditor guard, debounce timer, McpPanel's 2 s timeout is harmless (state set on an unmounted component is a no-op in React 19).
- No third-party chart or table library in the main chunk; charts are inline SVG.
- Cache headers: index.html `no-cache`, API `no-store` are right choices.

## 10x workspace (about 1,220 accounts, 7,550 contacts, 3,500 deals, 2,500 meetings)

| Path | Behavior at 10x |
|---|---|
| Contacts list (limit 1000) | Returns only the first 1000 of 7,550; header reads "1000 of 7550"; filters by account only reach the first 1000 accounts. About 78,000 DOM nodes if the cap were lifted. |
| Deals list (limit 1000) | Shows 1000 of 3,500, ~23,000 DOM nodes, ~550 kB uncompressed per load, each row with a select; the per-change `reload()` (Deals.tsx:23) refetches the whole 1000. Slow render (likely 300-800 ms). |
| Accounts list | 1000 of 1,220 rows, 20 kB more per refetch; "All accounts" selectors on Contacts/Deals/ContactForm silently drop 220 accounts. |
| Account/contact/deal detail | Per-account queries stay small (limit applies per account); fine. |
| Companies, meetings | Paged; fine. |
| Org chart panel, transcript viewer | Per-account / per-document; fine. |
| Flow editor | Server-side `flow_max_rows` 200,000; preview is truncated; fine for the client. |
| Payload | With no compression (PERF-F-01) the contacts and deals pages move multiple MB cold. |

Breaks first: Contacts and Deals pages (render time and the silent cap), then the account pickers.

## Priority order

1. PERF-F-01 (S) compression and asset caching.
2. PERF-F-02 and PERF-F-03 (M) paging and picker search.
3. PERF-F-06 (S) memoize WsContext.
4. PERF-F-04 and PERF-F-05 (M/S) remove the shell waterfall; preload the editor.
5. PERF-F-07 (M) abort and cache.
