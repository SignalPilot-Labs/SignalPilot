# Workspaces dbt Projects

dbt project link adapters for Workspaces. Round 4 fills the implementation.

## Three Link Modes

See `ARCHITECTURE.md §8` for full details.

**1. dbt Cloud link**
OAuth flow: user authorizes access -> gateway stores `account_id`, `project_id`, and encrypted refresh token. Agent triggers `dbt run` via the dbt Cloud Jobs API. No local clone required.

**2. GitHub link**
GitHub App install -> gateway clones the repository into the `workspaces-data` volume on demand. A webhook on push triggers an automatic pull. Agent runs `dbt run` locally against the checkout, via the credential-isolation dbt-proxy.

**3. Native upload**
User uploads a project tarball. Extracted into the `workspaces-data` volume. No automatic sync; user re-uploads to update.

## Package Layout

```
workspaces/dbt_projects/
  pyproject.toml                name = "workspaces-dbt-projects"
  workspaces_dbt_projects/
    __init__.py
    links/
      __init__.py               link adapter implementations (Round 4)
```
