import json, tempfile, unittest
from pathlib import Path
from src.research_core import Research, Limits
from src.scoring import score_run, write_blind_packet
from tests.test_lessons import B, KW, MAIN, BRAND, Transport, failing_site_search

TASK = Path(__file__).resolve().parents[1]
ARCHIVE = TASK / 'evidence' / 'live-agent-evaluation'


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.t = Transport()

    def engine(self, **kw):
        opts = dict(root=self.root, target=B, hosts=['research.example'], limits=Limits(interval=0), transport=self.t,
                    resolve=lambda h: ['8.8.8.8'], searcher=failing_site_search, keywords=KW, mode='memory')
        opts.update(kw)
        r = Research(**opts)
        self.addCleanup(r.db.close)
        return r

    def run_research(self, cite_failed_first=True):
        r = self.engine()
        r.call('research_status', {})
        failed = r.call('research_search', {'query': 'site:research.example 娛樂城'})['evidence_id']
        for url in (B + '/', B + '/hub/', MAIN, BRAND):
            last = r.call('research_fetch', {'url': url, 'purpose': 'test'})
        if cite_failed_first:
            r.call('research_finish', {'report': {'claims': [{'kind': 'observation', 'text': 'x', 'evidence_ids': [failed]}],
                                                  'actions': []}})
        r.call('research_finish', {'report': {'claims': [
            {'kind': 'observation', 'text': 'brand page', 'evidence_ids': [last['evidence_id']]},
            {'kind': 'observation', 'text': 'search unavailable', 'topic': 'access', 'evidence_ids': [failed]}],
            'actions': [{'action': 'compare', 'reason': 'test'}]}})
        r.learn_completed()
        (self.root / f'{r.id}-usage.json').write_text(json.dumps({'session_total_tokens': 1234, 'session_prompt_tokens': 1200,
                                                                   'session_completion_tokens': 34, 'session_api_calls': 5}))
        return r

    def test_scores_coverage_cost_and_failures(self):
        r = self.run_research()
        s = score_run(self.root, r.id, KW)
        self.assertTrue(s['both_target_pages_read'])
        self.assertEqual((s['target_pages']['娛樂城']['call'], s['target_pages']['3A娛樂城']['call']), (5, 6))
        self.assertEqual((s['calls_before_first_hit'], s['calls_until_both_hit'], s['tool_calls']), (4, 6, 8))
        self.assertEqual((s['failed_searches'], s['searches']), (1, 1))
        self.assertTrue(s['first_finish_rejected'])
        self.assertEqual(s['finish_rejections'], ['error_is_not_page_content'])
        self.assertEqual(s['failed_source_citations'], {'rejected_attempts': 1, 'final_report': 1})
        self.assertEqual((s['http_requests'], s['http_requests_controller']), (5, 0))
        self.assertEqual(s['tokens']['total'], 1234)

    def test_controller_reverification_is_not_a_model_read(self):
        self.run_research(False)
        self.run_research(False)
        r = self.engine()
        lessons = {x['key']: x for x in r.call('research_status', {})['lessons']}
        eid = lessons['discovery|research.example|娛樂城']['verification']['evidence_id']
        s = score_run(self.root, r.id, KW)
        self.assertIsNone(s['calls_before_first_hit'])
        self.assertEqual(s['http_requests_controller'], 3)
        r.call('research_evidence', {'evidence_id': eid})
        s = score_run(self.root, r.id, KW)
        self.assertEqual((s['target_pages']['娛樂城']['via'], s['calls_before_first_hit']), ('research_evidence', 1))
        self.assertEqual(s['stale_lessons_presented'], 0)

    def test_stale_presentation_is_detected_from_history(self):
        self.run_research(False)
        self.run_research(False)
        r = self.engine()
        lesson = r.ledger.by_key('failure|research_search|site_operator')
        r.ledger.veto(lesson['id'], 'reviewer disagrees', 'user')
        # Simulate a faulty controller that still shows the vetoed lesson.
        r.event('lessons_presented', {'time': r.ledger.ts(), 'lessons': [{'id': lesson['id'], 'expires': lesson['expires']}]})
        self.assertEqual(score_run(self.root, r.id, KW)['stale_lessons_presented'], 1)

    def test_blind_packet_hides_arm_and_copies_sources(self):
        r = self.run_research()
        blind = self.root / 'blind'
        bid = write_blind_packet(self.root, r.id, blind)
        items = json.loads((blind / bid / 'items.json').read_text(encoding='utf-8'))
        self.assertEqual([c['item'] for c in items['claims']], ['claim:1', 'claim:2'])
        self.assertTrue((blind / bid / items['claims'][0]['sources'][0]['snapshot']).exists())
        text = json.dumps(items)
        self.assertNotIn(r.id, text)
        self.assertNotIn('memory', text)

    def test_archived_v05_runs_reproduce_recorded_facts(self):
        base = score_run(ARCHIVE / 'baseline', 'd19217ae0c174d1a8dee6b423a6986da', KW)
        self.assertTrue(base['both_target_pages_read'])
        # 2 site: queries timed out or found nothing; 1 query returned only an empty placeholder result.
        self.assertEqual((base['calls_before_first_hit'], base['failed_searches'], base['http_requests']), (13, 3, 14))
        self.assertTrue(base['first_finish_rejected'])
        self.assertEqual(base['tokens']['total'], 438286)
        memory = score_run(ARCHIVE / 'memory', '17a6529ac799477a84695baee47b076b', KW)
        self.assertFalse(memory['both_target_pages_read'], 'on-site search result pages are not keyword pages')
        self.assertEqual((memory['failed_searches'], memory['searches'], memory['tokens']['total']), (3, 3, 743896))


    def test_late_finish_and_failed_evidence_read_do_not_rewrite_the_record(self):
        r = self.run_research(False)
        r.call('research_finish', {'report': {'claims': [], 'actions': []}})
        s = score_run(self.root, r.id, KW)
        self.assertEqual((s['first_finish_rejected'], s['claims']), (False, 2))
        r2 = self.engine()
        target = r2.call('research_fetch', {'url': MAIN, 'purpose': 'x'})['evidence_id']
        r3 = self.engine()
        r3.db.execute('UPDATE evidence SET run=? WHERE id=?', (r3.id, target))
        r3.db.commit()
        r3.call('research_evidence', {'evidence_id': target, 'query': 'x' * 201})
        self.assertIsNone(score_run(self.root, r3.id, KW)['target_pages']['娛樂城'])
        r3.call('research_evidence', {'evidence_id': target})
        self.assertEqual(score_run(self.root, r3.id, KW)['target_pages']['娛樂城']['via'], 'research_evidence')

    def test_empty_placeholder_search_counts_as_failed(self):
        r = self.engine(searcher=lambda q, n: {'success': True, 'data': {'web': [{'title': '', 'url': ''}]}})
        r.call('research_search', {'query': 'plain query'})
        s = score_run(self.root, r.id, KW)
        self.assertEqual((s['failed_searches'], s['failed_search_kinds']['no_results']), (1, 1))

    def test_stale_check_reads_expiry(self):
        self.run_research(False)
        self.run_research(False)
        r = self.engine()
        lesson = r.ledger.by_key('failure|research_search|site_operator')
        r.event('lessons_presented', {'time': r.ledger.ts(), 'lessons': [{'id': lesson['id'], 'expires': '2000-01-01'}]})
        self.assertEqual(score_run(self.root, r.id, KW)['stale_lessons_presented'], 1)


    def test_gated_call_does_not_erase_previous_read(self):
        source = self.engine().call('research_fetch', {'url': MAIN, 'purpose': 'x'})['evidence_id']
        r = self.engine(limits=Limits(calls=1, interval=0))
        r.db.execute('UPDATE evidence SET run=? WHERE id=?', (r.id, source))
        r.db.commit()
        r.call('research_evidence', {'evidence_id': source})
        self.assertEqual(r.call('research_evidence', {'evidence_id': source})['error'], 'tool_call_budget')
        self.assertEqual(r.call('research_evidence', {'evidence_id': ['not', 'a', 'string']})['error'], 'tool_call_budget')
        s = score_run(self.root, r.id, KW)
        self.assertEqual(s['target_pages']['娛樂城']['via'], 'research_evidence')
