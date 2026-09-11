"""Account-wide admission for MCP-origin Chats, including browser follow-ups."""

import hashlib
import os

from sqlalchemy import func, select, text
from gateway.db.models import GatewayChatConversation, GatewayChatRun
from gateway.standalone_chat.domain import NONTERMINAL_RUN_STATUSES


class AgentCapacityError(ValueError, RuntimeError):
    pass


async def lock_agent_account(db, org_id):
    transaction = db.sync_session.get_transaction()
    marker = db.info.get("mcp_admission_lock")
    if transaction is not None and marker == (transaction, org_id):
        return
    if db.bind.dialect.name == "postgresql":
        key = int.from_bytes(hashlib.sha256(("mcp-agent:" + org_id).encode()).digest()[:8], "big", signed=True)
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    elif db.bind.dialect.name == "sqlite":
        await db.execute(text("BEGIN IMMEDIATE"))
    else:
        raise AgentCapacityError("Agent admission requires PostgreSQL")
    db.info["mcp_admission_lock"] = (db.sync_session.get_transaction(), org_id)


async def check_agent_capacity(db, org_id):
    maximum = min(2, max(1, int(os.getenv("SP_AGENT_MAX_CONCURRENT_PER_ORG", "2"))))
    count = await db.scalar(
        select(func.count())
        .select_from(GatewayChatRun)
        .join(GatewayChatConversation, GatewayChatConversation.id == GatewayChatRun.conversation_id)
        .where(
            GatewayChatRun.org_id == org_id,
            GatewayChatConversation.org_id == org_id,
            GatewayChatConversation.origin == "mcp_agent",
            GatewayChatRun.status.in_(NONTERMINAL_RUN_STATUSES),
        )
    )
    if count >= maximum:
        raise AgentCapacityError("Account agent concurrency limit reached; retry when an active agent finishes")


async def admit_existing_agent_chat(db, *, org_id, user_id, conversation_id=None, run_id=None):
    query = select(GatewayChatConversation.origin).where(
        GatewayChatConversation.org_id == org_id, GatewayChatConversation.user_id == user_id
    )
    if run_id is not None:
        query = query.join(GatewayChatRun, GatewayChatRun.conversation_id == GatewayChatConversation.id).where(
            GatewayChatRun.id == run_id, GatewayChatRun.org_id == org_id, GatewayChatRun.user_id == user_id
        )
    else:
        query = query.where(GatewayChatConversation.id == conversation_id)
    if await db.scalar(query) == "mcp_agent":
        # Always take the account lock before a conversation/run row lock.
        await lock_agent_account(db, org_id)
        await check_agent_capacity(db, org_id)
