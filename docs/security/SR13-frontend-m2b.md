# SR13: M2b frontend security review

Scope: `frontend/src/{orgchart,titles,meetings}`, `pages/{Contacts,ContactDetail}.tsx`, the "Themes vs win rate" template in `src/flows/graph.ts`. Method: source review plus `npm run typecheck` (clean), `npm test` (64 pass), `npm run build` (ok), `npm audit` (0 vulnerabilities). No application code was changed.

## Findings

| ID | Severity | File:line | Issue | Repro | Suggested fix |
|---|---|---|---|---|---|
| SR13-01 | Low | `src/meetings/MeetingsPanel.tsx` (TranscriptDialog, `buildTurns` call) | `buildTurns` runs on every render (not memoized) and the viewer renders every segment as a DOM node with no cap or windowing. A very large transcript with thousands of chunks makes the tab slow, and every modal state change re-runs it. This is a self-inflicted slowdown only (loopback, single user). | Upload a multi-MB .txt, open View. | `useMemo` on `[d]`; render turns in pages, or cap and offer "show more". |
| SR13-02 | Low | `src/meetings/MeetingsPanel.tsx` UploadDialog | No client-side size check. The `accept` attribute is only a hint. The server is the real limit. A huge file is read fully by the browser before the server rejects it. | Pick a very large file. | Show a size warning above the server limit from the contract; keep server enforcement. |
| SR13-03 | Low | `src/orgchart/OrgChartPanel.tsx` ProposalItem | Accept and Reject act on one click with no confirm. Accept writes a reports_to link (a fact) and Reject suppresses re-proposal for that pair (contract line 193). Both are user-initiated and one-item, but a misclick is hard to undo in the UI. | Click Reject. | Add `Confirm` for Reject, or an undo notice. Optional. |
| SR13-04 | Info | `src/titles/TitlesToolbar.tsx` ReviewTitles | `<Link to={it.contact_id}>` is a relative link built from server data. react-router treats it as a path (no `javascript:` execution), so it is safe with UUIDs. A non-UUID value would resolve relative to the current URL. | n/a | Use an absolute path `/w/${ws.slug}/contacts/${id}` with `e()`. |

No finding at medium or above.

## Confirmed protections

- **Untrusted text rendering.** There is no `dangerouslySetInnerHTML`, `innerHTML` or `insertAdjacent*` in `src` (grep). The only `href=` is a static one in `main.tsx`. Transcript text, speaker labels, theme labels, top terms, excerpts and evidence all render as React text nodes. `<mark>` gets `className` from an index-based `th0..th5` (`themeClass`, modulo-safe) and `title` from the label (an attribute value, escaped by React). Evidence is read through `str()`, so non-string JSON values are dropped.
- **Highlight builder** (`meetings/text.ts`). Offsets go through `safeOffset`: NaN or Infinity gives 0, negatives are clamped to 0, values past the text are clamped to the length, and offsets never cut a surrogate pair. Chunks are sorted and clipped against a cursor, so overlapping, inverted or empty ranges never repeat or lose text. Concatenating all segments gives back the original, and tests cover this (`text.test.ts`). Markup cannot be created from data.
- **Upload.** Uses `FormData` with `fetch`, header `X-DataForce: 1`, and no manual Content-Type (the browser sets the multipart boundary). `credentials` is `same-origin`. The file input has `accept=".pdf,.md,.markdown,.txt"`. Title is `maxLength=200`. Errors go through `parseApiError`.
- **Flow from theme label.** `themesVsWinRateGraph(label)` places the label only as the string `value` of one `eq` condition on a fixed graph skeleton. Column, op, node ids and types are constants. JSON serialization escapes the label, so it cannot add nodes, keys or edges. The flow name is sliced to 200 characters. The label is not passed through `parseScalar`, so "true" or "42" stays a string. The backend still validates the graph.
- **Mutations.** All go through `request()` (adds `X-DataForce`) or the upload helper above.
- **Destructive actions.** Delete transcript uses `Confirm` with danger styling and a copy that states the data cannot be recovered. Accept and Reject are covered by SR13-03. Title-class changes are explicit Save/Cancel.
- **AI disclosure.** Normalize titles and theme naming both state what is sent to the model and tag AI-sourced results ("AI", "named by AI") and flag them for check. Suggested links are drawn apart from facts and labelled "not confirmed".
- **CSP.** The new CSS is plain static stylesheets (`orgchart.css`, `meetings.css`) bundled by Vite. There are no `<style>` tags or `createElement("style")` in `dist` JS, and no inline script or style in `dist/index.html`. Highlight colours are classes, not inline styles.
- **Dependencies.** `git diff 654bfde` on `package.json` and `package-lock.json` shows only `@xyflow/react 12.12.0` and its transitive packages. That was added in the M2a commit 4f62805 and reviewed in SR11. `git diff 4f62805` on both files is empty, so M2b added nothing. `npm audit` reports 0 vulnerabilities.

## Residual risks

- A huge transcript is only mitigated by the backend size limit (SR13-01 and SR13-02).
- AI-chosen theme labels can be long, misleading or misspelled. They are displayed safely but are not trustworthy. They are tagged "named by AI".
- Rendering with `white-space: pre-wrap` keeps control or bidi characters from transcripts, which could visually reorder text. This is cosmetic.
- The experience of the CSP in a real browser was not exercised (source and bundle inspection only).

## Resolution (tech lead, 2026-10-17)

| ID | Status | What changed |
|---|---|---|
| SR13-01 | Fixed | The transcript turns are memoised per document and rendered 200 at a time, with "Show more". |
| SR13-02 | Fixed | A file over 5 MB (the server limit) shows a warning, and Upload is disabled. The server still enforces the limit. |
| SR13-03 | Fixed | Accept and Reject open a confirmation that says what happens (a fact with its evidence; or never suggested again). |
| SR13-04 | Fixed | The review list links to the absolute contact path, with encoded segments. |
