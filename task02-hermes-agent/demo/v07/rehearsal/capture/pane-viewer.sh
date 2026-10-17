#!/usr/bin/env bash
export LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1
sleep 0.5  # let the recorder attach pipe-pane first
cd /home/user/soulo/task02-hermes || exit 1
python3 /mnt/c/Users/user/Desktop/SEO/tasks/task02-hermes/scripts/demo_live_view.py events --task-root . --root evaluation/v06/runs/2030-series --replay --steps evaluation/v06/steps.json --step R3 --hermes-log .runtime/user/logs/agent.log --pre 6 --page-pause 4 --pace 0.4 --banner '演練：重播 v0.6 R3（只測管線，非最終 Demo；不呼叫模型）' --ledger-before evaluation/v06/ledger/R3-attempt1-before.json --ledger-after evaluation/v06/ledger/R3-attempt1-after.json --compare 'v0.6 R1=evaluation/v06/scores/R1.json' --compare 'v0.6 B1=evaluation/v06/scores/B1.json'
touch /mnt/c/Users/user/Desktop/SEO/tasks/task02-hermes/demo/v07/rehearsal/capture/viewer.done
exec sleep 86400  # keep the final screen; the recorder ends the session
