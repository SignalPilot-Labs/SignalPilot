#!/usr/bin/env bash
# ADE-bench Full Run — ade-main-1
# Downloads full traces, KB entries, project files
# Results go to benchmark/results/ade-main-1/

set -euo pipefail
set -a; source benchmark/.env; set +a

ADE_BENCH_DIR="C:/Users/kiwi0/Desktop/SPEcosystem/ade-bench"
DB_URL="postgresql+asyncpg://signalpilot:changeme_dev_only@signalpilot-db-1:5432/signalpilot"
IMAGE="sp-ade-benchmark-agent"
NETWORK="signalpilot_default"
RESULTS_DIR="benchmark/results/ade-main-1"
CONCURRENCY=6
MAX_RETRIES=0

KEYS=("$CLAUDE_KEY_1" "$CLAUDE_KEY_4")

# Ordered hardest → easiest: known failures first, then flaky/regressed, then stable
ALL_TASKS=(
  # Tier 1: Known failures (4 tasks — currently failing)
  analytics_engineering004 analytics_engineering006 f1002 intercom001
  # Tier 2: Recent flips (6 tasks — passed but could regress)
  helixops_saas010 quickbooks003 asana005 intercom003 airbnb007 f1011
  # Tier 3: Previously regressed then fixed (4 tasks)
  f1009 helixops_saas012 asana002 airbnb008
  # Tier 4: Stable passes (46 tasks)
  airbnb001 airbnb002 airbnb003 airbnb004 airbnb005
  airbnb006 airbnb009 airbnb010 airbnb011 airbnb012 airbnb013
  analytics_engineering001 analytics_engineering002 analytics_engineering003
  analytics_engineering005 analytics_engineering007 analytics_engineering008
  asana001 asana003 asana004
  f1001 f1003 f1004 f1005 f1006 f1007 f1010
  helixops_saas001 helixops_saas002 helixops_saas003 helixops_saas004
  helixops_saas005 helixops_saas006 helixops_saas007 helixops_saas008
  helixops_saas009 helixops_saas011 helixops_saas013 helixops_saas015
  helixops_saas016 helixops_saas017 helixops_saas018
  intercom002
  quickbooks001 quickbooks002 quickbooks004
)

PASSED=0
FAILED=0
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
  # Download project files, agent output, task result
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
        # Copy YML files for schema context
        find /data/ade/$T -name '*.yml' -not -path '*/dbt_packages/*' -not -path '*/target/*' -exec cp {} /out/$T/project/ \; 2>/dev/null
      }
    " 2>/dev/null || true
  # Download audit trace
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
  # Download KB entries
  MSYS_NO_PATHCONV=1 docker run --rm \
    -v signalpilot_signalpilot-data:/data:ro -v "$(pwd)/$RESULTS_DIR:/out" \
    alpine sh -c "
      mkdir -p /out/$T/sp-kb
      [ -d /data/knowledge/$T ] && cp -r /data/knowledge/$T/* /out/$T/sp-kb/ 2>/dev/null
    " 2>/dev/null || true
  # Container logs
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
echo "  ADE-bench Full Run: ade-main-1"
echo "  Tasks: ${#ALL_TASKS[@]}"
echo "  Concurrency: $CONCURRENCY"
echo "  Results: $RESULTS_DIR"
echo "============================================================"
echo ""

# Build queue — all tasks, fresh start
QUEUE=("${ALL_TASKS[@]}")
TOTAL=${#ALL_TASKS[@]}
echo "[$(date +%H:%M:%S)] Queue: ${#QUEUE[@]} tasks"
echo ""

# Track running tasks
RUNNING=""
QUEUE_IDX=0
FAILED_TASKS=""

count_running() { echo "$RUNNING" | wc -w | tr -d ' '; }

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
    if docker ps -q --filter "name=sp-ade-$T" 2>/dev/null | grep -q .; then
      NEW_RUNNING="$NEW_RUNNING $T"
    else
      download_result "$T"
      if check_result "$T"; then
        PASSED=$((PASSED + 1))
        TURNS=$(python3 -c "import json; print(json.load(open('$RESULTS_DIR/$T/task_result.json')).get('turns',0))" 2>/dev/null || echo "?")
        echo "[$(date +%H:%M:%S)]   PASS $T ($TURNS turns) [$PASSED pass, $FAILED fail of $TOTAL]"
      else
        FAILED=$((FAILED + 1))
        FAILED_TASKS="$FAILED_TASKS $T"
        echo "[$(date +%H:%M:%S)]   FAIL $T *** [$PASSED pass, $FAILED fail of $TOTAL]"
      fi
      cleanup_task "$T"
      launch_next
    fi
  done
  RUNNING="$NEW_RUNNING"
done

echo ""
echo "============================================================"
echo "  ADE-bench ade-main-1 Complete!"
echo "  Score: $PASSED/$TOTAL"
echo "  Failed: $FAILED"
echo "  Failed tasks:$FAILED_TASKS"
echo "  Results: $RESULTS_DIR"
echo "============================================================"
