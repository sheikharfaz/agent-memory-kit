"""
Smoke test for the original codebase-memory skill: build the index against
this kit's own repo (small, fast) and confirm the basic verbs work. This
skill had no automated coverage before -- this is the floor, not a
replacement for deeper unit tests on index.py's parsers.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

KIT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_PY = os.path.join(KIT_ROOT, ".agent", "skills", "codebase-memory", "index.py")
QUERY_PY = os.path.join(KIT_ROOT, ".agent", "skills", "codebase-memory", "query.py")


def run(cmd, cwd=KIT_ROOT, timeout=60):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


class TestCodebaseMemorySmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = run([sys.executable, INDEX_PY, "build"])
        assert r.returncode == 0, r.stderr

    @classmethod
    def tearDownClass(cls):
        # .agent/memory/ is gitignored in this repo (see .gitignore), so
        # `git clean` without -x would leave it alone -- remove it directly
        # to keep the kit repo's own working tree clean after the test run.
        shutil.rmtree(os.path.join(KIT_ROOT, ".agent", "memory"), ignore_errors=True)

    def test_verify_reports_ok_after_build(self):
        r = run([sys.executable, INDEX_PY, "verify"])
        self.assertEqual(r.returncode, 0)

    def test_arch_query_runs(self):
        r = run([sys.executable, QUERY_PY, "arch"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("index generation", r.stdout)

    def test_search_finds_a_known_symbol(self):
        r = run([sys.executable, QUERY_PY, "def", "find_repo_root", "--json"])
        self.assertEqual(r.returncode, 0)

    def test_stats_query_runs(self):
        r = run([sys.executable, QUERY_PY, "stats"])
        self.assertEqual(r.returncode, 0)


class TestDrift(unittest.TestCase):
    """query.py drift / index.py's drift-log.jsonl, exercised in an isolated
    repo (not the kit's own) since it needs multiple real builds with
    changes between them."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = self._tmp.name
        run(["git", "init", "-q", "."], cwd=self.repo)
        run(["git", "-c", "user.email=t@example.com", "-c", "user.name=T",
             "commit", "-q", "-m", "init", "--allow-empty"], cwd=self.repo)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, content):
        full = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(content)

    def build(self):
        r = run([sys.executable, INDEX_PY, "build", "--calls", "off"], cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_drift_reports_not_enough_history_after_one_build(self):
        self.write("a.py", "def f():\n    return 1\n")
        self.build()
        r = run([sys.executable, QUERY_PY, "drift"], cwd=self.repo)
        self.assertEqual(r.returncode, 0)
        self.assertIn("only 1 build", r.stdout)

    def test_drift_reports_growth_between_two_builds(self):
        self.write("src/a.py", "def f():\n    return 1\n")
        self.build()
        self.write("src/a.py", "def f():\n    return 1\n\n\ndef g():\n    return 2\n")
        self.write("src/b.py", "def h():\n    return 3\n")
        self.build()

        r = run([sys.executable, QUERY_PY, "drift", "--json"], cwd=self.repo)
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertGreater(data["to"]["loc_total"], data["from"]["loc_total"])
        self.assertGreater(data["to"]["files_total"], data["from"]["files_total"])

        r = run([sys.executable, QUERY_PY, "drift"], cwd=self.repo)
        self.assertIn("files:", r.stdout)
        self.assertIn("by language:", r.stdout)

    def test_no_op_rebuild_does_not_duplicate_drift_log_entry(self):
        self.write("a.py", "def f():\n    return 1\n")
        self.build()
        self.build()  # nothing changed -- same content-addressed generation
        log_path = os.path.join(self.repo, ".agent", "memory", "history", "drift-log.jsonl")
        with open(log_path) as fh:
            lines = [l for l in fh if l.strip()]
        self.assertEqual(len(lines), 1)


if __name__ == "__main__":
    unittest.main()
