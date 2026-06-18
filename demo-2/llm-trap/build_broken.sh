#!/usr/bin/env bash
# Build a BROKEN pipeline into an isolated `trap_*` schema set, leaving the
# canonical analytics_marts untouched as ground truth.
#
# Pick which break with BREAK=revenue|risk|cac  (default: revenue)
#
#   revenue : int_transfers_enriched LEFT JOINs transfer_status_history (~3.9
#             rows/transfer) without deduping -> fees/revenue fan out ~3.9x.
#             fct_revenue_daily silently inflated; fct_transfers unique test fails.
#   risk    : int_customer_risk filters on the unreliable is_current_flag instead
#             of is_latest -> stale/duplicate scores -> high-risk % wrong;
#             dim_customer_risk unique(customer_code) test fails.
#   cac     : int_marketing_spend_unioned adds a "Performance Max" channel that
#             reads the same Google feed -> Google spend double-counted -> blended
#             CAC ~doubles. No test fails (new channel keeps the grain unique).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEMO2="$(cd "$HERE/.." && pwd)"
SRC="$DEMO2/nala_dbt"
WS="$HERE/workspace/nala_dbt"
DBT="$DEMO2/warehouse/.venv/Scripts/dbt.exe"
BREAK="${BREAK:-revenue}"

case "$BREAK" in
  revenue) MODEL=int_transfers_enriched;       SELECT="+fct_revenue_daily +fct_transfers"; MART=fct_revenue_daily;     FILTER="where revenue_date between '2026-01-01' and '2026-03-31' and send_currency='GBP'"; MEASURE="round(sum(total_revenue))";;
  risk)    MODEL=int_customer_risk;            SELECT="+dim_customer_risk";                 MART=dim_customer_risk;     FILTER="";                                                                            MEASURE="round(100.0*count(*) filter (where risk_band='high')/count(*),2)||'% high-risk, n='||count(*)";;
  cac)     MODEL=int_marketing_spend_unioned;  SELECT="+fct_marketing_spend_daily";         MART=fct_marketing_spend_daily; FILTER="where report_date between '2026-01-01' and '2026-03-31'";                  MEASURE="round(sum(spend))||' spend'";;
  *) echo "unknown BREAK=$BREAK (use revenue|risk|cac)"; exit 1;;
esac

echo ">> BREAK=$BREAK  model=$MODEL"
echo ">> resetting broken workspace"
rm -rf "$HERE/workspace"; mkdir -p "$HERE/workspace"
cp -r "$SRC" "$WS"
rm -rf "$WS/target" "$WS/dbt_packages" "$WS/logs"

echo ">> applying break to $MODEL.sql"
cp "$HERE/break/$MODEL.sql" "$WS/models/intermediate/$MODEL.sql"

echo ">> writing trap profile (schema=trap)"
cat > "$WS/profiles.yml" <<'YML'
nala:
  target: dev
  outputs:
    dev:
      type: postgres
      host: localhost
      port: 5602
      user: nala
      password: nala_dev_only
      dbname: nala_warehouse
      schema: trap
      threads: 8
      sslmode: disable
YML

echo ">> building broken lineage into trap_* ($SELECT)"
cd "$WS"
"$DBT" run --profiles-dir . --select $SELECT 2>&1 | tail -4

echo ">> BROKEN  trap_marts.$MART     : $(docker exec nala-warehouse-pg psql -U nala -d nala_warehouse -t -c "select $MEASURE from trap_marts.$MART $FILTER;" | tr -d '[:space:]')"
echo ">> TRUTH   analytics_marts.$MART: $(docker exec nala-warehouse-pg psql -U nala -d nala_warehouse -t -c "select $MEASURE from analytics_marts.$MART $FILTER;" | tr -d '[:space:]')"
echo ">> done. broken project at: $WS"
