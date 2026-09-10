# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/). No
package registry exists for this kit (it's copied via `install.sh`/
`install.ps1`/`install.py`), so "release" means a tagged commit a team can
pin their internal mirror or golden image to — see [SETUP.md](SETUP.md).

## [Unreleased]

### Added
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
