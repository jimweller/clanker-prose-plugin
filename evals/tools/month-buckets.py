#!/usr/bin/env python3
"""Prints month boundary pairs from a start date forward, one pair per line.

The miner runs one Confluence query per bucket so the sample spreads across the
whole window. A single query ordered by creation date returns the newest N and
nothing else, which produced a corpus spanning nine days.

Usage
    tools/month-buckets.py 2025-09-17 12
"""

import datetime as dt
import sys

if len(sys.argv) != 3:
    print(__doc__, file=sys.stderr)
    raise SystemExit(2)

start = dt.date.fromisoformat(sys.argv[1])
months = int(sys.argv[2])

cursor = start
for _ in range(months):
    year, month = cursor.year, cursor.month + 1
    if month > 12:
        year, month = year + 1, 1
    nxt = cursor.replace(year=year, month=month, day=1)
    print(f"{cursor.isoformat()} {nxt.isoformat()}")
    cursor = nxt
    if cursor > dt.date.today():
        break
