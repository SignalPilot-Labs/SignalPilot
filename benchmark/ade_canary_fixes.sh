#!/usr/bin/env bash
# Canary: 8 fix targets + 4 sentinels
# Targets: airbnb011 AE003 asana004 asana005 hs010 qb003 intercom002 f1009
# Sentinels: airbnb008 airbnb005 asana003 intercom001
export RESULTS_DIR="benchmark/results/ade-canary-fixes"
exec bash benchmark/ade_run.sh \
  airbnb011 analytics_engineering003 asana004 asana005 \
  helixops_saas010 quickbooks003 intercom002 f1009 \
  airbnb008 airbnb005 asana003 intercom001
