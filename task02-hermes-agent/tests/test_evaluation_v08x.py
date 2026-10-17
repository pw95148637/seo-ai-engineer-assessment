import contextlib, importlib.util, io, json, shutil, unittest
from datetime import datetime, timezone
from pathlib import Path
from src import hermes_homes as hh
from tests.test_evaluation_v08 import V08Fixture, FakeRunner, usage_at, MORNING, ev

TASK = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('evaluate_v08x', TASK / 'scripts' / 'evaluate_v08x.py')
x = importlib.util.module_from_spec(spec)
spec.loader.exec_module(x)


class V08xFixture(V08Fixture):
    """A finished v0.8 sequence on the fixture site (FakeRunner), then the v0.8x plan registered on top of it."""
    def setUp(self):
        super().setUp()
        saved = x.clock
        x.clock = lambda: self.now
        self.addCleanup(setattr, x, 'clock', saved)
        self.run_until('HL', FakeRunner(self.task))
        self.score()
        shutil.copyfile(TASK / 'scripts' / 'evaluate_v08x.py', self.task / 'scripts' / 'evaluate_v08x.py')
        self.digest = x.make_plan(self.task)

    def xstep(self, name, runner=None, session=5.0, weekly=20.0):
        with contextlib.redirect_stdout(io.StringIO()):
            return x.run_step(self.task, name, usage=lambda t: dict(session=session, weekly=weekly, usage={}),
                              runner=runner or FakeRunner(self.task), link_plugin=False, check_commit=False)

    def run_all(self, runner):
        with contextlib.redirect_stdout(io.StringIO()):
            return x.run_all(self.task, usage=usage_at(5.0), runner=runner, link_plugin=False, check_commit=False)

    def answers(self, prefer):
        """Answers of every reviewer; prefer maps a step pair to the step every reviewer prefers (or 'equal')."""
        key = json.loads((self.task / x.OUT / 'pairwise-key.json').read_text(encoding='utf-8'))
        for r in x.REVIEWERS:
            rows = key['assignments'][r]
            pairs = {}
            for p in rows:
                pair = next(q for q in x.PAIRS if set(q) == {p['A'], p['B']})
                choice = prefer.get(pair, 'equal')
                pairs[p['pair']] = dict(preferred='equal' if choice == 'equal' else 'A' if p['A'] == choice else 'B',
                                        strength='slight', reasons='fixture')
            reports = {key['codes'][s]: dict(summary='', defects=[]) for p in rows for s in (p['A'], p['B'])}
            (self.task / x.OUT / 'pairwise' / 'answers' / f'{r}.json').write_text(json.dumps(dict(
                reviewer=r, reports=reports, pairs=pairs), ensure_ascii=False), encoding='utf-8')


class EvaluationV08xTests(V08xFixture):
    def test_plan_is_registered_once_and_checks_the_v08_system(self):
        plan = x.verify_plan(self.task)
        self.assertEqual(plan['order'][0], 'X0')
        self.assertEqual(plan['order'][1:4], ['C6', 'L6', 'N6'])
        self.assertEqual(plan['order'][-3:], ['C10', 'L10', 'N10'])  # round 10 in the position of rounds 1 and 5
        self.assertEqual(plan['base']['v08_plan_sha256'], (self.task / ev.PLAN).with_suffix('.sha256')
                         .read_text().strip())
        with self.assertRaisesRegex(SystemExit, 'never rewritten'):
            x.make_plan(self.task)
        code = self.task / 'src' / 'lessons.py'  # a v0.8 fingerprint file: the extension must stop
        code.write_bytes(code.read_bytes() + b'# changed\n')
        with self.assertRaisesRegex(SystemExit, 'code changed'):
            x.verify_plan(self.task)

    def test_continuation_runs_and_isolation(self):
        with self.assertRaisesRegex(SystemExit, 'needs earlier steps'):
            self.xstep('C6')
        v08_native = hh.learned_files(hh.home_path(self.task, ev.NATIVE_HOME))
        entry = self.xstep('X0')
        v08 = ev.settled(ev.load_log(self.task))
        self.assertEqual(entry['ledger_sha256'], v08['LZ']['ledger_sha256'])
        self.assertEqual(entry['native_digest'], v08['NZ']['frozen_digest'])
        with self.assertRaisesRegex(SystemExit, 'at or above 90%'):
            self.xstep('C6', session=90.0)
        with self.assertRaisesRegex(SystemExit, 'at or above 90%'):
            self.xstep('C6', weekly=95.0)
        runner = FakeRunner(self.task)
        ran = self.run_all(runner)
        self.assertEqual(ran, x.ORDER[1:])
        done = x.settled(x.load_log(self.task))
        self.assertTrue(all(not e.get('isolation') for e in done.values()))
        # the ledger arm continued: L6 saw the discovery paths and the review the v0.8 ledger holds
        self.assertEqual(len(runner.seen_lessons['L6']), 3)
        self.assertEqual(runner.seen_lessons['C6'], [])
        # the native arm continued: its first session saw what v0.8 N5 kept (six sessions, two entries each)
        first_native = x.ORDER.index('N6') - 1
        self.assertEqual(len(runner.seen_memory[first_native].split(hh.ENTRY_DELIMITER)), 12)
        # the v0.8 home and ledger stay as v0.8 left them
        self.assertEqual(hh.learned_files(hh.home_path(self.task, ev.NATIVE_HOME)), v08_native)
        x.verify_plan(self.task)
        with self.assertRaisesRegex(SystemExit, 'already settled'):
            self.xstep('C6')

        self.assertEqual(x.score_all(self.task)['not_run'], [])
        x.pairwise_packet(self.task, seed=2)
        key = json.loads((self.task / x.OUT / 'pairwise-key.json').read_text(encoding='utf-8'))
        packet = self.task / x.OUT / 'pairwise'
        self.assertEqual(len(list((packet / 'reports').iterdir())), 6)
        run_ids = {x.run_source(self.task, s)[0]['run_id'] for s in x.REPORTS}
        for d in (packet / 'reports').iterdir():
            text = (d / 'report.md').read_text(encoding='utf-8')
            self.assertFalse(any(r in text for r in run_ids))
            self.assertTrue(text.startswith('# 研究報告 ' + d.name))
            self.assertTrue(json.loads((d / 'sources.json').read_text(encoding='utf-8')))
        listing = json.dumps([str(p.relative_to(packet)) for p in packet.rglob('*')])
        self.assertFalse(any(s in listing for s in ('C10', 'L10', 'N10', 'key')))
        for r in x.REVIEWERS:
            assigned = json.loads((packet / f'{r}.json').read_text(encoding='utf-8'))
            self.assertEqual(len(assigned['pairs']), 5)
            self.assertIn(f'answers/{r}.json', (packet / f'INSTRUCTIONS-{r}.md').read_text(encoding='utf-8'))
        self.assertEqual(set(key['codes']), set(x.REPORTS))
        with self.assertRaisesRegex(SystemExit, 'written once'):
            x.pairwise_packet(self.task)

        v = x.compare(self.task)
        self.assertEqual(v['judgment']['ledger']['verdict'], 'pending_blind_review')
        self.assertEqual(v['judgment']['ledger']['product'], 'pending')
        self.assertEqual(set(v['rows']), {f'{a}{k}' for a in 'CLN' for k in range(1, 11)})
        self.answers({('L1', 'L10'): 'L10', ('N1', 'N10'): 'N1', ('C1', 'C10'): 'equal', ('L10', 'C10'): 'L10'})
        v = x.compare(self.task)
        self.assertEqual(v['pairwise']['majority']['L1-L10'], 'L10')
        self.assertEqual(v['judgment']['ledger']['product'], 'better')
        self.assertEqual(v['judgment']['native']['product'], 'worse')
        self.assertEqual(v['judgment']['ledger']['dimensions']['self']['quality'], 'better')
        self.assertEqual(len(v['stores']['native']), 10)
        diff = x.diff(self.task, 'L1', 'L10')
        self.assertIn('L10', diff['counts'])
        rspec = importlib.util.spec_from_file_location('render_v08x', TASK / 'scripts' / 'render_v08x.py')
        render = importlib.util.module_from_spec(rspec)
        rspec.loader.exec_module(render)
        tables = render.render(json.loads((self.task / x.OUT / 'verdict.json').read_text(encoding='utf-8')))
        self.assertIn('| 10 |', tables)
        self.assertIn('| L1-L10 |', tables)


class PairwiseRuleTests(unittest.TestCase):
    def test_majority_and_product_verdicts(self):
        self.assertEqual(x.majority(['L10', 'L10', 'L1']), 'L10')
        self.assertEqual(x.majority(['L10', 'equal', 'L1']), 'no_majority')
        self.assertEqual(x.majority(['equal', 'equal', 'L1']), 'no_majority')
        base = {('L1', 'L10'): 'L10', ('N1', 'N10'): 'no_majority', ('C1', 'C10'): 'no_majority',
                ('L10', 'C10'): 'no_majority', ('N10', 'C10'): 'C10'}
        self.assertEqual(x.product_verdict('ledger', base), 'better')
        self.assertEqual(x.product_verdict('ledger', {**base, ('C1', 'C10'): 'C10'}), 'better_but_control_too')
        self.assertEqual(x.product_verdict('ledger', {**base, ('L10', 'C10'): 'C10'}),
                         'better_than_first_not_control')
        self.assertEqual(x.product_verdict('native', base), 'not_shown')
        self.assertEqual(x.product_verdict('native', {**base, ('N1', 'N10'): 'N1'}), 'worse')
        self.assertEqual(x.product_verdict('native', {**base, ('N1', 'N10'): 'N1', ('C1', 'C10'): 'C1'}),
                         'worse_but_control_too')
        self.assertEqual(x.product_verdict('ledger', None), 'pending')

    def test_scrub_removes_run_ids_and_dates(self):
        text, n = x.scrub('# 研究報告 run abc123\n讀取於 2026/10/17 與 10/17，run abc123', {'abc123'},
                          {'2026/10/17', '10/17'})
        self.assertEqual(text, '# 研究報告\n讀取於 [日期已移除] 與 [日期已移除]，run [已移除]')
        self.assertEqual(n, 3)
        self.assertIn('2026-10-17', x.run_dates(dict(started='2026-10-16T19:21:13+00:00')))  # Taiwan date too


if __name__ == '__main__':
    unittest.main()
