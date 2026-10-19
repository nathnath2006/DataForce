# SR18 - M4 phase 1: activities, new flow blocks, workbooks

Scope: the uncommitted M4 phase-1 code (2026-10-19).
- A: deal stage history, activities, tasks and timeline: `services/{activities,stage_events,tasks,timeline}.py`, `routes/{activities,pipeline}.py`, `flows/sources/crm.py`, `demo/activities.py`, `src/activity/**`.
- C: new flow blocks: `flows/blocks/{dedup,aging,forecast,window,domain}.py`, SVM and SVR in `model.py`, the chronological split.
- D: workbooks: `app/viz/**`, `routes/{viz,workbooks}.py`, `services/workbooks.py`, `src/workbooks/**`, and echarts 5.6.0.

Method: two read-only Sonnet verifiers, one for A and C and one for D, plus browser checks by the tech lead.

Summary: 0 high, 2 medium, 6 low. All fixed, with a test each.

## Findings

### SR18-01 (medium) Chart tooltips built HTML from data values
- Where: `frontend/src/workbooks/option.ts`. The scatter and heatmap tooltip formatters put row labels and column names into a string with `<br/>`, and ECharts renders a string tooltip as HTML.
- Failure: an account named `<img src=x onerror=…>` injects markup into the tooltip. The CSP blocks inline script, but markup and attribute injection remain.

### SR18-02 (medium) Fuzzy dedup was effectively unbounded
- Where: `flows/blocks/dedup.py`. Comparisons ran on up to 2,000 values per block, which is about 2M pure-Python comparisons, with one deadline check per block. Comparison keys had no length limit, and Levenshtein is quadratic in length.
- Failure: a run spends minutes before its timeout is ever checked.

### SR18-03 (low) A naive timeline cursor gave a 500
- Where: `services/timeline.py` `decode_cursor`.
- Failure: comparing a naive cursor datetime with aware datetimes raised TypeError.

### SR18-04 (low) `PATCH activity {"subject": null}` gave a 500

### SR18-05 (low) Erasure masked the contact's name only
- Where: `activities.redact_contact`. Task `evidence` was not masked, and neither was an email address or phone number typed into an activity or task.
- Impact: phase 2 puts AI source sentences into `evidence`, so the gap would grow.

### SR18-06 (low) Timeline titles carried no untrusted flag
- Activity subjects, task titles, note text and meeting titles are rep or customer text, but only the summary was flagged.

### SR18-07 (low) Saved workbook specs had no bound on filter values or total size
- Where: `schemas_viz.py`. Filter values were bounded only at query time, and the spec had no overall size cap.

### SR18-08 (low) The CRM source path skipped the concurrency slot
- Where: `viz/source.py`. Abandoned slow queries (past the 20 s budget) could pile up threads.

## What passed

**Isolation and validation**
- **Workspace isolation:** every new query is scoped. Deals, accounts, participants, owners, authors, workbooks, flows and nodes are all checked against the workspace (404 across workspaces). Participants must belong to the deal's account.
- **Validation:**
  - text limits: subject and title 300, body 10,000;
  - enums;
  - stage dates: not in the future, not before the deal was created;
  - 50 participants;
  - timeline `limit` ≤ 200, with `kinds` whitelisted;
  - viz: 30 filters, 500 `in` values, 5,000 rows, a 20 s budget.
- **Viz query:** columns are checked against the frame and aggregations and operators are fixed lists. Nothing is evaluated from strings, and `contains` is literal.

**Data handling**
- **No HTML from data:** no `dangerouslySetInnerHTML` or `innerHTML` in the new frontend code. Pie, funnel and treemap labels draw on canvas.
- **Flow sources:** activities and tasks are exposed without body text, as lengths only.
- **SVM:** support vectors are training rows, so they are not exported above 2,000. No pickle and no eval anywhere.
- **Backfill command:** it refuses non-demo workspaces and never deletes.

**Requests and dependencies**
- **Mutations:** every new route sits behind the Origin and `X-DataForce` guard, and no GET mutates.
- **Dependency:** echarts is pinned exact at 5.6.0 with an integrity hash; the only new transitive packages are zrender 5.6.1 and tslib. `ignore-scripts` is kept, echarts is lazy-loaded, and the CSP is unchanged.

## Resolution

| Id | Fix | Test |
|---|---|---|
| 01 | Every tooltip uses `renderMode: "richText"`, drawn as canvas text and never HTML; the scatter formatter uses `\n` | `option.test.ts`: a label like `<img onerror>` comes back as itself, with no `<br` |
| 02 | Keys cut to 100 characters, `ctx.check()` every 1,000 pairs, at most 500 values per block, and a warning that names the cap | `test_batch1.py` |
| 03 | A naive cursor is read as UTC; TypeError and OverflowError give 422 | `test_activities.py` |
| 04 | A null subject gives 422 | `test_activities.py` |
| 05 | The name, emails and phones are masked in subject, body, task title and every string in `evidence`. Channels are unsealed in process only, never logged; one that cannot be unsealed is skipped. A phone matches on its last 9 digits with any separators | the erasure test in `test_activities.py` |
| 06 | `title_untrusted` on user-text items, in the backend schema and the frontend type | `test_activities.py`, `logic.test.ts` |
| 07 | `Filter`: at most 500 values and 1,000 characters per string; a workbook spec is at most 1 MB of JSON | `test_viz.py`, `test_workbooks.py` |
| 08 | The CRM path takes the flows slot and frees it when the thread ends | `test_viz.py` |

### Follow-up found in the browser

The first version of fix 08 refused a query at once when no slot was free. A canvas sends one query per tile at the same time, so a three-tile workbook got two "another analysis is still running" errors. This already applied to flow-node sources before the fix. Now a tile waits up to 15 s (`SLOT_WAIT_S`) for a slot before giving up. `test_viz.py` covers a slot that frees during the wait.

Not changed: a workbook tile whose source is a flow node re-runs that flow for each query. Caching flow outputs is noted for phase 2.
