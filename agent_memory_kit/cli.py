"""
amk -- the one command for agent-memory-kit.

  amk init [dir] [--hooks] [--mcp] [--force] [--no-build] [--no-gitignore]
  amk doctor [dir]
  amk find <plain words> [--limit N]
  amk query <verb> [args...]
  amk mcp [--root DIR]
  amk version

Install without cloning, and without piping anything into a shell
(PyPI name `agent-memory-kit-cli`; `agent-memory-kit` there is unrelated):

  uvx agent-memory-kit-cli init
  pipx install agent-memory-kit-cli

Python 3.8+ standard library only at runtime. `init` copies the same file
set the clone-based installers do -- the list lives in `install.py` and is
imported from there, never duplicated here.
"""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(PKG_DIR)
QUERY_REL = os.path.join(".agent", "skills", "codebase-memory", "query.py")
INDEX_REL = os.path.join(".agent", "skills", "codebase-memory", "index.py")
SERVER_REL = os.path.join(".agent", "skills", "mcp-bridge", "server.py")
GITIGNORE_LINES = (".agent/memory/session/", ".agent/work/")


def payload_dir():
    """Kit files bundled into the wheel, or the repo root when this runs
    straight from a checkout (`python -m agent_memory_kit`)."""
    for candidate in (os.path.join(PKG_DIR, "payload"), REPO_ROOT):
        if os.path.isfile(os.path.join(candidate, "install.py")):
            return candidate
    sys.exit("amk: kit files not found next to the package -- reinstall it")


def load_installer():
    spec = importlib.util.spec_from_file_location(
        "amk_install", os.path.join(payload_dir(), "install.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def version():
    try:
        with open(os.path.join(payload_dir(), "VERSION"), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return "unknown"


def find_install_root(start):
    p = os.path.abspath(start)
    while True:
        if os.path.isfile(os.path.join(p, QUERY_REL)):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


def _run(argv, cwd=None):
    sys.stdout.flush()
    return subprocess.run(argv, cwd=cwd).returncode


def command_prefix():
    """How the user should invoke the next command. Under `uvx`, the package
    lives in a throwaway environment inside uv's cache and `amk` is gone
    the moment this process exits, so telling the user to run `amk doctor`
    would send them straight into "command not found"."""
    exe = sys.executable.replace("\\", "/")
    if os.environ.get("UV") and "/archive-v" in exe:
        return "uvx agent-memory-kit-cli"
    return "amk"


def _ensure_gitignore(target):
    path = os.path.join(target, ".gitignore")
    existing = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            existing = fh.read()
    have = {line.strip() for line in existing.splitlines()}
    missing = [line for line in GITIGNORE_LINES if line not in have]
    if not missing:
        return []
    with open(path, "a", encoding="utf-8") as fh:
        if existing and not existing.endswith("\n"):
            fh.write("\n")
        fh.write("# agent-memory-kit: private session text and local task notes\n")
        for line in missing:
            fh.write(line + "\n")
    return missing


# ------------------------------------------------------------------ commands

def cmd_init(args):
    target = os.path.abspath(args.dir)
    installer = load_installer()
    try:
        installer.install(payload_dir(), target, force=args.force,
                          wire_hooks=args.hooks, wire_mcp=args.mcp)
    except ValueError as exc:
        print("amk init: %s" % exc, file=sys.stderr)
        return 2

    if not args.no_gitignore:
        added = _ensure_gitignore(target)
        if added:
            print("\nAdded to .gitignore: %s" % ", ".join(added))

    if not args.no_build:
        print("\nBuilding the codebase index ...")
        rc = _run([sys.executable, os.path.join(target, INDEX_REL), "build",
                   "--root", target])
        sys.stderr.flush()
        if rc != 0:
            print("amk init: index build failed (exit %d)" % rc, file=sys.stderr)
            return rc

    cmd = command_prefix()
    steps = [("doctor", "check the install is healthy"),
             ("find <plain words>", "find a symbol without knowing its name")]
    if not args.hooks:
        steps.append(("init --hooks", "cross-session recall in Claude Code"))
    if not args.mcp:
        steps.append(("init --mcp", "live tools in Cursor / Claude Desktop / any MCP host"))
    width = max(len("%s %s" % (cmd, verb)) for verb, _ in steps) + 2
    print("\nReady. Next:")
    for verb, why in steps:
        print("  %-*s# %s" % (width, "%s %s" % (cmd, verb), why))
    if cmd != "amk":
        print("(`pipx install agent-memory-kit-cli` gives you a permanent `amk` instead.)")
    print("Your agent reads AGENTS.md from here on.")
    return 0


def _check(results, status, label, detail=""):
    results.append((status, label, detail))


def cmd_doctor(args):
    target = os.path.abspath(args.dir)
    installer = load_installer()
    results = []

    v = sys.version_info
    _check(results, "PASS" if v >= (3, 8) else "FAIL",
           "python %d.%d.%d" % (v[0], v[1], v[2]), "" if v >= (3, 8) else "3.8+ required")

    git = shutil.which("git")
    _check(results, "PASS" if git else "WARN", "git",
           "found" if git else "not on PATH -- .gitignore and diff features degrade")

    missing = [f for f in installer.FILES
               if not os.path.exists(os.path.join(target, f.replace("/", os.sep)))]
    if missing:
        _check(results, "FAIL", "kit files",
               "%d of %d missing (e.g. %s) -- run `amk init --force`"
               % (len(missing), len(installer.FILES), missing[0]))
    else:
        _check(results, "PASS", "kit files", "all %d present" % len(installer.FILES))

    manifest = os.path.join(target, ".agent", "memory", "graph", "manifest.json")
    if not os.path.isfile(os.path.join(target, INDEX_REL)):
        _check(results, "FAIL", "index", "indexer not installed")
    elif not os.path.exists(manifest):
        _check(results, "FAIL", "index", "not built -- run `amk init` or index.py build")
    else:
        r = subprocess.run([sys.executable, os.path.join(target, INDEX_REL), "verify",
                            "--root", target], capture_output=True, text=True)
        last = (r.stdout.strip().splitlines() or [""])[-1]
        status = {0: "PASS", 2: "WARN"}.get(r.returncode, "FAIL")
        with open(manifest, encoding="utf-8") as fh:
            m = json.load(fh)
        _check(results, status, "index",
               "%s files, %s symbols -- %s" % (m.get("files_total"), m.get("symbols"), last))

    text = _text(os.path.join(target, ".gitignore"))
    covered = any(line.strip().rstrip("/") in (".agent/memory/session", ".agent/memory", ".agent")
                  for line in text.splitlines())
    _check(results, "PASS" if covered else "WARN", "privacy",
           ".agent/memory/session/ is gitignored" if covered
           else ".agent/memory/session/ is NOT gitignored -- raw prompt text could get committed")

    settings = os.path.join(target, ".claude", "settings.json")
    hooks = "session-memory/hooks" in _text(settings)
    _check(results, "PASS" if hooks else "INFO", "claude code hooks",
           "wired" if hooks else "not wired (optional) -- `amk init --hooks`")

    mcp_path = os.path.join(target, ".mcp.json")
    mcp = False
    if os.path.exists(mcp_path):
        try:
            with open(mcp_path, encoding="utf-8") as fh:
                mcp = "agent-memory-kit" in json.load(fh).get("mcpServers", {})
        except ValueError:
            _check(results, "WARN", "mcp", ".mcp.json is not valid JSON")
    _check(results, "PASS" if mcp else "INFO", "mcp server",
           "registered in .mcp.json" if mcp else "not registered (optional) -- `amk init --mcp`")

    stale = []
    for f in installer.FILES:
        a = os.path.join(target, f.replace("/", os.sep))
        b = os.path.join(payload_dir(), f.replace("/", os.sep))
        if os.path.exists(a) and os.path.exists(b) and _read(a) != _read(b):
            stale.append(f)
    _check(results, "INFO" if stale else "PASS", "kit version",
           ("%d file(s) differ from amk %s (local edits, or an older install) -- "
            "`amk init --force` to update" % (len(stale), version())) if stale
           else "matches amk %s" % version())

    print("agent-memory-kit doctor  ·  %s" % target)
    print()
    for status, label, detail in results:
        print("  %-4s  %-20s %s" % (status, label, detail))
    fails = sum(1 for s, _, _ in results if s == "FAIL")
    warns = sum(1 for s, _, _ in results if s == "WARN")
    print()
    print("%d failure(s), %d warning(s)." % (fails, warns))
    return 1 if fails else 0


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def _text(path):
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _passthrough(rel, extra):
    root = find_install_root(os.getcwd())
    script = os.path.join(root or payload_dir(), rel)
    return _run([sys.executable, script] + extra)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "find":
        return _passthrough(QUERY_REL, argv)
    if argv and argv[0] == "query":
        return _passthrough(QUERY_REL, argv[1:])
    if argv and argv[0] == "mcp":
        return _passthrough(SERVER_REL, argv[1:])

    ap = argparse.ArgumentParser(prog="amk", description=__doc__.strip().splitlines()[0])
    sub = ap.add_subparsers(dest="cmd")
    i = sub.add_parser("init", help="install the kit into a repo and build its index")
    i.add_argument("dir", nargs="?", default=".")
    i.add_argument("--hooks", action="store_true", help="wire Claude Code session hooks")
    i.add_argument("--mcp", action="store_true", help="register the MCP server in .mcp.json")
    i.add_argument("--force", action="store_true", help="overwrite existing kit files (upgrade)")
    i.add_argument("--no-build", action="store_true", help="skip building the index")
    i.add_argument("--no-gitignore", action="store_true", help="leave .gitignore untouched")
    d = sub.add_parser("doctor", help="check an install is healthy")
    d.add_argument("dir", nargs="?", default=".")
    sub.add_parser("find", help="find symbols by plain words (passes through to query.py)")
    sub.add_parser("query", help="run any query.py verb")
    sub.add_parser("mcp", help="run the MCP server over stdio")
    sub.add_parser("version", help="print the kit version")
    args = ap.parse_args(argv)

    if args.cmd == "init":
        return cmd_init(args)
    if args.cmd == "doctor":
        return cmd_doctor(args)
    if args.cmd == "version":
        print("agent-memory-kit %s" % version())
        return 0
    ap.print_help()
    return 0


def entry():
    sys.exit(main())


if __name__ == "__main__":
    entry()
