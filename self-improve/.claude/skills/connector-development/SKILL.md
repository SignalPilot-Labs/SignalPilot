---
description: "Use when building new database connectors, modifying the postgres connector, or working with the connector interface. Covers the connector architecture and patterns."
---

# Connector Development

## Current Connectors
- **PostgreSQL** (`gateway/connectors/postgres.py`) — async via asyncpg, readonly transactions

## Connector Interface
Each connector must implement:
```python
async def execute_query(
    connection_string: str,
    sql: str,
    row_limit: int = 1000,
) -> QueryResult:
    """Execute a read-only query and return results."""
    ...
```

## QueryResult Shape
```python
@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool  # True if row_limit was hit
    execution_time_ms: float
```

## Adding a New Connector
1. Create `gateway/connectors/{name}.py`
2. Implement the `execute_query` interface
3. Register in the connector registry
4. Add connection string parsing for the new DB type
5. Write integration tests using test databases

## Postgres Connector Issues to Fix
- Creates new pool per query — should use persistent pool
- No connection timeout configuration
- No query timeout (relies on DB-level timeouts)
- Connection string validation is minimal

## Test Databases Available
- Enterprise OLTP: `postgresql://enterprise_admin:Ent3rpr1se!S3cur3@host.docker.internal:5601/enterprise_prod`
- Analytics Warehouse: `postgresql://warehouse_admin:W4reh0use!An4lyt1cs@host.docker.internal:5602/analytics_warehouse`
