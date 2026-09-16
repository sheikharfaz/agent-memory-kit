#!/usr/bin/env python3
"""
session-memory :: SessionStart hook.
Fires when a Claude Code session starts (or resumes/clears). Three jobs:
  1. Surfaces the most recent entry from each *other* session recorded in
     this repo, so a fresh session opens already knowing what the last one
     was doing -- the mechanism that lets you close a session and pick the
     thread back up in a new one.
  2. If dev-recap is also installed and no project-familiarity profile has
     been recorded yet, nudges the agent to ask the developer once (new to
     this project / somewhat familiar / veteran) and record it -- this is
     the "new-hire week one" entry point: asked once, at first contact,
     stored per-project, never asked again once answered. Silent no-op if
     dev-recap isn't installed, or a profile already exists.
  3. If codebase-memory is installed and its map hasn't changed since the
     last session ended (map_state.json, stamped by the Stop hook), says so
     -- an optional skip, never a directive, and silent whenever state is
     missing or the generations differ. AGENTS.md's own "read the map every
     session" rule stays the default; this only fires when there is real
     evidence nothing moved.

Wire-up (.claude/settings.json):
  "SessionStart": [{"hooks": [{"type": "command",
    "command": "python3 .agent/skills/session-memory/hooks/session_start.py"}]}]

Never blocks startup: any failure here is swallowed and the hook exits 0
emitting nothing. AGENT_MEMORY_KIT_DISABLE_SESSION_MEMORY silences both
jobs, not just recall -- this hook is the only place either one runs.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # skill dir: memory.py
sys.path.insert(0, HERE)                   # this dir: _common.py

import memory as mem  # noqa: E402
from _common import read_hook_input, emit, snippet, safe_main, session_memory_disabled  # noqa: E402


def _familiarity_nudge(root):
    dev_recap_dir = os.path.join(root, ".agent", "skills", "dev-recap")
    if not os.path.isdir(dev_recap_dir):
        return None
    profile_path = os.path.join(root, ".agent", "memory", "learning", "profile-log.jsonl")
    if os.path.exists(profile_path):
        return None
    return (
        "No project-familiarity profile recorded yet for this repo "
        "(dev-recap). Ask the developer once, briefly: are they new to "
        "this project, somewhat familiar, or a veteran on it? Then record "
        "it and don't ask again this session or in future ones:\n"
        "  python .agent/skills/dev-recap/recap_log.py set-familiarity "
        "--level new|some|veteran"
    )


def _map_freshness_note(root):
    current = mem.current_map_generation(root)
    if not current:
        return None
    state = mem.map_generation_state(root)
    if not state or state.get("generation") != current:
        return None
    return (
        "CODEBASE_MAP.md is unchanged since generation %s, last confirmed "
        "at the end of session %s (%s). You may skip re-reading it this "
        "session unless you need specifics from it -- if in doubt, read it "
        "anyway; this is a time-saving option, not a rule." % (
            current[:12], state.get("session_id", "unknown")[:8],
            state.get("ts", "unknown")))


def run():
    if session_memory_disabled():
        return
    data = read_hook_input()
    session_id = data.get("session_id", "unknown")
    cwd = data.get("cwd") or os.getcwd()
    root = mem.find_repo_root(cwd)

    blocks = []

    rows = mem.recent(root, exclude_session=session_id, limit=5)
    if rows:
        lines = [
            "Local session-memory (.agent/memory/session/) has context from "
            "earlier sessions in this repo. Lexical recall, not verified for "
            "this turn -- confirm anything load-bearing before acting on it:",
        ]
        for e in rows:
            lines.append("- %s [session %s, %s]: %s" % (
                e.get("ts"), e.get("session_id", "")[:8], e.get("kind"),
                snippet(e.get("text", ""))))
        blocks.append("\n".join(lines))

    nudge = _familiarity_nudge(root)
    if nudge:
        blocks.append(nudge)

    freshness = _map_freshness_note(root)
    if freshness:
        blocks.append(freshness)

    if blocks:
        emit("\n\n".join(blocks), "SessionStart")


if __name__ == "__main__":
    safe_main(run)
