"""Tokenization and term expansion for schema linking queries."""

from __future__ import annotations

from gateway.api.schema._constants import _re_link
from gateway.api.schema.linking._data import _ABBREVIATIONS, _STOPWORDS, _SYNONYMS


def _lemmatize(word: str) -> str:
    """Reduce common English inflections to base form."""
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"  # categories → category
    if word.endswith("ves") and len(word) > 4:
        return word[:-3] + "f"  # shelves → shelf
    if word.endswith("ses") and len(word) > 4:
        return word[:-2]  # addresses → address
    if word.endswith("es") and len(word) > 3:
        return word[:-2]  # taxes → tax
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]  # orders → order
    if word.endswith("ing") and len(word) > 5:
        return word[:-3]  # shipping → ship
    if word.endswith("ed") and len(word) > 4:
        return word[:-2]  # created → creat
    return word


def extract_terms(question_lower: str) -> tuple[list[str], list[str]]:
    """Tokenize and expand a lowercased question into (terms, ngram_terms).

    Returns:
        terms: Expanded list of meaningful search terms (including synonyms, abbreviations, lemmas).
        ngram_terms: Bigram and trigram compound terms for compound table/column matching.
    """
    terms = [
        w for w in _re_link.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", question_lower) if len(w) >= 3 and w not in _STOPWORDS
    ]

    # N-gram extraction: combine adjacent terms into compound matches
    # "order items" should match "order_items" table, "customer address" → "customer_address"
    raw_terms = [
        w for w in _re_link.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", question_lower) if len(w) >= 2 and w not in _STOPWORDS
    ]
    ngram_terms: list[str] = []
    for i in range(len(raw_terms) - 1):
        bigram = f"{raw_terms[i]}_{raw_terms[i + 1]}"
        ngram_terms.append(bigram)
        if i + 2 < len(raw_terms):
            trigram = f"{raw_terms[i]}_{raw_terms[i + 1]}_{raw_terms[i + 2]}"
            ngram_terms.append(trigram)

    # Expand terms with semantic synonyms (improves recall for Spider2.0)
    expanded_terms = list(terms)
    for term in terms:
        if term in _SYNONYMS:
            for syn in _SYNONYMS[term]:
                if syn not in expanded_terms:
                    expanded_terms.append(syn)
        # Abbreviation expansion
        if term in _ABBREVIATIONS:
            for full_word in _ABBREVIATIONS[term]:
                if full_word not in expanded_terms:
                    expanded_terms.append(full_word)
    # Add n-gram compound terms
    for ng in ngram_terms:
        if ng not in expanded_terms:
            expanded_terms.append(ng)
    terms = expanded_terms

    # Add lemmatized forms for better matching
    lemma_additions = []
    for term in terms:
        lemma = _lemmatize(term)
        if lemma != term and lemma not in terms and len(lemma) >= 3:
            lemma_additions.append(lemma)
    terms.extend(lemma_additions)

    return terms, ngram_terms
