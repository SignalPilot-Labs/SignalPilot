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
    "bigquery": 0.000_006_25,      # $6.25/TB scanned (2026 pricing), ~1KB/row average
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
        """Use EXPLAIN USING JSON to estimate Snowflake query cost.

        Parses partitionsTotal, partitionsAssigned, and row estimates from
        the JSON execution plan to calculate cost based on Snowflake credits.
        """
        try:
            explain_sql = f"EXPLAIN USING JSON {sql}"
            rows = await connector.execute(explain_sql)
            if not rows:
                return CostEstimate(warning="EXPLAIN returned no data")

            plan_text = ""
            plan_json = None
            for val in rows[0].values():
                if isinstance(val, str):
                    plan_text = val
                    try:
                        plan_json = json.loads(val)
                    except (json.JSONDecodeError, ValueError):
                        pass
                    break

            estimated_rows = 0
            partitions_total = 0
            partitions_assigned = 0

            if plan_json:
                # Walk the plan tree to extract row estimates and partition info
                def _walk_plan(node: dict) -> None:
                    nonlocal estimated_rows, partitions_total, partitions_assigned
                    if isinstance(node, dict):
                        er = node.get("outputRows") or node.get("estimatedRowCount") or node.get("rowCount", 0)
                        if er:
                            estimated_rows = max(estimated_rows, int(er))
                        pt = node.get("partitionsTotal", 0)
                        pa = node.get("partitionsAssigned", 0)
                        if pt:
                            partitions_total = max(partitions_total, int(pt))
                        if pa:
                            partitions_assigned = max(partitions_assigned, int(pa))
                        for v in node.values():
                            if isinstance(v, dict):
                                _walk_plan(v)
                            elif isinstance(v, list):
                                for item in v:
                                    if isinstance(item, dict):
                                        _walk_plan(item)

                _walk_plan(plan_json)

            if estimated_rows == 0:
                # Fallback: try TEXT format
                try:
                    text_rows = await connector.execute(f"EXPLAIN USING TEXT {sql}")
                    plan_text = "\n".join(str(list(r.values())) for r in text_rows) if text_rows else plan_text
                except Exception:
                    pass
                estimated_rows = 10000  # Conservative fallback

            estimated_usd = estimated_rows * _COST_PER_ROW["snowflake"]

            partition_info = ""
            if partitions_total > 0:
                pct = round(partitions_assigned / partitions_total * 100, 1) if partitions_total else 0
                partition_info = f" | Partitions: {partitions_assigned}/{partitions_total} ({pct}% scanned)"

            return CostEstimate(
                estimated_rows=estimated_rows,
                estimated_cost=0,
                estimated_usd=estimated_usd,
                raw_plan=(plan_text[:1900] + partition_info) if plan_text else partition_info,
            )
        except Exception as e:
            return CostEstimate(warning=f"Cost estimation failed: {e}")

    @staticmethod
    async def estimate_bigquery(connector: BaseConnector, sql: str) -> CostEstimate:
        """Use dry_run to estimate BigQuery query cost (bytes processed).

        Uses the connector's dry_run() method which respects location settings.
        Also checks against maximum_bytes_billed safety limit if configured.
        """
        try:
            from ..connectors.bigquery import BigQueryConnector
            if isinstance(connector, BigQueryConnector):
                dry_result = await connector.dry_run(sql)
                bytes_processed = dry_result.get("total_bytes_processed", 0)
                estimated_usd = dry_result.get("estimated_cost_usd", 0.0)
                estimated_rows = bytes_processed // 100  # ~100 bytes per row heuristic

                warning = None
                if dry_result.get("would_exceed_limit"):
                    limit = connector._maximum_bytes_billed or 0
                    warning = (
                        f"Query would scan {dry_result['human_readable']} — "
                        f"exceeds safety limit of {connector._format_bytes(limit)}"
                    )

                return CostEstimate(
                    estimated_rows=estimated_rows,
                    estimated_cost=bytes_processed,
                    estimated_usd=estimated_usd,
                    warning=warning,
                    raw_plan=f"Bytes to process: {bytes_processed:,} ({dry_result.get('human_readable', '')})",
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
        """Use SET SHOWPLAN_ALL to estimate SQL Server query cost.

        SHOWPLAN_ALL returns the execution plan without executing the query.
        We wrap the session in SHOWPLAN mode and restore it afterward to avoid
        side effects on the connection's read-only transaction state.
        """
        try:
            # SHOWPLAN_ALL returns plan rows instead of executing the query.
            # It must be enabled/disabled as a session-level setting.
            await connector.execute("SET SHOWPLAN_ALL ON")
            try:
                rows = await connector.execute(sql)
            finally:
                try:
                    await connector.execute("SET SHOWPLAN_ALL OFF")
                except Exception:
                    pass  # Best-effort cleanup — connection may be reused

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
                # EstimateIO and EstimateCPU are also useful for tuning
                stmt = row.get("StmtText", "")
                if stmt:
                    plan_lines.append(str(stmt))

            estimated_usd = estimated_rows * _COST_PER_ROW["mssql"]
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
            "sqlite": CostEstimator.estimate_duckdb,  # SQLite is local — same minimal cost model
            "mssql": CostEstimator.estimate_mssql,
            "trino": CostEstimator.estimate_trino,
        }
        estimator = estimators.get(db_type)
        if estimator:
            return await estimator(connector, sql)
        return CostEstimate(warning=f"Cost estimation not supported for {db_type}")
