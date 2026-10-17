"""Cases found by an independent review of the v0.7 change; each failed before its fix."""
import gzip, importlib.util, json, unittest
from pathlib import Path
from unittest import mock
from src.research_core import Research, Limits, Failure, decode_body, PublicPeerHTTPSConnection
from src.scoring import score_run
from tests.test_lessons import B, KW, MAIN, O, LessonFixture, page
from tests.test_offpage import EXT, offsite_routes, search_listing

TASK = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('evaluate_v07_review', TASK / 'scripts' / 'evaluate_v07.py')
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


class ControllerReviewTests(LessonFixture):
    def setUp(self):
        super().setUp()
        self.t.data.update(offsite_routes())

    def test_listed_host_must_match_exactly(self):
        r = self.engine(searcher=search_listing(['https://a.example%2Fb.example/', 'https://research.example./x']))
        r.call('research_search', {'query': 'x'})
        x = r.call('research_offpage', {'url': 'https://a.example/b.example/', 'purpose': 'x'})
        self.assertEqual(x['error'], 'offpage_not_from_search')
        x = r.call('research_offpage', {'url': 'https://research.example./x', 'purpose': 'x'})
        self.assertEqual(x['error'], 'offpage_target_host', 'a trailing dot is still the target host')
        self.assertEqual(self.t.calls, [])

    def test_malformed_search_url_does_not_lose_the_search(self):
        r = self.engine(searcher=search_listing(['https://[bad/', EXT + '/review']))
        found = r.call('research_search', {'query': 'x'})
        self.assertEqual([w['host'] for w in found['data']['web']], ['', 'ext.example'])
        r.call('research_finish', {'report': {'claims': [], 'actions': []}})
        self.assertEqual(score_run(self.root, r.id, KW)['searches'], 1)

    def test_offsite_snapshot_is_read_only_as_excerpts(self):
        r = self.engine(searcher=search_listing([EXT + '/review']))
        r.call('research_search', {'query': 'x'})
        eid = r.call('research_offpage', {'url': EXT + '/review', 'purpose': 'x'})['evidence_id']
        self.assertEqual(r.call('research_evidence', {'evidence_id': eid})['error'], 'offpage_query_required')
        self.assertIn('compared', r.call('research_evidence', {'evidence_id': eid, 'query': 'compared'})['text'])
        claim = dict(kind='observation', section='off_page', text='review links in', evidence_ids=[eid])
        self.assertTrue(r.call('research_finish', {'report': {'claims': [claim], 'actions': []}})['accepted'],
                        'citation checks still read the snapshot')

    def test_offsite_redirect_elsewhere_is_not_a_model_lesson(self):
        for _ in range(2):
            r = self.engine(searcher=search_listing([EXT + '/away']))
            r.call('research_search', {'query': 'x'})
            self.assertEqual(r.call('research_offpage', {'url': EXT + '/away', 'purpose': 'x'})['error'],
                             'offpage_redirect_off_host')
            self.finish(r)
        self.assertEqual([x['key'] for x in r.ledger.export()['lessons']], [])

    def test_rule_lessons_read_as_rules_and_transfer_hints_stay_tentative(self):
        for _ in range(2):
            r = self.engine()
            r.call('research_finish', {'report': {'claims': [{'kind': 'observation', 'text': 'x'}], 'actions': []}})
            self.finish(r)
        shown = {x['key']: x for x in self.engine().status()['lessons']}
        self.assertTrue(shown['failure|research_finish|claim_needs_evidence']['statement'].startswith('遵守：'))
        self.discover()
        self.discover()
        other = {x['key']: x for x in self.engine(O).status()['lessons']}
        self.assertTrue(other['failure|research_search|site_operator']['statement'].startswith('只在 research.example 觀察到'))

    def test_bad_unknowns_are_rejected_before_the_run_closes(self):
        r = self.engine()
        x = r.call('research_finish', {'report': {'claims': [], 'actions': [], 'unknowns': 5}})
        self.assertEqual(x['error'], 'report_schema')
        self.assertFalse(r.closed)

    def test_refetch_counts_only_pages_handed_over_as_verified(self):
        self.discover()
        self.t.data[MAIN] = (301, {'location': B + '/'}, b'')  # the controller ends on the homepage with HTTP 200
        r = self.engine()
        shown = {x['key'] for x in r.status()['lessons']}
        self.assertNotIn('discovery|research.example|娛樂城', shown)
        self.fetch(r, B + '/')
        self.assertEqual(score_run(self.root, r.id, KW)['refetched_verified_pages'], 0)

    def test_redirect_hops_are_not_counted_as_offsite_pages(self):
        r = self.engine(searcher=search_listing([EXT + '/hop']))
        r.call('research_search', {'query': 'x'})
        r.call('research_offpage', {'url': EXT + '/hop', 'purpose': 'x'})
        r.call('research_finish', {'report': {'claims': [], 'actions': []}})
        s = score_run(self.root, r.id, KW)
        self.assertEqual((s['offpage']['pages_fetched'], s['offpage_policy_violations']), (1, []))


class TransportReviewTests(unittest.TestCase):
    def test_truncated_or_oversized_compressed_bodies_are_refused(self):
        body = gzip.compress(bytes(range(256)) * 40)
        with self.assertRaisesRegex(Failure, 'content_decoding'):
            decode_body({'content-encoding': 'gzip'}, body[:len(body) // 2], 100000)
        with self.assertRaisesRegex(Failure, 'response_too_large'):
            decode_body({'content-encoding': 'gzip'}, body, len(body) - 1)

    def test_connected_peer_must_be_public(self):
        conn = PublicPeerHTTPSConnection('research.example')
        conn.sock = mock.Mock(getpeername=lambda: ('10.0.0.5', 443))
        with mock.patch('http.client.HTTPSConnection.connect'):
            with self.assertRaises(OSError):
                conn.connect()
            conn.sock = mock.Mock(getpeername=lambda: ('8.8.8.8', 443))
            conn.connect()
            conn._tunnel_host = 'research.example'
            conn.sock = mock.Mock(getpeername=lambda: ('10.0.0.5', 8080))
            conn.connect()  # through a configured proxy the peer is the proxy


class JudgeReviewTests(unittest.TestCase):
    def score(self, known=2, link=1, blind='x'):
        return dict(target_pages={k: {'call': 2} for k in KW}, both_target_pages_read=True, calls_before_first_hit=1,
                    tool_calls=10, tokens={'total': 1000}, stale_lessons_presented=0, blind_id=blind, sitemap_reads=0,
                    refetched_verified_pages=0, offpage=dict(known=known, known_external=1, known_link_verified=link,
                                                             three_columns=True), offpage_policy_violations=[])

    def answer(self):
        return dict(unsupported=0, scope_error=0, off_page_supported_known=2,
                    coverage=dict(on_page=1, off_page=1, actionable=1, epistemic=1))

    def test_offpage_verdict_waits_only_when_the_outcome_is_open(self):
        scores = dict(R4=self.score(blind='r'), B2=self.score(known=1, blind='b'))
        self.assertEqual(ev.judge(scores, {})['offpage_verdict'], 'pending_blind_review')
        scores = dict(R4=self.score(link=0, blind='r'), B2=self.score(link=0, blind='b'))
        self.assertEqual(ev.judge(scores, {'r': self.answer()})['offpage_verdict'], 'partial')

    def test_failed_attempts_are_audited(self):
        scores = dict(R4=self.score(blind='r'), B2=self.score(blind='b'))
        review = dict(r=self.answer(), b=self.answer())
        self.assertEqual(ev.judge(scores, review)['verdict'], 'improved')
        j = ev.judge(scores, review, audit=[dict(rule='host_not_from_search', step='R4', attempt=1)])
        self.assertEqual((j['verdict'], j['offpage_verdict']), ('regression', 'unsafe'))
