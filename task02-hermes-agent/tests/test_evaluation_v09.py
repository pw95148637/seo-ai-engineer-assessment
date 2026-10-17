import contextlib, importlib.util, io, json, shutil, tempfile, unittest, uuid
from datetime import datetime, timezone
from pathlib import Path
from src.research_core import Research, Limits, learn_run
from src.lessons import Ledger
from src.runner_support import HERMES_MODES
from src import hermes_homes as hh
from tests.test_research_memory import Transport, B, KW, MAIN, BRAND, TAIL, OTHER
from tests.test_lessons import Transport as V08Transport, MAIN as V08MAIN

TASK = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('evaluate_v09', TASK / 'scripts' / 'evaluate_v09.py')
v9 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v9)
ev = v9.ev


def parse(cmd):
    out, i = {}, 0
    while i < len(cmd):
        if cmd[i].startswith('--'):
            if i + 1 < len(cmd) and not cmd[i + 1].startswith('--'):
                out[cmd[i][2:]] = cmd[i + 1]
                i += 2
            else:
                out[cmd[i][2:]] = True
                i += 1
        else:
            i += 1
    return out


class Runner:
    """Stands in for run_research.sh: a real controller run on the fixture site. A run with research memory reads the
    first unread candidate it is shown, so the ledger arm explores further than the control arm."""
    def __init__(self, crashes=0):
        self.crashes, self.seen = crashes, {}

    def __call__(self, cmd, cwd, env, timeout):
        a = parse(cmd)
        root, home = Path(a['root']), Path(a['hermes-home'])
        root.mkdir(parents=True, exist_ok=True)
        rid = uuid.uuid4().hex
        memory = 'research-memory' in a
        r = Research(root, target=B, limits=Limits(interval=0), transport=Transport(), resolve=lambda h: ['8.8.8.8'],
                     keywords=KW, mode='memory', learn='no-learn' not in a, run_id=rid, memory=memory)
        status = r.call('research_status', {})
        self.seen[home.name] = status.get('research_memory')
        msgs = [dict(role='tool', tool_name='research_status', content=json.dumps(status, ensure_ascii=False))]
        cited = [r.call('research_fetch', {'url': u, 'purpose': 'p'})['evidence_id'] for u in (B + '/hub/', MAIN)]
        mem = status.get('research_memory') or {}
        for c in mem.get('unread_candidates', [])[:1]:
            cited.append(r.call('research_fetch', {'url': c['url'], 'purpose': 'unread'})['evidence_id'])
        msgs.append(dict(role='tool', tool_name='research_fetch', content=json.dumps({'evidence_id': cited[1]})))
        claims = [{'kind': 'observation', 'section': 'on_page', 'text': f'page {i}', 'evidence_ids': [e]}
                  for i, e in enumerate(cited)]
        claims.append({'kind': 'unknown', 'section': 'off_page', 'text': 'backlinks unknown'})
        resolved = [u['id'] for u in mem.get('open_unknowns', [])[:1]]
        r.call('research_finish', {'report': {'claims': claims, 'actions': [{'action': 'a', 'reason': 'b'}],
                                              'resolved_unknowns': resolved}})
        if 'no-learn' not in a:
            learn_run(r.db, root, rid, memory=memory)
        r.db.close()
        if self.crashes:
            self.crashes -= 1
            return '', 'crashed', 3
        (root / f'{rid}-usage.json').write_text(json.dumps(dict(
            session_prompt_tokens=1000, session_completion_tokens=100, session_total_tokens=1100,
            session_cache_read_tokens=500, session_cache_write_tokens=0, session_api_calls=5)))
        (root / f'{rid}-hermes.json').write_text(json.dumps(dict(messages=msgs), ensure_ascii=False), encoding='utf-8')
        (root / f'{rid}-surface.json').write_text(json.dumps(dict(
            hermes_home=str(home), hermes_learning='off', valid_tool_names=sorted(HERMES_MODES['off']['tools']),
            memory_block=False, user_block=False, skills_index=False)))
        return json.dumps(dict(run_id=rid, state='research_complete', exit_code=0)) + '\n', '', 0


class V09Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.task = Path(self.tmp.name)
        for f in v9.FINGERPRINT:
            (self.task / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(TASK / f, self.task / f)
        for d in ('memories', 'skills'):
            (self.task / hh.ROOT_HOME / d).mkdir(parents=True)
        r = Research(self.task / ev.REVIEW_SOURCE, target='https://research.example', limits=Limits(interval=0),
                     transport=V08Transport(), resolve=lambda h: ['8.8.8.8'], keywords=KW, mode='memory')
        eid = r.call('research_fetch', {'url': V08MAIN, 'purpose': 'fixture'})['evidence_id']
        r.call('research_finish', {'report': {'claims': [{'kind': 'observation', 'text': '作者是編輯部',
                                                          'evidence_ids': [eid]}], 'actions': [{'action': 'a', 'reason': 'b'}]}})
        Ledger(r.db).add_feedback(r.id, 'claim:1', 'unsupported', '團隊署名不是具名作者', '審查者甲', scope='general')
        r.db.close()
        v9.make_plan(self.task, 'test-model', draft=True)
        self.digest = v9.make_plan(self.task, 'test-model')

    def run_all(self, runner, session=5.0):
        with contextlib.redirect_stdout(io.StringIO()):
            return v9.run_all(self.task, usage=lambda t: dict(session=session, weekly=20.0, usage={}), runner=runner,
                              link_plugin=False, check_commit=False)

    def test_plan_order_and_registration(self):
        plan = v9.verify_plan(self.task)
        self.assertEqual(plan['order'][:3], ['C1', 'L1', 'LF'])
        self.assertEqual(plan['order'][-2:], ['C10', 'L10'])
        self.assertEqual(sum(o[0] == 'C' for o in v9.ROUND_ORDER), 5)
        with self.assertRaisesRegex(SystemExit, 'never rewritten'):
            v9.make_plan(self.task, 'test-model')
        code = self.task / 'src' / 'research_memory.py'
        code.write_bytes(code.read_bytes() + b'# changed\n')
        with self.assertRaisesRegex(SystemExit, 'code changed'):
            v9.verify_plan(self.task)

    def test_usage_gate(self):
        with self.assertRaisesRegex(SystemExit, 'at or above 90%'):
            self.run_all(Runner(), session=90.0)

    def test_full_sequence_metrics_and_pairwise(self):
        runner = Runner(crashes=1)
        self.assertEqual(self.run_all(runner), v9.ORDER)
        log = v9.load_log(self.task)
        self.assertEqual(v9.status(self.task)['failed_attempts'], ['C1#1:no_summary'])
        done = v9.settled(log)
        self.assertTrue(all(not x.get('isolation') for x in done.values()))
        self.assertIsNone(runner.seen['v09-l1-a1'])  # nothing kept before the first ledger run
        self.assertTrue(runner.seen['v09-l2-a1']['findings'])
        self.assertTrue(all(runner.seen[f'v09-c{k}-a1'] is None for k in range(2, 11)))
        v9.score_all(self.task)
        rows = v9.rows_of(self.task)
        self.assertGreater(rows['L10']['cumulative_onsite'], rows['C10']['cumulative_onsite'])
        self.assertEqual(rows['C10']['cumulative_onsite'], 2)
        self.assertEqual(rows['L2']['resolved_unknowns'], ['u1'])
        self.assertEqual(rows['L2']['candidates_read'], 1)
        v = v9.compare(self.task)
        self.assertEqual(v['judgment']['verdict'], 'pending_blind_review')
        self.assertEqual(v['judgment']['exploration']['verdict'], 'broader')
        log = v9.load_log(self.task)  # pretend C9 ended without a report: the packet shows C8 in its place
        next(x for x in log if x['step'] == 'C9' and x.get('settled'))['state'] = 'no_autonomous_tool_use'
        v9.save_log(self.task, log)
        v9.pairwise_packet(self.task, 'C:/tmp/pw09/', seed=3)
        packet = self.task / v9.OUT / 'pairwise'
        self.assertEqual(len(list((packet / 'reports').iterdir())), 6)
        self.assertIn('C:/tmp/pw09/', (packet / 'INSTRUCTIONS-R1.md').read_text(encoding='utf-8'))
        key = json.loads((self.task / v9.OUT / 'pairwise-key.json').read_text(encoding='utf-8'))
        for r in v9.REVIEWERS:
            rows_ = key['assignments'][r]
            pairs = {}
            for p in rows_:
                pair = next(q for q in v9.PAIRS if set(q) == {p['A'], p['B']})
                want = {('L1', 'L10'): 'L10', ('L10', 'C10'): 'L10', ('L9', 'C9'): 'L9'}.get(pair, 'equal')
                pairs[p['pair']] = dict(preferred='equal' if want == 'equal' else 'A' if p['A'] == want else 'B',
                                        strength='slight', reasons='fixture')
            (packet / 'answers' / f'{r}.json').write_text(json.dumps(dict(reviewer=r, reports={}, pairs=pairs)),
                                                          encoding='utf-8')
        v = v9.compare(self.task)
        self.assertEqual(v['judgment']['product'], 'better')
        self.assertEqual(v['judgment']['verdict'], 'improved')
        self.assertEqual(v['judgment']['first_vs_tenth_without_learning'], 'no_majority')
        rspec = importlib.util.spec_from_file_location('render_v09', TASK / 'scripts' / 'render_v09.py')
        render = importlib.util.module_from_spec(rspec)
        rspec.loader.exec_module(render)
        tables = render.render(json.loads((self.task / v9.OUT / 'verdict.json').read_text(encoding='utf-8')))
        self.assertIn('| 10 |', tables)
        self.assertIn('| L9-C9 |', tables)
        self.assertEqual((key['shown_runs']['C1'], key['shown_runs']['C9']), ('C1', 'C8'))  # C9 had no report

    def test_product_rules(self):
        base = {('L1', 'L10'): 'L10', ('L10', 'C10'): 'L10', ('L9', 'C9'): 'L9', ('C1', 'C10'): 'C10'}
        self.assertEqual(v9.product_verdict(base), 'better')
        self.assertEqual(v9.product_verdict({**base, ('L9', 'C9'): 'no_majority'}), 'better_than_first_unattributed')
        self.assertEqual(v9.product_verdict({**base, ('L1', 'L10'): 'L1'}), 'better_than_control_only')
        self.assertEqual(v9.product_verdict({**base, ('L1', 'L10'): 'L1', ('L10', 'C10'): 'C10', ('L9', 'C9'): 'C9'}),
                         'worse_than_control')
        self.assertEqual(v9.product_verdict({**base, ('L1', 'L10'): 'no_majority', ('L9', 'C9'): 'C9'}), 'not_shown')
        self.assertEqual(v9.product_verdict(None), 'pending')


if __name__ == '__main__':
    unittest.main()
