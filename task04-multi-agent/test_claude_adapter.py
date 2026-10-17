"""Claude CLI adapter against a scripted fake CLI process; never real model evidence."""
import contextlib, io, json, os, sys, tempfile, textwrap, unittest
from pathlib import Path
from unittest.mock import patch
from claude_subscription import ClaudeDualRoleAgent
from workflow import State, run

POLICY = json.loads(Path(__file__).with_name("policy.json").read_text(encoding="utf-8"))
FAKE = textwrap.dedent('''
    import json, os, sys, time
    MODE = %r
    args = sys.argv[1:]
    if args == ["--version"]:
        print("0.0.0-fake (Claude Code)"); sys.exit(0)
    leaked = [k for k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "ANTHROPIC_API_KEY") if k in os.environ]
    needed = ["--safe-mode", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"]
    if leaked or not all(x in args for x in needed) or os.listdir(".") or os.environ.get("CLAUDE_CODE_DISABLE_CLAUDE_MDS") != "1":
        print(json.dumps({"is_error": True, "subtype": "isolation_failed", "result": str(leaked)})); sys.exit(1)
    system = open(args[args.index("--system-prompt-file") + 1], encoding="utf-8").read()
    context = json.loads(sys.stdin.buffer.read().decode("utf-8"))["context"]
    def reply(value):
        out = {"type": "result", "subtype": "success", "is_error": False, "structured_output": value,
               "result": json.dumps(value, ensure_ascii=False), "modelUsage": {"fake-model": {}},
               "usage": {"output_tokens": 1}, "duration_ms": 1, "session_id": "fake"}
        sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8")); sys.exit(0)
    if MODE == "sleep": time.sleep(60)
    if MODE == "garbage": print("not json"); sys.exit(0)
    if MODE == "overloaded":
        print(json.dumps({"type": "result", "subtype": "success", "is_error": True, "api_error_status": 529,
                          "result": "API Error: 529 overloaded"})); sys.exit(1)
    if "passed" in json.loads(args[args.index("--json-schema") + 1])["properties"]:
        bad = "保證出金" in context["draft"]["title"]
        reply({"passed": not bad, "findings": [{"quote": "保證出金", "reason": "無依據保證",
               "revision": "改以出金條件查核吸引讀者", "rule": "CLAIMS"}] if bad else []})
    if context["iteration"] == 1:
        reply({"title": "娛樂城推薦：保證出金", "sections": ["待審草稿"]})
    reply({"title": "娛樂城推薦怎麼看？出金條件與資安查核", "sections": ["出金條款查核", "風險揭露"]})
''')

class ClaudeAdapterTests(unittest.IsolatedAsyncioTestCase):
    def fake(self, mode):
        path = Path(self.temp.name) / ("fake_%s.py" % mode)
        path.write_text(FAKE % mode, encoding="utf-8")
        return [sys.executable, str(path)]
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
    def tearDown(self):
        self.temp.cleanup()
    async def invoke(self, mode, **bounds):
        logs = []
        agent = ClaudeDualRoleAgent(POLICY, logs.append, cli=self.fake(mode), evidence_mode="offline_fixture")
        s = await run(agent, State(mode="offline_fixture"), backoff=0, **bounds)
        return s, logs, agent

    async def test_runner_end_to_end_with_isolated_env(self):
        from run_claude import execute, parser
        out = Path(self.temp.name) / "run"
        args = parser().parse_args(["--scenario", "forced_conflict", "--out", str(out)])
        with patch.dict(os.environ, {"CLAUDECODE": "1", "ANTHROPIC_API_KEY": "must-not-pass"}), \
                contextlib.redirect_stdout(io.StringIO()):
            status = await execute(args, cli=self.fake("conflict"))
        self.assertEqual(status, 0)
        records = [json.loads(x) for x in (out / "provider.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["role"] for r in records], ["planner", "auditor", "planner", "auditor"])
        self.assertNotIn("must-not-pass", (out / "provider.jsonl").read_text(encoding="utf-8"))
        self.assertTrue(all(r["request"]["system_prompt_sha256"] for r in records))
        checks = json.loads((out / "verification.json").read_text(encoding="utf-8"))["checks"]
        self.assertTrue(checks["raw_outputs_match_state"] and checks["feedback_carried_to_revision"])

    async def test_transient_cli_error_retried_once(self):
        s, logs, agent = await self.invoke("overloaded")
        self.assertEqual(agent.calls, 2); self.assertEqual(s.status, "error"); self.assertIsNone(s.final)

    async def test_invalid_output_not_retried(self):
        s, logs, agent = await self.invoke("garbage")
        self.assertEqual(agent.calls, 1); self.assertEqual(s.status, "error")

    async def test_timeout_kills_cli_process(self):
        s, logs, agent = await self.invoke("sleep", timeout=1, retries=0, total_timeout=30)
        self.assertEqual(s.status, "error")
        self.assertEqual(logs[0]["error"], "cancelled")
        self.assertIsNotNone(logs[0]["returncode"])        # process really ended
        self.assertLess(logs[0]["elapsed_seconds"], 20)

    def test_isolation_check_uses_largest_single_request(self):
        from verify_run import ISOLATION_TOKEN_CEILING, request_context_tokens
        isolated = {"usage": {"input_tokens": 3, "cache_read_input_tokens": 1800, "iterations": [
            {"input_tokens": 2, "cache_read_input_tokens": 900}, {"input_tokens": 1, "cache_creation_input_tokens": 1500}]}}
        leaked = {"usage": {"input_tokens": 5, "cache_creation_input_tokens": 97000}}
        self.assertEqual(request_context_tokens(isolated), 1501)
        self.assertGreaterEqual(request_context_tokens(leaked), ISOLATION_TOKEN_CEILING)

if __name__ == "__main__": unittest.main(verbosity=2)
