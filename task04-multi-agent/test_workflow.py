import asyncio, unittest
from workflow import State,run,TransientError
from fixtures import Fixture
class Tests(unittest.IsolatedAsyncioTestCase):
    async def test_normal(self):
        s=await run(Fixture("normal")); self.assertEqual(s.status,"approved_provisional"); self.assertEqual(s.iteration,1)
    async def test_conflict_revision(self):
        s=await run(Fixture()); self.assertEqual(s.status,"approved_provisional"); self.assertEqual(s.iteration,2)
        self.assertIn("保證出金",s.history[0]["output"]["title"])
        self.assertNotIn("保證出金",str(s.final)); self.assertTrue(s.history[2]["feedback"]["findings"])
    async def test_immutable(self):
        s=await run(Fixture(),State(immutable_conflict=True)); self.assertEqual(s.status,"unsatisfiable"); self.assertIsNone(s.final)
    async def test_limit(self):
        f=Fixture("stubborn"); s=await run(f); self.assertEqual(s.status,"human_review"); self.assertEqual(s.iteration,3)
        self.assertIsNone(s.final); self.assertEqual(f.calls,6)  # 3 rounds x (Planner + Auditor), then stop
    async def test_api(self):
        f=Fixture("api_error"); s=await run(f); self.assertEqual(s.status,"error"); self.assertEqual(f.calls,2); self.assertIsNone(s.final)
    async def test_timeout(self):
        s=await run(Fixture("timeout"),timeout=.001); self.assertEqual(s.status,"error")
    async def test_schema(self):
        s=await run(Fixture("malformed")); self.assertEqual(s.status,"error")
    async def test_false_pass(self):
        s=await run(Fixture("false_pass"),State(max_iterations=1)); self.assertEqual(s.status,"human_review")
        guard=next(e["output"] for e in s.history if e["node"]=="guard")
        self.assertEqual([f["quote"] for f in guard["findings"]],["娛樂城推薦：穩賺不賠、保證出金"]*2)
        self.assertIn("字面防線",guard["note"])
    async def test_retry_recovery(self):
        f=Fixture("normal")
        async def recovering(role,s):
            if not hasattr(recovering,"failed"):
                recovering.failed=True; raise TransientError("injected")
            return await f(role,s)
        s=await run(recovering); self.assertEqual(s.status,"approved_provisional"); self.assertEqual(len(s.errors),1)
    async def test_total_timeout(self):
        s=await run(Fixture("timeout"),total_timeout=.001); self.assertEqual(s.status,"error")
if __name__=="__main__": unittest.main(verbosity=2)
