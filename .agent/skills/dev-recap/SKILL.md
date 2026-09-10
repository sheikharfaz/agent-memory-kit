---
name: dev-recap
description: Close out a non-trivial implementation with a plain-English recap, a heuristic gap scan, and an optional quiz/walkthrough so the developer -- who did not write this code -- actually understands what shipped under their name. Trigger at the same moment as AGENTS.md's Definition of Done (§7), for any change beyond a one-line fix. Do NOT trigger for read-only questions, for changes the developer wrote themselves and just asked you to review, or mid-task before there is anything to recap.
---

# Skill: dev-recap

The other three skills make the agent faster and safer. This one exists for
a different reason: **the developer is accountable for code they didn't
write, and that's a real gap this kit should not pretend away.** A fast,
well-cited diff is not the same thing as an understood one.

## AI ethics stance -- read this before skipping the skill

This exists because of a specific risk, not a generic "AI ethics" box to
tick: an agent that always explains itself less than it could is optimizing
for looking finished, not for the developer's actual competence. That trades
short-term velocity for long-term understanding, and the debt lands on the
developer, not the agent. Concretely:

* **Informed consent, not a rubber stamp.** The developer should be able to
  explain, defend, and maintain what just shipped -- not just approve a diff
  that looked plausible. The recap is how that happens without re-reading
  every line yourself.
* **Never a dark pattern.** The quiz/walkthrough offer in step 4 below is
  genuinely optional every time. Never guilt, never gate a merge on it,
  never repeat the offer if declined once for this task.
* **Local and private, always.** Quiz results answer one question --
  "does this developer want this topic reinforced again?" -- for that
  developer, on their own machine. Nothing here reports results to a
  manager, a dashboard, CI, or anyone but the developer themselves. If you
  are wiring this into something that *would* surface results elsewhere,
  stop -- that is a different feature with a different ethics case, not
  this one.
* **Honesty over confidence.** The recap states what was verified and what
  wasn't, the same way the HVE gate (`AGENTS.md` §5) already requires.
  Never write a gap-free recap because writing gaps felt like undermining
  the work -- an unlisted gap is a bigger cost to the developer than an
  awkward line in a summary.

## When this fires

Same moment as `AGENTS.md` §7's Definition of Done, for anything beyond a
one-line fix: after tests/lint/build pass, before you tell the developer the
task is complete. Skip it for pure read/explain requests, and skip it if the
developer wrote the change themselves and only asked for a review.

## The five things every recap covers

Write these as your closing message, not as a file (a `.agent/work/<task>/`
progress note already exists if you're running RPI -- this is what you *say*
to the developer, distinct from that artifact). Keep it real, not
templated filler -- a two-line recap for a two-file change is correct.

**1. What changed, junior-dev pitched.** Plain English: what problem this
solves, the shape of the fix, and how the pieces connect -- cite
`path:line` the way `AGENTS.md` §1 already requires everywhere else. Assume
the reader can code but did not watch you write this.

**2. How it fits this project specifically.** Not generic best practice --
*this* codebase's own conventions. If `codebase-memory` is installed and
built here, ground this in it (`query.py impact <path>`, `changed`,
`callers`); if not, say you're going on direct inspection of neighbouring
files instead, per `AGENTS.md` §6. If something genuinely deviates from an
established local pattern, say so and say why (a real reason, or
`ASSUMPTION:` if you're not sure it was intentional).

**3. Gaps.** Run the heuristic scanner, cite what it finds honestly (it is a
lead generator, not proof -- same accuracy contract as `codebase-memory`):

```bash
python .agent/skills/dev-recap/recap_log.py gaps
```

Flags changed files with no obviously-matching test touched, new
TODO/FIXME/XXX markers introduced by the diff, and (if `codebase-memory` is
built) changed paths missing from its index. A clean result means *the
heuristic found nothing*, never *nothing is missing* -- add your own
judgment on top (logic correctness, edge cases, error handling) the way
`AGENTS.md` §7 already asks. State gaps found even when it's tempting not to.

**4. Offer to help it stick -- genuinely optional.** Ask, don't assume:

> Want to lock this in? I can quiz you on it (a few questions, no
> grading), walk through the diff piece by piece, or you can just move on.

If they take the quiz, ask 3-5 questions *you* generate from the actual
change (not a script -- this needs real understanding of what was built),
grounded in what's actually in the diff. Evaluate their answers
conversationally, then log the outcome for spaced-repetition-style recall
later:

```bash
python .agent/skills/dev-recap/recap_log.py record-quiz --topic "<task-slug>" --result understood|partial|confused
```

Log the recap itself either way (this also mirrors a note into
`session-memory` if that skill is installed, so it's recallable across
sessions too):

```bash
python .agent/skills/dev-recap/recap_log.py record-recap --task "<task-slug>" \
  --files "path/a.py,path/b.py" --summary "one paragraph, what and why"
```

At the start of a later session, check what's due for reinforcement instead
of re-explaining everything from scratch:

```bash
python .agent/skills/dev-recap/recap_log.py due-for-review
```

Ranks topics that were marked `partial`/`confused`, or haven't come up in
`--stale-days` (default 14), weakest/stalest first. This is a crude
frequency+recency heuristic, not a real spaced-repetition algorithm or a
model of what the developer actually remembers -- treat a `due-for-review`
hit as "worth a one-line check-in," not as evidence of anything.

**5. Assumptions and diversions -- always present, never optional.** Close
every recap with this, even when the honest answer is "none":

> **Assumptions & diversions:** none this time. *(or:)* Assumed the retry
> count should match the existing `src/http/client.py` default since the
> ticket didn't specify one -- flagged `ASSUMPTION:` above. Diverged from
> the plan by adding a null-check in `parse.py` after testing surfaced a
> crash the plan hadn't accounted for.

This is the same discipline `AGENTS.md` §5's HVE gate already requires
mid-task; the point of restating it here is that it's the *last* thing the
developer reads, not buried mid-transcript where it's easy to miss.

## What this is not

Not a gate, not a scorecard, not a substitute for code review, and not
proof of correctness -- `gaps` is heuristic (see its own caveats above) and
the quiz is a comprehension check, not a test suite. It does not run
without a trigger (see "When this fires"), and it never blocks anything --
if the developer wants to skip straight past step 4, that's the whole point
of "genuinely optional."
