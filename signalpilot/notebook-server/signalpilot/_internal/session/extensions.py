"""Internal API for session extensions."""

from signalpilot._session.extensions.extensions import (
    CachingExtension,
    HeartbeatExtension,
    LoggingExtension,
    NotificationListenerExtension,
    QueueExtension,
    ReplayExtension,
    SessionViewExtension,
)
from signalpilot._session.extensions.types import (
    EventAwareExtension,
    ExtensionRegistry,
    SessionExtension,
)

__all__ = [
    "CachingExtension",
    "EventAwareExtension",
    "ExtensionRegistry",
    "HeartbeatExtension",
    "LoggingExtension",
    "NotificationListenerExtension",
    "QueueExtension",
    "ReplayExtension",
    "SessionExtension",
    "SessionViewExtension",
]
