#!/usr/bin/env python3
"""
How many real symbols does codebase-memory's secret filter hide?

Before v0.5.0 the filter matched the bare *words* token/secret/password/
api_key/... and was applied to symbol names, so any symbol merely named
after a credential concept (`check_password`, `TokenStore`) silently
vanished from the index. This script re-runs both filters over a repo's
symbol definitions and reports what each one drops.

  python3 benchmarks/symbol_filter_audit.py --repo /tmp/django

Reads source files only; writes nothing. Standard library only.
"""

import argparse
import collections
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), ".agent", "skills", "codebase-memory"))

import index  # noqa: E402

# The pre-v0.5.0 pattern, verbatim, kept here as the baseline being measured.
OLD_SECRET_TEXT = re.compile(
    r"(?i)(?:api[_-]?key|secret|passw(?:or)?d|token|bearer\s|access[_-]?key"
    r"|private[_-]?key|-----BEGIN|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}"
    r"|sk-[A-Za-z0-9]{20,}|xox[baprs]-)"
)
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".agent"}


def symbol_names(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            lang = index.EXT_LANG.get(os.path.splitext(fn)[1])
            if not lang or lang not in index.DEFS:
                continue
            try:
                with open(os.path.join(dirpath, fn), encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            for rx, _kind in index.DEFS[lang]:
                for m in rx.finditer(text):
                    name = (m.group(m.lastindex or 1) or "").strip('"`')
                    if name and name.lower() not in index.KEYWORDS and len(name) >= 2:
                        yield name


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--show", type=int, default=10, help="how many dropped names to list")
    args = ap.parse_args()

    total = 0
    old, new = collections.Counter(), collections.Counter()
    for name in symbol_names(args.repo):
        total += 1
        if OLD_SECRET_TEXT.search(name):
            old[name] += 1
        if index.SECRET_LITERAL.search(name):
            new[name] += 1

    print("%s: %d symbol definitions" % (args.repo, total))
    print("  pre-v0.5.0 filter drops: %d definitions, %d distinct names"
          % (sum(old.values()), len(old)))
    print("  current filter drops:    %d definitions, %d distinct names"
          % (sum(new.values()), len(new)))
    for name, count in old.most_common(args.show):
        print("    was hidden: %-40s x%d" % (name, count))


if __name__ == "__main__":
    main()
