---
description: "Use when debugging failing tests, tracing errors, or fixing bugs found during self-improvement runs. Provides a systematic 4-phase debugging methodology: investigate, analyze, hypothesize, implement."
---

# Systematic Debugging

## Iron Law

**No fixes without root cause investigation first.**

Fixing symptoms creates whack-a-mole debugging. Every fix that doesn't address root cause makes the next bug harder to find. Find the root cause, then fix it.

## Phase 1: Root Cause Investigation

Gather context before forming any hypothesis.

1. **Collect symptoms:** Read the error messages, stack traces, and test output carefully.
2. **Read the code:** Trace the code path from the symptom back to potential causes. Use Grep to find all references, Read to understand the logic.
3. **Check recent changes:**
   ```bash
   git log --oneline -20 -- <affected-files>
   ```
   Was this working before? What changed? A regression means the root cause is in the diff.
4. **Reproduce:** Can you trigger the bug deterministically? If not, gather more evidence.

Output: **"Root cause hypothesis: ..."** - a specific, testable claim about what is wrong and why.

## Phase 2: Pattern Analysis

Check if the bug matches a known pattern:

| Pattern | Signature | Where to look |
|---------|-----------|---------------|
| Race condition | Intermittent, timing-dependent | Concurrent access to shared state |
| Nil/null propagation | TypeError, AttributeError | Missing guards on optional values |
| State corruption | Inconsistent data, partial updates | Transactions, callbacks, hooks |
| Integration failure | Timeout, unexpected response | External API calls, service boundaries |
| Configuration drift | Works locally, fails in CI | Env vars, feature flags, DB state |
| Import/dependency | ModuleNotFoundError, ImportError | Missing packages, circular imports |

Also check:
- `git log` for prior fixes in the same area - recurring bugs in the same files are an architectural smell
- Test output for related failures that may share a root cause

## Phase 3: Hypothesis Testing

Before writing ANY fix, verify your hypothesis.

1. **Confirm the hypothesis:** Add a temporary log statement or assertion at the suspected root cause. Run the reproduction. Does the evidence match?
2. **If the hypothesis is wrong:** Return to Phase 1. Gather more evidence. Do not guess.
3. **3-strike rule:** If 3 hypotheses fail, STOP. The issue may be architectural rather than a simple bug. Escalate by documenting findings and moving to the next task.

**Red flags - slow down if you see:**
- Proposing a fix before tracing data flow - you're guessing
- Each fix reveals a new problem elsewhere - wrong layer, not wrong code
- "Quick fix for now" - there is no "for now." Fix it right or skip it.

## Phase 4: Implementation

Once root cause is confirmed:

1. **Fix the root cause, not the symptom.** The smallest change that eliminates the actual problem.
2. **Minimal diff:** Fewest files touched, fewest lines changed. Resist the urge to refactor adjacent code.
3. **Write a regression test** that fails without the fix and passes with the fix.
4. **Run the full test suite.** No regressions allowed.
5. **If the fix touches >5 files:** Reconsider. Large blast radius for a bug fix suggests the wrong approach.

## Verification & Report

After fixing, reproduce the original scenario and confirm it's fixed. Run the test suite.

Structure your commit message to include:
- What the symptom was
- What the root cause was
- What the fix does

## Rules

- 3+ failed fix attempts -> question the architecture, not your hypotheses
- Never apply a fix you cannot verify with tests
- Never say "this should fix it" - prove it with test output
- If fix touches >5 files, reconsider the approach
