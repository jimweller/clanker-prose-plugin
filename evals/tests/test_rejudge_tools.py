import importlib.util
import io
import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout

SUITE = pathlib.Path(__file__).resolve().parent.parent


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, SUITE / "tools" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rejudge = load("rejudge_tests", "rejudge-tests.py")
agreement = load("judge_agreement", "judge-agreement.py")


def write(data):
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    return f.name


def capture(fn, argv):
    out = io.StringIO()
    with redirect_stdout(out):
        code = fn(argv)
    return code, out.getvalue()


def graded_row(reply, pass_findings, label="with-plugin", arm="with", p=3):
    keys = {}
    for i, fs in enumerate(pass_findings):
        for k in fs:
            keys.setdefault(k, []).append({"pass_index": i, "span": "s", "why": "w"})
    m = p // 2 + 1
    findings = [{"pass": len(v) < m, "score": 0, "reason": "", "metadata": {"role": "finding", "judge_kind": "comply", "key": k, "rule": k,
                 "votes": len({x["pass_index"] for x in v}), "passes_total": p, "majority": len({x["pass_index"] for x in v}) >= m, "passes": v}}
                for k, v in keys.items()]
    clean = sum(1 for fs in pass_findings if not fs)
    ns = {"comply_clean": int(clean >= m), "cmp_judged": 1, "cmp_passes": p, "cmp_pass_clean": clean, "cmp_clean_maj": int(clean >= m)}
    return {"provider": {"label": label}, "vars": {"passage": "q", "expect": "mixed", "__description": "d"},
            "response": {"output": reply, "metadata": {"arm": arm}},
            "gradingResult": {"namedScores": ns, "componentResults": [{"pass": True, "score": 1, "reason": "", "metadata": {"role": "judge", "judge_kind": "comply"}}, *findings]}}


class RejudgeTestsTest(unittest.TestCase):
    def test_graded_rows_become_provider_output_tests(self):
        src = write({"results": {"results": [graded_row("reply one", [[], [], []]), graded_row("reply two", [[], [], []], label="baseline", arm="baseline")]}})
        out = tempfile.mkdtemp() + "/tests.json"
        code, _ = capture(rejudge.main, [src, out])
        self.assertEqual(code, 0)
        tests = json.load(open(out))
        self.assertEqual([t["providerOutput"] for t in tests], ["reply one", "reply two"])
        self.assertEqual([t["vars"]["arm"] for t in tests], ["with", "baseline"])
        self.assertEqual(tests[0]["vars"]["passage"], "q")
        self.assertNotIn("__description", tests[0]["vars"])
        self.assertEqual(tests[0]["vars"]["source_label"], "with-plugin")

    def test_error_rows_are_skipped_and_counted(self):
        rows = [graded_row("ok", [[]] * 3), {"provider": {"label": "with-plugin"}, "error": "ISOLATION_BREACH: x", "response": {"error": "ISOLATION_BREACH: x"}}]
        out = tempfile.mkdtemp() + "/tests.json"
        code, text = capture(rejudge.main, [write({"results": {"results": rows}}), out])
        self.assertEqual(code, 0)
        self.assertEqual(len(json.load(open(out))), 1)
        self.assertIn("skipped 1 error row", text)

    def test_an_empty_reply_is_refused_and_nothing_is_written(self):
        rows = [graded_row("ok", [[]] * 3), graded_row("   ", [[]] * 3)]
        out = tempfile.mkdtemp() + "/tests.json"
        code, text = capture(rejudge.main, [write({"results": {"results": rows}}), out])
        self.assertEqual(code, 1)
        self.assertIn("empty output", text)
        self.assertFalse(pathlib.Path(out).exists())


class AgreementTest(unittest.TestCase):
    def test_within_run_pass_pairs(self):
        rows = [graded_row("a", [[], [], []]), graded_row("b", [["violation:PC-a"], ["violation:PC-a"], []])]
        code, text = capture(agreement.main, ["within", write({"results": {"results": rows}})])
        self.assertEqual(code, 0)
        # row a: 3 agreeing pairs. row b: (0,1) agree, (0,2) and (1,2) disagree. 4 of 6.
        self.assertIn("pass-vs-pass clean agreement 4/6", text)
        # finding pairs: row b has (0,1) agree on CR-a, (0,2) and (1,2) each one-sided. 1 of 3.
        self.assertIn("finding agreement 1/3", text)

    def test_across_runs_matches_rows_by_reply(self):
        a = write({"results": {"results": [graded_row("x", [[], [], []]), graded_row("y", [["violation:PC-a"]] * 3)]}})
        b = write({"results": {"results": [graded_row("y", [[], [], ["violation:PC-a"]]), graded_row("x", [[], [], []])]}})
        code, text = capture(agreement.main, ["across", a, b])
        self.assertEqual(code, 0)
        self.assertIn("matched 2", text)
        self.assertIn("clean-majority agreement 1/2", text)

    def test_across_runs_compares_majority_findings(self):
        a = write({"results": {"results": [graded_row("x", [["violation:PC-a", "violation:PC-b"], ["violation:PC-a", "violation:PC-b"], ["violation:PC-a"]]),
                                           graded_row("y", [["violation:PC-c"]] * 3)]}})
        b = write({"results": {"results": [graded_row("x", [["violation:PC-a"], ["violation:PC-a"], ["violation:PC-d"]]),
                                           graded_row("y", [["violation:PC-c", "violation:PC-d"]] * 3)]}})
        code, text = capture(agreement.main, ["across", a, b])
        self.assertEqual(code, 0)
        # x: majority {a, b} vs {a}. y: {c} vs {c, d}. PC-d in x is one pass of three, so no majority.
        self.assertIn("majority findings agree 2  a-only 1  b-only 1", text)
        self.assertIn("majority finding agreement 2/4", text)
        self.assertRegex(text, r"violation:PC-b\s+0\s+1\s+0")
        self.assertRegex(text, r"violation:PC-d\s+0\s+0\s+1")

    def test_unmatched_rows_are_reported(self):
        a = write({"results": {"results": [graded_row("x", [[]] * 3)]}})
        b = write({"results": {"results": [graded_row("z", [[]] * 3)]}})
        code, text = capture(agreement.main, ["across", a, b])
        self.assertEqual(code, 1)
        self.assertIn("matched 0", text)


if __name__ == "__main__":
    unittest.main()
