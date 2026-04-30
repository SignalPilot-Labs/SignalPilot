---
sidebar_position: 7
---

# Claude Code Plugin

SignalPilot ships a Claude Code plugin with skills and standalone scripts for local dbt workflows.

## Install

```bash
claude plugin add SignalPilot-Labs/signalpilot-plugin
```

## Skills

The plugin adds guided skills to Claude Code:

- **signalpilot** -- main skill for querying and exploring databases via MCP
- **dbt-workflow** -- guided dbt development workflow with validation

## Standalone scripts

For local dbt projects, the plugin includes scripts that run directly (no MCP needed):

| Script | Purpose |
|--------|---------|
| `scan_project.py` | Scan a dbt project and report structure, model counts, test coverage |
| `validate_project.py` | Run `dbt parse` and report any compilation errors |

These are stdlib-only Python scripts that work without installing extra dependencies.
