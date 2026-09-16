#!/usr/bin/env python3
"""
session-memory :: memory.py
An append-only, local log of prompts and turns in this repo, recalled by
lexical (BM25) similarity so a session that starts cold can pick up context
a previous, separate session already established.

  python .agent/skills/session-memory/memory.py record --kind prompt --text "..."
  python .agent/skills/session-memory/memory.py recall "how does auth work" --limit 5
  python .agent/skills/session-memory/memory.py recent --limit 5
  python .agent/skills/session-memory/memory.py stats
  python .agent/skills/session-memory/memory.py prune --keep-last 4000

Guarantees:
  * Python 3.8+ standard library only. No network. No daemon. No installs.
  * Writes ONLY inside .agent/memory/session/.
  * Every write passes through redact() first -- best-effort, not a guarantee.
  * Ranking is Okapi BM25 over a code-aware tokenizer (identifiers are
    split, so `getUserById` is reachable by the words "user" and "id"): a
    lexical/keyword method, not a trained embedding model. It finds entries
    that share vocabulary with the query, not entries that are conceptually
    similar but worded differently. `evals/` in the kit repo measures both
    the gain and the remaining blind spot.

Hooks (.agent/skills/session-memory/hooks/) import this module directly
instead of shelling out, so all normal Claude Code hook JSON handling and
fail-open behaviour lives there, not here.
"""

import argparse
import json
import math
import os
import re
import sys
import time
import uuid
from collections import Counter

SCHEMA = 1
MEMORY_SUBDIR = os.path.join(".agent", "memory", "session")
ENTRIES_FILE = "entries.jsonl"
MAP_STATE_FILE = "map_state.json"
MANIFEST_REL = os.path.join(".agent", "memory", "graph", "manifest.json")
MAX_TEXT_CHARS = 4000
DEFAULT_KEEP_LAST = 4000
DEFAULT_RECALL_LIMIT = 5
MIN_SCORE = 0.05
DISABLE_ENV = "AGENT_MEMORY_KIT_DISABLE_SESSION_MEMORY"


def disabled():
    """Org-wide or per-developer opt-out (e.g. via a shell profile pushed by
    MDM, or a compliance policy): set this env var and every entry point
    into this module -- hooks, the CLI, and mcp-bridge's tool calls alike --
    becomes a silent no-op. The hooks also short-circuit earlier, before
    reaching this module at all (see hooks/_common.py); this guard is what
    makes the same opt-out apply to direct CLI/MCP use, not just hooks."""
    return os.environ.get(DISABLE_ENV, "").strip().lower() in ("1", "true", "yes")

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "so", "for", "to",
    "of", "in", "on", "at", "by", "with", "is", "are", "was", "were", "be",
    "been", "being", "this", "that", "these", "those", "it", "its", "as",
    "from", "into", "not", "no", "yes", "you", "your", "we", "our", "i",
    "me", "my", "do", "does", "did", "can", "could", "should", "would",
    "will", "shall", "have", "has", "had", "what", "why", "how", "when",
    "where", "which", "who", "please", "just", "also", "like",
}

SECRET_PATTERNS = [re.compile(p) for p in [
    r"AKIA[0-9A-Z]{16}",
    r"(?i)(api[_-]?key|secret|token|passwd|password)\s*[:=]\s*['\"]?[A-Za-z0-9_\-./+]{8,}",
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
]]

# .../.agent/skills/session-memory/memory.py -> .../.agent/lib/
_HERE = os.path.dirname(os.path.abspath(__file__))
_LIB_DIR = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "lib")
_UNSET = object()
_shared = _UNSET


def shared_retrieval():
    """`.agent/lib/retrieval.py` if it is installed alongside this skill,
    else None. Guarded on purpose: a developer who copied only this skill's
    files still gets working recall, just the older lexical path -- the same
    fail-open posture every hook in this skill already takes. Resolved once
    and cached; the answer cannot change mid-process."""
    global _shared
    if _shared is _UNSET:
        _shared = None
        if os.path.isfile(os.path.join(_LIB_DIR, "retrieval.py")):
            try:
                if _LIB_DIR not in sys.path:
                    sys.path.insert(0, _LIB_DIR)
                import retrieval
                _shared = retrieval
            except Exception:
                _shared = None
    return _shared


# --------------------------------------------------------------------- io ---

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


def memory_dir(root):
    return os.path.join(root, MEMORY_SUBDIR)


def entries_path(root):
    return os.path.join(memory_dir(root), ENTRIES_FILE)


def map_state_path(root):
    return os.path.join(memory_dir(root), MAP_STATE_FILE)


def current_map_generation(root):
    """The generation hash codebase-memory just built, straight from its
    manifest -- cheap (a few hundred bytes), unlike reading CODEBASE_MAP.md
    itself. None if codebase-memory isn't installed or hasn't been built
    here yet."""
    path = os.path.join(root, MANIFEST_REL)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("generation")
    except Exception:
        return None


def record_map_generation(root, generation, session_id):
    """Stamps 'this session's end saw the map at generation X' -- current
    state, not a log, so this overwrites rather than appends. Called from
    the Stop hook: by the time a session ends, AGENTS.md's own protocol
    already required it to have read the map at whatever generation was
    current, so this is a record of that, not a new claim."""
    if not generation:
        return
    d = memory_dir(root)
    os.makedirs(d, exist_ok=True)
    entry = {"generation": generation, "session_id": session_id or "unknown",
              "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    path = map_state_path(root)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(entry, fh, sort_keys=True)
    os.replace(tmp, path)


def map_generation_state(root):
    path = map_state_path(root)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def redact(text):
    for pat in SECRET_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


def load_entries(root):
    path = entries_path(root)
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue  # never let one bad line break recall/record


def rewrite_entries(root, entries):
    d = memory_dir(root)
    os.makedirs(d, exist_ok=True)
    path = entries_path(root)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e, sort_keys=True) + "\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------- writing ---

def append_entry(root, session_id, cwd, kind, text, tags=None):
    if disabled():
        return None
    text = redact((text or "").strip())
    if not text:
        return None
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + " …[truncated]"
    entry = {
        "id": uuid.uuid4().hex[:10],
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session_id": session_id or "unknown",
        "cwd": cwd or "",
        "kind": kind,
        "text": text,
        "tags": tags or [],
        "weight": 1,
    }
    d = memory_dir(root)
    os.makedirs(d, exist_ok=True)
    with open(entries_path(root), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def bump_weight(root, ids, amount=1):
    ids = set(ids)
    if not ids:
        return
    entries = list(load_entries(root))
    changed = False
    for e in entries:
        if e.get("id") in ids:
            e["weight"] = int(e.get("weight", 1)) + amount
            changed = True
    if changed:
        rewrite_entries(root, entries)


# --------------------------------------------------------------- ranking ---

def tokenize_plain(text):
    """The v0.4.0 tokenizer, kept verbatim. It lowercases before splitting,
    so `getUserById` collapses to one opaque term and a later plain-words
    question about it recalls nothing. That defect is why the code-aware
    tokenizer exists -- this stays as the fallback when `.agent/lib/` was
    not installed, and as the baseline arm `evals/recall_eval.py --scorer
    tfidf` measures against, so the improvement is reproducible rather than
    asserted."""
    return [t for t in re.findall(r"[a-z0-9]{2,}", (text or "").lower())
            if t not in STOPWORDS]


def tokenize(text):
    """The active tokenizer: code-aware when `.agent/lib/retrieval.py` is
    installed, the v0.4.0 behaviour otherwise."""
    shared = shared_retrieval()
    if shared is not None:
        return shared.tokenize(text, STOPWORDS)
    return tokenize_plain(text)


def resolve_scorer(scorer=None):
    """Which retrieval method to use. Each name selects a *pair* -- tokenizer
    and ranker together -- because measuring one without the other would not
    describe any version this kit has ever shipped:

      "bm25"  code-aware tokenizer + Okapi BM25   (current default)
      "tfidf" v0.4.0 tokenizer + TF-IDF cosine    (fallback, and the baseline)

    None means "whatever this installation would use by default"."""
    if scorer == "tfidf":
        return "tfidf"
    if scorer == "bm25":
        if shared_retrieval() is None:
            raise ValueError(
                "bm25 needs .agent/lib/retrieval.py, which is not installed here")
        return "bm25"
    return "bm25" if shared_retrieval() is not None else "tfidf"


def _tf_weight(tf):
    return 0.0 if tf <= 0 else 1.0 + math.log(tf)


def _build_idf(doc_tokens, n_docs):
    df = Counter()
    for toks in doc_tokens:
        df.update(set(toks))
    return {term: math.log((1.0 + n_docs) / (1.0 + c)) + 1.0 for term, c in df.items()}


def _vector(tokens, idf):
    tf = Counter(tokens)
    vec = {}
    for term, count in tf.items():
        w = idf.get(term)
        if w is None:
            continue
        vec[term] = _tf_weight(count) * w
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {k: v / norm for k, v in vec.items()}


def _cosine(a, b):
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


def _similarities(entries, query_text, method):
    """One similarity per entry, same order, in [0, 1]. Both arms return the
    same shape and the same scale, so everything downstream -- the weight
    boost, `min_score`, the hooks' injection thresholds -- is unchanged by
    which one ran."""
    if method == "bm25":
        shared = shared_retrieval()

        def tok(text):
            return shared.tokenize(text, STOPWORDS)

        qtokens = tok(query_text)
        if not qtokens:
            return None
        return shared.BM25([tok(e.get("text", "")) for e in entries]).score(qtokens)

    doc_tokens = [tokenize_plain(e.get("text", "")) for e in entries]
    idf = _build_idf(doc_tokens, len(entries))
    qvec = _vector(tokenize_plain(query_text), idf)
    if not qvec:
        return None
    return [_cosine(qvec, _vector(toks, idf)) for toks in doc_tokens]


def recall(root, query_text, limit=DEFAULT_RECALL_LIMIT, exclude_session=None,
           kinds=None, min_score=MIN_SCORE, scorer=None):
    if disabled():
        return []
    entries = list(load_entries(root))
    if exclude_session:
        entries = [e for e in entries if e.get("session_id") != exclude_session]
    if kinds:
        entries = [e for e in entries if e.get("kind") in kinds]
    if not entries:
        return []

    sims = _similarities(entries, query_text, resolve_scorer(scorer))
    if sims is None:
        return []

    scored = []
    for e, sim in zip(entries, sims):
        if sim <= 0:
            continue
        # Mild reinforcement: entries that have proven relevant before (their
        # `weight` was bumped by a prior recall — see bump_weight) rank a
        # little higher than a same-similarity entry that never has. This is
        # a frequency heuristic, not a trained model or true RL.
        boosted = sim * (1.0 + 0.03 * min(int(e.get("weight", 1)), 20))
        scored.append((boosted, sim, e))

    scored.sort(key=lambda t: t[0], reverse=True)
    out = [(e, sim) for boosted, sim, e in scored if sim >= min_score][:limit]
    return out


def recent(root, exclude_session=None, limit=DEFAULT_RECALL_LIMIT, one_per_session=True):
    if disabled():
        return []
    # load_entries() yields in append (chronological) order. Timestamps only
    # have 1-second resolution, so two entries written in the same second --
    # common, e.g. two prompts in quick succession -- can tie on `ts`. Sort
    # by (ts, original position) so ties break toward the one written later,
    # not toward Python's stable-sort default of "keeps original order",
    # which would silently prefer the *older* of two tied entries.
    entries = [e for e in load_entries(root)
               if not exclude_session or e.get("session_id") != exclude_session]
    entries = [e for _, e in sorted(enumerate(entries),
                                     key=lambda pair: (pair[1].get("ts", ""), pair[0]),
                                     reverse=True)]
    if not one_per_session:
        return entries[:limit]
    out, seen = [], set()
    for e in entries:
        sid = e.get("session_id")
        if sid in seen:
            continue
        seen.add(sid)
        out.append(e)
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------- upkeep -----

def stats(root):
    entries = list(load_entries(root))
    by_kind = Counter(e.get("kind") for e in entries)
    sessions = {e.get("session_id") for e in entries}
    ts = sorted(e.get("ts", "") for e in entries)
    return {
        "schema": SCHEMA,
        "entries": len(entries),
        "sessions": len(sessions),
        "by_kind": dict(by_kind),
        "oldest": ts[0] if ts else None,
        "newest": ts[-1] if ts else None,
        "path": entries_path(root),
    }


def prune(root, keep_last=DEFAULT_KEEP_LAST, keep_days=None):
    entries = list(load_entries(root))
    before = len(entries)
    if keep_days is not None:
        cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                time.gmtime(time.time() - keep_days * 86400))
        entries = [e for e in entries if e.get("ts", "") >= cutoff]
    entries.sort(key=lambda e: (e.get("ts", ""), int(e.get("weight", 1))))
    if len(entries) > keep_last:
        entries = entries[-keep_last:]
    entries.sort(key=lambda e: e.get("ts", ""))
    rewrite_entries(root, entries)
    return {"before": before, "after": len(entries)}


# ----------------------------------------------------------------- cli ----

def _snippet(text, n=140):
    text = text.replace("\n", " ").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def cmd_record(args):
    root = find_repo_root(args.root)
    if disabled():
        print("(session-memory disabled via %s, not recorded)" % DISABLE_ENV)
        return
    text = args.text
    if text == "-":
        text = sys.stdin.read()
    e = append_entry(root, args.session, args.cwd, args.kind, text)
    print(json.dumps(e, sort_keys=True) if e else "(empty text, not recorded)")


def cmd_recall(args):
    root = find_repo_root(args.root)
    hits = recall(root, args.query, limit=args.limit, exclude_session=args.exclude_session)
    if args.json:
        print(json.dumps([{"score": round(s, 3), **e} for e, s in hits], indent=1))
        return
    if not hits:
        print("(no related entries)")
        return
    for e, s in hits:
        print("[%.2f] %s %s :: %s" % (s, e.get("ts"), e.get("kind"), _snippet(e.get("text", ""))))


def cmd_recent(args):
    root = find_repo_root(args.root)
    rows = recent(root, exclude_session=args.exclude_session, limit=args.limit)
    if args.json:
        print(json.dumps(rows, indent=1))
        return
    if not rows:
        print("(no prior sessions recorded)")
        return
    for e in rows:
        print("%s [%s] %s :: %s" % (e.get("ts"), e.get("session_id", "")[:8],
                                     e.get("kind"), _snippet(e.get("text", ""))))


def cmd_stats(args):
    root = find_repo_root(args.root)
    s = stats(root)
    print(json.dumps(s, indent=1) if args.json else "\n".join("%s: %s" % kv for kv in s.items()))


def cmd_prune(args):
    root = find_repo_root(args.root)
    r = prune(root, keep_last=args.keep_last, keep_days=args.keep_days)
    print("pruned %d -> %d entries" % (r["before"], r["after"]))


def cmd_verify(args):
    root = find_repo_root(args.root)
    path = entries_path(root)
    if not os.path.exists(path):
        print("no session memory yet (this is normal on first use)")
        return
    bad = 0
    total = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                json.loads(line)
            except json.JSONDecodeError:
                bad += 1
    print("OK: %d entries, %d unreadable line(s)" % (total, bad) if bad == 0
          else "DAMAGED: %d/%d lines unreadable -- consider pruning/rebuilding" % (bad, total))


def main():
    p = argparse.ArgumentParser(prog="memory.py")
    p.add_argument("--root", default=".")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record")
    r.add_argument("--session", default="cli")
    r.add_argument("--cwd", default=".")
    r.add_argument("--kind", default="note", choices=["prompt", "turn", "note"])
    r.add_argument("--text", required=True, help="text, or '-' to read stdin")
    r.set_defaults(func=cmd_record)

    c = sub.add_parser("recall")
    c.add_argument("query")
    c.add_argument("--limit", type=int, default=DEFAULT_RECALL_LIMIT)
    c.add_argument("--exclude-session", default=None)
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_recall)

    n = sub.add_parser("recent")
    n.add_argument("--limit", type=int, default=DEFAULT_RECALL_LIMIT)
    n.add_argument("--exclude-session", default=None)
    n.add_argument("--json", action="store_true")
    n.set_defaults(func=cmd_recent)

    s = sub.add_parser("stats")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_stats)

    pr = sub.add_parser("prune")
    pr.add_argument("--keep-last", type=int, default=DEFAULT_KEEP_LAST)
    pr.add_argument("--keep-days", type=int, default=None)
    pr.set_defaults(func=cmd_prune)

    v = sub.add_parser("verify")
    v.set_defaults(func=cmd_verify)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
