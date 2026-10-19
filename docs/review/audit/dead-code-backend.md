# Dead code audit: backend (lens: unused code)

Method: AST script (`.../scratchpad/audit/defs.py`, `defs2.py`, `cfg.py`) listing every non-decorated def/class in `backend/app` with Name/Attribute/import/string-constant reference counts across app, tests, eval and alembic; each candidate re-checked with grep. Decorated callables (FastAPI routes, typer commands, validators, exception handlers) are registered by decorator, so they were excluded from the unreferenced list and routes were checked separately against `frontend/src`. No dynamic lookup (getattr on names, registries, dict dispatch) reaches any "certain" item: the names appear nowhere as strings or attributes. Read-only; no tests run.

## Certain: unreferenced anywhere (app, tests, eval, alembic, frontend)

| id | location | evidence | rec |
|---|---|---|---|
| DC-B-01 | `backend/app/services/safe_yaml.py:1-31` (whole module, 31 lines) | `load_yaml_limited` and `safe_yaml` appear only in the file itself and in docs/ARCHITECTURE.md ("keep"). No import in app/tests/eval. It is also the only `import yaml` in the backend (see DC-B-12). | delete (or wire into a real YAML entry point; docs say "keep" but nothing uses it) |
| DC-B-02 | `backend/app/services/validation.py:28-38` `require_http_url` (11 lines) | 0 references outside its def. `is_http_url` in the same file is used. | delete the function |
| DC-B-03 | `backend/app/api/schemas.py:44-59` `ErrorBody` + `ErrorResponse` (about 16 lines) | `ErrorResponse` appears only in a docstring and its def; `ErrorBody` only inside `ErrorResponse`. Not used as `responses=` in any route; the error handlers build the dict by hand. | delete both, or use as `responses=` for OpenAPI |
| DC-B-04 | `backend/app/domain/enums.py:124-132` `ConnectorProvider`, `ConnectorStatus` (about 10 lines) | Names only in the def and one comment in `db/models.py:307`. The DB stores plain strings (`"connected"`, `"tamtam"`). | delete, or use them where the strings are written |
| DC-B-05 | `backend/app/assistant/ratelimit.py:30-32` `reset()` (3 lines) | AST: 0 uses. Tests import only `check_and_count`. | delete |
| DC-B-06 | `backend/app/agent/_util.py:55` `iso` (2 lines) | 0 uses (the only grep hit for "iso" is a regex word in lexicon.py). | delete |

## Certain: test-only ("tested but unused")

The whole embedding stack is unreachable from the app: nothing calls `get_embedder`, and no app code calls `.embed(`. `pgvector` columns are "M2" per the comments in `db/models.py:43`.

| id | location | evidence | rec |
|---|---|---|---|
| DC-B-07 | `backend/app/llm/gemini.py:194-266` `l2_normalize`, `GeminiEmbedder` (about 73 lines); `backend/app/llm/fake.py:198-249` `_embed_tokens`, `_bucket`, `FakeEmbedder` (about 52 lines); `backend/app/domain/ports.py:73-80` `EmbeddingProvider`; `backend/app/llm/registry.py:36-50` `get_embedder` (15 lines) | Only `registry.get_embedder` references the embedder classes, and only tests call `get_embedder` (5 test refs). | keep only if M2 embeddings are imminent; otherwise delete (about 150 lines, plus `embedding_provider`, `embedding_dim`, `gemini_embedding_model` settings) |
| DC-B-08 | `backend/app/llm/registry.py:18-33` `get_llm` (16 lines) | App uses `get_chat_llm` (routes/ai.py, routes/titles.py). `get_llm` is called only from tests. With it, `Settings.llm_provider` and the `"fake"` provider choice are test-only. `FakeLLM` itself is used by tests (9 files) directly. | delete `get_llm` and `llm_provider`, or keep as test support |
| DC-B-09 | `backend/app/enrichment/registry.py:1-29` (29 lines) `get_enrichment_provider` | Called only from tests (7 refs). The route `api/routes/enrichment.py:81` builds `FakeEnrichmentProvider` directly and `connectors/tamtam.py` uses `tamtam_mcp` directly. `Settings.enrichment_provider` is read only here. | delete or merge |
| DC-B-10 | `services/admin.py:20 db_size` (15), `services/runs.py:93 list_runs` (11), `services/llm_usage.py:73 usage_summary` (21), `services/channels.py:98 delete_channels_for_contact` (9), `services/schema.py:33 head_revision` (2), `services/contacts.py:71 get_contact` (2), `services/deals.py:56 get_deal` (2) | Each has 0 app references and 1-3 test references. `admin.py` is 34 lines and wholly test-only. These are the services behind the unused setting `db_quota_mb` (DC-B-11). | delete with their tests, or expose via API/CLI/MCP |
| DC-B-10b | `app/flows/memory.py:14 MemoryLoader`, `app/db/session.py:86 dispose_engines`, `app/llm/fake.py:135 register_text`, `services/org_ai.py:37 reset_limits`, `services/titles.py:40 reset_ai_limits` | Test fixtures or reset hooks living in app code. | keep (test support), ideally move to tests |

## Settings nothing reads (app/config.py)

| id | location | evidence | rec |
|---|---|---|---|
| DC-B-11 | `config.py:210 db_quota_mb`, `:234 llm_max_calls_per_run`, `:251 demo_seed`, `:252 demo_n_deals` | No read in app/tests/eval (`llm_max_calls_per_run` only asserted as a default in tests/db/test_config.py:231). Documented as dead in docs/security/SR5-llm-stats-demo.md (SR5-13). Also listed in `.env.example`. certain for db_quota_mb, demo_seed, demo_n_deals, llm_max_calls_per_run. | delete or wire in (llm_max_calls_per_run was deferred to M2 on purpose; keep if M2 is planned) |

`test_database_url` is read only by tests (conftest): keep. `embedding_*`, `llm_provider`, `enrichment_provider`, `tamtam_mcp_token`: only read by test-only registries (DC-B-07..09).

## Dependencies (pyproject.toml)

| id | item | evidence | rec |
|---|---|---|---|
| DC-B-12 | `pyyaml>=6.0.1` and dev `types-PyYAML` | the only `import yaml` is in dead `safe_yaml.py` (DC-B-01) | delete with DC-B-01 (likely; certain once DC-B-01 goes) |
| DC-B-13 | `pgvector>=0.3.2` | 0 imports in app/tests/alembic. The DB extension is created by raw SQL (`alembic/versions/0001_initial.py:90`); no `Vector` column exists yet. | likely: remove until the M2 vector columns land |
| DC-B-14 | `python-multipart` | not imported directly, but FastAPI `UploadFile`/`Form` in `routes/data.py` require it at runtime | keep |
| DC-B-15 | notebook extras (jupyterlab etc.) | used by `notebooks/M1_engine_demo.ipynb` | keep |

All other listed dependencies have at least one import in app.

## DB columns / tables
All 25 tables have app references. Per-column scan (every `Mapped` attribute): all are read or written in app except:
- DC-B-16 `Run.finished_at` (`db/models.py`, `services/runs.py:77`): written, never read in app or frontend. Confidence: unsure (it may be read through a schema or a query not caught by the name search). Recommendation: keep, it is lifecycle metadata.

## Routes
Compared 90 `@router` paths with `frontend/src` (segment match) plus tests and CLI/MCP:
- DC-B-17 `GET /w/{ws}/titles/preview` (`api/routes/titles.py:68`, 14 lines, plus `PreviewOut` in `schemas_titles.py:51`): the frontend never calls it, and nothing in CLI/MCP does; the only user is `tests/api/test_titles.py:78,80`. Test-only. Confidence: certain. Recommendation: delete route and schema, or keep if the UI title editor is planned.
- `GET /connectors/tamtam/callback`: browser redirect target of the OAuth flow, not called by frontend code. Keep.
- All other routes are called by an `api.ts` helper.

## Duplicates
- DC-B-18 `new_client()` identical in `backend/app/connectors/oauth.py:49` and `backend/app/registry/client.py:50` (6 lines each). Merge (likely).
- DC-B-19 `_percentile` `backend/app/stats/intervals.py:63` and `interval` `backend/app/flows/blocks/_boot.py:24`: identical bodies. Merge (certain duplicate).
- DC-B-20 accent folding written 5 times: `orgchart/meetings.py:44 fold`, `llm/fake.py:40 fold`, `themes/glossary.py:55 fold`, `titles/normalize.py:19 _strip_accents`, `transcripts/names.py:20`. Merge into one helper (likely; the NFD-per-char and NFKD variants differ slightly, so check behavior first).
- DC-B-21 whitespace regex `\s+` compiled in `agent/_util.py:21`, `assistant/context.py:122`, `llm/quotes.py:40`, `titles/normalize.py:14`. Trivial; keep or merge.
- DC-B-22 reset helpers `services/titles.py:40 reset_ai_limits` vs `services/org_ai.py:37 reset_limits` (same 4-line body over different globals). Keep.

## Not findings (checked)
Undecorated-looking items such as `cli/_common.py:59 _group` are typer callbacks; `BlockType` (flows/schemas.py:241) is a Literal consumed by pydantic; `KINDS`, `PATTERN_IDS`, `DEFAULT_K`, `BY_ID` are used inside their modules or by tests (module-level constants with 1 occurrence: `orgchart/meeting_ai.py:35 KINDS`, `orgchart/meetings.py:443 PATTERN_IDS`, `themes/discover.py:24 DEFAULT_K` have no reference outside their def: likely dead, 1 line each, delete).
