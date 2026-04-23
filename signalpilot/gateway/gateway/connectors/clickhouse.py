"""ClickHouse connector — supports both native TCP (clickhouse-driver) and HTTP (clickhouse-connect).

Supports ClickHouse Cloud, on-premise, and self-hosted instances.
Falls back from native to HTTP protocol for maximum compatibility.
"""

from __future__ import annotations

from typing import Any

from .base import BaseConnector

try:
    from clickhouse_driver import Client as CHClient
    HAS_CLICKHOUSE_NATIVE = True
except ImportError:
    HAS_CLICKHOUSE_NATIVE = False

try:
    import clickhouse_connect
    HAS_CLICKHOUSE_HTTP = True
except ImportError:
    HAS_CLICKHOUSE_HTTP = False

HAS_CLICKHOUSE = HAS_CLICKHOUSE_NATIVE or HAS_CLICKHOUSE_HTTP


class ClickHouseConnector(BaseConnector):
    def __init__(self):
        super().__init__()
        self._client = None  # Either CHClient or clickhouse_connect client
        self._http_client = None  # clickhouse_connect client (HTTP)
        self._use_http = False
        self._database: str = "default"

    @property
    def _identifier_quote(self) -> str:
        return '`'

    def set_credential_extras(self, extras: dict) -> None:
        """Extract SSL config and timeout settings from credential extras."""
        super().set_credential_extras(extras)

    async def connect(self, connection_string: str) -> None:
        if not HAS_CLICKHOUSE:
            raise RuntimeError(
                "clickhouse-driver not installed. "
                "Run: pip install clickhouse-driver"
            )
        params = self._parse_connection_string(connection_string)
        self._database = params.get("database", "default")

        connect_args = {
            "host": params.get("host", "localhost"),
            "port": int(params.get("port", 9000)),
            "user": params.get("user", "default"),
            "password": params.get("password", ""),
            "database": self._database,
            "connect_timeout": self._connection_timeout,
            "send_receive_timeout": self._query_timeout,
        }

        # SSL support — from connection string or explicit ssl_config
        if params.get("secure"):
            connect_args["secure"] = True
            connect_args["verify"] = True

        if self._ssl_config and self._ssl_config.get("enabled"):
            connect_args["secure"] = True
            mode = self._ssl_config.get("mode", "require")

            if mode in ("verify-ca", "verify-full"):
                connect_args["verify"] = True
            else:
                connect_args["verify"] = False

            # Write PEM strings to temp files using base class helper
            ssl_paths = self._write_ssl_files()
            if "ca" in ssl_paths:
                connect_args["ca_certs"] = ssl_paths["ca"]
                connect_args["verify"] = True
            if "cert" in ssl_paths:
                connect_args["certfile"] = ssl_paths["cert"]
            if "key" in ssl_paths:
                connect_args["keyfile"] = ssl_paths["key"]

        # If explicit HTTP mode requested (clickhouse+http:// or clickhouse+https://),
        # skip native TCP and go directly to HTTP
        force_http = params.get("use_http", False)

        # Try native TCP first, fall back to HTTP (clickhouse-connect) for compatibility
        native_error = None
        if HAS_CLICKHOUSE_NATIVE and not force_http:
            try:
                self._client = CHClient(**connect_args)
                self._client.execute("SELECT 1")
                self._use_http = False
                return
            except Exception as e:
                native_error = e
                self._client = None

        # Fallback: try HTTP protocol (clickhouse-connect) — supports newer ClickHouse versions
        if HAS_CLICKHOUSE_HTTP:
            try:
                http_port = connect_args.get("port", 9000)
                # Map native ports → HTTP ports (common convention)
                native_to_http = {9000: 8123, 9440: 8443, 9100: 8124}
                if http_port in native_to_http:
                    http_port = native_to_http[http_port]
                http_kwargs = {
                    "host": connect_args.get("host", "localhost"),
                    "port": http_port,
                    "username": connect_args.get("user", "default"),
                    "password": connect_args.get("password", ""),
                    "database": connect_args.get("database", "default"),
                    "connect_timeout": self._connection_timeout,
                }
                # Pass SSL settings to HTTP client
                if connect_args.get("secure"):
                    http_kwargs["secure"] = True
                    if connect_args.get("verify") is not None:
                        http_kwargs["verify"] = connect_args["verify"]
                    if connect_args.get("ca_certs"):
                        http_kwargs["ca_cert"] = connect_args["ca_certs"]
                    if connect_args.get("certfile"):
                        http_kwargs["client_cert"] = connect_args["certfile"]
                    if connect_args.get("keyfile"):
                        http_kwargs["client_cert_key"] = connect_args["keyfile"]
                self._http_client = clickhouse_connect.get_client(**http_kwargs)
                self._http_client.query("SELECT 1")
                self._use_http = True
                return
            except Exception as e:
                if native_error:
                    raise self._classify_connect_error(native_error) from native_error
                raise RuntimeError(f"ClickHouse connection error (HTTP fallback): {e}") from e

        if native_error:
            raise self._classify_connect_error(native_error) from native_error
        raise RuntimeError("No ClickHouse driver available")

    @staticmethod
    def _classify_connect_error(err: Exception) -> RuntimeError:
        """Extract a human-readable error from ClickHouse driver exceptions."""
        err_str = str(err)
        err_lower = err_str.lower()
        # Extract DB::Exception message line (e.g., "DB::Exception: default: Authentication failed: ...")
        msg = err_str
        for line in err_str.split("\n"):
            if "DB::Exception" in line:
                # Strip "Code: NNN. " prefix and stack trace reference
                msg = line.split("DB::Exception: ", 1)[-1].rstrip(". ")
                break
        if "authentication" in err_lower or "wrong password" in err_lower:
            return RuntimeError(f"Authentication failed: {msg}")
        elif "connection refused" in err_lower or "timed out" in err_lower:
            return RuntimeError(f"Connection failed: {msg}")
        elif "unknown database" in err_lower or "database .* doesn't exist" in err_lower:
            return RuntimeError(f"Database not found: {msg}")
        return RuntimeError(f"ClickHouse connection error: {msg}")

    def _parse_connection_string(self, conn_str: str) -> dict:
        """Parse ClickHouse connection strings.

        Supported formats:
        - clickhouse://user:pass@host:9000/db (native TCP, default)
        - clickhouses://user:pass@host:9440/db (native TCP + TLS)
        - clickhouse+http://user:pass@host:8123/db (HTTP protocol)
        - clickhouse+https://user:pass@host:8443/db (HTTPS protocol)
        """
        from urllib.parse import urlparse, unquote

        secure = False
        use_http = False
        s = conn_str

        if s.startswith("clickhouse+https://"):
            secure = True
            use_http = True
            s = "clickhouse://" + s[len("clickhouse+https://"):]
        elif s.startswith("clickhouse+http://"):
            use_http = True
            s = "clickhouse://" + s[len("clickhouse+http://"):]
        elif s.startswith("clickhouses://"):
            secure = True
            s = "clickhouse://" + s[len("clickhouses://"):]
        elif not s.startswith("clickhouse://"):
            s = "clickhouse://" + s

        parsed = urlparse(s)

        # Default port depends on protocol and TLS
        if use_http:
            default_port = 8443 if secure else 8123
        else:
            default_port = 9440 if secure else 9000

        result = {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or default_port,
            "user": unquote(parsed.username or "default"),
            "password": unquote(parsed.password or ""),
            "database": parsed.path.lstrip("/") or "default",
        }
        if secure:
            result["secure"] = True
        if use_http:
            result["use_http"] = True
        return result

    def _raw_execute(self, sql: str, params=None, settings=None):
        """Execute a query using the active backend. Returns (rows_data, columns_info) tuple."""
        if self._use_http and self._http_client:
            result = self._http_client.query(sql, parameters=params, settings=settings or {})
            col_names = result.column_names
            return result.result_rows, [(name,) for name in col_names]
        elif self._client:
            execute_args = {"with_column_types": True}
            if settings:
                execute_args["settings"] = settings
            if params:
                return self._client.execute(sql, params, **execute_args)
            return self._client.execute(sql, **execute_args)
        raise RuntimeError("No active ClickHouse connection")

    def _ensure_connected(self) -> None:
        """Verify connection is alive; raise if lost."""
        if self._client is None and self._http_client is None:
            raise RuntimeError("Not connected")
        try:
            self._raw_execute("SELECT 1")
        except Exception:
            self._client = None
            self._http_client = None
            raise RuntimeError("Connection lost — please reconnect")

    async def execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        if self._client is None and self._http_client is None:
            raise RuntimeError("Not connected")

        effective_timeout = timeout or self._query_timeout

        def _run():
            settings = {}
            if effective_timeout:
                settings["max_execution_time"] = effective_timeout

            result = self._raw_execute(sql, params, settings)
            if isinstance(result, tuple) and len(result) == 2:
                rows_data, columns_info = result
                col_names = [c[0] for c in columns_info]
                return [dict(zip(col_names, row)) for row in rows_data]
            return []

        try:
            return await self._run_in_thread(_run, effective_timeout, label="ClickHouse")
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"ClickHouse query error: {e}") from e

    async def get_schema(self) -> dict[str, Any]:
        if self._client is None and self._http_client is None:
            raise RuntimeError("Not connected")

        # ClickHouse uses system tables for metadata
        sql = """
            SELECT
                database,
                table,
                name AS column_name,
                type AS data_type,
                default_kind,
                comment,
                is_in_primary_key
            FROM system.columns
            WHERE database NOT IN ('system', 'INFORMATION_SCHEMA', 'information_schema')
            ORDER BY database, table, position
        """
        import asyncio

        # Table engine and sorting key info (critical for ClickHouse query optimization)
        table_meta_sql = """
            SELECT
                database, name AS table_name,
                engine, sorting_key, primary_key,
                total_rows, total_bytes
            FROM system.tables
            WHERE database NOT IN ('system', 'INFORMATION_SCHEMA', 'information_schema')
        """

        # Column-level statistics from system.parts_columns (data size per column)
        col_stats_sql = """
            SELECT
                database, table, column,
                sum(rows) AS total_rows,
                sum(data_uncompressed_bytes) AS uncompressed_bytes,
                sum(data_compressed_bytes) AS compressed_bytes
            FROM system.parts_columns
            WHERE active
                AND database NOT IN ('system', 'INFORMATION_SCHEMA', 'information_schema')
            GROUP BY database, table, column
        """

        # Run queries sequentially — clickhouse-driver and clickhouse-connect
        # are NOT thread-safe for concurrent queries on a single connection
        def _fetch(query: str):
            try:
                return self._raw_execute(query)
            except Exception:
                return ([], [])

        def _fetch_all():
            return _fetch(sql), _fetch(table_meta_sql), _fetch(col_stats_sql)

        col_result, meta_result, stats_result = await asyncio.to_thread(_fetch_all)

        rows_data, columns_info = col_result
        col_names = [c[0] for c in columns_info]

        # Build table metadata map
        table_meta: dict[str, dict] = {}
        meta_rows, meta_cols = meta_result
        meta_col_names = [c[0] for c in meta_cols] if meta_cols else []
        for r in meta_rows:
            rd = dict(zip(meta_col_names, r))
            key = f"{rd['database']}.{rd['table_name']}"
            table_meta[key] = {
                "engine": rd.get("engine", ""),
                "sorting_key": rd.get("sorting_key", ""),
                "primary_key": rd.get("primary_key", ""),
                "row_count": rd.get("total_rows", 0),
                "total_bytes": rd.get("total_bytes", 0),
            }

        # Build column statistics map
        col_stats: dict[str, dict] = {}
        stats_rows, stats_cols = stats_result
        stats_col_names = [c[0] for c in stats_cols] if stats_cols else []
        for r in stats_rows:
            rd = dict(zip(stats_col_names, r))
            stat_key = f"{rd['database']}.{rd['table']}.{rd['column']}"
            col_stats[stat_key] = {
                "data_bytes": rd.get("uncompressed_bytes", 0),
                "compressed_bytes": rd.get("compressed_bytes", 0),
            }

        schema: dict[str, Any] = {}
        for row_vals in rows_data:
            row = dict(zip(col_names, row_vals))
            key = f"{row['database']}.{row['table']}"
            if key not in schema:
                meta = table_meta.get(key, {})
                engine = meta.get("engine", "")
                is_view = engine in ("View", "MaterializedView", "LiveView", "WindowView")
                schema[key] = {
                    "schema": row["database"],
                    "name": row["table"],
                    "type": "view" if is_view else "table",
                    "columns": [],
                    "engine": engine,
                    "sorting_key": meta.get("sorting_key", ""),
                    "row_count": meta.get("row_count", 0),
                    "total_bytes": meta.get("total_bytes", 0),
                    "size_mb": round((meta.get("total_bytes", 0) or 0) / (1024 * 1024), 2),
                }
            # ClickHouse Nullable types contain 'Nullable(' wrapper
            data_type = row["data_type"]
            nullable = "Nullable" in data_type
            low_cardinality = "LowCardinality" in data_type
            if nullable:
                data_type = data_type.replace("Nullable(", "").rstrip(")")
            if low_cardinality:
                data_type = data_type.replace("LowCardinality(", "").rstrip(")")

            col_entry: dict[str, Any] = {
                "name": row["column_name"],
                "type": data_type,
                "nullable": nullable,
                "primary_key": bool(row.get("is_in_primary_key", 0)),
                "comment": row.get("comment", ""),
            }
            if low_cardinality:
                col_entry["low_cardinality"] = True
            stat_key = f"{row['database']}.{row['table']}.{row['column_name']}"
            if stat_key in col_stats:
                col_entry["stats"] = col_stats[stat_key]
            schema[key]["columns"].append(col_entry)
        return schema

    async def get_sample_values(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        """Get sample distinct values via single UNION ALL query (1 round trip)."""
        if (self._client is None and self._http_client is None) or not columns:
            return {}
        try:
            sql = self._build_sample_union_sql(table, columns, limit, quote='`')
            data = self._raw_execute(sql)
            if isinstance(data, tuple) and len(data) == 2:
                rows = data[0]
            else:
                rows = data
            return self._parse_sample_union_result(rows)
        except Exception:
            # Fallback to per-column queries
            result: dict[str, list] = {}
            safe_table = self._quote_table(table)
            for col in columns[:20]:
                try:
                    data = self._raw_execute(
                        f'SELECT DISTINCT {self._quote_identifier(col)} FROM {safe_table} WHERE {self._quote_identifier(col)} IS NOT NULL LIMIT {limit}'
                    )
                    if isinstance(data, tuple) and len(data) == 2:
                        rows = data[0]
                    else:
                        rows = data
                    values = [str(row[0]) for row in rows]
                    if values:
                        result[col] = values
                except Exception:
                    continue
            return result

    async def health_check(self) -> bool:
        if self._client is None and self._http_client is None:
            return False
        try:
            self._raw_execute("SELECT 1")
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._client:
            self._client.disconnect()
            self._client = None
        if self._http_client:
            self._http_client.close()
            self._http_client = None
        self._use_http = False
        self._cleanup_temp_files()
