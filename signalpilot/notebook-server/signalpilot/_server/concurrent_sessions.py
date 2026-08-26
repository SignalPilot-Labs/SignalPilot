from __future__ import annotations

import os


def allow_concurrent_edit_sessions() -> bool:
    """Whether one notebook server may host multiple editors for one file.

    Cloud runtimes are isolated per user at the pod boundary. Local direct mode
    intentionally shares one notebook server, so its development Compose
    overlay enables this flag to emulate those independent user runtimes with
    distinct kernel session IDs.
    """
    return os.environ.get(
        "SP_ALLOW_CONCURRENT_EDIT_SESSIONS",
        "",
    ).strip().lower() in {"1", "true", "yes", "on"}


def should_reject_edit_connection(
    *,
    has_connected_client: bool,
    kiosk: bool,
    rtc_enabled: bool,
) -> bool:
    """Return whether edit mode must reject a second frontend connection."""
    return (
        has_connected_client
        and not kiosk
        and not rtc_enabled
        and not allow_concurrent_edit_sessions()
    )
