import copy,json,tempfile,unittest
from pathlib import Path
from case_input import load_case
from verify_run import inspect

class CaseTests(unittest.TestCase):
    def test_canonical_conflict_case(self):
        case,s=load_case("forced_conflict","offline_fixture","custom-provisional-v2")
        self.assertEqual(s.scenario,"forced_conflict")
        self.assertFalse(s.immutable_conflict)
        self.assertIn("保證出金",s.initial_instruction)
        # The design note (revocable only by the Planner) is documentation, never sent to roles.
        self.assertIn("可以撤銷",case["design"])
        self.assertNotIn("可以撤銷",s.initial_instruction+s.request)
        self.assertEqual(case["expected_status"],"approved_provisional")
    def test_planner_does_not_receive_rulebook(self):
        from roles import build_messages
        from workflow import snapshot
        case,s=load_case("forced_conflict","offline_fixture","custom-provisional-v3")
        policy={"version":"x","rules":[{"id":"CLAIMS"}]}
        planner=json.loads(build_messages("planner",snapshot(s),policy)[1]["content"])
        auditor=json.loads(build_messages("auditor",snapshot(s),policy)[1]["content"])
        self.assertNotIn("policy",planner); self.assertEqual(auditor["policy"],policy)
        s.iteration=1
        self.assertIn("必須逐字包含",build_messages("planner",snapshot(s),policy)[0]["content"])
    def test_other_case_contracts(self):
        case,s=load_case("normal","offline_fixture","custom-provisional-v2")
        self.assertFalse(s.immutable_conflict)
        case,s=load_case("immutable","offline_fixture","custom-provisional-v2")
        self.assertTrue(s.immutable_conflict)
        self.assertEqual(case["expected_status"],"unsatisfiable")
    def test_sources_resolve(self):
        base=Path(__file__).parent
        policy=json.loads((base/"policy.json").read_text(encoding="utf-8"))
        ids={s["id"] for s in policy["sources"]}
        for rule in policy["rules"]:
            self.assertTrue(set(rule["source_ids"]) <= ids)
        # The assignment text stays private, so the public copy has no reference/ directory.
        if not (base/"reference/company-original.txt").is_file():
            self.skipTest("assignment text is not published with the public copy")

class RawEvidenceTests(unittest.TestCase):
    def copy_evidence(self,directory):
        source=Path(__file__).parent/"evidence/http-fixture"
        target=Path(directory)
        for name in ("state.json","provider.jsonl"):
            (target/name).write_bytes((source/name).read_bytes())
        return target
    def test_raw_outputs_match_offline_state(self):
        with tempfile.TemporaryDirectory() as d:
            result=inspect(self.copy_evidence(d))
            self.assertTrue(result["checks"]["raw_outputs_match_state"])
            self.assertFalse(result["checks"]["mode_is_llm_runtime"])
    def test_tampered_state_fails(self):
        with tempfile.TemporaryDirectory() as d:
            target=self.copy_evidence(d)
            state=json.loads((target/"state.json").read_text(encoding="utf-8"))
            state["history"][0]["output"]["title"]="被替換的輸出"
            (target/"state.json").write_text(json.dumps(state),encoding="utf-8")
            self.assertFalse(inspect(target)["checks"]["raw_outputs_match_state"])

class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_runner_saves_canonical_input_and_summary(self):
        # Synthetic provider in a temporary directory; never retained as runtime evidence.
        import httpx,contextlib,io
        from unittest.mock import patch
        from fixtures import SAFE
        from run_model import execute,parser
        calls=[]
        def handler(request):
            body=json.loads(request.content);calls.append(body)
            n=len(calls)
            result=({"title":"娛樂城推薦：保證出金","sections":["待審草稿"]}
                    if n==1 else {"passed":False,"findings":[
                        {"quote":"保證出金","reason":"無依據保證","revision":"改以查核條件吸引讀者","rule":"CLAIMS"}]}
                    if n==2 else SAFE if n==3 else {"passed":True,"findings":[]})
            return httpx.Response(200,json={"choices":[{"finish_reason":"stop","message":{"content":json.dumps(result,ensure_ascii=False)}}]})
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/"new-run"
            args=parser().parse_args(["--base-url","http://127.0.0.1:1/v1",
                "--model","synthetic-test-only","--access","local","--out",str(out)])
            with patch("run_model.httpx.AsyncClient",return_value=client), contextlib.redirect_stdout(io.StringIO()):
                status=await execute(args)
            self.assertEqual(status,0)
            meta=json.loads((out/"metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["case_input"]["id"],"forced_conflict")
            self.assertEqual(len(calls),4)
            self.assertTrue((out/"summary.md").is_file())
            self.assertTrue((out/"outline.md").is_file())
            self.assertIn("可以撤銷",meta["case_input"]["design"])
