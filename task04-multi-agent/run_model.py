"""Explicit user-selected provider; --check performs NO HTTP/model request."""
import argparse
import getpass
import asyncio
import json
import hashlib
import os
import sys
from dataclasses import asdict
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from provider import Config,DualRoleAgent,JsonlLog
from workflow import run
from case_input import load_case
from verify_run import inspect

def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url",required=True)
    p.add_argument("--model",required=True)
    p.add_argument("--auditor-model")
    p.add_argument("--key-env",default="TASK04_API_KEY")
    p.add_argument("--prompt-key",action="store_true",help="Read provider key privately in your local terminal")
    p.add_argument("--access",choices=("local","confirmed-free","approved-paid"),required=True,
                   help="User-confirmed billing basis. This flag cannot verify provider billing.")
    p.add_argument("--scenario",choices=("normal","forced_conflict","immutable"),default="forced_conflict")
    p.add_argument("--out",default="evidence/runtime")
    p.add_argument("--check",action="store_true")
    return p

async def execute(args):
    key=getpass.getpass("Provider API key (hidden): ") if args.prompt_key else os.getenv(args.key_env,"")
    local=urlsplit(args.base_url).hostname in ("127.0.0.1","localhost","::1")
    if args.access=="local" and not local:
        raise ValueError("local access requires a loopback endpoint")
    if not local and not key:
        raise ValueError("Missing explicit provider key in "+args.key_env)
    cfg=Config(args.base_url,args.model,args.auditor_model or args.model,key)
    if args.check:
        print(json.dumps({"check":"configuration_only","model_requests":0,"access":args.access,
                          "planner_model":cfg.planner_model,"auditor_model":cfg.auditor_model,
                          "key_present":bool(key)},ensure_ascii=False))
        return 0
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=False)
    policy=json.loads(Path(__file__).with_name("policy.json").read_text(encoding="utf-8"))
    case,state=load_case(args.scenario,"llm_runtime",policy["version"])
    meta={"started_at":datetime.now(timezone.utc).isoformat(),"mode":"llm_runtime",
          "access_basis":args.access,"base_url":cfg.base_url,"planner_model":cfg.planner_model,
          "auditor_model":cfg.auditor_model,"max_calls":cfg.max_calls,
          "max_output_tokens_per_call":cfg.max_output_tokens,"run_id":state.run_id,
          "policy":policy,"case_input":case,
          "policy_sha256":hashlib.sha256(json.dumps(policy,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
          "company_manual_obtained":False}
    (out/"metadata.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
    async with httpx.AsyncClient(timeout=30,follow_redirects=False,trust_env=False) as client:
        agent=DualRoleAgent(cfg,client,policy,JsonlLog(out/"provider.jsonl"))
        try:
            state=await run(agent,state,sink=JsonlLog(out/"events.jsonl"))
        finally:
            (out/"state.json").write_text(json.dumps(asdict(state),ensure_ascii=False,indent=2),encoding="utf-8")
    if state.final:
        (out/"outline.md").write_text("# "+state.final["title"]+"\n\n"+"\n\n".join(
            "## "+s for s in state.final["sections"]),encoding="utf-8")
    verification=inspect(out)
    print(json.dumps({"status":state.status,"iteration":state.iteration,"calls":agent.calls,
                      "out":str(out),"evidence_checks_passed":all(verification["checks"].values())},ensure_ascii=False))
    return 0 if all(verification["checks"].values()) else 2

def main():
    try:
        return asyncio.run(execute(parser().parse_args()))
    except (ValueError,OSError) as e:
        print(str(e),file=sys.stderr)
        return 2
if __name__=="__main__":
    raise SystemExit(main())
