"""Speed benchmark for the KB search algorithm at 200 / 1,000 / 10,000 entries.

Run manually (not part of the test suite):
    python benchmarks/kb_search_bench.py

Two measurements per corpus size:
  1. bm25_rank cold      — the real production path: score the whole corpus per
                           query, including tokenization (no cached index).
  2. hybrid end-to-end   — hybrid_search_knowledge on in-memory SQLite
                           (lexical ILIKE arm + BM25 arm + RRF fusion),
                           i.e. what one search request actually costs minus
                           Postgres FTS and network.

Synthetic docs are deterministic (seeded RNG): titles 3–6 words, bodies
120–400 words drawn from a 2,200-word vocabulary plus per-doc anchor terms so
queries have realistic selectivity.
"""

from __future__ import annotations

import asyncio
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[0] / ".."))

from gateway.store.kb_rank import Bm25Index, bm25_rank  # noqa: E402

SIZES = [200, 1_000, 10_000]
N_QUERY_ROUNDS = 20

_DOMAIN = (
    "revenue invoice billing refund charge claim ledger payout margin churn "
    "warehouse redshift snowflake databricks duckdb postgres schema table column "
    "grain fanout join duplicate aggregate incremental snapshot mart staging "
    "model verify governance audit knowledge agent pipeline drift metric "
).split()

QUERIES = [
    "revenue recognition invoice",
    "join fan-out duplicates",
    "redshift serverless quirks",
    "incremental model late arriving facts",
    "refund window store credit",
    "grain check duplicate keys",
    "recognising revenue monthly reports",  # variant spelling → n-gram path
    "schema drift alerting",
    "warehouse cost governance budget",
    "snapshot strategy scd two",
]


def _vocab(rng: random.Random) -> list[str]:
    words = list(_DOMAIN)
    for i in range(2_000):
        n = rng.randint(4, 10)
        words.append("".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(n)))
    return words


def make_corpus(n_docs: int) -> list[tuple[str, str, str]]:
    rng = random.Random(42)
    vocab = _vocab(rng)
    docs = []
    for i in range(n_docs):
        title = " ".join(rng.choice(vocab) for _ in range(rng.randint(3, 6)))
        body_words = [rng.choice(vocab) for _ in range(rng.randint(120, 400))]
        # sprinkle domain anchors so queries hit a realistic subset
        for _ in range(rng.randint(2, 8)):
            body_words.insert(rng.randrange(len(body_words)), rng.choice(_DOMAIN))
        docs.append((f"doc-{i}", title, " ".join(body_words)))
    return docs


def bench_bm25(docs: list[tuple[str, str, str]]) -> dict:
    timings: list[float] = []
    hits_total = 0
    for _ in range(N_QUERY_ROUNDS):
        for q in QUERIES:
            t0 = time.perf_counter()
            result = bm25_rank(q, docs, limit=50)
            timings.append((time.perf_counter() - t0) * 1000)
            hits_total += len(result)
    return _stats(timings, hits_total)


def bench_bm25_indexed(docs: list[tuple[str, str, str]]) -> tuple[float, dict]:
    """Build the inverted index once (returns build ms), then query it."""
    t0 = time.perf_counter()
    index = Bm25Index(docs)
    build_ms = (time.perf_counter() - t0) * 1000
    timings: list[float] = []
    hits_total = 0
    for _ in range(N_QUERY_ROUNDS):
        for q in QUERIES:
            t0 = time.perf_counter()
            result = index.rank(q, limit=50)
            timings.append((time.perf_counter() - t0) * 1000)
            hits_total += len(result)
    return build_ms, _stats(timings, hits_total)


async def bench_hybrid(docs: list[tuple[str, str, str]]) -> dict:
    import uuid

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from gateway.db.models import GatewayBase, GatewayKnowledgeDoc
    from gateway.store.knowledge_search import hybrid_search_knowledge

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = time.time()
    async with factory() as session:
        for batch_start in range(0, len(docs), 500):
            for doc_id, title, body in docs[batch_start : batch_start + 500]:
                session.add(
                    GatewayKnowledgeDoc(
                        id=doc_id or str(uuid.uuid4()),
                        org_id="bench",
                        scope="org",
                        scope_ref=None,
                        category="decisions",
                        title=title[:120],
                        body=body,
                        status="active",
                        bytes=len(body.encode()),
                        view_count=0,
                        created_at=now,
                        updated_at=now,
                    )
                )
            await session.commit()

        timings: list[float] = []
        hits_total = 0
        for _ in range(3):  # fewer rounds — includes DB fetch per query
            for q in QUERIES:
                t0 = time.perf_counter()
                hits = await hybrid_search_knowledge(
                    session, org_id="bench", query=q, scope=None, scope_ref=None, category=None, limit=20
                )
                timings.append((time.perf_counter() - t0) * 1000)
                hits_total += len(hits)
    await engine.dispose()
    return _stats(timings, hits_total)


def _stats(timings: list[float], hits_total: int) -> dict:
    return {
        "n": len(timings),
        "mean_ms": statistics.mean(timings),
        "p50_ms": statistics.median(timings),
        "p95_ms": sorted(timings)[int(len(timings) * 0.95) - 1],
        "max_ms": max(timings),
        "avg_hits": hits_total / len(timings),
    }


def main() -> None:
    print(f"{'size':>7} | {'phase':<14} | {'mean':>8} | {'p50':>8} | {'p95':>8} | {'max':>8} | hits/q")
    print("-" * 78)
    for size in SIZES:
        docs = make_corpus(size)
        corpus_mb = sum(len(t) + len(b) for _, t, b in docs) / 1e6
        r = bench_bm25(docs)
        print(
            f"{size:>7} | {'bm25 cold':<14} | {r['mean_ms']:>6.1f}ms | {r['p50_ms']:>6.1f}ms "
            f"| {r['p95_ms']:>6.1f}ms | {r['max_ms']:>6.1f}ms | {r['avg_hits']:>5.1f}   (corpus {corpus_mb:.1f} MB)"
        )
        build_ms, ri = bench_bm25_indexed(docs)
        print(
            f"{size:>7} | {'bm25 indexed':<14} | {ri['mean_ms']:>6.1f}ms | {ri['p50_ms']:>6.1f}ms "
            f"| {ri['p95_ms']:>6.1f}ms | {ri['max_ms']:>6.1f}ms | {ri['avg_hits']:>5.1f}   (build {build_ms:.0f}ms once)"
        )
        h = asyncio.run(bench_hybrid(docs))
        print(
            f"{size:>7} | {'hybrid sqlite':<14} | {h['mean_ms']:>6.1f}ms | {h['p50_ms']:>6.1f}ms "
            f"| {h['p95_ms']:>6.1f}ms | {h['max_ms']:>6.1f}ms | {h['avg_hits']:>5.1f}"
        )


if __name__ == "__main__":
    main()
