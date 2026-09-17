# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/). A
release is a tagged commit. Pin one with
`uvx --from git+https://github.com/sheikharfaz/agent-memory-kit@v0.6.1 amk init`,
or point an internal mirror or golden image at the tag — see
[SETUP.md](SETUP.md).

## [Unreleased]

## [0.6.1] — 2026-09-17

Launch release: no behaviour change to the installed kit beyond
documentation.

### Added
- README "How it compares": an even-handed table against
  codebase-memory-mcp, Serena, and Mem0, built only from facts in each
  project's own README, including where each one beats this kit.
- A proof strip at the top of the README; every number in it links to the
  command that reproduces it.
- `benchmarks/symbol_filter_audit.py`: reproduces the "349 symbols hidden
  from Django's index" figure by running the old and current secret filters
  over any repo.
- A manually triggered PyPI release workflow using trusted publishing (no
  stored token).

### Fixed
- Published claims that had drifted: symbol extraction covers 31
  languages, not "~40"; the shipped code is ~5,000 lines, not "~1,600";
  codebase-memory-mcp covers 162 languages, not "150+"/"158"; and the
  benchmarks README attributed all of Django's +451 symbols to the filter
  fix when 395 were (the rest is upstream change between clones).
- `codebase-memory/SKILL.md` still said "no MCP server" and described the
  secret filter in its pre-v0.5.0 terms.

## [0.6.0] — 2026-09-17

### Added
- **`amk`, a one-command install and CLI.** `uvx --from
  git+https://github.com/sheikharfaz/agent-memory-kit amk init` installs the
  kit into the current project, gitignores the two private paths, and builds
  the index -- no clone, no absolute paths into a checkout, and no `curl |
  bash` (which `AGENTS.md` §8 forbids, so the kit does not ask users to do
  it either). `pipx install git+…` gives a persistent `amk`. Commands:
  `init` (install/upgrade, `--hooks`, `--mcp`), `doctor`, `find`, `query`,
  `mcp`, `version`. Zero runtime dependencies; the wheel carries the kit
  files at their real repo paths via hatchling `force-include`, so nothing
  is duplicated in the tree, and `init` imports `install.py`'s `FILES`
  rather than keeping its own list.
- **`amk doctor`**: a one-screen health check -- Python, git, every kit
  file, index built and fresh, session text gitignored, hooks and MCP wired,
  and whether the installed files match this `amk` version. Non-zero exit on
  any failure, so it doubles as a CI gate.
- A CI job that builds the sdist and wheel, installs the wheel into a bare
  venv on Ubuntu and Windows (Python 3.8 and 3.12), asserts it declares no
  runtime dependencies, and runs `init` / `doctor` / `find` against a fresh
  project -- the test suite covers the checkout, this covers what users get.
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, bug-report and PR templates, and
  a *Retrieval miss* issue template that collects exactly what `evals/`
  needs -- real misses are the fix for the eval dataset's biggest weakness,
  which is that the maintainers wrote it.

### Changed
- `install.py` now exposes `install(src, target, ...)`; its command line and
  output are unchanged.
- README leads with the one-command install. The manual-copy list there,
  which had drifted (no `.agent/lib/`, no `mcp-bridge`), now points at
  `FILES` in `install.py` instead of repeating it.

### Fixed
- `wire_mcp.py` wrote the absolute path of whichever interpreter ran it into
  `.mcp.json`. Project-scope `.mcp.json` is meant to be committed, so that
  leaked one developer's venv path to the whole team -- and under `uvx` the
  path points into a temporary environment that can be garbage-collected,
  silently breaking the server later. It now writes a bare `python3` /
  `python` resolved from PATH (the server is stdlib-only, so any 3.8+
  interpreter runs it).
- Installer output could print out of order when piped, because stdout was
  not flushed before the hook/MCP wiring subprocesses ran.

## [0.5.0] — 2026-09-16

### Added
- `evals/`: a reproducible retrieval-*quality* harness, answering the
  question `benchmarks/` deliberately does not -- when `session-memory`
  recalls something, is it the right thing? Reports recall@1/@3/@5 and MRR
  over a shipped 40-entry / 20-query developer-session dataset, runs both
  the old and new ranking arms from one flag (`--scorer tfidf|bm25`), and
  prints the queries it still fails rather than omitting them. Zero
  dependencies, no network, no LLM call, ~1s. CI runs it on every push and
  fails if quality regresses below the published numbers, so the README
  cannot quietly go stale. Methodology, the authoring-bias disclosure, and
  why these numbers are *not* comparable to LongMemEval/LOCOMO:
  `evals/README.md`.
- `.agent/lib/retrieval.py`: one shared, stdlib-only code-aware tokenizer
  and Okapi BM25 scorer, consumed by `session-memory` and `codebase-memory`
  through a guarded import -- an install missing this one file degrades to
  the previous behaviour instead of failing.
- `query.py find "<plain words>"` (and the `codebase_find` MCP tool, taking
  `mcp-bridge` from 20 tools to 21): ranked symbol search for when you can
  describe what you want but cannot name it -- `find verify a users
  password` reaches `verify_password` in django/django in about half a
  second, with no embedding model, vector store, or language server.

### Changed
- `session-memory` ranks with BM25 over a code-aware tokenizer instead of
  TF-IDF cosine over a plain one. Measured on the new dataset: recall@1
  0.450 -> 0.675, recall@3 0.625 -> 0.775, MRR 0.588 -> 0.787, misses 6 ->
  3; per query, 5 better, 15 unchanged, **0 worse**. The gain is
  concentrated where the old tokenizer was structurally blind (below).
  Score scale is unchanged -- BM25 is normalised by each query's achievable
  maximum -- so `MIN_SCORE` and the hooks' injection thresholds keep the
  meaning they were calibrated for.

### Fixed
- **`session-memory` could not recall anything about a camelCase symbol.**
  The tokenizer lowercased *before* splitting, so `getUserById` became one
  opaque term: asking "where do we look up a user by id" a week later
  shared zero vocabulary with the entry that recorded it, scored 0.0, and
  returned nothing. Since camelCase covers most of JS, TS, Java, Go, C# and
  Swift, that one line capped recall for the majority of real repositories
  -- in a memory system whose subject matter is code. Identifiers are now
  split into parts while the whole term is kept, so exact-name queries stay
  precise. On the `identifier` bucket of the eval, recall@3 went 0.700 ->
  **1.000** and misses 3 -> 0.
- **`codebase-memory` silently deleted security-critical symbols from the
  index.** The secret scrubber matched the bare *words* `token`, `secret`,
  `password`, `api_key`, `bearer`, `access_key`, `private_key` -- and that
  pattern was applied to symbol *names*. Any symbol whose name merely
  mentioned the concept was dropped: measured against django/django, 349
  distinct symbols and 395 definitions were missing, including
  `check_password`, `set_password` and `verify_password`. The index would
  report that Django's password-checking functions did not exist, in
  exactly the part of a codebase where a false negative is most dangerous,
  and nothing surfaced the loss because a missing symbol looks identical to
  a symbol that was never there. The filter now rejects credential
  *shapes* (`AKIA…`, `ghp_…`, `sk-…`, `xox…-`, PEM headers) anywhere, and
  credential-ish words only when bound to a literal value
  (`api_key="sk-live-…"`); a name is an identifier, not a value. Benchmark
  numbers were re-run against the corrected index (django: 43,170 ->
  43,621 symbols; 395 of that is this fix, the rest is upstream Django
  changing between clones) and `SECURITY.md` documents the narrowed scope and the
  residual risk it accepts.
- `VERSION` had drifted again (`0.2.0` while `v0.4.0` was tagged).

## [0.4.0] — 2026-09-16

### Added
- `mcp-bridge`: a stdlib-only Model Context Protocol server (`server.py`,
  stdio transport, newline-delimited JSON-RPC 2.0 per
  https://modelcontextprotocol.io -- no `mcp` package, no third-party
  dependency) exposing `codebase-memory` and `session-memory` as 20 live,
  schema-described tools, for any MCP-capable host -- Cursor, Claude
  Desktop, a custom Agent-SDK build -- not just Claude Code's own hooks.
  Every tool is a direct subprocess passthrough to the same `query.py`/
  `index.py`/`memory.py` the CLI already uses, so an MCP answer always
  matches the equivalent CLI output, same accuracy caveats included.
  Exactly two tools write anything (`codebase_build`, only
  `.agent/memory/graph/`; `session_remember`, one `note` entry) -- every
  other tool is read-only, and `tool-provisioning`'s install/uninstall,
  and `dev-recap`'s/`spec-first`'s write verbs, are deliberately NOT
  exposed, keeping the kit's propose-only safety posture intact for hosts
  with no conversational approval step of their own. `wire_mcp.py` merges
  an entry into a target repo's `.mcp.json`, idempotently; `install.py|
  .sh|.ps1 --wire-mcp` runs it automatically. `AGENTS.md` §16, `SETUP.md`
  step 10, `SECURITY.md`, and the README document it; full tool list and
  what's excluded and why: `.agent/skills/mcp-bridge/SKILL.md`.

### Fixed
- `session-memory`: `AGENT_MEMORY_KIT_DISABLE_SESSION_MEMORY` only ever
  silenced the Claude Code hooks (`hooks/_common.py`'s own check) -- direct
  CLI use of `memory.py record`/`recall`/`recent`, and now `mcp-bridge`'s
  `session_*` tools, ignored it entirely. Moved the guard into `memory.py`
  itself (`append_entry`/`recall`/`recent`), so the same org-wide opt-out
  now applies uniformly regardless of which entry point reaches it.
  `cmd_record`'s CLI message also no longer claims "(empty text, not
  recorded)" when the real reason was the kill switch.
- `VERSION` was still reading `0.2.0` after the `v0.3.0` tag.

## [0.3.0] — 2026-09-16

### Added
- `session-memory`: a map-freshness cache, opt-in on top of `codebase-memory`.
  `hooks/stop.py` stamps the map's `generation` at session end to
  `.agent/memory/session/map_state.json`; `hooks/session_start.py` compares
  that stamp to the map's current generation and, only on an exact match,
  notes that nothing has changed since a given session last read it. Any
  mismatch or missing stamp and it says nothing -- the "read the map every
  session" rule (`AGENTS.md` §2) is the unaffected default; this only ever
  offers a time-saving skip when there is real evidence nothing moved.
  Pure opt-in layering: no change to `codebase-memory` itself, and a repo
  without `session-memory` installed sees nothing new.
- `benchmarks/`: a reproducible token comparison (`token_comparison.py`)
  measuring how many tokens an agent spends answering four "getting
  oriented" questions against a real repo, with `codebase-memory` versus a
  grep-and-read naive baseline. Run against `psf/requests` and
  `django/django`; results and full methodology in `benchmarks/README.md`,
  summarized in the main README's new "Proof" section.
- `.agentignore` now supports `!pattern` negation lines (gitignore-style),
  the one way to opt a path back in that the default rules would otherwise
  exclude. It can never reach `.agent/memory/` -- that exclusion is
  unconditional, on purpose (see below).

### Changed
- `index.py`: `.agent/skills/` is excluded from indexing **by default**.
  This reverses an earlier fix in this same unreleased range (below) --
  the corrected understanding, found by building two real projects with
  the kit installed
  ([linkshrink-agent-memory-kit](https://github.com/sheikharfaz/linkshrink-agent-memory-kit)):
  in the overwhelmingly common case, `.agent/skills/` holds a *vendored*
  copy of this kit's own scripts (put there by `install.sh`/`.ps1`/`.py`),
  not the consumer repo's own source, and indexing it buries a small
  project's real code under this tool's own internals -- one demo repo's
  map was ~93% kit-internal LOC before this change. `.agent/work/`
  (PRD/TRD/research docs, always the repo's own content, never vendored)
  stays indexed by default. This kit's own repo -- the one real exception,
  where `.agent/skills/` genuinely is the source -- opts back in via the
  new `.agentignore` negation support (see its own `.agentignore`).
- `CODEBASE_MAP.md`'s fixed-overhead sections were tightened without
  dropping any of the information they carry: the "How to use this file"
  and "Coverage and limits" prose is denser; modules with zero parsed
  symbols are summarized in one line instead of a full table row each;
  and the "Hubs" section now requires 2+ callers (a symbol called from
  exactly one place isn't a hub by any reasonable reading of the word, and
  including it was pure noise, worst on a small repo where nearly
  everything has exactly one caller). Combined with the `.agent/skills/`
  fix above, this took `linkshrink-agent-memory-kit`'s per-session map
  cost from being the largest reason a kit-assisted session cost *more*
  tokens than an unaided one, to the kit-assisted total coming in below
  the baseline overall -- see that repo's `SESSION_LOG.md`/`COMPARISON.md`
  for the exact before/after numbers.
- A second round on the same map, still dropping no information: `Stack`/
  `Likely entry points`/`HTTP surface` fold into one `Overview` section
  when there are few enough entry points and routes to name (a larger
  surface keeps the fuller, separately headed form, where the structure
  earns its keep); the module table only appears once there are enough
  modules to be worth tabulating, otherwise modules list as compact lines;
  `Coverage and limits`' four bullets condense to two. `query.py file`
  also got denser -- symbols list on one comma-joined line
  (`name(kind):line`) instead of one padded line each. Combined with the
  round above, `linkshrink-agent-memory-kit`'s Sessions 2-4 total dropped
  further, from ~1,676 to ~1,430 tokens against baseline's ~1,993 (~28%
  fewer, not the ~2x-worse first measurement) -- see that repo's
  `SESSION_LOG.md` for the full, still-honest accounting, including why
  it stops short of literally half without trading away either the map's
  actual informativeness or the "always read the map" guarantee.

### Fixed
- `query.py`: `--root <path>` (and `--json`/`--limit`) silently reset to
  their defaults when placed *before* the verb (e.g.
  `query.py --root X def Y` ignored `--root`) -- argparse's subparsers
  re-parse into the same namespace the top-level parser already populated,
  and a shared flag definition on both levels let the subparser's default
  clobber a value already set. Found via the benchmarks script, which
  calls verbs exactly this way.
- `index.py`: `.agent` was originally a blanket hard-denied directory
  name, which also hid `.agent/skills/` and `.agent/work/` from the index,
  not just the intended target, `.agent/memory/` (generated output plus
  session-memory/tool-provisioning/dev-recap's local logs). First fixed by
  scoping the exclusion to `.agent/memory/` specifically -- which was
  itself half right, corrected above once the consumer-repo case surfaced.
  `.agent/memory/`'s exclusion has stayed a hard, unconditional path-prefix
  check throughout.
- `query.py`: several verbs (`def`, `callers`, `search`, `importers`,
  `routes`, `orphans`) printed a trailing human-readable summary/caveat
  line even when `--json` was set, producing output that wasn't valid JSON
  for a machine consumer. Now suppressed under `--json`.
- `dev-recap`'s `gaps` cross-referenced `codebase-memory`'s `files.jsonl`
  against the wrong field name (`"path"` instead of the real short key
  `"p"`), so it always reported every changed file as "not in the
  codebase index" regardless of whether it actually was. Found by building
  a real project with the kit installed and noticing a freshly-rebuilt
  index still triggered the warning.

## [0.2.0] — 2026-09-10

### Added
- `session-memory` skill: cross-session recall of prompts/turns via local
  TF-IDF, with Claude Code `SessionStart`/`UserPromptSubmit`/`Stop` hooks.
  Opt-in via `install.sh|.ps1|.py --wire-hooks`.
- `tool-provisioning` skill: propose-only tool acquisition (`search` →
  `plan` → approve → `install` → `uninstall`), with an append-only ledger.
- `toolkit.py doctor`: read-only preflight diagnostic for PyPI/npm/mirror
  reachability, proxy env vars, and available CLIs — self-serve
  troubleshooting on a locked-down network without an IT ticket.
- Org policy for `tool-provisioning` (`registry.org.json` /
  `AGENT_MEMORY_KIT_ORG_POLICY`): allowlist/denylist/override registry
  entries, and redirect pip installs through an internal mirror
  (`pip_index_url`). Takes precedence over any project-local registry.
- `toolkit.py sync-org-registry`: the one explicit, developer-run command
  that fetches an org policy file over the network.
- Best-effort SBOM capture (`pip show`) on install, and
  `toolkit.py export-audit` to produce a portable audit report.
- `session-memory` compliance controls: `AGENT_MEMORY_KIT_DISABLE_SESSION_MEMORY`
  org-wide kill switch, `AGENT_MEMORY_KIT_RETENTION_DAYS` retention cap.
- `install.py`: cross-platform, stdlib-only installer alongside
  `install.sh`/`install.ps1`, for machines where PowerShell's execution
  policy blocks running `.ps1` scripts without admin rights.
- `SECURITY.md`: threat model and data-flow summary for AppSec/OSPO review.
- Test suite (`tests/`, stdlib `unittest` only, zero dependencies) and a
  GitHub Actions CI workflow across Ubuntu/Windows/macOS × Python 3.8/3.12.
- Three new stdlib-only registry entries (`csv`, `zip`, `xml`) that resolve
  to "already available" instead of proposing a pip install.
- `dev-recap` skill: a closing protocol (`AGENTS.md` §15) for anything
  beyond a one-line fix — a plain-English, junior-dev-pitched recap with
  citations, grounded in this repo's own conventions; a heuristic
  `recap_log.py gaps` scan (missing tests, new TODO/FIXME markers,
  paths missing from `codebase-memory`'s index); a genuinely optional
  quiz/walkthrough offer (questions generated live by the agent from the
  actual diff, not scripted); spaced-repetition-lite `due-for-review`
  tracking; and a mandatory closing "assumptions & diversions" line, even
  when it's "none." Quiz/recap data stays local to the developer's own
  machine by design — see its SKILL.md's "AI ethics stance."
- `dev-recap` project-familiarity profile ("new-hire week one" mode):
  `recap_log.py set-familiarity --level new|some|veteran`, asked once per
  project via `session-memory`'s `SessionStart` hook on first contact
  (never again once answered), calibrating recap depth. Local only, never
  aggregated or reported elsewhere.
- `spec-first` skill: a PRD before Research and a TRD-quality bar on Plan
  in the existing RPI workflow (`AGENTS.md` §5 renamed accordingly) --
  writing requirements and a design before touching code, the way a
  senior engineer works, instead of vibe coding. `spec_first.py`
  scaffolds `PRD.md`/`TRD.md` templates and checks them (unchecked
  acceptance criteria, unanswered open questions, missing TRD sections)
  via markdown-structure parsing only -- the actual requirements/design
  thinking stays the agent's job, same as `research.md` always was.
- `codebase-memory` `drift` verb + automatic history logging: every
  `index.py build` appends a compact, derived-stats-only snapshot to
  `.agent/memory/history/drift-log.jsonl` (files/symbols/LOC totals, LOC
  by language, LOC by module -- never file bodies), and
  `query.py drift [--last N]` diffs two points in that history to show
  what grew, what shrank, and which modules moved most. Deduplicates a
  no-op rebuild automatically (same content-addressed generation).

### Fixed
- `session-memory`'s `recent()` could return a session's *older* entry
  instead of its newer one when two entries landed in the same one-second
  timestamp window (common for rapid successive prompts), because a stable
  descending sort keeps tied elements in their original (oldest-first)
  order. Ties now break toward the later-written entry.

## [0.1.0]

- Initial release: `AGENTS.md` contract + `codebase-memory` local codebase
  index (`index.py` build, `query.py` read-only verbs).
