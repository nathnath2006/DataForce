# M5 contract: login, roles and the UI rework

Decided with the PO on 2026-10-19. This brings forward the login part of M3b, without hosting.
The audit's must-dos for identity (SYS-01, SYS-10) apply here.

## PO decisions

1. **First launch.** A setup screen creates the admin: email, display name and password. After
   that, everyone signs in with email and password.
2. **Accounts.** One account per person (email), joined to one or more workspaces with a role in
   each. The admin sees every workspace and can switch between them.
3. **Roles.**
   - By default, a **rep** sees only their own data, and their statistics cover only their own
     data.
   - The admin can grant a rep, per workspace:
     - **see all**: the rep sees everyone's data in that workspace;
     - **delete own**: the rep may delete records they own.
   - Only the admin deletes anything by default.
4. **Empty passwords** are allowed only for members of *demo* workspaces (such as Test data), and
   only while the app runs on this computer (loopback). Real workspaces need a password of at
   least 10 characters.
5. **Design.**
   - Framer's simplicity: white surfaces, a soft grey canvas, compact controls, one accent.
   - OAC DV's visual analysis: data, grammar and canvas.
   - Dynamics 365's clear organisation: grouped left navigation; record pages with a command bar,
     key-field header, stage process bar, tabs, and fields beside the timeline.

## What "own data" means (tech-lead defaults; the PO can change them)

| Record | A rep owns or sees it when… |
|---|---|
| Deal | its `owner_id` is the rep's CRM identity |
| Account | its new `owner_id` is the rep, **or** the rep owns at least one deal on it |
| Contact, note, comment, activity, task, meeting document, theme assignment, org proposal | it belongs to a visible account (or visible deal) |
| Company | it groups at least one visible account; its page lists only visible accounts |
| Record with no owner | visible to the admin and to *see all* members only |
| Record a rep creates | owned by that rep: the server sets the deal or account owner |

- **Authors are set by the server.** The author of notes, comments, activities, stage moves,
  tasks, flows, workbooks and saved models is the signed-in member's CRM identity. Request bodies
  can no longer set `author_id`, `changed_by_id` or `owner_id` for someone else; only an admin can
  reassign an owner.
- **Analytics use the viewer's rows.** The following are computed over the rows the viewer may
  see:
  - CRM sources in flows and workbooks, and *Score now*;
  - the stats scan, data quality and Explain;
  - the assistant's context and GenAI;
  - org chart, meetings and themes.

  Flow, workbook and saved-model *definitions* are shared in the workspace; their data is
  filtered at run time.
- **Admin only:**
  - Settings: AI key, TamTam, mailbox OAuth clients, data connections;
  - uploaded files and PostgreSQL connections (they bypass row visibility);
  - the Admin page and user management;
  - workspace creation and deletion;
  - GDPR erasure, the demo backfills, and mailbox connect (per-user mailboxes come later).
- **Deleting:** the admin can always delete; a rep can delete only with *delete own*, and only
  their own records.
- **MCP server** (stdio, local process): acts as the admin of its workspace. Whoever runs
  programs on this computer already has the database.

## Data model (migration `0011_auth`)

| Table | Columns |
|---|---|
| `user_account` | id, email (unique, lowercase), display_name, password_hash (null = empty password), is_admin (superadmin), disabled, created_at, last_login_at |
| `membership` | user_account_id (cascade), workspace_id (cascade), app_user_id (the CRM identity in that workspace; unique per workspace, set null), role (`admin` / `rep`), see_all, delete_own, created_at; unique (user_account, workspace) |
| `user_session` | id, user_account_id (cascade), token_hash (sha256, unique), created_at, last_seen_at, expires_at, user_agent (≤ 200) |
| `account.owner_id` | new nullable FK to `app_user` (set null), backfilled from the owner of the account's most recent deal |

## Security rules

- **Passwords:** `hashlib.scrypt` (N=2^15, r=8, p=1, 16-byte salt), in a versioned format
  `scrypt$15$8$1$<salt>$<hash>`, with constant-time comparison. No new dependency.
- **Sessions:**
  - a 32-byte random token in the cookie `df_session`: HttpOnly, SameSite=Lax, Path=/, and
    Secure when not on loopback;
  - only its SHA-256 is stored;
  - 14 days of sliding life, 30 days at most;
  - logout deletes the session.
- **Every `/api` route needs a session**, except:
  - `GET /api/health`;
  - `GET /api/auth/status`, which says only whether setup is needed and whether a session
    exists;
  - `POST /api/auth/setup`, only while no admin exists;
  - `POST /api/auth/login`;
  - the OAuth callbacks, whose state is bound to the member who started them.
- **Workspace access:** a non-member gets 404 on a workspace route (no enumeration). The admin
  sees all. A rep gets 403 on an admin-only action.
- **Login:**
  - at most 10 failures per email per 15 minutes, and 50 per client per 15 minutes;
  - the same error for an unknown email and a wrong password;
  - timing evened out with a dummy hash.
- The existing Origin and `X-DataForce` guard stays. A 401 sends the frontend to `/login`.
- **MCP server and CLI:** not affected (local). The CLI gains `dataforce users …` to list, create,
  reset and disable users.

## Test data

- `dataforce demo backfill-logins --workspace test-data` creates one user per CRM user:
  - the email is the CRM user's synthetic email;
  - the password is empty;
  - the role is rep;
  - *see all* and *delete own* are off.
- The command refuses non-demo workspaces and never touches the PO's admin account.
- Setup gives the admin an admin membership in every existing workspace. The admin can also act
  as a CRM identity, chosen in the user menu.

## The new UI

- **Navigation (Dynamics-style groups).** The Admin group shows only to the admin.

  | Group | Pages |
  |---|---|
  | My work | Home, Tasks, Activities |
  | Customers | Companies, Accounts, Contacts |
  | Sales | Deals, Meetings |
  | Analysis | Flows, Workbooks, Models, Insights |
  | Admin | People and access, Settings, Admin |

- **Top bar:** workspace switcher, global search, AI drawer, user menu (name, role, workspace,
  CRM identity for the admin, sign out). *Acting as* goes away.
- **Record page template (Dynamics-style):**
  - a command bar (Save, New, Close as won / lost, Delete when allowed);
  - a header with 3 to 5 key fields;
  - the stage process bar;
  - tabs: Summary, Timeline, Related, Meetings and emails;
  - Summary is two columns: fields on the left, the timeline and AI on the right.
- **Design tokens (Framer simplicity):**
  - white surfaces on a soft grey canvas;
  - 32 px controls;
  - 8 px radius for controls, 12 px for cards;
  - subtle shadows;
  - one blue accent, with yellow kept for AI;
  - Helvetica.

## Phases

1. **Wave 1, in parallel, on disjoint files.**
   - **L1, auth core.** Tables, hashing, sessions, setup / login / logout / me, the real
     `CurrentViewer`, workspace membership, login rate limit, admin user-management API, CLI and
     backfill. Frontend: `src/auth/**` (login, setup, auth context, user menu) and an Admin page
     section *People and access*.
   - **L2, visibility and authors.**
     - `app/auth/visibility.py` filters for every service, CRM loader, stats, quality, assistant,
       GenAI, org chart and themes route;
     - authors and owners set by the server;
     - admin-only and delete checks;
     - `account.owner_id`;
     - frontend forms stop sending author ids.
   - **U1, design and shell.**
     - tokens refresh, the new shell (navigation groups, top bar);
     - the `RecordPage` template and a presentational `DataTable`;
     - the deal page rebuilt on the template.
2. **Wave 2.**
   - Server paging and windowed tables, a cached data layer, generated API types (audit
     PERF-F-02/03/04/05/07, SYS-13).
   - Account, contact and company record pages, with a clickable visual org chart.
   - Data quality per rep, plus cleanup blocks (standardise, regex extract and replace).
   - Restyled login and setup pages.
3. **Wave 3.**
   - Security review: sessions, CSRF, enumeration, rate limits, and cross-rep leaks through
     every route, including analytics and exports.
   - Browser check (light, dark, phone); docs and build report.

## Definition of done

- ruff, the full pytest suite, tsc, vitest and build are green.
- A test signs in as two reps and proves that neither sees the other's deals, accounts, notes,
  stats, flow rows or assistant context.
- A test proves that a rep cannot delete without *delete own*, nor another rep's record with it.
- Light and dark mode checked in the browser.

## Wave 3: the PO's UI feedback (2026-10-20)

PO's words, condensed:
- **Links:** "the default blue hyperlink is a mess". Use action buttons and quiet hover highlights instead, such as a grey bento box at low alpha. React Bits is the inspiration.
- **Analysis:** the palette blocks need icons and two columns, and the whole Analysis section should follow a bento style.
- **Docs:** warnings are good, but each block, method and warning needs detailed documentation, in a Docs section.
- **Org chart:** inspired by `react-organizational-chart`: a centred tree with rounded connector lines (MIT; ideas only, no dependency).
- **Summary:** styled like React Bits Pro *Analytics 1* (a bento of KPI cards with deltas and sparklines, plus charts), reusing the sign-in dot-sea background.
- **Notes:** like Apple Notes, with no click-to-open friction. A list beside an inline editor, with smart preloading.
- **Meetings:** a real calendar like React Bits Pro *Scheduling 6*, with the upcoming events listed underneath.
- **Mailbox:** reps connect their own mailbox; the admin only registers the OAuth clients once.
- **Settings for everyone:** change password, theme and display basics.
- **Admin settings:** the admin controls caps and limits from the UI, not from `.env`.
- **Assistant:** the chat UI is reworked.

### Decisions (tech lead)

- **Links.** Plain text links disappear from the app chrome:
  - navigation uses rows with a hover highlight;
  - record names in tables are the row's own hover target (the whole row is clickable);
  - in-text links keep the ink colour with an underline on hover;
  - actions are buttons (primary, quiet and ghost), with icons where helpful.
- **Mailbox per user.** `mailbox_connection` gains `user_account_id` (migration `0012`).
  - Each member connects their own mailbox.
  - The candidate emails of a mailbox are private to its owner. Once an email is linked to a deal, it becomes a normal CRM activity that follows the visibility rules.
  - The OAuth client registration stays with the admin, done once in workspace Settings.
- **Admin-editable limits.**
  - A `setting_override` table (global, plus optional per workspace) holds values for an allow-list of limits, each with bounds: AI daily caps, assistant rate, GenAI caps, mailbox sync caps, flow row and time caps, and similar.
  - The effective value is the override if set, otherwise `.env`. Every service reads limits through one helper.
  - Changes are audited (who, when, old → new).
- **Personal settings** (`/w/:ws/me`, every member):
  - change password (current + new; ends other sessions);
  - theme (system, light or dark) and density (comfortable or compact), stored per user;
  - my mailbox (connect, sync, disconnect).
- **Documentation** (`/w/:ws/docs`, `/docs/:topic`): one page per block, method and warning. Each page covers:
  - what it does, its inputs and outputs, and its config fields;
  - how *verified* is decided, its caps and warnings with their meaning, a worked example, and references.

  Every block form, result warning and verdict tag links to its topic.

### Owners

- **Wave 3A, in parallel:**
  - **V1, visual system:** links, buttons, hovers, bento cards; the Analysis section in bento style; palette icons in two columns.
  - **V4, settings:** personal settings, per-user mailbox, admin-editable limits.
  - **V5, assistant:** the chat drawer redesign.
- **Wave 3B, in parallel:**
  - **V2:** Summary and Home in the analytics style with the dot-sea background, and the org chart tree.
  - **V3:** Apple Notes-style notes, and the meetings calendar with upcoming events.
  - **V6:** in-app documentation.
