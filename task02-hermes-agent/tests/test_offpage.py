import json, socket, unittest
from unittest import mock
import plugin
from src.research_core import Research, Limits, report_markdown
from src.runner_support import TOOLS
from tests.test_lessons import B, KW, MAIN, HTML, LessonFixture, page

EXT = 'https://ext.example'
ROBOTS_OPEN = (200, {'content-type': 'text/plain'}, b'User-agent: *\nDisallow:\n')


def offsite_routes():
    return {
        EXT + '/robots.txt': ROBOTS_OPEN,
        EXT + '/review': (200, HTML, (
            '<title>Brand review</title><p>We compared Brand at research.example with others.</p>'
            f'<a href="{B}/hub/" rel="nofollow">Brand 推薦</a><a href="https://else.example/">else</a>').encode('utf-8')),
        EXT + '/plain': page('No link', 'No link'),
        EXT + '/hop': (301, {'location': 'https://www.ext.example/hop'}, b''),
        'https://www.ext.example/robots.txt': ROBOTS_OPEN,
        'https://www.ext.example/hop': page('Moved', 'Moved'),
        EXT + '/away': (302, {'location': 'https://evil.example/x'}, b''),
        'https://blocked.example/robots.txt': (200, {'content-type': 'text/plain'}, b'User-agent: *\nDisallow: /\n'),
    }


def search_listing(urls):
    return lambda q, n: {'success': True, 'data': {'web': [{'url': u, 'title': 't', 'description': 'd'} for u in urls]}}


LISTED = [EXT + '/review', EXT + '/plain', EXT + '/hop', EXT + '/away', 'https://blocked.example/p', B + '/']


class OffpageTests(LessonFixture):
    def setUp(self):
        super().setUp()
        self.t.data.update(offsite_routes())

    def offsite(self, **kw):
        return self.engine(searcher=search_listing(LISTED), **kw)

    def read(self, r, url, mention=''):
        return r.call('research_offpage', {'url': url, 'purpose': 'does this page link to the target?', 'mention': mention})

    def test_only_urls_listed_by_this_runs_search(self):
        r = self.offsite()
        self.assertEqual(self.read(r, EXT + '/review')['error'], 'offpage_not_from_search')
        self.assertEqual(self.t.calls, [])
        found = r.call('research_search', {'query': 'Brand review'})
        flags = {w['url']: (w['host'], w['is_target_host']) for w in found['data']['web']}
        self.assertEqual(flags[EXT + '/review'], ('ext.example', False))
        self.assertEqual(flags[B + '/'], ('research.example', True))
        stored = r.db.execute('SELECT path FROM evidence WHERE id=?', (found['evidence_id'],)).fetchone()[0]
        self.assertNotIn('is_target_host', (self.root / stored).read_text(encoding='utf-8'), 'snapshot stays raw')
        self.assertEqual(self.read(r, B + '/')['error'], 'offpage_target_host')
        self.assertEqual(self.read(r, EXT + '/elsewhere')['error'], 'offpage_not_from_search')
        self.assertEqual(self.t.calls, [])
        x = self.read(r, EXT + '/review', mention='Brand')
        self.assertEqual(x['links_to_target'], [{'url': B + '/hub/', 'anchor': 'Brand 推薦', 'rel': ['nofollow']}])
        self.assertIn('research.example', x['host_mentions'][0])
        self.assertEqual((x['mention_total'], x['source_type']), (3, 'offpage_page'))
        self.assertNotIn('text', x, 'structured findings only; page text stays in the evidence ledger')
        self.assertEqual(self.t.calls, [EXT + '/robots.txt', EXT + '/review'])
        e = r.evidence(x['evidence_id'], 'compared')
        self.assertEqual(e['method'], 'offpage_http')
        channels = [json.loads(d[0])['channel'] for d in r.db.execute(
            'SELECT data FROM events WHERE run=? AND kind="request"', (r.id,))]
        self.assertEqual(channels, ['offpage', 'offpage'])
        self.assertEqual(self.read(r, EXT + '/plain')['links_to_target_total'], 0)

    def test_robots_redirects_dns_and_budget(self):
        r = self.offsite()
        r.call('research_search', {'query': 'Brand'})
        self.assertEqual(self.read(r, 'https://blocked.example/p')['error'], 'robots_disallow')
        self.assertEqual(self.t.calls, ['https://blocked.example/robots.txt'])
        self.assertEqual(self.read(r, EXT + '/hop')['url'], 'https://www.ext.example/hop', 'www. twin is the same site')
        self.assertEqual(self.read(r, EXT + '/away')['error'], 'offpage_redirect_off_host')
        self.assertNotIn('https://evil.example/x', self.t.calls)
        self.assertEqual(self.read(r, EXT + '/review')['status'], 200)
        self.assertEqual(self.read(r, EXT + '/plain')['error'], 'offpage_budget', 'four off-site reads per run')
        self.assertEqual(r.status()['offpage_left'], 0)

        p = self.engine(searcher=search_listing([EXT + '/review']), resolve=lambda h: ['10.0.0.8'])
        p.call('research_search', {'query': 'Brand'})
        self.assertEqual(self.read(p, EXT + '/review')['error'], 'private_address')

        def no_dns(h):
            raise socket.gaierror(-3, 'fixture local DNS unavailable')
        q = self.engine(searcher=search_listing([EXT + '/review']), resolve=no_dns)
        q.proxy_dns = True
        q.call('research_search', {'query': 'Brand'})
        self.assertEqual(self.read(q, EXT + '/review')['error'], 'dns_unavailable',
                         'proxy-side DNS is trusted only for operator-approved hosts')

    def test_target_pages_report_outbound_hosts(self):
        self.t.data[B + '/'] = (200, HTML, (
            '<title>Sports</title><a href="/hub/">hub</a>'
            '<a href="https://social.example/p">fb</a><a href="https://social.example/share?u=1">share</a>'
            '<a href="https://aff.example/register?st=x" rel="nofollow sponsored">註冊</a>'
            '<a href="mailto:a@research.example">mail</a>').encode('utf-8'))
        x = self.fetch(self.engine(), B + '/')
        self.assertEqual(x['outbound_hosts'], [
            {'host': 'social.example', 'links': 2, 'image_links': 0, 'rel': [], 'sample': 'https://social.example/p',
             'sample_anchor': 'fb'},
            {'host': 'aff.example', 'links': 1, 'image_links': 0, 'rel': ['nofollow', 'sponsored'],
             'sample': 'https://aff.example/register?st=x', 'sample_anchor': '註冊'}])
        self.assertEqual(x['outbound_hosts_total'], 2)

    def test_finish_requires_on_and_off_page_sections(self):
        r = self.engine(required_sections=('on_page', 'off_page'))
        home = self.fetch(r, B + '/')['evidence_id']
        on = {'kind': 'observation', 'section': 'on_page', 'text': 'home links to hub', 'evidence_ids': [home]}
        x = r.call('research_finish', {'report': {'claims': [on], 'actions': []}})
        self.assertEqual(x['error'], 'section_missing:off_page')
        bad = {'kind': 'unknown', 'section': 'offsite', 'text': 'backlinks unknown'}
        self.assertEqual(r.call('research_finish', {'report': {'claims': [on, bad], 'actions': []}})['error'],
                         'section_invalid')
        off = {'kind': 'unknown', 'section': 'Off-Page', 'text': 'complete backlinks are not public'}
        report = {'claims': [on, off], 'actions': [{'action': 'audit our hub', 'reason': 'competitor hub'}]}
        self.assertTrue(r.call('research_finish', {'report': report})['accepted'])
        md = (self.root / f'{r.id}-report.md').read_text(encoding='utf-8')
        self.assertIn('## Off-page', md)
        self.assertIn('### 未知（unknown）', md)
        self.assertIn(home, md)
        self.assertTrue(self.engine().call('research_finish', {'report': {'claims': [], 'actions': []}})['accepted'],
                        'the library default requires no section; the plugin runtime does')
        self.assertEqual(plugin.required_sections({}), ['on_page', 'off_page'])

    def test_plugin_exposes_offpage_with_optional_mention(self):
        rows = []

        class Context:
            def register_tool(self, **kw):
                rows.append(kw)
        plugin.register(Context())
        schemas = {x['name']: x['schema']['parameters'] for x in rows}
        self.assertEqual(set(schemas), TOOLS)
        self.assertEqual(schemas['research_offpage']['required'], ['url', 'purpose'])
        self.assertIn('section', plugin.SCHEMAS['research_finish'][0])
        r = self.offsite()
        with mock.patch.object(plugin, '_runtime', r):
            json.loads(plugin.dispatch('research_search', {'query': 'Brand'}))
            shown = json.loads(plugin.dispatch('research_offpage', {'url': EXT + '/review', 'purpose': 'x'}))
        self.assertEqual(shown['links_to_target_total'], 1)

    def test_report_markdown_splits_known_inferred_unknown(self):
        report = {'claims': [{'kind': 'observation', 'section': 'off_page', 'text': 'A links in', 'evidence_ids': ['e1']},
                             {'kind': 'inference', 'section': 'off_page', 'text': 'brand outreach', 'evidence_ids': ['e1']},
                             {'kind': 'observation', 'text': 'no section', 'evidence_ids': ['e2']}],
                  'actions': [{'action': 'do x', 'reason': 'because'}], 'unknowns': ['traffic']}
        md = report_markdown('rid', report)
        self.assertLess(md.index('## Off-page'), md.index('## 其他'))
        self.assertIn('### 已知（observation）\n- A links in（evidence: e1）', md)
        self.assertIn('1. do x：because', md)


class TransportDecodingTests(unittest.TestCase):
    def test_compressed_bodies_are_decoded_within_the_size_cap(self):
        import gzip, zlib
        from src.research_core import decode_body, Failure, HTTP
        page = '<a href="https://research.example/">首頁</a>'.encode('utf-8')
        self.assertEqual(decode_body({'content-encoding': 'gzip'}, gzip.compress(page), 1000), page)
        self.assertEqual(decode_body({'content-encoding': 'deflate'}, zlib.compress(page), 1000), page)
        raw = zlib.compressobj(wbits=-15)
        self.assertEqual(decode_body({'content-encoding': 'deflate'}, raw.compress(page) + raw.flush(), 1000), page)
        self.assertEqual(decode_body({}, page, 1000), page)
        self.assertEqual(len(decode_body({'content-encoding': 'gzip'}, gzip.compress(b'x' * 5000), 100)), 101,
                         'decompression stops one byte past the cap so the size check still fires')
        with self.assertRaises(Failure):
            decode_body({'content-encoding': 'br'}, b'...', 1000)
        with self.assertRaises(Failure):
            decode_body({'content-encoding': 'gzip'}, b'not gzip', 1000)
        sent = {}

        class Response:
            status, headers = 200, {'Content-Type': 'text/html', 'Content-Encoding': 'gzip'}
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n): return gzip.compress(page)
        http = HTTP()
        http.opener = mock.Mock(open=lambda req, timeout: sent.update(req.headers) or Response())
        status, headers, body = http('https://research.example/', 5, 1000)
        self.assertEqual((status, body), (200, page))
        self.assertEqual(sent.get('Accept-encoding'), 'identity')

    def test_www_twin_and_subdomains_of_the_target_are_internal(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        r = Research(tmp.name, target='https://www.research.example', transport=lambda *a: None,
                     resolve=lambda h: ['8.8.8.8'])
        self.addCleanup(r.db.close)
        self.assertTrue(all(r.is_target(h) for h in ('www.research.example', 'research.example', 'm.research.example')))
        self.assertFalse(r.is_target('research.example.evil.example'))
        self.assertFalse(r.is_target('notresearch.example'))
