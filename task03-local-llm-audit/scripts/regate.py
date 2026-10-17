"""Offline: judge a downloaded train bundle's real outputs with the CURRENT gate, contract and train targets.

python scripts/regate.py <bundle>/work03 [--selfcheck train_selfcheck_base.jsonl] [--out evidence/<name>.json]
Reads only <bundle>/work03/outputs/<selfcheck> and consistency.json plus local train12/targets/knowledge.
Never writes into the bundle (its train_gate.json is covered by the bundle's lock). Train-only; holdout is not read.
summary: hard counts (train12 vs consistency, with and without CONTRACT_INVALID, which an older output format
fails by construction), Score MAE against the train targets, severe-case scores (ID14, ID7) and YMYL_RISK counts."""
import argparse,json,sys
from pathlib import Path
from workflow import data,targets,knowledge_ids,jsonl,read,write
from selfcheck import train_gate,YMYL_BORDERLINE
ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('bundle',help='downloaded work03 directory');ap.add_argument('--selfcheck',default='train_selfcheck.jsonl');ap.add_argument('--out')
a=ap.parse_args();o=Path(a.bundle)/'outputs';rows=data('train12');T=targets()
sc=jsonl(o/a.selfcheck);cons=read(o/'consistency.json')
assert [r['ID'] for r in sc]==[r['ID'] for r in rows],'bundle self-check is not train12'
g=train_gate(rows,sc,cons,T,knowledge_ids())
def counts(fs):
 c={}
 for f in fs:c[f['code']]=c.get(f['code'],0)+1
 return c
t12=[f for f in g['hard_failures'] if not f['where'].startswith('consistency')];con=[f for f in g['hard_failures'] if f['where'].startswith('consistency')]
nc=lambda fs:[f for f in fs if f['code']!='CONTRACT_INVALID']
parsed={r['ID']:r.get('parsed') for r in sc}
err={i:abs(p['Score']-T[i]['Score']) for i,p in parsed.items() if p}
ymyl=lambda p:bool(p) and 'YMYL_RISK' in {r['code'] for r in p['Reasons']}
clear=[i for i,t in T.items() if i not in YMYL_BORDERLINE and 'YMYL_RISK' not in {r['code'] for r in t['Reasons']}]
target_ymyl=[i for i,t in T.items() if 'YMYL_RISK' in {r['code'] for r in t['Reasons']}]
summary=dict(selfcheck=a.selfcheck,
 hard_train12=counts(t12),hard_consistency=counts(con),
 hard_total_excl_contract=len(nc(g['hard_failures'])),hard_codes_excl_contract=sorted({f['code'] for f in nc(g['hard_failures'])}),
 score_mae=round(sum(err.values())/len(err),1) if err else None,score_mae_n=len(err),no_valid_output=[i for i,p in parsed.items() if not p],
 severe_scores={i:(parsed[i] or {}).get('Score') for i in ('14','7')},target_severe={i:T[i]['Score'] for i in ('14','7')},
 consistency_id14_scores=[(r.get('parsed') or {}).get('Score') for r in cons['runs']],
 ymyl_flagged=f"{sum(ymyl(p) for p in parsed.values())}/12",ymyl_on_clear=f"{sum(ymyl(parsed[i]) for i in clear)}/{len(clear)}",ymyl_on_target=f"{sum(ymyl(parsed[i]) for i in target_ymyl)}/{len(target_ymyl)}")
if a.selfcheck!='train_selfcheck.jsonl':summary['note']='consistency.json is the adapter run; only hard_train12 describes this self-check'
g['regated']=dict(bundle=Path(a.bundle).as_posix(),note='Real outputs from the bundle judged by the current local gate/contract/targets; the bundle itself is unchanged.',summary=summary)
if a.out:write(a.out,g)
sys.stdout.reconfigure(errors='replace')
print(json.dumps(dict(status=g['status'],**summary),ensure_ascii=False))
for f in g['hard_failures']:
 if f['code']!='CONTRACT_INVALID':print('HARD',f['where'],f['code'],f['detail'])
