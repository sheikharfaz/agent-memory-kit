# Setup — agent memory kit

Drop-in for any repository. No install, no service, no MCP server, no network.
Requires Python 3.8+ and, ideally, git.

## 1. Copy these into the repo root

```
AGENTS.md                                  the contract, read every session
SECURITY.md                                threat model, for your AppSec/OSPO reviewer
.github/copilot-instructions.md            Copilot entry point → points at AGENTS.md
.agent/skills/codebase-memory/SKILL.md     the skill definition
.agent/skills/codebase-memory/index.py     builder
.agent/skills/codebase-memory/query.py     read-only query CLI
```

Two more skills ship in the same repo, both opt-in — copy them too if you
want cross-session memory and/or propose-only tool provisioning (`install.sh`
copies everything, including these, by default):

```
.agent/skills/session-memory/SKILL.md          the skill definition
.agent/skills/session-memory/memory.py         record/recall engine + CLI
.agent/skills/session-memory/wire_hooks.py     merges hooks into .claude/settings.json
.agent/skills/session-memory/hooks/*.py        the three Claude Code hooks
.agent/skills/tool-provisioning/SKILL.md       the skill definition
.agent/skills/tool-provisioning/toolkit.py     search/plan/install/uninstall CLI
.agent/skills/tool-provisioning/registry.json  curated tool registry
.agent/skills/dev-recap/SKILL.md               the skill definition
.agent/skills/dev-recap/recap_log.py           recap/quiz/gap-scan/familiarity CLI
.agent/skills/spec-first/SKILL.md               the skill definition
.agent/skills/spec-first/spec_first.py         PRD/TRD scaffold + check CLI
```

## 2. Build the index once

```bash
python .agent/skills/codebase-memory/index.py build
```

Creates `.agent/memory/` with `CODEBASE_MAP.md`, `modules/*.md`, and
`graph/*.jsonl`. Nothing outside `.agent/memory/` is written, ever.

## 3. Decide whether to commit the memory

**Commit it** so the whole team and every agent session shares one map (output is
sorted and deterministic, so diffs stay clean):

```gitignore
.agent/work/
```

**Or keep it local** so each developer builds their own:

```gitignore
.agent/memory/
.agent/work/
```

Either way, add `.agentignore` in the repo root for paths you want kept out of
the index:

```
docs/legacy/**
**/__fixtures__/**
generated/
```

## 4. Wire it into Copilot

VS Code Copilot reads `.github/copilot-instructions.md` automatically, and
recent versions also read `AGENTS.md`. The Copilot file is a thin pointer, so
either path works and you are not maintaining two contracts.

If you already run RPI-style chat modes (`research`, `plan`, `implement`),
they compose directly — `AGENTS.md` §5 defines the same shape, now with a
PRD step before Research and a TRD-quality bar on the Plan artifact (see
`.agent/skills/spec-first/`), and names the artifacts to write:

```
.agent/work/<task-slug>/PRD.md
.agent/work/<task-slug>/research.md
.agent/work/<task-slug>/TRD.md
.agent/work/<task-slug>/progress.md
```

Your research mode's job becomes much cheaper: instead of exploring blind, it
starts from `CODEBASE_MAP.md` and `query.py`, and its output is a citation-dense
research doc rather than a wall of pasted source.

To make the skill fire reliably, add one line to your research mode prompt:

> Before exploring, run `python .agent/skills/codebase-memory/index.py verify`
> and read `.agent/memory/CODEBASE_MAP.md`. Answer structural questions with
> `.agent/skills/codebase-memory/query.py` before reading any file.

## 5. Keep it fresh

```bash
python .agent/skills/codebase-memory/index.py verify   # cheap staleness check
python .agent/skills/codebase-memory/index.py build    # rebuild, idempotent
```

Worth adding to a `post-merge` git hook or a `make index` target on an active
repo. It is a full rebuild every time — simpler and safer than incremental, and
fast enough that incremental would not earn its complexity.

## 6. Optional: wire up session-memory's hooks

Without this step, `session-memory` still works by hand
(`python .agent/skills/session-memory/memory.py recall "..."`), but the
automatic "recall on every prompt" behaviour needs three Claude Code hooks
registered in `.claude/settings.json`.

Easiest — run the installer with the flag, from the kit directory:

```bash
bash /path/to/agent-memory-kit/install.sh /path/to/your/project --wire-hooks
```

This merges (never overwrites) three entries into your project's
`.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {"hooks": [{"type": "command", "command": "python3 .agent/skills/session-memory/hooks/session_start.py"}]}
    ],
    "UserPromptSubmit": [
      {"hooks": [{"type": "command", "command": "python3 .agent/skills/session-memory/hooks/user_prompt_submit.py"}]}
    ],
    "Stop": [
      {"hooks": [{"type": "command", "command": "python3 .agent/skills/session-memory/hooks/stop.py"}]}
    ]
  }
}
```

Or run `python3 .agent/skills/session-memory/wire_hooks.py .` from inside
your project any time later, or paste the JSON above into
`.claude/settings.json` yourself if you'd rather review the diff by hand.
It's idempotent either way — re-running never duplicates an entry.

Windows note: the wired command is `python3 ...`. If your PATH only has
`python` or the `py` launcher (no `python3` shim), edit the three
`"command"` strings in `.claude/settings.json` accordingly — it's plain
JSON, safe to hand-edit.

Add `.agent/memory/session/` to `.gitignore` (raw prompt/turn text, not
derived structural facts like the codebase map — keep it local unless your
team has explicitly decided to share it):

```gitignore
.agent/memory/session/
```

## 7. Optional: tool-provisioning

Nothing to wire up — it's a CLI the agent (or you) runs on demand:

```bash
python .agent/skills/tool-provisioning/toolkit.py search "read a pdf"
python .agent/skills/tool-provisioning/toolkit.py plan pdf-text
```

`plan` only ever prints commands; `install`/`uninstall` require you to have
approved the exact command in chat first. Extend the registry per-project
without touching the shipped file by adding
`.agent/memory/tools/registry.local.json` (same shape as `registry.json`).

## 8. Optional: dev-recap

Nothing to wire up — it's a protocol the agent follows at the Definition of
Done (`AGENTS.md` §7/§15), backed by a CLI it calls itself:

```bash
python .agent/skills/dev-recap/recap_log.py gaps
python .agent/skills/dev-recap/recap_log.py record-recap --task <slug> --files a.py,b.py --summary "..."
python .agent/skills/dev-recap/recap_log.py due-for-review
```

Nothing here requires the other two extensions, but it mirrors a note into
`session-memory` (if installed) and can cross-reference `codebase-memory`'s
index (if built) — install all three for the full effect. Read
`.agent/skills/dev-recap/SKILL.md`'s "AI ethics stance" section once,
whichever agent/IDE you're using — it explains why the quiz/walkthrough
offer must always stay optional and why results never leave the
developer's own machine.

On first-ever session in a repo (if `session-memory`'s hooks are also wired
up — step 6), the agent is nudged to ask, once, how familiar the developer
already is with *this* project and record it:

```bash
python .agent/skills/dev-recap/recap_log.py set-familiarity --level new|some|veteran
python .agent/skills/dev-recap/recap_log.py get-familiarity
```

Never asked again once it's set. Without the hooks wired up, nothing asks
automatically, but the recap still reads whatever's recorded.

## 9. Optional: spec-first

A PRD before Research, and a TRD in place of a plain `plan.md`, for anything
beyond a one-file, unambiguous fix — see `AGENTS.md` §5 and
`.agent/skills/spec-first/SKILL.md`. Nothing to wire up; scaffold and check
the artifacts as you go:

```bash
python .agent/skills/spec-first/spec_first.py scaffold <task-slug>
python .agent/skills/spec-first/spec_first.py check <task-slug>
python .agent/skills/spec-first/spec_first.py list
```

## Very large repositories

```bash
# structure only, no call edges — fastest
python .agent/skills/codebase-memory/index.py build --calls off

# one package of a monorepo, in depth
python .agent/skills/codebase-memory/index.py build --root packages/checkout
```

Call edges are disabled automatically above 25,000 parsed files. Reference
timing: ~300k LOC in about 2 seconds single-threaded, producing a ~1.5k-token
map.

## What this deliberately is not

Not a language server, not an AST-accurate call graph, not a semantic search
engine. It is a fast, honest, dependency-free structural index whose limits are
written into its own output so the agent quotes them back to you instead of
inventing certainty. If you later want compiler-grade accuracy across 150+
languages with sub-millisecond queries, that is what a real indexer like
`codebase-memory-mcp` gives you — this kit is the zero-dependency, no-MCP
version of the same idea.
