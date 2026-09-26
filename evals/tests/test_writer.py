import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

SUITE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUITE / "providers"))
import writer  # noqa: E402

SKILL = str(SUITE.parent / "skills" / "prose" / "SKILL.md")


def init(plugins=("clanker-prose",), skills=("clanker-prose:prose",), tools=("Read", "Skill", "Write"), path=None):
    return {"type": "system", "subtype": "init", "plugins": [{"name": p, "path": path or str(writer.PLUGIN_ROOT)} for p in plugins], "skills": list(skills),
            "tools": list(tools), "mcp_servers": [], "output_style": "default"}


def hook(event, code=0):
    return [{"type": "system", "subtype": "hook_started", "hook_event": event},
            {"type": "system", "subtype": "hook_response", "hook_event": event, "exit_code": code}]


def skill_call(name="clanker-prose:prose", tid="s1", error=False):
    return [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": "Skill", "input": {"skill": name}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "is_error": error, "content": "Launching skill"}]}}]


def read_call(path=SKILL, tid="r1", error=False):
    return [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": "Read", "input": {"file_path": path}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "is_error": error, "content": "..."}]}}]


def result(text="The build fails on Windows.", cost=0.2, is_error=False, subtype="success"):
    return {"type": "result", "subtype": subtype, "is_error": is_error, "result": text, "total_cost_usd": cost, "duration_ms": 5000,
            "num_turns": 3, "usage": {"input_tokens": 5, "cache_creation_input_tokens": 200, "cache_read_input_tokens": 2000, "output_tokens": 80},
            "modelUsage": {"claude-opus-5-5[1m]": {}}}


def stream(*parts):
    lines = []
    for p in parts:
        lines.extend(p if isinstance(p, list) else [p])
    return "\n".join(json.dumps(e) for e in lines) + "\n"


def ok_stream(text="The build fails on Windows.", load=None):
    return stream(hook("SessionStart"), init(), load if load is not None else skill_call(), result(text))


class FakeRunner:
    def __init__(self, stdout, code=0, timed_out=False, notes="VIOLATED | PC-emdashes | -- | a period\n"):
        self.stdout, self.code, self.timed_out, self.notes = stdout, code, timed_out, notes
        self.calls = []

    def __call__(self, argv, *, input, cwd, env, timeout_s):
        self.calls.append({"argv": argv, "input": input, "cwd": cwd, "env": env})
        m = re.search(r"write your notes to (\S+?),", input)
        if m and self.notes is not None:
            pathlib.Path(m.group(1)).write_text(self.notes)
        return self.code, self.stdout, "", self.timed_out


def call(runner, task="rewrite", environ=None, **config):
    notes_dir = tempfile.mkdtemp()
    env = {"PATH": "/bin", "HOME": "/h", "REWRITE_NOTES_DIR": notes_dir}
    env.update(environ or {})
    r = writer.call_api("The build passes -- it fails on Windows.", {"config": {"task": task, **config}}, {"vars": {}},
                        runner=runner, environ=env, settings_path="/no/such/settings.json")
    return r, notes_dir


class ArgvTest(unittest.TestCase):
    def test_writer_loads_only_the_prose_plugin_with_read_skill_write(self):
        argv = writer.build_argv("opus", "/plugin")
        self.assertNotIn("--bare", argv)
        self.assertNotIn("--settings", argv)
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        self.assertEqual(argv[argv.index("--plugin-dir") + 1], "/plugin")
        # Restricting the tool set with --tools made the opus 5.5 safeguard refuse the
        # rewrite prompt with reasoning_extraction on 4 of 8 runs of one case, and 0 of 8
        # without it, so the writer keeps the default tools and pre-approves three.
        self.assertNotIn("--tools", argv)
        self.assertEqual(argv[argv.index("--allowedTools") + 1], "Read,Skill,Write")
        self.assertEqual(argv[-1], "--no-session-persistence")

    def test_only_aliases_are_models(self):
        with self.assertRaises(ValueError):
            writer.check_alias("claude-opus-5-5")


class GlyphTest(unittest.TestCase):
    CASES = [
        "✳️ 🖋️ The build fails.\nSecond line ✳️ stays.\n",
        "🖋️\nThe build fails.\n",
        "The build fails — on Windows.\n",
        "  ✳️ indented first line\n",
        "✳️",
        "",
        "✳️🖋️The build.\n",
        "Ünïcode first letter stays? No, it goes.\n",
    ]

    def test_matches_the_perl_strip_byte_for_byte(self):
        for text in self.CASES:
            perl = subprocess.run(["perl", "-CSD", "-pe", r"if ($. == 1) { s/^(?:[^\x00-\x7F]+\s*)+// }"],
                                  input=text.encode(), capture_output=True, check=True).stdout.decode()
            self.assertEqual(writer.strip_glyph(text), perl, repr(text))


class WriterTest(unittest.TestCase):
    def test_rewrite_runs_the_notes_prompt_and_returns_the_stripped_edit(self):
        runner = FakeRunner(ok_stream("✳️ 🖋️ The build fails on Windows."))
        r, notes_dir = call(runner)
        self.assertNotIn("error", r)
        self.assertEqual(r["output"], "The build fails on Windows.")
        self.assertEqual(r["cost"], 0.2)
        self.assertEqual(r["tokenUsage"]["prompt"], 2205)
        sent = runner.calls[0]["input"]
        self.assertIn("Use the prose skill to rewrite the text between the markers.", sent)
        self.assertIn("The build passes -- it fails on Windows.", sent)
        m = r["metadata"]
        self.assertEqual(m["task"], "rewrite")
        self.assertTrue(m["contract_loaded"])
        self.assertEqual(m["contract_via"], "Skill")
        self.assertFalse(m["notes_missing"])
        self.assertEqual(m["notes"], "VIOLATED | PC-emdashes | -- | a period\n")
        self.assertRegex(pathlib.Path(m["notes_path"]).name, r"^[0-9a-f]{12}\.[0-9a-f]{8}\.txt$")
        self.assertEqual(str(pathlib.Path(m["notes_path"]).parent), notes_dir)
        self.assertIn("clanker-prose:prose", m["skills"])
        self.assertEqual(m["hook_fired"], {"SessionStart": 1})
        self.assertFalse(os.path.exists(runner.calls[0]["cwd"]))

    def test_the_writer_writes_notes_inside_its_own_working_directory(self):
        # Claude Code refuses a write inside a --plugin-dir directory as a sensitive file,
        # and corpus/notes sits inside the plugin, so the writer writes to its cwd and the
        # provider copies the file out afterward.
        runner = FakeRunner(ok_stream())
        r, notes_dir = call(runner)
        prompted = re.search(r"write your notes to (\S+?),", runner.calls[0]["input"]).group(1)
        self.assertEqual(str(pathlib.Path(prompted).parent), runner.calls[0]["cwd"])
        self.assertEqual(pathlib.Path(prompted).name, pathlib.Path(r["metadata"]["notes_path"]).name)
        self.assertTrue(pathlib.Path(r["metadata"]["notes_path"]).is_file())

    def test_generate_uses_the_notes_free_generation_prompt(self):
        # The opus 5.5 safeguard refuses the notes version with reasoning_extraction.
        runner = FakeRunner(ok_stream(load=read_call()))
        r, _ = call(runner, task="generate")
        self.assertNotIn("error", r)
        sent = runner.calls[0]["input"]
        self.assertIn("Write one paragraph presenting the facts between the markers", sent)
        self.assertNotIn("notes", sent)
        self.assertEqual(r["metadata"]["contract_via"], "Read")
        self.assertFalse(r["metadata"]["notes_expected"])
        self.assertTrue(r["metadata"]["notes_missing"])

    def test_rewrite_expects_notes(self):
        r, _ = call(FakeRunner(ok_stream()))
        self.assertTrue(r["metadata"]["notes_expected"])

    def test_missing_notes_are_recorded_not_fatal(self):
        r, _ = call(FakeRunner(ok_stream(), notes=None))
        self.assertNotIn("error", r)
        self.assertTrue(r["metadata"]["notes_missing"])
        self.assertEqual(r["metadata"]["notes"], "")

    def test_two_runs_of_one_source_get_different_notes_files(self):
        a, _ = call(FakeRunner(ok_stream()))
        b, _ = call(FakeRunner(ok_stream()))
        self.assertEqual(pathlib.Path(a["metadata"]["notes_path"]).name[:12], pathlib.Path(b["metadata"]["notes_path"]).name[:12])
        self.assertNotEqual(pathlib.Path(a["metadata"]["notes_path"]).name, pathlib.Path(b["metadata"]["notes_path"]).name)

    def breach(self, stdout, pattern):
        r, _ = call(FakeRunner(stdout))
        self.assertRegex(r.get("error", ""), r"^ISOLATION_BREACH")
        self.assertRegex(r["error"], pattern)

    def test_missing_plugin(self):
        self.breach(stream(hook("SessionStart"), init(plugins=()), skill_call(), result()), "plugin")

    def test_a_plugin_loaded_from_outside_the_clone_is_a_breach(self):
        # The installed copy carries the same name, so only the path tells it from the clone.
        cache = "/Users/x/.claude/plugins/cache/jimweller/clanker-prose/0.1.0"
        r, _ = call(FakeRunner(stream(hook("SessionStart"), init(path=cache), skill_call(), result())))
        self.assertRegex(r.get("error", ""), r"^ISOLATION_BREACH.*plugins/cache")
        self.assertEqual(r["metadata"]["plugin_paths"], [cache])
        self.assertEqual(r["metadata"]["plugin_dir"], str(writer.PLUGIN_ROOT))

    def test_missing_session_start(self):
        self.breach(stream(init(), skill_call(), result()), "SessionStart")

    def test_missing_skill(self):
        self.breach(stream(hook("SessionStart"), init(skills=()), skill_call(), result()), "skill")

    def not_loaded(self, stdout):
        r, _ = call(FakeRunner(stdout))
        self.assertNotIn("error", r)
        self.assertFalse(r["metadata"]["contract_loaded"])
        self.assertIsNone(r["metadata"]["contract_via"])

    def test_an_unloaded_contract_is_recorded_not_a_breach(self):
        # Whether the writer follows the SessionStart pointer or the skill is plugin
        # behavior the eval measures, so it lands in metadata and the clean rate.
        self.not_loaded(stream(hook("SessionStart"), init(), result()))

    def test_a_failed_skill_load_is_not_a_loaded_contract(self):
        self.not_loaded(stream(hook("SessionStart"), init(), skill_call(error=True), result()))

    def test_a_different_skill_is_not_the_contract(self):
        self.not_loaded(stream(hook("SessionStart"), init(), skill_call(name="md-style"), result()))

    def refusal(self):
        return stream(init(), result("API Error: Opus 5.5 (1M context)'s safeguards flagged this message. Details: `[reasoning_extraction]`", is_error=True))

    def test_a_safeguard_refusal_is_retried_in_a_new_session_and_counted(self):
        outs = [self.refusal(), ok_stream()]
        runner = FakeRunner(None)
        runner.stdout_seq = outs
        def seq(argv, **kw):
            runner.stdout = runner.stdout_seq.pop(0)
            return FakeRunner.__call__(runner, argv, **kw)
        r, _ = call(seq)
        self.assertNotIn("error", r)
        self.assertEqual(r["metadata"]["safeguard_refusals"], 1)
        self.assertEqual(len(runner.calls), 2)
        self.assertNotEqual(runner.calls[0]["cwd"], runner.calls[1]["cwd"])

    def test_refusals_past_the_retry_budget_are_a_writer_error(self):
        runner = FakeRunner(self.refusal())
        r, _ = call(runner)
        self.assertRegex(r["error"], r"^WRITER_ERROR: .*reasoning_extraction")
        self.assertEqual(r["metadata"]["safeguard_refusals"], 3)
        self.assertEqual(len(runner.calls), 3)

    def test_other_writer_errors_are_not_retried(self):
        runner = FakeRunner(stream(init(), result("rate limited", is_error=True)))
        r, _ = call(runner)
        self.assertRegex(r["error"], r"^WRITER_ERROR: is_error")
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(r["metadata"]["safeguard_refusals"], 0)

    def test_a_runner_exception_is_a_writer_error(self):
        def boom(argv, **kw):
            raise OSError("claude not found")
        r, _ = call(boom)
        self.assertRegex(r["error"], r"^WRITER_ERROR: .*claude not found")

    def test_run_claude_returns_text_on_timeout(self):
        code, out, err, timed_out = writer.run_claude(["-c", "printf partial; sleep 5"], input="", cwd=tempfile.mkdtemp(),
                                                     env={"PATH": "/bin:/usr/bin"}, timeout_s=0.5, binary="sh")
        self.assertTrue(timed_out)
        self.assertEqual(out, "partial")

    def test_writer_error_keeps_the_stream_tail(self):
        r, _ = call(FakeRunner(stream(init()), code=1))
        self.assertIn("system", r["metadata"]["stream_tail"])

    def test_writer_errors(self):
        self.assertRegex(call(FakeRunner("", code=1))[0]["error"], r"^WRITER_ERROR: exit 1")
        self.assertRegex(call(FakeRunner("", code=None, timed_out=True))[0]["error"], r"^WRITER_ERROR: timeout")
        self.assertRegex(call(FakeRunner(stream(init(), result("x", is_error=True))))[0]["error"], r"^WRITER_ERROR: is_error")
        self.assertRegex(call(FakeRunner(stream(init())))[0]["error"], r"^WRITER_ERROR: no result")
        self.assertRegex(call(FakeRunner(ok_stream()), task="summarize")[0]["error"], r"^WRITER_ERROR: .*task")
        self.assertRegex(call(FakeRunner(ok_stream()), environ={"EVAL_MODEL": "gpt-6"})[0]["error"], r"^WRITER_ERROR: .*alias")


if __name__ == "__main__":
    unittest.main()
