"""
End-to-end smoke tests: invoke the actual scripts as subprocesses against a
throwaway git repo, the way a real user would. No mocking -- these are
deliberately slower and fewer than the unit tests, to catch wiring mistakes
the unit tests (which import modules directly) wouldn't.

  python3 -m unittest discover -s tests -v
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

KIT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(cmd, cwd=None, input_text=None, timeout=30):
    return subprocess.run(cmd, cwd=cwd, input=input_text, capture_output=True,
                           text=True, timeout=timeout)


class TempRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = self._tmp.name
        run(["git", "init", "-q", "."], cwd=self.repo)

    def tearDown(self):
        self._tmp.cleanup()


class TestInstallPy(TempRepo):
    def test_install_copies_expected_files(self):
        r = run([sys.executable, os.path.join(KIT_ROOT, "install.py"), self.repo], timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        for rel in ("AGENTS.md", "SETUP.md", "SECURITY.md",
                    ".agent/skills/session-memory/memory.py",
                    ".agent/skills/tool-provisioning/toolkit.py",
                    ".agent/skills/dev-recap/recap_log.py"):
            self.assertTrue(os.path.exists(os.path.join(self.repo, rel)), rel)

    def test_install_is_idempotent_without_force(self):
        run([sys.executable, os.path.join(KIT_ROOT, "install.py"), self.repo])
        r = run([sys.executable, os.path.join(KIT_ROOT, "install.py"), self.repo])
        self.assertEqual(r.returncode, 0)
        self.assertIn("skipped", r.stdout)

    def test_wire_hooks_flag_merges_settings_and_is_idempotent(self):
        run([sys.executable, os.path.join(KIT_ROOT, "install.py"), self.repo, "--wire-hooks"])
        settings_path = os.path.join(self.repo, ".claude", "settings.json")
        self.assertTrue(os.path.exists(settings_path))
        with open(settings_path) as fh:
            settings = json.load(fh)
        self.assertIn("SessionStart", settings["hooks"])
        self.assertIn("UserPromptSubmit", settings["hooks"])
        self.assertIn("Stop", settings["hooks"])

        # re-run: must not duplicate entries
        run([sys.executable, os.path.join(KIT_ROOT, "install.py"), self.repo, "--wire-hooks", "--force"])
        with open(settings_path) as fh:
            settings2 = json.load(fh)
        self.assertEqual(len(settings2["hooks"]["SessionStart"]), 1)

    def test_refuses_to_install_into_kit_itself(self):
        r = run([sys.executable, os.path.join(KIT_ROOT, "install.py"), KIT_ROOT])
        self.assertNotEqual(r.returncode, 0)


class TestSessionMemoryHooksAcrossSessions(TempRepo):
    def setUp(self):
        super().setUp()
        run([sys.executable, os.path.join(KIT_ROOT, "install.py"), self.repo])
        self.hooks = os.path.join(self.repo, ".agent", "skills", "session-memory", "hooks")

    def test_second_session_recalls_first_sessions_prompt(self):
        payload_a = json.dumps({
            "session_id": "sessA", "cwd": self.repo,
            "prompt": "how do I configure the retry policy for the payment webhook",
        })
        r = run([sys.executable, os.path.join(self.hooks, "user_prompt_submit.py")],
                cwd=self.repo, input_text=payload_a)
        self.assertEqual(r.returncode, 0)

        payload_b = json.dumps({
            "session_id": "sessB", "cwd": self.repo,
            "prompt": "remind me about the retry policy for the payment webhook",
        })
        r = run([sys.executable, os.path.join(self.hooks, "user_prompt_submit.py")],
                cwd=self.repo, input_text=payload_b)
        self.assertEqual(r.returncode, 0)
        self.assertTrue(r.stdout.strip(), "expected additionalContext for a lexically similar prompt")
        out = json.loads(r.stdout)
        self.assertIn("retry policy", out["hookSpecificOutput"]["additionalContext"])

    def test_disable_env_var_makes_hooks_silent(self):
        env = dict(os.environ, AGENT_MEMORY_KIT_DISABLE_SESSION_MEMORY="1")
        payload = json.dumps({"session_id": "sessA", "cwd": self.repo, "prompt": "anything"})
        r = subprocess.run([sys.executable, os.path.join(self.hooks, "user_prompt_submit.py")],
                            cwd=self.repo, input=payload, capture_output=True, text=True,
                            env=env, timeout=30)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")
        entries_path = os.path.join(self.repo, ".agent", "memory", "session", "entries.jsonl")
        self.assertFalse(os.path.exists(entries_path))

    def test_hooks_never_crash_on_garbage_stdin(self):
        for hook in ("session_start.py", "user_prompt_submit.py", "stop.py"):
            r = run([sys.executable, os.path.join(self.hooks, hook)],
                    cwd=self.repo, input_text="not json {{{")
            self.assertEqual(r.returncode, 0, "%s should fail open" % hook)


class TestToolkitCliSmoke(TempRepo):
    def setUp(self):
        super().setUp()
        run([sys.executable, os.path.join(KIT_ROOT, "install.py"), self.repo])
        self.toolkit = os.path.join(self.repo, ".agent", "skills", "tool-provisioning", "toolkit.py")

    def test_search_runs_and_lists_stdlib_entries(self):
        r = run([sys.executable, self.toolkit, "search", "csv"], cwd=self.repo)
        self.assertEqual(r.returncode, 0)
        self.assertIn("csv", r.stdout)

    def test_plan_never_executes_anything_for_unknown_tool(self):
        r = run([sys.executable, self.toolkit, "plan", "no-such-tool-xyz"], cwd=self.repo)
        self.assertNotEqual(r.returncode, 0)

    def test_uninstall_refuses_when_not_in_ledger(self):
        r = run([sys.executable, self.toolkit, "uninstall", "pdf-text"], cwd=self.repo)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refusing", r.stdout)

    def test_doctor_runs_and_terminates(self):
        r = run([sys.executable, self.toolkit, "doctor"], cwd=self.repo, timeout=30)
        self.assertEqual(r.returncode, 0)
        self.assertIn("python:", r.stdout)

    def test_org_policy_denylist_blocks_plan(self):
        policy_dir = os.path.join(self.repo, ".agent", "memory", "tools")
        os.makedirs(policy_dir, exist_ok=True)
        with open(os.path.join(policy_dir, "registry.org.json"), "w") as fh:
            json.dump({"mode": "denylist", "deny": ["pdf-text"]}, fh)
        r = run([sys.executable, self.toolkit, "plan", "pdf-text"], cwd=self.repo)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("BLOCKED", r.stdout)


class TestDevRecapCliSmoke(TempRepo):
    def setUp(self):
        super().setUp()
        run([sys.executable, os.path.join(KIT_ROOT, "install.py"), self.repo])
        self.recap = os.path.join(self.repo, ".agent", "skills", "dev-recap", "recap_log.py")

    def test_gaps_on_clean_repo_reports_no_changes(self):
        with open(os.path.join(self.repo, "a.py"), "w") as fh:
            fh.write("print(1)\n")
        run(["git", "add", "-A"], cwd=self.repo)
        run(["git", "-c", "user.email=t@example.com", "-c", "user.name=T", "commit", "-q", "-m", "init"],
            cwd=self.repo)
        r = run([sys.executable, self.recap, "gaps", "--json"], cwd=self.repo)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout)["changed_files"], 0)

    def test_record_recap_then_stats(self):
        r = run([sys.executable, self.recap, "record-recap", "--task", "demo",
                  "--files", "a.py", "--summary", "did a thing"], cwd=self.repo)
        self.assertEqual(r.returncode, 0)
        r = run([sys.executable, self.recap, "stats", "--json"], cwd=self.repo)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout)["recaps"], 1)

    def test_record_quiz_and_due_for_review(self):
        r = run([sys.executable, self.recap, "record-quiz", "--topic", "demo", "--result", "confused"],
                cwd=self.repo)
        self.assertEqual(r.returncode, 0)
        r = run([sys.executable, self.recap, "due-for-review", "--json"], cwd=self.repo)
        self.assertEqual(r.returncode, 0)
        topics = [row["topic"] for row in json.loads(r.stdout)]
        self.assertIn("demo", topics)

    def test_invalid_quiz_result_rejected(self):
        r = run([sys.executable, self.recap, "record-quiz", "--topic", "demo", "--result", "bogus"],
                cwd=self.repo)
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
