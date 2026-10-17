"""Read-only research controller. No LLM credentials or prewritten competitor findings."""
from pathlib import Path
from dataclasses import dataclass
from urllib.parse import urlsplit,urljoin,urlunsplit,unquote,quote
from urllib.request import Request,build_opener,HTTPRedirectHandler,HTTPSHandler
from http.client import HTTPSConnection
from urllib.error import HTTPError,URLError
from urllib.robotparser import RobotFileParser
from html.parser import HTMLParser
from datetime import datetime,timezone
import hashlib,ipaddress,json,os,socket,sqlite3,time,uuid,zlib
import xml.etree.ElementTree as ET
from src.lessons import Ledger,keyword_page,classify_search,norm_url
class Failure(Exception): pass
@dataclass
class Limits:
    requests:int=30
    calls:int=40
    bytes:int=2_000_000
    seconds:int=900
    timeout:int=20
    interval:float=2
    redirects:int=3
    offpage:int=4
    controller_requests:int=10  # the controller's own re-checks of stored lessons and findings, apart from the model's budget
SECTIONS=('on_page','off_page','other')
LINK_REL={'nofollow','sponsored','ugc'}
# Characters left as they are when a path or query is percent-encoded; '%' keeps existing escapes intact.
URL_SAFE="/%:@!$&'()*+,;=-._~"
def ascii_url(u):
    """Path and query percent-encoded as UTF-8, so a Chinese path reaches http.client as ASCII; an already
    encoded URL comes back unchanged. The host stays as listed (the transport converts it with IDNA)."""
    return urlunsplit((u.scheme,u.netloc,quote(u.path or '/',safe=URL_SAFE),quote(u.query,safe=URL_SAFE+'?'),''))
def wire_url(url):
    """The URL as sent on the wire: a non-ASCII host converted with IDNA (a proxy CONNECT line is ASCII only)."""
    u=urlsplit(url);host=u.hostname or ''
    if host.isascii():return url
    try:netloc=host.encode('idna').decode('ascii')+(f':{u.port}' if u.port else '')
    except UnicodeError as e:raise Failure('invalid_host') from e
    return urlunsplit((u.scheme,netloc,u.path,u.query,u.fragment))
def section_of(claim):
    """Normalized report section of a claim; None when the value is not a known section. Missing means other."""
    s=str(claim.get('section') or 'other').strip().lower().replace('-','_').replace(' ','_')
    s={'onpage':'on_page','offpage':'off_page'}.get(s,s)
    return s if s in SECTIONS else None
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*a,**k): return None
def decode_body(headers,body,cap):
    """Some servers compress even when asked not to; store what the page says, never more than cap+1 bytes.

    A compressed body past the cap was cut by the read, and a stream that does not reach its end is incomplete:
    both stop instead of storing a silently shortened page."""
    enc=headers.get('content-encoding','').strip().lower()
    if enc in ('','identity'):return body
    if enc not in ('gzip','x-gzip','deflate'):raise Failure('unsupported_content_encoding')
    if len(body)>cap:raise Failure('response_too_large')
    def inflate(wbits):
        d=zlib.decompressobj(wbits);out=d.decompress(body,cap+1)
        if len(out)<=cap and not d.eof:raise zlib.error('incomplete stream')
        return out
    try:return inflate(47 if enc!='deflate' else 15)
    except zlib.error:
        if enc!='deflate':raise Failure('content_decoding')
    try:return inflate(-15)  # raw deflate without a zlib header
    except zlib.error as e:raise Failure('content_decoding') from e
class PublicPeerHTTPSConnection(HTTPSConnection):
    """Re-check the connected address: DNS was checked before connecting, but a second lookup may differ."""
    def connect(self):
        super().connect()
        if self._tunnel_host:return  # through a configured proxy the peer is the proxy itself
        if not ipaddress.ip_address(self.sock.getpeername()[0]).is_global:
            self.sock.close();raise OSError('connected to a non-public address')
class PublicPeerHTTPSHandler(HTTPSHandler):
    def https_open(self,req):return self.do_open(PublicPeerHTTPSConnection,req,context=self._context)
class HTTP:
    def __init__(self): self.opener=build_opener(NoRedirect(),PublicPeerHTTPSHandler())
    def __call__(self,url,timeout,cap):
        try: r=self.opener.open(Request(wire_url(url),headers={'User-Agent':'SouloResearch/0.2 (read-only assessment)','Accept-Encoding':'identity'}),timeout=timeout)
        except HTTPError as e: r=e
        except (URLError,OSError) as e: raise Failure('transport:'+type(e).__name__) from e
        with r:
            headers={k.lower():v for k,v in r.headers.items()}
            return r.status,headers,decode_body(headers,r.read(cap+1),cap)
class HTML(HTMLParser):
    def __init__(self,url):
        super().__init__(convert_charrefs=True);self.url=url;self.links=[];self.anchors=[];self.anchor=None;self.rels={};self.text=[];self.title=[];self.h1=[];self.skip=0;self.tag='';self.in_title=False;self.in_h1=False;self.canonical=None;self.description=None;self.robots=None
        # JSON-LD blocks and images inside links: page structure the visible text leaves out (summaries only).
        self.jsonld=[];self.jsonld_buf=None;self.images=[]
    def handle_starttag(self,t,attrs):
        a=dict(attrs);self.tag=t
        if t=='title':self.in_title=True
        if t=='h1':self.in_h1=True
        if t=='script' and 'ld+json' in (a.get('type') or '').lower():self.jsonld_buf=[]
        if t=='img' and self.anchor is not None:
            src=a.get('src') or a.get('data-src') or ''
            self.images.append((self.anchor[0],(a.get('alt') or '').strip(),unquote(urlsplit(urljoin(self.url,src)).path.rsplit('/',1)[-1]) if src else ''))
        if t in ('script','style'):self.skip+=1
        if t=='a' and a.get('href'):
            self.links.append(urljoin(self.url,a['href']));self.anchor=[self.links[-1],[]];self.anchors.append(self.anchor)
            self.rels.setdefault(self.links[-1],set()).update((a.get('rel') or '').lower().split())
        if t=='link' and 'canonical' in (a.get('rel') or '').lower().split():self.canonical=urljoin(self.url,a.get('href',''))
        if t=='meta' and (a.get('name') or '').lower()=='description':self.description=a.get('content')
        if t=='meta' and (a.get('name') or '').lower()=='robots':self.robots=a.get('content')
    def handle_endtag(self,t):
        if t=='script' and self.jsonld_buf is not None:
            if len(self.jsonld)<20:self.jsonld.append(''.join(self.jsonld_buf)[:200_000])
            self.jsonld_buf=None
        if t in ('script','style'):self.skip=max(0,self.skip-1)
        if t=='title':self.in_title=False
        if t=='h1':self.in_h1=False
        if t=='a':self.anchor=None
        self.tag=''
    def handle_data(self,d):
        if self.jsonld_buf is not None:self.jsonld_buf.append(d);return
        if self.skip or not d.strip():return
        self.text.append(d.strip())
        if self.anchor is not None:self.anchor[1].append(d.strip())
        if self.in_title:self.title.append(d)
        if self.in_h1:self.h1.append(d)
    def anchor_pairs(self):
        # First non-empty anchor text per URL, in page order.
        out={}
        for u,parts in self.anchors:
            if not out.get(u):out[u]=' '.join(parts)
        return list(out.items())
def now():return datetime.now(timezone.utc).isoformat()
def page_lines(text):return {x.strip() for x in (text or '').split('\n') if len(x.strip())>=4}
JSONLD_FIELDS=('headline','name','datePublished','dateModified','url')
def structured_data(blocks,limit=12):
    """JSON-LD summary: @type and a few fields per object (FAQ question count, rating, breadcrumb). Page data, not
    instructions; the full markup stays in the snapshot."""
    out=[];errors=0
    def walk(o,depth=0):
        if len(out)>=limit or depth>3:return
        if isinstance(o,list):
            for x in o:walk(x,depth)
            return
        if not isinstance(o,dict):return
        if '@graph' in o:walk(o['@graph'],depth+1)
        t=o.get('@type')
        if t is None:return
        s=dict(type=[str(x)[:40] for x in (t if isinstance(t,list) else [t])][:3])
        for f in JSONLD_FIELDS:
            if isinstance(o.get(f),(str,int,float)):s[f]=str(o[f])[:160]
        for f in ('author','publisher'):
            v=o.get(f);v=v[0] if isinstance(v,list) and v else v
            if isinstance(v,dict) and v.get('name'):s[f]=str(v['name'])[:80]
            elif isinstance(v,str):s[f]=v[:80]
        if 'FAQPage' in s['type']:
            me=o.get('mainEntity');qs=me if isinstance(me,list) else [me] if me else []
            s['faq_questions']=sum(1 for q in qs if isinstance(q,dict))
            s['faq_sample']=[str(q['name'])[:100] for q in qs if isinstance(q,dict) and q.get('name')][:3]
        if isinstance(o.get('itemListElement'),list):
            s['items']=len(o['itemListElement'])
            if 'BreadcrumbList' in s['type']:
                s['breadcrumb']=[str(i['item'].get('name') if isinstance(i.get('item'),dict) else i.get('name'))[:40] for i in o['itemListElement'] if isinstance(i,dict)][:6]
        r=o.get('aggregateRating')
        if isinstance(r,dict):s['rating']={k:str(r[k])[:20] for k in ('ratingValue','reviewCount','ratingCount','bestRating') if k in r}
        out.append(s)
    cap,limit=limit,40  # collect more, then keep the content types first and drop exact repeats
    for b in blocks:
        try:walk(json.loads(b))
        except ValueError:errors+=1
    first=('FAQPage','Article','NewsArticle','BlogPosting','Review','Product','ItemList','BreadcrumbList','WebPage')
    rows=[];[rows.append(o) for o in sorted(out,key=lambda o:min([first.index(t) for t in o['type'] if t in first] or [len(first)])) if o not in rows]
    return dict(objects=rows[:cap],blocks=len(blocks),unparsed_blocks=errors,truncated=len(rows)>cap)
def image_links(h,is_target,limit=20):
    """Links whose content is an image: URL, host, alt text, file name and rel. Outbound ones first, since banners
    are where pages place ads and affiliate links."""
    rows,seen=[],set()
    for u,alt,f in h.images:
        if (u,alt,f) in seen:continue
        seen.add((u,alt,f));host=(urlsplit(u).hostname or '').lower()
        rows.append(dict(url=u[:200],host=host,internal=bool(is_target(host)),alt=alt[:80],file=f[:80],rel=sorted(h.rels.get(u,set())&LINK_REL)))
    return ([r for r in rows if not r['internal']]+[r for r in rows if r['internal']])[:limit],len(rows)
def safe_xml(text):
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():raise Failure('xml_entity_forbidden')
    return ET.fromstring(text)
def snapshot_info(root,row):
    """Parse one stored evidence row: title/H1/anchors for HTML, loc URLs for sitemaps, results for search."""
    body=(Path(root)/row['path']).read_bytes()
    if hashlib.sha256(body).hexdigest()!=row['hash']:return None
    meta=json.loads(row['meta']);ct=meta.get('headers',{}).get('content-type','').lower();text=body.decode('utf-8','replace')
    info=dict(id=row['id'],url=row['url'],status=row['status'],kind='other',title='',h1='',anchors=[],locs=[])
    try:
        if meta.get('method')=='search_index':
            result=json.loads(text);web=(result.get('data') or {}).get('web') if isinstance(result.get('data'),dict) else []
            info.update(kind='search',search_outcome=classify_search(result),anchors=[(w['url'],w.get('title','')) for w in web or [] if isinstance(w,dict) and w.get('url')])
            return info
        if row['status']!=200:return info
        if 'html' in ct:
            h=HTML(row['url']);h.feed(text);info.update(kind='html',title=' '.join(h.title).strip(),h1=' '.join(x.strip() for x in h.h1).strip(),anchors=h.anchor_pairs())
        elif 'xml' in ct or text.lstrip().startswith('<?xml'):
            info.update(kind='sitemap',locs=[n.text.strip() for n in safe_xml(text).iter() if n.tag.split('}')[-1]=='loc' and n.text])
    except (Failure,ET.ParseError,ValueError,AttributeError):pass
    return info
def report_markdown(run_id,report):
    """Readable view of an accepted report: on-page and off-page split into known / inferred / unknown."""
    names=dict(on_page='On-page',off_page='Off-page',other='其他')
    kinds=(('observation','已知'),('inference','推論'),('unknown','未知'))
    lines=[f'# 研究報告 run {run_id}','','已知與推論都附本輪 evidence_id；控制器只檢查引用存在與雜湊，語意支持需另行審查。']
    for sec in SECTIONS:
        claims=[c for c in report['claims'] if (section_of(c) or 'other')==sec]
        if not claims:continue
        lines+=['',f'## {names[sec]}']
        for kind,label in kinds:
            rows=[c for c in claims if c.get('kind')==kind]
            if rows:lines+=['',f'### {label}（{kind}）']+[f'- {c["text"]}'+(f'（evidence: {", ".join(c.get("evidence_ids") or [])}）' if c.get('evidence_ids') else '') for c in rows]
    lines+=['','## 行動（依提交順序）']+[f'{i}. {a["action"]}：{a["reason"]}' for i,a in enumerate(report['actions'],1)]
    if report.get('unknowns'):lines+=['','## 其他未知']+[f'- {u}' for u in report['unknowns']]
    return '\n'.join(lines)+'\n'
class Research:
    def __init__(self,root,target='https://2030.tw',hosts=None,limits=None,transport=None,resolve=None,clock=time.monotonic,sleep=time.sleep,mode='memory',learn=True,run_id=None,searcher=None,keywords=(),required_sections=(),memory=False):
        if mode not in ('baseline','memory','history'):raise ValueError('invalid mode')
        if any(s not in SECTIONS for s in required_sections):raise ValueError('invalid required section')
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.db=sqlite3.connect(self.root/'research.sqlite',check_same_thread=False);self.db.row_factory=sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,host TEXT,mode TEXT,status TEXT,created TEXT);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,run TEXT,kind TEXT,data TEXT);
        CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY,run TEXT,url TEXT,status INT,hash TEXT,path TEXT,meta TEXT);
        ''')
        self.ledger=Ledger(self.db);self.keywords=tuple(keywords);self.actor='model';self.channel='direct';self.presented=None
        # memory: v0.9 research memory (findings, unread candidates, open unknowns) in memory mode; controller_pages caches the controller's own re-fetches of this run
        self.memory=bool(memory);self.memory_presented=None;self.controller_pages={}
        self.searcher=searcher;self.searches=0;self.search_urls=set();self.offpage_used=0;self.required_sections=tuple(required_sections)
        self.proxy_dns=transport is None and bool(os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy'))
        self.target=target.rstrip('/');self.host=urlsplit(target).hostname;self.hosts=set(hosts or [self.host]);self.limits=limits or Limits();self.transport=transport or HTTP();self.resolve=resolve or self.dns
        self.clock=clock;self.sleep=sleep;self.start=clock();self.mode=mode;self.learn=learn;self.id=run_id or uuid.uuid4().hex;self.requests=0;self.controller_requests=0;self.calls=0;self.last={};self.rules={};self.closed=False
        self.db.execute('INSERT INTO runs VALUES(?,?,?,?,?)',(self.id,self.host,mode,'open',now()));self.db.commit();self.event('start',dict(mode=mode,target=target,keywords=list(self.keywords),limits=vars(self.limits),learning=learn,required_sections=list(self.required_sections)))
    @staticmethod
    def dns(h):return {x[4][0] for x in socket.getaddrinfo(h,443,type=socket.SOCK_STREAM)}
    def event(self,kind,data):self.db.execute('INSERT INTO events(run,kind,data) VALUES(?,?,?)',(self.id,kind,json.dumps(data,ensure_ascii=False)));self.db.commit()
    def gate(self):
        if self.closed:raise Failure('run_closed')
        if self.clock()-self.start>=self.limits.seconds:raise Failure('time_budget')
    def is_target(self,host):
        # The target site with or without www. and its subdomains: links there are internal, never off-site.
        host,base=(host or '').lower().rstrip('.'),self.host.lower().removeprefix('www.')
        return host in self.hosts or host==base or host.endswith('.'+base)
    def url(self,url,hosts=None):
        # hosts=None: the operator allow-list. Off-page fetches pass a per-call set derived from search results.
        u=urlsplit(url)
        if u.scheme!='https' or u.username or u.password or u.port not in (None,443):raise Failure('https_only')
        if u.hostname not in (self.hosts if hosts is None else hosts):raise Failure('host_not_allowed')
        if u.hostname=='localhost' or u.hostname.endswith(('.localhost','.local','.internal')):raise Failure('private_address')
        try: literal=ipaddress.ip_address(u.hostname)
        except ValueError: literal=None
        if literal is not None and not literal.is_global:raise Failure('private_address')
        try: addresses=self.resolve(u.hostname)
        except socket.gaierror:
            # Proxy-side DNS is only trusted for operator-approved hosts; an off-page host must resolve locally to public IPs.
            if not self.proxy_dns or hosts is not None:raise Failure('dns_unavailable')
            # Exact operator allow-list still applies; trusted configured HTTPS proxy resolves DNS.
            # This is an environment constraint, not proof that proxy egress is a network sandbox.
            self.event('proxy_dns',dict(host=u.hostname,limitation='local DNS unavailable; configured HTTPS proxy resolves approved host'))
            return ascii_url(u)
        if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):raise Failure('private_address')
        return ascii_url(u)
    def raw(self,url,hosts=None):
        self.gate();url=self.url(url,hosts)
        mine=self.actor=='controller'
        if mine and self.controller_requests>=self.limits.controller_requests:raise Failure('controller_request_budget')
        if not mine and self.requests>=self.limits.requests:raise Failure('request_budget')
        host=urlsplit(url).hostname;delay=self.limits.interval-(self.clock()-self.last.get(host,-1e10))
        if delay>0:self.sleep(delay)
        self.gate()
        if mine:self.controller_requests+=1
        else:self.requests+=1
        self.last[host]=self.clock();self.event('request',dict(url=url,number=self.controller_requests if mine else self.requests,actor=self.actor,channel=self.channel))
        status,headers,body=self.transport(url,min(self.limits.timeout,max(.01,self.limits.seconds-(self.clock()-self.start))),self.limits.bytes)
        headers={k.lower():v for k,v in headers.items()}
        if len(body)>self.limits.bytes:raise Failure('response_too_large')
        eid=uuid.uuid4().hex;digest=hashlib.sha256(body).hexdigest();path=Path('snapshots')/(eid+'.txt');(self.root/path).parent.mkdir(exist_ok=True);(self.root/path).write_bytes(body)
        meta=dict(method='offpage_http' if self.channel=='offpage' else 'direct_http',time=now(),headers={k:headers[k] for k in ('content-type','location','retry-after','last-modified') if k in headers})
        if headers.get('content-encoding','identity').strip().lower() not in ('','identity'):meta['decoded_from']=headers['content-encoding']  # snapshot holds the decoded bytes
        self.db.execute('INSERT INTO evidence VALUES(?,?,?,?,?,?,?)',(eid,self.id,url,status,digest,str(path),json.dumps(meta)));self.db.commit();self.event('response',dict(evidence_id=eid,url=url,status=status,sha256=digest,actor=self.actor,**meta))
        return eid,status,headers,body
    def robots(self,url,hosts=None):
        u=urlsplit(url);origin=f'{u.scheme}://{u.netloc}'
        if origin not in self.rules:
            eid,status,headers,body=self.raw(origin+'/robots.txt',hosts)
            if status not in (200,404,410):raise Failure('robots_unknown:'+str(status))
            rp=RobotFileParser();rp.parse(body.decode('utf-8','replace').splitlines() if status==200 else []);self.rules[origin]=rp
        return self.rules[origin]
    def outbound(self,h):
        """External hosts a target page links to: outbound links, never evidence of backlinks."""
        out={};texts=dict(h.anchor_pairs());alts={}
        for u,alt,f in h.images:alts.setdefault(u,alt or f)
        for u in h.links:
            p=urlsplit(u);host=(p.hostname or '').lower()
            if p.scheme not in ('http','https') or not host or self.is_target(host):continue
            o=out.setdefault(host,dict(host=host,links=0,image_links=0,rel=set(),sample=u[:120],sample_anchor=(texts.get(u) or ('[圖片] '+alts[u] if alts.get(u) else ''))[:80]))
            o['links']+=1;o['image_links']+=u in alts;o['rel']|=h.rels.get(u,set())&LINK_REL
        rows=sorted(out.values(),key=lambda o:(-o['links'],o['host']))
        return [dict(o,rel=sorted(o['rel'])) for o in rows[:10]],len(rows)
    def fetch(self,url,purpose,hosts=None):
        if not purpose.strip():raise Failure('purpose_required')
        url=self.url(url,hosts)
        for hop in range(self.limits.redirects+1):
            if urlsplit(url).path!='/robots.txt' and not self.robots(url,hosts).can_fetch('SouloResearch',url):raise Failure('robots_disallow')
            eid,status,headers,body=self.raw(url,hosts)
            if status in (301,302,303,307,308):
                if hop==self.limits.redirects:raise Failure('redirect_limit')
                if not headers.get('location'):raise Failure('redirect_missing_location')
                try:url=self.url(urljoin(url,headers['location']),hosts)
                except Failure as e:
                    # An off-site page redirecting elsewhere is the third party's doing, not the model's choice.
                    if hosts is not None and str(e)=='host_not_allowed':raise Failure('offpage_redirect_off_host') from e
                    raise
                continue
            base=dict(evidence_id=eid,url=url,status=status,untrusted_content=True)
            if status!=200:return dict(**base,error='http_error',retry_after=headers.get('retry-after'),links=[],text='')
            ct=headers.get('content-type','').lower();text=body.decode('utf-8','replace')
            if not any(t in ct for t in ('text/','xml','json')):raise Failure('unsupported_content_type')
            if 'html' in ct:
                h=HTML(url);h.feed(text);result=dict(**base,kind='html',title=' '.join(h.title),h1=' '.join(h.h1),canonical=h.canonical,description=h.description,robots=h.robots,links=list(dict.fromkeys(h.links))[:1000],text='\n'.join(h.text)[:30000])
                if self.keywords:result['keyword_links']=self.keyword_links(h.anchor_pairs())
                result['outbound_hosts'],result['outbound_hosts_total']=self.outbound(h)
                result['structured_data']=structured_data(h.jsonld);result['image_links'],result['image_links_total']=image_links(h,self.is_target)
            elif 'xml' in ct or text.lstrip().startswith('<?xml'):
                tree=safe_xml(text);links=list(dict.fromkeys(n.text.strip() for n in tree.iter() if n.tag.split('}')[-1]=='loc' and n.text))[:1000];result=dict(**base,kind='sitemap',links=links,text=text[:30000])
            else:result=dict(**base,kind='text',links=[],text=text[:30000])
            self.event('extracted',dict(evidence_id=eid,kind=result['kind'],links_count=len(result['links']),purpose=purpose,actor=self.actor,channel=self.channel));return result
    def keyword_links(self,pairs,limit=20):
        # Anchor text plus URL, so the model can map visible link text to its address. Exact keyword pages first.
        rows=[dict(url=u,anchor=t[:80],exact_keyword=any(keyword_page(u,t,'',k) for k in self.keywords)) for u,t in pairs
              if any(k.casefold() in (t+' '+unquote(u)).casefold() for k in self.keywords)]
        return sorted(rows,key=lambda r:not r['exact_keyword'])[:limit]
    def search(self,query):
        if not isinstance(query,str) or not query.strip() or len(query)>400:raise Failure('invalid_search_query')
        if self.searches>=5:raise Failure('search_budget')
        if self.limits.seconds-(self.clock()-self.start)<31:raise Failure('insufficient_search_time')
        if not self.searcher:raise Failure('search_unavailable')
        self.searches+=1
        self.event('search_request',dict(query=query,provider='hermes_ddgs_keyless',number=self.searches))
        result=self.searcher(query,5)
        body=json.dumps(result,ensure_ascii=False).encode()
        if len(body)>self.limits.bytes:raise Failure('response_too_large')
        eid=uuid.uuid4().hex;path=Path('snapshots')/(eid+'.txt');(self.root/path).parent.mkdir(exist_ok=True);(self.root/path).write_bytes(body)
        meta=dict(method='search_index',time=now(),query=query,provider='hermes_ddgs_keyless',limitation='Search snippets are not direct page fetches; source support and freshness need verification.')
        status=200 if result.get('success') else 503
        web=(result.get('data') or {}).get('web') if isinstance(result.get('data'),dict) else None
        meta['result_count']=sum(1 for w in web or [] if isinstance(w,dict) and w.get('url'));meta['outcome']=classify_search(result)
        self.db.execute('INSERT INTO evidence VALUES(?,?,?,?,?,?,?)',(eid,self.id,'search:ddgs',status,hashlib.sha256(body).hexdigest(),str(path),json.dumps(meta)));self.db.commit()
        self.event('search_response',dict(evidence_id=eid,status=status,**meta))
        out=dict(evidence_id=eid,source_type='search_index',untrusted_content=True,**result,limitation=meta['limitation'])
        if web is not None:
            # The stored snapshot stays the raw provider answer; only the reply is annotated. Listed URLs become the
            # only off-site pages research_offpage may read in this run.
            shown=[]
            for w in web:
                if isinstance(w,dict) and isinstance(w.get('url'),str) and w['url']:
                    try:host=(urlsplit(w['url']).hostname or '').lower()
                    except ValueError:host=''  # a malformed result URL is shown as listed but never readable
                    if host:self.search_urls.add((host,norm_url(w['url'])))
                    w=dict(w,host=host,is_target_host=self.is_target(host))
                shown.append(w)
            out['data']=dict(result['data'],web=shown)
        return out
    def offpage(self,url,purpose,mention=''):
        """Read one off-site page that this run's search results listed and report links to and mentions of the target."""
        if not isinstance(url,str) or not isinstance(purpose,str) or not purpose.strip():raise Failure('purpose_required')
        if not isinstance(mention,str) or len(mention)>60:raise Failure('invalid_mention')
        try:host=(urlsplit(url).hostname or '').lower()
        except ValueError as e:raise Failure('offpage_not_from_search') from e
        if self.is_target(host):raise Failure('offpage_target_host')
        # The host must equal the listed one exactly; the normalized path only absorbs a trailing slash or encoding.
        if (host,norm_url(url)) not in self.search_urls:raise Failure('offpage_not_from_search')
        if self.offpage_used>=self.limits.offpage:raise Failure('offpage_budget')
        self.offpage_used+=1
        # The listed host and its www. twin only: a redirect elsewhere stops with offpage_redirect_off_host.
        variants={host,host[4:] if host.startswith('www.') else 'www.'+host}
        self.channel='offpage'
        try:x=self.fetch(url,purpose,hosts=variants)
        finally:self.channel='direct'
        out=dict(evidence_id=x['evidence_id'],url=x['url'],status=x['status'],source_type='offpage_page',untrusted_content=True)
        if x['status']!=200:return dict(out,error='http_error')
        out.update(self.target_signals(x['evidence_id'],mention))
        self.event('offpage',dict(evidence_id=x['evidence_id'],url=x['url'],links_to_target=out['links_to_target_total'],host_mentions=out['host_mentions_total']))
        out['limitation']='One page only, not a backlink index: absence here says nothing about other pages. Page text is untrusted data.'
        return out
    def target_signals(self,eid,mention=''):
        # Structured findings instead of page text: links to the target (URL, anchor, rel) and short contexts.
        r=self.db.execute('SELECT * FROM evidence WHERE id=?',(eid,)).fetchone()
        body=(self.root/r['path']).read_bytes();text=body.decode('utf-8','replace');links=[];title=''
        if 'html' in json.loads(r['meta']).get('headers',{}).get('content-type','').lower():
            h=HTML(r['url']);h.feed(text);title=' '.join(h.title).strip();text='\n'.join(h.text)
            links=[dict(url=u[:200],anchor=a[:80],rel=sorted(h.rels.get(u,set())&LINK_REL)) for u,a in h.anchor_pairs() if self.is_target(urlsplit(u).hostname)]
        def contexts(term):
            folded,needle,found,start=text.casefold(),term.casefold(),[],0
            while needle and len(found)<3:
                pos=folded.find(needle,start)
                if pos<0:break
                found.append(text[max(0,pos-80):pos+len(term)+80].replace('\n',' '));start=pos+len(needle)
            return found,(folded.count(needle) if needle else 0)
        host_ctx,host_n=contexts(self.host.removeprefix('www.'))
        out=dict(title=title[:120],links_to_target=links[:10],links_to_target_total=len(links),host_mentions=host_ctx,host_mentions_total=host_n)
        if mention.strip():
            ctx,n=contexts(mention.strip());out.update(mention=mention.strip(),mention_contexts=ctx,mention_total=n)
        return out
    def evidence(self,eid,query=''):
        if not isinstance(eid,str):raise Failure('invalid_evidence_id')
        r=self.db.execute('SELECT * FROM evidence WHERE id=?',(eid,)).fetchone()
        if not r:raise Failure('unknown_evidence')
        body=(self.root/r['path']).read_bytes()
        if hashlib.sha256(body).hexdigest()!=r['hash']:raise Failure('evidence_integrity')
        if not isinstance(query,str) or len(query)>200:raise Failure('invalid_evidence_query')
        meta=json.loads(r['meta']);text=body.decode('utf-8','replace');extra={}
        if 'html' in meta.get('headers',{}).get('content-type',''):
            h=HTML(r['url']);h.feed(text)
            # Search visible text plus metadata, not a truncated HTML header.
            text='\n'.join(h.text)
            extra=dict(title=' '.join(h.title),h1=' '.join(h.h1),description=h.description,canonical=h.canonical,robots=h.robots,structured_data=structured_data(h.jsonld))
            extra['outbound_hosts'],extra['outbound_hosts_total']=self.outbound(h)
            extra['image_links'],extra['image_links_total']=image_links(h,self.is_target)
            if query:
                extra['matching_links']=[u for u in dict.fromkeys(h.links) if query.casefold() in u.casefold()][:12]
                extra['matching_anchor_links']=[dict(url=u,anchor=t[:80]) for u,t in h.anchor_pairs() if query.casefold() in t.casefold()][:12]
        total=len(text)
        if query:
            folded=text.casefold();needle=query.casefold();positions=[];start=0
            while len(positions)<8:
                pos=folded.find(needle,start)
                if pos<0:break
                positions.append(pos);start=pos+max(len(needle),300)
            text='\n[excerpt]\n'.join(text[max(0,pos-250):pos+len(query)+400] for pos in positions)
            extra.update(query=query,matches_returned=len(positions))
        return dict(evidence_id=eid,run_id=r['run'],url=r['url'],status=r['status'],sha256=r['hash'],untrusted_content=True,text=text[:8000],source_text_characters=total,text_truncated=not query and total>8000,**extra,**meta)
    def read_evidence(self,eid,query=''):
        # Off-site pages reach the model only as focused excerpts, never as their first 8000 characters.
        r=self.db.execute('SELECT meta FROM evidence WHERE id=?',(eid,)).fetchone() if isinstance(eid,str) else None
        if r and json.loads(r['meta']).get('method')=='offpage_http' and not (isinstance(query,str) and query.strip()):
            raise Failure('offpage_query_required')
        return self.evidence(eid,query)
    def lessons(self):
        # Computed once per run: discovery paths are re-fetched by the controller before they are shown.
        if self.presented is None:
            self.presented=self.ledger.applicable(self.host,self.verify_discovery,persist=self.learn) if self.mode=='memory' else []
            self.event('lessons_presented',dict(time=now(),lessons=[dict(id=x['id'],key=x['key'],applies=x['applies'],expires=x['expires'],verification=x.get('verification')) for x in self.presented]))
        return self.presented
    def check_page(self,url,purpose='controller re-verification of stored research memory'):
        """The controller's own fetch of a stored page, once per run per URL, on the controller budget."""
        key=norm_url(url)
        if key in self.controller_pages:return self.controller_pages[key]
        self.actor='controller'
        try:
            x=self.fetch(url,purpose)
            if x.get('status') in (404,410):out=dict(state='gone',reason='HTTP '+str(x['status']),evidence_id=x['evidence_id'])
            elif x.get('status')!=200 or x.get('kind')!='html':out=dict(state='error',reason='HTTP '+str(x.get('status')),evidence_id=x['evidence_id'])
            else:out=dict(state='ok',evidence_id=x['evidence_id'],url=x['url'],title=x.get('title',''),h1=x.get('h1',''),lines=page_lines(x.get('text','')))
        except Failure as e:
            code=str(e).split(':')[0];out=dict(state='blocked' if code in ('robots_disallow','host_not_allowed') else 'budget' if code=='controller_request_budget' else 'error',reason=code)
        except (ValueError,OSError,ET.ParseError) as e:out=dict(state='error',reason=type(e).__name__)
        finally:self.actor='model'
        self.controller_pages[key]=out
        return out
    def old_page(self,eid):
        """(title, visible lines) of a stored HTML snapshot, as fetch() extracts them; None when missing or altered."""
        r=self.db.execute('SELECT * FROM evidence WHERE id=?',(eid,)).fetchone()
        if not r or not (self.root/r['path']).exists():return None
        body=(self.root/r['path']).read_bytes()
        if hashlib.sha256(body).hexdigest()!=r['hash']:return None
        h=HTML(r['url']);h.feed(body.decode('utf-8','replace'))
        return ' '.join(h.title),page_lines('\n'.join(h.text)[:30000])
    def verify_discovery(self,lesson):
        url,k=lesson['data']['target_url'],lesson['data']['keyword']
        c=self.check_page(url,'controller re-verification of a stored discovery lesson')
        if c['state'] in ('blocked','gone'):return 'fail',c['reason'],c.get('evidence_id')
        if c['state']!='ok':return 'inconclusive',c['reason'],c.get('evidence_id')
        if keyword_page(c['url'],c.get('title'),c.get('h1'),k):return 'ok','HTTP 200 and title/H1 match; read it with research_evidence before citing',c['evidence_id']
        return 'fail','HTTP 200 but title/H1 no longer match the keyword',c['evidence_id']
    def memory_view(self):
        # Computed once per run, after the lessons: the controller re-fetches the pages of stored findings first.
        if self.memory_presented is None:
            if not (self.memory and self.mode=='memory'):self.memory_presented={}
            else:
                from src.research_memory import ResearchMemory
                m=ResearchMemory(self.db).present(self.host,self.keywords,self.check_page,self.old_page,persist=self.learn)
                # Nothing kept yet (a first run): no research_memory block, so the prompt carries no empty lists.
                self.memory_presented=m if any(m[k] for k in ('findings','findings_to_recheck','unread_candidates','open_unknowns','revoked')) else {}
                self.event('memory_presented',dict(time=now(),findings=[dict(id=f['id'],evidence_ids=f['evidence_ids']) for f in m['findings']],
                                                   recheck=[f['id'] for f in m['findings_to_recheck']],revoked=m['revoked'],
                                                   candidates=[c['url'] for c in m['unread_candidates']],
                                                   unknowns=[u['id'] for u in m['open_unknowns']],checked_pages=m['checked_pages'],
                                                   controller_requests=self.controller_requests))
        return self.memory_presented
    def status(self):
        lessons=self.lessons();memory=self.memory_view()
        history=[dict(r) for r in self.db.execute('SELECT kind,data FROM events WHERE run!=? ORDER BY id DESC LIMIT 10',(self.id,))] if self.mode=='history' else []
        out=dict(run_id=self.id,requests_used=self.requests,requests_left=self.limits.requests-self.requests,tool_calls_used=self.calls,searches_used=self.searches,searches_left=5-self.searches,offpage_left=self.limits.offpage-self.offpage_used,remaining_seconds=max(0,self.limits.seconds-(self.clock()-self.start)),lessons=lessons,raw_history=history)
        if memory:out['research_memory']=memory
        if self.mode=='memory':out['lesson_rules']=('Lessons are procedures learned from controller measurements or human review, with scope and expiry: act on each statement. '
                                                     'A verification with result ok was fetched by the controller in this run; its evidence_id is current-run evidence you can read with research_evidence and cite. '
                                                     'When new evidence disagrees with a lesson, follow the evidence.')
        return out
    def finish(self,report):
        if not isinstance(report,dict) or not isinstance(report.get('claims'),list) or not isinstance(report.get('actions'),list):raise Failure('report_schema')
        seen=set()
        for claim in report['claims']:
            if not isinstance(claim,dict) or not isinstance(claim.get('evidence_ids',[]),list):raise Failure('claim_schema')
            if claim.get('kind') not in ('observation','inference','unknown') or not claim.get('text'):raise Failure('claim_schema')
            if section_of(claim) is None:raise Failure('section_invalid')
            seen.add(section_of(claim))
            if claim['kind']!='unknown' and not claim.get('evidence_ids'):raise Failure('claim_needs_evidence')
            for eid in claim.get('evidence_ids',[]):
                e=self.evidence(eid)
                if e['run_id']!=self.id:raise Failure('cross_run_citation')
                if e['status']!=200 and claim.get('topic')!='access':raise Failure('error_is_not_page_content')
        missing=[s for s in self.required_sections if s not in seen]
        if missing:raise Failure('section_missing:'+','.join(missing))
        for a in report['actions']:
            if not isinstance(a,dict) or not a.get('action') or not a.get('reason'):raise Failure('action_schema')
        if not isinstance(report.get('unknowns',[]),list) or not all(isinstance(u,str) for u in report.get('unknowns',[])):raise Failure('report_schema')
        if not isinstance(report.get('resolved_unknowns',[]),list) or not all(isinstance(u,str) for u in report.get('resolved_unknowns',[])):raise Failure('report_schema')
        markdown=report_markdown(self.id,report)  # rendered before the run closes, so a render error cannot follow acceptance
        self.db.execute('UPDATE runs SET status="finished" WHERE id=?',(self.id,));self.db.commit();self.event('report',report);self.closed=True
        (self.root/(self.id+'-report.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        (self.root/(self.id+'-report.md')).write_text(markdown,encoding='utf-8')
        return dict(accepted=True,run_id=self.id,limitation='ID/hash/schema checked; semantic support requires source review')
    def call(self,name,args):
        self.calls+=1;logged=False
        try:
            self.gate()
            if self.calls>self.limits.calls:raise Failure('tool_call_budget')
            self.event('tool_call',dict(name=name,args=args));logged=True
            if name=='research_status':return self.status()
            if name=='research_search':return self.search(args['query'])
            if name=='research_fetch':return self.fetch(args['url'],args['purpose'])
            if name=='research_offpage':return self.offpage(args['url'],args['purpose'],args.get('mention') or '')
            if name=='research_evidence':return self.read_evidence(args['evidence_id'],args.get('query',''))
            if name=='research_finish':return self.finish(args['report'])
            raise Failure('unknown_tool')
        except (Failure,ValueError,KeyError,TypeError,AttributeError,OSError,ET.ParseError,sqlite3.Error) as e:
            # call_logged=False marks calls stopped by a gate before their tool_call event (budget, time, closed run).
            result=dict(error=str(e),error_type=type(e).__name__);self.event('tool_error',dict(name=name,call_logged=logged,**result));return result
    def learn_completed(self):return learn_run(self.db,self.root,self.id,memory=self.memory)
    def export(self,path):Path(path).write_text(json.dumps([dict(r) for r in self.db.execute('SELECT * FROM events WHERE run=? ORDER BY id',(self.id,))],ensure_ascii=False,indent=2),encoding='utf-8')

def learn_run(db,root,run_id,memory=False):
    """Learn from one run after the runner judged it research_complete.

    Learning happens once, only for memory-mode runs started with learning on, and reads controller
    events and stored evidence only; report claims never become lessons. With memory (v0.9) the research memory also
    records the run's on-site pages, links, re-checkable findings of the accepted report and its unknowns
    (src/research_memory.py); findings are re-verified by the controller before any later run sees them.
    """
    db.row_factory=sqlite3.Row
    run=db.execute('SELECT * FROM runs WHERE id=?',(run_id,)).fetchone()
    start=db.execute('SELECT data FROM events WHERE run=? AND kind="start"',(run_id,)).fetchone()
    if not run or run['status']!='finished' or not start:return None
    cfg=json.loads(start['data'])
    if cfg.get('mode')!='memory' or not cfg.get('learning'):return None
    if db.execute('SELECT 1 FROM events WHERE run=? AND kind="learning"',(run_id,)).fetchone():return None
    def page_info(eid):
        r=db.execute('SELECT * FROM evidence WHERE id=?',(eid,)).fetchone()
        return snapshot_info(root,r) if r else None
    changes=Ledger(db).learn_from_run(run_id,run['host'],cfg.get('keywords',[]),page_info)
    if memory:
        from src.research_memory import ResearchMemory
        changes=changes+ResearchMemory(db).learn_from_run(run_id,run['host'],cfg.get('keywords',[]),page_info)
    db.execute('INSERT INTO events(run,kind,data) VALUES(?,?,?)',(run_id,'learning',json.dumps(dict(changes=changes),ensure_ascii=False)));db.commit()
    return changes
