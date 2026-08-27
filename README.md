# agent-memory-kit

A drop-in `AGENTS.md` contract plus a local codebase index, for AI coding agents
working in real repositories.

No MCP server. No daemon. No binary. No network calls. No dependencies beyond
Python 3.8+. Two scripts and four markdown files that you copy into any repo.

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

Windows PowerShell:

```powershell
git clone https://github.com/<you>/agent-memory-kit.git
cd C:\path\to\your\project
& C:\path\to\agent-memory-kit\install.ps1 .
python .agent\skills\codebase-memory\index.py build
```

Or copy the files by hand — that is all the installer does:

```
AGENTS.md                                  -> your repo root
SETUP.md                                   -> your repo root
.github/copilot-instructions.md            -> your repo
.agent/skills/codebase-memory/SKILL.md     -> your repo
.agent/skills/codebase-memory/index.py     -> your repo
.agent/skills/codebase-memory/query.py     -> your repo
```

Then add to your project's `.gitignore`:

```gitignore
.agent/work/
# .agent/memory/     <- uncomment if each developer should build their own index
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

`AGENTS.md` is read by GitHub Copilot (recent VS Code), Claude Code, Codex,
Cursor, Zed, and most agent harnesses. `.github/copilot-instructions.md` is a
thin pointer at the same contract so Copilot picks it up either way — you
maintain one file, not two.

If you already run RPI chat modes, they compose directly: `AGENTS.md` §5 defines
the same three phases and names the artifacts they should write.

---

## What this is not

Not a language server, not an AST-accurate call graph, not semantic search. If
you want compiler-grade accuracy across 158 languages with sub-millisecond
queries and a proper knowledge graph, use
[codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp), which is
where several ideas here came from — the tiered agent profiles, the coverage-vs-
completeness distinction, and the layered ignore model. This kit is the
zero-dependency, no-MCP version of the same idea, for people who want a
markdown-and-scripts approach they can read in one sitting and audit in ten
minutes.

---

## Contributing

Useful directions: better symbol patterns for under-served languages (the tables
live at the top of `index.py`), additional query verbs, and real-world reports of
what the index misses on your codebase. Open an issue with the language, a small
reproducer, and what was missed.

## License

MIT. See [LICENSE](LICENSE).
