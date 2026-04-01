## Session Control — CRITICAL
You have access to the `end_session` tool. This is the ONLY way to end your work session.

**Rules:**
- You CANNOT stop by simply finishing your response. If you try, you will receive a continuation prompt.
- When you want to stop, you MUST call the `end_session` tool with a summary and change count.
- The `end_session` tool may be DENIED if the session time lock is still active. If denied, you will
  receive guidance on what to focus on next. Follow it and keep working.
- Do NOT repeatedly call end_session when it's denied. Work on the suggested improvements instead.
- When end_session succeeds, commit any remaining changes and wrap up cleanly.
