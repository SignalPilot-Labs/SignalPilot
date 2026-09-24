"""Map a SignalPilot connection to Tableau connection attributes and a live .tds.

The password comes from the stored connection string (parsed with the shared
``parse_connection_url``) and only ever goes to Tableau inside a publish or
credential-update request. It is excluded from ``repr`` and from
``public_dict``, and it never reaches a log line.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from gateway.network import parse_connection_url

from .client import TableauError

# SignalPilot db_type -> Tableau connection class.
TABLEAU_CLASSES: dict[str, str] = {
    "mssql": "sqlserver",
    "postgres": "postgres",
    "redshift": "redshift",
    "xata": "postgres",  # Xata branches are Postgres endpoints
}
DEFAULT_SCHEMAS: dict[str, str] = {"sqlserver": "dbo", "postgres": "public", "redshift": "public"}
DEFAULT_PORTS: dict[str, int] = {"sqlserver": 1433, "postgres": 5432, "redshift": 5439}


@dataclass(frozen=True)
class ConnectionTarget:
    """Tableau-facing view of one SignalPilot connection."""

    name: str
    db_type: str
    tableau_class: str | None
    host: str
    port: int | None
    database: str
    username: str
    ssl: bool
    password: str = field(default="", repr=False)

    def public_dict(self) -> dict[str, Any]:
        """Connection attributes for the agent. Never includes the password."""
        out: dict[str, Any] = {
            "name": self.name,
            "db_type": self.db_type,
            "supported": self.tableau_class is not None,
            "tableau_class": self.tableau_class,
            "server": self.host,
            "port": self.port,
            "database": self.database,
            "username": self.username,
        }
        if self.tableau_class == "sqlserver":
            out["sql_server_address"] = f"{self.host},{self.port}"
        return out

    def require_supported(self) -> str:
        if not self.tableau_class:
            raise TableauError(
                f"Tableau publishing for '{self.db_type}' connections is not supported yet "
                "(supported: SQL Server, Postgres, Redshift)",
                status_code=400,
            )
        return self.tableau_class

    def matches_host(self, server_address: str | None) -> bool:
        """True when a Tableau serverAddress (``host``, ``host,port`` or ``host:port``) is this host."""
        address = (server_address or "").strip().lower()
        if not address or not self.host:
            return False
        host = address.split(",", 1)[0]
        if host.count(":") == 1:
            host = host.split(":", 1)[0]
        return host == self.host.strip().lower()


def _db_type(info: Any) -> str:
    value = getattr(info, "db_type", "")
    return str(getattr(value, "value", value) or "")


async def connection_target(store: Any, name: str) -> ConnectionTarget:
    """Build the target for SignalPilot connection ``name`` (404 when unknown)."""
    try:
        info = await store.get_connection(name)
    except ValueError as exc:
        raise TableauError(str(exc), status_code=403) from None
    if info is None:
        raise TableauError(f"Connection '{name}' not found", status_code=404)
    db_type = _db_type(info)
    tableau_class = TABLEAU_CLASSES.get(db_type)
    parsed: dict[str, Any] = {}
    dsn = await store.get_connection_string(name)
    if dsn:
        parsed = parse_connection_url(dsn, db_type="postgres" if db_type == "xata" else db_type)
    host = info.host or parsed.get("host") or ""
    port = info.port or parsed.get("port") or (DEFAULT_PORTS.get(tableau_class or "") if tableau_class else None)
    ssl = bool(info.ssl or parsed.get("ssl"))
    return ConnectionTarget(
        name=name,
        db_type=db_type,
        tableau_class=tableau_class,
        host=host,
        port=int(port) if port else None,
        database=info.database or parsed.get("database") or "",
        username=info.username or parsed.get("username") or "",
        ssl=ssl,
        password=str(parsed.get("password") or ""),
    )


def _bracket(identifier: str) -> str:
    return "[" + identifier.replace("]", "]]") + "]"


def _named_connection_attrs(target: ConnectionTarget, tableau_class: str, database: str) -> str:
    port = target.port or DEFAULT_PORTS[tableau_class]
    common = (
        f"dbname={quoteattr(database)} one-time-sql='' port='{port}' "
        f"server={quoteattr(target.host)} username={quoteattr(target.username)}"
    )
    if tableau_class == "sqlserver":
        return f"authentication='sqlserver' class='sqlserver' {common} odbc-native-protocol='yes'"
    sslmode = " sslmode='require'" if target.ssl or tableau_class == "redshift" else ""
    return f"authentication='username-password' class='{tableau_class}' {common}{sslmode}"


def build_tds(
    target: ConnectionTarget,
    *,
    caption: str,
    database: str | None = None,
    schema: str | None = None,
    table: str | None = None,
    sql: str | None = None,
) -> str:
    """A live (no extract) .tds on one table or one custom SQL query of ``target``."""
    tableau_class = target.require_supported()
    if bool(table) == bool(sql):
        raise TableauError("Give exactly one of table or sql", status_code=400)
    db = database or target.database
    if not db:
        raise TableauError("The connection has no default database; pass database", status_code=400)
    conn_name = f"{tableau_class}.{uuid.uuid4().hex[:28]}"
    if table:
        schema_name = schema or DEFAULT_SCHEMAS[tableau_class]
        relation = (
            f"<relation connection='{conn_name}' name={quoteattr(table)} "
            f"table={quoteattr(f'{_bracket(schema_name)}.{_bracket(table)}')} type='table' />"
        )
    else:
        relation = (
            f"<relation connection='{conn_name}' name='Custom SQL Query' type='text'>{escape(sql or '')}</relation>"
        )
    return (
        "<?xml version='1.0' encoding='utf-8' ?>\n"
        f"<datasource formatted-name={quoteattr(caption)} inline='true' source-platform='win' version='18.1' "
        "xmlns:user='http://www.tableausoftware.com/xml/user'>\n"
        "  <connection class='federated'>\n"
        "    <named-connections>\n"
        f"      <named-connection caption={quoteattr(target.host)} name='{conn_name}'>\n"
        f"        <connection {_named_connection_attrs(target, tableau_class, db)} />\n"
        "      </named-connection>\n"
        "    </named-connections>\n"
        f"    {relation}\n"
        "  </connection>\n"
        "</datasource>\n"
    )
