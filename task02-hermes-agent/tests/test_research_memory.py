import json, sqlite3, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from src.research_core import Research, Limits, learn_run
from src.research_memory import ResearchMemory, candidate_ok
from src.lessons import Ledger, search_feature

B = 'https://research.example'
KW = ('娛樂城', '3A娛樂城')
HTML = {'content-type': 'text/html'}
MAIN, BRAND = B + '/hub/' + quote('娛樂城'), B + '/hub/' + quote('3a娛樂城')
TAIL, OTHER = B + '/hub/' + quote('3a娛樂城出金速度'), B + '/hub/' + quote('富遊娛樂城')
JSONLD = ('<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Article",'
          '"headline":"MLB 比分","dateModified":"2026-09-29","author":{"@type":"Person","name":"小編"}},'
          '{"@type":"FAQPage","mainEntity":[{"@type":"Question","name":"出金多久？"},{"@type":"Question","name":"安全嗎？"}]}'
          ']}</script><script type="application/ld+json">{not json</script>')
BANNER = ('<a href="https://wg.example/register?st=2030WG" rel="nofollow"><img src="/img/2030xWG%E5%A8%9B%E6%A8%82%E5%9F%8E.jpg"'
          ' alt="WG娛樂城"></a>')


def page(title, lines, links=(), extra=''):
    body = f'<title>{title}</title><h1>{title}</h1>' + ''.join(f'<p>{x}</p>' for x in lines) + extra + ''.join(
        f'<a href="{u}">{t}</a>' for u, t in links)
    return 200, HTML, body.encode('utf-8')


def site():
    return {
        B + '/robots.txt': (200, {'content-type': 'text/plain'}, b'User-agent: *\nDisallow:\n'),
        B + '/': page('Sports', ['今日賽事一覽', '世界盃專區'], [('/hub/', '線上娛樂城推薦')], BANNER),
        B + '/hub/': page('hub', ['娛樂城評測總覽', '共 2502 篇評測'],
                          [(MAIN, '娛樂城'), (BRAND, '3A娛樂城'), (TAIL, '3a出金速度'), (OTHER, '富遊'), ('/tag/x', 'x')]),
        MAIN: page('娛樂城', ['娛樂城指南第一段', '出金半小時至一小時', '常見問題五類'], extra=JSONLD),
        BRAND: page('3a娛樂城', ['3a品牌頁內容']), TAIL: page('3a娛樂城出金速度', ['15到30分鐘']),
        OTHER: page('富遊娛樂城', ['富遊內容'])}


class Transport:
    def __init__(self):
        self.data = site()
        self.calls = []

    def __call__(self, url, timeout, cap):
        self.calls.append(url)
        return self.data.get(url, (404, {'content-type': 'text/plain'}, b'not found'))


def searcher(q, n):
    return {'success': True, 'data': {'web': [{'url': 'https://news.example/a', 'title': 'news'}]}}


class MemoryFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.t = Transport()
        self.engines = []
        self.addCleanup(lambda: [e.db.close() for e in self.engines])  # Windows cannot delete an open database

    def engine(self, memory=True, learn=True, **kw):
        opts = dict(root=self.root, target=B, hosts=['research.example'], limits=Limits(interval=0), transport=self.t,
                    resolve=lambda h: ['8.8.8.8'], searcher=searcher, keywords=KW, mode='memory', learn=learn,
                    memory=memory)
        opts.update(kw)
        self.engines.append(Research(**opts))
        return self.engines[-1]

    def fetch(self, r, url):
        x = r.call('research_fetch', {'url': url, 'purpose': 'test'})
        self.assertNotIn('error', x, x)
        return x['evidence_id']

    def complete(self, r, claims, unknowns=(), resolved=None, memory=True):
        report = {'claims': claims, 'actions': [{'action': 'a', 'reason': 'b'}], 'unknowns': list(unknowns)}
        if resolved is not None:
            report['resolved_unknowns'] = resolved
        self.assertEqual(r.call('research_finish', {'report': report}).get('accepted'), True)
        learn_run(r.db, self.root, r.id, memory=memory)

    def first_run(self):
        r = self.engine()
        self.assertNotIn('findings', r.call('research_status', {}).get('research_memory', {}))
        home, hub, main = (self.fetch(r, u) for u in (B + '/', B + '/hub/', MAIN))
        search = r.call('research_search', {'query': 'brand'})['evidence_id']
        self.complete(r, [
            {'kind': 'observation', 'section': 'on_page', 'text': '娛樂城頁寫出金半小時至一小時', 'evidence_ids': [main]},
            {'kind': 'inference', 'section': 'on_page', 'text': '首頁經樞紐導向娛樂城頁', 'evidence_ids': [home, hub, main]},
            {'kind': 'observation', 'section': 'off_page', 'text': '搜尋結果列出新聞頁', 'evidence_ids': [search]},
            {'kind': 'unknown', 'section': 'off_page', 'text': '完整 backlinks 未知'}], unknowns=['排名未知'])
        return r


class ToolTests(MemoryFixture):
    def test_fetch_and_evidence_show_structured_data_and_image_links(self):
        r = self.engine(memory=False)
        x = r.call('research_fetch', {'url': MAIN, 'purpose': 'schema'})
        sd = x['structured_data']
        self.assertEqual(sd['blocks'], 2)
        self.assertEqual(sd['unparsed_blocks'], 1)
        types = {o['type'][0]: o for o in sd['objects']}
        self.assertEqual(types['Article']['dateModified'], '2026-09-29')
        self.assertEqual(types['Article']['author'], '小編')
        self.assertEqual(types['FAQPage']['faq_questions'], 2)
        self.assertEqual(types['FAQPage']['faq_sample'], ['出金多久？', '安全嗎？'])
        self.assertNotIn('MLB 比分', x['text'])  # JSON-LD is summarized, not mixed into the visible text
        home = r.call('research_fetch', {'url': B + '/', 'purpose': 'banner'})
        self.assertEqual(home['image_links'][0]['alt'], 'WG娛樂城')
        self.assertEqual(home['image_links'][0]['file'], '2030xWG娛樂城.jpg')
        self.assertEqual(home['image_links'][0]['rel'], ['nofollow'])
        self.assertFalse(home['image_links'][0]['internal'])
        self.assertEqual(home['outbound_hosts'][0]['sample_anchor'], '[圖片] WG娛樂城')
        self.assertEqual(home['outbound_hosts'][0]['image_links'], 1)
        ev = r.call('research_evidence', {'evidence_id': home['evidence_id']})
        self.assertEqual(ev['outbound_hosts'][0]['host'], 'wg.example')
        self.assertEqual(ev['image_links'][0]['alt'], 'WG娛樂城')
        self.assertEqual(r.call('research_evidence', {'evidence_id': x['evidence_id']})['structured_data']['blocks'], 2)

    def test_site_exclusion_is_not_a_site_operator(self):
        self.assertEqual(search_feature('"2030.tw" -site:2030.tw'), 'plain')
        self.assertEqual(search_feature('site:2030.tw 娛樂城'), 'site_operator')
        self.assertEqual(search_feature('娛樂城 SITE:2030.tw'), 'site_operator')

    def test_resolved_unknowns_must_be_strings(self):
        r = self.engine(memory=False)
        e = self.fetch(r, MAIN)
        bad = r.call('research_finish', {'report': {'claims': [{'kind': 'observation', 'text': 't', 'evidence_ids': [e]}],
                                                    'actions': [], 'resolved_unknowns': [1]}})
        self.assertEqual(bad['error'], 'report_schema')
        ok = r.call('research_finish', {'report': {'claims': [{'kind': 'observation', 'text': 't', 'evidence_ids': [e]}],
                                                   'actions': [], 'resolved_unknowns': ['u1']}})
        self.assertTrue(ok['accepted'])
        self.assertNotIn('u1', (self.root / f'{r.id}-report.md').read_text(encoding='utf-8'))

    def test_without_memory_nothing_is_kept_or_shown(self):
        r = self.engine(memory=False)
        e = self.fetch(r, MAIN)
        self.complete(r, [{'kind': 'observation', 'section': 'on_page', 'text': 't', 'evidence_ids': [e]}], memory=False)
        self.assertFalse(r.db.execute('SELECT 1 FROM sqlite_master WHERE name="site_pages"').fetchone())
        self.assertNotIn('research_memory', self.engine(memory=False).status())


class MemoryTests(MemoryFixture):
    def test_learning_keeps_only_reverifiable_findings_pages_links_and_unknowns(self):
        self.first_run()
        db = sqlite3.connect(self.root / 'research.sqlite')
        self.addCleanup(db.close)
        db.row_factory = sqlite3.Row
        rows = db.execute('SELECT * FROM lessons WHERE kind="finding"').fetchall()
        self.assertEqual(len(rows), 2)  # the claim citing a search result is not kept
        self.assertEqual({r['status'] for r in rows}, {'candidate'})
        self.assertEqual(db.execute('SELECT COUNT(*) FROM site_pages').fetchone()[0], 3)
        m = ResearchMemory(db)
        cands = [c['url'] for c in m.candidates('research.example', KW)]
        self.assertIn(BRAND, cands)
        self.assertNotIn(MAIN, cands)
        self.assertFalse(any('/tag/' in u for u in cands))
        self.assertEqual(m.unknowns('research.example'), [dict(id='u1', text='完整 backlinks 未知'),
                                                          dict(id='u2', text='排名未知')])
        self.assertFalse(candidate_ok('https://research.example/img/a.png', 'research.example'))
        self.assertFalse(candidate_ok('https://other.example/x', 'research.example'))

    def test_next_run_sees_reverified_findings_with_its_own_evidence(self):
        self.first_run()
        r = self.engine()
        mem = r.call('research_status', {})['research_memory']
        self.assertEqual(len(mem['findings']), 2)
        self.assertEqual(mem['findings_to_recheck'], [])
        cited = {e for f in mem['findings'] for e in f['evidence_ids']}
        runs = {row[0] for row in r.db.execute('SELECT run FROM evidence WHERE id IN (%s)' % ','.join('?' * len(cited)),
                                                tuple(cited))}
        self.assertEqual(runs, {r.id})  # citable in this run
        self.assertEqual(r.requests, 0)
        self.assertEqual(r.controller_requests, 4)  # robots + three pages, on the controller's own budget
        self.assertNotIn(MAIN, [c['url'] for c in mem['unread_candidates']])
        self.assertEqual(mem['open_unknowns'][0]['id'], 'u1')
        status = {row[0] for row in r.db.execute('SELECT status FROM lessons WHERE kind="finding"')}
        self.assertEqual(status, {'active'})
        presented = json.loads(r.db.execute('SELECT data FROM events WHERE run=? AND kind="memory_presented"',
                                            (r.id,)).fetchone()[0])
        self.assertEqual(presented['unknowns'], ['u1', 'u2'])
        # the newer report supersedes the older findings; only re-checkable claims are kept
        e = mem['findings'][0]['evidence_ids'][0]
        tail = self.fetch(r, TAIL)
        self.complete(r, [{'kind': 'observation', 'section': 'on_page', 'text': '長尾頁寫15到30分鐘', 'evidence_ids': [tail]},
                          {'kind': 'observation', 'section': 'on_page', 'text': '娛樂城頁出金半小時', 'evidence_ids': [e]}],
                      resolved=['u2'])
        statuses = sorted(row[0] for row in r.db.execute('SELECT status FROM lessons WHERE kind="finding"'))
        self.assertEqual(statuses, ['candidate', 'candidate', 'superseded', 'superseded'])

    def test_changed_page_goes_to_recheck_and_gone_page_revokes(self):
        self.first_run()
        self.t.data[MAIN] = page('娛樂城', ['全新內容一', '全新內容二', '全新內容三'])
        self.t.data[B + '/hub/'] = (404, {'content-type': 'text/plain'}, b'gone')
        r = self.engine()
        mem = r.call('research_status', {})['research_memory']
        self.assertEqual(mem['findings'], [])
        self.assertEqual(len(mem['findings_to_recheck']), 1)
        self.assertEqual(mem['findings_to_recheck'][0]['pages'][0]['state'], 'changed')
        self.assertEqual(len(mem['revoked']), 1)
        hist = r.db.execute('SELECT reason FROM lesson_history WHERE new="revoked"').fetchone()[0]
        self.assertIn('HTTP 404', hist)

    def test_budget_veto_and_expiry(self):
        self.first_run()
        r = self.engine(limits=Limits(interval=0, controller_requests=2))
        mem = r.call('research_status', {})['research_memory']
        self.assertEqual(r.controller_requests, 2)
        self.assertEqual(len(mem['findings']), 1)  # robots + the most cited page; the other finding needs more pages
        self.assertEqual({p['state'] for p in mem['findings_to_recheck'][0]['pages']} - {'ok'}, {'unchecked'})
        db = sqlite3.connect(self.root / 'research.sqlite')
        db.row_factory = sqlite3.Row
        ledger = Ledger(db)
        for (lid,) in db.execute('SELECT id FROM lessons WHERE kind="finding"').fetchall():
            ledger.veto(lid, 'reviewer disagrees', 'tester')
        db.commit()
        db.close()
        self.assertEqual(self.engine().status()['research_memory']['findings'], [])
        later = datetime.now(timezone.utc) + timedelta(days=30)
        db = sqlite3.connect(self.root / 'research.sqlite')
        db.row_factory = sqlite3.Row
        db.execute('UPDATE lessons SET status="active" WHERE kind="finding"')
        db.commit()
        m = ResearchMemory(db, clock=lambda: later)
        out = m.present('research.example', KW, lambda u: dict(state='ok', evidence_id='x', title='', lines=set()),
                        lambda e: None)
        self.assertEqual(out['findings'], [])
        self.assertEqual({row[0] for row in db.execute('SELECT status FROM lessons WHERE kind="finding"')}, {'expired'})
        db.close()

    def test_handoff_queue_lists_new_and_rechecked_findings(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('handoff_queue', Path(__file__).resolve().parents[1] / 'scripts' /
                                                      'handoff_queue.py')
        hq = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hq)
        first = self.first_run()
        titles = [x['title'] for x in hq.build_queue(self.root / 'research.sqlite', first.id, self.root)['items']]
        self.assertIn('研究記憶新增 2 條發現', titles)
        self.assertFalse(any(t.startswith('候選經驗：finding') for t in titles))
        self.t.data[B + '/hub/'] = (404, {'content-type': 'text/plain'}, b'gone')
        r = self.engine()
        r.call('research_status', {})
        e = self.fetch(r, MAIN)
        self.complete(r, [{'kind': 'observation', 'section': 'on_page', 'text': 't', 'evidence_ids': [e]}])
        q = hq.build_queue(self.root / 'research.sqlite', r.id, self.root)['items']
        recheck = next(x for x in q if x['title'] == '研究記憶的重驗')
        self.assertEqual(recheck['priority'], 'review')
        self.assertTrue(any('撤銷 finding' in line for line in recheck['evidence']))
        self.assertTrue(any(x['title'] == '研究記憶新增 1 條發現' for x in q))

    def test_findings_are_never_shown_as_lessons(self):
        self.first_run()
        lessons = self.engine().status()['lessons']
        self.assertFalse(any(x['kind'] == 'finding' for x in lessons))


if __name__ == '__main__':
    unittest.main()
