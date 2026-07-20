# Org-level Anthropic API key + kill Notion fallback

**Date:** 2026-07-15 · **Owner:** Luiz · **Status:** Planned
**Origin:** slack-first task 2 (org key) + task 3d (Notion-fallback bug). Slack/Notion agent *features* are on hold; this is platform work.

**User win:** One admin pastes the Anthropic key once on the integrations page; every teammate uses SP with zero setup. Slack-only orgs stop crashing with Notion-referencing errors.

## Current state (verified in code)

Key resolution is per-user in three places:

1. **Notebook pod env injection** — `gateway/notebooks/session_service.py:126` (`_pod_extra_env`): `get_user_anthropic_key(org_id, user_id)` → injects `ANTHROPIC_API_KEY` into the pod. This is the path that actually feeds the analysis agent — `notebook-server/.../ai/claude_agent.py:197` reads that env var; its gateway-fetch fallback (line 210-226) is a no-op that never returns a key.
2. **Delivery renderer** — `gateway/analysis_delivery/credentials.py:14` (`delivery_api_key_for_user`), called from `slack_poc/worker.py:516` and `notion/analysis.py:1614,1954`. Empty key ⇒ fallback (non-LLM) delivery.
3. **User secrets API** — `gateway/api/user_secrets.py` (`/api/user/secrets` GET/PUT, `RequireScope`), backed by `store/user_secrets.py` + `GatewayUserSecrets` (`db/models.py:944`, Fernet via `store/crypto.py`). Notebook-server proxies it for the in-notebook key overlay (`_server/api/endpoints/agent.py:82,132`).

**The bug (3d):** `slack_poc/worker.py:668-677` `_analysis_user_id`: when `config.user_id` is unset (env-mode / single-tenant), falls back to `_latest_notion_installation_user_id` (`worker.py:1104`). Slack-only org ⇒ `RuntimeError` mentioning Notion — after the user already messaged. That user_id feeds both credential lookup (`credential_user_id`, worker.py:444) and record attribution.

**Schema migrations:** no alembic — `create_all` + hand-written helpers in `db/engine.py`. A new table needs zero migration code.

## Phases

### Phase 1 — Org secret storage + API (gateway)

- `db/models.py`: `GatewayOrgSecrets` — `id`, `org_id` (unique), `anthropic_api_key_enc: LargeBinary | None`, `updated_at`. `create_all` picks it up.
- `store/org_secrets.py`: `get_org_anthropic_key(session, org_id)`, `set_org_anthropic_key`, `delete_org_anthropic_key` — mirror `store/user_secrets.py` including `_decrypt_with_migration` re-encrypt pattern.
- `api/org_secrets.py`: `GET/PUT /api/org/secrets` mirroring `api/user_secrets.py`. GET = `RequireScope("read")`, PUT = `RequireScope("write")` (same gate as OAuth start). Response: `has_org_key`, `key_preview` (prefix-mask, reuse `_mask_preview`), `updated_at`, and `active_mode: "org" | "user_legacy" | "none"` (org key set → `org`; else caller's user key → `user_legacy`; else `none`). Empty-string PUT clears, same as user endpoint.
- Register router in the app (wherever `user_secrets.router` is mounted).
- Tests: set/rotate/clear roundtrip, masking (mirror `test_user_secrets_preview.py` / `test_user_secrets_api_rotation.py`), write-scope gating on PUT.

### Phase 2 — Resolution chain everywhere

Chain: **org key → user key (legacy) → none**. Org wins so admins rotate centrally.

- `store/anthropic_key.py` (or extend `org_secrets.py`): single resolver `resolve_anthropic_key(session, org_id, user_id) -> tuple[str, str] | None` returning `(key, source)`; `user_id` optional.
- `session_service.py:_pod_extra_env` → use resolver. This alone covers the notebook agent (env injection).
- `analysis_delivery/credentials.py` → `delivery_api_key_for_user` uses resolver; keeps signature (`user_id` may be `None` now). Callers in `slack_poc/worker.py` and `notion/analysis.py` unchanged.
- `api/user_secrets.py` GET: add `has_org_key` + `effective` fields so the notebook-server `/agent/status` check (`agent.py:87`) reports configured=true when only the org key exists — keep `has_anthropic_key` meaning unchanged (per-user) to avoid breaking the PUT/preview flow.
- Tests: resolver order (org set / only user / neither), delivery credentials with `user_id=None`.

### Phase 3 — Kill the Notion fallback (the bug)

Principle: the API key is an **org** resource. Analyses must not depend on any user tied to a Slack/Notion installation.

- Delete `_latest_notion_installation_user_id` (`worker.py:1104-1120`).
- The notebook pod already runs under a synthetic identity (`session_service.py:410`, `user_id = "analysis:{source}:{request_id}"`); a real user is passed only as `credential_user_id` to fetch that user's key. Make `credential_user_id` fully optional: `_analysis_user_id` → `config.user_id or None`, no installation-derived lookup of any kind.
- Resolution then falls to Phase 2's chain: org key → `config.user_id`'s key (legacy only) → Phase 5 nudge ("admin: add org key in integrations"). No error path references Notion or requires a linked user.
- Tests: analysis with `config.user_id=None` + org key set succeeds; Slack-only org (zero Notion installs) resolves; no-key path yields the nudge, not a Notion/user error.

### Phase 4 — Integrations page: org key section

`web/app/integrations/page.tsx` — new `SectionHeader` section "anthropic api key" alongside the notion/slack oauth sections:

- Shows state from `GET /api/org/secrets`: org key set (masked preview + updated date) / legacy user-key mode / none.
- Set / rotate (input + save) / remove. Input never re-displays the saved key (prefix preview only).
- Non-write-scope users see status read-only.
- The in-notebook per-user overlay (`web/notebook/components/chat/agent-chat-panel.tsx`) stays as-is — legacy path, untouched.

### Phase 5 — Slack no-key nudge (thin)

- Where analysis startup fails because the resolver returns none, post in-thread: "SignalPilot needs an Anthropic API key. Ask your admin to add it on the integrations page: {link}" instead of a technical error. Single message, no retry logic — full dead-end coverage stays in the deferred 3a/3b/3c work.

## Definition of done (from slack-first task 2, plus 3d)

- [ ] Admin sets org key in web UI; a different user in the same org runs a Slack analysis end-to-end with zero setup.
- [ ] Rotating the org key takes effect on next analysis; no Slack reinstall.
- [ ] Removing the org key falls back to legacy user key if present; otherwise Slack replies with the admin nudge.
- [ ] Delivery renderer uses the same chain.
- [ ] Key never in logs or API responses (prefix-mask only).
- [ ] `_latest_notion_installation_user_id` deleted; Slack-only org completes an analysis end-to-end; no error path mentions Notion.
- [ ] Unit tests: resolver chain order, PUT admin-gating, `_analysis_user_id` fallback + error copy.

## Explicitly out of scope

- Reinstall idempotency + cross-org install conflict (3a/3b) — deferred.
- Per-user quota tracking, BYO-key override, usage attribution changes.
- Conversations (task 1) and install UX (task 4).
