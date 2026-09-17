#!/usr/bin/env python3
"""
Wire agent-memory-kit into Claude Code for a target repo:

1. Merge the session-memory hook commands into .claude/settings.json.
   Only ever adds these three commands; every other key and hook already
   there is left exactly as it was.
2. Make Claude Code load AGENTS.md. Claude Code reads CLAUDE.md, not
   AGENTS.md, so without this the kit's contract never reaches the agent.
   Following Claude Code's own documented pattern, CLAUDE.md gets an
   `@AGENTS.md` import line (created if missing, appended otherwise).

Both steps are idempotent.

  python3 wire_hooks.py <target-repo-dir>

Called by install.sh/install.ps1/install.py only when --wire-hooks is
passed explicitly, and by `amk init` (step 2 always, step 1 with --hooks).
"""

import json
import os
import sys

SCRIPTS = {
    "SessionStart": "hooks/session_start.py",
    "UserPromptSubmit": "hooks/user_prompt_submit.py",
    "Stop": "hooks/stop.py",
}


IMPORT_LINE = "@AGENTS.md"
IMPORT_NOTE = "<!-- agent-memory-kit: Claude Code reads CLAUDE.md, not AGENTS.md -->"


def claude_md_imports_agents(target):
    """True if Claude Code will load AGENTS.md for this repo: a CLAUDE.md
    (root or .claude/) that is a link to AGENTS.md or has an import line."""
    for rel in ("CLAUDE.md", os.path.join(".claude", "CLAUDE.md")):
        path = os.path.join(target, rel)
        if os.path.islink(path):
            if os.path.basename(os.path.realpath(path)) == "AGENTS.md":
                return True
            continue
        if os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                if any(line.strip() in (IMPORT_LINE, "@./AGENTS.md") for line in fh):
                    return True
    return False


def wire_claude_md(target):
    """Returns what happened: 'present', 'created', 'appended', or
    'skipped-symlink' (a CLAUDE.md link to some other file is left alone,
    because appending through it would edit the file it points at)."""
    target = os.path.abspath(target)
    if claude_md_imports_agents(target):
        return "present"
    root_md = os.path.join(target, "CLAUDE.md")
    nested_md = os.path.join(target, ".claude", "CLAUDE.md")
    path = nested_md if (os.path.isfile(nested_md) and not os.path.exists(root_md)) else root_md
    if os.path.islink(path):
        return "skipped-symlink"
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(IMPORT_NOTE + "\n" + IMPORT_LINE + "\n")
        return "created"
    with open(path, encoding="utf-8", errors="replace") as fh:
        existing = fh.read()
    with open(path, "a", encoding="utf-8") as fh:
        if existing and not existing.endswith("\n"):
            fh.write("\n")
        fh.write("\n" + IMPORT_NOTE + "\n" + IMPORT_LINE + "\n")
    return "appended"


CLAUDE_MD_MESSAGES = {
    "present": "CLAUDE.md already loads AGENTS.md",
    "created": "created CLAUDE.md with @AGENTS.md so Claude Code loads the contract",
    "appended": "added @AGENTS.md to CLAUDE.md so Claude Code loads the contract",
    "skipped-symlink": "CLAUDE.md is a link to another file; left it alone -- "
                       "add @AGENTS.md to it yourself so Claude Code loads the contract",
}


def main():
    args = sys.argv[1:]
    skip_claude_md = "--no-claude-md" in args
    args = [a for a in args if a != "--no-claude-md"]
    if len(args) != 1:
        print("usage: wire_hooks.py <target-repo-dir> [--no-claude-md]", file=sys.stderr)
        sys.exit(2)
    target = os.path.abspath(args[0])
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
    if not skip_claude_md:
        print(CLAUDE_MD_MESSAGES[wire_claude_md(target)])


if __name__ == "__main__":
    main()
