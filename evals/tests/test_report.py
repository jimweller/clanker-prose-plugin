import importlib.util
import io
import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout

SUITE = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("comply_report", SUITE / "tools" / "comply-report.py")
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)

SOURCE = "In today's world the team shipped it — and it scales. The job ran on no worker."


def finding(kind, rule, spans, p=3):
    m = p // 2 + 1
    votes = len({i for i, _ in spans})
    return {"pass": votes < m, "score": 0, "reason": "", "metadata": {"role": "finding", "judge_kind": "comply", "key": f"{kind}:{rule}", "rule": rule,
            "kind": kind, "votes": votes, "passes_total": p, "majority": votes >= m, "passes": [{"pass_index": i, "span": s, "why": "w"} for i, s in spans]}}


def scores(findings, klass, p=3):
    m = p // 2 + 1
    dirty = {x["pass_index"] for f in findings for x in f["metadata"]["passes"]}
    clean = p - len(dirty)
    def passes_with(kind):
        return len({x["pass_index"] for f in findings if f["metadata"]["kind"] == kind for x in f["metadata"]["passes"]})
    ns = {"cmp_judged": 1, "cmp_judge_error": 0, "cmp_passes": p, "cmp_pass_clean": clean, "cmp_clean_maj": int(clean >= m),
          "cmp_clean_union": int(clean == p), "cmp_pass_agree": int(clean in (0, p)),
          "cmp_viol_maj": int(passes_with("violation") >= m), "cmp_over_maj": int(passes_with("over-applied") >= m), "comply_clean": int(clean >= m)}
    for c in ("good", "mixed", "slop"):
        ns[f"cmp_judged_{c}"] = int(c == klass)
        ns[f"cmp_clean_maj_{c}"] = int(c == klass and clean >= m)
    return ns


def row(case, findings, klass="mixed", notes="", rewrite="The team shipped it.", cached=False):
    comps = [{"pass": True, "score": 1, "reason": "cmp"},
             {"pass": True, "score": 1, "reason": "judge run metadata", "metadata": {"role": "judge", "judge_kind": "comply", "kind": "comply", "cost_total": 0.3}},
             *findings]
    return {"provider": {"label": "comply"}, "success": True, "testCase": {"description": case, "vars": {"passage": SOURCE, "expect": klass}},
            "vars": {"passage": SOURCE, "expect": klass},
            "response": {"output": rewrite, "cached": cached, "cost": 0.2, "metadata": {"task": "rewrite", "notes": notes, "notes_missing": notes == ""}},
            "gradingResult": {"pass": True, "namedScores": scores(findings, klass), "componentResults": comps}}


def doc(rows, tamper=None):
    sums = {}
    for r in rows:
        for k, v in ((r.get("gradingResult") or {}).get("namedScores") or {}).items():
            sums[k] = sums.get(k, 0) + v
    derived = dict(sums)
    for name, (num, den) in report.DERIVED.items():
        if sums.get(den):
            derived[name] = sums.get(num, 0) / sums[den]
    derived.update(tamper or {})
    return {"results": {"results": rows, "prompts": [{"provider": "comply", "metrics": {"namedScores": derived}}]}}


def run(data, *args):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(data, f)
    out = io.StringIO()
    with redirect_stdout(out):
        code = report.main([f.name, *args])
    return code, out.getvalue()


class BucketTest(unittest.TestCase):
    def rows(self):
        return [
            row("case-1", []),
            row("case-2", [finding("violation", "PC-emdashes", [(0, "it — and"), (1, "it — and")])], klass="slop",
                notes="NOT VIOLATED | PC-emdashes | it — and | kept\n"),
            row("case-3", [finding("violation", "PC-hype", [(0, "blazing"), (1, "blazing"), (2, "blazing")])], klass="good"),
            row("case-4", [finding("over-applied", "PC-synthetic-negation", [(0, "ran on no worker"), (2, "ran on no worker")])],
                notes="VIOLATED | PC-synthetic-negation | ran on no worker | did not run on any worker\n"),
            row("case-5", [finding("violation", "PC-generic-openings", [(1, "In today's world")])]),
        ]

    def test_buckets_rates_and_exit_zero(self):
        code, out = run(doc(self.rows()))
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"clean_maj_rate=0\.400")
        self.assertRegex(out, r"viol_maj_rate=0\.400")
        self.assertRegex(out, r"over_maj_rate=0\.200")
        self.assertRegex(out, r"held-then-violation\s+1")
        self.assertRegex(out, r"self-inflicted\s+1")
        self.assertRegex(out, r"fired-then-over-applied\s+1")
        self.assertRegex(out, r"good\s+1 rows, clean\s+0")

    def test_majority_drops_a_single_pass_finding(self):
        code, out = run(doc(self.rows()))
        self.assertNotIn("PC-generic-openings", out)

    def test_union_keeps_it(self):
        code, out = run(doc(self.rows()), "--findings", "union")
        self.assertIn("PC-generic-openings", out)
        self.assertRegex(out, r"unseen-violation\s+1")

    def test_mismatch_cached_and_judge_error_exit_one(self):
        self.assertEqual(run(doc(self.rows(), tamper={"clean_maj_rate": 0.99}))[0], 1)
        rows = self.rows()
        rows[0]["response"]["cached"] = True
        self.assertIn("CACHED", run(doc(rows))[1])
        rows = self.rows()
        rows.append({"provider": {"label": "comply"}, "success": False, "testCase": {"vars": {}}, "response": {"output": "x", "metadata": {}},
                     "gradingResult": {"reason": "JUDGE_ERROR: pass 0 unit whole: timeout", "namedScores": {"cmp_judge_error": 1}, "componentResults": []}})
        code, out = run(doc(rows))
        self.assertEqual(code, 1)
        self.assertIn("JUDGE_ERROR", out)

    def test_isolation_breach_exits_one(self):
        rows = self.rows() + [{"provider": {"label": "comply"}, "success": False, "error": "ISOLATION_BREACH: contract never loaded",
                               "response": {"error": "ISOLATION_BREACH: contract never loaded"}}]
        code, out = run(doc(rows))
        self.assertEqual(code, 1)
        self.assertIn("ISOLATION_BREACH", out)

    def test_a_row_inconsistent_with_its_findings_exits_one(self):
        rows = self.rows()
        rows[0]["gradingResult"]["componentResults"].append(finding("violation", "PC-hype", [(0, "x"), (1, "x")]))
        code, out = run(doc(rows))
        self.assertEqual(code, 1)
        self.assertIn("INCONSISTENT", out)

    def test_rows_that_expect_no_notes_do_not_count_as_missing(self):
        rows = self.rows()
        for r in rows:
            r["response"]["metadata"].update({"notes": "", "notes_missing": True, "notes_expected": False})
        code, out = run(doc(rows))
        self.assertIn("missing notes 0", out)

    def test_safeguard_refusals_are_counted(self):
        rows = self.rows()
        rows[0]["response"]["metadata"]["safeguard_refusals"] = 2
        rows[1]["response"]["metadata"]["safeguard_refusals"] = 1
        code, out = run(doc(rows))
        self.assertIn("safeguard refusals 3", out)

    def test_any_provider_error_exits_one(self):
        rows = self.rows() + [{"provider": {"label": "comply"}, "success": False, "failureReason": 2,
                               "error": "Error: Python error: startswith first arg must be bytes", "response": {}}]
        code, out = run(doc(rows))
        self.assertEqual(code, 1)
        self.assertIn("PROVIDER_ERROR", out)


class LegacyTest(unittest.TestCase):
    def test_legacy_artifacts_are_one_pass_rows(self):
        text = ("<<<REWRITE>>>\nThe team shipped it.\n<<<NOTES>>>\nVIOLATED | PC-emdashes | — | period\n"
                "<<<FINDINGS>>>\nFINDING | violation | PC-hype | blazing fast | hype\nVERDICT violations=1 over-applied=0\n")
        rows = [{"provider": {"label": "comply"}, "success": True, "testCase": {"description": "c", "vars": {"passage": SOURCE, "expect": "slop"}},
                 "response": {"output": text, "cached": False}, "gradingResult": {"componentResults": []}},
                {"provider": {"label": "comply"}, "success": True, "testCase": {"description": "d", "vars": {"passage": SOURCE, "expect": "good"}},
                 "response": {"output": "<<<REWRITE>>>\nx\n<<<NOTES>>>\nNO NOTES FILE\n<<<FINDINGS>>>\nVERDICT violations=0 over-applied=0\n", "cached": False},
                 "gradingResult": {"componentResults": []}}]
        code, out = run({"results": {"results": rows, "prompts": []}})
        self.assertEqual(code, 0, out)
        self.assertIn("adapter=legacy", out)
        self.assertRegex(out, r"clean_maj_rate=0\.500")
        self.assertRegex(out, r"missing notes 1")
        self.assertRegex(out, r"self-inflicted\s+1")


if __name__ == "__main__":
    unittest.main()
