#!/usr/bin/env bash
# ADE-bench Benchmark Runner — 6-slot pool with instant backfill
# When one task finishes, the next starts immediately. No batch waiting.
#
# Usage:
#   bash benchmark/ade_run.sh                    # Run all tasks
#   bash benchmark/ade_run.sh airbnb001 f1001    # Run specific tasks

set -euo pipefail
set -a; source benchmark/.env; set +a

ADE_BENCH_DIR="C:/Users/kiwi0/Desktop/SPEcosystem/ade-bench"
DB_URL="postgresql+asyncpg://signalpilot:changeme_dev_only@signalpilot-db-1:5432/signalpilot"
IMAGE="sp-ade-benchmark-agent"
NETWORK="signalpilot_default"
RESULTS_DIR="${RESULTS_DIR:-benchmark/results/ade}"
CONCURRENCY=6
MAX_RETRIES=2

KEYS=("$CLAUDE_KEY_1" "$CLAUDE_KEY_4")

if [ $# -gt 0 ]; then
  ALL_TASKS=("$@")
else
  ALL_TASKS=(
    airbnb001 airbnb002 airbnb003 airbnb004 airbnb005
    airbnb006 airbnb007 airbnb008 airbnb009 airbnb010
    airbnb011 airbnb012 airbnb013
    analytics_engineering001 analytics_engineering002 analytics_engineering003
    analytics_engineering004 analytics_engineering005 analytics_engineering006
    analytics_engineering007 analytics_engineering008
    asana001 asana002 asana003 asana004 asana005
    f1001 f1002 f1003 f1004 f1005 f1006 f1007 f1009 f1010 f1011
    helixops_saas001 helixops_saas002 helixops_saas003 helixops_saas004
    helixops_saas005 helixops_saas006 helixops_saas007 helixops_saas008
    helixops_saas009 helixops_saas010 helixops_saas011 helixops_saas012
    helixops_saas013 helixops_saas015 helixops_saas016 helixops_saas017
    helixops_saas018
    intercom001 intercom002 intercom003
    quickbooks001 quickbooks002 quickbooks003 quickbooks004
    simple001 simple002
  )
fi

PASSED=0
FAILED=0
SKIPPED=0
FAILED_TASKS=""
KEY_IDX=0

mkdir -p "$RESULTS_DIR"

run_container() {
  local T=$1 KEY=$2
  docker rm -f "sp-ade-$T" 2>/dev/null || true
  docker volume rm "sp-workdir-ade-$T" 2>/dev/null || true
  docker volume create "sp-workdir-ade-$T" > /dev/null
  MSYS_NO_PATHCONV=1 docker run -d \
    --name "sp-ade-$T" --entrypoint bash --network "$NETWORK" \
    -e SP_GATEWAY_URL=http://signalpilot-gateway-1:3300 \
    -e ADE_BENCH_DIR=/ade-bench -e ADE_WORK_DIR=/workdir/ade -e BENCHMARK_AUDIT_DIR=/audit \
    -e CLAUDE_CODE_OAUTH_TOKEN="$KEY" -e DATABASE_URL="$DB_URL" \
    -e SP_DATA_DIR=/sp-data -e SP_DISABLE_SANDBOX=1 -e SP_ORG_ID="$T" -e SP_KB_READONLY=1 \
    -v "$ADE_BENCH_DIR:/ade-bench:ro" -v sp-benchmark-audit:/audit \
    -v "sp-workdir-ade-$T:/workdir" -v signalpilot_signalpilot-data:/sp-data:ro \
    "$IMAGE" -c "
      mkdir -p /workdir/ade /audit /home/agentuser/.claude
      chown -R agentuser:agentuser /workdir /audit /home/agentuser/.claude
      echo '{\"claudeAiOauth\":{\"accessToken\":\"'\${CLAUDE_CODE_OAUTH_TOKEN}'\",\"expiresAt\":9999999999999}}' > /home/agentuser/.claude/.credentials.json
      chown agentuser:agentuser /home/agentuser/.claude/.credentials.json
      gosu agentuser env PYTHONPATH=/app DATABASE_URL=\"$DB_URL\" SP_DATA_DIR=/sp-data SP_DISABLE_SANDBOX=1 SP_ORG_ID=\"$T\" ADE_BENCH_DIR=/ade-bench ADE_WORK_DIR=/workdir/ade python -m benchmark.ade.runner $T --model claude-sonnet-4-6
    " > /dev/null 2>&1
}

download_result() {
  local T=$1
  mkdir -p "$RESULTS_DIR/$T/sp-kb" "$RESULTS_DIR/$T/project"
  MSYS_NO_PATHCONV=1 docker run --rm \
    -v "sp-workdir-ade-${T}:/data:ro" -v "$(pwd)/$RESULTS_DIR:/out" \
    alpine sh -c "
      mkdir -p /out/$T/project
      [ -d /data/ade/$T ] && {
        cp /data/ade/$T/task_result.json /out/$T/ 2>/dev/null
        cp /data/ade/$T/agent_output.json /out/$T/ 2>/dev/null
        cp -r /data/ade/$T/models /out/$T/project/ 2>/dev/null
        cp -r /data/ade/$T/macros /out/$T/project/ 2>/dev/null
        cp -r /data/ade/$T/seeds /out/$T/project/ 2>/dev/null
        cp -r /data/ade/$T/tests /out/$T/project/ 2>/dev/null
        cp /data/ade/$T/dbt_project.yml /out/$T/project/ 2>/dev/null
        cp /data/ade/$T/target/run_results.json /out/$T/project/ 2>/dev/null
        cp /data/ade/$T/failure_report.html /out/$T/ 2>/dev/null
        cp /data/ade/$T/technical_spec.md /out/$T/ 2>/dev/null
      }
    " 2>/dev/null || true
  MSYS_NO_PATHCONV=1 docker run --rm \
    -v sp-benchmark-audit:/data:ro -v "$(pwd)/$RESULTS_DIR:/out" \
    alpine sh -c "
      RUN=\$(ls -t /data/runs/ 2>/dev/null | grep 'single-${T}-' | head -1)
      [ -n \"\$RUN\" ] && {
        cp /data/runs/\$RUN/tasks/*.json /out/$T/task_result_audit.json 2>/dev/null
        cp /data/runs/\$RUN/run_metadata.json /out/$T/ 2>/dev/null
        cp /data/runs/\$RUN/traces/*.json /out/$T/trace.json 2>/dev/null
      }
    " 2>/dev/null || true
  docker logs "sp-ade-$T" > "$RESULTS_DIR/$T/container.log" 2>&1 || true
}

check_result() {
  local T=$1
  [ -f "$RESULTS_DIR/$T/task_result.json" ] && \
    python3 -c "import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d.get('passed') else 1)" "$RESULTS_DIR/$T/task_result.json" 2>/dev/null
}

cleanup_task() {
  local T=$1
  docker rm -f "sp-ade-$T" 2>/dev/null || true
  docker volume rm "sp-workdir-ade-$T" 2>/dev/null || true
}

echo "============================================================"
echo "  ADE-bench Benchmark Run (pool mode)"
echo "  Tasks: ${#ALL_TASKS[@]}"
echo "  Concurrency: $CONCURRENCY"
echo "  Max retries: $MAX_RETRIES"
echo "  Results: $RESULTS_DIR"
echo "============================================================"
echo ""

# Clear stale connections AND credentials once at startup. A killed run can
# orphan a gateway_credentials row, whose uq_gw_cred_org_conn constraint then
# blocks that task's next registration with a false "already exists". Both
# tables must be cleared together (deleting only connections leaves orphans).
docker exec signalpilot-db-1 psql -U signalpilot -d signalpilot -q \
  -c "DELETE FROM gateway_credentials; DELETE FROM gateway_connections;" 2>/dev/null \
  && echo "[$(date +%H:%M:%S)] Cleared stale connections + credentials" || true

# Build queue — skip already-passed tasks
QUEUE=()
for T in "${ALL_TASKS[@]}"; do
  if check_result "$T"; then
    PASSED=$((PASSED + 1)); SKIPPED=$((SKIPPED + 1))
    echo "[$(date +%H:%M:%S)] SKIP $T already PASS"
  elif [ -f "$RESULTS_DIR/$T/task_result.json" ]; then
    # Has a result file but didn't pass = previous FAIL, skip it too
    FAILED=$((FAILED + 1)); SKIPPED=$((SKIPPED + 1))
    FAILED_TASKS="$FAILED_TASKS $T"
    echo "[$(date +%H:%M:%S)] SKIP $T already FAIL"
  else
    QUEUE+=("$T")
  fi
done

TOTAL=${#ALL_TASKS[@]}
echo ""
echo "[$(date +%H:%M:%S)] Queue: ${#QUEUE[@]} to run, $SKIPPED skipped"
echo ""

# Track running tasks as a simple space-separated string
RUNNING=""
QUEUE_IDX=0

# Track retry counts in files
rm -f "$RESULTS_DIR"/*/.retries 2>/dev/null || true

# Helper: count words in RUNNING
count_running() { echo "$RUNNING" | wc -w | tr -d ' '; }

# Helper: launch next task from queue
launch_next() {
  if [ $QUEUE_IDX -lt ${#QUEUE[@]} ]; then
    local T="${QUEUE[$QUEUE_IDX]}"
    QUEUE_IDX=$((QUEUE_IDX + 1))
    KEY_IDX=$((KEY_IDX + 1))
    local KEY="${KEYS[$((KEY_IDX % ${#KEYS[@]}))]}"
    docker exec signalpilot-db-1 psql -U signalpilot -d signalpilot -q -c "DELETE FROM gateway_knowledge_docs WHERE org_id='$T';" 2>/dev/null || true
    run_container "$T" "$KEY"
    RUNNING="$RUNNING $T"
    echo "[$(date +%H:%M:%S)] START $T ($(count_running)/$CONCURRENCY slots)"
  fi
}

# Seed the pool
while [ "$(count_running)" -lt "$CONCURRENCY" ] && [ $QUEUE_IDX -lt ${#QUEUE[@]} ]; do
  launch_next
done

# Poll loop
while [ "$(count_running)" -gt 0 ]; do
  sleep 10
  NEW_RUNNING=""
  for T in $RUNNING; do
    STATUS=$(docker ps --filter "name=sp-ade-$T" --format "{{.Status}}" 2>/dev/null || true)
    if [ -z "$STATUS" ]; then
      # Container finished — download and check
      download_result "$T"
      if check_result "$T"; then
        PASSED=$((PASSED + 1))
        TURNS=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('turns','?'))" "$RESULTS_DIR/$T/task_result.json" 2>/dev/null || echo "?")
        echo "[$(date +%H:%M:%S)]   PASS $T ($TURNS turns) [$PASSED pass, $FAILED fail of $TOTAL]"
        cleanup_task "$T"
        # Backfill
        launch_next
      else
        # Check retries
        RETRY_FILE="$RESULTS_DIR/$T/.retries"
        RETRIES=0
        [ -f "$RETRY_FILE" ] && RETRIES=$(cat "$RETRY_FILE")
        RETRIES=$((RETRIES + 1))
        if [ $RETRIES -le $MAX_RETRIES ]; then
          echo "[$(date +%H:%M:%S)]   FAIL $T — retry $RETRIES/$MAX_RETRIES"
          echo "$RETRIES" > "$RETRY_FILE"
          rm -f "$RESULTS_DIR/$T/task_result.json"
          cleanup_task "$T"
          docker exec signalpilot-db-1 psql -U signalpilot -d signalpilot -q -c "DELETE FROM gateway_knowledge_docs WHERE org_id='$T';" 2>/dev/null || true
          KEY_IDX=$((KEY_IDX + 1))
          run_container "$T" "${KEYS[$((KEY_IDX % ${#KEYS[@]}))]}"
          NEW_RUNNING="$NEW_RUNNING $T"
        else
          FAILED=$((FAILED + 1))
          FAILED_TASKS="$FAILED_TASKS $T"
          echo "[$(date +%H:%M:%S)]   FAIL $T after $MAX_RETRIES retries *** [$PASSED pass, $FAILED fail of $TOTAL]"
          cleanup_task "$T"
          # Backfill
          launch_next
        fi
      fi
    else
      NEW_RUNNING="$NEW_RUNNING $T"
    fi
  done
  # Update RUNNING with any new launches from launch_next (appended to RUNNING)
  # Merge NEW_RUNNING (still active) with anything new in RUNNING
  # RUNNING may have new tasks appended by launch_next, keep those too
  for T in $RUNNING; do
    # If T is not in NEW_RUNNING and not already handled, it was just launched by backfill
    if ! echo " $NEW_RUNNING " | grep -q " $T "; then
      # Check if it's a freshly launched container (still running)
      S=$(docker ps --filter "name=sp-ade-$T" --format "{{.Status}}" 2>/dev/null || true)
      [ -n "$S" ] && NEW_RUNNING="$NEW_RUNNING $T"
    fi
  done
  RUNNING="$NEW_RUNNING"
done

# Count passes on the 43-task leaderboard subset (excludes helixops_saas)
PASS_43=0; TOTAL_43=0
PASS_60=0
for T in "${ALL_TASKS[@]}"; do
  IS_HELIX=false
  [[ "$T" == helixops_saas* ]] && IS_HELIX=true
  if check_result "$T"; then
    PASS_60=$((PASS_60 + 1))
    if ! $IS_HELIX; then PASS_43=$((PASS_43 + 1)); fi
  fi
  if ! $IS_HELIX; then TOTAL_43=$((TOTAL_43 + 1)); fi
done

echo ""
echo "============================================================"
echo "  ADE-bench Run Complete!"
echo "  Leaderboard score: $PASS_43/$TOTAL_43 (excludes helixops_saas)"
echo "  Full score:        $PASS_60/$TOTAL"
echo "  Failed: $FAILED"
echo "  Skipped (already pass): $SKIPPED"
if [ -n "$FAILED_TASKS" ]; then
  echo "  Failed tasks:$FAILED_TASKS"
fi
echo "  Results: $RESULTS_DIR/"
echo "============================================================"
