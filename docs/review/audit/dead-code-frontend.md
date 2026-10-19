# Dead code audit: frontend (lens: unused code)

Scope: `frontend/src`, `frontend/package.json`. Read-only audit. Scripts: `/private/tmp/claude-501/-Users-a1234-Documents-GitHub/09ecc94a-9687-4eaa-8fb7-441ce6fde086/scratchpad/audit/` (`dead.py` import graph, `css.py` classes and tokens, `api.py` helpers, `routes.py` route diff).

## Tooling summary
- `npx tsc --noEmit --noUnusedLocals --noUnusedParameters -p .`: exit clean, zero diagnostics (tsconfig already enables both flags). No unused locals/params.
- Import graph (all `.ts/.tsx` under src): one non-test file nothing imports (DC-F-01). Everything else is reachable from `main.tsx`.
- CSS: all classes in the 7 CSS files are referenced, except those listed below (dynamic or library). Tokens: one unused.
- API routes: every frontend `request(...)` call maps to an existing backend route. No stale calls. (Three false alarms in the script came from template-literal artifacts, checked by hand.)

## Findings

### DC-F-01  Unused page component `pages/OrgChart.tsx`
- Path: `frontend/src/pages/OrgChart.tsx:1-23` (export `OrgChart`, line 19).
- Evidence: no module imports `./pages/OrgChart` or `../pages/OrgChart` (import graph); `OrgChart` has 0 uses in the file besides its definition and no JSX use elsewhere. App.tsx routes do not mention it. It was superseded by `orgchart/OrgChartPanel.tsx`, which renders its own `<ul className="tree">` and `Branch` (OrgChartPanel.tsx:139). `frontend/README.md:12` still says `src/pages/*` are screens, harmless.
- Confidence: certain
- Recommendation: delete the file. `buildOrgTree`/`OrgTreeNode` in `lib.ts` stay (used by `orgchart/model.ts:2`, `OrgChartPanel.tsx:6`). `.tree` CSS (styles.css:70-71) stays (OrgChartPanel uses it).

### DC-F-02  `ancestors()` exists only for its test
- Path: `frontend/src/flows/graph.ts:157`.
- Evidence: referenced only in `graph.test.ts:3,83`. No own-file use (0 other occurrences in graph.ts), no component use.
- Confidence: certain (kept only by its own test)
- Recommendation: delete the function and its test case (`graph.test.ts:82-84`), or keep if a planned feature needs it (then mark as such).

### DC-F-03  Client helper `flowApi.deleteFile` never called
- Path: `frontend/src/flows/flowApi.ts:41`.
- Evidence: name appears only at its definition; no `.deleteFile` call in any .ts/.tsx. Backend route `DELETE /w/{ws}/files/{id}` exists (so it is a UI gap, not a stale call).
- Confidence: certain (unused); whether to remove or wire up a delete button is a product call.
- Recommendation: remove, or add the missing UI. Same decision for the backend route.

### DC-F-04  Unused CSS token `--accent-text`
- Path: `frontend/src/tokens.css:59`.
- Evidence: zero `var(--accent-text)` in any CSS/TS/TSX/index.html. It is labelled legacy alias.
- Confidence: certain (static search); likely safe.
- Recommendation: delete the alias.

### DC-F-05  Functions exported only for tests (production code does not use the export, but uses the function internally)
- `lib.ts:148 formatWithCi` (used internally by `formatStat`, lib.ts:157, and tested at lib.test.ts:51-52); `lib.ts:133 formatValue`, `lib.ts:139 formatDiff` (used internally only, no other importer). `theme.tsx:9 nextTheme`, `:18 readTheme`, `:25 saveTheme`, `:29 applyTheme` (own-file use; imported by theme.test.ts). `shell/logic.ts:4 DRAWER_KEY`, `quality/HealthBar.tsx:5 segmentWidths`, `meetings/text.ts:10 safeOffset`, `flows/graph.ts:101 wouldCycle` (all used internally, exported for tests).
- Confidence: certain that the `export` is test-only; these are not dead code.
- Recommendation: leave (test seams). Listed so nobody deletes them as "unused".

### DC-F-06  Exports with no importer anywhere (the symbol is used inside its own file, only the `export` keyword is surplus)
Types: `types.ts:11 RecordSource, :15 Dimension, :16 StatStatus, :83 StageTotals, :98 GroupStats, :108 ScanReport, :115 PricingOut, :116 ToolOut, :153 ActivityItem, :180 AskQuote`; `theme.tsx:3 ThemeChoice, :4 THEME_KEY`; `quality/api.ts:3 SegmentKind, :6 QualityOut`; `shell/scope.tsx:3 DrawerScope`; `shell/logic.ts:14 StageState, :15 RoadmapStep`; `shell/DetailHeader.tsx:7 StageRoadmap`; `agent/format.ts:2-4 AgentConnect, AgentTool, AgentCall`; `orgchart/api.ts:4-5 AiPassResult, ProposeResult`; `orgchart/model.ts:5-7,13,20,98 LinkOrigin, ProposalKind, ProposalStatus, PersonRef, SuggestedEdge, EvidenceView`; `titles/api.ts:7 ReviewItem`; `titles/TitleClass.tsx:26 sourceKind`; `meetings/text.ts:3 Seg, :85 THEME_CLASSES, :86 themeClass`; `meetings/api.ts:6 UploadFields`; `meetings/types.ts:2 SpeakerOut, :15-16 ThemeKind, ThemeExcerpt`; `assistant/AskPanel.tsx:12 AnswerText`; `ui.tsx:26 toApiError`; `pages/Analysis.tsx:138 gatesLine`; `flows/Results.tsx:71 PivotTable`; `flows/pivot.ts:15,17,18,37 TOTAL_LABEL, PivotRowModel, PivotModel, Scale`; `flows/columns.ts:29 Bar`; `flows/ConfigForm.tsx:58 FormProps`; `flows/types.ts:2,3,14,15,16,23,61 Scalar, CrmTable, SortKey, Operand, ComputedOp, JoinKey, Dtype`; `flows/graph.ts:22,98,170,176,246 PaletteGroup, Conn, ColumnCtx, datasetColumns, Template`.
- Evidence: name-based grep across src (excluding self) finds no other module. Many are type declarations that give exported function signatures a nameable type.
- Confidence: likely (name collisions could hide a user, but none were found; tsc passes).
- Recommendation: low value. Optionally drop `export` from these to shrink the public surface. Not a removal of logic. `themeClass`/`THEME_CLASSES` have a test (text.test.ts:48 checks the output), still used inside text.ts:82.

### DC-F-07  Dynamically built CSS classes (not dead)
- `flows/flows.css:61-62 .s1-.s6` built by `` `s${(i % 6) + 1}` `` in `flows/Charts.tsx:45,68`; `meetings/meetings.css:6-8 .th0-.th5` built by `themeClass` (`meetings/text.ts:86`); `.react-flow`, `.react-flow__handle` (flows.css:31,43) are @xyflow/react library selectors; `stage ${s.state}` (shell/DetailHeader.tsx:13) and `side ${navOpen ? "open" : ""}` (App.tsx:142) resolved, matching classes exist.
- Confidence: unsure for the `.sN`/`.thN` individual members (reachable only for index ranges 0-5 as built); certain they are live as a family.
- Recommendation: keep.

### DC-F-08  Duplicate helper: two `formatDate` implementations with different output
- Paths: `frontend/src/lib.ts:174` ("21 Aug 2026", "—" for empty, en-GB) and `frontend/src/meetings/text.ts:89` (ISO `YYYY-MM-DD`, "no date" for empty). Both used (MeetingsPanel imports the text.ts one).
- Related inconsistency: date-time shown three ways: `lib.formatDateTime` (en-GB), `meetings/MeetingsPage.tsx:81` and `flows/FlowsPage.tsx:37` call `new Date(...).toLocaleString()` with browser locale. Number grouping uses `en-IE` in lib.ts:100-125 and meetings/text.ts:95, `en-US` in flows/pivot.ts:8, flows/Results.tsx:22,65, flows/ColumnsGrid.tsx:53.
- Confidence: certain that they are duplicate/divergent; intent unknown (the meetings one may be deliberate).
- Recommendation: unify on `lib.ts` helpers (or rename the meetings one to avoid the same name), and pick one locale for counts.

### DC-F-09  Duplicate storage wrapper
- Paths: `frontend/src/theme.tsx:13-27` (own `defaultStore()` try/catch around `localStorage`) vs `frontend/src/ui.tsx:135 safeStorage` (used by App.tsx and shell/logic.ts).
- Evidence: both wrap localStorage in try/catch; theme.tsx takes an injectable store for tests, which is why it differs.
- Confidence: likely (partial duplicate, justified by testability).
- Recommendation: optional: have theme use `safeStorage` through an adapter. Low priority.

### DC-F-10  npm dependency probably unused: `@types/node`
- Path: `frontend/package.json` devDependencies `@types/node`.
- Evidence: no `node:` imports, `process.`, `__dirname`, or `require` in `src/` or `vite.config.ts`; tsconfig `"types": ["vite/client"]` excludes ambient node types. Other deps all imported: `@xyflow/react` (flows/FlowEditor.tsx, graph.ts), `react`, `react-dom` (main.tsx), `react-router`, `@vitejs/plugin-react` and `vitest` (vite.config.ts, 13 test files), `typescript`, `vite`, `@types/react`, `@types/react-dom`.
- Confidence: unsure (Vite's own type declarations may reference node types transitively; with skipLibCheck, removal could still be fine).
- Recommendation: try removing in a branch and run `npm run build` and `npm test`.

### DC-F-11  Backend routes with no frontend caller
- `GET /w/{ws}/titles/preview` (`backend/app/api/routes/titles.py:68`): no frontend reference (`titles/api.ts` exposes only normalize, review, title-class).
- `GET /connectors/tamtam/callback`: browser redirect target, not called by fetch (expected).
- Confidence: likely for titles/preview (could be used by the MCP agent or tests; outside the frontend lens).
- Recommendation: confirm with the backend audit before removing.

### Checked and clean
- Unused locals and parameters (tsc), unimported files (other than DC-F-01), unreferenced CSS classes (other than dynamic), stale API paths, unused `api.ts` methods (only DC-F-03), `src/api.ts` helpers all called.
- `dist/` and `tsconfig.tsbuildinfo` are build outputs (dist is git-ignored), not source.

## Counts
certain: 5 (DC-F-01, 02, 03, 04, 08) plus DC-F-05 (informational, not dead); likely: 3 (DC-F-06, 09, 11); unsure: 2 (DC-F-07, DC-F-10).
