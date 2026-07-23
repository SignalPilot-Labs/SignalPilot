# Feature 1 — Subagent Panel Results (8 ideation + 8 review)

Run: workflow `feature1-kb-search-panels` (16 agents, ~728k tokens).
Ideation lenses: search-quality, agent-UX, ops/scale, product, data-quality,
security/governance, integration, competitive.
Review lenses: correctness, async-safety, SQL/dialect, API design, error handling,
test coverage, maintainability, performance.

## Review findings — APPLIED before commit

| Finding | Severity | Fix |
|---|---|---|
| `get_knowledge` logged 15 retrieval events but delivered ≤5 (category filter after logging) — skewed heat-map | major | hybrid call now `log_events=False`; only delivered docs logged explicitly, both paths consistent |
| Retrieval-event pruning dead when embeddings disabled → unbounded `gateway_knowledge_retrievals` growth | major | loop always runs pruning; only the sync half is gated on embedding config |
| Sync scan loaded every doc body + every embedding vector (ORM entities) across all orgs each pass | major | staleness scan selects light columns only; embedding vectors never loaded during scan |
| Up to ~51 pool checkouts per search (per-hit fire-and-forget view bumps, each own session) | major | view bumps batched into the single retrieval-log background write (one session) |
| `retrieval_stats` fetched every event row into Python | major | SQL GROUP BY (doc, source, bucket) aggregation |
| Fire-and-forget `asyncio.create_task` refs GC-able → silently dropped events | minor | `fire_and_forget()` helper with strong-ref set + done-callback discard |
| FTS arm failure only visible at DEBUG → silent quality degradation | major(test)/minor | warn-once at WARNING level; same for persistent retrieval-log failures |
| Lexical arm dead for long prose queries (whole-string ILIKE) | high (ideation) | tokenized multi-keyword OR'd ILIKE with term-coverage ranking |
| `zip()` silently truncates on short provider response | nit | length check + warning, skip batch |
| No FTS expression index — per-query re-tokenization | minor | `idx_knowledge_fts` GIN expression index added to engine migrations |
| Sync endpoint bypassed Store facade / could sync all orgs if org unset | minor | `Store.sync_knowledge_embeddings()` wrapper with `_require_org_id()` |
| `source` had a default → accidental mislabeled logging | minor | `source` now required kwarg |
| Private `_row_to_doc` cross-module import | minor | public `row_to_doc` added |
| In-function imports of knowledge_search in Store | minor | hoisted to module level, return type annotated |
| Hash-fallback constructed 4× | nit | `_hash_fallback()` local |
| Tests: fallback path, provider matrix, env isolation, archived-after-sync vector, bucket placement, provider-swap re-embed, limit truncation all untested | major | 11 tests added (30 total, all pass) |

## Review findings — NOT applied (deliberate)

- **numpy/pgvector for vector arm** — documented scaling boundary; JSON+Python is right at MB-quota corpus size. Provider-tagged rows make later migration a storage swap.
- **httpx client per embed call** — remote providers only; batch loop reuse is a micro-opt at ≤hundreds of docs. Noted for when a remote provider becomes default.
- **Pydantic response model for /knowledge/retrievals** — deferred to Feature 2 (heatmap UI) where the contract consumer lands.
- **Provider-aware vector floor (0.05 vs hash inflation)** — needs the golden-query harness (below) to calibrate; guessing a higher floor risks recall.
- **Postgres-marked integration test for FTS arm** — suite is SQLite-only by design; FTS arm verified manually against live docker Postgres (long-prose + stemmed queries return correct ranking, no FTS warnings in logs).

## Ideation — implemented now

- **`read_knowledge(doc_ids)` MCP tool** (agent-UX, small/high): search wide → read narrow two-phase retrieval; logs `read_knowledge` source (a much stronger usage signal than result-list appearance).
- **Tokenized multi-term lexical arm** (search-quality, small/high): as above.

## Ideation — best of the backlog (for roadmap)

1. **Chunked embeddings with max-pooling** — long God-Docs partially invisible past 8k chars; add chunk_idx, score doc as max over chunks, return best chunk as snippet. (high/medium)
2. **ts_headline snippets + arm/score provenance in search output** — snippet currently falls back to body[:200] for stemmed/vector-only hits. (high/medium)
3. **Relevance-aware truncation in get_knowledge** — task hits are truncated before low-relevance project baselines; priority-ordered dropping + 500-char stubs. (high/small-medium)
4. **Query decomposition for task descriptions** — multi-variant RRF (raw text for vector, keyword string for FTS/lexical). (high/medium)
5. **Golden-query eval harness** — (query, expected_docs) fixtures + recall@5/MRR per arm; mine `gateway_knowledge_retrievals` for real pairs. Makes weights measurable. (medium/medium)
6. **KB Reflector usage signal** — retrieval log × verification outcomes → staleness/quality proposals. (product, feeds roadmap M2)
7. **Configurable FTS language / unaccent** — hardcoded English stemming hurts non-English KBs. (medium/small)
8. **PII scrubbing for logged queries** — task descriptions can contain customer data; queries stored 90d. Governance review before cloud GA. (security, medium/small)
