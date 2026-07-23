"""Pure-Python BM25 ranking for knowledge-base search.

No embedding models, no vector storage, no background indexing — Okapi BM25
computed entirely in-process. KB corpora are quota-capped to megabytes, so
even cold scoring is fast; ``Bm25Index`` additionally lets callers build the
inverted index once and query it many times (the hybrid-search arm caches one
index per org), which keeps large corpora (10k+ docs) at millisecond query
latency instead of re-tokenizing the corpus per query.

Tokenization is words + character 4-grams of words ≥5 chars: the n-grams give
typo and spelling-variant tolerance (recognising/recognized, warehouse with a
dropped letter) that plain word matching lacks, while BM25's IDF
automatically down-weights the n-grams shared by everything. Known limits:
words <5 chars get no grams (no fuzzy tolerance), and hyphenated compounds
only bridge their closed forms when a part is ≥5 chars ('pre-aggregated' ↔
'preaggregated' works; 'fan-out' ↔ 'fanout' does not — both parts too short).
"""

from __future__ import annotations

import math
import re
from collections import Counter

_WORD_RE = re.compile(r"[a-z0-9_]+")
_K1 = 1.5
_B = 0.75
_TITLE_WEIGHT = 3  # title tokens count this many times (field boost)
_NGRAM_MIN_WORD = 5
_NGRAM_N = 4


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens plus char 4-grams of words ≥5 chars."""
    tokens: list[str] = []
    for word in _WORD_RE.findall(text.lower()):
        tokens.append(word)
        if len(word) >= _NGRAM_MIN_WORD:
            for i in range(len(word) - _NGRAM_N + 1):
                tokens.append("#" + word[i : i + _NGRAM_N])
    return tokens


class Bm25Index:
    """Inverted BM25 index over (doc_id, title, body) tuples.

    Build once (O(corpus tokens)), query many times (O(postings of the query's
    tokens) — independent of corpus size for selective queries). Scoring is
    exactly ``bm25_rank``'s: title tokens counted ``_TITLE_WEIGHT`` times so
    title hits outrank body-only hits at equal term frequency.
    """

    def __init__(self, docs: list[tuple[str, str, str]]) -> None:
        self._doc_ids: list[str] = []
        self._doc_len: list[int] = []
        # token -> [(doc_index, term_frequency), ...]
        self._postings: dict[str, list[tuple[int, int]]] = {}
        total_len = 0
        for doc_id, title, body in docs:
            counts = Counter(tokenize(body or ""))
            for tok, n in Counter(tokenize(title or "")).items():
                counts[tok] += n * _TITLE_WEIGHT
            idx = len(self._doc_ids)
            self._doc_ids.append(doc_id)
            doc_len = sum(counts.values())
            self._doc_len.append(doc_len)
            total_len += doc_len
            for tok, tf in counts.items():
                self._postings.setdefault(tok, []).append((idx, tf))
        self._n_docs = len(self._doc_ids)
        self._avg_len = total_len / self._n_docs if self._n_docs else 1.0

    def __len__(self) -> int:
        return self._n_docs

    def rank(
        self,
        query: str,
        *,
        limit: int = 50,
        min_score: float = 0.0,
        allowed_ids: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        """(doc_id, score) sorted by BM25 score descending.

        Only docs with a strictly positive score are returned (a zero score
        means no query term matched, regardless of ``min_score``). ``limit``
        is clamped at 0. ``allowed_ids`` restricts results to a subset of doc
        ids (used for scope/category filtering against a whole-org index).
        """
        query_tokens = set(tokenize(query))
        if not query_tokens or not self._n_docs:
            return []

        idf: dict[str, float] = {}
        for tok in query_tokens:
            postings = self._postings.get(tok)
            if postings:
                df = len(postings)
                idf[tok] = math.log(1.0 + (self._n_docs - df + 0.5) / (df + 0.5))
        if not idf:
            return []

        scores: dict[int, float] = {}
        k1_b_over_avg = _K1 * _B / self._avg_len
        k1_one_minus_b = _K1 * (1 - _B)
        for tok, tok_idf in idf.items():
            for doc_idx, tf in self._postings[tok]:
                denom = tf + k1_one_minus_b + k1_b_over_avg * self._doc_len[doc_idx]
                scores[doc_idx] = scores.get(doc_idx, 0.0) + tok_idf * (tf * (_K1 + 1)) / denom

        # Build in doc-input order so equal-score ties keep input order,
        # matching the pre-index implementation.
        scored = [
            (self._doc_ids[i], score)
            for i, score in sorted(scores.items())
            if score > 0.0
            and score > min_score
            and (allowed_ids is None or self._doc_ids[i] in allowed_ids)
        ]
        scored.sort(key=lambda p: p[1], reverse=True)
        return scored[: max(0, limit)]


def bm25_rank(
    query: str,
    docs: list[tuple[str, str, str]],  # (doc_id, title, body)
    *,
    limit: int = 50,
    min_score: float = 0.0,
) -> list[tuple[str, float]]:
    """One-shot convenience: build an index over ``docs`` and rank ``query``."""
    return Bm25Index(docs).rank(query, limit=limit, min_score=min_score)
