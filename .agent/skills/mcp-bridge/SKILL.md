---
name: mcp-bridge
description: Exposes codebase-memory and session-memory as a live Model Context Protocol (MCP) server, so any MCP-capable host -- Claude Code, Claude Desktop, Cursor, or anything else that speaks MCP -- can call this repo's local index and cross-session recall directly as tools, not just via AGENTS.md conventions or Claude Code's own hooks. Trigger when the developer asks to use this kit from a tool other than Claude Code, wants "live" access to codebase-memory/session-memory instead of reading generated files, or asks how to wire this repo up to an MCP client.
---

# Skill: mcp-bridge

A minimal, stdlib-only MCP server (`server.py`) that turns `codebase-memory`
and `session-memory` into 21 callable tools over the standard MCP stdio
transport. Everything else in this kit reaches an agent through file
conventions (`AGENTS.md`, `CODEBASE_MAP.md`) or Claude Code's own hook
mechanism (`session-memory`'s `SessionStart`/`UserPromptSubmit`/`Stop`).
This skill is the third path: any host that speaks MCP gets the same
capabilities as live, schema-described tool calls, no file-reading
convention required.

## Why this exists

`AGENTS.md` already travels across tools -- it is plain markdown most agents
read directly (Claude Code via an `@AGENTS.md` import in `CLAUDE.md`). But `session-memory`'s cross-session recall only *activates*
automatically inside Claude Code, because it rides Claude Code's specific
hook events. A developer using Cursor, Claude Desktop, or a custom agent
built on the Claude Agent SDK gets none of that unless they read this
kit's scripts and shell out to them by hand. This server removes that gap:
point any MCP client at it and `codebase_*`/`session_*` tools show up in
its tool list immediately, self-described, with no hook wiring at all.

## Starting it

```bash
python3 .agent/skills/mcp-bridge/server.py --root /path/to/repo
```

`--root` is optional -- omitted, it walks up from the current working
directory looking for `.git` or `.agent`, the same rule `session-memory`
uses. A per-call `root` argument (see Tools, below) overrides it, for a
host that manages several repos from one server process.

### Wiring into Claude Code

```bash
python3 .agent/skills/mcp-bridge/wire_mcp.py <target-repo-dir>
```

merges an `agent-memory-kit` entry into `<target-repo-dir>/.mcp.json`
(idempotent -- safe to re-run). Equivalent by hand:

```bash
claude mcp add --transport stdio --scope project agent-memory-kit \
  -- python3 .agent/skills/mcp-bridge/server.py --root .
```

`install.py|.sh|.ps1 --wire-mcp` does this automatically at install time.

### Wiring into another MCP host

Any host that reads a `command`/`args` stdio server definition works the
same way -- point it at
`python3 .agent/skills/mcp-bridge/server.py --root <repo>`. Claude
Desktop's `claude_desktop_config.json` and most other hosts use the same
`mcpServers: {name: {command, args}}` shape `wire_mcp.py` writes.

## Tools

17 `codebase_*` tools mirror `query.py`'s verbs one-for-one (`verify`,
`build`, `arch`, `def`, `callers`, `callees`, `search`, `find`, `file`,
`importers`, `routes`, `impact`, `changed`, `coverage`, `orphans`,
`stats`, `drift`) plus 4 `session_*` tools mirror `memory.py`'s read
verbs (`recall`, `recent`, `stats`) plus one write (`remember`, which
appends a `note` entry). `codebase_find` is the one to reach for when the
model does not already know what a symbol is called -- `codebase_search`
needs a regex that already matches the real name.

Each tool's `description` and `inputSchema` are generated straight from the
same flags the CLI verb takes -- run
`query.py <verb> --help` or read `query.py`'s docstring if a tool's
purpose isn't clear from its MCP description alone.

Every handler is a direct subprocess passthrough to `query.py`/`index.py`/
`memory.py` -- **no logic is duplicated**, so a tool's answer always
matches what the equivalent CLI command prints. This also means the same
accuracy caveats apply: a `codebase_callers` result is unresolved-by-design
for ambiguous call sites, a `session_recall` hit is a lexical lead not a
verified fact -- see `codebase-memory/SKILL.md` and
`session-memory/SKILL.md` for the full accuracy contract each tool
inherits unchanged.

## What is deliberately NOT exposed, and why

- **`tool-provisioning`'s `install`/`uninstall`/`sweep`/`sync-org-registry`.**
  This kit's whole tool-acquisition design is propose-only: `search` and
  `plan` are read-only, and installing anything requires a human to read
  the printed command and run it themselves in chat (`AGENTS.md` §14,
  §8's command policy). Exposing `install` as a raw MCP tool would let any
  model behind any MCP host silently reinstate exactly the auto-installing
  behavior this kit exists to prevent, for hosts that have no
  conversational approval step of their own. Search/plan may be added
  here later; the write verbs will not be, on the same reasoning.
- **`dev-recap`'s `record-recap`/`record-quiz`/`set-familiarity`, and
  `spec-first`'s `scaffold`.** These are judgment-heavy, conversational
  flows -- a recap needs an actual diff to summarize, a quiz needs
  actual back-and-forth, a PRD scaffold needs a real requirements
  conversation first. They stay skills an agent runs deliberately in
  context, not tools a model can invoke as a one-shot IPC call.

## What writes, and what never does

Exactly two tools write anything: `codebase_build` (only
`.agent/memory/graph/` and `CODEBASE_MAP.md` -- the kit's own generated
cache, identical to what `index.py build` already writes) and
`session_remember` (appends one `note`-kind entry to
`.agent/memory/session/entries.jsonl`, identical to `memory.py record`).
Every other tool is read-only. No tool, ever, makes a network call,
installs a package, or writes outside `.agent/memory/`.

## Failure behaviour

- A missing/unknown tool name is a JSON-RPC protocol error (`-32602`), not
  a tool result -- matches the MCP spec's own example for this case.
- A missing required argument (e.g. `codebase_def` without `name`) comes
  back as a tool result with `isError: true` and an explanatory message,
  not a crash or a protocol error -- the client can show this to the
  model and let it retry with corrected arguments.
- A malformed line on stdin, or any notification, is silently ignored --
  matches the fail-open posture every other hook/script in this kit
  already follows. The server never exits on bad input; only a closed
  stdin (the client disconnecting) ends the process.

## Compliance controls

`AGENT_MEMORY_KIT_DISABLE_SESSION_MEMORY=1` still silences every
`session_*` tool's underlying `memory.py` calls the same way it silences
the hooks -- the env var is read by `memory.py` itself, not by this
bridge, so the effect is identical however the call arrives.
