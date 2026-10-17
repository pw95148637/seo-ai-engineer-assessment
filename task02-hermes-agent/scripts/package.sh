#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$task_root"
git bundle create .runtime/repository.bundle task/02
python3 - <<'PY'
from pathlib import Path
import zipfile
root=Path.cwd()
with zipfile.ZipFile(root.parent/'Soulo_Task02_Setup.zip','w',zipfile.ZIP_DEFLATED) as z:
    for f in root.rglob('*'):
        if f.is_file() and f.name != 'repository.bundle' and not any(x in f.relative_to(root).parts for x in ['.runtime','.git','__pycache__']):
            z.write(f,str(Path('task02-hermes')/f.relative_to(root)))
    z.write(root/'.runtime/repository.bundle','task02-hermes/repository.bundle')
PY
