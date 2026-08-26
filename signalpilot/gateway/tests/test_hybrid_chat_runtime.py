from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.api.standalone_chat import _sanitize_runtime_archive_html
from gateway.db.models import GatewayBase, GatewayQueryPlan
from gateway.governance.cost_estimator import CostEstimator
from gateway.governance.query_executor import GovernedQueryContext, normalize_sql
from gateway.governance.query_planner import (
    MAX_RESULT_BYTES,
    MCP_MAX_ROWS,
    TRACK_A_MAX_ROWS,
    UNKNOWN_SCOUT_ROWS,
    QueryPlanError,
    _approval_required,
    _policy_hash,
    choose_query_route,
    require_execution_plan,
)
from gateway.standalone_chat.artifacts import normalize_table_snapshot, table_to_csv
from gateway.standalone_chat.object_storage import (
    MultipartUploadWriter,
    conversation_prefix,
    runtime_object_key,
)


def _route(
    *,
    rows: int | None,
    byte_size: int | None,
    execution_need: str = "sql",
    quality: str = "exact",
    track_b: bool = False,
    supported: bool = True,
    justified: bool = False,
    raw_export: bool = False,
):
    return choose_query_route(
        execution_need=execution_need,  # type: ignore[arg-type]
        estimated_output_rows=rows,
        estimated_output_bytes=byte_size,
        estimate_quality=quality,
        track_b_enabled=track_b,
        connector_supports_datasets=supported,
        row_level_analysis_justified=justified,
        raw_export_requested=raw_export,
    )


@pytest.mark.asyncio
async def test_chat_approval_is_not_required_when_feature_is_disabled(monkeypatch):
    monkeypatch.delenv("SP_FEATURE_CHAT_QUERY_APPROVAL", raising=False)
    context = GovernedQueryContext(
        path="mcp",
        conversation_id="conversation-a",
        run_id="run-a",
        project_id="project-a",
        commit_sha="a" * 40,
        branch="main",
    )
    store = SimpleNamespace()

    assert await _approval_required(store, context, 999.0) is False


@pytest.mark.asyncio
async def test_get_query_plan_normalizes_local_notebook_owner(monkeypatch):
    from gateway.api import query as query_api

    context = GovernedQueryContext(
        path="sdk",
        conversation_id="conversation-a",
        run_id="run-a",
        project_id="project-a",
        commit_sha="a" * 40,
        branch="main",
        plan_id="plan-a",
    )

    async def query_context(*_args, **_kwargs):
        return context

    plan = SimpleNamespace(
        id="plan-a",
        org_id="local",
        user_id="local",
        run_id="run-a",
        project_id="project-a",
        commit_sha="a" * 40,
        branch="main",
        sql_hash="hash-a",
        route="notebook_sdk",
        route_reason="Python requires the notebook SDK.",
        estimate_quality="exact",
        approval_required=False,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    class Session:
        async def get(self, _model, plan_id):
            assert plan_id == "plan-a"
            return plan

    monkeypatch.setattr(query_api, "_query_context", query_context)
    store = SimpleNamespace(
        user_id=None,
        session=Session(),
        _require_org_id=lambda: "local",
    )

    response = await query_api.get_query_plan("plan-a", store, SimpleNamespace())

    assert response["route"] == "notebook_sdk"


@pytest.mark.parametrize(
    ("rows", "byte_size", "execution_need", "expected"),
    [
        (MCP_MAX_ROWS, MAX_RESULT_BYTES, "sql", "mcp"),
        (MCP_MAX_ROWS + 1, MAX_RESULT_BYTES, "sql", "notebook_sdk"),
        (1, 1, "python", "notebook_sdk"),
        (TRACK_A_MAX_ROWS, MAX_RESULT_BYTES, "python", "notebook_sdk"),
        (TRACK_A_MAX_ROWS + 1, MAX_RESULT_BYTES, "sql", "aggregate_required"),
        (1, MAX_RESULT_BYTES + 1, "sql", "aggregate_required"),
    ],
)
def test_locked_track_a_routing_boundaries(rows, byte_size, execution_need, expected):
    route, _reason, scout_limit = _route(
        rows=rows,
        byte_size=byte_size,
        execution_need=execution_need,
    )
    assert route == expected
    assert scout_limit is None


def test_unknown_output_only_allows_bounded_scouting():
    assert _route(rows=None, byte_size=None, quality="unknown") == (
        "mcp",
        "Output cardinality is unknown; only a 1,000-row scouting query is permitted before a bounded aggregate.",
        UNKNOWN_SCOUT_ROWS,
    )


@pytest.mark.asyncio
async def test_postgres_estimate_separates_large_scan_from_small_aggregate_output():
    class Connector:
        async def execute(self, _sql: str):
            return [
                {
                    "QUERY PLAN": [
                        {
                            "Plan": {
                                "Node Type": "Aggregate",
                                "Plan Rows": 1,
                                "Plan Width": 8,
                                "Total Cost": 1234.5,
                                "Plans": [
                                    {
                                        "Node Type": "Seq Scan",
                                        "Plan Rows": 2_000_000,
                                        "Plan Width": 64,
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]

    estimate = await CostEstimator.estimate_postgres(Connector(), "SELECT SUM(amount) FROM orders")

    assert estimate.estimated_scan_rows == 2_000_000
    assert estimate.estimated_scan_bytes == 128_000_000
    assert estimate.estimated_output_rows == 1
    assert estimate.estimated_output_bytes == 8
    assert _route(
        rows=estimate.estimated_output_rows,
        byte_size=estimate.estimated_output_bytes,
    )[0] == "mcp"


def test_track_b_requires_flag_connector_support_and_row_level_justification():
    oversized = TRACK_A_MAX_ROWS + 1
    assert _route(rows=oversized, byte_size=1, track_b=True, supported=True, justified=True)[0] == "dataset_ref"
    assert _route(rows=oversized, byte_size=1, track_b=True, supported=False, justified=True)[0] == (
        "aggregate_required"
    )
    assert _route(rows=oversized, byte_size=1, track_b=True, supported=True, justified=False)[0] == (
        "aggregate_required"
    )
    assert _route(
        rows=10,
        byte_size=1,
        track_b=True,
        supported=True,
        justified=True,
        raw_export=True,
    )[0] == "refuse"


def test_routes_are_deterministic_for_identical_inputs():
    values = [_route(rows=42_000, byte_size=2_000_000, execution_need="sql") for _ in range(10)]
    assert len(set(values)) == 1


@pytest_asyncio.fixture
async def plan_store():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        store = SimpleNamespace(
            session=session,
            user_id="user-a",
            _require_org_id=lambda: "org-a",
        )

        async def get_connection(_name: str):
            return SimpleNamespace(db_type="postgres")

        async def load_settings():
            return SimpleNamespace(blocked_tables=[])

        store.get_connection = get_connection
        store.load_settings = load_settings
        yield store
    await engine.dispose()


@pytest.mark.asyncio
async def test_plan_is_bound_to_sql_scope_expiry_and_current_policy(plan_store, monkeypatch):
    from gateway.governance import query_planner

    monkeypatch.setenv("SP_FEATURE_CHAT_SIZE_ROUTER", "true")
    monkeypatch.setattr(
        query_planner,
        "load_annotations",
        lambda _org_id, _connection: SimpleNamespace(blocked_tables=[]),
    )
    sql = "SELECT 1 AS value"
    normalized = normalize_sql(sql, "postgres")
    row = GatewayQueryPlan(
        id="plan-a",
        org_id="org-a",
        user_id="user-a",
        conversation_id="conversation-a",
        run_id="run-a",
        project_id="project-a",
        commit_sha="a" * 40,
        branch="main",
        connection_name="warehouse",
        purpose="Test plan binding",
        execution_need="sql",
        normalized_sql=normalized,
        sql_hash=hashlib.sha256(normalized.encode()).hexdigest(),
        estimated_scan_rows=1_000_000,
        estimated_scan_bytes=100_000_000,
        estimated_output_rows=1,
        estimated_output_bytes=8,
        estimated_cost_usd=0.01,
        estimate_quality="exact",
        route="mcp",
        route_reason="bounded aggregate",
        approval_required=False,
        policy_version="hybrid-chat-router-v1",
        policy_hash=_policy_hash(db_type="postgres", blocked_tables=[]),
        shadow=False,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    plan_store.session.add(row)
    await plan_store.session.commit()
    context = GovernedQueryContext(
        path="mcp",
        conversation_id="conversation-a",
        run_id="run-a",
        project_id="project-a",
        commit_sha="a" * 40,
        branch="main",
        plan_id="plan-a",
    )

    assert (
        await require_execution_plan(
            plan_store,
            plan_id="plan-a",
            sql=sql,
            connection_name="warehouse",
            context=context,
            allowed_routes={"mcp"},
        )
    ).id == "plan-a"
    with pytest.raises(QueryPlanError, match="execution scope"):
        await require_execution_plan(
            plan_store,
            plan_id="plan-a",
            sql="SELECT 2 AS value",
            connection_name="warehouse",
            context=context,
            allowed_routes={"mcp"},
        )

    monkeypatch.setenv("SP_FEATURE_CHAT_SIZE_ROUTER", "shadow")
    with pytest.raises(QueryPlanError, match="policy changed"):
        await require_execution_plan(
            plan_store,
            plan_id="plan-a",
            sql=sql,
            connection_name="warehouse",
            context=context,
            allowed_routes={"mcp"},
        )

    monkeypatch.setenv("SP_FEATURE_CHAT_SIZE_ROUTER", "true")
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await plan_store.session.commit()
    with pytest.raises(QueryPlanError, match="expired"):
        await require_execution_plan(
            plan_store,
            plan_id="plan-a",
            sql=sql,
            connection_name="warehouse",
            context=context,
            allowed_routes={"mcp"},
        )


def test_runtime_object_keys_isolate_org_conversation_and_run():
    key = runtime_object_key(
        org_id="org/private value",
        conversation_id="../conversation-a",
        run_id="../run-a",
        category="derived/results",
        object_id="object-a",
        filename="../rows.json",
    )
    assert "org/private value" not in key
    assert ".." not in key
    assert key.startswith(conversation_prefix("org/private value", "../conversation-a") + "/runs/")
    assert "/derived-results/" in key


class _MultipartClient:
    def __init__(self) -> None:
        self.uploads: list[bytes] = []
        self.completed = False
        self.aborted = False

    def create_multipart_upload(self, **_kwargs):
        return {"UploadId": "upload-a"}

    def upload_part(self, *, Body, PartNumber, **_kwargs):
        self.uploads.append(bytes(Body))
        return {"ETag": f"etag-{PartNumber}"}

    def complete_multipart_upload(self, **_kwargs):
        self.completed = True

    def abort_multipart_upload(self, **_kwargs):
        self.aborted = True


def test_multipart_writer_hashes_and_streams_without_full_payload_materialization():
    client = _MultipartClient()
    writer = MultipartUploadWriter(
        client=client,
        bucket="private",
        key="runtime.parquet",
        content_type="application/vnd.apache.parquet",
    )
    writer._MIN_PART_BYTES = 4
    writer.start()
    writer.write(b"abc")
    writer.write(b"defgh")
    stored = writer.complete()

    assert client.uploads == [b"abcd", b"efgh"]
    assert client.completed is True
    assert stored.byte_size == 8
    assert stored.content_hash == hashlib.sha256(b"abcdefgh").hexdigest()


def test_multipart_writer_produces_a_readable_parquet_object():
    import pyarrow as pa
    import pyarrow.parquet as pq

    client = _MultipartClient()
    writer = MultipartUploadWriter(
        client=client,
        bucket="private",
        key="runtime.parquet",
        content_type="application/vnd.apache.parquet",
    )
    writer.start()
    table = pa.Table.from_pylist([{"id": 1, "amount": 12.5}, {"id": 2, "amount": 20.0}])
    parquet_writer = pq.ParquetWriter(writer, table.schema, compression="zstd")
    parquet_writer.write_table(table)
    parquet_writer.close()
    writer.complete()

    recovered = pq.read_table(pa.BufferReader(b"".join(client.uploads))).to_pylist()
    assert recovered == [{"id": 1, "amount": 12.5}, {"id": 2, "amount": 20.0}]


def test_table_preview_is_bounded_while_full_csv_keeps_all_rows():
    snapshot = {
        "columns": [{"name": "id"}, {"name": "value"}],
        "rows": [{"id": index, "value": f"row-{index}"} for index in range(5_000)],
        "saved_row_count": 5_000,
        "truncated": False,
    }

    preview = normalize_table_snapshot(snapshot)
    csv_lines = table_to_csv(snapshot).decode("utf-8-sig").splitlines()

    assert len(preview["rows"]) == 200
    assert preview["display_limited"] is True
    assert preview["saved_row_count"] == 5_000
    assert len(csv_lines) == 5_001
    assert csv_lines[-1] == "4999,row-4999"


def test_runtime_archive_html_gets_a_non_networked_csp_and_loses_navigation_tags():
    sanitized = _sanitize_runtime_archive_html(
        '<html><head><base href="https://evil.example"><meta http-equiv="refresh" content="0; url=x">'
        "</head><body><script>renderNotebook()</script></body></html>"
    )
    assert "<base" not in sanitized.lower()
    assert "http-equiv=\"refresh\"" not in sanitized.lower()
    assert "Content-Security-Policy" in sanitized
    assert "connect-src 'none'" in sanitized
    assert "<script>renderNotebook()</script>" in sanitized


def test_runtime_archive_html_injects_a_head_when_one_is_missing():
    sanitized = _sanitize_runtime_archive_html("<html><body>notebook</body></html>")

    assert sanitized.startswith('<html><head><meta http-equiv="Content-Security-Policy"')
    assert "connect-src 'none'" in sanitized


@pytest.mark.asyncio
async def test_mssql_estimate_separates_large_scan_from_small_top_n_output():
    class Connector:
        def __init__(self):
            self.statements = []

        async def execute(self, sql: str):
            self.statements.append(sql)
            if sql.startswith("SET SHOWPLAN_ALL"):
                return []
            # SHOWPLAN_ALL lists the root first, then operators depth-first.
            return [
                {"StmtText": "SELECT TOP 10 ...", "EstimateRows": 10, "TotalSubtreeCost": 4.2},
                {"StmtText": "  |--Sort(...)", "EstimateRows": 850, "TotalSubtreeCost": 4.0},
                {"StmtText": "    |--Clustered Index Scan(...)", "EstimateRows": 1_200_000, "TotalSubtreeCost": 3.5},
            ]

    estimate = await CostEstimator.estimate_mssql(
        Connector(), "SELECT TOP 10 market, SUM(x) FROM f GROUP BY market"
    )

    assert estimate.estimated_scan_rows == 1_200_000
    assert estimate.estimated_output_rows == 10
    assert _route(
        rows=estimate.estimated_output_rows,
        byte_size=estimate.estimated_output_rows * 512,
    )[0] == "mcp"


def test_explicit_row_limit_caps_the_router_input_regardless_of_dialect():
    from gateway.governance.query_planner import _explicit_row_limit

    assert _explicit_row_limit("SELECT TOP 10 a FROM t GROUP BY a", "tsql") == 10
    assert _explicit_row_limit("SELECT a FROM t LIMIT 25", "duckdb") == 25
    assert (
        _explicit_row_limit(
            "SELECT a FROM t ORDER BY a OFFSET 0 ROWS FETCH NEXT 15 ROWS ONLY", "tsql"
        )
        == 15
    )
    assert _explicit_row_limit("SELECT a FROM t", "tsql") is None
    assert _explicit_row_limit("not sql at all (", "tsql") is None
