# Task 4 — Install ends in Slack

**User win:** Installation finishes and one click drops the user into Slack with SP ready — first successful analysis within a minute of installing. (Direct ask from Fahim's feedback.)

## Current behavior

After OAuth callback, the user lands back on the SignalPilot integrations page. From there: nothing points to Slack, no confirmation the bot is alive, and if the default project isn't assigned yet, the first message in Slack fails (`worker.py:687`). The "aha" moment is buried behind an unguided gap.

## Solution

**4a. Post-install success screen** on the integrations page after OAuth callback:
- If no default project yet → single required step: project picker (we already have `/oauth/{id}/provision`, `api/slack.py:226`), inline.
- Then a prominent **"Open in Slack"** button → `https://slack.com/app_redirect?app={app_id}&team={team_id}` (deep-links straight to the bot's DM, works on desktop app and browser).

**4b. Bot sends a first-touch DM.** On successful provision, the bot DMs the installer: one-line intro + two copy-pasteable example prompts based on the assigned project. Requires adding `im:write` scope (open DM) — additive scope, existing installs prompt to re-authorize; handle both scope sets gracefully.

**4c. Channel greeting.** When SP is invited to a channel (`member_joined_channel` event for our bot user), post one short intro message with an example @mention. Requires no new scopes beyond `chat:write`.

Out of scope: Slack App Home tab, onboarding checklists, Marketplace listing.

## Definition of done

- [ ] Fresh install flow, timed: OAuth start → project assigned → "Open in Slack" → first-touch DM visible — under one minute, no documentation needed (manual test, fresh dev workspace).
- [ ] "Open in Slack" button appears for already-installed workspaces too (re-entry point).
- [ ] First-touch DM arrives with working example prompts; sending one produces an analysis.
- [ ] Inviting SP to a channel posts the intro exactly once.
- [ ] Installs that haven't re-authorized for `im:write` skip the DM without erroring.
