# SR16 - UI identity round (fd87f39..1ebe182)

Read-only review. Probe: scratchpad sr16/test_probe.py (profile on 200k x 80 text columns, unhashable, inf and NaN columns, expired deadline). No High or Medium findings.

## Findings

### SR16-01 Low - Column profile top values bypass the agent's secret/contact redaction
Evidence: backend/app/flows/profile.py:44-45 builds top-5 values over the full frame for any text column, including names like password, token, email, phone. app/agent/tools.py:122 (_REDACT) blanks such columns in the preview, but the REST NodeResult.profile (flows/schemas.py:462) is not redacted. The profile is also wider than the preview: top values come from every row, not only the first rows. It is absent from the agent (_node_out builds NodeOut explicitly, tools.py:796-824), from MCP, and from run records (services/flows.py:145 summarise keeps only status, n_rows, error).
Impact: the local user sees values from rows beyond the preview. The user already controls the flow and source, so exposure is low; it matters if profile output is later forwarded elsewhere.
Fix: skip `top` for columns matching the _REDACT pattern, or share that predicate.

### SR16-02 Low - Drawer panel focus has no visible ring
Evidence: frontend/src/shell/shell.css `.drawer {... outline: none; }` while AssistantDrawer.tsx focuses the panel (tabIndex -1) on open. The rail button and inner controls use the global :focus-visible (styles.css:21), so they are fine.
Impact: keyboard users get no visible cue on the panel on open, though the next Tab lands on a visible control.
Fix: drop outline:none, or focus the close button or the first field instead.

### SR16-03 Low - Raw colour outside tokens.css
Evidence: frontend/src/styles.css:86 `dialog::backdrop { background: rgba(17, 24, 39, .45) }`. No `!important` anywhere in src (grep).
Fix: add a --scrim token.

### SR16-04 Info - Profile cost is unbounded between deadline checks and runs on every node
Evidence: profile.py:55-61 checks the deadline per column only. Probe: 200k rows x 60 high-cardinality text columns took 3.5 s for one node and 18.8 KB of JSON (60 cols cap, 60-char values, 10,000 unique cap all held; 5000-char values truncated to 60; unhashable dicts handled; inf and all-NaN columns gave hist None; expired deadline returned None). The profile is computed for every node, including those not displayed.
Impact: slower runs on wide frames; bounded by the run deadline and the 200k row cap.
Fix: optionally profile only the requested target node.

### SR16-05 Info - Small hardening items
- frontend/src/flows/columns.ts sparkBars: a NaN count would give NaN SVG attributes. Server counts are ints, so unreachable today. Filter with Number.isFinite.
- nodeState returns st-sel before st-unverified, so a selected unverified node loses its amber edge. It never shows green, so this is not a dishonest-state case.
- tests/api/test_quality.py has an unknown-workspace 404 test but no two-workspace isolation test. The SQL filters workspace_id on every query, including the OrgProposal EXISTS.

## Verified OK
- Quality endpoint: scoped by CurrentWorkspace (unknown slug gives 404). Only workspace_id-filtered SQL aggregates are returned (counts, fixed labels), no row data. 4 queries in total, with no per-row loops. The EXISTS uses ix_org_proposal_contact, and other filters are on workspace_id. It is a GET, so like the other GETs it passes the Host allow-list and needs no Origin or X-DataForce. Registered in api/main.py.
- Counts are exact integers (func.count / sum(case)); segments sum to total (test asserts it).
- Profile bounds: 60 columns, 10,000 unique cap, 60-char values, 8 bins; the deadline is honoured.
- Profile excluded from agent run_flow and MCP output and from run records (only counts and status are stored).
- XSS: no dangerouslySetInnerHTML or innerHTML in src. The only href is a static one (main.tsx). Column names, top values, meaning chips, titles, "Ask about {name}", deal names and AiBadge text are rendered as React text or attributes. SVG attributes come from numbers (bar geometry) and the aria-label string.
- Drawer: Ask goes through the same aiApi.ask with history sliced to 5 turns and 4000 characters. The storage key df.drawer holds only "open" or "closed"; no record data is stored. AskPanel is keyed by kind:id, and the scope is cleared on page unmount, so conversation state is not carried from account A to account B. A reply to an in-flight A request lands only in an unmounted component. While closed, the panel is `inert` and visibility:hidden, so it is not focusable.
- Honest state: nodeState gives green only for a verified model or a stats block with at least one verified row. Clusters, not-verified results and skipped blocks are unverified; errors are bad. The Meaning chip is labelled "a guess". The quality bars print the exact count per segment.
- Rail and inner controls keep the global focus-visible outline.

## Resolution (2026-10-19, tech lead)

| Finding | Change | Covered by |
|---|---|---|
| SR16-01 | Column profiles keep the counts of columns whose names look like secrets or contact details (`*_enc`, password, token, email, phone, mobile…) but show their values as "(hidden)". This is the same rule as the agent tools' flow output. The profile covering the full frame is by design: it is the exact-count view. | `tests/flows/test_profile.py::test_sensitive_columns_keep_counts_but_hide_values` |
| SR16-02 | The drawer shows a 2px `primary` focus ring (`:focus-visible`) instead of `outline: none`. | Manual check, keyboard |
| SR16-03 | The dialog backdrop uses the new `--backdrop` token (light and dark). No raw color remains outside `tokens.css`. | `grep` in CI review |
| SR16-04 | Accepted: the caps held (3.5 s and 19 KB for 200k rows × 60 text columns), and the run deadline still bounds the run. | — |
| SR16-05 | `sparkBars` treats non-finite values as 0. A selected node showing blue rather than its verified state is kept on purpose: selection is temporary and the results panel shows the status. The quality isolation test already seeds a second workspace. | `columns.test.ts` (non-finite) |
