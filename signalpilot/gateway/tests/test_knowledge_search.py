"""Tests for hybrid knowledge search, embeddings, and retrieval-event logging.

Runs on in-memory SQLite: the FTS arm is Postgres-only and silently absent
here, so these tests exercise the lexical + vector arms, RRF fusion, the
embedding sync lifecycle, and retrieval stats aggregation.
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
    GatewayKnowledgeEmbedding,
    GatewayKnowledgeRetrieval,
)
from gateway.embeddings import HashingEmbedder, cosine_similarity
from gateway.store.knowledge_search import (
    RetrievalEvent,
    content_hash,
    hybrid_search_knowledge,
    prune_retrieval_events,
    retrieval_stats,
    sync_knowledge_embeddings,
)

ORG = "test-org"


@pytest.fixture(autouse=True)
def _hash_provider_env(monkeypatch):
    """Pin the embedding provider to the offline hash embedder for all tests.

    Without this, ambient SP_EMBEDDINGS_* env (e.g. a configured openai key)
    would make unit tests issue live HTTP calls.
    """
    from gateway.config.embeddings import get_embeddings_settings

    monkeypatch.setenv("SP_EMBEDDINGS_PROVIDER", "hash")
    monkeypatch.delenv("SP_EMBEDDINGS_API_KEY", raising=False)
    get_embeddings_settings.cache_clear()
    yield
    get_embeddings_settings.cache_clear()


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


# ── HashingEmbedder ───────────────────────────────────────────────────────────


class TestHashingEmbedder:
    @pytest.mark.asyncio
    async def test_deterministic(self):
        emb = HashingEmbedder(dim=128)
        [a] = await emb.embed(["revenue is recognized at invoice date"])
        [b] = await emb.embed(["revenue is recognized at invoice date"])
        assert a == b
        assert len(a) == 128

    @pytest.mark.asyncio
    async def test_similar_texts_score_higher_than_unrelated(self):
        emb = HashingEmbedder()
        [a, b, c] = await emb.embed(
            [
                "revenue recognition rules for invoices",
                "how revenue is recognized on an invoice",
                "kubernetes pod scheduling internals",
            ]
        )
        assert cosine_similarity(a, b) > cosine_similarity(a, c)

    @pytest.mark.asyncio
    async def test_unit_normalized(self):
        emb = HashingEmbedder()
        [v] = await emb.embed(["some text"])
        assert abs(sum(x * x for x in v) - 1.0) < 1e-9

    @pytest.mark.asyncio
    async def test_empty_text(self):
        emb = HashingEmbedder()
        [v] = await emb.embed([""])
        assert len(v) == emb.dim


# ── Embedding sync ────────────────────────────────────────────────────────────


class TestEmbeddingSync:
    @pytest.mark.asyncio
    async def test_sync_embeds_active_docs(self, session):
        await _seed(session, [_doc("rev rules", "Revenue rules body."), _doc("grain", "Grain body.")])
        n = await sync_knowledge_embeddings(session, org_id=ORG)
        assert n == 2
        rows = (await session.execute(GatewayKnowledgeEmbedding.__table__.select())).fetchall()
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_sync_is_idempotent(self, session):
        await _seed(session, [_doc("a", "body a")])
        assert await sync_knowledge_embeddings(session, org_id=ORG) == 1
        assert await sync_knowledge_embeddings(session, org_id=ORG) == 0

    @pytest.mark.asyncio
    async def test_edit_triggers_reembed(self, session):
        [doc] = await _seed(session, [_doc("a", "body a")])
        await sync_knowledge_embeddings(session, org_id=ORG)
        doc.body = "changed body"
        await session.commit()
        assert await sync_knowledge_embeddings(session, org_id=ORG) == 1

    @pytest.mark.asyncio
    async def test_archived_doc_embedding_removed(self, session):
        [doc] = await _seed(session, [_doc("a", "body a")])
        await sync_knowledge_embeddings(session, org_id=ORG)
        doc.status = "archived"
        await session.commit()
        await sync_knowledge_embeddings(session, org_id=ORG)
        rows = (await session.execute(GatewayKnowledgeEmbedding.__table__.select())).fetchall()
        assert rows == []

    def test_content_hash_changes_with_body(self):
        assert content_hash("t", "a") != content_hash("t", "b")


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
    async def test_semantic_match_without_exact_substring(self, session):
        docs = await _seed(
            session,
            [
                _doc("revenue recognition", "Revenue is recognized when the invoice is issued, not paid."),
                _doc("pod scheduling", "Kubernetes pods schedule via kubelet affinity rules."),
            ],
        )
        await sync_knowledge_embeddings(session, org_id=ORG)
        # "recognizing invoices" shares no exact substring hit ordering with
        # doc 2; the vector arm must rank the revenue doc first.
        hits = await hybrid_search_knowledge(
            session, org_id=ORG, query="recognizing invoice revenue", scope=None, scope_ref=None, category=None, limit=5
        )
        assert hits
        assert hits[0].doc.id == docs[0].id
        assert "vector" in hits[0].arms

    @pytest.mark.asyncio
    async def test_archived_docs_excluded(self, session):
        await _seed(session, [_doc("secret", "archived body", status="archived")])
        await sync_knowledge_embeddings(session, org_id=ORG)
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
        await sync_knowledge_embeddings(session, org_id=ORG)
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
        await sync_knowledge_embeddings(session, org_id=ORG)
        hits = await hybrid_search_knowledge(
            session, org_id=ORG, query="billing grain", scope=None, scope_ref=None, category=None, limit=5
        )
        assert hits[0].doc.title == "billing grain"
        assert len(hits[0].arms) >= 2  # lexical + vector both fired


# ── Retrieval events ──────────────────────────────────────────────────────────


class TestRetrievalStats:
    async def _log(self, session, doc_id: str, source: str, ts: float):
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

    def test_retrieval_event_dataclass_defaults(self):
        ev = RetrievalEvent(org_id=ORG, doc_id="d", source="search_knowledge")
        assert ev.query is None and ev.rank is None

    @pytest.mark.asyncio
    async def test_bucket_placement_oldest_and_newest(self, session):
        now = time.time()
        await self._log(session, "d1", "search_knowledge", now - 30 * 86400 + 3600)  # oldest bucket
        await self._log(session, "d1", "search_knowledge", now - 60)  # newest bucket
        stats = await retrieval_stats(session, org_id=ORG, since_days=30)
        series = stats["docs"][0]["series"]
        assert series[0] == 1 and series[-1] == 1
        assert sum(series) == 2


# ── Provider selection fallbacks ─────────────────────────────────────────────


class TestProviderSelection:
    def _provider(self, monkeypatch, **env):
        from gateway.config.embeddings import get_embeddings_settings
        from gateway.embeddings import get_embedding_provider

        for k, v in env.items():
            monkeypatch.setenv(k, v)
        get_embeddings_settings.cache_clear()
        try:
            return get_embedding_provider()
        finally:
            get_embeddings_settings.cache_clear()

    def test_none_disables(self, monkeypatch):
        assert self._provider(monkeypatch, SP_EMBEDDINGS_PROVIDER="none") is None

    def test_openai_without_key_falls_back_to_hash(self, monkeypatch):
        p = self._provider(monkeypatch, SP_EMBEDDINGS_PROVIDER="openai")
        assert p is not None and p.provider_id.startswith("hash:")

    def test_openai_with_base_url_allowed_keyless(self, monkeypatch):
        p = self._provider(
            monkeypatch, SP_EMBEDDINGS_PROVIDER="openai", SP_EMBEDDINGS_BASE_URL="http://localhost:11434/v1"
        )
        assert p is not None and p.provider_id.startswith("openai:")

    def test_voyage_without_key_falls_back_to_hash(self, monkeypatch):
        p = self._provider(monkeypatch, SP_EMBEDDINGS_PROVIDER="voyage")
        assert p is not None and p.provider_id.startswith("hash:")

    def test_unknown_provider_falls_back_to_hash(self, monkeypatch):
        p = self._provider(monkeypatch, SP_EMBEDDINGS_PROVIDER="wat")
        assert p is not None and p.provider_id.startswith("hash:")


# ── Additional hybrid edge cases ─────────────────────────────────────────────


class TestHybridEdgeCases:
    @pytest.mark.asyncio
    async def test_archived_after_sync_excluded_by_vector_arm(self, session):
        """Doc archived AFTER embedding sync must not surface via its stale vector."""
        [doc] = await _seed(session, [_doc("stale vec", "unique zebra giraffe content")])
        await sync_knowledge_embeddings(session, org_id=ORG)
        doc.status = "archived"
        await session.commit()
        # No re-sync: embedding row still exists, doc join must filter it.
        hits = await hybrid_search_knowledge(
            session, org_id=ORG, query="unique zebra giraffe content", scope=None, scope_ref=None, category=None, limit=5
        )
        assert hits == []

    @pytest.mark.asyncio
    async def test_long_task_description_still_matches_keywords(self, session):
        """Lexical arm must fire for long prose queries (tokenized, not substring)."""
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
    async def test_provider_swap_triggers_reembed(self, session, monkeypatch):
        from gateway.db.models import GatewayKnowledgeEmbedding as Emb

        await _seed(session, [_doc("a", "body a")])
        await sync_knowledge_embeddings(session, org_id=ORG)
        # Simulate a config swap by rewriting the stored provider id
        row = (await session.execute(Emb.__table__.select())).fetchone()
        await session.execute(
            Emb.__table__.update().where(Emb.doc_id == row.doc_id).values(provider="old:model:1")
        )
        await session.commit()
        assert await sync_knowledge_embeddings(session, org_id=ORG) == 1

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
