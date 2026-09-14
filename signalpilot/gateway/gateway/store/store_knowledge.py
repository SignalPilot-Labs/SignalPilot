"""Knowledge base documents, search and retrieval stats."""

from __future__ import annotations

import logging

import gateway.store.knowledge as knowledge_mod
import gateway.store.knowledge_search as knowledge_search_mod
from gateway.models.knowledge import KnowledgeDoc, KnowledgeDocCreate, KnowledgeEdit, KnowledgeUsage
from gateway.util.tasks import fire_and_forget

logger = logging.getLogger(__name__)


class KnowledgeStoreMixin:
    """Knowledge base documents, search and retrieval stats."""

    # Knowledge Base.

    async def _knowledge_limits(self):
        """Resolve the org's knowledge ceilings from its entitlement."""
        from gateway.governance.org_limits import get_org_limits

        return await get_org_limits(self._require_org_id())

    async def list_knowledge_docs(
        self,
        *,
        scope: str | None = None,
        scope_ref: str | None = None,
        category: str | None = None,
        status: str = "active",
        include_body: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> list[KnowledgeDoc]:
        oid = self._require_org_id()
        return await knowledge_mod.list_knowledge_docs(
            self.session,
            org_id=oid,
            scope=scope,
            scope_ref=scope_ref,
            category=category,
            status=status,
            include_body=include_body,
            limit=limit,
            offset=offset,
        )

    async def get_knowledge_doc(
        self, doc_id: str, *, include_body: bool = True, bump_view: bool = False
    ) -> KnowledgeDoc | None:
        import asyncio

        oid = self._require_org_id()
        row = await knowledge_mod.get_knowledge_doc(self.session, org_id=oid, doc_id=doc_id, include_body=include_body)
        if row is None:
            return None
        doc = knowledge_mod._row_to_doc(row, include_body=include_body)
        if bump_view:
            asyncio.create_task(self.increment_knowledge_view(doc_id))
        return doc

    async def get_knowledge_doc_by_key(
        self,
        *,
        scope: str,
        scope_ref: str | None,
        category: str,
        title: str,
        bump_view: bool = False,
    ) -> KnowledgeDoc | None:
        import asyncio

        oid = self._require_org_id()
        row = await knowledge_mod.get_knowledge_doc_by_key(
            self.session,
            org_id=oid,
            scope=scope,
            scope_ref=scope_ref,
            category=category,
            title=title,
        )
        if row is None:
            return None
        doc = knowledge_mod._row_to_doc(row, include_body=True)
        if bump_view:
            asyncio.create_task(self.increment_knowledge_view(doc.id))
        return doc

    async def insert_knowledge_doc(
        self, payload: KnowledgeDocCreate, *, user_id: str | None, agent: str | None = None
    ) -> KnowledgeDoc:
        oid = self._require_org_id()
        limits = await self._knowledge_limits()
        settings = await self.load_settings()
        return await knowledge_mod.insert_knowledge_doc(
            self.session,
            org_id=oid,
            payload=payload,
            user_id=user_id,
            agent=agent,
            limits=limits,
            settings=settings,
        )

    async def upsert_knowledge_doc(
        self, payload: KnowledgeDocCreate, *, user_id: str | None, agent: str | None = None
    ) -> KnowledgeDoc:
        oid = self._require_org_id()
        limits = await self._knowledge_limits()
        settings = await self.load_settings()
        return await knowledge_mod.upsert_knowledge_doc(
            self.session,
            org_id=oid,
            payload=payload,
            user_id=user_id,
            agent=agent,
            limits=limits,
            settings=settings,
        )

    async def update_knowledge_body(
        self,
        doc_id: str,
        *,
        body: str,
        user_id: str | None,
        agent: str | None = None,
    ) -> KnowledgeDoc:
        oid = self._require_org_id()
        limits = await self._knowledge_limits()
        settings = await self.load_settings()
        return await knowledge_mod.update_knowledge_body(
            self.session,
            org_id=oid,
            doc_id=doc_id,
            body=body,
            user_id=user_id,
            agent=agent,
            limits=limits,
            settings=settings,
        )

    async def archive_knowledge_doc(self, doc_id: str) -> bool:
        oid = self._require_org_id()
        return await knowledge_mod.archive_knowledge_doc(self.session, org_id=oid, doc_id=doc_id)

    async def approve_knowledge_doc(self, doc_id: str, *, user_id: str | None) -> KnowledgeDoc:
        oid = self._require_org_id()
        return await knowledge_mod.approve_knowledge_doc(self.session, org_id=oid, doc_id=doc_id, user_id=user_id)

    async def list_knowledge_edits(self, doc_id: str, *, limit: int = 20) -> list[KnowledgeEdit]:
        oid = self._require_org_id()
        return await knowledge_mod.list_knowledge_edits(self.session, org_id=oid, doc_id=doc_id, limit=limit)

    async def search_knowledge(
        self,
        *,
        query: str,
        scope: str | None = None,
        scope_ref: str | None = None,
        category: str | None = None,
        limit: int = 20,
        bump_view: bool = True,
    ) -> list[KnowledgeDoc]:
        import asyncio

        oid = self._require_org_id()
        docs = await knowledge_mod.search_knowledge(
            self.session,
            org_id=oid,
            query=query,
            scope=scope,
            scope_ref=scope_ref,
            category=category,
            limit=limit,
        )
        if bump_view:
            for doc in docs:
                asyncio.create_task(self.increment_knowledge_view(doc.id))
        return docs

    async def search_knowledge_hybrid(
        self,
        *,
        query: str,
        source: str,
        scope: str | None = None,
        scope_ref: str | None = None,
        category: str | None = None,
        limit: int = 20,
        log_events: bool = True,
        bump_view: bool = False,
    ) -> list[knowledge_search_mod.SearchHit]:
        """Hybrid (FTS + lexical + vector) search with retrieval-event logging.

        Use plain ILIKE search when hybrid search fails.
        One background task records retrieval events and view counts for all results.
        """
        oid = self._require_org_id()
        try:
            hits = await knowledge_search_mod.hybrid_search_knowledge(
                self.session,
                org_id=oid,
                query=query,
                scope=scope,
                scope_ref=scope_ref,
                category=category,
                limit=limit,
            )
        except Exception as exc:
            logger.warning("Hybrid knowledge search failed, falling back to ILIKE: %r", exc)
            docs = await knowledge_mod.search_knowledge(
                self.session,
                org_id=oid,
                query=query,
                scope=scope,
                scope_ref=scope_ref,
                category=category,
                limit=limit,
            )
            hits = [knowledge_search_mod.SearchHit(doc=d, score=0.0, arms=["lexical"]) for d in docs]

        events = []
        if log_events and hits:
            events = [
                knowledge_search_mod.RetrievalEvent(
                    org_id=oid,
                    doc_id=h.doc.id,
                    source=source,
                    query=query,
                    user_id=self.user_id,
                    rank=i + 1,
                    score=h.score,
                )
                for i, h in enumerate(hits)
            ]
        bump_ids = [h.doc.id for h in hits] if bump_view else None
        if events or bump_ids:
            fire_and_forget(knowledge_search_mod.log_retrieval_events(events, bump_view_ids=bump_ids))
        return hits

    async def log_knowledge_retrievals(
        self, doc_ids: list[str], *, source: str, query: str | None = None, bump_view: bool = False
    ) -> None:
        """Fire-and-forget retrieval logging for non-search pulls (baseline docs)."""
        oid = self._require_org_id()
        events = [
            knowledge_search_mod.RetrievalEvent(org_id=oid, doc_id=d, source=source, query=query, user_id=self.user_id)
            for d in doc_ids
        ]
        fire_and_forget(knowledge_search_mod.log_retrieval_events(events, bump_view_ids=doc_ids if bump_view else None))

    async def knowledge_retrieval_stats(self, *, since_days: int = 30) -> dict:
        oid = self._require_org_id()
        return await knowledge_search_mod.retrieval_stats(self.session, org_id=oid, since_days=since_days)

    async def get_knowledge_usage(self) -> KnowledgeUsage:
        oid = self._require_org_id()
        limits = await self._knowledge_limits()
        return await knowledge_mod.get_knowledge_usage(self.session, org_id=oid, limits=limits)

    async def increment_knowledge_view(self, doc_id: str) -> None:
        """Best-effort fire-and-forget view counter increment."""
        oid = self._require_org_id()
        from gateway.db.engine import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            await knowledge_mod.increment_knowledge_view(session, org_id=oid, doc_id=doc_id)
