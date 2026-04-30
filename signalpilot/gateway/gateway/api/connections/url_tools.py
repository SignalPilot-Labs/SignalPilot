from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus, unquote, urlparse

from fastapi import HTTPException, Request

from gateway.api.connections._build_url import _BUILD_URL_FIELD_LIMITS
from gateway.api.connections._router import router
from gateway.auth import UserID
from gateway.security.scope_guard import RequireScope


@router.post("/connections/parse-url", dependencies=[RequireScope("read")])
async def parse_url_endpoint(_: UserID, request: Request):
    """Parse a database connection URL into individual credential fields."""
    body = await request.json()
    url = body.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    if len(url) > 4096:
        raise HTTPException(status_code=422, detail="URL must be at most 4096 characters")

    from gateway.url_parser import parse_connection_url

    result = parse_connection_url(url, db_type=body.get("db_type", ""))
    if not result:
        raise HTTPException(status_code=400, detail="Could not parse URL")
    return result


@router.post("/connections/validate-url", dependencies=[RequireScope("read")])
async def validate_connection_url(_: UserID, body: dict):
    """Validate and parse a connection string without saving or connecting."""
    url = body.get("connection_string", "")
    db_type = body.get("db_type", "")

    if not url:
        return {"valid": False, "error": "Connection string is empty"}
    if len(url) > 4096:
        raise HTTPException(status_code=422, detail="connection_string must be at most 4096 characters")
    if not db_type:
        return {"valid": False, "error": "db_type is required"}

    try:
        parsed_info: dict[str, Any] = {"db_type": db_type}
        warnings: list[str] = []

        if db_type in ("postgres", "mysql", "redshift", "clickhouse", "mssql"):
            normalized = url
            if db_type == "clickhouse":
                for prefix in ("clickhouse+https://", "clickhouse+http://", "clickhouses://", "clickhouse://"):
                    if normalized.startswith(prefix):
                        normalized = "http://" + normalized[len(prefix) :]
                        break
            elif db_type == "redshift" and normalized.startswith("redshift://"):
                normalized = "postgresql://" + normalized[len("redshift://") :]
            elif db_type == "mysql" and normalized.startswith("mysql+pymysql://"):
                normalized = "http://" + normalized[len("mysql+pymysql://") :]
            elif db_type == "mssql":
                for prefix in ("mssql://", "mssql+pymssql://", "sqlserver://"):
                    if normalized.startswith(prefix):
                        normalized = "http://" + normalized[len(prefix) :]
                        break

            parsed = urlparse(normalized)
            parsed_info["host"] = parsed.hostname or ""
            parsed_info["port"] = parsed.port
            parsed_info["database"] = (parsed.path or "").lstrip("/")
            parsed_info["username"] = unquote(parsed.username or "")
            parsed_info["has_password"] = bool(parsed.password)

            if not parsed_info["host"]:
                warnings.append("No host specified")
            if not parsed_info["database"]:
                warnings.append("No database specified")
            if not parsed_info["username"]:
                warnings.append("No username specified")
            if not parsed_info["has_password"]:
                warnings.append("No password in URL — will need separate credentials")

        elif db_type == "trino":
            normalized = url
            if normalized.startswith("trino://"):
                normalized = "http://" + normalized[len("trino://") :]
            elif normalized.startswith("trino+https://"):
                normalized = "http://" + normalized[len("trino+https://") :]
            parsed = urlparse(normalized)
            path_parts = [p for p in (parsed.path or "").split("/") if p]
            parsed_info["host"] = parsed.hostname or ""
            parsed_info["port"] = parsed.port or 8080
            parsed_info["username"] = unquote(parsed.username or "trino")
            parsed_info["has_password"] = bool(parsed.password)
            parsed_info["catalog"] = path_parts[0] if path_parts else ""
            parsed_info["schema"] = path_parts[1] if len(path_parts) > 1 else ""
            if not parsed_info["host"]:
                warnings.append("No host specified")
            if not parsed_info["catalog"]:
                warnings.append("No catalog specified")

        elif db_type == "snowflake":
            if url.startswith("snowflake://"):
                parsed = urlparse(url)
                path_parts = [p for p in (parsed.path or "").split("/") if p]
                parsed_info["account"] = parsed.hostname or ""
                parsed_info["username"] = unquote(parsed.username or "")
                parsed_info["has_password"] = bool(parsed.password)
                parsed_info["database"] = path_parts[0] if path_parts else ""
                parsed_info["schema"] = path_parts[1] if len(path_parts) > 1 else ""
                if not parsed_info["account"]:
                    warnings.append("No account identifier specified")
            else:
                warnings.append("Snowflake URLs should start with snowflake://")

        elif db_type == "databricks":
            if url.startswith("databricks://"):
                parsed = urlparse(url)
                parsed_info["host"] = parsed.hostname or ""
                parsed_info["http_path"] = (parsed.path or "").lstrip("/")
                parsed_info["has_token"] = bool(parsed.username)
                if not parsed_info["host"]:
                    warnings.append("No hostname specified")
                if not parsed_info["http_path"]:
                    warnings.append("No HTTP path specified")
            else:
                warnings.append("Databricks URLs should start with databricks://")

        return {"valid": True, "parsed": parsed_info, "warnings": warnings}
    except Exception:
        return {"valid": False, "error": "Invalid URL format"}


@router.post("/connections/build-url", dependencies=[RequireScope("read")])
async def build_connection_url(_: UserID, body: dict):
    """Build a connection string from individual fields."""
    db_type = body.get("db_type", "")
    host = body.get("host", "")
    port = body.get("port")
    database = body.get("database", "")
    username = body.get("username", "")
    password = body.get("password", "")

    if not db_type:
        return {"url": "", "error": "db_type is required"}

    for field_name, max_len in _BUILD_URL_FIELD_LIMITS.items():
        value = body.get(field_name, "")
        if isinstance(value, str) and len(value) > max_len:
            raise HTTPException(
                status_code=422,
                detail=f"{field_name} must be at most {max_len} characters",
            )

    try:
        userpass = ""
        if username:
            userpass = quote_plus(username)
            if password:
                userpass += f":{quote_plus(password)}"
            userpass += "@"

        if db_type == "postgres":
            p = port or 5432
            url = f"postgresql://{userpass}{host}:{p}/{database}"
        elif db_type == "mysql":
            p = port or 3306
            url = f"mysql://{userpass}{host}:{p}/{database}"
        elif db_type == "redshift":
            p = port or 5439
            url = f"redshift://{userpass}{host}:{p}/{database}"
        elif db_type == "mssql":
            p = port or 1433
            url = f"mssql://{userpass}{host}:{p}/{database}"
        elif db_type == "clickhouse":
            protocol = body.get("protocol", "native")
            ssl = body.get("ssl", False)
            if protocol == "http":
                p = port or (8443 if ssl else 8123)
                scheme = "clickhouse+https" if ssl else "clickhouse+http"
            else:
                p = port or (9440 if ssl else 9000)
                scheme = "clickhouses" if ssl else "clickhouse"
            url = f"{scheme}://{userpass}{host}:{p}/{database}"
        elif db_type == "trino":
            https = body.get("https", False)
            p = port or (443 if https else 8080)
            scheme = "trino+https" if https else "trino"
            catalog = body.get("catalog", "")
            schema_name = body.get("schema_name", "")
            path = catalog
            if schema_name:
                path += f"/{schema_name}"
            url = f"{scheme}://{userpass}{host}:{p}/{path}"
        elif db_type == "snowflake":
            account = body.get("account", "")
            warehouse = body.get("warehouse", "")
            schema_name = body.get("schema_name", "")
            role = body.get("role", "")
            url = f"snowflake://{userpass}{account}/{database}"
            if schema_name:
                url += f"/{schema_name}"
            params = []
            if warehouse:
                params.append(f"warehouse={quote_plus(warehouse)}")
            if role:
                params.append(f"role={quote_plus(role)}")
            if params:
                url += "?" + "&".join(params)
        elif db_type == "databricks":
            access_token = body.get("access_token", "")
            http_path = body.get("http_path", "")
            catalog = body.get("catalog", "")
            url = f"databricks://token:{quote_plus(access_token)}@{host}/{http_path}"
            if catalog:
                url += f"?catalog={quote_plus(catalog)}"
        elif db_type in ("duckdb", "sqlite"):
            url = database or ":memory:"
        elif db_type == "bigquery":
            project = body.get("project", "")
            dataset = body.get("dataset", "")
            url = f"bigquery://{project}"
            if dataset:
                url += f"/{dataset}"
        else:
            return {"url": "", "error": f"Unknown db_type: {db_type}"}

        masked = url
        if password:
            masked = masked.replace(quote_plus(password), "****")

        return {"url": url, "masked_url": masked, "db_type": db_type}
    except Exception:
        return {"url": "", "error": "Failed to build URL"}
