"""Build the post-hoc 14B Kaggle notebook (kernel pw95148637/soulo-work03-posthoc-14b) from posthoc14b.py.

python kaggle/posthoc-14b/build_notebook.py   (run from tasks/task03-local-llm)
Embeds the sha256 of evaluation/posthoc14b-plan.md, so the run shows which pre-registered plan it followed.
Push with: python -P -m kaggle kernels push -p kaggle/posthoc-14b
(push only this folder; never push the v3b-train, v3-eval or posthoc-fp16 kernels)."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[1]
PLAN = TASK / 'evaluation' / 'posthoc14b-plan.md'
LOCK_SHA256 = '8ab9b7ae24fe5907965e6dc7b7e226bdcd7f74a845ccc2bfee995f2fc627d0cf'
HOLDOUT_SHA256 = '818b491f19541c7703cc311afd498fe1169c223a1c03fb4902e275b46b7a9106'
PACKAGES = ['transformers==4.57.6', 'peft==0.20.0', 'accelerate==1.14.0', 'bitsandbytes==0.50.2', 'datasets==4.8.5',
            'jsonschema>=4,<5', 'pandas>=2,<3']

plan_sha = hashlib.sha256(PLAN.read_bytes()).hexdigest()
code = (HERE / 'posthoc14b.py').read_text(encoding='utf-8')

intro = f"""# 第三題：凍結後的事後分析（Qwen3-14B）

這不是凍結系統的一部分。計畫在執行前寫好：`evaluation/posthoc14b-plan.md`（sha256 `{plan_sha}`）。結果不論好壞，都不用來調整 prompt、知識卡、模型或微調權重，也不改寫既有判定。

**要回答的問題**：YMYL 依主題過度標記，是 Qwen3-8B 能力不足，還是 prompt 或任務框架的問題。同一個凍結 prompt 換成 Qwen3-14B（revision `40c06982…`），用和凍結系統相同的 4-bit 設定載入單張 T4、不載微調權重，審同樣 8 篇測試文章，和既有的 8B 4-bit 無微調輸出比較。

載入、組 prompt、greedy 生成、最多一次重寫與輸出契約都從凍結 bundle 匯入、不修改；只把凍結的 `load()` 讀到的模型名稱與版本換成 14B。讀測試資料之前，先檢查磁碟、chat template 與 fp16 logits。"""

setup = f"""import os,sys,json,hashlib,shutil,subprocess
from pathlib import Path
PLAN_SHA256='{plan_sha}'
LOCK_SHA256='{LOCK_SHA256}'
HOLDOUT_SHA256='{HOLDOUT_SHA256}'
INPUT=Path('/kaggle/input');WORK=Path('/kaggle/working');ROOT=WORK/'work03';POST=WORK/'posthoc14b'
def find(name):return sorted(Path(d)/name for d,_,fs in os.walk(INPUT,followlinks=True) if name in fs)
locks=[p for p in find('frozen.json') if p.parent.name=='outputs' and p.parent.parent.name=='work03']
assert len(locks)==1,locks
assert hashlib.sha256(locks[0].read_bytes()).hexdigest()==LOCK_SHA256,'Mounted train bundle is not the frozen lock'
shutil.copytree(locks[0].parent.parent,ROOT,ignore=shutil.ignore_patterns('__pycache__','trainer'))
POST.mkdir(parents=True,exist_ok=True)
(POST/'plan_sha256.txt').write_text(PLAN_SHA256+'\\n',encoding='utf-8')
(WORK/'posthoc14b.py').write_text({code!r},encoding='utf-8')
subprocess.run([sys.executable,'-m','pip','install',*{PACKAGES!r}],check=True)
env={{**os.environ,'WORK03_ROOT':str(ROOT),'POSTHOC_OUT':str(POST),'HOLDOUT_SHA256':HOLDOUT_SHA256,
     'PYTORCH_CUDA_ALLOC_CONF':'expandable_segments:True'}}
# Frozen check: every locked file (prompt, knowledge, config, data, scripts, adapter) must match the lock.
subprocess.run([sys.executable,str(ROOT/'scripts/workflow.py'),'check-freeze'],check=True,env=env)
for p in ['/','/tmp','/root','/kaggle/working']:
    u=shutil.disk_usage(p);print(p,f'free {{u.free/1e9:.1f}} GB of {{u.total/1e9:.1f}} GB')"""

run = """# Only locate the test CSV here; posthoc14b.py hash-checks and reads it after the environment checks pass.
holdouts=find('holdout8.csv')
assert len(holdouts)==1,holdouts
subprocess.run([sys.executable,str(WORK/'posthoc14b.py')],check=True,
               env={**env,'HOLDOUT_PATH':str(holdouts[0]),'CUDA_VISIBLE_DEVICES':'0'})"""

show = """import pandas as pd
from IPython.display import display
rows=[json.loads(s) for s in (POST/'holdout_14b.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
display(pd.DataFrame([dict(ID=r['ID'],first_pass_valid=r['first_pass_valid'],final_valid=r['final_valid'],
  Score=(r['parsed'] or {}).get('Score'),codes=','.join(x['code'] for x in (r['parsed'] or {}).get('Reasons',[])),
  severities=','.join(x['severity'] for x in (r['parsed'] or {}).get('Reasons',[])),
  seconds=round(sum(a['seconds'] for a in r['attempts']),1)) for r in rows]))
print(json.dumps(json.loads((POST/'env_14b.json').read_text(encoding='utf-8')),ensure_ascii=False,indent=1))
# Keep only the post-hoc outputs; the frozen bundle and the test CSV stay in their original kernel and dataset.
shutil.rmtree(ROOT)
print(sorted(p.name for p in POST.iterdir()))"""


def cell(kind, src):
    c = {'cell_type': kind, 'metadata': {}, 'source': src.splitlines(keepends=True)}
    if kind == 'code':
        c.update(execution_count=None, outputs=[])
    return c


nb = {'cells': [cell('markdown', intro), cell('code', setup),
                cell('markdown', '## Qwen3-14B、4-bit、不載微調，審 8 篇測試文章\n'
                                 '先下載固定版本的權重並做環境檢查，通過後才核對測試資料雜湊並讀取。'),
                cell('code', run),
                cell('markdown', '## 結果摘要\n逐筆判讀與指標在本機依預先登錄的計畫計算。'),
                cell('code', show)],
      'metadata': {'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
                   'language_info': {'name': 'python'}},
      'nbformat': 4, 'nbformat_minor': 5}
(HERE / 'work03_posthoc14b.ipynb').write_text(json.dumps(nb, ensure_ascii=False, indent=1) + '\n', encoding='utf-8',
                                              newline='\n')
meta = {'id': 'pw95148637/soulo-work03-posthoc-14b', 'title': 'Soulo Work03 Posthoc 14B',
        'code_file': 'work03_posthoc14b.ipynb', 'language': 'python', 'kernel_type': 'notebook', 'is_private': 'true',
        'enable_gpu': 'true', 'enable_tpu': 'false', 'enable_internet': 'true', 'machine_shape': 'NvidiaTeslaT4',
        'competition_sources': [], 'model_sources': [],
        'dataset_sources': ['pw95148637/soulo-work03-isolated-holdout8'],
        'kernel_sources': ['pw95148637/soulo-work03-v3b-train']}
(HERE / 'kernel-metadata.json').write_text(json.dumps(meta, indent=2) + '\n', encoding='utf-8', newline='\n')
print('plan sha256', plan_sha)
