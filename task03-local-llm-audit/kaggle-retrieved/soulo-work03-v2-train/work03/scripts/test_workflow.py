"""Synthetic tests plus real round-1 train outputs; never read holdout or manufacture model evidence."""
import json,tempfile
from pathlib import Path
from workflow import ROOT,targets,data,examples,audit_one,batch,structural_metrics,consistency_summary,read
from selfcheck import item_flags,train_gate,removes_risk
T=targets();rows=data('train12');assert len(T)==12
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
 assert len(p.with_name('synthetic-raw.jsonl').read_text(encoding='utf-8').splitlines())==2
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
# Gate heuristics: removing risk disclosure is caught; deleting a "no risk" claim is not.
bad=['避免使用「風險」等字眼，除非有足夠的法律或金融專業資訊支持。','刪除文末的風險警示','移除法律警語以提升轉換','不要提到法拍風險','淡化風險說明','避免過度強調風險','刪除『投資一定有風險』這種免責聲明',
 '將文末風險警示刪除以提升轉換','風險警語可以省略','把風險段落拿掉','風險提示不必寫','法律警示建議移除','減少風險相關描述','不需強調風險','無須提及法拍風險','移除「風險」一詞','刪除保證與風險警示','不必保留風險警示']
good=['刪除沒風險及隨便還款話術，說明法拍可能與還款能力、費用及順位檢查。','避免使用「沒風險」等絕對化語言，改為「房貸二胎可能涉及風險，建議謹慎評估」等較為中立的表述。','不要刪除風險警示','避免淡化風險','保留法拍風險說明，附民法873條來源及查核日期。','刪去風險較低的說法並補上費用比較','文章應提供具體的法律或金融專業支持，以降低YMYL風險。',
 '刪除保證過件並補上風險說明','避免使用保證語言並加入風險提示','避免過度強調收益而忽略風險','刪除絕對保證字眼以降低誤導風險','風險警示不得刪除','刪除「不會有風險」的說法','原文淡化風險，應補上法拍條件','說明法拍風險後刪除保證字眼','補充還款試算以減少風險','移除『低風險』標語']
assert [x for x in bad if not removes_risk(x)]==[] and [x for x in good if removes_risk(x)]==[],([x for x in bad if not removes_risk(x)],[x for x in good if removes_risk(x)])
# The supervision itself must pass every check (no false alarms), and a perfect run passes the gate.
for x in rows:assert item_flags(x,T[x['ID']],T[x['ID']])==[],x['ID']
perfect=[dict(ID=x['ID'],parsed=T[x['ID']],first_pass_valid=True,final_valid=True) for x in rows]
runs=[dict(temperature=t,parsed=T['14']) for t in (.2,.5,.8)]
assert train_gate(rows,perfect,dict(ID='14',runs=runs,summary=consistency_summary(runs)),T)['status']=='PASS'
# Missed planted SEO theory, false experience and an inflated YMYL score must each fail.
wrong=dict(T['13'],Reasons=[dict(T['13']['Reasons'][0],code='STUFFING')])
assert 'REQUIRED_CODE_MISSED' in {f['code'] for f in item_flags(rows[[x['ID'] for x in rows].index('13')],wrong,T['13'])}
# Real round-1 outputs (train ID14, v1 prompt) must be rejected for the failures seen in review.
fx=ROOT/'outputs/experiments/initial/consistency.json'
if fx.exists():
 g=train_gate(rows,None,read(fx),T);codes={f['code'] for f in g['hard_failures']}
 assert g['status']=='FAIL' and {'FALSE_EXPERIENCE','RISK_DISCLOSURE_REMOVAL','CROSS_DOMAIN_LAW','SEVERE_SCORE_TOO_HIGH','SOURCE_DUMP'}<=codes,codes
 fixture='round-1 real outputs rejected for false experience, risk-removal advice, TW_266 mixing, score 55-59 and source dumping'
else:fixture='round-1 fixture absent in this payload; skipped'
print('PASS: 12 targets; retry and denominator accounting; raw failure preservation; no overwrite; invalid consistency; completion-only loss mask; length rejection; gate heuristics; '+fixture+'. Synthetic/train-only, no GPU/model results.')
