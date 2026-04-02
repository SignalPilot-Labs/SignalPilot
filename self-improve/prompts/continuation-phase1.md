Continue working. Focus on the highest-severity issues first — CRITICAL and HIGH findings from the security audit, any actual bugs, and missing input validation at system boundaries. Commit each fix separately.

Spawn `security-guard` to run a deep security audit on the codebase — it will find injection vectors, credential exposure, auth gaps, and OWASP Top 10 issues. Use `plan-reviewer` before starting any complex architectural change to validate the approach. Use `qa` to systematically find and fix existing bugs rather than guessing.
