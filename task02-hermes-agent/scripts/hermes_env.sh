# Source this file; official PM environment, this task's isolated profile.
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export HERMES_HOME="$task_root/.runtime/user"
export HERMES_RUNTIME_DIR="$task_root/.runtime/tools"
source "$task_root/.runtime/pinned/scripts/_activation.sh"
hermes_apply_env "$(hermes_compose_env "$task_root/.runtime/pinned" sh)"
export PYTHONPATH="$task_root:$task_root/.runtime/pinned${PYTHONPATH:+:$PYTHONPATH}"

# DDGS has its own proxy variable; reuse the configured egress, never log its value.
if [[ -z "${DDGS_PROXY:-}" ]]; then
  if [[ -n "${HTTPS_PROXY:-}" ]]; then export DDGS_PROXY="$HTTPS_PROXY";
  elif [[ -n "${https_proxy:-}" ]]; then export DDGS_PROXY="$https_proxy"; fi
fi
