---
name: session-memory
description: Cross-session working memory for this repo -- a local, lexical (TF-IDF) log of prompts and turns that lets a new Claude Code session recall what an earlier, separate session established, without either of you re-explaining it. Trigger when asked what was discussed or decided previously, when picking a task back up after a break, when the developer says "like we talked about" or "continue from last time", or when deciding whether to install the hooks. Do NOT trigger for structural questions about the codebase itself -- that is the codebase-memory skill.
---

# Skill: session-memory

An append-only, local record of prompts and assistant turns in this repo,
recalled by TF-IDF lexical similarity. Entirely local: standard-library
Python, no network, no daemon beyond Claude Code's own hook mechanism, no
external index server. Reads and writes only `.agent/memory/session/`.

This is not the codebase index. `codebase-memory` (`.agent/skills/codebase-memory/`)
knows the *code*. This skill knows the *conversation history* -- what was
asked, discussed, and done, across sessions that would otherwise not know
about each other.

## What "cross-session" means here

Every Claude Code session in this repo writes to the same
`.agent/memory/session/entries.jsonl`. A session that starts after yesterday's
ended reads the same file. That is the entire mechanism -- no server, no
sync, just a shared local file plus a similarity search over it.

## How it engages automatically

If the hooks below are wired into `.claude/settings.json` (see SETUP.md),
this runs without you invoking anything:

| Hook | When | Does |
|---|---|---|
| `hooks/session_start.py` | Session starts/resumes | Surfaces the latest entry from each other session as additional context |
| `hooks/user_prompt_submit.py` | Every prompt, before you see it | Records the prompt; recalls lexically similar entries from other sessions and injects them as additional context |
| `hooks/stop.py` | After each response | Records the assistant's final text as a "turn" entry; prunes periodically |

All three fail open: any error, missing file, or unreadable transcript means
the hook emits nothing and exits 0. They never block a session.

Without the hooks wired up, you can still use this by hand -- see Commands
below. In that case, run `recall` yourself at the start of a task the way you
would `codebase-memory`'s `verify`+read-the-map.

## Commands

```bash
python .agent/skills/session-memory/memory.py record --kind note --text "..."
python .agent/skills/session-memory/memory.py recall "what we talked about" --limit 5
python .agent/skills/session-memory/memory.py recent --limit 5
python .agent/skills/session-memory/memory.py stats
python .agent/skills/session-memory/memory.py prune --keep-last 4000
python .agent/skills/session-memory/memory.py verify
```

## What kind of "semantic" this is -- read before trusting a result

Ranking is TF-IDF cosine similarity over tokenized text: it finds entries
that **share vocabulary** with your query. It is not a trained embedding
model and does not understand paraphrase, synonyms, or concepts it has no
shared words for. Consequences:

* A high-scoring hit shares real terms with your prompt. Treat it as a lead.
* A miss does not mean nothing relevant exists -- it may be worded
  differently. `recent` (chronological, no matching required) is the
  fallback when `recall` comes up empty.
* Recalled entries get a small ranking boost the more often they are
  recalled (`weight` field, bumped in `recall`/hooks). This rewards entries
  that keep proving useful, but it is a frequency heuristic, not
  reinforcement learning in the ML sense, and it never overrides topical
  relevance by more than a modest margin.
* Every entry is a **fact that something was said**, not a verified fact
  about the codebase. Cross-check against the actual code before acting on
  a recalled claim, the same way `codebase-memory`'s NOTES.md entries are
  provenance-tagged, not gospel.

## Privacy and size

* Text is redacted for common secret shapes (AWS-style keys, `key=`/`token=`
  assignments, JWTs, PEM private-key blocks) before it is written. This is a
  heuristic regex pass, not a guarantee -- do not paste real secrets into a
  prompt and rely on this to catch it.
* Entries are capped at 4,000 characters each; `prune` caps total entries
  (default keeps the most recent 4,000) and runs automatically every ~250
  entries via the Stop hook.
* `.agent/memory/session/` is local to this machine's checkout. It is not
  synced, uploaded, or shared unless you commit it yourself -- and because it
  contains raw prompt/response text rather than derived structural facts, the
  default (see `.gitignore` in SETUP.md) is to **not** commit it.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `recall`/`recent` say nothing recorded | First use in this repo, or hooks not wired -- see SETUP.md |
| Hooks seem to do nothing | Check `.claude/settings.json` has the three hook entries; run a hook manually with a fake JSON stdin payload to see output |
| `entries.jsonl` growing large | `prune --keep-last N`, or lower `PRUNE_EVERY` in `hooks/stop.py` |
| A recalled entry contains something sensitive | Redaction is heuristic. Edit or delete the offending line in `entries.jsonl` directly, or `prune` |
