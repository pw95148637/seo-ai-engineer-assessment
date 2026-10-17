import json,copy
from audit_io import parse
ok={'Reasons':[{'code':'EXPERIENCE_UNVERIFIED','quote':'實測','explanation':'缺少可核對紀錄，不能認定造假','source_ids':['G_HELP'],'severity':'minor'}],'Score':80,'Actionable Advice':['補充方法與測試紀錄']}
parse(json.dumps(ok),'實測三個月',['G_HELP'])
cases={
'markdown':'```json\n'+json.dumps(ok)+'\n```',
'out_of_range':json.dumps(dict(ok,Score=101)),
'boolean_score':json.dumps(dict(ok,Score=True)),
'extra_field':json.dumps(dict(ok,extra='x')),
'missing_advice':json.dumps({k:v for k,v in ok.items() if k!='Actionable Advice'}),
'wrong_quote':json.dumps(ok,ensure_ascii=False).replace('實測','不存在的引句'),
'unknown_source':json.dumps(ok).replace('G_HELP','FAKE'),
'duplicate_key':'{"Score":90,"Score":95,"Reasons":[],"Actionable Advice":["a"]}',
'missing_severity':json.dumps(dict(ok,Reasons=[{k:v for k,v in ok['Reasons'][0].items() if k!='severity'}])),
'unknown_severity':json.dumps(dict(ok,Reasons=[dict(ok['Reasons'][0],severity='low')])),
'score_outside_band':json.dumps(dict(ok,Score=90)),
'no_reason_low_score':json.dumps(dict(ok,Reasons=[],Score=70))
}
for name,raw in cases.items():
 try:parse(raw,'實測三個月',['G_HELP'])
 except Exception as e:print(name,'REJECT',type(e).__name__)
 else:raise AssertionError(name)
print(f'PASS: 1 valid, {len(cases)} invalid rejected. Synthetic checks, not model results.')
