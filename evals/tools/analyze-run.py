#!/usr/bin/env python3
"""Breaks a promptfoo run down by bullet, polarity and failure mode.

The split that matters is rewrite against preserve. A bullet failing its rewrite
cases means the rule under-triggers and the model leaves the defect alone. A
bullet failing its preserve cases means the rule over-triggers and the model
deletes something an exemption protects. Those two want opposite edits, so a
single pass rate hides the decision.

Usage
    tools/analyze-run.py RESULT_JSON [--min-cases 4] [--show-failures BULLET]
"""

import argparse
import collections
import json
import pathlib
import sys

SHARED = {"banned-literals.js", "no-prose-colon.js", "length-guard.js"}


def grader_name(component) -> str:
    value = str(component.get("assertion", {}).get("value", ""))
    for name in SHARED:
        if name in value:
            return name
    return "case-assertion"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result_json")
    parser.add_argument("--min-cases", type=int, default=4)
    parser.add_argument("--show-failures", default=None,
                        help="print the failing spans for one bullet")
    args = parser.parse_args()

    data = json.loads(pathlib.Path(args.result_json).read_text())
    rows = (data.get("results") or {}).get("results") or []
    if not rows:
        print("no results in that file", file=sys.stderr)
        return 1

    stat = collections.defaultdict(lambda: {"n": 0, "ok": 0})
    graders = collections.Counter()
    failures = collections.defaultdict(list)

    for r in rows:
        v = (r.get("testCase") or {}).get("vars") or {}
        bullet, pol = v.get("bullet", "?"), v.get("polarity", "?")
        for key in ((bullet, pol), (bullet, "all")):
            stat[key]["n"] += 1
            if r.get("success"):
                stat[key]["ok"] += 1
        if not r.get("success"):
            comps = (r.get("gradingResult") or {}).get("componentResults") or []
            bad = [c for c in comps if not c.get("pass")]
            for c in bad:
                graders[grader_name(c)] += 1
            failures[bullet].append({
                "polarity": pol,
                "input": v.get("input", ""),
                "output": str((r.get("response") or {}).get("output", "")).replace("\n", " "),
                "why": " | ".join(str(c.get("reason", ""))[:110] for c in bad),
            })

    total = sum(1 for r in rows)
    passed = sum(1 for r in rows if r.get("success"))
    print(f"{passed}/{total} passed, {100*passed/total:.0f}%\n")

    print("failing assertions by grader")
    for g, c in graders.most_common():
        print(f"  {c:5d}  {g}")
    print()

    bullets = sorted({b for b, p in stat if p == "all"})
    scored = []
    for b in bullets:
        a = stat[(b, "all")]
        if a["n"] < args.min_cases:
            continue
        rw = stat.get((b, "rewrite"), {"n": 0, "ok": 0})
        pr = stat.get((b, "preserve"), {"n": 0, "ok": 0})
        scored.append((a["ok"] / a["n"], b, a, rw, pr))
    scored.sort()

    print(f"{'bullet':52s} {'all':>9s} {'rewrite':>9s} {'preserve':>9s}")
    for rate, b, a, rw, pr in scored:
        def f(d):
            return f"{d['ok']}/{d['n']}" if d["n"] else "-"
        print(f"  {b[:50]:50s} {f(a):>9s} {f(rw):>9s} {f(pr):>9s}   {100*rate:3.0f}%")

    if args.show_failures:
        print(f"\nfailures for {args.show_failures}")
        for item in failures.get(args.show_failures, []):
            print(f"\n  [{item['polarity']}] {item['why']}")
            print(f"    in  {item['input'][:150]}")
            print(f"    out {item['output'][:150]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
