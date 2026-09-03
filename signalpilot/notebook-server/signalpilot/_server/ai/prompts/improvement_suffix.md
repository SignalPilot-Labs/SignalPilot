<automated_improvement_run>
This is an AUTOMATED IMPROVEMENT RUN scheduled by SignalPilot, not a user
conversation. Your mission: analyze the selected dbt project for warehouse
cost-saving opportunities and publish an HTML report.

Additional rules for this run only:
- You have sandbox VM tools (sandbox_exec, sandbox_write_file,
  sandbox_read_file): a disposable Linux VM seeded with the dbt project at
  /workspace, dbt preinstalled, stub profile at /tmp/sp-profiles.
  Use it to parse/compile the project sources you need.
  The project files are also available read-only in your working directory.
- Workflow: enumerate the project's models, use estimate_query_cost on the
  compiled SQL of the most material models against the selected connection,
  and identify concrete savings (duplicated subqueries worth extracting into
  a cached staging model, SELECT * from wide tables, expensive views that
  many models reference, dead models with no downstream refs).
- Rank recommendations by estimated savings and show before/after cost when
  you can estimate both.
- Save exactly one HTML report to
  `$SP_CHAT_ARTIFACTS_DIRECTORY/cost_optimization_report.html` and link it
  in the answer. Title it "Cost optimization report". The report must
  include: an executive summary, a ranked recommendation table with
  estimated impact, and the per-model cost estimates you gathered. If you
  find no meaningful savings, save the report saying so with the evidence.
- Never modify the database, the project, or any external system. Read-only
  queries and the sandbox only.
- End with a 3-6 sentence plain-language summary of the findings.
</automated_improvement_run>
