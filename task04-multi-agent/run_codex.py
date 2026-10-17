"""Run task04 with official CLI ChatGPT subscription auth; no API/token forwarding."""
import argparse,asyncio,json
from dataclasses import asdict
from pathlib import Path
from case_input import load_case
from codex_subscription import CodexDualRoleAgent,DEFAULT_CLI,rpc_preflight
from provider import JsonlLog
from verify_run import inspect
from workflow import run
async def main():
    p=argparse.ArgumentParser()
    p.add_argument("--scenario",choices=("normal","forced_conflict","immutable"),default="forced_conflict")
    p.add_argument("--model",help="Optional model supported by your subscription; default CLI choice")
    p.add_argument("--out",required=True)
    args=p.parse_args()
    quota=await rpc_preflight()
    if not quota.get("included_only_confirmed"):
        print(json.dumps({"status":"blocked_before_model_call","preflight":quota},ensure_ascii=False,indent=2))
        return 2
    policy=json.loads(Path(__file__).with_name("policy.json").read_text(encoding="utf-8"))
    case,state=load_case(args.scenario,"llm_runtime",policy["version"])
    out=Path(args.out);out.mkdir(parents=True,exist_ok=False)
    meta={"transport":"codex_cli","auth":"independent_chatgpt_subscription","model":args.model or "CLI default",
          "run_id":state.run_id,"case_input":case,"policy":policy,"company_manual_obtained":False,
          "initial_quota":quota,"cli_install":"@openai/codex@0.162.1"}
    (out/"metadata.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
    agent=CodexDualRoleAgent(policy,JsonlLog(out/"provider.jsonl"),args.model)
    try:
        state=await run(agent,state,timeout=120,total_timeout=600,retries=0,sink=JsonlLog(out/"events.jsonl"))
    finally:
        (out/"state.json").write_text(json.dumps(asdict(state),ensure_ascii=False,indent=2),encoding="utf-8")
    if state.final:
        (out/"outline.md").write_text("# "+state.final["title"]+"\n\n"+"\n\n".join("## "+s for s in state.final["sections"]),encoding="utf-8")
    result=inspect(out)
    print(json.dumps({"status":state.status,"calls":agent.calls,"evidence_checks_passed":all(result["checks"].values())},ensure_ascii=False))
    return 0 if all(result["checks"].values()) else 2
if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
