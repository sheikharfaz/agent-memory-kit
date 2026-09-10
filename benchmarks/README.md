# Benchmarks

A reproducible comparison: how many tokens does an AI coding agent spend
answering a fixed set of "getting oriented in an unfamiliar repo" questions,
with `codebase-memory` versus without it? Run against two real, public
repositories — not synthetic examples.

```bash
git clone https://github.com/psf/requests.git /tmp/requests
git clone https://github.com/django/django.git /tmp/django

python3 benchmarks/token_comparison.py --repo /tmp/requests --spec benchmarks/specs/requests.json
python3 benchmarks/token_comparison.py --repo /tmp/django   --spec benchmarks/specs/django.json
```

Nothing here calls an LLM. This measures the size of the context an agent
would have to read to answer each question — the input tokens any
provider's pricing bills against — not model behaviour or answer quality.

## Results

| Repo | Files (parsed) | Symbols | Index build | `CODEBASE_MAP.md` | Naive tokens (4 questions) | Kit-assisted tokens | Ratio |
|---|---|---|---|---|---|---|---|
| [psf/requests](https://github.com/psf/requests) | 118 (37) | 797 | 0.22s | 1,051 | 85,220 | 1,667 | **51.1x** |
| [django/django](https://github.com/django/django) | 6,904 (2,979) | 43,170 | 4.43s | 2,912 | 167,437 | 4,631 | **36.2x** |

Raw output: [`results/requests.json`](results/requests.json) ·
[`results/django.json`](results/django.json) ·
[`results/requests.txt`](results/requests.txt) ·
[`results/django.txt`](results/django.txt).

### Per-question breakdown (django/django)

| Question | Naive tokens | Kit tokens |
|---|---|---|
| Where is the `QuerySet` class defined? | 30,423 | 16 |
| What calls `force_str`? | 52,543 | 252 |
| What does `db/models/query.py` contain and depend on? | 30,408 | 472 |
| What breaks if `db/models/base.py` changes? | 54,063 | 979 |

The fourth question is the most telling: `codebase-memory` reports the real
blast radius of `db/models/base.py` — 35 files that call into it directly,
272 that import it by name, 155 covering test files — for 979 tokens. The
naive baseline's 54,063 tokens reflects reading only the first 6 files a
grep for its imports turned up, **not** all ~460 of them; see Limitations.

## Methodology

Two baselines are compared, for four question kinds, applied identically to
both repos with only the target symbol/file swapped (see
[`specs/requests.json`](specs/requests.json) and
[`specs/django.json`](specs/django.json)):

**Without `codebase-memory` (naive baseline).** For "where is X defined"
and "what calls X", grep the repo for the pattern, then read the full
content of every distinct file the grep matched, in match order, capped at
6 files — a bounded, realistic simulation of an agent opening a few
promising files to confirm the real answer, not the strawman of reading
the whole repository. For "what does file F contain", read F in full — no
grep needed, that's literally what an agent does today without an index.
For "what breaks if F changes", grep for imports of F's module across the
repo and read the matched files the same capped way. A file already read
earlier in the session isn't re-charged if a later question touches it
again, the same way a real agent wouldn't re-read something already in its
context.

**With `codebase-memory`.** `CODEBASE_MAP.md` is read once for the whole
session — exactly what `AGENTS.md` §2 already requires at session start —
then the single most appropriate `query.py <verb>` answers each question.
Cost = the map (once) + each query's output, summed.

Token counts use `tiktoken`'s `cl100k_base` encoding if installed
(`pip install tiktoken`, optional — not a kit dependency, just a more
precise counter for this benchmark), otherwise a chars/4 heuristic — the
same approximation this kit's own `AGENTS.md` token-budget checks use. The
results above used chars/4 (`tiktoken` wasn't installed for this run — see
`"counter"` in the raw JSON for what any given run actually used). Whichever
counter is active, both sides are measured with it, so the *ratio* is
meaningful regardless of which one ran.

## Limitations, stated plainly

- **The naive baseline is capped, and that cap favours the naive side.**
  Reading only 6 files understates what a real, unaided attempt at a
  *complete* answer would cost — for `db/models/base.py`'s blast radius,
  the real number of files involved is closer to 460 than 6. The reported
  ratios are a floor, not a ceiling.
- **chars/4 is an approximation**, not any specific model's real
  tokenizer. Install `tiktoken` for exact `cl100k_base` counts; the
  relative comparison holds either way since both sides use the same
  counter.
- **This is a token-size comparison, not an accuracy comparison.** It says
  nothing about whether the naive approach or the kit-assisted one gives a
  *better* answer — `codebase-memory`'s own accuracy contract (in the main
  README and `SKILL.md`) is the honest treatment of that question.
- **Four question kinds, two repos.** This is a representative sample of
  "getting oriented" questions, not an exhaustive workload. Different
  question mixes will show different ratios — run the script against your
  own repo and questions for a number that applies to you.

## Illustrative cost

Token counts translate to real cost via whatever your model provider
charges per input token — that rate changes over time and by model, so
compute it with your own current pricing rather than trusting a number
frozen in this file. As one illustrative reference point: at $3 per
million input tokens (a commonly cited mid-tier rate at the time of
writing, *not a quote* — check your provider's current pricing page), the
django/django session above would run about $0.50 naive versus $0.01
kit-assisted for those four questions — and that gap compounds every time
a new session re-explores the same repo from zero.

## Reproducing this

```bash
git clone https://github.com/sheikharfaz/agent-memory-kit.git
cd agent-memory-kit
git clone --depth 1 https://github.com/psf/requests.git /tmp/requests
git clone --depth 1 https://github.com/django/django.git /tmp/django
python3 benchmarks/token_comparison.py --repo /tmp/requests --spec benchmarks/specs/requests.json --json
python3 benchmarks/token_comparison.py --repo /tmp/django   --spec benchmarks/specs/django.json --json
```

Add `--skip-build` to reuse an index you already built. Write a new
`specs/<name>.json` (same shape as the two shipped here) to run this
against any other repo and question set.
