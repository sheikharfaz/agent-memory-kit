#!/usr/bin/env python3
"""
Merge the session-memory hook commands into a target repo's
.claude/settings.json. Idempotent -- running it twice does not duplicate
entries. Only ever adds these three commands; every other key and every
other hook already in settings.json is left exactly as it was.

  python3 wire_hooks.py <target-repo-dir>

Called by install.sh/install.ps1 only when --wire-hooks is passed explicitly.
Never run automatically.
"""

import json
import os
import sys

SCRIPTS = {
    "SessionStart": "hooks/session_start.py",
    "UserPromptSubmit": "hooks/user_prompt_submit.py",
    "Stop": "hooks/stop.py",
}


def main():
    if len(sys.argv) != 2:
        print("usage: wire_hooks.py <target-repo-dir>", file=sys.stderr)
        sys.exit(2)
    target = os.path.abspath(sys.argv[1])
    settings_path = os.path.join(target, ".claude", "settings.json")

    settings = {}
    if os.path.exists(settings_path):
        with open(settings_path, encoding="utf-8") as fh:
            settings = json.load(fh)

    hooks = settings.setdefault("hooks", {})
    added = []
    for event, rel in SCRIPTS.items():
        cmd = "python3 .agent/skills/session-memory/%s" % rel
        groups = hooks.setdefault(event, [])
        existing_cmds = {h.get("command") for g in groups for h in g.get("hooks", [])}
        if cmd in existing_cmds:
            continue
        groups.append({"hooks": [{"type": "command", "command": cmd}]})
        added.append(event)

    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    with open(settings_path, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
        fh.write("\n")

    if added:
        print("wired hooks for: %s" % ", ".join(added))
    else:
        print("hooks already wired, nothing changed")


if __name__ == "__main__":
    main()
