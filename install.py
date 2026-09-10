#!/usr/bin/env python3
"""
agent-memory-kit installer -- cross-platform, stdlib-only.

  python3 install.py <target-repo-dir> [--force] [--wire-hooks]

Why this exists alongside install.sh/install.ps1: some corporate Windows
images set PowerShell's execution policy to Restricted, which blocks
install.ps1 from running at all -- and that policy is itself something an
end user without admin rights cannot change. `python3 install.py` needs no
script-execution policy, only an interpreter that's already a prerequisite
for codebase-memory. Prefer this entry point on a locked-down machine.

Guarantees, same as the shell installers: local file copy only, no network,
no package installs, no writes outside the target directory (and, with
--wire-hooks, a merge into <target>/.claude/settings.json -- see
wire_hooks.py). Existing files are never overwritten unless --force.
"""

import argparse
import os
import shutil
import subprocess
import sys

SRC = os.path.dirname(os.path.abspath(__file__))

FILES = [
    "AGENTS.md",
    "SETUP.md",
    "SECURITY.md",
    ".github/copilot-instructions.md",
    ".agent/skills/codebase-memory/SKILL.md",
    ".agent/skills/codebase-memory/index.py",
    ".agent/skills/codebase-memory/query.py",
    ".agent/skills/session-memory/SKILL.md",
    ".agent/skills/session-memory/memory.py",
    ".agent/skills/session-memory/wire_hooks.py",
    ".agent/skills/session-memory/hooks/_common.py",
    ".agent/skills/session-memory/hooks/session_start.py",
    ".agent/skills/session-memory/hooks/user_prompt_submit.py",
    ".agent/skills/session-memory/hooks/stop.py",
    ".agent/skills/tool-provisioning/SKILL.md",
    ".agent/skills/tool-provisioning/toolkit.py",
    ".agent/skills/tool-provisioning/registry.json",
]


def main():
    p = argparse.ArgumentParser(description="Install agent-memory-kit into a target repo.")
    p.add_argument("target", help="target repository directory")
    p.add_argument("--force", action="store_true", help="overwrite existing files")
    p.add_argument("--wire-hooks", action="store_true",
                    help="also merge session-memory hooks into .claude/settings.json")
    args = p.parse_args()

    target = os.path.abspath(args.target)
    if not os.path.isdir(target):
        sys.stderr.write("error: '%s' is not a directory\n" % args.target)
        sys.exit(2)
    if target == SRC:
        sys.stderr.write("error: target is the kit itself; pass your project directory\n")
        sys.exit(2)

    copied, skipped = 0, 0
    for rel in FILES:
        rel = rel.replace("/", os.sep)
        src = os.path.join(SRC, rel)
        dest = os.path.join(target, rel)
        if os.path.exists(dest) and not args.force:
            print("  skip     %s (exists; use --force to overwrite)" % rel)
            skipped += 1
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src, dest)
        print("  install  %s" % rel)
        copied += 1

    print()
    print("%d file(s) installed, %d skipped." % (copied, skipped))

    if args.wire_hooks:
        print()
        print("Wiring session-memory hooks into %s ..." % os.path.join(target, ".claude", "settings.json"))
        wire_script = os.path.join(SRC, ".agent", "skills", "session-memory", "wire_hooks.py")
        subprocess.run([sys.executable, wire_script, target], check=False)

    print()
    print("Next:")
    print("  cd %s" % target)
    print("  printf '.agent/work/\\n.agent/memory/session/\\n' >> .gitignore")
    print("  python .agent/skills/codebase-memory/index.py build")
    print()
    print("Add '.agent/memory/' to .gitignore too if each developer should build")
    print("their own index instead of sharing one committed map.")
    print()
    print("Blocked on outbound PyPI/npm from tool-provisioning? Run:")
    print("  python .agent/skills/tool-provisioning/toolkit.py doctor")
    if not args.wire_hooks:
        print()
        print("session-memory ships two more features, both opt-in:")
        print("  - re-run with --wire-hooks to register the SessionStart / UserPromptSubmit /")
        print("    Stop hooks in .claude/settings.json (Claude Code only; see SETUP.md)")
        print("  - tool-provisioning: python .agent/skills/tool-provisioning/toolkit.py search '<need>'")


if __name__ == "__main__":
    main()
