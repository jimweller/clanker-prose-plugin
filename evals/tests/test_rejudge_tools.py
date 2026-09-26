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


def legacy_row(reply, rules, label="with-plugin"):
    body = "\n".join(f"FINDING | {r.split(':')[0]} | {r.split(':')[1]} | s | w" for r in rules)
    text = f"<<<REWRITE>>>\n{reply}\n<<<NOTES>>>\nNO NOTES FILE\n<<<FINDINGS>>>\n{body}\nVERDICT violations={len(rules)} over-applied=0\n"
    return {"provider": {"label": label}, "vars": {"passage": "q", "expect": "mixed"}, "response": {"output": text}}


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

    def test_legacy_rows_contribute_only_the_reply_section(self):
        src = write({"results": {"results": [legacy_row("the reply", ["violation:PC-a"])]}})
        out = tempfile.mkdtemp() + "/tests.json"
        code, _ = capture(rejudge.main, [src, out])
        self.assertEqual(code, 0)
        self.assertEqual(json.load(open(out))[0]["providerOutput"], "the reply")

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

    def test_incumbent_compares_every_new_pass_to_the_old_verdict(self):
        new = write({"results": {"results": [graded_row("a", [[], [], ["violation:PC-b"]]), graded_row("b", [["violation:PC-a"], ["violation:PC-a"], ["violation:PC-a"]])]}})
        old = write({"results": {"results": [legacy_row("a", []), legacy_row("b", ["violation:PC-a", "violation:PC-c"])]}})
        code, text = capture(agreement.main, ["incumbent", new, "--legacy", old])
        self.assertEqual(code, 0)
        self.assertIn("matched 2 of 2", text)
        # row a: passes clean, clean, dirty vs clean: 2 of 3. row b: dirty x3 vs dirty: 3 of 3.
        self.assertIn("per-pass vs incumbent verdict agreement 5/6", text)
        # findings: a: pass2 {CR-b} vs {} -> 0 of 1. b: each pass {CR-a} vs {CR-a, CR-c} -> 1 of 2, three times.
        self.assertIn("finding agreement 3/7", text)

    def test_across_runs_matches_rows_by_reply(self):
        a = write({"results": {"results": [graded_row("x", [[], [], []]), graded_row("y", [["violation:PC-a"]] * 3)]}})
        b = write({"results": {"results": [graded_row("y", [[], [], ["violation:PC-a"]]), graded_row("x", [[], [], []])]}})
        code, text = capture(agreement.main, ["across", a, b])
        self.assertEqual(code, 0)
        self.assertIn("matched 2", text)
        self.assertIn("clean-majority agreement 1/2", text)

    def test_unmatched_rows_are_reported(self):
        a = write({"results": {"results": [graded_row("x", [[]] * 3)]}})
        b = write({"results": {"results": [graded_row("z", [[]] * 3)]}})
        code, text = capture(agreement.main, ["across", a, b])
        self.assertEqual(code, 1)
        self.assertIn("matched 0", text)


if __name__ == "__main__":
    unittest.main()
