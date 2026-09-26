#!/usr/bin/env python3
"""Triages a compliance or generation run by diffing the editor's notes against the judge's findings.

The two enumerations disagree in distinct ways, and each one points at a different repair.

    fired-then-over-applied   The editor applied rule R and the judge says an exemption
                              covered the span. The exemption is too weak, or its markers
                              read as an unconditional ban.
    held-then-violation       The editor declined R on an exemption and the judge says the
                              exemption did not reach. The exemption is too broad.
    unseen-violation          The judge cites R and R appears nowhere in the notes. R's
                              markers are incomplete or the rule is not reaching the span.
    self-inflicted            No span the judge quoted for R appears in the original, so the
                              rewrite created the defect. The contract caused what it bans.

Reads both shapes of run. A graded row carries the promptfoo judge's GradingResult, with
namedScores and one componentResults entry per finding key, and its notes in the provider
metadata. A legacy row carries the old exec provider's text artifact and is read as one pass.

Findings are per row. Each row is one rewrite, so the old union of findings across three
different rewrites of a case is gone. --findings maj (default) keeps the keys at least
floor(P/2)+1 judge passes reported, and --findings union keeps a key any pass reported.

For graded rows every rate is recomputed twice, from each row's findings against its own
namedScores and as column sums against promptfoo's derived metrics. The report exits 1 on
a mismatch, a cached row, a judge error, or a writer or isolation error.

Usage
    tools/comply-report.py RESULT_JSON [--findings maj|union] [--show N] [--rule PC-ID]
"""

import argparse
import collections
import json
import pathlib
import re

SECTION = re.compile(r"<<<(NOTES|REWRITE|FINDINGS)>>>")
EVAL_ROOT = pathlib.Path(__file__).resolve().parent.parent
# The tags sit on lines of their own. The skill's header names the tag inline, so an
# unanchored match would start there.
BLOCK = re.compile(r"^<prose-contract>\n(.*?)^</prose-contract>$", re.DOTALL | re.MULTILINE)
CLASSES = ("good", "mixed", "slop")
DERIVED = {
    "clean_maj_rate": ("cmp_clean_maj", "cmp_judged"),
    "clean_union_rate": ("cmp_clean_union", "cmp_judged"),
    "clean_pass_rate": ("cmp_pass_clean", "cmp_passes"),
    "pass_agree_rate": ("cmp_pass_agree", "cmp_judged"),
    "viol_maj_rate": ("cmp_viol_maj", "cmp_judged"),
    "over_maj_rate": ("cmp_over_maj", "cmp_judged"),
    **{f"clean_rate_{c}": (f"cmp_clean_maj_{c}", f"cmp_judged_{c}") for c in CLASSES},
}
ROW_ERRORS = ("ISOLATION_BREACH", "WRITER_ERROR")
ORDER = ["self-inflicted", "fired-then-over-applied", "held-then-violation", "unseen-violation", "fired-then-violation", "over-applied-untraced"]


def known_ids():
    contract = EVAL_ROOT.parent / "skills" / "prose" / "SKILL.md"
    blocks = BLOCK.findall(contract.read_text())
    if len(blocks) != 1:
        raise LookupError(f"expected 1 <prose-contract> block, found {len(blocks)}")
    return set(re.findall(r"^- `(PC-[a-z0-9-]+)`", blocks[0], re.MULTILINE))


def split_artifact(text):
    parts, last, pos = {}, None, 0
    for m in SECTION.finditer(text):
        if last:
            parts[last] = text[pos:m.start()].strip()
        last, pos = m.group(1), m.end()
    if last:
        parts[last] = text[pos:].strip()
    return parts


def parse_notes(block):
    fired, held = set(), set()
    for line in block.splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 3:
            continue
        tag = cells[0].upper()
        if tag in ("VIOLATED", "FIRED"):
            fired.add(cells[1].lower())
        elif tag in ("NOT VIOLATED", "HELD"):
            held.add(cells[1].lower())
    return fired, held


def parse_legacy_findings(block):
    out = []
    for line in block.splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 4 or cells[0].upper() != "FINDING" or cells[1].lower() not in ("violation", "over-applied"):
            continue
        out.append({"kind": cells[1].lower(), "rule": cells[2], "spans": [cells[3].strip('"')], "why": cells[4] if len(cells) > 4 else ""})
    return out


def vars_of(row):
    return (row.get("testCase") or {}).get("vars") or row.get("vars") or {}


def graded(row, mode):
    g = row.get("gradingResult") or {}
    scores = g.get("namedScores") or {}
    found = [c["metadata"] for c in g.get("componentResults") or []
             if (c.get("metadata") or {}).get("role") == "finding" and c["metadata"].get("judge_kind") == "comply"]
    problems = []
    if scores.get("cmp_judged"):
        p = scores["cmp_passes"]
        m = p // 2 + 1
        dirty = {x["pass_index"] for f in found for x in f["passes"]}
        by_kind = lambda k: len({x["pass_index"] for f in found if f["kind"] == k for x in f["passes"]})
        clean = p - len(dirty)
        expect = {"cmp_pass_clean": clean, "cmp_clean_maj": int(clean >= m), "cmp_clean_union": int(clean == p),
                  "cmp_pass_agree": int(clean in (0, p)), "cmp_viol_maj": int(by_kind("violation") >= m), "cmp_over_maj": int(by_kind("over-applied") >= m)}
        for k, v in expect.items():
            if scores.get(k, 0) != v:
                problems.append(f"INCONSISTENT {k}={scores.get(k)} but the findings give {v}")
    keep = [f for f in found if mode == "union" or f["majority"]]
    findings = [{"kind": f["kind"], "rule": f["rule"], "spans": [x["span"] for x in f["passes"]], "why": f["passes"][0]["why"], "votes": f["votes"]} for f in keep]
    meta = (row.get("response") or {}).get("metadata") or {}
    notes = meta.get("notes", "")
    return scores, findings, notes, bool(meta.get("notes_missing")) and meta.get("notes_expected", True), problems


def legacy(row):
    parts = split_artifact((row.get("response") or {}).get("output") or "")
    findings = parse_legacy_findings(parts.get("FINDINGS", ""))
    notes = parts.get("NOTES", "")
    clean = int(not findings)
    by = lambda k: int(any(f["kind"] == k for f in findings))
    scores = {"cmp_judged": 1, "cmp_passes": 1, "cmp_pass_clean": clean, "cmp_clean_maj": clean, "cmp_clean_union": clean,
              "cmp_pass_agree": 1, "cmp_viol_maj": by("violation"), "cmp_over_maj": by("over-applied")}
    klass = vars_of(row).get("expect")
    if klass in CLASSES:
        scores[f"cmp_judged_{klass}"] = 1
        scores[f"cmp_clean_maj_{klass}"] = clean
    return scores, findings, notes, "NO NOTES FILE" in notes, []


def is_graded(row):
    return any((c.get("metadata") or {}).get("role") == "judge" for c in (row.get("gradingResult") or {}).get("componentResults") or [])


def bucket(f, source, fired, held):
    key = f["rule"].lower()
    if f["kind"] == "over-applied":
        return "fired-then-over-applied" if key in fired else "over-applied-untraced"
    if all(s.strip() and s.strip() not in source for s in f["spans"]):
        return "self-inflicted"
    if key in held:
        return "held-then-violation"
    if key in fired:
        return "fired-then-violation"
    return "unseen-violation"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("result_json")
    ap.add_argument("--findings", choices=("maj", "union"), default="maj")
    ap.add_argument("--show", type=int, default=3, help="examples per bucket")
    ap.add_argument("--rule", help="only this rule id")
    args = ap.parse_args(argv)

    with open(args.result_json) as f:
        data = json.load(f)
    rows = data["results"]["results"]
    prompts = {p.get("provider"): (p.get("metrics") or {}).get("namedScores") or {} for p in data["results"].get("prompts") or []}
    ids = known_ids()

    cols = collections.OrderedDict()
    problems = []
    buckets = collections.defaultdict(list)
    per_rule = collections.defaultdict(collections.Counter)
    unknown = collections.Counter()
    for i, row in enumerate(rows):
        provider = row.get("provider") or {}
        label = provider.get("label") or provider.get("id") or "unknown"
        col = cols.setdefault(label, {"rows": 0, "adapters": set(), "sums": collections.Counter(), "missing_notes": 0,
                                      "writer_cost": 0.0, "judge_cost": 0.0})
        col["rows"] += 1
        resp = row.get("response") or {}
        # promptfoo also fills row.error with an assertion's failure reason, so only a row
        # that never reached grading is a provider error, whatever its text says.
        err = str(row.get("error") or resp.get("error") or "")
        if err and (not row.get("gradingResult") or row.get("failureReason") == 2):
            kind = next((e for e in ROW_ERRORS if err.startswith(e)), "PROVIDER_ERROR")
            problems.append(f"{kind} row {i} ({label}): {err[:300]}")
            continue
        if resp.get("cached"):
            problems.append(f"CACHED row {i} ({label})")
        g = row.get("gradingResult") or {}
        if (g.get("namedScores") or {}).get("cmp_judge_error") or str(g.get("reason", "")).startswith("JUDGE_ERROR"):
            problems.append(f"JUDGE_ERROR row {i} ({label}): {g.get('reason', '')}")
            continue
        adapter = "graded" if is_graded(row) else "legacy"
        col["adapters"].add(adapter)
        scores, findings, notes, notes_missing, row_problems = graded(row, args.findings) if adapter == "graded" else legacy(row)
        problems += [f"{p} (row {i}, {label})" for p in row_problems]
        col["sums"].update(scores)
        col["missing_notes"] += int(notes_missing)
        col["writer_cost"] += resp.get("cost") or 0
        col["judge_cost"] += sum((c.get("metadata") or {}).get("cost_total") or 0 for c in (row.get("gradingResult") or {}).get("componentResults") or []
                                 if (c.get("metadata") or {}).get("role") == "judge")
        v = vars_of(row)
        case = v.get("__description") or (row.get("testCase") or {}).get("description") or f"row {i}"
        fired, held = parse_notes(notes)
        for f in findings:
            if args.rule and args.rule.lower() != f["rule"].lower():
                continue
            if f["rule"] not in ids:
                unknown[f["rule"]] += 1
            b = bucket(f, v.get("passage", ""), fired, held)
            per_rule[f["rule"]][b] += 1
            buckets[b].append((case, f))

    for label, col in cols.items():
        s = col["sums"]
        rates = {name: (s[num] / s[den] if s[den] else None) for name, (num, den) in DERIVED.items()}
        if "graded" in col["adapters"]:
            derived = prompts.get(label, {})
            for name, value in rates.items():
                if value is None:
                    continue
                got = derived.get(name)
                if got is None or abs(got - value) > 1e-9:
                    problems.append(f"MISMATCH {label} {name}: recomputed {value:.6f}, promptfoo derived {got}")
        head = " ".join(f"{k}={v:.3f}" for k, v in rates.items() if v is not None and not k.startswith("clean_rate_"))
        print(f"== {label} ==  adapter={'+'.join(sorted(col['adapters'])) or 'none'} rows={col['rows']} judged={s['cmp_judged']} {head}")
        print(f"  missing notes {col['missing_notes']}  writer_cost=${col['writer_cost']:.2f}  judge_cost=${col['judge_cost']:.2f}")
        for c in CLASSES:
            if s[f"cmp_judged_{c}"]:
                print(f"  {c:<8}{s[f'cmp_judged_{c}']:>4} rows, clean {s[f'cmp_clean_maj_{c}']:>3} ({100 * s[f'cmp_clean_maj_{c}'] / s[f'cmp_judged_{c}']:.0f}%)")
    print(f"\nfindings ({args.findings})")
    print("bucket                     n")
    for b in ORDER:
        if buckets[b]:
            print(f"{b:<26} {len(buckets[b])}")
    if unknown:
        print(f"\n{sum(unknown.values())} findings cite an id the contract does not define:")
        for rid, k in unknown.most_common(10):
            print(f"  {k:>3}  {rid!r}")
    print("\nrules by total findings")
    for rule, counts in sorted(per_rule.items(), key=lambda kv: -sum(kv[1].values()))[:15]:
        print(f"{sum(counts.values()):>3}  {rule}  [{' '.join(f'{k}={v}' for k, v in counts.most_common())}]")
    for b in ORDER:
        if buckets[b]:
            print(f"\n--- {b} ---")
            for case, f in buckets[b][:args.show]:
                print(f"[{case}] {f['rule']}")
                print(f"    span  {f['spans'][0][:160]}")
                print(f"    why   {f['why'][:200]}")
    if problems:
        print()
    for p in problems:
        print(p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
