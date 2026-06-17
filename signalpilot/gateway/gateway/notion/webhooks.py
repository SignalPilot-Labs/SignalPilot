"""Tenant routing and validation for Notion public-integration webhooks."""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import NotionInstallation, NotionInstallationConfig
from gateway.notion import client as notion_client
from gateway.store import notion as notion_store

logger = logging.getLogger(__name__)


class NotionWebhookError(Exception):
    """Base class for expected Notion webhook processing errors."""


class InvalidNotionSignature(NotionWebhookError):
    """Raised when the Notion HMAC signature does not match."""


class AmbiguousNotionInstallation(NotionWebhookError):
    """Raised when an event could route to more than one active installation."""


@dataclass(frozen=True)
class RoutedNotionInstallation:
    installation: NotionInstallation
    config: NotionInstallationConfig
    access_token: str


def verify_notion_signature(raw_body: bytes, signature: str | None, verification_token: str) -> None:
    """Validate Notion's X-Notion-Signature header."""
    if not signature:
        raise InvalidNotionSignature("Missing X-Notion-Signature")
    expected = "sha256=" + hmac.new(verification_token.encode(), raw_body, hashlib.sha256).hexdigest()
    if len(signature) != len(expected) or not hmac.compare_digest(signature, expected):
        raise InvalidNotionSignature("Invalid Notion signature")


def is_bot_authored(payload: dict) -> bool:
    return any(author.get("type") == "bot" for author in payload.get("authors") or [])


def _ownership_matches(installation: NotionInstallation, payload: dict) -> bool:
    integration_id = payload.get("integration_id")
    if integration_id and notion_client.normalize_id(str(integration_id)) == notion_client.normalize_id(installation.bot_id):
        return True

    accessible_by = payload.get("accessible_by") or []
    for owner in accessible_by:
        owner_id = owner.get("id")
        if owner_id and notion_client.normalize_id(str(owner_id)) == notion_client.normalize_id(installation.bot_id):
            return True

    return False


async def route_comment_event(
    session: AsyncSession,
    payload: dict,
) -> RoutedNotionInstallation | None:
    """Resolve a comment.created event to exactly one active Notion install."""
    workspace_id = payload.get("workspace_id")
    page_id = (payload.get("data") or {}).get("page_id")
    if not workspace_id or not page_id:
        logger.info(
            "Notion webhook route skipped: workspace_id=%s page_id=%s reason=missing_workspace_or_page",
            workspace_id,
            page_id,
        )
        return None

    candidates = await notion_store.list_active_installation_records_for_workspace(session, str(workspace_id))
    if not candidates:
        logger.info(
            "Notion webhook route skipped: workspace_id=%s page_id=%s reason=no_active_installations",
            workspace_id,
            page_id,
        )
    matched: list[RoutedNotionInstallation] = []
    for installation, config, access_token in candidates:
        if config is None or not config.enabled:
            logger.info(
                "Notion webhook route skipped candidate: workspace_id=%s page_id=%s installation_id=%s "
                "org_id=%s reason=%s",
                workspace_id,
                page_id,
                installation.id,
                installation.org_id,
                "installation_not_provisioned" if config is None else "installation_disabled",
            )
            continue
        if not _ownership_matches(installation, payload):
            logger.info(
                "Notion webhook route skipped candidate: workspace_id=%s page_id=%s installation_id=%s "
                "org_id=%s reason=ownership_mismatch",
                workspace_id,
                page_id,
                installation.id,
                installation.org_id,
            )
            continue
        belongs = await notion_client.page_belongs_to_scope(
            access_token,
            str(page_id),
            parent_page_id=config.parent_page_id,
            trigger_page_id=config.trigger_page_id,
            requests_data_source_id=config.requests_data_source_id,
            requests_database_page_id=config.requests_database_page_id,
        )
        if belongs:
            matched.append(RoutedNotionInstallation(installation, config, access_token))
        else:
            logger.info(
                "Notion webhook route skipped candidate: workspace_id=%s page_id=%s installation_id=%s "
                "org_id=%s reason=page_outside_scope",
                workspace_id,
                page_id,
                installation.id,
                installation.org_id,
            )

    if len(matched) > 1:
        matched_by_mention = await _filter_by_trigger_page_mention(matched, payload)
        if len(matched_by_mention) == 1:
            return matched_by_mention[0]
        if len(matched_by_mention) > 1:
            raise AmbiguousNotionInstallation(
                f"Notion event mentioned trigger pages for {len(matched_by_mention)} active installations"
            )
        raise AmbiguousNotionInstallation(f"Notion event matched {len(matched)} active installations")
    return matched[0] if matched else None


async def _filter_by_trigger_page_mention(
    candidates: list[RoutedNotionInstallation],
    payload: dict,
) -> list[RoutedNotionInstallation]:
    comment_id = (payload.get("entity") or {}).get("id")
    page_id = (payload.get("data") or {}).get("page_id")
    parent_block_id = ((payload.get("data") or {}).get("parent") or {}).get("id")
    if not comment_id or not page_id:
        return []

    result: list[RoutedNotionInstallation] = []
    for candidate in candidates:
        block_id = parent_block_id or page_id
        comments = await notion_client.list_comments(candidate.access_token, str(block_id))
        comment = next((item for item in comments if item.get("id") == comment_id), None)
        if comment is None:
            comment = await notion_client.retrieve_comment(candidate.access_token, str(comment_id))
        if notion_client.comment_has_page_mention(comment, candidate.config.trigger_page_id or ""):
            result.append(candidate)
    return result
