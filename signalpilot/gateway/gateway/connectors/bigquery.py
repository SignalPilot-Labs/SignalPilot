"""BigQuery connector — google-cloud-bigquery backed.

Supports service account JSON auth and ADC (Application Default Credentials).
Tier 1 connector matching HEX's BigQuery integration.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from .base import BaseConnector

try:
    from google.cloud import bigquery
    from google.oauth2 import service_account

    HAS_BIGQUERY = True
except ImportError:
    HAS_BIGQUERY = False


class BigQueryConnector(BaseConnector):
    def __init__(self):
        super().__init__()
        self._conn = None  # unused — BQ uses self._client
        self._client: bigquery.Client | None = None
        self._project: str = ""
        self._dataset: str = ""
        self._location: str = ""  # e.g. "US", "EU", "us-east1"
        self._maximum_bytes_billed: int | None = None  # safety limit — query fails if exceeded
        self._last_job_stats: dict | None = None  # stats from most recent query job
        # Auth method: "service_account" | "oauth" | "impersonation" | "adc"
        self._auth_method: str = "adc"
        self._oauth_token: str = ""
        self._impersonate_service_account: str = ""  # target SA email for impersonation

    # ─── Identifier quoting ───────────────────────────────────────────

    @property
    def _identifier_quote(self) -> str:
        return '`'

    # ─── Connect ──────────────────────────────────────────────────────

    async def connect(self, connection_string: str) -> None:
        if not HAS_BIGQUERY:
            raise RuntimeError(
                "google-cloud-bigquery not installed. "
                "Run: pip install google-cloud-bigquery"
            )
        # connection_string is the project ID
        self._project = connection_string
        # Credentials are set via set_credentials() / set_credential_extras() before connect
        # or fall back to ADC
        try:
            if self._client is None:
                self._client = bigquery.Client(project=self._project)
        except Exception as e:
            err_str = str(e).lower()
            if "credentials" in err_str or "authentication" in err_str:
                raise RuntimeError(f"Authentication failed: {e}") from e
            elif "project" in err_str and ("not found" in err_str or "invalid" in err_str):
                raise RuntimeError(f"GCP project not found: '{self._project}'") from e
            raise RuntimeError(f"BigQuery connection error: {e}") from e

    # ─── Credentials ──────────────────────────────────────────────────

    def set_credentials(self, credentials_json: str, project: str = "", dataset: str = "",
                        location: str = "", maximum_bytes_billed: int | None = None):
        """Set credentials from a service account JSON string."""
        if not HAS_BIGQUERY:
            raise RuntimeError("google-cloud-bigquery not installed")
        try:
            info = json.loads(credentials_json)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid service account JSON: {e}") from e
        if not isinstance(info, dict) or "type" not in info:
            raise RuntimeError(
                "Invalid service account JSON: must be a JSON object with a 'type' field. "
                "Download the JSON key file from GCP Console > IAM > Service Accounts."
            )
        creds = service_account.Credentials.from_service_account_info(info)

        # If impersonation is requested, wrap credentials
        if self._impersonate_service_account:
            creds = self._wrap_impersonation(creds)

        self._project = project or info.get("project_id", "")
        self._dataset = dataset
        self._location = location
        if maximum_bytes_billed is not None:
            self._maximum_bytes_billed = maximum_bytes_billed
        self._client = bigquery.Client(
            project=self._project,
            credentials=creds,
            location=self._location or None,
        )

    def _wrap_impersonation(self, source_creds):
        """Wrap credentials with service account impersonation (HEX pattern).

        Allows a service account to act as another service account,
        useful for cross-project access and least-privilege patterns.
        """
        try:
            from google.auth import impersonated_credentials
            target_scopes = ["https://www.googleapis.com/auth/bigquery"]
            return impersonated_credentials.Credentials(
                source_credentials=source_creds,
                target_principal=self._impersonate_service_account,
                target_scopes=target_scopes,
            )
        except ImportError:
            raise RuntimeError("google-auth library required for impersonation. Run: pip install google-auth")

    def _create_oauth_client(self):
        """Create BigQuery client from OAuth access token (HEX OAuth pattern)."""
        if not HAS_BIGQUERY:
            raise RuntimeError("google-cloud-bigquery not installed")
        try:
            from google.oauth2.credentials import Credentials as OAuthCredentials
            creds = OAuthCredentials(token=self._oauth_token)
            self._client = bigquery.Client(
                project=self._project,
                credentials=creds,
                location=self._location or None,
            )
        except Exception as e:
            raise RuntimeError(f"BigQuery OAuth setup failed: {e}") from e

    def set_credential_extras(self, extras: dict) -> None:
        """Extract BigQuery credentials from credential extras.

        BQ does NOT use standard SSL/timeout fields from the base class,
        so we intentionally skip super().set_credential_extras().
        """
        # Parse maximum_bytes_billed from extras (safety limit)
        if extras.get("maximum_bytes_billed"):
            try:
                self._maximum_bytes_billed = int(extras["maximum_bytes_billed"])
            except (ValueError, TypeError):
                pass
        if extras.get("location"):
            self._location = extras["location"]
        if extras.get("auth_method"):
            self._auth_method = extras["auth_method"]
        if extras.get("impersonate_service_account"):
            self._impersonate_service_account = extras["impersonate_service_account"]

        # OAuth access token (HEX pattern)
        if extras.get("oauth_access_token"):
            self._oauth_token = extras["oauth_access_token"]
            self._project = extras.get("project", self._project)
            self._dataset = extras.get("dataset", self._dataset)
            self._create_oauth_client()
        elif extras.get("credentials_json"):
            self.set_credentials(
                credentials_json=extras["credentials_json"],
                project=extras.get("project", self._project),
                dataset=extras.get("dataset", self._dataset),
                location=extras.get("location", self._location),
                maximum_bytes_billed=self._maximum_bytes_billed,
            )

    # ─── Ensure connected ─────────────────────────────────────────────

    async def _ensure_connected(self) -> None:
        """Verify BigQuery client can reach the API; raise RuntimeError if not."""
        if self._client is None:
            raise RuntimeError("Not connected")
        try:
            await asyncio.to_thread(lambda: list(self._client.query("SELECT 1", timeout=10).result(timeout=10)))
        except Exception:
            self._client = None
            raise RuntimeError("BigQuery connection lost — please reconnect")

    # ─── Execute (CRITICAL: non-blocking) ─────────────────────────────

    async def _execute_impl(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        if self._client is None:
            raise RuntimeError("Not connected")

        client = self._client
        dataset = self._dataset
        project = self._project
        max_bytes = self._maximum_bytes_billed

        def _run():
            job_config = bigquery.QueryJobConfig()
            if dataset:
                job_config.default_dataset = f"{project}.{dataset}"
            # Safety limit: fail query before execution if it would scan too many bytes
            if max_bytes is not None:
                job_config.maximum_bytes_billed = max_bytes

            query_job = client.query(sql, job_config=job_config, timeout=timeout)
            results = query_job.result(timeout=timeout)
            rows = [dict(row) for row in results]

            # Capture job stats for cost reporting
            stats = {
                "total_bytes_processed": query_job.total_bytes_processed,
                "total_bytes_billed": query_job.total_bytes_billed,
                "cache_hit": query_job.cache_hit,
                "estimated_cost_usd": round(
                    (query_job.total_bytes_billed or 0) / (1024**4) * 6.25, 6
                ),
                "slot_millis": getattr(query_job, "slot_millis", None),
                "job_id": query_job.job_id,
            }
            return rows, stats

        try:
            rows, stats = await asyncio.to_thread(_run)
            self._last_job_stats = stats
            return rows
        except Exception as e:
            err_str = str(e).lower()
            if "exceeded" in err_str and "bytes" in err_str:
                raise RuntimeError(
                    f"Query would scan more than the safety limit "
                    f"({self._maximum_bytes_billed:,} bytes). "
                    f"Reduce query scope or increase maximum_bytes_billed."
                ) from e
            raise RuntimeError(f"BigQuery query error: {e}") from e

    # ─── Dry run ──────────────────────────────────────────────────────

    async def dry_run(self, sql: str) -> dict[str, Any]:
        """Estimate query cost without executing (dry run).

        Returns bytes that would be processed and estimated cost in USD.
        """
        if self._client is None:
            raise RuntimeError("Not connected")
        try:
            job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
            if self._dataset:
                job_config.default_dataset = f"{self._project}.{self._dataset}"

            def _run():
                return self._client.query(sql, job_config=job_config)

            query_job = await asyncio.to_thread(_run)
            total_bytes = query_job.total_bytes_processed or 0
            return {
                "total_bytes_processed": total_bytes,
                "estimated_cost_usd": round(total_bytes / (1024**4) * 6.25, 6),
                "human_readable": self._format_bytes(total_bytes),
                "would_exceed_limit": (
                    self._maximum_bytes_billed is not None
                    and total_bytes > self._maximum_bytes_billed
                ),
            }
        except Exception as e:
            raise RuntimeError(f"BigQuery dry run error: {e}") from e

    def get_last_job_stats(self) -> dict | None:
        """Return stats from the most recently executed query job."""
        return self._last_job_stats

    @staticmethod
    def _format_bytes(n: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if abs(n) < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} PB"

    # ─── Schema ───────────────────────────────────────────────────────

    async def get_schema(self) -> dict[str, Any]:
        if self._client is None:
            raise RuntimeError("Not connected")

        from concurrent.futures import ThreadPoolExecutor

        schema: dict[str, Any] = {}

        def _list_datasets():
            return list(self._client.list_datasets())

        def _list_tables(dataset_id: str):
            dataset_ref = self._client.dataset(dataset_id)
            return dataset_id, list(self._client.list_tables(dataset_ref))

        def _get_table(table_ref):
            return self._client.get_table(table_ref)

        # Step 1: List datasets
        datasets = await asyncio.to_thread(_list_datasets)
        if not datasets:
            return schema

        # Step 2: List tables in all datasets concurrently
        table_lists = await asyncio.gather(
            *(asyncio.to_thread(_list_tables, ds.dataset_id) for ds in datasets)
        )

        # Step 3: Fetch full table metadata concurrently (batched for large schemas)
        all_table_refs = []
        for dataset_id, tables in table_lists:
            for table_ref in tables:
                all_table_refs.append((dataset_id, table_ref))

        # Batch concurrent get_table calls (max 20 concurrent to respect API limits)
        batch_size = 20
        for i in range(0, len(all_table_refs), batch_size):
            batch = all_table_refs[i : i + batch_size]
            tables = await asyncio.gather(
                *(asyncio.to_thread(_get_table, ref) for _, ref in batch)
            )
            for (dataset_id, _), table in zip(batch, tables):
                key = f"{dataset_id}.{table.table_id}"

                def _flatten_fields(fields, prefix=""):
                    """Flatten nested STRUCT/RECORD fields for Spider2.0 compatibility."""
                    cols = []
                    for field in fields:
                        full_name = f"{prefix}.{field.name}" if prefix else field.name
                        cols.append({
                            "name": full_name,
                            "type": field.field_type,
                            "nullable": field.mode != "REQUIRED",
                            "primary_key": False,
                            "comment": field.description or "",
                            "mode": field.mode,
                        })
                        # Recursively flatten nested RECORD fields
                        if field.field_type == "RECORD" and field.fields:
                            cols.extend(_flatten_fields(field.fields, full_name))
                    return cols

                columns = _flatten_fields(table.schema)

                # BigQuery table_type: TABLE, VIEW, MATERIALIZED_VIEW, EXTERNAL, SNAPSHOT
                bq_type = getattr(table, "table_type", "TABLE") or "TABLE"
                obj_type = "view" if "VIEW" in bq_type else "table"
                table_meta: dict[str, Any] = {
                    "schema": dataset_id,
                    "name": table.table_id,
                    "type": obj_type,
                    "columns": columns,
                    "row_count": table.num_rows,
                    "size_bytes": table.num_bytes,
                }
                # BigQuery-specific metadata for query optimization
                if table.time_partitioning:
                    table_meta["partitioning"] = {
                        "field": table.time_partitioning.field,
                        "type": table.time_partitioning.type_,
                    }
                if table.clustering_fields:
                    table_meta["clustering_fields"] = list(table.clustering_fields)
                if table.description:
                    table_meta["description"] = table.description
                schema[key] = table_meta

        return schema

    # ─── Sample values ────────────────────────────────────────────────

    async def get_sample_values(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        """Get sample distinct values via single UNION ALL query (1 round trip).

        Critical for BigQuery where each query job has ~500ms overhead.
        """
        if self._client is None or not columns:
            return {}
        try:
            sql = self._build_sample_union_sql(table, columns, limit, quote='`')

            def _run():
                job = self._client.query(sql, timeout=30)
                return [dict(row) for row in job.result(timeout=30)]

            rows = await asyncio.to_thread(_run)
            return self._parse_sample_union_result(rows)
        except Exception:
            # Fallback to per-column queries (also non-blocking)
            result: dict[str, list] = {}
            for col in columns[:20]:
                try:
                    safe_col = col.replace('`', '``')
                    safe_table = self._quote_table(table)
                    query = f"SELECT DISTINCT `{safe_col}` FROM {safe_table} WHERE `{safe_col}` IS NOT NULL LIMIT {limit}"

                    def _run_col(q=query, c=col):
                        job = self._client.query(q, timeout=10)
                        rows = list(job.result(timeout=10))
                        return [str(row[c]) for row in rows if row[c] is not None]

                    values = await asyncio.to_thread(_run_col)
                    if values:
                        result[col] = values
                except Exception:
                    continue
            return result

    # ─── Health check (non-blocking) ──────────────────────────────────

    async def health_check(self) -> bool:
        if self._client is None:
            return False
        try:
            def _ping():
                job = self._client.query("SELECT 1", timeout=10)
                list(job.result(timeout=10))
            await asyncio.to_thread(_ping)
            return True
        except Exception:
            return False

    # ─── Close ────────────────────────────────────────────────────────

    async def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
        self._cleanup_temp_files()
