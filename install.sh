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
for arg in "${@:2}"; do
  [ "$arg" = "--force" ] && FORCE=1
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
  ".github/copilot-instructions.md"
  ".agent/skills/codebase-memory/SKILL.md"
  ".agent/skills/codebase-memory/index.py"
  ".agent/skills/codebase-memory/query.py"
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
echo
echo "Next:"
echo "  cd \"$TARGET\""
echo "  printf '.agent/work/\\n' >> .gitignore"
echo "  python .agent/skills/codebase-memory/index.py build"
echo
echo "Add '.agent/memory/' to .gitignore too if each developer should build"
echo "their own index instead of sharing one committed map."
