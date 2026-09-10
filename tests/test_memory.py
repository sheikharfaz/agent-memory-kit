"""
Unit tests for .agent/skills/session-memory/memory.py.
Standard-library unittest only -- run with:
  python3 -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.join(HERE, "..", ".agent", "skills", "session-memory")
sys.path.insert(0, os.path.abspath(SKILL_DIR))

import memory as mem  # noqa: E402


class TempRoot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        os.makedirs(os.path.join(self.root, ".git"))  # marks it as a repo root

    def tearDown(self):
        self._tmp.cleanup()


class TestTokenizeRedact(unittest.TestCase):
    def test_tokenize_drops_stopwords_and_short_tokens(self):
        toks = mem.tokenize("The quick fox is a b jumping over the lazy DOG")
        self.assertIn("quick", toks)
        self.assertIn("jumping", toks)
        self.assertNotIn("the", toks)
        self.assertNotIn("a", toks)  # too short
        self.assertNotIn("b", toks)

    def test_redact_aws_key(self):
        out = mem.redact("my key is AKIAABCDEFGHIJKLMNOP thanks")
        self.assertNotIn("AKIAABCDEFGHIJKLMNOP", out)
        self.assertIn("[REDACTED]", out)

    def test_redact_generic_token_assignment(self):
        out = mem.redact("api_key=sk-1234567890abcdef please use this")
        self.assertNotIn("sk-1234567890abcdef", out)

    def test_redact_pem_block(self):
        pem = "-----BEGIN PRIVATE KEY-----\nMIIBVQ==\n-----END PRIVATE KEY-----"
        out = mem.redact("here: %s end" % pem)
        self.assertNotIn("MIIBVQ==", out)

    def test_redact_preserves_ordinary_text(self):
        out = mem.redact("how does the auth middleware validate JWT tokens?")
        self.assertIn("auth middleware", out)


class TestAppendAndLoad(TempRoot):
    def test_append_then_load_roundtrip(self):
        e = mem.append_entry(self.root, "sess1", self.root, "prompt", "hello world")
        self.assertIsNotNone(e)
        loaded = list(mem.load_entries(self.root))
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["text"], "hello world")
        self.assertEqual(loaded[0]["session_id"], "sess1")
        self.assertEqual(loaded[0]["weight"], 1)

    def test_append_empty_text_is_noop(self):
        e = mem.append_entry(self.root, "sess1", self.root, "prompt", "   ")
        self.assertIsNone(e)
        self.assertEqual(list(mem.load_entries(self.root)), [])

    def test_append_truncates_long_text(self):
        long_text = "x" * (mem.MAX_TEXT_CHARS + 500)
        e = mem.append_entry(self.root, "sess1", self.root, "note", long_text)
        self.assertLess(len(e["text"]), len(long_text))

    def test_load_entries_skips_corrupt_lines(self):
        mem.append_entry(self.root, "sess1", self.root, "note", "good line")
        path = mem.entries_path(self.root)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("{not valid json\n")
        loaded = list(mem.load_entries(self.root))
        self.assertEqual(len(loaded), 1)  # corrupt line skipped, not fatal


class TestRecallAndRecent(TempRoot):
    def test_recall_ranks_lexically_similar_higher(self):
        mem.append_entry(self.root, "sessA", self.root, "prompt",
                          "how does the auth middleware validate JWT tokens")
        mem.append_entry(self.root, "sessA", self.root, "prompt",
                          "what's the deploy process for the frontend")
        hits = mem.recall(self.root, "explain JWT validation in auth middleware", limit=5)
        self.assertTrue(hits)
        top_entry, top_score = hits[0]
        self.assertIn("JWT", top_entry["text"])

    def test_recall_excludes_current_session(self):
        mem.append_entry(self.root, "sessA", self.root, "prompt", "database migration rollback plan")
        hits = mem.recall(self.root, "database migration rollback", exclude_session="sessA")
        self.assertEqual(hits, [])

    def test_recall_empty_corpus_returns_empty(self):
        self.assertEqual(mem.recall(self.root, "anything"), [])

    def test_recall_no_shared_vocabulary_returns_empty(self):
        mem.append_entry(self.root, "sessA", self.root, "prompt", "completely unrelated topic zzzqux")
        hits = mem.recall(self.root, "database migration rollback plan")
        self.assertEqual(hits, [])

    def test_bump_weight_gives_mild_boost_not_override(self):
        mem.append_entry(self.root, "sessA", self.root, "prompt", "kubernetes deployment rollback strategy")
        mem.append_entry(self.root, "sessA", self.root, "prompt", "kubernetes deployment canary strategy")
        entries = list(mem.load_entries(self.root))
        rollback_id = next(e["id"] for e in entries if "rollback" in e["text"])
        # heavily reinforce the less-similar one; it should NOT overtake a
        # much more lexically similar competitor -- boost is capped/mild.
        mem.bump_weight(self.root, [rollback_id], amount=1000)
        hits = mem.recall(self.root, "kubernetes deployment canary rollout")
        self.assertTrue(hits)
        self.assertIn("canary", hits[0][0]["text"])

    def test_recent_dedupes_one_per_session_and_orders_desc(self):
        mem.append_entry(self.root, "sessA", self.root, "prompt", "first in A")
        mem.append_entry(self.root, "sessA", self.root, "prompt", "second in A")
        mem.append_entry(self.root, "sessB", self.root, "prompt", "only in B")
        rows = mem.recent(self.root, limit=10)
        sessions = [r["session_id"] for r in rows]
        self.assertEqual(len(sessions), len(set(sessions)))  # one per session
        a_row = next(r for r in rows if r["session_id"] == "sessA")
        self.assertEqual(a_row["text"], "second in A")  # most recent of that session

    def test_recent_excludes_given_session(self):
        mem.append_entry(self.root, "sessA", self.root, "prompt", "hello")
        rows = mem.recent(self.root, exclude_session="sessA")
        self.assertEqual(rows, [])


class TestPruneAndStats(TempRoot):
    def test_prune_keeps_most_recent_n(self):
        for i in range(10):
            mem.append_entry(self.root, "s", self.root, "note", "entry %d" % i)
        result = mem.prune(self.root, keep_last=3)
        self.assertEqual(result["before"], 10)
        self.assertEqual(result["after"], 3)
        remaining = [e["text"] for e in mem.load_entries(self.root)]
        self.assertEqual(remaining, ["entry 7", "entry 8", "entry 9"])

    def test_prune_by_age(self):
        mem.append_entry(self.root, "s", self.root, "note", "old-ish entry")
        entries = list(mem.load_entries(self.root))
        entries[0]["ts"] = "2000-01-01T00:00:00Z"
        mem.rewrite_entries(self.root, entries)
        result = mem.prune(self.root, keep_last=1000, keep_days=1)
        self.assertEqual(result["after"], 0)

    def test_stats_reports_counts(self):
        mem.append_entry(self.root, "s1", self.root, "prompt", "a")
        mem.append_entry(self.root, "s2", self.root, "turn", "b")
        s = mem.stats(self.root)
        self.assertEqual(s["entries"], 2)
        self.assertEqual(s["sessions"], 2)
        self.assertEqual(s["by_kind"], {"prompt": 1, "turn": 1})

    def test_stats_on_empty_repo(self):
        s = mem.stats(self.root)
        self.assertEqual(s["entries"], 0)
        self.assertIsNone(s["oldest"])


if __name__ == "__main__":
    unittest.main()
