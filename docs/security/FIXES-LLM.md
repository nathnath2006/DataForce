# Fix log: LLM and TamTam connector (M1 pivot)

Source review: `docs/security/SR2-llm-enrichment.md`. Profile extraction, scoring and the lookalike
services were removed in the pivot, so findings about them are moot. Tests live under
`backend/tests/`. Status: fixed (done in this milestone), already-fixed (done in the 2026-10-16
partial pass, verified and now covered by tests), moot, accepted.

| Finding | Status | Files | Tests |
|---|---|---|---|
| SR2-01 verified badge with no evidence | moot (feature removed) | n/a | n/a |
| SR2-02 quote proves existence, not support | fixed (carried into the generic verifier: whitespace collapsed, min 20 chars and 3 words, word-boundary match, one quote backs at most 2 claims; the residual "string exists is not support" is documented in the module) | `app/llm/quotes.py` | `tests/llm/test_untrusted_quotes.py` |
| SR2-03 tool selection could pick a mutating tool | already-fixed + fixed (allow-list only, no keyword fallback; keyword matches are suggestions in the error; tools annotated destructive or not `readOnlyHint=true` refused) | `app/enrichment/tamtam_mcp.py` | `tests/enrichment/test_hardening.py`, `test_tamtam_mcp.py::test_keyword_match_is_only_a_suggestion_never_called` |
| SR2-04 paid guard, no ceiling, trusted credits | fixed (`allow_paid is True`, per-tool cost estimate with unpriced tool = ceiling, refusal above `enrichment_max_credits_per_call` before any connection, server credits validated finite / >= 0 / <= ceiling else `anomalous` + notes; fake provider strict too) | `app/enrichment/tamtam_mcp.py`, `app/enrichment/fake.py` | `tests/enrichment/test_hardening.py`, `test_tamtam_mcp.py`, `test_fake_and_registry.py` |
| SR2-05 fakes overwrite real data | moot for this layer (feature removed; fake outputs are labelled `fake` and the registry logs a warning) | `app/llm/registry.py` | `tests/llm/test_registry.py` |
| SR2-06 personal data to LLM and stored quotes | moot (profile extraction removed; M2 callers must redact before `wrap_sources`) | n/a | n/a |
| SR2-07 fake provenance | moot for profiles; fake enrichment stays on the reserved `.example` TLD | `app/enrichment/fake.py` | `tests/enrichment/test_fake_and_registry.py` |
| SR2-08 company name and attributes outside the data block | fixed (ids restricted to a safe charset, deduplicated; bodies sanitized) | `app/llm/untrusted.py` | `tests/llm/test_untrusted_quotes.py` |
| SR2-09 no size limits on the LLM schema | moot (schema removed; M2 schemas must bound their fields; quotes capped at 300 chars) | `app/llm/quotes.py` | `tests/llm/test_untrusted_quotes.py` |
| SR2-10 quadratic regex, recursion after a paid call | fixed (bounded regexes, size cap before parsing, depth and node budget, any parse failure after the call returns an `anomalous` result with the assumed cost) | `app/enrichment/tamtam_mcp.py` | `tests/enrichment/test_hardening.py` |
| SR2-11 server text reflected in errors | fixed (control / ANSI stripped, contact values, token, person and company masked, tool names restricted, length capped) | `app/enrichment/tamtam_mcp.py` | `tests/enrichment/test_hardening.py` |
| SR2-12 key and token destinations not pinned | fixed (SDK base URLs passed explicitly, env overrides ignored; MCP URL must be https, http only for loopback in dev/test, no credentials in the URL; also enforced by `Settings`) | `app/llm/gemini.py`, `app/llm/anthropic_provider.py`, `app/enrichment/tamtam_mcp.py` | `tests/llm/test_hardening.py`, `tests/enrichment/test_hardening.py` |
| SR2-13 no LLM spend ceiling | accepted (retry limited to one, no retry on safety / truncation finish reasons; the per-run call cap `llm_max_calls_per_run` is applied by the M2 caller) | `app/llm/_structured.py` | `tests/llm/test_gemini.py`, `test_anthropic.py` |
| SR2-14 zero / NaN vectors | fixed (Gemini embedder rejects zero or non-finite norm; fake embedder never emits one) | `app/llm/gemini.py`, `app/llm/fake.py` | `tests/llm/test_hardening.py` |
| SR2-15 `raise ... from exc` keeps raw SDK messages | fixed (errors raised outside the handler, so nothing is chained; only class name and HTTP code are kept) | `app/llm/_structured.py`, `app/llm/gemini.py` | `tests/llm/test_gemini.py::test_sdk_error_is_wrapped_without_message_or_prompt` |
| SR2-16 `sanitize_text` not idempotent, homoglyphs | fixed (NFKC + drop control/format chars + tag neutralization repeated to a fixed point); Cyrillic look-alike letters accepted as residual (not a delimiter) | `app/llm/untrusted.py` | `tests/llm/test_untrusted_quotes.py` |
| SR2-17 free-text explain bullets | moot (explain removed; M2 explanations must cite verified quotes) | n/a | n/a |
| SR2-18 `.gitignore` / `.env` | out of scope (not in LLM/enrichment files) | n/a | n/a |
| SR2-19 GDPR notes | accepted (process note; unchanged) | n/a | n/a |
| SR2-20 website binding trust root | moot (feature removed) | n/a | n/a |

## SR5 resolution (2026-10-17)

Source review: `docs/security/SR5-llm-stats-demo.md` (LLM and enrichment findings only; stats and demo
findings are tracked by their own fix logs).

| id | Status | Files / rationale | Tests |
|---|---|---|---|
| SR5-01 quadratic `<source` regex | fixed (whitespace gaps bounded to `\s{0,16}`; `sanitize_text` truncates input above `MAX_SANITIZE_CHARS` = 200 000 chars per text; `verify_quotes` cuts the quote to 4 x 300 chars before any sanitising) | `app/llm/untrusted.py`, `app/llm/quotes.py` | `tests/llm/test_untrusted_quotes.py::test_whitespace_flood_after_angle_bracket_is_linear`, `test_oversized_quote_is_cut_before_sanitizing` |
| SR5-02 ceiling NaN / inf / negative | fixed (`check_ceiling` refuses non-finite, <= 0 or > 1000 at construction; `Settings` field also constrained) | `app/enrichment/tamtam_mcp.py`, `app/config.py` | `tests/enrichment/test_hardening.py::test_bad_ceiling_is_refused_at_construction` (NaN, inf, -1, 0, 1001) |
| SR5-07 unsanitised server `source` | fixed (control / format / ANSI stripped, 80 chars max, empty becomes `None`) | `app/enrichment/tamtam_mcp.py` | `test_hardening.py::test_server_source_string_is_sanitized` |
| SR5-08 `credit_costs` unvalidated | fixed (finite and >= 0 else `EnrichmentConfigError`, real and fake providers) | `app/enrichment/tamtam_mcp.py`, `app/enrichment/fake.py` | `test_hardening.py::test_bad_credit_costs_are_refused` (NaN, inf, -1) |
| SR5-10 zero-width fusion of words | accepted: format characters are deleted by design (needed to defeat tag look-alikes, SR2-16); a fused quote still requires every other character to match the source on word boundaries, so it cannot assert anything the source text does not contain. Turning them into spaces would corrupt legitimate text (ZWJ, soft hyphens, Indic scripts) and break idempotence guarantees | `app/llm/untrusted.py` | `test_untrusted_quotes.py::test_zero_width_fusion_is_accepted_residual` (documents behaviour) |
| SR5-11 existence, not support | accepted (documented residual of SR2-02; M2 UI must say "verified quote", show context) | `app/llm/quotes.py` | n/a |
| SR5-13 `llm_max_calls_per_run` unused | deferred to M2: there is no run object or per-run counter in `app/llm` (the provider and `CallTimer` are process-wide and the DB recorder belongs to `app/services`), so a cap here would be per-process, not per-run. The M2 pipeline caller must count calls and stop at the setting | n/a | n/a |

Other SR5 ids (03, 04, 05, 06, 09, 12) are outside `app/llm` and `app/enrichment`.
Note: a `<` followed by more than 16 whitespace characters before `source` is no longer rewritten;
no model reads that as a tag, and the block delimiter is still safe because ids and bodies never
contain a literal `</source>`.
