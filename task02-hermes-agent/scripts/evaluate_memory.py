"""Synthetic component check of the lessons ledger: fixtures and a fixed scripted policy, no LLM.

Two development runs learn on a stable fixture; frozen held-out cases then compare baseline and
memory under the same policy. Output always goes to a new directory (default
runs/memory-evaluation/<UTC time>); the archived v0.5 result in evidence/memory-evaluation is
never written.
"""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
import argparse, json, shutil, sys, tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.research_core import Research, Limits
from src.lessons import keyword_page
from src.scoring import score_run

B = 'https://research.example'
KW = ('娛樂城', '3A娛樂城')
HTML = {'content-type': 'text/html'}


def page(title, h1, links=()):
    body = f'<title>{title}</title><h1>{h1}</h1>' + ''.join(f'<a href="{u}">{t}</a>' for u, t in links)
    return 200, HTML, body.encode('utf-8')


class Site:
    """Home links to a hub (anchor 線上娛樂城推薦) after 17 other links; sitemaps omit the keyword pages."""
    def __init__(self, moved=False, site_search=False):
        main = B + ('/guide/' if moved else '/hub/') + quote('娛樂城')
        brand = B + '/hub/' + quote('3a娛樂城')
        news = [(f'/news/{i}', f'新聞 {i}') for i in range(17)]
        self.site_search = site_search
        self.routes = {
            B + '/robots.txt': (200, {'content-type': 'text/plain'}, b'User-agent: *\nDisallow:\n'),
            B + '/': page('Sports news', 'Sports news', news + [('/hub/', '線上娛樂城推薦')]),
            B + '/hub/': page('線上娛樂城推薦', '線上娛樂城推薦', [(main, '娛樂城'), (brand, '3A娛樂城'),
                                                         ('/hub/' + quote('富遊娛樂城'), '富遊娛樂城')]),
            main: page('娛樂城評價｜指南', 'Site 娛樂城 - 完整評測'),
            brand: page('3a娛樂城｜攻略', 'Site 3a娛樂城 - 完整評測'),
            B + '/sitemap_index.xml': (200, {'content-type': 'application/xml'}, (
                '<?xml version="1.0"?><urlset>' + ''.join(f'<url><loc>{B}/news/{i}</loc></url>' for i in range(17))
                + '</urlset>').encode())}

    def __call__(self, url, timeout, cap):
        return self.routes.get(url, (404, {'content-type': 'text/plain'}, b'not found'))

    def search(self, query, n):
        if 'site:' in query and not self.site_search:
            return {'success': False, 'error': 'No results found'}
        return {'success': True, 'data': {'web': [{'url': B + '/', 'title': 'Sports news'}]}}


def engine(root, site, **kw):
    return Research(root, target=B, limits=Limits(interval=0), transport=site, resolve=lambda h: ['8.8.8.8'],
                    searcher=site.search, keywords=KW, **kw)


def policy(r):
    """Same scripted agent for every arm; only the lessons returned by research_status differ."""
    lessons = r.call('research_status', {})['lessons']
    avoid_site = any(x['key'] == 'failure|research_search|site_operator' for x in lessons)
    r.call('research_search', {'query': ('"research.example" ' if avoid_site else 'site:research.example ') + '娛樂城'})
    found = set()
    for x in lessons:
        if x['kind'] == 'discovery_path' and x['verification']['result'] == 'ok':
            e = r.call('research_evidence', {'evidence_id': x['verification']['evidence_id']})
            found.update(k for k in KW if keyword_page(e['url'], e.get('title'), e.get('h1'), k))
    queue, fetches = [B + '/sitemap_index.xml', B + '/'], 0
    while queue and len(found) < len(KW) and fetches < 10:
        x = r.call('research_fetch', {'url': queue.pop(0), 'purpose': 'find keyword pages'})
        fetches += 1
        found.update(k for k in KW if x.get('kind') == 'html' and keyword_page(x['url'], x.get('title'), x.get('h1'), k))
        for link in x.get('keyword_links', []):
            if link['exact_keyword'] and not any(keyword_page(link['url'], link['anchor'], '', k) for k in found):
                queue.insert(0, link['url'])
            elif not link['exact_keyword'] and link['url'] not in queue:
                queue.append(link['url'])
    r.call('research_finish', {'report': {'claims': [], 'actions': [], 'unknowns': ['synthetic fixture only']}})
    r.learn_completed()  # what the runner does after a complete run; skipped for baseline and frozen runs


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', default='runs/memory-evaluation/' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    out = Path(p.parse_args().output)
    if out.exists():
        p.error('refusing to write into an existing directory: ' + str(out))
    cases = {'stable': {}, 'moved_page': {'moved': True}, 'site_search_recovered': {'site_search': True}}
    rows = []
    with tempfile.TemporaryDirectory() as temp:
        dev = Path(temp) / 'dev'
        for _ in range(2):
            r = engine(dev, Site(), mode='memory', learn=True)
            policy(r)
            r.db.close()
        for case, opts in cases.items():
            for mode in ('baseline', 'memory'):
                root = Path(temp) / f'{case}-{mode}'
                shutil.copytree(dev, root)
                r = engine(root, Site(**opts), mode=mode, learn=False)
                policy(r)
                rid = r.id
                r.db.close()
                s = score_run(root, rid, KW)
                rows.append(dict(case=case, mode=mode, both_target_pages_read=s['both_target_pages_read'],
                                 tool_calls=s['tool_calls'], calls_before_first_hit=s['calls_before_first_hit'],
                                 failed_searches=s['failed_searches'], http_requests=s['http_requests'],
                                 lessons_presented=s['lessons_presented'], stale=s['stale_lessons_presented']))
        out.mkdir(parents=True)
        (out / 'results.json').write_text(json.dumps(dict(
            kind='synthetic_component_check_no_model', development_runs=2, holdout_learning=False, results=rows,
            note=('Fixtures and a scripted policy. Shows mechanism behaviour (reuse, re-verification, transfer of a '
                  'failure lesson), not Hermes or LLM research quality.')), ensure_ascii=False, indent=2),
            encoding='utf-8')
    sys.stdout.buffer.write(json.dumps(rows, ensure_ascii=False, indent=1).encode('utf-8') + b'\n')


if __name__ == '__main__':
    main()
