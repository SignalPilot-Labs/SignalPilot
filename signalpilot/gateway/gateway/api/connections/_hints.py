from __future__ import annotations


def _connection_error_hint(db_type: str, error_msg: str) -> str:
    """Generate actionable error hints based on DB type and error message."""
    err_lower = error_msg.lower()

    if any(
        kw in err_lower
        for kw in (
            "connection refused",
            "timed out",
            "unreachable",
            "no route",
            "name or service not known",
            "getaddrinfo",
            "name resolution",
            "errno -2",
            "errno 111",
        )
    ):
        hints = {
            "postgres": "Check: 1) PostgreSQL is running 2) Port 5432 is open 3) pg_hba.conf allows your IP 4) VPN/SSH tunnel is active if remote",
            "mysql": "Check: 1) MySQL is running 2) Port 3306 is open 3) bind-address includes your IP 4) skip-networking is disabled",
            "mssql": "Check: 1) SQL Server is running 2) TCP/IP protocol is enabled in SQL Server Configuration Manager 3) Firewall allows port 1433",
            "clickhouse": "Check: 1) ClickHouse is running 2) Native port 9000 or HTTP port 8123 is open 3) listen_host includes your IP",
            "snowflake": "Check: 1) Account identifier is correct (e.g. xy12345.us-east-1) 2) Network policy allows your IP 3) HTTPS (443) is not blocked",
            "bigquery": "Check: 1) GCP project exists 2) Internet access is available 3) Proxy settings are correct",
            "databricks": "Check: 1) Workspace URL is correct 2) HTTPS (443) is not blocked 3) IP Access List allows your IP",
            "redshift": "Check: 1) Cluster is available 2) Port 5439 is open 3) VPC security group allows your IP 4) Cluster is not paused",
        }
        return hints.get(db_type, "Check hostname, port, firewall rules, and VPN/SSH tunnel settings")

    if any(kw in err_lower for kw in ("authentication", "login failed", "access denied", "password", "credentials")):
        hints = {
            "postgres": "Check: 1) Username and password are correct 2) User exists in PostgreSQL 3) pg_hba.conf allows password auth for this user",
            "mysql": "Check: 1) User exists (SELECT user FROM mysql.user) 2) Password is correct 3) User has GRANT for this host ('%' or specific IP)",
            "mssql": "Check: 1) SQL auth is enabled (not just Windows auth) 2) User/password correct 3) For Azure SQL, use Azure AD if SQL auth disabled",
            "clickhouse": "Check: 1) User exists in users.xml or system.users 2) Password matches 3) User is not restricted by network/IP",
            "snowflake": "Check: 1) Username is correct (case-sensitive) 2) Password is correct 3) User is not locked 4) For key-pair auth, check RSA key format",
            "bigquery": "Check: 1) Service account JSON is valid 2) SA has BigQuery Job User role 3) For OAuth, token is not expired",
            "databricks": "Check: 1) PAT is valid and not expired 2) For OAuth M2M, client_id and client_secret are correct 3) Service principal has workspace access",
            "redshift": "Check: 1) Username and password are correct 2) User exists in pg_user 3) For IAM auth, ensure IAM policy allows redshift:GetClusterCredentials",
        }
        return hints.get(db_type, "Check username, password, and database permissions")

    if any(kw in err_lower for kw in ("database", "not found", "does not exist", "unknown database", "catalog")):
        hints = {
            "postgres": "Check: 1) Database name is spelled correctly (case-sensitive) 2) Run \\l in psql to list databases",
            "mysql": "Check: 1) Database name is spelled correctly 2) Run SHOW DATABASES to list available databases",
            "mssql": "Check: 1) Database name is correct 2) User has CONNECT permission on the database 3) Database is online (not offline/restoring)",
            "clickhouse": "Check: 1) Database exists (SHOW DATABASES) 2) User has access to the database",
            "snowflake": "Check: 1) Database exists (SHOW DATABASES) 2) Role has USAGE on the database 3) Database name is case-correct",
            "bigquery": "Check: 1) Project ID is correct (not project name) 2) Dataset exists in the project",
            "databricks": "Check: 1) Catalog exists in Unity Catalog 2) User has USE CATALOG permission",
            "redshift": "Check: 1) Database exists (SELECT datname FROM pg_database) 2) User has CONNECT permission",
        }
        return hints.get(db_type, "Check that the database name exists and you have access")

    if any(kw in err_lower for kw in ("warehouse", "http_path", "compute")):
        hints = {
            "snowflake": "Check: 1) Warehouse name is correct and exists 2) Warehouse is not suspended 3) Role has USAGE on the warehouse",
            "databricks": "Check: 1) http_path is correct (SQL Warehouse -> Connection Details) 2) SQL Warehouse is running (not stopped)",
        }
        return hints.get(db_type, "Check warehouse/compute resource configuration")

    if any(kw in err_lower for kw in ("ssl", "tls", "certificate", "handshake")):
        return "Check: 1) SSL certificate is valid and not expired 2) CA certificate matches the server's cert chain 3) SSL mode matches server requirements"

    return "Check connection parameters, credentials, and network access"
