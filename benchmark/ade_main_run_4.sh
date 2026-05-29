#!/usr/bin/env bash
# ADE-bench Full Suite — Phase 4 Validation
# Expected: 57+ / 60
export RESULTS_DIR="benchmark/results/ade-main-4"
exec bash benchmark/ade_run.sh "$@"
