#!/usr/bin/env python3
"""
agent-memory-kit :: session-memory retrieval quality eval.

Measures whether `session-memory` recalls the *right* entry, not just how
few tokens it costs -- the question `benchmarks/` deliberately does not
answer. Standard IR metrics over a shipped dataset: recall@1/@3/@5 and MRR.

  python3 evals/recall_eval.py
  python3 evals/recall_eval.py --scorer tfidf --json
  python3 evals/recall_eval.py --dataset evals/datasets/session_recall.json

Zero dependencies, no network, no LLM call. The corpus is loaded through
the real `append_entry()` and scored through the real `recall()`, so
redaction, truncation, the MIN_SCORE floor, and the weight boost are all
inside the measured path rather than bypassed for a flattering number.

Read `evals/README.md` before quoting any number this prints -- especially
the authoring-bias disclosure and why these are not comparable to
LongMemEval/LOCOMO scores.
"""

import argparse
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
KIT_ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(KIT_ROOT, ".agent", "skills", "session-memory"))

import memory as mem  # noqa: E402

DEFAULT_DATASET = os.path.join(HERE, "datasets", "session_recall.json")
CUTOFFS = (1, 3, 5)
DEPTH = 10  # how deep to look when computing MRR


def load_dataset(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def build_corpus(root, entries):
    """Append every dataset entry through the real write path. Returns
    {dataset_id: generated_entry_id} plus any entry the redactor altered --
    a silently redacted corpus would change what is being measured, so the
    report says so out loud instead of hiding it."""
    id_map = {}
    redacted = []
    for e in entries:
        written = mem.append_entry(root, e["session"], root, e["kind"], e["text"])
        if written is None:
            raise SystemExit("entry %s was not recorded (empty after redaction?)" % e["id"])
        id_map[e["id"]] = written["id"]
        if written["text"] != e["text"]:
            redacted.append(e["id"])
    return id_map, redacted


def evaluate_query(root, query, id_map, scorer):
    gold = {id_map[g] for g in query["gold"]}
    hits = mem.recall(root, query["text"], limit=DEPTH, scorer=scorer)
    ranked = [e["id"] for e, _ in hits]
    scores = [s for _, s in hits]

    first_gold_rank = None
    for i, entry_id in enumerate(ranked, start=1):
        if entry_id in gold:
            first_gold_rank = i
            break

    row = {
        "id": query["id"],
        "bucket": query.get("bucket", "unspecified"),
        "text": query["text"],
        "gold_count": len(gold),
        "returned": len(ranked),
        "first_gold_rank": first_gold_rank,
        "reciprocal_rank": (1.0 / first_gold_rank) if first_gold_rank else 0.0,
        "top_score": round(scores[0], 4) if scores else 0.0,
    }
    for k in CUTOFFS:
        found = len(gold & set(ranked[:k]))
        row["recall@%d" % k] = found / float(len(gold))
    return row


def aggregate(rows):
    if not rows:
        return {}
    out = {"queries": len(rows)}
    for k in CUTOFFS:
        key = "recall@%d" % k
        out[key] = round(sum(r[key] for r in rows) / len(rows), 4)
    out["mrr"] = round(sum(r["reciprocal_rank"] for r in rows) / len(rows), 4)
    out["misses"] = sum(1 for r in rows if r["first_gold_rank"] is None)
    return out


def by_bucket(rows):
    buckets = {}
    for r in rows:
        buckets.setdefault(r["bucket"], []).append(r)
    return {name: aggregate(rs) for name, rs in sorted(buckets.items())}


def run(dataset_path, scorer):
    data = load_dataset(dataset_path)
    root = tempfile.mkdtemp(prefix="amk-eval-")
    try:
        os.makedirs(os.path.join(root, ".agent"), exist_ok=True)
        id_map, redacted = build_corpus(root, data["entries"])
        rows = [evaluate_query(root, q, id_map, scorer) for q in data["queries"]]
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return {
        "dataset": data.get("name", os.path.basename(dataset_path)),
        "scorer": scorer or "auto",
        "entries": len(data["entries"]),
        "redacted_entries": redacted,
        "overall": aggregate(rows),
        "by_bucket": by_bucket(rows),
        "queries": rows,
    }


def print_report(result):
    o = result["overall"]
    print("dataset: %s  ·  %d entries  ·  %d queries  ·  scorer=%s"
          % (result["dataset"], result["entries"], o["queries"], result["scorer"]))
    if result["redacted_entries"]:
        print("WARNING: redaction altered %d entr(ies) before scoring: %s"
              % (len(result["redacted_entries"]), ", ".join(result["redacted_entries"])))
    print()
    print("%-6s %-12s %-46s %6s %5s" % ("query", "bucket", "text", "rank", "top"))
    print("-" * 80)
    for r in result["queries"]:
        rank = r["first_gold_rank"]
        print("%-6s %-12s %-46s %6s %5.2f"
              % (r["id"], r["bucket"], r["text"][:46],
                 rank if rank else "MISS", r["top_score"]))
    print()
    print("overall: recall@1 %.3f · recall@3 %.3f · recall@5 %.3f · MRR %.3f · %d miss(es)"
          % (o["recall@1"], o["recall@3"], o["recall@5"], o["mrr"], o["misses"]))
    print()
    print("%-12s %7s %8s %8s %7s %7s" % ("bucket", "queries", "recall@1", "recall@3", "MRR", "misses"))
    for name, agg in result["by_bucket"].items():
        print("%-12s %7d %8.3f %8.3f %7.3f %7d"
              % (name, agg["queries"], agg["recall@1"], agg["recall@3"],
                 agg["mrr"], agg["misses"]))
    print()
    print("A MISS in the `paraphrase` bucket is expected, not a bug: this is "
          "lexical retrieval,\nand a query that shares no vocabulary with its "
          "answer is outside what it can do.\nSee evals/README.md.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--dataset", default=DEFAULT_DATASET)
    ap.add_argument("--scorer", choices=["auto", "bm25", "tfidf"], default="auto",
                    help="auto uses whatever session-memory would use by default")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    scorer = None if args.scorer == "auto" else args.scorer
    result = run(args.dataset, scorer)
    if args.json:
        print(json.dumps(result, indent=1, sort_keys=True))
    else:
        print_report(result)


if __name__ == "__main__":
    main()
