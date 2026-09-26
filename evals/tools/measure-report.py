#!/usr/bin/env python3
"""Compares a before and an after run of the same cases, split by polarity.

Most catalog edits move the rewrite arm and the preserve arm in opposite
directions, because telling an editor to cut harder also makes it cut things an
exemption protects. A single overall number hides that trade, so this prints
both arms and the per-case detail for anything that moved.

Usage
    tools/measure-report.py BEFORE_JSON AFTER_JSON
"""

import collections
import json
import pathlib
import sys


def load(path: pathlib.Path):
    if not path.exists():
        return None
    rows = (json.loads(path.read_text()).get("results") or {}).get("results") or []
    arms = collections.defaultdict(lambda: {"n": 0, "ok": 0})
    cases = collections.defaultdict(lambda: {"n": 0, "ok": 0, "pol": "?"})
    for r in rows:
        v = (r.get("testCase") or {}).get("vars") or {}
        pol = v.get("polarity", "?")
        key = str(v.get("input", ""))[:70]
        for bucket, name in ((arms, pol), (arms, "all")):
            bucket[name]["n"] += 1
            if r.get("success"):
                bucket[name]["ok"] += 1
        cases[key]["n"] += 1
        cases[key]["pol"] = pol
        if r.get("success"):
            cases[key]["ok"] += 1
    return arms, cases


def pct(d):
    return 100 * d["ok"] / d["n"] if d["n"] else 0.0


def main() -> int:
    before = load(pathlib.Path(sys.argv[1]))
    after = load(pathlib.Path(sys.argv[2]))

    if after is None:
        print("baseline captured, edit the catalog then rerun with phase after")
        return 0
    if before is None:
        print("no baseline found, capture one with phase before")
        return 1

    ba, bc = before
    aa, ac = after

    print(f"\n{'arm':12s} {'before':>12s} {'after':>12s} {'delta':>8s}")
    for arm in ("all", "rewrite", "preserve"):
        b, a = ba.get(arm), aa.get(arm)
        if not b or not a or not b["n"]:
            continue
        d = pct(a) - pct(b)
        print(f"  {arm:10s} {b['ok']:4d}/{b['n']:<3d} {pct(b):3.0f}% "
              f"{a['ok']:4d}/{a['n']:<3d} {pct(a):3.0f}% {d:+7.0f}")

    moved = []
    for key in set(bc) | set(ac):
        b, a = bc.get(key), ac.get(key)
        if not b or not a:
            continue
        if b["ok"] / b["n"] != a["ok"] / a["n"]:
            moved.append((a["ok"] / a["n"] - b["ok"] / b["n"], key, b, a))
    if moved:
        moved.sort()
        print("\ncases that moved")
        for _, key, b, a in moved:
            print(f"  [{a['pol']:8s}] {b['ok']}/{b['n']} to {a['ok']}/{a['n']}   {key}")

    print("\nA case that moved by one trial out of five is noise. Trust an arm-level")
    print("delta, and treat a single case flipping as a prompt to add more repeats.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
