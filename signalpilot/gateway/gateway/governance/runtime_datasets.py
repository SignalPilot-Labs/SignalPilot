"""Track B streamed query execution into opaque private Parquet datasets."""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from gateway.connectors.pool_manager import pool_manager
from gateway.db.models import (
    GatewayGovernedQueryExecution,
    GatewayRuntimeDataset,
)
from gateway.engine import sqlglot_dialect, validate_sql
from gateway.governance.annotations import load_annotations
from gateway.governance.pii import PIIRedactor
from gateway.governance.plan_limits import check_query_limit, get_org_limits, record_query
from gateway.governance.query_executor import GovernedQueryContext
from gateway.governance.query_planner import QueryPlanError, require_execution_plan
from gateway.standalone_chat.config import enterprise_chat_feature_flags
from gateway.standalone_chat.object_storage import chat_object_storage, runtime_object_key
from gateway.standalone_chat.query_approvals import (
    reconcile_reservation,
    reserve_or_request_approval,
)
from gateway.store import Store
from gateway.store import standalone_chat as chat_store


class RuntimeDatasetError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class RuntimeDatasetExecutor:
    def __init__(self) -> None:
        self._active_connectors: dict[str, Any] = {}

    async def cancel(self, execution_id: str) -> bool:
        connector = self._active_connectors.get(execution_id)
        return await connector.cancel_current_query() if connector is not None else False

    async def execute(
        self,
        store: Store,
        *,
        connection_name: str,
        sql: str,
        plan_id: str,
        context: GovernedQueryContext,
        timeout_seconds: int,
    ) -> GatewayRuntimeDataset:
        if not context.run_id or not context.conversation_id or not context.project_id or not context.commit_sha:
            raise RuntimeDatasetError("scope_incomplete", "DatasetRef execution requires a complete chat scope")
        org_id = store._require_org_id()
        limits = await get_org_limits(org_id)
        check_query_limit(org_id, limits)
        try:
            plan = await require_execution_plan(
                store,
                plan_id=plan_id,
                sql=sql,
                connection_name=connection_name,
                context=context,
                allowed_routes={"dataset_ref"},
            )
        except QueryPlanError as exc:
            raise RuntimeDatasetError(exc.code, str(exc)) from exc
        existing = (
            await store.session.execute(
                select(GatewayRuntimeDataset).where(
                    GatewayRuntimeDataset.run_id == context.run_id,
                    GatewayRuntimeDataset.plan_id == plan_id,
                    GatewayRuntimeDataset.org_id == org_id,
                    GatewayRuntimeDataset.owner_user_id == (store.user_id or "local"),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        info = await store.get_connection(connection_name)
        if info is None:
            raise RuntimeDatasetError("connection_not_found", "Connection not found")
        if info.db_type not in {"postgres", "snowflake"}:
            raise RuntimeDatasetError(
                "aggregate_required",
                "This connector does not support streamed datasets; aggregate in warehouse SQL",
            )
        settings = await store.load_settings()
        annotations = load_annotations(store._require_org_id(), connection_name)
        blocked_tables = list(annotations.blocked_tables)
        blocked_tables.extend(table for table in settings.blocked_tables or [] if table not in blocked_tables)
        validation = validate_sql(
            sql,
            blocked_tables=blocked_tables or None,
            dialect=sqlglot_dialect(info.db_type),
        )
        if not validation.ok:
            raise RuntimeDatasetError("query_blocked", validation.blocked_reason or "Query blocked")
        execution = GatewayGovernedQueryExecution(
            id=str(uuid.uuid4()),
            org_id=org_id,
            user_id=store.user_id,
            conversation_id=context.conversation_id,
            run_id=context.run_id,
            project_id=context.project_id,
            commit_sha=context.commit_sha,
            connection_name=connection_name,
            plan_id=plan_id,
            query_path="dataset_ref",
            sql_hash=plan.sql_hash,
            status="running",
            timeout_seconds=timeout_seconds,
            estimated_cost_usd=plan.estimated_cost_usd,
            started_at=datetime.now(UTC),
        )
        store.session.add(execution)
        plan.used_at = datetime.now(UTC)
        await store.session.commit()

        proposal_id = None
        if enterprise_chat_feature_flags().query_approval:
            reservation = await reserve_or_request_approval(
                store.session,
                run_id=context.run_id,
                sql_hash=plan.sql_hash,
                normalized_sql=plan.normalized_sql,
                connection_name=connection_name,
                query_path="dataset_ref",
                purpose=plan.purpose,
                timeout_seconds=timeout_seconds,
                estimated_cost_usd=plan.estimated_cost_usd,
                estimate_quality=plan.estimate_quality,
                estimate_json={
                    "estimated_scan_rows": plan.estimated_scan_rows,
                    "estimated_scan_bytes": plan.estimated_scan_bytes,
                    "estimated_output_rows": plan.estimated_output_rows,
                    "estimated_output_bytes": plan.estimated_output_bytes,
                },
                plan_id=plan_id,
            )
            proposal_id = reservation.proposal_id
            plan.proposal_id = proposal_id
            if not reservation.approved:
                execution.status = "waiting_for_approval"
                await store.session.commit()
                raise RuntimeDatasetError(
                    "query_approval_required",
                    f"Query approval required (proposal {proposal_id})",
                )
        await chat_store.append_event(
            store.session,
            run_id=context.run_id,
            event_type="query_started",
            payload={
                "execution_id": execution.id,
                "plan_id": plan_id,
                "proposal_id": proposal_id,
                "route": "dataset_ref",
            },
        )

        dataset_id = str(uuid.uuid4())
        key = runtime_object_key(
            org_id=org_id,
            conversation_id=context.conversation_id,
            run_id=context.run_id,
            category="datasets",
            object_id=dataset_id,
            filename="dataset.parquet",
        )
        writer = None
        parquet_writer = None
        row_count = 0
        arrow_schema = None
        conn_str = await store.get_connection_string(connection_name)
        if not conn_str:
            execution.status = "failed"
            execution.public_error_code = "credentials_missing"
            execution.terminal_at = datetime.now(UTC)
            await store.session.commit()
            if proposal_id:
                await reconcile_reservation(
                    store.session,
                    proposal_id=proposal_id,
                    actual_cost_usd=None,
                    completed=False,
                )
            raise RuntimeDatasetError("credentials_missing", "No credentials stored for this connection")
        extras = await store.get_credential_extras(connection_name)
        redactor = PIIRedactor()
        if info.pii_enabled and info.pii_rules:
            for column, rule in info.pii_rules.items():
                redactor.add_rule(column, rule)
        for column, rule in annotations.pii_columns.items():
            redactor.add_rule(column, rule)
        started = time.monotonic()
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq

            writer = await chat_object_storage().multipart_writer(
                key=key,
                content_type="application/vnd.apache.parquet",
            )

            async with pool_manager.connection(
                info.db_type,
                conn_str,
                credential_extras=extras,
                connection_name=connection_name,
            ) as connector:
                self._active_connectors[execution.id] = connector
                async for batch in connector.stream_batches(
                    sql,
                    batch_size=10_000,
                    timeout=timeout_seconds,
                ):
                    if redactor.has_rules():
                        batch = redactor.redact_rows(batch)
                    table = pa.Table.from_pylist(batch, schema=arrow_schema)
                    if arrow_schema is None:
                        arrow_schema = table.schema
                        parquet_writer = pq.ParquetWriter(writer, arrow_schema, compression="zstd")
                    assert parquet_writer is not None
                    await asyncio.to_thread(parquet_writer.write_table, table)
                    row_count += table.num_rows
                    await chat_store.append_event(
                        store.session,
                        run_id=context.run_id,
                        event_type="query_progress",
                        payload={"execution_id": execution.id, "rows_streamed": row_count},
                    )
                execution.warehouse_query_id = connector.get_last_query_id()
                stats = connector.get_last_query_stats() or {}
            if parquet_writer is None:
                arrow_schema = pa.schema([])
                parquet_writer = pq.ParquetWriter(writer, arrow_schema, compression="zstd")
            await asyncio.to_thread(parquet_writer.close)
            stored = await asyncio.to_thread(writer.complete)
        except BaseException as exc:
            with suppress(Exception):
                if parquet_writer is not None:
                    await asyncio.to_thread(parquet_writer.close)
            with suppress(Exception):
                if writer is not None:
                    await asyncio.to_thread(writer.abort)
            with suppress(Exception):
                connector = self._active_connectors.get(execution.id)
                if connector is not None:
                    await connector.cancel_current_query()
            execution.status = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
            execution.public_error_code = (
                "query_cancelled" if isinstance(exc, asyncio.CancelledError) else "dataset_stream_failed"
            )
            execution.terminal_at = datetime.now(UTC)
            await store.session.commit()
            if proposal_id:
                with suppress(Exception):
                    await reconcile_reservation(
                        store.session,
                        proposal_id=proposal_id,
                        actual_cost_usd=None,
                        completed=False,
                    )
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise RuntimeDatasetError("dataset_stream_failed", "Streamed dataset execution failed") from exc
        finally:
            self._active_connectors.pop(execution.id, None)

        schema_json = [
            {"name": field.name, "logical_type": str(field.type), "nullable": field.nullable}
            for field in arrow_schema
        ]
        dataset = GatewayRuntimeDataset(
            id=dataset_id,
            org_id=org_id,
            owner_user_id=store.user_id or "local",
            conversation_id=context.conversation_id,
            run_id=context.run_id,
            project_id=context.project_id,
            commit_sha=context.commit_sha,
            connection_name=connection_name,
            plan_id=plan_id,
            query_execution_id=execution.id,
            schema_json=schema_json,
            row_count=row_count,
            byte_size=stored.byte_size,
            completeness="complete",
            object_key=stored.key,
            content_hash=stored.content_hash,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        store.session.add(dataset)
        execution.status = "completed"
        elapsed_ms = (time.monotonic() - started) * 1000
        actual_cost_usd = float(stats.get("estimated_cost_usd") or 0) or (
            elapsed_ms / 1000
        ) * 0.000014
        execution.actual_cost_usd = actual_cost_usd
        for key_name in ("total_bytes_processed", "total_bytes_billed", "bytes_scanned", "scanned_bytes"):
            if stats.get(key_name) is None:
                continue
            try:
                execution.actual_scan_bytes = max(0, int(stats[key_name]))
                break
            except (TypeError, ValueError):
                continue
        execution.actual_output_bytes = stored.byte_size
        execution.execution_ms = elapsed_ms
        execution.row_count = row_count
        execution.completeness = "complete"
        execution.terminal_at = datetime.now(UTC)
        try:
            await store.session.commit()
        except Exception as exc:
            await store.session.rollback()
            with suppress(Exception):
                await chat_object_storage().delete(stored.key)
            with suppress(Exception):
                persisted_execution = await store.session.get(GatewayGovernedQueryExecution, execution.id)
                if persisted_execution is not None:
                    persisted_execution.status = "failed"
                    persisted_execution.public_error_code = "dataset_persistence_failed"
                    persisted_execution.actual_cost_usd = actual_cost_usd
                    persisted_execution.actual_output_bytes = stored.byte_size
                    persisted_execution.execution_ms = elapsed_ms
                    persisted_execution.row_count = row_count
                    persisted_execution.completeness = "complete"
                    persisted_execution.terminal_at = datetime.now(UTC)
                    await store.session.commit()
            if proposal_id:
                with suppress(Exception):
                    await reconcile_reservation(
                        store.session,
                        proposal_id=proposal_id,
                        actual_cost_usd=actual_cost_usd,
                        completed=True,
                    )
            record_query(org_id)
            raise RuntimeDatasetError(
                "dataset_persistence_failed",
                "The warehouse query completed but DatasetRef metadata could not be persisted",
            ) from exc
        if proposal_id:
            await reconcile_reservation(
                store.session,
                proposal_id=proposal_id,
                actual_cost_usd=execution.actual_cost_usd,
                completed=True,
            )
        record_query(org_id)
        await chat_store.append_event(
            store.session,
            run_id=context.run_id,
            event_type="query_completed",
            payload={
                "execution_id": execution.id,
                "dataset_id": dataset.id,
                "row_count": row_count,
                "byte_size": stored.byte_size,
                "completeness": "complete",
            },
        )
        return dataset


runtime_dataset_executor = RuntimeDatasetExecutor()
