# Contract: org statements from meetings, opt-in AI pass

Decided with the PO on 2026-10-18 (DECISIONS §J, sets 1 and 2):

- Fixed patterns for meeting org statements are precise but find about 1 link in 10 on new
  wording.
- An **opt-in** AI pass reads only *candidate sentences*. Code verifies everything it returns,
  and a person still accepts every link.

The patterns stay. They run first, need no AI and win on duplicates.

## 1. Rules

- **Off by default, per workspace.** The pass needs a saved AI model (Settings → AI) and the
  switch "Read meeting sentences for org statements". When the AI settings are deleted, the
  switch goes with them.
- **Minimum sent.**
  - The pass sends only the speaker turns that contain a candidate sentence (§2), each capped at
    600 characters, plus the account's contact **names**.
  - It never sends whole transcripts, titles, emails, phones, notes or deal data.
  - Text sent is wrapped with `app/llm/untrusted.wrap_sources`. The system prompt says it is
    data, never instructions.
- **Nothing unverified becomes a suggestion** (§3).
- **Exactness.** The stored excerpt is an exact slice of the document text, as for patterns.
- **Budget.**
  - One structured call per transcript, with at most 40 candidate turns and 12,000 characters.
    Longer transcripts are split into several calls and count against the cap.
  - Caps: `org_ai_max_calls_per_run` = 50 and `org_ai_max_calls_per_day` = 500 per workspace,
    in memory like titles. The response reports the calls made, capped and failed.
- **Cache.**
  - Results are cached per (document, text sha256, provider, model), so a rerun sends nothing
    again.
  - Deleting a document deletes its cache (FK cascade).
  - Erasing a contact deletes the cache of that account's documents.
- **Labels.** AI findings are meeting proposals with `evidence.found_by = "ai"`,
  `evidence.provider` and `evidence.model`. The UI shows a "found by AI" tag next to "from
  meeting".

## 2. Candidate sentences (code, local)

- Only speaker turns whose speaker matched a contact of the account are considered, as for the
  patterns.
- A sentence is a candidate when it names a contact of the account (same `aliases()` as the
  patterns) or contains an org cue.
- **Org cues** are a broad FR/EN cue list, matched on folded text. Examples: report, boss,
  manager, line manager, n+1, director, directeur, directrice, rattach, équipe / team, sous,
  under, answer to, dépend, décid / decide, decision, signe / sign, final, dernier mot,
  valide / sign off, contre / against, réticent / reluctant, oppos, bloque / block, pousser /
  push, défendre / defend, champion, soutenir / back.
- The cue list is a recall filter, not a classifier: keep it wide. Unit-test it on the
  wordings of `backend/eval/meetings/set1` and `set2`; those sets are no longer held-out.

## 3. Verification of each AI finding (code)

The model returns a list of `{kind, contact, manager, quote, confidence}`:

- `kind` is one of reports_to, champion, blocker or decision_maker;
- `contact` and `manager` are names from the given list (`manager` only for reports_to);
- `quote` is copied verbatim.

A finding is kept only if all of these hold:

1. `quote` is an exact substring of one candidate turn that was sent. Its document offsets are
   computed by code, and the excerpt is the document slice at those offsets.
2. `contact`, and `manager` when present, each resolve to exactly one contact of the account
   with the same alias rules; `contact != manager`.
3. The quote mentions the contact or the manager by an alias, or the turn's speaker is the
   contact (first person).
4. The quote has no hypothetical word (the patterns' `_HYPOTHETICAL`).
5. For reports_to: the link is not already true in the CRM, would not create a cycle (`rules.
   would_cycle`), and is not blocked by an earlier rejection.

Everything else is dropped and counted in `ai.dropped`, with no text logged. Pattern findings
win on the same (contact, kind, manager).

## 4. Surfaces

- **Migration 0007.**
  - `llm_credential.allow_meeting_org boolean not null default false`.
  - Table `meeting_org_ai_cache`: id, workspace_id, document_id (FK cascade), text_sha256,
    provider, model, findings jsonb (verified findings only), created_at; unique on (document,
    sha, provider, model).
- **API.**
  - `PUT /api/w/{ws}/ai/meeting-org {enabled: bool}` returns 409 when no AI settings exist.
  - `GET /api/w/{ws}/ai` adds `allow_meeting_org`.
  - `POST /orgchart/propose` takes `use_ai: bool = false`. AI runs only when it is true, the
    switch is on and `meeting` is among the origins.
  - `ProposeOut` adds `ai: {used, calls, capped, failed, dropped} | null`.
- **UI.**
  - The Settings AI panel has a checkbox, disabled without a model, with this text: "Sends only
    sentences that name one of the account's contacts or contain an org phrase, with the
    account's contact names, to {provider} {model}. Full transcripts are never sent. Off by
    default."
  - The org chart "Suggest links" button sends `use_ai: true` when the switch is on and says
    what was sent.
  - Proposals show the "found by AI" tag.
- **Tests (FakeLLM only, no network).**
  - Candidate selection, including the cue list on the eval wordings.
  - Every verification rule, each with a negative test: invented quote, unknown name, name of
    another account, hypothetical, cycle, already true, rejected.
  - Prompt injection inside a transcript turn: an instruction in the text must not produce an
    unverified suggestion.
  - The switch off means no call; caps; the cache hit means no call; deletion and erasure purge
    the cache.
  - Pattern-first dedupe; the API and UI.
- **Eval.** `backend/eval/meetings/score.py --ai` runs the pass in-process on the set's
  transcripts with the workspace's saved model. The key is never printed. Calls go only to the
  provider saved in Settings.

## 5. Out of scope

- AI themes from transcripts: themes stay local.
- AI for titles beyond what exists.
- Any write by the AI.
