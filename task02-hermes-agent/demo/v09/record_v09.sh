#!/usr/bin/env bash
# Record one extra research run with the v0.9 ledger for the Demo. Run inside WSL; see demo/v09/RECORDING.md.
#   bash /mnt/c/Users/user/Desktop/SEO/tasks/task02-hermes/demo/v09/record_v09.sh
# The run happens after the v0.9 evaluation and does not count toward any verdict. It works on a copy of the v0.9
# ledger (runs/demo-v09/ledger-series); the evaluation evidence in evaluation/v09/ is only read.
set -euo pipefail
task=${TASK:-$HOME/soulo/task02-hermes}
win=${WIN:-/mnt/c/Users/user/Desktop/SEO/tasks/task02-hermes}
out=${1:-$win/demo/v09/capture}
root=runs/demo-v09/ledger-series
home=v09-demo-a1
V="python3 $win/scripts/demo_live_view.py"

cd "$task"
command -v tmux >/dev/null || { echo 'tmux missing (sudo apt install tmux)'; exit 2; }
[ -e "$out/frames.jsonl" ] && { echo "$out already holds a recording; pass a new directory"; exit 2; }
[ -e "$root" ] && { echo "$root exists; the demo run starts from a fresh copy of the v0.9 ledger"; exit 2; }
python3 scripts/evaluate_v09.py --verify >/dev/null || { echo 'evaluate_v09.py --verify failed: stop and report'; exit 2; }

# Copy the ledger as v0.9 round 10 left it and check the copy against the evaluation log.
mkdir -p "$root"
cp evaluation/v09/runs/ledger-series/research.sqlite "$root/"
cp -r evaluation/v09/runs/ledger-series/snapshots "$root/"
python3 - "$root" <<'PY'
import hashlib, json, sys
want = next(x for x in json.load(open('evaluation/v09/steps.json')) if x['step'] == 'L10' and x.get('settled'))
got = hashlib.sha256(open(sys.argv[1] + '/research.sqlite', 'rb').read()).hexdigest()
if got != want['ledger_after_sha256']:
    sys.exit('the copied ledger differs from the one L10 left')
print('ledger copy ok', got[:12])
PY
python3 -c "from src import hermes_homes as hh; hh.create_home('.', '$home', learn=False)"

# Usage: no start at or above 90% of the Session window; banked resets are never used.
set +u; source scripts/hermes_env.sh >/dev/null 2>&1; set -u
python "$task_root/.runtime/pinned/hermes" usage --provider openai-codex --json > "$out.usage-before.json" 2>/dev/null || true
python3 - "$out.usage-before.json" <<'PY'
import json, sys
w = {x['label']: x.get('used_percent') for x in json.load(open(sys.argv[1]))['windows']}
print('usage before', w)
if (w.get('Session') or 100) >= 90:
    sys.exit('Session at or above 90%: wait for the reset')
PY

python3 "$win/scripts/demo_record.py" --out "$out" --cwd "$task" --pre 15 --tail 6 \
  --viewer "$V events --task-root . --root $root --ledger-db $root/research.sqlite \
--hermes-log .runtime/user/profiles/$home/logs/agent.log --page-pause 9 --pace 1.2 \
--banner '評估結束後另跑的一次，不計入判定：在 v0.9 帳本的複本上執行' \
--compare '帶經驗第 10 次（評估）=evaluation/v09/scores/L10.json' \
--compare '不學習第 10 次（評估）=evaluation/v09/scores/C10.json' \
--compare '帶經驗第 1 次（評估）=evaluation/v09/scores/L1.json' \
--proof '如何證明進步：判準先鎖定的評估中，帶經驗與不學習的兩組各跑 10 次，盲評判定第 10 次變好（evaluation/v09/RESULT.md）。'" \
  --log "$V hermes-log --log .runtime/user/profiles/$home/logs/agent.log" \
  --main "bash scripts/run_research.sh --model gpt-6.1-sol --mode memory --root $root --target https://2030.tw \
--keyword 娛樂城 --keyword 3A娛樂城 --hermes-home .runtime/user/profiles/$home --hermes-learning off --research-memory"

python "$task_root/.runtime/pinned/hermes" usage --provider openai-codex --json > "$out.usage-after.json" 2>/dev/null || true
