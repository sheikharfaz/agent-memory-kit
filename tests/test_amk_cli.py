"""
End-to-end tests for the `amk` CLI (agent_memory_kit/cli.py), driven as a
subprocess the way a user runs it. From a checkout the payload is the repo
root; CI separately builds the wheel and repeats the key flow against the
installed package.

  python3 -m unittest discover -s tests -v
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

KIT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KIT_ROOT)

import install  # noqa: E402 -- FILES is the single source of truth being checked


def amk(*args, cwd=None, input_text=None, timeout=120):
    env = dict(os.environ, PYTHONPATH=KIT_ROOT)
    return subprocess.run([sys.executable, "-m", "agent_memory_kit"] + list(args),
                          cwd=cwd, env=env, input=input_text, capture_output=True,
                          text=True, timeout=timeout)


class TempProject(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = self._tmp.name
        subprocess.run(["git", "init", "-q", "."], cwd=self.repo, check=True)
        os.makedirs(os.path.join(self.repo, "src"))
        with open(os.path.join(self.repo, "src", "auth.py"), "w", encoding="utf-8") as fh:
            fh.write("def refreshUserAuthToken(session):\n    return session\n")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=T",
                        "commit", "-q", "-m", "init"], cwd=self.repo, check=True)

    def tearDown(self):
        self._tmp.cleanup()

    def path(self, *parts):
        return os.path.join(self.repo, *parts)

    def read_json(self, *parts):
        with open(self.path(*parts), encoding="utf-8") as fh:
            return json.load(fh)


class TestInit(TempProject):
    def test_installs_exactly_the_installer_file_set_and_builds(self):
        r = amk("init", self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        for rel in install.FILES:
            self.assertTrue(os.path.exists(self.path(*rel.split("/"))), rel)
        self.assertTrue(os.path.exists(self.path(".agent", "memory", "graph", "manifest.json")))

    def test_defaults_to_the_current_directory(self):
        r = amk("init", "--no-build", cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(self.path("AGENTS.md")))

    def test_adds_private_paths_to_gitignore_once(self):
        amk("init", self.repo, "--no-build")
        amk("init", self.repo, "--no-build")
        with open(self.path(".gitignore"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(text.count(".agent/memory/session/"), 1)
        self.assertEqual(text.count(".agent/work/"), 1)

    def test_preserves_existing_gitignore_content(self):
        with open(self.path(".gitignore"), "w", encoding="utf-8") as fh:
            fh.write("node_modules/")  # no trailing newline on purpose
        amk("init", self.repo, "--no-build")
        with open(self.path(".gitignore"), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        self.assertEqual(lines[0], "node_modules/")
        self.assertIn(".agent/memory/session/", lines)

    def test_no_gitignore_flag_leaves_it_alone(self):
        amk("init", self.repo, "--no-build", "--no-gitignore")
        self.assertFalse(os.path.exists(self.path(".gitignore")))

    def test_hooks_and_mcp_are_wired_idempotently(self):
        for _ in range(2):
            r = amk("init", self.repo, "--hooks", "--mcp", "--no-build")
            self.assertEqual(r.returncode, 0, r.stderr)
        settings = self.read_json(".claude", "settings.json")
        self.assertEqual(len(settings["hooks"]["SessionStart"]), 1)
        servers = self.read_json(".mcp.json")["mcpServers"]
        self.assertEqual(list(servers), ["agent-memory-kit"])

    def test_mcp_command_is_portable_not_an_absolute_venv_path(self):
        # project-scope .mcp.json is meant to be committed; one developer's
        # venv (or a garbage-collectable uvx env) must not leak into it
        amk("init", self.repo, "--mcp", "--no-build")
        command = self.read_json(".mcp.json")["mcpServers"]["agent-memory-kit"]["command"]
        self.assertFalse(os.path.isabs(command), command)

    def test_refuses_to_install_into_the_kit_itself(self):
        r = amk("init", KIT_ROOT, "--no-build")
        self.assertEqual(r.returncode, 2)
        self.assertIn("kit itself", r.stderr)

    def test_missing_directory_is_a_clean_error(self):
        r = amk("init", self.path("does-not-exist"), "--no-build")
        self.assertEqual(r.returncode, 2)


class TestDoctor(TempProject):
    def test_healthy_install_passes(self):
        amk("init", self.repo, "--hooks", "--mcp")
        r = amk("doctor", self.repo)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("0 failure(s), 0 warning(s)", r.stdout)

    def test_missing_kit_file_fails_with_exit_1(self):
        amk("init", self.repo)
        os.remove(self.path(".agent", "lib", "retrieval.py"))
        r = amk("doctor", self.repo)
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stdout, r"FAIL\s+kit files")

    def test_unbuilt_index_fails(self):
        amk("init", self.repo, "--no-build")
        r = amk("doctor", self.repo)
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stdout, r"FAIL\s+index")

    def test_ungitignored_session_memory_is_a_privacy_warning(self):
        amk("init", self.repo, "--no-gitignore")
        r = amk("doctor", self.repo)
        self.assertEqual(r.returncode, 0)  # a warning, not a failure
        self.assertRegex(r.stdout, r"WARN\s+privacy")

    def test_optional_integrations_are_info_not_failures(self):
        amk("init", self.repo)
        r = amk("doctor", self.repo)
        self.assertEqual(r.returncode, 0)
        self.assertRegex(r.stdout, r"INFO\s+claude code hooks")
        self.assertRegex(r.stdout, r"INFO\s+mcp server")

    def test_locally_edited_kit_file_is_reported(self):
        amk("init", self.repo)
        with open(self.path("AGENTS.md"), "a", encoding="utf-8") as fh:
            fh.write("\nlocal house rule\n")
        r = amk("doctor", self.repo)
        self.assertEqual(r.returncode, 0)
        self.assertIn("1 file(s) differ", r.stdout)

    def test_empty_directory_fails_cleanly(self):
        r = amk("doctor", self.repo)
        self.assertEqual(r.returncode, 1)


class TestPassthrough(TempProject):
    def setUp(self):
        super().setUp()
        amk("init", self.repo)

    def test_find_works_from_a_subdirectory(self):
        r = amk("find", "user", "auth", "token", cwd=self.path("src"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("refreshUserAuthToken", r.stdout)

    def test_query_runs_any_verb(self):
        r = amk("query", "def", "refreshUserAuthToken", cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("src/auth.py", r.stdout)

    def test_query_exit_code_propagates(self):
        r = amk("query", "not-a-verb", cwd=self.repo)
        self.assertNotEqual(r.returncode, 0)

    def test_mcp_speaks_the_protocol(self):
        req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "t", "version": "0"}}})
        r = amk("mcp", cwd=self.repo, input_text=req + "\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout.splitlines()[0])["result"]["serverInfo"]["name"],
                         "agent-memory-kit")


class TestVersion(unittest.TestCase):
    def test_prints_the_version_file(self):
        with open(os.path.join(KIT_ROOT, "VERSION"), encoding="utf-8") as fh:
            expected = fh.read().strip()
        r = amk("version")
        self.assertEqual(r.returncode, 0)
        self.assertIn(expected, r.stdout)

    def test_no_arguments_prints_help(self):
        r = amk()
        self.assertEqual(r.returncode, 0)
        self.assertIn("init", r.stdout)


if __name__ == "__main__":
    unittest.main()
