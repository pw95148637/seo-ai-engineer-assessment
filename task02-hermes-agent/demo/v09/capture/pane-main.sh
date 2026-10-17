#!/usr/bin/env bash
export LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1
sleep 0.5  # let the recorder attach pipe-pane first
cd /home/user/soulo/task02-hermes || exit 1
printf "%s\n" '（15 秒後開始，先讓上方檢視器顯示帳本）'
sleep 15.0
printf "\033[2J\033[H"
printf "$ %s\n" 'bash scripts/run_research.sh --model gpt-6.1-sol --mode memory --root runs/demo-v09/ledger-series --target https://2030.tw --keyword 娛樂城 --keyword 3A娛樂城 --hermes-home .runtime/user/profiles/v09-demo-a1 --hermes-learning off --research-memory'
bash scripts/run_research.sh --model gpt-6.1-sol --mode memory --root runs/demo-v09/ledger-series --target https://2030.tw --keyword 娛樂城 --keyword 3A娛樂城 --hermes-home .runtime/user/profiles/v09-demo-a1 --hermes-learning off --research-memory
ec=$?
printf "[命令結束 exit=%s %s]\n" "$ec" "$(date +%H:%M:%S)"
touch /mnt/c/Users/user/Desktop/SEO/tasks/task02-hermes/demo/v09/capture/main.done
exec sleep 86400  # keep the final screen; the recorder ends the session
