"""Official Codex CLI adapter; credentials remain in this Work's private CLI home."""
import asyncio
import json
import os
import signal
import tempfile
import time
from datetime import datetime,timezone
from pathlib import Path
from roles import build_messages,output_schema
from workflow import ProviderError,validate

ROOT=Path(__file__).resolve().parent
DEFAULT_CLI=ROOT/".codex-cli/node_modules/.bin/codex"
# Outside the repository, excluded from every deliverable.
PRIVATE_HOME=ROOT.parent/"task04-private-codex"
def cli_environment():
    names=("PATH","HOME","TMPDIR","LANG","LC_ALL","HTTPS_PROXY","HTTP_PROXY",
           "ALL_PROXY","NO_PROXY","SSL_CERT_FILE","SSL_CERT_DIR","NODE_EXTRA_CA_CERTS")
    env={k:os.environ[k] for k in names if k in os.environ}
    PRIVATE_HOME.mkdir(mode=0o700,parents=True,exist_ok=True)
    PRIVATE_HOME.chmod(0o700)
    env["CODEX_HOME"]=str(PRIVATE_HOME)
    return env

def cli_base():
    return [str(DEFAULT_CLI),"-c",'forced_login_method="chatgpt"',"-c",'cli_auth_credentials_store="file"']

async def rpc_preflight():
    """Read public account/quota metadata; never auth.json or token methods."""
    proc=await asyncio.create_subprocess_exec(*cli_base(),"app-server",
        env=cli_environment(),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL)
    async def send(method,identifier=None,params=None):
        msg={"method":method}
        if identifier is not None: msg["id"]=identifier
        if params is not None: msg["params"]=params
        proc.stdin.write((json.dumps(msg)+"\n").encode())
        await proc.stdin.drain()
        if identifier is None: return None
        while True:
            line=await proc.stdout.readline()
            if not line: raise ProviderError("Codex app-server closed before reply")
            reply=json.loads(line)
            if reply.get("id")==identifier:
                if "error" in reply:
                    raise ProviderError("Codex public preflight unavailable")
                return reply["result"]
    try:
        async with asyncio.timeout(20):
            await send("initialize",1,{"clientInfo":{"name":"soulo_task04","version":"0.1.0"}})
            await send("initialized",params={})
            account=await send("account/read",2,{"refreshToken":False})
            identity=account.get("account") or {}
            result={"auth_type":identity.get("type"),"plan_type":identity.get("planType")}
            if result["auth_type"]!="chatgpt":
                result.update({"included_only_confirmed":False,"reason":"Independent ChatGPT login required"})
                return result
            quota=await send("account/rateLimits/read",3)
            limits=quota.get("rateLimits") or {}
            windows=[limits.get(k) for k in ("primary","secondary") if limits.get(k)]
            credits=limits.get("credits")
            # Cannot disable purchased-credit fallback through a documented CLI flag.
            # Run only when the service explicitly reports no usable credit pool.
            no_credits=isinstance(credits,dict) and credits.get("hasCredits") is False and credits.get("unlimited") is not True
            included=(bool(windows) and all(isinstance(w.get("usedPercent"),(int,float)) and
                       0<=w["usedPercent"]<100 for w in windows)
                       and not limits.get("rateLimitReachedType"))
            result.update({"rate_limits":limits,"included_only_confirmed":
                           no_credits and included and result["plan_type"] in ("plus","pro"),
                           "reason":"Requires personal included quota and explicit no-credit balance"})
            return result
    finally:
        if proc.returncode is None:
            proc.terminate()
        await proc.wait()

def schema_for(role):
    return output_schema(role)

class CodexDualRoleAgent:
    def __init__(self,policy,raw_log,model=None,max_calls=6):
        self.policy=policy; self.raw_log=raw_log; self.model=model
        self.max_calls=max_calls; self.calls=0
    async def __call__(self,role,state):
        if self.calls>=self.max_calls: raise ProviderError("CLI request limit reached")
        quota=await rpc_preflight()
        if not quota["included_only_confirmed"]:
            self.raw_log({"mode":"llm_runtime","transport":"codex_cli","run_id":state["run_id"],
                          "role":role,"iteration":state["iteration"],"error":"included quota not confirmed","preflight":quota})
            raise ProviderError("Cannot confirm subscription-only quota without credits; stop before model call")
        messages=build_messages(role,state,self.policy)
        self.calls+=1
        event={"mode":"llm_runtime","transport":"codex_cli","run_id":state["run_id"],"role":role,
               "iteration":state["iteration"],"request":{"messages":messages,"model":self.model or "CLI default"},
               "preflight":quota,"started_at":datetime.now(timezone.utc).isoformat(),"call":self.calls}
        started=time.monotonic()
        with tempfile.TemporaryDirectory(prefix="task04-cli-") as temp:
            folder=Path(temp)
            schema=folder/"schema.json"; schema.write_text(json.dumps(schema_for(role)),encoding="utf-8")
            answer=folder/"answer.json"
            instructions=messages[0]["content"]+" 不使用工具、外部網站或本機檔案；只根據提供資料完成角色回覆。"
            command=cli_base()+["exec","--ignore-user-config","--ephemeral",
                "--sandbox","read-only","--skip-git-repo-check","--json","--color","never",
                "-c","developer_instructions="+json.dumps(instructions,ensure_ascii=False),
                "-c","features.shell_tool=false","-c","features.apps=false",
                "-c",'web_search="disabled"',"--output-schema",str(schema),
                "--output-last-message",str(answer)]
            if self.model: command+=["--model",self.model]
            command+=["-"]
            proc=await asyncio.create_subprocess_exec(*command,cwd=folder,env=cli_environment(),
                start_new_session=True,stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            communication=asyncio.create_task(proc.communicate(messages[1]["content"].encode()))
            try:
                stdout,stderr=await asyncio.shield(communication)
                event.update({"returncode":proc.returncode,"cli_events_jsonl":stdout.decode(errors="replace"),
                              "cli_stderr":stderr.decode(errors="replace")})
                if proc.returncode!=0: raise ProviderError("Codex exec failed; see retained CLI log")
                if not answer.is_file(): raise ProviderError("Codex did not save a final JSON response")
                event["response_text"]=answer.read_text(encoding="utf-8")
                events=[json.loads(line) for line in stdout.decode().splitlines() if line.strip()]
                completed=[x for x in events if x.get("type")=="turn.completed"]
                event["usage"]=completed[-1].get("usage") if completed else None
                event["thread_ids"]=[x.get("thread_id") for x in events if x.get("type")=="thread.started"]
                value=json.loads(event["response_text"]);validate(role,value)
                return value
            except asyncio.CancelledError:
                if proc.returncode is None: os.killpg(proc.pid,signal.SIGTERM)
                try:
                    stdout,stderr=await asyncio.wait_for(communication,5)
                except TimeoutError:
                    if proc.returncode is None: os.killpg(proc.pid,signal.SIGKILL)
                    stdout,stderr=await communication
                event.update({"error":"cancelled","returncode":proc.returncode,
                              "cli_events_jsonl":stdout.decode(errors="replace"),
                              "cli_stderr":stderr.decode(errors="replace")})
                raise
            except (ValueError,ProviderError) as e:
                event["error"]=str(e)
                raise ProviderError("Codex response invalid or failed; see CLI evidence") from e
            finally:
                event["elapsed_seconds"]=round(time.monotonic()-started,3)
                self.raw_log(event)
