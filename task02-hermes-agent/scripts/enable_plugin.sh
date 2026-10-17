#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/hermes_env.sh"
mkdir -p "$HERMES_HOME/plugins"
ln -sfn "$task_root/plugin" "$HERMES_HOME/plugins/soulo-research"
python - <<'PY'
from pathlib import Path
import os,hermes_yaml as yaml
p=Path(os.environ['HERMES_HOME'])/'config.yaml';c=yaml.safe_load(p.read_text()) or {}
c.setdefault('auth',{})['adopt_external_logins']=False
c.setdefault('plugins',{})['enabled']=sorted(set(c.get('plugins',{}).get('enabled',[]))|{'soulo-research'})
c.setdefault('tools',{})['tool_search']={'enabled':'off'}
p.write_text(yaml.safe_dump(c))
PY
