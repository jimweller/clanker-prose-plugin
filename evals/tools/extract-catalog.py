#!/usr/bin/env python3
"""Pulls the prose-contract out of the clanker-prose plugin's skill file.

The contract names itself. `<prose-contract>` wraps `How to Write`, `Banned Patterns in
All Writing` and `Ghostwriting for Other Humans`, which the contract calls "the contract
for a written artifact". The persona, the evidence rules, the audience table and the chat
register sit outside the tag, because a compliance judge grading a written artifact has no
use for them and every extra section is context the judge can wander into.

Cutting on the tag rather than on three heading strings means a renamed heading no longer
breaks extraction, and the boundary is stated in the file rather than restated here.

Every rule inside the block carries a `PC-` id as its first token. Those ids are the shared
vocabulary between the contract, `cases/*.csv`, and anything that reports a finding.

Source of truth is skills/prose/SKILL.md, a sibling of this evals/ directory inside the
clanker-prose plugin. Override with CONTRACT_FILE when running from somewhere else.

Usage
    tools/extract-catalog.py [--ids] [OUT_FILE]
"""

import os
import pathlib
import re
import sys

EVAL_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = EVAL_ROOT.parent / "skills" / "prose" / "SKILL.md"
BLOCK = re.compile(r"<prose-contract>(.*?)</prose-contract>", re.DOTALL)
RULE_ID = re.compile(r"^- `(PC-[a-z0-9-]+)`", re.MULTILINE)


def contract_path() -> pathlib.Path:
    override = os.environ.get("CONTRACT_FILE")
    return pathlib.Path(override) if override else DEFAULT_CONTRACT


def extract(text: str) -> str:
    blocks = BLOCK.findall(text)
    if not blocks:
        raise LookupError("no <prose-contract> block")
    if len(blocks) > 1:
        # Two blocks means a stray tag, and silently concatenating them would hide it.
        raise LookupError(f"{len(blocks)} <prose-contract> blocks, expected 1")
    return blocks[0].strip()


def main() -> int:
    argv = sys.argv[1:]
    listing = "--ids" in argv
    argv = [a for a in argv if a != "--ids"]

    path = contract_path()
    if not path.is_file():
        print(f"contract not found at {path}", file=sys.stderr)
        return 1

    try:
        body = extract(path.read_text())
    except LookupError as e:
        print(f"{path}: {e}", file=sys.stderr)
        return 1

    if listing:
        for rule_id in RULE_ID.findall(body):
            print(rule_id)
        return 0

    if argv:
        pathlib.Path(argv[0]).write_text(body)
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
