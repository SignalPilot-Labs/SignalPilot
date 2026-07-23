# Feature 1 — KB Semantic Search

**Status:** Built, tested (unit + live docker), reviewed by 8-agent panel.
**Branch:** `feature-sprint-7-22`

## What was built

Hybrid semantic search for the knowledge base, replacing the ILIKE-only search
(`store/knowledge.py:563`) that the realism audit (research-7-20/17, §1.3) flagged as the
top greenfield gap — plus the per-retrieval event logging that the roadmap's whole
"knowledge loop" (semantic search → tracking → heat-map → Reflector) depends on.

### Architecture

Three retrieval arms fused with **Reciprocal Rank Fusion** (K=60):

| Arm | Implementation | Weight | Degrades when |
|---|---|---|---|
| Full-text | Postgres `websearch_to_tsquery` + `ts_rank_cd` | 1.0 | non-Postgres (tests) |
| Lexical | legacy ILIKE search (title hits ranked first) | 0.7 | never |
| Vector | cosine over per-doc embeddings, computed in-process | 1.0 | embeddings disabled |

RRF was chosen over score blending because the three arms produce incomparable score
scales; rank fusion needs no normalization and degrades gracefully when an arm is empty.

**Embeddings** are stored one-per-doc as JSON float lists in
`gateway_knowledge_embeddings` — deliberately **no pgvector**: org KB quota is megabytes
(≤ a few hundred docs), so loading an org's vectors and doing cosine in Python is
microseconds, avoids a Postgres image swap, and keeps the aiosqlite test suite runnable.
The `provider` + `content_hash` columns make staleness self-describing; a provider/model
swap or doc edit automatically triggers re-embedding by the background loop
(`main.py::_knowledge_embedding_loop`, interval `SP_EMBEDDINGS_SYNC_INTERVAL`, default 300s).

**Providers** (`gateway/embeddings/__init__.py`):
- `hash` (default) — deterministic char-3/4/5-gram + word feature hashing, signed-hash
  trick, L2-normalized, 384-dim. Zero deps, offline, deterministic across processes.
  Lexical-semantic (typo tolerance, partial overlap) rather than truly semantic.
- `openai` — any OpenAI-compatible `/embeddings` endpoint (OpenAI, Ollama, vLLM, TEI).
- `voyage` — Voyage AI.
Misconfiguration falls back to `hash` with a warning rather than breaking search.

**Retrieval events** (`gateway_knowledge_retrievals`): every agent-side doc pull is
logged fire-and-forget with source (`get_knowledge_baseline` | `get_knowledge_task` |
`search_knowledge`), query, rank, score, user. Human browsing in the web UI is
deliberately **not** logged so the heat-map reflects agent usage only (same philosophy as
the existing `view_count` comment in `api/knowledge.py`). 90-day retention, pruned by the
sync loop.

**`get_knowledge` upgrade:** task-specific retrieval now runs one hybrid search over the
full task description (instead of up to 12 sequential per-keyword ILIKE queries), with
the keyword loop retained as a recall backstop when the semantic pass returns nothing.

### New API surface

- `GET /api/knowledge?q=` — now hybrid (was ILIKE)
- `GET /api/knowledge/retrievals?since_days=` — per-doc totals, by-source counts, daily
  series (heat-map feed for Feature 2)
- `POST /api/knowledge/embeddings/sync` — admin: force re-index after config change

### Config

| Var | Default | Purpose |
|---|---|---|
| `SP_EMBEDDINGS_PROVIDER` | `hash` | `hash` \| `openai` \| `voyage` \| `none` |
| `SP_EMBEDDINGS_MODEL` | provider default | model name |
| `SP_EMBEDDINGS_API_KEY` | — | for openai/voyage |
| `SP_EMBEDDINGS_BASE_URL` | — | OpenAI-compat override (Ollama etc.) |
| `SP_EMBEDDINGS_DIM` | provider default | output dimension |
| `SP_EMBEDDINGS_SYNC_INTERVAL` | 300 | reconcile loop seconds, 0 = off |

## Verification

- `tests/test_knowledge_search.py`: 19 tests (embedder determinism/similarity, sync
  lifecycle incl. edit-triggered re-embed and archive cleanup, hybrid ranking, org
  isolation, category filters, stats aggregation, retention pruning). All pass.
  Pre-existing `test_knowledge_mcp.py` failures (19) exist identically on the baseline
  commit — eval-upload WIP breakage, not from this feature.
- Live docker: created docs via REST, forced sync (`{"embedded":2}`), semantic query
  "recognising invoice revenue" (British spelling, no exact substring) correctly ranked
  the revenue-recognition doc first; MCP `search_knowledge` call logged retrieval events
  visible in `/api/knowledge/retrievals` with correct source and daily series.

## Panel outcomes

See `writeups/feature-1-panels.md` for the full 8-ideation + 8-review agent output and
which findings were applied.

## Follow-ups deliberately not done

- pgvector + HNSW index: the JSON/Python design is right at current scale; the
  `provider`-tagged rows make a later pgvector migration a pure storage swap.
- Chunking long docs: docs are capped small; single-vector-per-doc is adequate.
- True semantic default: needs an API key decision (human) — see final human-task list.

## Addendum (2026-07-23): embeddings replaced by pure-Python BM25

Per review feedback the embedding machinery was judged too fancy for a KB-sized
corpus and removed wholesale: no providers, no `gateway_knowledge_embeddings`
table (dropped by migration), no background sync loop, no `SP_EMBEDDINGS_*`
config, no sync endpoint. The vector arm is now **Okapi BM25** implemented in
one dependency-free module (`gateway/store/kb_rank.py`, ~100 lines): word
tokens + character 4-grams (typo/variant tolerance — the British-spelling
live test still ranks correctly), title tokens triple-weighted, IDF-weighted
scoring computed in-process at query time. RRF fusion, retrieval logging, and
all API/MCP surfaces are unchanged apart from the removed sync endpoint.
126 sprint tests green after the swap; live docker verification repeated.
