from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from signalpilot._session.extensions.types import SessionExtension
from signalpilot._types.ids import ConsumerId

if TYPE_CHECKING:
    from signalpilot._messaging.types import KernelMessage
    from signalpilot._session.model import ConnectionState


class SessionConsumer(ABC, SessionExtension):
    """
    Consumer for a session. This extends the SessionExtension interface.

    This allows us to communicate with a session via different
    connection types.
    """

    @property
    @abstractmethod
    def consumer_id(self) -> ConsumerId: ...

    @abstractmethod
    def notify(self, notification: KernelMessage) -> None: ...

    @abstractmethod
    def connection_state(self) -> ConnectionState: ...
