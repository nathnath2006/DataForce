# DataForce

An analysis workspace for sales and marketing teams. It is a minimal CRM (accounts, contacts with
"reports to", deals, append-only notes and comments) where teams analyse their data in place.
Every number is computed in code with a confidence interval; anything without enough evidence is
shown as **not verified**. The LLM never calculates: it only names or explains facts that code
computed.

The demo data is **synthetic, generated with a known ground truth, and announced as such**.

Design and build contract: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (M1) and
[`docs/UI-CONTRACT.md`](docs/UI-CONTRACT.md) (M1b: local UI, TamTam connect) and
[`docs/M2A-CONTRACT.md`](docs/M2A-CONTRACT.md) (M2a: flows, Company 360, AI assistant) and
[`docs/M2B-CONTRACT.md`](docs/M2B-CONTRACT.md) (M2b: titles, org-chart proposals, meetings). Decisions:
[`docs/DECISIONS.md`](docs/DECISIONS.md). What was built and why, for non-developers:
[`docs/DataForce-build-report.pdf`](docs/DataForce-build-report.pdf).

## Use it in the browser (M1b)

Requirements: Docker, Python 3.13, Node 20+. From the repository root, the first time:

```bash
make db-up                                     # Postgres on 127.0.0.1:5433
cd backend && python3.13 -m venv .venv \
  && .venv/bin/pip install --require-hashes -r requirements-dev.lock \
  && .venv/bin/pip install --no-deps -e . && cd ..
make migrate                                   # create / upgrade the schema
make testdata                                  # the synthetic "Test data" workspace
```

Then, every time: `make ui` and open **http://127.0.0.1:8800** (use exactly this address: the
TamTam sign-in comes back to it). `make ui` creates the secret key in `backend/.env` the first time,
builds the frontend when it changed, and starts the app on loopback only. There is no login before
M3: anyone who can run programs on this computer can use it, nobody else can.

- **Test data (synthetic)** holds generated companies, people, deals, notes and 160 meetings,
  with a known answer key. Enrichment there always uses a fake provider and never spends credits.
  `make testdata` reloads it from scratch (your own workspaces are never touched).
- **Connect TamTam**: create a real workspace (workspace menu, *+ New workspace…*), open
  *Settings*, click *Connect TamTam* and sign in on TamTam's page. DataForce registers itself with
  TamTam, keeps the token encrypted in the database and never shows it. *Check connection* lists
  the tools TamTam offers; *Disconnect* deletes the token.
- **Paid lookups** happen only when you click *Enrich* on a contact of a real workspace and
  confirm the credit amount. Found emails / mobiles are stored encrypted, each with a *Delete*.
- **Companies** (M2a): type a name to see whether you already dealt with a company. A company
  groups its accounts and shows its address, contacts, deals and activity. *Search the public
  registry* looks the name up in the free French company register (api.gouv.fr) only when you
  click, and *Add to CRM* creates it.
- **Analysis** (M2a): drag blocks onto a canvas, wire them, and press *Run all*. Datasets come from
  the CRM, an uploaded CSV / Excel file or a read-only PostgreSQL connection (*Settings > Data
  connections*). Blocks include filter, sort, columns, group, join, **pivot**, stats test, chart,
  train/test split, regression and clustering. Comparisons and models are labelled *verified* or
  *not verified*, exactly like the M1 engine.
- **AI model** (M2a): in *Settings > AI model*, pick Gemini or Anthropic and paste your API key.
  It is stored encrypted and never shown again. The *Ask* panel on an account or company answers
  from that record's data, cites it, and flags any number it could not find in the data.
- **Job titles** (M2b): *Contacts > Normalize titles* maps every title to a function and a
  seniority with a French / English dictionary; unknown titles can go to your AI model (title text
  only, cached, flagged). *Review titles* lists what needs a look; your corrections always win.
- **Org chart suggestions** (M2b): on an account, *Suggest links* proposes managers from the job
  titles (same account, next level up) and from what people said in meetings ("I report to…",
  "c'est X qui signe"), each with its evidence. Nothing becomes a fact until you *Accept* it.
  - The meeting patterns are exact but miss most other wordings (`docs/DECISIONS.md` §J).
  - *Settings > AI model > Read meeting sentences for org statements* is off by default. When
    on, it also sends the sentences that name a contact, or say something like "my boss…",
    plus the account's contact names, to your model. Full transcripts are never sent.
  - Code keeps an AI finding only if its quote is word for word in the transcript and the
    names are contacts of the account. The suggestion is tagged *found by AI*.
- **Meetings** (M2b): upload transcripts (PDF, Markdown or text) on an account, optionally tied
  to a deal. *Meetings > Find themes* tags known sales themes (price, competitor, security,
  integration, timing, legal, onboarding, support) by keywords, with exact quotes, then looks for
  other recurring topics. All of it runs locally. *Test against win rate* opens a flow that
  compares deals whose meetings mention a theme with the others: a screening test, not proof.
- **Connect an AI assistant** (M3a): Claude Desktop, Claude Code or another MCP client on this
  computer can query one workspace and get exact results.
  - It gets counts from SQL, comparisons from the stats engine with their *verified* / *not
    verified* labels, saved flows, meetings and themes.
  - *Settings > AI assistants (MCP)* shows the snippet to paste. You can also print it with
    `backend/.venv/bin/dataforce mcp config --workspace test-data --client claude-desktop`
    (or `--client claude-code`).
  - The assistant starts `dataforce mcp --workspace SLUG` itself, over stdio: there is no
    network port. Access is read-only and limited to that workspace.
  - Customer text is marked as untrusted. Emails, phones and keys are never returned.
  - Each call is logged under *Recent calls*.
- **Theme**: the *Theme* button in the header cycles System / Light / Dark.
- `make ui-dev` runs the same app with the Vite dev server (hot reload) on 127.0.0.1:5173.

## Quickstart

Requirements: Docker, Python 3.12+.

```bash
# 1. Database: Postgres 16 + pgvector on 127.0.0.1:5433 (dev credentials: dataforce / dataforce)
docker compose up -d --wait db          # or: make db-up

# 2. Python environment
cd backend
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements-dev.lock
.venv/bin/pip install --no-deps -e .
# runtime only: pip install --require-hashes -r requirements.lock && pip install --no-deps -e .

# 3. Configuration (optional: defaults match docker-compose.yml)
cp .env.example .env && chmod 600 .env

# 4. Schema
.venv/bin/dataforce db upgrade          # or: make migrate
```

## Tests

```bash
make test               # unit tests, no database or network
make db-up && make test-integration   # tests that need Postgres (database dataforce_test)
make lint               # ruff
make lock               # regenerate the hashed locks (UPGRADE=1 to bump)
```

Integration tests are skipped, with a message, when the test database is unreachable. If you
change `backend/app/db/models.py`, update the migrations: `tests/db/test_migrations.py` fails on
any drift (then `make db-reset-test`).

## Layout

| Path | What |
|---|---|
| `docker-compose.yml`, `docker/postgres/init/` | local database (+ `dataforce_test`, `vector` extension) |
| `backend/app/` | domain contracts, DB models, services, stats engine, demo generator, LLM, CLI |
| `backend/app/api/` | local HTTP API (FastAPI) + request guards + SPA hosting |
| `backend/app/connectors/` | TamTam OAuth over MCP (discovery, registration, PKCE, sealed tokens) |
| `backend/app/flows/` | analysis flow engine, blocks, data sources (CRM, files, PostgreSQL) |
| `backend/app/registry/`, `backend/app/assistant/` | public company registry client; AI Ask assistant |
| `backend/app/titles/`, `backend/app/orgchart/` | title normalisation; org-chart rules and meeting statements |
| `backend/app/transcripts/`, `backend/app/themes/` | transcript import and parsing; known themes and topic discovery |
| `backend/alembic/` | migrations (`0001_initial` ... `0006_m2b`) |
| `frontend/` | React UI (Vite + TypeScript), built into `frontend/dist` by `make ui` |
| `docs/` | architecture, decisions, security reports |

## Changing the database password

The Postgres image applies `POSTGRES_PASSWORD` only when the data volume is first created. On an
existing volume run `ALTER ROLE dataforce PASSWORD '...'` inside the container, or recreate the
volume (`docker compose down -v`, destroys the data), then update `DATABASE_URL` in `backend/.env`.

## Run Milestone 1

Everything below uses **synthetic data**: generated by code with a known answer key (some effects planted
on purpose, some groups deliberately too small, one variant that is pure noise). No real customer or person.

Prerequisites: Docker, Python 3.13.

```bash
make db-up                                   # Postgres + pgvector on 127.0.0.1:5433
cd backend
python3.13 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements-dev.lock
.venv/bin/pip install --no-deps -e .
.venv/bin/dataforce db upgrade               # create the schema
```

Generate, load and check the demo data (workspace `demo-<variant>-<seed>`; the answer key is written to
`data/demo/ground_truth_<variant>_<seed>.json`, which is gitignored):

```bash
.venv/bin/dataforce demo generate --variant planted --seed 42 --replace
.venv/bin/dataforce demo generate --variant noise   --seed 1  --replace
.venv/bin/dataforce demo check --variant planted --seed 42   # exit code 1 if the engine fails
.venv/bin/dataforce demo check --variant noise   --seed 1    # nothing may be verified
```

The noise demo uses seed 1. At 350 deals, about 1 noise dataset in 25 shows one chance finding that
passes every gate (the 5% false discovery rate doing what it promises, see `docs/DECISIONS.md`
section E): noise seed 42 is such a dataset, and its check fails on purpose, naming the false
positive (owner x cycle days).

Look at the numbers (every read command accepts `--json`). "Not verified" means the evidence is too thin
to call it a finding (too few deals, interval too wide, or not significant after correcting for many
comparisons); it is listed with its reasons:

```bash
.venv/bin/dataforce stats pipeline --workspace demo-planted-42
.venv/bin/dataforce stats scan     --workspace demo-planted-42
.venv/bin/dataforce crm accounts   --workspace demo-planted-42
.venv/bin/dataforce crm org-chart  --workspace demo-planted-42 --account "Alderon Labs"
# notes are append-only: correct and delete keep the history
.venv/bin/dataforce crm notes add     --workspace demo-planted-42 --contact <contact-uuid> --body "text"
.venv/bin/dataforce crm notes correct --workspace demo-planted-42 --note <note-uuid> --body "new text"
.venv/bin/dataforce crm notes delete  --workspace demo-planted-42 --note <note-uuid>
.venv/bin/dataforce crm notes history --workspace demo-planted-42 --note <note-uuid>
```

The walkthrough notebook is `notebooks/M1_engine_demo.ipynb` (saved with its outputs, so it can be read
on GitHub without running anything). To run it, first install the notebook extras
(`.venv/bin/pip install --require-hashes -r requirements-notebook.lock && .venv/bin/pip install --no-deps -e .`). Then open it with `make notebook` (JupyterLab), or re-run it
from the command line:

```bash
cd backend && .venv/bin/jupyter nbconvert --to notebook --execute --inplace ../notebooks/M1_engine_demo.ipynb
```

Run the tests with `make test` (unit tests) and `make db-up && make test-integration` (database and
end-to-end CLI tests, which only touch `dataforce_test`).
