"""Store-layer tests for the Knowledge Base module.

All tests use mocked SQLAlchemy sessions — no live DB required.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from sqlalchemy.exc import IntegrityError

from gateway.governance.knowledge_limits import MAX_DOC_BYTES, check_doc_size, check_org_storage
from gateway.governance.plan_limits import PLAN_TIERS
from gateway.models.knowledge import (
    KnowledgeCategory,
    KnowledgeDoc,
    KnowledgeDocCreate,
    KnowledgeScope,
    KnowledgeStatus,
)
from gateway.store.knowledge import (
    KnowledgeDuplicate,
    KnowledgeNotFound,
    KnowledgeOrgQuotaExceeded,
    KnowledgeSizeExceeded,
    KnowledgeStateConflict,
    _row_to_doc,
    approve_knowledge_doc,
    archive_knowledge_doc,
    get_knowledge_usage,
    increment_knowledge_view,
    insert_knowledge_doc,
    upsert_knowledge_doc,
)


def _make_doc_row(
    *,
    doc_id: str | None = None,
    org_id: str = "test-org",
    scope: str = "org",
    scope_ref: str | None = None,
    category: str = "conventions",
    title: str = "test-doc",
    body: str = "hello world",
    status: str = "active",
    bytes_val: int | None = None,
    view_count: int = 0,
) -> MagicMock:
    row = MagicMock()
    row.id = doc_id or str(uuid.uuid4())
    row.org_id = org_id
    row.scope = scope
    row.scope_ref = scope_ref
    row.category = category
    row.title = title
    row.body = body
    row.status = status
    row.bytes = bytes_val if bytes_val is not None else len(body.encode("utf-8"))
    row.view_count = view_count
    row.created_at = time.time()
    row.updated_at = time.time()
    row.created_by = None
    row.updated_by = None
    row.proposed_by_agent = None
    return row


def _make_limits(storage_mb: int = 0, history_versions: int = 5):
    limits = MagicMock()
    limits.knowledge_storage_mb = storage_mb
    limits.knowledge_history_versions = history_versions
    return limits


def _make_settings(override: int | None = None):
    settings = MagicMock()
    settings.knowledge_history_versions_override = override
    return settings


class TestKnowledgeGovernance:
    """Tests for governance helpers — no DB required."""

    def test_check_doc_size_passes_under_limit(self):
        check_doc_size(MAX_DOC_BYTES - 1)  # No exception

    def test_check_doc_size_passes_at_limit(self):
        check_doc_size(MAX_DOC_BYTES)  # No exception at exactly the limit

    def test_check_doc_size_raises_above_limit(self):
        with pytest.raises(KnowledgeSizeExceeded):
            check_doc_size(MAX_DOC_BYTES + 1)

    def test_check_org_storage_unlimited_no_op(self):
        limits = _make_limits(storage_mb=0)
        check_org_storage(1_000_000, 5_000_000, 0, limits)  # No exception

    def test_check_org_storage_within_cap(self):
        limits = _make_limits(storage_mb=1)  # 1 MB
        check_org_storage(500_000, 400_000, 0, limits)  # 900 KB < 1 MB

    def test_check_org_storage_raises_over_cap(self):
        limits = _make_limits(storage_mb=1)  # 1 MB
        with pytest.raises(KnowledgeOrgQuotaExceeded):
            check_org_storage(900_000, 200_000, 0, limits)  # 1.1 MB > 1 MB

    def test_check_org_storage_accounts_for_old_bytes(self):
        limits = _make_limits(storage_mb=2)  # 2 MB cap
        # current=1.5MB, replacing 800KB with 900KB: projected = 1.5MB - 800KB + 900KB = ~1.6MB < 2MB
        check_org_storage(1_500_000, 900_000, 800_000, limits)  # within cap — no exception


class TestDocSizeCap:
    def test_doc_size_cap_raises_KnowledgeSizeExceeded(self):
        with pytest.raises(KnowledgeSizeExceeded):
            check_doc_size(MAX_DOC_BYTES + 1)


class TestOrgStorageCap:
    def test_org_storage_cap_raises_KnowledgeOrgQuotaExceeded(self):
        limits = _make_limits(storage_mb=1)
        with pytest.raises(KnowledgeOrgQuotaExceeded):
            check_org_storage(1_000_000, 500_000, 0, limits)


class TestRowToDoc:
    def test_row_to_doc_with_body(self):
        row = _make_doc_row(body="some content")
        doc = _row_to_doc(row, include_body=True)
        assert doc.body == "some content"
        assert doc.title == "test-doc"
        assert doc.scope.value == "org"

    def test_row_to_doc_without_body(self):
        row = _make_doc_row(body="some content")
        doc = _row_to_doc(row, include_body=False)
        assert doc.body is None


class TestApproveKnowledgeDoc:
    @pytest.mark.asyncio
    async def test_approve_pending_to_active(self):
        session = AsyncMock()
        row = _make_doc_row(status="pending")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = row
        session.execute = AsyncMock(return_value=result_mock)
        session.commit = AsyncMock()
        session.refresh = AsyncMock()

        doc = await approve_knowledge_doc(session, org_id="test-org", doc_id=row.id, user_id="user1")
        assert row.status == "active"

    @pytest.mark.asyncio
    async def test_approve_not_found_raises_KnowledgeNotFound(self):
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(KnowledgeNotFound):
            await approve_knowledge_doc(session, org_id="test-org", doc_id="missing-id", user_id="user1")

    @pytest.mark.asyncio
    async def test_approve_active_doc_raises_KnowledgeStateConflict(self):
        session = AsyncMock()
        row = _make_doc_row(status="active")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = row
        session.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(KnowledgeStateConflict):
            await approve_knowledge_doc(session, org_id="test-org", doc_id=row.id, user_id="user1")


class TestArchiveKnowledgeDoc:
    @pytest.mark.asyncio
    async def test_archive_returns_true_on_found(self):
        session = AsyncMock()
        row = _make_doc_row(status="active")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = row
        session.execute = AsyncMock(return_value=result_mock)
        session.commit = AsyncMock()

        result = await archive_knowledge_doc(session, org_id="test-org", doc_id=row.id)
        assert result is True
        assert row.status == "archived"

    @pytest.mark.asyncio
    async def test_archive_returns_false_when_not_found(self):
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        result = await archive_knowledge_doc(session, org_id="test-org", doc_id="missing")
        assert result is False


class TestGetKnowledgeUsage:
    @pytest.mark.asyncio
    async def test_archive_excludes_from_usage(self):
        """get_knowledge_usage only counts active docs."""
        session = AsyncMock()
        # Simulate 2 active docs, 500 bytes total
        result_mock = MagicMock()
        result_mock.one.return_value = (2, 500)
        session.execute = AsyncMock(return_value=result_mock)

        limits = _make_limits(storage_mb=50)
        usage = await get_knowledge_usage(session, org_id="test-org", limits=limits)
        assert usage.active_docs == 2
        assert usage.active_bytes == 500
        assert usage.storage_limit_mb == 50
        assert usage.storage_limit_bytes == 50 * 1024 * 1024

    @pytest.mark.asyncio
    async def test_usage_unlimited_storage(self):
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.one.return_value = (0, 0)
        session.execute = AsyncMock(return_value=result_mock)

        limits = _make_limits(storage_mb=0)
        usage = await get_knowledge_usage(session, org_id="test-org", limits=limits)
        assert usage.storage_limit_bytes == 0
        assert usage.storage_limit_mb == 0


class TestIncrementKnowledgeView:
    @pytest.mark.asyncio
    async def test_view_count_increment_swallows_errors(self):
        """increment_knowledge_view is best-effort; errors must not propagate."""
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=Exception("DB error"))
        # Should not raise
        await increment_knowledge_view(session, org_id="test-org", doc_id="some-id")

    @pytest.mark.asyncio
    async def test_view_count_increments_on_success(self):
        session = AsyncMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        await increment_knowledge_view(session, org_id="test-org", doc_id="some-id")
        session.execute.assert_awaited_once()


class TestPlanLimitsTiersUpdated:
    """Verify all 5 tier literals have the new knowledge fields."""

    def test_all_tiers_have_knowledge_storage_mb(self):
        for tier_name, limits in PLAN_TIERS.items():
            assert hasattr(limits, "knowledge_storage_mb"), f"{tier_name} missing knowledge_storage_mb"
            assert isinstance(limits.knowledge_storage_mb, int)

    def test_all_tiers_have_knowledge_history_versions(self):
        for tier_name, limits in PLAN_TIERS.items():
            assert hasattr(limits, "knowledge_history_versions"), f"{tier_name} missing knowledge_history_versions"
            assert isinstance(limits.knowledge_history_versions, int)

    def test_free_tier_storage_mb(self):
        assert PLAN_TIERS["free"].knowledge_storage_mb == 50

    def test_unlimited_tier_storage_mb(self):
        assert PLAN_TIERS["unlimited"].knowledge_storage_mb == 0

    def test_unlimited_tier_history_versions(self):
        assert PLAN_TIERS["unlimited"].knowledge_history_versions == 100


class TestKnowledgeDocCreateValidation:
    def test_valid_org_conventions(self):
        doc = KnowledgeDocCreate(
            scope=KnowledgeScope.org,
            scope_ref=None,
            category=KnowledgeCategory.conventions,
            title="my-conventions",
            body="content",
        )
        assert doc.title == "my-conventions"

    def test_invalid_slug_title_rejected(self):
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            KnowledgeDocCreate(
                scope=KnowledgeScope.org,
                scope_ref=None,
                category=KnowledgeCategory.conventions,
                title="Invalid Title!",
                body="content",
            )

    def test_wrong_category_for_scope_rejected(self):
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            KnowledgeDocCreate(
                scope=KnowledgeScope.org,
                scope_ref=None,
                category=KnowledgeCategory.quirks,  # quirks only for connection
                title="wrong-cat",
                body="content",
            )

    def test_scope_ref_required_for_project(self):
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            KnowledgeDocCreate(
                scope=KnowledgeScope.project,
                scope_ref=None,
                category=KnowledgeCategory.conventions,
                title="my-doc",
                body="content",
            )

    def test_scope_ref_must_be_none_for_org(self):
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            KnowledgeDocCreate(
                scope=KnowledgeScope.org,
                scope_ref="some-ref",
                category=KnowledgeCategory.conventions,
                title="my-doc",
                body="content",
            )


class TestEffectiveHistoryVersions:
    def test_override_takes_precedence(self):
        from gateway.governance.knowledge_limits import effective_history_versions

        limits = _make_limits(history_versions=5)
        settings = _make_settings(override=0)
        assert effective_history_versions(limits, settings) == 0

    def test_plan_default_used_when_no_override(self):
        from gateway.governance.knowledge_limits import effective_history_versions

        limits = _make_limits(history_versions=25)
        settings = _make_settings(override=None)
        assert effective_history_versions(limits, settings) == 25


class TestGatewaySettingsKnowledgeOverride:
    def test_none_allowed(self):
        from gateway.models.settings import GatewaySettings

        s = GatewaySettings(knowledge_history_versions_override=None)
        assert s.knowledge_history_versions_override is None

    def test_zero_allowed(self):
        from gateway.models.settings import GatewaySettings

        s = GatewaySettings(knowledge_history_versions_override=0)
        assert s.knowledge_history_versions_override == 0

    def test_positive_int_allowed(self):
        from gateway.models.settings import GatewaySettings

        s = GatewaySettings(knowledge_history_versions_override=10)
        assert s.knowledge_history_versions_override == 10

    def test_negative_rejected(self):
        import pydantic

        from gateway.models.settings import GatewaySettings

        with pytest.raises(pydantic.ValidationError):
            GatewaySettings(knowledge_history_versions_override=-1)

    def test_string_rejected(self):
        """Non-int types like strings must be rejected."""
        import pydantic

        from gateway.models.settings import GatewaySettings

        with pytest.raises(pydantic.ValidationError):
            GatewaySettings(knowledge_history_versions_override="not-an-int")  # type: ignore[arg-type]


def _make_insert_session(existing_bytes: int = 0) -> AsyncMock:
    """Build a session mock suitable for insert_knowledge_doc."""
    session = AsyncMock()
    row = MagicMock()
    row.id = str(uuid.uuid4())
    row.org_id = "test-org"
    row.scope = "org"
    row.scope_ref = None
    row.category = "conventions"
    row.title = "test-doc"
    row.body = "content"
    row.status = "active"
    row.bytes = len("content".encode("utf-8"))
    row.view_count = 0
    row.created_at = time.time()
    row.updated_at = time.time()
    row.created_by = None
    row.updated_by = None
    row.proposed_by_agent = None

    scalar_result = MagicMock()
    scalar_result.scalar.return_value = existing_bytes
    session.execute = AsyncMock(return_value=scalar_result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock(side_effect=lambda r: None)

    return session, row


class TestAgentProposalCloudGating:
    """Cloud-mode gating for agent-proposed knowledge docs."""

    @pytest.mark.asyncio
    async def test_agent_proposal_active_in_localhost(self, monkeypatch):
        """In localhost mode, agent-proposed docs are auto-accepted (status=active)."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")

        session, row = _make_insert_session()
        captured_rows: list = []

        def capture_add(r):
            captured_rows.append(r)

        session.add = MagicMock(side_effect=capture_add)

        payload = KnowledgeDocCreate(
            scope=KnowledgeScope.org,
            scope_ref=None,
            category=KnowledgeCategory.conventions,
            title="test-doc",
            body="content",
        )
        limits = _make_limits()
        settings = _make_settings()

        await insert_knowledge_doc(
            session,
            org_id="test-org",
            payload=payload,
            user_id=None,
            agent="propose_knowledge",
            limits=limits,
            settings=settings,
        )
        assert len(captured_rows) == 1
        assert captured_rows[0].status == "active"

    @pytest.mark.asyncio
    async def test_agent_proposal_pending_in_cloud(self, monkeypatch):
        """In cloud mode, agent-proposed docs are forced to pending regardless of category."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")

        session, row = _make_insert_session()
        captured_rows: list = []

        def capture_add(r):
            captured_rows.append(r)

        session.add = MagicMock(side_effect=capture_add)

        payload = KnowledgeDocCreate(
            scope=KnowledgeScope.org,
            scope_ref=None,
            category=KnowledgeCategory.conventions,
            title="test-doc",
            body="content",
        )
        limits = _make_limits()
        settings = _make_settings()

        await insert_knowledge_doc(
            session,
            org_id="test-org",
            payload=payload,
            user_id=None,
            agent="propose_knowledge",
            limits=limits,
            settings=settings,
        )
        assert len(captured_rows) == 1
        assert captured_rows[0].status == "pending"

    @pytest.mark.asyncio
    async def test_agent_upsert_update_pending_in_cloud(self, monkeypatch):
        """In cloud mode, agent update of an active doc forces status=pending."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")

        session = AsyncMock()
        existing = _make_doc_row(status="active", body="old content")

        call_count = 0

        async def execute_side_effect(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # _find_doc_by_key: returns existing row
                result.scalar_one_or_none.return_value = existing
            elif call_count == 2:
                # current_bytes query
                result.scalar.return_value = 100
            else:
                result.scalar_one_or_none.return_value = existing
                result.scalar_one.return_value = existing
            return result

        session.execute = AsyncMock(side_effect=execute_side_effect)
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        payload = KnowledgeDocCreate(
            scope=KnowledgeScope.org,
            scope_ref=None,
            category=KnowledgeCategory.conventions,
            title=existing.title,
            body="new content",
        )
        limits = _make_limits()
        settings = _make_settings()

        await upsert_knowledge_doc(
            session,
            org_id="test-org",
            payload=payload,
            user_id=None,
            agent="propose_knowledge",
            limits=limits,
            settings=settings,
        )
        assert existing.status == "pending"

    @pytest.mark.asyncio
    async def test_human_upsert_update_keeps_active_in_cloud(self, monkeypatch):
        """In cloud mode, human update of an active doc does NOT change status."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")

        session = AsyncMock()
        existing = _make_doc_row(status="active", body="old content")

        call_count = 0

        async def execute_side_effect(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = existing
            elif call_count == 2:
                result.scalar.return_value = 100
            else:
                result.scalar_one_or_none.return_value = existing
                result.scalar_one.return_value = existing
            return result

        session.execute = AsyncMock(side_effect=execute_side_effect)
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        payload = KnowledgeDocCreate(
            scope=KnowledgeScope.org,
            scope_ref=None,
            category=KnowledgeCategory.conventions,
            title=existing.title,
            body="new content",
        )
        limits = _make_limits()
        settings = _make_settings()

        await upsert_knowledge_doc(
            session,
            org_id="test-org",
            payload=payload,
            user_id="admin-user",
            agent=None,
            limits=limits,
            settings=settings,
        )
        assert existing.status == "active"

    @pytest.mark.asyncio
    async def test_upsert_update_revives_archived_doc(self, monkeypatch):
        """Editing an archived doc (local mode) revives it to active, not hidden."""
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)

        session = AsyncMock()
        existing = _make_doc_row(status="archived", body="old content")

        call_count = 0

        async def execute_side_effect(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = existing
            elif call_count == 2:
                result.scalar.return_value = 100
            else:
                result.scalar_one_or_none.return_value = existing
                result.scalar_one.return_value = existing
            return result

        session.execute = AsyncMock(side_effect=execute_side_effect)
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        payload = KnowledgeDocCreate(
            scope=KnowledgeScope.org,
            scope_ref=None,
            category=KnowledgeCategory.conventions,
            title=existing.title,
            body="new content",
        )
        limits = _make_limits()
        settings = _make_settings()

        await upsert_knowledge_doc(
            session,
            org_id="test-org",
            payload=payload,
            user_id=None,
            agent="propose_knowledge",
            limits=limits,
            settings=settings,
        )
        assert existing.status == "active"
        assert existing.body == "new content"
