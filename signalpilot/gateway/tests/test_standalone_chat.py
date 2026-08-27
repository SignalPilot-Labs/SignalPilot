"""Focused contracts for durable standalone data chat and team sharing."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.auth import jwt_secret
from gateway.auth.notebook_jwt import mint_session_jwt, verify_session_jwt
from gateway.db.models import (
    GatewayBase,
    GatewayChatArtifact,
    GatewayChatConversation,
    GatewayChatMessage,
    GatewayChatRun,
    GatewayChatRunEvent,
    GatewayChatShareGrant,
    GatewayChatUserPreference,
    GatewayConnection,
    GatewayCredential,
    GatewayDbtManifest,
    GatewayStructuredQueryResult,
    GatewayWorkspaceProject,
)
from gateway.mcp.audit import standalone_chat_tool_denial
from gateway.mcp.context import (
    mcp_allowed_connection_var,
    mcp_execution_identity_var,
)
from gateway.models.standalone_chat import (
    StandaloneConversationPatch,
    StandaloneRunCreate,
)
from gateway.standalone_chat import execution as chat_execution
from gateway.standalone_chat import projects as chat_projects
from gateway.standalone_chat.artifacts import (
    normalize_table_snapshot,
    protect_csv_cell,
    sanitize_chart_snapshot,
    sanitize_report_html,
    table_to_csv,
)
from gateway.standalone_chat.chart_theme import (
    CHART_BACKGROUND,
    CHART_COLORS,
    CHART_MUTED_TEXT,
    CHART_TEXT,
    MAX_CHART_CATEGORIES,
    MAX_CHART_SERIES,
    SIGNALPILOT_CHART_THEME,
)
from gateway.standalone_chat.domain import (
    assert_run_transition,
    fallback_conversation_title,
    select_context_for_summary,
)
from gateway.standalone_chat.projects import (
    evaluate_project_readiness,
    generate_starter_questions,
    resolve_default_project,
)
from gateway.standalone_chat.worker import _merge_text_delta
from gateway.store import chat as notebook_chat_store
from gateway.store import standalone_chat as chat_store
from gateway.store.store import Store


def test_merge_text_delta_separates_semantic_text_blocks() -> None:
    updated, emitted = _merge_text_delta(
        "underlying data.",
        "Perfect!",
        starts_new_block=True,
    )

    assert updated == "underlying data.\n\nPerfect!"
    assert emitted == "\n\nPerfect!"


def test_merge_text_delta_preserves_token_whitespace_and_existing_newlines() -> None:
    updated, emitted = _merge_text_delta(
        "and the",
        " underlying data.",
        starts_new_block=False,
    )
    assert updated == "and the underlying data."
    assert emitted == " underlying data."

    updated, emitted = _merge_text_delta(
        "done.\n",
        "\nNext",
        starts_new_block=True,
    )
    assert updated == "done.\n\nNext"
    assert emitted == "\nNext"


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _project(db: AsyncSession, *, org_id: str = "org-a") -> GatewayWorkspaceProject:
    project = GatewayWorkspaceProject(
        id="project-a",
        org_id=org_id,
        name="revenue",
        display_name="Revenue",
        description="Revenue analytics",
        connection_name="production",
        source="managed",
        status="active",
        settings={"model_names": ["orders"], "metric_names": ["revenue"]},
        file_count=2,
        total_bytes=100,
        default_branch="main",
        created_at=1.0,
        updated_at=1.0,
    )
    db.add(project)
    await db.commit()
    return project


async def _conversation_and_run(
    db: AsyncSession,
    *,
    user_id: str = "user-a",
) -> tuple[str, GatewayChatRun]:
    project = await _project(db)
    conversation, run = await chat_store.create_conversation_with_run(
        db,
        org_id="org-a",
        user_id=user_id,
        project=project,
        branch="main",
        message="What changed in revenue?",
        commit_sha="a" * 40,
    )
    return conversation.id, run


async def _completed_shared_conversation(
    db: AsyncSession,
) -> tuple[str, GatewayChatRun, str]:
    conversation_id, run = await _conversation_and_run(db)
    conversation = (
        await db.execute(select(GatewayChatConversation).where(GatewayChatConversation.id == conversation_id))
    ).scalar_one()
    assistant_message_id = "assistant-message-a"
    db.add(
        GatewayChatMessage(
            id=assistant_message_id,
            org_id="org-a",
            user_id="user-a",
            project_id="project-a",
            conversation_id=conversation_id,
            role="assistant",
            content="Revenue increased by 12%.",
            metadata_json={
                "surface": "standalone",
                "run_id": run.id,
                "internal": {"sql": "select * from revenue"},
            },
            idempotency_key=f"chat-run:{run.id}:final",
            sequence=2,
            created_at=2.0,
        )
    )
    db.add(
        GatewayChatArtifact(
            id="artifact-a",
            org_id="org-a",
            user_id="user-a",
            conversation_id=conversation_id,
            run_id=run.id,
            assistant_message_id=assistant_message_id,
            kind="table",
            filename="revenue.csv",
            mime_type="text/csv",
            snapshot_json={
                "columns": [{"name": "revenue"}],
                "rows": [{"revenue": 112}],
            },
            provenance_json={"sql": "select revenue from private_schema.revenue"},
            freshness_at=datetime(2026, 7, 30, tzinfo=UTC),
            assumptions=["Booked revenue only"],
            exclusions=["Refunds"],
            caveats=["Partial current day"],
        )
    )
    conversation.title = "Revenue trend"
    conversation.internal_summary = "Hidden execution summary"
    conversation.message_count = 2
    run.status = "completed"
    run.terminal_at = datetime.now(UTC)
    await db.commit()
    return conversation_id, run, assistant_message_id


def test_state_machine_and_title_contracts():
    assert_run_transition("queued", "running")
    assert_run_transition("running", "waiting_for_user")
    assert_run_transition("waiting_for_user", "queued")
    with pytest.raises(ValueError, match="Invalid chat run transition"):
        assert_run_transition("completed", "running")
    assert len(fallback_conversation_title("x" * 100)) == 60
    with pytest.raises(ValueError):
        StandaloneRunCreate(message="answer", role="assistant")
    with pytest.raises(ValueError):
        StandaloneConversationPatch(title="Renamed", project_id="another-project")
    messages = [{"role": "user" if index % 2 == 0 else "assistant", "content": "x" * 100} for index in range(20)]
    selection = select_context_for_summary(
        messages,
        artifact_refs=[{"id": "artifact-a"}],
        usable_context_chars=2_000,
    )
    assert selection is not None
    assert len(selection["recent_messages"]) == 16
    assert selection["artifact_refs"] == [{"id": "artifact-a"}]


def test_starter_questions_are_exactly_four_and_project_aware():
    project = GatewayWorkspaceProject(
        id="project-a",
        org_id="org-a",
        name="revenue",
        display_name="Revenue",
        status="active",
        settings={
            "model_names": ["orders", "customers"],
            "metric_names": ["net_revenue"],
            "source_names": ["stripe"],
        },
        file_count=1,
        total_bytes=1,
        created_at=1.0,
        updated_at=1.0,
    )
    questions = generate_starter_questions(project, "main")
    assert len(questions) == 4
    assert any("net revenue" in question for question in questions)
    assert any("orders" in question for question in questions)


def test_artifact_security_helpers():
    assert protect_csv_cell("=SUM(A1:A2)") == "'=SUM(A1:A2)"
    content = table_to_csv(
        {
            "columns": [{"name": "value"}],
            "rows": [{"value": "@cmd"}],
            "truncated": True,
        }
    ).decode("utf-8-sig")
    assert "'@cmd" in content
    assert "governed query row limit" in content

    sanitized = sanitize_report_html(
        '<script>alert(1)</script><img src="https://example.com/x.png" onerror="x">'
        '<img src="/api/private">'
        '<p style="color:red">safe</p><a href="javascript:alert(1)">bad</a>'
    )
    assert "<script" not in sanitized
    assert "onerror" not in sanitized
    assert "https://example.com" not in sanitized
    assert "/api/private" not in sanitized
    assert "javascript:" not in sanitized
    assert 'style="color:red"' in sanitized
    assert "connect-src 'none'" in sanitized

    full_document = sanitize_report_html(
        "<!doctype html><html><head>"
        '<meta charset="utf-8"><link rel="stylesheet" href="https://example.com/report.css">'
        "<style>body{color:#171717}.metric{display:grid}</style>"
        '</head><body><main class="metric"><h1>Revenue</h1><p>$42</p></main></body></html>'
    )
    assert "<main" in full_document
    assert "<h1>Revenue</h1>" in full_document
    assert "body{color:#171717}" in full_document
    assert "example.com/report.css" not in full_document

    unsafe_style = sanitize_report_html("<style>.metric{background:url(https://example.com/pixel)}</style><p>safe</p>")
    assert "example.com/pixel" not in unsafe_style
    assert "<p>safe</p>" in unsafe_style

    with pytest.raises(ValueError, match="no renderable static content"):
        sanitize_report_html('<meta charset="utf-8"><script>document.write("report")</script>')

    chart = sanitize_chart_snapshot(
        {
            "spec": {
                "mark": "bar",
                "data": {"url": "https://example.com/data.json"},
                "encoding": {
                    "x": {"field": "label", "href": "https://example.com"},
                    "y": {"field": "value"},
                },
                "transform": [
                    {"calculate": "datum.value * 2", "as": "unsafe"},
                    {"filter": "datum.value > 0"},
                ],
            },
            "rows": [{"label": "A", "value": 1}],
        }
    )
    serialized = str(chart)
    assert "https://example.com" not in serialized
    assert "calculate" not in serialized
    assert "datum.value" not in serialized
    assert chart["source"]["rows"] == [{"label": "A", "value": 1}]
    assert len(normalize_table_snapshot({"rows": list(range(1_100))})["rows"]) == 200


def test_chart_theme_is_enforced_after_sanitization_and_limits_visual_density():
    rows = [
        {
            "category": f"Very long category label {category:02d}",
            "value": (-1 if category % 2 else 1) * (category + 1) * 1_000_000,
            "series": f"Series {series:02d}",
        }
        for category in range(MAX_CHART_CATEGORIES + 3)
        for series in range(MAX_CHART_SERIES + 2)
    ]
    chart = sanitize_chart_snapshot(
        {
            "spec": {
                "title": {"text": "Revenue by category", "color": "#000000"},
                "background": "#000000",
                "mark": {
                    "type": "bar",
                    "color": "#000000",
                    "opacity": 0.05,
                },
                "config": {
                    "axis": {"labelColor": "#000000"},
                    "range": {"category": ["#000000"]},
                },
                "encoding": {
                    "x": {
                        "field": "category",
                        "type": "nominal",
                        "axis": {"labelColor": "#000000"},
                    },
                    "y": {
                        "field": "value",
                        "type": "quantitative",
                        "scale": {"domain": [0, 1]},
                    },
                    "color": {
                        "field": "series",
                        "type": "nominal",
                        "scale": {"range": ["#000000"]},
                        "legend": {"labelColor": "#000000"},
                    },
                },
            },
            "rows": rows,
        }
    )

    spec = chart["spec"]
    assert spec["background"] == CHART_BACKGROUND
    assert spec["title"] == "Revenue by category"
    assert spec["mark"] == {
        "type": "bar",
        "cornerRadiusEnd": 3,
        "invalid": "filter",
    }
    assert spec["config"]["axis"]["labelColor"] == CHART_TEXT
    assert spec["config"]["axis"]["titleColor"] == CHART_TEXT
    assert spec["config"]["legend"]["labelColor"] == CHART_TEXT
    assert spec["config"]["range"]["category"] == list(CHART_COLORS)
    assert spec["encoding"]["x"]["axis"]["labelAngle"] == -45
    assert spec["encoding"]["y"]["axis"]["format"] == ".3~s"
    assert spec["encoding"]["y"]["scale"] == {
        "type": "linear",
        "nice": True,
        "zero": True,
    }
    assert spec["encoding"]["color"]["scale"]["range"] == list(CHART_COLORS)
    assert spec["encoding"]["xOffset"]["field"] == "series"
    assert spec["usermeta"]["signalpilotChartTheme"] == SIGNALPILOT_CHART_THEME
    assert "#000000" not in str(spec)
    assert chart["display"] == {
        "category_limit": MAX_CHART_CATEGORIES,
        "legend_limit": MAX_CHART_SERIES,
        "limited": True,
        "omitted_rows": len(rows) - (MAX_CHART_CATEGORIES * MAX_CHART_SERIES),
    }
    assert len(chart["rows"]) == MAX_CHART_CATEGORIES * MAX_CHART_SERIES
    assert chart["source"]["rows"] == rows[:200]
    assert chart["source"]["display_limited"] is True
    assert chart["source"]["saved_row_count"] == len(rows)


def test_chart_theme_text_contrast_is_at_least_wcag_aa():
    def luminance(color: str) -> float:
        values = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in values]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    background = luminance(CHART_BACKGROUND)
    for foreground in (CHART_TEXT, CHART_MUTED_TEXT):
        light, dark = sorted((luminance(foreground), background), reverse=True)
        assert (light + 0.05) / (dark + 0.05) >= 4.5


@pytest.mark.asyncio
async def test_same_org_peer_cannot_discover_private_conversation(db_session):
    conversation_id, _ = await _conversation_and_run(db_session)
    assert (
        await chat_store.get_conversation_detail(
            db_session,
            org_id="org-a",
            user_id="user-b",
            conversation_id=conversation_id,
        )
        is None
    )
    assert (
        await chat_store.list_conversations(
            db_session,
            org_id="org-a",
            user_id="user-b",
        )
        == []
    )


@pytest.mark.asyncio
async def test_share_grant_is_hashed_same_org_and_trace_free(db_session):
    conversation_id, _, _ = await _completed_shared_conversation(db_session)
    result = await chat_store.create_share_grant(
        db_session,
        org_id="org-a",
        user_id="user-a",
        conversation_id=conversation_id,
    )
    assert result is not None
    grant, token = result
    assert grant.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in grant.token_hash

    shared = await chat_store.get_shared_conversation(
        db_session,
        org_id="org-a",
        token=token,
    )
    assert shared is not None
    assert shared.conversation.title == "Revenue trend"
    assert [message.role for message in shared.messages] == ["user", "assistant"]
    assert not hasattr(shared.messages[1], "metadata")
    assert len(shared.artifacts) == 1
    assert shared.artifacts[0].assumptions == ["Booked revenue only"]
    assert not hasattr(shared.artifacts[0], "provenance")
    assert (
        await chat_store.get_shared_conversation(
            db_session,
            org_id="org-b",
            token=token,
        )
        is None
    )


@pytest.mark.asyncio
async def test_rotating_revoking_and_archiving_share_returns_not_found(db_session):
    conversation_id, _, _ = await _completed_shared_conversation(db_session)
    first = await chat_store.create_share_grant(
        db_session,
        org_id="org-a",
        user_id="user-a",
        conversation_id=conversation_id,
    )
    assert first is not None
    _, first_token = first
    second = await chat_store.create_share_grant(
        db_session,
        org_id="org-a",
        user_id="user-a",
        conversation_id=conversation_id,
    )
    assert second is not None
    _, second_token = second
    assert (
        await chat_store.get_shared_conversation(
            db_session,
            org_id="org-a",
            token=first_token,
        )
        is None
    )
    assert await chat_store.get_shared_conversation(
        db_session,
        org_id="org-a",
        token=second_token,
    )

    assert await chat_store.revoke_share_grants(
        db_session,
        org_id="org-a",
        user_id="user-a",
        conversation_id=conversation_id,
    )
    assert (
        await chat_store.get_shared_conversation(
            db_session,
            org_id="org-a",
            token=second_token,
        )
        is None
    )

    third = await chat_store.create_share_grant(
        db_session,
        org_id="org-a",
        user_id="user-a",
        conversation_id=conversation_id,
    )
    assert third is not None
    third_grant, third_token = third
    assert await chat_store.archive_conversation(
        db_session,
        org_id="org-a",
        user_id="user-a",
        conversation_id=conversation_id,
    )
    await db_session.refresh(third_grant)
    assert third_grant.state == "revoked"
    assert third_grant.revoked_at is not None
    assert (
        await chat_store.get_shared_conversation(
            db_session,
            org_id="org-a",
            token=third_token,
        )
        is None
    )


@pytest.mark.asyncio
async def test_same_org_viewer_can_fork_share_safe_snapshot(db_session):
    conversation_id, _, assistant_message_id = await _completed_shared_conversation(db_session)
    shared = await chat_store.create_share_grant(
        db_session,
        org_id="org-a",
        user_id="user-a",
        conversation_id=conversation_id,
    )
    assert shared is not None
    _, token = shared

    fork = await chat_store.fork_shared_conversation(
        db_session,
        org_id="org-a",
        user_id="user-b",
        token=token,
        per_query_budget_usd=0.5,
        chat_budget_usd=2.0,
    )
    assert fork is not None
    assert fork.id != conversation_id
    assert fork.user_id == "user-b"
    assert fork.internal_summary is None
    assert fork.commit_sha == "a" * 40
    assert fork.forked_from_conversation_id == conversation_id
    assert fork.per_query_budget_usd == 0.5
    assert fork.chat_budget_usd == 2.0

    detail = await chat_store.get_conversation_detail(
        db_session,
        org_id="org-a",
        user_id="user-b",
        conversation_id=fork.id,
    )
    assert detail is not None
    assert [message.content for message in detail.messages] == [
        "What changed in revenue?",
        "Revenue increased by 12%.",
    ]
    assert detail.messages[1].id != assistant_message_id
    assert detail.current_run is None
    assert len(detail.artifacts) == 1
    assert detail.artifacts[0].assistant_message_id == detail.messages[1].id

    copied_artifact = (
        await db_session.execute(select(GatewayChatArtifact).where(GatewayChatArtifact.id == detail.artifacts[0].id))
    ).scalar_one()
    assert copied_artifact.provenance_json["forked_from_conversation_id"] == conversation_id
    assert copied_artifact.snapshot_json["rows"] == [{"revenue": 112}]

    reshared = await chat_store.create_share_grant(
        db_session,
        org_id="org-a",
        user_id="user-b",
        conversation_id=fork.id,
    )
    assert reshared is not None
    _, reshared_token = reshared
    reshared_detail = await chat_store.get_shared_conversation(
        db_session,
        org_id="org-a",
        token=reshared_token,
    )
    assert reshared_detail is not None
    assert len(reshared_detail.artifacts) == 1


@pytest.mark.asyncio
async def test_fork_preview_preserves_project_commit_and_recipient_budgets(db_session):
    conversation_id, _, _ = await _completed_shared_conversation(db_session)
    shared = await chat_store.create_share_grant(
        db_session,
        org_id="org-a",
        user_id="user-a",
        conversation_id=conversation_id,
    )
    assert shared is not None
    _, token = shared
    db_session.add(
        GatewayChatUserPreference(
            org_id="org-a",
            user_id="user-b",
            default_per_query_budget_usd=0.4,
            default_chat_budget_usd=1.5,
        )
    )
    await db_session.commit()

    preview = await chat_store.get_fork_preview(
        db_session,
        org_id="org-a",
        user_id="user-b",
        token=token,
    )
    assert preview is not None
    assert preview["project_id"] == "project-a"
    assert preview["commit_sha"] == "a" * 40
    assert preview["per_query_budget_usd"] == 0.4
    assert preview["chat_budget_usd"] == 1.5
    assert "live warehouse data" in preview["warehouse_cost_notice"]


@pytest.mark.asyncio
async def test_share_fork_rejects_active_run_and_cross_org(db_session):
    conversation_id, run = await _conversation_and_run(db_session)
    db_session.add(
        GatewayChatArtifact(
            id="in-progress-artifact",
            org_id="org-a",
            user_id="user-a",
            conversation_id=conversation_id,
            run_id=run.id,
            kind="table",
            filename="in-progress.csv",
            mime_type="text/csv",
            snapshot_json={"columns": [], "rows": []},
            assumptions=[],
            exclusions=[],
            caveats=[],
        )
    )
    await db_session.commit()
    shared = await chat_store.create_share_grant(
        db_session,
        org_id="org-a",
        user_id="user-a",
        conversation_id=conversation_id,
    )
    assert shared is not None
    _, token = shared
    shared_detail = await chat_store.get_shared_conversation(
        db_session,
        org_id="org-a",
        token=token,
    )
    assert shared_detail is not None
    assert shared_detail.artifacts == []
    assert (
        await chat_store.get_shared_artifact(
            db_session,
            org_id="org-a",
            token=token,
            artifact_id="in-progress-artifact",
        )
        is None
    )
    with pytest.raises(RuntimeError, match="finish before forking"):
        await chat_store.fork_shared_conversation(
            db_session,
            org_id="org-a",
            user_id="user-b",
            token=token,
            per_query_budget_usd=0.25,
            chat_budget_usd=1.0,
        )
    assert (
        await chat_store.fork_shared_conversation(
            db_session,
            org_id="org-b",
            user_id="user-b",
            token=token,
            per_query_budget_usd=0.25,
            chat_budget_usd=1.0,
        )
        is None
    )
    grants = list(
        (
            await db_session.execute(
                select(GatewayChatShareGrant).where(GatewayChatShareGrant.conversation_id == conversation_id)
            )
        ).scalars()
    )
    assert len(grants) == 1


@pytest.mark.asyncio
async def test_notebook_chat_crud_cannot_see_or_mutate_standalone_rows(db_session):
    conversation_id, _ = await _conversation_and_run(db_session)
    conversations, total = await notebook_chat_store.list_conversations(
        db_session,
        org_id="org-a",
        user_id="user-a",
    )
    assert conversations == []
    assert total == 0
    assert (
        await notebook_chat_store.get_conversation(
            db_session,
            org_id="org-a",
            user_id="user-a",
            conversation_id=conversation_id,
        )
        is None
    )
    with pytest.raises(ValueError, match="not found"):
        await notebook_chat_store.append_message(
            db_session,
            org_id="org-a",
            user_id="user-a",
            conversation_id=conversation_id,
            role="assistant",
            content="Legacy write",
        )


@pytest.mark.asyncio
async def test_default_project_resolution_order_and_inactive_readiness(db_session):
    alpha = await _project(db_session)
    alpha.display_name = "Alpha"
    beta = GatewayWorkspaceProject(
        id="project-b",
        org_id="org-a",
        name="beta",
        display_name="Beta",
        status="inactive",
        settings={},
        file_count=0,
        total_bytes=0,
        default_branch="main",
        created_at=1.0,
        updated_at=1.0,
    )
    db_session.add(beta)
    await db_session.commit()

    assert (
        await resolve_default_project(
            db_session,
            org_id="org-a",
            user_id="user-a",
            ready_project_ids={"project-a", "project-b"},
            projects=[beta, alpha],
        )
        == "project-a"
    )
    db_session.add(
        GatewayChatUserPreference(
            org_id="org-a",
            user_id="user-a",
            default_chat_project_id="project-b",
        )
    )
    await db_session.commit()
    assert (
        await resolve_default_project(
            db_session,
            org_id="org-a",
            user_id="user-a",
            ready_project_ids={"project-a", "project-b"},
            projects=[alpha, beta],
        )
        == "project-b"
    )
    readiness = await evaluate_project_readiness(
        db_session,
        org_id="org-a",
        user_id="user-a",
        project=beta,
    )
    assert not readiness.ready
    assert readiness.code == "project_inactive"


@pytest.mark.asyncio
async def test_existing_conversation_readiness_uses_its_frozen_branch(
    db_session,
    monkeypatch,
):
    project = await _project(db_session)
    db_session.add_all(
        [
            GatewayConnection(
                org_id="org-a",
                user_id="user-a",
                name="production",
                db_type="postgres",
                status="connected",
                created_at=1.0,
                description="",
                tags=[],
                schema_filter_include=[],
                schema_filter_exclude=[],
            ),
            GatewayCredential(
                org_id="org-a",
                user_id="user-a",
                connection_name="production",
                connection_string_enc=b"encrypted",
            ),
        ]
    )
    await db_session.commit()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "configured")
    monkeypatch.setattr(
        chat_projects,
        "_project_tree",
        lambda _project_id, branch: (
            ["dbt_project.yml", "models/orders.sql"],
            "frozen-head" if branch == "production-frozen" else None,
        ),
    )

    readiness = await evaluate_project_readiness(
        db_session,
        org_id="org-a",
        user_id="user-a",
        project=project,
        branch_override="production-frozen",
    )
    assert readiness.ready
    assert readiness.branch == "production-frozen"


@pytest.mark.asyncio
async def test_project_readiness_accepts_org_anthropic_key(db_session, monkeypatch):
    project = await _project(db_session)
    db_session.add_all(
        [
            GatewayConnection(
                org_id="org-a",
                user_id="user-a",
                name="production",
                db_type="postgres",
                status="connected",
                created_at=1.0,
                description="",
                tags=[],
                schema_filter_include=[],
                schema_filter_exclude=[],
            ),
            GatewayCredential(
                org_id="org-a",
                user_id="user-a",
                connection_name="production",
                connection_string_enc=b"encrypted",
            ),
        ]
    )
    await db_session.commit()
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        chat_projects,
        "_project_tree",
        lambda *_args: (["dbt_project.yml", "models/orders.sql"], "frozen-head"),
    )
    resolve_org_key = AsyncMock(return_value="sk-ant-org")
    monkeypatch.setattr(
        chat_projects.org_secrets_store,
        "resolve_anthropic_key",
        resolve_org_key,
    )

    readiness = await evaluate_project_readiness(
        db_session,
        org_id="org-a",
        user_id="user-without-a-key",
        project=project,
    )

    assert readiness.ready
    resolve_org_key.assert_awaited_once_with(db_session, "org-a")


async def _add_production_connection(db: AsyncSession) -> None:
    db.add_all(
        [
            GatewayConnection(
                org_id="org-a",
                user_id="user-a",
                name="production",
                db_type="postgres",
                status="connected",
                created_at=1.0,
                description="",
                tags=[],
                schema_filter_include=[],
                schema_filter_exclude=[],
            ),
            GatewayCredential(
                org_id="org-a",
                user_id="user-a",
                connection_name="production",
                connection_string_enc=b"encrypted",
            ),
        ]
    )
    await db.commit()


@pytest.mark.asyncio
async def test_readiness_recognizes_a_nested_dbt_project(db_session, monkeypatch):
    """Most real repos nest the dbt project in a subfolder. Readiness must find
    it the same way compile/execute do, not assume `dbt_project.yml` at root."""
    project = await _project(db_session)
    await _add_production_connection(db_session)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "configured")
    # dbt project lives under `dumpsters_dbt/`, and there is decoy content
    # (design docs, a second broken copy) that must not fool detection.
    monkeypatch.setattr(
        chat_projects,
        "_project_tree",
        lambda *_args: (
            [
                "README.md",
                "design/models/fct_orders.md",
                "dumpsters_dbt/dbt_project.yml",
                "dumpsters_dbt/models/marts/fct_orders.sql",
                "dumpsters_dbt_broken/dbt_project.yml",
            ],
            "head-sha",
        ),
    )

    readiness = await evaluate_project_readiness(
        db_session,
        org_id="org-a",
        user_id="user-a",
        project=project,
    )

    assert readiness.ready
    assert readiness.code == "ready"


@pytest.mark.asyncio
async def test_readiness_trusts_a_successful_compile_when_tree_is_bare(
    db_session, monkeypatch
):
    """A green dbt-map manifest is proof metadata exists even when the local git
    mirror can't surface the files (sparse/generated models)."""
    project = await _project(db_session)
    await _add_production_connection(db_session)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "configured")
    # Tree carries no dbt project at all — only the compiled manifest vouches.
    monkeypatch.setattr(
        chat_projects,
        "_project_tree",
        lambda *_args: (["README.md", "notes.txt"], "head-sha"),
    )
    db_session.add(
        GatewayDbtManifest(
            org_id="org-a",
            project_id=project.id,
            branch="main",
            revision=1,
            status="success",
            trigger="manual",
            node_count=5,
            created_at=1.0,
            updated_at=1.0,
        )
    )
    await db_session.commit()

    readiness = await evaluate_project_readiness(
        db_session,
        org_id="org-a",
        user_id="user-a",
        project=project,
    )

    assert readiness.ready

    # A failed compile is NOT proof — flip the manifest and readiness must fail.
    manifest = (
        await db_session.execute(select(GatewayDbtManifest))
    ).scalar_one()
    manifest.status = "failed"
    await db_session.commit()

    readiness = await evaluate_project_readiness(
        db_session,
        org_id="org-a",
        user_id="user-a",
        project=project,
    )
    assert not readiness.ready
    assert readiness.code == "metadata_unavailable"


@pytest.mark.asyncio
async def test_execution_uses_org_anthropic_key_as_request_scoped_auth(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-server")
    monkeypatch.setattr(
        chat_execution,
        "ensure_execution_runtime",
        AsyncMock(
            return_value=SimpleNamespace(
                session_id="session-a",
                internal_base_url="http://notebook.internal",
            )
        ),
    )
    resolve_org_key = AsyncMock(return_value="sk-ant-org")
    monkeypatch.setattr(
        chat_execution.org_secrets_store,
        "resolve_anthropic_key",
        resolve_org_key,
    )
    monkeypatch.setattr(chat_execution, "mint_session_jwt", lambda **_kwargs: "session-jwt")
    monkeypatch.setattr(
        chat_execution,
        "get_gateway_public_settings",
        lambda: SimpleNamespace(sp_session_jwt_ttl_seconds=300),
    )
    run = SimpleNamespace(
        id="run-a",
        org_id="org-a",
        user_id="user-without-a-key",
        project_id="project-a",
    )

    prepared = await chat_execution.prepare_execution(
        db_session,
        run=run,
        worker_id="worker-a",
        branch="main",
        connection_name="production",
        commit_sha="a" * 40,
        prompt="Analyze revenue",
        messages=[],
        warm_context={},
    )

    assert prepared.payload["runtime_auth"] == {
        "type": "api_key",
        "token": "sk-ant-org",
    }
    resolve_org_key.assert_awaited_once_with(db_session, "org-a")


@pytest.mark.asyncio
async def test_one_nonterminal_run_and_atomic_initial_state(db_session):
    conversation_id, run = await _conversation_and_run(db_session)
    detail = await chat_store.get_conversation_detail(
        db_session,
        org_id="org-a",
        user_id="user-a",
        conversation_id=conversation_id,
    )
    assert detail is not None
    assert detail.conversation.title == "New chat"
    assert [message.role for message in detail.messages] == ["user"]
    assert detail.current_run and detail.current_run.id == run.id
    with pytest.raises(RuntimeError, match="already active"):
        await chat_store.create_run(
            db_session,
            org_id="org-a",
            user_id="user-a",
            conversation_id=conversation_id,
            message="A second question",
        )


@pytest.mark.asyncio
async def test_event_ordering_redaction_and_replay(db_session):
    _, run = await _conversation_and_run(db_session)
    first = await chat_store.append_event(
        db_session,
        run_id=run.id,
        event_type="tool_started",
        payload={"password": "secret", "connection_string": "postgres://user:pw@host/db"},
    )
    second = await chat_store.append_event(
        db_session,
        run_id=run.id,
        event_type="progress",
        payload={"label": "Reading governed metadata"},
    )
    assert (first.sequence, second.sequence) == (1, 2)
    replay = await chat_store.list_run_events(
        db_session,
        org_id="org-a",
        user_id="user-a",
        run_id=run.id,
        after=1,
    )
    assert replay is not None and [event.sequence for event in replay] == [2]
    assert first.payload_json["password"] == "[REDACTED]"
    assert "postgres://" not in first.payload_json["connection_string"]


@pytest.mark.asyncio
async def test_event_ordering_refreshes_a_stale_locked_run(db_session):
    _, run = await _conversation_and_run(db_session)
    factory = async_sessionmaker(
        db_session.bind,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with factory() as stale_session:
        stale_run = await stale_session.get(GatewayChatRun, run.id)
        assert stale_run is not None
        assert stale_run.last_event_sequence == 0

        first = await chat_store.append_event(
            db_session,
            run_id=run.id,
            event_type="tool_completed",
            payload={"error": False},
        )
        second = await chat_store.append_event(
            stale_session,
            run_id=run.id,
            event_type="artifact_created",
            payload={"artifact_id": "artifact-a"},
        )

    assert (first.sequence, second.sequence) == (1, 2)


@pytest.mark.asyncio
async def test_claim_completion_and_final_message_are_idempotent(db_session):
    conversation_id, run = await _conversation_and_run(db_session)
    claimed = await chat_store.claim_runs(
        db_session,
        worker_id="worker-a",
        limit=4,
        lease_seconds=45,
    )
    assert claimed == [run.id]
    worker_run = await chat_store.get_worker_run(
        db_session,
        run_id=run.id,
        worker_id="worker-a",
    )
    assert worker_run is not None and worker_run.execution_attempt == 1
    first = await chat_store.complete_run(
        db_session,
        run_id=run.id,
        worker_id="worker-a",
        content="Revenue increased.",
    )
    second = await chat_store.complete_run(
        db_session,
        run_id=run.id,
        worker_id="worker-a",
        content="Duplicate.",
    )
    assert first is not None
    assert second is None
    count = await db_session.scalar(
        select(func.count(GatewayChatMessage.id)).where(
            GatewayChatMessage.conversation_id == conversation_id,
            GatewayChatMessage.role == "assistant",
        )
    )
    assert count == 1
    terminal_events = list(
        (
            await db_session.execute(
                select(GatewayChatRunEvent).where(
                    GatewayChatRunEvent.run_id == run.id,
                    GatewayChatRunEvent.event_type == "status",
                )
            )
        ).scalars()
    )
    assert [event.payload_json for event in terminal_events] == [{"status": "completed"}]
    detail = await chat_store.get_conversation_detail(
        db_session,
        org_id="org-a",
        user_id="user-a",
        conversation_id=conversation_id,
    )
    assert detail is not None
    assert detail.conversation.title == "What changed in revenue?"


@pytest.mark.asyncio
async def test_expired_lease_is_reclaimed(db_session):
    _, run = await _conversation_and_run(db_session)
    await chat_store.claim_runs(
        db_session,
        worker_id="dead-worker",
        limit=1,
        lease_seconds=45,
    )
    row = await db_session.get(GatewayChatRun, run.id)
    assert row is not None
    row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    reclaimed = await chat_store.claim_runs(
        db_session,
        worker_id="replacement-worker",
        limit=1,
        lease_seconds=45,
    )
    assert reclaimed == [run.id]
    await db_session.refresh(row)
    assert row.lease_owner == "replacement-worker"
    assert row.execution_attempt == 2


@pytest.mark.asyncio
async def test_cancelled_and_failed_runs_leave_inspectable_status_messages(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
):
    conversation_id, queued_run = await _conversation_and_run(db_session)
    cancelled = await chat_store.request_cancellation(
        db_session,
        org_id="org-a",
        user_id="user-a",
        run_id=queued_run.id,
    )
    assert cancelled is not None and cancelled.status == "cancelled"
    detail = await chat_store.get_conversation_detail(
        db_session,
        org_id="org-a",
        user_id="user-a",
        conversation_id=conversation_id,
    )
    assert detail is not None
    assert detail.messages[-1].metadata["status"] == "cancelled"
    cancelled_events = await chat_store.list_run_events(
        db_session,
        org_id="org-a",
        user_id="user-a",
        run_id=queued_run.id,
    )
    assert cancelled_events is not None
    assert cancelled_events[-1].payload == {"status": "cancelled"}

    failed_run = await chat_store.create_run(
        db_session,
        org_id="org-a",
        user_id="user-a",
        conversation_id=conversation_id,
        message="Try another analysis",
    )
    await chat_store.claim_runs(
        db_session,
        worker_id="worker-a",
        limit=1,
        lease_seconds=45,
    )
    failed_artifact = await chat_store.persist_artifact(
        db_session,
        run=failed_run,
        payload={
            "kind": "table",
            "filename": "unvalidated.csv",
            "mime_type": "text/csv",
            "snapshot": {
                "columns": [{"name": "value"}],
                "rows": [{"value": 1}],
            },
        },
    )
    failed_artifact.storage_kind = "object"
    failed_artifact.object_key = "artifacts/unvalidated.csv"
    failed_artifact.source_object_key = "artifact-sources/unvalidated.csv"
    await db_session.commit()
    delete_object = AsyncMock()
    monkeypatch.setattr(
        chat_store,
        "chat_object_storage",
        lambda: SimpleNamespace(delete=delete_object),
    )
    assert await chat_store.fail_run(
        db_session,
        run_id=failed_run.id,
        worker_id="worker-a",
        code="analysis_failed",
        message="The analysis could not be completed.",
    )
    detail = await chat_store.get_conversation_detail(
        db_session,
        org_id="org-a",
        user_id="user-a",
        conversation_id=conversation_id,
    )
    assert detail is not None
    assert detail.messages[-1].metadata["status"] == "failed"
    assert all(artifact.id != failed_artifact.id for artifact in detail.artifacts)
    assert await db_session.get(GatewayChatArtifact, failed_artifact.id) is None
    assert [call.args[0] for call in delete_object.await_args_list] == [
        "artifacts/unvalidated.csv",
        "artifact-sources/unvalidated.csv",
    ]
    failed_events = await chat_store.list_run_events(
        db_session,
        org_id="org-a",
        user_id="user-a",
        run_id=failed_run.id,
    )
    assert failed_events is not None
    assert failed_events[-1].payload == {"status": "failed"}


@pytest.mark.asyncio
async def test_running_cancellation_wins_over_a_late_final_answer(db_session):
    conversation_id, run = await _conversation_and_run(db_session)
    await chat_store.claim_runs(
        db_session,
        worker_id="worker-a",
        limit=1,
        lease_seconds=45,
    )
    cancellation = await chat_store.request_cancellation(
        db_session,
        org_id="org-a",
        user_id="user-a",
        run_id=run.id,
    )
    assert cancellation is not None and cancellation.status == "running"
    assert (
        await chat_store.complete_run(
            db_session,
            run_id=run.id,
            worker_id="worker-a",
            content="A late answer that must not be displayed.",
        )
        is None
    )
    detail = await chat_store.get_conversation_detail(
        db_session,
        org_id="org-a",
        user_id="user-a",
        conversation_id=conversation_id,
    )
    assert detail is not None
    assert detail.current_run is not None
    assert detail.current_run.status == "cancelled"
    assert detail.messages[-1].content == "This run was stopped."


@pytest.mark.asyncio
async def test_expired_cancelled_run_is_finalized_during_recovery(db_session):
    conversation_id, run = await _conversation_and_run(db_session)
    await chat_store.claim_runs(
        db_session,
        worker_id="dead-worker",
        limit=1,
        lease_seconds=45,
    )
    cancellation = await chat_store.request_cancellation(
        db_session,
        org_id="org-a",
        user_id="user-a",
        run_id=run.id,
    )
    assert cancellation is not None and cancellation.status == "running"
    row = await db_session.get(GatewayChatRun, run.id)
    assert row is not None
    row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    assert (
        await chat_store.claim_runs(
            db_session,
            worker_id="replacement-worker",
            limit=1,
            lease_seconds=45,
        )
        == []
    )
    detail = await chat_store.get_conversation_detail(
        db_session,
        org_id="org-a",
        user_id="user-a",
        conversation_id=conversation_id,
    )
    assert detail is not None
    assert detail.current_run is not None
    assert detail.current_run.status == "cancelled"
    assert detail.messages[-1].content == "This run was stopped."


@pytest.mark.asyncio
async def test_archive_hides_descendants_without_deleting_them(db_session):
    conversation_id, run = await _conversation_and_run(db_session)
    await chat_store.append_event(
        db_session,
        run_id=run.id,
        event_type="progress",
        payload={"label": "Started"},
    )
    assert await chat_store.archive_conversation(
        db_session,
        org_id="org-a",
        user_id="user-a",
        conversation_id=conversation_id,
    )
    assert (
        await chat_store.get_conversation_detail(
            db_session,
            org_id="org-a",
            user_id="user-a",
            conversation_id=conversation_id,
        )
        is None
    )
    assert (
        await chat_store.list_run_events(
            db_session,
            org_id="org-a",
            user_id="user-a",
            run_id=run.id,
        )
        is None
    )
    stored = await db_session.get(GatewayChatRun, run.id)
    assert stored is not None


@pytest.mark.asyncio
async def test_artifact_parent_scope_and_immutable_snapshots(db_session):
    _, run = await _conversation_and_run(db_session)
    parent = await chat_store.persist_artifact(
        db_session,
        run=run,
        payload={
            "kind": "table",
            "filename": "revenue.csv",
            "mime_type": "text/csv",
            "snapshot": {
                "columns": [{"name": "revenue"}],
                "rows": [{"revenue": 10}],
            },
        },
    )
    recovered_parent = await chat_store.persist_artifact(
        db_session,
        run=run,
        payload={
            "kind": "table",
            "filename": "revenue.csv",
            "mime_type": "text/csv",
            "snapshot": {
                "columns": [{"name": "revenue"}],
                "rows": [{"revenue": 999}],
            },
        },
    )
    assert recovered_parent.id == parent.id
    child = await chat_store.persist_artifact(
        db_session,
        run=run,
        payload={
            "kind": "table",
            "filename": "revenue-refined.csv",
            "mime_type": "text/csv",
            "parent_artifact_id": parent.id,
            "snapshot": {
                "columns": [{"name": "revenue"}],
                "rows": [{"revenue": 12}],
            },
        },
    )
    assert child.parent_artifact_id == parent.id
    stored_parent = await db_session.get(GatewayChatArtifact, parent.id)
    assert stored_parent is not None
    assert stored_parent.snapshot_json["rows"] == [{"revenue": 10}]
    with pytest.raises(ValueError, match="MIME"):
        await chat_store.persist_artifact(
            db_session,
            run=run,
            payload={
                "kind": "table",
                "filename": "bad.csv",
                "mime_type": "text/html",
                "snapshot": {"columns": [], "rows": []},
            },
        )
    with pytest.raises(ValueError, match="10 MiB"):
        await chat_store.persist_artifact(
            db_session,
            run=run,
            payload={
                "kind": "report",
                "filename": "oversized.html",
                "mime_type": "text/html",
                "snapshot": {"html": "<p>small report</p>"},
                "provenance": {f"source_{index}": "x" * 20_000 for index in range(530)},
            },
        )


@pytest.mark.asyncio
async def test_fresh_runtime_context_includes_durable_derived_result_references(db_session):
    conversation_id, run = await _conversation_and_run(db_session)
    db_session.add(
        GatewayStructuredQueryResult(
            id="derived-result-a",
            execution_id=None,
            org_id=run.org_id,
            owner_user_id=run.user_id,
            conversation_id=conversation_id,
            run_id=run.id,
            columns_json=[{"name": "total", "logical_type": "integer"}],
            rows_json=[],
            preview_rows_json=[{"total": 42}],
            storage_kind="object",
            object_key="private/result.json",
            byte_size=14,
            content_hash="a" * 64,
            source_result_ids_json=["source-a"],
            code_hash="b" * 64,
            result_origin="runtime",
            query_row_count=1,
            saved_row_count=1,
            source_completeness="complete",
            result_completeness="complete",
            display_completeness="complete",
            provenance_json={"name": "total"},
        )
    )
    await db_session.commit()

    context = await chat_store.worker_context(db_session, run=run)

    assert [result.id for result in context["query_results"]] == ["derived-result-a"]


@pytest.mark.asyncio
async def test_store_connection_claim_limits_visibility(db_session):
    db_session.add_all(
        [
            GatewayConnection(
                org_id="org-a",
                user_id="user-a",
                name="production",
                db_type="postgres",
                created_at=1.0,
                description="",
                tags=[],
                schema_filter_include=[],
                schema_filter_exclude=[],
            ),
            GatewayConnection(
                org_id="org-a",
                user_id="user-a",
                name="sensitive-secondary",
                db_type="postgres",
                created_at=1.0,
                description="",
                tags=[],
                schema_filter_include=[],
                schema_filter_exclude=[],
            ),
        ]
    )
    await db_session.commit()
    store = Store(
        db_session,
        org_id="org-a",
        user_id="user-a",
        allowed_connection_name="production",
    )
    assert [connection.name for connection in await store.list_connections()] == ["production"]
    with pytest.raises(ValueError, match="outside"):
        await store.get_connection("sensitive-secondary")


def test_standalone_session_claims_and_mcp_allowlist(monkeypatch):
    monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
    monkeypatch.setenv("SP_SESSION_JWT_SECRET", "standalone-chat-test-secret-at-least-32-bytes")
    monkeypatch.setattr(jwt_secret, "_cached_secret", None)
    token = mint_session_jwt(
        user_id="user-a",
        org_id="org-a",
        session_id="session-a",
        project_id="project-a",
        branch="main",
        connection_name="production",
        commit_sha="a" * 40,
        capabilities=["schema:read", "query:read"],
        execution_identity="chat:run-a",
        scopes=["read", "query", "execute"],
        ttl=60,
    )
    claims = verify_session_jwt(token)
    assert claims["commit_sha"] == "a" * 40
    assert claims["connection_name"] == "production"
    assert "write" not in claims["scopes"]

    identity_token = mcp_execution_identity_var.set("chat:run-a")
    connection_token = mcp_allowed_connection_var.set("production")
    try:
        assert standalone_chat_tool_denial("query_database", "production") is None
        assert standalone_chat_tool_denial("plan_query", "production") is None
        assert "outside" in (standalone_chat_tool_denial("query_database", "secondary") or "")
        assert "unavailable" in (standalone_chat_tool_denial("notion_create_page", None) or "")
    finally:
        mcp_execution_identity_var.reset(identity_token)
        mcp_allowed_connection_var.reset(connection_token)
