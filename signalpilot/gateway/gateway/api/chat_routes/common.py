"""Shared guards and project-readiness helpers for chat routes."""

from __future__ import annotations

from fastapi import HTTPException

from gateway.standalone_chat.config import enterprise_chat_feature_flags, standalone_chat_enabled
from gateway.standalone_chat.projects import authorize_chat_project, evaluate_project_readiness
from gateway.store import standalone_chat as chat_store

from ..deps import StoreD


def require_enabled() -> None:
    if not standalone_chat_enabled():
        raise HTTPException(status_code=404, detail="Standalone chat is not enabled")


async def owned_conversation_or_404(store: StoreD, conversation_id: str):
    """Return the conversation when the caller owns it; 404 otherwise."""
    conversation = await chat_store.get_owned_conversation(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        conversation_id=conversation_id,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def require_enterprise_feature(name: str) -> None:
    if not getattr(enterprise_chat_feature_flags(), name):
        raise HTTPException(status_code=404, detail="Chat capability is not enabled")


def is_admin(role: str) -> bool:
    return role in {"admin", "org:admin"}


async def readiness_or_error(
    store: StoreD,
    project_id: str,
    *,
    branch_override: str | None = None,
):
    project = await authorize_chat_project(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        project_id=project_id,
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    readiness = await evaluate_project_readiness(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        project=project,
        branch_override=branch_override,
    )
    return project, readiness


def unready_detail(readiness, *, admin: bool) -> dict[str, str | bool]:
    return {
        "code": readiness.code,
        "message": (
            readiness.message
            if admin
            else "This project is not ready for data chat. Ask an administrator to finish setup."
        ),
        "setup_cta": admin,
    }
