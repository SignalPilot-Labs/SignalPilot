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
        # Credentials are set via set_credentials() before connect
        # or fall back to ADC
        self._client = bigquery.Client(project=self._project)

    def set_credentials(self, credentials_json: str, project: str = "", dataset: str = ""):
        """Set credentials from a service account JSON string."""
        if not HAS_BIGQUERY:
            raise RuntimeError("google-cloud-bigquery not installed")
        info = json.loads(credentials_json)
        creds = service_account.Credentials.from_service_account_info(info)
        self._project = project or info.get("project_id", "")
        self._dataset = dataset
        self._client = bigquery.Client(
            project=self._project,
            credentials=creds,
        )

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

        schema: dict[str, Any] = {}

        # List all datasets in the project
        datasets = list(self._client.list_datasets())
        for ds in datasets:
            dataset_ref = self._client.dataset(ds.dataset_id)
            tables = list(self._client.list_tables(dataset_ref))

            for table_ref in tables:
                table = self._client.get_table(table_ref)
                key = f"{ds.dataset_id}.{table.table_id}"
                columns = []
                for field in table.schema:
                    columns.append({
                        "name": field.name,
                        "type": field.field_type,
                        "nullable": field.mode != "REQUIRED",
                        "primary_key": False,  # BigQuery doesn't have traditional PKs
                        "description": field.description or "",
                    })
                schema[key] = {
                    "schema": ds.dataset_id,
                    "name": table.table_id,
                    "columns": columns,
                    "row_count": table.num_rows,
                    "size_bytes": table.num_bytes,
                }

        return schema

    async def get_sample_values(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        """Get sample distinct values for schema linking optimization."""
        if self._client is None:
            return {}
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
