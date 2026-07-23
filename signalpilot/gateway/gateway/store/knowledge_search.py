"""Hybrid search + retrieval-event logging for the knowledge base.

Three retrieval arms, fused with Reciprocal Rank Fusion (RRF):

    1. Postgres full-text search  (websearch_to_tsquery + ts_rank_cd)
    2. Lexical keyword search     (tokenized OR'd ILIKE, term-coverage ranked)
    3. BM25                       (pure-Python Okapi BM25, store/kb_rank.py)

No embedding models anywhere — BM25 with word + char-4-gram tokens covers the
fuzzy/variant matching an embedder would, entirely in-process. RRF avoids
score normalization across heterogeneous arms: each arm ranks its candidates
and a doc's fused score is Σ weight/(K + rank). Arms degrade independently —
on SQLite (tests) only arms 2+3 run; the search never fails because one arm
does.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import (
    GatewayKnowledgeDoc,
    GatewayKnowledgeRetrieval,
)
from gateway.models.knowledge import KnowledgeDoc, KnowledgeStatus
from gateway.store.kb_rank import bm25_rank
from gateway.store.knowledge import row_to_doc

logger = logging.getLogger(__name__)

_RRF_K = 60
_ARM_WEIGHTS = {"fts": 1.0, "bm25": 1.0, "lexical": 0.7}
_ARM_CANDIDATES = 50
_RETRIEVAL_RETENTION_DAYS = 90
_MAX_LEXICAL_KEYWORDS = 8

_STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "for", "in", "on", "at", "to", "of",
        "with", "by", "from", "as", "is", "it", "its", "be", "was", "are",
        "were", "not", "but", "if", "do", "did", "has", "have", "had",
        "this", "that", "these", "those", "can", "will", "would", "could",
        "should", "may", "might", "shall", "use", "using", "used", "how",
        "what", "when", "where", "which", "who", "why",
    }
)

from gateway.util.tasks import fire_and_forget  # re-export; shared helper


def content_hash(title: str, body: str) -> str:
    return hashlib.sha256(f"{title}\n{body}".encode()).hexdigest()


def _is_postgres(session: AsyncSession) -> bool:
    bind = session.get_bind()
    return bind is not None and bind.dialect.name == "postgresql"


def extract_keywords(query: str, *, max_keywords: int = _MAX_LEXICAL_KEYWORDS) -> list[str]:
    """Significant lowercase word tokens from a free-text query, order-preserved."""
    seen: set[str] = set()
    out: list[str] = []
    for token in re.findall(r"[a-zA-Z0-9_-]{3,}", query.lower()):
        if token in _STOPWORDS or token in seen:
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= max_keywords:
            break
    return out


@dataclass
class SearchHit:
    doc: KnowledgeDoc
    score: float
    arms: list[str] = field(default_factory=list)


# ── Retrieval arms ────────────────────────────────────────────────────────────


_fts_warned = False


async def _fts_arm(
    session: AsyncSession,
    *,
    org_id: str,
    query: str,
    scope: str | None,
    scope_ref: str | None,
    category: str | None,
) -> list[str]:
    """Ranked doc IDs from Postgres full-text search. Empty off-Postgres."""
    global _fts_warned
    if not _is_postgres(session):
        return []
    filters = ["org_id = :org_id", "status = 'active'"]
    params: dict = {"org_id": org_id, "q": query, "n": _ARM_CANDIDATES}
    if scope is not None:
        filters.append("scope = :scope")
        params["scope"] = scope
    if scope_ref is not None:
        filters.append("scope_ref = :scope_ref")
        params["scope_ref"] = scope_ref
    if category is not None:
        filters.append("category = :category")
        params["category"] = category
    sql = (
        "SELECT id FROM gateway_knowledge_docs "
        f"WHERE {' AND '.join(filters)} "
        "AND to_tsvector('english', title || ' ' || body) @@ websearch_to_tsquery('english', :q) "
        "ORDER BY ts_rank_cd(to_tsvector('english', title || ' ' || body), "
        "websearch_to_tsquery('english', :q)) DESC "
        "LIMIT :n"
    )
    try:
        result = await session.execute(text(sql), params)
        return [row[0] for row in result.fetchall()]
    except Exception as exc:
        # A broken FTS arm silently degrades search quality — surface it once
        # at WARNING so operators notice, then stay quiet.
        if not _fts_warned:
            _fts_warned = True
            logger.warning("FTS search arm failed (degrading to lexical+vector): %r", exc)
        else:
            logger.debug("FTS arm failed (query=%r): %r", query, exc)
        return []


async def _lexical_arm(
    session: AsyncSession,
    *,
    org_id: str,
    query: str,
    scope: str | None,
    scope_ref: str | None,
    category: str | None,
) -> list[str]:
    """Ranked doc IDs from tokenized keyword ILIKE search.

    The query is split into significant keywords OR'd together, ranked by term
    coverage (title matches weighted 2x). This keeps the arm alive for long
    free-text queries (task descriptions) where a whole-string substring match
    would never fire.
    """
    keywords = extract_keywords(query)
    if not keywords:
        return []

    def _pat(kw: str) -> str:
        esc = kw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{esc}%"

    conds = [
        GatewayKnowledgeDoc.title.ilike(_pat(kw)) | GatewayKnowledgeDoc.body.ilike(_pat(kw))
        for kw in keywords
    ]
    stmt = (
        select(GatewayKnowledgeDoc.id, GatewayKnowledgeDoc.title, GatewayKnowledgeDoc.body)
        .where(
            GatewayKnowledgeDoc.org_id == org_id,
            GatewayKnowledgeDoc.status == KnowledgeStatus.active.value,
            or_(*conds),
        )
        .limit(_ARM_CANDIDATES * 2)
    )
    if scope is not None:
        stmt = stmt.where(GatewayKnowledgeDoc.scope == scope)
    if scope_ref is not None:
        stmt = stmt.where(GatewayKnowledgeDoc.scope_ref == scope_ref)
    if category is not None:
        stmt = stmt.where(GatewayKnowledgeDoc.category == category)
    try:
        rows = (await session.execute(stmt)).fetchall()
    except Exception as exc:
        logger.debug("Lexical arm failed (query=%r): %r", query, exc)
        return []

    q_full = query.lower().strip()
    scored: list[tuple[float, str]] = []
    for doc_id, title, body in rows:
        title_l = title.lower()
        body_l = body.lower()
        coverage = sum(2.0 if kw in title_l else (1.0 if kw in body_l else 0.0) for kw in keywords)
        if q_full and q_full in title_l:
            coverage += 4.0  # exact whole-query title match dominates
        elif q_full and q_full in body_l:
            coverage += 2.0
        if coverage > 0:
            scored.append((coverage, doc_id))
    scored.sort(key=lambda p: p[0], reverse=True)
    return [doc_id for _, doc_id in scored[:_ARM_CANDIDATES]]


async def _bm25_arm(
    session: AsyncSession,
    *,
    org_id: str,
    query: str,
    scope: str | None,
    scope_ref: str | None,
    category: str | None,
) -> list[str]:
    """Ranked doc IDs from in-process BM25 over the org's active docs.

    The corpus is quota-capped to megabytes, so fetching (id, title, body)
    and scoring per query is cheap — no persistent index, no models.
    """
    stmt = select(
        GatewayKnowledgeDoc.id, GatewayKnowledgeDoc.title, GatewayKnowledgeDoc.body
    ).where(
        GatewayKnowledgeDoc.org_id == org_id,
        GatewayKnowledgeDoc.status == KnowledgeStatus.active.value,
    )
    if scope is not None:
        stmt = stmt.where(GatewayKnowledgeDoc.scope == scope)
    if scope_ref is not None:
        stmt = stmt.where(GatewayKnowledgeDoc.scope_ref == scope_ref)
    if category is not None:
        stmt = stmt.where(GatewayKnowledgeDoc.category == category)
    try:
        rows = (await session.execute(stmt)).fetchall()
    except Exception as exc:
        logger.debug("BM25 arm failed (query=%r): %r", query, exc)
        return []
    scored = bm25_rank(query, [(r[0], r[1], r[2]) for r in rows], limit=_ARM_CANDIDATES)
    return [doc_id for doc_id, _ in scored]


# ── Fusion ────────────────────────────────────────────────────────────────────


async def hybrid_search_knowledge(
    session: AsyncSession,
    *,
    org_id: str,
    query: str,
    scope: str | None,
    scope_ref: str | None,
    category: str | None,
    limit: int,
) -> list[SearchHit]:
    """RRF-fused hybrid search. Returns hits sorted by fused score."""
    fts_ids = await _fts_arm(
        session, org_id=org_id, query=query, scope=scope, scope_ref=scope_ref, category=category
    )
    lex_ids = await _lexical_arm(
        session, org_id=org_id, query=query, scope=scope, scope_ref=scope_ref, category=category
    )
    bm25_ids = await _bm25_arm(
        session, org_id=org_id, query=query, scope=scope, scope_ref=scope_ref, category=category
    )

    fused: dict[str, float] = {}
    arms_by_doc: dict[str, list[str]] = {}
    for arm_name, ranked in (("fts", fts_ids), ("lexical", lex_ids), ("bm25", bm25_ids)):
        weight = _ARM_WEIGHTS[arm_name]
        for rank, doc_id in enumerate(ranked):
            fused[doc_id] = fused.get(doc_id, 0.0) + weight / (_RRF_K + rank + 1)
            arms_by_doc.setdefault(doc_id, []).append(arm_name)

    if not fused:
        return []

    top_ids = sorted(fused, key=lambda d: fused[d], reverse=True)[: max(1, limit)]
    result = await session.execute(
        select(GatewayKnowledgeDoc).where(
            GatewayKnowledgeDoc.id.in_(top_ids),
            GatewayKnowledgeDoc.org_id == org_id,
            GatewayKnowledgeDoc.status == KnowledgeStatus.active.value,
        )
    )
    rows = {r.id: r for r in result.scalars().all()}
    hits = [
        SearchHit(doc=row_to_doc(rows[doc_id], include_body=True), score=fused[doc_id], arms=arms_by_doc[doc_id])
        for doc_id in top_ids
        if doc_id in rows
    ]
    return hits


# ── Retrieval-event logging ───────────────────────────────────────────────────


@dataclass
class RetrievalEvent:
    org_id: str
    doc_id: str
    source: str  # get_knowledge_baseline | get_knowledge_task | search_knowledge | read_knowledge
    query: str | None = None
    user_id: str | None = None
    rank: int | None = None
    score: float | None = None


_retrieval_log_warned = False


async def log_retrieval_events(events: list[RetrievalEvent], *, bump_view_ids: list[str] | None = None) -> None:
    """Best-effort hot-path retrieval logging in a dedicated session.

    Optionally batches view-count bumps into the same session/transaction so a
    search burst costs one pool checkout instead of one per hit. Swallows all
    errors — losing a retrieval event must never fail a search — but warns
    once if writes are persistently failing (missing table, permissions).
    """
    global _retrieval_log_warned
    if not events and not bump_view_ids:
        return
    try:
        from gateway.db.engine import get_session_factory

        now = time.time()
        factory = get_session_factory()
        async with factory() as session:
            for ev in events:
                session.add(
                    GatewayKnowledgeRetrieval(
                        id=str(uuid.uuid4()),
                        org_id=ev.org_id,
                        doc_id=ev.doc_id,
                        source=ev.source,
                        query=(ev.query or "")[:300] or None,
                        user_id=ev.user_id,
                        rank=ev.rank,
                        score=ev.score,
                        ts=now,
                    )
                )
            if bump_view_ids:
                await session.execute(
                    update(GatewayKnowledgeDoc)
                    .where(GatewayKnowledgeDoc.id.in_(bump_view_ids))
                    .values(view_count=GatewayKnowledgeDoc.view_count + 1)
                )
            await session.commit()
    except Exception as exc:
        if not _retrieval_log_warned:
            _retrieval_log_warned = True
            logger.warning("Knowledge retrieval logging is failing (heat-map will be empty): %r", exc)
        else:
            logger.debug("log_retrieval_events failed (%d events): %r", len(events), exc)


async def prune_retrieval_events(session: AsyncSession, *, retention_days: int = _RETRIEVAL_RETENTION_DAYS) -> int:
    """Delete retrieval events older than the retention window."""
    cutoff = time.time() - retention_days * 86400
    result = await session.execute(delete(GatewayKnowledgeRetrieval).where(GatewayKnowledgeRetrieval.ts < cutoff))
    await session.commit()
    return result.rowcount or 0


# ── Retrieval stats (heat-map feed) ──────────────────────────────────────────


async def retrieval_stats(
    session: AsyncSession,
    *,
    org_id: str,
    since_days: int = 30,
    bucket_days: int = 1,
) -> dict:
    """Per-doc retrieval counts plus a daily time series for the heat-map UI.

    Aggregated in SQL (GROUP BY doc, source, bucket) so the endpoint reads
    O(docs × sources × buckets) rows, not one row per event. Returns {
      "since_days", "bucket_days", "generated_at",
      "docs": [{doc_id, total, by_source: {src: n}, last_retrieved_at, series: [n, ...]}],
    } — series buckets run oldest → newest, len == since_days // bucket_days.
    """
    since = time.time() - since_days * 86400
    n_buckets = max(1, since_days // bucket_days)
    bucket_span = since_days * 86400 / n_buckets

    bucket_expr = func.floor((GatewayKnowledgeRetrieval.ts - since) / bucket_span)
    stmt = (
        select(
            GatewayKnowledgeRetrieval.doc_id,
            GatewayKnowledgeRetrieval.source,
            bucket_expr.label("bucket"),
            func.count().label("n"),
            func.max(GatewayKnowledgeRetrieval.ts).label("last_ts"),
        )
        # Join docs so events for since-archived/deleted docs don't inflate
        # totals the heat-map UI can't attribute to a visible row.
        .join(GatewayKnowledgeDoc, GatewayKnowledgeDoc.id == GatewayKnowledgeRetrieval.doc_id)
        .where(
            GatewayKnowledgeRetrieval.org_id == org_id,
            GatewayKnowledgeRetrieval.ts >= since,
            GatewayKnowledgeDoc.status == KnowledgeStatus.active.value,
        )
        .group_by(GatewayKnowledgeRetrieval.doc_id, GatewayKnowledgeRetrieval.source, bucket_expr)
    )
    result = await session.execute(stmt)

    docs: dict[str, dict] = {}
    for doc_id, source, bucket, n, last_ts in result.fetchall():
        entry = docs.setdefault(
            doc_id,
            {"doc_id": doc_id, "total": 0, "by_source": {}, "last_retrieved_at": None, "series": [0] * n_buckets},
        )
        entry["total"] += n
        entry["by_source"][source] = entry["by_source"].get(source, 0) + n
        if entry["last_retrieved_at"] is None or last_ts > entry["last_retrieved_at"]:
            entry["last_retrieved_at"] = last_ts
        idx = min(n_buckets - 1, max(0, int(bucket)))
        entry["series"][idx] += n
    ranked = sorted(docs.values(), key=lambda d: d["total"], reverse=True)
    return {
        "since_days": since_days,
        "bucket_days": bucket_days,
        "generated_at": time.time(),
        "docs": ranked,
    }
