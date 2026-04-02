---
description: "Use when reviewing code quality, fixing error handling, adding input validation, or improving code structure. Covers patterns for the SignalPilot Python and TypeScript codebases."
---

# Code Quality Standards

## Error Handling

- Never use bare `except:` — always catch specific exceptions
- Log errors with context before re-raising
- At API boundaries: return structured error responses, never raw exception strings
- Internal functions: let exceptions propagate unless you can handle them meaningfully

## Input Validation

- Validate at system boundaries (API endpoints, user input, external data)
- Use Pydantic models for request/response validation
- Don't validate internal function calls — trust the type system

## Python Patterns

- Type hints on all public function signatures
- Docstrings on public functions (one-liner is fine for simple functions)
- Use `pathlib.Path` over string concatenation for file paths
- Use `asyncio` consistently — don't mix sync and async database calls

## TypeScript Patterns

- Strict mode enabled
- Explicit return types on exported functions
- Use `unknown` over `any` where possible
- Proper null checks with optional chaining

## What NOT to Fix

- Import ordering — leave it alone
- String quote style — leave it alone
- Trailing whitespace — leave it alone
- Variable naming in working code — leave it alone
- Adding comments to self-explanatory code
