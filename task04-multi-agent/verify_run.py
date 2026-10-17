"""Compare raw provider responses with state; not a legal/CTR certification."""
import argparse,json
from pathlib import Path
from workflow_v8 import attached,derive_review,flatten,must_rule_ids,program_findings
# Isolated role calls measured 1.7k-17.1k input tokens per API request in the official runs; a leaked
# user/project CLAUDE.md plus MCP instructions measured ~97k (raw output deleted, only the number kept).
# Anything above this ceiling is suspect.
ISOLATION_TOKEN_CEILING=40000
def request_context_tokens(envelope):
    """Largest single API request context (input + cache read/write) inside one CLI call."""
    usage=envelope.get("usage") or {}
    return max(sum(x.get(k) or 0 for k in ("input_tokens","cache_creation_input_tokens","cache_read_input_tokens"))
               for x in (usage.get("iterations") or [usage]))
def tiered_checks(root,state,planners,auditors,decisions):
    """v8: recompute every decision from the raw outputs and the run's policy; levels never come from a model."""
    policy=json.loads((root/"metadata.json").read_text(encoding="utf-8"))["policy"]
    drafts={e["iteration"]:e["output"] for e in planners}
    audits={e["iteration"]:e["output"] for e in auditors}
    recomputed=[derive_review(d["iteration"],program_findings(drafts[d["iteration"]],policy),audits[d["iteration"]],policy)
                for d in decisions if d["iteration"] in drafts and d["iteration"] in audits]
    final=state.get("final")
    return {
        "decisions_recomputed_from_policy":bool(decisions) and recomputed==[d["review"] for d in decisions],
        "every_blocking_item_is_must":all(m["source"]=="program" or m["rule"] in must_rule_ids(policy)
                                          for d in decisions for m in d["review"]["must"]),
        "no_round_for_should_only":all(d["review"]["must"] for d in decisions if d["action"] in ("revise","human_review")),
        "should_never_blocks":all(d["action"] in ("approve_provisional","unsatisfiable") for d in decisions if not d["review"]["must"]),
        "final_attaches_unadopted_suggestions":final is None or final.get("attached_suggestions")==attached(state["suggestions"]),
        "final_program_checks_clear":final is None or program_findings(final,policy)==[]}

def planner_saw_review(records,state,decisions):
    """Second Planner call's raw user prompt holds the first round's review verbatim."""
    rec=[r for r in records if r.get("role")=="planner" and r.get("iteration")==2 and not r.get("error")]
    if not rec or not decisions: return False
    return json.loads(rec[-1]["request"]["user_prompt"])["context"].get("review")==decisions[0]["review"]

def tiered_turn_lines(turn):
    review=turn["review"] or {"must":[],"should":[]}
    out=[f"- MUST {m['id']}（{'程式' if m['source']=='program' else 'Auditor'}，{m['rule']}）{m['quote']}：{m['reason']}；建議：{m['revision']}"
         for m in review["must"]]
    out+=[f"- SHOULD {s['id']}：{s['suggestion']}" for s in review["should"]]
    out+=[f"- Planner 對 {r['id']}：{r['action']}"+(f"，{r['reason']}" if r.get("reason") else "") for r in turn["suggestion_responses"] or []]
    return out

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
    # v8 runs (workflow_v8.TieredState) carry a review; their decisions are recomputed in tiered_checks.
    tiered="review" in state
    decisions=[e for e in state["history"] if e["node"]=="decision"]
    checks={
        "mode_is_llm_runtime":state["mode"]=="llm_runtime" and bool(records) and all(e.get("mode")=="llm_runtime" for e in records),
        "has_both_roles":set(e["role"] for e in records)=={"planner","auditor"},
        "raw_outputs_match_state":bool(expected) and raw_success==expected,
        "run_ids_match":bool(records) and all(e.get("run_id")==state["run_id"] for e in records),
        "expected_terminal_status":state["status"]==("unsatisfiable" if is_immutable else "approved_provisional"),
        "final_output_contract":final is None if is_immutable else bool(final),
        # Article text only, like the controller guard; negotiation_note may quote dropped words.
        "final_literal_guard_clear":is_immutable or (bool(final) and not any(
            w in final["title"]+"\n"+"\n".join(flatten(x) for x in final["sections"]) for w in forbidden)),
        "raw_responses_saved":bool(records) and all("response_text" in e or "error" in e for e in records),
        # Only meaningful for the Claude CLI transport; other transports have no injected local context.
        "claude_cli_context_isolated":all(t<ISOLATION_TOKEN_CEILING for t in context_tokens)
    }
    if state.get("scenario")=="forced_conflict":
        first_feedback=auditors[0]["output"] if auditors else None
        revision=planners[1] if len(planners)>1 else None
        checks.update({
            "initial_conflict_present":any(w in initial.get("title","") for w in forbidden),
            **({"first_round_blocked":bool(decisions) and decisions[0]["review"]["blocked"]} if tiered else
               {"first_auditor_rejected":bool(first_feedback) and not first_feedback["passed"]}),
            "revision_occurred":bool(revision),
            # v8: the Planner prompt carries review (not audit); compare what the raw prompt really contained.
            "feedback_carried_to_revision":bool(revision) and (planner_saw_review(records,state,decisions) if tiered
                                                                else revision["input"]["audit"]==first_feedback),
            "draft_changed":bool(final) and ({k:final[k] for k in ("title","sections")}!=
                                             {k:initial.get(k) for k in ("title","sections")} if tiered else final!=initial)
        })
    if tiered:
        checks.update(tiered_checks(root,state,planners,auditors,decisions))
    summary={"run_id":state["run_id"],"mode":state["mode"],"status":state["status"],
             "scenario":state["scenario"],"checks":checks,"max_request_context_tokens_per_call":context_tokens,
             "limitations":["模式與原文比對仍不能單獨證明伺服器為真實模型，需核對provider、模型及帳號執行紀錄",
                            "吸引力與語意合規仍需獨立閱讀；本程式不測量CTR或認證法律/公司手冊合規"],
             "negotiation":[{"iteration":a["iteration"],
                             "planner_title":next((x["output"]["title"] for x in planners if x["iteration"]==a["iteration"]),None),
                             "planner_note":next((x["output"].get("negotiation_note") for x in planners if x["iteration"]==a["iteration"]),None),
                             "auditor_passed":(not next((d["review"]["blocked"] for d in decisions if d["iteration"]==a["iteration"]),True)) if tiered else a["output"]["passed"],"auditor_note":a["output"].get("note"),
                             "findings":a["output"]["findings"],
                             "controller_guard":[g["output"] for g in state["history"] if g["node"]=="guard" and g["iteration"]==a["iteration"]],
                             **({"review":next((d["review"] for d in decisions if d["iteration"]==a["iteration"]),None),
                                 "suggestion_responses":next((x["output"].get("suggestion_responses") for x in planners
                                                              if x["iteration"]==a["iteration"]),None)} if tiered else {})}
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
        lines.append(("判定（只有 MUST 退回）：" if tiered else "Auditor 判定：")+("通過" if turn["auditor_passed"] else "退回"))
        if turn["auditor_note"]: lines.append(f"Auditor 回應：{turn['auditor_note']}")
        if tiered:
            lines.extend(tiered_turn_lines(turn))
            continue
        lines.extend(f"- {f['quote']}：{f['reason']}；建議：{f['revision']}（{f['rule']}）" for f in turn["findings"])
        lines.extend(f"- controller 字面防線改判退回：{g['findings']}" for g in turn["controller_guard"])
    if tiered and final and final.get("attached_suggestions"):
        lines.append("\n## 定稿附上的建議（SHOULD，未採納或未處理）")
        lines.extend(f"- {x['id']}（{x['status']}）{x['suggestion']}"+(f"；Planner：{x['planner_reason']}" if x.get("planner_reason") else "")
                     for x in final["attached_suggestions"])
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
