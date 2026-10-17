import contextlib, importlib.util, io, json, shutil, sqlite3, tempfile, unittest, uuid
from datetime import datetime, timezone
from pathlib import Path
from src.research_core import Research, Limits, learn_run
from src.lessons import Ledger
from src.runner_support import HERMES_MODES
from src import hermes_homes as hh
from tests.test_lessons import B, BRAND, KW, MAIN, Transport

TASK = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('evaluate_v08', TASK / 'scripts' / 'evaluate_v08.py')
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)
MORNING = datetime(2026, 10, 17, 1, 0, tzinfo=timezone.utc)  # 09:00 Taiwan
REFUSED = "Tool 'skill_view' does not exist. Available tools: research_evidence, research_fetch"


def usage_at(session):
    return lambda task: dict(session=session, weekly=20.0, usage={'windows': []})


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


def label(a):
    """The step a command belongs to: from the per-attempt root, or from the home name of a ledger run."""
    root, home = Path(a['root']), Path(a['hermes-home']).name
    if root.name.startswith('a') and root.parent.name in ev.STEPS:
        return root.parent.name
    return home.split('-')[1].upper()  # v08-l3-a1 -> L3


class FakeRunner:
    """Stands in for run_research.sh: a real controller run on the fixture site, plus what Hermes would write.

    In a native session the agent writes one memory entry ('agent k'), the runner copies the store, then the review
    writes another entry ('note k') and a skill."""
    def __init__(self, task, prompt_tokens=None, crashes=0, review_ok=True, leak_to=None, write_frozen=False,
                 touch_ledger=False, seed_lesson=False, hermes_call=False, refused_call=False):
        self.task, self.crashes, self.review_ok, self.leak_to = task, crashes, review_ok, leak_to
        self.write_frozen, self.touch_ledger, self.seed_lesson = write_frozen, touch_ledger, seed_lesson
        self.hermes_call, self.refused_call = hermes_call, refused_call
        self.prompt_tokens = prompt_tokens or {}
        self.seen_memory, self.memory_at, self.seen_lessons, self.calls = [], {}, {}, 0

    def __call__(self, cmd, cwd, env, timeout):
        self.calls += 1
        a = parse(cmd)
        root, home = Path(a['root']), Path(a['hermes-home'])
        mode = 'feedback' if 'feedback-file' in a else a['hermes-learning']
        mem = home / 'memories' / 'MEMORY.md'
        self.seen_memory.append(mem.read_text(encoding='utf-8') if mem.exists() else '')
        self.memory_at[label(a)] = self.seen_memory[-1]
        root.mkdir(parents=True, exist_ok=True)
        rid = uuid.uuid4().hex
        if mode in ('learn', 'feedback'):
            entries = [e for e in self.seen_memory[-1].split(hh.ENTRY_DELIMITER) if e]
            entries.append(f'agent {len(entries) + 1}')
            mem.write_text(hh.ENTRY_DELIMITER.join(entries), encoding='utf-8')
            hh.snapshot(home, root / f'{rid}-pre-review')
            entries.append(f'note {len(entries) + 1}')
            mem.write_text(hh.ENTRY_DELIMITER.join(entries), encoding='utf-8')
            (home / 'skills' / 'seo-research').mkdir(exist_ok=True)
            (home / 'skills' / 'seo-research' / 'SKILL.md').write_text(
                '---\nname: seo-research\ndescription: Research a competitor site.\n---\n1. Read the hub page first.\n',
                encoding='utf-8')
        if self.leak_to:
            (self.task / hh.PROFILES / self.leak_to / 'memories' / 'MEMORY.md').write_text('leak', encoding='utf-8')
        if self.write_frozen and mode == 'frozen':
            mem.write_text('rewritten', encoding='utf-8')
        if self.touch_ledger:
            db = sqlite3.connect(self.task / ev.LEDGER_ROOT / 'research.sqlite')
            db.execute('UPDATE lessons SET statement=statement||"x"')
            db.commit()
            db.close()
        messages, state = [], 'feedback_complete'
        if mode != 'feedback':
            learn = 'no-learn' not in a
            r = Research(root, target=B, limits=Limits(interval=0), transport=Transport(), resolve=lambda h: ['8.8.8.8'],
                         keywords=KW, mode='memory', learn=learn, run_id=rid)
            if self.seed_lesson:
                r.ledger._create('failure_pattern', 'failure|research_search|site_operator', 'research.example', 'host',
                                 'active', 'controller', rid, 'seeded', 'x', dict(tool='research_search',
                                 feature='site_operator', fails=2, alternative=[0, 0], hosts=['research.example']),
                                 '2099-01-01T00:00:00+00:00')
            status = r.call('research_status', {})
            self.seen_lessons[label(a)] = [x['key'] for x in status['lessons']]
            messages.append(dict(role='tool', tool_name='research_status', content=json.dumps(status, ensure_ascii=False)))
            if self.hermes_call or mode in ('learn', 'frozen'):
                messages.append(dict(role='tool', tool_name='skills_list', content='{"skills": []}'))
            if self.refused_call:
                messages.append(dict(role='tool', tool_name='skill_view', content=REFUSED))
            x = r.call('research_fetch', {'url': MAIN, 'purpose': 'target page'})
            messages.append(dict(role='tool', tool_name='research_fetch', content=json.dumps(x, ensure_ascii=False)))
            r.call('research_fetch', {'url': BRAND, 'purpose': 'target page'})
            r.call('research_finish', {'report': {'claims': [
                {'kind': 'observation', 'text': 'title', 'section': 'on_page', 'evidence_ids': [x['evidence_id']]},
                {'kind': 'unknown', 'text': 'backlinks', 'section': 'off_page'}],
                'actions': [{'action': 'audit our page', 'reason': 'title'}]}})
            if learn:
                learn_run(r.db, root, rid)
            r.db.close()
            state = 'research_complete'
        if self.crashes:
            self.crashes -= 1
            return '', 'crashed', 3
        prompt = self.prompt_tokens.get(label(a), 1000)
        (root / f'{rid}-usage.json').write_text(json.dumps(dict(
            session_prompt_tokens=prompt, session_completion_tokens=100, session_total_tokens=prompt + 100,
            session_cache_read_tokens=prompt // 2, session_cache_write_tokens=0, session_api_calls=5)))
        (root / f'{rid}-hermes.json').write_text(json.dumps(dict(messages=messages), ensure_ascii=False), encoding='utf-8')
        has_store = mode != 'off'
        (root / f'{rid}-surface.json').write_text(json.dumps(dict(
            hermes_home=str(home), hermes_learning=mode, valid_tool_names=sorted(HERMES_MODES[mode]['tools']),
            memory_block=has_store and bool(hh.memory_items(home)), user_block=False,
            skills_index=has_store and any((home / 'skills').rglob('SKILL.md')))))
        if mode in ('learn', 'feedback'):
            (root / f'{rid}-review.json').write_text(json.dumps(dict(
                triggered=True, completed=self.review_ok, timed_out=not self.review_ok, result='skill+memory',
                actions=[], warnings=[], usage=dict(api_calls=3, input=900, output=200, cache_read=4000))))
        return json.dumps(dict(run_id=rid, state=state, exit_code=0)) + '\n', '', 0


class V08Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.task = Path(self.tmp.name)
        self.now = MORNING
        saved = ev.clock
        ev.clock = lambda: self.now
        self.addCleanup(setattr, ev, 'clock', saved)
        for f in ev.FINGERPRINT:
            (self.task / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(TASK / f, self.task / f)
        for d in ('memories', 'skills'):
            (self.task / hh.ROOT_HOME / d).mkdir(parents=True)
        r = Research(self.task / ev.REVIEW_SOURCE, target=B, limits=Limits(interval=0), transport=Transport(),
                     resolve=lambda h: ['8.8.8.8'], keywords=KW, mode='memory')
        eid = r.call('research_fetch', {'url': MAIN, 'purpose': 'fixture'})['evidence_id']
        r.call('research_finish', {'report': {'claims': [{'kind': 'observation', 'text': '作者是編輯部，頁面有作者資訊',
                                                          'evidence_ids': [eid]}], 'actions': [{'action': 'a', 'reason': 'b'}]}})
        Ledger(r.db).add_feedback(r.id, 'claim:1', 'unsupported', '團隊署名不是具名作者', '審查者甲', scope='general')
        r.db.close()
        (self.task / ev.V07_PLAN).write_text(json.dumps({'holdout': {'primary': 'casinobase.tw',
                                                                     'fallback': 'goldbobet.com'}}), encoding='utf-8')
        (self.task / ev.V07_PLAN).with_suffix('.sha256').write_text('v07\n')
        ev.make_plan(self.task, 'test-model', draft=True)
        self.digest = ev.make_plan(self.task, 'test-model')

    def step(self, name, runner=None, session=5.0):
        with contextlib.redirect_stdout(io.StringIO()):
            return ev.run_step(self.task, name, usage=usage_at(session), runner=runner or FakeRunner(self.task),
                               link_plugin=False, check_commit=False,
                               probe=lambda h: dict(host=h, homepage_status=200, ok=True))

    def run_until(self, last, runner=None):
        for s in ev.ORDER[:ev.ORDER.index(last) + 1]:
            if s not in ev.passed(ev.load_log(self.task)):
                self.assertTrue(self.step(s, runner)['settled'], s)

    def score(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return ev.score_all(self.task, seed=1)

    def compare(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return ev.compare(self.task)

    def blind_answers(self, defects=0):
        order = json.loads((self.task / ev.OUT / 'blind' / 'order.json').read_text(encoding='utf-8'))['order']
        return {b: dict(unsupported=defects, scope_error=0, off_page_supported_known=0,
                        coverage=dict(on_page=1, off_page=0, actionable=1, epistemic=1), notes='') for b in order}


class EvaluationV08Tests(V08Fixture):
    def test_draft_registration_and_verify(self):
        plan = ev.verify_plan(self.task)
        self.assertEqual(plan['status'], 'registered before any v0.8 model run')
        self.assertIn('團隊署名不是具名作者', plan['feedback']['message'])
        self.assertIn('寫研究主張時套用', plan['feedback']['message'])  # the same instruction FEEDBACK_PREFIX gives
        self.assertEqual(plan['order'][:5], ['C1', 'L1', 'N1', 'LF', 'NF'])
        self.assertEqual(plan['round_order'][4], plan['round_order'][0])
        self.assertEqual(plan['order'][-3:], ['HN', 'HC', 'HL'])
        with self.assertRaises(SystemExit):
            ev.make_plan(self.task, 'test-model')
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, True)
        shutil.copytree(self.task, other, dirs_exist_ok=True)
        (other / ev.PLAN).with_suffix('.sha256').unlink()
        ev.make_plan(other, 'test-model', draft=True)
        with self.assertRaisesRegex(SystemExit, 'draft'):
            ev.verify_plan(other)
        code = other / 'src' / 'scoring.py'
        code.write_bytes(code.read_bytes() + b'# changed\n')
        self.assertEqual(ev.check_draft(other, 'test-model'), ['code_fingerprint'])
        with self.assertRaisesRegex(SystemExit, 'differs from the reviewed draft in code_fingerprint'):
            ev.make_plan(other, 'test-model')
        path = self.task / ev.PLAN
        path.write_text(path.read_text(encoding='utf-8').replace('"F6"', '"F6x"'), encoding='utf-8')
        with self.assertRaisesRegex(SystemExit, 'plan hash'):
            ev.verify_plan(self.task)

    def test_usage_gates(self):
        with self.assertRaisesRegex(SystemExit, 'at most 10%'):
            self.step('C1', session=11.0)
        self.assertEqual(ev.load_log(self.task), [])
        self.assertTrue(self.step('C1', session=10.0)['settled'])
        self.assertTrue(self.step('L1', session=84.0)['settled'])  # after the first model step only 85% stops a run
        with self.assertRaisesRegex(SystemExit, 'below 85%'):
            self.step('N1', session=85.0)

    def test_full_sequence_scores_only_after_the_last_step(self):
        runner = FakeRunner(self.task, prompt_tokens={'N4': 600, 'N5': 600, 'L4': 400, 'L5': 400})
        self.run_until('LZ', runner)  # LZ runs HP3 in the same call
        self.assertEqual(ev.settled(ev.load_log(self.task))['HP3']['state'], 'chosen')
        self.run_until('HL', runner)
        self.assertFalse((self.task / ev.OUT / 'scores').exists())
        done = ev.settled(ev.load_log(self.task))
        self.assertTrue(all(not x.get('isolation') for x in done.values()))
        self.assertEqual(done['NZ']['memory_entries'], 12)  # six sessions, each an agent entry and a review entry
        self.assertEqual(runner.memory_at['NF'], 'agent 1' + hh.ENTRY_DELIMITER + 'note 2')
        self.assertEqual(runner.memory_at['C5'], '')
        self.assertEqual(runner.seen_lessons['L1'], [])
        self.assertEqual(len(runner.seen_lessons['L2']), 3)  # two discovery paths from L1 and the review from LF
        frozen = json.loads((self.task / ev.NATIVE_FROZEN / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(hh.learned_files(hh.home_path(self.task, done['HN']['home'])), frozen)
        result = self.score()
        self.assertEqual((result['blind'], result['formal_result'], result['not_run']), (9, 'v0.8', []))
        with self.assertRaisesRegex(SystemExit, 'written once'):
            self.score()
        packet = ev.learned_packet(self.task, seed=3)
        self.assertEqual(packet['per_arm'], dict(native=14, ledger=3))  # 12 entries + front matter + 1 step; 3 lessons
        items = json.loads((self.task / ev.OUT / 'learned' / 'items.json').read_text(encoding='utf-8'))['items']
        key = json.loads((self.task / ev.OUT / 'learned-key.json').read_text(encoding='utf-8'))
        native = [i for i in items if i['group'] == key['native']]
        self.assertEqual({i['first_held_after'] for i in native if i['text'] == 'agent 3'}, {'NF'})
        self.assertTrue(all(i['transcript'].endswith('-hermes.json') for i in native))
        self.assertTrue(all('data' in i and 'support' in i for i in items if i['group'] == key['ledger']))
        self.assertNotIn('Hermes', json.dumps(json.loads((self.task / ev.OUT / 'learned' / 'items.json')
                                                         .read_text(encoding='utf-8'))['groups']))
        answers = {i['item_id']: dict(type='research_method', correctness='supported', from_web_text=False,
                                      instruction_from_web=False, notes='') for i in items}
        answers[native[0]['item_id']].update(from_web_text=True, instruction_from_web=True)
        (self.task / ev.OUT / 'learned-review.json').write_text(json.dumps(answers), encoding='utf-8')
        (self.task / ev.OUT / 'blind-review.json').write_text(json.dumps(self.blind_answers()), encoding='utf-8')
        self.now = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)  # 23:00 Taiwan: past every deadline
        v = self.compare()
        self.assertEqual(v['formal_result'], 'v0.8')  # fixed at --score; a late --compare does not change it
        self.assertEqual(v['ledger_learning']['verdict'], 'improved')
        self.assertEqual(v['ledger_learning']['dimensions']['self']['cost'], 'better')
        self.assertNotIn('cost_learning', v['native_learning']['dimensions']['control'])
        self.assertEqual(v['native_learning']['dimensions']['self']['cost'], 'better')
        self.assertEqual(v['native_learning']['dimensions']['control']['calls'], 'worse')  # skills_list before the page
        self.assertEqual(v['native_learning']['verdict'], 'not_proven')
        self.assertEqual(v['native_learning_sessions'], dict(learned=6, sessions=6, operating=True))
        self.assertEqual(v['learned']['native']['verdict'], 'contaminated')
        self.assertEqual(v['native_vs_ledger']['verdict'], 'ledger_better')
        self.assertEqual([r['cost'] for r in v['series']['native']], [600, 600, 600, 400, 400])
        self.assertEqual([r['cost_learning'] for r in v['series']['native']], [1700, 1700, 1700, 1500, 1500])
        self.assertEqual(v['series']['native'][0]['calls'], 2)
        self.assertEqual((v['encoding_errors'], v['abandoned'], v['skipped'], v['not_run']), (0, [], [], []))

    def test_research_and_review_settle_separately(self):
        self.run_until('NF')
        home = hh.home_path(self.task, ev.NATIVE_HOME)
        before = [e for e in (home / 'memories' / 'MEMORY.md').read_text(encoding='utf-8').split(hh.ENTRY_DELIMITER)]
        self.assertTrue(self.step('L2')['settled'])
        runner = FakeRunner(self.task, review_ok=False)
        entry = self.step('N2', runner)
        self.assertEqual((entry['settled'], entry['learned'], entry['attempt'], runner.calls), (True, False, 1, 1))
        kept = (home / 'memories' / 'MEMORY.md').read_text(encoding='utf-8').split(hh.ENTRY_DELIMITER)
        self.assertEqual(kept, before + ['agent 5'])  # the agent's own entry stays, the review's entry is dropped
        self.assertTrue(entry['kept_snapshot'].endswith('-pre-review'))
        self.assertTrue(self.step('C2')['settled'])
        self.assertEqual(self.step('N3')['learned'], True)  # the chain goes on from what N2 kept

    def test_a_failed_attempt_is_undone_and_retried_once_in_the_same_call(self):
        self.run_until('NF')
        runner = FakeRunner(self.task, crashes=1)
        entry = self.step('L2', runner)
        self.assertEqual((entry['settled'], entry['attempt'], runner.calls), (True, 2, 2))
        log = ev.load_log(self.task)
        self.assertTrue([x for x in log if x['step'] == 'L2'][0]['undone'])
        self.assertEqual(ev.ledger_sha(self.task), ev.ledger_expected(log))
        runner = FakeRunner(self.task, crashes=1)
        self.assertEqual(self.step('N2', runner)['attempt'], 2)
        self.assertEqual(runner.seen_memory[0], runner.seen_memory[1])  # restored before the retry
        with self.assertRaisesRegex(SystemExit, 'already settled'):
            self.step('N2')

    def test_a_step_that_fails_twice_is_abandoned_and_the_order_continues(self):
        self.run_until('N2')
        self.assertFalse(self.step('C2', FakeRunner(self.task, crashes=2))['settled'])
        with self.assertRaisesRegex(SystemExit, 'abandoned'):
            self.step('C2')
        self.assertTrue(self.step('N3')['settled'])
        self.assertEqual(ev.status(self.task)['abandoned'], ['C2'])

    def test_after_the_round_deadline_steps_stop_and_scoring_records_what_did_not_run(self):
        self.run_until('N3')
        self.now = datetime(2026, 10, 17, 10, 1, tzinfo=timezone.utc)  # 18:01 Taiwan
        with self.assertRaisesRegex(SystemExit, 'v0.7 stays the formal result'):
            self.step('C3')
        result = self.score()
        self.assertEqual(result['formal_result'], 'v0.7')
        self.assertIn('C5', result['not_run'])
        (self.task / ev.OUT / 'blind-review.json').write_text(json.dumps(self.blind_answers()), encoding='utf-8')
        v = self.compare()
        self.assertEqual((v['formal_result'], v['native_learning']['verdict']), ('v0.7', 'incomplete'))
        self.assertEqual(v['series']['native'][2]['cost'], 600)  # what ran is still scored

    def test_a_started_holdout_is_waited_for_until_the_scoring_deadline(self):
        self.run_until('HN')
        self.now = datetime(2026, 10, 17, 10, 40, tzinfo=timezone.utc)  # 18:40 Taiwan
        with self.assertRaisesRegex(SystemExit, 'scoring waits for HC, HL'):
            self.score()
        self.now = datetime(2026, 10, 17, 14, 1, tzinfo=timezone.utc)  # 22:01 Taiwan
        result = self.score()
        self.assertEqual((result['not_run'], result['formal_result']), (['HC', 'HL'], 'v0.7'))

    def test_scoring_waits_for_every_step_before_the_deadline(self):
        self.run_until('C1')
        with self.assertRaisesRegex(SystemExit, 'scoring waits'):
            self.score()

    def test_holdout_is_skipped_by_rule_and_caps_the_verdict(self):
        self.run_until('NZ', FakeRunner(self.task, prompt_tokens={'L4': 400, 'L5': 400}))
        self.now = datetime(2026, 10, 17, 10, 31, tzinfo=timezone.utc)  # 18:31 Taiwan
        self.step('LZ')
        self.assertEqual(ev.settled(ev.load_log(self.task))['HP3']['state'], 'skipped_by_rule')
        for s in ('HN', 'HC', 'HL'):
            self.assertEqual(self.step(s)['state'], 'skipped_by_rule')
        self.score()
        ev.learned_packet(self.task, seed=1)
        (self.task / ev.OUT / 'blind-review.json').write_text(json.dumps(self.blind_answers()), encoding='utf-8')
        v = self.compare()
        self.assertEqual((v['holdout_state'], v['ledger_learning']['verdict']), ('skipped', 'improved_primary_only'))

    def test_holdout_start_condition_checks_usage(self):
        self.run_until('NZ')
        self.step('LZ', session=79.0)
        hp3 = ev.settled(ev.load_log(self.task))['HP3']
        self.assertEqual((hp3['state'], hp3['reason']['session']), ('skipped_by_rule', 79.0))

    def test_isolation_checks(self):
        self.run_until('L2')
        entry = self.step('N2', FakeRunner(self.task, touch_ledger=True))
        self.assertEqual(entry['state'], 'isolation_violation')
        self.assertIn('the ledger changed during N2', entry['isolation'])
        entry = self.step('C2', FakeRunner(self.task, seed_lesson=True, hermes_call=True))
        self.assertTrue(any('controller lesson' in p for p in entry['isolation']))
        self.assertTrue(any('skill tools ran' in p for p in entry['isolation']))
        entry = self.step('N3', FakeRunner(self.task, leak_to='v08-c2-a1'))
        self.assertIn('home v08-c2-a1 changed', entry['isolation'][0])

    def test_a_refused_tool_name_is_recorded_not_an_isolation_failure(self):
        self.run_until('C1')
        entry = self.step('L1', FakeRunner(self.task, refused_call=True))
        self.assertEqual((entry['state'], entry['isolation'], entry['other_tools']),
                         ('research_complete', [], ['skill_view']))

    def test_frozen_native_store_cannot_change_on_the_holdout(self):
        self.run_until('HP3')
        entry = self.step('HN', FakeRunner(self.task, write_frozen=True))
        self.assertEqual(entry['state'], 'isolation_violation')
        self.assertIn('frozen', ' '.join(entry['isolation']))

    def test_stores_and_roots_must_be_as_expected(self):
        self.run_until('LF')
        (hh.home_path(self.task, ev.NATIVE_HOME) / 'memories' / 'MEMORY.md').write_text('edited by hand')
        with self.assertRaisesRegex(SystemExit, 'changed between steps'):
            self.step('NF')
        (self.task / ev.OUT / 'runs' / 'C2' / 'a1').mkdir(parents=True)
        (self.task / ev.OUT / 'runs' / 'C2' / 'a1' / 'stray.txt').write_text('x')
        with self.assertRaisesRegex(SystemExit, 'not empty'):
            ev.prepare(self.task, ev.verify_plan(self.task), 'C2', 1, ev.load_log(self.task), link_plugin=False)

    def test_program_errors_keep_their_traceback(self):
        def broken(*a):
            raise RuntimeError('boom')
        with self.assertRaises(RuntimeError):
            self.step('C1', broken)
        errors = list((self.task / ev.OUT / 'errors').glob('C1-*.txt'))
        self.assertEqual(len(errors), 1)
        self.assertIn('RuntimeError: boom', errors[0].read_text(encoding='utf-8'))

    def test_missing_measurements_stay_unknown(self):
        self.assertIsNone(ev.transcript_calls(self.task, 'absent', {}))
        self.assertIsNone(ev.run_metrics(dict(state='research_complete', target_pages={}, tokens=dict(cost=10),
                                              review_cost=None, transcript_calls=None), {})['cost_learning'])


def metrics(cost=1000, pages=2, calls=3, defects=0, coverage=6, report=True, review_cost=0):
    return dict(report=report, pages=pages, calls=calls, cost=cost,
                cost_learning=None if review_cost is None else cost + review_cost, defects=defects, coverage=coverage,
                target_pages={k: ({'call': calls} if i < pages else None) for i, k in enumerate(KW)})


class JudgeV08Tests(unittest.TestCase):
    """Controls C1-C5 cost 950-1050 and need 3-5 calls; the quality width is the floor of 2 unless C1 and C5 differ."""
    def judge(self, runs=None, invalid=(), violations=None, stale=None, learned=None, holdout='run', sessions=(6, 6)):
        m = {}
        for k, (cost, calls) in enumerate(((1000, 3), (950, 4), (1050, 5), (1000, 4), (1000, 3)), 1):
            m[ev.step_of('control', k)] = metrics(cost=cost, calls=calls)
        for arm in ('ledger', 'native'):
            for k in (1, 4, 5):
                m[ev.step_of(arm, k)] = metrics()
        for arm in ('control', 'ledger', 'native'):
            m[ev.step_of(arm, 'holdout')] = metrics(pages=0, calls=10)
        m.update(runs or {})
        clean = dict(items=3, classifiable=3, errors=0, error_share=0.0, contamination=0)
        return ev.judge(m, set(invalid), violations or {}, stale or {},
                        learned if learned is not None else dict(native=clean, ledger=clean), holdout, sessions)

    def test_self_rule_does_not_depend_on_where_run_one_landed(self):
        band = (950, 1050)
        self.assertEqual(ev.pairwise('cost', 899, 1000), 'better')
        self.assertEqual(ev.pairwise('cost', 950, 1000), 'equal')
        self.assertEqual(ev.pairwise('calls', 2, 4), 'better')
        self.assertEqual(ev.pairwise('calls', 2, 3), 'equal')
        self.assertEqual(ev.self_change('cost', 800, 1000, band, False), 'better')
        self.assertEqual(ev.self_change('cost', 800, 1000, band, False, [1000]), 'equal')  # X4 inside the band
        self.assertEqual(ev.self_change('cost', 930, 1000, band, False), 'equal')  # outside the band, below 10%
        self.assertEqual(ev.self_change('cost', 1200, 1000, band, False), 'worse')
        self.assertEqual(ev.self_change('calls', None, 4, (3, 5), False), 'not_measured')
        for x1 in (3, 4, 5):  # wherever run 1 sits inside the band, the same run 5 counts the same
            self.assertEqual(ev.self_change('calls', 1, x1, (3, 5), False), 'better')
        self.assertEqual(ev.quality(metrics(report=False), metrics()), 'worse')

    def test_improved_needs_the_threshold_and_run_five_beyond_the_controls(self):
        self.assertEqual(self.judge({'N5': metrics(cost=800), 'N4': metrics(cost=850)})['native_learning']['verdict'],
                         'improved')
        v = self.judge({'N5': metrics(cost=800), 'N4': metrics(cost=1000)})
        self.assertEqual(v['native_learning']['verdict'], 'not_proven')
        v = self.judge({'N5': metrics(cost=930), 'N4': metrics(cost=930)})
        self.assertEqual(v['native_learning']['verdict'], 'not_proven')
        v = self.judge({'L5': metrics(calls=1), 'L4': metrics(calls=1)})
        self.assertEqual(v['ledger_learning']['verdict'], 'improved')
        v = self.judge({'L5': metrics(calls=1), 'L4': metrics(calls=1)}, holdout='skipped')
        self.assertEqual(v['ledger_learning']['verdict'], 'improved_primary_only')

    def test_learning_verdicts_ignore_review_cost(self):
        v = self.judge({'N5': metrics(cost=800, review_cost=5000), 'N4': metrics(cost=850, review_cost=5000)})
        self.assertEqual(v['native_learning']['verdict'], 'improved')
        self.assertEqual(v['native_vs_ledger']['dimensions']['cost_learning'], 'worse')
        self.assertEqual(v['native_vs_ledger']['verdict'], 'mixed')
        v = self.judge({'N5': metrics(cost=800, review_cost=None)})
        self.assertEqual(v['native_vs_ledger']['dimensions']['cost_learning'], 'not_measured')
        self.assertEqual(v['native_vs_ledger']['verdict'], 'native_better')

    def test_quality(self):
        v = self.judge({'N5': metrics(cost=800, coverage=8), 'N4': metrics(cost=850)})
        self.assertEqual(v['native_learning']['dimensions']['control']['quality'], 'better')
        self.assertEqual(v['native_learning']['dimensions']['self']['quality'], 'equal')  # +2 is not above the floor
        v = self.judge({'N5': metrics(coverage=8), 'N1': metrics(defects=1, coverage=6)})
        self.assertEqual(v['native_learning']['dimensions']['self']['quality'], 'better')  # +3
        v = self.judge({'N5': metrics(cost=800, coverage=8), 'N4': metrics(cost=850), 'C5': metrics(coverage=8)})
        self.assertEqual(v['native_learning']['dimensions']['control']['quality'], 'equal')

    def test_failures_mean_regression(self):
        v = self.judge({'L5': metrics(cost=1400)})
        self.assertEqual((v['ledger_learning']['failure']['F2'], v['ledger_learning']['verdict']), (True, 'regression'))
        self.assertTrue(self.judge({'L5': metrics(pages=1)})['ledger_learning']['failure']['F1'])
        self.assertTrue(self.judge({'N5': metrics(defects=2)})['native_learning']['failure']['F3'])
        self.assertTrue(self.judge({'N5': metrics(report=False)})['native_learning']['failure']['F6'])
        v = self.judge({'HN': metrics(pages=0, calls=10, cost=1400), 'N5': metrics(cost=800), 'N4': metrics(cost=850)})
        self.assertEqual((v['native_learning']['failure']['H4'], v['native_learning']['verdict']), (True, 'regression'))
        self.assertTrue(self.judge({'HL': metrics(pages=0, calls=10, report=False)})['ledger_learning']['failure']['H3'])
        v = self.judge(violations={'native': [dict(url='x')]}, stale={'ledger': 1})
        self.assertEqual((v['native_learning']['verdict'], v['ledger_learning']['verdict']), ('regression', 'regression'))
        self.assertEqual(self.judge(invalid={'control'})['native_learning']['verdict'], 'invalid')

    def test_missing_data(self):
        self.assertEqual(self.judge({'N5': metrics(defects=None)})['native_learning']['verdict'], 'pending_blind_review')
        self.assertEqual(self.judge({'N1': None})['native_learning']['verdict'], 'incomplete')
        self.assertEqual(self.judge({'N1': None})['ledger_learning']['verdict'], 'not_proven')  # only that arm
        self.assertEqual(self.judge({'HN': None})['native_learning']['verdict'], 'incomplete')  # abandoned, not skipped
        self.assertEqual(self.judge(holdout='not_started')['native_learning']['verdict'], 'incomplete')
        self.assertEqual(self.judge({'C2': None, 'C3': None, 'C4': None})['native_learning']['verdict'], 'incomplete')
        v = self.judge({'N5': metrics(calls=None)})
        self.assertEqual(v['native_learning']['dimensions']['self']['calls'], 'not_measured')

    def test_native_learning_that_did_not_operate_is_named(self):
        runs = {'N5': metrics(cost=800), 'N4': metrics(cost=850)}
        v = self.judge(sessions=(2, 6))  # would be not_proven
        self.assertEqual(v['native_learning']['verdict'], 'learning_not_operating')
        self.assertEqual(v['native_learning']['learned_sessions'], dict(learned=2, sessions=6))
        self.assertEqual(v['native_learning_sessions'], dict(learned=2, sessions=6, operating=False))
        v = self.judge(runs, sessions=(2, 6))  # a real improvement stays improved, with the count beside it
        self.assertEqual((v['native_learning']['verdict'], v['native_learning']['learned_sessions']['learned']),
                         ('improved', 2))
        self.assertEqual(self.judge(sessions=(3, 6))['native_learning']['verdict'], 'not_proven')

    def test_native_against_ledger(self):
        self.assertEqual(self.judge({'N5': metrics(cost=800)})['native_vs_ledger']['verdict'], 'native_better')
        self.assertEqual(self.judge({'N5': metrics(cost=950)})['native_vs_ledger']['verdict'], 'equal')
        v = self.judge({'HN': metrics(pages=0, calls=10, cost=1400)})
        self.assertEqual(v['native_vs_ledger']['dimensions']['holdout_harm'], 'worse')
        self.assertEqual(self.judge(learned={})['native_vs_ledger']['verdict'], 'pending_review')
        self.assertEqual(ev.learned_verdict(dict(items=0, contamination=0, errors=0)), 'empty')

    def test_learned_error_share_needs_a_gap_and_two_errors(self):
        ledger = dict(items=10, classifiable=10, errors=0, error_share=0.0, contamination=0)
        one = dict(items=5, classifiable=5, errors=1, error_share=0.2, contamination=0)
        two = dict(items=10, classifiable=10, errors=2, error_share=0.2, contamination=0)
        close = dict(items=40, classifiable=40, errors=2, error_share=0.05, contamination=0)
        self.assertEqual(ev.error_share_compare(one, ledger), 'equal')
        self.assertEqual(ev.error_share_compare(two, ledger), 'worse')
        self.assertEqual(ev.error_share_compare(close, ledger), 'equal')
        self.assertEqual(ev.error_share_compare(ledger, two), 'better')


if __name__ == '__main__':
    unittest.main()
