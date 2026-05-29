#!/usr/bin/env bash
# Quick canary: intercom tasks + 2 sentinels
export RESULTS_DIR="benchmark/results/ade-canary-intercom"
exec bash benchmark/ade_run.sh intercom001 intercom002 intercom003 airbnb008 asana002
