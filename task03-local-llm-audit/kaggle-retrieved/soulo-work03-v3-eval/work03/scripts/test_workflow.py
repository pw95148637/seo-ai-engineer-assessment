"""Synthetic tests plus real round-1 and v2 train outputs; never read holdout or manufacture model evidence."""
import json,tempfile
from pathlib import Path
from workflow import ROOT,targets,data,examples,audit_one,batch,structural_metrics,consistency_summary,read,jsonl,knowledge_ids
from selfcheck import item_flags,train_gate,removes_risk
from audit_io import validate,BANDS
T=targets();rows=data('train12');assert len(T)==12
row={'ID':'synthetic','Content Snippet (文章片段)':'示意文章','Target Keyword':'示意'}
ok={'Reasons':[],'Score':90,'Actionable Advice':['核對來源']}
seq=iter([{'raw':'bad'},{'raw':json.dumps(ok)}])
r=audit_one(row,lambda m:next(seq));assert not r['first_pass_valid'] and r['final_valid'] and len(r['attempts'])==2
seq=iter([{'raw':'bad'}])
def fail(m):
 try:return next(seq)
 except StopIteration:raise RuntimeError('synthetic failure')
r2=audit_one(row,fail);assert len(r2['attempts'])==1 and not r2['final_valid']
assert structural_metrics([r,r2])['final_json_rate']==.5
# Score must sit in the band of the highest severity; a mismatch is rejected and retried with the error, never rewritten.
art='示意文章'
def reason(sev):return dict(code='UNSUPPORTED_CLAIM',quote='示意',explanation='缺少依據',source_ids=[],severity=sev)
def rejects(o):
 try:validate(o,art,[])
 except ValueError as e:return 'severity' in str(e)
 return False
for sevs,score,good in [([],85,1),([],84,0),(['minor'],84,1),(['minor'],85,0),(['major'],30,1),(['major'],29,0),(['critical'],29,1),(['minor','critical'],60,0),(['minor','critical'],0,1),(['major','minor'],59,1)]:
 o={'Reasons':[reason(x) for x in sevs],'Score':score,'Actionable Advice':['補依據']}
 assert rejects(o)!=bool(good),(sevs,score)
mismatch=json.dumps({'Reasons':[reason('critical')],'Score':55,'Actionable Advice':['補依據']},ensure_ascii=False)
seen=[];seq=iter([{'raw':mismatch},{'raw':mismatch.replace('"Score": 55','"Score": 20')}])
r3=audit_one({'ID':'synthetic','Content Snippet (文章片段)':art},lambda m:(seen.append(m),next(seq))[1])
assert not r3['first_pass_valid'] and r3['final_valid'] and r3['parsed']['Score']==20 and 'severity' in seen[1][-1]['content']
assert r3['attempts'][0]['raw']==mismatch,'first raw kept unchanged'
# The prompt states the same bands the program enforces.
prompt=(ROOT/'system_prompt.txt').read_text(encoding='utf-8')
assert all(f"{k}（{lo}–{hi}）" in prompt for k,(lo,hi) in BANDS.items() if k) and f"{BANDS[None][0]}–{BANDS[None][1]}" in prompt,'prompt bands differ from audit_io.BANDS'
with tempfile.TemporaryDirectory() as d:
 p=Path(d)/'synthetic.jsonl';batch([row],lambda m:{'raw':'bad'},p)
 assert len(p.with_name('synthetic-raw.jsonl').read_text(encoding='utf-8').splitlines())==2
 try:batch([row],lambda m:{'raw':'bad'},p)
 except AssertionError:pass
 else:raise AssertionError('Overwrite permitted')
s=consistency_summary([{'temperature':.2,'parsed':ok},{'temperature':.5,'parsed':None},{'temperature':.8,'parsed':dict(ok,Score=100)}]);assert s['score_range']==10 and s['pairs'][0]['code_jaccard'] is None
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
# Checker bug found after the v3b run: a prohibition before coordinated verbs (避免否認或淡化) was missed, so advice that ADDS
# disclosure was blocked. The two real v3b sentences (train ID14, consistency T0.5) must pass; real softening must still fail.
good+=['建議修改原文，避免否認或淡化法律風險，例如增加說明抵押物可能被拍賣的條件與程序，並提醒讀者應諮詢專業法律意見。',
 '修改文章中「房貸二胎沒風險」的表述，避免否認或淡化法律後果，並補充抵押物拍賣的法律風險，例如引用民法873條的內容，說明債權到期未受清償時抵押物可能被拍賣，以降低法律風險。',
 '風險警示不得省略或刪除']
bad+=['建議否認或淡化法拍風險，以免嚇跑讀者','不要否認風險，但可以淡化法律後果','避免冗長並淡化風險說明','淡化或省略法律後果以提升轉換','參考別人的做法和刪除風險警示',
 # Independent review before holdout: only disclosure-negating verbs coordinate with a prohibition; 分別／個別 are not 別.
 '建議將標題與內文分別精簡、刪除風險警示段落，以提升閱讀體驗。','可視版面個別調整或刪除風險揭露文字。','頁尾的免責聲明可以個別刪減或省略。','各段落可分別精簡、減少風險說明篇幅，讓文章更易讀。',
 '不要堆砌、移除風險警語，讓頁面更簡潔。','切勿拖延、淡化法拍風險以免讀者流失。','避免重複、省略法律警示，提升可讀性。','建議分別刪除風險警示與免責聲明']
good+=['避免誇大或淡化風險','避免否認、淡化法律風險']
assert [x for x in bad if not removes_risk(x)]==[] and [x for x in good if removes_risk(x)]==[],([x for x in bad if not removes_risk(x)],[x for x in good if removes_risk(x)])
# The supervision itself must pass every check (no false alarms), and a perfect run passes the gate.
for x in rows:assert item_flags(x,T[x['ID']],T[x['ID']])==[],x['ID']
perfect=[dict(ID=x['ID'],parsed=T[x['ID']],first_pass_valid=True,final_valid=True) for x in rows]
runs=[dict(temperature=t,parsed=T['14']) for t in (.2,.5,.8)]
assert train_gate(rows,perfect,dict(ID='14',runs=runs,summary=consistency_summary(runs)),T,knowledge_ids())['status']=='PASS'
# Raw-text soft flags: Score written before the evidence, and a repair that changed severity instead of only the Score.
from selfcheck import raw_flags
first=json.dumps({'Score':55,'Reasons':[reason('critical')],'Actionable Advice':['補依據']},ensure_ascii=False)
fixed={'Reasons':[reason('major')],'Score':55,'Actionable Advice':['補依據']}
assert {f['code'] for f in raw_flags([{'raw':first},{'raw':json.dumps(fixed,ensure_ascii=False)}],fixed)}=={'SEVERITY_CHANGED_IN_REPAIR'}
assert {f['code'] for f in raw_flags([{'raw':first}],dict(fixed,Reasons=[reason('critical')],Score=20))}=={'SCORE_BEFORE_REASONS'}
assert raw_flags([{'raw':json.dumps(T['14'],ensure_ascii=False)}],T['14'])==[]
# Same-prompt comparison without the adapter (baseline stage), on train-only synthetic results.
import workflow as W
with tempfile.TemporaryDirectory() as d:
 W.OUT=Path(d);bad=[dict(x,parsed=dict(T[x['ID']],Reasons=[],Score=90) if x['ID']=='14' else x['parsed']) for x in perfect]
 for name,res in (('train_selfcheck.jsonl',perfect),('train_selfcheck_base.jsonl',bad)):(W.OUT/name).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in res),encoding='utf-8')
 (W.OUT/'consistency.json').write_text(json.dumps(dict(ID='14',runs=runs,summary=consistency_summary(runs)),ensure_ascii=False),encoding='utf-8')
 W.compare();cmp=read(W.OUT/'baseline_comparison.json')
 assert cmp['hard_counts']['adapter']=={} and cmp['hard_counts']['base'].get('REQUIRED_CODE_MISSED')==1 and len(cmp['items'])==12
 W.OUT=ROOT/'outputs'
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
# Real v2 train outputs (v2 prompt, 6-step LoRA): the v3 gate must reject the 25/55/85 scores without severity,
# YMYL_RISK on almost every item, the missed self-reported experience and advice to soften a legal consequence.
v2=ROOT/'kaggle-retrieved/soulo-work03-v2-train/work03/outputs'
if (v2/'train_selfcheck.jsonl').exists():
 sc=jsonl(v2/'train_selfcheck.jsonl');g=train_gate(rows,sc,read(v2/'consistency.json'),T,knowledge_ids());codes={f['code'] for f in g['hard_failures']}
 assert g['status']=='FAIL' and {'CONTRACT_INVALID','YMYL_OVERFLAG','RISK_DISCLOSURE_REMOVAL','CLEAN_ITEM_FLAGGED','REQUIRED_CODE_MISSED','SEVERE_SCORE_TOO_HIGH'}<=codes,codes
 # Band check on a real output: v2 ID14 (Score 55) with its own YMYL reason marked critical is rejected; only a model-chosen 0-29 Score passes.
 o14=json.loads(json.dumps(next(x['parsed'] for x in sc if x['ID']=='14')))
 for x in o14['Reasons']:x['severity']='critical'
 art14=rows[[x['ID'] for x in rows].index('14')]['Content Snippet (文章片段)']
 try:validate(o14,art14,knowledge_ids())
 except ValueError as e:assert '0–29' in str(e)
 else:raise AssertionError('v2 ID14 Score 55 accepted for a critical reason')
 fixture+='; v2 real outputs rejected for missing severity, YMYL over-flagging, missed experience, legal-consequence softening and ID14/7 at 55'
# Real v3b train outputs (the frozen run): the corrected gate keeps the four real failures and no longer blocks ID14's added disclosure.
v3b=ROOT/'kaggle-retrieved/soulo-work03-v3b-train/work03/outputs'
if (v3b/'train_selfcheck.jsonl').exists():
 g=train_gate(rows,jsonl(v3b/'train_selfcheck.jsonl'),read(v3b/'consistency.json'),T,knowledge_ids());codes=[f['code'] for f in g['hard_failures']]
 assert g['status']=='FAIL' and sorted(codes)==['CLEAN_ITEM_FLAGGED','INVALID_JSON','REQUIRED_CODE_MISSED','YMYL_OVERFLAG'],codes
 fixture+='; v3b real outputs keep 4 hard failures (ID20 flagged, ID5 experience missed, ID7 invalid, YMYL over-flagging) without the ID14 checker false positive'
print('PASS: 12 targets; retry and denominator accounting; severity-band contract and retry; prompt bands match code; raw failure preservation; no overwrite; invalid consistency; completion-only loss mask; length rejection; gate heuristics; '+fixture+'. Synthetic/train-only, no GPU/model results.')
