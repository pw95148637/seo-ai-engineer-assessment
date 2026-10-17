"""Score one research run from its ledger: coverage, cost and failure counts.

Reads the run root read-only. Semantic support of claims is not scored here; claims and
actions are exported as a blind review packet instead.
"""
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
import json, shutil, sqlite3, uuid
from src.research_core import snapshot_info, section_of
from src.lessons import keyword_page, norm_url

KEYWORDS = ('娛樂城', '3A娛樂城')


def open_ro(root):
    db = sqlite3.connect(Path(root, 'research.sqlite').resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    return db


def score_run(root, run_id=None, keywords=KEYWORDS):
    db = open_ro(root)
    try:
        return _score(Path(root), db, run_id, keywords)
    finally:
        db.close()


def _host(url):
    try:
        return (urlsplit(url).hostname or '').lower().rstrip('.')
    except ValueError:
        return ''


def _twins(host):
    host = (host or '').lower()
    return {host, host[4:] if host.startswith('www.') else 'www.' + host}


def _score(root, db, run_id, keywords):
    run = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone() if run_id else \
        db.execute('SELECT * FROM runs ORDER BY created DESC LIMIT 1').fetchone()
    if not run:
        raise ValueError('run not found')
    rid, host = run['id'], run['host']
    evidence = {r['id']: r for r in db.execute('SELECT * FROM evidence WHERE run=?', (rid,))}
    infos = {}

    base = host.lower().removeprefix('www.')

    def is_target(h):
        # Same rule as the controller: the target with or without www. and its subdomains.
        h = (h or '').lower().rstrip('.')
        return h == base or h.endswith('.' + base)

    def info_of(eid):
        r = evidence.get(eid) if isinstance(eid, str) else None
        if not r:
            return None
        if eid not in infos:
            infos[eid] = snapshot_info(root, r)
        return infos[eid]

    def pages_for(eid):
        r = evidence.get(eid) if isinstance(eid, str) else None
        if not r or r['status'] != 200 or urlsplit(r['url']).hostname != host:
            return []
        info = info_of(eid)
        if not info or info['kind'] != 'html':
            return []
        return [k for k in keywords if keyword_page(r['url'], info['title'], info['h1'], k)]

    calls, current, hits, attempts, searches, presented, pending = 0, None, {}, [], [], [], None
    http = dict(model=0, controller=0)
    sitemap_reads, refetched, verified_urls = 0, 0, set()
    search_hosts, robots_rules, violations = set(), {}, []

    def settle():
        # A research_evidence read counts only when the call did not end in a tool_error.
        nonlocal sitemap_reads
        if pending:
            for k in pages_for(pending['evidence_id']):
                hits.setdefault(k, pending)
            sitemap_reads += (info_of(pending['evidence_id']) or {}).get('kind') == 'sitemap'

    for kind, d in ((k, json.loads(v)) for k, v in
                    db.execute('SELECT kind,data FROM events WHERE run=? ORDER BY id', (rid,))):
        if kind == 'tool_call':
            settle()
            pending = None
            calls += 1
            current = d['name']
            args = d.get('args') or {}
            if current == 'research_evidence':
                pending = dict(call=calls, evidence_id=args.get('evidence_id'), via='research_evidence')
            if current == 'research_finish':
                attempts.append(dict(call=calls, report=args.get('report') or {}, accepted=None))
        elif kind == 'request':
            actor, channel, u = d.get('actor', 'model'), d.get('channel', 'direct'), urlsplit(d['url'])
            http[actor] += 1
            if actor == 'model' and channel == 'direct' and u.path != '/robots.txt' and norm_url(d['url']) in verified_urls:
                refetched += 1  # the controller already fetched this page in this run and handed over its evidence_id
            if channel == 'offpage':
                origin = f'{u.scheme}://{u.netloc}'
                if (u.hostname or '').lower() not in search_hosts:
                    violations.append(dict(url=d['url'], rule='host_not_from_search'))
                elif u.path != '/robots.txt' and origin not in robots_rules:
                    violations.append(dict(url=d['url'], rule='robots_not_checked'))
                elif u.path != '/robots.txt' and not robots_rules[origin].can_fetch('SouloResearch', d['url']):
                    violations.append(dict(url=d['url'], rule='robots_disallow'))
        elif kind == 'response':
            u = urlsplit(d['url'])
            if d.get('method') == 'offpage_http' and u.path == '/robots.txt':
                rp = RobotFileParser()
                r = evidence.get(d.get('evidence_id'))
                body = (root / r['path']).read_bytes().decode('utf-8', 'replace') if r else ''
                rp.parse(body.splitlines() if d.get('status') == 200 else [] if d.get('status') in (404, 410) else
                         ['User-agent: *', 'Disallow: /'])
                robots_rules[f'{u.scheme}://{u.netloc}'] = rp
            if kind == 'response' and current == 'research_fetch' and d.get('actor', 'model') == 'model':
                for k in pages_for(d['evidence_id']):
                    hits.setdefault(k, dict(call=calls, evidence_id=d['evidence_id'], url=d['url'], via='research_fetch'))
        elif kind == 'extracted':
            if (current == 'research_fetch' and d.get('kind') == 'sitemap' and d.get('actor', 'model') == 'model'
                    and d.get('channel', 'direct') == 'direct'):
                sitemap_reads += 1
        elif kind == 'search_response':
            r = evidence.get(d.get('evidence_id'))
            info = snapshot_info(root, r) if r else None
            outcome = (info or {}).get('search_outcome') or ('ok' if d.get('status') == 200 else 'error')
            searches.append(dict(query=d.get('query'), outcome=outcome, evidence_id=d.get('evidence_id')))
            for u, _ in (info or {}).get('anchors', []):
                if _host(u):
                    search_hosts |= _twins(_host(u))
        elif kind == 'tool_error' and d.get('call_logged', True):
            # A call stopped by a gate has no tool_call event; its error must not touch the previous call.
            if d.get('name') == 'research_evidence':
                pending = None
            if d.get('name') == 'research_finish' and attempts and attempts[-1]['accepted'] is None:
                attempts[-1].update(accepted=False, error=d.get('error'))
        elif kind == 'report' and attempts and attempts[-1]['accepted'] is None:
            attempts[-1]['accepted'] = True
        elif kind == 'lessons_presented':
            presented.append(d)
            # Pages handed to the model as verified current-run evidence; fetching them again is a re-check.
            for item in d.get('lessons', []):
                v = item.get('verification') or {}
                if v.get('result') == 'ok' and v.get('evidence_id') in evidence:
                    verified_urls.add(norm_url(evidence[v['evidence_id']]['url']))
    settle()

    def failed_citations(report, outside_access_only):
        n = 0
        for c in report.get('claims') or []:
            if not isinstance(c, dict) or (outside_access_only and c.get('topic') == 'access'):
                continue
            n += sum(1 for e in c.get('evidence_ids') or [] if isinstance(e, str) and e in evidence
                     and evidence[e]['status'] != 200)
        return n

    final = next((a['report'] for a in reversed(attempts) if a['accepted']), None)
    first_hit = min((h['call'] for h in hits.values()), default=None)
    usage_file = root / f'{rid}-usage.json'
    usage = json.loads(usage_file.read_text(encoding='utf-8')) if usage_file.exists() else {}
    result = dict(
        run_id=rid, host=host, mode=run['mode'], run_status=run['status'], keywords=list(keywords),
        target_pages={k: hits.get(k) for k in keywords},
        both_target_pages_read=all(k in hits for k in keywords),
        tool_calls=calls,
        calls_before_first_hit=None if first_hit is None else first_hit - 1,
        calls_until_both_hit=max(h['call'] for h in hits.values()) if len(hits) == len(keywords) else None,
        searches=len(searches), failed_searches=sum(s['outcome'] != 'ok' for s in searches),
        failed_search_kinds={k: sum(s['outcome'] == k for s in searches) for k in ('no_results', 'error')},
        failed_search_queries=[s['query'] for s in searches if s['outcome'] != 'ok'],
        http_requests=http['model'] + http['controller'], http_requests_controller=http['controller'],
        sitemap_reads=sitemap_reads, refetched_verified_pages=refetched,
        finish_attempts=len(attempts), first_finish_rejected=bool(attempts) and attempts[0]['accepted'] is False,
        finish_rejections=[a.get('error') for a in attempts if a['accepted'] is False],
        failed_source_citations=dict(
            rejected_attempts=sum(failed_citations(a['report'], True) for a in attempts if a['accepted'] is False),
            final_report=failed_citations(final, False) if final else None),
        lessons_presented=sum(len(p.get('lessons', [])) for p in presented),
        stale_lessons_presented=stale_lessons(db, presented),
        tokens=token_fields(usage) if usage else None,
        hermes_tools=hermes_tool_results(root, rid),
        claims=len(final.get('claims') or []) if final else 0, actions=len(final.get('actions') or []) if final else 0)
    result.update(report_sections(final, evidence, info_of, is_target, searches), offpage_policy_violations=violations)
    return result


def token_fields(usage):
    """Session usage of one run. cost is the cache-aware measure: prompt tokens not served from the prompt cache plus
    completion tokens (None for runs recorded before cache counters were saved)."""
    out = dict(total=usage.get('session_total_tokens'), prompt=usage.get('session_prompt_tokens'),
               completion=usage.get('session_completion_tokens'), api_calls=usage.get('session_api_calls'))
    cache = usage.get('session_cache_read_tokens')
    if cache is not None and out['prompt'] is not None and out['completion'] is not None:
        out.update(cache_read=cache, cache_write=usage.get('session_cache_write_tokens'),
                   uncached_prompt=out['prompt'] - cache, cost=out['prompt'] - cache + out['completion'])
    return out


def hermes_tool_results(root, run_id):
    """Tool results by name in the Hermes transcript, including calls refused because the tool was absent."""
    f = Path(root) / f'{run_id}-hermes.json'
    if not f.exists():
        return None
    counts = {}
    for m in json.loads(f.read_text(encoding='utf-8')).get('messages') or []:
        if isinstance(m, dict) and m.get('role') == 'tool':
            name = m.get('tool_name') or m.get('name') or '?'
            counts[name] = counts.get(name, 0) + 1
    return counts


def report_sections(final, evidence, info_of, is_target, searches):
    """Section counts and off-page evidence quality of the accepted report."""
    ok_search = {s['evidence_id'] for s in searches if s['outcome'] == 'ok'}
    # Redirect hops are not pages; robots.txt answers are not pages either.
    pages = {e for e, r in evidence.items() if json.loads(r['meta']).get('method') == 'offpage_http'
             and urlsplit(r['url']).path != '/robots.txt' and r['status'] not in (301, 302, 303, 307, 308)}
    linking = {e for e in pages if evidence[e]['status'] == 200 and (info_of(e) or {}).get('kind') == 'html'
               and any(is_target(_host(u)) for u, _ in info_of(e)['anchors'])}
    external = ok_search | {e for e in pages if evidence[e]['status'] == 200}
    claims = [c for c in (final or {}).get('claims') or [] if isinstance(c, dict)]
    sections = {s: sum((section_of(c) or 'other') == s for c in claims) for s in ('on_page', 'off_page', 'other')}
    off = [c for c in claims if section_of(c) == 'off_page']
    kinds = {k: sum(c.get('kind') == k for c in off) for k in ('observation', 'inference', 'unknown')}

    def known(pool):
        return sum(1 for c in off if c.get('kind') == 'observation' and
                   any(isinstance(e, str) and e in evidence and evidence[e]['status'] == 200 and (pool is None or e in pool)
                       for e in c.get('evidence_ids') or []))
    return dict(sections=sections, offpage=dict(
        claims=len(off), **kinds, three_columns=all(kinds.values()),
        known=known(None), known_external=known(external), known_link_verified=known(linking),
        pages_fetched=len(pages), pages_linking_to_target=len(linking)))


def stale_lessons(db, presented):
    """Count lessons shown while revoked, vetoed, expired or never active, checked against the history table."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='lesson_history'").fetchone():
        return 0
    stale = 0
    for p in presented:
        for item in p.get('lessons', []):
            last = db.execute('SELECT new FROM lesson_history WHERE lesson=? AND time<=? ORDER BY time DESC, id DESC',
                              (item['id'], p['time'])).fetchone()
            expired = item.get('expires') and item['expires'] <= p['time']
            stale += (not last or last[0] != 'active' or bool(expired))
    return stale


# Coverage scores give the blind review discriminating power beyond the defect counts.
RUBRIC = dict(
    counts=dict(
        unsupported='observation／inference 中，引用快照不支持其內容的項數',
        scope_error='把競爭者與我方網站混為一談，或超出公開證據範圍的主張與行動項數',
        off_page_supported_known='section=off_page 的 observation 中，引用快照確實支持其內容的項數'),
    coverage={
        'on_page': ['0：幾乎沒有附證據的站內觀察',
                    '1：有目標頁標題、H1、內容等附證據的觀察，但沒有涵蓋站內連結架構或技術訊號',
                    '2：同時涵蓋目標頁內容、站內連結架構與至少一項技術訊號（canonical、robots、sitemap 等），並說明和兩個關鍵字的關係'],
        'off_page': ['0：只列未知，或站外主張沒有證據',
                     '1：有附證據的站外相關已知（出站連結類型、搜尋索引中的站外提及），但沒有用實際讀取的站外頁佐證入站連結或提及',
                     '2：至少一項以實際讀取的站外頁佐證入站連結或品牌提及（附錨文字或上下文），區分入站與出站，並說明公開資料看不到完整 backlinks'],
        'actionable': ['0：行動籠統（例如「加強內容」），看不出要做什麼',
                       '1：行動具體，但缺優先順序，或和報告中的發現連不起來',
                       '2：行動具體（對象頁面、元素或查詢）、依優先順序排列、各自連到報告中的發現，並寫出如何驗證成效'],
        'epistemic': ['0：推論寫成事實，或缺少未知',
                      '1：有分類，但有推論寫成確定，或未知沒有說明缺什麼資料',
                      '2：已知、推論、未知清楚分開，推論標出依據與限度，未知寫明缺哪些資料']},
    answer_format={'<blind_id>': {'unsupported': 0, 'scope_error': 0, 'off_page_supported_known': 0,
                                  'coverage': {'on_page': 0, 'off_page': 0, 'actionable': 0, 'epistemic': 0},
                                  'notes': ''}})


def review_packet(root, run_id, rubric=RUBRIC):
    """Claims and actions of the accepted report with their cited sources, without arm or mode labels."""
    db = open_ro(root)
    row = db.execute('SELECT data FROM events WHERE run=? AND kind="report" ORDER BY id DESC', (run_id,)).fetchone()
    report = json.loads(row[0]) if row else {'claims': [], 'actions': [], 'unknowns': []}
    ev = {r['id']: r for r in db.execute('SELECT * FROM evidence WHERE run=?', (run_id,))}
    db.close()
    claims = [dict(item=f'claim:{i}', kind=c.get('kind'), section=section_of(c) or 'other', topic=c.get('topic'),
                   text=c.get('text'),
                   sources=[dict(evidence_id=e, url=ev[e]['url'], status=ev[e]['status'], sha256=ev[e]['hash'],
                                 method=json.loads(ev[e]['meta']).get('method'),
                                 snapshot=ev[e]['path'].replace('\\', '/')) for e in c.get('evidence_ids') or [] if e in ev])
              for i, c in enumerate(report.get('claims') or [], 1) if isinstance(c, dict)]
    actions = [dict(item=f'action:{i}', action=a.get('action'), reason=a.get('reason'))
               for i, a in enumerate(report.get('actions') or [], 1) if isinstance(a, dict)]
    return dict(claims=claims, actions=actions, unknowns=report.get('unknowns') or [],
                review_questions=['Is each observation/inference supported by its cited snapshot? (unsupported)',
                                  'Does any claim or action confuse the competitor with our own site, or overreach '
                                  'beyond public evidence? (scope_error)',
                                  'Score coverage 0-2 on each rubric dimension, and count supported off_page '
                                  'observations (off_page_supported_known).'],
                rubric=rubric)


def write_blind_packet(root, run_id, blind_dir, rubric=RUBRIC):
    """Copy claims and cited snapshots under a random id so the reviewer cannot tell which arm wrote them."""
    blind_id = uuid.uuid4().hex[:8]
    out = Path(blind_dir) / blind_id
    out.mkdir(parents=True)
    packet = review_packet(root, run_id, rubric)
    for c in packet['claims']:
        for s in c['sources']:
            dest = out / s['snapshot']
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(root) / s['snapshot'], dest)
    (out / 'items.json').write_text(json.dumps(dict(blind_id=blind_id, **packet), ensure_ascii=False, indent=2),
                                    encoding='utf-8')
    return blind_id
