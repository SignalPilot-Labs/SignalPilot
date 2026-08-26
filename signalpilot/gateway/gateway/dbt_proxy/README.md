# dbt-proxy — Postgres-wire listener for sandboxed dbt runs

## Overview

The dbt-proxy lets a credential-less sandbox run `dbt` commands against a real
Postgres database by speaking Postgres-wire-protocol v3 to a host-side listener
authenticated by a short-lived run-token.

## Threat model

- **Authentication**: Run-tokens are HMAC-SHA256 over
  `{run_id}:{org_id}:{user_id}:{connector_name}:{expires_at_iso}` with a
  server-side secret. Verification is constant-time (`hmac.compare_digest`).
- **Transport**: Loopback / container-internal only (`host.containers.internal`).
  No TLS in R3 — short TTL + HMAC provides integrity. R8 will add SCRAM/TLS.
- **Governance**: Every statement passes `validate_dbt_statement()` which
  denies COPY, GRANT/REVOKE, privilege escalation, and cross-database
  references before execution. Connector-level credential scoping provides
  tenant isolation.
- **Audit**: Every executed or blocked statement produces exactly one audit row.
- **Token lifecycle**: Tokens are in-memory only; gateway restart invalidates
  all live runs. Tokens expire after `ttl_seconds` (60–86400 s).

## Port

Single static port: `SP_DBT_PROXY_PORT` (default `15432`). No per-run port
allocation. All concurrent dbt runs share the listener; auth resolves the
run-token to the correct tenant and connector.

## Supported Postgres-wire message types

### Backend (server → client)
| Type | Code | Description |
|---|---|---|
| AuthenticationCleartextPassword | R(3) | Request password from client |
| AuthenticationOk | R(0) | Auth successful |
| ErrorResponse | E | Error with SQLSTATE |
| ReadyForQuery | Z | Backend ready for next query |
| RowDescription | T | Column metadata |
| DataRow | D | One result row |
| CommandComplete | C | Command completed (e.g. "SELECT 5") |
| ParameterStatus | S | Server parameter value |
| BackendKeyData | K | Process ID + cancel key |

### Frontend (client → server)
| Type | Code | Description |
|---|---|---|
| StartupMessage | (no type byte) | v3 startup |
| PasswordMessage | p | Cleartext token |
| SimpleQuery | Q | Full SQL statement |
| Parse | P | Extended query: named statement |
| Bind | B | Extended query: bind parameters |
| Describe | D | Extended query: describe portal |
| Execute | E | Extended query: execute portal |
| Sync | S | Flush extended query cycle |
| Terminate | X | Close connection |

## Supported parameter type OIDs (Bind messages)

| OID | Type |
|---|---|
| 23 | int4 |
| 20 | int8 |
| 25 | text |
| 1043 | varchar |
| 16 | bool |
| 1184 | timestamptz |
| 1700 | numeric |
| 701 | float8 |

Any other OID → `ErrorResponse SQLSTATE 0A000 unsupported_parameter_oid`.

## R3 limits

- No SSL/TLS (loopback only; R8 target).
- No COPY, LISTEN/NOTIFY, cursor protocol.
- No real server-side prepared-statement caching (Extended Query → inline substitution).
- Schema-ownership enforcement deferred to R7.
- Session count limit per run_id not enforced (R3 allows concurrent sessions within TTL).

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `SP_DBT_PROXY_HOST` | `0.0.0.0` | Bind host |
| `SP_DBT_PROXY_PORT` | `15432` | Single listener port |
| `SP_GATEWAY_RUN_TOKEN_SECRET` | (required) | HMAC secret for run-token signing |
| `SP_DBT_PROXY_ENABLED` | `true` | When false, mint returns 503 |
