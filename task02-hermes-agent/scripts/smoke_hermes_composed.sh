#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "$0")/.." && pwd)"
export HERMES_HOME="$task_root/.runtime/user"
export HERMES_RUNTIME_DIR="$task_root/.runtime/tools"
cd "$task_root/.runtime/pinned"
# Official environment composition from already installed PM state.
# Avoid reinstalling the optional browser for each CLI/tool subprocess.
source scripts/_activation.sh
hermes_apply_env "$(hermes_compose_env "$PWD" sh)"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
git rev-parse HEAD > "$task_root/evidence/hermes-version.txt"
timeout 30 python hermes --help > "$task_root/evidence/hermes-cli-help-final.txt" 2>&1
timeout 30 python "$task_root/scripts/hermes_tool_check.py" > "$task_root/evidence/hermes-terminal-final.txt" 2>&1
