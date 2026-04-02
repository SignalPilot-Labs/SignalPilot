---
description: "Use when assessing codebase health, measuring code quality metrics, or deciding what to improve next. Runs available quality tools and produces a scored dashboard to guide self-improvement priorities."
---

# Code Health Dashboard

Run available quality tools, score the results, and produce a clear dashboard. This guides self-improvement priorities by showing where quality is weakest.

**Read-only.** Do not fix issues. Produce the dashboard and recommendations only.

## Step 1: Detect Health Stack

Auto-detect available tools for the SignalPilot project:

```bash
# Python linting
command -v ruff >/dev/null 2>&1 && echo "LINT: ruff check ."
command -v pylint >/dev/null 2>&1 && echo "LINT: pylint"

# Type checking
command -v mypy >/dev/null 2>&1 && echo "TYPECHECK: mypy"
command -v pyright >/dev/null 2>&1 && echo "TYPECHECK: pyright"

# Test runner
[ -f pyproject.toml ] && grep -q "pytest" pyproject.toml 2>/dev/null && echo "TEST: pytest"
[ -f package.json ] && grep -q '"test"' package.json 2>/dev/null && echo "TEST: npm test"

# TypeScript
[ -f tsconfig.json ] && echo "TYPECHECK_TS: tsc --noEmit"

# ESLint
ls eslint.config.* .eslintrc.* 2>/dev/null | head -1 && echo "LINT_TS: eslint ."
```

## Step 2: Run Tools

Run each detected tool independently. For each:
1. Capture stdout and stderr
2. Record the exit code
3. Capture the last 50 lines of output

If a tool is not installed, record as `SKIPPED` with reason, not as a failure.

## Step 3: Score Each Category

Score each category on a 0-10 scale:

| Category | Weight | 10 | 7 | 4 | 0 |
|-----------|--------|------|-----------|------------|-----------|
| Type check | 25% | Clean (exit 0) | <10 errors | <50 errors | >=50 errors |
| Lint | 20% | Clean (exit 0) | <5 warnings | <20 warnings | >=20 warnings |
| Tests | 30% | All pass (exit 0) | >95% pass | >80% pass | <=80% pass |
| Dead code | 15% | Clean (exit 0) | <5 unused exports | <20 unused | >=20 unused |
| Shell lint | 10% | Clean (exit 0) | <5 issues | >=5 issues | N/A (skip) |

**Composite score:**
```
composite = sum(category_score * weight) for active categories
```

If a category is skipped, redistribute its weight proportionally.

## Step 4: Present Dashboard

```
CODE HEALTH DASHBOARD
=====================
Project: SignalPilot
Branch:  <current branch>
Date:    <today>

Category      Tool              Score   Status     Details
----------    ----------------  -----   --------   -------
Type check    mypy              10/10   CLEAN      0 errors
Lint          ruff check .       8/10   WARNING    3 warnings
Tests         pytest            10/10   CLEAN      47/47 passed
...

COMPOSITE SCORE: X.X / 10
```

Status labels:
- 10: `CLEAN`
- 7-9: `WARNING`
- 4-6: `NEEDS WORK`
- 0-3: `CRITICAL`

For any category below 7, list the top issues from that tool's output.

## Step 5: Recommendations

Prioritize suggestions by impact (weight * score deficit):

```
RECOMMENDATIONS (by impact)
============================
1. [HIGH]  Fix 2 failing tests (Tests: 9/10, weight 30%)
2. [MED]   Address 12 lint warnings (Lint: 6/10, weight 20%)
3. [LOW]   Add type hints to 4 functions (Type check: 7/10, weight 25%)
```

Rank by `weight * (10 - score)` descending. Only show categories below 10.

## Using the Dashboard for Self-Improvement

The health dashboard should inform the CEO/Product Director's task assignments:
- Categories scoring below 7 should be prioritized
- Categories scoring 7-9 are good candidates for incremental improvement
- Categories at 10 need no work
- Focus on high-weight categories first (tests > type check > lint)
