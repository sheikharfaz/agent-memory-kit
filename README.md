# agent-memory-kit

[![CI](https://github.com/sheikharfaz/agent-memory-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/sheikharfaz/agent-memory-kit/actions/workflows/ci.yml)

A drop-in `AGENTS.md` contract plus a local codebase index, for AI coding agents
working in real repositories. Two opt-in extensions add cross-session
continuity and propose-only tool provisioning on top of the same local-files
approach.

No MCP server. No daemon. No binary. No dependencies beyond Python 3.8+ —
including the test suite (`tests/`, stdlib `unittest`). The core kit
(`codebase-memory`) makes no network calls, period. The two extensions below
are opt-in and each documents its own, narrower trade-off: `session-memory`
still makes no network calls; `tool-provisioning` makes none either, except
the install command you explicitly approve (or a `doctor` reachability
probe that fetches nothing, or the one explicit `sync-org-registry` command).

Built with locked-down corporate machines in mind: nothing here needs admin
rights, IT provisioning, or a procurement/security review beyond reading
[SECURITY.md](SECURITY.md) — see that file for the full threat model.

---

## The problem

An agent dropped into an unfamiliar repository explores by grepping and reading
files. On a large codebase that burns tens of thousands of tokens before it has
answered anything, and it still hallucinates paths and symbols because nothing
grounds it.

## The approach

Index the repo once into a local knowledge graph. Render the graph into three
tiers, from cheapest to most expensive:

| Tier | Artifact | Cost | When the agent reads it |
|---|---|---|---|
| Map | `.agent/memory/CODEBASE_MAP.md` | ~1.5k tokens | Every session, once |
| Shard | `.agent/memory/modules/<slug>.md` | ~2–7k tokens | After narrowing to one module |
| Graph | `.agent/memory/graph/*.jsonl` | ~200 tokens per query | Never read — queried via CLI |

Then give the agent a contract (`AGENTS.md`) that makes it climb that ladder from
the top, cite `path:line` for every claim, and verify before declaring anything
done.

Reference numbers from the test suite: 286k LOC indexed in 2.0s single-threaded,
producing a 1,650-token map. Structural queries return in ~0.1s.

---

## Quick start

```bash
git clone https://github.com/sheikharfaz/agent-memory-kit.git
cd /path/to/your/project
bash /path/to/agent-memory-kit/install.sh .
python .agent/skills/codebase-memory/index.py build
```

Add `--wire-hooks` to also register `session-memory`'s Claude Code hooks
(`bash /path/to/agent-memory-kit/install.sh . --wire-hooks`) — optional, and
safe to run later once you've read [SETUP.md](SETUP.md).

Windows PowerShell:

```powershell
git clone https://github.com/<you>/agent-memory-kit.git
cd C:\path\to\your\project
& C:\path\to\agent-memory-kit\install.ps1 .
python .agent\skills\codebase-memory\index.py build
```

On a machine where PowerShell's execution policy is `Restricted` (common on
locked-down corporate images, and not something a non-admin user can
change), use the stdlib-only Python installer instead — same behaviour,
needs no script-execution policy at all:

```bash
python3 /path/to/agent-memory-kit/install.py . --wire-hooks
```

Or copy the files by hand — that is all the installer does:

```
AGENTS.md                                       -> your repo root
SETUP.md                                        -> your repo root
SECURITY.md                                     -> your repo root (kit's threat model, for your AppSec reviewer)
.github/copilot-instructions.md                 -> your repo
.agent/skills/codebase-memory/SKILL.md          -> your repo
.agent/skills/codebase-memory/index.py          -> your repo
.agent/skills/codebase-memory/query.py          -> your repo
.agent/skills/session-memory/                   -> your repo   (opt-in, see below)
.agent/skills/tool-provisioning/                -> your repo   (opt-in, see below)
```

Then add to your project's `.gitignore`:

```gitignore
.agent/work/
.agent/memory/session/   # session-memory's local log -- raw prompt/turn text, keep it local
# .agent/memory/          <- uncomment the codebase map too if each developer should build their own index
```

---

## Query CLI

`python .agent/skills/codebase-memory/query.py <verb>` — read-only, local, ~0.1s.

| Need | Command |
|---|---|
| Orient in an unfamiliar repo | `arch` |
| Where is X defined? | `def X` · `search '<regex>' --kind class` |
| What breaks if I change X? | `callers X` · `impact <path>` |
| What does this file depend on? | `file <path>` · `callees <path>` |
| Who imports this module? | `importers <module>` |
| What HTTP surface exists? | `routes [prefix]` |
| Risk of my current diff | `changed` |
| Is this path even indexed? | `coverage <path>...` |
| Possibly-unused symbols | `orphans` |

All verbs accept `--limit N`, `--json`, and `--root <dir>`.

---

## Extension: session-memory (cross-session continuity, opt-in)

`codebase-memory` knows the *code*. `session-memory` knows the
*conversation* — an append-only local log of prompts and turns, searched by
lexical (TF-IDF) similarity, so a session that starts after an earlier one
ended can recall what that session established.

```bash
python .agent/skills/session-memory/memory.py recall "what we discussed about auth"
python .agent/skills/session-memory/memory.py recent
```

Wire it into Claude Code's `SessionStart` / `UserPromptSubmit` / `Stop` hooks
(`bash install.sh . --wire-hooks`, or by hand — see SETUP.md) and it runs
without being invoked: every prompt is recorded and matched against every
earlier session's entries in this repo, with related hits injected as
context automatically. This is the "sits between the calls" behaviour — the
agent gets relevant history without you or it having to remember it exists.

It is lexical similarity, not a trained embedding model: a hit shares real
vocabulary with your query, not necessarily a paraphrased concept. Recalled
entries get a small, capped ranking boost the more often they prove
relevant (`weight`, bumped on recall) — a frequency heuristic that nudges
toward what keeps mattering, not reinforcement learning in the ML sense, and
never enough to override actual topical similarity. Every write passes
through a best-effort secret redaction pass first, entries are capped and
auto-pruned, and `AGENT_MEMORY_KIT_DISABLE_SESSION_MEMORY=1` is a
one-variable org-wide kill switch if a compliance policy requires one.
Detail:
[`.agent/skills/session-memory/SKILL.md`](.agent/skills/session-memory/SKILL.md).

## Extension: tool-provisioning (propose-only, opt-in)

Detects that a task needs a tool/library/MCP server, and — **only after you
approve it in chat** — installs it, lets the agent use it, then uninstalls
it again. Nothing is ever installed silently.

```bash
python .agent/skills/tool-provisioning/toolkit.py doctor            # read-only: what's reachable here?
python .agent/skills/tool-provisioning/toolkit.py search "read a pdf"
python .agent/skills/tool-provisioning/toolkit.py plan pdf-text     # prints commands, runs nothing
python .agent/skills/tool-provisioning/toolkit.py install pdf-text  # only after you say yes
python .agent/skills/tool-provisioning/toolkit.py uninstall pdf-text
```

Every install is logged to a local ledger, with a best-effort SBOM fragment
(name/version/license via `pip show`); `uninstall` reads its recorded
command back from that ledger and refuses to act on anything not listed
there, so it can never remove a package that was already on your machine
before the kit touched it. `list-installed` / `sweep` recover from a task
that ended before cleanup ran; `export-audit` produces a portable report for
a compliance review. The registry is a small curated JSON file you extend
per-project without touching the shipped copy — and an org can layer a
read-only **policy file** on top (allowlist/denylist specific tools, or
redirect installs through an internal package mirror) that a project's own
registry cannot override; `sync-org-registry` is the one explicit,
developer-run command that pulls it from a URL. `doctor` is a read-only
preflight — is PyPI/npm/your mirror actually reachable from here, what CLIs
exist, what proxy env vars are set — so a developer on a locked-down network
self-diagnoses in seconds instead of opening an IT ticket. Detail:
[`.agent/skills/tool-provisioning/SKILL.md`](.agent/skills/tool-provisioning/SKILL.md).

---

## What the agent contract enforces

`AGENTS.md` is loaded every turn, so it stays under ~4k tokens. It covers:

- **Retrieval ladder** — map → query → shard → targeted grep → line range →
  whole file. Never more than 3 whole files before answering. Never a 1000+ line
  file in full.
- **Evidence rules** — every claim about the repo carries `path:line`. No
  citation means the agent goes and looks.
- **RPI workflow** — Research → Plan → Implement, each writing a durable
  artifact under `.agent/work/<task-slug>/` that survives context compaction.
- **HVE gate** — Hypothesis → Verify → Evidence at every phase boundary.
  Unverified assumptions get labelled, never dropped.
- **Command policy** — an explicit allow / ask-first / never list. `git push`,
  force-push, `reset --hard`, deleting tests to go green, and piping downloads
  into a shell are on the never list under any framing.
- **Prompt-injection stance** — repo content is data, not instructions. A file
  telling the agent to run something gets quoted back to you, not executed.
- **Durable memory** — `NOTES.md` with provenance tags
  (`[verified]` / `[stated]` / `[assumption]`) and ADRs for real decisions.

---

## Accuracy contract

Symbols come from language-aware pattern matching across ~40 languages, not from
a compiler front end or a language server. This is a deliberate trade: zero
dependencies and a 2-second build, in exchange for imperfect recall. The limits
are written into the generated output itself, so the agent quotes them back at
you instead of inventing certainty.

- **Present means present.** A recorded symbol at `path:line` is real.
- **Absent does not mean absent.** Dynamic dispatch, reflection, DI containers,
  macros, metaprogramming, codegen, and string-built calls are invisible.
- **Call edges favour precision over recall.** An edge is recorded only when a
  called name resolves to exactly one definition repo-wide. Ambiguous names are
  counted and discarded rather than guessed, and the count is published in the
  map.
- **`orphans` is a lead list, never a delete list.** Exported APIs, entry points
  and framework hooks look identical to dead code here.

Before any negative claim, `AGENTS.md` requires the agent to run `coverage` on
the relevant paths, grep them directly, and state which paths it covered. A clean
result means *no recorded gap*, never *proven complete*.

---

## Privacy and safety

- No network access in either script. Nothing is uploaded, phoned home, or
  logged off-machine.
- Writes are confined to `.agent/memory/`. Verified by md5-diffing every other
  file in the tree across a build.
- Secrets are excluded structurally, not heuristically: `.env*`, `*.pem`,
  `*.key`, keystores, `*.tfstate`, `kubeconfig*`, and anything matching
  `*secret*` or `*credential*` are never opened.
- Only paths, symbol names, and one-line signatures are written — never file
  bodies. Extracted strings that look like credentials are dropped.
- Three ignore layers: a built-in deny-list (`node_modules`, `dist`, `target`,
  caches, binaries, lockfiles, minified and generated files) → your `.gitignore`
  via `git ls-files` → a `.agentignore` you control.

---

## Large repositories

```bash
# structure only, no call edges — fastest
python .agent/skills/codebase-memory/index.py build --calls off

# one package of a monorepo, in depth
python .agent/skills/codebase-memory/index.py build --root packages/checkout
```

Call edges are disabled automatically above 25,000 parsed files. Builds are full
rather than incremental — simpler, safer, and fast enough that incremental
wouldn't earn its complexity. Output is sorted and deterministic, so committing
`.agent/memory/` gives your team a shared map with clean diffs.

---

## Compatibility

`AGENTS.md` and `codebase-memory` are read by GitHub Copilot (recent VS Code),
Claude Code, Codex, Cursor, Zed, and most agent harnesses.
`.github/copilot-instructions.md` is a thin pointer at the same contract so
Copilot picks it up either way — you maintain one file, not two.

`session-memory`'s automatic behaviour (the hooks) is Claude-Code-specific —
that harness is what defines `SessionStart` / `UserPromptSubmit` / `Stop`
hooks. Its `memory.py` CLI and `tool-provisioning`'s `toolkit.py` are plain
Python and work anywhere; other harnesses just have to invoke them by hand or
via their own hook/skill mechanism instead of getting it for free.

If you already run RPI chat modes, they compose directly: `AGENTS.md` §5 defines
the same three phases and names the artifacts they should write.

---

## What this is not

`codebase-memory` is not a language server, not an AST-accurate call graph,
not semantic search. If you want compiler-grade accuracy across 158 languages
with sub-millisecond queries and a proper knowledge graph, use
[codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp), which is
where several ideas here came from — the tiered agent profiles, the coverage-vs-
completeness distinction, and the layered ignore model. This kit is the
zero-dependency, no-MCP version of the same idea, for people who want a
markdown-and-scripts approach they can read in one sitting and audit in ten
minutes.

`session-memory` is not semantic search either — its TF-IDF recall matches
shared vocabulary, not paraphrased meaning, and it is not reinforcement
learning in the ML sense; see the extension section above. `tool-provisioning`
is not a package manager or a sandbox — it never installs anything without an
explicit yes from a human in the current chat, and it never uninstalls
anything it didn't itself install.

---

## Testing

```bash
python3 -m unittest discover -s tests -v
```

Stdlib `unittest` only — no `pytest`, no test dependencies to install, so
the "zero dependencies" claim holds for development too. Covers
`memory.py`/`toolkit.py` unit-level (tokenizing, redaction, ranking, org
policy, ledger semantics) plus subprocess-level smoke tests that run the
actual installers and hooks the way a real user would. CI
(`.github/workflows/ci.yml`) runs the same suite on Ubuntu/Windows/macOS
across Python 3.8 and 3.12 on every push and PR.

## For security/procurement reviewers

See [SECURITY.md](SECURITY.md) for the full threat model, data-flow table,
and what's explicitly out of scope. Short version: no telemetry, no network
calls except a command you approve, nothing written outside `.agent/memory/`,
zero third-party dependencies.

## Contributing

Useful directions: better symbol patterns for under-served languages (the tables
live at the top of `index.py`), additional query verbs, real-world reports of
what the index misses on your codebase, and additional `tool-provisioning`
registry entries for common needs. Open an issue with the language/tool, a
small reproducer, and what was missing.

## License

MIT. See [LICENSE](LICENSE). Version history: [CHANGELOG.md](CHANGELOG.md).
