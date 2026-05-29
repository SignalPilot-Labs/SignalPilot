#!/usr/bin/env bash
# Canary Batch A: Tool validation (10 tasks)
# Expected: 5 sentinels PASS, AE004+intercom001+intercom003 FLIP, AE006 5/7, qb003 FAIL
export RESULTS_DIR="benchmark/results/ade-canary-a"
exec bash benchmark/ade_run.sh \
  analytics_engineering004 intercom001 intercom003 analytics_engineering006 \
  airbnb007 airbnb008 f1009 asana003 helixops_saas012 quickbooks003
