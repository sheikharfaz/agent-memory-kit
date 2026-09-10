#!/usr/bin/env python3
"""
session-memory :: UserPromptSubmit hook.
Fires on every prompt, before the agent sees it. Two jobs:
  1. Record the prompt into .agent/memory/session/entries.jsonl (secrets
     redacted, best-effort).
  2. Recall entries from *other* sessions that are lexically similar to this
     prompt, and inject them as additional context -- this is what "sits
     between the calls": the agent gets related history automatically,
     without either of you having to remember it exists.

Recalled entries have their `weight` bumped (see memory.py `recall` /
`bump_weight`), a frequency heuristic so entries that keep proving relevant
rank a little higher next time. It is not a trained model and not true
reinforcement learning -- it is a cheap, honest approximation of it.

Wire-up (.claude/settings.json):
  "UserPromptSubmit": [{"hooks": [{"type": "command",
    "command": "python3 .agent/skills/session-memory/hooks/user_prompt_submit.py"}]}]

Never blocks the prompt: any failure here is swallowed and the hook exits 0.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import memory as mem  # noqa: E402
from _common import read_hook_input, emit, snippet, safe_main  # noqa: E402


def run():
    data = read_hook_input()
    session_id = data.get("session_id", "unknown")
    cwd = data.get("cwd") or os.getcwd()
    prompt = data.get("prompt", "")
    root = mem.find_repo_root(cwd)

    mem.append_entry(root, session_id, cwd, "prompt", prompt)

    if not prompt.strip():
        return
    hits = mem.recall(root, prompt, limit=5, exclude_session=session_id)
    if not hits:
        return
    mem.bump_weight(root, [e["id"] for e, _ in hits])

    lines = [
        "Related context from earlier sessions in this repo, found by local "
        "lexical recall (TF-IDF over past prompts/turns, not semantic "
        "understanding) -- treat as a lead, verify before relying on it:",
    ]
    for e, score in hits:
        lines.append("- [%.2f] %s %s: %s" % (
            score, e.get("ts"), e.get("kind"), snippet(e.get("text", ""))))
    emit("\n".join(lines), "UserPromptSubmit")


if __name__ == "__main__":
    safe_main(run)
