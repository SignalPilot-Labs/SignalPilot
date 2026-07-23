# Feature 3 — GitHub Bot (PipelineProof PR bot MVP)

**Status:** Built, live-tested against a real GitHub PR + real warehouse, reviewed by 8+8 agent panel.

## What was built

The roadmap's "PipelineProof PR bot MVP" (research-7-20/06, item #2; realism audit 17 §3.1):
when a PR changes dbt models, verify them against the governed warehouse and post a
report comment + commit status. **Report-first — the bot never blocks a merge itself.**

### Components

- `gateway/github_bot/client.py` — minimal GitHub REST client. Persistent
  httpx.AsyncClient per scan, retry w/ backoff honoring `Retry-After` (403 secondary
  rate limits, 429, 5xx), comment **upsert** keyed on an HTML marker (re-scans edit in
  place; PATCH-404 falls back to create), commit statuses under context
  `signalpilot/pipelineproof`, plus branch/file/PR helpers (used by Feature 4).
- `gateway/github_bot/scanner.py` — verification core:
  - `parse_changed_models`: `models/**/*.sql`, removed files excluded, names validated.
  - Schema resolution: bare model names resolved across all non-system schemas via
    information_schema (dbt materializes into per-project schemas — `public` is wrong).
  - **Single-pass aggregate** per model: row count + `COUNT(DISTINCT key)` + 40-column
    null saturation in ONE query (3× cost cut vs naive; matters on RPU/bytes-billed
    warehouses), 60s query timeout, 30-model cap per scan (rest reported skipped).
  - Grain key: `id`/`{model}_id`/`pk`/`surrogate_key`, with first-column-`*_id`
    fallback. Duplicates on a *declared-pattern* key ⇒ fail; on the fallback (may be a
    fact-table FK) ⇒ warn with the fan-out factor — avoids false-fail credibility hits.
  - Verdicts: fail (missing table, grain dups) / warn (0 rows, null-saturated cols,
    scan errors) / pass.
- `gateway/github_bot/runner.py` — orchestration (kept out of the API layer):
  per-(repo, PR) **cancel-and-replace** so an older slow scan can never overwrite newer
  results, global semaphore (4) capping warehouse load, 30-min scan deadline,
  sanitized commit-status text (no exception URLs/hostnames leak to the PR).
- `gateway/api/github_bot.py` — `POST /api/github/webhook` (HMAC-sha256; auth/CSRF
  exempt; unsigned allowed only in local mode, cloud 503s without a secret; org
  resolved from repo link, lookup *failure* 503s so GitHub redelivers) and
  `POST /api/github/bot/scan` (admin, synchronous re-run).
- `gateway/store/github.py` — `_resolve_repo_link` (oldest-active-link, deterministic
  across multi-org links) powering token + org resolution; installation token
  preferred, `SP_GITHUB_BOT_TOKEN` PAT fallback (fallback now logged at WARNING).
- `gateway/util/tasks.py` — shared `fire_and_forget` (extracted from knowledge_search).

### Config
`SP_GITHUB_BOT_TOKEN` (PAT for local testing), `SP_GITHUB_WEBHOOK_SECRET`,
`SP_GITHUB_BOT_CONNECTION` (default verification connection; unset short-circuits with
a clear "bot not configured" report instead of fabricated per-model failures).
Compose passthrough added (token never committed).

## Live verification (real GitHub, real warehouse)

Private repo `kiwi0401/sp-pipelineproof-test`, PR #1 (one real model, one ghost):
- `stg_fx__fx_rates` → ✅ pass — 3,485,520 rows, grain `rate_id` unique, auto-resolved
  to `analytics_staging.stg_fx__fx_rates` on connection `perf_nala_pg`.
- `fct_ghost_model` → ❌ "table not found — has the model been materialized?"
- Commit status: `signalpilot/pipelineproof — 2 model(s) verified — 1 failing`.
- Re-scans **edited the same comment** (marker upsert verified twice, incl. after the
  single-pass refactor).
- Webhook: synthetic signed/unsigned deliveries → ping/pong, action filtering,
  background scan scheduled and executed.
- 22 unit tests (parsing, rendering, signatures, single-pass check logic incl.
  FK-fallback warn, real `_get_columns` resolution incl. alphabetical tie-break).

## Panel outcomes (16 agents, ~660k tokens) — applied

Comment-upsert/status race (cancel-and-replace + semaphore), 3-full-scans→1 aggregate,
no timeout/cap/deadline → all added, unset-connection guard, FK-fallback false-fail →
warn, retry/backoff + Retry-After, PATCH-404 fallback, persistent AsyncClient, error
text sanitization (status + 502 body), org-lookup failure → 503 (GitHub redelivers),
PAT-fallback logging, orchestration moved to runner (schema_watch precedent), shared
fire_and_forget, `_resolve_repo_link` dedup + determinism.

## Backlog (best of ideation)

1. **Fan-out vs sources** — parse `ref()`/`source()` from changed SQL (contents API),
   compare model row count vs upstreams with the 0.5×/2.0× thresholds from
   `audit_model_sources` — the real fan-out detector. (high/medium)
2. **schema.yml awareness** — declared `unique`/`not_null` tests as the authoritative
   grain key (incl. composite), ephemeral/materialization configs to kill
   "table not found" false-positives, `+schema` configs for deterministic resolution.
   (high/medium — flagged as the biggest correctness risk by the panel)
3. **Constant-column detection** folded into the aggregate pass. (high/small)
4. **Per-repo connection mapping** instead of one global env var. (high/small)
5. **Row-count drift between pushes** ("3.48M → 1.2M since last push") via a
   gateway_github_scans table. (medium/medium)
6. **Checks API** (annotations, re-run button) over statuses; webhook delivery-GUID
   dedup; 3000-file PR truncation note. (medium)
7. GitHub Action wrapper + GitLab CI. (Q2 roadmap)

## Known limitations
- PAT mode identity is the user, not a bot app (App installation path exists and is
  preferred when a repo link exists).
- Warn verdict maps to status "success" (visible in the comment only) — deliberate
  report-first choice, documented here per panel note.
- Local gateway is not internet-reachable; webhook tested with synthetic deliveries.
  Real GitHub→gateway webhooks need a public URL or smee.io relay (human task list).
