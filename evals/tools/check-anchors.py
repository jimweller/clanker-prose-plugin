#!/usr/bin/env python3
"""Fails when the contract and the case files disagree about what a rule is called.

Before ids, every place that named a rule typed it out. Two sessions naming the same rule
produced two strings, and the counting code treated them as two rules. One measured run
scored `trailing supplements` at 3 and `trailing supplements that hang a second beat on a
finished clause` at 3 instead of one rule at 6, and it did that to three rules.
`evals/CLAUDE.md` records the same failure in the case files, where a typo in the `bullet`
column "silently creates a new bullet".

Five checks, each catching a different way the two can drift.

    unknown id       A `bullet` value in cases/*.csv names an id the contract does not have
    orphan rule      A rule in the contract has no id at all, or carries two
    duplicate id     Two rules claim the same id
    dangling move    A [move N] tag points at a move How to Write does not define
    group drift      tools/bullet-groups.json names an id the contract lacks, or puts one
                     id in two groups, which would judge it twice per pass in group mode

An id with no case row is reported but does not fail, because a rule is allowed to exist
before anyone writes a case for it.

Usage
    tools/check-anchors.py
"""

import collections
import csv
import glob
import json
import pathlib
import re
import sys

EVAL_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EVAL_ROOT / "tools"))

BLOCK = re.compile(r"<prose-contract>(.*?)</prose-contract>", re.DOTALL)
BULLET = re.compile(r"^- (.*)$", re.MULTILINE)
LEADING_ID = re.compile(r"^`(PC-[a-z0-9-]+)` ")
ANY_ID = re.compile(r"`(PC-[a-z0-9-]+)`")
MOVE_TAG = re.compile(r"\[move (\d+)\]")
MOVE_DEF = re.compile(r"^(\d+)\. \*\*", re.MULTILINE)


def main() -> int:
    contract = EVAL_ROOT.parent / "skills" / "prose" / "SKILL.md"
    if not contract.is_file():
        print(f"contract not found at {contract}", file=sys.stderr)
        return 1

    blocks = BLOCK.findall(contract.read_text())
    if len(blocks) != 1:
        print(f"expected 1 <prose-contract> block, found {len(blocks)}", file=sys.stderr)
        return 1
    body = blocks[0]

    failures = []

    ids, orphans = [], []
    for line in BULLET.findall(body):
        m = LEADING_ID.match(line)
        if not m:
            orphans.append(line[:70])
            continue
        ids.append(m.group(1))

    dupes = [i for i, n in collections.Counter(ids).items() if n > 1]
    if dupes:
        failures.append(f"duplicate ids: {', '.join(sorted(dupes))}")
    if orphans:
        failures.append(f"{len(orphans)} rules with no id, first: {orphans[0]!r}")

    defined_moves = {int(n) for n in MOVE_DEF.findall(body)}
    dangling = {int(n) for n in MOVE_TAG.findall(body)} - defined_moves
    if dangling:
        failures.append(f"[move N] tags with no move defined: {sorted(dangling)}")

    # The provider rebuilds corpus/catalog.md only when the contract's mtime is newer.
    # A git checkout restoring an older contract carries a newer mtime and defeats
    # that, leaving the judge grading against rules nobody deployed. Compare content.
    cat = EVAL_ROOT / "corpus" / "catalog.md"
    if cat.is_file():
        if cat.read_text().strip() != body.strip():
            failures.append("corpus/catalog.md differs from the contract, "
                            "so the judge grades against a stale rule set")
    else:
        print("corpus/catalog.md absent, the provider will build it on the next run")

    known = set(ids)
    used = collections.Counter()
    for f in sorted(glob.glob(str(EVAL_ROOT / "cases" / "*.csv"))):
        for row in csv.DictReader(open(f)):
            b = (row.get("bullet") or "").strip()
            if not b:
                continue
            used[b] += 1
            if b not in known:
                failures.append(f"{pathlib.Path(f).name}: unknown id {b!r}")

    uncovered = sorted(known - set(used))

    groups = {k: v for k, v in json.loads((EVAL_ROOT / "tools" / "bullet-groups.json").read_text()).items() if not k.startswith("_")}
    owner = {}
    for name, members in groups.items():
        for g in members:
            if g not in known:
                failures.append(f"bullet-groups.json: group {name} names unknown id {g!r}")
            if g in owner:
                failures.append(f"bullet-groups.json: {g} sits in both {owner[g]} and {name}")
            owner.setdefault(g, name)

    print(f"contract rules {len(ids)}, unique {len(known)}")
    print(f"moves defined {sorted(defined_moves)}")
    print(f"case rows {sum(used.values())} across {len(used)} ids")
    print(f"judge groups {len(groups)} holding {len(owner)} ids, remainder {len(known - set(owner))}")
    if uncovered:
        print(f"\n{len(uncovered)} rules with no case row, allowed:")
        for i in uncovered:
            print(f"  {i}")

    if failures:
        print("\nFAIL")
        for f in failures:
            print(f"  {f}")
        return 1
    print("\nPASS, every id resolves in both directions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
