"""50-test suite for the knowledge-base hybrid search pipeline.

Runs on in-memory SQLite: the FTS arm is Postgres-only and silently absent
here, so every test exercises the lexical + BM25 arms and RRF fusion.

Test-design rules used throughout:
  * every expected-first doc has ANCHOR terms that appear in no other seeded
    doc, so rank assertions are provable rather than near-ties;
  * distractor docs use disjoint filler vocabulary;
  * no network, no patching, fully deterministic.
"""

from __future__ import annotations

import time
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.db.models import GatewayBase, GatewayKnowledgeDoc
from gateway.store.knowledge_search import hybrid_search_knowledge

ORG = "test-org"


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _doc(
    title: str,
    body: str,
    *,
    category: str = "decisions",
    status: str = "active",
    scope: str = "org",
    scope_ref: str | None = None,
    org_id: str = ORG,
) -> GatewayKnowledgeDoc:
    now = time.time()
    return GatewayKnowledgeDoc(
        id=str(uuid.uuid4()),
        org_id=org_id,
        scope=scope,
        scope_ref=scope_ref,
        category=category,
        title=title,
        body=body,
        status=status,
        bytes=len(body.encode()),
        view_count=0,
        created_at=now,
        updated_at=now,
    )


async def _seed(session, docs):
    for d in docs:
        session.add(d)
    await session.commit()
    return docs


async def _search(session, query: str, *, scope=None, scope_ref=None, category=None, limit=10):
    return await hybrid_search_knowledge(
        session,
        org_id=ORG,
        query=query,
        scope=scope,
        scope_ref=scope_ref,
        category=category,
        limit=limit,
    )


# ── 1. Both fields through the full pipeline (10) ────────────────────────────


class TestBothFields:
    @pytest.mark.asyncio
    async def test_title_only_match_found(self, session):
        await _seed(
            session,
            [
                _doc("quokka onboarding guide", "general notes without special vocabulary"),
                _doc("unrelated topic", "totally different filler content here"),
            ],
        )
        hits = await _search(session, "quokka")
        assert hits and hits[0].doc.title == "quokka onboarding guide"

    @pytest.mark.asyncio
    async def test_body_only_match_found(self, session):
        await _seed(
            session,
            [
                _doc("general notes", "the mongoose appears once in this body text"),
                _doc("unrelated topic", "totally different filler content here"),
            ],
        )
        hits = await _search(session, "mongoose")
        assert hits and hits[0].doc.title == "general notes"

    @pytest.mark.asyncio
    async def test_title_match_outranks_body_match(self, session):
        """Both arms boost titles: title-hit doc must beat body-hit doc for the same term."""
        title_hit = _doc("quokka handbook", "general filler notes about nothing much")
        body_hit = _doc("general handbook", "a quokka appears once in this body text")
        await _seed(session, [title_hit, body_hit])
        hits = await _search(session, "quokka")
        assert len(hits) == 2
        assert hits[0].doc.id == title_hit.id
        assert hits[1].doc.id == body_hit.id

    @pytest.mark.asyncio
    async def test_content_at_end_of_long_body_found(self, session):
        filler = " ".join(f"filler{i} padding{i} verbiage{i}" for i in range(120))
        long = _doc("operations notes", filler + " axolotl reconciliation procedure")
        await _seed(session, [long, _doc("distractor", "nothing relevant lives here")])
        hits = await _search(session, "axolotl")
        assert hits and hits[0].doc.id == long.id

    @pytest.mark.asyncio
    async def test_query_words_split_across_title_and_body(self, session):
        both = _doc("walrus habits", "glacier calving patterns observed weekly")
        title_only = _doc("walrus territory", "unrelated filler content entirely")
        body_only = _doc("plain memo", "glacier melt commentary without more")
        await _seed(session, [both, title_only, body_only])
        hits = await _search(session, "walrus glacier")
        assert hits and hits[0].doc.id == both.id

    @pytest.mark.asyncio
    async def test_multiword_title_query_found(self, session):
        target = _doc("marmoset feeding schedule", "husbandry details live elsewhere")
        await _seed(session, [target, _doc("distractor", "completely different filler words")])
        hits = await _search(session, "marmoset feeding schedule")
        assert hits and hits[0].doc.id == target.id

    @pytest.mark.asyncio
    async def test_body_phrase_query_found(self, session):
        target = _doc("care manual", "covers porcupine quill maintenance routines")
        await _seed(session, [target, _doc("distractor", "completely different filler words")])
        hits = await _search(session, "porcupine quill maintenance")
        assert hits and hits[0].doc.id == target.id

    @pytest.mark.asyncio
    async def test_uppercase_query_matches_lowercase_title(self, session):
        target = _doc("quokka census results", "annual counting exercise summary")
        await _seed(session, [target, _doc("distractor", "completely different filler words")])
        hits = await _search(session, "QUOKKA")
        assert hits and hits[0].doc.id == target.id

    @pytest.mark.asyncio
    async def test_lowercase_query_matches_uppercase_body(self, session):
        target = _doc("wildlife log", "spotted a BADGER near the fence yesterday")
        await _seed(session, [target, _doc("distractor", "completely different filler words")])
        hits = await _search(session, "badger")
        assert hits and hits[0].doc.id == target.id

    @pytest.mark.asyncio
    async def test_title_and_body_doc_outranks_body_only_doc(self, session):
        both = _doc("ocelot tracking", "the ocelot roams these body sentences too")
        body_only = _doc("plain journal", "an ocelot shows up once right here")
        await _seed(session, [both, body_only])
        hits = await _search(session, "ocelot")
        assert len(hits) == 2
        assert hits[0].doc.id == both.id


# ── 2. Filters (10) ──────────────────────────────────────────────────────────


class TestFilters:
    async def _seed_scoped(self, session):
        org = _doc("org zebra guidance", "zebra rules at the org level", scope="org")
        proj = _doc(
            "project zebra guidance",
            "zebra rules for one project",
            scope="project",
            scope_ref="proj-1",
        )
        return await _seed(session, [org, proj])

    @pytest.mark.asyncio
    async def test_scope_org_excludes_project_docs(self, session):
        org, _proj = await self._seed_scoped(session)
        hits = await _search(session, "zebra", scope="org")
        assert [h.doc.id for h in hits] == [org.id]

    @pytest.mark.asyncio
    async def test_scope_project_excludes_org_docs(self, session):
        _org, proj = await self._seed_scoped(session)
        hits = await _search(session, "zebra", scope="project")
        assert [h.doc.id for h in hits] == [proj.id]

    @pytest.mark.asyncio
    async def test_no_scope_filter_returns_both_scopes(self, session):
        org, proj = await self._seed_scoped(session)
        hits = await _search(session, "zebra")
        assert {h.doc.id for h in hits} == {org.id, proj.id}

    @pytest.mark.asyncio
    async def test_scope_ref_filter(self, session):
        a = _doc("proj a zebra", "zebra notes here", scope="project", scope_ref="proj-a")
        b = _doc("proj b zebra", "zebra notes there", scope="project", scope_ref="proj-b")
        await _seed(session, [a, b])
        hits = await _search(session, "zebra", scope_ref="proj-a")
        assert [h.doc.id for h in hits] == [a.id]

    @pytest.mark.asyncio
    async def test_category_filter(self, session):
        rules = _doc("zebra rule doc", "zebra convention body", category="rules")
        dec = _doc("zebra decision doc", "zebra decision body", category="decisions")
        await _seed(session, [rules, dec])
        hits = await _search(session, "zebra", category="rules")
        assert [h.doc.id for h in hits] == [rules.id]

    @pytest.mark.asyncio
    async def test_category_filter_troubleshooting(self, session):
        ts = _doc(
            "zebra quirk fix",
            "zebra troubleshooting body",
            category="troubleshooting",
            scope="project",
            scope_ref="p1",
        )
        ctx = _doc("zebra context", "zebra context body", category="context")
        await _seed(session, [ts, ctx])
        hits = await _search(session, "zebra", category="troubleshooting")
        assert [h.doc.id for h in hits] == [ts.id]

    @pytest.mark.asyncio
    async def test_scope_and_category_combined(self, session):
        want = _doc(
            "zebra proj rules",
            "zebra body one",
            category="rules",
            scope="project",
            scope_ref="p1",
        )
        wrong_scope = _doc("zebra org rules", "zebra body two", category="rules", scope="org")
        wrong_cat = _doc(
            "zebra proj decisions",
            "zebra body three",
            category="decisions",
            scope="project",
            scope_ref="p1",
        )
        await _seed(session, [want, wrong_scope, wrong_cat])
        hits = await _search(session, "zebra", scope="project", category="rules")
        assert [h.doc.id for h in hits] == [want.id]

    @pytest.mark.asyncio
    async def test_scope_ref_and_category_combined(self, session):
        want = _doc(
            "zebra pa rules", "zebra body", category="rules", scope="project", scope_ref="pa"
        )
        wrong_ref = _doc(
            "zebra pb rules", "zebra body", category="rules", scope="project", scope_ref="pb"
        )
        wrong_cat = _doc(
            "zebra pa ctx", "zebra body", category="context", scope="project", scope_ref="pa"
        )
        await _seed(session, [want, wrong_ref, wrong_cat])
        hits = await _search(session, "zebra", scope_ref="pa", category="rules")
        assert [h.doc.id for h in hits] == [want.id]

    @pytest.mark.asyncio
    async def test_category_filter_excludes_bm25_only_match(self, session):
        """'recognising' has no substring match (lexical arm silent) but shares
        char 4-grams with 'recognized' — only BM25 finds this doc. The category
        filter must still exclude it, proving filters apply inside the BM25 arm."""
        doc = _doc(
            "billing policy", "revenue is recognized on invoice issuance", category="decisions"
        )
        await _seed(session, [doc])
        unfiltered = await _search(session, "recognising")
        assert unfiltered and unfiltered[0].doc.id == doc.id
        assert unfiltered[0].arms == ["bm25"]
        filtered = await _search(session, "recognising", category="rules")
        assert filtered == []

    @pytest.mark.asyncio
    async def test_scope_ref_filter_applies_to_lexical_arm(self, session):
        doc = _doc(
            "wombat runbook", "wombat exact keyword body", scope="project", scope_ref="proj-x"
        )
        await _seed(session, [doc])
        assert await _search(session, "wombat", scope_ref="proj-y") == []
        hits = await _search(session, "wombat", scope_ref="proj-x")
        assert hits and hits[0].doc.id == doc.id and "lexical" in hits[0].arms


# ── 3. Status / tenancy (6) ──────────────────────────────────────────────────


class TestStatusTenancy:
    @pytest.mark.asyncio
    async def test_archived_doc_never_returned(self, session):
        await _seed(session, [_doc("gone doc", "contains pelican keyword", status="archived")])
        assert await _search(session, "pelican") == []

    @pytest.mark.asyncio
    async def test_pending_doc_never_returned(self, session):
        await _seed(session, [_doc("draft doc", "contains pelican keyword", status="pending")])
        assert await _search(session, "pelican") == []

    @pytest.mark.asyncio
    async def test_archived_doc_hidden_even_for_exact_title_query(self, session):
        await _seed(session, [_doc("quarterly ledger", "old ledger content", status="archived")])
        assert await _search(session, "quarterly ledger") == []

    @pytest.mark.asyncio
    async def test_other_org_doc_not_returned(self, session):
        await _seed(session, [_doc("foreign doc", "contains pelican keyword", org_id="other-org")])
        assert await _search(session, "pelican") == []

    @pytest.mark.asyncio
    async def test_org_isolation_with_both_orgs_seeded(self, session):
        mine = _doc("my pelican doc", "pelican body here")
        theirs = _doc("their pelican doc", "pelican body there", org_id="other-org")
        await _seed(session, [mine, theirs])
        hits = await _search(session, "pelican")
        assert [h.doc.id for h in hits] == [mine.id]
        assert all(h.doc.org_id == ORG for h in hits)

    @pytest.mark.asyncio
    async def test_empty_corpus_returns_empty_list(self, session):
        assert await _search(session, "anything at all") == []


# ── 4. RRF fusion behavior (8) ───────────────────────────────────────────────


class TestRrfFusion:
    @pytest.mark.asyncio
    async def test_exact_match_carries_both_arm_names(self, session):
        await _seed(session, [_doc("walnut pricing", "walnut costs are seasonal")])
        hits = await _search(session, "walnut")
        assert hits and set(hits[0].arms) == {"lexical", "bm25"}

    @pytest.mark.asyncio
    async def test_dual_arm_doc_outranks_bm25_only_doc(self, session):
        exact = _doc("spelling memo", "we write recognising in british english")
        variant = _doc("billing memo", "revenue recognized on invoice issuance")
        await _seed(session, [exact, variant])
        hits = await _search(session, "recognising")
        assert len(hits) == 2
        assert hits[0].doc.id == exact.id
        assert set(hits[0].arms) == {"lexical", "bm25"}
        assert hits[1].arms == ["bm25"]

    @pytest.mark.asyncio
    async def test_scores_strictly_descending(self, session):
        a = _doc("zebra alert", "short filler note")
        b = _doc("plain title", "zebra appears here")
        c = _doc(
            "plain title two",
            "zebra appears somewhere within a considerably longer body text that "
            "continues with additional filler content words extending this document "
            "length substantially beyond its peers",
        )
        await _seed(session, [a, b, c])
        hits = await _search(session, "zebra")
        assert [h.doc.id for h in hits] == [a.id, b.id, c.id]
        scores = [h.score for h in hits]
        assert all(scores[i] > scores[i + 1] for i in range(len(scores) - 1))

    @pytest.mark.asyncio
    async def test_hit_count_never_exceeds_limit(self, session):
        await _seed(session, [_doc(f"zebra doc {i}", f"zebra body {i}") for i in range(6)])
        hits = await _search(session, "zebra", limit=3)
        assert len(hits) == 3

    @pytest.mark.asyncio
    async def test_limit_one_returns_single_best(self, session):
        best = _doc("quokka handbook", "general filler notes about nothing much")
        worse = _doc("general handbook", "a quokka appears once in this body text")
        await _seed(session, [best, worse])
        hits = await _search(session, "quokka", limit=1)
        assert len(hits) == 1 and hits[0].doc.id == best.id

    @pytest.mark.asyncio
    async def test_bm25_only_variant_hit_has_single_arm(self, session):
        await _seed(session, [_doc("billing memo", "revenue recognized on invoice issuance")])
        hits = await _search(session, "recognising")
        assert hits and hits[0].arms == ["bm25"]

    @pytest.mark.asyncio
    async def test_fts_arm_absent_on_sqlite(self, session):
        await _seed(session, [_doc("zebra doc", "zebra body content")])
        hits = await _search(session, "zebra")
        assert hits and all("fts" not in h.arms for h in hits)

    @pytest.mark.asyncio
    async def test_scores_positive_and_top_is_max(self, session):
        await _seed(
            session,
            [_doc("zebra alert", "short note"), _doc("plain title", "zebra appears here")],
        )
        hits = await _search(session, "zebra")
        assert hits
        assert all(h.score > 0 for h in hits)
        assert hits[0].score == max(h.score for h in hits)


# ── 5. Realistic KB scenarios (10) ───────────────────────────────────────────
#
# Each doc owns a DISTINCT vocabulary anchor set; every query below uses terms
# that appear only in its target doc, so first place is unambiguous.


@pytest_asyncio.fixture
async def kb(session):
    docs = [
        _doc(
            "Revenue recognition policy",
            "Revenue is recognized when the invoice is issued, not when payment clears. "
            "Deferred revenue amortizes monthly.",
            category="rules",
        ),
        _doc(
            "Join fan-out troubleshooting",
            "A join against a child grain multiplies parent counts, producing duplicates. "
            "Watch for cartesian explosion before aggregating.",
            category="troubleshooting",
            scope="project",
            scope_ref="p1",
        ),
        _doc(
            "Redshift serverless quirks",
            "pg_table_def yields nothing on serverless endpoints; introspect via "
            "svv_all_columns instead.",
            category="troubleshooting",
            scope="connection",
            scope_ref="c1",
        ),
        _doc(
            "dbt materialization conventions",
            "Marts build as physical relations, intermediates stay ephemeral, heavy models "
            "go incremental via merge strategies.",
            category="rules",
        ),
        _doc(
            "Schema naming standards",
            "Identifiers stay snake_case; plural entities keep singular prefixes across "
            "every warehouse layer.",
            category="rules",
        ),
        _doc(
            "Refund window policy",
            "Refunds are honored inside a forty-five business-cycle window; chargebacks "
            "afterwards route through disputes.",
            category="rules",
        ),
        _doc(
            "Customer churn definition",
            "A customer churns after ninety idle intervals; reactivation resets its "
            "churn clock.",
            category="decisions",
        ),
        _doc(
            "Timezone handling rules",
            "Persist timestamps in UTC everywhere; shift to local timezone only inside "
            "presentation layers.",
            category="rules",
        ),
        _doc(
            "Late arriving facts",
            "Backfill jobs reprocess trailing partitions so late arriving facts land "
            "correctly downstream.",
            category="decisions",
        ),
        _doc(
            "Currency conversion rates",
            "Foreign exchange rates refresh nightly through a treasury feed; historical "
            "fx snapshots remain immutable.",
            category="decisions",
        ),
    ]
    await _seed(session, docs)
    return session


class TestRealisticCorpus:
    @pytest.mark.asyncio
    async def test_refund_window_query(self, kb):
        hits = await _search(kb, "refund window")
        assert hits and hits[0].doc.title == "Refund window policy"

    @pytest.mark.asyncio
    async def test_fanout_join_duplicates_query(self, kb):
        hits = await _search(kb, "fan-out join duplicates")
        assert hits and hits[0].doc.title == "Join fan-out troubleshooting"

    @pytest.mark.asyncio
    async def test_redshift_pg_table_def_query(self, kb):
        hits = await _search(kb, "redshift pg_table_def")
        assert hits and hits[0].doc.title == "Redshift serverless quirks"

    @pytest.mark.asyncio
    async def test_revenue_recognition_query(self, kb):
        hits = await _search(kb, "revenue recognition invoice")
        assert hits and hits[0].doc.title == "Revenue recognition policy"

    @pytest.mark.asyncio
    async def test_customer_churn_query(self, kb):
        hits = await _search(kb, "customer churn")
        assert hits and hits[0].doc.title == "Customer churn definition"

    @pytest.mark.asyncio
    async def test_timezone_utc_query(self, kb):
        hits = await _search(kb, "timezone utc")
        assert hits and hits[0].doc.title == "Timezone handling rules"

    @pytest.mark.asyncio
    async def test_currency_exchange_rates_query(self, kb):
        hits = await _search(kb, "currency exchange rates")
        assert hits and hits[0].doc.title == "Currency conversion rates"

    @pytest.mark.asyncio
    async def test_backfill_late_arriving_facts_query(self, kb):
        hits = await _search(kb, "backfill late arriving facts")
        assert hits and hits[0].doc.title == "Late arriving facts"

    @pytest.mark.asyncio
    async def test_ephemeral_incremental_query(self, kb):
        hits = await _search(kb, "ephemeral incremental materialization")
        assert hits and hits[0].doc.title == "dbt materialization conventions"

    @pytest.mark.asyncio
    async def test_snake_case_naming_query(self, kb):
        hits = await _search(kb, "snake_case naming")
        assert hits and hits[0].doc.title == "Schema naming standards"


# ── 6. Robustness (6) ────────────────────────────────────────────────────────


class TestRobustness:
    @pytest.mark.asyncio
    async def test_query_longer_than_200_chars(self, session):
        target = _doc("Redshift serverless quirks", "pg_table_def yields nothing on serverless")
        await _seed(session, [target, _doc("distractor", "campaign touchpoints ranked linearly")])
        query = (
            "redshift pg_table_def serverless introspection details needed because our "
            "warehouse pipelines keep failing whenever deployment scripts attempt enumerating "
            "table definitions during nightly maintenance windows across analytics "
            "environments everywhere"
        )
        assert len(query) > 200
        hits = await _search(session, query)
        assert hits and hits[0].doc.id == target.id

    @pytest.mark.asyncio
    async def test_all_stopword_query_returns_empty(self, session):
        # Bodies deliberately avoid 'the', 'of', 'and' so no arm can fire.
        await _seed(session, [_doc("zebra migration", "covers zebra migrations regionwide")])
        assert await _search(session, "the of and") == []

    @pytest.mark.asyncio
    async def test_punctuation_only_query_returns_empty(self, session):
        await _seed(session, [_doc("zebra migration", "covers zebra migrations regionwide")])
        assert await _search(session, "?!.,;:*()[]") == []

    @pytest.mark.asyncio
    async def test_sql_text_query_matches_orders_doc(self, session):
        target = _doc("orders table guide", "orders land hourly via kafka ingestion")
        await _seed(session, [target, _doc("marketing memo", "campaign touchpoints ranked linearly")])
        hits = await _search(session, "SELECT * FROM orders WHERE")
        assert hits and hits[0].doc.id == target.id

    @pytest.mark.asyncio
    async def test_markdown_body_matched(self, session):
        target = _doc(
            "grain checklist",
            "## Fan-out checklist\n```sql\nSELECT persimmon_id FROM claims\n```\n"
            "- verify persimmon grain\n- rerun counts",
        )
        await _seed(session, [target, _doc("distractor", "campaign touchpoints ranked linearly")])
        hits = await _search(session, "persimmon")
        assert hits and hits[0].doc.id == target.id

    @pytest.mark.asyncio
    async def test_single_character_query_returns_empty(self, session):
        # 'z' never appears as a standalone token in the seeded doc.
        await _seed(session, [_doc("zebra migration", "covers zebra migrations regionwide")])
        assert await _search(session, "z") == []
