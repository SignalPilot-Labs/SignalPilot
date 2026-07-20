# Task 3 — Never silently mute

**User win:** The bot always responds — with an answer or a clear reason. A user (or a trial customer) never messages SP and gets dead air.

## Current behavior (silent-death paths)

1. **Ambiguous team → event dropped.** If a Slack workspace has more than one active installation row (reinstall leaving the old row active, or two SignalPilot orgs connecting the same workspace), `_dispatch_self_serve_payload` logs a warning and drops the event (`worker.py:1068-1074`). Bot goes completely mute for that workspace.
2. **No installation → dropped** (`worker.py:1065-1067`). Can happen mid-trial if an install row is disabled.
3. **Missing default project → RuntimeError** after the user already messaged (`worker.py:687-691`) — surfaced only if the exception handler posts it; the user hit friction that setup should have prevented.
4. **Notion-fallback key resolution in env mode** (`worker.py:668-677`): Slack-only orgs on single-tenant deployments crash with a Notion-referencing error.
5. **Installing user has no Anthropic key** → analysis fails at notebook-session start, error message is technical.

## Solution

**3a. Make reinstalls idempotent.** On OAuth callback upsert, deactivate any other active installation for the same `(team_id)` in the same org before activating the new one (`store/slack.py`). One workspace, one org, one active install.

**3b. Cross-org conflict = explicit failure at install time, not runtime.** If another org already has an active install for that `team_id`, fail the OAuth callback with a human message ("This Slack workspace is already connected to another SignalPilot organization") instead of allowing a second row that mutes both.

**3c. Runtime dead-ends answer in Slack.** Wherever we currently drop or raise (`no installation`, `ambiguous`, `no default project`, `no API key`), post a short in-thread reply with the one action needed and a link to the integrations page. For the ambiguous case we can still pick nothing — but we can respond using either install's bot token since both are for the same workspace.

**3d. Kill the Notion fallback.** Replace `_latest_notion_installation_user_id` with: config `user_id` (already set in self-serve) → org-level key owner (Task 2) → clear error naming Slack setup, never Notion.

Out of scope: durable event queue / restart-surviving analyses (bigger infra; separate decision), Slack token rotation.

## Definition of done

- [ ] Reinstalling the Slack app leaves exactly one active installation row; bot answers immediately after reinstall (manual test in dev workspace).
- [ ] Connecting a workspace already owned by another org fails at OAuth with a human-readable message.
- [ ] Messaging SP with: no default project / no API key configured → in-thread reply telling the user exactly what to fix, with link. No stack traces, no silence.
- [ ] `_latest_notion_installation_user_id` is gone; a Slack-only org (zero Notion installs) completes an analysis end-to-end.
- [ ] Unit tests for the upsert-deactivation and each dead-end reply path.
