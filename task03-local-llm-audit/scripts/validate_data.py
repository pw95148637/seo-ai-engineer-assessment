import csv,json,random,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def load(name):
 with (ROOT/'data'/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def check():
 s=load('seo-diagnostic-samples.csv');a=load('train12.csv');b=load('holdout8.csv');m=json.loads((ROOT/'data/split-manifest.json').read_text(encoding='utf-8'))
 ids=lambda x:[r['ID'] for r in x]
 assert len(s)==len(set(ids(s)))==20 and len(a)==12 and len(b)==8
 assert not set(ids(a))&set(ids(b))
 shuffled=s.copy();random.Random(m['seed']).shuffle(shuffled)
 assert a==shuffled[:12] and b==shuffled[12:]
 assert ids(a)==m['train_ids'] and ids(b)==m['holdout_ids']
 assert all(all(r.values()) for r in s)
 sha=hashlib.sha256((ROOT/'data/seo-diagnostic-samples.csv').read_bytes()).hexdigest();assert sha==m['source_sha256']
 return dict(status='PASS',source_rows=20,train_rows=12,holdout_rows=8,overlap=0,seed=m['seed'],split_reproduced=True,source_sha256=sha,train_ids=ids(a),holdout_ids=ids(b))
if __name__=='__main__':print(json.dumps(check(),indent=2))
