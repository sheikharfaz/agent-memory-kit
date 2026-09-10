"""
Unit tests for .agent/skills/dev-recap/recap_log.py.
Standard-library unittest only -- run with:
  python3 -m unittest discover -s tests -v
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.join(HERE, "..", ".agent", "skills", "dev-recap")
sys.path.insert(0, os.path.abspath(SKILL_DIR))

import recap_log as rl  # noqa: E402


def git(args, cwd):
    subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, check=True)


class TempRoot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        os.makedirs(os.path.join(self.root, ".git"))  # marks it as a repo root for find_repo_root

    def tearDown(self):
        self._tmp.cleanup()


class TempGitRoot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        git(["init", "-q", "."], self.root)
        git(["config", "user.email", "test@example.com"], self.root)
        git(["config", "user.name", "Test"], self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, content):
        full = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(content)

    def commit(self, msg="c"):
        git(["add", "-A"], self.root)
        git(["commit", "-q", "-m", msg], self.root)


class TestRecap(TempRoot):
    def test_record_recap_roundtrip(self):
        e = rl.record_recap(self.root, "sess1", "my-task", ["a.py", "b.py"], "did a thing")
        self.assertEqual(e["task"], "my-task")
        loaded = list(rl._load(rl.recap_path(self.root)))
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["summary"], "did a thing")

    def test_record_recap_truncates_summary(self):
        long_text = "x" * (rl.MAX_SUMMARY_CHARS + 100)
        e = rl.record_recap(self.root, "sess1", "t", [], long_text)
        self.assertLessEqual(len(e["summary"]), rl.MAX_SUMMARY_CHARS)

    def test_mirror_to_session_memory_when_present(self):
        sess_dir = os.path.join(self.root, ".agent", "skills", "session-memory")
        real_sess_dir = os.path.join(HERE, "..", ".agent", "skills", "session-memory")
        os.makedirs(sess_dir, exist_ok=True)
        for fn in ("memory.py",):
            with open(os.path.join(real_sess_dir, fn), encoding="utf-8") as src:
                content = src.read()
            with open(os.path.join(sess_dir, fn), "w", encoding="utf-8") as dst:
                dst.write(content)

        rl.record_recap(self.root, "sess1", "auth-fix", ["a.py"], "fixed the auth retry logic")

        entries_path = os.path.join(sess_dir, "..", "..", "memory", "session", "entries.jsonl")
        entries_path = os.path.join(self.root, ".agent", "memory", "session", "entries.jsonl")
        self.assertTrue(os.path.exists(entries_path))
        with open(entries_path, encoding="utf-8") as fh:
            mirrored = json.loads(fh.readline())
        self.assertIn("auth-fix", mirrored["text"])

    def test_mirror_is_silent_noop_when_session_memory_absent(self):
        # should not raise, should not create anything under .agent/memory/session
        rl.record_recap(self.root, "sess1", "t", [], "summary")
        self.assertFalse(os.path.exists(os.path.join(self.root, ".agent", "memory", "session")))


class TestQuiz(TempRoot):
    def test_record_quiz_rejects_invalid_result(self):
        with self.assertRaises(ValueError):
            rl.record_quiz(self.root, "sess1", "topic", "definitely-not-valid")

    def test_topic_strength_folds_scores(self):
        rl.record_quiz(self.root, "s", "topic-a", "understood")
        rl.record_quiz(self.root, "s", "topic-a", "confused")
        strength = rl.topic_strength(self.root)
        # understood (+2) then confused (-1) => 1, floored at 0 along the way
        self.assertEqual(strength["topic-a"]["score"], 1)
        self.assertEqual(strength["topic-a"]["count"], 2)

    def test_topic_strength_floors_at_zero(self):
        rl.record_quiz(self.root, "s", "topic-b", "confused")
        rl.record_quiz(self.root, "s", "topic-b", "confused")
        strength = rl.topic_strength(self.root)
        self.assertEqual(strength["topic-b"]["score"], 0)

    def test_due_for_review_ranks_weak_topics(self):
        rl.record_quiz(self.root, "s", "strong-topic", "understood")
        rl.record_quiz(self.root, "s", "weak-topic", "confused")
        due = rl.due_for_review(self.root, stale_days=9999)  # ignore staleness, isolate "weak"
        topics = [d["topic"] for d in due]
        self.assertIn("weak-topic", topics)
        self.assertNotIn("strong-topic", topics)

    def test_due_for_review_empty_when_no_quizzes(self):
        self.assertEqual(rl.due_for_review(self.root), [])


class TestFamiliarity(TempRoot):
    def test_no_profile_returns_none(self):
        self.assertIsNone(rl.current_familiarity(self.root))

    def test_set_and_read_current(self):
        rl.set_familiarity(self.root, "s", "new", notes="joined last week")
        profile = rl.current_familiarity(self.root)
        self.assertEqual(profile["level"], "new")
        self.assertEqual(profile["notes"], "joined last week")

    def test_latest_entry_wins_but_history_is_kept(self):
        rl.set_familiarity(self.root, "s", "new")
        rl.set_familiarity(self.root, "s", "veteran", notes="six months in now")
        self.assertEqual(rl.current_familiarity(self.root)["level"], "veteran")
        history = list(rl._load(rl.profile_path(self.root)))
        self.assertEqual(len(history), 2)  # both kept, not overwritten

    def test_invalid_level_rejected(self):
        with self.assertRaises(ValueError):
            rl.set_familiarity(self.root, "s", "expert-guru")

    def test_stats_reports_current_familiarity(self):
        rl.set_familiarity(self.root, "s", "some")
        self.assertEqual(rl.stats(self.root)["familiarity"], "some")

    def test_stats_familiarity_none_when_unset(self):
        self.assertIsNone(rl.stats(self.root)["familiarity"])


class TestGapsNotGitRepo(unittest.TestCase):
    def test_gaps_reports_not_applicable_outside_git(self):
        with tempfile.TemporaryDirectory() as d:
            result = rl.gaps(d)
            self.assertFalse(result["applicable"])


class TestGapsInGitRepo(TempGitRoot):
    def test_no_changes_reports_zero(self):
        self.write("a.py", "print(1)\n")
        self.commit()
        result = rl.gaps(self.root)
        self.assertTrue(result["applicable"])
        self.assertEqual(result["changed_files"], 0)

    def test_flags_missing_test_and_todo_marker(self):
        self.write("src/thing.py", "def f():\n    return 1\n")
        self.commit()
        self.write("src/thing.py", "def f():\n    # TODO: handle edge case\n    return 1\n")
        result = rl.gaps(self.root)
        self.assertTrue(result["applicable"])
        self.assertEqual(result["changed_files"], 1)
        finding = result["findings"][0]
        self.assertEqual(finding["path"], "src/thing.py")
        self.assertIn("no_test_touched", finding)
        self.assertIn("new_todo_markers", finding)
        self.assertTrue(any("TODO" in m for m in finding["new_todo_markers"]))

    def test_does_not_flag_when_test_file_also_touched(self):
        self.write("src/thing.py", "def f():\n    return 1\n")
        self.write("tests/test_thing.py", "def test_f():\n    pass\n")
        self.commit()
        self.write("src/thing.py", "def f():\n    return 2\n")
        self.write("tests/test_thing.py", "def test_f():\n    assert True\n")
        result = rl.gaps(self.root)
        thing_finding = next((f for f in result["findings"] if f["path"] == "src/thing.py"), None)
        self.assertIsNone(thing_finding)  # both files changed together -> no "missing test" flag

    def test_non_code_extension_ignored(self):
        self.write("README.md", "hello\n")
        self.commit()
        self.write("README.md", "hello again\n")
        result = rl.gaps(self.root)
        self.assertEqual(result["changed_files"], 0)


class TestStats(TempRoot):
    def test_stats_on_empty(self):
        s = rl.stats(self.root)
        self.assertEqual(s["recaps"], 0)
        self.assertEqual(s["quizzes"], 0)

    def test_stats_counts_entries(self):
        rl.record_recap(self.root, "s", "t", [], "sum")
        rl.record_quiz(self.root, "s", "topic", "understood")
        s = rl.stats(self.root)
        self.assertEqual(s["recaps"], 1)
        self.assertEqual(s["quizzes"], 1)
        self.assertEqual(s["topics_tracked"], 1)


if __name__ == "__main__":
    unittest.main()
