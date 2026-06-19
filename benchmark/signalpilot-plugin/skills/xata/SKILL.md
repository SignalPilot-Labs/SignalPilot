---
name: xata
description: "Load when working with Xata Postgres branches: connecting to a branch, diffing two branches, or checking whether an upstream branch's schema change breaks a dbt project or pipeline before it merges. Covers branch connections, schema_diff_branches, pgroll migrations, and the pre-merge impact report."
type: skill
---

# Xata branches and pre-merge impact analysis

Xata is a Postgres-at-scale platform. Branches are copy-on-write copies of a
Postgres database. Each branch is a standard Postgres endpoint with its own
connection string. Treat a Xata branch as a normal `postgres` connection.

## Connect to a workspace

Register a Xata workspace as a `xata`-type connection, not as a raw `postgres`
URL. The stored secret is a scoped Xata API key, not a database connection string.
The gateway resolves the per-branch Postgres endpoint server-side. Set the
workspace, region, database, and default branch on the connection.

Do not paste a `postgresql://...xata.sh/...` URL as a connection. Store the API
key on a `xata` connection and let the gateway build the endpoint. One workspace
connection addresses every branch.

## Diff two branches

Call `xata_branch_diff(connection_name, base_branch, compare_branch)` to compare
two branches from one workspace connection. The gateway swaps the branch on the
stored credential and diffs the two live schemas. Use this for the pre-merge gate.

Call `schema_diff_branches(base_connection, compare_connection)` when the two
branches are registered as two separate connections instead.

Do not use `schema_diff` to compare branches. `schema_diff` compares one
connection against its own cached snapshot, not against another connection.

## List branches

Call `xata_list_branches(connection_name, project)` to list the branches in a Xata
project. Each branch shows its name, id, and parent branch.

## Pre-merge impact workflow

Run this before a feature branch merges into the base branch.

1. Diff the branches with `schema_diff_branches(base, feature)`.
2. For each removed column, find every dbt model whose SQL selects that column
   from the changed source table. Each such model is a breaking change.
3. For each removed column, find every dbt test (`accepted_values`, `not_null`,
   `unique`, `relationships`) on that column. Each such test is a breaking change.
4. For each type change, flag models that use the column as a warning. Flag any
   `accepted_values` test on that column as breaking when the new type is numeric
   and the listed values are strings.
5. Propagate downstream: any model that `ref()`s a breaking model is a warning,
   because it cannot build once its parent fails.
6. Report a verdict. Any breaking change means do not merge.

The static report is a superset of what a dbt run surfaces. A dbt run stops at
the first failed node in a chain and skips the rest. The static report lists
every break, not just the first one dbt hits.

## pgroll migrations

Xata applies schema changes with pgroll (`xata roll`). pgroll runs expand then
contract. During expand it keeps the old and new columns both live, exposed
through versioned view schemas named `public_<migration_name>`. Applications
select a version with `SET search_path = 'public_<migration_name>'`.

When a branch under review uses pgroll expand/contract, the old column still
exists until `pgroll complete` runs. Recommend the expand/contract path as the
safe remediation: it lets the warehouse migrate to the new column before the old
one is dropped, so the merge does not break the pipeline.

Introspect only the application schema (for example `raw`) when diffing. Ignore
pgroll's internal `pgroll` schema and its `<schema>_<migration>` version schemas.
