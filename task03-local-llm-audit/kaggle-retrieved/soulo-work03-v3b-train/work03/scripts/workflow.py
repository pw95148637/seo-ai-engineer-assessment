"""Task03 local-weights workflow. GPU imports occur only in GPU stages.
Train kernel: preflight, train, consistency, selfcheck, baseline, freeze (holdout never mounted).
Eval kernel: check-freeze, evaluate (reads holdout only after the reviewed lock verifies).
WORK03_ROOT may point at a downloaded work03 bundle for offline gate/check-freeze."""
import argparse,csv,hashlib,html,itertools,json,os,sys,time
from pathlib import Path
from audit_io import parse,max_severity
ROOT=Path(os.environ.get('WORK03_ROOT') or Path(__file__).resolve().parents[1]).resolve()
OUT=ROOT/'outputs'
CONFIG_FILES=['run_config.json','schema.json','system_prompt.txt','knowledge.json','evaluation_policy.json','data/train12.csv','data/train_targets.jsonl','data/split-manifest.json']
FROZEN_OUTPUTS=['training.json','consistency.json','train_selfcheck.jsonl','train_selfcheck-raw.jsonl','train_gate.json','train_selfcheck_base.jsonl','train_selfcheck_base-raw.jsonl','baseline_comparison.json','hardware.json','model.json','smoke.json','requirements-resolved.txt']
ADAPTER_REQUIRED=['adapter/adapter_model.safetensors','adapter/adapter_config.json']
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def write(p,obj):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def jsonl(p):return [json.loads(s) for s in Path(p).read_text(encoding='utf-8').splitlines() if s.strip()]
def config():return read(ROOT/'run_config.json')
def knowledge_ids():return [k['id'] for k in read(ROOT/'knowledge.json')]
def data(split):
 with (ROOT/'data'/f'{split}.csv').open(encoding='utf-8-sig',newline='') as f:r=list(csv.DictReader(f))
 m=read(ROOT/'data/split-manifest.json');key='train_ids' if split=='train12' else 'holdout_ids'
 assert [x['ID'] for x in r]==m[key], 'Split IDs changed'
 return r
def messages(row):return [{'role':'system','content':(ROOT/'system_prompt.txt').read_text(encoding='utf-8')},{'role':'user','content':json.dumps({'article':row['Content Snippet (文章片段)'],'knowledge':read(ROOT/'knowledge.json')},ensure_ascii=False)}]
def targets():
 labels=jsonl(ROOT/'data/train_targets.jsonl');rows=data('train12')
 assert [x['ID'] for x in labels]==[x['ID'] for x in rows]
 sources=knowledge_ids()
 for a,b in zip(labels,rows):parse(json.dumps(a['target']),b['Content Snippet (文章片段)'],sources)
 return {x['ID']:x['target'] for x in labels}
def load(adapter=False):
 import torch
 from transformers import AutoTokenizer,AutoModelForCausalLM,BitsAndBytesConfig
 assert torch.cuda.is_available(),'Kaggle GPU required; no CPU or hosted inference replacement'
 c=config();assert c['model_revision'] and len(c['model_revision'])==40,'Run preflight first to record exact Hub revision'
 tok=AutoTokenizer.from_pretrained(c['model_id'],revision=c['model_revision']);tok.pad_token=tok.eos_token;tok.padding_side='right'
 q=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type='nf4',bnb_4bit_use_double_quant=True,bnb_4bit_compute_dtype=torch.float16)
 model=AutoModelForCausalLM.from_pretrained(c['model_id'],revision=c['model_revision'],quantization_config=q,device_map={'':0},torch_dtype=torch.float16)
 if adapter:
  from peft import PeftModel
  model=PeftModel.from_pretrained(model,str(OUT/'adapter'))
 return tok,model

def generate(tok,model,msg,temperature=None,seed=42):
 import torch
 from transformers import set_seed
 c=config();set_seed(seed);model.eval();torch.cuda.reset_peak_memory_stats(0)
 text=tok.apply_chat_template(msg,tokenize=False,add_generation_prompt=True,enable_thinking=False)
 x=tok(text,add_special_tokens=False,return_tensors='pt').to('cuda:0');assert x.input_ids.shape[1]+c['max_new_tokens']<=c['context_limit'],'Fixed generation context limit exceeded'
 # Stop on <|im_end|> (trained answer end) and <|endoftext|>, as Qwen3's own generation_config does.
 eos=[tok.eos_token_id]+[i for i in [tok.convert_tokens_to_ids('<|endoftext|>')] if isinstance(i,int) and i!=tok.eos_token_id]
 kw=dict(max_new_tokens=c['max_new_tokens'],do_sample=temperature is not None,pad_token_id=tok.eos_token_id,eos_token_id=eos)
 if temperature is not None:kw.update(temperature=temperature,top_p=.8,top_k=20)
 started=time.monotonic()
 with torch.inference_mode():y=model.generate(**x,**kw)
 t=y[0,x.input_ids.shape[1]:]
 return dict(raw=tok.decode(t,skip_special_tokens=True),seconds=time.monotonic()-started,input_tokens=int(x.input_ids.shape[1]),output_tokens=len(t),eos_reached=bool(len(t) and int(t[-1]) in eos),temperature=temperature,seed=seed,peak_gpu_bytes=torch.cuda.max_memory_allocated(0))

def preflight():
 import torch,subprocess,importlib.metadata as meta
 OUT.mkdir(exist_ok=True)
 env={'python':sys.version,'torch':torch.__version__,'cuda_available':torch.cuda.is_available(),'devices':[{'name':torch.cuda.get_device_name(i),'vram_bytes':torch.cuda.get_device_properties(i).total_memory} for i in range(torch.cuda.device_count())]}
 write(OUT/'hardware.json',env);assert env['cuda_available'],'Complete Kaggle phone verification and enable GPU'
 from huggingface_hub import HfApi
 c=config()
 if c['model_revision'] is None:
  c['model_revision']=HfApi().model_info(c['model_id']).sha;write(ROOT/'run_config.json',c)
 tok,model=load();r=generate(tok,model,[{'role':'user','content':'用繁體中文寫一句話，說明內容審核需要可核對的證據。'}]);assert r['raw'].strip()
 write(OUT/'smoke.json',r);write(OUT/'model.json',dict(model_id=c['model_id'],revision=c['model_revision'],parameters=model.num_parameters(),footprint_bytes=model.get_memory_footprint(),device_map=str(model.hf_device_map),versions={p:meta.version(p) for p in ['transformers','peft','bitsandbytes','accelerate','datasets']}))
 (OUT/'requirements-resolved.txt').write_text(subprocess.check_output([sys.executable,'-m','pip','freeze'],text=True),encoding='utf-8');print(r['raw'])

def examples(tok,rows,labels,max_length):
 result=[]
 for row in rows:
  p=tok.apply_chat_template(messages(row),tokenize=False,add_generation_prompt=True,enable_thinking=False)
  a=tok(p,add_special_tokens=False)['input_ids'];b=tok(json.dumps(labels[row['ID']],ensure_ascii=False,separators=(',',':'))+tok.eos_token,add_special_tokens=False)['input_ids']
  assert len(a)+len(b)<=max_length,f'Train {row["ID"]} exceeds length; no silent truncation'
  result.append(dict(input_ids=a+b,attention_mask=[1]*(len(a)+len(b)),labels=[-100]*len(a)+b))
 return result

def train():
 import torch
 from transformers import set_seed,Trainer,TrainingArguments,DataCollatorForSeq2Seq
 from peft import prepare_model_for_kbit_training,get_peft_model,LoraConfig
 from datasets import Dataset
 c=config();set_seed(c['seed']);labels=targets();rows=data('train12');tok,model=load();ds=examples(tok,rows,labels,c['max_length'])
 model=prepare_model_for_kbit_training(model,use_gradient_checkpointing=True)
 model=get_peft_model(model,LoraConfig(r=8,lora_alpha=16,lora_dropout=.05,target_modules=['q_proj','v_proj'],task_type='CAUSAL_LM'));model.config.use_cache=False
 before={n:p.detach().float().cpu().clone() for n,p in model.named_parameters() if p.requires_grad}
 args=TrainingArguments(output_dir=str(OUT/'trainer'),num_train_epochs=c['epochs'],learning_rate=c['learning_rate'],per_device_train_batch_size=1,gradient_accumulation_steps=4,fp16=True,logging_steps=1,save_strategy='no',report_to='none',seed=c['seed'],optim='adamw_torch')
 # v3b: v3-train OOMed at step 0 (full-sequence fp32 logits ~1.2 GiB on a 14.6 GiB T4). Prompt tokens are
 # label-masked anyway, so compute logits only from the first answer position; same loss, less memory.
 class AnswerOnlyTrainer(Trainer):
  def compute_loss(self,model,inputs,return_outputs=False,num_items_in_batch=None):
   labels=inputs.pop('labels');j0=max(1,int((labels!=-100).nonzero(as_tuple=True)[1].min()))
   out=model(**inputs,logits_to_keep=labels.shape[1]-j0+1)
   logits=out.logits[:,:-1,:].float();tgt=labels[:,j0:]
   loss=torch.nn.functional.cross_entropy(logits.reshape(-1,logits.size(-1)),tgt.reshape(-1),ignore_index=-100,reduction='sum')
   loss=loss/(num_items_in_batch if num_items_in_batch is not None else (tgt!=-100).sum())
   return (loss,out) if return_outputs else loss
 trainer=AnswerOnlyTrainer(model=model,args=args,train_dataset=Dataset.from_list(ds),data_collator=DataCollatorForSeq2Seq(tok,padding=True,label_pad_token_id=-100))
 r=trainer.train();assert trainer.state.global_step>0
 changed=sum(not torch.equal(before[n],p.detach().float().cpu()) for n,p in model.named_parameters() if p.requires_grad);assert changed>0,'Adapter did not change'
 model.save_pretrained(OUT/'adapter');tok.save_pretrained(OUT/'adapter')
 write(OUT/'training.json',dict(global_step=trainer.state.global_step,changed_adapter_tensors=changed,metrics=r.metrics,logs=trainer.state.log_history,train_ids=[x['ID'] for x in rows],lengths=[len(x['input_ids']) for x in ds],targets_sha256=sha(ROOT/'data/train_targets.jsonl'),prompt_sha256=sha(ROOT/'system_prompt.txt'),config=c,claim='Actual training, not proof of generalization'))

def selfcheck():
 """Train-only semantic self-check: same greedy decoding and one-repair rule as holdout evaluation."""
 tok,model=load(adapter=True)
 batch(data('train12'),lambda msg:generate(tok,model,msg),OUT/'train_selfcheck.jsonl')
 gate()

def gate():
 from selfcheck import train_gate
 assert not (OUT/'frozen.json').exists(),'Bundle already frozen: read outputs/train_gate.json; rewriting it would invalidate the lock'
 p=OUT/'train_selfcheck.jsonl'
 g=train_gate(data('train12'),jsonl(p) if p.exists() else None,read(OUT/'consistency.json'),targets(),knowledge_ids())
 write(OUT/'train_gate.json',g)
 print(json.dumps({k:g[k] for k in ['status','selfcheck_first_pass_valid','selfcheck_final_valid','consistency_valid']},ensure_ascii=False))
 for f in g['hard_failures']:print('HARD',f['where'],f['code'],f['detail'])
 for f in g['soft_flags']:print('soft',f['where'],f['code'],f['detail'])

def baseline():
 """Same prompt, greedy decoding and repair rule on train12 without the adapter: measures what the LoRA adds."""
 tok,model=load(adapter=False)
 batch(data('train12'),lambda msg:generate(tok,model,msg),OUT/'train_selfcheck_base.jsonl')
 compare()

def compare():
 from selfcheck import train_gate
 rows=data('train12');T=targets();src=knowledge_ids();cons=read(OUT/'consistency.json')
 g={k:train_gate(rows,jsonl(OUT/f),cons,T,src) for k,f in [('adapter','train_selfcheck.jsonl'),('base','train_selfcheck_base.jsonl')]}
 def hard(x):
  c={}
  for f in x['hard_failures']:
   if not f['where'].startswith('consistency'):c[f['code']]=c.get(f['code'],0)+1
  return c
 items=[dict(ID=a['ID'],target_score=a['target_score'],target_severity=a['target_severity'],adapter_score=a['Score'],base_score=b['Score'],adapter_severity=a['severity'],base_severity=b['severity'],adapter_codes=a['codes'],base_codes=b['codes'],adapter_flags=a['flags'],base_flags=b['flags']) for a,b in zip(g['adapter']['items'],g['base']['items'])]
 write(OUT/'baseline_comparison.json',dict(note='Same prompt, greedy decoding and repair rule; base has no adapter. train12 is in-sample for the adapter, so this bounds what LoRA adds, not generalisation.',hard_counts={k:hard(x) for k,x in g.items()},first_pass_valid={k:x['selfcheck_first_pass_valid'] for k,x in g.items()},items=items))
 print(json.dumps({k:hard(x) for k,x in g.items()},ensure_ascii=False))

def freeze():
 """Candidate lock written by the train kernel; it becomes the freeze only when its sha256 is embedded in the eval notebook."""
 assert not (OUT/'holdout.jsonl').exists() and not (ROOT/'data/holdout8.csv').exists(),'Cannot reset freeze after holdout is present'
 assert not (OUT/'frozen.json').exists(),'Lock already written; a new lock would not match the reviewed Kaggle output'
 missing=[n for n in FROZEN_OUTPUTS+ADAPTER_REQUIRED if not (OUT/n).is_file()];assert not missing,f'Train outputs missing; nothing to freeze: {missing}'
 assert read(OUT/'training.json')['changed_adapter_tensors']>0
 g=read(OUT/'train_gate.json')
 files=[ROOT/n for n in CONFIG_FILES]+sorted((ROOT/'scripts').glob('*.py'))+[OUT/n for n in FROZEN_OUTPUTS]+sorted((OUT/'adapter').rglob('*'))
 lock=dict(created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),train_gate_status=g['status'],hard_failures=len(g['hard_failures']),hashes={p.relative_to(ROOT).as_posix():sha(p) for p in files if p.is_file()})
 write(OUT/'frozen.json',lock)
def check_freeze():
 lock=read(OUT/'frozen.json')
 for n,d in lock['hashes'].items():assert (ROOT/n).is_file() and sha(ROOT/n)==d,f'Frozen file changed or missing: {n}'
 extra=[p.relative_to(ROOT).as_posix() for p in (ROOT/'scripts').glob('*.py') if p.relative_to(ROOT).as_posix() not in lock['hashes']]
 assert not extra,f'Unfrozen scripts present: {extra}'
 print(f"PASS: {len(lock['hashes'])} frozen files verified; train gate {lock['train_gate_status']}")
 return lock

def audit_one(row,call,sink=lambda x:None):
 msg=messages(row);attempts=[];obj=None;sources=knowledge_ids()
 for i in range(2):
  try:r=call(msg)
  except Exception as e:return dict(ID=row['ID'],attempts=attempts,parsed=None,first_pass_valid=False,final_valid=False,runtime_error=f'{type(e).__name__}: {e}')
  sink(dict(ID=row['ID'],attempt=i,result=r));attempts.append(r)
  try:obj=parse(r['raw'],row['Content Snippet (文章片段)'],sources);r['validation_error']=None;break
  except Exception as e:
   r['validation_error']=str(e)[:500]
   msg=msg+[{'role':'assistant','content':r['raw']},{'role':'user','content':'請只修正下列錯誤（JSON結構、原文引句、來源ID或Score區間），不增加新主張。錯誤：'+r['validation_error']}]
 return dict(ID=row['ID'],attempts=attempts,parsed=obj,first_pass_valid=attempts[0]['validation_error'] is None,final_valid=obj is not None)

def batch(rows,call,path):
 raw_path=path.with_name(path.stem+'-raw.jsonl');assert not path.exists() and not raw_path.exists(),'Keep earlier outputs; use a fresh run directory'
 with path.open('w',encoding='utf-8') as f,raw_path.open('w',encoding='utf-8') as rf:
  def sink(x):rf.write(json.dumps(x,ensure_ascii=False)+'\n');rf.flush()
  for row in rows:
   r=audit_one(row,call,sink);f.write(json.dumps(r,ensure_ascii=False)+'\n');f.flush()

def consistency_summary(runs):
 valid=[r for r in runs if r.get('parsed') is not None];scores=[r['parsed']['Score'] for r in valid];pairs=[]
 for a,b in itertools.combinations(runs,2):
  if a.get('parsed') is None or b.get('parsed') is None:j=None
  else:
   x={r['code'] for r in a['parsed']['Reasons']};y={r['code'] for r in b['parsed']['Reasons']};j=len(x&y)/len(x|y) if x|y else 1.
  pairs.append(dict(temperature_a=a['temperature'],temperature_b=b['temperature'],code_jaccard=j))
 return dict(valid_n=len(valid),total=len(runs),score_range=max(scores)-min(scores) if scores else None,pairs=pairs,advice_conflicts='Requires semantic review; code agreement does not prove advice agreement')

def consistency():
 tok,model=load(adapter=True);row=next(r for r in data('train12') if r['ID']=='14');runs=[];sources=knowledge_ids()
 for t in [.2,.5,.8]:
  r=generate(tok,model,messages(row),temperature=t,seed=42)
  # No repair/cherry-picking in consistency experiment.
  try:r['parsed']=parse(r['raw'],row['Content Snippet (文章片段)'],sources)
  except Exception as e:r['parsed']=None;r['validation_error']=str(e)
  runs.append(r);write(OUT/'consistency.json',dict(ID=row['ID'],runs=runs,summary=consistency_summary(runs)))

def evaluate():
 import torch,importlib.metadata as meta
 lock=check_freeze()
 # Same pinned libraries as the train run (checked before holdout is read); a Kaggle image torch change is recorded, not blocked.
 trained=read(OUT/'model.json')['versions'];now={p:meta.version(p) for p in trained}
 assert now==trained,f'Library versions differ from the train run: {now} vs {trained}'
 train_torch=read(OUT/'hardware.json')['torch']
 if torch.__version__!=train_torch:print('WARNING: torch',torch.__version__,'differs from train run',train_torch)
 rows=data('holdout8')
 write(OUT/'eval_env.json',dict(started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),lock_sha256=sha(OUT/'frozen.json'),python=sys.version,torch=torch.__version__,train_torch=train_torch,same_torch=torch.__version__==train_torch,gpu=torch.cuda.get_device_name(0),versions=now,holdout_sha256=sha(ROOT/'data/holdout8.csv'),train_gate_status=lock['train_gate_status']))
 tok,model=load(adapter=True)
 batch(rows,lambda msg:generate(tok,model,msg),OUT/'holdout.jsonl');report()

def structural_metrics(results):
 n=len(results);assert n
 return dict(n=n,first_pass_json_valid=sum(r['first_pass_valid'] for r in results),final_json_valid=sum(r['final_valid'] for r in results),first_pass_json_rate=sum(r['first_pass_valid'] for r in results)/n,final_json_rate=sum(r['final_valid'] for r in results)/n,note='Contract validity (schema, quotes, sources, Score within the highest-severity band) is not diagnostic accuracy')

def report_html(df,metrics):
 import pandas as pd
 e=lambda v:html.escape('' if v is None or (not isinstance(v,(list,dict)) and pd.isna(v)) else str(v))
 def items(v):
  try:xs=json.loads(v) if isinstance(v,str) and v else []
  except ValueError:xs=[]
  return '<ul>'+''.join('<li>'+(e(x) if isinstance(x,str) else f"<b>{e(x.get('code'))}</b> <i>{e(x.get('severity'))}</i>「{e(x.get('quote'))}」{e(x.get('explanation'))} <small>{e(','.join(x.get('source_ids',[])))}</small>")+'</li>' for x in (xs or []))+'</ul>'
 rows=''.join(f"<tr><td>{e(r.ID)}</td><td>{e(r.Category)}</td><td data-v='{e(r.Score)}'>{e(r.Score)}</td><td>{e(r.MaxSeverity)}</td><td>{e(r.Codes)}</td><td>{items(r.Reasons)}</td><td>{items(r.Advice)}</td><td>{e(r.AutoFlags)}</td><td>{e(r.FirstPassValid)}/{e(r.FinalValid)}</td><td><details><summary>文章與最後一次原始輸出</summary><p>{e(r.Article)}</p><pre>{e(r.Raw)}</pre>{e(r.Error)}</details></td></tr>" for r in df.itertuples())
 return ('<!doctype html><meta charset="utf-8"><title>Work03 holdout8 audit</title><style>body{font-family:sans-serif;margin:16px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:6px;vertical-align:top;font-size:14px}th{cursor:pointer;background:#f3f3f3}pre{white-space:pre-wrap}</style>'
  f"<h1>8筆獨立審核（凍結後一次執行）</h1><p>輸出契約（JSON schema、原文引句、來源ID、Score落在最高severity區間）首次有效 {metrics['first_pass_json_valid']}/{metrics['n']}，修正後 {metrics['final_json_valid']}/{metrics['n']}。AutoFlags為凍結前預先設定的啟發式檢查，不是準確率；逐筆品質見manual_review.csv。</p>"
  '<input id="q" placeholder="篩選（ID、代碼、旗標或任意文字）" style="width:100%;padding:6px;margin:8px 0">'
  '<table id="t"><thead><tr><th>ID</th><th>類別</th><th>Score</th><th>最高severity</th><th>代碼</th><th>Reasons</th><th>Actionable Advice</th><th>AutoFlags</th><th>JSON首次/最終</th><th>原文</th></tr></thead><tbody>'+rows+'</tbody></table>'
  "<script>const q=document.getElementById('q'),b=document.querySelector('#t tbody');q.oninput=()=>{for(const r of b.rows)r.style.display=r.textContent.toLowerCase().includes(q.value.toLowerCase())?'':'none'};"
  "document.querySelectorAll('#t th').forEach((h,i)=>{let asc=true;h.onclick=()=>{const rs=[...b.rows];rs.sort((x,y)=>{const a=x.cells[i].dataset.v??x.cells[i].textContent,c=y.cells[i].dataset.v??y.cells[i].textContent,n=parseFloat(a)-parseFloat(c);return (isNaN(n)?a.localeCompare(c):n)*(asc?1:-1)});asc=!asc;rs.forEach(r=>b.appendChild(r))}})</script>")

def report():
 import pandas as pd
 from selfcheck import item_flags,flag_text,raw_flags
 results=jsonl(OUT/'holdout.jsonl');rows=data('holdout8')
 assert len(results)==8 and [r['ID'] for r in results]==[r['ID'] for r in rows]
 records=[];flag_counts={}
 for row,r in zip(rows,results):
  obj=r['parsed'] or {};flags=item_flags(row,r['parsed'])+raw_flags(r['attempts'],r['parsed'])
  for f in flags:k=f"{f['level']}:{f['code']}";flag_counts[k]=flag_counts.get(k,0)+1
  records.append(dict(ID=row['ID'],Category=row['Category'],Article=row['Content Snippet (文章片段)'],Score=obj.get('Score'),MaxSeverity=(max_severity(obj) or 'none') if obj else '',Codes=','.join(x['code'] for x in obj.get('Reasons',[])),Reasons=json.dumps(obj.get('Reasons'),ensure_ascii=False),Advice=json.dumps(obj.get('Actionable Advice'),ensure_ascii=False),AutoFlags=flag_text(flags),FirstPassValid=r['first_pass_valid'],FinalValid=r['final_valid'],Error=r.get('runtime_error') or (r['attempts'][-1].get('validation_error') or '' if r['attempts'] else ''),Raw=r['attempts'][-1]['raw'] if r['attempts'] else ''))
 df=pd.DataFrame(records);df['Score']=df['Score'].astype('Int64');df.to_csv(OUT/'audit_report.csv',index=False,encoding='utf-8-sig')
 m=dict(structural_metrics(results),auto_flag_counts=flag_counts,auto_flag_note='Pre-registered heuristics, not accuracy')
 (OUT/'audit_report.html').write_text(report_html(df,m),encoding='utf-8')
 write(OUT/'metrics.json',m)
 path=OUT/'manual_review.csv'
 if not path.exists():
  with path.open('w',newline='',encoding='utf-8-sig') as f:
   w=csv.writer(f);w.writerow(['ID','required_codes','missed_critical_risk','false_positive','source_support_0_2','advice_actionability_0_2','accurate_or_bias_explanation','source_urls'])
   for row in rows:w.writerow([row['ID']]+['']*7)
 print(df[['ID','Score','MaxSeverity','Codes','AutoFlags','FirstPassValid','FinalValid']].to_string(index=False))

if __name__=='__main__':
 for s in (sys.stdout,sys.stderr):s.reconfigure(errors='replace')  # Windows cp950 console: never crash on model text
 p=argparse.ArgumentParser();p.add_argument('stage',choices=['check-targets','preflight','train','consistency','selfcheck','baseline','compare','gate','freeze','check-freeze','evaluate','report']);a=p.parse_args()
 if a.stage=='check-targets':targets();print('PASS: 12 train-only targets validated')
 else:globals()[a.stage.replace('-','_')]()
