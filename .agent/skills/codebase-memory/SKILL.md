---
name: codebase-memory
description: Build and query a local knowledge graph of this repository so structural questions are answered from an index instead of by reading files. Trigger when starting work in an unfamiliar repo, when asked where something is defined, what calls what, what a change would break, what the HTTP surface is, or whether a symbol exists; when the index is missing or stale; and before any multi-file change. Do NOT trigger for single-file edits inside a file already open, or for questions with no repo component.
---

# Skill: codebase-memory

A repository index that costs one build and pays for itself on every question
after. Entirely local: standard-library Python, no network, no daemon, no
install, no MCP server. Reads source, writes only `.agent/memory/`.

## When to use this

Use it when the question is **structural** — where, what calls, what breaks,
what exists. Do not use it to read a file you already have open.

| Situation | Do this |
|---|---|
| First turn in this repo | `verify`, then `build` if needed, then read the map |
| "Where is X?" | `def X` or `search '<regex>'` |
| "What breaks if I change X?" | `callers X`, then `impact <path>` |
| "How does this module fit?" | Read `modules/<slug>.md` |
| "What endpoints exist?" | `routes` |
| Before a multi-file edit | `impact` on every file you plan to touch |
| After a big refactor | rebuild |
| "Is this codebase growing/shrinking, where?" | `drift` (needs 2+ builds logged) |

## Commands

```bash
# Build or refresh (writes only .agent/memory/)
python .agent/skills/codebase-memory/index.py build

# Is the index usable?
python .agent/skills/codebase-memory/index.py verify

# Query (read-only, ~0.1s)
python .agent/skills/codebase-memory/query.py arch
python .agent/skills/codebase-memory/query.py def <Name> [--fuzzy]
python .agent/skills/codebase-memory/query.py callers <Name>
python .agent/skills/codebase-memory/query.py callees <path>
python .agent/skills/codebase-memory/query.py search '<regex>' [--kind class|function|method|type|interface] [--module <prefix>]
python .agent/skills/codebase-memory/query.py file <path>
python .agent/skills/codebase-memory/query.py importers <module-or-name>
python .agent/skills/codebase-memory/query.py routes [prefix]
python .agent/skills/codebase-memory/query.py impact <path>
python .agent/skills/codebase-memory/query.py changed [--base <ref>]
python .agent/skills/codebase-memory/query.py coverage <path>...
python .agent/skills/codebase-memory/query.py orphans
python .agent/skills/codebase-memory/query.py stats
python .agent/skills/codebase-memory/query.py drift [--last N]
```

Global flags: `--root <dir>` `--limit N` `--json`.
On Windows use `py` or `python` — both scripts are pure stdlib, 3.8+.

## Build options

| Flag | Default | Use |
|---|---|---|
| `--calls auto\|on\|off` | `auto` | `off` for a fast structure-only pass on a huge repo; `auto` disables call edges above 25k parsed files |
| `--max-bytes N` | 1,500,000 | Lower it if the repo has huge generated sources |
| `--max-files N` | 200,000 | Safety cap; the build tells you if it trips |
| `--root <dir>` | `.` | Index a subdirectory instead of the whole monorepo |

Monorepo tactic: index the whole tree once for the map, and rebuild with
`--root packages/<the-one-you-are-in>` when you need dense detail in one place.

## Scoping what gets indexed

Three layers, in order: a hard deny-list built into the indexer
(`node_modules`, `dist`, `target`, `.git`, caches, binaries, lockfiles,
minified and generated files) → `.gitignore` via `git ls-files` → `.agentignore`
in the repo root, gitignore-style, for anything else you want out.

```
# .agentignore
docs/legacy/**
**/fixtures/**
generated/
```

Secrets are excluded structurally, not heuristically: `.env*`, `*.pem`, `*.key`,
keystores, `*.tfstate`, `kubeconfig*`, and anything matching `*secret*` or
`*credential*` are never opened. The indexer writes paths, symbol names, and
one-line signatures — never file bodies — and drops any extracted string that
looks like a credential.

## What the artifacts are

* `CODEBASE_MAP.md` — the root map. Stack, entry points, HTTP surface, module
  table, most-called symbols, and an explicit coverage section. ~1–2k tokens
  even on a large repo. Read it every session.
* `modules/<slug>.md` — one shard per module: its files, its symbols with
  `path:line`, its routes. Read on demand, never all of them.
* `graph/{files,symbols,edges}.jsonl` + `manifest.json` — the machine index.
  **Never read these into context.** Query them.
* `history/drift-log.jsonl` — one compact, derived-stats-only line appended
  on every `build` (files/symbols/LOC totals, LOC by language and by
  module — never file bodies). What `drift` reads. Never read directly;
  query it.

A module is the nearest ancestor directory containing a package manifest
(`package.json`, `go.mod`, `pyproject.toml`, `Cargo.toml`, `pom.xml`, `*.csproj`
…), falling back to the first two path segments.

Output is sorted and deterministic, so committing `.agent/memory/` produces
clean diffs and lets a team share one map. Gitignoring it is equally fine.

## Accuracy contract — read this before trusting a result

Symbols come from language-aware pattern matching over ~40 languages, not from a
compiler front end or a language server. Consequences you must respect:

* **Present means present.** A recorded symbol at `path:line` is real. Cite it.
* **Absent does not mean absent.** Dynamic dispatch, reflection, DI containers,
  macros, metaprogramming, code generation, and calls built from strings are
  invisible. So are unparsed files.
* **Call edges are deliberately incomplete.** An edge is recorded only when a
  called name resolves to exactly one definition in the whole repo. Ambiguous
  names are counted and discarded rather than guessed — the map reports how
  many. This trades recall for precision on purpose: a recorded caller is a real
  caller.
* **`orphans` is a lead list.** Exported APIs, entry points, framework hooks and
  cross-language callers all look identical to dead code here.

Before any negative claim ("there is no X", "nothing calls Y", "this is unused"):
run `coverage` on the paths that would contain it, grep those paths directly,
and state which paths you covered. A clean result means *no recorded gap*, never
*proven complete*.

## Rebuild triggers

Rebuild after: a merge or rebase that moved many files, a rename or module move,
adding a package, or ~20+ files changed since the last build. `verify` flags an
index older than two weeks or sitting on more than 40 uncommitted changes.
Rebuilding is idempotent and cheap; stale shards from removed modules are pruned
automatically.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `no index found` | Run `index.py build` from the repo root |
| `STALE: schema N` | Indexer was upgraded — rebuild |
| Files missing from the map | They are gitignored, in `.agentignore`, binary, generated, or over `--max-bytes`. Check with `coverage <path>` |
| Symbol count looks low for a language | That language has coarse patterns; the file is still indexed as a file node. Grep it directly and note that in your answer |
| `def` finds nothing | Try `--fuzzy`, then `search '<partial>'`, then grep the module's paths |
| Build is slow on a monorepo | `--calls off` for structure, or `--root <subpackage>` |
| Everything looks unparsed | The repo is not a git checkout and the walk hit the deny-list; check `discovery` in `stats` |

## Cost model

Roughly 300k LOC indexes in ~2s single-threaded and produces a ~1.5k-token map
plus ~0.1s queries. The map plus two or three queries answers most structural
questions for a few hundred tokens, against tens of thousands for the equivalent
file-by-file exploration. The build is the only expensive step, and it happens
once.
