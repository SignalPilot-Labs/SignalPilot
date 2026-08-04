from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
import yaml
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.db.models import (
    GatewayBase,
    GatewayChatConversation,
    GatewayChatRun,
    GatewayChatUserPreference,
    GatewayQueryProposal,
)
from gateway.governance.cost_estimator import CostEstimator
from gateway.standalone_chat.config import enterprise_chat_feature_flags
from gateway.standalone_chat.contracts import (
    CONTRACT_VERSION,
    ApprovalScope,
    BudgetLedger,
    BudgetPolicy,
    Completeness,
    CompletenessState,
    EnterpriseRunStatus,
    EstimateQuality,
    ForkContract,
    QueryApproval,
    QueryEstimate,
    QueryEventType,
    QueryPath,
    QueryProposal,
    QueryProposalStatus,
    QueryPublicEvent,
    QueryScope,
    ResultColumn,
    ResultProvenance,
    ShareContract,
    StructuredResult,
    stable_sql_hash,
)
from gateway.standalone_chat.query_approvals import (
    decide_query_proposal,
    reconcile_reservation,
    reserve_or_request_approval,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
BENCHMARK_DIR = REPO_ROOT / "signalpilot" / "gateway" / "benchmarks" / "enterprise_data_chat"
COMMIT_SHA = "a" * 40
NOW = datetime(2026, 7, 31, tzinfo=UTC)


@pytest_asyncio.fixture
async def approval_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _chat_run(approval_db, run_id: str = "run-a"):
    if await approval_db.get(GatewayChatConversation, "conversation-a") is None:
        approval_db.add(
            GatewayChatConversation(
                id="conversation-a",
                org_id="org-a",
                user_id="user-a",
                project_id="project-a",
                surface="standalone",
                branch="main",
                commit_sha=COMMIT_SHA,
                status="active",
                per_query_budget_usd=1.0,
                chat_budget_usd=1.0,
                title="Budget test",
                message_count=1,
                total_tokens=0,
                total_cost_usd=0,
                created_at=1,
                updated_at=1,
            )
        )
    run = GatewayChatRun(
        id=run_id,
        org_id="org-a",
        user_id="user-a",
        conversation_id="conversation-a",
        project_id="project-a",
        user_message_id=f"message-{run_id}",
        status="running",
    )
    approval_db.add(run)
    await approval_db.commit()
    return run


def _scope() -> QueryScope:
    return QueryScope(
        org_id="org-a",
        user_id="user-a",
        conversation_id="conversation-a",
        run_id="run-a",
        project_id="project-a",
        commit_sha=COMMIT_SHA,
        connection_id="connection-a",
    )


def _estimate(cost: str = "0.10") -> QueryEstimate:
    return QueryEstimate(
        estimated_cost_usd=Decimal(cost),
        quality=EstimateQuality.approximate,
        estimated_rows=10,
        warning="Capacity-based estimate",
    )


def test_contracts_bind_query_to_scope_hash_timeout_and_estimate():
    normalized_sql = "SELECT month, SUM(revenue) FROM analytics.orders GROUP BY month"
    proposal = QueryProposal(
        id="proposal-a",
        scope=_scope(),
        path=QueryPath.sdk,
        purpose="Calculate monthly revenue",
        normalized_sql=normalized_sql,
        sql_hash=stable_sql_hash(normalized_sql),
        timeout_seconds=120,
        status=QueryProposalStatus.estimated,
        estimate=_estimate(),
        policy_version="policy-v1",
        created_at=NOW,
    )
    assert proposal.scope.commit_sha == COMMIT_SHA
    assert proposal.sql_hash == stable_sql_hash(normalized_sql)

    with pytest.raises(ValidationError, match="require an estimate"):
        proposal.model_copy(update={"estimate": None})
        QueryProposal(**{**proposal.model_dump(), "estimate": None})
    with pytest.raises(ValidationError, match="40-character Git SHA"):
        QueryScope(**{**_scope().model_dump(), "commit_sha": "main"})
    with pytest.raises(ValidationError, match="less than or equal to 3600"):
        QueryProposal(**{**proposal.model_dump(), "timeout_seconds": 3_601})


def test_budget_contract_has_locked_defaults_and_no_implicit_overspend():
    policy = BudgetPolicy()
    assert policy.per_query_budget_usd == Decimal("0.25")
    assert policy.chat_budget_usd == Decimal("1.00")
    ledger = BudgetLedger(
        policy=policy,
        actual_spend_usd=Decimal("0.55"),
        reserved_spend_usd=Decimal("0.20"),
        estimated_spend_usd=Decimal("0.75"),
    )
    assert ledger.remaining_chat_budget_usd == Decimal("0.25")
    with pytest.raises(ValidationError, match="at least per_query_budget_usd"):
        BudgetPolicy(per_query_budget_usd="1.01", chat_budget_usd="1.00")
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        BudgetPolicy(per_query_budget_usd="-0.01", chat_budget_usd="1.00")


@pytest.mark.asyncio
async def test_chat_budget_reservation_is_transactional_and_reconciles_actual_cost(approval_db):
    await _chat_run(approval_db)
    first = await reserve_or_request_approval(
        approval_db,
        run_id="run-a",
        sql_hash="1" * 64,
        normalized_sql="SELECT 1",
        connection_name="warehouse",
        query_path="sdk",
        purpose="First query",
        timeout_seconds=30,
        estimated_cost_usd=0.7,
        estimate_quality="approximate",
        estimate_json={},
    )
    assert first.approved
    conversation = await approval_db.get(GatewayChatConversation, "conversation-a")
    assert conversation.reserved_spend_usd == pytest.approx(0.7)

    await reconcile_reservation(
        approval_db,
        proposal_id=first.proposal_id,
        actual_cost_usd=0.6,
        completed=True,
    )
    await approval_db.refresh(conversation)
    assert conversation.reserved_spend_usd == 0
    assert conversation.actual_spend_usd == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_cumulative_budget_pauses_and_exact_decision_resumes_same_run(approval_db):
    run = await _chat_run(approval_db)
    conversation = await approval_db.get(GatewayChatConversation, "conversation-a")
    conversation.actual_spend_usd = 0.9
    await approval_db.commit()
    decision = await reserve_or_request_approval(
        approval_db,
        run_id=run.id,
        sql_hash="2" * 64,
        normalized_sql="SELECT 2",
        connection_name="warehouse",
        query_path="mcp",
        purpose="Over remaining chat budget",
        timeout_seconds=30,
        estimated_cost_usd=0.2,
        estimate_quality="approximate",
        estimate_json={},
    )
    assert not decision.approved
    await approval_db.refresh(run)
    assert run.status == "waiting_for_query_approval"

    resumed = await decide_query_proposal(
        approval_db,
        org_id="org-a",
        user_id="user-a",
        proposal_id=decision.proposal_id,
        decision="approve",
        approval_scope="run_once",
        per_query_budget_usd=None,
        chat_budget_usd=None,
    )
    assert resumed is not None
    assert resumed.id == run.id
    assert resumed.status == "queued"
    proposal = await approval_db.get(GatewayQueryProposal, decision.proposal_id)
    assert proposal.sql_hash == "2" * 64
    assert proposal.status == "approved"


@pytest.mark.asyncio
async def test_user_default_approval_updates_future_defaults_only_explicitly(approval_db):
    run = await _chat_run(approval_db)
    conversation = await approval_db.get(GatewayChatConversation, "conversation-a")
    conversation.per_query_budget_usd = 0.25
    await approval_db.commit()
    reservation = await reserve_or_request_approval(
        approval_db,
        run_id=run.id,
        sql_hash="3" * 64,
        normalized_sql="SELECT 3",
        connection_name="warehouse",
        query_path="sdk",
        purpose="Update explicit defaults",
        timeout_seconds=30,
        estimated_cost_usd=0.5,
        estimate_quality="approximate",
        estimate_json={},
    )
    await decide_query_proposal(
        approval_db,
        org_id="org-a",
        user_id="user-a",
        proposal_id=reservation.proposal_id,
        decision="approve",
        approval_scope="user_defaults",
        per_query_budget_usd=0.75,
        chat_budget_usd=2.0,
    )
    preference = (
        await approval_db.execute(
            select(GatewayChatUserPreference).where(
                GatewayChatUserPreference.org_id == "org-a",
                GatewayChatUserPreference.user_id == "user-a",
            )
        )
    ).scalar_one()
    assert preference.default_per_query_budget_usd == 0.75
    assert preference.default_chat_budget_usd == 2.0


def test_approval_is_exact_hash_scoped_and_expiring():
    sql_hash = stable_sql_hash("SELECT 1")
    approval = QueryApproval(
        id="approval-a",
        proposal_id="proposal-a",
        approver_user_id="user-a",
        scope=ApprovalScope.run_once,
        sql_hash=sql_hash,
        connection_id="connection-a",
        project_id="project-a",
        run_id="run-a",
        approved_estimated_cost_usd="2.50",
        policy_version="policy-v1",
        expires_at=NOW + timedelta(minutes=15),
        created_at=NOW,
    )
    assert approval.sql_hash != stable_sql_hash("SELECT 2")
    assert EnterpriseRunStatus.waiting_for_query_approval.value == "waiting_for_query_approval"


def test_result_requires_three_explicit_completeness_dimensions_and_provenance():
    complete = Completeness(state=CompletenessState.complete)
    result = StructuredResult(
        id="result-a",
        org_id="org-a",
        owner_user_id="user-a",
        columns=[ResultColumn(name="revenue", logical_type="decimal", nullable=False)],
        query_row_count=1,
        saved_row_count=1,
        preview_rows=[{"revenue": "765.00"}],
        source_completeness=Completeness(
            state=CompletenessState.unknown,
            reason="Source coverage requires analyst confirmation",
        ),
        result_completeness=complete,
        display_completeness=complete,
        provenance=ResultProvenance(
            query_execution_id="execution-a",
            sql_hash=stable_sql_hash("SELECT 765 AS revenue"),
            project_id="project-a",
            commit_sha=COMMIT_SHA,
            connection_id="connection-a",
            runtime_version="runtime-1",
            plugin_version="plugin-1",
            model_names=["orders"],
            source_names=["production.orders"],
            freshness_at=NOW,
        ),
        created_at=NOW,
    )
    assert result.result_completeness.state == CompletenessState.complete
    with pytest.raises(ValidationError, match="requires a reason"):
        Completeness(state=CompletenessState.truncated)
    with pytest.raises(ValidationError, match="cannot exceed"):
        StructuredResult(**{**result.model_dump(), "saved_row_count": 2})


def test_share_and_fork_contracts_lock_auth_org_commit_and_fresh_runtime():
    share = ShareContract(
        conversation_id="conversation-a",
        owner_user_id="user-a",
        org_id="org-a",
    )
    fork = ForkContract(
        parent_conversation_id="conversation-a",
        recipient_user_id="user-b",
        org_id="org-a",
        project_id="project-a",
        commit_sha=COMMIT_SHA,
        budget=BudgetPolicy(),
        confirmed_at=NOW,
    )
    assert share.authenticated and share.same_organization_only
    assert fork.fresh_sandbox_required and fork.parent_snapshot_immutable
    with pytest.raises(ValidationError):
        ShareContract(
            conversation_id="conversation-a",
            owner_user_id="user-a",
            org_id="org-a",
            authenticated=False,
        )


def test_public_query_event_vocabulary_is_complete_and_versioned():
    expected = {
        "query_proposed",
        "query_estimated",
        "query_approval_requested",
        "query_approved",
        "query_declined",
        "query_started",
        "query_progress",
        "query_completed",
        "query_cancelled",
    }
    assert {event.value for event in QueryEventType} == expected
    event = QueryPublicEvent(
        type=QueryEventType.query_completed,
        run_id="run-a",
        proposal_id="proposal-a",
        query_execution_id="execution-a",
        sequence=8,
        occurred_at=NOW,
        payload={"result_id": "result-a", "row_count": 1},
    )
    assert event.contract_version == CONTRACT_VERSION
    with pytest.raises(ValidationError):
        QueryPublicEvent(**{**event.model_dump(), "payload": {}, "sql": "SELECT secret"})


def test_enterprise_feature_boundaries_are_independent_and_disabled_by_default(monkeypatch):
    names = [
        "SP_FEATURE_CHAT_SANDBOX_RUNTIME",
        "SP_FEATURE_CHAT_QUERY_APPROVAL",
        "SP_FEATURE_CHAT_STRUCTURED_RESULTS",
        "SP_FEATURE_CHAT_ORG_SHARING",
        "SP_FEATURE_CHAT_FORKING",
        "SP_FEATURE_CHAT_SIZE_ROUTER",
        "SP_FEATURE_CHAT_NOTEBOOK_ANALYSIS",
        "SP_FEATURE_CHAT_RUNTIME_RESULTS",
        "SP_FEATURE_CHAT_RUNTIME_ARTIFACTS",
        "SP_FEATURE_CHAT_DATASET_REFS",
    ]
    for name in names:
        monkeypatch.delenv(name, raising=False)
    assert not any(vars(enterprise_chat_feature_flags()).values())

    monkeypatch.setenv("SP_FEATURE_CHAT_QUERY_APPROVAL", "true")
    flags = enterprise_chat_feature_flags()
    assert flags.query_approval
    assert not flags.sandbox_runtime
    assert not flags.structured_results
    assert not flags.organization_sharing
    assert not flags.forking

    monkeypatch.setenv("SP_FEATURE_CHAT_SIZE_ROUTER", "shadow")
    flags = enterprise_chat_feature_flags()
    assert flags.size_router is False
    assert flags.size_router_shadow is True


def test_gold_benchmark_spec_covers_phase_zero_scenarios_and_has_expected_results():
    spec = yaml.safe_load((BENCHMARK_DIR / "gold_questions.yaml").read_text())
    scenarios = {scenario["id"]: scenario for scenario in spec["scenarios"]}
    assert set(scenarios) == {
        "full-history-aggregate",
        "monthly-trend",
        "high-cardinality-top-n",
        "fanout-prone-join",
        "long-history-anomaly",
        "raw-export-request",
        "per-query-budget-exceedance",
        "cumulative-chat-budget-exceedance",
        "query-timeout",
        "query-cancellation",
        "worker-loss",
        "sandbox-loss",
        "artifact-consistency",
    }
    sql_scenarios = [scenario for scenario in scenarios.values() if "gold_sql" in scenario]
    assert len(sql_scenarios) == 5
    assert all("expected" in scenario and "tolerances" in scenario for scenario in sql_scenarios)
    assert (BENCHMARK_DIR / spec["fixture"]).is_file()


def test_gold_sql_matches_deterministic_duckdb_fixture():
    duckdb = pytest.importorskip("duckdb")
    spec = yaml.safe_load((BENCHMARK_DIR / "gold_questions.yaml").read_text())
    connection = duckdb.connect(":memory:")
    connection.execute((BENCHMARK_DIR / spec["fixture"]).read_text())

    for scenario in spec["scenarios"]:
        if "gold_sql" not in scenario:
            continue
        cursor = connection.execute(scenario["gold_sql"])
        columns = [column[0] for column in cursor.description]
        rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
        normalized_rows = [
            {
                key: (
                    value.isoformat()
                    if hasattr(value, "isoformat")
                    else int(value)
                    if isinstance(value, Decimal) and value == value.to_integral()
                    else value
                )
                for key, value in row.items()
            }
            for row in rows
        ]
        expected = scenario["expected"]
        if "rows" in expected:
            assert normalized_rows == expected["rows"], scenario["id"]
        else:
            for key, value in normalized_rows[0].items():
                assert value == expected[key], scenario["id"]

    connection.close()


@pytest.mark.asyncio
async def test_postgres_estimator_accounts_for_full_plan_tree():
    class Connector:
        async def execute(self, _sql):
            return [
                {
                    "QUERY PLAN": [
                        {
                            "Plan": {
                                "Node Type": "Hash Join",
                                "Plan Rows": 10,
                                "Total Cost": 42.0,
                                "Plans": [
                                    {"Node Type": "Seq Scan", "Plan Rows": 1_000},
                                    {"Node Type": "Seq Scan", "Plan Rows": 2_000},
                                ],
                            }
                        }
                    ]
                }
            ]

    estimate = await CostEstimator.estimate_postgres(Connector(), "SELECT 1")  # type: ignore[arg-type]
    assert estimate.estimated_rows == 3_000
    assert estimate.estimated_cost == 42.0
