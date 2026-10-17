"""Task03 local-weights workflow. GPU imports occur only in GPU stages."""
import argparse,csv,hashlib,itertools,json,sys,time
from pathlib import Path
from audit_io import parse
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs'
def read(p):return json.loads(Path(p).read_text())
def write(p,obj):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj,ensure_ascii=False,indent=2))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def config():return read(ROOT/'run_config.json')
def data(split):
 with (ROOT/'data'/f'{split}.csv').open(encoding='utf-8-sig',newline='') as f:r=list(csv.DictReader(f))
 m=read(ROOT/'data/split-manifest.json');key='train_ids' if split=='train12' else 'holdout_ids'
 assert [x['ID'] for x in r]==m[key], 'Split IDs changed'
 return r
def messages(row):return [{'role':'system','content':(ROOT/'system_prompt.txt').read_text()},{'role':'user','content':json.dumps({'article':row['Content Snippet (文章片段)'],'knowledge':read(ROOT/'knowledge.json')},ensure_ascii=False)}]
def targets():
 labels=[json.loads(s) for s in (ROOT/'data/train_targets.jsonl').read_text().splitlines() if s.strip()];rows=data('train12')
 assert [x['ID'] for x in labels]==[x['ID'] for x in rows]
 sources=[k['id'] for k in read(ROOT/'knowledge.json')]
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
 kw=dict(max_new_tokens=c['max_new_tokens'],do_sample=temperature is not None,pad_token_id=tok.eos_token_id,eos_token_id=tok.eos_token_id)
 if temperature is not None:kw.update(temperature=temperature,top_p=.8,top_k=20)
 started=time.monotonic()
 with torch.inference_mode():y=model.generate(**x,**kw)
 t=y[0,x.input_ids.shape[1]:]
 return dict(raw=tok.decode(t,skip_special_tokens=True),seconds=time.monotonic()-started,input_tokens=int(x.input_ids.shape[1]),output_tokens=len(t),eos_reached=bool(len(t) and int(t[-1])==tok.eos_token_id),temperature=temperature,seed=seed,peak_gpu_bytes=torch.cuda.max_memory_allocated(0))

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
 (OUT/'requirements-resolved.txt').write_text(subprocess.check_output([sys.executable,'-m','pip','freeze'],text=True));print(r['raw'])

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
 trainer=Trainer(model=model,args=args,train_dataset=Dataset.from_list(ds),data_collator=DataCollatorForSeq2Seq(tok,padding=True,label_pad_token_id=-100))
 r=trainer.train();assert trainer.state.global_step>0
 changed=sum(not torch.equal(before[n],p.detach().float().cpu()) for n,p in model.named_parameters() if p.requires_grad);assert changed>0,'Adapter did not change'
 model.save_pretrained(OUT/'adapter');tok.save_pretrained(OUT/'adapter')
 write(OUT/'training.json',dict(global_step=trainer.state.global_step,changed_adapter_tensors=changed,metrics=r.metrics,logs=trainer.state.log_history,train_ids=[x['ID'] for x in rows],lengths=[len(x['input_ids']) for x in ds],targets_sha256=sha(ROOT/'data/train_targets.jsonl'),config=c,claim='Actual training, not proof of generalization'))

def freeze():
 assert not (OUT/'holdout.jsonl').exists(),'Cannot reset freeze after seeing holdout'
 assert read(OUT/'training.json')['changed_adapter_tensors']>0
 files=[ROOT/n for n in ['run_config.json','schema.json','system_prompt.txt','knowledge.json','evaluation_policy.json','data/train12.csv','data/train_targets.jsonl','data/split-manifest.json']]+list((ROOT/'scripts').glob('*.py'))+list((OUT/'adapter').rglob('*'))
 lock=dict(created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),hashes={str(p.relative_to(ROOT)):sha(p) for p in files if p.is_file()})
 write(OUT/'frozen.json',lock)
def check_freeze():
 lock=read(OUT/'frozen.json')
 for n,d in lock['hashes'].items():assert sha(ROOT/n)==d,f'Frozen file changed: {n}'

def audit_one(row,call,sink=lambda x:None):
 msg=messages(row);attempts=[];obj=None;sources=[k['id'] for k in read(ROOT/'knowledge.json')]
 for i in range(2):
  try:r=call(msg)
  except Exception as e:return dict(ID=row['ID'],attempts=attempts,parsed=None,first_pass_valid=False,final_valid=False,runtime_error=f'{type(e).__name__}: {e}')
  sink(dict(ID=row['ID'],attempt=i,result=r));attempts.append(r)
  try:obj=parse(r['raw'],row['Content Snippet (文章片段)'],sources);r['validation_error']=None;break
  except Exception as e:
   r['validation_error']=str(e)[:500]
   msg=msg+[{'role':'assistant','content':r['raw']},{'role':'user','content':'請只修正JSON結構、原文引句與來源ID，不增加新主張。錯誤：'+r['validation_error']}]
 return dict(ID=row['ID'],attempts=attempts,parsed=obj,first_pass_valid=attempts[0]['validation_error'] is None,final_valid=obj is not None)

def batch(rows,call,path):
 raw_path=path.with_name(path.stem+'-raw.jsonl');assert not path.exists() and not raw_path.exists(),'Keep earlier outputs; use a fresh run directory'
 with path.open('w') as f,raw_path.open('w') as rf:
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
 tok,model=load(adapter=True);row=next(r for r in data('train12') if r['ID']=='14');runs=[];sources=[x['id'] for x in read(ROOT/'knowledge.json')]
 for t in [.2,.5,.8]:
  r=generate(tok,model,messages(row),temperature=t,seed=42)
  # No repair/cherry-picking in consistency experiment.
  try:r['parsed']=parse(r['raw'],row['Content Snippet (文章片段)'],sources)
  except Exception as e:r['parsed']=None;r['validation_error']=str(e)
  runs.append(r);write(OUT/'consistency.json',dict(ID=row['ID'],runs=runs,summary=consistency_summary(runs)))

def evaluate():
 check_freeze();rows=data('holdout8');tok,model=load(adapter=True)
 batch(rows,lambda msg:generate(tok,model,msg),OUT/'holdout.jsonl');report()

def structural_metrics(results):
 n=len(results);assert n
 return dict(n=n,first_pass_json_valid=sum(r['first_pass_valid'] for r in results),final_json_valid=sum(r['final_valid'] for r in results),first_pass_json_rate=sum(r['first_pass_valid'] for r in results)/n,final_json_rate=sum(r['final_valid'] for r in results)/n,note='Structural validity is not diagnostic accuracy')

def report():
 import pandas as pd
 results=[json.loads(s) for s in (OUT/'holdout.jsonl').read_text().splitlines() if s.strip()];rows=data('holdout8')
 assert len(results)==8 and [r['ID'] for r in results]==[r['ID'] for r in rows]
 records=[]
 for row,r in zip(rows,results):
  obj=r['parsed'] or {};records.append(dict(ID=row['ID'],Category=row['Category'],Article=row['Content Snippet (文章片段)'],Score=obj.get('Score'),Reasons=json.dumps(obj.get('Reasons'),ensure_ascii=False),Advice=json.dumps(obj.get('Actionable Advice'),ensure_ascii=False),FirstPassValid=r['first_pass_valid'],FinalValid=r['final_valid'],Error=r.get('runtime_error',''),Raw=r['attempts'][0]['raw'] if r['attempts'] else ''))
 df=pd.DataFrame(records);df.to_csv(OUT/'audit_report.csv',index=False)
 (OUT/'audit_report.html').write_text('<!doctype html><meta charset="utf-8"><h1>8筆獨立審核</h1><p>原始模型輸出；品質需逐筆來源查核，JSON率不代表準確率。</p>'+df.to_html(index=False,escape=True))
 write(OUT/'metrics.json',structural_metrics(results))
 path=OUT/'manual_review.csv'
 if not path.exists():
  with path.open('w',newline='') as f:
   w=csv.writer(f);w.writerow(['ID','required_codes','missed_critical_risk','false_positive','source_support_0_2','advice_actionability_0_2','accurate_or_bias_explanation','source_urls'])
   for row in rows:w.writerow([row['ID']]+['']*7)
 print(df[['ID','Score','FirstPassValid','FinalValid']].to_string(index=False))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('stage',choices=['check-targets','preflight','train','consistency','freeze','evaluate','report']);a=p.parse_args()
 if a.stage=='check-targets':targets();print('PASS: 12 train-only targets validated')
 else:globals()[a.stage.replace('-','_')]()
