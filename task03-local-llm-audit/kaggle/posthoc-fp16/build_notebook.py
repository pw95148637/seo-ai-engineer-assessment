"""Build the post-hoc Kaggle notebook (kernel pw95148637/soulo-work03-posthoc-fp16) from posthoc.py.

python kaggle/posthoc-fp16/build_notebook.py   (run from tasks/task03-local-llm)
Embeds the sha256 of evaluation/posthoc-plan.md, so the run shows which pre-registered plan it followed.
Push with: python -P -m kaggle kernels push -p kaggle/posthoc-fp16   (never push the v3b-train or v3-eval folders)."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[1]
PLAN = TASK / 'evaluation' / 'posthoc-plan.md'
LOCK_SHA256 = '8ab9b7ae24fe5907965e6dc7b7e226bdcd7f74a845ccc2bfee995f2fc627d0cf'
HOLDOUT_SHA256 = '818b491f19541c7703cc311afd498fe1169c223a1c03fb4902e275b46b7a9106'
PACKAGES = ['transformers==4.57.6', 'peft==0.20.0', 'accelerate==1.14.0', 'bitsandbytes==0.50.2', 'datasets==4.8.5',
            'jsonschema>=4,<5', 'pandas>=2,<3']

plan_sha = hashlib.sha256(PLAN.read_bytes()).hexdigest()
code = (HERE / 'posthoc.py').read_text(encoding='utf-8')

intro = f"""# 第三題：凍結後的事後分析

這不是凍結系統的一部分。計畫在執行前寫好：`evaluation/posthoc-plan.md`（sha256 `{plan_sha}`）。結果不論好壞，都不用來調整 prompt、知識卡、模型或微調權重，也不改寫既有判定。

- **實驗 A**：Qwen3-8B 以 16 位元載入兩張 T4、不載微調權重，用凍結的 prompt、知識卡、greedy 解碼與重寫規則審同樣 8 篇測試文章，和既有的 4-bit 無微調輸出比較，回答「YMYL 標太多是不是 4-bit 量化造成」。
- **實驗 B**：與訓練相同的 4-bit 載入，在 12 筆訓練資料的監督答案上計算載入與不載入微調權重時的交叉熵，回答「微調有沒有讓模型更接近答案」。不讀測試資料。

程式從凍結 bundle 匯入、不修改；只有模型載入方式（實驗 A）與 loss 計算（實驗 B）是新寫的。"""

setup = f"""import os,sys,json,hashlib,shutil,subprocess
from pathlib import Path
PLAN_SHA256='{plan_sha}'
LOCK_SHA256='{LOCK_SHA256}'
HOLDOUT_SHA256='{HOLDOUT_SHA256}'
INPUT=Path('/kaggle/input');WORK=Path('/kaggle/working');ROOT=WORK/'work03';POST=WORK/'posthoc'
def find(name):return sorted(Path(d)/name for d,_,fs in os.walk(INPUT,followlinks=True) if name in fs)
locks=[p for p in find('frozen.json') if p.parent.name=='outputs' and p.parent.parent.name=='work03']
assert len(locks)==1,locks
assert hashlib.sha256(locks[0].read_bytes()).hexdigest()==LOCK_SHA256,'Mounted train bundle is not the frozen lock'
shutil.copytree(locks[0].parent.parent,ROOT,ignore=shutil.ignore_patterns('__pycache__','trainer'))
(WORK/'posthoc.py').write_text({code!r},encoding='utf-8')
subprocess.run([sys.executable,'-m','pip','install',*{PACKAGES!r}],check=True)
env={{**os.environ,'WORK03_ROOT':str(ROOT),'POSTHOC_OUT':str(POST),'PYTORCH_CUDA_ALLOC_CONF':'expandable_segments:True'}}
# Frozen check: every locked file (prompt, knowledge, config, data, scripts, adapter) must match the lock.
subprocess.run([sys.executable,str(ROOT/'scripts/workflow.py'),'check-freeze'],check=True,env=env)"""

run_a = """holdouts=find('holdout8.csv')
assert len(holdouts)==1,holdouts
assert hashlib.sha256(holdouts[0].read_bytes()).hexdigest()==HOLDOUT_SHA256,'holdout8.csv bytes changed'
shutil.copyfile(holdouts[0],ROOT/'data/holdout8.csv')
subprocess.run([sys.executable,str(WORK/'posthoc.py'),'fp16'],check=True,env={**env,'CUDA_VISIBLE_DEVICES':'0,1'})"""

run_b = """subprocess.run([sys.executable,str(WORK/'posthoc.py'),'loss'],check=True,env={**env,'CUDA_VISIBLE_DEVICES':'0'})"""

show = """import pandas as pd
from IPython.display import display
rows=[json.loads(s) for s in (POST/'holdout_fp16.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
display(pd.DataFrame([dict(ID=r['ID'],first_pass_valid=r['first_pass_valid'],final_valid=r['final_valid'],
  Score=(r['parsed'] or {}).get('Score'),codes=','.join(x['code'] for x in (r['parsed'] or {}).get('Reasons',[])),
  severities=','.join(x['severity'] for x in (r['parsed'] or {}).get('Reasons',[]))) for r in rows]))
loss=json.loads((POST/'train_target_loss.json').read_text(encoding='utf-8'))
print({k:loss[k] for k in ['answer_tokens','ce_base','ce_adapter','relative_reduction']})
display(pd.DataFrame(loss['items']))
(POST/'plan_sha256.txt').write_text(PLAN_SHA256+'\\n',encoding='utf-8')
# Keep only the post-hoc outputs; the frozen bundle and the test CSV stay in their original kernels and dataset.
shutil.rmtree(ROOT)
print(sorted(p.name for p in POST.iterdir()))"""


def cell(kind, src):
    c = {'cell_type': kind, 'metadata': {}, 'source': src.splitlines(keepends=True)}
    if kind == 'code':
        c.update(execution_count=None, outputs=[])
    return c


nb = {'cells': [cell('markdown', intro), cell('code', setup),
                cell('markdown', '## 實驗 A：16 位元、不載微調，審 8 篇測試文章\n核對測試資料雜湊後才讀取；兩張 T4 分攤權重。'),
                cell('code', run_a),
                cell('markdown', '## 實驗 B：微調前後在 12 筆監督答案上的交叉熵\n不讀測試資料；同一個 4-bit 模型，分別啟用與停用微調權重。'),
                cell('code', run_b),
                cell('markdown', '## 結果摘要\n逐筆判讀與指標在本機依預先登錄的計畫計算。'),
                cell('code', show)],
      'metadata': {'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
                   'language_info': {'name': 'python'}},
      'nbformat': 4, 'nbformat_minor': 5}
(HERE / 'work03_posthoc.ipynb').write_text(json.dumps(nb, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
meta = {'id': 'pw95148637/soulo-work03-posthoc-fp16', 'title': 'Soulo Work03 Posthoc FP16',
        'code_file': 'work03_posthoc.ipynb', 'language': 'python', 'kernel_type': 'notebook', 'is_private': 'true',
        'enable_gpu': 'true', 'enable_tpu': 'false', 'enable_internet': 'true', 'machine_shape': 'NvidiaTeslaT4',
        'competition_sources': [], 'model_sources': [],
        'dataset_sources': ['pw95148637/soulo-work03-isolated-holdout8'],
        'kernel_sources': ['pw95148637/soulo-work03-v3b-train']}
(HERE / 'kernel-metadata.json').write_text(json.dumps(meta, indent=2) + '\n', encoding='utf-8', newline='\n')
print('plan sha256', plan_sha)
