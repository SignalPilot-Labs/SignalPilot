# Secrets & Private Documents Audit

Audit date: 2026-07-29
Branch: `autofyn/run-a-security-a-880618` vs `main`
Scope: 272 files changed, ~19.8k insertions. Focused on (a) credential leaks in the branch diff, (b) private/internal markdown that must not ship publicly.

## Summary

| Category | Count |
|---|---|
| CRITICAL secrets in diff | 0 |
| HIGH/MEDIUM secret-shaped items in diff | 0 (all values examined were placeholders, test fakes, or env-var references) |
| Pre-existing suspicious items in `main` | 1 (LOW — a well-known "EXAMPLE" AWS key in a test file) |
| Private/internal markdown docs flagged | 13 (2 CRITICAL, 8 HIGH, 3 MEDIUM) |
| Files/patterns confirmed clean | many (see clean-list) |

Severity mix: no live credentials leaked, but a large `writeups/` directory with roadmap details, private repo/customer names, and internal partnership economics is currently included in the diff and must be removed before publishing.

---

## Secrets Found (in branch diff)

None. Every string matching secret-shaped regexes in the diff was one of:

- Test fixtures with obvious fakes (`xoxb-test`, `xapp-test`, `sk-ant-api03-ABCDEFGHIJKLMNOP-XYZ9`, `sk-ant-old-org-key`, `sk-ant-rotated-SECRET`, `xau_users_own_key`, `-----BEGIN ... FAKE ...-----`).
- Env var references (`${XATA_KEY:-}`, `${SP_GITHUB_BOT_TOKEN:-}`, `${CLAUDE_CODE_OAUTH_TOKEN:-}`) in `docker-compose.yml`. No actual values.
- MinIO local-dev default `minioadmin/minioadmin` in the compose file — acceptable for a local dev stack when documented, but see hardening note below.
- Placeholder private-key strings in UI placeholders and test files (`-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----`).
- Documentation examples using RFC-5737 / obvious sample IPs like `172.31.99.42` (test data), `bastion.example.com`, `db.internal.example.com`, `100.64.1.50`, `203.0.113.10`, `10.0.2.45` — these are RFC-5737/RFC-1918/CGNAT examples, not real hosts.

### Hardening notes (non-blocking)

- `docker-compose.yml` sets `MINIO_ROOT_PASSWORD: minioadmin` and `SP_EVAL_UPLOADS_S3_ACCESS_KEY/SECRET_KEY: minioadmin`. Fine for local dev; add a comment stating this file is DEV-ONLY, or template these to env vars for the prod compose to avoid the default ever making it into a production image.
- `.gitignore` correctly adds `.env`, `.redshift-nala-creds.txt`, `research-7-20/`, `research-7-24/`, `presentations/`, `dh.json`, `xata-partnership.md`, `five-customer-problems.md`, `knowledge-base-redesign.md`, `AGENTS.md`, `cc.md`, various `demo-*` scratch dirs. This is the right posture and none of these appear in the diff. Good.
- The removed `signalpilot/gateway/gateway/dev_local_api_key.py` used `secrets.token_hex(16)` — not a leak, just noting it was scrubbed cleanly.

---

## Suspicious Content in `main` (pre-existing)

### [LOW] `tests/test_iam_auth.py:25,30`
- Excerpt: `"aws_access_key_id": "AKIAIOSFODNN7EXAMPLE"`
- This is the AWS-documented **example** access key ID (literally ends in `EXAMPLE`, published in AWS IAM docs). Not a real secret. Left as-is; noted only because grep flagged it.

No other real-secret-shaped strings were found in `main` (spot-checked with the full pattern set: `sk-ant-`, `AKIA…` non-EXAMPLE, `ghp_`, `xoxb-`, `AIza`, `-----BEGIN … PRIVATE KEY-----` outside of placeholders/tests/docs). The private-key hits in `main` were all UI placeholders, doc examples, and fake test fixtures — none are live keys.

---

## Private / Internal Markdown Files

The entire `writeups/` directory (13 files) is new in this branch and reads as internal sprint-tracking / roadmap / partnership documentation. **None of it should ship on a public OSS release.** Details below.

### [CRITICAL] `writeups/HUMAN-TASKS.md`
- Why private: Names a private customer/scratch GitHub repo, an internal container name, dollar-figure hosting cost projections tied to a Xata partnership, and a live to-ship credential-management directive naming the exact env var.
- Excerpts:
  - `"kiwi0401/sp-pipelineproof-test — PRs #1–#4 there are the test artifacts; delete the repo when done"`
  - `"XATA_KEY must go into AWS Secrets Manager before this ships. It is the org-wide Xata control-plane key."` — pointing at (and giving a name to) an unrotated, still-live production key.
  - `"AKASA has no companion dbt repo yet"` — reveals customer/partner name AKASA and its unreleased state.
  - `"~$0.024/hr ≈ $17/mo each, plus $0.28/GB storage"` — internal Xata unit economics.
  - `"The nala-warehouse-pg container was attached to the signalpilot_default docker network"` — internal infra.
- Recommendation: **REMOVE from the diff entirely.** Move to a private repo. If any of the guidance is still needed publicly, rewrite as generic operator docs with no repo/customer/vendor economics.

### [CRITICAL] `writeups/SPRINT-SUMMARY.md`
- Why private: Sprint-planning artifact enumerating unshipped features, cross-org authorization holes, a SQL injection vector, per-feature "live PRs" on a private test repo, and dollar-figure agent-token costs.
- Excerpts:
  - `"A cross-org authorization hole (schema watches could PR to another org's repo with that org's installation token)."`
  - `"A SQL injection vector (MetricProof where-clause passthrough)."`
  - `"~5.7M subagent tokens across 8 panels + 4 sweep agents"`
  - `"live PR on kiwi0401/sp-pipelineproof-test#1 — 3.48M-row model verified, ghost model failed"`
- Publishing this after fixes are landed is still risky: it forensically catalogues where security bugs *were*, which invites regression hunting. Also names the private test repo repeatedly.
- Recommendation: **REMOVE.** Keep as an internal artifact.

### [HIGH] `writeups/feature-1-kb-semantic-search.md`
- Why private: Reads like an internal design memo — references `research-7-20/17, §1.3` (a private research folder listed in `.gitignore`), internal roadmap items, and enumerates unresolved product decisions ("needs an API key decision (human)"). Discusses agent-side data (task descriptions) stored 90d and calls out a needed PII/retention decision.
- Excerpt: `"the realism audit (research-7-20/17, §1.3) flagged as the top greenfield gap"`; `"needs a PII/retention decision before cloud GA"`.
- Recommendation: Remove or heavily redact; consider a public engineering blog version with the private references stripped.

### [HIGH] `writeups/feature-1-panels.md`
- Why private: Explicit internal-security-review log listing bugs by severity and internal roadmap ("KB Reflector usage signal … feeds roadmap M2", "PII scrubbing for logged queries … Governance review before cloud GA"). Also lists roadmap-classified backlog items.
- Excerpt: `"PII scrubbing for logged queries — task descriptions can contain customer data; queries stored 90d. Governance review before cloud GA."`
- Recommendation: Remove.

### [HIGH] `writeups/feature-2-retrieval-heatmap.md`
- Why private: 8-agent panel outcomes; enumerated backlog with roadmap prioritization; internal review process detail.
- Excerpt: `"Panel outcomes (16 agents, ~616k tokens)"` and a bug-list with severities.
- Recommendation: Remove.

### [HIGH] `writeups/feature-3-github-bot.md`
- Why private:
  - Names the private test repo `kiwi0401/sp-pipelineproof-test` and includes real-world row counts (`3,485,520 rows`) from a live warehouse (`perf_nala_pg`, likely NALA customer/env).
  - Describes an internal auth-token fallback chain and admin routes.
  - Excerpt: `"Private repo kiwi0401/sp-pipelineproof-test, PR #1 … stg_fx__fx_rates → pass — 3,485,520 rows, grain rate_id unique, auto-resolved to analytics_staging.stg_fx__fx_rates on connection perf_nala_pg."`
- Recommendation: Remove. If a public writeup is desired, redact the repo name, warehouse/connection names, and row counts.

### [HIGH] `writeups/feature-4-schema-diff-cron.md`
- Why private: Direct URLs to PRs on the private repo (`https://github.com/kiwi0401/sp-pipelineproof-test/pull/2`), internal warehouse name and table counts (`perf_nala_pg (261 tables)`), and — critically — again names the cross-org auth vulnerability.
- Excerpt: `"the panel found the cross-org hole: org A could otherwise PR to org B's linked repo with org B's installation token."`
- Recommendation: Remove.

### [HIGH] `writeups/feature-5-databricks-testing.md`
- Why private: Internal audit-vs-roadmap gap analysis; panel-review internal process.
- Excerpt: `"Panel outcomes (16 agents, ~666k tokens)"`.
- Recommendation: Remove. Lower risk than 3/4 (no customer names) but still leaks internal process and unshipped-decision backlog.

### [HIGH] `writeups/feature-6-metricproof.md`
- Why private: Explicitly discloses that a critical SQL-injection vector was in the code, references un-live features awaiting human validation, and includes competitive/GTM strategy language.
- Excerpts:
  - `"where-clause injection removal (critical)"`
  - `"the partner-shaped play against Snowflake/Databricks instead of a war-shaped one"` — internal positioning language.
- Recommendation: Remove.

### [HIGH] `writeups/feature-7-dbt-fusion.md`
- Why private: Internal vendor-probe results ("recon assumptions"), specific dbt-fusion preview version, and known-remaining-gap disclosure of an unfixed benchmark-infra vulnerability.
- Excerpt: `"benchmark/Dockerfile.dbt-agent faketime shim: LD_PRELOAD interception of a Rust binary is unreliable"`.
- Recommendation: Remove or convert to a public engineering post after review.

### [MEDIUM] `writeups/feature-8-ux-overhaul.md`
- Why private: References an internal design doc (`signalpilot/web/UX.md`, also in the diff), enumerates a shipping bug that made prod ("Ctrl+C hijack (shipping bug)"), and lists open TODO backlog.
- Excerpt: `"Ctrl+C hijack (shipping bug): the Chats nav shortcut intercepted the copy chord"`.
- Recommendation: Remove or rework as a public design post; the shipping-bug callout is embarrassing but not exploitable.

### [MEDIUM] `writeups/kb-search-test-suite.md`
- Why private: Internal benchmarks with subagent-generated test details, but the content is largely engineering-substantive and could plausibly be a public blog post after light edit.
- Excerpt: `"800+ assertions … The generators were held to a 'provable expectations only' contract"`.
- Recommendation: Remove from OSS repo; can be a public engineering post separately.

### [CRITICAL] `writeups/research-metric-sources-and-connectors.md`
- Why private: This is a **competitive intelligence and licensing-strategy memo** citing a specific person by first name, discussing which OSS licenses can be embedded, and analyzing partnership candidates.
- Excerpts:
  - `"Question from Dan: validate the metric-scatter hypothesis"` — names an internal stakeholder.
  - `"Nango is the sleeper in the source-available tier … the partnership/embed candidate if we want one-click OAuth"` — partnership-strategy speculation.
  - `"ELv2 exposure note for us specifically: SignalPilot itself is a governed gateway — if we ever expose an embedded ELv2 component's own API surface to customers we edge toward the forbidden zone … Counsel review before any ELv2 embed ships."` — legal-strategy internal note.
- Recommendation: **REMOVE.** This is the single highest-risk file — mixes personal names, competitive analysis, licensing strategy, and internal legal posture. Ship nowhere near public.

### [MEDIUM] `writeups/kb-search-test-suite.md` and other `benchmark/` MDs
- The `benchmark/prompts/kb_generation_system.md` and `benchmark/signalpilot-plugin/skills/dbt-knowledgebase/SKILL.md` changes are small formatting/style additions and appear safe. No customer or roadmap detail.
- `signalpilot/web/UX.md` (added, ~110 lines): a product-design document. Mostly generic UX/typography direction, but it does reference the internal `WebstormProjects/signalpilot/landing-page` local path in the header, plus internal loop naming. Recommendation: LOW — either strip the WebstormProjects reference line and ship it, or move to internal wiki.

---

## Additional flags outside `writeups/`

- **`CONTRIBUTING.md`**: the diff removes a large block of dev-stack documentation. That's a content decision, not a security concern — no secrets exposed by the change.
- **`.gitignore`** additions include mentions of private files by name (e.g., `xata-partnership.md`, `dh.json`, `five-customer-problems.md`, `research-7-*`). Ignoring the *names* of private files in `.gitignore` is a mild information leak (adversaries learn those files exist), but the standard tradeoff is worth it. **Consider deleting the `.gitignore` line for `dh.json` and `.redshift-nala-creds.txt` after confirming those files have never been committed** — advertising them by name in a public repo mildly increases their target value. Severity: LOW.

---

## Clean-list (checked and confirmed OK)

- `docker-compose.yml`, `docker-compose.dev.yml`: no hardcoded live secrets. `${XATA_KEY:-}`, `${SP_GITHUB_BOT_TOKEN:-}`, `${SP_GITHUB_WEBHOOK_SECRET:-}`, `${CLAUDE_CODE_OAUTH_TOKEN:-}` are env-var references. MinIO dev creds are default and non-sensitive but flagged for hardening.
- `.env.example` deletion — the old file contained only commented-out variable names, no values.
- All `xoxb-test` / `xapp-test` / `sk-ant-…-XYZ9` / `xau_users_own_key` occurrences in the test suite: obvious fakes.
- All `-----BEGIN … PRIVATE KEY-----` occurrences: UI placeholders, doc examples with `\n...`, or test fixtures with literal `\nFAKE\n` bodies.
- No AWS access-key IDs matching `AKIA[0-9A-Z]{16}` other than the AWS-documented `AKIAIOSFODNN7EXAMPLE` in tests.
- No `ghp_…` / `gho_…` GitHub tokens found anywhere in the diff or `main`.
- No `AIza…` Google API keys.
- No JWTs with real-looking payloads (`eyJhbGciO…`) in code paths.
- No `postgres://user:password@…` or other DB connection strings with embedded credentials in the diff.
- Internal IPs found in code are all example ranges (172.31.99.42 in a test, 100.64.1.50/203.0.113.10/10.0.2.45 in docs).
- `demo-2.zip`, `demo-3/`, `nala-demo.zip`, `akasa_dbt.zip`, `redshift_nala_load.py`, `.redshift-nala-creds.txt`, `dh.json`, `xata-partnership.md`, `research-7-*/`, `presentations/`, `AGENTS.md`, `cc.md`, `eval-format.md`, `eval-upload-spec.md`, `five-customer-problems.md`, `knowledge-base-redesign.md`, `codex-signalpilot-plugin/`, `redshift_export/` are all in `.gitignore` and confirmed **not present** in the diff.

---

## Action items (recommended, not implemented — this is diagnostic)

1. Delete the entire `writeups/` directory from this branch before merging to `main` for public release. Move to a private tracking repo.
2. Add `writeups/` to `.gitignore` so future sprints do not re-introduce the same leak.
3. Independently rotate `XATA_KEY`, `SP_GITHUB_BOT_TOKEN`, `SP_GITHUB_WEBHOOK_SECRET`, `CLAUDE_CODE_OAUTH_TOKEN`, and any credentials associated with `kiwi0401/sp-pipelineproof-test` — because their existence, purpose, and location are documented in the writeups that were already in the git history of this branch (even if you delete the files now, they persist in reflogs unless the branch is force-recreated or the objects garbage-collected on the remote).
4. Consider whether `kiwi0401/sp-pipelineproof-test`, `kiwi0401/parallax-demo`, `perf_nala_pg`, `nala-warehouse-pg`, and `AKASA` are names you want in the *commit history* of a public repo. If not, this branch should be rebased/squashed before pushing, and any prior remote pushes reviewed.
5. Strip the "WebstormProjects/signalpilot/landing-page" local path reference from `signalpilot/web/UX.md` before shipping.
6. In `docker-compose.yml`, add a `# DEV ONLY — do not use in production` comment above the `minioadmin` block.
