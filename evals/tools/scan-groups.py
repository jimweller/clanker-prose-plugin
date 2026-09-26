#!/usr/bin/env python3
"""Prints the bullet group names, one per line, skipping keys starting with _.

Usage
    tools/scan-groups.py GROUPS_JSON
"""

import json
import pathlib
import sys

if len(sys.argv) != 2:
    print(__doc__, file=sys.stderr)
    raise SystemExit(2)

for key in json.loads(pathlib.Path(sys.argv[1]).read_text()):
    if not key.startswith("_"):
        print(key)
