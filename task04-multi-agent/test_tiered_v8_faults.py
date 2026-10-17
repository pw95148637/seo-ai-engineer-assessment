"""Timeouts and API errors on the tiered controller (workflow_v8.run); offline, no model calls.

The v8 controller has its own call/retry code (workflow_v8.call), so its fault handling is tested here directly
rather than through the v6 controller's tests. Kept out of test_tiered_v8.py, whose hash is recorded in the v8 and
v8.1 preregistrations (evidence/tiered-v8/prereg.json, evidence/tiered-v81/prereg.json).
"""
import asyncio, copy, json, unittest
from pathlib import Path
from workflow import ProviderError, TransientError
from workflow_v8 import TieredState, run

POLICY = json.loads((Path(__file__).resolve().parent / "policy_v8.json").read_text(encoding="utf-8"))
GOOD = {"title": "娛樂城推薦前必看：出金條款5問", "sections": [{"heading": "前言", "points": "要點"}],
        "negotiation_note": "", "suggestion_responses": []}
PASS = {"findings": [], "suggestions": [], "note": "通過"}


class Faulty:
    """Answers like a passing Planner/Auditor, except that chosen calls (1-based, counted per role) misbehave."""
    def __init__(self, faults=None, role="planner"):
        self.faults, self.role, self.calls, self.by_role = faults or {}, role, 0, {"planner": 0, "auditor": 0}

    async def __call__(self, role, state):
        self.calls += 1
        self.by_role[role] += 1
        fault = self.faults.get(self.by_role[role]) if role == self.role else None
        if fault == "slow":
            await asyncio.sleep(5)
        elif fault == "transient":
            raise TransientError("injected 529")
        elif fault == "provider":
            raise ProviderError("Claude CLI returned no JSON (exit 1)")
        elif fault == "malformed":
            return {**copy.deepcopy(GOOD), "sections": ["字串段落"]}
        return copy.deepcopy(GOOD if role == "planner" else PASS)


def state():
    return TieredState(mode="offline_fixture")


class FaultTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_call_timeout_is_retried_once_and_the_run_continues(self):
        agent = Faulty({1: "slow"})
        s = await run(agent, state(), POLICY, timeout=0.05, retries=1, backoff=0)
        self.assertEqual((s.status, agent.calls), ("approved_provisional", 3))
        self.assertEqual([(e["role"], e["attempt"], e["type"]) for e in s.errors], [("planner", 0, "TimeoutError")])

    async def test_transient_error_on_the_auditor_is_retried_once(self):
        agent = Faulty({1: "transient"}, role="auditor")
        s = await run(agent, state(), POLICY, retries=1, backoff=0)
        self.assertEqual((s.status, agent.by_role["auditor"]), ("approved_provisional", 2))
        self.assertEqual(len(s.errors), 1)

    async def test_transient_error_twice_stops_with_error_and_no_outline(self):
        agent = Faulty({1: "transient", 2: "transient"})
        s = await run(agent, state(), POLICY, retries=1, backoff=0)
        self.assertEqual((s.status, agent.calls), ("error", 2))
        self.assertIsNone(s.final)
        self.assertEqual(s.errors[-1]["type"], "TransientError")

    async def test_timeout_twice_stops_with_error(self):
        agent = Faulty({1: "slow", 2: "slow"})
        s = await run(agent, state(), POLICY, timeout=0.05, retries=1, backoff=0)
        self.assertEqual((s.status, agent.calls), ("error", 2))
        self.assertIsNone(s.final)

    async def test_no_json_from_the_cli_is_not_retried(self):
        agent = Faulty({1: "provider"})
        s = await run(agent, state(), POLICY, retries=1, backoff=0)
        self.assertEqual((s.status, agent.calls), ("error", 1))
        self.assertEqual(s.errors[-1]["type"], "ProviderError")

    async def test_format_error_is_not_retried(self):
        agent = Faulty({1: "malformed"})
        s = await run(agent, state(), POLICY, retries=1, backoff=0)
        self.assertEqual((s.status, agent.calls), ("error", 1))
        self.assertEqual(s.errors[-1]["type"], "ValueError")
        self.assertIsNone(s.final)

    async def test_total_timeout_stops_the_run(self):
        agent = Faulty({1: "slow"})
        s = await run(agent, state(), POLICY, timeout=10, total_timeout=0.05, backoff=0)
        self.assertEqual(s.status, "error")
        self.assertIsNone(s.final)

    async def test_events_already_written_survive_an_error(self):
        events = []
        agent = Faulty({1: "transient", 2: "transient"}, role="auditor")
        s = await run(agent, state(), POLICY, retries=1, backoff=0, sink=events.append)
        self.assertEqual(s.status, "error")
        nodes = [e["node"] for e in events]
        self.assertEqual(nodes[:2], ["planner", "program_check"])
        self.assertEqual(nodes.count("call_error"), 2)
        self.assertEqual((nodes[-1], events[-1]["status"]), ("finish", "error"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
