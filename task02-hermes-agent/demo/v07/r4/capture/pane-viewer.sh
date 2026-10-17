#!/usr/bin/env bash
export LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1
sleep 0.5  # let the recorder attach pipe-pane first
cd /home/user/soulo/task02-hermes || exit 1
python3 /mnt/c/Users/user/Desktop/SEO/tasks/task02-hermes/scripts/demo_live_view.py events --task-root . --root evaluation/v07/runs/R4 --ledger-db evaluation/v06/runs/2030-series/research.sqlite --hermes-log .runtime/user/logs/agent.log --page-pause 9 --pace 1.2 --compare '上一版 空帳本首跑=evaluation/v06/scores/R1.json' --compare '上一版 無記憶對照=evaluation/v06/scores/B1.json' --compare '上一版 凍結帳本=evaluation/v06/scores/R3.json'
touch /mnt/c/Users/user/Desktop/SEO/tasks/task02-hermes/demo/v07/r4/capture/viewer.done
exec sleep 86400  # keep the final screen; the recorder ends the session
