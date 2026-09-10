#!/usr/bin/env python3
"""
session-memory :: SessionStart hook.
Fires when a Claude Code session starts (or resumes/clears). Surfaces the
most recent entry from each *other* session recorded in this repo, so a fresh
session opens already knowing what the last one was doing -- the mechanism
that lets you close a session and pick the thread back up in a new one.

Wire-up (.claude/settings.json):
  "SessionStart": [{"hooks": [{"type": "command",
    "command": "python3 .agent/skills/session-memory/hooks/session_start.py"}]}]

Never blocks startup: any failure here is swallowed and the hook exits 0
emitting nothing.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # skill dir: memory.py
sys.path.insert(0, HERE)                   # this dir: _common.py

import memory as mem  # noqa: E402
from _common import read_hook_input, emit, snippet, safe_main, session_memory_disabled  # noqa: E402


def run():
    if session_memory_disabled():
        return
    data = read_hook_input()
    session_id = data.get("session_id", "unknown")
    cwd = data.get("cwd") or os.getcwd()
    root = mem.find_repo_root(cwd)

    rows = mem.recent(root, exclude_session=session_id, limit=5)
    if not rows:
        return

    lines = [
        "Local session-memory (.agent/memory/session/) has context from "
        "earlier sessions in this repo. Lexical recall, not verified for "
        "this turn -- confirm anything load-bearing before acting on it:",
    ]
    for e in rows:
        lines.append("- %s [session %s, %s]: %s" % (
            e.get("ts"), e.get("session_id", "")[:8], e.get("kind"),
            snippet(e.get("text", ""))))
    emit("\n".join(lines), "SessionStart")


if __name__ == "__main__":
    safe_main(run)
