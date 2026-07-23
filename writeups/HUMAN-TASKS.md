# Human-Required Tasks — feature-sprint-7-22

Things I could not do autonomously (credentials, external accounts, product sign-off).
Everything below the line is configured/stubbed and ready — these are the last-mile
switches only you can flip.

## Credentials / accounts

1. **GitHub App for the PR bot (production path).** The bot currently runs in PAT mode
   (`SP_GITHUB_BOT_TOKEN`, tested live via your `gh` token against
   `kiwi0401/sp-pipelineproof-test` — PRs #1–#4 there are the test artifacts; delete
   the repo when done). For real use: register/verify the SignalPilot GitHub App,
   set a **webhook URL** (needs a public gateway URL or smee.io relay in dev) and
   `SP_GITHUB_WEBHOOK_SECRET`, and link repos via the existing /settings/github flow.
   Also set `SP_GITHUB_BOT_CONNECTION` per deployment (compose default: perf_nala_pg).
2. ~~Embeddings provider decision~~ — resolved: embeddings were removed entirely in
   favor of pure-Python BM25 (`gateway/store/kb_rank.py`). Nothing to configure.
3. **Snowflake account with Semantic Views + Databricks workspace with Metric
   Views** to live-validate MetricProof (Feature 6). All parsing/SQL construction is
   tested against documented formats; the two MCP tools are registered. A free-trial
   Snowflake + Databricks Express workspace each with one semantic/metric view is
   enough. Same accounts unlock live Databricks connector tests (Feature 5's suite is
   mock-based by design).
4. **dbt Fusion on a real project.** `dbt-fusion 2.0.0-preview.202` probes clean;
   compat fixes are tested on captured fixtures. Worth one manual pass of your real
   dbt project under Fusion (`curl -fsSL https://public.cdn.getdbt.com/fs/install/install.sh | sh`)
   — especially the dbt-proxy postgres path (needs `DBT_ALLOW_EXPERIMENTAL_ADAPTERS=true`).

## Decisions / sign-off

5. **Schema-watch rollout**: pick which connections get watches + intervals + target
   repos (`POST /api/schema-watches`). Consider the ignore-pattern backlog item before
   watching ETL-heavy warehouses (dbt tmp tables will look like drift).
6. **UX review**: click through the overhauled console (screenshots in
   `signalpilot/web/e2e-ux-*.png`, rationale in `signalpilot/web/UX.md`). Two scoped
   design layers were deliberately left (knowledge page, evals transcript viewer) —
   say the word if you want them re-skinned to match.
7. **Retrieval-log privacy**: agent task descriptions are stored 90 days in
   `gateway_knowledge_retrievals.query` for the heatmap. Fine locally; needs a
   PII/retention decision before cloud GA.
8. **Benchmark harness under Fusion**: the faketime LD_PRELOAD shim won't intercept
   the Rust binary — deterministic-time strategy needs a decision (env-var time
   injection vs container clock) before running trap-arena evals on Fusion.

## Cleanup

9. `kiwi0401/sp-pipelineproof-test` — private scratch repo created for live bot
   testing. Keep as a demo or delete.
10. The `nala-warehouse-pg` container was attached to the `signalpilot_default`
    docker network for testing (`docker network connect`) — persistent; detach if
    unwanted.
11. Local pip installed `aiosqlite` into the sp-dev-work conda env (test dependency
    that was missing locally; it's already in the gateway's dev extras).
