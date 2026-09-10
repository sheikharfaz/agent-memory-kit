"""
Shared helpers for the session-memory Claude Code hooks.

A hook must never break the session it is attached to. Every hook entry point
runs through safe_main(), which swallows any exception and always exits 0 --
worst case the memory feature silently does nothing this turn.
"""

import json
import sys


def read_hook_input():
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def emit(additional_context, event_name):
    if not additional_context:
        return
    payload = {"hookSpecificOutput": {
        "hookEventName": event_name,
        "additionalContext": additional_context,
    }}
    try:
        print(json.dumps(payload))
    except Exception:
        pass


def snippet(text, n=200):
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def safe_main(fn):
    try:
        fn()
    except Exception:
        pass
    sys.exit(0)
