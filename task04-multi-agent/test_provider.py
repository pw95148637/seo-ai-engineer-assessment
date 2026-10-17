"""All responses here are scripted HTTP fixtures, never real model evidence."""
import asyncio,json,tempfile,unittest
from dataclasses import asdict
from pathlib import Path
import httpx
from fixtures import SAFE
from provider import Config,DualRoleAgent,JsonlLog,retry_after
from roles import build_messages
from workflow import State,run,ProviderError
POLICY=json.loads(Path(__file__).with_name("policy.json").read_text(encoding="utf-8"))

def envelope(value,finish="stop"):
    return {"id":"fixture-completion","model":"fixture-model","usage":{"total_tokens":10},
            "choices":[{"finish_reason":finish,"message":{"content":json.dumps(value,ensure_ascii=False)}}]}
FINDING={"passed":False,"findings":[{"quote":"保證出金","reason":"無證據的提款保證",
    "revision":"改用出金條款查核，保留讀者問題與吸引力","rule":"CLAIMS"}]}

class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def invoke(self,handler,max_iterations=1,retries=1,timeout=.2,total_timeout=2):
        logs=[]
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),trust_env=False) as client:
            agent=DualRoleAgent(Config("https://fixture.invalid/v1","planner-test","auditor-test","fixture-secret"),
                                client,POLICY,logs.append,"offline_http_fixture")
            s=await run(agent,State(mode="offline_http_fixture",max_iterations=max_iterations),
                        retries=retries,timeout=timeout,total_timeout=total_timeout,backoff=0)
        return s,logs,agent

    async def test_two_distinct_roles_and_feedback(self):
        requests=[]
        def handler(request):
            body=json.loads(request.content)
            requests.append(body)
            if len(requests)==1:
                result={"title":"娛樂城推薦：保證出金","sections":["出金攻略"]}
            elif body["model"]=="auditor-test":
                result=FINDING if len(requests)==2 else {"passed":True,"findings":[]}
            else:
                context=json.loads(body["messages"][1]["content"])["context"]
                self.assertEqual(context["audit"]["findings"][0]["rule"],"CLAIMS")
                self.assertIn("保證出金",context["draft"]["title"])
                result=SAFE
            return httpx.Response(200,json=envelope(result))
        s,logs,agent=await self.invoke(handler,max_iterations=3)
        self.assertEqual(s.status,"approved_provisional")
        self.assertEqual(agent.calls,4)
        self.assertNotEqual(requests[0]["messages"][0],requests[1]["messages"][0])
        self.assertIn("第一版內部草稿",requests[0]["messages"][0]["content"])
        self.assertNotIn("第一版內部草稿",requests[2]["messages"][0]["content"])
        # v2: the traffic demand is not withdrawn by the controller; the Planner decides.
        self.assertIn("流量負責人的要求",requests[2]["messages"][0]["content"])
        self.assertNotIn("已撤銷",requests[2]["messages"][0]["content"])
        self.assertTrue(all(x["mode"]=="offline_http_fixture" for x in logs))
        self.assertNotIn("fixture-secret",json.dumps(logs))

    async def test_401_not_retried(self):
        s,logs,agent=await self.invoke(lambda req:httpx.Response(401,text="fixture-secret"))
        self.assertEqual(agent.calls,1); self.assertEqual(s.status,"error")
        self.assertIn("[REDACTED]",logs[0]["response_text"])

    async def test_429_retry_after(self):
        def handler(req):
            if not hasattr(handler,"called"):
                handler.called=True
                return httpx.Response(429,headers={"Retry-After":"0"})
            role=json.loads(req.content)["model"]
            return httpx.Response(200,json=envelope(SAFE if role=="planner-test" else {"passed":True,"findings":[]}))
        s,logs,agent=await self.invoke(handler)
        self.assertEqual(agent.calls,3); self.assertEqual(s.status,"approved_provisional")

    async def test_503_exhausted(self):
        s,logs,agent=await self.invoke(lambda req:httpx.Response(503))
        self.assertEqual(agent.calls,2); self.assertIsNone(s.final)

    async def test_400_not_retried(self):
        s,logs,agent=await self.invoke(lambda req:httpx.Response(400))
        self.assertEqual(agent.calls,1); self.assertEqual(s.status,"error")

    async def test_malformed_envelope(self):
        s,logs,agent=await self.invoke(lambda req:httpx.Response(200,json={"choices":[]}))
        self.assertEqual(agent.calls,1); self.assertEqual(s.status,"error")

    async def test_invalid_role_json(self):
        s,logs,agent=await self.invoke(lambda req:httpx.Response(200,json=envelope({"title":1})))
        self.assertEqual(agent.calls,1); self.assertEqual(s.status,"error")

    async def test_truncated_completion(self):
        s,logs,agent=await self.invoke(lambda req:httpx.Response(200,json=envelope(SAFE,"length")))
        self.assertEqual(agent.calls,1); self.assertEqual(s.status,"error")

    async def test_http_timeout_retried(self):
        def handler(req): raise httpx.ReadTimeout("scripted",request=req)
        s,logs,agent=await self.invoke(handler)
        self.assertEqual(agent.calls,2); self.assertEqual(s.status,"error")

    async def test_async_cancel_recorded(self):
        async def handler(req): await asyncio.sleep(10)
        s,logs,agent=await self.invoke(handler,timeout=.001)
        self.assertEqual(s.status,"error")
        self.assertEqual([x["error"] for x in logs],["cancelled","cancelled"])

    async def test_request_limit(self):
        logs=[]
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,json=envelope(SAFE)))) as client:
            agent=DualRoleAgent(Config("https://fixture.invalid/v1","p","a",max_calls=1),
                                client,POLICY,logs.append,"offline_http_fixture")
            s=await run(agent,State(mode="offline_http_fixture"))
        self.assertEqual(agent.calls,1); self.assertEqual(s.status,"error"); self.assertIsNone(s.final)

    async def test_incremental_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            log=JsonlLog(Path(d)/"events.jsonl")
            from fixtures import Fixture
            s=await run(Fixture(),sink=log)
            records=[json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records[-1]["status"],"approved_provisional")
            self.assertIn("findings",records[2]["feedback"])
            self.assertEqual(s.iteration,2)

    def test_retry_after_and_url_config(self):
        self.assertEqual(retry_after("4"),4)
        self.assertEqual(retry_after("Thu, 01 Jan 1970 00:00:00 GMT"),0)
        self.assertIsNone(retry_after("garbage"))
        for url in ("http://remote.invalid/v1","https://user:pass@host/v1","https://host/v1?key=secret"):
            with self.assertRaises(ValueError): Config(url,"p","a")

    def test_no_recursive_history_inputs(self):
        from workflow import snapshot
        s=State()
        s.history=[{"node":"planner","input":{"secret_context":"not recursive"},"output":SAFE}]
        self.assertNotIn("input",snapshot(s)["history"][0])

    def test_contradictory_audit_rejected(self):
        from workflow import validate
        with self.assertRaises(ValueError):
            validate("auditor",{"passed":True,"findings":[FINDING["findings"][0]]})

class LoopbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_loopback_http(self):
        received=[]
        async def handle(reader,writer):
            try:
                head=await reader.readuntil(b"\r\n\r\n")
                length=int(next(x.split(b":",1)[1] for x in head.split(b"\r\n") if x.lower().startswith(b"content-length:")))
                body=json.loads(await reader.readexactly(length))
                received.append(body)
                n=len(received)
                result=({"title":"娛樂城推薦：保證出金","sections":["出金攻略"]} if n==1 else
                        FINDING if n==2 else SAFE if n==3 else {"passed":True,"findings":[]})
                payload=json.dumps(envelope(result),ensure_ascii=False).encode()
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "+
                             str(len(payload)).encode()+b"\r\nConnection: close\r\n\r\n"+payload)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
        server=await asyncio.start_server(handle,"127.0.0.1",0)
        port=server.sockets[0].getsockname()[1]
        raw=[]; events=[]
        async with server:
            async with httpx.AsyncClient(timeout=2,trust_env=False) as client:
                agent=DualRoleAgent(Config(f"http://127.0.0.1:{port}/v1","fixture-planner","fixture-auditor"),
                                    client,POLICY,raw.append,"offline_http_fixture")
                s=await run(agent,State(mode="offline_http_fixture"),sink=events.append)
        self.assertEqual(len(received),4); self.assertEqual(s.status,"approved_provisional")
        self.assertEqual(s.iteration,2); self.assertIn("保證出金",s.history[0]["output"]["title"])
        # Written to a temp dir: evidence/http-fixture is an archived sample and must not change per test run.
        from verify_run import inspect
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)
            (target/"state.json").write_text(json.dumps(asdict(s),ensure_ascii=False,indent=2),encoding="utf-8",newline="\n")
            for name,records in (("provider",raw),("events",events)):
                (target/(name+".jsonl")).write_text("\n".join(json.dumps(x,ensure_ascii=False) for x in records)+"\n",encoding="utf-8",newline="\n")
            checks=inspect(target)["checks"]
        self.assertFalse(checks["mode_is_llm_runtime"])
        self.assertTrue(checks["raw_outputs_match_state"])
        self.assertTrue(checks["initial_conflict_present"])
        self.assertTrue(checks["feedback_carried_to_revision"])

if __name__=="__main__": unittest.main(verbosity=2)
