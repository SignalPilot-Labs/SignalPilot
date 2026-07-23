"""Pure-Python BM25 ranking for knowledge-base search.

No embedding models, no vector storage, no background indexing — Okapi BM25
computed in-process over the org's active docs at query time. KB corpora are
quota-capped to megabytes (≤ a few hundred docs), so scoring the whole corpus
per query is sub-millisecond and needs no persistent index.

Tokenization is words + character 4-grams of longer words: the n-grams give
typo and variant tolerance (recognising/recognized, fanout/fan-out) that
plain word matching lacks, while BM25's IDF automatically down-weights the
n-grams shared by everything.
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


def bm25_rank(
    query: str,
    docs: list[tuple[str, str, str]],  # (doc_id, title, body)
    *,
    limit: int = 50,
    min_score: float = 0.0,
) -> list[tuple[str, float]]:
    """(doc_id, score) sorted by BM25 score descending.

    Title tokens are counted _TITLE_WEIGHT times so title hits outrank
    body-only hits at equal term frequency.
    """
    query_tokens = set(tokenize(query))
    if not query_tokens or not docs:
        return []

    doc_freqs: list[tuple[str, Counter]] = []
    df: Counter = Counter()
    total_len = 0
    for doc_id, title, body in docs:
        counts = Counter(tokenize(body))
        title_counts = Counter(tokenize(title))
        for tok, n in title_counts.items():
            counts[tok] += n * _TITLE_WEIGHT
        doc_freqs.append((doc_id, counts))
        total_len += sum(counts.values())
        for tok in counts:
            if tok in query_tokens:
                df[tok] += 1

    n_docs = len(docs)
    avg_len = total_len / n_docs if n_docs else 1.0

    idf = {
        tok: math.log(1.0 + (n_docs - df[tok] + 0.5) / (df[tok] + 0.5))
        for tok in query_tokens
        if df.get(tok)
    }
    if not idf:
        return []

    scored: list[tuple[str, float]] = []
    for doc_id, counts in doc_freqs:
        doc_len = sum(counts.values())
        score = 0.0
        for tok, tok_idf in idf.items():
            tf = counts.get(tok, 0)
            if not tf:
                continue
            score += tok_idf * (tf * (_K1 + 1)) / (tf + _K1 * (1 - _B + _B * doc_len / avg_len))
        if score > min_score:
            scored.append((doc_id, score))
    scored.sort(key=lambda p: p[1], reverse=True)
    return scored[:limit]
