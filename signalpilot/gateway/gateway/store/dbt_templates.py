"""dbt project template strings and scaffold directory list."""

from __future__ import annotations

_DBT_PROJECT_YML_TEMPLATE = """\
name: '{name}'
version: '1.0.0'
config-version: 2
profile: '{name}'

model-paths: ["models"]
analysis-paths: ["analyses"]
test-paths: ["tests"]
seed-paths: ["seeds"]
macro-paths: ["macros"]
snapshot-paths: ["snapshots"]

clean-targets:
  - "target"
  - "dbt_packages"
"""

_PACKAGES_YML_TEMPLATE = """\
packages: []
"""

_PROFILES_DUCKDB = """\
{name}:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: '{database}'
"""

_PROFILES_POSTGRES = """\
{name}:
  target: dev
  outputs:
    dev:
      type: postgres
      host: '{host}'
      port: {port}
      user: '{username}'
      dbname: '{database}'
      schema: public
"""

_PROFILES_SNOWFLAKE = """\
{name}:
  target: dev
  outputs:
    dev:
      type: snowflake
      account: '{account}'
      user: '{username}'
      database: '{database}'
      warehouse: '{warehouse}'
      schema: public
      role: '{role}'
"""

_PROFILES_BIGQUERY = """\
{name}:
  target: dev
  outputs:
    dev:
      type: bigquery
      method: service-account
      project: '{project}'
      dataset: '{dataset}'
      location: '{location}'
"""

_PROFILES_PLACEHOLDER = """\
# TODO: Configure profile for {db_type}
# See https://docs.getdbt.com/docs/core/connect-data-platform
{name}:
  target: dev
  outputs:
    dev:
      type: '{db_type}'
"""

_SCAFFOLD_DIRS = [
    "models/staging",
    "models/marts",
    "analyses",
    "tests",
    "seeds",
    "macros",
    "snapshots",
]
