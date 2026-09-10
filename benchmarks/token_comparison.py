#!/usr/bin/env python3
"""
benchmarks :: token_comparison.py
Reproducible comparison: how many tokens does an agent spend answering a
fixed set of "getting oriented in an unfamiliar repo" questions, with
codebase-memory versus without it?

  python3 benchmarks/token_comparison.py --repo /path/to/target/repo \
      --spec benchmarks/specs/requests.json

Methodology, identical for every repo -- nothing here is hand-tuned per run:

  WITHOUT codebase-memory (the "naive" baseline). Three question kinds:
    - "def"    (where is X defined?)  -> grep for `class X`/`def X`,
      then read the full content of every distinct file the grep matched,
      in match order, capped at MAX_FILES_READ files. A bounded but
      realistic simulation of an agent opening a few promising files to
      confirm the real answer -- not the strawman of reading the whole
      repository, and not an unrealistically lucky "opens exactly the
      right file first try" either.
    - "callers" (what calls X?)       -> same, grepping for `X(`.
    - "file"   (what does file F contain/depend on?) -> read F in full.
      No grep needed -- this is literally what an agent does today to
      answer this question without an index.
    - "impact" (what breaks if I change F?) -> grep for imports of F's
      module across the repo, then read each matched file in full
      (capped, same as above).
  A file already read earlier in the same session is not re-charged if a
  later question happens to touch it again, the same way a real agent
  doesn't re-read something already in its context.

  WITH codebase-memory. `CODEBASE_MAP.md` is read once for the whole
  session (as AGENTS.md's own protocol requires at session start), then
  the single most appropriate `query.py <verb>` command runs per question.
  Cost = the map (once) + each query's stdout, summed.

Token counts use tiktoken's cl100k_base encoding if `tiktoken` is
importable (pip install tiktoken for exact provider-tokenizer counts);
otherwise this falls back to a chars/4 heuristic -- a commonly cited rule
of thumb for English prose and source code, and the same heuristic this
kit's own AGENTS.md budget checks use. Whichever counter is active, BOTH
sides of the comparison are measured with it, so the ratio between them is
meaningful regardless -- the active method is always printed and recorded
in the output.

Nothing here calls an LLM or the network. This measures the size of the
context an agent would have to read, which is what any provider's input
pricing bills against -- not model behaviour, and not a claim about answer
quality.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
QUERY_PY = os.path.join(HERE, "..", ".agent", "skills", "codebase-memory", "query.py")
INDEX_PY = os.path.join(HERE, "..", ".agent", "skills", "codebase-memory", "index.py")
MAX_FILES_READ = 6  # naive baseline: cap on distinct files opened in full per question

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
    COUNTER_NAME = "tiktoken cl100k_base"

    def count_tokens(text):
        return len(_ENC.encode(text, disallowed_special=()))
except ImportError:
    COUNTER_NAME = "chars/4 heuristic (tiktoken not installed)"

    def count_tokens(text):
        return max(1, len(text) // 4) if text else 0


def run(cmd, cwd, timeout=60):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return r.stdout, r.stderr, r.returncode


def grep(repo, pattern, ext="py"):
    """Returns (stdout_text, [distinct file paths in match order])."""
    stdout, _, code = run(["grep", "-rnE", "--include=*.%s" % ext, pattern, "."], cwd=repo)
    files, seen = [], set()
    for line in stdout.splitlines():
        path = line.split(":", 1)[0]
        if path not in seen:
            seen.add(path)
            files.append(path)
    return stdout, files


def read_capped(repo, files, already_read, cap):
    """Reads full content of files not already read this session, up to
    `cap` NEW files for this question. Returns (concatenated_text, newly_read_paths)."""
    text_parts = []
    newly_read = []
    budget = cap
    for f in files:
        if budget <= 0:
            break
        if f in already_read:
            continue
        full = os.path.join(repo, f)
        try:
            with open(full, encoding="utf-8", errors="ignore") as fh:
                text_parts.append(fh.read())
        except OSError:
            continue
        newly_read.append(f)
        budget -= 1
    return "\n".join(text_parts), newly_read


def naive_cost(repo, question, already_read):
    kind = question["kind"]
    if kind == "def":
        pattern = r"(class|def)\s+%s\b" % re.escape(question["symbol"])
        grep_out, files = grep(repo, pattern)
        read_text, newly_read = read_capped(repo, files, already_read, MAX_FILES_READ)
        already_read.update(newly_read)
        return count_tokens(grep_out) + count_tokens(read_text), len(newly_read)
    if kind == "callers":
        pattern = r"%s\(" % re.escape(question["symbol"])
        grep_out, files = grep(repo, pattern)
        read_text, newly_read = read_capped(repo, files, already_read, MAX_FILES_READ)
        already_read.update(newly_read)
        return count_tokens(grep_out) + count_tokens(read_text), len(newly_read)
    if kind == "file":
        path = question["path"]
        read_text, newly_read = read_capped(repo, [path], already_read, cap=1)
        already_read.update(newly_read)
        return count_tokens(read_text), len(newly_read)
    if kind == "impact":
        base = os.path.basename(question["path"]).rsplit(".py", 1)[0]
        # Matches both `from X.base import Y` and `import base` / `from X
        # import base` -- a line starting with from/import that also
        # contains the module's basename as a whole word anywhere after.
        pattern = r"^\s*(from|import)\s.*\b%s\b" % re.escape(base)
        grep_out, files = grep(repo, pattern)
        read_text, newly_read = read_capped(repo, files, already_read, MAX_FILES_READ)
        already_read.update(newly_read)
        return count_tokens(grep_out) + count_tokens(read_text), len(newly_read)
    raise ValueError("unknown question kind: %s" % kind)


def kit_verb_args(question):
    kind = question["kind"]
    if kind == "def":
        return ["def", question["symbol"]]
    if kind == "callers":
        return ["callers", question["symbol"]]
    if kind == "file":
        return ["file", question["path"]]
    if kind == "impact":
        return ["impact", question["path"]]
    raise ValueError("unknown question kind: %s" % kind)


def kit_cost(repo, question):
    args = kit_verb_args(question)
    stdout, stderr, code = run([sys.executable, QUERY_PY, "--root", repo] + args, cwd=HERE)
    return count_tokens(stdout), stdout


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", required=True, help="path to the target repo (already git-cloned)")
    p.add_argument("--spec", required=True, help="path to a benchmarks/specs/*.json question file")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--skip-build", action="store_true", help="assume the index is already built")
    args = p.parse_args()

    repo = os.path.abspath(args.repo)
    with open(args.spec, encoding="utf-8") as fh:
        spec = json.load(fh)

    if not args.skip_build:
        t0 = time.time()
        stdout, stderr, code = run([sys.executable, INDEX_PY, "build"], cwd=repo, timeout=600)
        if code != 0:
            sys.stderr.write("index build failed:\n%s\n" % stderr)
            sys.exit(1)
        build_elapsed = time.time() - t0
    else:
        build_elapsed = None

    map_path = os.path.join(repo, ".agent", "memory", "CODEBASE_MAP.md")
    with open(map_path, encoding="utf-8") as fh:
        map_text = fh.read()
    map_tokens = count_tokens(map_text)

    already_read = set()
    rows = []
    kit_total = map_tokens  # map read once per session, before any question
    naive_running = 0  # naive baseline never reads a map -- it doesn't have one

    for q in spec["questions"]:
        n_cost, n_files = naive_cost(repo, q, already_read)
        k_cost, k_out = kit_cost(repo, q)
        naive_running += n_cost
        kit_total += k_cost
        rows.append({
            "id": q["id"], "question": q["question"], "kind": q["kind"],
            "naive_tokens": n_cost, "naive_files_read": n_files,
            "kit_tokens": k_cost,
        })

    result = {
        "repo": spec.get("repo", os.path.basename(repo)),
        "counter": COUNTER_NAME,
        "build_seconds": round(build_elapsed, 2) if build_elapsed is not None else None,
        "codebase_map_tokens": map_tokens,
        "questions": rows,
        "totals": {
            "naive_tokens": naive_running,
            "kit_tokens": kit_total,
            "kit_tokens_excl_map": kit_total - map_tokens,
        },
    }

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print("== %s (%s) ==" % (result["repo"], COUNTER_NAME))
    if build_elapsed is not None:
        print("index build: %.2fs, CODEBASE_MAP.md = %d tokens" % (build_elapsed, map_tokens))
    print()
    print("%-10s %-45s %12s %12s" % ("kind", "question", "naive tokens", "kit tokens"))
    for r in rows:
        print("%-10s %-45s %12d %12d" % (r["kind"], r["question"][:45], r["naive_tokens"], r["kit_tokens"]))
    print()
    print("TOTAL (naive):                %d tokens" % result["totals"]["naive_tokens"])
    print("TOTAL (kit, map read once):   %d tokens (%d map + %d queries)" % (
        result["totals"]["kit_tokens"], map_tokens, result["totals"]["kit_tokens_excl_map"]))
    if result["totals"]["kit_tokens"] > 0:
        ratio = result["totals"]["naive_tokens"] / result["totals"]["kit_tokens"]
        print("ratio: naive used %.1fx more tokens than the kit-assisted session" % ratio)


if __name__ == "__main__":
    main()
