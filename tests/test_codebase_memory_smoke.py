"""
Smoke test for the original codebase-memory skill: build the index against
this kit's own repo (small, fast) and confirm the basic verbs work. This
skill had no automated coverage before -- this is the floor, not a
replacement for deeper unit tests on index.py's parsers.
"""

import os
import shutil
import subprocess
import sys
import unittest

KIT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_PY = os.path.join(KIT_ROOT, ".agent", "skills", "codebase-memory", "index.py")
QUERY_PY = os.path.join(KIT_ROOT, ".agent", "skills", "codebase-memory", "query.py")


def run(cmd, timeout=60):
    return subprocess.run(cmd, cwd=KIT_ROOT, capture_output=True, text=True, timeout=timeout)


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


if __name__ == "__main__":
    unittest.main()
