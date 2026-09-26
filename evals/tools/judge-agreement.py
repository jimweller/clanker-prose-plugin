#!/usr/bin/env python3
"""Measures how far the JSON judge agrees with itself and across runs.

Rows are matched on the stripped rewrite text, never on position, so two runs over the same
stored replies line up even when promptfoo orders them differently.

Two numbers per comparison.
    clean agreement    both sides call the reply clean, or both call it dirty
    finding agreement  findings both sides report, matched on key, over their union

Modes
    within RUN                    every pair of passes inside each row of one graded run
    across RUN_A RUN_B            clean-majority verdicts and majority findings of two graded runs,
                                  with each rule's agree, a-only, and b-only counts

Exits 1 when no row matched, since every number would then be 0 of 0.

Usage
    tools/judge-agreement.py within RUN_JSON
    tools/judge-agreement.py across RUN_A_JSON RUN_B_JSON
"""

import argparse
import collections
import itertools
import json

JUDGE_KIND = "comply"
PREFIX = "cmp"


def load_rows(path):
    with open(path) as f:
        return json.load(f)["results"]["results"]


def graded(row):
    """Returns (reply, per-pass key sets, clean_maj) for a graded row, or None."""
    comps = (row.get("gradingResult") or {}).get("componentResults") or []
    metas = [c.get("metadata") or {} for c in comps]
    if not any(m.get("role") == "judge" and m.get("judge_kind") == JUDGE_KIND for m in metas):
        return None
    scores = (row.get("gradingResult") or {}).get("namedScores") or {}
    if not scores.get(f"{PREFIX}_judged"):
        return None
    p = scores[f"{PREFIX}_passes"]
    passes = [set() for _ in range(p)]
    for m in metas:
        if m.get("role") == "finding" and m.get("judge_kind") == JUDGE_KIND:
            for x in m["passes"]:
                passes[x["pass_index"]].add(m["key"])
    reply = ((row.get("response") or {}).get("output") or "").strip()
    return reply, passes, scores[f"{PREFIX}_clean_maj"]


def index(items):
    out = {}
    for reply, *rest in items:
        out.setdefault(reply, []).append(rest)
    return out


def match(a, b):
    """Pairs entries with equal replies, first come first served."""
    pairs, bi = [], {k: list(v) for k, v in index(b).items()}
    for reply, *rest in a:
        if bi.get(reply):
            pairs.append((rest, bi[reply].pop(0)))
    return pairs


def majority(passes):
    """Keys at least floor(P/2)+1 of the passes reported."""
    m = len(passes) // 2 + 1
    counts = collections.Counter(k for keys in passes for k in keys)
    return {k for k, n in counts.items() if n >= m}


def ratio(n, d):
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else f"{n}/{d} (n/a)"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=("within", "across"))
    ap.add_argument("runs", nargs="+")
    args = ap.parse_args(argv)

    if args.mode == "within":
        rows = [g for g in map(graded, load_rows(args.runs[0])) if g]
        agree = pairs = f_agree = f_union = 0
        for _, passes, _ in rows:
            for x, y in itertools.combinations(passes, 2):
                pairs += 1
                agree += int(bool(x) == bool(y))
                f_agree += len(x & y)
                f_union += len(x | y)
        print(f"rows {len(rows)}")
        print(f"pass-vs-pass clean agreement {ratio(agree, pairs)}")
        print(f"finding agreement {ratio(f_agree, f_union)}")
        return 0 if rows else 1

    if len(args.runs) != 2:
        ap.error("across needs two runs")
    a, b = ([g for g in map(graded, load_rows(r)) if g] for r in args.runs)
    pairs = match(a, b)
    agree = sum(1 for (_, ca), (_, cb) in pairs if ca == cb)
    per_rule = collections.defaultdict(lambda: [0, 0, 0])
    for (pa, _), (pb, _) in pairs:
        ka, kb = majority(pa), majority(pb)
        for keys, col in ((ka & kb, 0), (ka - kb, 1), (kb - ka, 2)):
            for k in keys:
                per_rule[k][col] += 1
    both, a_only, b_only = (sum(v[i] for v in per_rule.values()) for i in range(3))
    print(f"matched {len(pairs)} of {len(a)} and {len(b)}")
    print(f"clean-majority agreement {ratio(agree, len(pairs))}")
    print(f"majority findings agree {both}  a-only {a_only}  b-only {b_only}")
    print(f"majority finding agreement {ratio(both, both + a_only + b_only)}")
    if per_rule:
        print(f"{'rule':<34}{'agree':>6}{'a-only':>8}{'b-only':>8}")
        for rule, (x, y, z) in sorted(per_rule.items(), key=lambda kv: (-sum(kv[1]), kv[0])):
            print(f"{rule:<34}{x:>6}{y:>8}{z:>8}")
    return 0 if pairs else 1


if __name__ == "__main__":
    raise SystemExit(main())
