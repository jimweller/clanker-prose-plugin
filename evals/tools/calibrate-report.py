#!/usr/bin/env python3
"""Compares a candidate judge against the incumbent on identical rewrites.

Both judges scored the same stored text, so any difference is the model rather than
the rewriter. Three numbers decide whether the cheaper judge is adoptable.

    agreement     Findings both judges reported, matched on rule id and kind
    candidate-only  Findings the cheaper judge invented, or caught that the other missed
    incumbent-only  Findings the cheaper judge lost

Span wording drifts between models, so matching is on (kind, PC-id) within a case
rather than on the quoted span. That overcounts agreement when one judge reports two
findings on one rule in one case, which is rare and is noted in the output.

Usage
    tools/calibrate-report.py corpus/calibrate/<model>
"""

import collections
import pathlib
import re
import sys

FINDING = re.compile(r"^FINDING\s*\|\s*(violation|over-applied)\s*\|\s*(PC-[a-z0-9-]+)",
                     re.IGNORECASE | re.MULTILINE)


def parse(path: pathlib.Path):
    if not path.is_file():
        return set()
    return {(k.lower(), r) for k, r in FINDING.findall(path.read_text())}


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    root = pathlib.Path(sys.argv[1])
    cases = sorted(p for p in root.glob("*.txt") if not p.name.endswith(".incumbent.txt"))
    if not cases:
        print(f"no judged cases under {root}", file=sys.stderr)
        return 1

    agree = cand_only = inc_only = 0
    per_rule = collections.defaultdict(lambda: [0, 0, 0])
    both_clean = disagree_cases = 0

    for c in cases:
        cand = parse(c)
        inc = parse(c.with_suffix("").with_suffix(".incumbent.txt"))
        if not cand and not inc:
            both_clean += 1
        if cand != inc:
            disagree_cases += 1
        for f in cand & inc:
            agree += 1; per_rule[f[1]][0] += 1
        for f in cand - inc:
            cand_only += 1; per_rule[f[1]][1] += 1
        for f in inc - cand:
            inc_only += 1; per_rule[f[1]][2] += 1

    total = agree + cand_only + inc_only
    print(f"cases {len(cases)}, both clean {both_clean}, cases differing {disagree_cases}")
    print(f"findings  agree {agree}  candidate-only {cand_only}  incumbent-only {inc_only}")
    if total:
        print(f"agreement {agree / total * 100:.0f}% of the union")
    print("\nrule                              agree  cand-only  inc-only")
    for rule, (a, c, i) in sorted(per_rule.items(), key=lambda kv: -sum(kv[1])):
        print(f"{rule:<34}{a:>5}{c:>11}{i:>10}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
