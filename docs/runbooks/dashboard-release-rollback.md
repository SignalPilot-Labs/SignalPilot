# Dashboard release rollback

Use this runbook only for the global dashboard release. Dashboard schema changes are additive: rollback changes the web and gateway binaries, keeps the dashboard tables and rows, and never runs a destructive down migration.

## Ownership and decision threshold

- Operator: the release operator named in the completed dashboard release manifest.
- Approver: the incident commander named in that manifest.
- Roll back immediately for any cross-organization disclosure, unauthorized durable mutation, corrupted immutable version lineage, or HTML export containing an unauthorized result.
- Roll back when dashboard opens fail above 5% for 10 consecutive minutes, query failures exceed the pre-release baseline by 10 percentage points for 10 minutes, or recovery Retry fails for three consecutive probes.
- Do not roll back for one isolated tile failure while exact cached fallback is healthy; investigate and use the bounded retry path.

## Pinned images

The previous pair was built from `0e39f91687caf6f67e0e712e97af9c50b4479c96` and is the rollback target for this remediation release.

```sh
export SP_PREVIOUS_GATEWAY_IMAGE='signalpilot-phase7-gateway@sha256:4a03a814f3d18b6bb6e7fad7abfd8b558834b65092037c73617307e3fce0303e'
export SP_PREVIOUS_WEB_IMAGE='signalpilot-phase7-web@sha256:c2b99e08b55530a0f83d3deaca57bccb0f3e9c2430466833e8f1be3038c817e0'
export SP_CURRENT_GATEWAY_IMAGE='signalpilot-phase7-gateway@sha256:7ab1c8e43e5697e408ee1d025654ace63c6f883612028074120e3205eaa7d295'
export SP_CURRENT_WEB_IMAGE='signalpilot-phase7-web@sha256:82205de4ed084d1ca3e5b2b90bde04787e1d8f071d30c7cbb1f7a96c30255e71'
```

Do not use mutable tags in a release manifest. Confirm all four references resolve before migration or deployment:

```sh
docker image inspect "$SP_PREVIOUS_GATEWAY_IMAGE" --format '{{.Id}}'
docker image inspect "$SP_PREVIOUS_WEB_IMAGE" --format '{{.Id}}'
docker image inspect "$SP_CURRENT_GATEWAY_IMAGE" --format '{{.Id}}'
docker image inspect "$SP_CURRENT_WEB_IMAGE" --format '{{.Id}}'
```

## Preflight

Run from the tested clean commit and attach the output to the evidence report.

```sh
git status --short
git rev-parse HEAD
docker compose config --quiet
docker compose ps
curl --fail --silent --show-error http://127.0.0.1:3300/health
curl --fail --silent --show-error http://127.0.0.1:3200/ >/dev/null
```

Record the migration/schema evidence before changing binaries:

```sh
docker compose exec -T db psql -U signalpilot -d signalpilot -v ON_ERROR_STOP=1 -c \
  "SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'gateway_dashboard%' ORDER BY table_name;"
docker compose exec -T db psql -U signalpilot -d signalpilot -v ON_ERROR_STOP=1 -c \
  "SELECT data_type, character_maximum_length FROM information_schema.columns WHERE table_name='gateway_audit_logs' AND column_name='event_type';"
```

## Roll back the binaries

These commands preserve Postgres and every dashboard table. `--no-build` prevents an accidental source rebuild.

```sh
GATEWAY_IMAGE="$SP_PREVIOUS_GATEWAY_IMAGE" WEB_IMAGE="$SP_PREVIOUS_WEB_IMAGE" \
  docker compose up -d --no-build --force-recreate gateway gateway-chat-worker web
docker compose ps gateway gateway-chat-worker web
```

If the orchestrator is not Docker Compose, set the gateway, chat worker, and web workloads to the same pinned pair and wait for their normal readiness gates. Do not change database migration state.

## Health and role smoke checks

```sh
curl --fail --silent --show-error http://127.0.0.1:3300/health
curl --fail --silent --show-error http://127.0.0.1:3200/ >/dev/null
curl --fail --silent --show-error -H "Authorization: Bearer $OWNER_TOKEN" \
  "$SP_GATEWAY_URL/api/dashboards/$SP_PILOT_DASHBOARD_ID" >/tmp/sp-owner-dashboard.json
curl --fail --silent --show-error -H "Authorization: Bearer $VIEWER_TOKEN" \
  "$SP_GATEWAY_URL/api/dashboards/$SP_PILOT_DASHBOARD_ID" >/tmp/sp-viewer-dashboard.json
test "$(curl --silent --output /tmp/sp-denied-dashboard.json --write-out '%{http_code}' \
  -H "Authorization: Bearer $UNAUTHORIZED_TOKEN" \
  "$SP_GATEWAY_URL/api/dashboards/$SP_PILOT_DASHBOARD_ID")" = 404
```

Also verify one non-dashboard route so rollback does not merely pass liveness:

```sh
curl --fail --silent --show-error -H "Authorization: Bearer $OWNER_TOKEN" \
  "$SP_GATEWAY_URL/api/projects" >/tmp/sp-projects.json
```

The owner must be able to open the saved version; the same-organization viewer must open the shared version without owner actions; the other-organization request must remain a 404 and return no definition, SQL, rows, result IDs, export grant, cache metadata, or analysis context.

## Identify the rollback window

```sql
SELECT event_type,
       count(*) AS events,
       min(to_timestamp(timestamp)) AS first_seen,
       max(to_timestamp(timestamp)) AS last_seen
FROM gateway_audit_logs
WHERE org_id = :'org_id'
  AND timestamp >= extract(epoch FROM :'rollback_started_at'::timestamptz)
  AND event_type LIKE 'dashboard_%'
GROUP BY event_type
ORDER BY event_type;
```

Inspect only allowlisted metadata fields. Never copy raw SQL, parameters, rows, prompts, credentials, connection strings, or raw exceptions into the incident record.

## Forward recovery

After the cause is fixed and the current pair is approved again:

```sh
GATEWAY_IMAGE="$SP_CURRENT_GATEWAY_IMAGE" WEB_IMAGE="$SP_CURRENT_WEB_IMAGE" \
  docker compose up -d --no-build --force-recreate gateway gateway-chat-worker web
docker compose ps gateway gateway-chat-worker web
```

Repeat the health, owner/viewer/unauthorized, exact-cache, export, and telemetry checks. Confirm the dashboard row and immutable version IDs are unchanged across rollback and forward recovery.

## Data policy

- Keep `gateway_dashboards`, `gateway_dashboard_versions`, `gateway_dashboard_authoring_sessions`, and `gateway_dashboard_results` in place.
- Keep the widened `gateway_audit_logs.event_type` column in place.
- Do not run a down migration, drop a dashboard table, delete a dashboard version, or rewrite the saved pilot dashboard.
- A pilot repair is a separate owner-reviewed authoring preview and explicit Apply that creates a new immutable version.
