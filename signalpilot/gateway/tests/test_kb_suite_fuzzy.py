"""Fuzzy/variant-matching tests for the KB BM25 ranker (gateway.store.kb_rank).

Mechanism under test: tokenize() emits lowercase word tokens plus '#'-prefixed
character 4-grams for words >= 5 chars.  Spelling variants and typos in LONG
words therefore partially match through shared grams; short words (< 5 chars)
get no grams and thus no fuzzy tolerance.  bm25_rank scores with Okapi BM25;
IDF down-weights (but never zeroes) grams shared by every doc.

Every ranking expectation below is gated on an in-test tokenize() overlap
check, so the tests document the algorithm's ACTUAL behavior.

Exactly 50 test functions.  Pure: no DB, no async, no randomness.
"""

from __future__ import annotations

import math

from gateway.store.kb_rank import bm25_rank, tokenize


def _toks(text: str) -> set[str]:
    return set(tokenize(text))


def _shared(a: str, b: str) -> set[str]:
    return _toks(a) & _toks(b)


def _ids(results: list[tuple[str, float]]) -> list[str]:
    return [doc_id for doc_id, _ in results]


def _assert_disjoint(query: str, body: str) -> None:
    """Guard: the unrelated doc must share NO tokens/grams with the query."""
    assert not _shared(query, body), _shared(query, body)


# ---------------------------------------------------------------------------
# Group 1 — Spelling variants (12 tests)
# ---------------------------------------------------------------------------


def test_variant_recognising_matches_recognized():
    # recognising: #reco #ecog #cogn #ogni #gnis #nisi #isin #sing
    # recognized:  #reco #ecog #cogn #ogni #gniz #nize #ized -> 4 shared
    q = "recognising"
    rel = ("rel", "", "revenue recognized under the accrual policy")
    unrel = ("unrel", "", "zebra habitat quokka burrow lynx den")
    assert {"#reco", "#ecog", "#cogn", "#ogni"} <= _shared(q, rel[2])
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


def test_variant_optimisation_matches_optimization():
    # shared grams: #opti #ptim #timi #atio #tion (5)
    q = "optimisation"
    rel = ("rel", "", "query optimization guide for the planner")
    unrel = ("unrel", "", "violin cello brass drums flute")
    assert {"#opti", "#ptim", "#timi", "#atio", "#tion"} <= _shared(q, rel[2])
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


def test_variant_analyse_matches_analyze():
    # analyse: #anal #naly #alys #lyse ; analyze: #anal #naly #alyz #lyze -> 2 shared
    q = "analyse"
    rel = ("rel", "", "analyze the churn cohort weekly")
    unrel = ("unrel", "", "granite basalt quartz gravel")
    assert {"#anal", "#naly"} <= _shared(q, rel[2])
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


def test_variant_colour_matches_color_via_single_gram():
    # colour: #colo #olou #lour ; color: #colo #olor -> only #colo shared,
    # still enough to rank above a doc with zero overlap.
    q = "colour"
    rel = ("rel", "", "color palette for the theme")
    unrel = ("unrel", "", "engine piston torque diesel")
    assert _shared(q, rel[2]) == {"#colo"}
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


def test_variant_plural_invoices_matches_invoice():
    # invoice grams #invo #nvoi #voic #oice all contained in invoices' grams
    q = "invoices"
    rel = ("rel", "", "invoice ledger for the vendor")
    unrel = ("unrel", "", "trumpet melody chorus rhythm")
    assert {"#invo", "#nvoi", "#voic", "#oice"} <= _shared(q, rel[2])
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


def test_variant_aggregated_matches_aggregation():
    # shared: #aggr #ggre #greg #rega #egat (5)
    q = "aggregated"
    rel = ("rel", "", "daily aggregation of the metrics")
    unrel = ("unrel", "", "canyon mesa butte plateau")
    assert {"#aggr", "#ggre", "#greg", "#rega", "#egat"} <= _shared(q, rel[2])
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


def test_variant_plural_customers_matches_customer():
    # customer grams #cust #usto #stom #tome #omer contained in customers'
    q = "customers"
    rel = ("rel", "", "customer lifetime value model")
    unrel = ("unrel", "", "harbor jetty pier wharf")
    assert {"#cust", "#usto", "#stom", "#tome", "#omer"} <= _shared(q, rel[2])
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


def test_variant_modelling_matches_modeling():
    # modelling: #mode #odel #dell #elli #llin #ling
    # modeling:  #mode #odel #deli #elin #ling -> 3 shared
    q = "modelling"
    rel = ("rel", "", "dimensional modeling handbook")
    unrel = ("unrel", "", "pastry crumb yeast dough")
    assert {"#mode", "#odel", "#ling"} <= _shared(q, rel[2])
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


def test_variant_normalise_matches_normalized():
    # shared: #norm #orma #rmal #mali (4)
    q = "normalise"
    rel = ("rel", "", "normalized schema for the facts")
    unrel = ("unrel", "", "tundra glacier fjord icefloe")
    assert {"#norm", "#orma", "#rmal", "#mali"} <= _shared(q, rel[2])
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


def test_variant_behaviour_matches_behavior():
    # shared: #beha #ehav #havi #avio (4)
    q = "behaviour"
    rel = ("rel", "", "user behavior events funnel")
    unrel = ("unrel", "", "spruce cedar birch maple")
    assert {"#beha", "#ehav", "#havi", "#avio"} <= _shared(q, rel[2])
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


def test_variant_categorise_matches_categorized():
    # shared: #cate #ateg #tego #egor #gori (5)
    q = "categorise"
    rel = ("rel", "", "categorized expense buckets")
    unrel = ("unrel", "", "walrus otter seal narwhal")
    assert {"#cate", "#ateg", "#tego", "#egor", "#gori"} <= _shared(q, rel[2])
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


def test_variant_summarise_matches_summarized():
    # shared: #summ #umma #mmar #mari (4)
    q = "summarise"
    rel = ("rel", "", "summarized totals per region")
    unrel = ("unrel", "", "octave chord treble clef")
    assert {"#summ", "#umma", "#mmar", "#mari"} <= _shared(q, rel[2])
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


# ---------------------------------------------------------------------------
# Group 2 — Typo tolerance (9 tests)
# ---------------------------------------------------------------------------


def test_typo_kubernets_matches_kubernetes():
    # kubernets keeps #kube #uber #bern #erne #rnet of kubernetes (5 shared)
    q = "kubernets"
    rel = ("rel", "", "kubernetes deployment manifests")
    unrel = ("unrel", "", "saddle stirrup bridle canter")
    assert {"#kube", "#uber", "#bern", "#erne", "#rnet"} <= _shared(q, rel[2])
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


def test_typo_warhouse_matches_warehouse():
    # warhouse: #warh #arho #rhou #hous #ouse ; warehouse keeps #hous #ouse -> 2
    q = "warhouse"
    rel = ("rel", "", "warehouse loading dock schedule")
    unrel = ("unrel", "", "fresco mural canvas easel")
    assert {"#hous", "#ouse"} <= _shared(q, rel[2])
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


def test_typo_postgers_matches_postgres():
    # transposition keeps #post #ostg (2 shared)
    q = "postgers"
    rel = ("rel", "", "postgres replication primer")
    unrel = ("unrel", "", "acorn thicket bramble fern")
    assert {"#post", "#ostg"} <= _shared(q, rel[2])
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


def test_typo_snowflkae_matches_snowflake():
    # keeps #snow #nowf #owfl (3 shared)
    q = "snowflkae"
    rel = ("rel", "", "snowflake compute credits usage")
    unrel = ("unrel", "", "gecko iguana skink chameleon")
    assert {"#snow", "#nowf", "#owfl"} <= _shared(q, rel[2])
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


def test_typo_pipelien_matches_pipeline():
    # keeps #pipe #ipel #peli (3 shared)
    q = "pipelien"
    rel = ("rel", "", "pipeline retry semantics")
    unrel = ("unrel", "", "cactus yucca agave mesquite")
    assert {"#pipe", "#ipel", "#peli"} <= _shared(q, rel[2])
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


def test_typo_dashbaord_matches_dashboard():
    # transposition keeps #dash #ashb (2 shared)
    q = "dashbaord"
    rel = ("rel", "", "dashboard refresh cadence")
    unrel = ("unrel", "", "kelp plankton urchin krill")
    assert {"#dash", "#ashb"} <= _shared(q, rel[2])
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


def test_typo_transformtion_matches_transformation():
    # dropped 'a' keeps #tran #rans #ansf #nsfo #sfor #form #tion (7 shared)
    q = "transformtion"
    rel = ("rel", "", "transformation layer conventions")
    unrel = ("unrel", "", "pebble shale chalk flint")
    assert {"#tran", "#rans", "#ansf", "#nsfo", "#sfor", "#form", "#tion"} <= _shared(q, rel[2])
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


def test_typo_atribution_matches_attribution():
    # dropped 't' keeps #trib #ribu #ibut #buti #utio #tion (6 shared)
    q = "atribution"
    rel = ("rel", "", "attribution window defaults")
    unrel = ("unrel", "", "sonar buoy keel rudder")
    assert {"#trib", "#ribu", "#ibut", "#buti", "#utio", "#tion"} <= _shared(q, rel[2])
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


def test_typo_materalized_matches_materialized():
    # dropped 'i' keeps #mate #ater #aliz #lize #ized (5 shared)
    q = "materalized"
    rel = ("rel", "", "materialized view refresh policy")
    unrel = ("unrel", "", "bugle fanfare cymbal gong")
    assert {"#mate", "#ater", "#aliz", "#lize", "#ized"} <= _shared(q, rel[2])
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


# ---------------------------------------------------------------------------
# Group 3 — Compound / hyphenation / snake_case / camelCase (6 tests)
# ---------------------------------------------------------------------------


def test_hyphenated_fan_out_does_NOT_match_fanout():
    # 'fan-out' -> words 'fan','out' (both <5 chars: NO grams).
    # 'fanout' -> {'fanout', '#fano', '#anou', '#nout'}.
    # Zero token overlap: the ranker finds NOTHING.  Actual limitation.
    q = "fan-out"
    assert _toks(q) == {"fan", "out"}
    doc = ("d", "", "fanout multiplies rows silently")
    assert not _shared(q, doc[2])
    assert bm25_rank(q, [doc]) == []


def test_fanout_does_NOT_match_hyphenated_fan_out():
    # Reverse direction: query 'fanout' has grams, but doc words 'fan'/'out'
    # produce no grams, so still zero overlap.  Actual limitation.
    q = "fanout"
    doc = ("d", "", "fan out across the branches")
    assert not _shared(q, doc[2])
    assert bm25_rank(q, [doc]) == []


def test_snake_fan_underscore_out_does_NOT_match_fanout():
    # 'fan_out' is ONE token (underscore kept by the regex) with grams
    # #fan_ #an_o #n_ou #_out — none of which appear in 'fanout'
    # (#fano #anou #nout).  Underscore inside grams blocks the match.
    q = "fan_out"
    assert "fan_out" in _toks(q) and "#fan_" in _toks(q)
    doc = ("d", "", "fanout hazards in joins")
    assert not _shared(q, doc[2])
    assert bm25_rank(q, [doc]) == []


def test_snake_order_id_is_one_token_and_outranks_bare_order():
    # 'order_id' -> token 'order_id' + grams #orde #rder #der_ #er_i #r_id.
    # A doc with bare 'order' shares only #orde #rder, so the exact doc wins.
    q = "order_id"
    exact = ("exact", "", "order_id column mapping")
    partial = ("partial", "", "order column mapping")
    assert "order_id" in _shared(q, exact[2])
    assert _shared(q, partial[2]) == {"#orde", "#rder"}
    res = bm25_rank(q, [partial, exact])
    assert _ids(res) == ["exact", "partial"]
    assert res[0][1] > 2 * res[1][1]


def test_camelcase_not_split_but_grams_bridge_to_spaced_words():
    # 'orderId'.lower() -> single token 'orderid' (camelCase is NOT split);
    # its grams #orde #rder still reach a doc containing 'order'.
    q = "orderId"
    assert "orderid" in _toks(q) and "order" not in _toks(q)
    rel = ("rel", "", "order identifier semantics")
    unrel = ("unrel", "", "walnut pecan almond cashew")
    assert {"#orde", "#rder"} <= _shared(q, rel[2])
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


def test_hyphenated_pre_aggregated_matches_closed_preaggregated():
    # Unlike fan-out, the hyphen part 'aggregated' is >=5 chars so it emits
    # grams #aggr #ggre #greg #rega #egat #gate #ated, all present inside
    # 'preaggregated'.  Hyphen tolerance works iff a part is long enough.
    q = "pre-aggregated"
    rel = ("rel", "", "preaggregated rollup marts")
    unrel = ("unrel", "", "lantern wick flint tinder")
    assert {"#aggr", "#ggre", "#greg", "#rega", "#egat", "#gate", "#ated"} <= _shared(q, rel[2])
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


# ---------------------------------------------------------------------------
# Group 4 — Short-word limitation (4 tests)
# ---------------------------------------------------------------------------


def test_short_word_gets_no_grams():
    assert tokenize("fan") == ["fan"]
    assert tokenize("join") == ["join"]


def test_typo_in_short_word_jion_finds_nothing():
    # 'jion' (4 chars) emits no grams, so the typo cannot reach 'join'.
    q = "jion"
    assert _toks(q) == {"jion"}
    doc = ("d", "", "join the staging tables")
    assert not _shared(q, doc[2])
    assert bm25_rank(q, [doc]) == []


def test_typo_in_short_word_fna_finds_nothing():
    q = "fna"
    doc = ("d", "", "fan speed telemetry")
    assert not _shared(q, doc[2])
    assert bm25_rank(q, [doc]) == []


def test_short_word_exact_matches_but_truncation_does_not():
    doc = ("d", "", "data catalog entries")
    assert _ids(bm25_rank("data", [doc])) == ["d"]
    # 'dta' / 'dat' share nothing with token 'data' (no grams either side)
    assert bm25_rank("dta", [doc]) == []
    assert bm25_rank("dat", [doc]) == []


# ---------------------------------------------------------------------------
# Group 5 — No-overlap negatives, IDF behavior (9 tests)
# ---------------------------------------------------------------------------


def test_zero_overlap_query_returns_empty():
    q = "quarterly forecast"
    doc = ("d", "", "zebra lynx puma bison")
    assert not _shared(q, doc[2])
    assert bm25_rank(q, [doc]) == []


def test_disjoint_long_words_share_no_grams():
    # 'query' grams #quer #uery vs brick vocab: nothing shared.
    q = "query"
    docs = [
        ("d1", "", "brick mortar kiln clay"),
        ("d2", "", "chimney hearth flue soot"),
    ]
    for _, _, body in docs:
        assert not _shared(q, body)
    assert bm25_rank(q, docs) == []


def test_cross_language_query_returns_empty():
    q = "umsatz bericht kennzahl"
    docs = [
        ("d1", "", "revenue report metric"),
        ("d2", "", "billing ledger totals"),
    ]
    for _, _, body in docs:
        assert not _shared(q, body)
    assert bm25_rank(q, docs) == []


def test_single_gram_false_positive_color_vs_colossal():
    # 'color' and 'colossal' share only #colo -> the ranker DOES surface the
    # unrelated doc (a real false-positive mode), but the exact doc wins big.
    q = "color"
    exact = ("exact", "", "color palette wheel")
    false_pos = ("false_pos", "", "colossal statue plinth")
    assert _shared(q, false_pos[2]) == {"#colo"}
    res = bm25_rank(q, [false_pos, exact])
    assert _ids(res) == ["exact", "false_pos"]
    assert res[0][1] > 2 * res[1][1]


def test_ubiquitous_gram_does_not_reorder_exact_match():
    # All three docs contain 'reporting' (grams incl. #repo #epor #port).
    # Query 'reported' shares #repo #epor #port with every doc (df = n_docs,
    # IDF small but nonzero), plus the exact word only with doc1.
    q = "reported"
    docs = [
        ("d1", "", "reported figures inside the reporting pack"),
        ("d2", "", "reporting cadence for finance"),
        ("d3", "", "reporting owners and escalation"),
    ]
    for _, _, body in docs:
        assert {"#repo", "#epor", "#port"} <= _shared(q, body)
    res = bm25_rank(q, docs)
    assert res[0][0] == "d1"
    assert res[0][1] > 2 * res[1][1]


def test_idf_positive_even_when_gram_in_all_docs():
    # Formula: idf = log(1 + (n - df + 0.5)/(df + 0.5)); at df = n = 3 this is
    # log(1 + 0.5/3.5) > 0, so every doc sharing only that gram still scores.
    n = 3
    assert math.log(1.0 + (n - n + 0.5) / (n + 0.5)) > 0.0
    q = "porting"  # grams #port #orti #rtin #ting; only #port is in the docs
    docs = [
        ("d1", "", "export bundle alpha"),
        ("d2", "", "export bundle bravo"),
        ("d3", "", "export bundle delta"),
    ]
    for _, _, body in docs:
        assert _shared(q, body) == {"#port"}
    res = bm25_rank(q, docs)
    assert len(res) == 3
    assert all(score > 0.0 for _, score in res)


def test_zero_score_docs_are_excluded():
    q = "invoice"
    docs = [
        ("hit", "", "invoice totals ledger"),
        ("miss", "", "zeppelin gondola ballast"),
    ]
    assert not _shared(q, docs[1][2])
    assert _ids(bm25_rank(q, docs)) == ["hit"]


def test_high_min_score_filters_everything():
    q = "invoice"
    docs = [("hit", "", "invoice totals ledger")]
    assert bm25_rank(q, docs, min_score=1e9) == []


def test_empty_query_and_empty_docs_return_empty():
    assert bm25_rank("", [("d", "", "anything at all")]) == []
    assert bm25_rank("invoice", []) == []
    assert bm25_rank("", []) == []


# ---------------------------------------------------------------------------
# Group 6 — Mixed exact + fuzzy (6 tests)
# ---------------------------------------------------------------------------


def test_mixed_exact_reconciliation_plus_variant_invoices():
    # Both docs contain exact 'reconciliation'; only A also carries the
    # invoice grams (#invo #nvoi #voic #oice via 'invoices').
    q = "invoice reconciliation"
    both = ("both", "", "invoices reconciliation ledger")
    exact_only = ("exact_only", "", "reconciliation ledger notes")
    assert {"#invo", "#nvoi", "#voic", "#oice"} <= _shared("invoice", both[2])
    assert not _shared("invoice", exact_only[2])
    assert _ids(bm25_rank(q, [exact_only, both])) == ["both", "exact_only"]


def test_mixed_exact_aggregation_plus_variant_customers():
    q = "customer aggregation"
    both = ("both", "", "customers aggregation table")
    exact_only = ("exact_only", "", "aggregation table rows")
    assert {"#cust", "#usto", "#stom", "#tome", "#omer"} <= _shared("customer", both[2])
    assert not _shared("customer", exact_only[2])
    assert _ids(bm25_rank(q, [exact_only, both])) == ["both", "exact_only"]


def test_mixed_exact_warehouse_plus_variant_optimisation():
    q = "warehouse optimisation"
    both = ("both", "", "warehouse optimization plan")
    exact_only = ("exact_only", "", "warehouse seating basics")
    assert {"#opti", "#ptim", "#timi"} <= _shared("optimisation", both[2])
    assert not _shared("optimisation", exact_only[2])
    assert _ids(bm25_rank(q, [exact_only, both])) == ["both", "exact_only"]


def test_mixed_exact_payment_plus_variant_aggregated():
    q = "payment aggregated"
    both = ("both", "", "payment aggregation batch")
    exact_only = ("exact_only", "", "payment batch stubs")
    assert {"#aggr", "#ggre", "#greg"} <= _shared("aggregated", both[2])
    assert not _shared("aggregated", exact_only[2])
    assert _ids(bm25_rank(q, [exact_only, both])) == ["both", "exact_only"]


def test_mixed_exact_shipment_plus_variant_analyse():
    q = "shipment analyse"
    both = ("both", "", "shipment analyze speeds")
    exact_only = ("exact_only", "", "shipment speeds crates")
    assert {"#anal", "#naly"} <= _shared("analyse", both[2])
    assert not _shared("analyse", exact_only[2])
    assert _ids(bm25_rank(q, [exact_only, both])) == ["both", "exact_only"]


def test_mixed_exact_billing_plus_variant_normalize():
    q = "billing normalize"
    both = ("both", "", "billing normalised fields")
    exact_only = ("exact_only", "", "billing fields stack")
    assert {"#norm", "#orma", "#rmal", "#mali"} <= _shared("normalize", both[2])
    assert not _shared("normalize", exact_only[2])
    assert _ids(bm25_rank(q, [exact_only, both])) == ["both", "exact_only"]


# ---------------------------------------------------------------------------
# Group 7 — Unicode / case / digits (4 tests)
# ---------------------------------------------------------------------------


def test_uppercase_query_matches_lowercase_doc():
    q = "WAREHOUSE MIGRATION"
    rel = ("rel", "", "warehouse migration runbook")
    unrel = ("unrel", "", "puffin auk gannet skua")
    assert {"warehouse", "migration"} <= _shared(q, rel[2])
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]


def test_accented_characters_split_words():
    # é is outside [a-z0-9_], so 'café' tokenizes as just 'caf' (3 chars,
    # no grams) and cannot reach a doc containing 'cafe' (token 'cafe').
    assert tokenize("café") == ["caf"]
    doc = ("d", "", "cafe seating chart")
    assert not _shared("café", doc[2])
    assert bm25_rank("café", [doc]) == []


def test_digit_underscore_token_matches_exactly_but_bare_year_does_not():
    # 'q3_2025' is one 7-char token with grams #q3_2 #3_20 #_202 #2025.
    q = "q3_2025"
    assert {"q3_2025", "#q3_2", "#2025"} <= _toks(q)
    doc = ("d", "", "q3_2025 revenue close")
    assert _ids(bm25_rank(q, [doc])) == ["d"]
    # Query '2025' is a bare 4-char word token; the doc only holds the GRAM
    # '#2025', which never equals the word '2025' -> no match.  Limitation.
    assert not _shared("2025", doc[2])
    assert bm25_rank("2025", [doc]) == []


def test_camelcase_compound_bridges_via_many_grams():
    # 'KubernetesCluster' -> single token 'kubernetescluster' whose grams
    # cover all grams of both 'kubernetes' (7) and 'cluster' (4).
    q = "KubernetesCluster"
    rel = ("rel", "", "kubernetes cluster autoscaling")
    unrel = ("unrel", "", "meadow clover thistle sedge")
    shared = _shared(q, rel[2])
    assert {"#kube", "#uber", "#bern", "#rnet", "#clus", "#lust", "#ster"} <= shared
    _assert_disjoint(q, unrel[2])
    assert _ids(bm25_rank(q, [unrel, rel])) == ["rel"]
