"""Tests for hybrid knowledge search, BM25 ranking, and retrieval logging.

Runs on in-memory SQLite: the FTS arm is Postgres-only and silently absent
here, so these tests exercise the lexical + BM25 arms, RRF fusion, and
retrieval stats aggregation. No embedding models anywhere — ranking is
pure-Python BM25 (store/kb_rank.py).
"""

from __future__ import annotations

import time
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.db.models import (
    GatewayBase,
    GatewayKnowledgeDoc,
    GatewayKnowledgeRetrieval,
)
from gateway.store.kb_rank import bm25_rank, tokenize
from gateway.store.knowledge_search import (
    RetrievalEvent,
    hybrid_search_knowledge,
    prune_retrieval_events,
    retrieval_stats,
)

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


def _doc(title: str, body: str, *, category: str = "decisions", status: str = "active") -> GatewayKnowledgeDoc:
    now = time.time()
    return GatewayKnowledgeDoc(
        id=str(uuid.uuid4()),
        org_id=ORG,
        scope="org",
        scope_ref=None,
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


# ── BM25 core (pure) ─────────────────────────────────────────────────────────


class TestBm25:
    def test_tokenize_words_and_ngrams(self):
        toks = tokenize("Revenue fan-out")
        assert "revenue" in toks and "fan" in toks and "out" in toks
        assert "#reve" in toks  # 4-gram of a ≥5-char word
        assert not any(t.startswith("#") and len(t) != 5 for t in toks)

    def test_relevant_doc_ranks_first(self):
        docs = [
            ("a", "revenue recognition", "Revenue is recognized when the invoice is issued."),
            ("b", "pod scheduling", "Kubernetes pods schedule via kubelet affinity."),
        ]
        ranked = bm25_rank("invoice revenue", docs)
        assert ranked and ranked[0][0] == "a"

    def test_variant_spelling_matches_via_ngrams(self):
        """recognising/recognized share char 4-grams even though the words differ."""
        docs = [
            ("a", "revenue recognition", "Revenue is recognized when the invoice is issued."),
            ("b", "unrelated", "Totally different topic entirely here."),
        ]
        ranked = bm25_rank("recognising revenue", docs)
        assert ranked and ranked[0][0] == "a"

    def test_title_hits_outrank_body_hits(self):
        docs = [
            ("title_hit", "zebra migration guide", "general notes about things."),
            ("body_hit", "general notes", "mentions zebra once in the body text."),
        ]
        ranked = bm25_rank("zebra", docs)
        assert ranked[0][0] == "title_hit"

    def test_no_overlap_returns_empty(self):
        docs = [("a", "alpha", "beta gamma")]
        assert bm25_rank("zzzz qqqq", docs) == []

    def test_empty_inputs(self):
        assert bm25_rank("", [("a", "t", "b")]) == []
        assert bm25_rank("query", []) == []

    def test_limit_respected(self):
        docs = [(f"d{i}", f"zebra {i}", "zebra body") for i in range(20)]
        assert len(bm25_rank("zebra", docs, limit=5)) == 5

    def test_deterministic(self):
        docs = [("a", "revenue report", "monthly revenue numbers"), ("b", "revenue", "revenue")]
        assert bm25_rank("revenue", docs) == bm25_rank("revenue", docs)


# ── Hybrid search ─────────────────────────────────────────────────────────────


class TestHybridSearch:
    @pytest.mark.asyncio
    async def test_lexical_exact_match_found(self, session):
        await _seed(session, [_doc("fanout trap", "Watch for join fan-out on claims."), _doc("other", "nothing")])
        hits = await hybrid_search_knowledge(
            session, org_id=ORG, query="fan-out", scope=None, scope_ref=None, category=None, limit=10
        )
        assert hits and hits[0].doc.title == "fanout trap"

    @pytest.mark.asyncio
    async def test_variant_match_without_exact_substring(self, session):
        docs = await _seed(
            session,
            [
                _doc("revenue recognition", "Revenue is recognized when the invoice is issued, not paid."),
                _doc("pod scheduling", "Kubernetes pods schedule via kubelet affinity rules."),
            ],
        )
        # British spelling — no exact substring; BM25 n-grams must carry it.
        hits = await hybrid_search_knowledge(
            session, org_id=ORG, query="recognising invoice revenue", scope=None, scope_ref=None, category=None, limit=5
        )
        assert hits
        assert hits[0].doc.id == docs[0].id
        assert "bm25" in hits[0].arms

    @pytest.mark.asyncio
    async def test_archived_docs_excluded(self, session):
        await _seed(session, [_doc("secret", "archived body", status="archived")])
        hits = await hybrid_search_knowledge(
            session, org_id=ORG, query="archived body", scope=None, scope_ref=None, category=None, limit=5
        )
        assert hits == []

    @pytest.mark.asyncio
    async def test_org_isolation(self, session):
        other = _doc("other-org doc", "shared keyword zebra")
        other.org_id = "other-org"
        await _seed(session, [other])
        hits = await hybrid_search_knowledge(
            session, org_id=ORG, query="zebra", scope=None, scope_ref=None, category=None, limit=5
        )
        assert hits == []

    @pytest.mark.asyncio
    async def test_category_filter(self, session):
        await _seed(
            session,
            [
                _doc("rule doc", "zebra rules", category="rules"),
                _doc("decision doc", "zebra decisions", category="decisions"),
            ],
        )
        hits = await hybrid_search_knowledge(
            session, org_id=ORG, query="zebra", scope=None, scope_ref=None, category="rules", limit=5
        )
        assert [h.doc.category.value for h in hits] == ["rules"]

    @pytest.mark.asyncio
    async def test_fused_score_ranks_multi_arm_doc_first(self, session):
        await _seed(
            session,
            [
                _doc("billing grain", "billing grain and invoice fan-out"),
                _doc("unrelated", "totally different topic entirely"),
            ],
        )
        hits = await hybrid_search_knowledge(
            session, org_id=ORG, query="billing grain", scope=None, scope_ref=None, category=None, limit=5
        )
        assert hits[0].doc.title == "billing grain"
        assert len(hits[0].arms) >= 2  # lexical + bm25 both fired

    @pytest.mark.asyncio
    async def test_long_task_description_still_matches_keywords(self, session):
        await _seed(session, [_doc("redshift serverless", "pg_table_def does not work on Redshift serverless.")])
        long_query = (
            "I need to build an incremental dbt model on our redshift warehouse that "
            "aggregates daily order revenue and handles late arriving facts correctly"
        )
        hits = await hybrid_search_knowledge(
            session, org_id=ORG, query=long_query, scope=None, scope_ref=None, category=None, limit=5
        )
        assert hits and hits[0].doc.title == "redshift serverless"

    @pytest.mark.asyncio
    async def test_limit_truncation(self, session):
        await _seed(session, [_doc(f"zebra doc {i}", f"zebra body {i}") for i in range(5)])
        hits = await hybrid_search_knowledge(
            session, org_id=ORG, query="zebra", scope=None, scope_ref=None, category=None, limit=2
        )
        assert len(hits) == 2


# ── Store wrapper fallback ────────────────────────────────────────────────────


class TestStoreHybridFallback:
    @pytest.mark.asyncio
    async def test_fallback_to_ilike_on_hybrid_failure(self, session, monkeypatch):
        """The 'never regresses below legacy search' guarantee."""
        from gateway.store import knowledge_search as ks
        from gateway.store.store import Store

        await _seed(session, [_doc("fallback doc", "contains zebra keyword")])

        async def _boom(*a, **k):
            raise RuntimeError("hybrid exploded")

        monkeypatch.setattr(ks, "hybrid_search_knowledge", _boom)
        store = Store(session, org_id=ORG, user_id="u1")
        hits = await store.search_knowledge_hybrid(query="zebra", source="search_knowledge", log_events=False)
        assert hits and hits[0].doc.title == "fallback doc"
        assert hits[0].arms == ["lexical"]


# ── Retrieval events ──────────────────────────────────────────────────────────


class TestRetrievalStats:
    async def _log(self, session, doc_id: str, source: str, ts: float):
        # Stats join to active docs — ensure a doc row exists for the id.
        existing = await session.get(GatewayKnowledgeDoc, doc_id)
        if existing is None:
            d = _doc(f"doc {doc_id}", f"body {doc_id}")
            d.id = doc_id
            session.add(d)
        session.add(
            GatewayKnowledgeRetrieval(
                id=str(uuid.uuid4()), org_id=ORG, doc_id=doc_id, source=source, query="q", ts=ts
            )
        )
        await session.commit()

    @pytest.mark.asyncio
    async def test_stats_aggregate_counts_and_sources(self, session):
        now = time.time()
        await self._log(session, "d1", "search_knowledge", now - 100)
        await self._log(session, "d1", "get_knowledge_task", now - 50)
        await self._log(session, "d2", "search_knowledge", now - 10)
        stats = await retrieval_stats(session, org_id=ORG, since_days=30)
        assert len(stats["docs"]) == 2
        top = stats["docs"][0]
        assert top["doc_id"] == "d1"
        assert top["total"] == 2
        assert top["by_source"] == {"search_knowledge": 1, "get_knowledge_task": 1}
        assert sum(top["series"]) == 2

    @pytest.mark.asyncio
    async def test_stats_respects_window(self, session):
        now = time.time()
        await self._log(session, "old", "search_knowledge", now - 40 * 86400)
        stats = await retrieval_stats(session, org_id=ORG, since_days=30)
        assert stats["docs"] == []

    @pytest.mark.asyncio
    async def test_prune_deletes_old_events(self, session):
        now = time.time()
        await self._log(session, "old", "search_knowledge", now - 100 * 86400)
        await self._log(session, "new", "search_knowledge", now)
        deleted = await prune_retrieval_events(session, retention_days=90)
        assert deleted == 1
        stats = await retrieval_stats(session, org_id=ORG, since_days=365)
        assert [d["doc_id"] for d in stats["docs"]] == ["new"]

    @pytest.mark.asyncio
    async def test_archived_doc_events_excluded_from_stats(self, session):
        now = time.time()
        await self._log(session, "gone", "search_knowledge", now - 10)
        doc = await session.get(GatewayKnowledgeDoc, "gone")
        doc.status = "archived"
        await session.commit()
        stats = await retrieval_stats(session, org_id=ORG, since_days=30)
        assert stats["docs"] == []

    @pytest.mark.asyncio
    async def test_bucket_placement_oldest_and_newest(self, session):
        now = time.time()
        await self._log(session, "d1", "search_knowledge", now - 30 * 86400 + 3600)
        await self._log(session, "d1", "search_knowledge", now - 60)
        stats = await retrieval_stats(session, org_id=ORG, since_days=30)
        series = stats["docs"][0]["series"]
        assert series[0] == 1 and series[-1] == 1
        assert sum(series) == 2

    def test_retrieval_event_dataclass_defaults(self):
        ev = RetrievalEvent(org_id=ORG, doc_id="d", source="search_knowledge")
        assert ev.query is None and ev.rank is None
