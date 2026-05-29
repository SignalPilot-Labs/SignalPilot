#!/usr/bin/env bash
# ADE-bench Baseline Run — clean prompts (01b19d0) + modern harness + improved tools
export RESULTS_DIR="benchmark/results/ade-baseline"
exec bash benchmark/ade_run.sh "$@"
