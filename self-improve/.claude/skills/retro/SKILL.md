---
description: "Use to analyze what was accomplished during self-improvement runs, identify patterns in changes, and recommend focus areas for the next session. Produces a structured retrospective from git history."
---

# Self-Improvement Retrospective

Analyze recent self-improvement run history to understand what was accomplished, what patterns emerge, and where to focus next.

## Step 1: Gather Data

Collect metrics from git history for the current branch:

```bash
# Commits on this branch
git log --oneline main..HEAD

# Files changed with stats
git diff --stat main..HEAD

# Lines added/removed
git diff --shortstat main..HEAD

# Commit timestamps for session detection
git log --format="%H %ai %s" main..HEAD

# Per-directory change distribution
git diff --stat main..HEAD | grep -E '^\s' | sed 's|/[^/]*$||' | sort | uniq -c | sort -rn
```

## Step 2: Analyze Changes

### Change Categories
Classify each commit into categories:
- **Feature:** New functionality added
- **Fix:** Bug fix or error correction
- **Refactor:** Code restructuring without behavior change
- **Test:** New or improved tests
- **Security:** Security hardening
- **Performance:** Performance improvements
- **Docs:** Documentation updates
- **Chore:** Build, CI, or configuration changes

### Impact Assessment
For each category, assess:
- Number of commits
- Lines changed
- Files touched
- Whether tests were added alongside changes

## Step 3: Pattern Detection

Look for patterns that indicate improvement quality:

**Positive signals:**
- Tests added with each feature (good coverage discipline)
- Small, focused commits (good modularity)
- Bug fixes accompanied by regression tests
- Refactors that reduce file sizes (god file cleanup)

**Warning signals:**
- Large commits touching many files (possible scope creep)
- Features without tests
- Same file modified many times (possible churn)
- Commits that later need fixes (rework)

## Step 4: Produce Retrospective

```
SELF-IMPROVEMENT RETROSPECTIVE
================================
Branch:    <branch name>
Period:    <first commit date> to <last commit date>
Commits:   N
Lines:     +X / -Y

CHANGE BREAKDOWN
  Feature:     N commits (X lines)
  Fix:         N commits (X lines)
  Refactor:    N commits (X lines)
  Test:        N commits (X lines)
  Security:    N commits (X lines)

HOTSPOTS (most-modified areas)
  1. signalpilot/gateway/  (N files, X changes)
  2. self-improve/agent/   (N files, X changes)
  ...

QUALITY SIGNALS
  Test coverage:     N/N features have tests
  Commit size:       avg X lines per commit
  Rework rate:       N files modified >3 times

RECOMMENDATIONS FOR NEXT SESSION
  1. [priority] description
  2. [priority] description
  3. [priority] description
```

## Step 5: Focus Recommendations

Based on the retrospective, recommend 3-5 concrete tasks for the next session:

1. **Under-tested areas:** Modules that received features but no new tests
2. **Quality gaps:** Areas where health dashboard scores are low
3. **Incomplete work:** Refactors or features that were started but not finished
4. **Security debt:** Known vulnerabilities from SECURITY_AUDIT.md not yet addressed
5. **Architecture smells:** Files that grew past 500 lines, modules with too many responsibilities

Order recommendations by impact (user-facing improvements first, then reliability, then maintainability).

## Using with the CEO/Worker Loop

This skill is designed to be used by the CEO (Product Director) role when reviewing what the Worker accomplished. The CEO should:
1. Run the retrospective after each Worker session
2. Use the recommendations to assign the next concrete task
3. Track progress across sessions by comparing retrospectives
