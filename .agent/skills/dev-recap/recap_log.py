#!/usr/bin/env python3
"""
dev-recap :: recap_log.py
Local, append-only logs behind the dev-recap closing protocol (see SKILL.md):
what got explained to the developer, how well they say they understood it,
and a heuristic scan for gaps a diff commonly hides. The *quiz itself* is
not generated here -- that needs real understanding of what was built, which
is the calling agent's job, not a stdlib script's. This file only logs the
outcome and does the parts that ARE mechanical: diffing, grepping, ranking.

  python .agent/skills/dev-recap/recap_log.py record-recap --task auth-retry \
      --files src/auth/retry.py,tests/test_retry.py --summary "..."
  python .agent/skills/dev-recap/recap_log.py record-quiz --topic auth-retry --result understood
  python .agent/skills/dev-recap/recap_log.py due-for-review
  python .agent/skills/dev-recap/recap_log.py gaps
  python .agent/skills/dev-recap/recap_log.py stats

Guarantees:
  * Python 3.8+ standard library only. No network. Writes only
    .agent/memory/learning/.
  * `gaps` reads `git diff` and, if present, codebase-memory's
    .agent/memory/graph/files.jsonl. It never writes to either.
  * Quiz results are for the developer's own benefit. Nothing here reports
    them anywhere else, aggregates them across developers, or scores anyone
    -- see the "AI ethics stance" in SKILL.md before wiring this into
    anything that touches a manager, a dashboard, or a review process. That
    is explicitly not what this is for.
"""

import argparse
import json
import os
import subprocess
import sys
import time

SCHEMA = 1
LEARNING_SUBDIR = os.path.join(".agent", "memory", "learning")
RECAP_FILE = "recap-log.jsonl"
QUIZ_FILE = "quiz-log.jsonl"
PROFILE_FILE = "profile-log.jsonl"
DEFAULT_REVIEW_DAYS = 14
FAMILIARITY_LEVELS = ("new", "some", "veteran")
MAX_SUMMARY_CHARS = 4000
CODE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".rb", ".php", ".java",
    ".kt", ".cs", ".c", ".h", ".cc", ".cpp", ".hpp", ".swift", ".scala",
}
QUIZ_SCORES = {"understood": 2, "partial": 1, "confused": -1}


def find_repo_root(start="."):
    p = os.path.abspath(start)
    for _ in range(10):
        if os.path.isdir(os.path.join(p, ".git")) or os.path.isdir(os.path.join(p, ".agent")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return os.path.abspath(start)


def learning_dir(root):
    return os.path.join(root, LEARNING_SUBDIR)


def recap_path(root):
    return os.path.join(learning_dir(root), RECAP_FILE)


def quiz_path(root):
    return os.path.join(learning_dir(root), QUIZ_FILE)


def profile_path(root):
    return os.path.join(learning_dir(root), PROFILE_FILE)


def _append(path, entry):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def _load(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ------------------------------------------------------------------ recap --

def record_recap(root, session_id, task, files, summary, cwd=None):
    summary = (summary or "").strip()[:MAX_SUMMARY_CHARS]
    entry = {
        "ts": _now(), "session_id": session_id or "unknown", "task": task or "untitled",
        "files": files or [], "summary": summary, "cwd": cwd or root,
    }
    _append(recap_path(root), entry)
    _mirror_to_session_memory(root, session_id, cwd, task, summary)
    return entry


def _mirror_to_session_memory(root, session_id, cwd, task, summary):
    """Best-effort: if session-memory is also installed in this repo, drop a
    note there too so its cross-session TF-IDF recall picks this up. Silent
    no-op if session-memory isn't present -- dev-recap must work standalone."""
    sess_dir = os.path.join(root, ".agent", "skills", "session-memory")
    if not os.path.isdir(sess_dir):
        return
    try:
        sys.path.insert(0, sess_dir)
        import memory as sess_mem  # type: ignore
        sess_mem.append_entry(root, session_id, cwd or root, "note",
                               "[dev-recap: %s] %s" % (task, summary))
    except Exception:
        pass


# ------------------------------------------------------------------- quiz --

def record_quiz(root, session_id, topic, result, notes=""):
    if result not in QUIZ_SCORES:
        raise ValueError("result must be one of: %s" % ", ".join(QUIZ_SCORES))
    entry = {"ts": _now(), "session_id": session_id or "unknown", "topic": topic,
              "result": result, "notes": (notes or "")[:1000]}
    _append(quiz_path(root), entry)
    return entry


def topic_strength(root):
    """topic -> {score, last_ts, count}. score is a simple 0..N running
    total (understood +2, partial +1, confused -1, floored at 0) -- a
    deliberately crude proxy for "does this still need reinforcing", not a
    grade. Nothing here compares developers to each other."""
    strength = {}
    for e in _load(quiz_path(root)):
        t = e.get("topic")
        if not t:
            continue
        s = strength.setdefault(t, {"score": 0, "last_ts": "", "count": 0})
        s["score"] = max(0, s["score"] + QUIZ_SCORES.get(e.get("result"), 0))
        s["last_ts"] = max(s["last_ts"], e.get("ts", ""))
        s["count"] += 1
    return strength


def due_for_review(root, limit=10, stale_days=DEFAULT_REVIEW_DAYS):
    strength = topic_strength(root)
    if not strength:
        return []
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - stale_days * 86400))
    due = []
    for topic, s in strength.items():
        stale = s["last_ts"] < cutoff
        weak = s["score"] <= 1
        if stale or weak:
            due.append((s["score"], s["last_ts"], topic, stale, weak))
    due.sort(key=lambda t: (t[0], t[1]))  # weakest, then longest-untouched, first
    return [{"topic": t, "score": sc, "last_reviewed": ts,
              "reason": "stale" if stale and not weak else ("weak" if weak and not stale else "stale+weak")}
             for sc, ts, t, stale, weak in due[:limit]]


# ---------------------------------------------------------------- profile -

def set_familiarity(root, session_id, level, notes=""):
    """Record how familiar the developer says they are with *this specific
    project* -- not a general skill rating. Append-only, like everything
    else here: the latest entry is the current profile, older ones are kept
    as history (a new hire becoming a veteran six months in is a real,
    worth-keeping fact, not something to overwrite silently)."""
    if level not in FAMILIARITY_LEVELS:
        raise ValueError("level must be one of: %s" % ", ".join(FAMILIARITY_LEVELS))
    entry = {"ts": _now(), "session_id": session_id or "unknown", "level": level,
              "notes": (notes or "")[:1000]}
    _append(profile_path(root), entry)
    return entry


def current_familiarity(root):
    entries = list(_load(profile_path(root)))
    return entries[-1] if entries else None


# ------------------------------------------------------------------- gaps --

def _run(cmd, cwd):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=20)
        return r.returncode, r.stdout, r.stderr
    except Exception:
        return 1, "", ""


def _is_git_repo(root):
    code, out, _ = _run(["git", "rev-parse", "--is-inside-work-tree"], root)
    return code == 0 and out.strip() == "true"


def _changed_files(root, base=None):
    if base:
        code, out, _ = _run(["git", "diff", "--name-only", base, "HEAD"], root)
        if code == 0 and out.strip():
            return [l for l in out.splitlines() if l.strip()]
    code, out, _ = _run(["git", "diff", "--name-only", "HEAD"], root)
    files = [l for l in out.splitlines() if l.strip()] if code == 0 else []
    code, out, _ = _run(["git", "diff", "--name-only", "--cached"], root)
    files += [l for l in out.splitlines() if l.strip() and l not in files] if code == 0 else []
    return files


def _added_lines_with_markers(root, base):
    diff_cmd = ["git", "diff"] + ([base, "HEAD"] if base else ["HEAD"])
    code, out, _ = _run(diff_cmd, root)
    if code != 0:
        return {}
    hits = {}
    current_file = None
    for line in out.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
        elif line.startswith("+") and not line.startswith("+++"):
            if any(m in line for m in ("TODO", "FIXME", "XXX")):
                hits.setdefault(current_file, []).append(line[1:].strip()[:160])
    return hits


def _looks_like_test_touched(changed, path):
    base = os.path.splitext(os.path.basename(path))[0]
    candidates = ("test_%s" % base, "%s_test" % base, "%s.test" % base, "%s.spec" % base)
    return any(any(c in other for c in candidates) for other in changed if other != path)


def _codebase_memory_indexed(root, path):
    files_jsonl = os.path.join(root, ".agent", "memory", "graph", "files.jsonl")
    if not os.path.exists(files_jsonl):
        return None  # codebase-memory not built here -- not applicable, not a gap
    try:
        with open(files_jsonl, encoding="utf-8") as fh:
            for line in fh:
                rec = json.loads(line)
                # codebase-memory's files.jsonl uses short keys ("p" for
                # path, see index.py's write_jsonl) -- this checked "path"
                # instead, so it never matched anything and every changed
                # file was reported as unindexed regardless of truth.
                if rec.get("p") == path:
                    return True
    except Exception:
        return None
    return False


def gaps(root, base=None):
    if not _is_git_repo(root):
        return {"applicable": False, "reason": "not a git repository -- nothing to diff"}

    changed = [f for f in _changed_files(root, base)
               if os.path.splitext(f)[1] in CODE_EXTS]
    if not changed:
        return {"applicable": True, "changed_files": 0, "findings": [],
                 "note": "no changed code files found (clean tree, or base has no diff)"}

    markers = _added_lines_with_markers(root, base)
    findings = []
    for path in changed:
        item = {"path": path}
        if not _looks_like_test_touched(changed, path):
            item["no_test_touched"] = (
                "no file matching test_%s / %s_test / %s.spec was touched in this diff "
                "(heuristic -- a test may already exist and just wasn't changed; verify "
                "before concluding coverage is missing)" % (
                    os.path.splitext(os.path.basename(path))[0],
                    os.path.splitext(os.path.basename(path))[0],
                    os.path.splitext(os.path.basename(path))[0]))
        if path in markers:
            item["new_todo_markers"] = markers[path]
        indexed = _codebase_memory_indexed(root, path)
        if indexed is False:
            item["not_in_codebase_index"] = (
                "codebase-memory is built here but doesn't have this path -- "
                "rebuild the index, or it's excluded (see .agentignore/.gitignore)")
        if len(item) > 1:
            findings.append(item)

    return {"applicable": True, "changed_files": len(changed), "findings": findings}


# ------------------------------------------------------------------ stats --

def stats(root):
    recaps = list(_load(recap_path(root)))
    quizzes = list(_load(quiz_path(root)))
    profile = current_familiarity(root)
    return {
        "schema": SCHEMA, "recaps": len(recaps), "quizzes": len(quizzes),
        "topics_tracked": len(topic_strength(root)),
        "familiarity": profile.get("level") if profile else None,
        "recap_path": recap_path(root), "quiz_path": quiz_path(root),
    }


# ----------------------------------------------------------------- cli ----

def cmd_record_recap(args):
    root = find_repo_root(args.root)
    summary = args.summary
    if summary == "-":
        summary = sys.stdin.read()
    files = [f.strip() for f in (args.files or "").split(",") if f.strip()]
    e = record_recap(root, args.session, args.task, files, summary, cwd=args.root)
    print(json.dumps(e, sort_keys=True))


def cmd_record_quiz(args):
    root = find_repo_root(args.root)
    e = record_quiz(root, args.session, args.topic, args.result, args.notes)
    print(json.dumps(e, sort_keys=True))


def cmd_due(args):
    root = find_repo_root(args.root)
    rows = due_for_review(root, limit=args.limit, stale_days=args.stale_days)
    if args.json:
        print(json.dumps(rows, indent=1))
        return
    if not rows:
        print("(nothing due for review)")
        return
    for r in rows:
        print("%-30s score=%d last=%s (%s)" % (r["topic"], r["score"],
                                                 r["last_reviewed"] or "never", r["reason"]))


def cmd_gaps(args):
    root = find_repo_root(args.root)
    result = gaps(root, base=args.base)
    if args.json:
        print(json.dumps(result, indent=1))
        return
    if not result.get("applicable"):
        print(result.get("reason"))
        return
    if not result.get("findings"):
        print("no gaps flagged by the heuristic scan (%d changed file(s) checked). "
              "This is a lead, not proof -- it does not check logic correctness." % result["changed_files"])
        return
    for item in result["findings"]:
        print("- %s" % item["path"])
        if "no_test_touched" in item:
            print("    test:  %s" % item["no_test_touched"])
        if "new_todo_markers" in item:
            for m in item["new_todo_markers"]:
                print("    todo:  %s" % m)
        if "not_in_codebase_index" in item:
            print("    index: %s" % item["not_in_codebase_index"])


def cmd_set_familiarity(args):
    root = find_repo_root(args.root)
    e = set_familiarity(root, args.session, args.level, args.notes)
    print(json.dumps(e, sort_keys=True))


def cmd_get_familiarity(args):
    root = find_repo_root(args.root)
    profile = current_familiarity(root)
    if args.json:
        print(json.dumps(profile))
        return
    if not profile:
        print("no familiarity profile recorded yet for this project")
        return
    print("%s (recorded %s%s)" % (profile["level"], profile["ts"],
                                    ", notes: %s" % profile["notes"] if profile.get("notes") else ""))


def cmd_stats(args):
    root = find_repo_root(args.root)
    s = stats(root)
    print(json.dumps(s, indent=1) if args.json else "\n".join("%s: %s" % kv for kv in s.items()))


def main():
    p = argparse.ArgumentParser(prog="recap_log.py")
    p.add_argument("--root", default=".")
    sub = p.add_subparsers(dest="cmd", required=True)

    rr = sub.add_parser("record-recap")
    rr.add_argument("--session", default="cli")
    rr.add_argument("--task", default="untitled")
    rr.add_argument("--files", default="", help="comma-separated paths")
    rr.add_argument("--summary", required=True, help="text, or '-' to read stdin")
    rr.set_defaults(func=cmd_record_recap)

    rq = sub.add_parser("record-quiz")
    rq.add_argument("--session", default="cli")
    rq.add_argument("--topic", required=True)
    rq.add_argument("--result", required=True, choices=list(QUIZ_SCORES))
    rq.add_argument("--notes", default="")
    rq.set_defaults(func=cmd_record_quiz)

    sf_ = sub.add_parser("set-familiarity")
    sf_.add_argument("--session", default="cli")
    sf_.add_argument("--level", required=True, choices=list(FAMILIARITY_LEVELS))
    sf_.add_argument("--notes", default="")
    sf_.set_defaults(func=cmd_set_familiarity)

    gf = sub.add_parser("get-familiarity")
    gf.add_argument("--json", action="store_true")
    gf.set_defaults(func=cmd_get_familiarity)

    d = sub.add_parser("due-for-review")
    d.add_argument("--limit", type=int, default=10)
    d.add_argument("--stale-days", type=int, default=DEFAULT_REVIEW_DAYS)
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_due)

    g = sub.add_parser("gaps")
    g.add_argument("--base", default=None, help="git ref to diff against (default: working tree vs HEAD)")
    g.add_argument("--json", action="store_true")
    g.set_defaults(func=cmd_gaps)

    s = sub.add_parser("stats")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_stats)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
