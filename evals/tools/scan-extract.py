#!/usr/bin/env python3
"""Pulls the JSON array out of a judge reply and writes it, or fails.

A reply that is prose rather than JSON is a failed call, not a result, so this
exits non-zero and judge-scan.sh keeps the raw text as a .badjson file for
inspection instead of silently recording an empty candidate list.

Usage
    tools/scan-extract.py RAW_REPLY_PATH OUT_JSON_PATH
"""

import json
import pathlib
import sys

if len(sys.argv) != 3:
    print(__doc__, file=sys.stderr)
    raise SystemExit(2)

raw = pathlib.Path(sys.argv[1]).read_text().strip()
start, end = raw.find("["), raw.rfind("]")
if start < 0 or end < start:
    print("no JSON array in reply", file=sys.stderr)
    raise SystemExit(1)

payload = json.loads(raw[start:end + 1])
pathlib.Path(sys.argv[2]).write_text(json.dumps(payload))
