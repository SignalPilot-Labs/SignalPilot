# Dashboard release manifest

Complete every field and attach this file to the release evidence. Image references must use immutable digests.

## Ownership

- Release operator:
- Incident commander / rollback approver:
- Release window (UTC):
- Rollback decision deadline (UTC):

## Tested source

- Repository: `/Users/lfnandoo/Projects/sagebook/SignalPilot`
- Branch: `feat/data-chat-reports`
- Tested base commit (40 characters): `ee9d5c99289be759b26dd8541378184438c90530`
- Worktree clean at test start: no
- Worktree clean at test end: no
- Preserved unrelated paths: `docker-compose.dev.yml` and pre-existing dashboard UI edits
- Evidence report path: `analysis_outputs/phase-7-release-evidence-2026-08-26.md`

## Immutable artifacts

- Current gateway image and digest: `signalpilot-phase7-gateway@sha256:7ab1c8e43e5697e408ee1d025654ace63c6f883612028074120e3205eaa7d295`
- Current web image and digest: `signalpilot-phase7-web@sha256:82205de4ed084d1ca3e5b2b90bde04787e1d8f071d30c7cbb1f7a96c30255e71`
- Previous gateway image and digest: `signalpilot-phase7-gateway@sha256:4a03a814f3d18b6bb6e7fad7abfd8b558834b65092037c73617307e3fce0303e`
- Previous web image and digest: `signalpilot-phase7-web@sha256:c2b99e08b55530a0f83d3deaca57bccb0f3e9c2430466833e8f1be3038c817e0`

## Schema evidence

- Database / disposable environment identifier: isolated PostgreSQL 17 container `sp-phase7-remed-db` (removed after rehearsal)
- Migration command and result: current gateway startup `init_db()` passed
- Second idempotence run and result: current gateway restart passed
- Dashboard tables/indexes verified: four dashboard tables present; startup/index tests passed
- `gateway_audit_logs.event_type` width verified: 64 characters
- Previous image pair booted against upgraded schema: pass
- Current image pair restored against the same schema: pass
- Seed dashboard/version IDs preserved: `bb257ad8-929f-41d6-9634-91b7dbb8c96f` / `ff6a2f51-90ce-4ce6-bddd-e001573f820d`

## Acceptance

- Gateway production image build: pass
- Web production image build with TypeScript enforced: pass, including negative failure proof
- `npm run typecheck`: pass
- Dashboard backend/frontend suites: pass
- Selected Data Chat suite: pass; 2 explicit obsolete BudgetLedger skips
- Cloud role matrix with zero infrastructure skips: pass, 17 passed
- Dashboard HTTP role matrix: pass
- Controlled Chromium dashboard/recovery suite: pass, 4 passed
- Live MSSQL six-chart completion and exact reopen: pass for proposed 90-day runtime filter; saved-version Apply awaiting owner approval
- Telemetry presence/dedupe/authorization/sensitive-field negatives: pass locally
- Signed-in staging role matrix: externally blocked; no staging authorization/accounts
- Rollback and forward-recovery rehearsal: pass locally

## Decision

- Status: blocked
- Failed or externally blocked gates: clean/frozen commit, explicit pilot Apply approval, signed-in staging roles, real MSSQL outage/recovery, staging telemetry and rollback rehearsal
- Approval reference:
- Rollback threshold acknowledged: pending named operator and incident commander
- No feature flag, allowlist, or percentage rollout introduced: yes
