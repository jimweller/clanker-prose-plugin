#!/usr/bin/env python3
"""Verifies hooks/inject.sh's pointer output, per Phase 0's rules-delivery redesign."""
import json
import os
import pathlib
import subprocess
import unittest

PLUGIN_ROOT = pathlib.Path(__file__).resolve().parent.parent
INJECT = PLUGIN_ROOT / "hooks" / "inject.sh"
SKILL_FILE = PLUGIN_ROOT / "skills" / "prose" / "SKILL.md"
CAP_BYTES = 2000  # measured additionalContext preview cap sits around 2 KB


class InjectTest(unittest.TestCase):
    def _run(self, event: str) -> dict:
        env = dict(os.environ, CLAUDE_PLUGIN_ROOT=str(PLUGIN_ROOT))
        out = subprocess.run(
            [str(INJECT), event], env=env, capture_output=True, text=True, check=True
        )
        return json.loads(out.stdout)

    def test_session_start_parses_and_stays_under_cap(self):
        payload = self._run("SessionStart")
        ctx = payload["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertLess(len(ctx), CAP_BYTES)
        self.assertIn(str(SKILL_FILE), ctx)

    def test_subagent_start_parses_and_stays_under_cap(self):
        payload = self._run("SubagentStart")
        ctx = payload["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "SubagentStart")
        self.assertLess(len(ctx), CAP_BYTES)
        self.assertIn(str(SKILL_FILE), ctx)

    def test_named_file_exists_and_is_the_contract(self):
        self.assertTrue(SKILL_FILE.is_file())
        self.assertIn("<prose-contract>", SKILL_FILE.read_text())

    def test_missing_skill_file_fails_loudly(self):
        env = dict(os.environ, CLAUDE_PLUGIN_ROOT="/nonexistent-plugin-root")
        result = subprocess.run(
            [str(INJECT), "SessionStart"], env=env, capture_output=True, text=True
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
