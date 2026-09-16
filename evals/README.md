# Evals — does it recall the *right* thing?

`benchmarks/` answers "how many tokens does this save?". This answers the
harder question: **when `session-memory` recalls something, is it the thing
you actually wanted?**

Every serious agent-memory product publishes a retrieval-quality number.
Until now this kit published only a cost number, which is the cheap half of
the argument. This directory is the other half, including the parts that
still do not work.

```bash
python3 evals/recall_eval.py                  # current default
python3 evals/recall_eval.py --scorer tfidf   # the pre-v0.5.0 behaviour
python3 evals/recall_eval.py --scorer bm25 --json
```

No dependencies, no network, no LLM call — same contract as the rest of the
kit. Roughly a second to run.

## Results

Both arms, same dataset, same harness, one command apart:

| Retrieval method | recall@1 | recall@3 | recall@5 | MRR | queries with no hit |
|---|---|---|---|---|---|
| `tfidf` — v0.4.0: plain tokenizer + TF-IDF cosine | 0.450 | 0.625 | 0.675 | 0.588 | 6 / 20 |
| `bm25` — v0.5.0: code-aware tokenizer + Okapi BM25 | **0.675** | **0.775** | **0.825** | **0.787** | **3 / 20** |

Per-query, the change is **5 better, 15 unchanged, 0 worse**. Broken down by
what each query was testing:

| Bucket | What it tests | recall@1 tfidf → bm25 | recall@3 tfidf → bm25 |
|---|---|---|---|
| `literal` | wording overlaps the entry | 0.583 → 0.667 | 0.750 → 0.750 |
| `identifier` | asks in plain words about a camelCase symbol | 0.450 → **0.850** | 0.700 → **1.000** |
| `paraphrase` | shares no vocabulary with the answer at all | 0.250 → 0.250 | 0.250 → 0.250 |

Raw output: [`results/`](results/).

## What changed, and why it mattered

The v0.4.0 tokenizer lowercased text *before* splitting it, so every
camelCase and PascalCase identifier became one opaque term:

```
tokenize("Renamed getUserById to findUserById")
  ->  ['renamed', 'getuserbyid', 'finduserbyid']
```

Ask "where do we look up a user by id" a week later and you share **zero**
terms with that entry. TF-IDF scores it 0.0, and recall returns nothing —
correctly, and uselessly. Since camelCase covers most of JS, TS, Java, Go,
C# and Swift, that single line capped recall for the majority of real
repositories — in a memory system whose entire subject matter is code.

`.agent/lib/retrieval.py` now splits identifiers into parts while keeping
the whole term (so exact-name queries stay precise), and ranks with Okapi
BM25 instead of TF-IDF cosine, which handles this corpus's very uneven
document lengths — one-line prompts next to 4,000-character assistant turns
— more sensibly. The `identifier` row above is that fix, measured.

## The `paraphrase` row does not move, and that is the honest headline

Three queries miss under both methods:

- *"which parts of the system talk to the outside world"* → the webhook and
  email entries. No shared vocabulary.
- *"is there anything here we could safely delete"* → the unused Postgres
  implementation and the mystery legacy adapter.
- *"what did we make faster recently"* → the N+1 fix that took p95 from
  1.8s to 220ms.

A human reads all three instantly. Lexical retrieval cannot do any of them,
and no amount of tuning `k1` and `b` will change that — it is the method's
ceiling, not a bug in this implementation. Fixing it properly needs
embeddings, which would mean a model download, a vector store, and the end
of the zero-dependency, no-network, installs-on-a-locked-down-laptop
property that is the entire reason this kit exists. That trade is refused
deliberately, and this table is how you hold us to saying so out loud.

`recent` (chronological, no matching) remains the fallback when `recall`
comes up empty — see `session-memory/SKILL.md`.

## Methodology, and where it is weak

**The corpus.** 40 entries written as a realistic multi-session developer
log for one service — payments, auth, performance, CI, config, compliance —
with the mix of prompts, assistant turns, and notes the hooks actually
record. It includes deliberate distractors: entries that share vocabulary
with a query without being its answer (a generic retry helper next to the
payment retry decision; a rename note next to a lookup question).

**The queries.** 20, each labelled with the bucket it is testing and the
entry ids that genuinely answer it.

**The measured path is the real one.** Entries are loaded through the actual
`append_entry()` and scored through the actual `recall()`, so redaction,
the 4,000-char truncation, the `MIN_SCORE` floor and the weight boost all
sit inside what is being measured. The harness warns loudly if redaction
altered any entry, because a silently redacted corpus would change the thing
under test.

**Authoring bias — stated plainly.** We wrote both the entries and the
queries, which is the standard way a self-reported eval flatters itself.
Two mitigations, neither of them complete: the entries were written first,
as a log, with no queries in mind; then the queries were written afterwards
in the wording a developer would use later, deliberately not by copying
phrases out of the entries. The `paraphrase` bucket exists precisely because
a self-serving dataset would have quietly omitted it. Treat these numbers as
"this method, on this kind of content" — not as a leaderboard position.

**Not comparable to LongMemEval or LOCOMO.** Those are public benchmarks
over conversational-assistant histories, with their own splits and scoring.
This is a self-authored, 40-entry, developer-session corpus. Any sentence of
the form "we score X where Mem0 scores Y" would be false, and you will not
find one in this repo.

**Small.** 20 queries. A single query flipping moves recall@1 by five
points. The 5/15/0 per-query breakdown is the more robust signal than any
single aggregate, and it is printed by default.

**It costs something.** Splitting identifiers roughly doubles the number of
terms per entry, and BM25 does more work per document than cosine. Measured
at the 4,000-entry prune cap — the largest corpus the product allows —
recall went from ~17ms to ~40ms per query. That sits inside a
`UserPromptSubmit` hook, immediately before an LLM call that takes seconds,
so it is not a latency anyone can perceive; it is still a real 2.3x, and
worth knowing if you raise the cap a long way above the default.

## Adding your own dataset

Same shape as [`datasets/session_recall.json`](datasets/session_recall.json):
`entries[]` with `{id, session, kind, text}`, `queries[]` with
`{id, bucket, text, gold: [entry ids]}`. Then:

```bash
python3 evals/recall_eval.py --dataset path/to/yours.json
```

A dataset drawn from your own repo's real sessions is worth more than this
one, because it has none of the authoring bias above. If it shows this kit
doing badly on your content, that is a genuinely useful bug report.
