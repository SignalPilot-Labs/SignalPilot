"""Security-audit 2026-09-15 governance fixes: SP-07, SP-08, SP-09.

- SP-07: schema-qualified blocked-table policies match on qualified forms.
- SP-09: denylist additions per dialect + data-modifying CTE rejection.
- SP-08: Snowflake host override must stay on a Snowflake-operated domain.
"""

from __future__ import annotations

import pytest

from gateway.engine.validation import validate_sql
from gateway.network.validation import validate_cloud_warehouse_params

# ---------------------------------------------------------------------------
# SP-07: qualified blocked-table policies
# ---------------------------------------------------------------------------


class TestQualifiedBlockedTables:
    def test_qualified_policy_blocks_matching_schema(self):
        r = validate_sql("SELECT * FROM private.my_secrets", blocked_tables=["private.my_secrets"], dialect="postgres")
        assert not r.ok
        assert "private.my_secrets" in (r.blocked_reason or "")

    def test_qualified_policy_case_and_quote_insensitive(self):
        r = validate_sql('SELECT * FROM "Private"."My_Secrets"', blocked_tables=["PRIVATE.MY_SECRETS"], dialect="postgres")
        assert not r.ok

    def test_qualified_policy_allows_same_basename_in_other_schema(self):
        r = validate_sql("SELECT * FROM public.my_secrets", blocked_tables=["private.my_secrets"], dialect="postgres")
        assert r.ok, r.blocked_reason

    def test_qualified_policy_allows_unqualified_reference(self):
        # `my_secrets` with no schema is not provably `private.my_secrets`; a
        # qualified policy only claims that schema.
        r = validate_sql("SELECT * FROM my_secrets", blocked_tables=["private.my_secrets"], dialect="postgres")
        assert r.ok, r.blocked_reason

    def test_catalog_qualified_policy(self):
        blocked = ["cat.private.my_secrets"]
        assert not validate_sql("SELECT * FROM cat.private.my_secrets", blocked_tables=blocked, dialect="postgres").ok
        assert validate_sql("SELECT * FROM other.private.my_secrets", blocked_tables=blocked, dialect="postgres").ok
        assert validate_sql("SELECT * FROM private.my_secrets", blocked_tables=blocked, dialect="postgres").ok

    def test_unqualified_policy_blocks_everywhere(self):
        blocked = ["my_secrets"]
        assert not validate_sql("SELECT * FROM my_secrets", blocked_tables=blocked, dialect="postgres").ok
        assert not validate_sql("SELECT * FROM private.my_secrets", blocked_tables=blocked, dialect="postgres").ok
        assert not validate_sql("SELECT * FROM cat.private.my_secrets", blocked_tables=blocked, dialect="postgres").ok

    def test_qualified_policy_inside_join_and_cte(self):
        blocked = ["private.my_secrets"]
        sql = "WITH s AS (SELECT * FROM private.my_secrets) SELECT * FROM t JOIN s ON t.id = s.id"
        assert not validate_sql(sql, blocked_tables=blocked, dialect="postgres").ok

    def test_tables_output_stays_basenames(self):
        r = validate_sql("SELECT a FROM cat.private.my_secrets s JOIN public.t USING (id)", dialect="postgres")
        assert r.ok
        assert r.tables == ["my_secrets", "t"]


# ---------------------------------------------------------------------------
# SP-09: data-modifying CTEs / nested DML
# ---------------------------------------------------------------------------


class TestDataModifyingCTE:
    @pytest.mark.parametrize(
        "sql, kind",
        [
            ("WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x", "DELETE"),
            ("WITH x AS (INSERT INTO t VALUES (1) RETURNING *) SELECT 1", "INSERT"),
            ("WITH x AS (UPDATE t SET a = 1 RETURNING *) SELECT * FROM x", "UPDATE"),
        ],
    )
    def test_modifying_cte_rejected(self, sql, kind):
        r = validate_sql(sql, dialect="postgres")
        assert not r.ok
        assert kind in (r.blocked_reason or "")

    def test_read_only_cte_still_allowed(self):
        sql = "WITH x AS (SELECT * FROM t WHERE a > 1) SELECT x.a, COUNT(*) FROM x GROUP BY x.a"
        assert validate_sql(sql, dialect="postgres").ok


# ---------------------------------------------------------------------------
# SP-09: denylist additions
# ---------------------------------------------------------------------------

_SNOWFLAKE_BLOCKED = [
    "SELECT SYSTEM$ABORT_SESSION(1)",
    "SELECT SYSTEM$ABORT_TRANSACTION(1)",
    "SELECT SYSTEM$CANCEL_QUERY('x')",
    "SELECT SYSTEM$SEND_EMAIL('int','a@b','s','b')",
    "SELECT SYSTEM$SEND_SNOWFLAKE_NOTIFICATION('x','y')",
    "SELECT SYSTEM$GLOBAL_ACCOUNT_SET_PARAMETER('x','y','z')",
    "SELECT SYSTEM$AUTHORIZE_PRIVATELINK('x','y')",
    "SELECT SYSTEM$REVOKE_PRIVATELINK('x','y')",
    "SELECT SYSTEM$AUTHORIZE_STAGE_PRIVATELINK_ACCESS('x')",
    "SELECT SYSTEM$GENERATE_SCIM_ACCESS_TOKEN('x')",
    "SELECT SYSTEM$CREATE_BILLING_EVENT('x','y',1,1,1,1)",
    "SELECT SYSTEM$CREATE_BILLING_EVENTS('x')",
    "SELECT SYSTEM$SET_RETURN_VALUE('x')",
    "SELECT SYSTEM$USER_TASK_CANCEL_ONGOING_EXECUTIONS('x')",
    "SELECT SYSTEM$TASK_DEPENDENTS_ENABLE('x')",
    "SELECT SYSTEM$PIPE_REBINDING_WITH_NOTIFICATION_CHANNEL('x')",
    "SELECT SYSTEM$SET_TOKEN('x')",
    "SELECT SYSTEM$LINK_ACCOUNT_OBJECTS_BY_NAME('x','y')",
    "SELECT SYSTEM$MIGRATE_SAML_IDP_REGISTRATION('x')",
    "SELECT GET_PRESIGNED_URL(@s,'x')",
]

_CLICKHOUSE_BLOCKED = [
    "SELECT * FROM urlCluster('c','http://x','CSV')",
    "SELECT * FROM fileCluster('c','/x','CSV')",
    "SELECT * FROM gcs('https://x','CSV')",
    "SELECT * FROM oss('https://x','CSV')",
    "SELECT * FROM cosn('https://x','CSV')",
    "SELECT * FROM mongodb('x','db','c','u','p','')",
    "SELECT * FROM cluster('c','db','t')",
    "SELECT * FROM clusterAllReplicas('c','db','t')",
    "SELECT sleep(3)",
    "SELECT sleepEachRow(3) FROM numbers(100)",
]

_TRINO_BLOCKED = [
    "SELECT * FROM TABLE(sqlserver.system.procedure(query => 'exec xp_cmdshell'))",
    "SELECT * FROM TABLE(delta.system.vacuum(schema_name => 'x', table_name => 'y', retention => '7d'))",
    "SELECT * FROM TABLE(hive.system.flush_metadata_cache())",
]

_TSQL_BLOCKED = [
    r"SELECT * FROM fn_xe_file_target_read_file('c:\x.xel',null,null,null)",
    r"SELECT * FROM sys.fn_trace_gettable('c:\x.trc',default)",
    r"SELECT * FROM sys.fn_get_audit_file('c:\*',default,default)",
]

_MYSQL_BLOCKED = [
    "SELECT SLEEP(10)",
    "SELECT BENCHMARK(1e9, MD5('x'))",
    "SELECT GET_LOCK('x',100)",
]


class TestDenylistAdditions:
    @pytest.mark.parametrize(
        "dialect, sql",
        [("snowflake", s) for s in _SNOWFLAKE_BLOCKED]
        + [("clickhouse", s) for s in _CLICKHOUSE_BLOCKED]
        + [("trino", s) for s in _TRINO_BLOCKED]
        + [("tsql", s) for s in _TSQL_BLOCKED]
        + [("mysql", s) for s in _MYSQL_BLOCKED],
    )
    def test_blocked(self, dialect, sql):
        r = validate_sql(sql, dialect=dialect)
        assert not r.ok, f"{dialect}: {sql} should be blocked"
        assert "not permitted" in (r.blocked_reason or "")

    def test_mssql_alias_shares_tsql_denylist(self):
        assert not validate_sql(_TSQL_BLOCKED[0], dialect="mssql").ok

    @pytest.mark.parametrize(
        "dialect, sql",
        [
            ("snowflake", "SELECT SYSTEM$CLUSTERING_INFORMATION('t')"),
            ("snowflake", "SELECT * FROM t QUALIFY ROW_NUMBER() OVER (PARTITION BY a ORDER BY b) = 1"),
            ("snowflake", "SELECT * FROM information_schema.tables"),
            ("clickhouse", "SELECT * FROM t SAMPLE 0.1"),
            ("clickhouse", "SELECT * FROM t UNION ALL SELECT * FROM u"),
            ("trino", "SELECT * FROM cat.sch.t"),
            ("trino", "SELECT * FROM TABLE(sequence(start => 1, stop => 10))"),
            ("tsql", "SELECT * FROM master.sys.tables"),
            ("tsql", "SELECT * FROM STRING_SPLIT('a,b',',')"),
            ("mysql", "SELECT a, SUM(b) OVER (PARTITION BY c) FROM t JOIN u USING (id)"),
            ("postgres", "SELECT * FROM t TABLESAMPLE SYSTEM(1)"),
        ],
    )
    def test_legitimate_reads_still_ok(self, dialect, sql):
        r = validate_sql(sql, dialect=dialect)
        assert r.ok, f"{dialect}: {sql} wrongly blocked: {r.blocked_reason}"


# ---------------------------------------------------------------------------
# SP-08: Snowflake host override
# ---------------------------------------------------------------------------


class TestSnowflakeHostOverride:
    @pytest.mark.parametrize(
        "host",
        [
            "myorg-myacct.snowflakecomputing.com",
            "myacct.us-east-1.privatelink.snowflakecomputing.com",
            "myacct.eu-central-1.SNOWFLAKECOMPUTING.COM",
            "myacct.cn-north-1.snowflakecomputing.cn",
            "myacct.us-gov-west-1.aws.snowflakecomputing.com",
        ],
    )
    def test_accepts_snowflake_domains(self, host):
        validate_cloud_warehouse_params("snowflake", host=host)

    @pytest.mark.parametrize(
        "host",
        [
            "169.254.169.254",
            "localhost",
            "metadata.internal",
            "evil.example.com",
            "snowflakecomputing.com.evil.example",
            "snowflakecomputing.com",
            "myacct.snowflakecomputing.com:8443",
            "myacct.snowflakecomputing.com/path",
            "myacct.snowflakecomputing.comx",
        ],
    )
    def test_rejects_non_snowflake_hosts(self, host):
        with pytest.raises(ValueError, match="Snowflake host"):
            validate_cloud_warehouse_params("snowflake", host=host)

    def test_account_still_validated_independently(self):
        validate_cloud_warehouse_params("snowflake", account="myorg-myacct")
        with pytest.raises(ValueError, match="account"):
            validate_cloud_warehouse_params("snowflake", account="bad/acct")

    def test_connection_validator_rejects_bad_host(self):
        from gateway.api.connections._validation import _validate_connection_params
        from gateway.models import ConnectionCreate

        conn = ConnectionCreate(
            name="sf",
            db_type="snowflake",
            account="myorg-myacct",
            username="u",
            password="p",
            snowflake_host="169.254.169.254",
        )
        errors = _validate_connection_params(conn)
        assert any("Snowflake host" in e for e in errors), errors

        good = conn.model_copy(update={"snowflake_host": "myacct.privatelink.snowflakecomputing.com"})
        assert not [e for e in _validate_connection_params(good) if "host" in e.lower()]

    @pytest.mark.asyncio
    async def test_driver_connect_rejects_bad_host(self, monkeypatch):
        from gateway.connectors.drivers import snowflake as sf_mod

        if not sf_mod.HAS_SNOWFLAKE:
            pytest.skip("snowflake-connector-python not installed")

        called: list[dict] = []

        def fake_connect(**kwargs):
            called.append(kwargs)
            raise AssertionError("driver must not be reached")

        monkeypatch.setattr(sf_mod.snowflake.connector, "connect", fake_connect)
        c = sf_mod.SnowflakeConnector()
        c.set_credential_extras(
            {"account": "myorg-myacct", "username": "u", "password": "p", "snowflake_host": "169.254.169.254"}
        )
        with pytest.raises(ValueError, match="Snowflake host"):
            await c.connect("myorg-myacct")
        assert called == []

    @pytest.mark.asyncio
    async def test_driver_connect_passes_privatelink_host(self, monkeypatch):
        from gateway.connectors.drivers import snowflake as sf_mod

        if not sf_mod.HAS_SNOWFLAKE:
            pytest.skip("snowflake-connector-python not installed")

        seen: dict = {}

        class _Conn:
            def close(self):
                pass

        def fake_connect(**kwargs):
            seen.update(kwargs)
            return _Conn()

        monkeypatch.setattr(sf_mod.snowflake.connector, "connect", fake_connect)
        c = sf_mod.SnowflakeConnector()
        host = "myacct.us-east-1.privatelink.snowflakecomputing.com"
        c.set_credential_extras({"account": "myorg-myacct", "username": "u", "password": "p", "snowflake_host": host})
        await c.connect("myorg-myacct")
        assert seen["host"] == host
