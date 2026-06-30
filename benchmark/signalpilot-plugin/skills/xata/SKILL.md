---
name: xata
description: "Load when working with Xata Postgres branches: forking a branch, building or testing dbt models on a branch, wiring dbt to a branch's credentials, diffing two branches, or the pre-merge impact report. Covers create_xata_branch, delete_xata_branch, get_dbt_profile, xata_branch_diff, schema_diff_branches, and pgroll migrations."
type: skill
---

# Xata branches: build dbt on isolated branches, review, merge

Xata is a Postgres-at-scale platform. A branch is a copy-on-write clone of a
Postgres database — a full-data fork in under a second at no storage cost. Each
branch is a standard Postgres endpoint. Build and validate every model change on a
branch, then a human merges to production. Never build on `main` or `staging`.

## Connect to a workspace

Register a Xata workspace as a `xata`-type connection, not a raw `postgres` URL.
The stored secret is the control-plane API key (`xata_api_key`), with
`xata_organization`, `xata_project`, and `xata_database`. The gateway resolves each
branch's Postgres endpoint (`<branchID>.<region>.xata.tech`) server-side.

Do not paste a `postgresql://...xata.tech/...` URL as a connection. One workspace
connection addresses every branch.

## Branch lifecycle

Fork a branch with `create_xata_branch(connection_name, project, branch_name, parent_branch)`.
This is the only way to create a branch. Name it `agent_<model>_<YYYYMMDD>` using
`[A-Za-z0-9_.-]` only — no `/`. Fork from `staging` (or `main`) to get realistic data
at zero copy cost.

List branches with `xata_list_branches(connection_name, project)` before creating, to
avoid duplicate branches.

Delete a branch with `delete_xata_branch(connection_name, project, branch_name)` only
after a human confirms the change merged. `main`/`staging`/`prod` cannot be deleted
through this tool.

## Build dbt models on a branch

Build or change a model on a branch — never on `main` or `staging`.

1. Fork a branch with `create_xata_branch` (above).
2. Wire dbt with `get_dbt_profile(connection_name, branch, profile, target)`. It
   returns a shell COMMAND, not credentials. Run the command from the dbt project
   directory. It writes the branch's Postgres credentials into `profiles.yml`,
   upserting that one target and keeping your other targets.
3. Build with `dbt run --target <target>`. dbt writes tables to the branch.
4. Test with `dbt test --target <target>`.
5. Produce the review report with `xata_branch_diff(connection_name, base_branch,
   compare_branch, format="html")`. Share the returned URL.
6. A human merges. Then delete the branch with `delete_xata_branch`.

Do not read or print `profiles.yml` — it holds the live branch password. Do not paste
credentials into committed files, the diff report, or the handoff.

`get_dbt_profile` refuses `main`/`staging`/`prod`; it issues write credentials only for
agent-created branches. Write with `dbt run`. `query_database` is governed read-only and
blocks DDL/DML — use it (and `explore_table`, `schema_ddl`, `schema_link`) only to
inspect any branch.

## Diff two branches

Call `xata_branch_diff(connection_name, base_branch, compare_branch)` to compare two
branches from one workspace connection. The gateway swaps the branch on the stored
credential and diffs the two live schemas. Add `format="html"` to render the
review-ready pre-merge impact report and return a shareable URL.

Call `schema_diff_branches(base_connection, compare_connection)` when the two branches
are registered as two separate connections instead.

Do not use `schema_diff` to compare branches. `schema_diff` compares one connection
against its own cached snapshot, not against another connection.

## Pre-merge impact workflow

Run this before a feature branch merges into the base branch.

1. Diff the branches with `xata_branch_diff(connection_name, base, feature, format="html")`.
2. For each removed column, find every dbt model whose SQL selects that column from the
   changed source table. Each such model is a breaking change.
3. For each removed column, find every dbt test (`accepted_values`, `not_null`, `unique`,
   `relationships`) on that column. Each such test is a breaking change.
4. For each type change, flag models that use the column as a warning. Flag any
   `accepted_values` test on that column as breaking when the new type is numeric and the
   listed values are strings.
5. Propagate downstream: any model that `ref()`s a breaking model is a warning, because it
   cannot build once its parent fails.
6. Report a verdict. Any breaking change means do not merge.

The static report is a superset of what a dbt run surfaces. A dbt run stops at the first
failed node in a chain and skips the rest. The static report lists every break, not just
the first one dbt hits.

## pgroll migrations

Xata applies schema changes with pgroll (`xata roll`). pgroll runs expand then contract.
During expand it keeps the old and new columns both live, exposed through versioned view
schemas named `public_<migration_name>`. Applications select a version with
`SET search_path = 'public_<migration_name>'`.

When a branch under review uses pgroll expand/contract, the old column still exists until
`pgroll complete` runs. Recommend the expand/contract path as the safe remediation: it
lets the warehouse migrate to the new column before the old one is dropped, so the merge
does not break the pipeline.

Introspect only the application schema (for example `raw`) when diffing. Ignore pgroll's
internal `pgroll` schema and its `<schema>_<migration>` version schemas.
