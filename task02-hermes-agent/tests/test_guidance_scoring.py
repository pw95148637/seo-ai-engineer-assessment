import json, unittest
from src.lessons import FEEDBACK_PREFIX
from src.scoring import score_run, write_blind_packet
from tests.test_lessons import B, KW, MAIN, BRAND, LessonFixture
from tests.test_offpage import EXT, offsite_routes, search_listing

OLD_V06 = ('research.example 的「娛樂城」目標頁是 X（HTTP 200，title/H1 符合）。上次由 Y 的連結（錨文字「娛樂城」）到達；'
           '同一 run 讀了 1 份 sitemap，其中 0 份列出此頁。')


class GuidanceTests(LessonFixture):
    def lessons(self, **kw):
        return {x['key']: x for x in self.engine(**kw).status()['lessons']}

    def test_discovery_hands_over_current_run_evidence(self):
        self.discover()
        r = self.engine()
        shown = {x['key']: x for x in r.status()['lessons']}
        path = shown['discovery|research.example|娛樂城']
        eid = path['verification']['evidence_id']
        self.assertIn(eid, path['statement'])
        self.assertIn('本輪證據', path['statement'])
        for past_finding in ('sitemap', '錨文字', '上次由'):
            self.assertNotIn(past_finding, path['statement'])
        self.assertNotIn('untrusted_fields', path)
        self.assertEqual(r.call('research_evidence', {'evidence_id': eid, 'query': '娛樂城'})['url'], MAIN)

    def test_lessons_stored_by_v06_are_shown_in_the_new_wording(self):
        self.discover()
        self.discover()
        r = self.engine()
        r.db.execute('UPDATE lessons SET statement=? WHERE kind="discovery_path"', (OLD_V06,))
        r.db.commit()
        shown = self.lessons()
        self.assertNotIn('sitemap', shown['discovery|research.example|娛樂城']['statement'])
        site = shown['failure|research_search|site_operator']['statement']
        self.assertTrue(site.startswith('research_search 不要用 site:'), site)

    def test_unconfirmed_path_asks_for_a_fetch(self):
        self.discover()
        self.t.data[BRAND] = (503, {'content-type': 'text/plain'}, b'busy')
        shown = self.lessons()['discovery|research.example|3a娛樂城']
        self.assertEqual(shown['verification']['result'], 'inconclusive')
        self.assertIn('research_fetch', shown['statement'])
        self.assertNotIn('本輪證據', shown['statement'])

    def test_human_review_is_shown_as_a_standard(self):
        r = self.discover()
        lid = r.ledger.add_feedback(r.id, 'action:1', 'scope_error', '把競爭者與我方網站混為一談', 'user', 'general')
        shown = {x['id']: x for x in self.engine().status()['lessons']}
        self.assertTrue(shown[lid]['statement'].startswith(FEEDBACK_PREFIX))

    def test_offsite_page_is_not_a_discovery_entry(self):
        self.t.data.update(offsite_routes())
        self.t.data[EXT + '/review'] = (200, {'content-type': 'text/html'},
                                        f'<a href="{MAIN}">娛樂城</a>'.encode('utf-8'))
        r = self.engine(searcher=search_listing([EXT + '/review']))
        r.call('research_search', {'query': 'brand'})
        r.call('research_offpage', {'url': EXT + '/review', 'purpose': 'inbound link?'})
        self.fetch(r, MAIN)
        self.finish(r)
        data = r.ledger.by_key('discovery|research.example|娛樂城')['data']
        self.assertEqual((data['source_url'], data['source_kind']), (None, 'typed_or_memory'))


class V07ScoringTests(LessonFixture):
    def setUp(self):
        super().setUp()
        self.t.data.update(offsite_routes())

    def test_sitemap_reads_and_refetch_of_verified_pages(self):
        self.discover()
        r = self.engine()
        r.call('research_status', {})
        self.fetch(r, MAIN)
        sitemap = self.fetch(r, B + '/sitemap_index.xml')['evidence_id']
        r.call('research_evidence', {'evidence_id': sitemap, 'query': 'news'})
        s = score_run(self.root, r.id, KW)
        self.assertEqual((s['refetched_verified_pages'], s['sitemap_reads']), (1, 2))

    def offpage_run(self):
        r = self.engine(searcher=search_listing([EXT + '/review', EXT + '/plain']), required_sections=('on_page', 'off_page'))
        found = r.call('research_search', {'query': 'Brand'})['evidence_id']
        linking = r.call('research_offpage', {'url': EXT + '/review', 'purpose': 'inbound link?'})['evidence_id']
        plain = r.call('research_offpage', {'url': EXT + '/plain', 'purpose': 'inbound link?'})['evidence_id']
        home = self.fetch(r, B + '/')['evidence_id']
        claims = [
            dict(kind='observation', section='on_page', text='home links to hub', evidence_ids=[home]),
            dict(kind='observation', section='off_page', text='ext review links to hub', evidence_ids=[linking]),
            dict(kind='observation', section='off_page', text='index lists off-site pages', evidence_ids=[found]),
            dict(kind='observation', section='off_page', text='home has outbound links', evidence_ids=[home]),
            dict(kind='inference', section='off_page', text='some brand outreach', evidence_ids=[linking, plain]),
            dict(kind='unknown', section='off_page', text='complete backlinks')]
        self.assertTrue(r.call('research_finish', {'report': {'claims': claims, 'actions': [
            {'action': 'list our brand on review sites', 'reason': 'competitor is linked from one'}]}})['accepted'])
        return r

    def test_offpage_known_items_and_policy_audit(self):
        r = self.offpage_run()
        s = score_run(self.root, r.id, KW)
        self.assertEqual(s['sections'], {'on_page': 1, 'off_page': 5, 'other': 0})
        o = s['offpage']
        self.assertEqual((o['known'], o['known_external'], o['known_link_verified']), (3, 2, 1))
        self.assertTrue(o['three_columns'])
        self.assertEqual((o['pages_fetched'], o['pages_linking_to_target']), (2, 1))
        self.assertEqual(s['offpage_policy_violations'], [])
        # A request the controller would never make: an off-site host no search listed, without robots.txt.
        r.db.execute('INSERT INTO events(run,kind,data) VALUES(?,?,?)', (r.id, 'request', json.dumps(
            dict(url='https://rogue.example/x', number=99, actor='model', channel='offpage'))))
        r.db.execute('INSERT INTO events(run,kind,data) VALUES(?,?,?)', (r.id, 'request', json.dumps(
            dict(url=EXT + '/never-checked', number=100, actor='model', channel='offpage'))))
        r.db.commit()
        rules = [v['rule'] for v in score_run(self.root, r.id, KW)['offpage_policy_violations']]
        self.assertEqual(rules, ['host_not_from_search'])

    def test_robots_rule_is_audited(self):
        r = self.offpage_run()
        rows = r.db.execute("SELECT path FROM evidence WHERE url=?", (EXT + '/robots.txt',)).fetchone()
        (self.root / rows[0]).write_bytes(b'User-agent: *\nDisallow: /review\n')
        rules = [v['rule'] for v in score_run(self.root, r.id, KW)['offpage_policy_violations']]
        self.assertEqual(rules, ['robots_disallow'])

    def test_blind_packet_carries_sections_and_rubric(self):
        r = self.offpage_run()
        blind = self.root / 'blind'
        bid = write_blind_packet(self.root, r.id, blind)
        items = json.loads((blind / bid / 'items.json').read_text(encoding='utf-8'))
        self.assertEqual([c['section'] for c in items['claims']][:2], ['on_page', 'off_page'])
        self.assertEqual(set(items['rubric']['coverage']), {'on_page', 'off_page', 'actionable', 'epistemic'})
        self.assertTrue(all(len(v) == 3 for v in items['rubric']['coverage'].values()))
        self.assertEqual(items['claims'][1]['sources'][0]['method'], 'offpage_http')
        text = json.dumps(items, ensure_ascii=False)
        self.assertNotIn(r.id, text)
        self.assertNotIn('memory', text)
        self.assertNotIn('lesson', text.lower())
