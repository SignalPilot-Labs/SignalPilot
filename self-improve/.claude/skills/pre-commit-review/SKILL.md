---
description: "Use before committing changes to review the diff for bugs, security issues, and quality problems. Provides a structured review methodology with confidence-rated findings and auto-fix classification."
---

# Pre-Commit Code Review

Review the current diff against the base branch for bugs, security issues, and structural problems before committing. This skill is designed for autonomous self-review during self-improvement runs.

## Step 1: Get the Diff

```bash
git fetch origin main --quiet 2>/dev/null
git diff origin/main --stat
git diff origin/main
```

## Step 2: Critical Pass

Apply the checks from the **/code-quality** and **/security-audit** skills against the diff. In addition, check for these review-specific concerns:

### SQL & Data Safety
- Raw string interpolation in SQL queries (use parameterized queries)
- DDL/DML statements that should be blocked by the engine

### Concurrency & State
- Race conditions in async code (shared mutable state without locks)
- Missing await on async calls
- Database operations outside transactions where atomicity is needed

### Completeness
- New enum values not handled in all switch/match statements
- New config options without defaults
- New API endpoints without tests

## Step 3: Confidence Calibration

Every finding MUST include a confidence score (1-10):

| Score | Meaning | Action |
|-------|---------|--------|
| 9-10 | Verified by reading code. Concrete bug demonstrated. | Fix immediately |
| 7-8 | High confidence pattern match. Very likely correct. | Fix |
| 5-6 | Moderate. Could be a false positive. | Investigate before fixing |
| 3-4 | Low confidence. Suspicious but may be fine. | Note but don't fix |
| 1-2 | Speculation. | Ignore |

**Finding format:**
```
[SEVERITY] (confidence: N/10) file:line - description
```

## Step 4: Fix-First Classification

For each finding, classify as:

**AUTO-FIX** (apply immediately, no deliberation needed):
- Missing type annotations on public functions
- Bare except clauses -> specific exception types
- Unused imports

**INVESTIGATE** (requires deeper analysis before fixing):
- Missing LIMIT on queries (adding LIMIT changes semantics; verify the query intent first)
- Potential race conditions
- Security concerns
- Architectural issues
- Changes that touch >3 files

## Step 5: Apply Fixes

1. Auto-fix all AUTO-FIX items
2. For INVESTIGATE items, trace the code path and verify before fixing
3. After all fixes, run the test suite to confirm no regressions

## Output Format

```
PRE-COMMIT REVIEW: N issues (X critical, Y informational)

[For each finding, CRITICAL first, sorted by confidence descending]
[SEVERITY] (confidence: N/10) path:line - summary
  Action: AUTO-FIXED | NEEDS INVESTIGATION | SKIPPED (confidence too low)

Review Score: X/10
```

## Rules

- Do NOT flag import ordering, string quote style, or trailing whitespace
- Do NOT flag variable naming in working code
- Do NOT add unnecessary comments to self-explanatory code
- Only flag issues that could cause bugs, security problems, or maintenance burden
- False positive rate matters: a review that cries wolf loses trust
