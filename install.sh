#!/usr/bin/env bash
# agent-memory-kit installer
#
#   bash install.sh <target-repo-dir> [--force]
#
# Copies the kit into a target repository. Local file copy only: no network,
# no package installs, no writes outside the target directory. Existing files
# are never overwritten unless --force is passed.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-}"
FORCE=0
WIRE_HOOKS=0
for arg in "${@:2}"; do
  [ "$arg" = "--force" ] && FORCE=1
  [ "$arg" = "--wire-hooks" ] && WIRE_HOOKS=1
done

if [ -z "$TARGET" ]; then
  echo "usage: bash install.sh <target-repo-dir> [--force]" >&2
  exit 2
fi
if [ ! -d "$TARGET" ]; then
  echo "error: '$TARGET' is not a directory" >&2
  exit 2
fi
TARGET="$(cd "$TARGET" && pwd)"
if [ "$TARGET" = "$SRC" ]; then
  echo "error: target is the kit itself; pass your project directory" >&2
  exit 2
fi

FILES=(
  "AGENTS.md"
  "SETUP.md"
  "SECURITY.md"
  ".github/copilot-instructions.md"
  ".agent/skills/codebase-memory/SKILL.md"
  ".agent/skills/codebase-memory/index.py"
  ".agent/skills/codebase-memory/query.py"
  ".agent/skills/session-memory/SKILL.md"
  ".agent/skills/session-memory/memory.py"
  ".agent/skills/session-memory/wire_hooks.py"
  ".agent/skills/session-memory/hooks/_common.py"
  ".agent/skills/session-memory/hooks/session_start.py"
  ".agent/skills/session-memory/hooks/user_prompt_submit.py"
  ".agent/skills/session-memory/hooks/stop.py"
  ".agent/skills/tool-provisioning/SKILL.md"
  ".agent/skills/tool-provisioning/toolkit.py"
  ".agent/skills/tool-provisioning/registry.json"
  ".agent/skills/dev-recap/SKILL.md"
  ".agent/skills/dev-recap/recap_log.py"
)

copied=0
skipped=0
for f in "${FILES[@]}"; do
  dest="$TARGET/$f"
  if [ -e "$dest" ] && [ "$FORCE" -eq 0 ]; then
    echo "  skip     $f (exists; use --force to overwrite)"
    skipped=$((skipped + 1))
    continue
  fi
  mkdir -p "$(dirname "$dest")"
  cp "$SRC/$f" "$dest"
  echo "  install  $f"
  copied=$((copied + 1))
done

echo
echo "$copied file(s) installed, $skipped skipped."

if [ "$WIRE_HOOKS" -eq 1 ]; then
  echo
  echo "Wiring session-memory hooks into $TARGET/.claude/settings.json ..."
  python3 "$SRC/.agent/skills/session-memory/wire_hooks.py" "$TARGET"
fi

echo
echo "Next:"
echo "  cd \"$TARGET\""
echo "  printf '.agent/work/\\n.agent/memory/session/\\n' >> .gitignore"
echo "  python .agent/skills/codebase-memory/index.py build"
echo
echo "Add '.agent/memory/' to .gitignore too if each developer should build"
echo "their own index instead of sharing one committed map."
echo
if [ "$WIRE_HOOKS" -eq 0 ]; then
  echo "session-memory ships two more features, both opt-in:"
  echo "  - re-run with --wire-hooks to register the SessionStart / UserPromptSubmit /"
  echo "    Stop hooks in .claude/settings.json (Claude Code only; see SETUP.md)"
  echo "  - tool-provisioning: python .agent/skills/tool-provisioning/toolkit.py search '<need>'"
fi
