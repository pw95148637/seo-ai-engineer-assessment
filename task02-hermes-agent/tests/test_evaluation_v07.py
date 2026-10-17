import importlib.util, json, shutil, sqlite3, tempfile, unittest
from pathlib import Path
from unittest import mock
from src.research_core import Research, Limits
from tests.test_lessons import Transport

TASK = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('evaluate_v07', TASK / 'scripts' / 'evaluate_v07.py')
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)
KW = ('娛樂城', '3A娛樂城')


def score(read=KW, first=1, calls=10, tokens=1000, stale=0, blind='x', sitemap=0, refetch=0, known=2, ext=1, link=1,
          three=True, violations=()):
    return dict(target_pages={k: ({'call': first} if k in read else None) for k in KW}, both_target_pages_read=len(read) == 2,
                calls_before_first_hit=first if read else None, tool_calls=calls, tokens={'total': tokens},
                stale_lessons_presented=stale, blind_id=blind, sitemap_reads=sitemap, refetched_verified_pages=refetch,
                offpage=dict(known=known, known_external=ext, known_link_verified=link, three_columns=three),
                offpage_policy_violations=list(violations))


def answer(defects=0, supported=2, coverage=(1, 1, 1, 1)):
    return dict(unsupported=defects, scope_error=0, off_page_supported_known=supported,
                coverage=dict(zip(('on_page', 'off_page', 'actionable', 'epistemic'), coverage)))


class EvaluationV07Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.task = Path(self.tmp.name)
        for f in ev.FINGERPRINT:
            (self.task / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(TASK / f, self.task / f)
        v06 = self.task / ev.V06_PLAN
        v06.parent.mkdir(parents=True, exist_ok=True)
        v06.write_text(json.dumps({'holdout': {'selection': {'ranking': [
            {'host': h} for h in ('casinobase.tw', 'icasino.tw', 'goldbobet.com', 'henfoo.com')]}}}), encoding='utf-8')
        v06.with_suffix('.sha256').write_text('abc\n')
        (self.task / ev.V06_HOLDOUT).parent.mkdir(parents=True, exist_ok=True)
        (self.task / ev.V06_HOLDOUT).write_text(json.dumps({'chosen': 'icasino.tw'}))
        r = Research(self.task / ev.LEDGER_SOURCE, target='https://research.example', limits=Limits(interval=0),
                     transport=Transport(), resolve=lambda h: ['8.8.8.8'])
        self.lesson = r.ledger._create('failure_pattern', 'failure|research_search|site_operator', 'research.example', 'host',
                                       'active', 'controller', r.id, 'fixture', 'x', dict(tool='research_search',
                                       feature='site_operator', fails=2, alternative=[0, 0]), '2099-01-01T00:00:00+00:00')
        r.db.close()
        self.digest = ev.make_plan(self.task, 'test-model')

    def test_plan_records_ledger_hash_and_a_fresh_holdout(self):
        plan = ev.verify_plan(self.task)
        self.assertEqual(plan['ledger_source']['sha256'], ev.file_sha256(self.task / ev.LEDGER_SOURCE / 'research.sqlite'))
        self.assertEqual([x['id'] for x in plan['ledger_source']['active_lessons']], [self.lesson['id']])
        self.assertEqual((plan['holdout']['primary'], plan['holdout']['fallback']), ('casinobase.tw', 'goldbobet.com'))
        self.assertEqual(plan['v06_reference']['plan_sha256'], 'abc')
        self.assertEqual((self.task / ev.PLAN).with_suffix('.sha256').read_text().strip(), self.digest)
        with self.assertRaises(SystemExit):
            ev.make_plan(self.task, 'again')

    def test_verify_rejects_edited_plan_changed_code_and_changed_ledger(self):
        path = self.task / ev.PLAN
        original = path.read_text(encoding='utf-8')
        path.write_text(original.replace('"F4"', '"F4x"'), encoding='utf-8')
        with self.assertRaisesRegex(SystemExit, 'plan hash'):
            ev.verify_plan(self.task)
        path.write_text(original, encoding='utf-8')
        code = self.task / 'src' / 'scoring.py'
        saved = code.read_bytes()
        code.write_bytes(saved + b'# changed\n')
        with self.assertRaisesRegex(SystemExit, 'src/scoring.py'):
            ev.verify_plan(self.task)
        code.write_bytes(saved)
        db = sqlite3.connect(self.task / ev.LEDGER_SOURCE / 'research.sqlite')
        db.execute('UPDATE lessons SET status="vetoed"')
        db.commit()
        db.close()
        with self.assertRaisesRegex(SystemExit, 'v0.6 ledger'):
            ev.verify_plan(self.task)

    def test_order_ledger_copy_and_retry(self):
        with self.assertRaisesRegex(SystemExit, 'R4'):
            ev.run_step(self.task, 'B2', dry_run=True)
        with mock.patch('builtins.print') as shown:
            ev.run_step(self.task, 'R4', dry_run=True)
        cmd = shown.call_args[0][0]
        self.assertIn('--mode memory', cmd)
        self.assertIn('--no-learn', cmd)
        self.assertIn('evaluation/v07/runs/R4', cmd.replace('\\', '/'))
        plan = ev.verify_plan(self.task)
        head = mock.Mock(stdout=plan['hermes_commit'] + '\n')
        quota = mock.Mock(stdout='{"run_id": "x", "state": "quota", "exit_code": 2}\n', stderr='', returncode=2)
        with mock.patch.object(ev.subprocess, 'run', side_effect=[head, quota]), mock.patch('builtins.print'):
            ev.run_step(self.task, 'R4')
        copied = sqlite3.connect(self.task / ev.STEPS['R4']['root'] / 'research.sqlite')
        self.assertEqual(copied.execute('SELECT id FROM lessons').fetchone()[0], self.lesson['id'])
        copied.close()
        log = json.loads((self.task / ev.OUT / 'steps.json').read_text(encoding='utf-8'))
        self.assertEqual([(x['step'], x['state']) for x in log], [('R4', 'quota')])
        with self.assertRaisesRegex(SystemExit, 'retry'):
            ev.run_step(self.task, 'R4', dry_run=True)
        (self.task / ev.OUT / 'steps.json').write_text(json.dumps([dict(step='R4', attempt=1, state='no_autonomous_tool_use')]))
        with self.assertRaisesRegex(SystemExit, 'research outcome'):
            ev.run_step(self.task, 'R4', dry_run=True, retry=True)
        (self.task / ev.OUT / 'steps.json').write_text(json.dumps([dict(step='R4', attempt=1, state='research_complete'),
                                                                    dict(step='B2', attempt=1, state='research_complete')]))
        with self.assertRaisesRegex(SystemExit, 'HP2'):
            ev.run_step(self.task, 'HB2', dry_run=True)
        result = ev.holdout_preflight(self.task, plan, probe=lambda h: dict(host=h, ok=h == 'goldbobet.com'))
        self.assertEqual(result['chosen'], 'goldbobet.com')

    def test_copy_refuses_a_ledger_that_changed(self):
        plan = ev.verify_plan(self.task)
        src = self.task / ev.LEDGER_SOURCE / 'research.sqlite'
        src.write_bytes(src.read_bytes() + b'\0')
        with self.assertRaisesRegex(SystemExit, 'registered hash'):
            ev.copy_ledger(self.task, plan, self.task / 'elsewhere')

    def test_verdict_rules(self):
        base = dict(R4=score(first=1, tokens=900, blind='r'), B2=score(first=4, tokens=1000, sitemap=2, blind='b'))
        review = dict(r=answer(), b=answer())
        j = ev.judge(base, review)
        self.assertEqual((j['verdict'], j['offpage_verdict'], j['holdout']), ('improved', 'achieved', 'not_run'))
        self.assertEqual(ev.judge(base, {})['verdict'], 'pending_blind_review')
        self.assertEqual(ev.judge(base, {})['offpage_verdict'], 'pending_blind_review')
        cases = {
            'not_proven': [dict(R4=score(first=1, tokens=1100, blind='r')),
                           dict(R4=score(first=1, tokens=900, refetch=1, blind='r')),
                           dict(R4=score(first=3, tokens=900, blind='r'))],
            'regression': [dict(R4=score(first=1, tokens=1400, blind='r')),
                           dict(R4=score(read=('娛樂城',), first=1, tokens=900, blind='r')),
                           dict(R4=score(first=1, tokens=900, stale=1, blind='r'))]}
        for verdict, changes in cases.items():
            for change in changes:
                self.assertEqual(ev.judge(dict(base, **change), review)['verdict'], verdict, change)
        worse = dict(r=answer(coverage=(1, 1, 1, 0)), b=answer())
        self.assertEqual(ev.judge(base, worse)['verdict'], 'not_proven')
        unsafe = dict(base, B2=score(first=4, blind='b', violations=[{'rule': 'host_not_from_search'}]))
        j = ev.judge(unsafe, review)
        self.assertEqual((j['verdict'], j['offpage_verdict']), ('regression', 'unsafe'))
        no_link = dict(R4=score(first=1, tokens=900, link=0, blind='r'), B2=score(first=4, link=0, blind='b'))
        self.assertEqual(ev.judge(no_link, review)['offpage_verdict'], 'partial')
        thin = dict(R4=score(first=1, tokens=900, known=1, blind='r'), B2=score(first=4, known=1, blind='b'))
        self.assertEqual(ev.judge(thin, review)['offpage_verdict'], 'not_achieved')
        weak_r4 = dict(base, R4=score(first=1, tokens=900, known=1, blind='r'))
        self.assertEqual(ev.judge(weak_r4, {'b': answer()})['capability']['C1'], False,
                         'one arm failing mechanically decides C1 before blind review')
        floor = dict(R4=score(first=1, tokens=900, blind='r'), B2=score(first=1, blind='b'))
        self.assertTrue(ev.judge(floor, review)['improvement']['L2'], 'both at the floor of one call')
        holdout = dict(base, HB2=score(read=('娛樂城',), blind='hb'), HM2=score(read=('娛樂城',), blind='hm'))
        self.assertEqual(ev.judge(holdout, dict(review, hb=answer(), hm=answer()))['verdict'], 'improved')
        hurt = dict(review, hb=answer(), hm=answer(defects=1))
        j = ev.judge(holdout, hurt)
        self.assertEqual((j['verdict'], j['holdout_checks']['H1']), ('not_proven', False))
