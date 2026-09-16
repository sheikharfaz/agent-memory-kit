#!/usr/bin/env python3
"""
agent-memory-kit :: shared retrieval primitives.

One code-aware tokenizer and one BM25 scorer, used by `session-memory`'s
cross-session recall and `codebase-memory`'s `find` verb. A leaf module: it
imports nothing from any skill, so a skill can be installed without it and
degrade to its own previous behaviour (see each caller's guarded import).

Python 3.8+, standard library only, no network, no state, no I/O.

Why this exists
---------------
The original `session-memory` tokenizer lowercased before splitting, so
every camelCase and PascalCase identifier became one opaque term:

    "getUserById handles auth"  ->  ["getuserbyid", "handles", "auth"]

A developer asking "where do we look up a user by id" weeks later shares no
vocabulary with that entry at all, and lexical recall correctly -- and
uselessly -- returns nothing. Since the subject matter of this whole kit is
source code, and camelCase covers most of JS, TS, Java, Go, C# and Swift,
that one line capped recall quality for the majority of real repositories.
`evals/` measures the difference rather than assuming it.
"""

import math
import re
from collections import Counter

# Ordered alternation, and the order matters: `[A-Z]+(?![a-z])` must come
# first so an acronym run splits correctly -- "HTTPServerError" becomes
# HTTP + Server + Error, where a naive `[A-Z][a-z]*` split yields the
# useless H + T + T + P + Server + Error.
IDENT_PART = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|[0-9]+")
WORD = re.compile(r"[A-Za-z0-9]+")

# Deliberately small and generic. Callers with a tuned list (session-memory
# has one) pass their own; this default exists so `codebase-memory` does not
# have to invent one to use the same code path.
DEFAULT_STOPWORDS = frozenset("""
the a an and or but if then than that this these those is are was were be been
being do does did to of in on at by for with from as it its into over under
""".split())

K1 = 1.2   # term-frequency saturation; 1.2-1.5 is the standard range
B = 0.75   # document-length normalisation strength


def split_identifier(raw):
    """`refreshUserAuthToken` -> ['refresh', 'user', 'auth', 'token'].
    Returns [] when there is nothing to split beyond the token itself."""
    parts = IDENT_PART.findall(raw)
    if len(parts) <= 1:
        return []
    return [p.lower() for p in parts]


def tokenize(text, stopwords=DEFAULT_STOPWORDS, min_len=2):
    """Split into terms, keeping BOTH the whole identifier and its parts.

    Emitting both is the deliberate trade: the whole term keeps an
    exact-name query precise (`findUserById` still scores highest against
    itself), while the parts make a plain-words query possible at all. It
    inflates document length, which is exactly what BM25's `b` parameter is
    for -- and `evals/` is the check that the trade actually paid off.
    """
    out = []
    for raw in WORD.findall(text or ""):
        whole = raw.lower()
        if len(whole) >= min_len and whole not in stopwords:
            out.append(whole)
        for part in split_identifier(raw):
            if len(part) >= min_len and part not in stopwords and part != whole:
                out.append(part)
    return out


class BM25:
    """Okapi BM25 over pre-tokenized documents.

    Scores are normalised by the query's *achievable* maximum, so they land
    in [0, 1) and keep the "roughly, what fraction of this query matched"
    reading that the cosine score they replace already had. That matters:
    `session-memory`'s MIN_SCORE floor and the hook-injection thresholds are
    calibrated against that reading, and an unbounded raw BM25 score would
    have silently changed what gets surfaced to an agent.
    """

    def __init__(self, docs_tokens, k1=K1, b=B):
        self.k1 = k1
        self.b = b
        self.docs = [Counter(toks) for toks in docs_tokens]
        self.lengths = [sum(c.values()) for c in self.docs]
        n = len(self.docs) or 1
        self.avgdl = (sum(self.lengths) / float(n)) or 1.0
        df = Counter()
        for c in self.docs:
            df.update(c.keys())
        # Lucene-style IDF: always positive, so a term present in every
        # document contributes ~0 rather than going negative and actively
        # penalising a document for containing it.
        self.idf = {t: math.log(1.0 + (n - c + 0.5) / (c + 0.5))
                    for t, c in df.items()}

    def score(self, query_tokens):
        """Returns one normalised score per document, same order as input."""
        terms = [t for t in dict.fromkeys(query_tokens) if t in self.idf]
        if not terms:
            return [0.0] * len(self.docs)
        ceiling = sum(self.idf[t] for t in terms) * (self.k1 + 1.0)
        if ceiling <= 0:
            return [0.0] * len(self.docs)

        scores = []
        for counts, length in zip(self.docs, self.lengths):
            norm = self.k1 * (1.0 - self.b + self.b * (length / self.avgdl))
            total = 0.0
            for t in terms:
                f = counts.get(t, 0)
                if f:
                    total += self.idf[t] * (f * (self.k1 + 1.0)) / (f + norm)
            scores.append(total / ceiling)
        return scores
