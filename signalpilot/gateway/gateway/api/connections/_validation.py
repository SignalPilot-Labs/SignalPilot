from __future__ import annotations

from gateway.models import ConnectionCreate
from gateway.network import validate_cloud_warehouse_params, validate_connection_params


def _validate_connection_params(conn: ConnectionCreate) -> list[str]:
    """Validate connection parameters before persisting. Returns list of error messages."""
    from gateway.runtime.mode import is_cloud_mode

    errors: list[str] = []

    # Cloud mode: reject file-based local database connections
    if is_cloud_mode() and conn.db_type in ("duckdb", "sqlite"):
        db_path = conn.connection_string or conn.database or ""
        if db_path and db_path != ":memory:" and not db_path.startswith("md:"):
            errors.append(f"File-based {conn.db_type} connections are not available in cloud mode")
            return errors

    if conn.connection_string:
        if conn.db_type in ("duckdb", "sqlite"):
            pass  # Local file paths are sandboxed — no DATA_DIR restriction needed
        else:
            try:
                validate_connection_params(conn.host, conn.port, conn.db_type, conn.connection_string)
            except ValueError as e:
                errors.append(str(e))
        return errors

    try:
        validate_connection_params(conn.host, conn.port, conn.db_type, None)
    except ValueError as e:
        errors.append(str(e))

    db = conn.db_type

    if db in ("postgres", "mysql", "redshift", "clickhouse", "mssql"):
        if not conn.host:
            errors.append(f"{db} requires a host")
        if not conn.username:
            errors.append(f"{db} requires a username")
        if not conn.database:
            errors.append(f"{db} requires a database")

    if db == "trino":
        if not conn.host:
            errors.append("Trino requires a host")
        if not conn.catalog:
            errors.append("Trino requires a catalog")

    if db == "snowflake":
        if not conn.account:
            errors.append("Snowflake requires an account identifier")
        if not conn.username:
            errors.append("Snowflake requires a username")
        # SSRF: validate account identifier format
        try:
            validate_cloud_warehouse_params("snowflake", account=conn.account)
        except ValueError as e:
            errors.append(str(e))

    if db == "bigquery":
        if not conn.project:
            errors.append("BigQuery requires a GCP project ID")
        if not conn.credentials_json:
            errors.append("BigQuery requires service account credentials JSON")
        # SSRF: validate project ID format
        try:
            validate_cloud_warehouse_params("bigquery", project_id=conn.project)
        except ValueError as e:
            errors.append(str(e))

    if db == "databricks":
        if not conn.host:
            errors.append("Databricks requires a server hostname")
        if not conn.http_path:
            errors.append("Databricks requires an HTTP path (SQL warehouse endpoint)")
        if not conn.access_token:
            errors.append("Databricks requires a personal access token")
        # SSRF: validate Databricks host format
        try:
            validate_cloud_warehouse_params("databricks", host=conn.host)
        except ValueError as e:
            errors.append(str(e))

    if db in ("duckdb", "sqlite"):
        if not conn.database:
            errors.append(f"{db} requires a database file path (or :memory:)")

    if conn.ssh_tunnel and conn.ssh_tunnel.enabled:
        if not conn.ssh_tunnel.host:
            errors.append("SSH tunnel requires a bastion host")
        if not conn.ssh_tunnel.username:
            errors.append("SSH tunnel requires a username")
        if conn.ssh_tunnel.auth_method == "key" and not conn.ssh_tunnel.private_key:
            errors.append("SSH tunnel with key auth requires a private key")
        if conn.ssh_tunnel.auth_method == "password" and not conn.ssh_tunnel.password:
            errors.append("SSH tunnel with password auth requires a password")
        if db not in ("postgres", "mysql", "redshift", "clickhouse", "mssql", "trino"):
            errors.append(f"SSH tunnels are not supported for {db} (only host:port databases)")

    return errors
