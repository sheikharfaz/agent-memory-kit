# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/). No
package registry exists for this kit (it's copied via `install.sh`/
`install.ps1`/`install.py`), so "release" means a tagged commit a team can
pin their internal mirror or golden image to — see [SETUP.md](SETUP.md).

## [0.2.0] — unreleased

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

### Fixed
- `session-memory`'s `recent()` could return a session's *older* entry
  instead of its newer one when two entries landed in the same one-second
  timestamp window (common for rapid successive prompts), because a stable
  descending sort keeps tied elements in their original (oldest-first)
  order. Ties now break toward the later-written entry.

## [0.1.0]

- Initial release: `AGENTS.md` contract + `codebase-memory` local codebase
  index (`index.py` build, `query.py` read-only verbs).
