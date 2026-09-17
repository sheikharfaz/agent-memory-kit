#!/usr/bin/env python3
"""
Merge an agent-memory-kit entry into a target repo's project-scoped
.mcp.json (the format Claude Code, and most other MCP-capable hosts that
support project config, read: {"mcpServers": {"<name>": {...}}}).
Idempotent -- running it twice does not duplicate or reset the entry.
Only ever touches the "agent-memory-kit" key; every other server already
configured in .mcp.json is left exactly as it was.

  python3 wire_mcp.py <target-repo-dir>

Called by install.sh/install.ps1/install.py only when --wire-mcp is passed
explicitly. Never run automatically.
"""

import json
import os
import shutil
import sys

SERVER_NAME = "agent-memory-kit"


def portable_python():
    """A bare interpreter name resolved via PATH, not an absolute path.
    Project-scope .mcp.json is meant to be committed and shared, so one
    developer's venv path (or an ephemeral `uvx` environment that can be
    garbage-collected) must not end up in it. The server is stdlib-only, so
    any 3.8+ interpreter on PATH runs it."""
    for name in ("python3", "python"):
        if shutil.which(name):
            return name
    return sys.executable


def main():
    if len(sys.argv) != 2:
        print("usage: wire_mcp.py <target-repo-dir>", file=sys.stderr)
        sys.exit(2)
    target = os.path.abspath(sys.argv[1])
    mcp_path = os.path.join(target, ".mcp.json")

    config = {}
    if os.path.exists(mcp_path):
        with open(mcp_path, encoding="utf-8") as fh:
            config = json.load(fh)

    servers = config.setdefault("mcpServers", {})
    is_new = SERVER_NAME not in servers
    command = portable_python() if is_new else servers[SERVER_NAME].get("command", portable_python())
    servers[SERVER_NAME] = {
        "type": "stdio",
        "command": command,
        "args": [".agent/skills/mcp-bridge/server.py", "--root", "."],
    }

    with open(mcp_path, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)
        fh.write("\n")

    if is_new:
        print("wired %s into %s" % (SERVER_NAME, mcp_path))
    else:
        print("%s already wired in %s, args refreshed" % (SERVER_NAME, mcp_path))


if __name__ == "__main__":
    main()
