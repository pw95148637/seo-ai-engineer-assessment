#!/usr/bin/env bash
export LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1
sleep 0.5  # let the recorder attach pipe-pane first
cd /home/user/soulo/task02-hermes || exit 1
printf "%s\n" '（15 秒後開始，先讓上方檢視器顯示帳本）'
sleep 15.0
printf "\033[2J\033[H"
printf "$ %s\n" 'python3 scripts/evaluate_v07.py --step R4'
python3 scripts/evaluate_v07.py --step R4
ec=$?
printf "[命令結束 exit=%s %s]\n" "$ec" "$(date +%H:%M:%S)"
touch /mnt/c/Users/user/Desktop/SEO/tasks/task02-hermes/demo/v07/r4/capture/main.done
exec sleep 86400  # keep the final screen; the recorder ends the session
