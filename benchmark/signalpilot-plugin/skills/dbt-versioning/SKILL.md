---
name: dbt-versioning
description: "Load when task involves dbt model versioning, creating v2 of a model, or backward-compatible model changes. Covers versions YAML config, defined_in, latest_version, and ref() with version pins."
disable-model-invocation: false
allowed-tools: Bash(dbt *)
---

# dbt Model Versioning

## 1. Versioned Model vs Standalone Copy

When a task says "create a v2," "add a new version," or "backward-compatible change," use dbt's native `versions:` config (dbt-core 1.6+). Do NOT create a standalone model with a `_v2` suffix - that produces a separate node (`model.project.dim_customers_v2`) instead of a version node (`model.project.dim_customers.v2`).

## 2. YAML Structure

Declare versions inside the model's `.yml` file under the model entry:

```yaml
models:
 - name: dim_customers
    latest_version: 1
    versions:
 - v: 1
 - v: 2
        defined_in: dim_customers_v2
```

Rules:
- `versions:` is a list of `v:` entries inside the `models:` block, under the model name.
- `defined_in:` maps a version to its SQL filename (without `.sql`). Omit `defined_in` when the filename matches the default `<model_name>_v<N>.sql`.
- `latest_version:` controls which version `ref('dim_customers')` resolves to. If the task says "not yet the primary version," set `latest_version` to the old version number.

## 3. File Naming

Version SQL files use the pattern `<model_name>_v<N>.sql`.

- `dim_customers.sql` - original model, becomes v1 implicitly.
- `dim_customers_v2.sql` - new version.

Do NOT rename or move the original SQL file. It remains v1 without changes.

## 4. How `ref()` Works with Versions

- `ref('dim_customers')` resolves to whichever version `latest_version` specifies.
- `ref('dim_customers', v=2)` pins to version 2 regardless of `latest_version`.

Downstream models that need the new version must use `ref('dim_customers', v=2)`. Models using bare `ref('dim_customers')` continue to get the old version until `latest_version` is updated.

## 5. Writing the v2 SQL

Read the original model's SQL first. If the v2 only renames or adds columns, write a thin wrapper:

```sql
select
    customer_id,
    customer_name,
    account_status as customer_status  -- renamed column
from {{ ref('dim_customers', v=1) }}
```

Do NOT duplicate all upstream logic into the v2 file when a SELECT-with-renames suffices.

## 6. Verification

After creating the versioned model, run:

```bash
dbt ls --select dim_customers --output json
```

Confirm the output contains nodes `model.<project>.dim_customers.v1` and `model.<project>.dim_customers.v2`. If these nodes are missing, the `versions:` YAML is wrong.

## Rules

- NEVER create a standalone `_v2` model without `versions:` YAML - dbt will not register it as a version.
- NEVER rename or move the original SQL file when adding a new version.
- ALWAYS set `latest_version` explicitly - omitting it defaults to the highest version number, which may break downstream refs.
- ALWAYS read test files in `tests/` before writing models - they reveal required dbt features the task may only hint at.
