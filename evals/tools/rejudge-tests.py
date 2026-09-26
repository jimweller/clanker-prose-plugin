#!/usr/bin/env python3
"""Turns a prior promptfoo -o JSON into providerOutput tests for promptfooconfig.rejudge.yaml.

Each stored rewrite or composed paragraph becomes one test whose providerOutput is the reply, so the judge grades
text a writer already produced and the writer never runs again. A legacy row contributes
only its <<<REWRITE>>> section.

Rows that errored are skipped and counted. A row whose text is empty is refused and
nothing is written, because promptfoo treats an empty providerOutput as absent and calls
the provider instead, which here is the echo provider grading the source passage.

Usage
    tools/rejudge-tests.py RESULT_JSON [OUT_JSON]    (default corpus/rejudge/tests.json)
"""

import json
import pathlib
import re
import sys

REPLY_SECTION = "REWRITE"
JUDGE_KIND = "comply"
SECTION = re.compile(r"<<<([A-Z]+)>>>")
DEFAULT_OUT = pathlib.Path(__file__).resolve().parent.parent / "corpus" / "rejudge" / "tests.json"


def section(text, name):
    parts, last, pos = {}, None, 0
    for m in SECTION.finditer(text):
        if last:
            parts[last] = text[pos:m.start()]
        last, pos = m.group(1), m.end()
    if last:
        parts[last] = text[pos:]
    return parts.get(name)


def reply_of(row):
    output = (row.get("response") or {}).get("output") or ""
    legacy = section(output, REPLY_SECTION)
    return (legacy if legacy is not None else output).strip()


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
        if row.get("error") or (row.get("response") or {}).get("error"):
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
