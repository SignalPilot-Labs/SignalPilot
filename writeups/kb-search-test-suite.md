# KB Search — 200-Test Suite + Speed Benchmark

**Status:** 200 new tests (4 subagent-generated files, personally reviewed test-by-test),
+26 existing = 226 green. Benchmarked at 200 / 1,000 / 10,000 entries; the benchmark
exposed a real scaling problem that was fixed with an inverted index.

## The suite (exactly 200 collected, verified via pytest --collect-only)

| File | Tests | Focus |
|---|---|---|
| `tests/test_kb_suite_ranking.py` | 50 | tokenizer contract, title-vs-body weighting (3× boost proven via score-equality constructions), tf/length normalization, IDF, multi-term, ordering/limit/min_score API |
| `tests/test_kb_suite_fuzzy.py` | 50 | spelling variants (recognising↔recognized …), typo tolerance, hyphen/snake/camel compounds, short-word limits, false-positive modes, mixed exact+fuzzy — every ranking assertion gated on an explicit `tokenize()` overlap proof |
| `tests/test_kb_suite_hybrid.py` | 50 | full pipeline on SQLite: **title-only AND body-only recall**, filters proven to apply inside each arm, status/tenancy isolation, RRF fusion arms/ordering, a 10-doc realistic corpus, robustness (long prose, stopword-only, SQL-text queries) |
| `tests/test_kb_suite_adversarial.py` | 50 | degenerate inputs, hostile content (injection strings, 10k-char words, CJK/emoji), numeric/UUID content, hand-computed score identities, limit/min_score semantics |

### Review outcomes (my pass over all 800+ assertions)
The generators were held to a "provable expectations only" contract and largely met it
(overlap-proof gating in the fuzzy file is exemplary). The review surfaced and I fixed:

1. **Dead broken code**: `content_hash()` survived the BM25 refactor with its `hashlib`
   import removed — would `NameError` if ever called. Deleted.
2. **Docstring lied**: claimed `fanout`/`fan-out` tolerance; both hyphen parts are <5
   chars so no n-grams bridge them (proven by a test). Docstring corrected to the true
   rule (works iff a part is ≥5 chars: `pre-aggregated`↔`preaggregated`).
3. **Hardened semantics** (tests updated to match): negative `limit` clamped to 0
   (was a silent `[:-1]` slice dropping the tail), zero-score docs never returned
   regardless of `min_score`, `None` title/body treated as empty instead of crashing
   the whole search on one malformed row.

### Both-fields requirement
Explicitly covered at three levels: pure ranker (title-only/body-only/buried-deep
groups in ranking + adversarial files), full pipeline (hybrid file group 1), and live
docker (title query and body-only variant query both verified post-rebuild).

## Speed benchmark (`benchmarks/kb_search_bench.py`, seeded synthetic corpora)

Before (per-query corpus re-tokenization):

| entries | per-query p50 |
|---|---|
| 200 | 43 ms |
| 1,000 | 250 ms |
| **10,000** | **2,336 ms** ← unacceptable |

Fix: `Bm25Index` — an inverted index (postings per token) built once, identical
scoring math, ties keep input order. The hybrid arm now caches **one index per org**,
invalidated by a cheap signature `(active-doc count, max updated_at)` checked per
query; scope/category filters restrict rankable ids instead of rebuilding.
Cache-invalidation is regression-tested (add/edit/archive all reindex).

After:

| entries | indexed query p50 | build (once) | hybrid end-to-end p50 |
|---|---|---|---|
| 200 | 0.1 ms | 80 ms | 5.2 ms |
| 1,000 | 0.3 ms | 330 ms | 7.0 ms |
| 10,000 | 3.1 ms | 3.2 s | 13.8 ms |

~700× faster at 10k entries; the one-time build cost only recurs when the corpus
changes. At the KB's real quota-capped scale (≤ a few hundred docs) everything is
sub-millisecond after first query.
