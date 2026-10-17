import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import json
import plugin
from src.research_core import Research, Limits


class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.body = ('<html><head><meta name="robots" content="noindex"></head><body>'
                     + '<p>boilerplate</p>' * 4000
                     + '<h1>Verified late content</h1><a href="https://outside.example/specific">link</a>'
                     + ''.join(f'<a href="/article-{i}">article</a>' for i in range(100))
                     + '</body></html>').encode()
        def transport(url, timeout, cap):
            if url.endswith('robots.txt'):
                return 200, {'content-type':'text/plain'}, b'User-agent: *\nDisallow:\n'
            return 200, {'content-type':'text/html'}, self.body
        self.r = Research(Path(self.temp.name),target='https://research.example',
                          transport=transport,resolve=lambda _:['8.8.8.8'],limits=Limits(interval=0))
        self.addCleanup(self.r.db.close)
        self.patch = patch.object(plugin,'_runtime',self.r)
        self.patch.start()
        self.addCleanup(self.patch.stop)
    def fetch(self):
        return json.loads(plugin.dispatch('research_fetch',{'url':'https://research.example/','purpose':'verify late content'}))
    def test_focused_evidence_reaches_past_initial_html_prefix(self):
        x=self.fetch()
        e=self.r.evidence(x['evidence_id'],'Verified late')
        self.assertIn('Verified late content',e['text'])
        self.assertEqual(e['robots'],'noindex')
        self.assertNotIn('<p>',e['text'])
    def test_compact_return_keeps_full_verified_snapshot(self):
        x=self.fetch()
        self.assertLessEqual(len(x['links']),60)
        self.assertTrue(x['links_truncated'])
        self.assertLessEqual(len(x['text']),8000)
        e=self.r.evidence(x['evidence_id'],'specific')
        self.assertEqual(e['matching_links'],['https://outside.example/specific'])
        row=self.r.db.execute('SELECT path FROM evidence WHERE id=?',(x['evidence_id'],)).fetchone()
        self.assertEqual((self.r.root/row[0]).read_bytes(),self.body)
    def test_default_evidence_marks_truncation(self):
        x=self.fetch();e=self.r.evidence(x['evidence_id'])
        self.assertTrue(e['text_truncated'])
        self.assertEqual(len(e['text']),8000)
    def test_invalid_query_cannot_trigger_extra_fetch(self):
        x=self.fetch();before=self.r.requests
        result=self.r.call('research_evidence',{'evidence_id':x['evidence_id'],'query':'x'*201})
        self.assertEqual(result['error'],'invalid_evidence_query')
        self.assertEqual(self.r.requests,before)
    def test_optional_evidence_query_and_required_search_query(self):
        rows=[]
        class Context:
            def register_tool(self,**kw):rows.append(kw)
        plugin.register(Context())
        schemas={x['name']:x['schema']['parameters'] for x in rows}
        self.assertNotIn('query',schemas['research_evidence']['required'])
        self.assertIn('query',schemas['research_search']['required'])
