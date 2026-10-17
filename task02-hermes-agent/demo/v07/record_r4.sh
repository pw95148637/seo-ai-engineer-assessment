#!/usr/bin/env bash
# Record the real v0.7 R4 run for the Demo. Run inside WSL; see demo/v07/RECORDING.md.
#   bash /mnt/c/Users/user/Desktop/SEO/tasks/task02-hermes/demo/v07/record_r4.sh
# The bottom pane runs the registered step (python3 scripts/evaluate_v07.py --step R4), which calls the model.
# The demo scripts run from the Windows copy and only read the run; they are not part of the plan fingerprint.
set -euo pipefail
task=${TASK:-$HOME/soulo/task02-hermes}
win=${WIN:-/mnt/c/Users/user/Desktop/SEO/tasks/task02-hermes}
out=${1:-$win/demo/v07/r4/capture}
step=${STEP:-R4}
retry=${RETRY:+ --retry}   # RETRY=1 only after an environment failure, as evaluate_v07.py allows (once per step)
V="python3 $win/scripts/demo_live_view.py"

cd "$task"
command -v tmux >/dev/null || { echo 'tmux missing (sudo apt install tmux)'; exit 2; }
[ -e "$out/frames.jsonl" ] && { echo "$out already holds a recording; pass a new directory"; exit 2; }
python3 scripts/evaluate_v07.py --verify >/dev/null || { echo 'evaluate_v07.py --verify failed: stop and report'; exit 2; }
echo "verify ok; recording $step into $out"

python3 "$win/scripts/demo_record.py" --out "$out" --cwd "$task" --pre 15 --tail 6 \
  --viewer "$V events --task-root . --root evaluation/v07/runs/$step \
--ledger-db evaluation/v06/runs/2030-series/research.sqlite --hermes-log .runtime/user/logs/agent.log \
--page-pause 9 --pace 1.2 \
--compare '上一版 空帳本首跑=evaluation/v06/scores/R1.json' --compare '上一版 無記憶對照=evaluation/v06/scores/B1.json' \
--compare '上一版 凍結帳本=evaluation/v06/scores/R3.json'" \
  --log "$V hermes-log --log .runtime/user/logs/agent.log" \
  --main "python3 scripts/evaluate_v07.py --step $step$retry"
