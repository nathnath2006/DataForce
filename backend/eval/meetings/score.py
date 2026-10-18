"""Score meeting extraction on an independently written transcript set.

Imports the set's transcripts through the upload API of a running DataForce (`make ui`), runs
a theme run (no AI) and the meeting org-statement extraction, then compares with key.json:
speaker matching, known themes per meeting, reports-to links and signals. Rerunning replaces
the set's earlier imports. Run from backend/:

    .venv/bin/python eval/meetings/score.py eval/meetings/set1 [--ws test-data]
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import pathlib
import sys
import uuid
from collections import Counter
from types import ModuleType

import httpx

from app.stats.intervals import wilson

THEMES = ("price", "competitor", "security", "integration", "timing", "legal", "onboarding")
THEMES += ("support",)
SIGNALS = ("champion", "blocker", "decision_maker")


def ci(k: int, n: int) -> str:
    if n == 0:
        return "n/a"
    p, lo, hi = wilson(k, n)
    return f"{p:.0%} [{lo:.0%}, {hi:.0%}] ({k}/{n})"


def theme_id(label: str) -> str | None:
    low = label.lower()
    return next((t for t in THEMES if low.startswith(t[:5])), None)


def load_patterns(path: pathlib.Path | None) -> ModuleType:
    """The meeting pattern module: the app's, or another version of it (e.g. from git)."""
    if path is None:
        return importlib.import_module("app.orgchart.meetings")
    spec = importlib.util.spec_from_file_location("meetings_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while being built
    spec.loader.exec_module(module)
    return module


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("set_dir", type=pathlib.Path)
    ap.add_argument("--base", default="http://127.0.0.1:8800")
    ap.add_argument("--ws", default="test-data")
    ap.add_argument("--patterns", type=pathlib.Path, help="another version of meetings.py")
    a = ap.parse_args()
    key = json.loads((a.set_dir / "key.json").read_text())
    brief = {b["account"]: b for b in json.loads((a.set_dir / "brief.json").read_text())}
    prefix = f"Eval {a.set_dir.name} "
    api = f"{a.base}/api/w/{a.ws}"
    c = httpx.Client(timeout=300, headers={"Origin": a.base, "X-DataForce": "1"})

    # Remove this set's earlier imports, so a rerun scores only the fresh ones.
    old, offset = [], 0
    while True:
        page = c.get(f"{api}/documents", params={"limit": 200, "offset": offset}).json()["items"]
        old += [d["id"] for d in page if d["title"].startswith(prefix)]
        if len(page) < 200:
            break
        offset += 200
    for doc_id in old:
        c.delete(f"{api}/documents/{doc_id}").raise_for_status()

    docs: dict[str, dict] = {}
    for item in key:
        b = brief[item["account"]]
        accounts = c.get(f"{api}/accounts", params={"q": b["account"], "limit": 50}).json()
        acc = next(x for x in accounts["items"] if x["name"] == b["account"])
        deals = c.get(f"{api}/deals", params={"account_id": acc["id"], "limit": 200}).json()
        deal = next((x for x in deals["items"] if x["name"] == b["deal"]["name"]), None)
        f = a.set_dir / "transcripts" / item["file"]
        data = {"title": prefix + item["file"]} | ({"deal_id": deal["id"]} if deal else {})
        kind = "text/markdown" if f.suffix == ".md" else "text/plain"
        r = c.post(
            f"{api}/accounts/{acc['id']}/documents",
            data=data,
            files={"file": (f.name, f.read_bytes(), kind)},
        )
        r.raise_for_status()
        docs[item["file"]] = r.json()
    speakers = [s for d in docs.values() for s in d["speakers"]]
    matched = sum(bool(s.get("contact_id") or s.get("user_id")) for s in speakers)
    print(f"Imported {len(docs)} transcripts into '{a.ws}'.")
    print("Speakers matched to a contact or a rep:", ci(matched, len(speakers)))

    accounts_ids = {d["account_id"] for d in docs.values()}
    c.post(f"{api}/themes/run", json={"use_ai": False}).raise_for_status()

    tp, fp, fn = Counter(), Counter(), Counter()
    for item in key:
        full = c.get(f"{api}/documents/{docs[item['file']]['id']}").json()
        got = {theme_id(x["label"]) for x in full["chunk_themes"]} - {None}
        want = set(item["topics"])
        tp.update(got & want)
        fp.update(got - want)
        fn.update(want - got)
    print("\nKnown themes, per meeting:")
    for t in THEMES:
        print(f"  {t:12} precision {ci(tp[t], tp[t] + fp[t]):24} recall {ci(tp[t], tp[t] + fn[t])}")
    n_tp, n_fp, n_fn = sum(tp.values()), sum(fp.values()), sum(fn.values())
    print(f"  {'all':12} precision {ci(n_tp, n_tp + n_fp):24} recall {ci(n_tp, n_tp + n_fn)}")

    # Org statements: the app's extraction code runs here on this set's transcripts only. The
    # workspace's own synthetic meetings may already state the same links, and a proposal keeps
    # the first quote found, so reading proposals back would hide what this set contributed.
    patterns = load_patterns(a.patterns)
    found: list[tuple[str, str, str | None]] = []
    for acc_id in accounts_ids:
        people = c.get(f"{api}/contacts", params={"account_id": acc_id, "limit": 200}).json()
        people = people["items"]
        name = {p["id"]: p["full_name"] for p in people}
        current = {p["id"]: p["reports_to_id"] for p in people}
        refs = [patterns.ContactRef(uuid.UUID(p["id"]), p["full_name"]) for p in people]
        for d in docs.values():
            if d["account_id"] != acc_id:
                continue
            full = c.get(f"{api}/documents/{d['id']}").json()
            text, doc_id = full["text"], uuid.UUID(full["id"])
            chunks = [
                patterns.ChunkRec(
                    doc_id,
                    uuid.UUID(ch["id"]),
                    ch["speaker"],
                    uuid.UUID(ch["contact_id"]) if ch["contact_id"] else None,
                    ch["char_start"],
                    ch["char_end"],
                    text[ch["char_start"] : ch["char_end"]],
                )
                for ch in full["chunks"]
            ]
            for f in patterns.extract(chunks, refs, {doc_id: text}):
                who, boss = str(f.contact_id), str(f.manager_id) if f.manager_id else None
                if f.kind == "reports_to" and current.get(who) == boss:
                    continue  # already in the CRM: the app does not propose it
                found.append((f.kind, name[who], name.get(boss) if boss else None))
    props = [
        {"kind": k, "contact": {"full_name": n}, "manager": {"full_name": m} if m else None}
        for k, n, m in set(found)
    ]
    missing = {
        (ct["full_name"], ct["true_manager"])
        for b in brief.values()
        for ct in b["contacts"]
        if ct["manager_link_missing_in_crm"]
    }
    want_rt = {(r["contact"], r["manager"]) for k in key for r in k["reports_to"]}
    got_rt = {
        (p["contact"]["full_name"], (p.get("manager") or {}).get("full_name"))
        for p in props
        if p["kind"] == "reports_to"
    }
    want_new = want_rt & missing
    want_sig = {(s["contact"], s["kind"]) for k in key for s in k["signals"]}
    got_sig = {(p["contact"]["full_name"], p["kind"]) for p in props if p["kind"] != "reports_to"}
    hit_rt, hit_sig = got_rt & want_rt, got_sig & want_sig
    print("\nReports-to from meetings:")
    print("  precision", ci(len(hit_rt), len(got_rt)))
    print("  recall, all statements", ci(len(hit_rt), len(want_rt)))
    print("  recall, links missing from the CRM", ci(len(got_rt & want_new), len(want_new)))
    print("Signals from meetings:")
    print("  precision", ci(len(hit_sig), len(got_sig)), " recall", ci(len(hit_sig), len(want_sig)))
    for kind in SIGNALS:
        w = {x for x in want_sig if x[1] == kind}
        g = {x for x in got_sig if x[1] == kind}
        print(f"  {kind:15} found {len(g & w)}/{len(w)}, false {len(g - w)}")
    for name, extra in (("reports-to", got_rt - want_rt), ("signals", got_sig - want_sig)):
        if extra:
            print(f"False {name}:", sorted(extra))


if __name__ == "__main__":
    main()
