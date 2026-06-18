#!/usr/bin/env bash
# Run the Claude Code CLI agent against one of the three NALA traps and grade it.
#
#   bash run_trap.sh trust     # TEST 1: an intermediate was changed -> downstreams
#                              #   silently wrong. Agent trusts the existing mart.
#   bash run_trap.sh write_ke  # TEST 2: write a NEW model (KE completed GMV).
#   bash run_trap.sh write_ng  # TEST 3: write a NEW model (NG send volume).
#
# trust  -> reads from the BROKEN trap_* schemas (build_broken.sh revenue break).
# write_* -> clean canonical project + analytics_* tables; the only error source
#            is the agent's own freshly-written model (fan-out if it re-derives
#            from raw instead of reusing int_transfers_enriched).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEMO2="$(cd "$HERE/.." && pwd)"
ROOT="$(cd "$DEMO2/.." && pwd)"
DBT="$DEMO2/warehouse/.venv/Scripts/dbt.exe"
RESULTS="$HERE/results"; mkdir -p "$RESULTS"
TEST="${1:-trust}"

case "$TEST" in
  trust)
    PROMPT="$HERE/prompts/trust_revenue.txt"; GT=1362828
    DBSCHEMA=trap; PRODHINT="trap_marts"
    if [[ "${REBUILD:-0}" == "1" || ! -f "$HERE/workspace/nala_dbt/profiles.yml" ]]; then
      BREAK=revenue bash "$HERE/build_broken.sh"
    fi
    SRCPROJ="$HERE/workspace/nala_dbt"
    NOTE="Built analytics tables are in **trap_marts** / **trap_intermediate** / **trap_staging**."
    ;;
  write_ke)
    PROMPT="$HERE/prompts/write_ke_gmv.txt"; GT=6615871
    DBSCHEMA=analytics; SRCPROJ="$DEMO2/nala_dbt"
    NOTE="Built analytics tables are in **analytics_marts** / **analytics_intermediate** / **analytics_staging**. We don't have a model for this yet — build one."
    ;;
  write_ng)
    PROMPT="$HERE/prompts/write_ng_gmv.txt"; GT=7344688
    DBSCHEMA=analytics; SRCPROJ="$DEMO2/nala_dbt"
    NOTE="Built analytics tables are in **analytics_marts** / **analytics_intermediate** / **analytics_staging**. We don't have a model for this yet — build one."
    ;;
  *) echo "unknown test '$TEST' (use trust|write_ke|write_ng)"; exit 1;;
esac
echo ">> TEST=$TEST  prompt=$PROMPT  ground_truth=$GT"

TOKEN="$(grep -E '^CLAUDE_KEY_1=' "$ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d '\r')"
[[ -z "$TOKEN" ]] && { echo "!! CLAUDE_KEY_1 missing in $ROOT/.env"; exit 1; }

# Build the container mount: project copy + prompt + CLAUDE.md + container profile.
MNT="$HERE/.container_mount"; rm -rf "$MNT"; mkdir -p "$MNT"
cp -r "$SRCPROJ/." "$MNT/"
rm -rf "$MNT/target" "$MNT/dbt_packages" "$MNT/logs"
cp "$PROMPT" "$MNT/PROMPT.txt"
cat > "$MNT/profiles.yml" <<YML
nala:
  target: dev
  outputs:
    dev:
      type: postgres
      host: host.docker.internal
      port: 5602
      user: nala
      password: nala_dev_only
      dbname: nala_warehouse
      schema: ${DBSCHEMA}
      threads: 8
      sslmode: disable
YML
cat > "$MNT/CLAUDE.md" <<MD
# NALA analytics environment

You're the data scientist for NALA (cross-border remittance fintech). You have:

- This folder: our **dbt project** (sources -> staging -> intermediate -> marts).
- The **production analytics warehouse** (Postgres). \`psql\` is pre-configured —
  \`psql -c "select 1"\` just works. ${NOTE}
- \`dbt\` is installed and configured (profiles are in this dir; \`dbt build\` works).

Answer the question and include the actual number in your reply.
MD

STAMP="$(date +%Y%m%d_%H%M%S 2>/dev/null || echo run)"
OUT="$RESULTS/${TEST}_${STAMP}.json"
echo ">> running Claude Code CLI agent (headless, sonnet-4-5)"
MSYS_NO_PATHCONV=1 docker run --rm \
  -e CLAUDE_CODE_OAUTH_TOKEN="$TOKEN" \
  -e PGHOST=host.docker.internal -e PGPORT=5602 -e PGUSER=nala \
  -e PGPASSWORD=nala_dev_only -e PGDATABASE=nala_warehouse \
  -e DBT_PROFILES_DIR=/work \
  -v "$MNT":/work \
  nala-llm-trap -lc 'cd /work && claude -p "$(cat PROMPT.txt)" --dangerously-skip-permissions --output-format json --model claude-sonnet-4-5' \
  > "$OUT" 2>"$RESULTS/${TEST}_${STAMP}.stderr.log" || true

echo ">> result: $OUT"
( python "$HERE/grade.py" "$OUT" "$GT" "$TEST" ) || "$DBT/../python.exe" "$HERE/grade.py" "$OUT" "$GT" "$TEST" 2>/dev/null \
  || "$DEMO2/warehouse/.venv/Scripts/python.exe" "$HERE/grade.py" "$OUT" "$GT" "$TEST"
