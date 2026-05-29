#!/usr/bin/env bash
# ADE-bench Full Benchmark Run — ade-main-2
# Results go to benchmark/results/ade-main-2/

export RESULTS_DIR="benchmark/results/ade-main-2"
exec bash benchmark/ade_run.sh "$@"
