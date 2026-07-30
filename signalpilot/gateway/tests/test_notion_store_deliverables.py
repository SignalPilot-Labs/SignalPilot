from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.db.models import GatewayBase, NotionDeliverable, NotionDeliverableUpdate
from gateway.store import notion as notion_store


@asynccontextmanager
async def _session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(GatewayBase.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


def _deliverable() -> NotionDeliverable:
    return NotionDeliverable(
        id="deliverable-1",
        org_id="org-1",
        installation_id="install-1",
        page_id="page-1",
        request_id="notion-req-1",
        report_id="report-1",
        kind="dashboard",
        embed_block_id="embed-block-1",
        file_upload_id="file-original",
        status="active",
    )


async def _create_update(session: AsyncSession, mode: str) -> NotionDeliverableUpdate:
    return await notion_store.create_deliverable_update(
        session,
        deliverable_id="deliverable-1",
        org_id="org-1",
        mode=mode,
        prompt=f"{mode} prompt",
        data_instruction=f"{mode} data",
        render_instruction=f"{mode} render",
        old_file_upload_id="file-original",
    )


@pytest.mark.asyncio
async def test_context_snapshot_and_update_copy_generated_ids_to_deliverable() -> None:
    async with _session() as session:
        deliverable = _deliverable()
        session.add(deliverable)
        await session.commit()

        snapshot = await notion_store.record_deliverable_context_snapshot(
            session,
            deliverable_id="deliverable-1",
            org_id="org-1",
            request_id="notion-req-1",
            base_notebook_code="print('hello')",
        )
        await session.refresh(deliverable)

        assert snapshot.id
        assert deliverable.context_snapshot_id == snapshot.id

        update = await _create_update(session, "edit_existing")
        await session.refresh(deliverable)

        assert update.id
        assert deliverable.latest_update_id == update.id
        assert deliverable.status == "updating"


@pytest.mark.asyncio
async def test_stale_success_does_not_overwrite_current_deliverable_pointer() -> None:
    async with _session() as session:
        deliverable = _deliverable()
        session.add(deliverable)
        await session.commit()

        old_update = await _create_update(session, "edit_existing")
        new_update = await _create_update(session, "refresh_data")

        await notion_store.mark_deliverable_update_succeeded(
            session,
            update_id=old_update.id,
            deliverable_id="deliverable-1",
            new_file_upload_id="file-old-result",
            html_bytes=123,
        )
        await session.refresh(deliverable)

        assert deliverable.latest_update_id == new_update.id
        assert deliverable.file_upload_id == "file-original"
        assert deliverable.latest_file_upload_id is None
        assert deliverable.latest_html_bytes is None
        assert deliverable.status == "updating"
        assert old_update.status == "succeeded"

        await notion_store.mark_deliverable_update_succeeded(
            session,
            update_id=new_update.id,
            deliverable_id="deliverable-1",
            new_file_upload_id="file-new-result",
            html_bytes=456,
        )
        await session.refresh(deliverable)

        assert deliverable.latest_update_id == new_update.id
        assert deliverable.file_upload_id == "file-new-result"
        assert deliverable.latest_file_upload_id == "file-new-result"
        assert deliverable.latest_html_bytes == 456
        assert deliverable.status == "active"


@pytest.mark.asyncio
async def test_stale_failure_does_not_mark_current_deliverable_failed() -> None:
    async with _session() as session:
        deliverable = _deliverable()
        session.add(deliverable)
        await session.commit()

        old_update = await _create_update(session, "edit_existing")
        new_update = await _create_update(session, "refresh_data")

        await notion_store.mark_deliverable_update_failed(
            session,
            update_id=old_update.id,
            deliverable_id="deliverable-1",
            error="old failed",
        )
        await session.refresh(deliverable)

        assert deliverable.latest_update_id == new_update.id
        assert deliverable.status == "updating"
        assert deliverable.error is None
        assert old_update.status == "failed"
        assert old_update.error == "old failed"

        await notion_store.mark_deliverable_update_failed(
            session,
            update_id=new_update.id,
            deliverable_id="deliverable-1",
            error="new failed",
        )
        await session.refresh(deliverable)

        assert deliverable.latest_update_id == new_update.id
        assert deliverable.status == "failed"
        assert deliverable.error == "new failed"
