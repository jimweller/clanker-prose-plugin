#!/usr/bin/env python3
"""Renders one judge prompt for a chunk and a bullet group.

Exists as a file rather than an inline heredoc inside judge-scan.sh. The inline
version nested a multi-line python string inside a double-quoted command
substitution inside a single-quoted xargs body, which was unreadable and failed
in ways the shell reported as nothing at all.

Usage
    tools/scan-render.py GROUPS_JSON GROUP_NAME CHUNK_PATH TEMPLATE_PATH
"""

import json
import pathlib
import sys


def main() -> int:
    if len(sys.argv) != 5:
        print(__doc__, file=sys.stderr)
        return 2

    groups_path, group, chunk_path, template_path = sys.argv[1:5]
    groups = json.loads(pathlib.Path(groups_path).read_text())
    if group not in groups:
        print(f"no such bullet group, {group}", file=sys.stderr)
        return 1

    bullets = "\n".join("- " + b for b in groups[group])
    template = pathlib.Path(template_path).read_text()
    text = pathlib.Path(chunk_path).read_text()

    sys.stdout.write(template.replace("__BULLETS__", bullets).replace("__TEXT__", text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
