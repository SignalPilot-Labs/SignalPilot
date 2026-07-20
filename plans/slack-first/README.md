# Slack-First Plan

**Date:** 2026-07-13 · **Owner:** Luiz · **Status:** Active · **North star:** [DIRECTION.md](DIRECTION.md)

## Context (short)

We are going Slack-first. Notion is deprioritized (harder to distribute; more people live in Slack). The Slack agent works end-to-end today: @mention or DM → ack → agentic analysis loop (Claude Agent SDK, 50 turns, gateway MCP tools) → progress updates every 15s → answer + charts + confidence in the thread.

But as a product it behaves like a **single-shot vending machine**: you cannot ask follow-ups in DMs, thread replies without re-@mention are ignored, and messages sent mid-analysis are silently dropped. It also fails silently in several setups (two installations for one workspace = mute bot), and every user needs their own Anthropic API key.

Key code:
- `signalpilot/gateway/gateway/slack_poc/worker.py` — event pipeline
- `signalpilot/gateway/gateway/api/slack.py` — OAuth install
- `signalpilot/notebook-server/signalpilot/_server/api/endpoints/notion_analysis.py` — shared analysis engine (source-agnostic despite the name)

## How we work

Startup mode. Small iterations, each task ships alone and delivers a **user win** — something a user can feel the same day. No task starts without a clear win statement and definition of done. Anything not on this list is out of scope until the list is done.

## Prioritized tasks

| # | Task | User win |
|---|------|----------|
| 1 | [Conversations, not single shots](tasks/01-follow-up-conversations.md) | SP feels like Claude in Slack: follow-ups with context, steer or question a running analysis, "stop" stops, small talk never triggers a pipeline |
| 2 | [Org-level Anthropic key](tasks/02-org-level-api-key.md) | One admin sets the key; every teammate uses SP with zero setup |
| 3 | [Never silently mute](tasks/03-never-silently-mute.md) | The bot always responds — with an answer or a clear reason — never dead air |
| 4 | [Install ends in Slack](tasks/04-install-ends-in-slack.md) | After install, one click drops you into Slack with SP ready — first analysis within a minute |

Order rationale: #1 is the loudest user feedback (Fahim: "single shot" complaint) and the biggest perceived-intelligence jump. #2 removes the biggest team-adoption blocker — every new user today needs their own Anthropic key. #3 and #4 are reliability/stability work: they protect demos and polish the first-run moment, and follow once the product-experience wins ship.

## Explicitly deferred

- Notion features (dashboards via HTML embed, page context)
- Slack Marketplace listing / distribution research (separate track, research not code)
- Channel-history workspace context beyond the current thread (revisit after #1 ships and we see real usage)
- Block Kit interactivity / clarifying-question buttons (validate demand first)
