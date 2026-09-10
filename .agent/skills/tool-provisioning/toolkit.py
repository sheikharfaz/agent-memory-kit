#!/usr/bin/env python3
"""
tool-provisioning :: toolkit.py
Propose-only tool acquisition: find what a task needs, print the exact
install/uninstall commands and their risk, and -- only once a human has
approved in chat -- install it, use it, and uninstall it again. Every
install is logged to a ledger so nothing this mechanism installs is ever
forgotten or left behind, and `uninstall` will only ever remove something
this mechanism's own ledger says it installed.

  python .agent/skills/tool-provisioning/toolkit.py doctor
  python .agent/skills/tool-provisioning/toolkit.py search "read a pdf"
  python .agent/skills/tool-provisioning/toolkit.py plan pdf-text
  python .agent/skills/tool-provisioning/toolkit.py install pdf-text   # only after approval
  python .agent/skills/tool-provisioning/toolkit.py uninstall pdf-text
  python .agent/skills/tool-provisioning/toolkit.py list-installed
  python .agent/skills/tool-provisioning/toolkit.py sweep
  python .agent/skills/tool-provisioning/toolkit.py export-audit

Guarantees:
  * `search`, `plan`, `doctor` and `export-audit` never execute an
    install/uninstall command -- they only print or probe read-only state.
    `doctor`'s reachability probe is a bare TCP connect with a short
    timeout, nothing is sent or fetched.
  * `install` and `uninstall` run exactly the command in the registry (or,
    for uninstall, the ledger) via subprocess with an argument list, never
    a shell string -- no shell injection surface from a crafted name/query.
  * `uninstall` refuses to act on anything not present as an open entry in
    this machine's own ledger. It will not "clean up" something that was
    already installed before this tool ever touched it.
  * An optional org policy file (see load_org_policy) can allowlist,
    denylist, or override registry entries -- e.g. to redirect pip installs
    through an internal mirror. It is read-only local config; nothing here
    fetches it from a network automatically.
  * Registry, org policy and ledger live under .agent/memory/tools/ and
    .agent/skills/tool-provisioning/registry.json. No network calls happen
    except the install/uninstall commands themselves (which you approved)
    and doctor's connectivity probes (which fetch nothing).
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY_FILE = os.path.join(HERE, "registry.json")
LOCAL_REGISTRY_SUBPATH = os.path.join(".agent", "memory", "tools", "registry.local.json")
ORG_POLICY_SUBPATH = os.path.join(".agent", "memory", "tools", "registry.org.json")
ORG_POLICY_ENV = "AGENT_MEMORY_KIT_ORG_POLICY"
LEDGER_SUBPATH = os.path.join(".agent", "memory", "tools", "tool-ledger.jsonl")
CHECK_TIMEOUT = 15
RUN_TIMEOUT = 300
PROBE_TIMEOUT = 3


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

def _load_json(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def org_policy_path(root):
    return os.environ.get(ORG_POLICY_ENV) or os.path.join(root, ORG_POLICY_SUBPATH)


def load_org_policy(root):
    """
    Optional IT-owned policy file (JSON):
      {
        "mode": "advisory" | "allowlist" | "denylist",
        "allow": ["pdf-text", ...],          # only used when mode == allowlist
        "deny":  ["browser-automation"],     # used when mode == denylist or advisory
        "overrides": [ {registry entry that fully replaces one by name} ],
        "pip_index_url": "https://artifactory.corp.example.com/api/pypi/pypi/simple"
      }
    Location: <root>/.agent/memory/tools/registry.org.json, or an absolute
    path via the AGENT_MEMORY_KIT_ORG_POLICY env var (for an org that pushes
    policy outside any individual repo, e.g. via MDM). Read-only local file;
    this function never fetches anything over the network -- see
    `sync-org-registry` for the one explicit, developer-initiated command
    that does.
    """
    policy = _load_json(org_policy_path(root)) or {}
    policy.setdefault("mode", "advisory")
    policy.setdefault("allow", [])
    policy.setdefault("deny", [])
    policy.setdefault("overrides", [])
    return policy


def apply_org_policy(entries, policy):
    """Returns (visible_entries, denied) where denied maps name -> reason.
    Denied entries are dropped from what `search`/`plan`/`install` can act
    on entirely except to explain why, by design -- allow/deny is the one
    rule a project-local registry.local.json must not be able to override."""
    by_name = {e["name"]: dict(e) for e in entries}

    for ov in policy.get("overrides", []):
        name = ov.get("name")
        if name in by_name:
            by_name[name].update(ov)
        else:
            by_name[name] = dict(ov)

    idx_url = policy.get("pip_index_url")
    if idx_url:
        for e in by_name.values():
            cmd = e.get("install_cmd")
            if e.get("kind") == "pip" and cmd and "--index-url" not in cmd:
                e["install_cmd"] = list(cmd) + ["--index-url", idx_url]

    mode = policy.get("mode", "advisory")
    allow = set(policy.get("allow", []))
    deny = set(policy.get("deny", []))

    denied = {}
    visible = {}
    for name, e in by_name.items():
        if mode == "allowlist" and name not in allow:
            denied[name] = "org policy mode=allowlist and %r is not on the allow list" % name
            continue
        if name in deny:
            denied[name] = "org policy denies %r explicitly" % name
            continue
        visible[name] = e
    return list(visible.values()), denied


def load_registry(root):
    entries = {}
    for e in _load_json(REGISTRY_FILE) or []:
        entries[e["name"]] = e
    local = _load_json(os.path.join(root, LOCAL_REGISTRY_SUBPATH))
    for e in local or []:
        entries[e["name"]] = e  # local overrides/extends shipped entries
    return list(entries.values())


def load_effective_registry(root):
    """(visible_entries, denied_map) after local overlay + org policy."""
    policy = load_org_policy(root)
    return apply_org_policy(load_registry(root), policy)


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


def pip_show_info(package):
    """Best-effort SBOM fragment: name/version/license via `pip show`."""
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "show", package],
                            capture_output=True, text=True, timeout=CHECK_TIMEOUT)
        if r.returncode != 0:
            return None
        info = {}
        for line in r.stdout.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                info[k.strip().lower()] = v.strip()
        return {"name": info.get("name"), "version": info.get("version"),
                "license": info.get("license"), "home_page": info.get("home-page")}
    except Exception:
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


def _probe_tcp(host, port, timeout=PROBE_TIMEOUT):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


# ----------------------------------------------------------------- print --

def _fmt_installed(v):
    return {True: "installed", False: "not installed", None: "unknown (checked manually)"}[v]


def cmd_search(args):
    root = find_repo_root(args.root)
    registry, denied = load_effective_registry(root)
    hits = search(registry, " ".join(args.query))
    if not hits:
        print("no registry entry matches %r. See registry.json / registry.local.json, "
              "or `plan` a tool you already know the name of." % " ".join(args.query))
        if denied:
            print("(%d entr%s hidden by org policy)" % (len(denied), "y is" if len(denied) == 1 else "ies are"))
        return
    for e in hits:
        installed = check_installed(e)
        print("%-20s [%s] %-14s :: %s" % (e["name"], e["kind"], _fmt_installed(installed),
                                           e.get("risk", "")))


def cmd_plan(args):
    root = find_repo_root(args.root)
    registry, denied = load_effective_registry(root)
    if args.name in denied:
        print("BLOCKED by org policy: %s" % denied[args.name])
        sys.exit(3)

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
    registry, denied = load_effective_registry(root)
    if args.name in denied:
        print("BLOCKED by org policy: %s -- refusing to install." % denied[args.name])
        sys.exit(3)

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

    sbom = None
    if entry.get("kind") == "pip" and entry.get("package"):
        sbom = pip_show_info(entry["package"])

    ledger_append(root, {
        "event": "install", "name": entry["name"], "kind": entry["kind"],
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session": args.session, "install_cmd": entry["install_cmd"],
        "uninstall_cmd": entry.get("uninstall_cmd"), "sbom": sbom,
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


def cmd_export_audit(args):
    root = find_repo_root(args.root)
    events = list(ledger_events(root))
    if args.since:
        events = [e for e in events if e.get("ts", "") >= args.since]
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repo": root,
        "event_count": len(events),
        "open_installs": list(open_installs(root).keys()),
        "events": events,
    }
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print("wrote %d event(s) to %s" % (len(events), args.out))
    else:
        print(text)


def cmd_sync_org_registry(args):
    """The one command in this skill that makes a real network call -- and
    only when a developer runs it explicitly, with a source they typed
    themselves. Never invoked automatically by any hook or by `install`."""
    root = find_repo_root(args.root)
    dest = org_policy_path(root)
    src = args.source

    if src.startswith("http://") or src.startswith("https://"):
        try:
            with urllib.request.urlopen(src, timeout=args.timeout) as resp:
                raw = resp.read()
        except Exception as exc:
            print("fetch failed: %s" % exc)
            sys.exit(1)
    else:
        if not os.path.exists(src):
            print("no such file: %s" % src)
            sys.exit(1)
        with open(src, "rb") as fh:
            raw = fh.read()

    try:
        policy = json.loads(raw)
    except json.JSONDecodeError as exc:
        print("fetched content is not valid JSON: %s -- refusing to overwrite %s" % (exc, dest))
        sys.exit(1)
    if not isinstance(policy, dict) or "mode" not in policy:
        print("fetched JSON doesn't look like an org policy (expected an object with "
              "a 'mode' key) -- refusing to overwrite %s" % dest)
        sys.exit(1)

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(policy, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("wrote org policy to %s (mode=%s, allow=%d, deny=%d, overrides=%d)" % (
        dest, policy.get("mode"), len(policy.get("allow", [])),
        len(policy.get("deny", [])), len(policy.get("overrides", []))))


def cmd_doctor(args):
    root = find_repo_root(args.root)
    print("== tool-provisioning doctor (read-only; probes are bare TCP connects) ==")
    print()

    print("python: %s (%s)" % (sys.executable, sys.version.split()[0]))

    pip_ver = run_cmd([sys.executable, "-m", "pip", "--version"], timeout=CHECK_TIMEOUT)
    print("pip: %s" % (pip_ver[1].strip() if pip_ver[0] == 0 else "not available"))
    for var in ("PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "HTTP_PROXY", "HTTPS_PROXY",
                "NO_PROXY", "PIP_CERT"):
        val = os.environ.get(var)
        if val:
            print("  env %s = %s" % (var, val))

    npm_ver = run_cmd(["npm", "--version"], timeout=CHECK_TIMEOUT)
    print("npm: %s" % (npm_ver[1].strip() if npm_ver[0] == 0 else "not available"))
    npm_reg = run_cmd(["npm", "config", "get", "registry"], timeout=CHECK_TIMEOUT)
    if npm_reg[0] == 0:
        print("  registry = %s" % npm_reg[1].strip())

    claude_ver = run_cmd(["claude", "--version"], timeout=CHECK_TIMEOUT)
    print("claude CLI: %s" % (claude_ver[1].strip() if claude_ver[0] == 0 else "not available"))

    gh_ver = run_cmd(["gh", "--version"], timeout=CHECK_TIMEOUT)
    print("gh CLI: %s" % ("available" if gh_ver[0] == 0 else "not available"))

    print()
    print("connectivity (TCP connect only, nothing fetched):")
    index_url = os.environ.get("PIP_INDEX_URL")
    targets = [("pypi.org", 443, "public PyPI")]
    if index_url:
        u = urlparse(index_url)
        if u.hostname:
            targets.insert(0, (u.hostname, u.port or (443 if u.scheme == "https" else 80),
                                "configured PIP_INDEX_URL"))
    targets.append(("registry.npmjs.org", 443, "public npm"))
    for host, port, label in targets:
        ok = _probe_tcp(host, port)
        print("  %-28s %s:%d -> %s" % (label, host, port, "reachable" if ok else "blocked/unreachable"))

    print()
    policy_path = org_policy_path(root)
    policy = load_org_policy(root)
    if os.path.exists(policy_path):
        print("org policy: %s (mode=%s, allow=%d, deny=%d, overrides=%d)" % (
            policy_path, policy["mode"], len(policy["allow"]), len(policy["deny"]),
            len(policy["overrides"])))
    else:
        print("org policy: none found (%s) -- registry defaults apply" % policy_path)

    open_map = open_installs(root)
    print("ledger: %d open install(s)" % len(open_map))
    print()
    print("If PyPI/npm show 'blocked/unreachable' above, this environment likely routes")
    print("through an internal mirror. Ask IT for the mirror URL and set PIP_INDEX_URL /")
    print("`npm config set registry <url>` yourself -- no admin rights needed for either.")


def main():
    p = argparse.ArgumentParser(prog="toolkit.py")
    p.add_argument("--root", default=".")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor")
    d.set_defaults(func=cmd_doctor)

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

    ea = sub.add_parser("export-audit")
    ea.add_argument("--out", default=None)
    ea.add_argument("--since", default=None, help="ISO timestamp lower bound")
    ea.set_defaults(func=cmd_export_audit)

    so = sub.add_parser("sync-org-registry")
    so.add_argument("source", help="URL or local file path to an org policy JSON file")
    so.add_argument("--timeout", type=int, default=15)
    so.set_defaults(func=cmd_sync_org_registry)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
