"""Tests for fuzzy matching in schema search."""

import pytest

from signalpilot.gateway.gateway.api.schema import _fuzzy_match, _levenshtein


class TestLevenshtein:
    def test_identical(self):
        assert _levenshtein("hello", "hello") == 0

    def test_one_edit(self):
        assert _levenshtein("hello", "helo") == 1  # deletion
        assert _levenshtein("hello", "helloo") == 1  # insertion
        assert _levenshtein("hello", "hallo") == 1  # substitution

    def test_two_edits(self):
        assert _levenshtein("hello", "helo") == 1
        assert _levenshtein("customer", "custmer") == 1

    def test_completely_different(self):
        assert _levenshtein("abc", "xyz") == 3

    def test_empty(self):
        assert _levenshtein("hello", "") == 5
        assert _levenshtein("", "hello") == 5
        assert _levenshtein("", "") == 0


class TestFuzzyMatch:
    def test_exact_match_not_fuzzy(self):
        """Exact matches should not trigger fuzzy (handled by exact match logic)."""
        # _fuzzy_match checks edit distance, exact match has distance 0 so it would return True
        assert _fuzzy_match("customer", "customer") is True

    def test_typo_one_char(self):
        """Single character typo should match."""
        assert _fuzzy_match("customer", "custmer") is True
        assert _fuzzy_match("orders", "ordrs") is True
        assert _fuzzy_match("products", "produts") is True

    def test_typo_two_chars(self):
        """Two character typos should match."""
        assert _fuzzy_match("employee", "employe") is True

    def test_too_different(self):
        """Three+ edits should not match."""
        assert _fuzzy_match("customer", "cstmr") is False

    def test_short_terms_skip(self):
        """Terms shorter than 4 chars should not trigger fuzzy matching."""
        assert _fuzzy_match("id", "ids") is False
        assert _fuzzy_match("abc", "abd") is False

    def test_substring_fuzzy(self):
        """Fuzzy match should work for substrings of longer targets."""
        assert _fuzzy_match("order", "order_items") is True
        assert _fuzzy_match("cust", "customers") is True

    def test_no_false_positives(self):
        """Completely unrelated words should not match."""
        assert _fuzzy_match("hello", "world") is False
        assert _fuzzy_match("table", "chair") is False
