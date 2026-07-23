# Feature 4 — Schema-Diff Cron Job → GitHub PR

**Status:** Built, live-tested twice against a real warehouse + real GitHub PRs, reviewed by 8+8 agent panel.

## What was built

Roadmap item #27 ("Scheduled schema-diff watches") upgraded per the sprint brief from
Slack pings to **GitHub PRs**: a watch introspects a connection on an interval, diffs
the schema fingerprint against a durable stored snapshot (the in-memory
`schema_cache` history dies on restart — this doesn't), and on drift opens a PR
adding `schema-watch/<connection>/<date>-<fp>.md` — a reviewable audit trail of
upstream schema changes living next to the dbt code that depends on them.

### Components
- `GatewaySchemaWatch` (db/models.py): org-scoped watch config + inline **structural**
  snapshot (`strip_schema` removes row counts/sizes/stats so the JSON blob doesn't
  churn on unchanged fingerprints) + run/change/PR/error state.
- `gateway/schema_watch/runner.py`:
  - `run_watch` — claim-commit `last_run_at` *before* the slow introspection (no
    double-runs across loop ticks/replicas), per-watch asyncio lock (run-now vs loop),
    read connection info then commit before introspecting (no idle-in-transaction
    gateway session across warehouse/GitHub calls), fresh snapshot shared into
    `schema_cache`, rollback-first error path so `last_error` actually persists.
  - **Deterministic branch names** `schema-watch/<conn>-<fp[:12]>`: a retry after a
    partial failure (PR opened, commit failed / process died) hits
    "reference already exists" and is treated as already-reported — no duplicate PRs.
  - **Empty-diff suppression**: fingerprint hashes nullability/PK/FK which the diff
    doesn't render; such drift advances the baseline silently instead of opening a
    content-free PR (the panel's top noise finding).
  - `run_due_watches` — scalar-column due check (snapshot blobs load only for due
    watches), per-watch sessions, parallelism 3, 600s per-watch deadline: one hung
    warehouse can't stall other orgs' watches.
  - **Org-scoped token resolution** — a watch names an arbitrary repo, so tokens
    resolve only through *this org's* active repo link; shared-PAT fallback is
    local-mode-only. (Panel found the cross-org hole: org A could otherwise PR to
    org B's linked repo with org B's installation token.)
- `gateway/api/schema_watches.py`: list/get/create/delete (+ IntegrityError→409,
  other commit errors surface as 500) and run-now (admin, synchronous for demos).
- `main.py::_schema_watch_loop`: 60s tick.

## Live verification
Watch on `perf_nala_pg` (261 tables) → baseline run → `CREATE TABLE` + `ADD COLUMN`
→ [PR #2](https://github.com/kiwi0401/sp-pipelineproof-test/pull/2)
("+1 table, 1 modified", correct markdown). After the hardening pass:
second mutation → [PR #3] on deterministic branch `schema-watch/perf_nala_pg-cfb0f251c8bb`;
revert → [PR #4] ("-1 table"). Scratch tables cleaned up.

17 unit tests: rendering, PR-flow call sequence (incl. 422 already-exists short-circuit,
wrong-branch guard), `run_watch` core (baseline / unchanged / drift / nullability-only
suppression / missing-token error persistence + fingerprint retention), scheduling.

## Panel outcomes (16 agents, ~591k tokens) — applied
Cross-org token authorization, no-concurrency-control (claim commit + lock + per-watch
sessions/deadline/parallelism), session idle-in-transaction, rollback-before-error-write,
client aclose leak, empty-diff PR spam, duplicate-PR-after-partial-failure
(deterministic branches), full-entity 60s loop select + snapshot churn (scalar due
check + strip_schema), IntegrityError-only 409, GET single endpoint, PR body slimmed
(summary + truncated report instead of full duplicate).

## Backlog (best of ideation)
1. **Ignore rules** — per-watch glob patterns (`*__dbt_tmp`, `_airbyte_*`) filtered
   before fingerprinting; ETL scratch tables are the biggest real-world noise source. (high/medium)
2. **Downstream impact section** — parse the repo's `sources.yml`/models, map drifted
   tables → affected models in the PR ("removed column used by 12 marts"). (high/medium)
3. **Severity classing** — [BREAKING] vs [additive] title prefixes + min_severity gate. (high/medium)
4. **Digest batching** — roll multiple drifts into one open PR per watch. (high/large)
5. **Flap suppression** — confirm drift on a second consecutive run before PR. (medium/medium)
6. **KB cross-reference** — search knowledge base for drifted table names, embed hits;
   propose a KB drift entry. (medium)
7. Diff sensitivity alignment — extend `_compute_schema_diff` to render
   nullability/PK/FK changes (currently suppressed as empty). (medium/small)
8. Create-time validation of repo/base-branch/token reachability. (small)
