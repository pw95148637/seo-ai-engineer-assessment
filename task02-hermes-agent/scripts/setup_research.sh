#!/usr/bin/env bash
# No model or paid API call. OAuth remains a separate, user-completed step.
set -euo pipefail
task_root="$(cd "$(dirname "$0")/.." && pwd)"
bash "$task_root/scripts/install_hermes.sh"
bash "$task_root/scripts/enable_plugin.sh"
source "$task_root/scripts/hermes_env.sh"
cd "$task_root/.runtime/pinned"
timeout 180 python hermes pm install --extra ddgs
