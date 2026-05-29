#!/usr/bin/env bash
# Canary Batch B: Combined Phase 3A+3B prompt validation (12 tasks)
# Targets: hs012 (P5/P6), qb003 (P1/P5), airbnb007 (P2), airbnb011 (P8)
# Sentinels: airbnb008, asana003, asana002, f1009, airbnb001, hs008, qb004, intercom001
export RESULTS_DIR="benchmark/results/ade-canary-b"
exec bash benchmark/ade_run.sh \
  helixops_saas012 quickbooks003 airbnb007 airbnb011 \
  airbnb008 asana003 asana002 f1009 \
  airbnb001 helixops_saas008 quickbooks004 intercom001
