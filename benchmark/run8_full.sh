#!/usr/bin/env bash
# Run 8 Full Benchmark
# Single-phase: benchmark run with inline KB generation (Step 9)
# 3 retries with KB clearing between retries
# Concurrency: 4 tasks at a time (2 per API key)

set -euo pipefail
set -a; source benchmark/.env; set +a

SPIDER2_PATH="C:/Users/kiwi0/Desktop/SPEcosystem/spider2-repo"
DB_URL="postgresql+asyncpg://signalpilot:changeme_dev_only@signalpilot-db-1:5432/signalpilot"
IMAGE="sp-dbt-benchmark-agent"
NETWORK="signalpilot_default"
RUN_TAG="dbt-run9"
RESULTS_DIR="benchmark/results/$RUN_TAG"
CONCURRENCY=6

KEYS=("$CLAUDE_KEY_1" "$CLAUDE_KEY_4")

# All 42 confirmed pass tasks
TASKS=(
  activity001 airbnb001 airport001 app_reporting001 app_reporting002
  apple_store001 asana001 asset001 chinook001 divvy001
  f1002 f1003 google_play001 google_play002 greenhouse001
  hive001 hubspot001 intercom001 lever001 marketo001
  maturity001 mrr001 mrr002 pendo001 playbook001
  qualtrics001 quickbooks002 quickbooks003 recharge002 reddit001
  retail001 salesforce001 shopify001 shopify002
  shopify_holistic_reporting001 superstore001
  tickit001 tpch001 twilio001 workday001 workday002 zuora001
)

TOTAL=${#TASKS[@]}
PASSED=0
FAILED=0
FAILED_TASKS=""

get_task_date() {
  python3 -c "import json; print(json.load(open('benchmark/gold_build_dates.json')).get('$1', '$(date +%Y-%m-%d)'))" 2>/dev/null || date +%Y-%m-%d
}

run_container() {
  local T=$1 KEY=$2
  local TASK_DATE
  TASK_DATE=$(get_task_date "$T")
  local CONTAINER_NAME="sp-spec-${T}"
  local VOLUME_NAME="sp-workdir-spec-${T}"

  docker rm -f "$CONTAINER_NAME" 2>/dev/null || true
  docker volume rm "$VOLUME_NAME" 2>/dev/null || true
  docker volume create "$VOLUME_NAME" > /dev/null

  MSYS_NO_PATHCONV=1 docker run -d \
    --name "$CONTAINER_NAME" --entrypoint bash --network "$NETWORK" \
    -e SP_GATEWAY_URL=http://signalpilot-gateway-1:3300 \
    -e SPIDER2_DBT_DIR=/spider2/spider2-dbt \
    -e BENCHMARK_AUDIT_DIR=/audit \
    -e BENCHMARK_WORK_DIR=/workdir/dbt \
    -e CLAUDE_CODE_OAUTH_TOKEN="$KEY" \
    -e FAKETIME="$TASK_DATE 12:00:00" \
    -e DATABASE_URL="$DB_URL" \
    -e SP_DATA_DIR=/sp-data \
    -e SP_DISABLE_SANDBOX=1 \
    -e SP_ORG_ID="$T" \
    -v "$SPIDER2_PATH:/spider2:ro" \
    -v sp-benchmark-audit:/audit \
    -v "$VOLUME_NAME:/workdir" \
    -v signalpilot_signalpilot-data:/sp-data:ro \
    "$IMAGE" -c "
      mkdir -p /workdir/dbt /audit /home/agentuser/.claude
      chown -R agentuser:agentuser /workdir /audit /home/agentuser/.claude
      echo '{\"claudeAiOauth\":{\"accessToken\":\"'\${CLAUDE_CODE_OAUTH_TOKEN}'\",\"expiresAt\":9999999999999}}' > /home/agentuser/.claude/.credentials.json
      chown agentuser:agentuser /home/agentuser/.claude/.credentials.json
      gosu agentuser env PYTHONPATH=/app DATABASE_URL=\"$DB_URL\" SP_DATA_DIR=/sp-data SP_DISABLE_SANDBOX=1 SP_ORG_ID=\"$T\" python -m benchmark.run_direct $T --model claude-sonnet-4-6
    " > /dev/null 2>&1
}

wait_for_container() {
  local CONTAINER_NAME=$1
  docker wait "$CONTAINER_NAME" 2>/dev/null || echo "1"
}

download_task() {
  local T=$1
  mkdir -p "$RESULTS_DIR/$T/sp-kb"

  MSYS_NO_PATHCONV=1 docker run --rm \
    -v sp-benchmark-audit:/data:ro \
    -v "$(pwd)/$RESULTS_DIR:/out" \
    alpine sh -c "
      RUN=\$(ls -t /data/runs/ | grep 'single-${T}-' | head -1)
      if [ -z \"\$RUN\" ]; then exit 1; fi
      mkdir -p /out/$T
      cp /data/runs/\$RUN/tasks/*.json /out/$T/task_result.json 2>/dev/null
      cp /data/runs/\$RUN/run_metadata.json /out/$T/ 2>/dev/null
      cp /data/runs/\$RUN/traces/*.json /out/$T/trace.json 2>/dev/null
      [ -d /data/runs/\$RUN/projects/$T ] && cp -r /data/runs/\$RUN/projects/$T /out/$T/project 2>/dev/null
    " 2>/dev/null || true

  # KB entries as markdown
  local TMP_JSON="$RESULTS_DIR/$T/sp-kb/_entries.json"
  docker exec signalpilot-db-1 psql -U signalpilot -d signalpilot -t -A -c \
    "SELECT json_agg(row_to_json(d)) FROM (SELECT id, org_id, scope, scope_ref, category, title, body, created_at FROM gateway_knowledge_docs WHERE org_id='$T' ORDER BY created_at) d" \
    > "$TMP_JSON" 2>/dev/null
  python3 benchmark/export_kb_md.py "$TMP_JSON" "$RESULTS_DIR/$T/sp-kb" 2>/dev/null || true
  rm -f "$TMP_JSON"
}

check_result() {
  local T=$1
  local RESULT_FILE="$RESULTS_DIR/$T/task_result.json"
  if [ -f "$RESULT_FILE" ]; then
    python3 -c "import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d.get('passed') else 1)" "$RESULT_FILE" 2>/dev/null
    return $?
  fi
  return 1
}

echo "============================================================"
echo "  Run 8 Benchmark (inline KB generation via Step 9)"
echo "  Tasks: $TOTAL"
echo "  Concurrency: $CONCURRENCY"
echo "  Results: $RESULTS_DIR"
echo "============================================================"
echo ""

# Process tasks in batches of CONCURRENCY
for ((i=0; i<TOTAL; i+=CONCURRENCY)); do
  BATCH=("${TASKS[@]:i:CONCURRENCY}")
  BATCH_NUM=$((i/CONCURRENCY + 1))
  BATCH_TOTAL=$(( (TOTAL + CONCURRENCY - 1) / CONCURRENCY ))

  echo "=== Batch $BATCH_NUM/$BATCH_TOTAL: ${BATCH[*]} ==="

  # Filter out already-completed tasks
  BATCH_TODO=()
  for T in "${BATCH[@]}"; do
    if check_result "$T"; then
      PASSED=$((PASSED + 1))
      echo "[$(date +%H:%M:%S)]   SKIP $T already PASS"
    else
      BATCH_TODO+=("$T")
    fi
  done

  if [ ${#BATCH_TODO[@]} -eq 0 ]; then
    echo "[$(date +%H:%M:%S)] Batch $BATCH_NUM all done"
    echo ""
    continue
  fi

  # Clear KB from any previous runs before launching
  for T in "${BATCH_TODO[@]}"; do
    docker exec signalpilot-db-1 psql -U signalpilot -d signalpilot -q -c \
      "DELETE FROM gateway_knowledge_docs WHERE org_id='$T';" 2>/dev/null
  done

  # Launch benchmark (KB gen happens inline as Step 9)
  echo "[$(date +%H:%M:%S)] Running: ${BATCH_TODO[*]}"
  for j in "${!BATCH_TODO[@]}"; do
    T="${BATCH_TODO[$j]}"
    KEY="${KEYS[$((j % ${#KEYS[@]}))]}"
    run_container "$T" "$KEY"
  done
  sleep 5

  # Wait and check results
  for T in "${BATCH_TODO[@]}"; do
    EXIT=$(wait_for_container "sp-spec-$T")
    download_task "$T"

    if check_result "$T"; then
      PASSED=$((PASSED + 1))
      TURNS=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('turns','?'))" "$RESULTS_DIR/$T/task_result.json" 2>/dev/null || echo "?")
      KB_COUNT=$(docker exec signalpilot-db-1 psql -U signalpilot -d signalpilot -t -c \
        "SELECT COUNT(*) FROM gateway_knowledge_docs WHERE org_id='$T'" 2>/dev/null | tr -d ' ')
      echo "[$(date +%H:%M:%S)]   PASS $T ($TURNS turns, $KB_COUNT KB entries)"
    else
      # Clear KB from failed attempt
      docker exec signalpilot-db-1 psql -U signalpilot -d signalpilot -q -c \
        "DELETE FROM gateway_knowledge_docs WHERE org_id='$T';" 2>/dev/null
      # Retry up to 3 times for non-deterministic failures
      RETRY_PASS=false
      for RETRY in 1 2 3; do
        echo "[$(date +%H:%M:%S)]   FAIL $T attempt $RETRY/3 — retrying..."
        rm -f "$RESULTS_DIR/$T/task_result.json"
        # Clear poisoned KB entries from failed attempt
        docker exec signalpilot-db-1 psql -U signalpilot -d signalpilot -q -c \
          "DELETE FROM gateway_knowledge_docs WHERE org_id='$T';" 2>/dev/null
        docker rm -f "sp-spec-$T" 2>/dev/null || true
        docker volume rm "sp-workdir-spec-$T" 2>/dev/null || true
        docker volume create "sp-workdir-spec-$T" > /dev/null
        RETRY_KEY="${KEYS[$(( RETRY % ${#KEYS[@]} ))]}"
        run_container "$T" "$RETRY_KEY"
        sleep 5
        wait_for_container "sp-spec-$T" > /dev/null
        download_task "$T"
        if check_result "$T"; then
          RETRY_PASS=true
          TURNS=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('turns','?'))" "$RESULTS_DIR/$T/task_result.json" 2>/dev/null || echo "?")
          KB_COUNT=$(docker exec signalpilot-db-1 psql -U signalpilot -d signalpilot -t -c \
            "SELECT COUNT(*) FROM gateway_knowledge_docs WHERE org_id='$T'" 2>/dev/null | tr -d ' ')
          echo "[$(date +%H:%M:%S)]   PASS $T on retry $RETRY ($TURNS turns, $KB_COUNT KB entries)"
          break
        fi
        # Clear KB from this failed retry too
        docker exec signalpilot-db-1 psql -U signalpilot -d signalpilot -q -c \
          "DELETE FROM gateway_knowledge_docs WHERE org_id='$T';" 2>/dev/null
      done
      if [ "$RETRY_PASS" = true ]; then
        PASSED=$((PASSED + 1))
      else
        FAILED=$((FAILED + 1))
        FAILED_TASKS="$FAILED_TASKS $T"
        # Clear KB from final failed attempt
        docker exec signalpilot-db-1 psql -U signalpilot -d signalpilot -q -c \
          "DELETE FROM gateway_knowledge_docs WHERE org_id='$T';" 2>/dev/null
        echo "[$(date +%H:%M:%S)]   FAIL $T after 3 retries ***"
      fi
    fi
  done

  # Cleanup
  for T in "${BATCH_TODO[@]}"; do
    docker rm -f "sp-spec-$T" 2>/dev/null || true
    docker volume rm "sp-workdir-spec-$T" 2>/dev/null || true
  done

  echo "[$(date +%H:%M:%S)] Batch $BATCH_NUM done: $PASSED/$((PASSED+FAILED)) passed"
  echo ""
done

echo "============================================================"
echo "  Run 8 Complete!"
echo "  Passed: $PASSED/$TOTAL"
echo "  Failed: $FAILED"
if [ -n "$FAILED_TASKS" ]; then
  echo "  Failed tasks:$FAILED_TASKS"
fi
echo "  Results: $RESULTS_DIR/"
echo "============================================================"
