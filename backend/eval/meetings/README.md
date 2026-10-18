# Meeting extraction: independent test sets

Each set holds 15 synthetic sales-meeting transcripts in French and English, written by a separate
agent. That agent read only `brief.json` (15 accounts of the `test-data` workspace: deal, contacts,
true managers) and never the parsing code. `key.json` records what each meeting really contains:

- `topics`: the known themes discussed;
- `reports_to` and `signals`: the org statements, with their exact sentence;
- decoys: near-miss phrases that must *not* count.

Score a set against a running app (`make testdata`, then `make ui`):

    cd backend && .venv/bin/python eval/meetings/score.py eval/meetings/set1

The script imports the transcripts into the `test-data` workspace (titled "Eval set1 …"; a rerun
replaces them), runs the meeting org proposals and a theme run without AI, then prints:

- the speaker match rate;
- theme precision and recall per meeting;
- reports-to and signal precision and recall.

Each figure comes with a Wilson 95 % interval.

A set is held-out only until its misses have been used to change the rules. `set1` was used that
way on 2026-10-18 (see `docs/DECISIONS.md` §J).
