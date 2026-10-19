# Visual identity framework: TamTamAI × Dataiku, Apple-simple

Source: the PO's "System Blueprint v1.0" board (2026-10-18). Hex values below are copied from that
board. Everything not on the board (dark-mode values, semantic colors, spacing scale, type sizes) is a
**proposal derived from it** and is marked *(derived)*. Change a value here first, then in
`frontend/src/tokens.css`; nothing else in the code may hard-code a color.

This file is written to be handed to any AI that builds UI for any product. Paste it as context and
tell the AI: "Follow VISUAL-IDENTITY.md exactly; use only the tokens; ask before adding a color."

## 1. Principles

1. **Apple simplicity.** One idea per screen area. Generous whitespace. Few borders, soft shadow
   instead of lines where possible. No decoration that carries no information.
2. **Dataiku density where data lives.** Tables, flows, health bars and step lists are compact and
   scannable; the breathing room is *around* them, not inside every row.
3. **Blue acts, yellow marks.** Blue = the thing you can click / the current place. Yellow = a
   highlight, a step, an "auto/AI did this" marker. Never both loud in one component.
4. **Honest state.** A "not verified" or "AI-suggested" item never looks like a verified fact: grey or
   dashed, with a label. (Project rule from M1; the identity must not weaken it.)
5. **Light and dark are equals.** Every token has both values; check both.

## 2. Color tokens

| Token | Light | Dark *(derived)* | Use |
|---|---|---|---|
| `--primary` | `#1D4ED8` Primary Blue | `#60A5FA` | Primary buttons, links, active nav, focus ring |
| `--primary-ink` | `#FFFFFF` | `#0B1220` | Text on `--primary` |
| `--highlight` | `#FACC15` Accent Yellow | `#FACC15` | Markers, active step edge, AI/auto badge, highlights |
| `--highlight-ink` | `#1F2937` | `#1F2937` | Text on `--highlight` (never white-on-yellow) |
| `--ink` | `#1F2937` Charcoal | `#F3F4F6` | Body text, headings |
| `--ink-soft` | `#4B5563` *(derived)* | `#AEB6C2` (was `#9CA3AF`, 4.1:1; now 5.0:1 on `--mute-bg`) | Secondary text, labels |
| `--canvas` | `#F3F4F6` Subtle Gray | `#111827` | Page background |
| `--surface` | `#FFFFFF` | `#1F2937` | Cards, panels, tables |
| `--glass` | `rgba(255,255,255,.80)` Glass White | `rgba(31,41,55,.72)` | Top bar, drawers, popovers (with blur) |
| `--hairline` | `#E5E7EB` *(derived)* | `#374151` | Dividers, input borders |
| `--ok` / `--ok-bg` | `#15803D` / `#DCFCE7` | `#4ADE80` / `#14301F` | Verified, healthy |
| `--warn` / `--warn-bg` | `#854D0E` / `#FEF9C3` | `#FACC15` / `#3A2E10` | Needs attention |
| `--bad` / `--bad-bg` | `#B91C1C` / `#FEE2E2` | `#F87171` / `#3B1B19` | Error, destructive |
| `--mute-bg` | `#E5E7EB` | `#374151` | "Not verified", disabled, neutral tags |
| `--backdrop` | `rgba(17,24,39,.45)` *(derived)* | `rgba(0,0,0,.6)` | Dialog backdrop behind the blur |
| `--chart-1` … `--chart-6` *(derived)* | `#2A6FDB` `#B5651D` `#2E9D6B` `#B04FB0` `#9A7B0C` `#5F6B7A` | `#6C9CF5` `#F0A860` `#6FD39A` `#D58AD5` `#E6C860` `#A0ABBA` | Chart series (marks >= 3:1). Light `-2` and `-5` darkened from `#D9822B` / `#C4A21A` to reach 3:1 on white. |
| `--mark-0` … `--mark-5` *(derived)* | `rgba` tints of blue, green, amber, red, violet, teal (.20 to .28 alpha) | same | Theme highlights behind transcript text (`.th0` … `.th5`) and `.mark-swatch` keys |

Rules: yellow is never body-text color on a light surface (contrast). Max one `--primary` button per
view region. Text contrast must stay ≥ 4.5:1 (checked: `#1D4ED8` on white 6.7:1, `#1F2937` on
`#F3F4F6` 12.6:1).

## 3. Shape, depth, space, type

- **Radius:** `--r-lg` 16px (cards, drawers, dialogs), `--r-md` 10px (buttons, inputs, nodes),
  `--r-pill` 999px (tags, chips, avatar), `--r-sm` 4px *(derived)* (inline marks, `code`). *(16px is on the board; others derived.)*
- **Shadow:** `--shadow-1` very soft for cards (`0 1px 2px rgba(17,24,39,.06), 0 4px 16px rgba(17,24,39,.05)`),
  `--shadow-2` for floating layers (dialog, popover). Dark mode drops shadow, keeps hairline.
- **Glass:** top bar and drawers use `--glass` + `backdrop-filter: saturate(180%) blur(14px)`.
  Fallback when blur is unsupported: solid `--surface`.
- **Spacing:** 4px base: 4, 8, 12, 16, 24, 32, 48. Page gutter 24px (16px on phones).
- **Type:** Helvetica everywhere, code included: `--font` and `--mono` are both
  `"Helvetica Neue", Helvetica, Arial, sans-serif`. Scale *(derived)*: h1 28/34 semibold, tracking -.02em;
  h2 (card and dialog titles) 20/28 semibold; h3 15/22 semibold; body 15/22; table headers and labels
  12/16 medium, uppercase, tracking .04em. Numbers in tables use tabular figures. No external font
  download (privacy; the app is local-first).
- **AI badge:** `AiBadge` (`.ai-pill`): `--highlight` fill, `--highlight-ink` text, `--r-pill`, 12px
  semibold, never clickable. Marks AI-made items (org-chart proposals found by AI, titles classified
  by AI, themes named by AI); the item keeps its honest-state styling.
- **Icons:** 1.5px outline, rounded joins, 20px; one blue or charcoal stroke with at most one yellow
  accent element (as on the board).

## 4. Dataiku-specific components

| Component | Spec |
|---|---|
| **Health bar** | 6px-high pill track, segments ok / warn / bad / unknown proportional to counts; label + exact count beside it. Used for CRM data quality. |
| **Workflow node** | 10px radius card, 3px left edge = state (blue running/selected, yellow auto-generated, grey not verified, green verified), icon + name + one meta line. Hexagon only for dataset/model glyphs inside the card. |
| **Transform step** | Row card: drag handle, icon, step name, small yellow "Auto" pill when generated, "⋮" menu. Steps stack with 8px gap; "+ Add step" dashed row at the end. |
| **Columns grid** | Compact table: column name, inferred type tag, mini distribution sparkline, quality bar, semantic tag chip. Sticky header, 36px rows. |
| **Analysis drawer** | Right-hand glass drawer, 16px left radius, icon rail on the far edge. |

## 5. Layout contract (all screens)

```
┌ top bar (glass, 56px): logo · workspace · search … theme · user ┐
├ left nav 220px ┬ main content (max 1280px) ┬ assistant drawer ─┤
│ icon + label   │ page header + tabs        │ AI chat, collapsible│
└────────────────┴───────────────────────────┴─────────────────────┘
```

- Left tab: navigation. Right tab: AI assistant drawer, collapsed by default, remembers its state.
- Detail pages (deal, account, contact): header with stage roadmap, then tabs, then a 3-column
  summary (facts · timeline/documents · insights).
- Dialogs: one scroll area only (the body); header and footer stay fixed.

## 6. How an AI builder must use this

1. Import `tokens.css`; use `var(--token)` only. No raw hex in components.
2. Reuse the component classes in `styles.css` before inventing new ones.
3. Every new component ships in light and dark; check both before finishing.
4. If something needed is not in this file, propose the addition here first.
5. Never present unverified or AI-generated content with the same styling as verified data.

## 7. Legacy names

The duplicate `.swatch` class is resolved: the meetings key is `.mark-swatch` (this file's `--mark-*`
tokens); the flows `.swatch` stays in `flows.css`.


`--accent` is kept as an alias of `--primary` (it always meant blue in DataForce). Yellow is
`--highlight`. `--bg/--panel/--text/--muted/--line` alias `--canvas/--surface/--ink/--ink-soft/--hairline`.
New code uses the new names only.
