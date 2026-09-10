#!/usr/bin/env python3
"""
tool-provisioning :: toolkit.py
Propose-only tool acquisition: find what a task needs, print the exact
install/uninstall commands and their risk, and -- only once a human has
approved in chat -- install it, use it, and uninstall it again. Every
install is logged to a ledger so nothing this mechanism installs is ever
forgotten or left behind, and `uninstall` will only ever remove something
this mechanism's own ledger says it installed.

  python .agent/skills/tool-provisioning/toolkit.py search "read a pdf"
  python .agent/skills/tool-provisioning/toolkit.py plan pdf-text
  python .agent/skills/tool-provisioning/toolkit.py install pdf-text   # only after approval
  python .agent/skills/tool-provisioning/toolkit.py uninstall pdf-text
  python .agent/skills/tool-provisioning/toolkit.py list-installed
  python .agent/skills/tool-provisioning/toolkit.py sweep

Guarantees:
  * `search` and `plan` never execute an install/uninstall command -- they
    only print what would run.
  * `install` and `uninstall` run exactly the command in the registry (or,
    for uninstall, the ledger) via subprocess with an argument list, never
    a shell string -- no shell injection surface from a crafted name/query.
  * `uninstall` refuses to act on anything not present as an open entry in
    this machine's own ledger. It will not "clean up" something that was
    already installed before this tool ever touched it.
  * Registry and ledger live under .agent/memory/tools/ and
    .agent/skills/tool-provisioning/registry.json. No network calls happen
    except the install/uninstall commands themselves, which you approved.
"""

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY_FILE = os.path.join(HERE, "registry.json")
LOCAL_REGISTRY_SUBPATH = os.path.join(".agent", "memory", "tools", "registry.local.json")
LEDGER_SUBPATH = os.path.join(".agent", "memory", "tools", "tool-ledger.jsonl")
CHECK_TIMEOUT = 15
RUN_TIMEOUT = 300


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


# ------------------------------------------------------------- registry ---

def load_registry(root):
    entries = {}
    if os.path.exists(REGISTRY_FILE):
        with open(REGISTRY_FILE, encoding="utf-8") as fh:
            for e in json.load(fh):
                entries[e["name"]] = e
    local = os.path.join(root, LOCAL_REGISTRY_SUBPATH)
    if os.path.exists(local):
        with open(local, encoding="utf-8") as fh:
            for e in json.load(fh):
                entries[e["name"]] = e  # local overrides/extends shipped entries
    return list(entries.values())


def find_entry(registry, name):
    for e in registry:
        if e["name"] == name:
            return e
    hits = [e for e in registry if name.lower() in e["name"].lower()]
    return hits[0] if len(hits) == 1 else None


def search(registry, query):
    q = query.lower().split()
    scored = []
    for e in registry:
        hay = (e["name"] + " " + " ".join(e.get("match", []))).lower()
        score = sum(hay.count(term) for term in q)
        if score > 0:
            scored.append((score, e))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [e for _, e in scored]


# ----------------------------------------------------------------- check --

def check_installed(entry):
    """True/False, or None if this kind of entry can't be checked automatically."""
    check = entry.get("check") or {}
    ctype = check.get("type")
    try:
        if ctype == "python_import":
            r = subprocess.run([sys.executable, "-c", "import %s" % check["module"]],
                                capture_output=True, timeout=CHECK_TIMEOUT)
            return r.returncode == 0
        if ctype == "subprocess":
            r = subprocess.run(check["cmd"], capture_output=True, timeout=CHECK_TIMEOUT)
            return r.returncode == 0
        if ctype == "mcp":
            r = subprocess.run(["claude", "mcp", "list"], capture_output=True,
                                timeout=CHECK_TIMEOUT, text=True)
            if r.returncode != 0:
                return None
            return check["name"].lower() in r.stdout.lower()
    except Exception:
        return None
    return None


# ----------------------------------------------------------------- ledger -

def ledger_path(root):
    return os.path.join(root, LEDGER_SUBPATH)


def ledger_append(root, event):
    path = ledger_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")


def ledger_events(root):
    path = ledger_path(root)
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


def open_installs(root, name=None):
    """Names currently installed by this mechanism with no later uninstall,
    each mapped to the install event that put it there."""
    open_map = {}
    for ev in ledger_events(root):
        n = ev.get("name")
        if name and n != name:
            continue
        if ev.get("event") == "install":
            open_map[n] = ev
        elif ev.get("event") == "uninstall":
            open_map.pop(n, None)
    return open_map


# -------------------------------------------------------------------- run -

def run_cmd(cmd, timeout=RUN_TIMEOUT):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timed out after %ds" % timeout
    except Exception as exc:
        return 1, "", str(exc)


# ----------------------------------------------------------------- print --

def _fmt_installed(v):
    return {True: "installed", False: "not installed", None: "unknown (checked manually)"}[v]


def cmd_search(args):
    root = find_repo_root(args.root)
    registry = load_registry(root)
    hits = search(registry, " ".join(args.query))
    if not hits:
        print("no registry entry matches %r. See registry.json / registry.local.json, "
              "or `plan` a tool you already know the name of." % " ".join(args.query))
        return
    for e in hits:
        installed = check_installed(e)
        print("%-20s [%s] %-14s :: %s" % (e["name"], e["kind"], _fmt_installed(installed),
                                           e.get("risk", "")))


def cmd_plan(args):
    root = find_repo_root(args.root)
    registry = load_registry(root)
    entry = find_entry(registry, args.name)
    if not entry:
        print("no registry entry named %r. Run `search` first." % args.name)
        sys.exit(1)

    installed = check_installed(entry)
    print("tool: %s (%s)" % (entry["name"], entry["kind"]))
    print("risk: %s" % entry.get("risk", "(none noted)"))

    if installed is True:
        print("status: already available -- nothing to install, use it directly.")
        return
    if not entry.get("install_cmd"):
        print("status: no automatic install for this one (manual/OS-specific).")
        print("        hand this to the developer instead of trying to script it.")
        sys.exit(2)

    print("status: not detected (or unknown -- see above).")
    print()
    print("NOT YET RUN. Get explicit developer approval in this chat, then:")
    print("  install:   %s" % " ".join(entry["install_cmd"]))
    print("  uninstall: %s" % " ".join(entry["uninstall_cmd"] or ["(none recorded)"]))
    print()
    print("  python %s install %s" % (os.path.relpath(__file__), entry["name"]))


def cmd_install(args):
    root = find_repo_root(args.root)
    registry = load_registry(root)
    entry = find_entry(registry, args.name)
    if not entry:
        print("no registry entry named %r." % args.name)
        sys.exit(1)
    if not entry.get("install_cmd"):
        print("this entry has no automatic install command. See its risk note.")
        sys.exit(2)

    if check_installed(entry) is True:
        print("%s already available -- nothing installed, nothing to ledger." % entry["name"])
        return

    print("running: %s" % " ".join(entry["install_cmd"]))
    code, out, err = run_cmd(entry["install_cmd"])
    sys.stdout.write(out)
    sys.stderr.write(err)
    if code != 0:
        print("install FAILED (exit %d) -- nothing recorded in the ledger." % code)
        sys.exit(code)

    verified = check_installed(entry)
    if verified is False:
        print("install command exited 0 but the check still reports not-installed. "
              "Proceed with caution.")

    ledger_append(root, {
        "event": "install", "name": entry["name"], "kind": entry["kind"],
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session": args.session, "install_cmd": entry["install_cmd"],
        "uninstall_cmd": entry.get("uninstall_cmd"),
    })
    print("installed and logged to the ledger. Remember to `uninstall %s` when done." % entry["name"])


def cmd_uninstall(args):
    root = find_repo_root(args.root)
    open_map = open_installs(root, args.name)
    ev = open_map.get(args.name)
    if not ev:
        print("nothing in the ledger says this mechanism installed %r -- refusing to "
              "touch it. (It may already be uninstalled, or it was never installed "
              "through this tool.)" % args.name)
        sys.exit(1)

    uninstall_cmd = ev.get("uninstall_cmd")
    if not uninstall_cmd:
        print("ledger has no uninstall command recorded for %r -- nothing to run." % args.name)
        sys.exit(2)

    print("running: %s" % " ".join(uninstall_cmd))
    code, out, err = run_cmd(uninstall_cmd)
    sys.stdout.write(out)
    sys.stderr.write(err)
    if code != 0:
        print("uninstall FAILED (exit %d) -- still marked installed in the ledger." % code)
        sys.exit(code)

    ledger_append(root, {
        "event": "uninstall", "name": args.name,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session": args.session,
    })
    print("uninstalled and logged.")


def cmd_list_installed(args):
    root = find_repo_root(args.root)
    open_map = open_installs(root)
    if not open_map:
        print("(nothing currently open in the ledger)")
        return
    for name, ev in open_map.items():
        print("%-20s installed %s (session %s)" % (name, ev.get("ts"), ev.get("session")))


def cmd_sweep(args):
    root = find_repo_root(args.root)
    open_map = open_installs(root)
    if args.session:
        open_map = {n: e for n, e in open_map.items() if e.get("session") == args.session}
    if not open_map:
        print("(nothing to sweep)")
        return
    for name in list(open_map.keys()):
        a = argparse.Namespace(root=args.root, name=name, session=args.session)
        cmd_uninstall(a)


def main():
    p = argparse.ArgumentParser(prog="toolkit.py")
    p.add_argument("--root", default=".")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search")
    s.add_argument("query", nargs="+")
    s.set_defaults(func=cmd_search)

    pl = sub.add_parser("plan")
    pl.add_argument("name")
    pl.set_defaults(func=cmd_plan)

    i = sub.add_parser("install")
    i.add_argument("name")
    i.add_argument("--session", default="cli")
    i.set_defaults(func=cmd_install)

    u = sub.add_parser("uninstall")
    u.add_argument("name")
    u.add_argument("--session", default="cli")
    u.set_defaults(func=cmd_uninstall)

    li = sub.add_parser("list-installed")
    li.set_defaults(func=cmd_list_installed)

    sw = sub.add_parser("sweep")
    sw.add_argument("--session", default=None)
    sw.set_defaults(func=cmd_sweep)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
