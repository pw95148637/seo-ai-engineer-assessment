"""Compare raw provider responses with state; not a legal/CTR certification."""
import argparse,json
from pathlib import Path
# Isolated role calls measured 1.7k-17.1k input tokens per API request in the official runs; a leaked
# user/project CLAUDE.md plus MCP instructions measured ~97k (raw output deleted, only the number kept).
# Anything above this ceiling is suspect.
ISOLATION_TOKEN_CEILING=40000
def request_context_tokens(envelope):
    """Largest single API request context (input + cache read/write) inside one CLI call."""
    usage=envelope.get("usage") or {}
    return max(sum(x.get(k) or 0 for k in ("input_tokens","cache_creation_input_tokens","cache_read_input_tokens"))
               for x in (usage.get("iterations") or [usage]))
def inspect(directory):
    root=Path(directory)
    state=json.loads((root/"state.json").read_text(encoding="utf-8"))
    path=root/"provider.jsonl"
    records=[json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    planners=[e for e in state["history"] if e["node"]=="planner"]
    auditors=[e for e in state["history"] if e["node"]=="auditor"]
    role_events=[e for e in state["history"] if e["node"] in ("planner","auditor")]
    raw_success=[]; context_tokens=[]
    for record in records:
        if record.get("error"):
            continue
        try:
            if record.get("transport")=="codex_cli":
                if record.get("returncode")!=0: continue
                value=json.loads(record["response_text"])
                events=[json.loads(line) for line in record["cli_events_jsonl"].splitlines() if line.strip()]
                messages=[x["item"]["text"] for x in events if x.get("type")=="item.completed" and
                          x.get("item",{}).get("type")=="agent_message"]
                if not messages or json.loads(messages[-1])!=value: continue
                if not any(x.get("type")=="turn.completed" for x in events): continue
            elif record.get("transport")=="claude_cli":
                if record.get("returncode")!=0: continue
                envelope=json.loads(record["response_text"])
                if envelope.get("is_error") or envelope.get("subtype")!="success": continue
                value=envelope["structured_output"]
                context_tokens.append(request_context_tokens(envelope))
            else:
                if record.get("http_status")!=200: continue
                envelope=json.loads(record["response_text"])
                value=json.loads(envelope["choices"][0]["message"]["content"])
            raw_success.append((record["role"],record["iteration"],record["run_id"],value))
        except (KeyError,IndexError,TypeError,ValueError):
            continue
    expected=[(e["node"],e["iteration"],state["run_id"],e["output"]) for e in role_events]
    forbidden=("穩賺不賠","保證出金")
    initial=planners[0]["output"] if planners else {}
    final=state.get("final")
    is_immutable=state.get("scenario")=="immutable"
    checks={
        "mode_is_llm_runtime":state["mode"]=="llm_runtime" and bool(records) and all(e.get("mode")=="llm_runtime" for e in records),
        "has_both_roles":set(e["role"] for e in records)=={"planner","auditor"},
        "raw_outputs_match_state":bool(expected) and raw_success==expected,
        "run_ids_match":bool(records) and all(e.get("run_id")==state["run_id"] for e in records),
        "expected_terminal_status":state["status"]==("unsatisfiable" if is_immutable else "approved_provisional"),
        "final_output_contract":final is None if is_immutable else bool(final),
        # Article text only, like the controller guard; negotiation_note may quote dropped words.
        "final_literal_guard_clear":is_immutable or (bool(final) and not any(
            w in final["title"]+"\n"+"\n".join(final["sections"]) for w in forbidden)),
        "raw_responses_saved":bool(records) and all("response_text" in e or "error" in e for e in records),
        # Only meaningful for the Claude CLI transport; other transports have no injected local context.
        "claude_cli_context_isolated":all(t<ISOLATION_TOKEN_CEILING for t in context_tokens)
    }
    if state.get("scenario")=="forced_conflict":
        first_feedback=auditors[0]["output"] if auditors else None
        revision=planners[1] if len(planners)>1 else None
        checks.update({
            "initial_conflict_present":any(w in initial.get("title","") for w in forbidden),
            "first_auditor_rejected":bool(first_feedback) and not first_feedback["passed"],
            "revision_occurred":bool(revision),
            "feedback_carried_to_revision":bool(revision) and revision["input"]["audit"]==first_feedback,
            "draft_changed":bool(final) and final!=initial
        })
    summary={"run_id":state["run_id"],"mode":state["mode"],"status":state["status"],
             "scenario":state["scenario"],"checks":checks,"max_request_context_tokens_per_call":context_tokens,
             "limitations":["模式與原文比對仍不能單獨證明伺服器為真實模型，需核對provider、模型及帳號執行紀錄",
                            "吸引力與語意合規仍需獨立閱讀；本程式不測量CTR或認證法律/公司手冊合規"],
             "negotiation":[{"iteration":a["iteration"],
                             "planner_title":next((x["output"]["title"] for x in planners if x["iteration"]==a["iteration"]),None),
                             "planner_note":next((x["output"].get("negotiation_note") for x in planners if x["iteration"]==a["iteration"]),None),
                             "auditor_passed":a["output"]["passed"],"auditor_note":a["output"].get("note"),
                             "findings":a["output"]["findings"],
                             "controller_guard":[g["output"] for g in state["history"] if g["node"]=="guard" and g["iteration"]==a["iteration"]]}
                            for a in auditors],
             "final":final}
    (root/"verification.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8",newline="\n")
    lines=["# 執行證據摘要",f"模式：{state['mode']}；狀態：{state['status']}；案例：{state['scenario']}",
           "機器檢查："+("全部通過" if all(checks.values()) else "尚未全部通過")]
    lines.extend(f"- {k}：{v}" for k,v in checks.items())
    for turn in summary["negotiation"]:
        lines.append(f"\n## 第 {turn['iteration']} 輪")
        lines.append(f"Planner 標題：{turn['planner_title']}")
        if turn["planner_note"]: lines.append(f"Planner 說明：{turn['planner_note']}")
        lines.append("Auditor 判定："+("通過" if turn["auditor_passed"] else "退回"))
        if turn["auditor_note"]: lines.append(f"Auditor 回應：{turn['auditor_note']}")
        lines.extend(f"- {f['quote']}：{f['reason']}；建議：{f['revision']}（{f['rule']}）" for f in turn["findings"])
        lines.extend(f"- controller 字面防線改判退回：{g['findings']}" for g in turn["controller_guard"])
    lines.extend(["\n仍需人工核對：真實模型來源、內容吸引力、語意誤導與公司手冊缺口。"])
    (root/"summary.md").write_text("\n".join(lines)+"\n",encoding="utf-8",newline="\n")
    return summary
if __name__=="__main__":
    import sys
    sys.stdout.reconfigure(errors="backslashreplace")  # Windows consoles may not be UTF-8
    p=argparse.ArgumentParser();p.add_argument("directory")
    result=inspect(p.parse_args().directory)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if all(result["checks"].values()) else 2)
