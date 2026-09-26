#!/usr/bin/env python3
"""Reports the launder loop, meaning what share of rewrites a fresh judge calls human.

The headline is the laundered arm. The baseline arm is the same paragraphs judged
without a rewrite, so the gap between the two is what the contract buys.

It also measures sentence-length uniformity, because that is usually the reason a
rewrite still reads generated. The Ghostwriting section states that structural
uniformity outweighs vocabulary as a detection signal, and the SVO default plus
one fact per sentence drives sentence lengths together. A rewrite whose
coefficient of variation falls well below its source has traded a punctuation
tell for a rhythm tell.

Usage
    tools/launder-report.py RESULT_JSON [--rewrites corpus/rewrites]
"""

import argparse
import collections
import json
import pathlib
import re
import statistics
import sys

EVAL_ROOT = pathlib.Path(__file__).resolve().parent.parent


def sentence_lengths(text: str):
    parts = [p for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.split()]
    return [len(p.split()) for p in parts]


def cv(lengths):
    if len(lengths) < 2:
        return None
    mean = statistics.mean(lengths)
    return statistics.pstdev(lengths) / mean if mean else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result_json")
    parser.add_argument("--rewrites", default=str(EVAL_ROOT / "corpus" / "rewrites"))
    args = parser.parse_args()

    rows = (json.loads(pathlib.Path(args.result_json).read_text())
            .get("results") or {}).get("results") or []
    if not rows:
        print("no results", file=sys.stderr)
        return 1

    arm = collections.defaultdict(lambda: {"n": 0, "human": 0})
    per_case = collections.defaultdict(lambda: collections.defaultdict(lambda: {"n": 0, "human": 0}))
    sources = {}

    for r in rows:
        v = (r.get("testCase") or {}).get("vars") or {}
        label = ((r.get("provider") or {}).get("label")
                 or (r.get("provider") or {}).get("id") or "?")
        label = "laundered" if "rewrite-then-judge" in label or label == "laundered" else \
                ("baseline" if "judge-only" in label or label == "baseline" else label)
        out = str((r.get("response") or {}).get("output", "")).lower()
        human = "verdict human" in out
        desc = v.get("__description") or str(v.get("passage", ""))[:40]
        sources[desc] = str(v.get("passage", ""))
        for bucket in (arm[label], per_case[desc][label]):
            bucket["n"] += 1
            bucket["human"] += 1 if human else 0

    print(f"\n{'arm':12s} {'judged human':>16s}")
    for name in ("baseline", "laundered"):
        d = arm.get(name)
        if not d or not d["n"]:
            continue
        print(f"  {name:10s} {d['human']:5d}/{d['n']:<5d} {100*d['human']/d['n']:5.1f}%")
    if arm.get("baseline") and arm.get("laundered"):
        b, l = arm["baseline"], arm["laundered"]
        gain = 100 * l["human"] / l["n"] - 100 * b["human"] / b["n"]
        print(f"  {'gain':10s} {gain:+16.1f} points   target is 90% laundered")

    rew_dir = pathlib.Path(args.rewrites)
    if rew_dir.exists():
        src_cv = [c for c in (cv(sentence_lengths(s)) for s in sources.values()) if c]
        out_cv = [c for c in (cv(sentence_lengths(p.read_text()))
                              for p in rew_dir.glob("*.txt")) if c]
        if src_cv and out_cv:
            print(f"\nsentence-length variation, coefficient of variation")
            print(f"  source   median {statistics.median(src_cv):.2f}  n={len(src_cv)}")
            print(f"  rewrite  median {statistics.median(out_cv):.2f}  n={len(out_cv)}")
            print("  A rewrite median well below the source median means the edit")
            print("  flattened the rhythm, which is itself a detection signal.")

    losers = sorted(
        ((d["laundered"]["human"] / d["laundered"]["n"], desc)
         for desc, d in per_case.items() if d.get("laundered", {}).get("n")),
        key=lambda x: x[0])[:10]
    if losers:
        print("\nworst laundered cases, share judged human")
        for rate, desc in losers:
            print(f"  {100*rate:5.0f}%  {desc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
