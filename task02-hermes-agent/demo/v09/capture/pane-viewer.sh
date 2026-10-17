#!/usr/bin/env bash
export LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1
sleep 0.5  # let the recorder attach pipe-pane first
cd /home/user/soulo/task02-hermes || exit 1
python3 /mnt/c/Users/user/Desktop/SEO/tasks/task02-hermes/scripts/demo_live_view.py events --task-root . --root runs/demo-v09/ledger-series --ledger-db runs/demo-v09/ledger-series/research.sqlite --hermes-log .runtime/user/profiles/v09-demo-a1/logs/agent.log --page-pause 9 --pace 1.2 --banner '評估結束後另跑的一次，不計入判定：在 v0.9 帳本的複本上執行' --compare '帶經驗第 10 次（評估）=evaluation/v09/scores/L10.json' --compare '不學習第 10 次（評估）=evaluation/v09/scores/C10.json' --compare '帶經驗第 1 次（評估）=evaluation/v09/scores/L1.json' --proof '如何證明進步：判準先鎖定的評估中，帶經驗與不學習的兩組各跑 10 次，盲評判定第 10 次變好（evaluation/v09/RESULT.md）。'
touch /mnt/c/Users/user/Desktop/SEO/tasks/task02-hermes/demo/v09/capture/viewer.done
exec sleep 86400  # keep the final screen; the recorder ends the session
