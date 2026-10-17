#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/hermes_env.sh"
python "$task_root/scripts/device_login.py" "$@"
