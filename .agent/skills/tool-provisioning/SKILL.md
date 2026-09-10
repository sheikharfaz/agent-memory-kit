---
name: tool-provisioning
description: Look up whether a task needs a tool/package/MCP server that isn't already available, and if so print the exact install and uninstall commands for developer approval -- never install anything without that approval in this chat. Trigger when a task needs a capability not already present (reading a PDF/xlsx/image, browser automation, an MCP server) and you are about to reach for a library that might not be installed. Do NOT trigger to install anything the developer has not approved in the current conversation, and do NOT trigger for capabilities already available in the environment.
---

# Skill: tool-provisioning

A curated, local registry of task -> tool mappings, plus a ledger so nothing
this mechanism installs is ever installed silently or left behind
uninstalled. **Propose-only**: `search` and `plan` never run an install or
uninstall command, only print what would run. Nothing gets executed until a
human has approved it in the current chat, which matches this repo's own
command policy in `AGENTS.md` §8 ("ask first" before installing anything) --
this skill is that policy made concrete and auditable, not an exception to it.

## Workflow

1. **search** for what the task needs, by free text:
   ```bash
   python .agent/skills/tool-provisioning/toolkit.py search "read a pdf"
   ```
   Prints candidate registry entries with their current installed status.
2. **plan** the one you want, by name. This is read-only -- it runs the
   entry's *check*, never its install:
   ```bash
   python .agent/skills/tool-provisioning/toolkit.py plan pdf-text
   ```
   * Already installed → says so, stop here, just use it.
   * No automatic install exists (OS-specific, e.g. a CLI tool) → says so,
     hand it to the developer instead of trying to script it.
   * Not installed → prints the **exact** install command, the **exact**
     uninstall command, and the risk note. Nothing has run yet.
3. **Tell the developer what `plan` printed and wait for an explicit yes** in
   this conversation. This is a real approval gate, the same as any other
   install per the command policy -- do not treat a task description as
   pre-approval for whatever the registry happens to suggest.
4. **install**, only after that yes:
   ```bash
   python .agent/skills/tool-provisioning/toolkit.py install pdf-text
   ```
   Runs the install command, verifies it, and logs it to
   `.agent/memory/tools/tool-ledger.jsonl`.
5. Do the actual task.
6. **uninstall** what you installed, before finishing:
   ```bash
   python .agent/skills/tool-provisioning/toolkit.py uninstall pdf-text
   ```
   Refuses to act on anything the ledger doesn't say this mechanism
   installed -- it will never remove something that was already there
   before step 4. `sweep` uninstalls everything still open in the ledger, for
   end-of-task cleanup if several tools were provisioned in one go.

If a session ends before step 6 runs, nothing is lost: `list-installed` shows
every entry still open, so a later session (or the developer) can finish the
cleanup:

```bash
python .agent/skills/tool-provisioning/toolkit.py list-installed
python .agent/skills/tool-provisioning/toolkit.py sweep
```

## The registry

`.agent/skills/tool-provisioning/registry.json` ships a small, curated set of
common needs (PDF/xlsx/YAML/image/HTML/CSV libraries, one browser-automation
example, one MCP-server example, one manual/OS-specific example). Extend it
per-project without touching the shipped file by adding
`.agent/memory/tools/registry.local.json` (same array-of-entries shape) --
entries with a matching `name` override the shipped one; new names are added.

Each entry:

```json
{
  "name": "pdf-text",
  "kind": "pip",
  "match": ["pdf", "extract pdf", "read pdf"],
  "check": {"type": "python_import", "module": "pypdf"},
  "install_cmd": ["pip", "install", "--user", "pypdf"],
  "uninstall_cmd": ["pip", "uninstall", "-y", "pypdf"],
  "risk": "Installs the pure-Python 'pypdf' package from PyPI into the user site-packages."
}
```

`check.type` is one of `python_import` (runs `import <module>`),
`subprocess` (runs `check.cmd`, success = exit 0), or `mcp` (checks
`claude mcp list` for `check.name`). An entry with `install_cmd: null` is
`kind: "manual"` -- always hand those to the developer instead of trying to
automate them; there usually isn't a safe cross-platform command.

## Why the ledger, not just "install then uninstall"

A task can fail partway through, or a session can end before cleanup. The
ledger (`.agent/memory/tools/tool-ledger.jsonl`) is an append-only log of
every install/uninstall event this tool has run, keyed by name. `uninstall`
reads the ledger for the **recorded** uninstall command rather than trusting
the current registry (which may have changed), and refuses outright if the
ledger has no open install for that name -- so it can never be talked into
removing a package the developer had already installed themselves.

## What this is not

Not a package manager, not a sandbox, not a way around the "ask first"
command policy. It does not decide on its own that installing something is
fine because the task seems to need it -- the approval step is load-bearing,
not decorative. It also does not know about every tool that might ever be
needed; an unmatched `search` is not evidence nothing exists, just that this
registry doesn't have it yet -- add an entry to `registry.local.json`, or
fall back to asking the developer directly the way you would for anything
else not on the command-policy allow list.
