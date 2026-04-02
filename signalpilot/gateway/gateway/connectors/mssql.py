"""Microsoft SQL Server connector — pymssql backed.

Supports SQL Server 2016+, Azure SQL Database, Azure SQL Managed Instance.
Uses pymssql for synchronous operations wrapped in async context.

Schema introspection uses sys.* catalog views for comprehensive metadata
including row counts (sys.dm_db_partition_stats), column statistics,
extended properties for comments, and index definitions.
"""

from __future__ import annotations

from typing import Any

from .base import BaseConnector

try:
    import pymssql

    HAS_PYMSSQL = True
except ImportError:
    HAS_PYMSSQL = False


class MSSQLConnector(BaseConnector):
    def __init__(self):
        self._conn: pymssql.Connection | None = None
        self._connect_params: dict = {}
        self._ssl_config: dict | None = None
        self._login_timeout: int = 15
        self._query_timeout: int = 30
        # Azure AD / Entra ID auth via access token
        self._azure_ad_auth: bool = False
        self._azure_tenant_id: str = ""
        self._azure_client_id: str = ""
        self._azure_client_secret: str = ""

    def set_ssl_config(self, ssl_config: dict) -> None:
        self._ssl_config = ssl_config

    def set_credential_extras(self, extras: dict) -> None:
        if extras.get("ssl_config"):
            self.set_ssl_config(extras["ssl_config"])
        if extras.get("connection_timeout"):
            self._login_timeout = extras["connection_timeout"]
        if extras.get("query_timeout"):
            self._query_timeout = extras["query_timeout"]
        # Azure AD auth
        if extras.get("auth_method") == "azure_ad" or extras.get("azure_ad_auth"):
            self._azure_ad_auth = True
            self._azure_tenant_id = extras.get("azure_tenant_id", "")
            self._azure_client_id = extras.get("azure_client_id", "")
            self._azure_client_secret = extras.get("azure_client_secret", "")

    def _acquire_azure_ad_token(self) -> str:
        """Acquire an Azure AD / Entra ID access token for Azure SQL using client credentials.

        Uses MSAL (Microsoft Authentication Library) to get a token via OAuth2 client_credentials flow.
        The token is then used as the password for pymssql connection.
        """
        try:
            import msal
        except ImportError:
            raise RuntimeError("msal required for Azure AD auth. Run: pip install msal")

        if not self._azure_tenant_id:
            raise RuntimeError("Azure AD auth requires tenant_id")
        if not self._azure_client_id or not self._azure_client_secret:
            raise RuntimeError("Azure AD auth requires client_id and client_secret (service principal)")

        authority = f"https://login.microsoftonline.com/{self._azure_tenant_id}"
        app = msal.ConfidentialClientApplication(
            self._azure_client_id,
            authority=authority,
            client_credential=self._azure_client_secret,
        )
        # Azure SQL database scope
        result = app.acquire_token_for_client(scopes=["https://database.windows.net/.default"])
        if "access_token" in result:
            return result["access_token"]
        error = result.get("error_description", result.get("error", "Unknown error"))
        raise RuntimeError(f"Azure AD token acquisition failed: {error}")

    async def connect(self, connection_string: str) -> None:
        if not HAS_PYMSSQL:
            raise RuntimeError("pymssql not installed. Run: pip install pymssql")

        params = self._parse_connection_string(connection_string)
        self._connect_params = params

        connect_kwargs: dict = {
            "server": params.get("host", "localhost"),
            "port": str(params.get("port", "1433")),
            "user": params.get("user", ""),
            "password": params.get("password", ""),
            "database": params.get("database", "master"),
            "login_timeout": self._login_timeout,
            "timeout": self._query_timeout,
            "as_dict": True,
            "charset": "UTF-8",
        }

        # Azure AD auth — acquire token and use as password
        if self._azure_ad_auth:
            token = self._acquire_azure_ad_token()
            connect_kwargs["password"] = token
            # Azure SQL always requires encryption
            connect_kwargs["conn_properties"] = "Encrypt=yes;TrustServerCertificate=no"

        # Default to TDS 7.4 (SQL Server 2019+ / Azure SQL)
        connect_kwargs["tds_version"] = "7.4"

        # TLS encryption — from SSL config or URL encrypt=true
        enable_tls = params.get("encrypt", False)
        if not self._azure_ad_auth:  # Azure AD already sets encryption above
            if self._ssl_config and self._ssl_config.get("enabled"):
                enable_tls = True
                mode = self._ssl_config.get("mode", "require")
                if mode in ("verify-ca", "verify-full"):
                    connect_kwargs["conn_properties"] = "Encrypt=yes;TrustServerCertificate=no"
                else:
                    connect_kwargs["conn_properties"] = "Encrypt=yes;TrustServerCertificate=yes"
            elif enable_tls:
                connect_kwargs["conn_properties"] = "Encrypt=yes;TrustServerCertificate=yes"

        try:
            self._conn = pymssql.connect(**connect_kwargs)
        except pymssql.OperationalError as e:
            err_str = str(e).lower()
            if "login failed" in err_str:
                raise RuntimeError(f"Authentication failed: Login failed for user '{connect_kwargs.get('user', '')}'") from e
            elif "cannot open database" in err_str:
                raise RuntimeError(f"Database not found: Cannot open database '{connect_kwargs.get('database', '')}'") from e
            elif "connection refused" in err_str or "network" in err_str or "unable to connect" in err_str:
                raise RuntimeError(f"Connection failed: Cannot connect to SQL Server on '{connect_kwargs.get('server', '')}:{connect_kwargs.get('port', '1433')}'") from e
            raise RuntimeError(f"SQL Server connection error: {e}") from e

    def _parse_connection_string(self, conn_str: str) -> dict:
        """Parse mssql://user:pass@host:port/db or mssql+pymssql://... format.

        Also supports query parameters:
        - encrypt=true/false
        - trustServerCertificate=true/false
        - instance=SQLEXPRESS (named instance)
        """
        from urllib.parse import urlparse, unquote, parse_qs

        s = conn_str
        for prefix in ("mssql+pymssql://", "mssql://", "sqlserver://"):
            if s.startswith(prefix):
                s = "mssql://" + s[len(prefix):]
                break

        parsed = urlparse(s)
        query = parse_qs(parsed.query or "")

        result = {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 1433,
            "user": unquote(parsed.username or "sa"),
            "password": unquote(parsed.password or ""),
            "database": parsed.path.lstrip("/") if parsed.path else "master",
        }

        # Support named instances via query param: ?instance=SQLEXPRESS
        if query.get("instance"):
            result["host"] = f"{result['host']}\\{query['instance'][0]}"

        # Support encryption via query param: ?encrypt=true
        if query.get("encrypt", [""])[0].lower() in ("true", "1", "yes"):
            result["encrypt"] = True

        return result

    def _ensure_connected(self) -> None:
        """Ensure connection is alive, reconnect if needed."""
        if self._conn is None:
            if self._connect_params:
                # Rebuild connect kwargs from stored params
                self._conn = pymssql.connect(
                    server=self._connect_params.get("host", "localhost"),
                    port=str(self._connect_params.get("port", "1433")),
                    user=self._connect_params.get("user", ""),
                    password=self._connect_params.get("password", ""),
                    database=self._connect_params.get("database", "master"),
                    login_timeout=self._login_timeout,
                    timeout=self._query_timeout,
                    as_dict=True,
                    charset="UTF-8",
                )
            else:
                raise RuntimeError("Not connected")
            return
        try:
            cursor = self._conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchall()
            cursor.close()
        except Exception:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
            if self._connect_params:
                self._ensure_connected()  # Recursive reconnect
            else:
                raise RuntimeError("Connection lost and cannot reconnect")

    async def execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        if self._conn is None:
            raise RuntimeError("Not connected")
        try:
            self._ensure_connected()
            cursor = self._conn.cursor(as_dict=True)
            if timeout:
                # SET LOCK_TIMEOUT for blocking waits + query governor for CPU time
                cursor.execute(f"SET LOCK_TIMEOUT {timeout * 1000}")
            cursor.execute(sql, tuple(params) if params else None)
            if cursor.description is None:
                return []
            rows = cursor.fetchall()
            cursor.close()
            return list(rows) if rows else []
        except pymssql.Error as e:
            raise RuntimeError(f"SQL Server query error: {e}") from e

    async def get_schema(self) -> dict[str, Any]:
        if self._conn is None:
            raise RuntimeError("Not connected")
        self._ensure_connected()

        # Columns + primary keys from tables AND views
        col_sql = """
            SELECT
                s.name AS table_schema,
                o.name AS table_name,
                o.type AS object_type,
                c.name AS column_name,
                tp.name AS data_type,
                c.max_length,
                c.precision,
                c.scale,
                c.is_nullable,
                c.is_identity,
                OBJECT_DEFINITION(c.default_object_id) AS column_default,
                CASE WHEN pk.column_id IS NOT NULL THEN 1 ELSE 0 END AS is_primary_key,
                ep.value AS column_comment,
                ep_t.value AS table_comment
            FROM sys.objects o
            JOIN sys.schemas s ON o.schema_id = s.schema_id
            JOIN sys.columns c ON o.object_id = c.object_id
            JOIN sys.types tp ON c.user_type_id = tp.user_type_id
            LEFT JOIN (
                SELECT ic.object_id, ic.column_id
                FROM sys.index_columns ic
                JOIN sys.indexes i ON ic.object_id = i.object_id AND ic.index_id = i.index_id
                WHERE i.is_primary_key = 1
            ) pk ON c.object_id = pk.object_id AND c.column_id = pk.column_id
            LEFT JOIN sys.extended_properties ep
                ON ep.major_id = c.object_id AND ep.minor_id = c.column_id AND ep.name = 'MS_Description'
            LEFT JOIN sys.extended_properties ep_t
                ON ep_t.major_id = o.object_id AND ep_t.minor_id = 0 AND ep_t.name = 'MS_Description'
            WHERE o.type IN ('U', 'V')
                AND s.name NOT IN ('sys', 'INFORMATION_SCHEMA', 'guest')
                AND o.name NOT LIKE 'spt[_]%'
                AND o.name NOT IN ('MSreplication_options', 'MSmerge_altsyncpartners')
                AND OBJECTPROPERTY(o.object_id, 'IsMSShipped') = 0
            ORDER BY s.name, o.name, c.column_id
        """

        # Row counts and table sizes from dm_db_partition_stats (accurate, no table scan)
        rowcount_sql = """
            SELECT
                s.name AS table_schema,
                t.name AS table_name,
                SUM(p.row_count) AS row_count,
                CAST(ROUND(SUM(p.used_page_count) * 8.0 / 1024.0, 2) AS FLOAT) AS size_mb
            FROM sys.dm_db_partition_stats p
            JOIN sys.tables t ON p.object_id = t.object_id
            JOIN sys.schemas s ON t.schema_id = s.schema_id
            WHERE p.index_id IN (0, 1)
                AND s.name NOT IN ('sys', 'INFORMATION_SCHEMA', 'guest')
            GROUP BY s.name, t.name
        """

        # Foreign keys
        fk_sql = """
            SELECT
                OBJECT_SCHEMA_NAME(fk.parent_object_id) AS table_schema,
                OBJECT_NAME(fk.parent_object_id) AS table_name,
                COL_NAME(fkc.parent_object_id, fkc.parent_column_id) AS column_name,
                OBJECT_SCHEMA_NAME(fk.referenced_object_id) AS referenced_schema,
                OBJECT_NAME(fk.referenced_object_id) AS referenced_table,
                COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) AS referenced_column
            FROM sys.foreign_keys fk
            JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
        """

        # Indexes with included columns
        idx_sql = """
            SELECT
                OBJECT_SCHEMA_NAME(i.object_id) AS table_schema,
                OBJECT_NAME(i.object_id) AS table_name,
                i.name AS index_name,
                i.is_unique,
                i.type_desc AS index_type,
                STRING_AGG(c.name, ', ') WITHIN GROUP (ORDER BY ic.key_ordinal) AS columns
            FROM sys.indexes i
            JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
            JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
            WHERE i.name IS NOT NULL
                AND ic.is_included_column = 0
                AND OBJECT_SCHEMA_NAME(i.object_id) NOT IN ('sys', 'INFORMATION_SCHEMA')
            GROUP BY i.object_id, i.name, i.is_unique, i.type_desc
        """

        # Column statistics — helps Spider2.0 understand selectivity
        # Uses dm_db_stats_properties for actual distinct counts from auto-stats
        # OUTER APPLY is required because dm_db_stats_properties is a TVF
        stats_sql = """
            SELECT
                OBJECT_SCHEMA_NAME(s.object_id) AS table_schema,
                OBJECT_NAME(s.object_id) AS table_name,
                c.name AS column_name,
                s.name AS stat_name,
                STATS_DATE(s.object_id, s.stats_id) AS last_updated,
                sp.rows AS stat_rows,
                sp.modification_counter AS modifications
            FROM sys.stats s
            JOIN sys.stats_columns sc ON s.object_id = sc.object_id AND s.stats_id = sc.stats_id
            JOIN sys.columns c ON sc.object_id = c.object_id AND sc.column_id = c.column_id
            OUTER APPLY sys.dm_db_stats_properties(s.object_id, s.stats_id) sp
            WHERE sc.stats_column_id = 1
                AND OBJECT_SCHEMA_NAME(s.object_id) NOT IN ('sys', 'INFORMATION_SCHEMA')
        """

        # Column-level cardinality via unique indexes
        cardinality_sql = """
            SELECT
                OBJECT_SCHEMA_NAME(i.object_id) AS table_schema,
                OBJECT_NAME(i.object_id) AS table_name,
                c.name AS column_name,
                i.is_unique
            FROM sys.indexes i
            JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
            JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
            WHERE i.name IS NOT NULL
                AND ic.is_included_column = 0
                AND ic.key_ordinal = 1
                AND OBJECT_SCHEMA_NAME(i.object_id) NOT IN ('sys', 'INFORMATION_SCHEMA')
        """

        def _fetch(query: str) -> list:
            try:
                cursor = self._conn.cursor(as_dict=True)
                cursor.execute(query)
                result = cursor.fetchall()
                cursor.close()
                return result
            except Exception:
                return []

        def _fetch_all_sequential() -> tuple:
            """Run all metadata queries sequentially — pymssql uses a single connection."""
            return (
                _fetch(col_sql),
                _fetch(rowcount_sql),
                _fetch(fk_sql),
                _fetch(idx_sql),
                _fetch(stats_sql),
                _fetch(cardinality_sql),
            )

        # Run the synchronous queries in a thread pool to avoid blocking the event loop
        import asyncio
        loop = asyncio.get_event_loop()
        rows, rowcount_rows, fk_rows, idx_rows, stat_rows, card_rows = await loop.run_in_executor(
            None, _fetch_all_sequential
        )

        # Build row count and table size maps
        row_counts: dict[str, int] = {}
        table_sizes: dict[str, float] = {}
        for r in rowcount_rows:
            key = f"{r['table_schema']}.{r['table_name']}"
            row_counts[key] = r.get("row_count", 0) or 0
            table_sizes[key] = r.get("size_mb", 0) or 0

        # Build FK map
        foreign_keys: dict[str, list[dict]] = {}
        for r in fk_rows:
            key = f"{r['table_schema']}.{r['table_name']}"
            if key not in foreign_keys:
                foreign_keys[key] = []
            foreign_keys[key].append({
                "column": r["column_name"],
                "references_schema": r["referenced_schema"],
                "references_table": r["referenced_table"],
                "references_column": r["referenced_column"],
            })

        # Build index map
        indexes: dict[str, list[dict]] = {}
        for r in idx_rows:
            key = f"{r['table_schema']}.{r['table_name']}"
            if key not in indexes:
                indexes[key] = []
            indexes[key].append({
                "name": r["index_name"],
                "columns": r["columns"],
                "unique": bool(r["is_unique"]),
                "type": r.get("index_type", ""),
            })

        # Build stats map (column → statistics info)
        col_has_stats: set[str] = set()
        col_stat_info: dict[str, dict] = {}
        for r in stat_rows:
            stat_key = f"{r['table_schema']}.{r['table_name']}.{r['column_name']}"
            col_has_stats.add(stat_key)
            stat_rows_count = r.get("stat_rows", 0)
            if stat_rows_count and stat_key not in col_stat_info:
                col_stat_info[stat_key] = {"stat_rows": int(stat_rows_count)}

        # Build unique column set from indexes
        unique_cols: set[str] = set()
        for r in card_rows:
            if r.get("is_unique"):
                card_key = f"{r['table_schema']}.{r['table_name']}.{r['column_name']}"
                unique_cols.add(card_key)

        schema: dict[str, Any] = {}
        for row in rows:
            key = f"{row['table_schema']}.{row['table_name']}"
            if key not in schema:
                is_view = row.get("object_type", "U").strip() == "V"
                schema[key] = {
                    "schema": row["table_schema"],
                    "name": row["table_name"],
                    "type": "view" if is_view else "table",
                    "columns": [],
                    "foreign_keys": foreign_keys.get(key, []),
                    "indexes": indexes.get(key, []),
                    "row_count": row_counts.get(key, 0),
                    "size_mb": table_sizes.get(key, 0),
                    "description": str(row.get("table_comment", "") or ""),
                }

            # Build data type string with precision info
            data_type = row["data_type"]
            if data_type in ("nvarchar", "varchar", "char", "nchar", "binary", "varbinary"):
                max_len = row.get("max_length", -1)
                if max_len == -1:
                    data_type = f"{data_type}(max)"
                elif data_type.startswith("n"):
                    data_type = f"{data_type}({max_len // 2})"
                else:
                    data_type = f"{data_type}({max_len})"
            elif data_type in ("decimal", "numeric"):
                data_type = f"{data_type}({row.get('precision', 18)},{row.get('scale', 0)})"

            stat_key = f"{row['table_schema']}.{row['table_name']}.{row['column_name']}"
            col_entry: dict[str, Any] = {
                "name": row["column_name"],
                "type": data_type,
                "nullable": bool(row["is_nullable"]),
                "primary_key": bool(row["is_primary_key"]),
                "default": row.get("column_default"),
                "comment": str(row.get("column_comment", "") or ""),
            }
            if bool(row.get("is_identity")):
                col_entry["identity"] = True
            if stat_key in col_has_stats:
                col_entry["has_statistics"] = True
            # Enrich with cardinality info for schema linking
            if stat_key in unique_cols:
                col_entry["stats"] = {"distinct_fraction": -1.0}  # Unique column
            elif stat_key in col_stat_info:
                col_entry["stats"] = col_stat_info[stat_key]

            schema[key]["columns"].append(col_entry)
        return schema

    async def get_sample_values(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        """Get sample distinct values via single UNION ALL query (1 round trip)."""
        if self._conn is None or not columns:
            return {}
        self._ensure_connected()
        try:
            # MSSQL uses TOP N instead of LIMIT, and [] quoting
            parts = []
            for i, col in enumerate(columns[:20]):
                parts.append(
                    f"SELECT '{col}' AS _col, CAST([{col}] AS NVARCHAR(MAX)) AS _val "
                    f"FROM (SELECT DISTINCT TOP {limit} [{col}] FROM {table} WHERE [{col}] IS NOT NULL) t{i}"
                )
            sql = "\n UNION ALL \n".join(parts)
            cursor = self._conn.cursor(as_dict=True)
            cursor.execute(sql)
            rows = cursor.fetchall()
            cursor.close()
            return self._parse_sample_union_result(rows)
        except Exception:
            # Fallback to per-column queries
            result: dict[str, list] = {}
            for col in columns[:20]:
                try:
                    cursor = self._conn.cursor(as_dict=True)
                    cursor.execute(
                        f"SELECT DISTINCT TOP {limit} [{col}] FROM {table} WHERE [{col}] IS NOT NULL"
                    )
                    rows = cursor.fetchall()
                    cursor.close()
                    values = [str(r[col]) for r in rows if r[col] is not None]
                    if values:
                        result[col] = values
                except Exception:
                    continue
            return result

    async def health_check(self) -> bool:
        if self._conn is None:
            return False
        try:
            self._ensure_connected()
            cursor = self._conn.cursor(as_dict=True)
            cursor.execute("SELECT 1 AS ok")
            cursor.fetchall()
            cursor.close()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
