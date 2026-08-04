"""Adversarial / degenerate-input tests for gateway.store.kb_rank (tokenize + bm25_rank).

Pure tests: no DB, no fixtures. Every expectation is derived from reading the
algorithm, not from wished-for behavior. Filler vocabulary is kept to 4-char
words (kiwi, fern, oaks, pine, lime, dune, zeta, milk, kelp, wolf) so that no
character n-grams are emitted (n-grams only fire for words >= 5 chars), which
makes doc lengths and term frequencies exactly computable by hand.
"""

from __future__ import annotations

from gateway.store.kb_rank import bm25_rank, tokenize


def ids(result):
    return [doc_id for doc_id, _ in result]


def scores(result):
    return [score for _, score in result]


# ---------------------------------------------------------------------------
# Group 1: degenerate inputs
# ---------------------------------------------------------------------------


def test_empty_query_returns_empty():
    assert bm25_rank("", [("a", "kiwi", "fern oaks")]) == []


def test_whitespace_only_query_returns_empty():
    assert bm25_rank("   \t\n  ", [("a", "kiwi", "fern oaks")]) == []


def test_punctuation_only_query_returns_empty():
    # No [a-z0-9_] runs -> zero query tokens.
    assert bm25_rank("!!! ??? *** ---", [("a", "kiwi", "fern")]) == []


def test_empty_corpus_returns_empty():
    assert bm25_rank("kiwi", []) == []


def test_corpus_of_all_empty_docs_returns_empty():
    # No doc contains any query token -> idf dict empty -> [].
    docs = [("a", "", ""), ("b", "   ", "  \n ")]
    assert bm25_rank("kiwi", docs) == []


def test_query_equals_entire_body_ranks_that_doc_first():
    docs = [("a", "", "kiwi fern oaks"), ("b", "", "lime dune wolf")]
    result = bm25_rank("kiwi fern oaks", docs)
    assert ids(result) == ["a"]  # b shares no vocab, excluded by min_score
    assert result[0][1] > 0.0


def test_identical_docs_both_returned_with_exactly_equal_scores():
    docs = [("a", "kiwi", "fern oaks kiwi"), ("b", "kiwi", "fern oaks kiwi")]
    result = bm25_rank("kiwi fern", docs)
    assert set(ids(result)) == {"a", "b"}
    # Identical token counts + identical corpus stats -> bit-identical floats.
    assert result[0][1] == result[1][1]


def test_single_doc_corpus_matching_returns_it():
    result = bm25_rank("kiwi", [("only", "kiwi", "fern")])
    assert ids(result) == ["only"]
    assert result[0][1] > 0.0


def test_single_doc_corpus_non_matching_returns_empty():
    assert bm25_rank("zeta", [("only", "kiwi", "fern")]) == []


def test_thousand_term_query_does_not_crash_and_finds_match():
    query = " ".join(f"w{i}" for i in range(999)) + " kiwi"
    docs = [("a", "", "kiwi fern"), ("b", "", "lime dune")]
    result = bm25_rank(query, docs)
    assert ids(result) == ["a"]


def test_query_repeated_500x_scores_identical_to_single_occurrence():
    # bm25_rank uses set(tokenize(query)) -> repetition cannot change scores.
    docs = [("a", "", "kiwi fern oaks"), ("b", "", "kiwi lime")]
    once = bm25_rank("kiwi", docs)
    repeated = bm25_rank(" ".join(["kiwi"] * 500), docs)
    assert once == repeated  # identical ids AND identical float scores


# ---------------------------------------------------------------------------
# Group 2: hostile content
# ---------------------------------------------------------------------------


def test_sql_injection_body_is_tokenized_and_searchable():
    docs = [("a", "", "'; DROP TABLE users; --"), ("b", "", "lime dune")]
    result = bm25_rank("drop", docs)
    assert ids(result) == ["a"]


def test_regex_metacharacters_do_not_crash_and_yield_no_tokens():
    assert tokenize(".*+?[](){}|\\^$") == []
    docs = [("a", "", ".*+?[](){}|\\^$ kiwi"), ("b", "", "lime dune")]
    assert ids(bm25_rank("kiwi", docs)) == ["a"]


def test_none_and_nan_literal_strings_are_ordinary_tokens():
    assert tokenize("None nan NaN null") == ["none", "nan", "nan", "null"]
    docs = [("a", "", "value was None and nan"), ("b", "", "lime dune")]
    assert ids(bm25_rank("nan", docs)) == ["a"]


def test_html_script_tags_are_stripped_to_words_and_searchable():
    body = '<script>alert("xss")</script>'
    words = [t for t in tokenize(body) if not t.startswith("#")]
    assert words == ["script", "alert", "xss", "script"]
    docs = [("a", "", body), ("b", "", "lime dune")]
    assert ids(bm25_rank("alert", docs)) == ["a"]


def test_markdown_table_and_code_fence_searchable():
    body = "| col | val |\n|-----|-----|\n```sql\nSELECT kiwi FROM t\n```"
    docs = [("a", "", body), ("b", "", "lime dune")]
    assert ids(bm25_rank("kiwi", docs)) == ["a"]


def test_10k_char_single_word_does_not_crash_and_matches_via_ngram():
    # 'a'*10000 -> 1 word token + 9997 identical '#aaaa' grams.
    docs = [("a", "", "a" * 10000), ("b", "", "lime dune")]
    result = bm25_rank("aaaaa", docs)  # query word != doc word; only '#aaaa' gram overlaps
    assert ids(result) == ["a"]
    assert result[0][1] > 0.0


def test_emoji_vanishes_entirely():
    assert tokenize("\U0001f389\U0001f525") == []
    docs = [("a", "", "\U0001f389\U0001f525 party"), ("b", "", "lime")]
    assert bm25_rank("\U0001f389", docs) == []  # emoji-only query has no tokens


def test_cjk_text_vanishes_but_embedded_ascii_survives():
    assert tokenize("数据库") == []
    assert tokenize("data 数据") == ["data"]
    docs = [("a", "", "数据库 schema"), ("b", "", "lime dune")]
    assert bm25_rank("数据库", docs) == []


def test_rtl_arabic_vanishes():
    assert tokenize("مرحبا") == []
    docs = [("a", "", "مرحبا kiwi"), ("b", "", "lime")]
    assert ids(bm25_rank("kiwi", docs)) == ["a"]


def test_backslashes_and_quotes_split_into_words():
    words = [t for t in tokenize('C:\\path\\to\\file "quoted"') if not t.startswith("#")]
    assert words == ["c", "path", "to", "file", "quoted"]
    docs = [("a", "", 'C:\\path\\to\\file "quoted"'), ("b", "", "lime dune")]
    assert ids(bm25_rank("path", docs)) == ["a"]


def test_accented_character_truncates_word_at_non_ascii():
    # 'é' is not in [a-z0-9_], so "café" tokenizes as just "caf".
    assert tokenize("Café") == ["caf"]


# ---------------------------------------------------------------------------
# Group 3: numeric / id content
# ---------------------------------------------------------------------------


def test_uuid_tokenizes_into_hyphen_split_hex_segments():
    words = [
        t
        for t in tokenize("3f2a9c4e-1b7d-4e8a-9f0c-6d5e4a3b2c1d")
        if not t.startswith("#")
    ]
    assert words == ["3f2a9c4e", "1b7d", "4e8a", "9f0c", "6d5e4a3b2c1d"]


def test_searching_exact_uuid_finds_the_doc_containing_it():
    uuid = "3f2a9c4e-1b7d-4e8a-9f0c-6d5e4a3b2c1d"
    docs = [
        ("a", "", f"incident id {uuid} resolved"),
        ("b", "", "lime dune wolf"),
        ("c", "", "kelp pine oaks"),
    ]
    assert ids(bm25_rank(uuid, docs)) == ["a"]


def test_hex_id_is_one_word_plus_ngrams():
    tokens = tokenize("0xdeadbeef")
    assert tokens[0] == "0xdeadbeef"
    assert "#0xde" in tokens and "#beef" in tokens
    docs = [("a", "", "pointer 0xdeadbeef leaked"), ("b", "", "lime dune")]
    assert ids(bm25_rank("0xdeadbeef", docs)) == ["a"]


def test_timestamp_tokenization_splits_on_punctuation():
    words = [t for t in tokenize("2026-07-22T14:30:00Z") if not t.startswith("#")]
    assert words == ["2026", "07", "22t14", "30", "00z"]


def test_version_string_splits_on_dots_into_bare_digits():
    assert tokenize("2.0.0") == ["2", "0", "0"]


def test_ip_address_search_finds_doc_via_octet_tokens():
    docs = [
        ("a", "", "server at 172.31.99.42 unreachable"),
        ("b", "", "lime dune wolf"),
    ]
    result = bm25_rank("172.31.99.42", docs)
    assert ids(result) == ["a"]


def test_currency_amount_tokenizes_to_digit_groups():
    assert tokenize("$1,299.99") == ["1", "299", "99"]


def test_pure_numeric_query_matches_numeric_body():
    docs = [("a", "", "order 8675309 shipped"), ("b", "", "order 41 shipped")]
    result = bm25_rank("8675309", docs)
    assert ids(result) == ["a"]


# ---------------------------------------------------------------------------
# Group 4: scale / shape edge cases
# ---------------------------------------------------------------------------


def test_one_char_title_is_searchable():
    docs = [("a", "x", "fern oaks"), ("b", "y", "fern oaks")]
    assert ids(bm25_rank("x", docs)) == ["a"]


def test_four_char_word_emits_no_ngrams():
    assert tokenize("kiwi") == ["kiwi"]
    assert all(not t.startswith("#") for t in tokenize("kiwi fern oaks"))


def test_title_equals_body_scores_same_as_body_tf4():
    # A: title="kiwi", body="kiwi" -> counts[kiwi] = 1 + 3*1 = 4, doc_len 4.
    # B: body has kiwi 4x -> counts[kiwi] = 4, doc_len 4. Identical stats.
    docs = [("a", "kiwi", "kiwi"), ("b", "", "kiwi kiwi kiwi kiwi")]
    result = bm25_rank("kiwi", docs)
    assert set(ids(result)) == {"a", "b"}
    assert result[0][1] == result[1][1]


def test_title_word_repeated_100x_dominates_single_body_hit():
    # A: tf=300 (100 title occurrences x weight 3), dl=300.
    # B: tf=1, dl=1. Hand-computed: A ~= 2.478 > B ~= 1.808 despite length norm.
    docs = [("a", "kiwi " * 100, ""), ("b", "", "kiwi")]
    result = bm25_rank("kiwi", docs)
    assert ids(result) == ["a", "b"]


def test_idf_floor_all_docs_contain_term_ranking_driven_by_tf_and_length():
    # df == n_docs -> idf = log(1 + 0.5/(n+0.5)) > 0, never zero or negative.
    # A: tf=2, dl=2; B: tf=1, dl=4 -> A must win (hand-computed 1.6 vs ~0.87).
    docs = [("a", "", "milk milk"), ("b", "", "milk fern oaks pine")]
    result = bm25_rank("milk", docs)
    assert ids(result) == ["a", "b"]
    assert all(s > 0.0 for s in scores(result))


def test_empty_body_with_matching_title_is_found():
    docs = [("a", "kiwi", ""), ("b", "lime", "dune wolf")]
    assert ids(bm25_rank("kiwi", docs)) == ["a"]


def test_empty_title_with_matching_body_is_found():
    docs = [("a", "", "kiwi fern"), ("b", "lime", "dune wolf")]
    assert ids(bm25_rank("kiwi", docs)) == ["a"]


def test_title_hit_outranks_body_hit_at_equal_raw_occurrence():
    # A: kiwi once in title (tf=3, dl=6); B: kiwi once in body (tf=1, dl=4).
    # Hand-computed with avg_len=5: A ~= 1.587 > B ~= 1.099.
    docs = [("a", "kiwi", "fern oaks pine"), ("b", "", "kiwi fern oaks pine")]
    result = bm25_rank("kiwi", docs)
    assert ids(result) == ["a", "b"]


# ---------------------------------------------------------------------------
# Group 5: min_score / limit semantics
# ---------------------------------------------------------------------------


def test_default_min_score_zero_excludes_zero_score_docs_strict_gt():
    # Comparison is score > min_score, so a 0.0-score doc is dropped at default.
    docs = [("a", "", "kiwi fern"), ("b", "", "lime dune")]
    result = bm25_rank("kiwi", docs)
    assert ids(result) == ["a"]


def test_negative_min_score_still_excludes_non_matching_docs():
    # Exclude a document that contains no query term at any minimum score.
    docs = [("a", "", "kiwi fern"), ("b", "", "lime dune")]
    result = bm25_rank("kiwi", docs, min_score=-1.0)
    assert ids(result) == ["a"]


def test_huge_min_score_returns_empty():
    docs = [("a", "kiwi kiwi kiwi", "kiwi kiwi kiwi")]
    assert bm25_rank("kiwi", docs, min_score=1e9) == []


def test_limit_zero_returns_empty_slice():
    docs = [("a", "", "kiwi fern"), ("b", "", "kiwi lime")]
    assert bm25_rank("kiwi", docs, limit=0) == []


def test_negative_limit_clamped_to_zero():
    # Clamp a negative result limit to zero.
    docs = [
        ("a", "", "zeta zeta zeta lime"),
        ("b", "", "zeta zeta lime dune"),
        ("c", "", "zeta lime dune fern"),
    ]
    assert bm25_rank("zeta", docs, limit=-1) == []


def test_limit_larger_than_corpus_returns_all_matches():
    docs = [("a", "", "kiwi fern"), ("b", "", "kiwi lime")]
    result = bm25_rank("kiwi", docs, limit=999)
    assert set(ids(result)) == {"a", "b"}


# ---------------------------------------------------------------------------
# Group 6: score properties
# ---------------------------------------------------------------------------


def test_all_returned_scores_are_strictly_positive_by_default():
    docs = [
        ("a", "kiwi", "kiwi fern oaks"),
        ("b", "", "kiwi lime"),
        ("c", "", "dune wolf"),
    ]
    result = bm25_rank("kiwi fern", docs)
    assert result and all(s > 0.0 for s in scores(result))


def test_results_sorted_by_score_descending():
    # Equal doc lengths -> identical length norm -> higher tf strictly wins.
    docs = [
        ("c", "", "zeta lime dune fern"),
        ("a", "", "zeta zeta zeta lime"),
        ("b", "", "zeta zeta lime dune"),
    ]
    result = bm25_rank("zeta", docs)
    assert ids(result) == ["a", "b", "c"]
    s = scores(result)
    assert s == sorted(s, reverse=True)


def test_adding_unrelated_doc_does_not_change_winner():
    # Absolute scores shift (idf and avg_len move) but with equal doc lengths
    # the higher-tf doc stays on top.
    base = [("a", "", "zeta zeta zeta lime"), ("b", "", "zeta lime kelp dune")]
    before = bm25_rank("zeta", base)
    after = bm25_rank("zeta", [*base, ("x", "", "milk fern oaks pine")])
    assert ids(before)[0] == "a"
    assert ids(after)[0] == "a"


def test_duplicate_doc_ids_are_scored_independently_and_both_returned():
    # No dedup by id: each input tuple produces its own result row.
    docs = [("dup", "", "kiwi fern"), ("dup", "", "kiwi fern")]
    result = bm25_rank("kiwi", docs)
    assert ids(result) == ["dup", "dup"]
    assert result[0][1] == result[1][1]


def test_none_body_treated_as_empty():
    # Treat a null field as an empty string.
    result = bm25_rank("title", [("a", "title", None)])  # type: ignore[list-item]
    assert ids(result) == ["a"]


def test_none_title_treated_as_empty():
    result = bm25_rank("kiwi", [("a", None, "kiwi fern")])  # type: ignore[list-item]
    assert ids(result) == ["a"]
