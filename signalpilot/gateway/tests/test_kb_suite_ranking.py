"""Core-ranking correctness suite for gateway.store.kb_rank (tokenize + bm25_rank).

Design rules for provability:
- Query terms and filler words are kept <= 4 chars so tokenize() emits ONLY the
  word itself (no char 4-grams), making token overlap between docs exactly what
  the corpus construction says it is.
- Filler tokens are distinct per doc (x1, y1, ...) unless a test is explicitly
  about term frequency, so IDF of fillers never interferes.
- Winners are constructed with unambiguous margins (term present vs absent, or
  strictly higher tf at identical doc length), never near-ties. Exact-equality
  assertions are used only where the algorithm's inputs are literally identical.
"""

from __future__ import annotations

from gateway.store.kb_rank import bm25_rank, tokenize


def _ids(results):
    return [doc_id for doc_id, _ in results]


def _scores(results):
    return [score for _, score in results]


# ---------------------------------------------------------------------------
# 1. tokenize()
# ---------------------------------------------------------------------------


class TestTokenize:
    def test_extracts_simple_words(self):
        assert tokenize("cat dog") == ["cat", "dog"]

    def test_lowercases_input(self):
        assert tokenize("CAT Dog") == ["cat", "dog"]

    def test_underscore_kept_inside_token(self):
        # "foo_bar" is one 7-char word -> word + 4 grams, never split at "_".
        tokens = tokenize("foo_bar")
        assert tokens[0] == "foo_bar"
        assert "foo" not in tokens and "bar" not in tokens

    def test_digits_kept_inside_token(self):
        tokens = tokenize("abc123")
        assert tokens[0] == "abc123"

    def test_hyphen_splits_words(self):
        # Both halves are < 5 chars, so no n-grams appear.
        assert tokenize("fan-out") == ["fan", "out"]

    def test_punctuation_splits_words(self):
        assert tokenize("cat,dog!bee") == ["cat", "dog", "bee"]

    def test_four_char_word_has_no_ngrams(self):
        assert tokenize("word") == ["word"]

    def test_five_char_word_has_exactly_two_ngrams(self):
        # len 5 -> 5 - 4 + 1 = 2 grams.
        assert tokenize("abcde") == ["abcde", "#abcd", "#bcde"]

    def test_six_char_word_has_exactly_three_ngrams(self):
        # len 6 -> 6 - 4 + 1 = 3 grams.
        assert tokenize("abcdef") == ["abcdef", "#abcd", "#bcde", "#cdef"]

    def test_ngrams_are_hash_prefixed(self):
        tokens = tokenize("tokenizer")
        grams = [t for t in tokens if t != "tokenizer"]
        assert grams and all(t.startswith("#") for t in grams)

    def test_ngram_content_is_sliding_window(self):
        assert tokenize("query") == ["query", "#quer", "#uery"]

    def test_empty_and_punct_only_strings_yield_no_tokens(self):
        assert tokenize("") == []
        assert tokenize("!!! ... ---") == []


# ---------------------------------------------------------------------------
# 2. Title vs body weighting
# ---------------------------------------------------------------------------


class TestTitleWeighting:
    def test_title_match_beats_body_match_at_equal_raw_tf(self):
        # A: tf(cat)=3 (title boost), doc_len=3+2=5.
        # B: tf(cat)=1, doc_len=6+1=7. A wins on both tf and length.
        docs = [
            ("a", "cat", "x1 x2"),
            ("b", "y1 y2", "cat"),
        ]
        assert _ids(bm25_rank("cat", docs)) == ["a", "b"]

    def test_title_occurrence_counts_exactly_three_times(self):
        # Identical token Counters ({cat:3, aa:1, bb:1}) -> identical scores.
        docs = [
            ("a", "cat", "aa bb"),
            ("b", "", "cat cat cat aa bb"),
        ]
        results = dict(bm25_rank("cat", docs))
        assert abs(results["a"] - results["b"]) < 1e-12

    def test_two_title_occurrences_beat_one_at_equal_doc_len(self):
        # A: title "cat cat" -> tf=6, len=6+2=8. B: title "cat z1" -> tf=3, len=6+2=8.
        docs = [
            ("a", "cat cat", "x1 x2"),
            ("b", "cat z1", "y1 y2"),
        ]
        assert _ids(bm25_rank("cat", docs)) == ["a", "b"]

    def test_title_plus_body_beats_title_only_at_equal_doc_len(self):
        # A: tf=3+1=4, len=3+2=5.  B: tf=3, len=3+2=5.
        docs = [
            ("a", "cat", "cat x1"),
            ("b", "cat", "y1 y2"),
        ]
        assert _ids(bm25_rank("cat", docs)) == ["a", "b"]

    def test_title_tokens_inflate_doc_length(self):
        # Same tf(cat)=1 (body). A has extra title fillers -> doc_len 1+9=10
        # vs B doc_len 1. Shorter doc must score higher.
        docs = [
            ("a", "t1 t2 t3", "cat"),
            ("b", "", "cat"),
        ]
        assert _ids(bm25_rank("cat", docs)) == ["b", "a"]


# ---------------------------------------------------------------------------
# 3. Term frequency and length normalization
# ---------------------------------------------------------------------------


class TestTermFrequency:
    def test_three_occurrences_beat_one_at_equal_doc_len(self):
        docs = [
            ("a", "", "cat cat cat x1 x2"),
            ("b", "", "cat y1 y2 y3 y4"),
        ]
        assert _ids(bm25_rank("cat", docs)) == ["a", "b"]

    def test_five_occurrences_beat_one_at_equal_doc_len(self):
        docs = [
            ("a", "", "cat cat cat cat cat x1"),
            ("b", "", "cat y1 y2 y3 y4 y5"),
        ]
        assert _ids(bm25_rank("cat", docs)) == ["a", "b"]

    def test_two_occurrences_beat_one_at_equal_doc_len(self):
        docs = [
            ("a", "", "cat cat x1"),
            ("b", "", "cat y1 y2"),
        ]
        assert _ids(bm25_rank("cat", docs)) == ["a", "b"]

    def test_same_tf_shorter_doc_wins(self):
        # tf=1 both; doc_len 1 vs 8 -> smaller BM25 denominator for A.
        docs = [
            ("a", "", "cat"),
            ("b", "", "cat y1 y2 y3 y4 y5 y6 y7"),
        ]
        assert _ids(bm25_rank("cat", docs)) == ["a", "b"]

    def test_matching_doc_scores_positive(self):
        docs = [("a", "", "cat x1"), ("b", "", "y1 y2")]
        results = bm25_rank("cat", docs)
        assert _ids(results) == ["a"] and results[0][1] > 0.0


# ---------------------------------------------------------------------------
# 4. IDF
# ---------------------------------------------------------------------------


class TestIdf:
    def test_rare_term_outranks_common_term(self):
        # df(rare)=1, df(comm)=3 over n=4. A and B have identical tf=1 and
        # doc_len=2, so A (rare) must strictly outrank B (comm).
        docs = [
            ("a", "", "rare x1"),
            ("b", "", "comm y1"),
            ("c", "", "comm z1"),
            ("d", "", "comm w1"),
        ]
        results = bm25_rank("rare comm", docs)
        assert _ids(results)[0] == "a"
        assert dict(results)["a"] > dict(results)["b"]

    def test_term_in_every_doc_still_has_positive_idf(self):
        # df=n -> idf = log(1 + 0.5/(n+0.5)) > 0, so all docs are returned.
        docs = [("a", "", "comm x1"), ("b", "", "comm y1"), ("c", "", "comm z1")]
        results = bm25_rank("comm", docs)
        assert sorted(_ids(results)) == ["a", "b", "c"]
        assert all(s > 0.0 for s in _scores(results))

    def test_query_term_absent_from_corpus_returns_empty(self):
        docs = [("a", "", "x1 x2"), ("b", "", "y1 y2")]
        assert bm25_rank("zzzz", docs) == []

    def test_rare_plus_common_beats_common_only_at_equal_len(self):
        # A matches comm (same tf/len as B) plus rare -> strict superset score.
        docs = [
            ("a", "", "rare comm x1"),
            ("b", "", "comm y1 y2"),
            ("c", "", "comm z1 z2"),
        ]
        assert _ids(bm25_rank("rare comm", docs))[0] == "a"


# ---------------------------------------------------------------------------
# 5. Multi-term queries
# ---------------------------------------------------------------------------


class TestMultiTerm:
    def test_doc_matching_both_terms_beats_doc_matching_one(self):
        # Equal doc lengths; A's per-term denominators equal B's, and A adds a
        # second strictly-positive term contribution.
        docs = [
            ("a", "", "cat dog"),
            ("b", "", "cat x1"),
            ("c", "", "y1 y2"),
        ]
        assert _ids(bm25_rank("cat dog", docs))[0] == "a"

    def test_partial_matchers_are_still_returned(self):
        docs = [
            ("a", "", "cat dog"),
            ("b", "", "cat x1"),
            ("c", "", "dog y1"),
        ]
        assert sorted(_ids(bm25_rank("cat dog", docs))) == ["a", "b", "c"]

    def test_full_coverage_superset_outranks_at_equal_len(self):
        # A = B's match profile (cat tf=1, len=3) plus a dog match.
        docs = [
            ("a", "", "cat dog x1"),
            ("b", "", "cat y1 y2"),
        ]
        assert _ids(bm25_rank("cat dog", docs)) == ["a", "b"]

    def test_non_matching_doc_excluded_from_multi_term_results(self):
        docs = [
            ("a", "", "cat dog"),
            ("b", "", "x1 x2"),
        ]
        assert _ids(bm25_rank("cat dog", docs)) == ["a"]

    def test_duplicate_query_terms_collapse_to_set(self):
        docs = [
            ("a", "", "cat cat x1"),
            ("b", "", "cat y1 y2"),
        ]
        assert bm25_rank("cat cat cat", docs) == bm25_rank("cat", docs)


# ---------------------------------------------------------------------------
# 6. Both-fields requirement: title-only and body-only matches
# ---------------------------------------------------------------------------


class TestBothFields:
    def test_title_only_match_is_found(self):
        # Body has zero overlap with the query.
        docs = [
            ("a", "cat", "x1 x2 x3"),
            ("b", "y1", "y2 y3 y4"),
        ]
        assert _ids(bm25_rank("cat", docs)) == ["a"]

    def test_body_only_match_is_found(self):
        # Title has zero overlap with the query.
        docs = [
            ("a", "x1", "cat x2 x3"),
            ("b", "y1", "y2 y3 y4"),
        ]
        assert _ids(bm25_rank("cat", docs)) == ["a"]

    def test_body_match_returned_alongside_other_docs_title_match(self):
        # Query has two terms; one doc matches only via title, the other only
        # via body. Both must appear.
        docs = [
            ("a", "cat", "x1 x2"),
            ("b", "y1 y2", "dog"),
        ]
        assert sorted(_ids(bm25_rank("cat dog", docs))) == ["a", "b"]

    def test_term_buried_deep_in_long_body_is_found(self):
        filler = " ".join(f"w{i}" for i in range(100))
        docs = [
            ("a", "x1", filler + " cat"),
            ("b", "y1", "y2 y3"),
        ]
        assert "a" in _ids(bm25_rank("cat", docs))

    def test_title_match_with_empty_body_is_found(self):
        docs = [
            ("a", "cat", ""),
            ("b", "x1", "x2"),
        ]
        assert _ids(bm25_rank("cat", docs)) == ["a"]

    def test_body_match_with_empty_title_is_found(self):
        docs = [
            ("a", "", "cat x1"),
            ("b", "y1", "y2"),
        ]
        assert _ids(bm25_rank("cat", docs)) == ["a"]

    def test_title_match_ranks_above_body_match_but_both_returned(self):
        # A: tf=3, len=5. B: tf=1, len=7. Both returned, A first.
        docs = [
            ("a", "cat", "x1 x2"),
            ("b", "y1 y2", "cat"),
        ]
        results = bm25_rank("cat", docs)
        assert _ids(results) == ["a", "b"]
        assert results[0][1] > results[1][1]

    def test_title_match_survives_long_unrelated_body(self):
        filler = " ".join(f"z{i}" for i in range(80))
        docs = [
            ("a", "cat", filler),
            ("b", "x1", "x2 x3"),
        ]
        assert _ids(bm25_rank("cat", docs)) == ["a"]


# ---------------------------------------------------------------------------
# 7. Ordering / API contract
# ---------------------------------------------------------------------------


class TestOrderingApi:
    # tf 3 > 2 > 1 at identical doc_len=5 -> strictly distinct scores.
    GRADED_DOCS = [
        ("hi", "", "cat cat cat x1 x2"),
        ("mid", "", "cat cat y1 y2 y3"),
        ("lo", "", "cat z1 z2 z3 z4"),
    ]

    def test_scores_sorted_descending(self):
        scores = _scores(bm25_rank("cat", self.GRADED_DOCS))
        assert scores == sorted(scores, reverse=True)
        assert scores[0] > scores[1] > scores[2]

    def test_limit_truncates_results(self):
        assert _ids(bm25_rank("cat", self.GRADED_DOCS, limit=2)) == ["hi", "mid"]

    def test_limit_larger_than_matches_returns_all(self):
        assert len(bm25_rank("cat", self.GRADED_DOCS, limit=100)) == 3

    def test_huge_min_score_filters_everything(self):
        assert bm25_rank("cat", self.GRADED_DOCS, min_score=1e9) == []

    def test_min_score_is_strict_greater_than(self):
        # Re-run with min_score equal to the lowest doc's exact score: that doc
        # must drop out (filter is score > min_score, not >=).
        first = bm25_rank("cat", self.GRADED_DOCS)
        lowest = first[-1][1]
        again = bm25_rank("cat", self.GRADED_DOCS, min_score=lowest)
        assert _ids(again) == ["hi", "mid"]

    def test_no_match_returns_empty_list(self):
        assert bm25_rank("qqqq", self.GRADED_DOCS) == []

    def test_empty_query_returns_empty_list(self):
        assert bm25_rank("", self.GRADED_DOCS) == []
        assert bm25_rank("!!!", self.GRADED_DOCS) == []

    def test_empty_docs_returns_empty_list(self):
        assert bm25_rank("cat", []) == []

    def test_repeated_calls_are_deterministic(self):
        assert bm25_rank("cat", self.GRADED_DOCS) == bm25_rank("cat", self.GRADED_DOCS)

    def test_input_doc_order_does_not_change_ranking(self):
        # Scores are order-independent (avg_len is corpus-global) and strictly
        # distinct, so any input permutation yields the identical output.
        reordered = [self.GRADED_DOCS[2], self.GRADED_DOCS[0], self.GRADED_DOCS[1]]
        assert bm25_rank("cat", self.GRADED_DOCS) == bm25_rank("cat", reordered)

    def test_result_shape_is_doc_id_float_tuples(self):
        results = bm25_rank("cat", self.GRADED_DOCS)
        assert all(
            isinstance(r, tuple) and len(r) == 2 and isinstance(r[0], str) and isinstance(r[1], float)
            for r in results
        )
        assert set(_ids(results)) <= {"hi", "mid", "lo"}
