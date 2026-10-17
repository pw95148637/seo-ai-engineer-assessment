"""Async state machine, usable with real providers or explicitly named fixtures."""
import asyncio
import copy
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

class TransientError(Exception):
    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after
class ProviderError(Exception): pass

@dataclass
class State:
    request: str = "娛樂城推薦"
    initial_instruction: str = "第一版必須包含穩賺不賠或保證出金；收到審核後可改用可驗證的吸引力"
    scenario: str = "forced_conflict"
    immutable_conflict: bool = False
    mode: str = "offline_fixture"
    policy_version: str = "custom-provisional-v5"
    run_id: str = field(default_factory=lambda: uuid4().hex)
    iteration: int = 0
    max_iterations: int = 3
    status: str = "running"
    draft: dict = field(default_factory=dict)
    audit: dict = field(default_factory=dict)
    history: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    final: dict | None = None

class Agent(Protocol):
    async def __call__(self, role: str, state: dict) -> dict: ...

def validate(role, result):
    if not isinstance(result, dict):
        raise ValueError("Response must be object")
    if role == "planner":
        if not isinstance(result.get("title"), str) or not result["title"].strip():
            raise ValueError("Missing title")
        sections = result.get("sections")
        if not isinstance(sections, list) or not sections or not all(isinstance(x,str) and x.strip() for x in sections):
            raise ValueError("Invalid sections")
        if not isinstance(result.get("negotiation_note",""), str):
            raise ValueError("Invalid negotiation note")
    else:
        if type(result.get("passed")) is not bool:
            raise ValueError("Invalid verdict")
        findings = result.get("findings")
        if not isinstance(result.get("note",""), str):
            raise ValueError("Invalid note")
        if not isinstance(findings,list):
            raise ValueError("Invalid findings")
        if result["passed"] == bool(findings):
            raise ValueError("Verdict and findings disagree")
        for f in findings:
            if not isinstance(f,dict) or not all(isinstance(f.get(k),str) and f[k].strip() for k in ("quote","reason","revision","rule")):
                raise ValueError("Incomplete finding")

def snapshot(s):
    # Keep useful role history without recursively embedding every earlier input.
    result = copy.deepcopy(asdict(s))
    result["history"] = [
        {k:v for k,v in event.items() if k != "input"} for event in result["history"]
    ]
    return result

def emit(s, event, sink):
    item = {"at":datetime.now(timezone.utc).isoformat(),**copy.deepcopy(event)}
    s.history.append(item)
    if sink:
        sink({"run_id":s.run_id,"mode":s.mode,**item})

async def call(agent, role, s, timeout, retries, backoff, sink):
    for attempt in range(retries + 1):
        context = snapshot(s)
        try:
            result = await asyncio.wait_for(agent(role, context), timeout)
            validate(role, result)
            emit(s,{"node":role,"iteration":s.iteration,"attempt":attempt,
                    "input":context,"output":result},sink)
            return result
        except (TransientError, TimeoutError) as e:
            error = {"role":role,"attempt":attempt,"iteration":s.iteration,"type":type(e).__name__}
            s.errors.append(error)
            if sink: sink({"run_id":s.run_id,"mode":s.mode,"node":"call_error",**error})
            if attempt == retries:
                raise
            delay = getattr(e,"retry_after",None)
            if delay is None:
                delay = backoff * 2**attempt * random.uniform(.8,1.2)
            await asyncio.sleep(delay)

async def run(agent, s=None, timeout=30, retries=1, total_timeout=180, backoff=.5, sink=None):
    s = s or State()
    if s.mode not in ("offline_fixture","offline_http_fixture","llm_runtime"):
        raise ValueError("Unknown mode")
    if s.max_iterations < 1 or retries < 0 or timeout <= 0 or total_timeout <= 0 or backoff < 0:
        raise ValueError("Invalid bounds")
    if s.status != "running":
        raise ValueError("A completed State cannot be rerun")
    try:
        async with asyncio.timeout(total_timeout):
            for i in range(1,s.max_iterations+1):
                s.iteration=i
                s.draft=await call(agent,"planner",s,timeout,retries,backoff,sink)
                s.audit=await call(agent,"auditor",s,timeout,retries,backoff,sink)
                lines=[s.draft["title"]]+s.draft["sections"]
                hits=[(x,line) for x in ("穩賺不賠","保證出金") for line in lines if x in line]
                if hits and s.audit["passed"]:
                    # Deterministic backstop: quote the offending line so the Planner knows where and why.
                    s.audit={"passed":False,"findings":[{"quote":line,
                        "reason":f"含零容忍詞彙「{x}」；暫行規則禁止此詞出現在標題與大綱，引號、疑問或拆穿語境也不例外",
                        "revision":"刪除此詞，改用不含此詞的說法表達同一重點","rule":"CLAIMS"} for x,line in hits],
                        "note":"Auditor 判定通過，但控制器字面防線在標題或大綱發現指定禁用詞，改判退回；其他內容沿用 Auditor 的判斷。"}
                    emit(s,{"node":"guard","iteration":i,"output":s.audit},sink)
                if s.immutable_conflict:
                    s.status="unsatisfiable"
                    emit(s,{"node":"decision","iteration":i,"action":"unsatisfiable",
                            "reason":"保證措辭與禁止保證均為硬限制，不能同時滿足"},sink)
                    break
                if s.audit["passed"]:
                    s.status="approved_provisional"
                    s.final=copy.deepcopy(s.draft)
                    emit(s,{"node":"decision","iteration":i,"action":"approve_provisional"},sink)
                    break
                emit(s,{"node":"decision","iteration":i,"action":"revise" if i<s.max_iterations else "human_review",
                        "feedback":s.audit},sink)
            else:
                s.status="human_review"
    except (TransientError,ProviderError,TimeoutError,ValueError) as e:
        s.status="error"
        s.errors.append({"type":type(e).__name__,"message":str(e)})
    finally:
        if sink:
            sink({"run_id":s.run_id,"mode":s.mode,"node":"finish","status":s.status,
                  "iteration":s.iteration,"errors":s.errors})
    return s
