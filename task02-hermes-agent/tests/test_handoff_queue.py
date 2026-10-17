import contextlib, hashlib, importlib.util, io, json, os, sqlite3, tempfile, unittest
from pathlib import Path
from src.research_core import Research, Limits
from src.lessons import Ledger
from tests.test_lessons import B, BRAND, MAIN, KW, Transport, failing_site_search

TASK = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('handoff_queue', TASK / 'scripts' / 'handoff_queue.py')
hq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hq)
HOST = 'research.example'


class QueueFixture(unittest.TestCase):
    """Real controller runs on a fake site; the queue reads the ledger they leave behind."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.t = Transport()

    def engine(self, **kw):
        opts = dict(root=self.root, target=B, hosts=[HOST], limits=Limits(interval=0), transport=self.t,
                    resolve=lambda h: ['8.8.8.8'], searcher=failing_site_search, keywords=KW, mode='memory')
        opts.update(kw)
        r = Research(**opts)
        self.addCleanup(r.db.close)
        return r

    def fetch(self, r, url):
        return r.call('research_fetch', {'url': url, 'purpose': 'test'})

    def finish(self, r, actions=(('audit our own site', 'fixture'),), unknowns=(), learn=True):
        report = {'claims': [{'kind': 'unknown', 'text': 'fixture', 'section': 'other'}],
                  'actions': [{'action': a, 'reason': b} for a, b in actions], 'unknowns': list(unknowns)}
        result = r.call('research_finish', {'report': report})
        if learn:
            r.learn_completed()
        return result

    def queue(self, run=None):
        return hq.build_queue(self.root / 'research.sqlite', run, self.root)

    @staticmethod
    def pick(q, category, **refs):
        return [x for x in q['items'] if x['category'] == category
                and all(x['refs'].get(k) == v for k, v in refs.items())]


class BudgetAndRefusals(QueueFixture):
    def test_exhausted_budgets_are_listed_and_unused_ones_are_not(self):
        r = self.engine(limits=Limits(interval=0, requests=3))
        for i in range(5):
            r.call('research_search', {'query': f'娛樂城 {i}'})
        self.fetch(r, B + '/')        # robots.txt + page: 2 requests
        self.fetch(r, B + '/hub/')    # 3rd request
        self.fetch(r, MAIN)           # refused: request_budget
        self.finish(r)
        q = self.queue()
        self.assertEqual(q['usage']['requests'], dict(used=3, limit=3, by=dict(model=3, offpage=0, controller=0)))
        self.assertEqual(q['usage']['searches'], dict(used=5, limit=5))
        budgets = {x['refs']['budget']: x for x in self.pick(q, 'limit') if 'budget' in x['refs']}
        self.assertEqual(set(budgets), {'requests', 'searches'})
        self.assertTrue(any('request_budget' in e for e in budgets['requests']['evidence']))
        self.assertEqual(budgets['searches']['priority'], 'review')

    def test_controller_refusals_and_site_refusal_with_retry(self):
        self.t.data[B + '/blocked'] = (403, {'content-type': 'text/plain', 'retry-after': '60'}, b'no')
        r = self.engine(hosts=[HOST, 'intranet.example'],
                        resolve=lambda h: ['10.0.0.1'] if h == 'intranet.example' else ['8.8.8.8'])
        self.fetch(r, 'https://other.example/page')           # host_not_allowed
        self.fetch(r, 'https://intranet.example/')            # private_address
        r.call('research_offpage', {'url': 'https://elsewhere.example/a', 'purpose': 'test'})  # not from search
        self.fetch(r, B + '/blocked')
        self.fetch(r, B + '/blocked/')                        # the model asks again after a 403, trailing slash added
        self.finish(r)
        q = self.queue()
        codes = {x['refs']['code']: x for x in self.pick(q, 'limit') if 'code' in x['refs']}
        self.assertEqual(codes['host_not_allowed']['priority'], 'review')
        self.assertIn('https://other.example/page', ' '.join(codes['host_not_allowed']['evidence']))
        self.assertEqual(codes['private_address']['priority'], 'decide')
        self.assertEqual(codes['offpage_not_from_search']['priority'], 'review')
        refusal = [x for x in self.pick(q, 'limit') if 'retried' in x['refs']]
        self.assertEqual(len(refusal), 1)
        self.assertTrue(refusal[0]['refs']['retried'])
        self.assertEqual(refusal[0]['priority'], 'decide')
        self.assertIn('Retry-After 60', refusal[0]['evidence'][0])
        self.assertEqual(q['usage']['offpage']['used'], 0)  # refused before it counted against the budget


class LessonChanges(QueueFixture):
    def first_run(self):
        r = self.engine()
        r.call('research_search', {'query': 'site:research.example 娛樂城'})   # fails: site_operator
        for u in ('/', '/hub/'):
            self.fetch(r, B + u)
        self.fetch(r, MAIN)
        self.fetch(r, BRAND)
        self.finish(r)
        return r.id

    def test_activated_lessons_need_a_decision_and_candidates_explain_the_threshold(self):
        run1 = self.first_run()
        q = self.queue(run1)
        activated = [x for x in self.pick(q, 'lesson_change') if x['refs']['new'] == 'active']
        self.assertEqual(len(activated), 2)
        for x in activated:
            self.assertEqual(x['priority'], 'decide')
            self.assertTrue(x['refs']['created'])
            self.assertIn(f'veto --lesson {x["refs"]["lesson"]}', ' '.join(o['command'] or '' for o in x['options']))
        candidate = [x for x in self.pick(q, 'lesson_change') if x['refs']['new'] == 'candidate']
        self.assertEqual(len(candidate), 1)
        self.assertEqual(candidate[0]['priority'], 'review')
        self.assertIn('目前 1 個', candidate[0]['why_human'])
        self.assertIn('site:research.example 娛樂城', ' '.join(candidate[0]['evidence']))
        self.assertEqual(q['items'][0]['priority'], 'decide')  # decisions come first

    def test_second_run_activates_failure_and_lists_lessons_in_use(self):
        self.first_run()
        r = self.engine()
        r.call('research_status', {})
        r.call('research_search', {'query': 'site:research.example 3A娛樂城'})
        self.finish(r)
        q = self.queue(r.id)
        active = [x for x in self.pick(q, 'lesson_change') if x['refs']['new'] == 'active']
        self.assertEqual([x['title'] for x in active], ['啟用經驗：failure|research_search|site_operator'])
        in_use = self.pick(q, 'lessons_in_use')
        self.assertEqual(len(in_use), 1)
        self.assertEqual(in_use[0]['priority'], 'info')  # both discovery paths re-verified ok
        self.assertEqual(sum('重抓 ok' in e for e in in_use[0]['evidence']), 2)

    def test_revocation_at_start_is_attributed_to_the_run_and_a_veto_marks_items_handled(self):
        run1 = self.first_run()
        self.t.data[MAIN] = (404, {'content-type': 'text/plain'}, b'gone')
        r = self.engine()
        r.call('research_status', {})
        self.finish(r)
        q = self.queue(r.id)
        revoked = [x for x in self.pick(q, 'lesson_change') if x['refs']['new'] == 'revoked']
        self.assertEqual(len(revoked), 1)
        self.assertEqual((revoked[0]['refs']['old'], revoked[0]['priority']), ('active', 'review'))
        self.assertIn('研究開始時', ' '.join(revoked[0]['evidence']))
        brand = Ledger(r.db).by_key('discovery|research.example|3a娛樂城')
        Ledger(r.db).veto(brand['id'], 'wrong page', 'tester')
        handled = [x for x in self.queue(run1)['items'] if x['refs'].get('lesson') == brand['id']]
        self.assertIn('tester', handled[0]['handled'])


class ReportItems(QueueFixture):
    def test_p0_and_legal_actions_need_legal_or_decision_maker(self):
        r = self.engine()
        self.finish(r, actions=[('P0｜先建立我方基準', 'r1'), ('P2｜確認法規與牌照後再上線', 'r2'), ('P1｜改善內鏈', 'r3')])
        q = self.queue()
        flagged = {x['refs']['target']: x for x in self.pick(q, 'action') if 'target' in x['refs']}
        self.assertEqual(set(flagged), {'action:1', 'action:2'})
        self.assertEqual((flagged['action:1']['priority'], flagged['action:1']['refs']['tag']), ('decide', 'P0'))
        self.assertEqual((flagged['action:2']['priority'], flagged['action:2']['refs']['legal_terms']), ('review', ['法規', '牌照']))
        self.assertTrue(all('需要法務或決策者' in x['title'] for x in flagged.values()))
        rest = [x for x in self.pick(q, 'action') if 'targets' in x['refs']]
        self.assertEqual(rest[0]['refs']['targets'], ['action:3'])
        Ledger(r.db).add_feedback(r.id, 'action:1', 'scope_error', '不適用我方', 'tester')
        handled = [x for x in self.queue()['items'] if x['refs'].get('target') == 'action:1']
        self.assertIn('scope_error', handled[0]['handled'])
        self.assertEqual(self.queue()['summary']['handled'], 1)

    def test_unknowns_are_grouped_by_the_data_they_need(self):
        r = self.engine()
        self.finish(r, unknowns=['完整 backlink 清單', '競爭者排名與流量', '我方網域未提供', '出金說法的法律實體'])
        (x,) = self.pick(self.queue(), 'unknown')
        text = '\n'.join(x['evidence'])
        for label in ('完整反向連結', '競爭者的排名、流量與轉換', '我方網站資料', '法律、金流與契約', '其他'):
            self.assertIn(f'【{label}】', text)  # 'fixture' (the unknown claim) falls into 其他
        self.assertIn('未知項 5 項', x['title'])

    def test_rejected_report_is_listed_with_the_rule_it_broke(self):
        r = self.engine()
        bad = {'claims': [{'kind': 'observation', 'text': 'no evidence', 'section': 'other'}], 'actions': []}
        r.call('research_finish', {'report': bad})
        self.finish(r)
        q = self.queue()
        (x,) = self.pick(q, 'report_rejection')
        self.assertIn('claim_needs_evidence', x['evidence'][0])
        self.assertIn('observation/inference 必須引用', x['evidence'][0])
        self.assertEqual(q['run']['report_rejections'], 1)
        Ledger(r.db).add_feedback(r.id, 'run', 'reviewed_ok', '', 'tester')
        (x,) = self.pick(self.queue(), 'report_rejection')
        self.assertIn('tester', x['handled'])

    def test_finish_stopped_by_the_call_budget_is_a_limit_not_a_rejection(self):
        r = self.engine(limits=Limits(interval=0, calls=2))
        r.call('research_status', {})
        r.call('research_status', {})
        self.finish(r, learn=False)  # third call: refused before the controller judges the report
        q = self.queue()
        self.assertEqual(self.pick(q, 'report_rejection'), [])
        self.assertEqual(q['run']['report_rejections'], 0)
        (budget,) = [x for x in self.pick(q, 'limit') if x['refs'].get('budget') == 'calls']
        self.assertIn('research_finish 被拒（tool_call_budget）', ' '.join(budget['evidence']))
        self.assertIn('3/2（超過上限的 1 次被拒）', budget['title'])

    def test_missing_learning_record_is_flagged(self):
        r = self.engine()
        self.finish(r, learn=False)
        titles = [x['title'] for x in self.pick(self.queue(), 'preflight')]
        self.assertEqual(titles, ['這次研究沒有學習紀錄'])


class Interface(QueueFixture):
    def test_cli_writes_both_files_reads_only_and_defaults_to_latest_run(self):
        first = self.engine()
        self.finish(first)
        second = self.engine()
        self.finish(second)
        db = self.root / 'research.sqlite'
        before = hashlib.sha256(db.read_bytes()).hexdigest()
        out = self.root / 'out'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(hq.main([str(self.root), '--out', str(out), '--command-root', 'runs/copy']), 0)
        md = (out / f'{second.id}-handoff.md').read_text(encoding='utf-8')
        data = json.loads((out / f'{second.id}-handoff.json').read_text(encoding='utf-8'))
        self.assertTrue(md.startswith(f'# 交還人類清單：run {second.id[:8]}'))
        self.assertIn('## 固定由人決定的事', md)
        self.assertIn('--root runs/copy', md)
        self.assertEqual(data['source']['sha256'], before)
        self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), before)
        self.assertEqual(hq.build_queue(db, first.id[:8])['run']['id'], first.id)

    def test_failed_preflight_without_a_ledger_and_newer_than_ledger_runs(self):
        pf = dict(ready=False, blocker='oauth_required', logged_in=False, rate_limited=False,
                  actual_tools=['research_status'], expected_tools=['research_status'])
        stopped = 'f' * 32
        (self.root / f'{stopped}-preflight.json').write_text(json.dumps(pf), encoding='utf-8')
        (self.root / f'{stopped}-outcome.json').write_text(json.dumps(dict(state='oauth_required', exit_code=2)), encoding='utf-8')
        q = self.queue()  # no research.sqlite at all
        self.assertEqual((q['run']['id'], q['run']['started'], q['source']['sha256']), (stopped, False, None))
        (x,) = self.pick(q, 'preflight')
        self.assertEqual((x['priority'], x['title']), ('decide', '開跑前檢查未通過：oauth_required'))
        self.assertIn('沒有進入研究', hq.render_markdown(q))
        r = self.engine()
        self.finish(r)
        os.utime(self.root / f'{stopped}-preflight.json')  # the stopped attempt is the newest
        self.assertEqual(self.queue()['run']['id'], stopped)
        self.assertEqual(self.queue(r.id)['run']['id'], r.id)

    def test_native_learning_writes_need_a_decision(self):
        r = self.engine()
        self.finish(r)
        rid = r.id
        (self.root / f'{rid}-outcome.json').write_text(json.dumps(dict(state='research_complete', hermes_learning='learn')), encoding='utf-8')
        (self.root / f'{rid}-review.json').write_text(json.dumps(dict(completed=True, timed_out=False, result='skill',
                                                                       actions=["Skill 'x' patched"])), encoding='utf-8')
        call = lambda name: {'tool_calls': [{'function': {'name': name, 'arguments': '{}'}}]}
        (self.root / f'{rid}-hermes.json').write_text(json.dumps(dict(messages=[call('research_status'), call('skill_manage')])),
                                                      encoding='utf-8')
        (self.root / f'{rid}-pre-review').mkdir()
        (x,) = [i for i in self.pick(self.queue(), 'lesson_change') if i['refs'].get('native')]
        self.assertEqual(x['priority'], 'decide')
        text = ' '.join(x['evidence'])
        self.assertIn('skill_manage 1 次', text)
        self.assertIn("Skill 'x' patched", text)
        self.assertIn(f'{rid}-pre-review', ' '.join(o['command'] or '' for o in x['options']))

    def test_ledger_without_lessons_tables(self):
        db = sqlite3.connect(self.root / 'research.sqlite')
        db.executescript('CREATE TABLE runs(id TEXT PRIMARY KEY,host TEXT,mode TEXT,status TEXT,created TEXT);'
                         'CREATE TABLE events(id INTEGER PRIMARY KEY,run TEXT,kind TEXT,data TEXT);')
        db.execute("INSERT INTO runs VALUES('old1','x.example','baseline','finished','2026-10-15T00:00:00+00:00')")
        for kind, data in [('start', {'mode': 'baseline', 'limits': {'requests': 30, 'calls': 40}}),
                           ('tool_call', {'name': 'research_fetch', 'args': {'url': 'https://y.example/'}}),
                           ('tool_error', {'name': 'research_fetch', 'error': 'host_not_allowed', 'error_type': 'Failure'}),
                           ('report', {'claims': [], 'actions': [{'action': 'P0 audit', 'reason': 'r'}]})]:
            db.execute('INSERT INTO events(run,kind,data) VALUES(?,?,?)', ('old1', kind, json.dumps(data)))
        db.commit()
        db.close()
        q = self.queue()
        self.assertEqual(q['usage']['calls'], dict(used=1, limit=40))
        self.assertEqual([x['refs'].get('code') for x in self.pick(q, 'limit')], ['host_not_allowed'])
        self.assertEqual(self.pick(q, 'lesson_change'), [])
        self.assertIn('## 需要決定', hq.render_markdown(q))


if __name__ == '__main__':
    unittest.main()
