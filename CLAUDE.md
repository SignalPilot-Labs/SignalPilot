# Project Instructions

## Loaded skills and MCP tools override "be efficient"
When a skill or MCP server is loaded, its instructions are the workflow. Follow every step — do not skip, shortcut, or substitute steps with ad-hoc alternatives to save time. "Output efficiency" means concise *text*, not skipping prescribed tool calls or verification steps. If a skill says to use a specific tool or subagent, use it — do not replace it with a script, CLI command, or manual check.

## Use the tools you have
If an MCP tool or subagent exists for an action (querying, validation, verification), use it. Do not write throwaway scripts or shell commands to do what a provided tool already does. The tools exist because they enforce governance, logging, or correctness guarantees that ad-hoc alternatives bypass.

## Derive SQL from data, not from descriptions
User prompt descriptions explain what the data represents. Do NOT translate user description words into SQL predicates, aggregation levels, or deduplication logic. Query source tables first. Let the data's structure, the YML column contract, and sibling model patterns determine your SQL.
