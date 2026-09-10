#!/usr/bin/env python3
"""
spec-first :: spec_first.py
Mechanical support for writing like a senior engineer instead of vibe
coding: scaffold PRD.md/TRD.md templates under .agent/work/<task-slug>/,
and check them for unresolved acceptance criteria, unanswered open
questions, or a missing testing strategy. It does not write the content --
that's the agent's actual thinking, same as research.md/progress.md always
were -- it only enforces the shape and reports what's still incomplete.

  python .agent/skills/spec-first/spec_first.py scaffold auth-retry
  python .agent/skills/spec-first/spec_first.py check auth-retry
  python .agent/skills/spec-first/spec_first.py list

Guarantees: Python 3.8+ standard library only. No network. Writes only
under .agent/work/<task-slug>/ (the same directory the existing RPI
workflow already uses), and never overwrites an existing PRD.md/TRD.md
without --force.
"""

import argparse
import json
import os
import re
import sys

WORK_SUBDIR = os.path.join(".agent", "work")
PRD_FILENAME = "PRD.md"
TRD_FILENAME = "TRD.md"
RESEARCH_FILENAME = "research.md"
PROGRESS_FILENAME = "progress.md"

PRD_TEMPLATE = """# PRD: %(slug)s

<!-- Product/problem requirements. Capture WHAT and WHY before touching
     code. Skip this file entirely only for an already-unambiguous, trivial
     request -- see .agent/skills/spec-first/SKILL.md for the threshold. -->

## Problem
<!-- What's broken or missing, for whom, and why it matters now. -->

## Current vs desired behavior
- Current:
- Desired:

## Acceptance criteria
<!-- Testable/observable. Check a box only once it's actually verified,
     never just because it was written. -->
- [ ]

## Non-goals
<!-- Explicitly out of scope for this change. -->

## Open questions
<!-- Anything ambiguous. Ask the developer rather than guess -- remove the
     line once it's answered. An unanswered question here at TRD time is a
     real gap, not a formality. -->

## Assumptions
<!-- Only what's left after actually asking. Label ASSUMPTION: and carry it
     forward into TRD.md and the closing dev-recap. -->
"""

TRD_TEMPLATE = """# TRD: %(slug)s

<!-- Technical requirements/design: HOW, and why this way. This is what
     separates a senior engineer's plan from vibe coding -- show the
     alternatives you rejected, not just the one you picked. -->

## Approach
<!-- The chosen technical approach, one paragraph. -->

## Alternatives considered
<!-- What else was possible, and why it was rejected. If there was truly
     only one reasonable approach, say that and why. -->

## Design
<!-- Files/symbols touched (path:line, from research.md), interfaces or
     data contracts affected, edge cases and how each is handled. -->

## Testing strategy
<!-- What verifies each PRD.md acceptance criterion. Map them explicitly:
     criterion -> how it's checked. -->

## Rollback plan
<!-- How to undo this if it turns out wrong after shipping. -->

## Risks & blast radius
<!-- `query.py impact` on touched files; flag anything that touches a hub
     symbol from CODEBASE_MAP.md. -->

## Phases
<!-- intent / files touched / the change / how it's verified / how to roll
     it back -- one entry per checkpoint. Order so the tree builds and
     tests pass at every boundary. -->
- [ ] Phase 1:
"""


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


def task_dir(root, slug):
    return os.path.join(root, WORK_SUBDIR, slug)


# ------------------------------------------------------------- scaffold ---

def scaffold(root, slug, want_prd=True, want_trd=True, force=False):
    d = task_dir(root, slug)
    os.makedirs(d, exist_ok=True)
    written = []
    if want_prd:
        path = os.path.join(d, PRD_FILENAME)
        if force or not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(PRD_TEMPLATE % {"slug": slug})
            written.append(path)
    if want_trd:
        path = os.path.join(d, TRD_FILENAME)
        if force or not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(TRD_TEMPLATE % {"slug": slug})
            written.append(path)
    return written


# ----------------------------------------------------------------- check --

_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def _strip_comments(text):
    return _COMMENT_RE.sub("", text)


def _section(text, heading):
    """Lines under a `## heading` up to the next `## ` or end of file."""
    pattern = re.compile(r"^##\s+%s\s*$" % re.escape(heading), re.M | re.I)
    m = pattern.search(text)
    if not m:
        return None
    rest = text[m.end():]
    nxt = re.search(r"^##\s+", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def _checkbox_lines(section_text):
    if not section_text:
        return []
    return re.findall(r"^\s*-\s*\[([ xX])\]\s*(\S.*)$", section_text, re.M)


def _bullet_lines(section_text):
    if not section_text:
        return []
    return [m.strip() for m in re.findall(r"^\s*-\s+(\S.*)$", section_text, re.M)]


def check(root, slug):
    d = task_dir(root, slug)
    prd_path = os.path.join(d, PRD_FILENAME)
    trd_path = os.path.join(d, TRD_FILENAME)
    result = {"slug": slug, "prd_found": os.path.exists(prd_path),
              "trd_found": os.path.exists(trd_path)}

    if result["prd_found"]:
        with open(prd_path, encoding="utf-8") as fh:
            prd_text = _strip_comments(fh.read())
        boxes = _checkbox_lines(_section(prd_text, "Acceptance criteria"))
        result["acceptance_total"] = len(boxes)
        result["acceptance_checked"] = sum(1 for state, _ in boxes if state.lower() == "x")
        result["acceptance_unchecked"] = [text for state, text in boxes if state.lower() != "x"]
        result["open_questions"] = _bullet_lines(_section(prd_text, "Open questions"))

    if result["trd_found"]:
        with open(trd_path, encoding="utf-8") as fh:
            trd_text = _strip_comments(fh.read())
        testing = _section(trd_text, "Testing strategy")
        result["trd_has_testing_strategy"] = bool(testing and testing.strip())
        approach = _section(trd_text, "Approach")
        result["trd_has_approach"] = bool(approach and approach.strip())

    return result


def list_tasks(root):
    base = os.path.join(root, WORK_SUBDIR)
    if not os.path.isdir(base):
        return []
    rows = []
    for slug in sorted(os.listdir(base)):
        d = os.path.join(base, slug)
        if not os.path.isdir(d):
            continue
        rows.append({
            "slug": slug,
            "prd": os.path.exists(os.path.join(d, PRD_FILENAME)),
            "research": os.path.exists(os.path.join(d, RESEARCH_FILENAME)),
            "trd": os.path.exists(os.path.join(d, TRD_FILENAME)),
            "progress": os.path.exists(os.path.join(d, PROGRESS_FILENAME)),
        })
    return rows


# ----------------------------------------------------------------- cli ----

def cmd_scaffold(args):
    root = find_repo_root(args.root)
    written = scaffold(root, args.slug, want_prd=not args.trd_only,
                        want_trd=not args.prd_only, force=args.force)
    if not written:
        print("nothing written -- %s already has these files (use --force to overwrite)" % args.slug)
        return
    for path in written:
        print("wrote %s" % path)


def cmd_check(args):
    root = find_repo_root(args.root)
    result = check(root, args.slug)
    if args.json:
        print(json.dumps(result, indent=1))
        return
    if not result["prd_found"] and not result["trd_found"]:
        print("no PRD.md or TRD.md found for %r under .agent/work/ -- either this task "
              "skipped spec-first (fine for a trivial/unambiguous request), or "
              "`scaffold` hasn't been run yet." % args.slug)
        return
    if result["prd_found"]:
        print("PRD.md: %d/%d acceptance criteria checked" % (
            result["acceptance_checked"], result["acceptance_total"]))
        if result["acceptance_total"] == 0:
            print("  (no acceptance criteria written yet -- the template ships empty)")
        for text in result["acceptance_unchecked"]:
            print("  [ ] %s" % text)
        if result["open_questions"]:
            print("  %d open question(s) still unanswered:" % len(result["open_questions"]))
            for q in result["open_questions"]:
                print("    - %s" % q)
    else:
        print("PRD.md: not found")
    if result["trd_found"]:
        print("TRD.md: approach=%s testing_strategy=%s" % (
            "written" if result["trd_has_approach"] else "MISSING",
            "written" if result["trd_has_testing_strategy"] else "MISSING"))
    else:
        print("TRD.md: not found")


def cmd_list(args):
    root = find_repo_root(args.root)
    rows = list_tasks(root)
    if args.json:
        print(json.dumps(rows, indent=1))
        return
    if not rows:
        print("(no tasks under .agent/work/)")
        return

    def glyph(present):
        return "x" if present else "."

    for r in rows:
        print("%-30s PRD[%s] research[%s] TRD[%s] progress[%s]" % (
            r["slug"], glyph(r["prd"]), glyph(r["research"]), glyph(r["trd"]), glyph(r["progress"])))


def main():
    p = argparse.ArgumentParser(prog="spec_first.py")
    p.add_argument("--root", default=".")
    sub = p.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("scaffold")
    sc.add_argument("slug")
    sc.add_argument("--force", action="store_true")
    grp = sc.add_mutually_exclusive_group()
    grp.add_argument("--prd-only", action="store_true")
    grp.add_argument("--trd-only", action="store_true")
    sc.set_defaults(func=cmd_scaffold)

    ck = sub.add_parser("check")
    ck.add_argument("slug")
    ck.add_argument("--json", action="store_true")
    ck.set_defaults(func=cmd_check)

    ls = sub.add_parser("list")
    ls.add_argument("--json", action="store_true")
    ls.set_defaults(func=cmd_list)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
