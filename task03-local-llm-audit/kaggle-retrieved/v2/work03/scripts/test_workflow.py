"""Synthetic tests only; do not read holdout or manufacture model evidence."""
import json,tempfile
from pathlib import Path
from workflow import targets,examples,audit_one,batch,structural_metrics,consistency_summary
assert len(targets())==12
row={'ID':'synthetic','Content Snippet (文章片段)':'示意文章','Target Keyword':'示意'}
ok={'Score':70,'Reasons':[],'Actionable Advice':['核對來源']}
seq=iter([{'raw':'bad'},{'raw':json.dumps(ok)}])
r=audit_one(row,lambda m:next(seq));assert not r['first_pass_valid'] and r['final_valid'] and len(r['attempts'])==2
seq=iter([{'raw':'bad'}])
def fail(m):
 try:return next(seq)
 except StopIteration:raise RuntimeError('synthetic failure')
r2=audit_one(row,fail);assert len(r2['attempts'])==1 and not r2['final_valid']
assert structural_metrics([r,r2])['final_json_rate']==.5
with tempfile.TemporaryDirectory() as d:
 p=Path(d)/'synthetic.jsonl';batch([row],lambda m:{'raw':'bad'},p)
 assert len(p.with_name('synthetic-raw.jsonl').read_text().splitlines())==2
 try:batch([row],lambda m:{'raw':'bad'},p)
 except AssertionError:pass
 else:raise AssertionError('Overwrite permitted')
s=consistency_summary([{'temperature':.2,'parsed':ok},{'temperature':.5,'parsed':None},{'temperature':.8,'parsed':dict(ok,Score=80)}]);assert s['score_range']==10 and s['pairs'][0]['code_jaccard'] is None
class Tok:
 eos_token='END'
 def apply_chat_template(self,*args,**kwargs):return 'PREFIX'
 def __call__(self,s,**kwargs):return {'input_ids':list(range(len(s)))}
e=examples(Tok(),[row],{'synthetic':ok},1000)[0];assert e['labels'][:6]==[-100]*6 and all(x!=-100 for x in e['labels'][6:])
try:examples(Tok(),[row],{'synthetic':ok},5)
except AssertionError:pass
else:raise AssertionError('Silent truncation')
print('PASS: 12 targets; retry and denominator accounting; raw failure preservation; no overwrite; invalid consistency; completion-only loss mask; length rejection. Synthetic only, no GPU/model results.')
