"""Run task04 through the official Claude Code CLI with the existing subscription login.

--check prints configuration and CLI version only; it makes NO model request.
"""
import argparse, asyncio, hashlib, importlib, json, sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from case_input import load_case
from claude_subscription import (ClaudeDualRoleAgent, DEFAULT_EFFORT, DEFAULT_MODEL, ISOLATION_FLAGS,
                                 cli_version, default_cli)
from provider import JsonlLog
from verify_run import inspect
from workflow import ProviderError, run

HERE = Path(__file__).resolve().parent
ROLE_MODULES = {"v6": "roles", "v7": "roles_v7"}

def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scenario", choices=("normal", "forced_conflict", "immutable"), default="forced_conflict")
    p.add_argument("--model", default=DEFAULT_MODEL, help="Same model for Planner and Auditor")
    p.add_argument("--effort", default=DEFAULT_EFFORT, choices=("low", "medium", "high", "xhigh", "max"))
    p.add_argument("--out", help="New directory; never overwrites earlier evidence (required unless --check)")
    p.add_argument("--timeout", type=float, default=240, help="Seconds per role call")
    p.add_argument("--total-timeout", type=float, default=1200)
    p.add_argument("--prompts", choices=("v6", "v7"), default="v6",
                   help="Role prompt version: v6 = roles.py (official results), v7 = roles_v7.py")
    p.add_argument("--check", action="store_true")
    return p

def file_sha(name):
    return hashlib.sha256((HERE / name).read_bytes()).hexdigest()

async def execute(args, cli=None):
    cli = cli or default_cli()
    version = cli_version(cli)
    if args.check:
        print(json.dumps({"check": "configuration_only", "model_requests": 0, "cli_version": version,
                          "model": args.model, "effort": args.effort, "isolation_flags": ISOLATION_FLAGS},
                         ensure_ascii=False))
        return 0
    if not args.out:
        raise ValueError("--out is required for a model run")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    policy = json.loads((HERE / "policy.json").read_text(encoding="utf-8"))
    case, state = load_case(args.scenario, "llm_runtime", policy["version"])
    meta = {"started_at": datetime.now(timezone.utc).isoformat(), "mode": "llm_runtime",
            "transport": "claude_cli", "cli_version": version,
            "auth": "existing Claude Code subscription login on this machine; no API key, token or credential file read",
            "cost_note": "total_cost_usd in raw replies is the CLI list-price estimate, not a subscription charge",
            "planner_model": args.model, "auditor_model": args.model, "effort": args.effort,
            "same_model_reason": "Both roles use one model so differences come from role prompts and State only",
            "isolation_flags": ISOLATION_FLAGS, "per_call_timeout_s": args.timeout,
            "total_timeout_s": args.total_timeout, "retries_per_call": 1, "run_id": state.run_id,
            "roles_py_sha256": file_sha("roles.py"), "workflow_py_sha256": file_sha("workflow.py"),
            "prompt_version": args.prompts, "roles_module": ROLE_MODULES[args.prompts] + ".py",
            "roles_module_sha256": file_sha(ROLE_MODULES[args.prompts] + ".py"),
            "policy": policy, "case_input": case,
            "policy_sha256": hashlib.sha256(json.dumps(policy, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            "company_manual_obtained": False}
    (out / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    agent = ClaudeDualRoleAgent(policy, JsonlLog(out / "provider.jsonl"), args.model, args.effort, cli,
                                roles=importlib.import_module(ROLE_MODULES[args.prompts]))
    try:
        state = await run(agent, state, timeout=args.timeout, retries=1, total_timeout=args.total_timeout,
                          backoff=5, sink=JsonlLog(out / "events.jsonl"))
    finally:
        (out / "state.json").write_text(json.dumps(asdict(state), ensure_ascii=False, indent=2), encoding="utf-8")
    if state.final:
        (out / "outline.md").write_text("# " + state.final["title"] + "\n\n" + "\n\n".join(
            "## " + s for s in state.final["sections"]) + "\n", encoding="utf-8")
    verification = inspect(out)
    passed = all(verification["checks"].values())
    print(json.dumps({"status": state.status, "iteration": state.iteration, "calls": agent.calls,
                      "out": str(out), "evidence_checks_passed": passed}, ensure_ascii=False))
    return 0 if passed else 2

def main():
    try:
        return asyncio.run(execute(parser().parse_args()))
    except (ValueError, OSError, ProviderError) as e:
        print(str(e), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
