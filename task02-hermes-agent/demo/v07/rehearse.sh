#!/usr/bin/env bash
# Rehearsal of the Demo pipeline: replay the finished v0.6 R3 run through the real recorder. No model calls.
# Run inside WSL:  bash /mnt/c/Users/user/Desktop/SEO/tasks/task02-hermes/demo/v07/rehearse.sh [OUT_DIR]
set -euo pipefail
task=${TASK:-$HOME/soulo/task02-hermes}                       # WSL checkout: v0.6 data, agent.log, src/
win=${WIN:-/mnt/c/Users/user/Desktop/SEO/tasks/task02-hermes}  # Windows copy that holds the demo scripts
out=${1:-$win/demo/v07/rehearsal/capture}
V="python3 $win/scripts/demo_live_view.py"
steps=evaluation/v06/steps.json
banner='演練：重播 v0.6 R3（只測管線，非最終 Demo；不呼叫模型）'

python3 "$win/scripts/demo_record.py" --out "$out" --cwd "$task" --pre 6 --tail 3 \
  --viewer "$V events --task-root . --root evaluation/v06/runs/2030-series --replay --steps $steps --step R3 \
--hermes-log .runtime/user/logs/agent.log --pre 6 --page-pause 4 --pace 0.4 --banner '$banner' \
--ledger-before evaluation/v06/ledger/R3-attempt1-before.json --ledger-after evaluation/v06/ledger/R3-attempt1-after.json \
--compare 'v0.6 R1=evaluation/v06/scores/R1.json' --compare 'v0.6 B1=evaluation/v06/scores/B1.json'" \
  --log "$V hermes-log --log .runtime/user/logs/agent.log --replay --steps $steps --step R3 --pre 6" \
  --main "$V replay-console --steps $steps --step R3 --console evaluation/v06/console/R3-attempt1.txt --label v0.6 --linger 0" \
  --main-display 'python3 scripts/demo_live_view.py replay-console --step R3   # 演練：重播原始命令與輸出' \
  --title 'viewer=檢視器（演練：重播 v0.6 R3 的 research.sqlite 事件）' \
  --title 'log=Hermes agent.log（演練：重播 v0.6 R3 的原始日誌行）' \
  --title 'main=命令（演練：不呼叫模型）'
