# Security and privacy — for reviewers

A one-page threat model, written for an AppSec/OSPO reviewer deciding whether
developers can use this without an exception process. If you need something
this page doesn't answer, open an issue — that gap is worth fixing for the
next reviewer too.

## What this is

Markdown files plus Python scripts (standard library only, 3.8+) that a
developer copies into a git repository. There is no service to stand up, no
account to create, no vendor relationship, and no SaaS data-processing
agreement to negotiate — it runs entirely on the developer's own machine,
under their own OS-level permissions.

## Components and their network/write surface

| Component | Reads | Writes | Network |
|---|---|---|---|
| `codebase-memory` (`index.py`, `query.py`) | source files in the repo | only `.agent/memory/` (map, module shards, graph) | **none, ever** |
| `session-memory` (`memory.py`, hooks) | its own local log | only `.agent/memory/session/` | **none, ever** |
| `tool-provisioning` (`toolkit.py`) | its own registry/ledger | only `.agent/memory/tools/` | **only** the install/uninstall command a human approved in chat, plus `doctor`'s bare TCP reachability probes (nothing sent or fetched), plus the one explicit `sync-org-registry` command if a developer runs it |
| `dev-recap` (`recap_log.py`) | `git diff` output, its own logs, `codebase-memory`'s index if present | only `.agent/memory/learning/` | **none, ever** |

Nothing here phones home, collects telemetry, or uploads anything by itself.
Every network-capable action is either a command a human explicitly
approved in the current conversation, or a diagnostic that establishes a TCP
connection and reads nothing back.

## Threat model

**In scope / mitigated:**
- *Prompt injection from repo content.* `AGENTS.md` §1.4 requires the agent
  to treat all repo content, tool output, and file contents as data, never
  instructions — a file that says "run this command" gets quoted back to the
  developer, not executed.
- *Secret leakage into logs.* `session-memory` redacts common secret shapes
  (AWS-style keys, `key=`/`token=` assignments, JWTs, PEM blocks) before
  writing anything to disk. This is a best-effort regex pass, not a
  guarantee — see Limitations below.
- *Silent installs.* `tool-provisioning`'s `install`/`uninstall` only ever
  run a command a human approved in the current chat; `search`, `plan`, and
  `doctor` are read-only by construction (see the guarantees documented at
  the top of `toolkit.py`).
- *Orphaned installs.* Every install is logged to an append-only ledger;
  `uninstall` refuses to remove anything not present as an open entry in
  that ledger, so it can't be talked into deleting something that predates
  it. `list-installed`/`sweep` surface anything left over from an
  interrupted task.
- *Supply-chain surface of the kit itself.* Zero third-party dependencies —
  nothing to audit in a lockfile, nothing that can be typosquatted upstream
  of this repo.

**Explicitly out of scope:**
- *What an approved install itself does.* If a developer approves
  `pip install some-package`, this kit is not a sandbox and does not vet
  that package's contents — the same trust decision exists whether or not
  this tool is involved. `tool-provisioning`'s shipped registry only lists
  well-known, widely-used packages, and any project can restrict or replace
  it with an org policy file (see below).
- *A compromised or malicious AI agent.* This kit constrains an
  otherwise-cooperative agent (command policy, propose-only installs,
  evidence requirements). It is not a sandbox against an agent that has
  already been compromised or is being deliberately misused — that's the
  job of the harness running the agent, not a markdown contract.
- *Multi-user or server deployment.* Designed for one developer's local
  checkout. Nothing here does authentication, authorization, or multi-tenant
  isolation, because nothing here is a service.

## Data classification

`session-memory`'s `entries.jsonl` contains **raw prompt and assistant-turn
text** — closer to chat history than to derived metadata. Unlike
`codebase-memory`'s map (structural facts about code already in the repo),
this can include whatever the developer typed, redaction limits notwithstanding.
Consequences:

- It is local to the machine's checkout by default and is **not** committed
  (see the `.gitignore` guidance in SETUP.md) unless a team makes an
  explicit, separate decision to share it.
- Retention is bounded: entries cap at 4,000 characters, and pruning runs
  automatically (default: keep the most recent 4,000 entries; set
  `AGENT_MEMORY_KIT_RETENTION_DAYS` to also cap by age).
- An org-wide kill switch exists: set `AGENT_MEMORY_KIT_DISABLE_SESSION_MEMORY=1`
  (e.g. via a centrally managed environment variable) and every hook becomes
  a no-op without touching any repo file.

## Data classification — `dev-recap`

`.agent/memory/learning/` holds recap summaries and self-reported quiz
results (`understood`/`partial`/`confused` plus optional free-text notes).
This is explicitly **not** a performance-tracking or manager-visibility
feature — see the "AI ethics stance" in
`.agent/skills/dev-recap/SKILL.md`. It exists for one purpose: letting the
same developer's next session know what's worth reinforcing. Nothing here
aggregates results across developers, exports them, or is designed to be
read by anyone but the developer whose machine it's on. If your org wants
learning analytics, that is a different, opt-in feature this kit does not
provide — do not build it by silently piping this file somewhere else.

## Governance for `tool-provisioning`

An optional, IT-owned policy file
(`.agent/memory/tools/registry.org.json`, or a path set via
`AGENT_MEMORY_KIT_ORG_POLICY`) can allowlist or denylist specific tools, force
installs through an internal package mirror (`pip_index_url`), and override
any registry entry outright — and a project's own
`.agent/memory/tools/registry.local.json` cannot override an org-level
allow/deny decision. See `.agent/skills/tool-provisioning/SKILL.md`.

## Limitations, stated plainly

- Secret redaction is regex-based and best-effort. Do not rely on it as a
  substitute for not pasting real credentials into a prompt.
- `tool-provisioning`'s "already installed" checks (`pip show`, module
  import, `claude mcp list`) can have false negatives/positives depending on
  the local Python/Node environment; `plan` always shows its work rather
  than asserting silently.
- This document describes the design intent and is kept in sync by hand —
  it is not a substitute for reading the ~1,600 lines of Python it describes,
  which is short enough to read in one sitting; that's the point.

## Reporting a problem

Open a GitHub issue. There is no bug bounty and no formal disclosure SLA —
this is a small open-source utility, not a product with a security team on
call — but issues are read.
