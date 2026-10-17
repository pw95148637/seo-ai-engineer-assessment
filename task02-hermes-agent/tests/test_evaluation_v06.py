import importlib.util, json, shutil, tempfile, unittest
from pathlib import Path
from unittest import mock
from src.research_core import Research, Limits
from src.lessons import Ledger
from tests.test_lessons import Transport

TASK = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('evaluate_v06', TASK / 'scripts' / 'evaluate_v06.py')
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


def score(read=('娛樂城', '3A娛樂城'), first=2, calls=10, failed=0, tokens=1000, stale=0, blind='x'):
    return dict(target_pages={k: ({'call': first} if k in read else None) for k in ('娛樂城', '3A娛樂城')},
                both_target_pages_read=len(read) == 2, calls_before_first_hit=first if read else None, tool_calls=calls,
                failed_searches=failed, tokens={'total': tokens}, stale_lessons_presented=stale, blind_id=blind)


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.task = Path(self.tmp.name)
        for f in ev.FINGERPRINT:
            (self.task / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(TASK / f, self.task / f)
        stub = dict(primary='casinobase.tw', fallback='icasino.tw')
        with mock.patch.object(ev, 'select_holdout', return_value=stub):
            ev.make_plan(self.task, 'test-model')

    def test_registered_holdout_rule_on_archived_snapshots(self):
        sel = ev.select_holdout(TASK)
        self.assertEqual((sel['primary'], sel['fallback']), ('casinobase.tw', 'icasino.tw'))
        self.assertEqual(len(sel['snapshots']), 3)
        self.assertEqual(sel['alternative_rule_not_used']['top'][0]['host'], '3aarena.com.tw')

    def test_plan_hash_and_code_fingerprint_are_enforced(self):
        self.assertEqual(ev.verify_plan(self.task)['model'], 'test-model')
        with self.assertRaises(SystemExit):
            ev.make_plan(self.task, 'other')
        moved = self.task / 'evaluation' / 'superseded-plan.json'
        (self.task / ev.PLAN).rename(moved)
        (self.task / ev.OUT).mkdir(parents=True)
        (self.task / ev.OUT / 'steps.json').write_text('[]')
        with self.assertRaisesRegex(SystemExit, 'pre-registration'):
            ev.make_plan(self.task, 'other')
        moved.rename(self.task / ev.PLAN)
        path = self.task / ev.PLAN
        original = path.read_text(encoding='utf-8')
        path.write_text(original.replace('"F2"', '"F2x"'), encoding='utf-8')
        with self.assertRaisesRegex(SystemExit, 'plan hash'):
            ev.verify_plan(self.task)
        path.write_text(original, encoding='utf-8')
        code = self.task / 'src' / 'lessons.py'
        code.write_bytes(code.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
        ev.verify_plan(self.task)
        code.write_bytes(code.read_bytes() + b'# changed\n')
        with self.assertRaisesRegex(SystemExit, 'src/lessons.py'):
            ev.verify_plan(self.task)

    def test_steps_run_in_registered_order_and_r2_needs_feedback(self):
        with self.assertRaisesRegex(SystemExit, 'R1'):
            ev.run_step(self.task, 'R2', dry_run=True)
        series = self.task / ev.SERIES
        r = Research(series, target='https://research.example', hosts=['research.example'], limits=Limits(interval=0),
                     transport=Transport(), resolve=lambda h: ['8.8.8.8'], mode='memory')
        r.call('research_finish', {'report': {'claims': [], 'actions': []}})
        out = self.task / ev.OUT
        (out / 'steps.json').write_text(json.dumps([dict(step='R1', attempt=1, run_id=r.id, state='research_complete')]))
        with self.assertRaisesRegex(SystemExit, 'HF'):
            ev.run_step(self.task, 'R2', dry_run=True)
        Ledger(r.db).add_feedback(r.id, 'run', 'reviewed_ok', '', 'user')
        r.db.close()
        with mock.patch('builtins.print') as shown:
            ev.run_step(self.task, 'R2', dry_run=True)
        cmd = shown.call_args[0][0]
        self.assertIn('--mode memory', cmd)
        self.assertNotIn('--no-learn', cmd)
        with mock.patch('builtins.print') as shown:
            ev.run_step(self.task, 'R1', dry_run=True)
        self.assertIn('scored from run', shown.call_args[0][0], 'a finished run without a score is scored, not rerun')
        self.assertTrue((out / 'scores' / 'R1.json').exists())
        with self.assertRaisesRegex(SystemExit, 'R1 already completed'):
            ev.run_step(self.task, 'R1', dry_run=True)
        with self.assertRaisesRegex(SystemExit, 'B1'):
            ev.run_step(self.task, 'R3', dry_run=True)

    def test_failed_attempt_needs_retry_flag_and_has_a_limit(self):
        out = self.task / ev.OUT
        out.mkdir(parents=True)
        (out / 'steps.json').write_text(json.dumps([dict(step='R1', attempt=1, run_id='x', state='quota')]))
        with self.assertRaisesRegex(SystemExit, 'retry'):
            ev.run_step(self.task, 'R1', dry_run=True)
        with mock.patch('builtins.print'):
            ev.run_step(self.task, 'R1', dry_run=True, retry=True)
        (out / 'steps.json').write_text(json.dumps([dict(step='R1', attempt=i, run_id='x', state='quota') for i in (1, 2)]))
        with self.assertRaisesRegex(SystemExit, 'retry limit'):
            ev.run_step(self.task, 'R1', dry_run=True, retry=True)

    def test_attempt_is_logged_before_the_run_and_agent_outcomes_are_final(self):
        plan = ev.verify_plan(self.task)
        head = mock.Mock(stdout=plan['hermes_commit'] + '\n')
        timeout = ev.subprocess.TimeoutExpired(cmd='x', timeout=1000, output=b'partial')
        with mock.patch.object(ev.subprocess, 'run', side_effect=[head, timeout]), mock.patch('builtins.print'):
            ev.run_step(self.task, 'R1')
        log = json.loads((self.task / ev.OUT / 'steps.json').read_text(encoding='utf-8'))
        self.assertEqual([(x['step'], x['state']) for x in log], [('R1', 'controller_timeout')])
        with self.assertRaisesRegex(SystemExit, 'retry'):
            ev.run_step(self.task, 'R1', dry_run=True)
        (self.task / ev.OUT / 'steps.json').write_text(json.dumps([dict(step='R1', attempt=1, state='missing_controller_report')]))
        with self.assertRaisesRegex(SystemExit, 'research outcome'):
            ev.run_step(self.task, 'R1', dry_run=True, retry=True)
        (self.task / ev.OUT / 'steps.json').write_text(json.dumps([dict(step='R1', attempt=1, state='learning_failed')]))
        with self.assertRaisesRegex(SystemExit, 'register a new plan'):
            ev.run_step(self.task, 'R1', dry_run=True, retry=True)

    def test_holdout_preflight_falls_back_to_rank_two(self):
        plan = ev.verify_plan(self.task)
        result = ev.holdout_preflight(self.task, plan, probe=lambda h: dict(host=h, ok=h == 'icasino.tw'))
        self.assertEqual(result['chosen'], 'icasino.tw')
        self.assertTrue((self.task / ev.OUT / 'holdout-choice.json').exists())

    def test_verdict_rules(self):
        base = dict(R1=score(first=12), R2=score(), B1=score(first=10, tokens=1000, blind='b'), R3=score(first=3, tokens=900, blind='r'),
                    HB=score(failed=2, blind='hb'), HM=score(failed=0, blind='hm'))
        review = {k: {'unsupported': 0, 'scope_error': 0} for k in ('b', 'r', 'hb', 'hm')}
        self.assertEqual(ev.judge(base, review)['verdict'], 'improved')
        self.assertEqual(ev.judge(base, {})['verdict'], 'pending_blind_review')
        slow = dict(base, R3=score(first=6, tokens=900, blind='r'))
        self.assertEqual(ev.judge(slow, review)['verdict'], 'not_proven')
        costly = dict(base, R3=score(first=3, tokens=1400, blind='r'))
        self.assertEqual(ev.judge(costly, review)['verdict'], 'regression')
        missed = dict(base, R3=score(read=('娛樂城',), first=3, blind='r'))
        self.assertTrue(ev.judge(missed, review)['failure']['F1'])
        never = dict(base, R1=score(read=(), calls=20), B1=score(read=(), calls=18, blind='b'))
        self.assertTrue(ev.judge(never, review)['improvement']['I2'], 'a run that never hits counts its total calls')
        stale = dict(base, HM=score(stale=1, blind='hm'))
        self.assertEqual(ev.judge(stale, review)['verdict'], 'regression')
        no_usage = dict(base, B1=dict(score(first=10, blind='b'), tokens=None))
        self.assertEqual(ev.judge(no_usage, review)['verdict'], 'incomplete')
        stale_r2 = dict(base, R2=score(stale=1))
        self.assertTrue(ev.judge(stale_r2, review)['failure']['F3'])


class SyntheticCheckTests(unittest.TestCase):
    def test_writes_new_directory_and_never_touches_archive(self):
        spec = importlib.util.spec_from_file_location('evaluate_memory', TASK / 'scripts' / 'evaluate_memory.py')
        em = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(em)
        archived = (TASK / 'evidence' / 'memory-evaluation' / 'results.json').read_bytes()
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'new'
            with mock.patch('sys.argv', ['x', '--output', str(out)]), mock.patch('sys.stdout'):
                em.main()
            rows = json.loads((out / 'results.json').read_text(encoding='utf-8'))['results']
            with mock.patch('sys.argv', ['x', '--output', str(out)]), self.assertRaises(SystemExit), \
                    mock.patch('sys.stderr'):
                em.main()
        self.assertEqual((TASK / 'evidence' / 'memory-evaluation' / 'results.json').read_bytes(), archived)
        stable = {r['mode']: r for r in rows if r['case'] == 'stable'}
        self.assertLess(stable['memory']['calls_before_first_hit'], stable['baseline']['calls_before_first_hit'])
        self.assertTrue(all(r['both_target_pages_read'] and r['stale'] == 0 for r in rows))
