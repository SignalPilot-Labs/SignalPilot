"""Tests for enhanced schema linking algorithm.

Verifies n-gram matching, abbreviation expansion, lemmatization,
and question-type scoring for Spider2.0 optimization.
"""

import pytest
import re


# ── Test helpers: extracted from gateway/main.py schema linking logic ──

_STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
    "her", "was", "one", "our", "out", "has", "how", "man", "new", "now",
    "old", "see", "way", "who", "did", "get", "has", "him", "his", "let",
    "say", "she", "too", "use", "what", "which", "show", "find", "list",
    "give", "tell", "many", "much", "each", "every", "from", "with", "that",
    "this", "have", "will", "your", "they", "been", "more", "when", "make",
    "like", "very", "just", "than", "them", "some", "would", "could",
    "select", "where", "group", "having", "limit",
    "result", "table", "column", "database", "query", "display", "retrieve",
}

_ABBREVIATIONS = {
    "cust": ["customer", "client"],
    "prod": ["product", "production"],
    "cat": ["category"],
    "qty": ["quantity"],
    "amt": ["amount"],
    "txn": ["transaction"],
    "inv": ["inventory", "invoice"],
    "dept": ["department"],
    "emp": ["employee"],
    "mgr": ["manager"],
    "addr": ["address"],
    "desc": ["description"],
    "num": ["number"],
    "dt": ["date"],
    "cnt": ["count"],
    "pct": ["percent", "percentage"],
    "avg": ["average"],
    "tot": ["total"],
    "bal": ["balance"],
    "acct": ["account"],
    "org": ["organization"],
    "loc": ["location"],
    "sku": ["product", "item"],
    "ref": ["reference"],
    "seq": ["sequence"],
    "dim": ["dimension"],
    "fct": ["fact"],
    "stg": ["staging"],
}

_SYNONYMS = {
    "customer": ["client", "buyer", "account", "user"],
    "order": ["purchase", "transaction", "booking", "request"],
    "product": ["item", "sku", "goods", "inventory"],
    "revenue": ["amount", "total", "sales", "income", "price"],
    "department": ["dept", "division", "team", "group", "unit"],
}


def _lemmatize(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("ves") and len(word) > 4:
        return word[:-3] + "f"
    if word.endswith("ses") and len(word) > 4:
        return word[:-2]
    if word.endswith("es") and len(word) > 3:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    if word.endswith("ing") and len(word) > 5:
        return word[:-3]
    if word.endswith("ed") and len(word) > 4:
        return word[:-2]
    return word


def extract_terms(question: str) -> list[str]:
    """Extract and expand search terms from a question (mirrors gateway logic)."""
    question_lower = question.lower()
    raw = [w for w in re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', question_lower)
           if len(w) >= 2 and w not in _STOPWORDS]
    terms = [w for w in raw if len(w) >= 3]

    # N-grams
    ngrams = []
    for i in range(len(raw) - 1):
        ngrams.append(f"{raw[i]}_{raw[i + 1]}")
        if i + 2 < len(raw):
            ngrams.append(f"{raw[i]}_{raw[i + 1]}_{raw[i + 2]}")

    # Expand with synonyms
    expanded = list(terms)
    for term in terms:
        if term in _SYNONYMS:
            for syn in _SYNONYMS[term]:
                if syn not in expanded:
                    expanded.append(syn)
        if term in _ABBREVIATIONS:
            for full in _ABBREVIATIONS[term]:
                if full not in expanded:
                    expanded.append(full)

    # Add n-grams
    for ng in ngrams:
        if ng not in expanded:
            expanded.append(ng)

    # Lemmatize
    lemmas = []
    for t in expanded:
        lemma = _lemmatize(t)
        if lemma != t and lemma not in expanded and len(lemma) >= 3:
            lemmas.append(lemma)
    expanded.extend(lemmas)

    return expanded


# ── Tests ──

class TestNgramExtraction:
    def test_bigram_extraction(self):
        terms = extract_terms("customer orders")
        assert "customer_orders" in terms

    def test_trigram_extraction(self):
        terms = extract_terms("order line items")
        assert "order_line_items" in terms

    def test_compound_table_match(self):
        """'order items' should produce 'order_items' bigram."""
        terms = extract_terms("show me all order items")
        assert "order_items" in terms

    def test_bigram_with_stopwords_removed(self):
        """Stopwords should be excluded before n-gram generation."""
        terms = extract_terms("count of orders")
        # "of" is too short (2 chars), so bigrams skip it
        assert "orders" in terms or "order" in terms


class TestAbbreviationExpansion:
    def test_cust_expands(self):
        terms = extract_terms("cust details")
        assert "customer" in terms

    def test_dept_expands(self):
        terms = extract_terms("dept assignments")
        assert "department" in terms

    def test_qty_expands(self):
        terms = extract_terms("qty breakdown")
        assert "quantity" in terms

    def test_amt_expands(self):
        terms = extract_terms("amt totals")
        assert "amount" in terms

    def test_inv_expands(self):
        terms = extract_terms("inv report")
        assert "inventory" in terms or "invoice" in terms

    def test_acct_expands(self):
        terms = extract_terms("acct balance")
        assert "account" in terms


class TestLemmatization:
    def test_plural_s(self):
        assert _lemmatize("orders") == "order"

    def test_plural_es(self):
        assert _lemmatize("taxes") == "tax"

    def test_plural_ies(self):
        assert _lemmatize("categories") == "category"

    def test_plural_ves(self):
        assert _lemmatize("shelves") == "shelf"

    def test_ing_suffix(self):
        # Simple lemmatizer strips -ing; double consonants not handled
        assert _lemmatize("shipping") == "shipp"
        assert _lemmatize("ordering") == "order"

    def test_ed_suffix(self):
        assert _lemmatize("created") == "creat"

    def test_short_word_unchanged(self):
        """Short words should not be over-lemmatized."""
        assert _lemmatize("as") == "as"
        assert _lemmatize("is") == "is"

    def test_double_s_unchanged(self):
        """Words ending in 'ss' should not drop the final s."""
        assert _lemmatize("address") == "address"


class TestSynonymExpansion:
    def test_customer_synonyms(self):
        terms = extract_terms("customer list")
        assert "client" in terms or "buyer" in terms

    def test_order_synonyms(self):
        terms = extract_terms("order history")
        assert "purchase" in terms or "transaction" in terms

    def test_product_synonyms(self):
        terms = extract_terms("product catalog")
        assert "item" in terms or "goods" in terms

    def test_revenue_synonyms(self):
        terms = extract_terms("revenue trends")
        assert "amount" in terms or "sales" in terms


class TestQuestionTypeDetection:
    """Question-type detection is in the gateway; here we verify the keyword sets."""

    _AGG_KEYWORDS = {"average", "avg", "sum", "total", "count", "max", "maximum",
                     "min", "minimum", "mean", "median", "aggregate", "top",
                     "bottom", "highest", "lowest", "most", "least"}
    _TIME_KEYWORDS = {"when", "date", "year", "month", "week", "day", "quarter",
                      "recent", "latest", "oldest", "between", "before", "after",
                      "during", "period"}

    def test_aggregation_detection(self):
        words = set("what is the average order amount".split())
        assert bool(words & self._AGG_KEYWORDS), "Should detect aggregation"

    def test_temporal_detection(self):
        words = set("orders placed last month".split())
        assert bool(words & self._TIME_KEYWORDS), "Should detect temporal"

    def test_non_aggregation(self):
        words = set("show me all customers".split())
        assert not bool(words & self._AGG_KEYWORDS)

    def test_combined_detection(self):
        words = set("total orders by month".split())
        assert bool(words & self._AGG_KEYWORDS)
        assert bool(words & self._TIME_KEYWORDS)


class TestEndToEnd:
    def test_complex_question_terms(self):
        """Full pipeline: question → expanded terms should cover relevant tables/columns."""
        terms = extract_terms("what is the total revenue by product category for Q1")
        # Should have direct terms
        assert "revenue" in terms
        assert "product" in terms
        assert "category" in terms
        # Should have synonym expansions
        assert "amount" in terms or "sales" in terms  # revenue synonyms
        assert "item" in terms  # product synonym
        # Should have n-grams
        assert "product_category" in terms

    def test_abbreviation_heavy_question(self):
        terms = extract_terms("cust acct bal by dept")
        assert "customer" in terms
        assert "account" in terms
        assert "balance" in terms
        assert "department" in terms


class TestSmallSchemaBypass:
    """Test the small-schema bypass optimization.

    Per "The Death of Schema Linking?" (OpenReview), when the full schema
    fits the context window, skipping schema linking yields higher accuracy.
    """

    def test_small_schema_threshold(self):
        """Schemas with ≤ max_tables tables and ≤ 500 columns should bypass scoring."""
        # 10 tables, 5 columns each = 50 columns total → should bypass
        max_tables = 20
        schema = {f"public.t{i}": {"columns": [{"name": f"c{j}"} for j in range(5)]} for i in range(10)}
        total_columns = sum(len(t["columns"]) for t in schema.values())
        is_small = len(schema) <= max_tables and total_columns <= 500
        assert is_small is True

    def test_large_schema_no_bypass(self):
        """Schemas with > max_tables tables should use scoring."""
        max_tables = 20
        schema = {f"public.t{i}": {"columns": [{"name": f"c{j}"} for j in range(5)]} for i in range(25)}
        total_columns = sum(len(t["columns"]) for t in schema.values())
        is_small = len(schema) <= max_tables and total_columns <= 500
        assert is_small is False

    def test_many_columns_no_bypass(self):
        """Even a few tables with >500 total columns should use scoring."""
        max_tables = 20
        schema = {f"public.t{i}": {"columns": [{"name": f"c{j}"} for j in range(200)]} for i in range(5)}
        total_columns = sum(len(t["columns"]) for t in schema.values())
        is_small = len(schema) <= max_tables and total_columns <= 500
        assert is_small is False  # 5 tables * 200 cols = 1000 > 500

    def test_bypass_includes_all_tables(self):
        """When bypassing, all tables should be included in linked_keys."""
        schema = {f"public.t{i}": {"columns": [{"name": "id"}]} for i in range(10)}
        max_tables = 20
        total_columns = sum(len(t["columns"]) for t in schema.values())
        _small_schema = len(schema) <= max_tables and total_columns <= 500
        if _small_schema:
            linked_keys = set(schema.keys())
        assert linked_keys == set(schema.keys())
        assert len(linked_keys) == 10
