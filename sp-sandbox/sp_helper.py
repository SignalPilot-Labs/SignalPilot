"""Backward-compat shim — real client lives in the sp package."""

from sp._client import GatewayClient as SignalPilotClient

__all__ = ["SignalPilotClient"]
