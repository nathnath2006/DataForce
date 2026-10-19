# UI identity contract: applying the visual identity to the app

Decided with the PO on 2026-10-19.

- Apply `docs/VISUAL-IDENTITY.md` and the DataForce design system (claude.ai artifact "DataForce Visual Identity", whose component styles mirror `frontend/src`) to the whole UI.
- Use **Helvetica for everything**.

## Rules that still hold

- Numbers come from code.
- "Not verified" and AI-made items never look like facts.
- Light and dark are equals.
- No raw hex in components: only `var(--token)` from `tokens.css`.
- No external font download.
- Text contrast is at least 4.5:1, and chart marks at least 3:1, in both themes.

## 0. Who owns what

**Tech lead (do not edit):** `backend/app/{config,db/models}.py`, `backend/app/domain/*`, `backend/app/agent/**`, `backend/app/mcp_server/**`, `frontend/src/api.ts`, `frontend/src/types.ts` (append only, see below), and this file.

| Agent | Owns |
|---|---|
| **F: foundation** | `frontend/src/tokens.css`, `styles.css`, `ui.tsx` (adds `AiBadge`), `orgchart/**`, `meetings/**`, `titles/**`, `docs/VISUAL-IDENTITY.md` |
| **S: shell** | `frontend/src/App.tsx`, new `frontend/src/shell/**`, `pages/AccountDetail.tsx`, `pages/ContactDetail.tsx`, `companies/CompanyDetail.tsx`, `assistant/**` |
| **W: workflow** | `frontend/src/flows/**`, `backend/app/flows/**` (engine and result schema), `backend/app/api/routes/flows.py` with its schemas, and the tests for these |
| **Q: data quality** | new `backend/app/services/quality.py`, `backend/app/api/routes/quality.py`, `backend/app/api/schemas_quality.py` (register the router with one line in `app/api/main.py`), new `frontend/src/quality/**`, `pages/Accounts.tsx`, and their tests |

Shared rules:
- New CSS goes in the owner's own file, never in another agent's stylesheet.
- Only F edits `styles.css` and `tokens.css`. An agent that needs a new token asks the tech lead in its report.
- `types.ts` may get new exports appended, never edits to existing ones.

## 1. Foundation (F)

- **Fonts.** In `tokens.css`, `--font` and `--mono` both become `Helvetica, "Helvetica Neue", Arial, sans-serif` (classic Helvetica first): the PO asked for Helvetica everywhere, code included. Update `VISUAL-IDENTITY.md` §3 to match.
- **Contrast fixes** (both `tokens.css` dark blocks, and the doc):
  - dark `--ink-soft` becomes `#aeb6c2` (5.0:1 on dark `--mute-bg`, was 4.1:1);
  - light chart colors: `--chart-2` becomes `#b5651d` and `--chart-5` becomes `#9a7b0c` (both at least 3:1 on white).
- **New tokens.**
  - `--chart-1` … `--chart-6`, light and dark: the values of `flows.css` `--s1` … `--s6`, with the two light fixes above. W then points `--s*` at them.
  - `--mark-0` … `--mark-5`: the `.th0` … `.th5` rgba values, one value for both themes.
  - `--r-sm: 4px` for inline marks and `code`.
  - Add all of them to the doc, marked *(derived)*.
- **Gaps to close.**
  - `.th*` use `--mark-*`.
  - The meetings `.swatch` is renamed `.mark-swatch`, with its TSX updated. The flows `.swatch` stays W's.
  - The org chart's 6px radii become `--r-md`; mark and code radii become `--r-sm`.
- **Type scale.**
  - `h1` is 28/34 at weight 600, tracking -.02em.
  - `h2` (card and dialog titles) is 20/28 at weight 600.
  - `h3` is 15/22 at weight 600.
  - Table headers and labels are 12/16, weight 500, tracking .04em, uppercase.
  - Body text is 15/22.
  - Check that dense cards still read well.
- **AiBadge.**
  - `ui.tsx` exports `AiBadge({children})`: a `.ai-pill` with a `highlight` fill and `highlight-ink` text, `r-pill`, 12px semibold, never clickable. It goes in `styles.css`.
  - Use it for:
    - org-chart proposals with `evidence.found_by === "ai"`: "found by AI" (replacing the plain tag);
    - titles classified by the AI (`title_source === "llm"`): "AI" next to the class, keeping the existing flag text;
    - discovered themes named by the AI (`named_by === "llm"`): "named by AI".
  - The item keeps its honest-state styling.

## 2. Shell (S)

- **Assistant drawer** (`shell/AssistantDrawer.tsx`, `shell/shell.css`).
  - A right-hand glass drawer, with `--glass` and blur and a fallback to `--surface`, a 16px left radius and `--shadow-2`, plus an icon rail on the far right edge. The rail is 44px wide, with one button (Assistant) using a 1.5px outline icon.
  - **Collapsed by default.** Its open or closed state is remembered with `safeStorage` (key `df.drawer`).
  - **Scope.** Detail pages register their scope (`{kind: "account" | "company", id, name}`) through a small context in `shell/`, and the drawer then shows the existing `AskPanel` for that scope. Elsewhere it shows a one-line empty state: "Open an account or a company to ask about it."
  - The Ask panel leaves the account and company pages; its behaviour (caps, checks, citations) is unchanged.
  - **Phones** (under 720px): the drawer overlays full width, and the rail becomes a floating button that clears the safe-area inset.
  - Keyboard: Escape closes it, and focus returns to the rail button.
- **Detail header** (`shell/DetailHeader.tsx`).
  - Account, company and contact pages open with the record's name (h1), its key status tags, and on accounts a **stage roadmap** of its most recent open deal, or of its latest deal when none is open.
  - The roadmap is pills for prospecting → qualification → proposal → negotiation → closed:
    - done stages use `ok`;
    - the current stage uses `primary`;
    - later stages use `mute-bg`;
    - a lost deal shows "closed lost" in `bad`.
  - Then the page's existing content. Where the page has natural groups, lay it out as the 3-column summary: facts · timeline and documents · insights, stacking to one column under 1100px. Do not invent data.
- **Layout contract.** Content stays at most 1280px wide, with the 24px gutter (16px on phones). The top bar keeps brand, workspace, then a spacer, then theme. Do not add a search box.

## 3. Workflow (W)

- **Node state edge.**
  - The canvas node (`FlowEditor.tsx` and `.fnode`) becomes the framework's workflow node: a `--r-md` card with a 3px left edge that states its state:
    - `primary` when selected or running;
    - `ok` when the run gave a verified result (stats, model);
    - `ink-soft` dashed with `mute-bg` when not verified;
    - `bad` on an error;
    - `hairline` when idle.
  - Icon, name and one meta line. Dataset (source) and model blocks show a hexagon glyph.
  - Keep the handles and port labels working.
- **Column profile** (backend).
  - For each node's output frame, the engine adds `profile`, one entry per column for at most 60 columns, computed on the **full** frame with exact counts:
    - `{name, dtype, n, non_null, n_unique (capped at 10,000, with a flag)}`;
    - for numeric columns, `hist`: 8 equal-width bins, with min and max;
    - for text and boolean columns, `top`: up to 5 `{value, count}`, values capped at 60 characters.
  - The profile respects the existing time and size limits. It is optional in the result schema (older saved results have none), and it is **not** added to the agent tools' output (`app/agent` is untouched).
- **Columns grid** (`flows/ColumnsGrid.tsx`).
  - In the results panel, a "Columns" tab next to the preview shows a compact table with 36px rows and a sticky header:
    - the column name;
    - a mono type tag;
    - a mini distribution: an SVG sparkline of `hist` or `top`;
    - a quality bar, `non_null / n`, green over `bad-bg`, with the percentage printed;
    - a meaning chip (money, date, category, id, number, text) inferred from the name and dtype by a simple documented rule. The chip is labelled as a guess in its tooltip.
- **Chart colors.** `--s1` … `--s6` alias `--chart-1` … `--chart-6`.

## 4. Data quality (Q)

- **Endpoint.** `GET /api/w/{ws}/quality` returns exact SQL counts for the workspace, as a list of checks `{id, label, total, segments: [{kind: ok|warn|bad|unknown, label, count}]}`:
  - `managers`, "Contacts linked to a manager": ok = has a manager; warn = none, with an open suggestion; unknown = none, with no suggestion.
  - `titles`, "Job titles classified": ok = dictionary or manual; warn = classified by AI, or flagged; unknown = unknown or missing.
  - `amounts`, "Deals with an amount": ok = amount set; bad = missing on an open deal; unknown = missing on a closed deal.
  - `companies`, "Accounts linked to a company": ok = linked; unknown = not linked.
  - Read-only, workspace-scoped, one query per check. Tests check every count against SQL on the test DB, plus isolation.
- **HealthBar** (`quality/HealthBar.tsx`): the framework component. A 6px pill track with segments proportional to their counts, the label and "x of y" beside it, and a key with the exact count per segment. The bar never carries the number alone. It has an `aria-label` with the counts.
- **Placement.** A "Data quality" card at the top of the Accounts page with the four bars. Each bar links to where the problem is fixed: Contacts for titles, an account's org chart for managers, Deals for amounts, Companies for links.

## 5. Not done in this round

- `TransformStep`: no feature in the app is an ordered list of steps.
- A search box in the top bar.
- A user menu (M3b, login).

## 6. Definition of done (every agent)

- `npx tsc -b --noEmit`, `npx vitest run` and `npm run build` are clean. Backend owners also run ruff and their targeted pytest files; the tech lead runs the full suites.
- **Light and dark checked:**
  - no raw hex outside `tokens.css`;
  - no `!important`;
  - keyboard focus visible;
  - `prefers-reduced-motion` respected for the drawer's transition.
- **No new dependency.** No git. Do not use the dev DB or the server on port 8800.
- Report in at most 200 words.
