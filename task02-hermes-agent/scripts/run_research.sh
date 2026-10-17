#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/hermes_env.sh"
# 960 s covers the 900 s research budget; a learning run adds up to --review-wait for the end-of-turn review.
timeout "${SOULO_RUN_TIMEOUT:-960}" python "$task_root/scripts/run_research.py" "$@"
