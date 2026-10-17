#!/usr/bin/env bash
export LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1
sleep 0.5  # let the recorder attach pipe-pane first
cd /home/user/soulo/task02-hermes || exit 1
python3 /mnt/c/Users/user/Desktop/SEO/tasks/task02-hermes/scripts/demo_live_view.py hermes-log --log .runtime/user/logs/agent.log
exec sleep 86400  # keep the final screen; the recorder ends the session
