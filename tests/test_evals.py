"""
Smoke tests for evals/recall_eval.py. The harness is a published claim
generator -- if it silently breaks, the numbers in evals/README.md become
unverifiable -- so CI runs it end to end on every push, both arms.

  python3 -m unittest discover -s tests -v
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

KIT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL_PY = os.path.join(KIT_ROOT, "evals", "recall_eval.py")
DATASET = os.path.join(KIT_ROOT, "evals", "datasets", "session_recall.json")


def run_eval(*extra, **kw):
    cmd = [sys.executable, EVAL_PY] + list(extra)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, **kw)


class TestHarnessRuns(unittest.TestCase):
    def test_default_run_reports_the_headline_metrics(self):
        r = run_eval()
        self.assertEqual(r.returncode, 0, r.stderr)
        for metric in ("recall@1", "recall@3", "recall@5", "MRR"):
            self.assertIn(metric, r.stdout)

    def test_both_arms_run_against_the_same_dataset(self):
        for scorer in ("tfidf", "bm25"):
            r = run_eval("--scorer", scorer, "--json")
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertEqual(payload["scorer"], scorer)
            self.assertEqual(payload["entries"], 40)
            self.assertEqual(payload["overall"]["queries"], 20)

    def test_the_new_arm_beats_the_baseline_on_this_dataset(self):
        # this is the claim evals/README.md publishes; if a future change
        # regresses it, CI should say so before the README goes stale
        base = json.loads(run_eval("--scorer", "tfidf", "--json").stdout)["overall"]
        new = json.loads(run_eval("--scorer", "bm25", "--json").stdout)["overall"]
        self.assertGreater(new["recall@3"], base["recall@3"])
        self.assertGreater(new["mrr"], base["mrr"])
        self.assertLess(new["misses"], base["misses"])

    def test_no_entry_is_silently_altered_by_redaction(self):
        # a redacted corpus would quietly change what is being measured
        payload = json.loads(run_eval("--json").stdout)
        self.assertEqual(payload["redacted_entries"], [])

    def test_hard_cases_are_reported_not_hidden(self):
        payload = json.loads(run_eval("--scorer", "bm25", "--json").stdout)
        self.assertIn("paraphrase", payload["by_bucket"])
        # the honest part: lexical retrieval still misses these, and the
        # report says so rather than dropping the bucket
        self.assertGreater(payload["by_bucket"]["paraphrase"]["misses"], 0)

    def test_identifier_bucket_is_fully_solved_by_the_new_arm(self):
        payload = json.loads(run_eval("--scorer", "bm25", "--json").stdout)
        self.assertEqual(payload["by_bucket"]["identifier"]["misses"], 0)

    def test_explicit_dataset_path(self):
        r = run_eval("--dataset", DATASET)
        self.assertEqual(r.returncode, 0, r.stderr)


class TestDatasetIntegrity(unittest.TestCase):
    def setUp(self):
        with open(DATASET, encoding="utf-8") as fh:
            self.data = json.load(fh)

    def test_every_gold_id_refers_to_a_real_entry(self):
        ids = {e["id"] for e in self.data["entries"]}
        for q in self.data["queries"]:
            for gold in q["gold"]:
                self.assertIn(gold, ids, "%s cites unknown entry %s" % (q["id"], gold))

    def test_entry_ids_are_unique(self):
        ids = [e["id"] for e in self.data["entries"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_query_declares_a_bucket_and_at_least_one_gold(self):
        for q in self.data["queries"]:
            self.assertTrue(q.get("bucket"))
            self.assertTrue(q.get("gold"))


class TestCustomDataset(unittest.TestCase):
    def test_runs_against_a_caller_supplied_dataset(self):
        data = {
            "name": "tiny",
            "entries": [
                {"id": "a", "session": "s", "kind": "note",
                 "text": "ProductCatalogCache keeps entries for sixty seconds"},
                {"id": "b", "session": "s", "kind": "note",
                 "text": "Deploys run through GitHub Actions"},
            ],
            "queries": [
                {"id": "q1", "bucket": "identifier", "text": "product catalog caching",
                 "gold": ["a"]},
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                          encoding="utf-8") as fh:
            json.dump(data, fh)
            path = fh.name
        try:
            r = run_eval("--dataset", path, "--json")
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertEqual(payload["overall"]["recall@1"], 1.0)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
