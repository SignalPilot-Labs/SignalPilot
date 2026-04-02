"""
Query cost pre-estimation — Feature #13 from the feature table.

Uses EXPLAIN to estimate query cost before execution.
Supports: Postgres, DuckDB, MySQL, Snowflake, BigQuery, Redshift, ClickHouse, Databricks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..connectors.base import BaseConnector


@dataclass
class CostEstimate:
    """Estimated cost of executing a query."""
    estimated_rows: int = 0
    estimated_cost: float = 0.0  # Planner cost units (not USD)
    estimated_usd: float = 0.0  # Rough USD estimate
    warning: str | None = None
    raw_plan: str | None = None

    @property
    def is_expensive(self) -> bool:
        """Heuristic: queries over $1 estimated or 1M rows are expensive."""
        return self.estimated_usd > 1.0 or self.estimated_rows > 1_000_000


# Cost per row scanned — rough heuristics for managed databases
# Based on typical cloud pricing for compute + I/O
_COST_PER_ROW = {
    "postgres": 0.000_000_3,       # ~$0.10/hr RDS, ~100K rows/sec
    "redshift": 0.000_000_5,       # ~$0.25/hr per node, higher throughput
    "mysql": 0.000_000_3,          # ~$0.10/hr RDS
    "snowflake": 0.000_001_0,      # ~$2/credit, credits burn per-query
    "bigquery": 0.000_005_0,       # $5/TB scanned, ~1KB/row average
    "clickhouse": 0.000_000_1,     # Very efficient columnar storage
    "databricks": 0.000_001_0,     # Similar to Snowflake pricing model
    "duckdb": 0.0,                 # Local/free
    "sqlite": 0.0,                 # Local/free
    "mssql": 0.000_000_4,          # ~$0.10-0.20/hr, SQL Server/Azure SQL
    "trino": 0.000_000_2,          # Self-hosted federated engine
}


class CostEstimator:
    """Estimates the cost of a SQL query using EXPLAIN."""

    @staticmethod
    async def estimate_postgres(connector: BaseConnector, sql: str) -> CostEstimate:
        """Use EXPLAIN to estimate Postgres query cost."""
        try:
            explain_sql = f"EXPLAIN (FORMAT JSON) {sql}"
            rows = await connector.execute(explain_sql)
            if not rows:
                return CostEstimate(warning="EXPLAIN returned no data")

            plan_data = rows[0]
            plan_json = None
            for val in plan_data.values():
                if isinstance(val, str):
                    plan_json = json.loads(val)
                elif isinstance(val, list):
                    plan_json = val
                break

            if not plan_json or not isinstance(plan_json, list):
                return CostEstimate(warning="Could not parse EXPLAIN output")

            plan = plan_json[0].get("Plan", {})
            total_cost = plan.get("Total Cost", 0)
            plan_rows = plan.get("Plan Rows", 0)
            estimated_usd = plan_rows * _COST_PER_ROW["postgres"]

            return CostEstimate(
                estimated_rows=plan_rows,
                estimated_cost=total_cost,
                estimated_usd=estimated_usd,
                raw_plan=json.dumps(plan_json, indent=2)[:2000],
            )
        except Exception as e:
            return CostEstimate(warning=f"Cost estimation failed: {e}")

    @staticmethod
    async def estimate_mysql(connector: BaseConnector, sql: str) -> CostEstimate:
        """Use EXPLAIN to estimate MySQL query cost."""
        try:
            explain_sql = f"EXPLAIN FORMAT=JSON {sql}"
            rows = await connector.execute(explain_sql)
            if not rows:
                return CostEstimate(warning="EXPLAIN returned no data")

            # MySQL EXPLAIN JSON returns a single row with 'EXPLAIN' key
            plan_text = ""
            for val in rows[0].values():
                if isinstance(val, str):
                    plan_text = val
                    break

            if not plan_text:
                return CostEstimate(warning="Could not parse EXPLAIN output")

            plan_json = json.loads(plan_text)
            query_block = plan_json.get("query_block", {})
            cost_info = query_block.get("cost_info", {})
            query_cost = float(cost_info.get("query_cost", 0))

            # Estimate rows from table access
            estimated_rows = 0
            table = query_block.get("table", {})
            if table:
                estimated_rows = int(table.get("rows_examined_per_scan", 0))

            estimated_usd = estimated_rows * _COST_PER_ROW["mysql"]
            return CostEstimate(
                estimated_rows=estimated_rows,
                estimated_cost=query_cost,
                estimated_usd=estimated_usd,
                raw_plan=plan_text[:2000],
            )
        except Exception as e:
            return CostEstimate(warning=f"Cost estimation failed: {e}")

    @staticmethod
    async def estimate_snowflake(connector: BaseConnector, sql: str) -> CostEstimate:
        """Use EXPLAIN to estimate Snowflake query cost."""
        try:
            # Snowflake supports EXPLAIN but with limited output
            explain_sql = f"EXPLAIN USING TEXT {sql}"
            rows = await connector.execute(explain_sql)
            plan_text = "\n".join(str(list(r.values())) for r in rows) if rows else ""

            # Snowflake doesn't give row estimates in EXPLAIN easily
            # Use a heuristic based on the number of operations
            estimated_rows = 10000  # Conservative default
            estimated_usd = estimated_rows * _COST_PER_ROW["snowflake"]

            return CostEstimate(
                estimated_rows=estimated_rows,
                estimated_cost=0,
                estimated_usd=estimated_usd,
                raw_plan=plan_text[:2000],
            )
        except Exception as e:
            return CostEstimate(warning=f"Cost estimation failed: {e}")

    @staticmethod
    async def estimate_bigquery(connector: BaseConnector, sql: str) -> CostEstimate:
        """Use dry_run to estimate BigQuery query cost (bytes processed)."""
        try:
            # BigQuery has a special dry_run mode via the client
            # We access the underlying client for dry_run
            from ..connectors.bigquery import BigQueryConnector
            if isinstance(connector, BigQueryConnector) and connector._client:
                from google.cloud import bigquery
                job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
                query_job = connector._client.query(sql, job_config=job_config)
                bytes_processed = query_job.total_bytes_processed or 0
                # BigQuery charges $5/TB for on-demand queries
                estimated_usd = (bytes_processed / (1024**4)) * 5.0
                estimated_rows = bytes_processed // 100  # ~100 bytes per row heuristic
                return CostEstimate(
                    estimated_rows=estimated_rows,
                    estimated_cost=bytes_processed,
                    estimated_usd=estimated_usd,
                    raw_plan=f"Bytes to process: {bytes_processed:,}",
                )
            return CostEstimate(warning="BigQuery dry_run not available")
        except Exception as e:
            return CostEstimate(warning=f"Cost estimation failed: {e}")

    @staticmethod
    async def estimate_redshift(connector: BaseConnector, sql: str) -> CostEstimate:
        """Use EXPLAIN to estimate Redshift query cost (uses Postgres EXPLAIN)."""
        try:
            explain_sql = f"EXPLAIN {sql}"
            rows = await connector.execute(explain_sql)
            plan_text = "\n".join(str(list(r.values())[0]) for r in rows) if rows else ""

            # Parse rows estimate from EXPLAIN text
            estimated_rows = 0
            for line in plan_text.split("\n"):
                if "rows=" in line:
                    import re
                    match = re.search(r"rows=(\d+)", line)
                    if match:
                        estimated_rows = max(estimated_rows, int(match.group(1)))

            estimated_usd = estimated_rows * _COST_PER_ROW["redshift"]
            return CostEstimate(
                estimated_rows=estimated_rows,
                estimated_cost=0,
                estimated_usd=estimated_usd,
                raw_plan=plan_text[:2000],
            )
        except Exception as e:
            return CostEstimate(warning=f"Cost estimation failed: {e}")

    @staticmethod
    async def estimate_clickhouse(connector: BaseConnector, sql: str) -> CostEstimate:
        """Use EXPLAIN to estimate ClickHouse query cost.

        Tries EXPLAIN ESTIMATE first (gives rows/marks per part), falls back to
        EXPLAIN PLAN for the query plan tree with row estimates.
        """
        try:
            # Try EXPLAIN ESTIMATE first — most accurate for ClickHouse
            estimated_rows = 0
            plan_text = ""
            try:
                explain_sql = f"EXPLAIN ESTIMATE {sql}"
                rows = await connector.execute(explain_sql)
                if rows:
                    plan_text = str(rows)
                    for row in rows:
                        # EXPLAIN ESTIMATE columns: database, table, parts, rows, marks
                        row_count = row.get("rows", 0)
                        if isinstance(row_count, (int, float)):
                            estimated_rows += int(row_count)
            except Exception:
                pass

            # Fallback: EXPLAIN PLAN for query tree
            if estimated_rows == 0:
                try:
                    explain_sql = f"EXPLAIN PLAN {sql}"
                    rows = await connector.execute(explain_sql)
                    if rows:
                        plan_text = "\n".join(
                            str(list(r.values())[0]) for r in rows if r
                        )
                        import re
                        for line in plan_text.split("\n"):
                            match = re.search(r"rows:\s*(\d+)", line, re.IGNORECASE)
                            if match:
                                estimated_rows = max(estimated_rows, int(match.group(1)))
                except Exception:
                    pass

            estimated_usd = estimated_rows * _COST_PER_ROW["clickhouse"]
            return CostEstimate(
                estimated_rows=estimated_rows,
                estimated_cost=0,
                estimated_usd=estimated_usd,
                raw_plan=plan_text[:2000],
            )
        except Exception as e:
            return CostEstimate(warning=f"Cost estimation failed: {e}")

    @staticmethod
    async def estimate_databricks(connector: BaseConnector, sql: str) -> CostEstimate:
        """Estimate Databricks query cost using EXPLAIN FORMATTED.

        Parses row estimates from the physical plan output.
        """
        try:
            # EXPLAIN FORMATTED gives structured plan info on Databricks SQL
            explain_sql = f"EXPLAIN FORMATTED {sql}"
            rows = await connector.execute(explain_sql)
            plan_text = "\n".join(str(list(r.values())) for r in rows) if rows else ""

            estimated_rows = 0
            if plan_text:
                import re
                # Look for 'Statistics(sizeInBytes=X, rowCount=Y)' in plan
                row_match = re.search(r"rowCount=(\d+)", plan_text)
                if row_match:
                    estimated_rows = int(row_match.group(1))
                # Also try 'numOutputRows=X'
                if estimated_rows == 0:
                    output_match = re.search(r"numOutputRows[=:]?\s*(\d+)", plan_text)
                    if output_match:
                        estimated_rows = int(output_match.group(1))

            if estimated_rows == 0:
                estimated_rows = 10000  # Conservative default

            estimated_usd = estimated_rows * _COST_PER_ROW["databricks"]
            return CostEstimate(
                estimated_rows=estimated_rows,
                estimated_cost=0,
                estimated_usd=estimated_usd,
                raw_plan=plan_text[:2000],
            )
        except Exception as e:
            return CostEstimate(warning=f"Cost estimation failed: {e}")

    @staticmethod
    async def estimate_duckdb(connector: BaseConnector, sql: str) -> CostEstimate:
        """Estimate DuckDB query cost (local, so cost is minimal)."""
        try:
            explain_sql = f"EXPLAIN {sql}"
            rows = await connector.execute(explain_sql)
            plan_text = ""
            if rows:
                first_row = rows[0]
                plan_text = str(list(first_row.values())[0]) if first_row else ""

            return CostEstimate(
                estimated_rows=0,
                estimated_cost=0,
                estimated_usd=0,
                raw_plan=plan_text[:2000],
            )
        except Exception as e:
            return CostEstimate(warning=f"Cost estimation failed: {e}")

    @staticmethod
    async def estimate_mssql(connector: BaseConnector, sql: str) -> CostEstimate:
        """Use SET SHOWPLAN_ALL to estimate SQL Server query cost."""
        try:
            # Enable showplan mode, get plan, then disable
            await connector.execute("SET SHOWPLAN_ALL ON")
            try:
                rows = await connector.execute(sql)
            finally:
                await connector.execute("SET SHOWPLAN_ALL OFF")

            if not rows:
                return CostEstimate(warning="SHOWPLAN returned no data")

            estimated_rows = 0
            total_cost = 0.0
            plan_lines = []
            for row in rows:
                est = row.get("EstimateRows", 0)
                if est and isinstance(est, (int, float)):
                    estimated_rows = max(estimated_rows, int(est))
                cost = row.get("TotalSubtreeCost", 0)
                if cost and isinstance(cost, (int, float)):
                    total_cost = max(total_cost, float(cost))
                stmt = row.get("StmtText", "")
                if stmt:
                    plan_lines.append(str(stmt))

            # SQL Server on-premises is ~$0.10/hr, Azure SQL ~$0.20/hr
            estimated_usd = estimated_rows * 0.000_000_4
            return CostEstimate(
                estimated_rows=estimated_rows,
                estimated_cost=total_cost,
                estimated_usd=estimated_usd,
                raw_plan="\n".join(plan_lines)[:2000],
            )
        except Exception as e:
            return CostEstimate(warning=f"Cost estimation failed: {e}")

    @staticmethod
    async def estimate_trino(connector: BaseConnector, sql: str) -> CostEstimate:
        """Use EXPLAIN to estimate Trino query cost."""
        try:
            explain_sql = f"EXPLAIN {sql}"
            rows = await connector.execute(explain_sql)
            plan_text = "\n".join(str(list(r.values())[0]) for r in rows) if rows else ""

            estimated_rows = 0
            if plan_text:
                import re
                # Trino EXPLAIN shows "rows: N" or "est. N rows"
                for match in re.finditer(r"(?:rows|est\.?)\s*[:=]?\s*(\d+)", plan_text, re.IGNORECASE):
                    estimated_rows = max(estimated_rows, int(match.group(1)))

            # Trino is typically self-hosted, low cost
            estimated_usd = estimated_rows * 0.000_000_2
            return CostEstimate(
                estimated_rows=estimated_rows,
                estimated_cost=0,
                estimated_usd=estimated_usd,
                raw_plan=plan_text[:2000],
            )
        except Exception as e:
            return CostEstimate(warning=f"Cost estimation failed: {e}")

    @staticmethod
    async def estimate(connector: BaseConnector, sql: str, db_type: str) -> CostEstimate:
        """Route to the appropriate estimator based on db type."""
        estimators = {
            "postgres": CostEstimator.estimate_postgres,
            "mysql": CostEstimator.estimate_mysql,
            "snowflake": CostEstimator.estimate_snowflake,
            "bigquery": CostEstimator.estimate_bigquery,
            "redshift": CostEstimator.estimate_redshift,
            "clickhouse": CostEstimator.estimate_clickhouse,
            "databricks": CostEstimator.estimate_databricks,
            "duckdb": CostEstimator.estimate_duckdb,
            "mssql": CostEstimator.estimate_mssql,
            "trino": CostEstimator.estimate_trino,
        }
        estimator = estimators.get(db_type)
        if estimator:
            return await estimator(connector, sql)
        return CostEstimate(warning=f"Cost estimation not supported for {db_type}")
