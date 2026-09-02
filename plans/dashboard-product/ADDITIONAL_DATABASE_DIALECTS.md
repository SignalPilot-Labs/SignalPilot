# Additional dashboard database dialects plan

- **Date:** 2026-09-01
- **Updated:** 2026-09-02
- **Status:** implemented locally; live staging acceptance pending
- **Roadmap source:** `plans/dashboard-product/PLAN.md`, Phase 10
- **Release posture:** make every gateway-registered connector dashboard-capable; validate PostgreSQL and DuckDB as the two representative new live database paths alongside MSSQL

## Objective

Enable governed dashboards on every database connector registered in the SignalPilot gateway, while preserving one dashboard domain, one semantic resolver, and one governed execution path. Dashboard capability is part of the gateway connector contract, not a separate product allowlist.

The first delivery extracts current MSSQL behavior into the shared connector/dialect contract without changing generated SQL or saved dashboard behavior. It then implements that contract for every connector currently present in the gateway registry. Two representative non-MSSQL databases prove the shared live integration contract: PostgreSQL in Docker and DuckDB against a temporary local database.

These are the only new live dashboard database suites required by this plan. Together with the existing MSSQL proof they cover the three binding families used by the initial adapters (`$n`, `?`, and `%s`), remote and embedded execution, `LIMIT` and `TOP`, and ANSI/double-quote versus bracket quoting. Every other registered connector is still implemented for dashboards and receives adapter-level golden SQL, native-binding, schema-normalization, governance, and safety coverage plus its existing connector tests; it does not require a separate live dashboard environment in this phase.

This is not a feature-flag rollout. Every gateway-registered connector must be available to dashboard authoring when its project connection and credentials are valid.

## Current state

SignalPilot already registers connectors for PostgreSQL, DuckDB, MySQL, Snowflake, BigQuery, Redshift, ClickHouse, Databricks, MSSQL, Trino, SQLite, and Xata. The target product invariant is that gateway registration includes dashboard compatibility. The current implementation violates that invariant because the dashboard path is still MSSQL-specific.

The dashboard path remains MSSQL-specific:

| Boundary           | Current behavior                                                | Required change                                                                              |
| ------------------ | --------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| Semantic resolver  | Rejects every project connection whose `db_type` is not `mssql` | Resolve the server-owned connection type through its connector-owned dashboard contract      |
| Semantic compiler  | Uses MSSQL identifier quoting and relation syntax               | Route all identifier, relation, expression, and alias rendering through the selected dialect |
| Bound filters      | Emits `%s` and the governed executor counts/restores `%s`       | Use a typed parameter-binding contract that renders the target driver's native bindings      |
| Distinct values    | Uses `TOP`, `NVARCHAR`, and `[value]`                           | Compile limits, text search, casts, and aliases through the dialect                          |
| Custom SQL filters | Wraps SQL with `[sp_dashboard]` and MSSQL predicates            | Use a dialect-safe derived table and declared-output predicates                              |
| Diagnostics        | Labels every query `Compiled MSSQL`                             | Return and display the actual authorized connection type                                     |
| New-dashboard UI   | Lists all active projects, although only MSSQL executes today   | Treat every valid gateway-registered project connection as dashboard-capable                 |

Existing database-neutral behavior must remain unchanged: dashboard definitions, semantic field IDs, confidence, immutable versions, result ownership, cache rules, authorization, export, analysis references, and explicit Apply.

## Product and architecture contract

- Every database type in the gateway connector registry is dashboard-compatible. The registry entry must own or resolve its `DashboardDialect` and native-binding contract.
- Do not create an independently curated dashboard-support registry or allowlist. Add a registry-completeness test that fails when a gateway connector lacks its dashboard contract.
- A database type absent from the gateway registry remains an unknown connection type and fails closed. A registered connector with an incomplete dashboard contract is a build/release failure, not a user-selectable partially supported state.
- Use PostgreSQL and DuckDB as the two representative live dashboard tests. Do not require a separate live dashboard environment for every remaining connector.
- The two representative tests validate the shared adapter/execution architecture; they do not reduce the implementation scope. Every currently registered connector still needs a complete dialect, safe native bindings, schema normalization, and deterministic dashboard fixtures.
- Keep one `DashboardDefinition`, `DashboardSemanticResolver`, governed executor, cache, receipt, and authorization model. Dialects compile SQL; they do not create parallel dashboard products.
- Resolve the database type from the organization-scoped project connection. Never trust a browser-supplied dialect.
- Keep parameter values separate from SQL at every boundary. Never interpolate runtime filter, drill, search, or authoring values into query text.
- Custom SQL remains low confidence, requires explicit confirmation, and accepts runtime filters only through declared typed output bindings around the immutable inner query.
- Existing MSSQL definitions and results remain backward compatible. No destructive migration or stored-definition rewrite is allowed.
- Do not add a rollout feature flag, organization allowlist, connector-tier inference, or fallback to MSSQL/PostgreSQL syntax.

## Representative database test set

### Test database A — PostgreSQL 17 in Docker

PostgreSQL is the remote relational representative. It is easy to provision in Docker, broadly useful, and exercises the async connector plus positional `$1`, `$2`, ... bindings that the current `%s`-specific governed path cannot handle.

The test owns a disposable Compose service and must not depend on a developer's existing warehouse. Record before live staging acceptance:

- Docker Compose file/service: `signalpilot/gateway/tests/fixtures/dashboard-postgres-compose.yml`, service `dashboard-postgres` (`postgres:17`, random host port)
- Disposable database/schema: database `signalpilot_dashboard`, schema `analytics`; container and volume removed after the test
- Staging organization: **TBD**
- Connection name: **TBD**
- Project, branch, and immutable snapshot: **TBD**
- Acceptance owner: **TBD**

### Test database B — DuckDB temporary file

DuckDB is the embedded analytics representative. It starts in-process without Docker or cloud credentials, uses native `?` bindings, supports deterministic fixture creation, and exercises the file-backed transient read-only connector path.

The test creates and seeds a temporary `.duckdb` file before SignalPilot opens it. It must not use a developer's persistent Nala database or write outside the test temporary directory.

### Coverage inference

| Existing/new proof  | Native bindings | Identifier/limit family                   | Runtime shape                      |
| ------------------- | --------------- | ----------------------------------------- | ---------------------------------- |
| Existing MSSQL      | `%s`            | brackets, `TOP`, `NVARCHAR`               | remote synchronous DB-API          |
| New PostgreSQL test | `$1`, `$2`, ... | double quotes, `LIMIT`, PostgreSQL casts  | remote asynchronous pool           |
| New DuckDB test     | `?`             | double quotes, `LIMIT`, ANSI/DuckDB casts | embedded transient file connection |

Passing these three representative paths is sufficient for shared live-integration acceptance, but not for connector-registry parity. This release must also implement MySQL, Snowflake, BigQuery, Redshift, ClickHouse, Databricks, Trino, SQLite, and Xata dashboard contracts with safe native bindings, golden SQL/injection fixtures, schema-normalization fixtures, and their existing connector suites. A connector whose driver introduces a binding or execution model not covered by MSSQL/PostgreSQL/DuckDB must add deterministic coverage for that model; another full live dashboard environment remains optional unless implementation evidence or a customer rollout requires it.

## Work package 1 — Characterize and extract MSSQL without behavior changes

### Tasks

- Add golden characterization fixtures for the current MSSQL output of:
  - semantic KPI aggregation;
  - grouped table/bar/line/area queries;
  - sorts and row limits;
  - equality, multi-value, null, range, relative-date, dashboard, cross-filter, and drill predicates;
  - custom-SQL outer predicates;
  - distinct values with and without search;
  - empty-result output schema.
- Introduce a `DashboardDialect` protocol owned or resolved by each gateway connector registration. Its minimum contract covers:
  - stable database type and SQLGlot dialect names;
  - identifier and one/two/three-part relation quoting;
  - bound-parameter token creation and final driver rendering;
  - row-limit rendering where compilation owns the limit;
  - string casts and case-sensitive/insensitive search semantics;
  - derived-table aliases;
  - date/timestamp expressions and any required coercion;
  - distinct-value query construction.
- Implement `MssqlDashboardDialect` by moving the existing behavior behind that contract.
- Make the compiler require an explicit dialect. Do not retain global MSSQL helpers as a silent default.
- Extend the gateway connector registration model so registering a connector without a complete dashboard dialect/binding contract fails the registry-completeness test.
- Preserve current MSSQL SQL byte-for-byte where practical; document any intentional normalized difference and prove equivalent governed results.

### Tests

- Existing dashboard compiler tests remain green.
- Golden MSSQL SQL snapshots cover every item above.
- Invalid identifiers, empty relation parts, excessive relation depth, and null bytes remain rejected.
- A missing or unknown dialect raises a typed dashboard compatibility error before compilation or execution.

### Done when

- MSSQL runs through the registry with no saved-definition change and no dashboard behavior regression.

## Work package 2 — Make governed parameter execution dialect-aware

### Problem

`GovernedQueryExecutor` currently validates parameter count by counting `%s`, replaces those markers with numeric sentinels for SQLGlot/governance analysis, injects a row limit, then restores `%s`. That works for the current MSSQL dashboard path but is not a valid cross-driver contract.

### Tasks

- Introduce a typed bound-query representation with:
  - SQL containing unambiguous internal parameter tokens;
  - an ordered parameter list;
  - the selected database type/dialect;
  - rendering rules for the target connector;
  - a redacted/display SQL form containing placeholders but no values.
- Reject missing, duplicate, reordered, unused, or extra tokens before contacting a connector.
- Replace internal tokens with safe typed sentinels only for SQLGlot parsing, normalization, denylist checks, table extraction, cost estimation, and limit injection.
- Render native driver placeholders only after governance has accepted the query.
- Preserve normalized SQL hashing without including parameter values; preserve the separate parameter hash used by dashboard cache identity.
- Extend connector execution only where the selected adapter requires it. Do not silently ignore a non-empty parameter list.
- Add explicit capability checks for engines whose current drivers do not yet bind parameters correctly. Repair and test those driver paths as part of this plan; a registered connector cannot pass the release gate while remaining dashboard-incompatible.
- Keep cancellation, timeout handling, row-limit-plus-one completeness, query receipts, and audit behavior in the shared governed executor.
- Prove ordinary REST/MCP/Data Chat queries are unchanged; do not create a dashboard-only executor.

### Required binding fixtures

The suite must cover at least:

- MSSQL `%s` DB-API bindings.
- PostgreSQL `$1`, `$2`, ... bindings.
- DuckDB `?` bindings.
- The verified native binding contract for every other gateway-registered connector, including any named-parameter or driver-specific execution model not represented by the three live databases.
- Repeated values bound as separate positions.
- Strings containing `%s`, `?`, `$1`, or internal-token-like text that are not parameters.
- Datetime, date, number, boolean, null, Unicode, wildcard search, and multi-value `IN` values.
- Governance rejection before connector acquisition for malformed binding contracts.

### Done when

- The governed executor can validate, limit, hash, and execute bound queries using every registered connector's verified native binding style without interpolating values.

## Work package 3 — Implement dashboard dialects for every registered connector

### Tasks

- Add dashboard dialect/native-binding contracts for every current gateway connector: PostgreSQL, DuckDB, MySQL, Snowflake, BigQuery, Redshift, ClickHouse, Databricks, MSSQL, Trino, SQLite, and Xata.
- Keep PostgreSQL and DuckDB as the two new representative live paths; the remaining connectors use deterministic adapter, schema, binding, governance, and connector-suite coverage in this phase.
- Compile the complete semantic-query subset through it:
  - dimensions and approved metric aggregations;
  - grouping and ordering;
  - runtime filters and declared per-tile targets;
  - cross-filters and ordered drills;
  - relative date windows in the dashboard timezone;
  - limits and limit-plus-one completeness;
  - distinct values and search.
- Compile custom-SQL outer filtering through the same adapter:
  - preserve the user-confirmed inner SQL;
  - use a valid derived-table alias;
  - reference only declared output bindings;
  - bind every filter value natively;
  - retain low-confidence classification.
- Verify relation resolution for every engine's catalog/database/schema/table shape. Do not assume MSSQL's optional database plus schema naming convention.
- Reuse the existing SQLGlot dialect mapping and reviewed dangerous-function policy. If either is missing for a registered connector, implement it before the registry-parity gate can pass.
- Ensure the authoring prompt/context states the actual database type and prohibits syntax from other dialects, placeholders, or unknown explores.
- Keep compiler/server semantic validation final after agent generation and repair retries.

### Golden SQL matrix

For every gateway-registered connector, assert equivalent query intent across:

| Capability      | Required cases                                                                  |
| --------------- | ------------------------------------------------------------------------------- |
| Identifiers     | reserved words, spaces, embedded quote characters, qualified relations          |
| Metrics         | sum, count, count distinct, average, min, max                                   |
| Filters         | equals, multi-value, null/not-null, range, relative dates, timestamps/timezones |
| Interactions    | global filters, cross-filter, drill, explicit per-tile mapping                  |
| Custom SQL      | derived table, declared output binding, multiple predicates, trailing semicolon |
| Distinct values | bounded result, search, null exclusion, deterministic ordering                  |
| Completeness    | unbounded input, existing smaller limit, limit-plus-one truncation proof        |
| Safety          | injection payloads in identifiers, search, values, and custom binding metadata  |

### Done when

- All dashboard compiler paths have golden tests for every registered connector, every connector uses its verified native binding style, and no connector accidentally receives MSSQL or another engine's syntax.

## Work package 4 — Resolve semantic context from the real connection type

### Tasks

- Change `DashboardSemanticResolver.resolve()` to:
  - load the organization-scoped active project;
  - load its organization-scoped connection;
  - resolve `connection.db_type` through its gateway connector registration and required dashboard contract;
  - return a typed unknown-connection-type error when the type is absent from the gateway registry;
  - load schema through the existing pool, cache, endorsements, and include/exclude filters;
  - pass the real connection type into `resolve_from_authorities()` and `DashboardSemanticContext`.
- Characterize schema normalization for every registered connector: relation keys, catalog/database, schema, table names, case folding, quoted case, and physical column types.
- Keep durable workspace snapshot, project map, approved metrics, semantic model, verification references, and semantic fingerprint derivation shared.
- Include the connection type in semantic fingerprint input if changing a connection's type under the same name could otherwise preserve the fingerprint.
- Continue verifying that saved dashboard/project connection names and chart bindings match the server-resolved context.
- Return stable safe error codes for:
  - no project connection;
  - missing credentials;
  - unknown/unregistered connection type;
  - schema unavailable;
  - semantic context changed.

### Tests

- Same-organization connections resolve successfully for every registered connector fixture.
- An unknown connection type absent from the gateway registry fails before connector acquisition.
- Missing, cross-organization, and mismatched connections remain inaccessible.
- Schema/cache/endorsement/include/exclude behavior works for every registered connector through deterministic fixtures, with MSSQL, PostgreSQL, and DuckDB also covered by the representative live matrix.
- Changing connection type or semantic authorities invalidates the pinned context instead of reusing an incompatible cache entry.

### Done when

- The semantic endpoint returns the actual registered connection type and a valid immutable context for every gateway connector.

## Work package 5 — Publish connector readiness and fix setup UX

### Server contract

- Add a small server-authoritative dashboard readiness model derived from the gateway connector registry. It must return:
  - project ID and connection name;
  - resolved database type when available;
  - `registered: true|false`;
  - stable reason code such as `connection_missing`, `connection_type_unknown`, `credentials_missing`, or `ready`;
  - a sanitized actionable message.
- Prefer enriching the project bootstrap used by `/dashboards/new`, or add one batched dashboard-project-capabilities endpoint. Avoid one request per project.
- Derive readiness from the gateway connector registration plus project connection and credential state. Do not maintain a frontend or dashboard-specific database allowlist.
- Recheck readiness on every authoring/session/preview/Apply request; an already-open page must not bypass a connection change.

### Frontend tasks

- Update `/dashboards/new` so every project backed by a gateway-registered connector is selectable when its connection and credentials are ready.
- Show projects with missing connections, missing credentials, or unknown legacy connection types in a setup list with a link to project connection settings; do not print a serialized 422.
- Distinguish:
  - no project;
  - project without connection;
  - registered connection missing other authoring prerequisites;
  - unknown legacy connection type not present in the gateway registry;
  - billing/authorization failure.
- Keep project settings able to assign any general SignalPilot connection; dashboard compatibility must not narrow Data Chat or notebook capabilities.
- Add `connection_type` or a safe dialect label to dashboard query receipts and render `Compiled <dialect>` in technical details.
- Keep technical SQL collapsed and business-facing dashboard UI unchanged.

### Tests

- Every project using a registered, credentialed connector can create/continue/preview/Apply normally.
- Projects with missing credentials or an unknown connection type cannot start or restore authoring and receive an actionable setup state.
- A project changed to a missing or unknown connection while a session is open fails closed on the next mutation.
- No frontend hard-coded database allowlist can diverge from the gateway registry.
- Inspector diagnostics show the receipt's actual dialect and never expose credentials or parameter values.

### Done when

- Users can see connection readiness before starting authoring, every registered connector is available, and direct API calls enforce the identical boundary.

## Work package 6 — Live connector and dashboard golden-path acceptance

### Automated local gates

- Dashboard compiler, semantic resolver, domain, authoring, operations, store, telemetry, and HTTP authorization tests.
- Governed execution parameter, SQL dialect, denylist, table extraction, limit injection, cancellation, timeout, and completeness tests.
- Connector-specific deterministic dashboard tests for every registered connector, plus live focused tests for PostgreSQL and DuckDB.
- Frontend unit tests for project selection, setup states, runtime, authoring, inspector, and API contracts.
- Dashboard-scoped and full TypeScript checks.
- Gateway Ruff check and format check on touched Python files.
- Production frontend and gateway image builds.
- `git diff --check`.

### Required representative database test 1 — PostgreSQL Docker dashboard path

Add one named end-to-end test, `test_postgres_dashboard_golden_path`, in a focused dashboard dialect integration file.

#### Setup

- Start a disposable `postgres:17` service through a test-owned Compose definition with a health check and randomly available host port.
- Create a representative `analytics` schema containing a dated fact table and a dimension table, including enough rows to prove limit-plus-one completeness.
- Materialize a minimal project snapshot, dbt model metadata, approved metrics, organization-scoped connection, and dashboard definition against that fixture.
- Tear down the container and volumes after the suite. Do not reuse the gateway metadata PostgreSQL database or a developer's Nala warehouse.

#### Assertions

- Semantic resolution reports `connection_type=postgres`, resolves the expected relations/columns/metrics, and produces a stable fingerprint.
- Semantic queries, runtime filters, drills, distinct-value search, and custom-SQL outer predicates render PostgreSQL quoting and ordered `$1`, `$2`, ... bindings with values kept separate.
- The real `asyncpg` connector executes those bindings through `GovernedQueryExecutor`; SQL validation, denylist checks, table extraction, limit injection, timeout, and cancellation remain active.
- KPI, table, bar, line, and area receipts are complete and match their declared output columns.
- One exact version can be created/reopened from cache, while a changed filter produces a different parameter/cache identity.
- A malicious filter/search value is returned only as data or matches nothing; it never changes query structure or appears in compiled SQL, logs, telemetry, or receipts.
- The test is required in the dashboard dialect CI job. Once that job provisions Docker, an unavailable container is a failure rather than a successful skip.

### Required representative database test 2 — DuckDB temporary-file dashboard path

Add a second named end-to-end test, `test_duckdb_dashboard_golden_path`, alongside the PostgreSQL test.

#### Setup

- Create a temporary `.duckdb` file under pytest's `tmp_path`, seed the same logical fact/dimension fixture, and close the setup connection before the SignalPilot connector opens it.
- Create the minimal project snapshot, dbt metadata, approved metrics, connection, and dashboard definition against that file.
- Use the production file-backed transient read-only connector path. Do not use the persistent Nala DuckDB file and do not leave any artifact after the test.

#### Assertions

- Semantic resolution reports `connection_type=duckdb` and normalizes the expected catalog/schema/table and physical types.
- Semantic queries, filters, drills, distinct-value search, and custom-SQL outer predicates render DuckDB/ANSI syntax and ordered `?` bindings with values kept separate.
- The real DuckDB connector executes those bindings through `GovernedQueryExecutor`; validation, denylist checks, table extraction, `LIMIT`, and limit-plus-one completeness behave identically to the PostgreSQL path.
- KPI, table, bar, line, and area receipts are complete and match the PostgreSQL fixture's logical results.
- File-backed cancellation retains and interrupts the active transient connection, records a typed cancelled execution, and leaves the connector usable for the next query.
- Exact cache reopen and changed-filter cache identity match the PostgreSQL test's behavior.
- The test runs without Docker, network, cloud credentials, or a conditional skip when gateway development dependencies are installed.

### Two-test acceptance rule

These two tests, plus the existing MSSQL regression proof, are the complete live database matrix for this phase. Do not add full live dashboard suites for every registered connector.

This limited live matrix does not narrow product support. Every gateway-registered connector must be dashboard-capable and selectable at the exit gate. Each receives an explicit dialect/binding implementation, golden compiler/injection fixtures, schema-normalization fixtures, governance coverage, and its existing connector tests. If a connector uses a binding or runtime model not represented by MSSQL/PostgreSQL/DuckDB—such as BigQuery named query parameters—the missing shared capability must be implemented and unit-tested, but another full dashboard golden-path environment is optional unless a defect or customer rollout makes it necessary.

### Live staging prerequisites

- PostgreSQL fixture identifiers recorded in the representative database test set.
- One project snapshot containing the fixture's dbt models and approved metrics.
- Organization Anthropic credential for authoring acceptance.
- Owner and organization-viewer accounts plus a separate unauthorized organization.
- Observable query execution and dashboard telemetry.
- Permission to run read-only staging queries and create a disposable private dashboard/version.

DuckDB acceptance remains local and deterministic; it does not require a staging organization.

### Live golden path

1. Test and assign the PostgreSQL connection to its project.
2. Fetch semantic context and verify exact database type, relations, fields, approved metrics, fingerprints, and immutable snapshot.
3. Author KPI, table, bar, line, and area charts using semantic queries.
4. Add a bounded default date filter, explicit per-tile target, cross-filter, and lower-grain drill.
5. Add one explicitly confirmed custom-SQL chart with a declared output binding.
6. Preview every chart through governed execution and verify native bound parameters, timeout, cancellation, and complete results.
7. Apply exactly one immutable private version and reopen it from an exact cache.
8. Refresh after TTL and verify stale-while-refresh behavior without polling or duplicate refresh.
9. Stop or deny the data source in the disposable test path: exact cached results remain visible; no-cache tiles show the typed source failure; Retry recovers once.
10. Share with the organization, verify viewer authorization, export self-contained HTML, fork privately, and confirm cross-organization denial.
11. Run Analyze this change with the frozen chart/result reference.
12. Inspect receipts and telemetry: actual dialect, permitted SQL, hashes, completeness, freshness, cache state, and no sensitive values.
13. Run `test_duckdb_dashboard_golden_path` against a fresh temporary file.
14. Re-run the existing MSSQL golden path to prove backward compatibility.

### Done when

- PostgreSQL, DuckDB, and MSSQL pass their required paths from a clean tested commit. Evidence identifies the PostgreSQL container/fixture and confirms that DuckDB used an isolated temporary file.

## Implementation sequence and focused commits

1. `test(dashboards): characterize current mssql compilation`
2. `refactor(dashboards): introduce connector-owned dialect contract`
3. `refactor(governance): support typed native query bindings`
4. `test(governance): cover cross-driver bound parameters`
5. `feat(dashboards): add postgres and duckdb dialect compilers`
6. `feat(dashboards): add all registered connector dialects`
7. `test(dashboards): enforce gateway connector dashboard parity`
8. `feat(dashboards): resolve project connection dialect`
9. `feat(dashboards): publish project connection readiness`
10. `feat(web): enable authoring for every registered connector`
11. `test(dashboards): add postgres and duckdb golden paths`
12. `docs(dashboards): record connector parity and representative acceptance evidence`

Each commit must preserve unrelated worktree changes. Do not include `docker-compose.dev.yml`, `plugin/`, or other unrelated paths unless they become explicitly required and are separately authorized.

## Validation commands

Finalize exact selections after implementation based on touched files, but the minimum local gate is:

```bash
cd signalpilot/gateway
uv run ruff check gateway/dashboard gateway/governance/query_executor.py gateway/api/dashboards.py tests/test_dashboards.py tests/test_dashboard_authoring.py tests/test_dashboard_http_authorization.py
uv run pytest -q tests/test_dashboards.py tests/test_dashboard_authoring.py tests/test_dashboard_domain.py tests/test_dashboard_http_authorization.py tests/test_limit_enforcement.py tests/test_sql_governance_dialects.py
```

```bash
cd signalpilot/web
npm run typecheck
npm run test:unit -- components/dashboard lib/dashboard
npm run build
```

Also run `test_postgres_dashboard_golden_path`, `test_duckdb_dashboard_golden_path`, the existing MSSQL regression suite, production gateway image build, and `git diff --check`. A skipped required representative test is an incomplete gate, not a pass.

## Rollback

- Redeploy the prior compatible web/gateway images or revert the defective connector/dialect implementation as one coherent release.
- Existing immutable dashboards and results remain stored; do not delete or rewrite definitions.
- Do not keep a connector in the gateway registry while disabling it only for dashboards. If an emergency requires removing a connector registration, treat the resulting impact to all gateway products as an explicit operational decision.
- Authorized exact historical result access remains governed by the existing result/export rules while live execution is unavailable.
- Do not run a destructive down migration. This plan should require no dashboard storage migration unless implementation evidence proves otherwise.

## Exit gate

- PostgreSQL and DuckDB pass their named end-to-end dashboard tests; PostgreSQL also passes the staging semantic, governed execution, interaction, caching, authoring, Apply/reopen, failure recovery, export, analysis, and authorization flow.
- MSSQL generated SQL and runtime behavior remain backward compatible.
- Every database type in the gateway connector registry has a complete dashboard dialect/binding contract and passes deterministic compiler, schema, governance, and safety coverage.
- Every project using a registered connector is available in dashboard project selection when its connection and credentials are valid.
- Unknown database types absent from the gateway registry fail closed in both UI and API; an incomplete registered dashboard contract fails CI and cannot ship.
- All runtime values remain natively bound and absent from SQL, logs, telemetry, and technical receipts.
- No feature flag, parallel dashboard domain, duplicate semantic service, connector-tier inference, or syntax fallback is introduced.
- Live staging evidence identifies the organization, project snapshot, connection type/name, fixture, tested commit, and any remaining external gate.

## Implementation evidence — 2026-09-02

Implemented in the local repository without a feature flag or storage migration:

- The gateway connector registry now owns a complete dashboard dialect and native-binding contract for PostgreSQL, DuckDB, MySQL, Snowflake, BigQuery, Redshift, ClickHouse, Databricks, MSSQL, Trino, SQLite, and Xata. A registry-completeness test makes a missing contract a release failure.
- Dashboard compilation, distinct values, custom-SQL outer filters, semantic fingerprints, authoring context, governed execution, receipts, and project readiness now use the server-resolved connection type. Unknown connection types and removed credentials fail closed with stable safe codes.
- Typed internal parameter tokens are validated before connector acquisition, replaced with value-free sentinels for governance, and rendered to `%s`, `$n`, `?`, or named pyformat bindings only after validation and limit injection.
- BigQuery now builds typed positional query parameters, Trino forwards its positional values, and ClickHouse receives named values. DuckDB retains the active transient connection so cancellation works and a subsequent query remains usable.
- Dashboard project selection exposes server-authoritative readiness and a safe product dialect label. Technical details show `Compiled <dialect>` while keeping SQL collapsed.
- The required PostgreSQL test uses the disposable Compose service above and tears down its volume. The required DuckDB test creates its database only below pytest `tmp_path` and leaves no persistent repository artifact.

Local acceptance results:

- `485 passed` — dashboard compiler, semantic/domain/authoring, operations, authorization, governance, readiness, PostgreSQL Docker, and DuckDB suites (required representative tests were executed, not skipped).
- `48 passed` — focused dashboard, dialect-label, and project-picker web unit tests.
- TypeScript check and production Next.js build passed.
- Gateway Ruff check and format gate passed on every touched Python path.
- Production `signalpilot-gateway:latest` image build passed.
- `git diff --check` passed, and the PostgreSQL Compose test left no `sp-dashboard-*` container running.

The separate staging workflow remains external to this local implementation: no staging organization, organization Anthropic credential, project snapshot, connection name, acceptance owner, or authorization accounts were supplied, so no staging data or dashboard was mutated. Those identifiers remain the explicit release gate rather than being represented as local proof.

A broader legacy connector sweep produced `127 passed, 66 skipped, 13 failed`. The 13 failures are stale pre-existing test assumptions unrelated to this change: eight instantiate an abstract `_ConcreteConnector` fixture without its required implementations, and five inspect inherited public wrapper source instead of the connector's `_get_schema_impl`. They are not counted as acceptance evidence for this plan.

## Out of scope

- Provisioning and running a separate live dashboard environment for every registered connector.
- Supporting a future connector before it is added to the gateway registry; once registered, dashboard capability is mandatory in the same change.
- Building new general-purpose database connectors.
- Replacing the existing semantic model, dbt project model, governed executor, dashboard store, or cache.
- Cross-database joins or one dashboard spanning multiple connections.
- Browser-authored string substitution or unbound query parameters.
- Changing custom SQL confidence or confirmation policy.
- Redesigning the dashboard renderer, visualization contract, or immutable version model.
- Deploying, changing staging connections, creating live dashboards, or publishing to GitHub as part of writing this plan.
