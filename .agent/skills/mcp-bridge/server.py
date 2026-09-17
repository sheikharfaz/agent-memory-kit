#!/usr/bin/env python3
"""
agent-memory-kit :: MCP bridge.

A minimal, stdlib-only Model Context Protocol server -- stdio transport,
newline-delimited JSON-RPC 2.0, per https://modelcontextprotocol.io -- that
exposes this kit's local index and cross-session recall as live tools, for
any MCP-capable host (Claude Code, Claude Desktop, Cursor, ...), not just
Claude Code's own SessionStart/UserPromptSubmit/Stop hooks.

  python3 .agent/skills/mcp-bridge/server.py --root /path/to/repo

Every tool is a thin, direct passthrough to the same scripts the CLI and
hooks already use (query.py, index.py, memory.py) -- no duplicated logic,
so an MCP result always matches what `python query.py <verb>` would print.
Exactly two tools write anything: `codebase_build` (only
.agent/memory/graph/ and CODEBASE_MAP.md -- the kit's own generated cache)
and `session_remember` (appends one `note` entry to session-memory's own
log). Every other tool is read-only, and none of them ever touch the
network. tool-provisioning's install/uninstall, and dev-recap's and
spec-first's write verbs, are deliberately NOT exposed here -- see
SKILL.md for why: those are judgment-heavy or install-something flows this
kit already keeps propose-only and human-approved in chat, and turning
them into raw callable tools would quietly undo that safety posture for
any MCP host that lacks the same conversational guardrail.

No `mcp` package, no third-party dependency of any kind: this hand-rolls
the small slice of the MCP spec a tools-only, no-resources, no-prompts
server actually needs -- initialize, tools/list, tools/call -- directly
over stdin/stdout.
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.dirname(HERE)
INDEX_PY = os.path.join(SKILLS_DIR, "codebase-memory", "index.py")
QUERY_PY = os.path.join(SKILLS_DIR, "codebase-memory", "query.py")
MEMORY_PY = os.path.join(SKILLS_DIR, "session-memory", "memory.py")

sys.path.insert(0, os.path.join(SKILLS_DIR, "session-memory"))
import memory as mem  # noqa: E402 -- reuse find_repo_root, one definition

SERVER_NAME = "agent-memory-kit"
SERVER_VERSION = "0.6.4"
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_TIMEOUT = 45
BUILD_TIMEOUT = 300

DEFAULT_ROOT = None  # set in main()


# ------------------------------------------------------------------ errors --

class ToolInputError(Exception):
    """A handler's arguments were missing or malformed -- becomes isError."""


# --------------------------------------------------------------- subprocess -

def _run(argv, cwd, timeout=DEFAULT_TIMEOUT, ok_codes=(0,)):
    try:
        r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                            timeout=timeout, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return False, "timed out after %ss: %s" % (timeout, " ".join(argv))
    except Exception as exc:
        return False, "failed to run %s: %s" % (os.path.basename(argv[1]), exc)
    ok = r.returncode in ok_codes
    out = (r.stdout or "").rstrip("\n")
    err = (r.stderr or "").strip()
    if ok:
        # success: stdout/stderr split is an implementation detail here, not
        # a signal worth flagging -- e.g. index.py build's summary line is
        # stderr by convention, and isError is already False for it.
        text = "\n".join(p for p in (out, err) if p)
    else:
        text = out
        if err:
            text = (text + "\n[stderr] " + err) if text else ("[stderr] " + err)
    if not text.strip():
        text = "(no output, exit code %d)" % r.returncode
    return ok, text


def _index_argv(sub, extra, root):
    return [sys.executable, INDEX_PY, sub] + extra + ["--root", root]


def _query_argv(verb, extra, root):
    return [sys.executable, QUERY_PY, "--root", root, verb] + extra


def _memory_argv(sub, extra, root):
    return [sys.executable, MEMORY_PY, "--root", root, sub] + extra


def _require(args, key):
    v = args.get(key)
    if v is None or (isinstance(v, str) and not v.strip()):
        raise ToolInputError("missing required argument: %r" % key)
    return v


def _limit(args):
    n = args.get("limit")
    if n is None:
        return []
    try:
        n = int(n)
    except (TypeError, ValueError):
        raise ToolInputError("'limit' must be an integer")
    return ["--limit", str(n)]


# -------------------------------------------------------------- tool handlers

def h_codebase_verify(a, root):
    return _run(_index_argv("verify", [], root), root, ok_codes=(0, 2))


def h_codebase_build(a, root):
    return _run(_index_argv("build", [], root), root, timeout=BUILD_TIMEOUT)


def h_codebase_arch(a, root):
    return _run(_query_argv("arch", _limit(a), root), root)


def h_codebase_def(a, root):
    name = _require(a, "name")
    extra = [name] + (["--fuzzy"] if a.get("fuzzy") else []) + _limit(a)
    return _run(_query_argv("def", extra, root), root)


def h_codebase_callers(a, root):
    name = _require(a, "name")
    extra = [name] + (["--fuzzy"] if a.get("fuzzy") else []) + _limit(a)
    return _run(_query_argv("callers", extra, root), root)


def h_codebase_callees(a, root):
    path = _require(a, "path")
    return _run(_query_argv("callees", [path], root), root)


def h_codebase_search(a, root):
    pattern = _require(a, "pattern")
    extra = [pattern]
    if a.get("kind"):
        extra += ["--kind", a["kind"]]
    if a.get("module"):
        extra += ["--module", a["module"]]
    extra += _limit(a)
    return _run(_query_argv("search", extra, root), root)


def h_codebase_find(a, root):
    words = _require(a, "query")
    extra = [str(words)]
    if a.get("kind"):
        extra += ["--kind", a["kind"]]
    extra += _limit(a)
    return _run(_query_argv("find", extra, root), root)


def h_codebase_file(a, root):
    path = _require(a, "path")
    return _run(_query_argv("file", [path] + _limit(a), root), root)


def h_codebase_importers(a, root):
    target = _require(a, "target")
    return _run(_query_argv("importers", [target] + _limit(a), root), root)


def h_codebase_routes(a, root):
    extra = [a["pattern"]] if a.get("pattern") else []
    return _run(_query_argv("routes", extra + _limit(a), root), root)


def h_codebase_impact(a, root):
    path = _require(a, "path")
    return _run(_query_argv("impact", [path] + _limit(a), root), root)


def h_codebase_changed(a, root):
    extra = ["--base", a["base"]] if a.get("base") else []
    return _run(_query_argv("changed", extra, root), root)


def h_codebase_coverage(a, root):
    paths = a.get("paths")
    if not paths or not isinstance(paths, list):
        raise ToolInputError("'paths' must be a non-empty array of file paths")
    return _run(_query_argv("coverage", [str(p) for p in paths], root), root)


def h_codebase_orphans(a, root):
    return _run(_query_argv("orphans", _limit(a), root), root)


def h_codebase_stats(a, root):
    return _run(_query_argv("stats", [], root), root)


def h_codebase_drift(a, root):
    extra = ["--last", str(a["last"])] if a.get("last") else []
    return _run(_query_argv("drift", extra + _limit(a), root), root)


def h_session_recall(a, root):
    query = _require(a, "query")
    extra = [query, "--json"]
    if a.get("limit"):
        extra += ["--limit", str(a["limit"])]
    return _run(_memory_argv("recall", extra, root), root)


def h_session_recent(a, root):
    extra = ["--json"]
    if a.get("limit"):
        extra += ["--limit", str(a["limit"])]
    return _run(_memory_argv("recent", extra, root), root)


def h_session_stats(a, root):
    return _run(_memory_argv("stats", ["--json"], root), root)


def h_session_remember(a, root):
    text = _require(a, "text")
    extra = ["--session", "mcp-bridge", "--kind", "note", "--text", text]
    return _run(_memory_argv("record", extra, root), root)


# ------------------------------------------------------------- tool registry

def _schema(properties, required=None):
    return {"type": "object", "properties": properties,
            "required": required or [], "additionalProperties": False}


ROOT_PROP = {"type": "string", "description":
             "Repo root to operate on. Defaults to the directory this "
             "server was started against (--root at launch)."}
LIMIT_PROP = {"type": "integer", "description":
              "Max rows to return (tool-specific default applies if omitted)."}

TOOLS = [
    {"name": "codebase_verify",
     "description": "Check whether the local codebase-memory index is "
                     "fresh, stale, or missing. Read-only. Call this "
                     "first each session, before anything else here.",
     "inputSchema": _schema({"root": ROOT_PROP}),
     "handler": h_codebase_verify},
    {"name": "codebase_build",
     "description": "(Re)build the local codebase-memory index. Writes "
                     "only .agent/memory/graph/ and CODEBASE_MAP.md -- the "
                     "kit's own generated cache, nothing else. Run this "
                     "when codebase_verify reports STALE or missing.",
     "inputSchema": _schema({"root": ROOT_PROP}),
     "handler": h_codebase_build},
    {"name": "codebase_arch",
     "description": "One-shot architecture summary: stack, modules by "
                     "size, unparsed files. Cheaper than reading "
                     "CODEBASE_MAP.md when you only need the shape.",
     "inputSchema": _schema({"root": ROOT_PROP, "limit": LIMIT_PROP}),
     "handler": h_codebase_arch},
    {"name": "codebase_def",
     "description": "Find where a symbol (function, class, ...) is "
                     "defined, by exact or fuzzy name.",
     "inputSchema": _schema({
         "name": {"type": "string", "description": "Symbol name"},
         "fuzzy": {"type": "boolean", "description":
                   "Substring match instead of exact (default false)"},
         "root": ROOT_PROP, "limit": LIMIT_PROP}, required=["name"]),
     "handler": h_codebase_def},
    {"name": "codebase_callers",
     "description": "List files that call a symbol by name. "
                     "Unresolved-by-design for ambiguous call sites -- "
                     "a strong lead, not an exhaustive list.",
     "inputSchema": _schema({
         "name": {"type": "string", "description": "Symbol name"},
         "fuzzy": {"type": "boolean"},
         "root": ROOT_PROP, "limit": LIMIT_PROP}, required=["name"]),
     "handler": h_codebase_callers},
    {"name": "codebase_callees",
     "description": "List symbols a given file calls into.",
     "inputSchema": _schema({
         "path": {"type": "string", "description":
                  "File path, relative to repo root"},
         "root": ROOT_PROP}, required=["path"]),
     "handler": h_codebase_callees},
    {"name": "codebase_search",
     "description": "Regex search over indexed symbol names, optionally "
                     "filtered by kind (function/class/...) and module "
                     "prefix.",
     "inputSchema": _schema({
         "pattern": {"type": "string", "description":
                     "Case-insensitive regex"},
         "kind": {"type": "string", "description":
                  "Symbol kind filter, e.g. function, class"},
         "module": {"type": "string", "description":
                    "Module path prefix filter"},
         "root": ROOT_PROP, "limit": LIMIT_PROP}, required=["pattern"]),
     "handler": h_codebase_search},
    {"name": "codebase_find",
     "description": "Find symbols by plain words rather than an exact name "
                     "or regex -- 'user auth token refresh' reaches "
                     "refreshUserAuthToken. Use this when you do not already "
                     "know what the symbol is called; use codebase_search "
                     "when you do and want a regex.",
     "inputSchema": _schema({
         "query": {"type": "string", "description":
                   "Plain words describing what you are looking for"},
         "kind": {"type": "string", "description":
                  "Symbol kind filter, e.g. function, class"},
         "root": ROOT_PROP, "limit": LIMIT_PROP}, required=["query"]),
     "handler": h_codebase_find},
    {"name": "codebase_file",
     "description": "Summarize one indexed file: language, module, LOC, "
                     "its symbols, imports, and exposed routes.",
     "inputSchema": _schema({
         "path": {"type": "string"},
         "root": ROOT_PROP, "limit": LIMIT_PROP}, required=["path"]),
     "handler": h_codebase_file},
    {"name": "codebase_importers",
     "description": "List files that import a given module/target by name.",
     "inputSchema": _schema({
         "target": {"type": "string"},
         "root": ROOT_PROP, "limit": LIMIT_PROP}, required=["target"]),
     "handler": h_codebase_importers},
    {"name": "codebase_routes",
     "description": "List indexed HTTP routes, optionally filtered by a "
                     "substring of the route path.",
     "inputSchema": _schema({
         "pattern": {"type": "string", "description":
                     "Substring filter, e.g. /orders"},
         "root": ROOT_PROP, "limit": LIMIT_PROP}),
     "handler": h_codebase_routes},
    {"name": "codebase_impact",
     "description": "Blast radius of changing one file: direct callers, "
                     "importers, and covering test files.",
     "inputSchema": _schema({
         "path": {"type": "string"},
         "root": ROOT_PROP, "limit": LIMIT_PROP}, required=["path"]),
     "handler": h_codebase_impact},
    {"name": "codebase_changed",
     "description": "List files changed in the working tree (or against "
                     "a given git ref) that the index knows about.",
     "inputSchema": _schema({
         "base": {"type": "string", "description":
                  "git ref to diff against (default: HEAD)"},
         "root": ROOT_PROP}),
     "handler": h_codebase_changed},
    {"name": "codebase_coverage",
     "description": "For a list of file paths, report whether each is "
                     "indexed, present-but-unparsed, or absent.",
     "inputSchema": _schema({
         "paths": {"type": "array", "items": {"type": "string"},
                   "description": "File paths to check"},
         "root": ROOT_PROP}, required=["paths"]),
     "handler": h_codebase_coverage},
    {"name": "codebase_orphans",
     "description": "List functions/methods with no recorded caller in "
                     "the index -- a lead list for dead code, not a "
                     "delete list.",
     "inputSchema": _schema({"root": ROOT_PROP, "limit": LIMIT_PROP}),
     "handler": h_codebase_orphans},
    {"name": "codebase_stats",
     "description": "Raw index manifest: generation, file/symbol counts, "
                     "build time, language breakdown.",
     "inputSchema": _schema({"root": ROOT_PROP}),
     "handler": h_codebase_stats},
    {"name": "codebase_drift",
     "description": "Compare codebase shape across builds -- files, "
                     "symbols, LOC growth, modules that moved most. "
                     "Needs at least two builds logged to say anything.",
     "inputSchema": _schema({
         "last": {"type": "integer", "description":
                  "Only compare within the last N logged builds"},
         "root": ROOT_PROP, "limit": LIMIT_PROP}),
     "handler": h_codebase_drift},
    {"name": "session_recall",
     "description": "Recall entries from earlier, separate sessions in "
                     "this repo that are lexically similar to a query. A "
                     "lead ('something was said'), not a verified fact -- "
                     "cross-check before acting on it.",
     "inputSchema": _schema({
         "query": {"type": "string"},
         "limit": LIMIT_PROP, "root": ROOT_PROP}, required=["query"]),
     "handler": h_session_recall},
    {"name": "session_recent",
     "description": "Most recent entry from each other session recorded "
                     "in this repo, newest first.",
     "inputSchema": _schema({"limit": LIMIT_PROP, "root": ROOT_PROP}),
     "handler": h_session_recent},
    {"name": "session_stats",
     "description": "Counts of recorded session-memory entries: total, "
                     "by kind, sessions, oldest/newest.",
     "inputSchema": _schema({"root": ROOT_PROP}),
     "handler": h_session_stats},
    {"name": "session_remember",
     "description": "Record one note to session-memory so a future "
                     "session in this repo can recall it. The only write "
                     "this tool performs beyond the local index cache.",
     "inputSchema": _schema({
         "text": {"type": "string"},
         "root": ROOT_PROP}, required=["text"]),
     "handler": h_session_remember},
]

TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}
TOOL_DEFS = [{"name": t["name"], "description": t["description"],
              "inputSchema": t["inputSchema"]} for t in TOOLS]


# ----------------------------------------------------------------- dispatch -

def _resolve_root(explicit):
    if explicit:
        return os.path.abspath(os.path.expanduser(str(explicit)))
    return DEFAULT_ROOT


def call_tool(name, arguments):
    spec = TOOLS_BY_NAME[name]
    root = _resolve_root(arguments.get("root"))
    try:
        ok, text = spec["handler"](arguments, root)
    except ToolInputError as exc:
        return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    except Exception as exc:
        return {"content": [{"type": "text", "text":
                              "internal error: %s" % exc}], "isError": True}
    return {"content": [{"type": "text", "text": text}], "isError": not ok}


def do_initialize(params):
    requested = params.get("protocolVersion")
    version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": SERVER_NAME, "title": "agent-memory-kit",
                        "version": SERVER_VERSION},
        "instructions": (
            "Read-only local codebase index and cross-session recall for "
            "this repo, via agent-memory-kit. Call codebase_verify first "
            "each session; if it reports STALE or missing, call "
            "codebase_build once, then use the other codebase_* tools "
            "instead of grepping or reading whole files blind. "
            "session_recall/session_recent surface what earlier sessions "
            "in this repo established -- treat a hit as a lead, not a "
            "verified fact, the same way you would treat a NOTES.md entry "
            "tagged [stated] rather than [verified]."
        ),
    }


def _ok(id_, result):
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _err(id_, code, message):
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def handle_request(msg):
    method = msg.get("method")
    id_ = msg.get("id")
    try:
        if method == "initialize":
            return _ok(id_, do_initialize(msg.get("params") or {}))
        if method == "tools/list":
            return _ok(id_, {"tools": TOOL_DEFS})
        if method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            if name not in TOOLS_BY_NAME:
                return _err(id_, -32602, "Unknown tool: %s" % name)
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                return _err(id_, -32602, "'arguments' must be an object")
            return _ok(id_, call_tool(name, arguments))
        if method == "ping":
            return _ok(id_, {})
        return _err(id_, -32601, "Method not found: %s" % method)
    except Exception as exc:
        return _err(id_, -32603, "Internal error: %s" % exc)


# --------------------------------------------------------------------- main -

def _parse_root_flag(argv):
    if "--root" in argv:
        i = argv.index("--root")
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def main():
    global DEFAULT_ROOT
    root_arg = _parse_root_flag(sys.argv[1:])
    DEFAULT_ROOT = (os.path.abspath(os.path.expanduser(root_arg)) if root_arg
                     else mem.find_repo_root(os.getcwd()))

    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass  # best-effort; stdlib default is already utf-8 on most platforms

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue  # not a valid MCP message -- and we can't reply without an id
        if not isinstance(msg, dict) or "id" not in msg:
            continue  # notification, or malformed: no response, ever
        resp = handle_request(msg)
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
