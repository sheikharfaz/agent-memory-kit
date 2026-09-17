## What and why

<!-- The problem, and why this is the right fix. -->

## Evidence

<!-- Tests added, and -- for anything touching retrieval or the index -- the
     before/after from `python3 evals/recall_eval.py` or `benchmarks/`,
     including anything that got worse. -->

## Checklist

- [ ] `python3 -m unittest discover -s tests` passes
- [ ] No new runtime dependency, no new network call
- [ ] Docs that describe this behaviour agree with each other (README, SKILL.md, AGENTS.md, mcp-bridge)
- [ ] New shipped files added to `FILES` in `install.py` and to `install.sh` / `install.ps1`
- [ ] `CHANGELOG.md` updated under `[Unreleased]`
