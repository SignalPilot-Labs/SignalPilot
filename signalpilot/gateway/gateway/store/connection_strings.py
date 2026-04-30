"""Connection string builder and credential extras extractor."""

from __future__ import annotations

from urllib.parse import quote as url_quote

from gateway.models import ConnectionCreate, DBType


def _build_connection_string(conn: ConnectionCreate) -> str:
    if conn.db_type == DBType.postgres:
        user = url_quote(conn.username or "", safe="")
        pw = f":{url_quote(conn.password or '', safe='')}" if conn.password else ""
        host = conn.host or "localhost"
        port = conn.port or 5432
        db = conn.database or "postgres"
        ssl_mode = (
            conn.ssl_config.mode if conn.ssl_config and conn.ssl_config.enabled else ("require" if conn.ssl else "")
        )
        ssl_param = f"?sslmode={ssl_mode}" if ssl_mode else ""
        return f"postgresql://{user}{pw}@{host}:{port}/{db}{ssl_param}"
    if conn.db_type == DBType.mysql:
        user = url_quote(conn.username or "", safe="")
        pw = f":{url_quote(conn.password or '', safe='')}" if conn.password else ""
        host = conn.host or "localhost"
        port = conn.port or 3306
        db = conn.database or ""
        return f"mysql+pymysql://{user}{pw}@{host}:{port}/{db}"
    if conn.db_type == DBType.duckdb:
        return conn.database or ":memory:"
    if conn.db_type == DBType.sqlite:
        return conn.database or ":memory:"
    if conn.db_type == DBType.snowflake:
        account = conn.account or ""
        user = url_quote(conn.username or "", safe="")
        pw = f":{url_quote(conn.password or '', safe='')}" if conn.password else ""
        db = conn.database or ""
        schema = conn.schema_name or ""
        path = f"/{db}/{schema}" if schema else f"/{db}" if db else ""
        params = []
        if conn.warehouse:
            params.append(f"warehouse={url_quote(conn.warehouse, safe='')}")
        if conn.role:
            params.append(f"role={url_quote(conn.role, safe='')}")
        query = f"?{'&'.join(params)}" if params else ""
        return f"snowflake://{user}{pw}@{account}{path}{query}"
    if conn.db_type == DBType.bigquery:
        return conn.project or ""
    if conn.db_type == DBType.redshift:
        user = url_quote(conn.username or "", safe="")
        pw = f":{url_quote(conn.password or '', safe='')}" if conn.password else ""
        host = conn.host or "localhost"
        port = conn.port or 5439
        db = conn.database or "dev"
        ssl_param = "?sslmode=require" if conn.ssl else ""
        return f"redshift://{user}{pw}@{host}:{port}/{db}{ssl_param}"
    if conn.db_type == DBType.clickhouse:
        user = url_quote(conn.username or "default", safe="")
        pw = f":{url_quote(conn.password or '', safe='')}" if conn.password else ""
        host = conn.host or "localhost"
        db = conn.database or "default"
        use_http = conn.protocol == "http"
        use_ssl = conn.ssl or (conn.ssl_config and conn.ssl_config.enabled)
        if use_http:
            scheme = "clickhouse+https" if use_ssl else "clickhouse+http"
            port = conn.port or (8443 if use_ssl else 8123)
        else:
            scheme = "clickhouses" if use_ssl else "clickhouse"
            port = conn.port or (9440 if use_ssl else 9000)
        return f"{scheme}://{user}{pw}@{host}:{port}/{db}"
    if conn.db_type == DBType.databricks:
        host = conn.host or ""
        http_path = url_quote(conn.http_path or "", safe="/")
        token = url_quote(conn.access_token or "", safe="")
        params = []
        if conn.catalog:
            params.append(f"catalog={url_quote(conn.catalog, safe='')}")
        if conn.schema_name:
            params.append(f"schema={url_quote(conn.schema_name, safe='')}")
        query = f"?{'&'.join(params)}" if params else ""
        return f"databricks://{token}@{host}/{http_path}{query}"
    if conn.db_type == DBType.mssql:
        user = url_quote(conn.username or "sa", safe="")
        pw = f":{url_quote(conn.password or '', safe='')}" if conn.password else ""
        host = conn.host or "localhost"
        port = conn.port or 1433
        db = conn.database or "master"
        return f"mssql://{user}{pw}@{host}:{port}/{db}"
    if conn.db_type == DBType.trino:
        user = url_quote(conn.username or "trino", safe="")
        pw = f":{url_quote(conn.password or '', safe='')}" if conn.password else ""
        host = conn.host or "localhost"
        port = conn.port or 8080
        catalog = conn.catalog or ""
        schema = conn.schema_name or ""
        path = f"/{catalog}/{schema}" if schema else f"/{catalog}" if catalog else ""
        return f"trino://{user}{pw}@{host}:{port}{path}"
    return ""


def _extract_credential_extras(conn: ConnectionCreate) -> dict:
    extras: dict = {}
    if conn.ssh_tunnel and conn.ssh_tunnel.enabled:
        extras["ssh_tunnel"] = conn.ssh_tunnel.model_dump()
    if conn.ssl_config and conn.ssl_config.enabled:
        extras["ssl_config"] = conn.ssl_config.model_dump()
    if conn.credentials_json:
        extras["credentials_json"] = conn.credentials_json
    if conn.db_type == DBType.bigquery:
        for attr in ("location", "maximum_bytes_billed", "project", "dataset"):
            val = getattr(conn, attr, None)
            if val is not None:
                extras[attr] = val
    if conn.access_token:
        extras["access_token"] = conn.access_token
    # NOTE: password is intentionally excluded from extras — it is already
    # embedded in the encrypted connection string.  Storing it twice doubles
    # the blast radius of a credential leak.  Consumers that need the raw
    # password (e.g. dbt profiles.yml generation) should extract it from
    # the connection string at use-time.
    if conn.db_type == DBType.snowflake:
        for attr in ("account", "warehouse", "schema_name", "role", "username"):
            extras[attr] = getattr(conn, attr, None)
        if conn.private_key:
            extras["private_key"] = conn.private_key
        if conn.private_key_passphrase:
            extras["private_key_passphrase"] = conn.private_key_passphrase
    if conn.db_type == DBType.databricks:
        for attr in ("http_path", "access_token", "catalog", "schema_name"):
            extras[attr] = getattr(conn, attr, None)
    if conn.db_type == DBType.duckdb and getattr(conn, "motherduck_token", None):
        extras["motherduck_token"] = conn.motherduck_token
    for attr in ("connection_timeout", "query_timeout", "keepalive_interval"):
        val = getattr(conn, attr, None)
        if val is not None and (attr != "keepalive_interval" or val > 0):
            extras[attr] = val
    return extras
