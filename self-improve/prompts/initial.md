Begin your self-improvement pass on the codebase. Follow this structured workflow:

1. **Explore** — Read the project README, key source files, and recent git history to understand the current state.

2. **Assess** — Run the **/health** skill methodology: detect available quality tools, run them, and produce a scored dashboard. This gives you an objective baseline and identifies the weakest areas.

3. **Prioritize** — Pick the single highest-impact improvement from the health results. Focus on categories scoring below 7, weighted by importance (tests > type safety > lint > dead code).

4. **Implement** — Make the improvement. If you encounter bugs or failing tests, follow the **/investigate** methodology (root cause first, never fix symptoms). Use the **/pre-commit-review** skill with its specialist checklists before committing.

5. **Commit and push** — One logical change per commit with a clear message explaining WHY.

Use the available skills as structured methodologies — they provide codebase-specific patterns and checklists that produce better results than ad-hoc work. The Product Director will review your output and assign the next task.
