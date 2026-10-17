"""Controller-only live smoke of research_search + research_offpage on a neutral site. No model call."""
import json,sys,tempfile
from pathlib import Path
from plugins.web.ddgs.provider import DDGSWebSearchProvider
from src.research_core import Research
from src.scoring import score_run
out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
r=Research(out/'run',target='https://www.python.org',hosts=['www.python.org'],searcher=DDGSWebSearchProvider().search,mode='baseline',learn=False)
log=[]
def call(name,args):
    x=r.call(name,args);log.append(dict(tool=name,args=args,result=x));return x
s=call('research_search',{'query':'Python Software Foundation python.org'})
web=[w for w in (s.get('data') or {}).get('web') or [] if isinstance(w,dict)]
ext=[w['url'] for w in web if w.get('url') and not w.get('is_target_host')]
call('research_offpage',{'url':'https://www.python.org/about/','purpose':'smoke: target host must be refused'})
call('research_offpage',{'url':'https://unlisted.example.org/','purpose':'smoke: unlisted URL must be refused'})
for u in ext[:2]:
    call('research_offpage',{'url':u,'purpose':'smoke: does this listed page link to python.org?','mention':'Python Software Foundation'})
home=call('research_fetch',{'url':'https://www.python.org/','purpose':'smoke: outbound_hosts on a target page'})
log.append(dict(outbound_hosts=home.get('outbound_hosts'),outbound_hosts_total=home.get('outbound_hosts_total')))
r.db.close()
sc=score_run(out/'run',r.id,('Python',))
(out/'smoke.json').write_text(json.dumps(dict(run_id=r.id,calls=log,score=dict(offpage_policy_violations=sc['offpage_policy_violations'],http_requests=sc['http_requests'],offpage=sc['offpage'])),ensure_ascii=False,indent=1,default=str),encoding='utf-8')
for e in log:
    if 'tool' in e:
        res=e['result'];print(e['tool'],e['args'].get('url') or e['args'].get('query'),'->',res.get('error') or {k:res.get(k) for k in ('status','links_to_target_total','host_mentions_total','mention_total','url')})
    else:print('outbound',json.dumps(e,ensure_ascii=False)[:400])
print('violations',sc['offpage_policy_violations'],'http',sc['http_requests'])
