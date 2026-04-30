---
sidebar_position: 3
---

# How It Works

SignalPilot sits between your AI agent and your databases, governing every query.

## Query lifecycle

```
Agent  -->  MCP request  -->  Gateway  -->  SQL Governance  -->  Database
                                  |
                            Auth + Rate Limit
                                  |
                            Audit Log (PII-redacted)
```

1. **Agent sends a tool call** via MCP (e.g. `query_database`)
2. **Auth layer** validates the API key or Clerk JWT and resolves the org/tenant
3. **Rate limiter** checks per-key and per-org limits
4. **SQL governance** parses the query, blocks DDL/DML, strips dangerous functions, injects LIMIT
5. **Engine** executes against the target database
6. **Audit** logs the query with SQL literals redacted for PII protection
7. **Response** returned to the agent

## Governance rules

- **DDL/DML blocked**: No `CREATE`, `DROP`, `ALTER`, `INSERT`, `UPDATE`, `DELETE`
- **Dangerous functions blocked**: 79+ functions across 7 SQL dialects (e.g. `pg_read_file`, `LOAD_FILE`, `xp_cmdshell`)
- **LIMIT injection**: Every SELECT gets a configurable max row limit
- **INTO clause blocked**: Prevents `SELECT INTO` / `COPY TO` exfiltration
- **Stacking prevented**: Multi-statement queries are rejected

## Tenant isolation

Every API key is scoped to an organization. Queries can only access connections owned by that org. Cross-tenant access is impossible at the data layer.
