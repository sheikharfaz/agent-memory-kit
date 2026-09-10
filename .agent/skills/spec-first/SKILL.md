---
name: spec-first
description: Write requirements and a technical design before touching code -- a PRD (what, and why) and a TRD (how, and why this way) -- instead of jumping straight to an edit. Trigger for anything beyond a one-file, already-unambiguous fix, including when the developer says "just implement it" for something that isn't actually unambiguous. Do NOT trigger for a genuinely trivial, precisely-specified request (rename X to Y, fix the typo on line 12) -- ceremony for its own sake is its own failure mode.
---

# Skill: spec-first

The difference between a brilliant engineer using AI and someone vibe-coding
with it isn't speed -- it's that the brilliant one still writes down what
they're building and why *before* they build it, the same way they would
without AI in the loop. This skill is that discipline, made concrete: a PRD
before Research, a TRD in place of a bare `plan.md`. It slots into the
existing workflow in `AGENTS.md` §5 rather than replacing it.

## The workflow

```
PRD.md  →  research.md  →  TRD.md  →  progress.md
(what,      (what exists,   (how, and    (execute one
 and why)    unchanged        why this    phase at a
             from before)     way)        time, unchanged)
```

Only `PRD.md` and `TRD.md` are new; `research.md` and `progress.md` keep
doing exactly what they already did in `AGENTS.md` §5.

### PRD.md -- what, and why

```bash
python .agent/skills/spec-first/spec_first.py scaffold <task-slug>
```

Fill in: the problem and who it affects, current vs desired behavior,
**testable acceptance criteria** (a checklist — this becomes the
definition of done for the task, and dev-recap's closing recap references
it), explicit **non-goals** (the scope fence — say what you're deliberately
not doing), and **open questions**.

Open questions are the load-bearing part. If something is ambiguous, ask
the developer — in chat, or via whatever clarifying-question mechanism your
harness provides — rather than silently picking an interpretation. This
holds **even when the developer's own request was "just implement it"**:
surfacing a real ambiguity is not second-guessing them, it's the entire
point of writing a PRD instead of skipping straight to code. Only mark
something `ASSUMPTION:` in the PRD's own Assumptions section if you
genuinely couldn't get an answer (e.g. they're not available to ask) — not
as a way to avoid asking.

### research.md -- unchanged

Exactly `AGENTS.md` §5's existing Research phase: map what exists, cite
`path:line`, don't propose anything yet.

### TRD.md -- how, and why this way

```bash
python .agent/skills/spec-first/spec_first.py scaffold <task-slug> --trd-only
```

This is what `plan.md` used to be, held to a stricter bar — the single
biggest tell of senior-engineer thinking versus vibe coding is showing the
**alternatives you rejected**, not just presenting the one approach as if
it were the only option. Cover: the chosen approach; real alternatives
considered and why they lost; files/symbols/interfaces touched (from
`research.md`); edge cases and how each is handled; a **testing strategy
mapped explicitly to each PRD acceptance criterion** (criterion → how it's
checked); a rollback plan; and blast radius (`codebase-memory`'s
`query.py impact` on every touched file, flagging hub symbols).

**Stop and get approval before implementing** — same gate `AGENTS.md` §5
already requires at the Plan boundary, now against a real design instead of
a sketch.

### progress.md -- unchanged

Exactly `AGENTS.md` §5's existing Implement phase, except the final
verification is against **PRD.md's acceptance criteria**, not just "it
builds." Run `check` before declaring done:

```bash
python .agent/skills/spec-first/spec_first.py check <task-slug>
```

Reports unchecked acceptance criteria, unanswered open questions, and
whether the TRD actually has an approach and a testing strategy written
(not just section headers). This is markdown-structure parsing, not code
review — it catches "you forgot to fill this in," not "your design is
wrong." A clean `check` is a necessary condition for done, never a
sufficient one.

```bash
python .agent/skills/spec-first/spec_first.py list
```

Shows every task under `.agent/work/` and which of the four artifacts exist
— useful for resuming work, or noticing a task that has a `TRD.md` but no
`PRD.md` behind it (skipped intentionally for a trivial task, or skipped
because someone was in a hurry — `check` won't tell you which, use
judgment).

## When to skip PRD.md entirely

A genuinely trivial, already-unambiguous request: fix a typo on a named
line, rename a symbol everywhere, bump a version string, a one-file change
with obvious acceptance criteria. Go straight to `research.md` → `TRD.md`
(or even skip TRD too, per `AGENTS.md` §5's original one-file-edit
threshold) in that case. The failure mode this skill guards against is
"skipped the thinking," not "skipped the paperwork" — a two-line TRD for a
two-line change is correct, not lazy.

## What this is not

Not a stage-gate that blocks progress, not a template-filling exercise
disconnected from actual thinking, and not a replacement for `AGENTS.md`
§5's HVE gate (Hypothesis → Verify → Evidence), which still applies at
every phase boundary exactly as before. `spec_first.py` only scaffolds and
checks structure — the PRD and TRD's actual content is the agent doing real
requirements and design thinking, the same way `research.md` and
`progress.md` always required real work, not a filled-in form.
