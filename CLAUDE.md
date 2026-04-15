# SP Research

## Skill routing

When the user's request matches an available skill, ALWAYS invoke it using the Skill
tool as your FIRST action. Do NOT answer directly, do NOT use other tools first.
The skill has specialized workflows that produce better results than ad-hoc answers.

## Benchmark Audit Persistence

All benchmark runs MUST save audit logs to the `sp-benchmark-audit` Docker volume.

- Local audit dir: `/home/agentuser/benchmark-audit/`
- Docker volume: `sp-benchmark-audit`
- Sync script: `/tmp/sync_audit_v2.sh` — runs in background, copies local audit dir to Docker volume every 60s
- To verify: `docker run --rm -v sp-benchmark-audit:/audit alpine ls /audit/runs/`
- To restart sync if dead:
  ```bash
  nohup /tmp/sync_audit_v2.sh > /tmp/sync_audit_v2.log 2>&1 &
  ```
- Every round must verify the sync process is alive before starting benchmark tasks
- Run IDs are stored under `/home/agentuser/benchmark-audit/runs/<run-id>/`

## Benchmark Runner

- Single task: `python3 -u -m benchmark.runners.direct <task_id> --model claude-sonnet-4-6 --max-turns 200`
- Batch: `python3 -u -m benchmark.run_batch --suite spider2-dbt --model claude-sonnet-4-6 --max-turns 200 --parallel 1`
- Task list: 68 total in spider2-dbt, 65 with gold data for evaluation
- Audit saved to: `/home/agentuser/benchmark-audit/runs/<run-id>/`
- Workdirs: `/home/agentuser/repo/benchmark/_dbt_workdir/<task_id>/`
