#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "$0")/.." && pwd)"
export HERMES_HOME="$task_root/.runtime/user"
export HERMES_RUNTIME_DIR="$task_root/.runtime/tools"
export PYTHONPATH="$task_root/.runtime/pinned"
cd "$task_root/.runtime/pinned"
git rev-parse HEAD > "$task_root/evidence/hermes-version.txt"
timeout 120 bash scripts/run-in-hermes-env python hermes --help > "$task_root/evidence/hermes-cli-help.txt" 2>&1
timeout 60 bash scripts/run-in-hermes-env python "$task_root/scripts/hermes_tool_check.py" > "$task_root/evidence/hermes-terminal.txt" 2>&1
