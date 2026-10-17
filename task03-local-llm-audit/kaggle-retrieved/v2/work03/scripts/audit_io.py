import json
from pathlib import Path
from jsonschema import Draft202012Validator
ROOT=Path(__file__).resolve().parents[1]
SCHEMA=json.loads((ROOT/'schema.json').read_text())
def parse(raw,snippet,source_ids):
 def pairs(p):
  d={}
  for k,v in p:
   if k in d:raise ValueError('duplicate JSON key')
   d[k]=v
  return d
 obj=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda s:(_ for _ in ()).throw(ValueError(s)))
 Draft202012Validator(SCHEMA).validate(obj)
 for r in obj['Reasons']:
  if not r['quote'] or r['quote'] not in snippet:raise ValueError('quote not in article')
  if not set(r['source_ids'])<=set(source_ids):raise ValueError('unknown source')
 return obj
