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

    def test_root_flag_works_before_the_subcommand(self):
        # Regression test: argparse's subparsers re-parse into the same
        # namespace the top-level parser already populated, so a shared
        # --root/--json/--limit definition on both the top-level parser and
        # each subparser silently clobbered a --root given *before* the
        # verb (e.g. `query.py --root X def Y`) back to the default "."
        # unless it was also repeated after the verb. Run from a cwd that
        # is NOT the indexed repo, so a silently-ignored --root fails loudly.
        other_cwd = os.path.dirname(KIT_ROOT)
        r = run([sys.executable, QUERY_PY, "--root", KIT_ROOT, "def", "find_repo_root", "--json"],
                cwd=other_cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotEqual(json.loads(r.stdout), [])

        r2 = run([sys.executable, QUERY_PY, "def", "find_repo_root", "--root", KIT_ROOT, "--json"],
                 cwd=other_cwd)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertEqual(json.loads(r.stdout), json.loads(r2.stdout))


class TestAgentDirIndexing(unittest.TestCase):
    """Regression coverage for a real bug: .agent was originally a blanket
    hard-denied directory NAME, which also hid .agent/skills/ (hand-written
    source -- this is where every skill in this very kit lives) and
    .agent/work/ (PRD/TRD/research docs). Only .agent/memory/ (generated
    output + local logs) should ever be excluded."""

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

    def test_agent_skills_source_is_indexed_but_agent_memory_is_not(self):
        self.write(".agent/skills/my-skill/thing.py", "def real_source_symbol():\n    pass\n")
        self.write(".agent/work/task-1/PRD.md", "# PRD\n")
        # Simulate the generated/private output tree a previous build (or
        # session-memory/tool-provisioning/dev-recap) would have left behind.
        self.write(".agent/memory/graph/files.jsonl", '{"p": "bogus"}\n')
        self.write(".agent/memory/session/entries.jsonl", '{"text": "private prompt text"}\n')
        run(["git", "add", "-A"], cwd=self.repo)
        run(["git", "-c", "user.email=t@example.com", "-c", "user.name=T",
             "commit", "-q", "-m", "add files"], cwd=self.repo)

        r = run([sys.executable, INDEX_PY, "build"], cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)

        with open(os.path.join(self.repo, ".agent", "memory", "graph", "files.jsonl")) as fh:
            paths = [json.loads(l)["p"] for l in fh]
        self.assertIn(".agent/skills/my-skill/thing.py", paths)
        self.assertIn(".agent/work/task-1/PRD.md", paths)
        self.assertFalse(any(p.startswith(".agent/memory/") for p in paths),
                          "the indexer must never index its own .agent/memory/ tree")

        r = run([sys.executable, QUERY_PY, "def", "real_source_symbol"], cwd=self.repo)
        self.assertIn("thing.py", r.stdout)


class TestJsonFlagCleanliness(unittest.TestCase):
    """Regression coverage for a real bug: several verbs printed a trailing
    human-readable summary/caveat line even when --json was set, producing
    output that isn't valid JSON for a machine consumer."""

    @classmethod
    def setUpClass(cls):
        r = run([sys.executable, INDEX_PY, "build"])
        assert r.returncode == 0, r.stderr

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(os.path.join(KIT_ROOT, ".agent", "memory"), ignore_errors=True)

    def assert_clean_json(self, args):
        r = run([sys.executable, QUERY_PY] + args)
        self.assertEqual(r.returncode, 0, r.stderr)
        try:
            json.loads(r.stdout)
        except json.JSONDecodeError as exc:
            self.fail("not valid JSON for %r: %s\noutput was:\n%s" % (args, exc, r.stdout))

    def test_def_json_clean_with_and_without_results(self):
        self.assert_clean_json(["def", "find_repo_root", "--json"])
        self.assert_clean_json(["def", "definitely_not_a_real_symbol_xyz", "--json"])

    def test_callers_json_clean_with_and_without_results(self):
        self.assert_clean_json(["callers", "find_repo_root", "--json"])
        self.assert_clean_json(["callers", "definitely_not_a_real_symbol_xyz", "--json"])

    def test_search_json_clean(self):
        self.assert_clean_json(["search", "find_.*", "--json"])
        self.assert_clean_json(["search", "zzz_no_match_zzz", "--json"])

    def test_importers_json_clean(self):
        self.assert_clean_json(["importers", "os", "--json"])

    def test_orphans_json_clean(self):
        self.assert_clean_json(["orphans", "--json"])

    def test_routes_json_clean(self):
        self.assert_clean_json(["routes", "--json"])


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
