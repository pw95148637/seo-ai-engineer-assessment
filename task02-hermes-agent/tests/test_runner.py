import unittest
from src.runner_support import TOOLS,readiness,outcome
from src.research_core import HTML
class RunnerTests(unittest.TestCase):
    def test_logged_out_stops_before_model(self):
        x=readiness({'logged_in':False,'secret':'must not leak'},TOOLS)
        self.assertFalse(x['ready']);self.assertEqual(x['blocker'],'oauth_required');self.assertNotIn('secret',x);self.assertFalse(x['model_called'])
    def test_quota_blocks(self):self.assertEqual(readiness({'logged_in':True,'rate_limited':True},TOOLS)['blocker'],'quota')
    def test_extra_shell_blocks(self):self.assertEqual(readiness({'logged_in':True},TOOLS|{'terminal'})['blocker'],'unexpected_tools')
    def test_partial_cannot_be_success(self):self.assertNotEqual(outcome({'completed':True,'partial':True},[{'kind':'tool_call'},{'kind':'report'}])[1],0)
    def test_model_text_without_tools_cannot_pass(self):self.assertEqual(outcome({'completed':True},[])[0],'no_autonomous_tool_use')
    def test_text_without_report_cannot_pass_research(self):self.assertEqual(outcome({'completed':True},[{'kind':'tool_call'}])[0],'missing_controller_report')
    def test_report_plus_tools_can_complete(self):self.assertEqual(outcome({'completed':True},[{'kind':'tool_call'},{'kind':'report'}])[1],0)
    def test_smoke_needs_tool_not_full_report(self):self.assertEqual(outcome({'completed':True},[{'kind':'tool_call'}],smoke=True)[1],0)
    def test_nested_h1_is_extracted(self):
        h=HTML('https://example.org');h.feed('<h1>Good <strong>nested</strong> heading</h1><link rel="alternate canonical" href="/canonical">')
        self.assertEqual(' '.join(x.strip() for x in h.h1),'Good nested heading');self.assertEqual(h.canonical,'https://example.org/canonical')
