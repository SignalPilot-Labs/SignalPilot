"""Knowledge Base governance helpers: size cap, org quota, history version resolution."""

from __future__ import annotations

MAX_DOC_BYTES = 50 * 1024 * 1024  # 50 MiB hard cap, tier-independent


def effective_history_versions(limits, settings) -> int:
    """Return the number of history versions to keep (0 = unlimited).

    settings.knowledge_history_versions_override wins when not None.
    """
    override = getattr(settings, "knowledge_history_versions_override", None)
    if override is not None:
        return override
    return limits.knowledge_history_versions


def check_doc_size(body_bytes: int) -> None:
    """Raise KnowledgeSizeExceeded if body_bytes exceeds the hard cap."""
    # Import here to avoid circular dep: governance <- store
    from gateway.store.knowledge import KnowledgeSizeExceeded

    if body_bytes > MAX_DOC_BYTES:
        raise KnowledgeSizeExceeded(
            f"Document body is {body_bytes} bytes, exceeds maximum of {MAX_DOC_BYTES} bytes (50 MiB)"
        )


def check_org_storage(current_bytes: int, new_doc_bytes: int, old_doc_bytes: int, limits) -> None:
    """Raise KnowledgeOrgQuotaExceeded if adding new_doc_bytes would exceed the org cap.

    No-op when limits.knowledge_storage_mb == 0 (unlimited).
    """
    if limits.knowledge_storage_mb == 0:
        return

    cap_bytes = limits.knowledge_storage_mb * 1024 * 1024
    projected = current_bytes - old_doc_bytes + new_doc_bytes
    if projected > cap_bytes:
        from gateway.store.knowledge import KnowledgeOrgQuotaExceeded

        raise KnowledgeOrgQuotaExceeded(
            f"Adding this document would exceed the org's knowledge storage quota "
            f"({limits.knowledge_storage_mb} MiB). Current active storage: "
            f"{current_bytes / (1024 * 1024):.1f} MiB."
        )
