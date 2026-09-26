#!/usr/bin/env python3
"""Merges judge-scan output into one candidate file and reports the shape of it.

Spans are proprietary, so stdout carries counts only. The spans themselves go to
corpus/candidates-<source>.jsonl, which is gitignored.

Usage
    tools/aggregate-candidates.py [--source raw]
"""

import argparse
import collections
import hashlib
import json
import pathlib
import sys

EVAL_ROOT = pathlib.Path(__file__).resolve().parent.parent
CORPUS = EVAL_ROOT / "corpus"

REQUIRED = ("bullet", "polarity", "granularity", "span", "reason")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="raw")
    args = parser.parse_args()

    in_dir = CORPUS / "candidates" / args.source
    if not in_dir.exists():
        print(f"no candidates at {in_dir}", file=sys.stderr)
        return 1

    by_bullet = collections.Counter()
    by_polarity = collections.Counter()
    by_granularity = collections.Counter()
    by_confidence = collections.Counter()
    seen: set[str] = set()
    rows, malformed, empty_files = [], 0, 0

    for path in sorted(in_dir.glob("*.json")):
        stem, _, group = path.stem.rpartition(".")
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(payload, list):
            malformed += 1
            continue
        if not payload:
            empty_files += 1
            continue

        for item in payload:
            if not isinstance(item, dict) or any(k not in item for k in REQUIRED):
                malformed += 1
                continue
            span = str(item["span"]).strip()
            if len(span.split()) < 4:
                malformed += 1
                continue
            key = hashlib.sha256(span.lower().encode()).hexdigest()[:16]
            if key in seen:
                continue
            seen.add(key)

            row = {
                "key": key,
                "chunk": stem,
                "group": group,
                "bullet": item["bullet"],
                "polarity": item["polarity"],
                "granularity": item["granularity"],
                "confidence": item.get("confidence", "unknown"),
                "reason": item["reason"],
                "span": span,
                "triage": None,
            }
            rows.append(row)
            by_bullet[row["bullet"]] += 1
            by_polarity[row["polarity"]] += 1
            by_granularity[row["granularity"]] += 1
            by_confidence[row["confidence"]] += 1

    out = CORPUS / f"candidates-{args.source}.jsonl"
    with out.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")

    bad = len(list(in_dir.glob("*.badjson")))
    print()
    print(f"result files {len(list(in_dir.glob('*.json')))}, "
          f"empty {empty_files}, unparseable replies {bad}, rejected items {malformed}")
    print(f"unique candidates {len(rows)} written to {out.relative_to(EVAL_ROOT)}")
    print()
    print("polarity     " + "  ".join(f"{k}={v}" for k, v in by_polarity.most_common()))
    print("granularity  " + "  ".join(f"{k}={v}" for k, v in by_granularity.most_common()))
    print("confidence   " + "  ".join(f"{k}={v}" for k, v in by_confidence.most_common()))
    print()
    for bullet, count in by_bullet.most_common():
        pres = sum(1 for r in rows if r["bullet"] == bullet and r["polarity"] == "preserve")
        print(f"  {count:5d}  ({pres} preserve)  {bullet[:64]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
