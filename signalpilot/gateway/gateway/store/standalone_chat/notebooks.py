"""Named notebook pointers owned by one chat conversation.

One row per (conversation_id, name). "analysis" is the default notebook;
the legacy pointer columns on the conversation row mirror it for older
readers. The newest write wins.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayChatConversationNotebook

DEFAULT_NOTEBOOK_NAME = "analysis"

# Same slug rule the sandbox tool and the archive route enforce.
NOTEBOOK_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,40}$")


async def upsert_conversation_notebook(
    db: AsyncSession,
    *,
    conversation_id: str,
    name: str,
    gateway_session_id: str,
    kernel_session_id: str,
    notebook_path: str,
) -> GatewayChatConversationNotebook:
    """Insert or refresh the pointer for one named notebook. Latest wins."""
    values = {
        "gateway_session_id": gateway_session_id,
        "kernel_session_id": kernel_session_id,
        "notebook_path": notebook_path,
        "updated_at": datetime.now(UTC),
    }
    existing = (
        await db.execute(
            select(GatewayChatConversationNotebook).where(
                GatewayChatConversationNotebook.conversation_id == conversation_id,
                GatewayChatConversationNotebook.name == name,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        for field, value in values.items():
            setattr(existing, field, value)
        await db.commit()
        await db.refresh(existing)
        return existing
    row = GatewayChatConversationNotebook(
        conversation_id=conversation_id,
        name=name,
        **values,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent writer inserted the same name first. Update its row.
        await db.rollback()
        await db.execute(
            update(GatewayChatConversationNotebook)
            .where(
                GatewayChatConversationNotebook.conversation_id == conversation_id,
                GatewayChatConversationNotebook.name == name,
            )
            .values(**values)
        )
        await db.commit()
        return (
            await db.execute(
                select(GatewayChatConversationNotebook).where(
                    GatewayChatConversationNotebook.conversation_id == conversation_id,
                    GatewayChatConversationNotebook.name == name,
                )
            )
        ).scalar_one()
    await db.refresh(row)
    return row


async def list_conversation_notebooks(
    db: AsyncSession,
    *,
    conversation_id: str,
) -> list[GatewayChatConversationNotebook]:
    """Return the conversation's notebooks: "analysis" first, then by name."""
    rows = (
        (
            await db.execute(
                select(GatewayChatConversationNotebook)
                .where(
                    GatewayChatConversationNotebook.conversation_id == conversation_id
                )
                .order_by(GatewayChatConversationNotebook.name)
            )
        )
        .scalars()
        .all()
    )
    return sorted(rows, key=lambda row: (row.name != DEFAULT_NOTEBOOK_NAME, row.name))
