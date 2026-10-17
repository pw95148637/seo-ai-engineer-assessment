#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "$0")/.." && pwd)"
source_root="$task_root/.runtime/pinned"
mkdir -p "$source_root" "$task_root/.runtime/user"
if [[ ! -d "$source_root/.git" ]]; then git -C "$source_root" init -q; fi
timeout 90 git -C "$source_root" fetch --depth=1 https://github.com/NousResearch/hermes-agent.git 311155fade43d1993ea968909a2ad36762345bbc
git -C "$source_root" checkout --detach FETCH_HEAD
export HERMES_HOME="$task_root/.runtime/user"
export HERMES_RUNTIME_DIR="$task_root/.runtime/tools"
export TAR_OPTIONS=--no-same-owner
if [[ ! -f "$HERMES_HOME/config.yaml" ]]; then printf 'auth:\n  adopt_external_logins: false\n' > "$HERMES_HOME/config.yaml"; fi
cd "$source_root"
timeout 600 bash setup-hermes.sh --runtime-only
