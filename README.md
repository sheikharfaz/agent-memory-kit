# agent-memory-kit

**Give your AI coding assistant a memory, a spine, and good manners.**

[![CI](https://github.com/sheikharfaz/agent-memory-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/sheikharfaz/agent-memory-kit/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-informational.svg)](https://github.com/sheikharfaz/agent-memory-kit/blob/main/LICENSE)
![Dependencies: zero](https://img.shields.io/badge/dependencies-zero-brightgreen)
![Network calls: none by default](https://img.shields.io/badge/network%20calls-none%20by%20default-brightgreen)
![MCP: supported](https://img.shields.io/badge/MCP-supported-blue)

![agent-memory-kit: local memory, a codebase index, and working discipline for AI coding agents](https://raw.githubusercontent.com/sheikharfaz/agent-memory-kit/main/.github/social-preview.png)

[What it does](#what-is-this-in-plain-english) ·
[Who it's for](#who-its-for) ·
[Requirements](#requirements) ·
[Quick start](#quick-start) ·
[Proof](#proof) ·
[How it compares](#how-it-compares) ·
[Enterprise readiness](#enterprise-readiness) ·
[Security](https://github.com/sheikharfaz/agent-memory-kit/blob/main/SECURITY.md) ·
[Documentation](#documentation)

## What is this, in plain English?

When you use an AI coding assistant on a real project, a few things tend to
go wrong. It re-explores the whole codebase from scratch every time you ask
it something, burning time before it's answered anything. It forgets what
you talked about the moment you close the chat, so you end up re-explaining
yourself constantly. It jumps straight into writing code without checking
what you actually meant — "vibe coding." It installs things on your
computer without asking. And it hands you a finished piece of code that
*it* understands but *you* never really did, which is a problem, because
you're the one who has to maintain it afterwards.

**agent-memory-kit is a handful of files you copy into a code project that
fixes all five of those, at once.** Think of it like handing a brilliant
but forgetful new hire a company handbook, a notebook, and a habit of
checking in before they do anything risky — except the "new hire" is your
AI assistant, and the notebook is a folder on your own machine, not a
server anywhere. Nothing to install as a service, nothing to sign up for,
no data leaving your computer.

Try it in your project — one command, nothing left installed afterwards:

```bash
uvx --from git+https://github.com/sheikharfaz/agent-memory-kit amk init
```

Then `amk doctor` tells you whether it worked. More options in
[Quick start](#quick-start).

**Measured, not asserted** — every number here is reproducible with a
command in this repo:

| | |
|---|---|
| Tokens to answer four "getting oriented" questions in django/django | **167,437 → 4,505** (37x fewer) · [benchmarks](https://github.com/sheikharfaz/agent-memory-kit/blob/main/benchmarks/README.md) |
| Recalling the right past-session note (recall@3) | **0.625 → 0.775**, with 0 queries worse · [evals](https://github.com/sheikharfaz/agent-memory-kit/blob/main/evals/README.md) |
| Symbols missing from Django's index before our own measurement caught it | **349**, including `check_password` — fixed in v0.5.0 · [audit](https://github.com/sheikharfaz/agent-memory-kit/blob/main/benchmarks/symbol_filter_audit.py) |
| Runtime dependencies | **0** |

## Who it's for

- **Developers** who use an AI coding assistant daily and are tired of
  re-explaining the same context every session — or a little worried they
  don't actually understand all the code that's shipped in their name.
- **Employees at large or regulated companies** who want to use an AI
  coding assistant productively but can't install arbitrary software,
  don't have admin rights on their work laptop, and don't want to wait on
  an IT ticket or a security exception just to get started. This kit is
  built specifically so you don't have to ask permission to try it — see
  [Requirements](#requirements) and [Enterprise readiness](#enterprise-readiness)
  below.
- **Engineering leads, IT, and security teams**, especially at companies
  where employees can't freely install software, who want AI-assisted
  coding to be safe, auditable, and not require a procurement process of
  its own.
- **Anyone asking "is it actually safe to let AI write code here"** — this
  kit is built to answer that question honestly; see
  [SECURITY.md](https://github.com/sheikharfaz/agent-memory-kit/blob/main/SECURITY.md) for the full, plain-language case.

## Requirements

| Needs | Notes |
|---|---|
| **Python 3.8 or newer** | The only hard requirement. Every script is standard-library only — nothing to `pip install` for the core kit. |
| **git** *(recommended, not required)* | Used to honour `.gitignore` and to power diff-based features (`query.py changed`, `dev-recap`'s `gaps`). Without it, indexing still works via a plain filesystem walk — you just lose those git-aware features. |
| **Any OS** | macOS, Linux, or Windows. On Windows, use `install.py` (or `py`/`python`) if your PowerShell execution policy blocks `.ps1` scripts — see [Quick start](#quick-start). |
| **uv or pipx** *(optional)* | Only for the one-command install. Without them, clone the repo and run `install.py` — same files, no package manager. |
| **Claude Code** *(optional)* | Only needed for `session-memory`'s automatic hooks and the "new-hire" familiarity nudge. Everything else works by hand, or via any harness that reads `AGENTS.md` (GitHub Copilot, Cursor, Codex, Zed, …). |

Nothing else. No API key, no account, no subscription, no server to stand
up, no admin/root access at any point.

## What you get, one line each

| It gives your AI assistant... | So that... |
|---|---|
| A map of your codebase | It answers questions correctly instead of guessing file names that don't exist |
| A memory that survives closing the chat | You stop re-explaining the same thing every new session |
| A habit of asking before installing anything | Nothing gets put on your machine without your say-so |
| A habit of planning before it codes | It writes down *what* it's building and *why*, before touching a single file |
| A habit of explaining its own work | You actually understand what shipped, instead of just trusting it |

If none of that sounds like your problem, the rest of this README goes
deep on how it works. If it does, the [Quick start](#quick-start) below
takes about a minute.

## Enterprise readiness

This kit was designed around one constraint: **a developer at a large or
regulated company should be able to adopt it without asking anyone for
permission.** That shapes everything else about it.

- **No admin rights, ever.** Every install writes to your own user account
  or the project directory — nothing needs `sudo`, nothing needs a
  Windows admin prompt.
- **No new vendor to onboard.** There's no company behind this collecting
  your data, no SaaS product to run past procurement, no data-processing
  agreement to negotiate, no subscription to expense. It's files, on your
  machine, under the MIT license.
- **No telemetry, ever.** Nothing phones home. Nothing is uploaded. The
  only network calls this kit ever makes are an install command you
  explicitly approve, a connectivity check that fetches nothing, and one
  explicit org-policy sync command — see
  [SECURITY.md](https://github.com/sheikharfaz/agent-memory-kit/blob/main/SECURITY.md#components-and-their-networkwrite-surface)
  for the exact list, per skill.
- **An audit trail when you need one.** Every tool install/uninstall is
  logged locally to an append-only ledger with a best-effort software bill
  of materials, exportable as a portable report for a compliance review.
- **Central policy without central control of every keystroke.** An IT or
  security team can drop a single read-only policy file that allowlists or
  denylists specific tools, or routes installs through an internal package
  mirror — and no individual project can override that policy.
- **A one-sitting security review.** [SECURITY.md](https://github.com/sheikharfaz/agent-memory-kit/blob/main/SECURITY.md) is short
  enough to read end to end in about ten minutes: exactly what's read,
  what's written, and what (if anything) ever leaves the machine.

|  | This kit | A typical hosted AI-memory / context SaaS |
|---|---|---|
| Your code/prompts leave your machine? | Never | Usually, to the vendor's servers |
| New vendor / procurement review needed? | No | Yes |
| Needs admin rights to install? | No | Often (agents, browser extensions, services) |
| Ongoing cost? | None — MIT licensed | Per-seat or usage-based subscription |
| Can IT set a central policy? | Yes — a local, read-only policy file | Depends on the vendor's admin console |
| Audit trail? | Yes — local, append-only, exportable | Depends on the vendor's logging tier |

---

A drop-in `AGENTS.md` contract, a local codebase index, and five focused
companion skills — cross-session continuity, propose-only tool access, a
PRD/TRD discipline in place of vibe coding, a closing recap so the
developer understands what an agent just shipped under their name, and an
MCP bridge for hosts that aren't Claude Code — for AI coding agents working
in real repositories. Install the whole kit, or just the pieces you want.

No daemon. No binary. No dependencies beyond Python 3.8+ — including the
test suite (`tests/`, stdlib `unittest`). `codebase-memory` makes no
network calls, period. Every other skill documents its own, narrower
trade-off: `session-memory`, `dev-recap`, and `spec-first` make no network
calls at all; `tool-provisioning` makes none either, except the install
command you explicitly approve (or a `doctor` reachability probe that
fetches nothing, or the one explicit `sync-org-registry` command);
`mcp-bridge` is a local stdio process this kit starts itself, not a hosted
service — and it's opt-in, like the other three: the rest of the kit works
exactly the same with or without it installed.

See [Enterprise readiness](#enterprise-readiness) above and
[SECURITY.md](https://github.com/sheikharfaz/agent-memory-kit/blob/main/SECURITY.md) for the full threat model.

---

## The problem

An agent dropped into an unfamiliar repository explores by grepping and reading
files. On a large codebase that burns tens of thousands of tokens before it has
answered anything, and it still hallucinates paths and symbols because nothing
grounds it. Left unguided, it also skips straight to code without writing down
what it's building or why, ships a diff the developer never really understood,
and reaches for whatever library seems convenient without asking.

## The approach

Index the repo once into a local knowledge graph. Render the graph into three
tiers, from cheapest to most expensive:

| Tier | Artifact | Cost | When the agent reads it |
|---|---|---|---|
| Map | `.agent/memory/CODEBASE_MAP.md` | ~1.5k tokens | Every session, once |
| Shard | `.agent/memory/modules/<slug>.md` | ~2–7k tokens | After narrowing to one module |
| Graph | `.agent/memory/graph/*.jsonl` | ~200 tokens per query | Never read — queried via CLI |

Then give the agent a contract (`AGENTS.md`) that makes it climb that ladder
from the top, cite `path:line` for every claim, and verify before declaring
anything done.

Five focused skills sit on that foundation, each independently installable,
composing into one lifecycle rather than five separate tools bolted together:

| Stage | Skill | What it gives you |
|---|---|---|
| Every session | `codebase-memory` | The index above — grounded answers, no hallucinated paths |
| Across sessions | `session-memory` | Local recall of past prompts and turns, so a new session picks up where the last one left off |
| Before touching code | `spec-first` | A PRD (what, why) and a TRD (how, and real alternatives rejected) instead of vibe coding |
| When a task needs a tool | `tool-provisioning` | Propose → approve → install → use → uninstall, with a full local audit ledger |
| Closing out | `dev-recap` | A plain-English recap, a gap scan, and an optional quiz so the developer actually understands what shipped |

A sixth skill, `mcp-bridge`, isn't a lifecycle stage — it's an alternate
front door onto `codebase-memory` and `session-memory` for MCP-capable
hosts that aren't Claude Code (Cursor, Claude Desktop, ...). See its own
section below.

Reference numbers from the test suite: 286k LOC indexed in 2.0s single-threaded,
producing a 1,650-token map. Structural queries return in ~0.1s.

## Proof

A reproducible token comparison against two real, public repositories —
[`psf/requests`](https://github.com/psf/requests) and
[`django/django`](https://github.com/django/django) — running the same four
"getting oriented" questions with and without `codebase-memory`:

| Repo | Naive tokens | Kit-assisted tokens | Ratio |
|---|---|---|---|
| psf/requests (37 parsed files) | 85,220 | 1,566 | **54.4x** |
| django/django (2,979 parsed files) | 167,437 | 4,506 | **37.2x** |

```bash
python3 benchmarks/token_comparison.py --repo /path/to/any/repo --spec benchmarks/specs/django.json
```

No LLM calls, nothing hidden — full methodology, the exact grep-and-read
naive baseline it's measured against, honest limitations (the naive
baseline is capped at 6 files read per question, which understates its
true cost — these ratios are a floor, not a ceiling), and raw JSON output:
[`benchmarks/README.md`](https://github.com/sheikharfaz/agent-memory-kit/blob/main/benchmarks/README.md).

### Cheap is the easy half. Is it *correct*?

Token cost is the comfortable number to publish. The harder one is whether
the thing recalled is the thing you wanted — so that gets measured too, over
a shipped dataset, with the failures printed:

| Retrieval method | recall@1 | recall@3 | MRR | queries with no hit |
|---|---|---|---|---|
| v0.4.0 — plain tokenizer + TF-IDF cosine | 0.450 | 0.625 | 0.588 | 6 / 20 |
| v0.5.0 — code-aware tokenizer + BM25 | **0.675** | **0.775** | **0.787** | **3 / 20** |

```bash
python3 evals/recall_eval.py --scorer tfidf   # the old behaviour
python3 evals/recall_eval.py --scorer bm25    # the new one, same dataset
```

Per query it is 5 better, 15 unchanged, 0 worse. The gain is concentrated
where the old tokenizer was structurally blind: it lowercased before
splitting, so `getUserById` became one opaque term and "where do we look up
a user by id" recalled *nothing*. On that bucket of queries, recall@3 went
from 0.700 to **1.000**.

**Three queries still miss, under both methods, and the harness prints them
every run.** "What did we make faster recently" shares no vocabulary with
the entry recording a p95 drop from 1.8s to 220ms — a human sees it
instantly, lexical retrieval cannot, and no parameter tuning changes that.
Fixing it properly needs embeddings, which would mean a model download and
the end of the zero-dependency property this kit exists for. That trade is
refused on purpose, and the table is how you hold us to saying so.

Methodology, the authoring-bias disclosure, and why these numbers are **not**
comparable to LongMemEval or LOCOMO scores: [`evals/README.md`](https://github.com/sheikharfaz/agent-memory-kit/blob/main/evals/README.md).

### Case study: the same project, built twice

The benchmark above measures *reading* an existing repo. This measures
*building* one, session by session, real commits included — a small URL
shortener service (routes, storage, rate limiting, validation, tests),
built as two separate public repos from the same feature list:

- [`linkshrink-baseline`](https://github.com/sheikharfaz/linkshrink-baseline)
  — same tasks, no kit, no PRD/TRD trail, no local index.
- [`linkshrink-agent-memory-kit`](https://github.com/sheikharfaz/linkshrink-agent-memory-kit)
  — this kit installed from commit one, `AGENTS.md`'s spec-first workflow
  followed throughout.

Both repos' `app/` directories are byte-for-byte identical — same code, same
tests, same outcome. What differs is what it cost to get there, tracked
honestly in each repo's own `SESSION_LOG.md` as the work happened, not
reconstructed after the fact: **≈1,430 tokens kit-assisted versus ≈1,993
without it — 28% lower** — spent re-establishing context across four
sessions of real, incremental feature work. Not the "half" this kit's own
benchmarks show on a larger codebase (see Proof, above) — a project this
small has little map to save on — and both `SESSION_LOG.md` files say so
plainly, with a per-repo, line-by-line accounting of why, and a side-by-side
[`COMPARISON.md`](https://github.com/sheikharfaz/linkshrink-agent-memory-kit/blob/main/COMPARISON.md)
committed to both.

---

## How it compares

There are excellent tools in this space, and some of them beat this kit at
things it does not try to do. Every fact below comes from each project's own
README (checked 2026-09-17).

| | **agent-memory-kit** | [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) | [Serena](https://github.com/oraios/serena) | [Mem0](https://github.com/mem0ai/mem0) |
|---|---|---|---|---|
| **What it is** | Agent contract + local code index + cross-session memory + working-discipline skills | Code knowledge graph served over MCP | Language-server-backed code retrieval **and editing** over MCP | Memory layer for AI applications |
| **Ships as** | ~5,000 lines of stdlib Python, copied into your repo | Native binary (C) | Python tool installed with `uv`, plus language servers | Python library, or a managed platform |
| **Code parsing** | Regex patterns, 31 languages | tree-sitter, 162 languages (LSP type resolution for some) | Language servers, 40+ languages | Not a code index |
| **Runs without an LLM or API key** | Yes | Yes | Tools run locally; your agent's model drives them | No — needs an LLM (OpenAI by default) |
| **Edits code for the agent** | No | Not in its feature list | Yes, at symbol level | Not applicable |
| **Published evaluation** | Token cost and recall quality, both reproducible in-repo | arXiv preprint: 83% answer quality, 10x fewer tokens over 31 repos | Agent-run evaluation on ~20 routine coding tasks | LoCoMo 92.5, LongMemEval 94.4 (managed platform) |

**Pick codebase-memory-mcp** for the most accurate code graph, if you can
run a downloaded binary. **Pick Serena** if you want your agent to navigate
and *edit* with language-server precision. **Pick Mem0** if you are building
an application that needs user and conversation memory.

**Pick agent-memory-kit** if:

- you can't install binaries, services, or language servers — a locked-down
  work laptop, no admin rights, no exception process;
- you want your agent's *behaviour* disciplined — evidence for every claim,
  a spec before code, no installs without a yes, a recap you can understand
  — not only its retrieval;
- you want memory across sessions with no LLM call, no vector store, and no
  network.

They also compose: nothing stops you running codebase-memory-mcp for the
graph and this kit for the contract, the memory, and the guardrails.

## Quick start

One command, from inside your project. Nothing is cloned, nothing is piped
into a shell, and nothing is left installed afterwards:

```bash
uvx --from git+https://github.com/sheikharfaz/agent-memory-kit amk init
```

Prefer a command that stays on your PATH?

```bash
pipx install git+https://github.com/sheikharfaz/agent-memory-kit
amk init                 # install the kit here and build the index
amk init --hooks --mcp   # also: cross-session recall in Claude Code, live tools for any MCP host
```

`amk init` copies the kit into the current repo, gitignores the two private
paths (`.agent/memory/session/`, `.agent/work/`), and builds the index. Then
check it:

```console
$ amk doctor
agent-memory-kit doctor  ·  /home/you/project

  PASS  python 3.12.4
  PASS  git                  found
  PASS  kit files            all 25 present
  PASS  index                412 files, 3,180 symbols -- OK
  PASS  privacy              .agent/memory/session/ is gitignored
  PASS  claude code hooks    wired
  PASS  mcp server           registered in .mcp.json
  PASS  kit version          matches amk 0.6.0

0 failure(s), 0 warning(s).
```

| Command | Does |
|---|---|
| `amk init [dir]` | Install or upgrade (`--force`) the kit, build the index |
| `amk doctor [dir]` | One-screen health check; non-zero exit on any failure |
| `amk find <plain words>` | Find a symbol without knowing its name |
| `amk query <verb> …` | Any [query verb](#query-cli) |
| `amk mcp` | Run the MCP server over stdio |

The `amk` package itself has no runtime dependencies. Installing from git
fetches one build-time tool (`hatchling`) from your package index, once.

**On PyPI this is `agent-memory-kit-cli`.** A package called
`agent-memory-kit` also exists on PyPI, but it is an unrelated project by
another author — don't install it expecting this one.

### No outbound GitHub or pip? Clone and copy

Everything `amk init` does is also a plain file copy you can run from a
checkout — the same file list, with no package manager involved:

```bash
git clone https://github.com/sheikharfaz/agent-memory-kit.git
cd /path/to/your/project
python3 /path/to/agent-memory-kit/install.py . --wire-hooks --wire-mcp
python3 .agent/skills/codebase-memory/index.py build
```

`install.sh` (bash) and `install.ps1` (PowerShell) do the same. On a Windows
image whose execution policy is `Restricted` — common, and not something a
non-admin can change — use `install.py`; it needs no script-execution policy.

Or copy by hand; the complete list is `FILES` at the top of
[`install.py`](https://github.com/sheikharfaz/agent-memory-kit/blob/main/install.py). The core is `AGENTS.md`, `.agent/lib/`, and
`.agent/skills/codebase-memory/`; every other skill directory is optional.
Then add to `.gitignore`:

```gitignore
.agent/work/
.agent/memory/session/   # session-memory's local log -- raw prompt text, keep it local
# .agent/memory/          <- uncomment too if each developer should build their own index
```

---

## Query CLI

`python .agent/skills/codebase-memory/query.py <verb>` — read-only, local, ~0.1s.

| Need | Command |
|---|---|
| Orient in an unfamiliar repo | `arch` |
| Where is X defined? | `def X` · `search '<regex>' --kind class` |
| **I don't know what it's called** | **`find <plain words>`** — ranks symbols by words, no regex needed |
| What breaks if I change X? | `callers X` · `impact <path>` |
| What does this file depend on? | `file <path>` · `callees <path>` |
| Who imports this module? | `importers <module>` |
| What HTTP surface exists? | `routes [prefix]` |
| Risk of my current diff | `changed` |
| Is this path even indexed? | `coverage <path>...` |
| Possibly-unused symbols | `orphans` |
| Is the codebase growing/shrinking, where? | `drift` (needs 2+ builds logged — see below) |

All verbs accept `--limit N`, `--json`, and `--root <dir>`.

`find` is the one to reach for when you can describe what you want but not
name it. Identifiers are split, so plain words reach camelCase symbols:

```console
$ query.py find verify a users password        # django/django, 6,901 files
0.42  django/contrib/auth/hashers.py:39   function  verify_password
0.26  django/contrib/auth/hashers.py:251  function  verify
```

That took 0.5s, with no embedding model, no vector store, and no language
server. It is lexical ranking, not semantics — a symbol sharing no words
with your phrasing will not surface, and `find` says so rather than
pretending otherwise.

`drift` compares the current build against a past one using
`.agent/memory/history/drift-log.jsonl` — one compact, derived-stats-only
entry appended on every `build` (files/symbols/LOC totals, LOC by language,
LOC by module; never file bodies). Shows what grew, what shrank, and which
modules moved the most since your last build (or `--last N` builds ago). A
no-op rebuild never adds a duplicate entry.

---

## session-memory — cross-session continuity

`codebase-memory` knows the *code*. `session-memory` knows the
*conversation* — an append-only local log of prompts and turns, searched by
lexical (BM25) similarity, so a session that starts after an earlier one
ended can recall what that session established.

```bash
python .agent/skills/session-memory/memory.py recall "what we discussed about auth"
python .agent/skills/session-memory/memory.py recent
```

Wired into Claude Code's `SessionStart` / `UserPromptSubmit` / `Stop` hooks
(`bash install.sh . --wire-hooks`, or by hand — see SETUP.md), it runs
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

When both skills are installed, `session-memory` also layers a small
freshness cache on top of `codebase-memory`: it stamps the map's generation
at the end of every session, and if the next session's map hasn't changed,
it says so instead of staying silent — an optional skip, offered only when
there's real evidence nothing moved, never a reason on its own to trust a
stale map. `AGENTS.md`'s "read the map every session" default is unaffected
for anyone who ignores the note.
Detail:
[`.agent/skills/session-memory/SKILL.md`](https://github.com/sheikharfaz/agent-memory-kit/blob/main/.agent/skills/session-memory/SKILL.md).

## tool-provisioning — propose-only tool access

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
[`.agent/skills/tool-provisioning/SKILL.md`](https://github.com/sheikharfaz/agent-memory-kit/blob/main/.agent/skills/tool-provisioning/SKILL.md).

## spec-first — PRD/TRD instead of vibe coding

The difference between a brilliant engineer using AI and someone vibe-coding
with it isn't speed — it's that the brilliant one still writes down what
they're building and why *before* they build it. `AGENTS.md` §5 defines the
workflow this backs: a PRD before Research, and a TRD-quality Plan artifact.

```
PRD.md (what, why)  →  research.md (what exists)  →  TRD.md (how, why this way)  →  progress.md
```

`PRD.md` is skipped only for a genuinely trivial, already-unambiguous
request — **not** just because the developer said "just implement it" for
something that isn't actually unambiguous; surfacing that ambiguity is the
point. `TRD.md` holds the design to a stricter bar than a bare
implementation plan: real alternatives considered and why they were
rejected (the actual tell of senior-engineer thinking), a testing strategy
mapped to each PRD acceptance criterion, a rollback plan, and blast radius.

```bash
python .agent/skills/spec-first/spec_first.py scaffold auth-retry   # writes PRD.md + TRD.md templates
python .agent/skills/spec-first/spec_first.py check auth-retry      # unchecked criteria, unanswered questions, missing TRD sections
python .agent/skills/spec-first/spec_first.py list                  # what's in flight, which artifacts exist
```

The script only scaffolds structure and checks it's filled in — writing the
actual requirements and design is real thinking, the same way `research.md`
and `progress.md` always required real work, not a form. Detail:
[`.agent/skills/spec-first/SKILL.md`](https://github.com/sheikharfaz/agent-memory-kit/blob/main/.agent/skills/spec-first/SKILL.md).

## dev-recap — closing recap and optional quiz

The other skills make the agent faster, safer, and better-planned. This one
exists because the developer didn't write the code an agent just shipped
for them, and a fast, well-cited diff is not the same thing as an
understood one — see the "AI ethics stance" in its `SKILL.md` for the
reasoning.

At the Definition of Done for anything beyond a one-line fix, the agent:
gives a plain-English, junior-dev-pitched recap with `path:line` citations;
grounds it in *this* repo's own conventions (`codebase-memory`, if built,
or direct inspection otherwise); runs a heuristic gap scan; **genuinely
offers** — never forces — a quiz or walkthrough; and always closes with an
explicit **assumptions & diversions** line, even when it's "none." On the
very first session in a repo, it's also the "new-hire week one" entry
point: ask once how familiar the developer already is with *this* project,
record it locally, and calibrate recap depth accordingly (a recorded
veteran skips the 101-level framing).

```bash
python .agent/skills/dev-recap/recap_log.py gaps                 # heuristic: missing tests, new TODOs, unindexed files
python .agent/skills/dev-recap/recap_log.py record-recap --task auth-retry --files a.py,b.py --summary "..."
python .agent/skills/dev-recap/recap_log.py record-quiz --topic auth-retry --result understood
python .agent/skills/dev-recap/recap_log.py due-for-review        # spaced-repetition-lite: what's worth revisiting
python .agent/skills/dev-recap/recap_log.py set-familiarity --level new|some|veteran
```

The quiz questions themselves are generated live by the agent from the
actual diff, not by a script — `recap_log.py` only logs the outcome
(locally) and ranks what's worth a follow-up check-in later. Quiz and
familiarity data answer one question, for the developer alone: **nothing
here reports results to a manager, a dashboard, or CI** — see the SKILL.md
if you're tempted to wire it into something that would. `gaps` is a lead
generator with the same accuracy contract as `codebase-memory`'s `orphans`:
a clean result means the heuristic found nothing, never that nothing is
missing. Detail: [`.agent/skills/dev-recap/SKILL.md`](https://github.com/sheikharfaz/agent-memory-kit/blob/main/.agent/skills/dev-recap/SKILL.md).

## mcp-bridge — live tools for hosts that aren't Claude Code

Every skill above reaches an agent through files (`AGENTS.md`,
`CODEBASE_MAP.md`) or Claude Code's own hooks. `mcp-bridge` is the third
path: a stdlib-only [Model Context Protocol](https://modelcontextprotocol.io)
server, so Cursor, Claude Desktop, or any other MCP-capable host gets
`codebase-memory` and `session-memory` as 20 live, schema-described tools
instead of relying on file-reading conventions.

```bash
python3 .agent/skills/mcp-bridge/server.py --root /path/to/repo
```

Every tool is a direct passthrough to the same `query.py`/`index.py`/
`memory.py` the CLI already uses — no duplicated logic, so a tool's answer
always matches what the CLI would print, accuracy caveats included. Two
tools write anything (`codebase_build`, into `.agent/memory/graph/` only;
`session_remember`, one `note` entry) — everything else is read-only, and
`tool-provisioning`'s installs are deliberately excluded, keeping this
kit's propose-only safety posture intact for hosts with no approval step
of their own. `install.py|.sh|.ps1 --wire-mcp` registers it in your
project's `.mcp.json` automatically. Detail, full tool list, and what's
excluded and why: [`.agent/skills/mcp-bridge/SKILL.md`](https://github.com/sheikharfaz/agent-memory-kit/blob/main/.agent/skills/mcp-bridge/SKILL.md).

---

## What the agent contract enforces

`AGENTS.md` is loaded every turn and stays under ~5k tokens covering all
six skills' worth of contract. It defines:

- **Retrieval ladder** — map → query → shard → targeted grep → line range →
  whole file. Never more than 3 whole files before answering. Never a 1000+ line
  file in full.
- **Evidence rules** — every claim about the repo carries `path:line`. No
  citation means the agent goes and looks.
- **PRD → Research → TRD → Implement** — a PRD before touching code (what,
  why, acceptance criteria — skip only for a trivial, unambiguous request),
  through to a TRD-quality plan (real alternatives rejected, not just the
  one chosen), each a durable artifact under `.agent/work/<task-slug>/`
  that survives context compaction.
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

Symbols come from language-aware pattern matching across 31 languages (49 file
types are recognised; the rest are indexed as files without symbols), not from
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

- No network access in the core scripts. Nothing is uploaded, phoned home, or
  logged off-machine.
- Writes are confined to `.agent/memory/` (and, for `spec-first`, the
  already-established `.agent/work/`). Verified by md5-diffing every other
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

`session-memory`'s automatic behaviour (the hooks, and the familiarity nudge
riding on `SessionStart`) is Claude-Code-specific — that harness is what
defines `SessionStart` / `UserPromptSubmit` / `Stop` hooks. Its `memory.py`
CLI, and `tool-provisioning`'s, `dev-recap`'s, and `spec-first`'s
equivalents, are plain Python and work anywhere; other harnesses just have
to invoke them by hand or via their own hook/skill mechanism instead of
getting it for free. `dev-recap` and `spec-first` in particular are just
`AGENTS.md` §5/§15 plus a CLI each — no hooks needed at all, so both work
in any harness that reads `AGENTS.md`.

Or skip the hand-invoking entirely: `mcp-bridge` puts `codebase-memory` and
`session-memory` behind the standard [MCP](https://modelcontextprotocol.io)
stdio transport, which Cursor, Claude Desktop, and most other modern
harnesses speak natively. `--wire-mcp` at install time gets you the closest
thing to Claude Code's own hooks — live, schema-described tools instead of
a CLI you invoke by hand — on any of them.

If you already run RPI-style chat modes (research/plan/implement), they
compose directly: `AGENTS.md` §5 defines a PRD step before Research and a
TRD-quality bar on Plan, with the same artifact slots your chat modes
already expect.

---

## What this is not

`codebase-memory` is not a language server, not an AST-accurate call graph,
not semantic search. If you want tree-sitter accuracy across 162 languages
and a proper knowledge graph from a single native binary, use
[codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp), which is
where several ideas here came from — the tiered agent profiles, the coverage-vs-
completeness distinction, and the layered ignore model. This kit is the
zero-dependency, regex-based version of the same idea, for people who want
readable Python source they can audit — about 5,000 lines, no binary — including its own optional MCP server (`mcp-bridge`), a stdlib
stdio process this kit starts itself rather than a hosted one.

`session-memory` is not semantic search either — its BM25 recall matches
shared vocabulary, not paraphrased meaning, and it is not reinforcement
learning in the ML sense; `evals/` measures exactly where that ceiling
sits and publishes the queries it still fails. `tool-provisioning` is not
a package manager or a sandbox — it never installs anything without an
explicit yes from a human in the current chat, and it never uninstalls
anything it didn't itself install. `spec-first` is not a stage-gate or a
template-filling exercise — a two-line TRD for a two-line change is
correct, not lazy, and the PRD/TRD content itself is real thinking a script
can't do for you. `dev-recap` is not a gate, a scorecard, or proof of
correctness — the quiz is a comprehension check, not a test suite, `gaps`
is a heuristic lead, not a guarantee, and the familiarity profile is for
the developer's own benefit only; nothing about any of it blocks a task or
reports to anyone else. `mcp-bridge` adds no new capability or accuracy of
its own — it is a transport, not an engine; every answer it returns still
carries the exact same caveats as the CLI verb it calls.

---

## Testing

```bash
python3 -m unittest discover -s tests -v
```

Stdlib `unittest` only — no `pytest`, no test dependencies to install, so
the "zero dependencies" claim holds for development too. Covers every
skill's engine at the unit level (tokenizing, redaction, ranking, org
policy, ledger semantics, PRD/TRD parsing) plus subprocess-level smoke
tests that run the actual installers, hooks, and MCP protocol handshake
the way a real client would. CI also runs `evals/` on every push and fails
if retrieval quality regresses below the numbers published above — the
README cannot quietly go stale.
CI (`.github/workflows/ci.yml`) runs the same suite on Ubuntu/Windows/macOS
across Python 3.8 and 3.12 on every push and PR.

## For security/procurement reviewers

See [SECURITY.md](https://github.com/sheikharfaz/agent-memory-kit/blob/main/SECURITY.md) for the full threat model, data-flow table,
and what's explicitly out of scope. Short version: no telemetry, no network
calls except a command you approve, nothing written outside `.agent/memory/`
and `.agent/work/`, zero third-party dependencies.

## Documentation

| Start here | Go deeper |
|---|---|
| [AGENTS.md](https://github.com/sheikharfaz/agent-memory-kit/blob/main/AGENTS.md) — the operating contract | [SETUP.md](https://github.com/sheikharfaz/agent-memory-kit/blob/main/SETUP.md) — full install/wiring walkthrough |
| [SECURITY.md](https://github.com/sheikharfaz/agent-memory-kit/blob/main/SECURITY.md) — threat model & data flow | [CHANGELOG.md](https://github.com/sheikharfaz/agent-memory-kit/blob/main/CHANGELOG.md) — version history |
| [`.agent/skills/codebase-memory/SKILL.md`](https://github.com/sheikharfaz/agent-memory-kit/blob/main/.agent/skills/codebase-memory/SKILL.md) | [`.agent/skills/session-memory/SKILL.md`](https://github.com/sheikharfaz/agent-memory-kit/blob/main/.agent/skills/session-memory/SKILL.md) |
| [`.agent/skills/tool-provisioning/SKILL.md`](https://github.com/sheikharfaz/agent-memory-kit/blob/main/.agent/skills/tool-provisioning/SKILL.md) | [`.agent/skills/spec-first/SKILL.md`](https://github.com/sheikharfaz/agent-memory-kit/blob/main/.agent/skills/spec-first/SKILL.md) |
| [`.agent/skills/dev-recap/SKILL.md`](https://github.com/sheikharfaz/agent-memory-kit/blob/main/.agent/skills/dev-recap/SKILL.md) | [`.agent/skills/mcp-bridge/SKILL.md`](https://github.com/sheikharfaz/agent-memory-kit/blob/main/.agent/skills/mcp-bridge/SKILL.md) |
| [`benchmarks/README.md`](https://github.com/sheikharfaz/agent-memory-kit/blob/main/benchmarks/README.md) — what it costs | [`evals/README.md`](https://github.com/sheikharfaz/agent-memory-kit/blob/main/evals/README.md) — whether it's correct |
| `tests/` — the test suite is also readable documentation of expected behaviour | |

## Contributing

The most useful contribution is a real **retrieval miss** — something
`session-memory` or `amk find` should have surfaced and didn't. The eval
dataset was written by the maintainers, which is its biggest weakness, and
the *Retrieval miss* issue template collects exactly what `evals/` needs.
After that: symbol patterns for under-served languages, and
`tool-provisioning` registry entries. The constraints every change has to
respect, and a PR checklist, are in [CONTRIBUTING.md](https://github.com/sheikharfaz/agent-memory-kit/blob/main/CONTRIBUTING.md).

## License

MIT. See [LICENSE](https://github.com/sheikharfaz/agent-memory-kit/blob/main/LICENSE). Version history: [CHANGELOG.md](https://github.com/sheikharfaz/agent-memory-kit/blob/main/CHANGELOG.md).
