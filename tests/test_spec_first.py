"""
Unit tests for .agent/skills/spec-first/spec_first.py.
Standard-library unittest only -- run with:
  python3 -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.join(HERE, "..", ".agent", "skills", "spec-first")
sys.path.insert(0, os.path.abspath(SKILL_DIR))

import spec_first as sf  # noqa: E402


class TempRoot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        os.makedirs(os.path.join(self.root, ".git"))

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, slug, filename, content):
        d = sf.task_dir(self.root, slug)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, filename), "w", encoding="utf-8") as fh:
            fh.write(content)


class TestScaffold(TempRoot):
    def test_scaffold_writes_both_by_default(self):
        written = sf.scaffold(self.root, "my-task")
        self.assertEqual(len(written), 2)
        d = sf.task_dir(self.root, "my-task")
        self.assertTrue(os.path.exists(os.path.join(d, sf.PRD_FILENAME)))
        self.assertTrue(os.path.exists(os.path.join(d, sf.TRD_FILENAME)))

    def test_scaffold_trd_only(self):
        written = sf.scaffold(self.root, "my-task", want_prd=False, want_trd=True)
        self.assertEqual(len(written), 1)
        d = sf.task_dir(self.root, "my-task")
        self.assertFalse(os.path.exists(os.path.join(d, sf.PRD_FILENAME)))
        self.assertTrue(os.path.exists(os.path.join(d, sf.TRD_FILENAME)))

    def test_scaffold_does_not_overwrite_without_force(self):
        sf.scaffold(self.root, "my-task")
        d = sf.task_dir(self.root, "my-task")
        prd_path = os.path.join(d, sf.PRD_FILENAME)
        with open(prd_path, "a", encoding="utf-8") as fh:
            fh.write("\nreal content here\n")
        written = sf.scaffold(self.root, "my-task")
        self.assertEqual(written, [])
        with open(prd_path, encoding="utf-8") as fh:
            self.assertIn("real content here", fh.read())

    def test_scaffold_overwrites_with_force(self):
        sf.scaffold(self.root, "my-task")
        d = sf.task_dir(self.root, "my-task")
        prd_path = os.path.join(d, sf.PRD_FILENAME)
        with open(prd_path, "a", encoding="utf-8") as fh:
            fh.write("\nreal content here\n")
        written = sf.scaffold(self.root, "my-task", force=True)
        self.assertEqual(len(written), 2)
        with open(prd_path, encoding="utf-8") as fh:
            self.assertNotIn("real content here", fh.read())


class TestCheck(TempRoot):
    def test_check_reports_missing_when_no_files(self):
        result = sf.check(self.root, "ghost-task")
        self.assertFalse(result["prd_found"])
        self.assertFalse(result["trd_found"])

    def test_check_on_freshly_scaffolded_template(self):
        sf.scaffold(self.root, "my-task")
        result = sf.check(self.root, "my-task")
        self.assertTrue(result["prd_found"])
        self.assertEqual(result["acceptance_total"], 0)  # template ships with an empty checkbox
        self.assertFalse(result["trd_has_approach"])
        self.assertFalse(result["trd_has_testing_strategy"])

    def test_check_counts_checked_and_unchecked_criteria(self):
        self.write("t", sf.PRD_FILENAME, """# PRD: t

## Acceptance criteria
- [x] first thing works
- [ ] second thing works
- [X] third thing works (capital X counts too)
""")
        result = sf.check(self.root, "t")
        self.assertEqual(result["acceptance_total"], 3)
        self.assertEqual(result["acceptance_checked"], 2)
        self.assertEqual(result["acceptance_unchecked"], ["second thing works"])

    def test_check_extracts_open_questions(self):
        self.write("t", sf.PRD_FILENAME, """# PRD: t

## Open questions
- does this need a migration?
- should the default change?

## Assumptions
- unrelated section, not counted
""")
        result = sf.check(self.root, "t")
        self.assertEqual(len(result["open_questions"]), 2)
        self.assertIn("does this need a migration?", result["open_questions"])

    def test_check_ignores_html_comment_placeholder_text(self):
        # the shipped template's own instructional comment must never be
        # mistaken for a real open question or a real acceptance criterion
        sf.scaffold(self.root, "t")
        result = sf.check(self.root, "t")
        self.assertEqual(result["open_questions"], [])
        self.assertEqual(result["acceptance_total"], 0)

    def test_check_trd_detects_filled_sections(self):
        self.write("t", sf.TRD_FILENAME, """# TRD: t

## Approach
Use a retry queue with exponential backoff.

## Testing strategy
Unit test the backoff calculation; integration test the retry path.
""")
        result = sf.check(self.root, "t")
        self.assertTrue(result["trd_has_approach"])
        self.assertTrue(result["trd_has_testing_strategy"])


class TestListTasks(TempRoot):
    def test_list_empty(self):
        self.assertEqual(sf.list_tasks(self.root), [])

    def test_list_reports_which_artifacts_exist(self):
        sf.scaffold(self.root, "task-a", want_trd=False)
        d = sf.task_dir(self.root, "task-a")
        with open(os.path.join(d, sf.RESEARCH_FILENAME), "w") as fh:
            fh.write("notes")
        rows = sf.list_tasks(self.root)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["slug"], "task-a")
        self.assertTrue(row["prd"])
        self.assertTrue(row["research"])
        self.assertFalse(row["trd"])
        self.assertFalse(row["progress"])

    def test_list_ignores_non_directory_entries(self):
        base = os.path.join(self.root, sf.WORK_SUBDIR)
        os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, "stray-file.txt"), "w") as fh:
            fh.write("x")
        self.assertEqual(sf.list_tasks(self.root), [])


if __name__ == "__main__":
    unittest.main()
