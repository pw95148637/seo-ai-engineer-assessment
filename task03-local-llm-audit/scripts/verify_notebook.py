"""Offline checks for the two-stage Kaggle notebooks and kernel metadata. Holdout text is compared mechanically, never printed."""
import ast,csv,hashlib,json,re,tempfile,nbformat
from pathlib import Path
import build_notebook as B
from workflow import FROZEN_OUTPUTS,ADAPTER_REQUIRED
root=B.R
def check_nb(path_or_nb):
 n=nbformat.reads(B.dump(path_or_nb),as_version=4) if isinstance(path_or_nb,dict) else nbformat.read(path_or_nb,as_version=4)
 nbformat.validate(n);count=0
 for c in n.cells:
  if c.cell_type=='code':ast.parse(c.source);count+=1
 assert not any(c.get('outputs') for c in n.cells),'Notebook must not embed model outputs'
 return count
count=check_nb(B.CANONICAL)
assert B.CANONICAL.read_text(encoding='utf-8')==B.dump(B.notebook(B.cells('train'))),'Notebook is stale; run scripts/build_notebook.py'
assert B.TRAIN_NB.read_bytes()==B.CANONICAL.read_bytes(),'kaggle/train notebook differs from canonical; rebuild'
with (root/'data/holdout8.csv').open(encoding='utf-8-sig',newline='') as f:hold=[r['Content Snippet (文章片段)'] for r in csv.DictReader(f)]
# Compare decoded text (payload files and cell sources), so escaping cannot hide a snippet; 12-character overlaps catch partial copies.
texts=list(B.payload().values())+[c.source for p in (B.CANONICAL,B.EVAL_NB) if p.exists() for c in nbformat.read(p,as_version=4).cells]
assert len(hold)==8 and not any(s in t for s in hold for t in texts),'Holdout snippet embedded'
grams={s[i:i+12] for s in hold for i in range(len(s)-11)}
overlap={n:sum(g in t for g in grams) for n,t in B.payload().items()}
assert not any(overlap.values()),f'Holdout 12-character overlap in payload (counts only): { {k:v for k,v in overlap.items() if v} }'
tm=json.loads((root/'kaggle/train/kernel-metadata.json').read_text(encoding='utf-8'));em=json.loads((root/'kaggle/eval/kernel-metadata.json').read_text(encoding='utf-8'))
for m in (tm,em):assert m['is_private']=='true' and m['enable_gpu']=='true' and m['machine_shape']=='NvidiaTeslaT4' and m['kernel_type']=='notebook' and m['language']=='python'
assert tm['dataset_sources']==[] and tm['kernel_sources']==[] and tm['code_file']==B.TRAIN_NB.name,'Train kernel must not mount holdout or other bundles'
# Eval mounts exactly one train kernel of the same Kaggle account (the frozen one, not necessarily the latest train metadata id),
# so a reproduction under another account only has to rename the ids.
owner=em['id'].split('/')[0]
assert len(em['kernel_sources'])==1 and re.fullmatch(re.escape(owner)+r'/[a-z0-9-]+-train',em['kernel_sources'][0]) and len(em['dataset_sources'])==1 and em['code_file']==B.EVAL_NB.name,'Eval must mount exactly one <account>/<name>-train kernel and one holdout dataset'
assert not any(k in json.dumps(m).lower() for m in (tm,em) for k in ('key','token','password')),'No credentials in metadata'
# Eval build path with a synthetic lock in a temp dir (never published): PASS builds, FAIL needs a reason,
# drift, a tampered download or a lock without the adapter refuses.
def refused(*args):
 try:B.review_lock(*args)
 except AssertionError:return True
 return False
with tempfile.TemporaryDirectory() as d:
 o0=Path(d)/'work03/outputs';(o0/'adapter').mkdir(parents=True)
 for n in FROZEN_OUTPUTS+ADAPTER_REQUIRED:(o0/n).write_text('synthetic',encoding='utf-8')
 gate=o0/'train_gate.json';lockp=o0/'frozen.json'
 def make(status):
  gate.write_text(json.dumps(dict(status=status,hard_failures=[] if status=='PASS' else [{'code':'X'}])),encoding='utf-8')
  h={n:B.text_sha(t) for n,t in B.payload().items()}
  h.update({'outputs/'+p.relative_to(o0).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in o0.rglob('*') if p.is_file() and p!=lockp})
  lockp.write_text(json.dumps(dict(created_utc='synthetic',hashes=h)),encoding='utf-8');return h
 make('PASS');lock_sha,dec=B.review_lock(lockp);check_nb(B.notebook(B.cells('eval',lock_sha,dec)))
 make('FAIL');assert refused(lockp),'Failed gate accepted without reason'
 assert B.review_lock(lockp,'synthetic reason')[1]['accepted_failed_gate_reason']=='synthetic reason'
 h=make('PASS');h['system_prompt.txt']='0'*64;lockp.write_text(json.dumps(dict(hashes=h)),encoding='utf-8')
 assert refused(lockp),'Drifted prompt accepted'
 make('PASS');(o0/'adapter/adapter_model.safetensors').write_text('tampered',encoding='utf-8');assert refused(lockp),'Tampered adapter download accepted'
 h=make('PASS');del h['outputs/adapter/adapter_model.safetensors'];lockp.write_text(json.dumps(dict(hashes=h)),encoding='utf-8')
 assert refused(lockp),'Lock without adapter accepted'
 # Post-freeze code changes: only measurement/eval scripts, only with a reason; the contract and prompt never.
 def relock(**changed):
  h=make('PASS');h.update(changed);lockp.write_text(json.dumps(dict(hashes=h)),encoding='utf-8')
 relock(**{'scripts/selfcheck.py':'0'*64});assert refused(lockp),'Undeclared post-freeze code change accepted'
 assert set(B.review_lock(lockp,None,'synthetic')[1]['code_changes'])=={'scripts/selfcheck.py'}
 relock(**{'scripts/audit_io.py':'0'*64});assert refused(lockp,None,'synthetic'),'Contract change accepted after freeze'
 relock(**{'system_prompt.txt':'0'*64});assert refused(lockp,'x','synthetic'),'Prompt change accepted after freeze'
 # workflow.py: the bundle copy must be the frozen one; default-deny outside the exempt report/eval-glue statements.
 wl=B.payload()['scripts/workflow.py'];assert 'top_p=.8' in wl;(o0.parent/'scripts').mkdir(exist_ok=True);fw=o0.parent/'scripts/workflow.py'
 for frozen,ok in ((wl.replace('同prompt無adapter對照','對照'),True),(wl+'\ndef retired_stage():pass\n',False),(wl.replace('top_p=.8','top_p=.9'),False),(wl.replace("enable_thinking=False)\n x=","enable_thinking=True)\n x="),False)):
  assert frozen!=wl;fw.write_text(frozen,encoding='utf-8',newline='');relock(**{'scripts/workflow.py':B.text_sha(frozen)})
  assert refused(lockp,None,'synthetic')!=ok,('post-freeze guard',ok)
 relock(**{'scripts/workflow.py':'0'*64});assert refused(lockp,None,'synthetic'),'workflow.py change accepted without the frozen bundle copy'
 # Module-level wrappers, side effects, new imports or a remapped CLI dispatch are caught; changed CLI choices alone are not.
 disp="globals()[a.stage.replace('-','_')]()";assert disp in wl and "'evaluate-base'," in wl
 assert B.post_freeze_diff(wl,wl+'\nimport functools\ngenerate=functools.partial(generate,temperature=.7)\n')
 assert B.post_freeze_diff(wl,wl+"\nos.environ['X']='1'\n")
 assert B.post_freeze_diff(wl,wl.replace(disp,"globals()[a.stage.replace('-','_').replace('evaluate','evaluate_base')]()"))==['__main__']
 assert B.post_freeze_diff(wl,wl.replace("'evaluate-base',","'evaluate-base','extra',"))==[]
# Rehearse the train->eval seam on a Kaggle-style payload: gate, freeze, check-freeze, lock review, tamper detection.
import os,shutil,subprocess,sys
with tempfile.TemporaryDirectory() as d:
 w=Path(d)/'work03'
 for n,t in B.payload().items():(w/n).parent.mkdir(parents=True,exist_ok=True);(w/n).write_text(t,encoding='utf-8',newline='')
 o=w/'outputs';(o/'adapter').mkdir(parents=True);(o/'adapter/adapter_model.safetensors').write_bytes(b'synthetic')
 (o/'training.json').write_text(json.dumps({'changed_adapter_tensors':1}),encoding='utf-8')
 (o/'model.json').write_text(json.dumps({'versions':{}}),encoding='utf-8');(o/'hardware.json').write_text(json.dumps({'torch':'stub'}),encoding='utf-8')
 shutil.copyfile(root/'outputs/experiments/initial/consistency.json',o/'consistency.json')
 env={**os.environ,'WORK03_ROOT':str(w),'PYTHONIOENCODING':'utf-8'}
 wf=lambda s:subprocess.run([sys.executable,str(root/'scripts/workflow.py'),s],env=env,capture_output=True,text=True,encoding='utf-8')
 assert wf('gate').returncode==0,'gate'
 assert wf('freeze').returncode!=0 and not (o/'frozen.json').exists(),'freeze accepted missing train outputs'
 for n in FROZEN_OUTPUTS+ADAPTER_REQUIRED:
  if not (o/n).exists():(o/n).write_text('synthetic',encoding='utf-8')
 for s in ('freeze','check-freeze'):assert wf(s).returncode==0,s
 for s in ('gate','freeze'):assert wf(s).returncode!=0,f'{s} rewrote a frozen bundle'
 assert B.review_lock(o/'frozen.json','rehearsal')[1]['gate_status']=='FAIL'
 # Eval kernel after a declared post-freeze code change: undeclared fails, declared (lock, frozen and eval sha256) passes,
 # a wrong eval hash or a declared change to the contract (audit_io.py) fails.
 lk=json.loads((o/'frozen.json').read_text(encoding='utf-8'));fsha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
 def decide(**ch):(o/'freeze_decision.json').write_text(json.dumps(dict(lock_sha256=fsha(o/'frozen.json'),code_changes={n:dict(frozen_sha256=lk['hashes'][n],eval_sha256=s) for n,s in ch.items()})),encoding='utf-8')
 sc,ai=w/'scripts/selfcheck.py',w/'scripts/audit_io.py';sc0,ai0=sc.read_bytes(),ai.read_bytes()
 sc.write_bytes(sc0+b'\n# post-freeze fix\n');assert wf('check-freeze').returncode!=0,'Undeclared post-freeze change passed check-freeze'
 decide(**{'scripts/selfcheck.py':fsha(sc)});assert wf('check-freeze').returncode==0,'Declared post-freeze change refused'
 decide(**{'scripts/selfcheck.py':'0'*64});assert wf('check-freeze').returncode!=0,'Wrong declared hash passed'
 ai.write_bytes(ai0+b'\n#x\n');decide(**{'scripts/selfcheck.py':fsha(sc),'scripts/audit_io.py':fsha(ai)});assert wf('check-freeze').returncode!=0,'Contract change passed check-freeze'
 sc.write_bytes(sc0);ai.write_bytes(ai0);(o/'freeze_decision.json').unlink();assert wf('check-freeze').returncode==0
 pr=(w/'system_prompt.txt').read_bytes()
 (w/'system_prompt.txt').write_text('tampered',encoding='utf-8');assert wf('check-freeze').returncode!=0,'Tampered prompt passed check-freeze'
 (w/'system_prompt.txt').write_bytes(pr)
 # Eval post-processing on synthetic rows (train12 text relabelled with holdout IDs; real holdout untouched):
 # one valid, one repaired, one runtime failure, so CSV/HTML/metrics keep failures in the denominator.
 m=json.loads((w/'data/split-manifest.json').read_text(encoding='utf-8'))
 with (w/'data/train12.csv').open(encoding='utf-8-sig',newline='') as f:tr=list(csv.DictReader(f))
 syn=[dict(tr[i],ID=h) for i,h in enumerate(m['holdout_ids'])]
 with (w/'data/holdout8.csv').open('w',encoding='utf-8',newline='') as f:wr=csv.DictWriter(f,fieldnames=list(tr[0]));wr.writeheader();wr.writerows(syn)
 # Eval glue with a recording fake model and a stub torch (no GPU): check-freeze passes first, base refuses to run before
 # the adapter, load gets adapter=True then False, generate gets exactly (tok, model, msg), each run lands in its own file.
 glue=("import json,sys,types,workflow as W\n"
  "sys.modules['torch']=types.SimpleNamespace(__version__='stub',cuda=types.SimpleNamespace(get_device_name=lambda i:'stub'))\n"
  "loads,gens=[],[]\nW.load=lambda *a,**k:(loads.append((a,k)),('tok',len(loads)))[1]\n"
  "def gen(*a,**k):\n gens.append((len(a),sorted(k),a[1]));return dict(raw=json.dumps({'Reasons':[],'Score':90,'Actionable Advice':['核對來源']},ensure_ascii=False))\n"
  "W.generate=gen\ntry:W.evaluate_base()\nexcept AssertionError:pass\nelse:raise SystemExit('base ran before the adapter')\n"
  "W.evaluate();W.evaluate_base()\nassert loads==[((),{'adapter':True}),((),{'adapter':False})],loads\n"
  "assert [(n,k) for n,k,_ in gens]==[(3,[])]*16 and [m for *_,m in gens]==[1]*8+[2]*8,gens")
 r=subprocess.run([sys.executable,'-c',glue],env={**env,'PYTHONPATH':str(root/'scripts')},capture_output=True,text=True,encoding='utf-8')
 assert r.returncode==0,('eval glue rehearsal',r.stdout[-300:],r.stderr[-500:])
 assert json.loads((o/'eval_env.json').read_text(encoding='utf-8'))['train_gate_status']=='FAIL'
 assert all(len((o/n).read_text(encoding='utf-8').splitlines())==8 for n in ('holdout.jsonl','holdout-raw.jsonl','holdout_base.jsonl','holdout_base-raw.jsonl'))
 for n in ('holdout.jsonl','holdout-raw.jsonl','holdout_base.jsonl','holdout_base-raw.jsonl','eval_env.json'):(o/n).unlink()
 tg={json.loads(s)['ID']:json.loads(s)['target'] for s in (w/'data/train_targets.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()}
 res=[]
 for i,(r,t) in enumerate(zip(syn,tr)):
  ok=dict(raw=json.dumps(tg[t['ID']],ensure_ascii=False),validation_error=None)
  res.append(dict(ID=r['ID'],attempts=[],parsed=None,first_pass_valid=False,final_valid=False,runtime_error='RuntimeError: synthetic') if i==0 else
             dict(ID=r['ID'],attempts=[dict(raw='bad',validation_error='x'),ok] if i==1 else [ok],parsed=tg[t['ID']],first_pass_valid=i!=1,final_valid=True))
 (o/'holdout.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in res),encoding='utf-8')
 assert wf('report').returncode==0,'report failed on synthetic holdout-shaped rows'
 import pandas as pd
 df=pd.read_csv(o/'audit_report.csv',encoding='utf-8-sig');met=json.loads((o/'metrics.json').read_text(encoding='utf-8'))
 assert len(df)==8 and met['first_pass_json_valid']==6 and met['final_json_valid']==7 and (o/'audit_report.html').read_text(encoding='utf-8').count('<tr>')==9
 assert len(pd.read_csv(o/'manual_review.csv',encoding='utf-8-sig'))==8
 assert df.loc[1,'Raw']!='bad' and df.loc[0,'Error']=='RuntimeError: synthetic','report must show the final attempt and runtime errors'
 assert 'not available' in met['base']['note'] and not (o/'holdout_comparison.csv').exists(),'report without a base run'
 # Base (no adapter) run through the real holdout_run/batch/audit_one path with a fake model (no GPU): the loader must be
 # called with adapter=False and the output lands in holdout_base.jsonl; a partial base file never blocks the adapter report.
 (o/'holdout_base.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in res[:3]),encoding='utf-8')
 assert wf('report').returncode==0 and '3/8' in json.loads((o/'metrics.json').read_text(encoding='utf-8'))['base']['note'];(o/'holdout_base.jsonl').unlink()
 fake=("import json,workflow as W\nseen=[]\nW.load=lambda adapter=False:(seen.append(adapter),(None,None))[1]\n"
  "W.generate=lambda tok,model,msg:dict(raw=json.dumps({'Reasons':[],'Score':90,'Actionable Advice':['核對來源']},ensure_ascii=False))\n"
  "W.holdout_run(W.data('holdout8'),False);assert seen==[False],seen")
 assert subprocess.run([sys.executable,'-c',fake],env={**env,'PYTHONPATH':str(root/'scripts')},capture_output=True,text=True,encoding='utf-8').returncode==0,'base holdout_run failed'
 assert len((o/'holdout_base.jsonl').read_text(encoding='utf-8').splitlines())==8 and len((o/'holdout_base-raw.jsonl').read_text(encoding='utf-8').splitlines())==8
 assert wf('report').returncode==0,'report failed with a base run'
 met=json.loads((o/'metrics.json').read_text(encoding='utf-8'));cmp=pd.read_csv(o/'holdout_comparison.csv',encoding='utf-8-sig')
 assert met['base']['final_json_valid']==8 and len(cmp)==8 and list(cmp['base_score'])==[90]*8 and len(pd.read_csv(o/'audit_report_base.csv',encoding='utf-8-sig'))==8
 assert '無adapter對照' in (o/'audit_report.html').read_text(encoding='utf-8') and met['final_json_valid']==7,'adapter metrics must stay the adapter run'
if B.EVAL_NB.exists():
 check_nb(B.EVAL_NB);et=B.EVAL_NB.read_text(encoding='utf-8');assert 'EXPECTED_LOCK_SHA256=None' not in et
 # The eval notebook embeds the current payload and the lock of the train kernel it mounts (when that output is downloaded).
 pay=lambda cs:next(c['source'] for c in cs if c['cell_type']=='code' and 'payload=' in c['source'])
 assert pay(nbformat.read(B.EVAL_NB,as_version=4).cells)==pay(B.cells('train')),'eval notebook payload is stale; rebuild with --lock'
 lp=root/'kaggle-retrieved'/em['kernel_sources'][0].split('/')[1]/'work03/outputs/frozen.json'
 if lp.exists():assert f"EXPECTED_LOCK_SHA256={hashlib.sha256(lp.read_bytes()).hexdigest()!r}" in et,'eval notebook lock is not the mounted train kernel output'
for p in (root/'scripts').glob('*.py'):ast.parse(p.read_text(encoding='utf-8'))
print(f"PASS: train notebook current ({count} code cells); kaggle/train copy identical; no holdout text; metadata separation; train->eval seam and report rehearsed on synthetic rows; eval build gated by lock {'(eval notebook present)' if B.EVAL_NB.exists() else '(eval notebook not built yet)'}; all scripts parse; no model outputs")
