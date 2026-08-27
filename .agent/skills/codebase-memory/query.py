#!/usr/bin/env python3
"""
codebase-memory :: query.py
Read-only queries over the local graph in .agent/memory/graph/.
Replaces dozens of grep/read cycles with one cheap, structured answer.

  python .agent/skills/codebase-memory/query.py arch
  python .agent/skills/codebase-memory/query.py def   ProcessOrder
  python .agent/skills/codebase-memory/query.py callers ProcessOrder
  python .agent/skills/codebase-memory/query.py callees src/orders/service.py
  python .agent/skills/codebase-memory/query.py search '.*Handler$' --kind class
  python .agent/skills/codebase-memory/query.py file  src/orders/service.py
  python .agent/skills/codebase-memory/query.py importers svc.orders.core
  python .agent/skills/codebase-memory/query.py routes /orders
  python .agent/skills/codebase-memory/query.py impact src/orders/service.py
  python .agent/skills/codebase-memory/query.py changed
  python .agent/skills/codebase-memory/query.py coverage src/a.py src/b.py
  python .agent/skills/codebase-memory/query.py orphans --limit 30

Every command accepts --json and --limit. This process never writes and never
touches the network.
"""

import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def find_graph(root):
    root = os.path.abspath(root)
    for _ in range(8):
        g = os.path.join(root, ".agent", "memory", "graph")
        if os.path.isdir(g):
            return g
        parent = os.path.dirname(root)
        if parent == root:
            break
        root = parent
    sys.stderr.write(
        "no index found. run: python .agent/skills/codebase-memory/index.py build\n")
    sys.exit(3)


def stream(path):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


class Graph:
    def __init__(self, gdir):
        self.gdir = gdir
        self.f_syms = os.path.join(gdir, "symbols.jsonl")
        self.f_files = os.path.join(gdir, "files.jsonl")
        self.f_edges = os.path.join(gdir, "edges.jsonl")
        mp = os.path.join(gdir, "manifest.json")
        self.man = json.load(open(mp, encoding="utf-8")) if os.path.exists(mp) else {}

    def symbols(self):
        return stream(self.f_syms)

    def files(self):
        return stream(self.f_files)

    def edges(self, kind=None):
        for e in stream(self.f_edges):
            if kind is None or e["t"] == kind:
                yield e

    def syms_named(self, name, exact=True):
        out = []
        for s in self.symbols():
            if (s["n"] == name) if exact else (name.lower() in s["n"].lower()):
                out.append(s)
        return out


def emit(args, rows, fmt):
    if args.json:
        print(json.dumps(rows, indent=1, sort_keys=True))
        return
    if not rows:
        print("(no rows)")
        return
    for r in rows[: args.limit]:
        print(fmt(r))
    if len(rows) > args.limit:
        print("… %d more (raise --limit)" % (len(rows) - args.limit))


def banner(g):
    m = g.man
    return ("index generation %s (%s) · %d files / %d parsed · %d symbols · "
            "calls=%s" % (m.get("generation"), m.get("generated_at"),
                          m.get("files_total", 0), m.get("files_parsed", 0),
                          m.get("symbols", 0), m.get("calls_mode")))


# ------------------------------------------------------------------ verbs ---

def cmd_arch(g, args):
    m = g.man
    print(banner(g))
    print()
    langs = m.get("loc_by_lang", {})
    tot = sum(langs.values()) or 1
    print("stack: " + ", ".join("%s %.0f%%" % (k, 100.0 * v / tot)
                                for k, v in list(langs.items())[:8]))
    mods = {}
    for f in g.files():
        d = mods.setdefault(f["mod"], [0, 0])
        d[0] += 1
        d[1] += f.get("loc", 0)
    print("modules (%d), largest first:" % len(mods))
    for name, (n, loc) in sorted(mods.items(), key=lambda kv: -kv[1][1])[: args.limit]:
        print("  %-44s %4d files %9s LOC" % (name, n, f"{loc:,}"))
    sk = m.get("skipped", {})
    if sk:
        print("not parsed: " + ", ".join("%s=%d" % kv for kv in sorted(sk.items())))
    print("read .agent/memory/CODEBASE_MAP.md for the full narrative map.")


def cmd_def(g, args):
    rows = g.syms_named(args.name, exact=not args.fuzzy)
    emit(args, rows, lambda s: "%s:%d  %-9s %s   %s"
         % (s["p"], s["l"], s["k"], s["n"], s["sig"][:90]))
    if not rows:
        print("no symbol named %r in the index. It may be dynamically generated, "
              "in an unparsed file, or spelled differently — try `search` with a "
              "pattern, or grep the paths `coverage` reports as unparsed."
              % args.name)


def cmd_callers(g, args):
    ids = {s["id"] for s in g.syms_named(args.name, exact=not args.fuzzy)}
    if not ids:
        print("no such symbol in the index: %r" % args.name)
        return
    rows = sorted({e["s"] for e in g.edges("CALLS") if e["d"] in ids})
    emit(args, rows, lambda p: "  %s" % p)
    print("%d file(s) reference %r." % (len(rows), args.name))
    print("Unresolved-by-design: call sites whose name is ambiguous across files "
          "are not recorded. Treat this as a strong lead, not an exhaustive list.")


def cmd_callees(g, args):
    p = args.path.replace("\\", "/")
    rows = sorted({e["d"] for e in g.edges("CALLS") if e["s"] == p})
    emit(args, rows, lambda d: "  %s" % d.replace("#", "  ").replace("@", ":"))


def cmd_search(g, args):
    rx = re.compile(args.pattern, re.I)
    rows = []
    for s in g.symbols():
        if args.kind and s["k"] != args.kind:
            continue
        if args.module and not s["mod"].startswith(args.module):
            continue
        if rx.search(s["n"]):
            rows.append(s)
    emit(args, rows, lambda s: "%s:%d  %-9s %s" % (s["p"], s["l"], s["k"], s["n"]))
    print("%d match(es)." % len(rows))


def cmd_file(g, args):
    p = args.path.replace("\\", "/")
    rec = next((f for f in g.files() if f["p"] == p), None)
    if not rec:
        print("%s is NOT in the index. Either it does not exist, it is ignored, "
              "or it was skipped. Run `coverage %s` for the reason." % (p, p))
        return
    print("%s  lang=%s mod=%s loc=%s parsed=%s"
          % (p, rec["lang"], rec["mod"], rec.get("loc", "?"), rec.get("parsed")))
    syms = [s for s in g.symbols() if s["p"] == p]
    print("-- defines %d symbol(s)" % len(syms))
    for s in syms[: args.limit]:
        print("   %5d  %-9s %s" % (s["l"], s["k"], s["n"]))
    imps = sorted({e["d"] for e in g.edges("IMPORTS") if e["s"] == p})
    if imps:
        print("-- imports: " + ", ".join(imps[:30]))
    routes = sorted({e["d"] for e in g.edges("EXPOSES") if e["s"] == p})
    if routes:
        print("-- exposes: " + ", ".join(routes[:20]))


def cmd_importers(g, args):
    t = args.target
    rows = sorted({e["s"] for e in g.edges("IMPORTS")
                   if e["d"] == t or e["d"].endswith("/" + t) or t in e["d"]})
    emit(args, rows, lambda p: "  %s" % p)
    print("%d file(s) import something matching %r." % (len(rows), t))


def cmd_routes(g, args):
    pat = args.pattern or ""
    rows = [(e["d"], e["s"]) for e in g.edges("EXPOSES") if pat in e["d"]]
    rows.sort()
    emit(args, rows, lambda r: "  %-40s %s" % (r[0], r[1]))
    print("%d route(s)." % len(rows))


def cmd_impact(g, args):
    p = args.path.replace("\\", "/")
    syms = [s for s in g.symbols() if s["p"] == p]
    ids = {s["id"] for s in syms}
    direct = sorted({e["s"] for e in g.edges("CALLS") if e["d"] in ids})
    stem = os.path.splitext(os.path.basename(p))[0]
    imp = sorted({e["s"] for e in g.edges("IMPORTS")
                  if stem and (stem == os.path.basename(e["d"]) or e["d"].endswith("." + stem)
                               or e["d"].endswith("/" + stem))})
    print("blast radius for %s" % p)
    print("  defines %d symbol(s)" % len(syms))
    print("  %d file(s) call into it:" % len(direct))
    for x in direct[: args.limit]:
        print("     %s" % x)
    print("  %d file(s) import it by name:" % len(imp))
    for x in imp[: args.limit]:
        print("     %s" % x)
    tests = [x for x in set(direct) | set(imp) if re.search(r"(?i)test|spec", x)]
    print("  %d covering test file(s): %s" % (len(tests), ", ".join(sorted(tests)[:10]) or "none found"))
    print("  Ambiguous call sites are excluded by design. Confirm with a direct "
          "search before claiming the radius is complete.")


def cmd_changed(g, args):
    root = os.path.abspath(args.root)
    try:
        out = subprocess.run(["git", "-C", root, "diff", "--name-only",
                              args.base] if args.base else
                             ["git", "-C", root, "diff", "--name-only", "HEAD"],
                             capture_output=True, text=True, timeout=60)
        paths = [l.strip().replace("\\", "/") for l in out.stdout.splitlines() if l.strip()]
    except Exception as exc:
        print("git unavailable: %s" % exc)
        return
    if not paths:
        print("no changed files")
        return
    print("%d changed file(s)" % len(paths))
    for p in paths[: args.limit]:
        syms = [s for s in g.symbols() if s["p"] == p]
        ids = {s["id"] for s in syms}
        callers = sorted({e["s"] for e in g.edges("CALLS") if e["d"] in ids})
        risk = "HIGH" if len(callers) > 8 else "MED" if callers else "LOW"
        print("  %-52s %-4s %d symbol(s), %d caller file(s)"
              % (p, risk, len(syms), len(callers)))
        for c in callers[:6]:
            print("        ← %s" % c)


def cmd_coverage(g, args):
    known = {f["p"]: f for f in g.files()}
    for raw in args.paths:
        p = raw.replace("\\", "/")
        rec = known.get(p)
        if rec is None:
            hits = [k for k in known if k.endswith("/" + p) or p in k]
            if hits:
                print("%s  NOT-EXACT — did you mean: %s" % (p, ", ".join(hits[:5])))
            else:
                print("%s  ABSENT — not indexed. Read it directly and say so." % p)
        elif not rec.get("parsed"):
            print("%s  PRESENT-UNPARSED (%s) — no symbols recorded; read it directly."
                  % (p, rec.get("skip", rec["lang"])))
        else:
            print("%s  PARSED — %s LOC, %d symbols recorded."
                  % (p, f'{rec.get("loc",0):,}', rec.get("syms", 0)))
    print("A PARSED result means no recorded gap, not proof of completeness.")


def cmd_orphans(g, args):
    called = {e["d"] for e in g.edges("CALLS")}
    rows = []
    for s in g.symbols():
        if s["id"] in called:
            continue
        if s["k"] not in ("function", "method"):
            continue
        if re.search(r"(?i)test|spec|mock|fixture|conftest", s["p"]):
            continue
        if s["n"].startswith("_") or s["n"] in ("main", "handler", "run", "init"):
            continue
        rows.append(s)
    emit(args, rows, lambda s: "%s:%d  %-9s %s" % (s["p"], s["l"], s["k"], s["n"]))
    print("%d symbol(s) with no recorded caller." % len(rows))
    print("WARNING: this is a lead list, not a delete list. Entry points, exported "
          "APIs, dynamic dispatch, reflection, DI containers, and cross-language "
          "calls all look identical to dead code here. Verify each one before "
          "touching it.")


def cmd_stats(g, args):
    print(json.dumps(g.man, indent=1, sort_keys=True))


# ------------------------------------------------------------------- main ---

def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=".")
    common.add_argument("--json", action="store_true")
    common.add_argument("--limit", type=int, default=40)

    ap = argparse.ArgumentParser(description="Query the local codebase graph",
                                 parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, *pos, **kw):
        p = sub.add_parser(name, help=fn.__doc__, parents=[common])
        for a, akw in pos:
            p.add_argument(a, **akw)
        p.set_defaults(fn=fn)
        return p

    add("arch", cmd_arch)
    p = add("def", cmd_def, ("name", {}))
    p.add_argument("--fuzzy", action="store_true")
    p = add("callers", cmd_callers, ("name", {}))
    p.add_argument("--fuzzy", action="store_true")
    add("callees", cmd_callees, ("path", {}))
    p = add("search", cmd_search, ("pattern", {}))
    p.add_argument("--kind")
    p.add_argument("--module")
    add("file", cmd_file, ("path", {}))
    add("importers", cmd_importers, ("target", {}))
    p = add("routes", cmd_routes)
    p.add_argument("pattern", nargs="?")
    add("impact", cmd_impact, ("path", {}))
    p = add("changed", cmd_changed)
    p.add_argument("--base", default=None, help="git ref to diff against")
    p = add("coverage", cmd_coverage)
    p.add_argument("paths", nargs="+")
    add("orphans", cmd_orphans)
    add("stats", cmd_stats)

    args = ap.parse_args()
    g = Graph(find_graph(args.root))
    args.fn(g, args)


if __name__ == "__main__":
    main()
