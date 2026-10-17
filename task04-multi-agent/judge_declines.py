"""Independent judge for the suggestions a Planner declined (v8.1 experiment, condition 5). Model call, isolated.

Every declined suggestion from the given runs is shown anonymously, in seeded order, with the outline the
suggestion was about, the three MUST rules and the Planner's reason. One isolated `claude -p` call (same isolation
as the role calls and blind raters: no tools, empty working directory, input on stdin) judges each against
criteria written before any v8.1 run:
  (a) the reason names a concrete effect on readers' clicks or reading value for this outline (not a stance);
  (b) the suggestion is really about a compliance problem under the three MUST rules.
The judge is not told which version or run an item comes from, or what result is hoped for.

usage: python judge_declines.py --runs <run_dir> ... --seed N --out <judgments.json> --raw <raw.json> --key <key.json>
"""
import argparse, asyncio, hashlib, json, random, sys, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
from claude_subscription import (DEFAULT_EFFORT, DEFAULT_MODEL, ISOLATION_FLAGS, build_command, cli_version,
                                 default_cli, run_cli)
from verify_run import ISOLATION_TOKEN_CEILING, request_context_tokens
from workflow_v8 import flatten

HERE = Path(__file__).resolve().parent
SYSTEM = "你是一位獨立的審閱者，第一次看到這些內容。依使用者訊息中的判準逐項判斷，結果寫在 judgments，每項一個物件。"
JUDGMENT = {"type": "object", "properties": {
    "id": {"type": "string"},
    "reader_specific_reason": {"type": "boolean"}, "reason_note": {"type": "string"},
    "involves_must": {"type": "boolean"}, "must_note": {"type": "string"}},
    "required": ["id", "reader_specific_reason", "reason_note", "involves_must", "must_note"], "additionalProperties": False}
SCHEMA = {"type": "object", "properties": {"judgments": {"type": "array", "items": JUDGMENT}},
          "required": ["judgments"], "additionalProperties": False}
CRITERIA = """# 審閱：寫作者不採納建議的理由

一位寫作者在規劃「娛樂城推薦」文章大綱，審核者給了建議，寫作者決定不採納並寫下理由。請逐項判斷兩件事：

1. reader_specific_reason：寫作者的理由，有沒有針對這份大綱，說出採納建議會對讀者的點擊意願或閱讀價值造成什麼具體影響？只是表態（例如「我有自己的判斷」「不需要」）、只談流程或規則、或理由與這份大綱無關，都算沒有。
2. involves_must：被拒絕的建議本身，是不是其實在處理下面三條規則所禁止的問題（也就是一個應該修正的違規，而不只是讓文章更好的選項）？

附一句話說明各自的判斷。

## 三條規則

{rules}

## 待判斷的項目
"""


def collect(runs):
    items = []
    for run in runs:
        state = json.loads((Path(run) / "state.json").read_text(encoding="utf-8"))
        drafts = {e["iteration"]: e["output"] for e in state["history"] if e["node"] == "planner"}
        for x in state.get("suggestions", []):
            if x["status"] != "declined":
                continue
            draft = drafts[x["round"]]
            items.append({"run": Path(run).name, "suggestion_id": x["id"], "round": x["round"],
                          "suggestion": x["suggestion"], "reason": x.get("planner_reason", ""),
                          "outline": {"title": draft["title"], "sections": [flatten(s) for s in draft["sections"]]}})
    return items


def render(items, policy):
    rules = "\n".join(f"- **{r['id']}**：{r['instruction']}" for r in policy["rules"])
    parts = [CRITERIA.format(rules=rules)]
    for item in items:
        body = "\n".join(f"{i}. {s}" for i, s in enumerate(item["outline"]["sections"], 1))
        parts.append(f"### 項目 {item['id']}\n\n大綱標題：{item['outline']['title']}\n\n{body}\n\n"
                     f"審核者的建議：{item['suggestion']}\n\n寫作者不採納的理由：{item['reason'] or '（未寫理由）'}\n")
    return "\n".join(parts)


async def call(text, cli, timeout=900, budget=3.0):
    with tempfile.TemporaryDirectory(prefix="task04-judge-") as temp:
        system_file = Path(temp) / "system.txt"
        system_file.write_text(SYSTEM, encoding="utf-8")
        cwd = Path(temp) / "cwd"
        cwd.mkdir()
        command = build_command(cli, system_file, SCHEMA, DEFAULT_MODEL, DEFAULT_EFFORT, budget)
        started = time.monotonic()
        code, stdout, stderr = await asyncio.wait_for(run_cli(command, text, cwd), timeout)
    return code, stdout, stderr, round(time.monotonic() - started, 3)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--seed", type=int, required=True)
    for name in ("--out", "--raw", "--key"):
        ap.add_argument(name, required=True)
    args = ap.parse_args()
    for path in (args.out, args.raw, args.key):
        if Path(path).exists():
            raise SystemExit(f"{path} exists; judgments are never overwritten")
    items = collect(args.runs)
    random.Random(args.seed).shuffle(items)
    for n, item in enumerate(items, 1):
        item["id"] = f"D{n}"
    for path in (args.out, args.raw, args.key):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(args.key).write_text(json.dumps({"seed": args.seed, "items": [{k: i[k] for k in ("id", "run", "suggestion_id", "round")}
                                                                        for i in items]}, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8", newline="\n")
    if not items:
        Path(args.out).write_text("[]\n", encoding="utf-8", newline="\n")
        Path(args.raw).write_text(json.dumps({"note": "no declined suggestions; no model call"}) + "\n", encoding="utf-8")
        print(json.dumps({"declined": 0}))
        return 0
    policy = json.loads((HERE / "policy_v8.json").read_text(encoding="utf-8"))
    text = render(items, policy)
    cli = default_cli()
    code, stdout, stderr, elapsed = asyncio.run(call(text, cli))
    envelope = json.loads(stdout)
    tokens = request_context_tokens(envelope)
    raw = {"at": datetime.now(timezone.utc).isoformat(), "cli_version": cli_version(cli), "model": DEFAULT_MODEL,
           "effort": DEFAULT_EFFORT, "isolation_flags": ISOLATION_FLAGS, "system_prompt": SYSTEM, "input_text": text,
           "input_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "returncode": code,
           "elapsed_seconds": elapsed, "max_request_context_tokens": tokens,
           "context_isolated": tokens < ISOLATION_TOKEN_CEILING, "response_text": stdout, "cli_stderr": stderr}
    Path(args.raw).write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    if code != 0 or envelope.get("is_error") or envelope.get("subtype") != "success":
        print("judge call failed; raw reply saved", file=sys.stderr)
        return 2
    judgments = envelope["structured_output"]["judgments"]
    Path(args.out).write_text(json.dumps(judgments, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"declined": len(items), "judged": len(judgments), "context_isolated": raw["context_isolated"]}))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="backslashreplace")
    raise SystemExit(main())
