"""Define the shared declarative base and column helpers for gateway tables."""

from __future__ import annotations

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase

TZDateTime = DateTime(timezone=True)


class GatewayBase(DeclarativeBase):
    pass


# TLS material lives only in the encrypted credential extras. These fields are
# stripped before the ssl_config metadata column is written and redacted again on
# read so rows written by earlier releases cannot leak through a response.
SSL_SECRET_FIELDS = ("ca_cert", "client_cert", "client_key")


def strip_ssl_secrets(ssl_config: dict | None) -> dict | None:
    """Return ssl_config with certificate/key material removed."""
    if not ssl_config:
        return ssl_config
    return {k: v for k, v in ssl_config.items() if k not in SSL_SECRET_FIELDS}
