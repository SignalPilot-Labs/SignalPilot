"""BigQuery connector — google-cloud-bigquery backed.

Supports service account JSON auth and ADC (Application Default Credentials).
Tier 1 connector matching HEX's BigQuery integration.
"""

from __future__ import annotations

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
        self._client: bigquery.Client | None = None
        self._project: str = ""
        self._dataset: str = ""

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

    def set_credentials(self, credentials_json: str, project: str = "", dataset: str = ""):
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
        self._project = project or info.get("project_id", "")
        self._dataset = dataset
        self._client = bigquery.Client(
            project=self._project,
            credentials=creds,
        )

    def set_credential_extras(self, extras: dict) -> None:
        """Extract BigQuery credentials from credential extras."""
        if extras.get("credentials_json"):
            self.set_credentials(
                credentials_json=extras["credentials_json"],
                project=extras.get("project", self._project),
                dataset=extras.get("dataset", self._dataset),
            )

    async def _ensure_connected(self) -> None:
        """Verify BigQuery client can reach the API; raise RuntimeError if not."""
        if self._client is None:
            raise RuntimeError("Not connected")
        try:
            import asyncio
            await asyncio.to_thread(lambda: list(self._client.query("SELECT 1", timeout=10).result(timeout=10)))
        except Exception:
            self._client = None
            raise RuntimeError("BigQuery connection lost — please reconnect")

    async def execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        if self._client is None:
            raise RuntimeError("Not connected")
        try:
            job_config = bigquery.QueryJobConfig()
            if self._dataset:
                job_config.default_dataset = f"{self._project}.{self._dataset}"

            query_job = self._client.query(sql, job_config=job_config, timeout=timeout)
            results = query_job.result(timeout=timeout)
            return [dict(row) for row in results]
        except Exception as e:
            raise RuntimeError(f"BigQuery query error: {e}") from e

    async def get_schema(self) -> dict[str, Any]:
        if self._client is None:
            raise RuntimeError("Not connected")

        import asyncio
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

    async def get_sample_values(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        """Get sample distinct values via single UNION ALL query (1 round trip).

        Critical for BigQuery where each query job has ~500ms overhead.
        """
        if self._client is None or not columns:
            return {}
        try:
            sql = self._build_sample_union_sql(table, columns, limit, quote='`')
            import asyncio
            def _run():
                job = self._client.query(sql, timeout=30)
                return [dict(row) for row in job.result(timeout=30)]
            rows = await asyncio.to_thread(_run)
            return self._parse_sample_union_result(rows)
        except Exception:
            # Fallback to per-column queries
            result: dict[str, list] = {}
            for col in columns[:20]:
                try:
                    query = f"SELECT DISTINCT `{col}` FROM `{table}` WHERE `{col}` IS NOT NULL LIMIT {limit}"
                    job = self._client.query(query, timeout=10)
                    rows = list(job.result(timeout=10))
                    values = [str(row[col]) for row in rows if row[col] is not None]
                    if values:
                        result[col] = values
                except Exception:
                    continue
            return result

    async def health_check(self) -> bool:
        if self._client is None:
            return False
        try:
            query_job = self._client.query("SELECT 1", timeout=10)
            list(query_job.result(timeout=10))
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
