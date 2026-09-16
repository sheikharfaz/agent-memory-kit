"""
Unit tests for .agent/lib/retrieval.py -- the shared code-aware tokenizer
and BM25 scorer -- plus the guarded-import contract that lets
session-memory keep working when that file is not installed.

  python3 -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT_ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(KIT_ROOT, ".agent", "lib"))
sys.path.insert(0, os.path.join(KIT_ROOT, ".agent", "skills", "session-memory"))

import retrieval as r  # noqa: E402
import memory as mem  # noqa: E402


class TestSplitIdentifier(unittest.TestCase):
    def test_camel_case(self):
        self.assertEqual(r.split_identifier("getUserById"), ["get", "user", "by", "id"])

    def test_pascal_case(self):
        self.assertEqual(r.split_identifier("OrderStateMachine"),
                          ["order", "state", "machine"])

    def test_acronym_run_is_kept_whole(self):
        # the reason the alternation is ordered: a naive [A-Z][a-z]* split
        # would give h/t/t/p/server/error, which is worse than not splitting
        self.assertEqual(r.split_identifier("HTTPServerError"),
                          ["http", "server", "error"])
        self.assertEqual(r.split_identifier("parseCSVUpload"),
                          ["parse", "csv", "upload"])

    def test_digits_separate(self):
        self.assertEqual(r.split_identifier("v2Handler"), ["v", "2", "handler"])

    def test_single_word_has_nothing_to_split(self):
        self.assertEqual(r.split_identifier("handler"), [])
        self.assertEqual(r.split_identifier(""), [])


class TestTokenize(unittest.TestCase):
    def test_keeps_whole_identifier_and_its_parts(self):
        toks = r.tokenize("findUserById")
        self.assertIn("finduserbyid", toks)   # exact-name queries stay precise
        self.assertIn("user", toks)           # plain-words queries become possible
        self.assertIn("find", toks)

    def test_the_defect_this_module_exists_to_fix(self):
        # "where do we look up a user by id" shares nothing with the v0.4.0
        # tokenization of this text; it must share something with the new one
        toks = r.tokenize("Renamed getUserById to findUserById")
        self.assertTrue({"user", "id"}.issubset(set(toks)))

    def test_drops_stopwords_and_single_chars(self):
        toks = r.tokenize("the a x quick fox")
        self.assertNotIn("the", toks)
        self.assertNotIn("a", toks)
        self.assertNotIn("x", toks)
        self.assertIn("quick", toks)

    def test_respects_caller_supplied_stopwords(self):
        self.assertNotIn("quick", r.tokenize("quick fox", stopwords={"quick"}))

    def test_part_equal_to_whole_is_not_duplicated(self):
        self.assertEqual(r.tokenize("handler").count("handler"), 1)

    def test_empty_and_none_are_safe(self):
        self.assertEqual(r.tokenize(""), [])
        self.assertEqual(r.tokenize(None), [])


class TestBM25(unittest.TestCase):
    def setUp(self):
        self.docs = [
            r.tokenize("the payment gateway retries with exponential backoff"),
            r.tokenize("deploys run through GitHub Actions on merge to main"),
            r.tokenize("refreshUserAuthToken rotates the refresh token"),
        ]
        self.bm = r.BM25(self.docs)

    def test_matching_doc_outranks_non_matching(self):
        scores = self.bm.score(r.tokenize("exponential backoff"))
        self.assertGreater(scores[0], scores[1])
        self.assertEqual(scores[1], 0.0)

    def test_scores_are_bounded_in_unit_interval(self):
        for q in ("payment gateway", "refresh token rotation", "nothing here"):
            for s in self.bm.score(r.tokenize(q)):
                self.assertGreaterEqual(s, 0.0)
                self.assertLess(s, 1.0)

    def test_unknown_query_terms_score_zero(self):
        self.assertEqual(self.bm.score(r.tokenize("kubernetes helm chart")),
                          [0.0, 0.0, 0.0])

    def test_empty_query_scores_zero(self):
        self.assertEqual(self.bm.score([]), [0.0, 0.0, 0.0])

    def test_identifier_parts_are_reachable_by_plain_words(self):
        scores = self.bm.score(r.tokenize("auth token"))
        self.assertGreater(scores[2], 0.0)

    def test_empty_corpus_returns_empty(self):
        self.assertEqual(r.BM25([]).score(r.tokenize("anything")), [])

    def test_length_normalisation_prefers_the_denser_match(self):
        short = r.tokenize("cache invalidation")
        long = r.tokenize("cache invalidation " + "unrelated filler words here " * 20)
        bm = r.BM25([short, long])
        scores = bm.score(r.tokenize("cache invalidation"))
        self.assertGreater(scores[0], scores[1])


class TestSessionMemoryIntegration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        os.makedirs(os.path.join(self.root, ".agent"))
        mem.append_entry(self.root, "s1", self.root, "turn",
                          "Renamed getUserById to findUserById for consistency.")
        mem.append_entry(self.root, "s1", self.root, "turn",
                          "Deploys run through GitHub Actions on merge to main.")

    def tearDown(self):
        self._tmp.cleanup()

    def test_plain_words_now_recall_a_camel_case_entry(self):
        hits = mem.recall(self.root, "where do we look up a user by id")
        self.assertTrue(hits, "the defect this release fixes has regressed")
        self.assertIn("findUserById", hits[0][0]["text"])

    def test_the_old_path_still_misses_it_and_is_still_reachable(self):
        # the baseline arm must keep working: evals/ compares against it, and
        # an install without .agent/lib/ falls back to it
        self.assertEqual(mem.recall(self.root, "where do we look up a user by id",
                                     scorer="tfidf"), [])

    def test_exact_identifier_query_still_ranks_its_own_entry_first(self):
        hits = mem.recall(self.root, "findUserById")
        self.assertIn("findUserById", hits[0][0]["text"])

    def test_scores_stay_in_the_range_min_score_was_calibrated_for(self):
        for _, score in mem.recall(self.root, "user id lookup"):
            self.assertGreaterEqual(score, mem.MIN_SCORE)
            self.assertLessEqual(score, 1.0)


class TestFallbackWhenLibAbsent(unittest.TestCase):
    """An install that copied only the session-memory skill has no
    .agent/lib/retrieval.py. That must degrade to v0.4.0 behaviour, not fail."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        os.makedirs(os.path.join(self.root, ".agent"))
        mem.append_entry(self.root, "s1", self.root, "turn",
                          "The payment gateway retries with exponential backoff.")
        self._saved = mem._shared
        mem._shared = None  # simulate "the shared module is not installed"

    def tearDown(self):
        mem._shared = self._saved
        self._tmp.cleanup()

    def test_recall_still_works(self):
        hits = mem.recall(self.root, "exponential backoff retries")
        self.assertTrue(hits)

    def test_default_scorer_falls_back_to_tfidf(self):
        self.assertEqual(mem.resolve_scorer(None), "tfidf")

    def test_tokenize_falls_back_to_the_plain_tokenizer(self):
        self.assertEqual(mem.tokenize("getUserById"), mem.tokenize_plain("getUserById"))

    def test_asking_for_bm25_explicitly_fails_loudly(self):
        with self.assertRaises(ValueError):
            mem.resolve_scorer("bm25")


if __name__ == "__main__":
    unittest.main()
