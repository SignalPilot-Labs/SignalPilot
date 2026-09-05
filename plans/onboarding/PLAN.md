# SignalPilot First-Run Onboarding Plan

**Status:** Phase 1 implemented in PR #338; cloud acceptance and rollout remain open
**Current phase:** Phase 1 — Getting Started foundation and first complete vertical slice

## Goal

Help an authenticated user reach a useful, governed Chat Agent result without
having to discover setup dependencies across unrelated settings pages.

The onboarding product has three separate, resumable journeys:

1. **Demo** — see SignalPilot work with isolated sample data.
2. **Production setup** — connect the active Team's dbt project, warehouse, and
   AI access.
3. **Product Tour** — learn the working product after Demo or Setup.

The journeys share one persistent **Getting Started** controller, but they do
not share completion state.

## Locked product decisions

- The user is already authenticated when this flow starts.
- If the user has an active non-demo Team, production setup uses it rather than
  creating another Team.
- Demo runs in a separate, personal Demo Team so demo data and production data
  cannot be confused.
- The first demo catalog contains Parallax only because it has an allowlisted
  Xata project and a matching public dbt repository.
- The Demo Xata parent branch is protected and shared; each Demo Team receives
  a private writable child branch.
- GitHub import creates the SignalPilot project before warehouse linking.
- **Connect Warehouse** owns the automatic project link. The connection is
  linked only after a healthy connection test and dbt-adapter compatibility
  check. There is no separate manual link-project screen.
- Demo, Setup, and Product Tour are independent journeys.
- Setup progress belongs to the Team/workspace. Tour progress belongs to the
  user.
- Teammate invitation is optional and never blocks the first useful result.
- Demo limits are enforced by the gateway, not only by disabled UI.
- Saved replays do not consume a live Demo request.
- Demo deletion must remove the SignalPilot project, private Xata
  branch, and connection before the Clerk Team is deleted.
- `XATA_KEY` is a deployment secret and must never be returned to the browser,
  stored in the repository, or included in logs.

## User journeys

### Entry

After authentication, show one short question:

> **How would you like to start?**

- **Explore a demo** prepares the private Demo Team.
- **Connect my data** opens production setup in the active non-demo Team.
- **Skip for now** enters the product without destroying journey progress.

The choice is reversible. Getting Started remains accessible from the Team
switcher and can be collapsed, resumed, or restarted.

### Demo journey

1. Create or resume the user's personal Demo Team.
2. Provision a private Xata branch from the protected Parallax parent.
3. Register the fixed Xata connection without exposing credentials.
4. Import the allowlisted Parallax dbt repository.
5. Wait for successful dbt metadata compilation.
6. Seed or reuse the versioned saved Chat Agent replay.
7. Open the replay automatically and show its governed events in order.
8. Offer suggested live questions.
9. Enforce the five-live-request allowance atomically at the gateway.
10. Offer Product Tour and production-setup next actions.
11. On Demo Team deletion, clean up the project, private branch, and connection
    before deleting the Team.

### Production setup journey

1. Use the active non-demo Team. When leaving a Demo Team, create or select a
   production Team first.
2. Connect GitHub and import a dbt repository, branch, and project directory.
3. Carry the imported project ID into Connect Warehouse.
4. Create or select the warehouse connection.
5. Save and test the connection.
6. Verify access and dbt-adapter compatibility.
7. Link the healthy connection to the imported project idempotently.
8. Add or rotate the Team-scoped Anthropic API key.
9. Invite one technical teammate or explicitly skip the optional step.
10. Recompute readiness from current dbt metadata, connection credentials,
    project link, and AI access.
11. Set the ready project as the user's default and open Chat Agent.

Failed warehouse tests must not link the project. Saved connections remain
retryable, and leaving the flow must not erase progress.

### Product Tour journey

The initial tour uses real product routes and targets:

1. Ask a question in Chat Agent.
2. Follow the governed work and inspect the answer.
3. Explore a connection or schema.
4. Open dbt lineage and supporting knowledge.
5. Review the resulting product surface.
6. Invite a teammate or learn how to keep working.

The compact controller shows journey, current task, progress, Continue, and
Expand. The expanded controller shows all steps, locked/unlocked state, current
form, errors, fallback actions, and the primary action. Session-only dismissal
must not mark the user or Team complete.

## State and ownership

| State | Owner | Source of truth |
| --- | --- | --- |
| Active journey and Product Tour progress | User | Clerk user metadata |
| Setup Team and imported project identity | Team plus user resume pointer | Gateway project state and Clerk metadata |
| Warehouse link | Team project | Gateway workspace project `connection_name` |
| dbt readiness | Team project and revision | Compiled gateway dbt metadata |
| Anthropic access | Team | Server-side organization secret state |
| Demo identity | Demo Team | Pinned connection/project policy tags |
| Demo request usage | Demo Team | Gateway Chat runs excluding saved replay origin |
| Drawer visibility for the current browser session | Browser session | Session storage |

Client metadata is a resume aid, not authority for readiness, authorization,
limits, or resource ownership.

## Phase tracker

- [x] Phase 0 — Product contract and clickable prototype.
- [x] Phase 1 — Getting Started foundation and first complete vertical slice.
- [ ] Phase 2 — Configured-cloud acceptance and hardening.
- [ ] Phase 3 — Staged rollout and product completion.

Checked implementation work means the code exists on the Phase 1 branch. It
does not mean the branch has been merged, deployed, or accepted in production.

## Phase 0 — Product contract and prototype

**Status:** Product contract complete; this canonical plan is added in PR #338.

### Deliverables

- [x] Define Demo, Production Setup, and Product Tour as separate journeys.
- [x] Establish the first-login choice and reversible navigation.
- [x] Define Team-owned setup state and user-owned tour state.
- [x] Define the GitHub import to Connect Warehouse handoff.
- [x] Require healthy warehouse testing before automatic project linking.
- [x] Define Demo fallback and Resume Setup behavior.
- [x] Create the self-contained clickable prototype.

### Exit evidence

- This self-contained `plans/onboarding/PLAN.md`.
- A local clickable prototype used during product review. The prototype is not
  included in this implementation PR.

The prototype is product/design evidence only. It is not runtime acceptance.

## Phase 1 — Foundation and first vertical slice

**Status:** Implemented in PR #338. Local automated evidence exists; cloud
acceptance remains Phase 2.

### Getting Started controller

- [x] Add the global compact and expanded controller.
- [x] Persist active journey and Product Tour progress.
- [x] Support collapse, resume, restart, and session-only dismissal.
- [x] Add a Team-switcher entry point.
- [x] Add route-level Product Tour targets.

### Demo Team

- [x] Allowlist the Parallax catalog slug, Xata project, parent branch, and dbt
  repository.
- [x] Idempotently create or resume the private Demo connection and project.
- [x] Trigger dbt project preparation and wait for compiled metadata.
- [x] Seed a versioned, authorized saved replay.
- [x] Auto-start replay only after the gateway authorizes the conversation/run.
- [x] Exclude saved replays from live-request usage.
- [x] Enforce the five-request limit at conversation/run/retry boundaries.
- [x] Return usage and remaining allowance in Chat bootstrap.
- [x] Preserve pinned Demo ownership tags during cosmetic edits.
- [x] Clean up Demo project, private branch, and connection before Team deletion.

### Production setup

- [x] Reuse the GitHub import form and retain the OAuth return path.
- [x] Tag and persist the setup project for resumable discovery.
- [x] Reuse the connection editor inside Getting Started.
- [x] Return saved/tested connection state to the controller.
- [x] Link the connection to the imported project only after a healthy test.
- [x] Reuse Team-scoped Anthropic-key management.
- [x] Reuse the Team invitation form and support Skip.
- [x] Poll readiness while dbt metadata is being prepared.
- [x] Set the ready project as Chat Agent's default.

### Entitlements needed for first value

- [x] Make dbt projects and lineage available to Free Teams.
- [x] Keep user-managed notebook sessions as a paid entitlement.
- [x] Allow a Free Team owner plus one active or pending teammate.
- [x] Keep Demo Teams personal and disable Demo invitations.

### Local validation

- [x] Gateway Demo/Getting Started policy tests: 34 passed.
- [x] Getting Started, Chat replay, and error-copy frontend tests: 20 passed.
- [x] Web TypeScript typecheck passed.
- [x] Ruff lint checks passed for changed Python files.
- [x] Linux/Docker build passed on PR #338.
- [x] Windows native web build passed on PR #338.
- [x] macOS arm64 native web build passed on PR #338.
- [x] Secret scanning, Semgrep, Bandit, and Python dependency checks passed on
  PR #338.

### Phase 1 exit criteria

- [x] The focused onboarding branch is based on `main`.
- [x] The complete implementation and roadmap are reviewable in one PR.
- [ ] Required PR checks pass; the first PR run's Node dependency scan and docs
  preview failures must be resolved or shown to be unrelated before merge.
- [ ] PR #338 is reviewed and merged.
- [ ] Configured-cloud acceptance is complete.

The last two items intentionally remain unchecked. Merge does not replace live
acceptance, and local/CI builds do not prove the external integrations.

## Phase 2 — Configured-cloud acceptance and hardening

**Status:** Not started as acceptance evidence.

### Environment preparation

- [ ] Configure `SP_DEMO_XATA_ORG` and the allowlisted
  `SP_DEMO_CATALOG` in the target environment.
- [ ] Configure `XATA_KEY` only in the deployment secret store.
- [ ] Confirm Clerk organization creation/switching and user metadata writes.
- [ ] Provision a test GitHub installation, dbt repository, supported warehouse,
  and Team-scoped Anthropic key.

### Demo acceptance

- [ ] Create a first Demo Team from a fresh authenticated user.
- [ ] Prove that the Xata child branch is private, writable, and unique.
- [ ] Prove that the protected parent cannot be edited or deleted by the flow.
- [ ] Prove that the paired dbt repository compiles and the Demo becomes ready.
- [ ] Replay the saved run without consuming the live allowance.
- [ ] Use five live requests and prove the sixth is rejected by the gateway.
- [ ] Race concurrent tabs against the final allowance and prove no overrun.
- [ ] Reload and resume provisioning without duplicate resources.
- [ ] Delete the Demo Team and prove project, branch, and connection cleanup.
- [ ] Simulate cleanup failure and prove Team deletion stops with a retryable
  error rather than leaking private data.

### Production setup acceptance

- [ ] Start Setup in an existing non-demo Team without creating a duplicate.
- [ ] Start Setup from a Demo Team and switch to a separate production Team.
- [ ] Complete GitHub OAuth and return to the same Getting Started step.
- [ ] Import a dbt project and carry the exact project ID forward.
- [ ] Fail a warehouse test and prove the project remains unlinked.
- [ ] Pass the test and compatibility checks and prove automatic linking.
- [ ] Reload mid-flow and resume from server state.
- [ ] Add Team-scoped Anthropic access without exposing the secret.
- [ ] Skip invitation and reach readiness.
- [ ] Invite one teammate and reach readiness.
- [ ] Open Chat Agent with the ready project selected and complete a useful run.

### Product Tour and browser acceptance

- [ ] Complete the tour from both Demo and Production Setup.
- [ ] Prove each spotlight target exists on its intended route.
- [ ] Prove locked steps cannot be selected early.
- [ ] Collapse, expand, dismiss for the session, resume, and restart.
- [ ] Verify desktop and narrow-screen layouts.
- [ ] Verify keyboard focus, Escape handling, labels, and screen-reader status
  announcements.

### Operational hardening

- [ ] Add allowlisted, metadata-only telemetry for journey start, step completion,
  failure class, abandonment, readiness, and first useful run.
- [ ] Exclude credentials, SQL, prompts, result rows, and raw exceptions from
  telemetry.
- [ ] Add alerts for provisioning failure, stuck dbt compilation, cleanup
  failure, and request-limit anomalies.
- [ ] Document retry and manual cleanup procedures.

### Phase 2 exit criteria

- [ ] All Demo, Setup, Tour, and failure-path checks pass in a configured cloud
  environment.
- [ ] No secret or cross-Team data crosses the authorization boundary.
- [ ] Cleanup and retry procedures are exercised, not merely documented.
- [ ] Browser evidence exists for desktop and narrow-screen flows.
- [ ] Known failures have owners and explicit release decisions.

## Phase 3 — Staged rollout and product completion

**Status:** Planned.

### Product choices to close

- [ ] Choose Demo Team retention and inactivity cleanup windows.
- [ ] Choose whether a user may recreate a Demo Team after cleanup.
- [ ] Confirm the live-request allowance and whether it varies by campaign.
- [ ] Finalize the Demo feature surface beyond Chat Agent.
- [ ] Finalize the exact first Product Tour pages and completion event.
- [ ] Choose the default role and handoff behavior for a technical setup invite.
- [ ] Define support behavior when GitHub, dbt compilation, the warehouse, Xata,
  or Anthropic is unavailable.

### Rollout

- [ ] Deploy to the internal environment with production-equivalent secrets and
  external integrations.
- [ ] Run internal dogfood with fresh, invited, returning, and multi-Team users.
- [ ] Review funnel, failure, cleanup, and support telemetry.
- [ ] Rehearse rollback without orphaning Demo branches or losing setup state.
- [ ] Release to a small external cohort.
- [ ] Expand only after acceptance and operational thresholds hold.
- [ ] Record production evidence and close or re-scope this plan.

### Success measures

- A Demo user reaches the saved replay with one choice and no credentials.
- A production user reaches a ready Chat Agent project without searching across
  settings pages.
- Failed warehouse tests never create a project link.
- Both Demo and Setup can enter the same Product Tour.
- A new user completes a useful governed agent run.
- Demo resources remain isolated and are cleaned up reliably.
- Funnel and failure telemetry is actionable without collecting sensitive data.

### Phase 3 exit criteria

- [ ] The staged cohort meets the agreed activation and reliability thresholds.
- [ ] Security, privacy, cleanup, support, and rollback owners approve rollout.
- [ ] Production evidence distinguishes implemented, tested, staged, and live
  states.

## Configuration and security contract

Non-secret configuration:

- `SP_DEMO_XATA_ORG`
- `SP_DEMO_CATALOG`

Deployment secret:

- `XATA_KEY`

The browser receives only catalog-safe identifiers and bootstrap state. It must
never receive the gateway Xata credential, stored warehouse credentials, or the
full Team Anthropic key. Demo catalog input is allowlisted server-side rather
than trusted from request payloads.

## Deferred scope

The following are outside the current Phase 1 deliverable unless explicitly
promoted by a later product decision:

- Multiple Demo datasets or a user-selectable Demo catalog.
- Arbitrary Git repositories or Xata parents supplied by the browser.
- Sharing a personal Demo Team with teammates.
- Treating a saved replay as proof of live warehouse or model execution.
- Replacing the existing GitHub, connection, readiness, BYOK, invitation, or
  Chat Agent authorities with onboarding-specific duplicates.
- Claiming staging or production readiness from local tests, CI builds, the
  prototype, or a Vercel preview alone.

## Evidence log

### 2026-09-03 — Product contract and local prototype

- Defined the three-journey onboarding product specification.
- Built a local shareable clickable prototype for product review.
- Locked warehouse auto-linking inside Connect Warehouse.

### 2026-09-05 — Phase 1 implementation

- Branch: `feat/onboarding-getting-started-phase-1`
- Commit: `50369524a14ec98cd926c7960b98c73117a00fd8`
- Pull request: #338
- Base at branch creation: `main` at `88f11cf7bc974bfaecca2d86422434027d1d59f2`
- Local gateway tests: 34 passed.
- Local targeted frontend tests: 20 passed.
- Local TypeScript typecheck: passed.
- Linux/Docker, Windows native web, and macOS arm64 native web builds: passed.
- Configured-cloud and production acceptance: not yet performed.
