"""OpenAI-compatible async REST adapter. No platform/CLI credentials are discovered."""
import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from roles import build_messages
from workflow import TransientError, ProviderError, validate

@dataclass
class Config:
    base_url: str
    planner_model: str
    auditor_model: str
    api_key: str = ""
    max_output_tokens: int = 1600
    max_calls: int = 12

    def __post_init__(self):
        u = urlsplit(self.base_url)
        if u.scheme not in ("http","https") or not u.hostname or u.username or u.password or u.query or u.fragment:
            raise ValueError("Use a plain HTTP(S) base URL without credentials or query")
        if u.scheme == "http" and u.hostname not in ("localhost","127.0.0.1","::1"):
            raise ValueError("Non-local endpoints require HTTPS")
        if not self.planner_model or not self.auditor_model:
            raise ValueError("Both model IDs are required")
        if self.max_output_tokens < 1 or self.max_calls < 1:
            raise ValueError("Invalid provider bounds")

def retry_after(value):
    try:
        seconds = float(value)
    except (TypeError,ValueError):
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            seconds = (date - datetime.now(timezone.utc)).total_seconds()
        except (TypeError,ValueError,OverflowError):
            return None
    return max(0,seconds)

class JsonlLog:
    def __init__(self, path):
        self.path = Path(path)
    def __call__(self, event):
        with self.path.open("a",encoding="utf-8") as f:
            f.write(json.dumps(event,ensure_ascii=False)+"\n")

class DualRoleAgent:
    def __init__(self, config, client, policy, raw_log, evidence_mode="llm_runtime"):
        self.config=config
        self.client=client
        self.policy=policy
        self.raw_log=raw_log
        self.calls=0
        self.evidence_mode=evidence_mode

    async def __call__(self, role, state):
        if self.calls >= self.config.max_calls:
            raise ProviderError("Request limit reached")
        self.calls += 1
        model = self.config.planner_model if role == "planner" else self.config.auditor_model
        messages = build_messages(role,state,self.policy)
        body={"model":model,"messages":messages,"max_tokens":self.config.max_output_tokens,
              "response_format":{"type":"json_object"}}
        # Never save headers or a credential-bearing URL.
        event={"call":self.calls,"run_id":state["run_id"],"role":role,
               "iteration":state["iteration"],"mode":self.evidence_mode,
               "started_at":datetime.now(timezone.utc).isoformat(),"request":body}
        start=time.monotonic()
        try:
            headers={"Authorization":"Bearer "+self.config.api_key} if self.config.api_key else {}
            response=await self.client.post(self.config.base_url.rstrip("/")+"/chat/completions",
                                            json=body,headers=headers)
            event.update({"http_status":response.status_code,
                          "request_id":response.headers.get("x-request-id"),
                          "response_text":response.text})
            if response.status_code == 429 or response.status_code in (408,500,502,503,504):
                raise TransientError("Temporary provider HTTP "+str(response.status_code),
                                     retry_after(response.headers.get("retry-after")))
            if response.status_code >= 300:
                raise ProviderError("Provider HTTP "+str(response.status_code))
            try:
                envelope=response.json()
                choice=envelope["choices"][0]
                if choice.get("finish_reason") not in ("stop",None):
                    raise ValueError("Incomplete completion")
                text=choice["message"]["content"]
                if not isinstance(text,str):
                    raise ValueError("Missing text")
                result=json.loads(text)
                validate(role,result)
                event["response_id"]=envelope.get("id")
                event["model_returned"]=envelope.get("model")
                event["usage"]=envelope.get("usage")
                return result
            except (ValueError,KeyError,IndexError,TypeError) as e:
                raise ProviderError("Invalid provider JSON/schema: "+type(e).__name__) from e
        except httpx.TimeoutException as e:
            event["error"]="http_timeout"
            raise TransientError("Provider timeout") from e
        except httpx.TransportError as e:
            event["error"]="transport_error"
            raise TransientError("Provider transport error") from e
        except asyncio.CancelledError:
            event["error"]="cancelled"
            raise
        except (TransientError,ProviderError) as e:
            event["error"]=str(e)
            raise
        finally:
            event["elapsed_seconds"]=round(time.monotonic()-start,4)
            # Providers occasionally echo credentials in an error response.
            if self.config.api_key:
                event=json.loads(json.dumps(event,ensure_ascii=False).replace(
                    self.config.api_key,"[REDACTED]"))
            self.raw_log(event)
