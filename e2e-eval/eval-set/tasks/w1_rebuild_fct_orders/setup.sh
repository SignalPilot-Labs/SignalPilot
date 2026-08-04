#!/bin/sh
set -e
psql "$SP_WAREHOUSE_DSN" -v ON_ERROR_STOP=1 -c "DROP TABLE IF EXISTS marts.fct_orders"
echo "setup: dropped marts.fct_orders for task $1"
