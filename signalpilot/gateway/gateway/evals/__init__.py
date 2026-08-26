"""Production evaluation runs for knowledge-base and dbt workflows.

Run state lives in Postgres, evidence lives in S3, and proposed knowledge
entries plus run/task attribution are bound to short-lived stored API keys.
"""
