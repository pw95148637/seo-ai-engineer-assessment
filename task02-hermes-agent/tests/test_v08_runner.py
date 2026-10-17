import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from src.runner_support import (HERMES_MODES, HERMES_WRITE_TOOLS, SKILL_READ_TOOLS, TOOLS, readiness, feedback_outcome,
                                review_record)
from src.scoring import token_fields, hermes_tool_results

TASK = Path(__file__).resolve().parents[1]


def done_record(result='skill+memory'):
    return dict(message='Background review complete: thread=bg-review calls=4 in=9000 out=800 cache_read=50000 '
                        f'result={result}', args=[4, 9000, 800, 50000, result])


class SurfaceTests(unittest.TestCase):
    def test_each_mode_exposes_only_its_tools(self):
        self.assertEqual(HERMES_MODES['off']['tools'], TOOLS)
        self.assertTrue(HERMES_MODES['off']['skip_memory'] and not HERMES_MODES['off']['review'])
        self.assertEqual(HERMES_MODES['learn']['tools'], TOOLS | SKILL_READ_TOOLS | HERMES_WRITE_TOOLS)
        self.assertTrue(HERMES_MODES['learn']['review'] and not HERMES_MODES['learn']['skip_memory'])
        frozen = HERMES_MODES['frozen']
        self.assertFalse(frozen['tools'] & HERMES_WRITE_TOOLS)
        self.assertTrue(SKILL_READ_TOOLS <= frozen['tools'] and not frozen['review'] and not frozen['skip_memory'])
        self.assertNotIn('skills', frozen['toolsets'])  # the full skills toolset carries skill_manage
        self.assertFalse(HERMES_MODES['feedback']['tools'] & TOOLS)

    def test_readiness_checks_the_mode_tool_set(self):
        learn = HERMES_MODES['learn']['tools']
        self.assertTrue(readiness({'logged_in': True}, learn, learn)['ready'])
        self.assertEqual(readiness({'logged_in': True}, TOOLS, learn)['blocker'], 'unexpected_tools')
        self.assertEqual(readiness({'logged_in': True}, TOOLS)['ready'], True)

    def test_feedback_outcome(self):
        self.assertEqual(feedback_outcome({'completed': True}, []), ('feedback_complete', 0))
        self.assertEqual(feedback_outcome({'completed': True}, [{'kind': 'tool_call'}])[0], 'feedback_used_research_tools')
        self.assertEqual(feedback_outcome({'completed': False}, [])[0], 'model_failed_or_partial')

    def test_review_record(self):
        r = review_record(True, [done_record()], ['Memory updated'], False)
        self.assertTrue(r['triggered'] and r['completed'] and not r['timed_out'])
        self.assertEqual(r['usage'], dict(api_calls=4, input=9000, output=800, cache_read=50000))
        self.assertEqual(r['result'], 'skill+memory')
        self.assertFalse(review_record(True, [], [], True)['completed'])  # still running when the wait ended
        self.assertFalse(review_record(True, [done_record('error')], [], False)['completed'])
        failed = review_record(True, [dict(message='Background memory/skill review failed: boom', args=[])], [], False)
        self.assertFalse(failed['completed'])
        self.assertEqual(failed['warnings'], ['Background memory/skill review failed: boom'])
        self.assertFalse(review_record(False, [], [], False)['triggered'])

    def test_cost_counts_uncached_prompt_and_completion(self):
        t = token_fields(dict(session_total_tokens=1100, session_prompt_tokens=1000, session_completion_tokens=100,
                              session_cache_read_tokens=700, session_cache_write_tokens=0, session_api_calls=3))
        self.assertEqual((t['uncached_prompt'], t['cost'], t['total']), (300, 400, 1100))
        self.assertNotIn('cost', token_fields(dict(session_total_tokens=5, session_prompt_tokens=4,
                                                   session_completion_tokens=1)))

    def test_hermes_tool_results_count_refused_writes(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'r-hermes.json').write_text(json.dumps({'messages': [
                {'role': 'tool', 'tool_name': 'skill_view'}, {'role': 'tool', 'name': 'skill_manage'},
                {'role': 'assistant'}, {'role': 'tool', 'tool_name': 'skill_view'}]}), encoding='utf-8')
            self.assertEqual(hermes_tool_results(d, 'r'), {'skill_view': 2, 'skill_manage': 1})
            self.assertIsNone(hermes_tool_results(d, 'missing'))

    def test_review_capture_waits_for_the_review_thread(self):
        import importlib.util, logging, threading, time
        spec = importlib.util.spec_from_file_location('run_research_v08', TASK / 'scripts' / 'run_research.py')
        rr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rr)

        class Agent:
            background_review_callback = None

        def review(delay, agent):
            time.sleep(delay)
            logging.getLogger('agent.background_review').info(
                'Background review complete: thread=bg-review calls=%d in=%d out=%d cache_read=%d result=%s',
                4, 9000, 800, 50000, 'memory')
            agent.background_review_callback('Memory updated')

        for delay, wait, completed in ((0.2, 5, True), (1.5, 0.3, False)):
            agent, capture = Agent(), rr.ReviewCapture()
            capture.attach(agent)
            self.addCleanup(logging.getLogger('agent.background_review').removeHandler, capture)
            t = threading.Thread(target=review, args=(delay, agent), name='bg-review', daemon=True)
            t.start()
            r = capture.wait(wait)
            self.assertEqual((r['completed'], r['timed_out'], r['triggered']), (completed, not completed, True))
            if completed:
                self.assertEqual(r['usage'], dict(api_calls=4, input=9000, output=800, cache_read=50000))
                self.assertEqual(r['actions'], ['Memory updated'])
            t.join()

    def test_runner_refuses_learning_without_its_own_home(self):
        with tempfile.TemporaryDirectory() as d:
            for extra in (['--hermes-learning', 'learn'], ['--feedback-file', 'x.txt'],
                          ['--hermes-home', str(Path(d) / 'nowhere')]):
                p = subprocess.run([sys.executable, 'scripts/run_research.py', '--root', d, '--check-only', *extra],
                                   cwd=TASK, capture_output=True, text=True,
                                   env={**os.environ, 'PYTHONPATH': str(TASK)})
                self.assertEqual(p.returncode, 2, p.stderr)
                self.assertFalse(list(Path(d).glob('*-preflight.json')))


if __name__ == '__main__':
    unittest.main()
