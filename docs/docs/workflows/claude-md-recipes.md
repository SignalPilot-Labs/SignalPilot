---
sidebar_position: 4
sidebar_label: "CLAUDE.md (optional)"
---

# CLAUDE.md Recipes

Add these to your project's `CLAUDE.md` (or `~/.claude/CLAUDE.md` for global config) to ensure Claude Code follows the SignalPilot workflow correctly.

## Recommended CLAUDE.md

```markdown
# Project Instructions

## Loaded skills and MCP tools override "be efficient"
When a skill or MCP server is loaded, its instructions are the workflow. Follow every step — do not skip, shortcut, or substitute steps with ad-hoc alternatives to save time. "Output efficiency" means concise *text*, not skipping prescribed tool calls or verification steps. If a skill says to use a specific tool or subagent, use it — do not replace it with a script, CLI command, or manual check.

## Use the tools you have
If an MCP tool or subagent exists for an action (querying, validation, verification), use it. Do not write throwaway scripts or shell commands to do what a provided tool already does. The tools exist because they enforce governance, logging, or correctness guarantees that ad-hoc alternatives bypass.
```
