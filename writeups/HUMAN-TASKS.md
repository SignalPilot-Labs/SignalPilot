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

## Demo connector (added 2026-07-23)

Items 12–13 (Xata billing, loading parallax) are **DONE as of 2026-07-27** —
billing is active, both warehouses are provisioned and loaded, and the whole
journey was verified live. What is left:

12. **`XATA_KEY` must go into AWS Secrets Manager before this ships.** It is the
    org-wide Xata control-plane key. The gateway now resolves it per request and
    never writes it into a workspace's connection record (connections store
    `xata_credential_ref: "demo"` instead — see
    `gateway/connectors/xata_creds.py`), so the only copy in production is
    whatever the secret store holds. Inject it as the `XATA_KEY` env var.
13. **`SP_DEMO_CATALOG` is the one config knob** (root `.env` +
    `signalpilot/gateway/.env.local` + docker-compose passthrough). JSON array,
    one object per demo warehouse: `slug`, `project`, `title`, `description`,
    `repo_url`. Keep it ASCII — docker-compose's env parsing mangles non-ASCII
    (em-dashes came through as mojibake). `SP_DEMO_XATA_PROJECT` and friends are
    now only a legacy fallback used when the catalog is unset.
14. **AKASA has no companion dbt repo yet.** `kiwi0401/parallax-demo` exists and
    is wired up; the AKASA card on `/demo-db` simply omits the clone
    step until a public repo exists. Publish the pg-compatible project from
    `demo-3/akasa_dbt` (synthetic data only) and add `"repo_url"` to its catalog
    entry — no code change needed.
15. **Demo warehouse running costs**: each `main` base branch is a live
    `xata.small` Postgres (us-east-1, ~$0.024/hr ≈ $17/mo each, plus $0.28/GB
    storage). User forks are copy-on-write, so they cost almost nothing until
    written to, but nothing reaps abandoned ones — a user who never clicks
    "remove" leaves a branch behind forever. Consider a TTL sweeper before any
    public launch.
16. **The demo `main` branches hold only the `raw` layer** (`raw.client_blob`,
    ~2M rows each) by design — the point is for the user to build staging/marts
    themselves with dbt. If a demo needs pre-built marts, load them separately.
