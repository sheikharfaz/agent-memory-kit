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
    """.agent/skills/ is excluded from indexing by default: in the
    overwhelmingly common case it holds *vendored* copies of this kit's own
    scripts (installed into a consumer repo), not that repo's own source,
    and indexing them buries a small project's real code under this tool's
    internals -- confirmed directly against a real consumer-style repo
    (linkshrink-agent-memory-kit) whose map was ~93% kit-internal LOC
    before this fix. .agent/work/ (PRD/TRD/research docs -- always the
    repo's own content, never vendored) stays indexed by default.
    .agent/memory/ (generated output + local logs) stays excluded
    unconditionally, with no override -- see load_agentignore's docstring.
    A repo that *does* want .agent/skills/ indexed (this kit's own repo is
    the one real case) opts back in via `.agentignore`'s `!.agent/skills/`."""

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

    def _commit_and_build(self):
        run(["git", "add", "-A"], cwd=self.repo)
        run(["git", "-c", "user.email=t@example.com", "-c", "user.name=T",
             "commit", "-q", "-m", "add files"], cwd=self.repo)
        r = run([sys.executable, INDEX_PY, "build"], cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.repo, ".agent", "memory", "graph", "files.jsonl")) as fh:
            return [json.loads(l)["p"] for l in fh]

    def test_agent_skills_excluded_by_default_agent_work_is_not(self):
        self.write(".agent/skills/my-skill/thing.py", "def real_source_symbol():\n    pass\n")
        self.write(".agent/work/task-1/PRD.md", "# PRD\n")
        # Simulate the generated/private output tree a previous build (or
        # session-memory/tool-provisioning/dev-recap) would have left behind.
        self.write(".agent/memory/graph/files.jsonl", '{"p": "bogus"}\n')
        self.write(".agent/memory/session/entries.jsonl", '{"text": "private prompt text"}\n')
        paths = self._commit_and_build()

        self.assertNotIn(".agent/skills/my-skill/thing.py", paths)
        self.assertIn(".agent/work/task-1/PRD.md", paths)
        self.assertFalse(any(p.startswith(".agent/memory/") for p in paths),
                          "the indexer must never index its own .agent/memory/ tree")

    def test_agentignore_negation_opts_agent_skills_back_in(self):
        self.write(".agent/skills/my-skill/thing.py", "def real_source_symbol():\n    pass\n")
        self.write(".agentignore", "!.agent/skills/\n")
        paths = self._commit_and_build()

        self.assertIn(".agent/skills/my-skill/thing.py", paths)

        r = run([sys.executable, QUERY_PY, "def", "real_source_symbol"], cwd=self.repo)
        self.assertIn("thing.py", r.stdout)

    def test_agentignore_negation_cannot_reach_agent_memory(self):
        self.write(".agent/memory/graph/files.jsonl", '{"p": "bogus"}\n')
        self.write(".agentignore", "!.agent/memory/\n")
        paths = self._commit_and_build()

        self.assertFalse(any(p.startswith(".agent/memory/") for p in paths),
                          ".agent/memory/ must stay excluded even if .agentignore tries to negate it")


class TestMapCompactness(unittest.TestCase):
    """CODEBASE_MAP.md's fixed-overhead sections (Hubs, empty modules) were
    tightened so they don't dominate the map for a small repo -- confirmed
    against a real one (linkshrink-agent-memory-kit) where the pre-fix map
    was ~4.5k chars for a ~275-LOC app, mostly noise. These lock in the two
    specific behaviours that made the difference."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = self._tmp.name
        run(["git", "init", "-q", "."], cwd=self.repo)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, content):
        full = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(content)

    def build(self):
        run(["git", "add", "-A"], cwd=self.repo)
        run(["git", "-c", "user.email=t@example.com", "-c", "user.name=T",
             "commit", "-q", "-m", "init"], cwd=self.repo)
        r = run([sys.executable, INDEX_PY, "build"], cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.repo, ".agent", "memory", "CODEBASE_MAP.md")) as fh:
            return fh.read()

    def test_single_caller_symbols_are_not_listed_as_hubs(self):
        self.write("a.py", "def helper():\n    pass\n\ndef main():\n    helper()\n")
        map_text = self.build()
        self.assertNotIn("## Hubs", map_text)  # only 1 caller each -- not a hub

    def test_two_caller_symbol_is_listed_as_a_hub(self):
        # names must be 2+ chars (extractor filters shorter ones as noise),
        # and callers module the graph counts distinct *files* that call a
        # symbol, not distinct call sites -- two callers in the same file
        # would still show indegree 1, so this needs two separate files.
        self.write("shared.py", "def helper():\n    pass\n")
        self.write("a.py", "from shared import helper\ndef aaa():\n    helper()\n")
        self.write("b.py", "from shared import helper\ndef bbb():\n    helper()\n")
        map_text = self.build()
        self.assertIn("## Hubs", map_text)
        self.assertIn("helper", map_text)

    def test_modules_with_no_parsed_code_are_summarized_not_tabled(self):
        self.write("app/a.py", "def f():\n    pass\n")
        self.write("docs/readme.md", "# hello\n")
        map_text = self.build()
        self.assertIn("| `app`", map_text)          # real code -> full table row
        self.assertNotIn("| `docs`", map_text)       # no parsed code -> not a table row
        self.assertIn("no parsed code", map_text)    # but still mentioned


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
