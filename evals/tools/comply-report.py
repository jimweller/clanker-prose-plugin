#!/usr/bin/env python3
"""Triages a compliance run by diffing the editor's notes against the judge's findings.

The two enumerations disagree in four distinct ways, and each one points at a
different repair in the contract. That is the whole reason both sides enumerate.

    fired-then-over-applied   The editor applied rule R and the judge says
                              an exemption covered the span. The exemption is
                              too weak, or its markers read as an unconditional
                              ban.

    held-then-violation       The editor declined to apply R on an exemption and
                              the judge says the exemption did not reach. The
                              exemption is too broad.

    unseen-violation          The judge cites R and R appears nowhere in the
                              trace. The editor never noticed, so R's markers
                              are incomplete or the rule is not reaching it.

    self-inflicted            The violating span is absent from the original, so
                              the rewrite created it. The highest-value class,
                              because the contract caused the defect it bans.

Cases where the judge reported nothing need no reading and are counted only.

Usage
    tools/comply-report.py RESULT_JSON [--show N] [--rule NAME]
"""

import argparse
import collections
import json
import pathlib
import re
import sys

SECTION = re.compile(r"<<<(NOTES|REWRITE|FINDINGS)>>>")
VERDICT = re.compile(r"VERDICT\s+violations=(\d+)\s+over-applied=(\d+)", re.I)
EVAL_ROOT = pathlib.Path(__file__).resolve().parent.parent
BLOCK = re.compile(r"<prose-contract>(.*?)</prose-contract>", re.DOTALL)


def known_ids() -> set:
    """Every PC- id the contract defines, so an invented one is visible in the report.

    A rule named in free text could be wrong in a way nothing detected. An id either
    exists or it does not, so a judge citing PC-something-plausible now surfaces as an
    unknown rather than as a finding against a rule that was never written.
    """
    contract = EVAL_ROOT.parent / "skills" / "prose" / "SKILL.md"
    blocks = BLOCK.findall(contract.read_text())
    if len(blocks) != 1:
        raise LookupError(f"expected 1 <prose-contract> block, found {len(blocks)}")
    return set(re.findall(r"^- `(PC-[a-z0-9-]+)`", blocks[0], re.MULTILINE))


def norm(rule: str) -> str:
    """Rules are named by PC- id now, so matching is exact rather than fuzzy.

    Before ids this stripped case and punctuation to reconcile two sessions naming one
    rule differently, and it still could not merge a short name with a long one. One run
    scored `trailing supplements` and `trailing supplements that hang a second beat on a
    finished clause` as two rules at 3 each instead of one at 6, and did that to three
    rules. Case folding is all that remains, because an id is already canonical.
    """
    return rule.strip().lower()


def split_artifact(text: str) -> dict:
    parts, last, pos = {}, None, 0
    for m in SECTION.finditer(text):
        if last:
            parts[last] = text[pos:m.start()].strip()
        last, pos = m.group(1), m.end()
    if last:
        parts[last] = text[pos:].strip()
    return parts


def parse_trace(block: str):
    """Reads the editor's notes, which it writes to a file rather than to stdout.

    Keeping notes out of stdout matters twice. The judge grades only the rewrite, and
    the rewrite is what a real `/prose` run prints, so the measured artifact is the
    real one. An earlier version had the editor print its reasoning inline, which the
    judge then graded as prose.
    """
    fired, held, malformed = {}, {}, "NO NOTES FILE" in block
    for line in block.splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 3:
            continue
        # FIRED and HELD are the older tags. Runs stored before the prompt switched
        # to plain language still parse, so a baseline stays comparable.
        tag = cells[0].upper()
        if tag in ("VIOLATED", "FIRED"):
            fired[norm(cells[1])] = cells[1]
        elif tag in ("NOT VIOLATED", "HELD"):
            held[norm(cells[1])] = cells[1]
    return fired, held, malformed


def parse_findings(block: str):
    out = []
    for line in block.splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 4 or cells[0].upper() != "FINDING":
            continue
        kind = cells[1].lower()
        if kind not in ("violation", "over-applied"):
            continue
        out.append({"kind": kind, "rule": cells[2], "span": cells[3].strip('"'),
                    "why": cells[4] if len(cells) > 4 else ""})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("result_json")
    ap.add_argument("--show", type=int, default=3, help="examples per bucket")
    ap.add_argument("--rule", help="only this rule id")
    args = ap.parse_args()

    rows = (json.loads(pathlib.Path(args.result_json).read_text())
            .get("results") or {}).get("results") or []
    if not rows:
        print("no results", file=sys.stderr)
        return 1

    ids = known_ids()
    buckets = collections.defaultdict(list)
    per_rule = collections.defaultdict(collections.Counter)
    unknown = collections.Counter()
    n = clean = malformed_n = unparsed = 0
    viol_total = over_total = 0

    # One judge pass finds roughly 39 percent of what a second pass on the same text
    # finds, measured by re-judging 48 stored rewrites with the same model and
    # settings. Counting every occurrence therefore scores a defect caught in all
    # three repeats at 3 and one caught once at 1, which ranks by how reliably the
    # judge notices a rule rather than by how often the editor breaks it.
    #
    # Deduplicating on case, rule and kind takes the union across repeats instead.
    # Precision is already good, since 8 of 9 findings read by hand against source
    # and rewrite were correct, so the union raises recall without adding false
    # positives. Three passes at a 39 percent per-pass rate reach roughly 78 percent.
    #
    # Case-level clean rate is unaffected and stays the most reliable number here,
    # agreeing 81 percent across two identical judge runs.
    seen_findings = set()
    repeats = collections.Counter()
    # comply.csv carries genre since the selection started recording provenance.
    # Meeting minutes are AI-transcribed attributed speech rather than authored
    # prose, and they score differently, so they are reported apart rather than
    # averaged into the headline.
    by_genre = collections.defaultdict(lambda: [0, 0])

    # The editor's notes vary between repeats the same way the judge's findings do,
    # so bucketing a deduped finding against one arbitrary run's notes loses the
    # trace. Union the notes per case first, then a rule counts as considered if the
    # editor mentioned it on any pass.
    notes_fired = collections.defaultdict(dict)
    notes_held = collections.defaultdict(dict)
    for r in rows:
        out = ((r.get("response") or {}).get("output") or "")
        if not isinstance(out, str) or "<<<FINDINGS>>>" not in out:
            continue
        v = (r.get("testCase") or {}).get("vars") or {}
        case = v.get("__description") or (r.get("testCase") or {}).get("description") or "?"
        f, h, _ = parse_trace(split_artifact(out).get("NOTES", ""))
        notes_fired[case].update(f)
        notes_held[case].update(h)

    for r in rows:
        out = ((r.get("response") or {}).get("output") or "")
        if not isinstance(out, str) or "<<<FINDINGS>>>" not in out:
            unparsed += 1
            continue
        n += 1
        case = ((r.get("testCase") or {}).get("vars") or {}).get("__description") \
            or (r.get("testCase") or {}).get("description") or "?"
        parts = split_artifact(out)
        source = ((r.get("testCase") or {}).get("vars") or {}).get("passage", "")
        _, _, malformed = parse_trace(parts.get("NOTES", ""))
        malformed_n += malformed
        fired, held = notes_fired[case], notes_held[case]
        findings = parse_findings(parts.get("FINDINGS", ""))

        # "expect" records the judgment a reader should reach on the source, so
        # restraint and repair score separately. `good` is prose already written to
        # the contract, where a rewrite should change almost nothing.
        v = (r.get("testCase") or {}).get("vars") or {}
        klass = v.get("expect") or v.get("genre")
        if klass:
            by_genre[klass][0] += 1
            if not findings:
                by_genre[klass][1] += 1

        if not findings:
            clean += 1
            continue

        for f in findings:
            key = norm(f["rule"])
            if args.rule and args.rule.lower() not in f["rule"].lower():
                continue
            dedupe = (case, key, f["kind"])
            repeats[dedupe] += 1
            if dedupe in seen_findings:
                continue
            seen_findings.add(dedupe)
            if f["kind"] == "over-applied":
                over_total += 1
                bucket = "fired-then-over-applied" if key in fired else "over-applied-untraced"
            else:
                viol_total += 1
                span = f["span"].strip()
                if span and span not in source:
                    bucket = "self-inflicted"
                elif key in held:
                    bucket = "held-then-violation"
                elif key in fired:
                    bucket = "fired-then-violation"
                else:
                    bucket = "unseen-violation"
            if f["rule"] not in ids:
                unknown[f["rule"]] += 1
            per_rule[f["rule"]][bucket] += 1
            buckets[bucket].append((case, f))

    print(f"runs parsed {n}, clean runs {clean} ({clean / n * 100:.0f}%), "
          f"missing notes {malformed_n}, unparsed {unparsed}")
    if by_genre:
        for g in sorted(by_genre):
            gn, gc = by_genre[g]
            print(f"  {g:<8} {gn:>3} runs, clean {gc:>3} ({gc / gn * 100:.0f}%)")
    print(f"distinct findings, deduped across repeats: "
          f"violations {viol_total}, over-applications {over_total}")
    if repeats:
        once = sum(1 for v in repeats.values() if v == 1)
        print(f"reproducibility: {len(repeats)} distinct findings, "
              f"{once} seen in only one pass ({once / len(repeats) * 100:.0f}%)")
    if unknown:
        print(f"\n{sum(unknown.values())} findings cite an id the contract does not define:")
        for rid, k in unknown.most_common(10):
            print(f"  {k:>3}  {rid!r}")
    print()

    order = ["self-inflicted", "fired-then-over-applied", "held-then-violation",
             "unseen-violation", "fired-then-violation", "over-applied-untraced"]
    print("bucket                     n")
    for b in order:
        if buckets[b]:
            print(f"{b:<26} {len(buckets[b])}")

    print("\nrules by total findings")
    ranked = sorted(per_rule.items(), key=lambda kv: -sum(kv[1].values()))
    for rule, counts in ranked[:15]:
        detail = " ".join(f"{k}={v}" for k, v in counts.most_common())
        print(f"{sum(counts.values()):>3}  {rule}  [{detail}]")

    for b in order:
        if not buckets[b]:
            continue
        print(f"\n--- {b} ---")
        for case, f in buckets[b][:args.show]:
            print(f"[{case}] {f['rule']}")
            print(f"    span  {f['span'][:160]}")
            print(f"    why   {f['why'][:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
