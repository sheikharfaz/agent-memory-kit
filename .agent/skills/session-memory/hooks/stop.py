#!/usr/bin/env python3
"""
session-memory :: Stop hook.
Fires when the agent finishes responding. Records the last assistant text
turn from the transcript (not just what was asked, but what was actually
said/done), so future recall has substance to match against. Also runs
cheap periodic pruning so entries.jsonl never grows unbounded.

Best-effort transcript parsing: reads the Claude Code transcript JSONL at
`transcript_path`, takes the last record whose `message.role == "assistant"`,
and concatenates its text content blocks (tool_use/tool_result blocks are
skipped). If the transcript format changes or the file is unreadable, this
hook simply records nothing for the turn -- it never fails the session.

Wire-up (.claude/settings.json):
  "Stop": [{"hooks": [{"type": "command",
    "command": "python3 .agent/skills/session-memory/hooks/stop.py"}]}]

Never blocks stopping: any failure here is swallowed and the hook exits 0.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import memory as mem  # noqa: E402
from _common import read_hook_input, safe_main, session_memory_disabled  # noqa: E402

PRUNE_EVERY = 250
RETENTION_DAYS_ENV = "AGENT_MEMORY_KIT_RETENTION_DAYS"


def extract_last_assistant_text(transcript_path, max_chars):
    if not transcript_path or not os.path.exists(transcript_path):
        return ""
    last_text = ""
    try:
        with open(transcript_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = rec.get("message") if isinstance(rec, dict) else None
                if not isinstance(msg, dict) or msg.get("role") != "assistant":
                    continue
                content = msg.get("content")
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    parts = [b.get("text", "") for b in content
                             if isinstance(b, dict) and b.get("type") == "text"]
                    text = "\n".join(p for p in parts if p)
                else:
                    text = ""
                if text.strip():
                    last_text = text
    except Exception:
        pass
    return last_text[:max_chars]


def run():
    if session_memory_disabled():
        return
    data = read_hook_input()
    session_id = data.get("session_id", "unknown")
    cwd = data.get("cwd") or os.getcwd()
    root = mem.find_repo_root(cwd)

    text = extract_last_assistant_text(data.get("transcript_path"), mem.MAX_TEXT_CHARS)
    if text.strip():
        mem.append_entry(root, session_id, cwd, "turn", text)

    n = mem.stats(root).get("entries", 0)
    if n and n % PRUNE_EVERY == 0:
        keep_days = os.environ.get(RETENTION_DAYS_ENV)
        mem.prune(root, keep_days=int(keep_days) if keep_days else None)


if __name__ == "__main__":
    safe_main(run)
