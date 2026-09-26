#!/usr/bin/env python3
"""Measures how far the JSON judge agrees with itself, with the incumbent, and across runs.

Rows are matched on the stripped rewrite text, never on position, so two runs over the same
stored replies line up even when promptfoo orders them differently.

Two numbers per comparison, the same two the incumbent judge's noise floor was measured with.
    clean agreement    both sides call the reply clean, or both call it dirty
    finding agreement  findings both sides report, matched on key, over their union

Modes
    within RUN                    every pair of passes inside each row of one graded run
    incumbent RUN --legacy OLD    every new pass against the legacy text judge's single verdict
    across RUN_A RUN_B            clean-majority verdicts of two graded runs

Exits 1 when no row matched, since every number would then be 0 of 0.

Usage
    tools/judge-agreement.py within RUN_JSON
    tools/judge-agreement.py incumbent RUN_JSON --legacy LEGACY_JSON
    tools/judge-agreement.py across RUN_A_JSON RUN_B_JSON
"""

import argparse
import itertools
import json
import re

REPLY_SECTION = "REWRITE"
JUDGE_KIND = "comply"
PREFIX = "cmp"
LEGACY_FINDING = re.compile(r"^FINDING\s*\|\s*(violation|over-applied)\s*\|\s*(PC-[a-z0-9-]+)", re.MULTILINE | re.IGNORECASE)
SECTION = re.compile(r"<<<([A-Z]+)>>>")


def legacy_keys(block):
    return {f"{m.group(1).lower()}:{m.group(2)}" for m in LEGACY_FINDING.finditer(block)}


def load_rows(path):
    with open(path) as f:
        return json.load(f)["results"]["results"]


def sections(text):
    parts, last, pos = {}, None, 0
    for m in SECTION.finditer(text):
        if last:
            parts[last] = text[pos:m.start()]
        last, pos = m.group(1), m.end()
    if last:
        parts[last] = text[pos:]
    return parts


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


def legacy(row):
    parts = sections((row.get("response") or {}).get("output") or "")
    if REPLY_SECTION not in parts or "FINDINGS" not in parts:
        return None
    return parts[REPLY_SECTION].strip(), legacy_keys(parts["FINDINGS"])


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


def ratio(n, d):
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else f"{n}/{d} (n/a)"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=("within", "incumbent", "across"))
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--legacy")
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

    if args.mode == "incumbent":
        if not args.legacy:
            ap.error("incumbent needs --legacy")
        new = [g for g in map(graded, load_rows(args.runs[0])) if g]
        old = [l for l in map(legacy, load_rows(args.legacy)) if l]
        pairs = match(new, old)
        agree = total = f_agree = f_union = 0
        for (passes, _), (old_keys,) in pairs:
            for keys in passes:
                total += 1
                agree += int(bool(keys) == bool(old_keys))
                f_agree += len(keys & old_keys)
                f_union += len(keys | old_keys)
        print(f"matched {len(pairs)} of {len(new)}")
        print(f"per-pass vs incumbent verdict agreement {ratio(agree, total)}")
        print(f"finding agreement {ratio(f_agree, f_union)}")
        return 0 if pairs else 1

    if len(args.runs) != 2:
        ap.error("across needs two runs")
    a, b = ([g for g in map(graded, load_rows(r)) if g] for r in args.runs)
    pairs = match(a, b)
    agree = sum(1 for (_, ca), (_, cb) in pairs if ca == cb)
    print(f"matched {len(pairs)} of {len(a)} and {len(b)}")
    print(f"clean-majority agreement {ratio(agree, len(pairs))}")
    return 0 if pairs else 1


if __name__ == "__main__":
    raise SystemExit(main())
