#!/usr/bin/env bash
export LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1
sleep 0.5  # let the recorder attach pipe-pane first
cd /home/user/soulo/task02-hermes || exit 1
printf "%s\n" '（6 秒後開始，先讓上方檢視器顯示帳本）'
sleep 6.0
printf "\033[2J\033[H"
printf "$ %s\n" 'python3 scripts/demo_live_view.py replay-console --step R3   # 演練：重播原始命令與輸出'
python3 /mnt/c/Users/user/Desktop/SEO/tasks/task02-hermes/scripts/demo_live_view.py replay-console --steps evaluation/v06/steps.json --step R3 --console evaluation/v06/console/R3-attempt1.txt --label v0.6 --linger 0
ec=$?
printf "[命令結束 exit=%s %s]\n" "$ec" "$(date +%H:%M:%S)"
touch /mnt/c/Users/user/Desktop/SEO/tasks/task02-hermes/demo/v07/rehearsal/capture/main.done
exec sleep 86400  # keep the final screen; the recorder ends the session
