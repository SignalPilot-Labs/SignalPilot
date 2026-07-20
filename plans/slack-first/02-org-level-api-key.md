# Task 2 — Org-level Anthropic key

**User win:** One admin pastes the Anthropic API key once; every teammate in the Slack workspace uses SP with zero setup. New teammate = zero onboarding steps.

## Current behavior

Every analysis needs the *installing user's* personal Anthropic key from user secrets (`session_service.py:126`, `get_user_anthropic_key(org_id, user_id)`). Consequences:

- Each person who wants to own an integration must create a key in Anthropic Console — Fahim called this "bureaucracy," and it blocks team adoption.
- The delivery-formatting LLM call resolves a key the same per-user way (`analysis_delivery/credentials.py`).
- If the installing user leaves or revokes their key, the whole workspace's bot dies.

## Solution

**2a. Org secret storage.** Add `get_org_anthropic_key(org_id)` / `set_org_anthropic_key` beside the user-secrets store, same encryption-at-rest pattern. One key per org.

**2b. Resolution chain.** Everywhere a key is resolved (notebook session env injection, delivery renderer credentials): `org key → installing user's key (legacy) → clear error`. Org key wins so admins can rotate centrally.

**2c. Admin UI.** On the integrations page (`web/app/integrations/page.tsx`), replace the per-project API-key overlay flow with an org-level "Anthropic API key" card: set / rotate / remove, admin-gated (same `write`-scope check as OAuth start). Show which mode is active (org key vs. legacy user key).

**2d. Setup nudge from Slack.** When no key resolves, the in-thread error (Task 3c) says "Ask your admin to add the Anthropic key" + link — so non-admin users know it is not their problem to fix.

Decisions taken (revisit only if they hurt): no per-user quota tracking yet; no BYO-key-per-user override; usage attribution stays at the audit-trail level we already have.

## Definition of done

- [ ] Admin sets org key in web UI; a *different* user in the same org runs a Slack analysis end-to-end having configured nothing.
- [ ] Rotating the org key takes effect on the next analysis without reinstalling Slack.
- [ ] Removing the org key falls back to the legacy user key if present; otherwise Slack replies with the admin nudge.
- [ ] Delivery renderer uses the same chain (no per-user key needed for formatting).
- [ ] Key never appears in logs or API responses (masked in UI after save).
- [ ] Unit tests: resolution chain order, admin-gating on the set/rotate endpoint.
