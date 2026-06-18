# NALA LLM trap — does the agent check its upstream?

Three small experiments that hand a **Claude Code CLI agent** (running headless
in Docker, exactly like the benchmark) a simple Slack-style data question against
the NALA warehouse, and grade whether it gets the number right.

They all probe one failure mode: **the agent doesn't reason about dbt lineage /
grain.** Two ways that bites:

| test | type | what happens |
|------|------|--------------|
| `trust`    | *an intermediate was changed* | Someone modified `int_transfers_enriched`; it feeds **6 downstream models** (`dim_customers`, `dim_corridors`, `fct_revenue_daily`, `fct_transfers`, `int_revenue_per_transfer`, `int_customer_lifetime`). The agent is asked a number that already lives in a mart — it **trusts the existing (now-broken) model** and reports the inflated value. |
| `write_ke` | *write a new model* | Asked to build a model + a total. The vetted `int_transfers_enriched` already dedupes the 1-to-many `transfer_status_history`. The agent **re-derives from raw**, joins `transfer_status_history` (~3.9 rows/transfer) and sums value across the fan-out. |
| `write_ng` | *write a new model* | Same idea via `transfer_fees` (~2.15 rows/transfer). |

The lesson the demo makes concrete: **"produce me X" should just reuse the
vetted model; writing a new model from raw is where the agent silently fan-outs.**
And changing one intermediate quietly corrupts everything downstream.

## Prereqs

- The warehouse is up (`demo-2/warehouse`, Postgres on host port 5602) and dbt
  marts are built (`analytics_marts`). See `../warehouse/README.md`.
- Docker. The agent reaches the warehouse via `host.docker.internal:5602`.
- `CLAUDE_KEY_1` in the repo-root `.env` (used as `CLAUDE_CODE_OAUTH_TOKEN`).
- Build the agent image once:
  `MSYS_NO_PATHCONV=1 docker build -t nala-llm-trap -f Dockerfile .`

## Run

```bash
cd demo-2/llm-trap
bash run_trap.sh trust       # test 1 (builds the broken trap_* schemas first)
bash run_trap.sh write_ke    # test 2
bash run_trap.sh write_ng    # test 3
```

Each run prints the agent's reply tail, the parsed number, ground truth, and a
verdict. Raw transcripts land in `results/`.

### Verdicts (grade.py)

`CORRECT` (within 15% of truth — reused vetted logic / caught it) · `INFLATED`
(fell for the trap, no caveat) · `FLAGGED` (inflated but warned) · `OFF` · `UNKNOWN`.

## Observed results

- **trust** → agent reported **~£5.36M** GBP Q1 revenue (truth **£1.36M**, 3.9×),
  "a number I can stand behind", never traced the upstream fan-out. → `INFLATED`.
- **write_ke** → agent built a model joining `transfer_status_history` and
  reported **£26,463,484** "perfect for your risk review" (truth **£6,615,871**,
  exactly 4×) — got the *count* right (6,670) but summed value across the
  fan-out. → `INFLATED`.

A poor agent result is the expected, interesting outcome — not a bug.

## How it works

- `Dockerfile` — python + node + `@anthropic-ai/claude-code` + dbt-postgres
  (mirrors `benchmark/Dockerfile.ade-agent`).
- `build_broken.sh` — `BREAK=revenue|risk|cac` builds a broken pipeline into an
  isolated **`trap_*`** schema set, leaving canonical `analytics_*` untouched as
  ground truth. (`trust` uses the `revenue` break.)
- `break/` — drop-in broken intermediate models, each with a believable
  "developer changed this" comment.
- `prompts/` — the human Slack-style asks (1-2 sentences, no rigid format).
- `run_trap.sh` — prepares a container mount (project copy + prompt + a `CLAUDE.md`
  holding the boring environment context + a `host.docker.internal` profile),
  runs the CLI headless (`claude -p ... --output-format json`), and grades.
- `grade.py` — parses the number, compares to ground truth, classifies.

### Ground truth (Q1 2026, from the canonical `analytics_marts`)

| test | correct | trapped (naive) |
|------|---------|-----------------|
| trust (GBP revenue)        | £1,362,828 | £5,355,009 (3.9×) |
| write_ke (GBP→KE completed)| £6,615,871 | £26,463,484 (4×)  |
| write_ng (GBP→NG sent)     | £7,344,688 | £15,823,711 (2.15×) |

## Reset

The traps never touch `analytics_*`. To remove the broken copy:
```bash
docker exec nala-warehouse-pg psql -U nala -d nala_warehouse -c \
  "drop schema if exists trap_marts cascade; drop schema if exists trap_intermediate cascade; drop schema if exists trap_staging cascade;"
rm -rf workspace .container_mount
```
