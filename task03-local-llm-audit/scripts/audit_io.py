import json,os
from pathlib import Path
from jsonschema import Draft202012Validator
ROOT=Path(os.environ.get('WORK03_ROOT') or Path(__file__).resolve().parents[1]).resolve()
SCHEMA=json.loads((ROOT/'schema.json').read_text(encoding='utf-8'))
# Score band of the highest Reasons severity; None = no reasons. Mirrored in system_prompt.txt (test_workflow checks).
BANDS={'critical':(0,29),'major':(30,59),'minor':(60,84),None:(85,100)}
RANK=['minor','major','critical']
def max_severity(obj):
 s=[r['severity'] for r in obj['Reasons'] if r.get('severity') in RANK]
 return max(s,key=RANK.index) if s else None
def validate(obj,snippet,source_ids=None):
 """Contract check; the program never rewrites a model's Score or severity, it only rejects."""
 Draft202012Validator(SCHEMA).validate(obj)
 for r in obj['Reasons']:
  if not r['quote'] or r['quote'] not in snippet:raise ValueError('quote not in article')
  if source_ids is not None and not set(r['source_ids'])<=set(source_ids):raise ValueError('unknown source')
 sev=max_severity(obj);lo,hi=BANDS[sev]
 if not lo<=obj['Score']<=hi:raise ValueError(f"Score {obj['Score']}不在最高severity「{sev or '無原因'}」的區間{lo}–{hi}；Reasons與severity保持不變，只修改Score使其落在此區間")
 return obj
def parse(raw,snippet,source_ids):
 def pairs(p):
  d={}
  for k,v in p:
   if k in d:raise ValueError('duplicate JSON key')
   d[k]=v
  return d
 obj=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda s:(_ for _ in ()).throw(ValueError(s)))
 return validate(obj,snippet,source_ids)
