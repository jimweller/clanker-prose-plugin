#!/usr/bin/env python3
"""Turns a prior promptfoo -o JSON into providerOutput tests for promptfooconfig.rejudge.yaml.

Each stored rewrite or composed paragraph becomes one test whose providerOutput is the reply, so the judge grades
text a writer already produced and the writer never runs again.

Rows that errored are skipped and counted. A row whose text is empty is refused and
nothing is written, because promptfoo treats an empty providerOutput as absent and calls
the provider instead, which here is the echo provider grading the source passage.

Usage
    tools/rejudge-tests.py RESULT_JSON [OUT_JSON]    (default corpus/rejudge/tests.json)
"""

import json
import pathlib
import sys

JUDGE_KIND = "comply"
DEFAULT_OUT = pathlib.Path(__file__).resolve().parent.parent / "corpus" / "rejudge" / "tests.json"


def reply_of(row):
    return ((row.get("response") or {}).get("output") or "").strip()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) not in (1, 2):
        print(__doc__, file=sys.stderr)
        return 2
    with open(argv[0]) as f:
        rows = json.load(f)["results"]["results"]
    out = pathlib.Path(argv[1]) if len(argv) == 2 else DEFAULT_OUT

    tests, empty, errors = [], [], 0
    for i, row in enumerate(rows):
        err = row.get("error") or (row.get("response") or {}).get("error")
        # promptfoo also fills row.error with a failed assertion's reason, so only a row
        # that never reached grading is an error.
        if err and (not row.get("gradingResult") or row.get("failureReason") == 2):
            errors += 1
            continue
        reply = reply_of(row)
        provider = row.get("provider") or {}
        label = provider.get("label") or provider.get("id") or "unknown"
        if not reply:
            empty.append(f"row {i} ({label})")
            continue
        vars_ = {k: v for k, v in (row.get("vars") or {}).items() if not k.startswith("__")}
        arm = ((row.get("response") or {}).get("metadata") or {}).get("arm") or vars_.get("arm") or label
        vars_.update({"arm": arm, "source_label": label, "source_row": i})
        tests.append({"description": f"{label} row {i}", "vars": vars_, "providerOutput": reply})

    if empty:
        print(f"refusing: {len(empty)} rows have empty output, which promptfoo would send to the provider: {', '.join(empty)}")
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(tests, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {len(tests)} tests to {out}; skipped {errors} error row{'s' if errors != 1 else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
