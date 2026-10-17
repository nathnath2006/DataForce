# DataForce: architecture and Milestone 1 build contract

DataForce is an analysis workspace for sales and marketing teams. It's a minimal CRM (accounts,
contacts, deals, notes, comments) where teams analyse their data in place instead of exporting it.
Analyses are computed in code and come with confidence intervals. Anything without enough
evidence is shown as **"not verified"**. The LLM never calculates: it only names, classifies or
explains facts that code computed, and cites them.

The project was renamed from `tamtam-lookalike` on 2026-10-17 after the pivot (see
`DECISIONS.md`). What was kept from v1: the infra, the hardened config and DB session, the
services pattern, the LLM layer (Gemini plus Anthropic as the swap, with the fakes), and the
TamTam MCP client (fake by default). The crawler, the SIRENE and Wikidata connectors, lookalike
scoring and the leave-one-out eval were deleted.

## 0. Contracts (written by the tech lead; do not change them without asking)

| Contract | File |
|---|---|
| Enums | `backend/app/domain/enums.py` |
| Data types (pydantic) | `backend/app/domain/schemas.py` |
| Ports (LLM, embeddings, enrichment) | `backend/app/domain/ports.py` |
| ORM tables | `backend/app/db/models.py` |
| Settings, including the stats gates | `backend/app/config.py` |
| Dependencies | `backend/pyproject.toml` |

If a contract is wrong or missing something, finish what you can and report the exact change you
need. Purely additive changes, such as a new optional field, are allowed if you say so in your
report.

## 1. Milestone 1 scope (week 1): engine plus data, no UI

1. A **synthetic data generator** with a known ground truth.
   - About 200 deals with planted effects.
   - Companies with complete org charts.
   - French and English titles.
   - Realistic noise and missing values.
   - A **pure-noise variant**, on which the engine must answer "not verified".
2. The **minimal CRM schema plus the services layer**: workspaces, users (the sales reps), accounts, contacts (title plus "reports to"), deals, append-only notes (on a contact) and comments (on an account), runs, and LLM usage.
3. A **stats engine** for deals with "not verified" gates:
   - win rate, cycle length and deal amount, overall and by dimension;
   - group-vs-rest comparisons with confidence intervals, a test, and Benjamini-Hochberg FDR across a scan.
4. A **notebook** (`notebooks/M1_engine_demo.ipynb`, executed with outputs) that loads the planted and noise datasets, runs the engine and checks it against the ground truth. There is no UI.

Out of M1:
- M2: title normalisation, org-chart rules, transcript import and theme analysis, and the pgvector RAG over free text.
- M3: the React UI, the MCP server and API, the live TamTam connector, auth, and the hosted demo.

## 2. Layout and ownership

```
DataForce/
  docker-compose.yml, docker/, Makefile, .gitignore, README.md        [foundation]
  data/demo/                (generated ground-truth JSON, gitignored)  [integration]
  notebooks/M1_engine_demo.ipynb                                       [integration]
  docs/                                                                [tech lead / docs]
  backend/
    pyproject.toml, app/config.py, app/domain/*, app/db/models.py      [tech lead]
    alembic/ (new 0001 + 0002), app/db/session.py                      [foundation]
    app/services/ (all CRUD, see 3.1) except analytics.py              [foundation]
    app/services/analytics.py                                          [stats]
    app/stats/                                                         [stats]
    app/demo/  (generator, models, loader, check)                      [generator]
    app/llm/, app/enrichment/                                          [llm]
    app/cli/   (foundation: skeleton + `db upgrade`; integration: the rest)
    tests/conftest.py, tests/db/, tests/services/                      [foundation]
    tests/stats/ [stats]  tests/demo/ [generator]  tests/llm/ tests/enrichment/ [llm]
    tests/cli/, tests/e2e/                                             [integration]
```

Rules for every builder:
- Only create or modify files you own. You may read everything.
- Python ≥ 3.12, typed, `ruff check` clean. Comments explain *why*. Keep modules small. Match the surrounding style.
- The venv is `backend/.venv`; don't recreate it. Run tests with `cd backend && .venv/bin/pytest tests/<area>`. If you add a dependency, append it to `pyproject.toml` and say so.
- No network in tests. Tests that need Postgres get `@pytest.mark.integration` and use `tests/conftest.py` fixtures (`db_session`, `session_factory`). DB: `docker compose up -d db` (127.0.0.1:5433; dev DB `dataforce`, test DB `dataforce_test`).
- Never log secrets or personal data (contact names, note bodies).
- Run no state-changing git commands.
- Determinism: anything random takes a seed (`numpy.random.default_rng(seed)`). Same seed means the same output.

## 3. Module specs

### 3.1 Foundation: DB, services, infra (`foundation`)
- **docker-compose.yml:**
  - Rename everything from tamtam to `dataforce`: container `dataforce-db`, volume `dataforce_pgdata`, user, password and DB `dataforce`.
  - Keep the pinned image digest and the `127.0.0.1:5433` binding.
  - The init script creates `dataforce_test` and `CREATE EXTENSION vector` in both DBs.
- **Alembic:** the old migrations are deleted. Write new ones that mirror `models.py` exactly.
  - `0001_initial`:
    - the `vector` extension;
    - all tables, indexes, checks and FKs;
    - the **append-only trigger** on `note` and `comment`.
  - The append-only trigger, as a `plpgsql` function used by both tables:
    - UPDATE is allowed only when the sole changes are:
      - setting `deleted_at` and `deleted_by_id` from NULL to a value, once;
      - `author_id` or `deleted_by_id` becoming NULL (the FK `SET NULL` when a user is deleted).
    - Any other UPDATE raises an exception (`body`, `contact_id`/`account_id`, `corrects_id`, `created_at`, `workspace_id` are immutable).
    - DELETE raises unless `current_setting('dataforce.erasure', true) = 'on'`. That's how GDPR erasure (and workspace deletion) cascades.
  - `0002_lockdown` reuses the v1 pattern (see `docs/security/SR3-db-config-supplychain.md`, SR3-01):
    - ENABLE ROW LEVEL SECURITY on every table, plus `alembic_version`, with no policy;
    - a DO block that REVOKEs everything from `anon` and `authenticated` if those roles exist (Supabase), and does nothing on local docker;
    - a test asserting every model table is covered.
- **`app/db/session.py`:** keep it. It has the hardened timeouts.
- **Services:** plain functions with `session` first. **No commit inside.** Use `flush()` when ids are needed. SQLAlchemy expressions only, never string-built SQL. Inputs come in through `app.domain.schemas` models. Scrub incoming text with `textclean.scrub_text`. Return ORM objects (callers convert with `*.model_validate(obj)`).

  `workspaces`:
  - `create_workspace(slug, name, *, is_demo=False)`
  - `get_workspace_by_slug`
  - `list_workspaces`
  - `delete_workspace(slug)`: runs `SET LOCAL dataforce.erasure = 'on'` and lets the cascade delete everything.

  `users`:
  - `create_user(ws_id, UserIn)`
  - `list_users(ws_id)`

  `accounts`:
  - `create_account(ws_id, AccountIn)`
  - `get_account`
  - `list_accounts(ws_id)`
  - `erase_account(ws_id, account_id)`: erasure flag, cascade.

  `contacts`:
  - `create_contact(ws_id, ContactIn)`: checks the account and `reports_to` are in the same workspace and account.
  - `set_reports_to(ws_id, contact_id, manager_id | None)`: refuses cycles and cross-account links.
  - `list_contacts(ws_id, account_id=None)`
  - `org_chart(ws_id, account_id) -> list[(contact, manager_id)]`
  - `erase_contact(ws_id, contact_id)`: the "1-click delete". Erasure flag; the cascade deletes the contact's notes.

  `deals`:
  - `create_deal(ws_id, DealIn)`: same-workspace checks; a closed stage without `closed_on` is accepted, because real data is like that.
  - `list_deals(ws_id)`
  - `set_stage(ws_id, deal_id, stage, closed_on=None)`

  `notes`, on contacts:
  - `add_note(ws_id, contact_id, author_id, body)`
  - `correct_note(ws_id, note_id, author_id, new_body)`: inserts a new row with `corrects_id`.
  - `delete_note(ws_id, note_id, by_id)`: soft delete.
  - `current_notes(ws_id, contact_id)`: the latest version of each chain, not deleted.
  - `note_history(ws_id, note_id)`: the whole chain, oldest first.

  `comments`: the same API on accounts.

  `runs`:
  - `start_run(kind, ws_id=None, params={})`
  - `finish_run(run, status, result=None, error=None)`
  - `list_runs`

  `llm_usage`: keep `DbUsageRecorder` (point it at `Run`).

  `admin`: `db_size(quota_mb)`, adapted from v1, with per-table sizes.

  Also keep `errors.py`, `textclean.py`, `validation.py`, `safe_yaml.py` and `schema.py` (alembic helpers).
- **CLI skeleton:** `app/cli/__init__.py` exposes the Typer `app` (entry point `dataforce`) with sub-apps `db`, `demo`, `stats`, `crm`. Implement only `dataforce db upgrade`. Keep `_common.py`'s DB-error handler.
- **Tests:**
  - `tests/conftest.py`: keep the guard that the test DB name must end in `_test` and differ from the dev DB, adapted to `dataforce_test`.
  - Integration tests for every service, including:
    - the append-only trigger (UPDATE body, DELETE without the flag, and a second soft delete all raise; the soft delete and user deletion work);
    - erasure;
    - org-chart cycle refusal;
    - cross-workspace refusal;
    - the migrations no-diff check (`compare_metadata`), and RLS coverage.
  - Keep and update the kept `tests/db/*` (they still mention tamtam names).
- **Root files:**
  - `.gitignore`: keep v1's, add `data/demo/*.json`.
  - `backend/.env.example`: every Settings field, secrets commented out.
  - `Makefile`: `db-up`, `db-down`, `migrate`, `test`, `test-integration`, `lint`, `lock`, `notebook`.
  - Hashed locks via pip-compile: `requirements.lock` (runtime), `requirements-dev.lock`, `requirements-notebook.lock`.
  - `README.md`: what DataForce is, quickstart, and "synthetic demo data, announced as such".

### 3.2 Generator: synthetic data (`generator`) in `app/demo/`
- `models.py`: generator-side records with **local keys** instead of UUIDs: `DemoUser(key, ...UserIn)`, `DemoAccount(key, ...AccountIn)`, `DemoContact(key, account_key, full_name, title, reports_to_key)`, `DemoDeal(key, account_key, owner_key, ...DealIn fields)`, `DemoNote(key, contact_key, author_key, body, corrects_key=None)`, `DemoComment(...)`. `DemoDataset(users, accounts, contacts, deals, notes, comments, ground_truth: GroundTruth)`.
- `generator.py`: `generate(variant: Literal["planted","noise"], seed: int, n_deals: int = 200) -> DemoDataset`. It's **pure**: no DB and no I/O. The same seed gives identical output.
  - **Scale:** 6 reps; about 70 accounts; 4 to 9 contacts per account forming a **complete org chart** (CEO/DG → VP or Director Sales / CMO / CFO-DAF / CTO → Head of Sales → AEs, SDRs, plus some marketing and ops); `n_deals` deals over the last 24 months, about 80% closed.
  - **Realism:**
    - Titles mix French and English with noise: case, abbreviations like "Dir. commercial" and "Resp. marketing", some typos, about 5% missing titles.
    - Industries: 8 categories. Regions: 6 to 8 French regions. Segments are derived from employee count.
    - Amounts are log-normal with a few outliers.
    - Missing `lead_source` about 8%, missing `amount_eur` about 5%, closed deals missing `closed_on` about 3%, accounts missing industry or region about 5%.
    - About 40 notes and 20 comments in FR or EN, a few of them corrected (`corrects_key`).
    - Person names are invented (an FR + EN first/last name list). They must never be real people.
  - **Planted effects** (variant `planted`), sized to be detectable at about 170 closed deals with the default gates. Check this in tests.
    1. `lead_source` → `win_rate`. Inbound about 45%, outbound about 15%; the base is about 30%. Lead-source mix: inbound 35%, outbound 40%, referral 15%, partner 5%, event 5%.
    2. `segment` → `cycle_days`. Enterprise median about 110 days, midmarket about 60, SMB about 30. Segment mix: SMB 40%, midmarket 35%, enterprise 25%.
    3. `segment` → `deal_amount`. Enterprise median about €60k, SMB about €8k.
    4. A **small group**: `referral` is planted with a high win rate (about 70%) but has fewer than 30 closed deals. It must come out "not verified". List it in `ground_truth.small_groups`.
  - **Null dimensions** (no effect on any metric): `industry`, `region`, `owner`. List them in `ground_truth.null_dimensions`.
  - **Variant `noise`:** the same structure and marginal distributions, but **every metric is independent of every dimension**. Win/loss is Bernoulli(0.30) for all deals, and cycle and amount come from one distribution for all. `planted = []` and every dimension is null.
- `loader.py`: `load_dataset(session, dataset, *, workspace_slug, replace=False) -> dict` (counts). It creates a demo workspace (`is_demo=True`) and inserts everything through the **foundation services**: users, accounts, contacts in two passes for `reports_to`, deals, notes (corrections via `correct_note`) and comments. `replace=True` first calls `delete_workspace`. Records carry `source=demo`.
- `check.py`: `check_against_truth(report: ScanReport, truth: GroundTruth) -> CheckResult`, which is pure. CheckResult is a pydantic model with `found`, `missed`, `small_groups_ok`, `false_positives` and `passed: bool`. The rules:
  - Every planted effect must have a **verified** finding with the same dimension, group, metric and direction. Planting "inbound high" also implies "outbound low" is acceptable; don't count it as a false positive.
  - Every small group must have **no** verified finding.
  - Every null dimension must have **no** verified finding.
  - For `noise`, zero verified findings.
- **Tests:**
  - determinism;
  - realised proportions close to the targets;
  - org charts are trees (single root, no cycles) inside each account;
  - FR and EN title mix and missing-value rates;
  - the noise variant has no dependence (e.g. a chi-square p > 0.01 on the generator's own data for a fixed seed);
  - the loader (integration) with exact counts;
  - `check.py` on hand-built reports.

### 3.3 Stats engine (`stats`) in `app/stats/` + `app/services/analytics.py`
All the maths lives in pure functions (numpy + scipy) over plain rows, testable without a DB.
- `rows.py`:
  - `DealRow`, a frozen dataclass: `id`, `won: bool | None` (None if open), `stage`, `lead_source`, `segment`, `industry`, `region`, `owner`, `amount: float | None`, `created_on`, `closed_on`.
  - Derived values: `cycle_days` (closed deals with both dates) and `amount_band` (`<10k`, `10-50k`, `50k+`, or None).
  - `value_of(row, Dimension)`.
- `intervals.py`:
  - `wilson(k, n, conf)`;
  - `newcombe_diff(k1, n1, k2, n2, conf)`, Newcombe's hybrid score interval for p1 − p2;
  - `bootstrap_median(values, conf, resamples, rng)`;
  - `bootstrap_median_diff(a, b, conf, resamples, rng)`, percentile method.
  - Each returns `(estimate, low, high)`.
- `significance.py`:
  - `fisher_2x2(k1, n1, k2, n2) -> p` (two-sided);
  - `mann_whitney(a, b) -> p` (two-sided);
  - `benjamini_hochberg(pvalues) -> qvalues` (monotone, capped at 1, NaN-safe).
- `gates.py`, which uses `GateConfig`. Every failure adds a human-readable reason, e.g. "n = 18 < 30", "only 6 wins (< 10)", "CI ±21.4 pts > ±15".
  - `gate_rate(k, n, low, high, cfg)`: n ≥ min_n, wins ≥ min_wins, losses ≥ min_losses, half-width ≤ max pts.
  - `gate_median(n, est, low, high, cfg)`: n ≥ min_n, relative half-width ≤ max.
  - `gate_finding(...)`: both sides pass the n gates (and the win/loss gates for win rate), q < fdr_alpha, and the diff CI excludes 0.
- `engine.py`:
  - `overall(rows, cfg) -> dict[Metric, StatValue]`.
  - `group_stats(rows, dim, cfg) -> list[GroupStats]`.
  - `scan(rows, cfg, *, dimensions=all, workspace_id=None) -> ScanReport`:
    - **For every** dimension × group × metric (skipping `amount_band` × `deal_amount`, which is tautological), compare the group vs the rest of the rows with a value for that dimension.
    - Win rate: Fisher plus a Newcombe CI. Cycle and amount: Mann-Whitney plus a bootstrap median-diff CI.
    - Then BH across **all** p-values of the scan, then the finding gates.
    - Missing values: count them in `report.missing` and exclude them from that dimension. "(missing)" is never a group.
    - Use the seeded rng (`cfg.random_seed`), so the same input gives byte-identical JSON.
    - `notes` explain the gates and say that "not verified" ≠ "no effect".
  - `gate_config_from_settings(settings) -> GateConfig`.
- `services/analytics.py`:
  - `load_deal_rows(session, ws_id) -> list[DealRow]`: one SQL join of deal, account and owner.
  - `pipeline_summary(session, ws_id)`: **exact SQL aggregates**, no CI: counts and amount sums by stage, open/closed counts, won/lost counts.
  - `run_scan(session, ws_id, cfg=None) -> ScanReport`: records a `Run(kind=stats_scan)` whose `result` is the report JSON.
- **Tests:**
  - Wilson and Newcombe against published reference values (e.g. Newcombe 1998 examples);
  - BH against a hand-computed example;
  - bootstrap determinism;
  - gates at the boundaries (exactly 30, 29, 10 wins, …);
  - `scan` on synthetic numpy rows with a strong planted effect (found and verified) and under a global null over 50 seeds (the share of seeds with ≥ 1 verified finding should be ≤ about 10%);
  - missing-value handling;
  - an integration test of `analytics` on a small DB dataset.

### 3.4 LLM and TamTam connector clean-up (`llm`): `app/llm/`, `app/enrichment/`
The v1 profile extraction is gone from the product, so the LLM layer becomes generic again:
- Delete `profile_extraction.py` and `explain.py`. Move the reusable, security-hardened parts into generic modules for M2:
  - `app/llm/untrusted.py`: `sanitize_text`, plus wrapping untrusted text in `<source id="..."> … </source>` blocks, with the injection rules from v1.
  - `app/llm/quotes.py`: `verify_quotes(quotes, sources) -> list[VerifiedQuote]`, a deterministic verbatim check inside the named source. Carry over the SR2-02 hardening: whitespace collapsed rather than deleted, a minimum length, one quote backing at most 2 claims.
- `FakeLLM` becomes **generic**: a deterministic, schema-valid instance for any pydantic schema, plus an optional handler registry for specific schemas in M2. `FakeEmbedder` stays as it is.
- Update every `purpose` Literal to `title_classification | theme_naming | explanation` (plus `embedding` for usage records).
- Tests: rewrite the provider tests around a small local test schema instead of `ExtractedProfile`.
- Finish the pending SR2 hardening on what's kept. Check first: some of it may already be done (partial edits on 2026-10-16).
  - SR2-03: MCP tools from an allow-list only, refusing destructive or non-read-only annotations.
  - SR2-04: `allow_paid is True` strictly, a per-call credit ceiling (`enrichment_max_credits_per_call`), validated server credits.
  - SR2-10: no quadratic regex.
  - SR2-11: sanitized server text in errors.
  - SR2-12: pinned SDK base URLs.
  - SR2-15: `raise ... from None`.
  - SR2-16: idempotent `sanitize_text`.
  - Write `docs/security/FIXES-LLM.md`: finding → status → test.

### 3.5 Integration (after 3.1 to 3.4): CLI, notebook, end to end (`integration`)
- CLI `dataforce` with Rich tables and `--json` everywhere:
  - `db upgrade`;
  - `demo generate --variant planted|noise --seed N --n-deals 200 [--replace]`: workspace `demo-<variant>-<seed>`, writes `data/demo/ground_truth_<variant>_<seed>.json`;
  - `demo check --variant --seed`: runs the scan and `check_against_truth`, exits 1 on failure;
  - `stats scan --workspace SLUG [--json]`;
  - `stats pipeline --workspace SLUG`;
  - `crm accounts --workspace`;
  - `crm org-chart --workspace --account NAME`;
  - `crm notes add|correct|delete|history`, which demonstrates append-only.
- `notebooks/M1_engine_demo.ipynb`, saved **executed with outputs**, in this order:
  1. generate and load the planted and noise datasets;
  2. the pipeline summary (exact aggregates);
  3. overall stats with CIs;
  4. the scan table with verified versus not-verified findings and their reasons;
  5. plots (win rate by lead source with CI bars, cycle length by segment);
  6. the ground-truth check (all planted found, small group not verified, nulls clean);
  7. the noise variant, where everything comes out not verified;
  8. a multi-seed robustness cell (e.g. 20 seeds of each variant, summary table).

  The notebook says clearly that the data is synthetic.
- An e2e test (integration) that generates, loads, scans and checks for both variants with the default seed, and over 10 seeds for the noise false-positive rate.
- README "Run Milestone 1" section.

## 4. Security baseline
- Keep the v1 hardening:
  - config validators (TLS for remote DBs, no dev credentials outside dev, https endpoints);
  - DB timeouts;
  - text scrubbing at the persistence boundary;
  - `safe_yaml`;
  - the test-DB guard;
  - RLS lockdown;
  - hashed locks.
- Third-party personal data is kept to a strict minimum, and `erase_contact` / `erase_account` delete it with one call. Notes are append-only, except for that erasure.
- No string-built SQL. All writes are workspace-scoped: a service never touches a row from another workspace.
- Secrets live only in env (`SecretStr`) and are never logged. The LLM gets untrusted text only inside delimited blocks, and its output is schema-validated and never executed.
