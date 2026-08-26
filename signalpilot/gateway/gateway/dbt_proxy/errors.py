"""Error hierarchy for the dbt-proxy sub-package."""

from __future__ import annotations


class DbtProxyError(Exception):
    """Base class for all dbt-proxy errors."""

    error_code: str = "dbt_proxy_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AuthFailed(DbtProxyError):
    """Authentication failed — wrong token, wrong user format, or token not found."""

    error_code = "auth_failed"


class RunTokenExpired(DbtProxyError):
    """The run-token TTL has elapsed."""

    error_code = "run_token_expired"


class RunTokenAlreadyExists(DbtProxyError):
    """A token for this run_id has already been minted in this process."""

    error_code = "run_token_already_exists"


class NonPostgresConnector(DbtProxyError):
    """The connector referenced by the token is not Postgres-typed.

    The dbt-proxy only supports Postgres-wire (SQLSTATE 0A000).
    """

    error_code = "non_postgres_connector"


class UnsupportedMessage(DbtProxyError):
    """A pg-wire message type arrived that the proxy does not handle."""

    error_code = "unsupported_message"


class ProxyDisabled(DbtProxyError):
    """sp_dbt_proxy_enabled=false — mint route returns 503."""

    error_code = "proxy_disabled"


__all__ = [
    "DbtProxyError",
    "AuthFailed",
    "RunTokenExpired",
    "RunTokenAlreadyExists",
    "NonPostgresConnector",
    "UnsupportedMessage",
    "ProxyDisabled",
]
