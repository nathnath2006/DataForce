# SR15 - opt-in AI pass over meeting sentences (commit b9341a2)

Independent read-only review against `docs/ORG-AI-CONTRACT.md`. Probes (FakeLLM, test DB, no
network) are in the session scratchpad `sr15/test_probe_unit.py` and `sr15/test_probe_api.py`.
Repo tests `tests/orgchart/test_meeting_ai.py` and `tests/api/test_org_ai.py`: all pass.

Summary: 0 high, 3 medium, 3 low, 1 info.

## Findings

### SR15-01 (medium) - Verification of rule 4 and rule 3 is on the quote only, so a model or an injected transcript can pick a sub-quote that hides the negation, the hypothesis or the manager
- Evidence: `backend/app/orgchart/meeting_ai.py:252-258` (`_HYPOTHETICAL` is run on `fold(quote)`; the manager check runs on the whole `turn.text`, not the quote). No negation check exists anywhere in code; the system prompt (line 43-54) is the only guard.
- Probes (`test_probe_unit.py`):
  - P3: turn "If I reported to Bob Martin, I would quit tomorrow." with quote "reported to Bob Martin" is kept as reports_to.
  - P3b: "Bob Martin is definitely not my boss" is kept as reports_to (negation inside the quote is not examined).
  - P2: turn "I report to the CFO every week. Bob Martin is great." with quote "I report to the CFO every week." is kept as Ana reports_to Bob; the stored excerpt never names Bob.
- Impact: a proposal the contract says must not exist (hypothetical, negated, or manager not shown in the excerpt) reaches the review queue with evidence that does not support it. A person still accepts every link, but the reviewer reads the excerpt, so the evidence is misleading.
- Fix: run the hypothetical check on the whole containing sentence (use `sentences()` offsets, as the patterns do "earlier in the same sentence"), add a negation list (not, n't, ne...pas, jamais, plus, never) on that sentence, and for reports_to require the manager alias inside the quote itself (or widen the stored excerpt to the sentence).

### SR15-02 (medium) - Per-day (and per-run) budget can be exceeded by concurrent requests and by several processes
- Evidence: `backend/app/services/org_ai.py:141` snapshots `min(per_run, daily_remaining)` once at `AiPass.__init__`; `_take` (143-148) decrements only the local counter and increments the global one without re-checking it. Probe P10: two passes created for one workspace with day cap 60 and run cap 50 spent 100 calls.
- Impact: N concurrent `POST /orgchart/propose` (any number of accounts) spend up to N x per_run calls; the cap of 500/day is a soft limit. State is also per process (multiple workers multiply it) and reset at restart (the contract accepts "in memory like titles", but not the race).
- Fix: make `_take` atomic against the global counter (`with _LOCK: if _DAILY[...] >= cap: return False; _DAILY += 1`), drop the snapshot, optionally serialize AI passes per workspace; for multi-process use a DB counter.

### SR15-03 (medium) - Changing provider or model keeps the opt-in switch
- Evidence: `backend/app/services/llm_settings.py:78-92` (`save_settings` updates provider/model/key but never touches `allow_meeting_org`). Probe Q1: after `PUT /ai` from gemini to anthropic, `allow_meeting_org` is still true.
- Impact: consent was given for a named provider and model (the notice names them); transcript sentences then go to a different third party without a new opt-in. A key rotation alone is fine; a provider change is not.
- Fix: reset `allow_meeting_org = False` in `save_settings` when `provider` or `model` changes (UI already shows the notice for the new pair when the person re-enables).

### SR15-04 (low) - Third-party statements pass the "speaker is the contact" rule
- Evidence: `meeting_ai.py:246-250`. Probe P1: Ana says "Bob Martin opposes the whole project, he blocks everything."; model answers contact=Ana, blocker, quote "Bob Martin opposes the whole project"; kept, so Ana is flagged as a blocker from a sentence about Bob.
- Also P4: a quote with no org meaning ("the budget", 10 characters) is kept as decision_maker for the speaker; the 8-character minimum (`MIN_QUOTE_CHARS`) and no cue requirement make an injected transcript able to create a signal on the speaker with an arbitrary quote from the speaker's own turn.
- Impact: wrong suggestions (person-reviewed). Matches the literal contract rule 3 but defeats its intent.
- Fix: when the contact is not named in the quote, require that the quote contains an org cue (`CUES`) and no other contact's alias; raise the minimum quote length (about 20).

### SR15-05 (low) - Unbounded contact-name list sent on every call
- Evidence: `meeting_ai.py:190` sends `full_name` of every contact of the account in each call; `contacts.list_contacts` has no limit. The 40-turn/12,000-character caps do not cover it.
- Impact: an account with thousands of contacts inflates cost and sends more personal data than needed (names of people never mentioned in the sent turns).
- Fix: send only the speakers of the batch plus contacts whose alias occurs in the batch text, and cap the list (for example 200).

### SR15-06 (low) - Non-LLM exceptions skip failure memory and leave budget spent
- Evidence: `meeting_ai.py:301-305` and `org_ai.py:229-237` catch only `LLMError`. Any other exception (a DB error on cache insert, a provider bug) aborts the request with a 500 after calls were charged (`_take` ran); `_remember_failure` is not reached, so a retry button loop spends again (still bounded by caps and SR15-02).
- Fix: catch `Exception` around `ask`, count it as failed, remember the failure; run the cache insert in a savepoint.

### SR15-07 (info) - Eval scorer `--ai` bypasses the workspace switch; failure-memory dict never evicted
- `backend/eval/meetings/score.py:60-83` needs saved AI settings but does not check `allow_meeting_org`; it needs the explicit `--ai` flag, so this is by design, but it sends the eval transcripts' candidate turns even when the person left the switch off. Document it, or require the switch.
- `org_ai._FAILED` entries expire only when read again (`org_ai.py:59-65`); memory growth is tiny but unbounded in theory.

## Verified OK

1. What leaves the machine (`build_user_prompt`, `meeting_ai.py:180-193`): contact full names, and per turn the speaker's CRM name plus turn text. No titles, emails, notes, deal data, document titles, other accounts or workspaces (documents and chunks filtered by `workspace_id` and `account_id` in `org_proposals._meeting_rows`). Only turns whose speaker matched a contact of the account are candidates (`candidate_turns` line 143). Probe P9 and the repo test `test_nothing_but_names_and_turns_is_sent` agree. Names and text go through `wrap_sources`; `</source>` and `< / source>` variants are neutralized (probe P9); the system prompt declares the blocks as data.
2. Caps: turns cut to 600 characters (starting at the first candidate sentence, offsets checked by test); batches split at 40 turns / 12,000 characters (`batches`); chunk text must equal the document slice before use (line 146).
3. Zero calls: switch off, no AI settings, `use_ai=false` and origin without `meeting` each give `ai = null` and no factory call (`org_proposals.py:212-223`; `test_off_means_no_call`). `PUT /ai/meeting-org` returns 409 without settings; deleting settings deletes the row so the switch goes with it and returns off after re-creation.
4. Verification: invented quote, unknown name, foreign-account name, quote spanning turns, ambiguous alias (two contacts with the same full name, or a first name shared) are dropped (probes P7, P8). Zero-width and Cyrillic look-alike letters in the transcript cannot match the quote or an alias (P7). Offsets are computed by code and `excerpt == document.text[start:end]` (P6, repo test). Manager never inferred from another turn. Contact of another account cannot resolve. Rule 5 (already true, cycle, rejected) is applied in `_meeting_rows.add` for fresh and cached findings. Pattern findings win on duplicates.
5. Markup: the model output reaches the UI only as `evidence` JSON; `OrgChartPanel`/`model.ts` render the excerpt, provider and model as React text children; no `dangerouslySetInnerHTML` or `innerHTML` in `frontend/src`.
6. Persistence/GDPR: `meeting_org_ai_cache` stores verified findings only (written when the batches were complete), RLS enabled as for the other tables (0007), FK cascade on document and workspace; `redact_contact` purges the account's cache first (`documents.py:250`) and redacts other proposals' excerpts; cached findings are re-checked against the document text and known contacts on decode (`_decode`). Probe Q2: no transcript text or contact name in any log record during a run. Usage rows keep only counts and a masked 300-character error.
7. Failure handling: probe Q3 shows a failing provider is called once, reported (`failed`), remembered per (workspace, document, sha) for one hour, and not retried; failures are not cached. Daily and run counters and the failure memory are keyed by workspace.
8. Authorization: new routes sit on the same router and `SecurityMiddleware` (Host / Origin / `X-DataForce` for PUT/POST/DELETE) and use `CurrentWorkspace`; the toggle is a PUT under the same CSRF rules.
9. Eval scorer: prints only provider and model, builds the provider inside `AiPass` from the sealed credential (no key in scope), needs `--ai`, exits 2 without saved settings, and uses only the saved provider.
10. Frontend: notice text equals the contract wording (`orgchart/model.ts:78-79`); checkbox disabled without configuration or model (`Settings.tsx:174`); "found by AI" tag with provider and model from evidence rendered as text; the org chart button sends `use_ai` only when configured and switched on and shows what is sent.

## Resolution

- SR15-01: the stored excerpt is now the full containing sentence(s), recomputed offsets, exact
  slice. `_HYPOTHETICAL` and the patterns' past/negation guard run on it (reports_to, champion,
  decision_maker). Blocker skips the negation guard (residual, documented in the contract).
  reports_to needs the manager in the excerpt, widened by at most one preceding sentence.
- SR15-02: `_take` checks and spends the per-run and per-day counters under one lock; no snapshot.
  Test with concurrent threads never exceeds the day cap. Multi-process counting stays out of scope.
- SR15-03: `save_settings` resets `allow_meeting_org` on a provider or model change; key rotation keeps it.
- SR15-04: first-person route needs an org cue and no other contact's alias; `MIN_QUOTE_CHARS` = 12.
- SR15-05: prompt lists batch speakers plus contacts named in the batch, capped at 200.
- SR15-06: any `Exception` from the provider is a failed call and remembered; the cache insert runs in a savepoint.
- SR15-07: eval README documents that `--ai` ignores the switch on purpose; `_FAILED` evicts expired entries on write.
