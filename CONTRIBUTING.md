# Contributing

Thanks for looking. This kit has a few hard constraints that shape every
change — read them first, because a PR that breaks one will not merge no
matter how good it is otherwise.

## The constraints

1. **Zero runtime dependencies.** Python 3.8+ standard library only. A
   developer on a locked-down laptop must be able to copy these files in and
   have them work. (Build-time tooling for the wheel is fine.)
2. **No network calls** except the ones a human explicitly approves
   (`tool-provisioning` installs, `sync-org-registry`). No telemetry, ever.
3. **No writes outside `.agent/`** in a target repo — plus `.gitignore`,
   `.mcp.json` and `.claude/settings.json` only when the user asked for it.
4. **Measured, not asserted.** A change that claims to make recall or the
   index better comes with a number from `evals/` or `benchmarks/`, and
   publishes what still fails. A change that makes a number worse says so.
5. **Fail open.** Hooks and the MCP server never break the session they are
   attached to.

## Setup

```bash
git clone https://github.com/sheikharfaz/agent-memory-kit.git
cd agent-memory-kit
python3 -m unittest discover -s tests -v      # no pytest needed
python3 -m agent_memory_kit doctor /path/to/a/project
```

No virtualenv is required to develop. To check the packaged form:

```bash
python3 -m pip install build && python3 -m build
```

## Where things live

| Path | What |
|---|---|
| `AGENTS.md` | The contract every agent reads. Keep it under ~5k tokens. |
| `.agent/skills/<skill>/` | One directory per skill: `SKILL.md` plus stdlib scripts. |
| `.agent/lib/retrieval.py` | Shared tokenizer + BM25. Every consumer must degrade if it is absent. |
| `install.py` | `FILES` is the single list of what gets installed — the shell installers and `amk init` all follow it. |
| `agent_memory_kit/` | The `amk` CLI. |
| `evals/` | Retrieval *quality*. |
| `benchmarks/` | Token *cost*. |

## Good first contributions

- **A symbol pattern for an under-served language.** The tables are at the
  top of `.agent/skills/codebase-memory/index.py`. Add a fixture test in
  `tests/test_codebase_memory_smoke.py`. Prefer missing a symbol to inventing
  one — the agent is told to trust these records.
- **An eval case from real use.** If `session-memory` failed to recall
  something it should have, the *Retrieval miss* issue template collects
  exactly what `evals/datasets/` needs. Real cases fix the eval's biggest
  weakness: we wrote the current dataset ourselves.
- **A `tool-provisioning` registry entry** for a common need.

## A PR checklist

- [ ] Tests for the change, stdlib `unittest`.
- [ ] `python3 -m unittest discover -s tests` green locally.
- [ ] If a query verb, tool, or file changed: `README.md`, the skill's
      `SKILL.md`, `AGENTS.md` §3 and `mcp-bridge` agree with each other.
- [ ] If a new file ships to target repos: added to `FILES` in `install.py`,
      and to `install.sh` / `install.ps1`.
- [ ] `CHANGELOG.md` under `[Unreleased]`, written as what changed and why.
- [ ] Any number you quote is reproducible by the command next to it.

## Reporting a security issue

See [SECURITY.md](SECURITY.md#reporting-a-problem).
