"""Measurements and the adoption decision for the v8 experiment (evidence/tiered-v8/PREREGISTRATION.md). No model calls.

  analyze  <run_dir> ... --out analysis.json
      M1/M2 exactly as analyze_balance.py (v7), extended to v8 outlines (heading/points sections) and v8 texts:
      Planner text also includes suggestion_responses; Auditor-originated text also includes suggestions (SHOULD).
      For v6/v7 runs the numbers equal analyze_balance.py's (test_tiered_v8.py checks this). M1 is also reported for
      the body alone, because v8 hands the guard words in the title to code. Adds the tier metrics.
  package  --item <run_dir>:final|round1 ... --seed N --package <file.md> --reversed <file.md> --key <file.json>
      Anonymised outlines in seeded order (same labels in reverse order for the second rater) and the MUST rules of
      policy_v8.json. Every section is shown as "heading：points"; v6 string sections are split with the registered
      rule first, so the two versions look alike. The key goes to a different folder.
  score    --prereg prereg.json --key --analysis --ratings <r1.json> <r2.json> --probe <dir> --company <dir> --out
      Checks that every registered run, case and hash is present, then applies the registered conditions.
"""
import argparse
import json
import random
import statistics
import string
from pathlib import Path
from analyze_balance import ADOPT_RUN, FORBIDDEN, WINDOW, auditor_windows, coverage, longest_run, norm
from workflow_v8 import flatten, split_v6_section

HERE = Path(__file__).resolve().parent
V5 = json.loads((HERE / "policy.json").read_text(encoding="utf-8"))
V5_MUST_TEXT = {r["id"]: r["instruction"] for r in V5["rules"] if r["id"] in ("CLAIMS", "EVIDENCE", "LEGAL")}
BALANCE_CLAIM_MARGIN = 0.15   # same improvement margin the v7 plan required


def draft_text(draft):
    draft = draft or {}
    return norm(draft.get("title", "") + "".join(flatten(s) for s in draft.get("sections", [])))


def planner_text(output):
    extra = (output.get("negotiation_note") or "") + "".join(
        (r.get("wording") or "") + (r.get("quote") or "") for r in output.get("responses") or []) + "".join(
        r.get("reason") or "" for r in output.get("suggestion_responses") or [])
    return draft_text(output) + norm(extra)


def median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def analyze(directory):
    root = Path(directory)
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    meta = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    ver_path = root / "verification.json"
    verification = json.loads(ver_path.read_text(encoding="utf-8")) if ver_path.exists() else {"checks": {}}
    planners = {e["iteration"]: e["output"] for e in state["history"] if e["node"] == "planner"}
    auditors = {e["iteration"]: e["output"] for e in state["history"] if e["node"] == "auditor"}

    all_windows, findings_out = set(), []
    for r in sorted(auditors):
        prior = "".join(planner_text(planners[i]) for i in planners if i <= r)
        for x in auditors[r].get("suggestions") or []:          # v8 SHOULD text is Auditor-originated too
            all_windows |= auditor_windows(x, prior)
        for f in auditors[r]["findings"]:
            w = auditor_windows(f["revision"], prior)
            all_windows |= w
            row = {"round": r, "quote": f["quote"], "rule": f["rule"], "outcome": None}
            if r + 1 in planners:
                nxt = draft_text(planners[r + 1])
                if longest_run(coverage(nxt, w)) >= ADOPT_RUN:
                    row["outcome"] = "adopted"
                elif f["quote"] and norm(f["quote"]) in nxt:
                    row["outcome"] = "kept"
                    again = [norm(g["quote"]) for g in auditors.get(r + 1, {}).get("findings", [])]
                    row["defence_accepted"] = (r + 1 in auditors) and norm(f["quote"]) not in again
                else:
                    row["outcome"] = "own"
            findings_out.append(row)

    final = state.get("final")
    m1 = None
    if final:
        text, title = draft_text(final), norm(final["title"])
        body = draft_text({"sections": final["sections"]})
        m1 = {"auditor_share": round(sum(coverage(text, all_windows)) / len(text), 4),
              "auditor_share_title": round(sum(coverage(title, all_windows)) / len(title), 4), "chars": len(text),
              "auditor_share_body": round(sum(coverage(body, all_windows)) / len(body), 4) if body else None}
    judged = [x for x in findings_out if x["outcome"]]
    own_or_def = sum(x["outcome"] == "own" for x in judged) + sum(bool(x.get("defence_accepted")) for x in judged)
    m2 = {"findings_with_next_draft": len(judged),
          "adopted": sum(x["outcome"] == "adopted" for x in judged), "kept": sum(x["outcome"] == "kept" for x in judged),
          "own": sum(x["outcome"] == "own" for x in judged),
          "defence_accepted": sum(bool(x.get("defence_accepted")) for x in judged),
          "own_or_accepted_defence_ratio": round(own_or_def / len(judged), 4) if judged else None}

    policy = meta.get("policy", {})
    must_text = {r["id"]: r["instruction"] for r in policy.get("rules", []) if r["id"] in V5_MUST_TEXT}
    checks = verification.get("checks", {})
    final_text = (final["title"] + "".join(flatten(s) for s in final["sections"])) if final else ""
    m4 = {"status": state["status"], "machine_checks_all_pass": bool(checks) and all(checks.values()),
          "failed_checks": [k for k, v in checks.items() if not v],
          "must_rule_text_unchanged_from_v5": must_text == V5_MUST_TEXT,
          "final_literal_guard_clear": bool(final) and not any(t in final_text for t in FORBIDDEN)}

    tiers = None
    if "review" in state:
        decisions = [e for e in state["history"] if e["node"] == "decision"]
        ledger = state.get("suggestions", [])
        tiers = {
            "rounds": [{"round": d["iteration"], "action": d["action"],
                        "must_program": sum(m["source"] == "program" for m in d["review"]["must"]),
                        "must_auditor": sum(m["source"] == "auditor" for m in d["review"]["must"]),
                        "must_rules": sorted({m["rule"] for m in d["review"]["must"]}),
                        "should": len(d["review"]["should"])} for d in decisions],
            "rounds_back_without_must": sum(1 for d in decisions
                                            if d["action"] in ("revise", "human_review") and not d["review"]["must"]),
            "suggestions": {k: sum(x["status"] == k for x in ledger) for k in ("adopted", "declined", "unanswered", "open")},
            "declined": [{"id": x["id"], "suggestion": x["suggestion"], "reason": x.get("planner_reason", "")}
                         for x in ledger if x["status"] == "declined"],
            "attached_to_final": final.get("attached_suggestions", []) if final else None}
    return {"run": root.name, "scenario": state["scenario"], "prompt_version": meta.get("prompt_version", "v6"),
            "cli_version": meta.get("cli_version"), "rounds": state["iteration"],
            "converged_within_limit": state["status"] == "approved_provisional",
            "hashes": {k: meta.get(k) for k in ("roles_module_sha256", "controller_module_sha256", "policy_sha256")},
            "models_returned": sorted({m for line in (root / "provider.jsonl").read_text(encoding="utf-8").splitlines()
                                       if line.strip() for m in json.loads(line).get("model_returned") or []}),
            "m1": m1, "m2": m2, "m4": m4, "tiers": tiers, "findings": findings_out}


INSTRUCTIONS = """# 文章大綱評分

下面有 {n} 份「娛樂城推薦」文章大綱（標題與段落要點，每段寫成「小標：要點」），以英文字母標示。請逐份獨立評分，不要回頭依其他份調整分數。

## 1. 點擊吸引力（1 到 5 分）

假設你是在 Google 搜尋「娛樂城推薦」的台灣讀者：搜尋結果先看到標題，點進來後看到這份大綱。你多想點進來並讀下去？1 完全不想點，3 普通，5 非常想點。只評吸引力，不管內容是否合規。附一句理由。

## 2. 閱讀價值（1 到 5 分）

讀完這篇文章，讀者能得到多少具體、可用的資訊？1 幾乎沒有，3 普通，5 非常具體可用。只評閱讀價值，不管是否合規。附一句理由。

## 3. 合規

依下面三條規則，列出大綱中違反規則的原句（逐字引用）、規則代號與理由；沒有違規就給空陣列。只看標題與大綱本身。

{rules}

## 輸出

每份大綱一個物件：label（稿的字母）、click_appeal（1–5 的整數）、click_reason（一句理由）、reading_value（1–5 的整數）、reading_reason（一句理由）、violations（陣列，每項含 quote 原句、rule 規則代號、reason 理由；沒有違規給空陣列）。

## 大綱
"""


def rendered_sections(sections):
    """Uniform presentation: v6 strings are split with the registered rule, then everything is "heading：points"."""
    return [flatten(split_v6_section(s) if isinstance(s, str) else s) for s in sections]


def outline(spec):
    run_dir, which = spec.rsplit(":", 1)
    state = json.loads((Path(run_dir) / "state.json").read_text(encoding="utf-8"))
    meta = json.loads((Path(run_dir) / "metadata.json").read_text(encoding="utf-8"))
    draft = state["final"] if which == "final" else next(
        e["output"] for e in state["history"] if e["node"] == "planner" and e["iteration"] == 1)
    if not draft:
        raise SystemExit(f"{run_dir} has no final outline")
    return ({"title": draft["title"], "sections": rendered_sections(draft["sections"])},
            {"run": Path(run_dir).name, "which": which, "prompt_version": meta.get("prompt_version", "v6"),
             "scenario": state["scenario"], "status": state["status"]})


def package(args):
    if Path(args.key).resolve().parent in (Path(args.package).resolve().parent, Path(args.reversed).resolve().parent):
        raise SystemExit("keep the key outside the package folder")
    items = [outline(s) for s in args.item]
    random.Random(args.seed).shuffle(items)
    policy = json.loads((HERE / "policy_v8.json").read_text(encoding="utf-8"))
    rules = "\n".join(f"- **{r['id']}**：{r['instruction']}" for r in policy["rules"])
    rules += "\n- 兩個指定詞（literal_guard_terms）：" + "、".join(policy["program_checks"]["literal_guard_terms"]["terms"])
    labelled = list(zip(string.ascii_uppercase, items))
    for path, order in ((args.package, labelled), (args.reversed, labelled[::-1])):
        parts = [INSTRUCTIONS.format(n=len(items), rules=rules)]
        for label, (text, _) in order:
            body = "\n".join(f"{i}. {s}" for i, s in enumerate(text["sections"], 1))
            parts.append(f"### 稿 {label}\n\n**標題：{text['title']}**\n\n{body}\n")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text("\n".join(parts), encoding="utf-8", newline="\n")
    key = {"seed": args.seed, "items": args.item, "labels": {label: src for label, (_, src) in labelled},
           "reversed_order": [label for label, _ in labelled[::-1]]}
    Path(args.key).parent.mkdir(parents=True, exist_ok=True)
    Path(args.key).write_text(json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {args.package}, {args.reversed} ({len(items)} outlines) and {args.key}")


def load_rating(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = data["ratings"] if isinstance(data, dict) else data
    return {row["label"]: row for row in rows}


def completeness(prereg, analysis, key, raters, probe, company, rater_raw):
    """Everything registered must be present and unchanged; any gap means the experiment is incomplete."""
    reg, sha = prereg["registered"], prereg["file_sha256"]
    gaps = []
    runs = {r["run"]: r for r in analysis}
    expected = reg["v6_baseline"] + [reg["v6_drift"]] + reg["v8_conflict"] + [reg["v8_normal"]]
    if sorted(runs) != sorted(expected):
        gaps.append(f"analysis runs {sorted(runs)} != registered {sorted(expected)}")
    for name in reg["v8_conflict"] + [reg["v8_normal"]]:
        h = (runs.get(name) or {}).get("hashes", {})
        if (h.get("roles_module_sha256"), h.get("controller_module_sha256"), h.get("policy_sha256")) != (
                sha["roles_v8.py"], sha["workflow_v8.py"], prereg["policy_v8_sha256"]):
            gaps.append(f"{name}: code or policy hash differs from registration")
    finals = {(s["run"], s["which"]) for s in key.values()}
    for name in reg["v6_baseline"] + [r for r in reg["v8_conflict"] + [reg["v8_normal"], reg["v6_drift"]]
                                      if (runs.get(r) or {}).get("converged_within_limit")]:
        if (name, "final") not in finals:
            gaps.append(f"{name}: final missing from the blind package")
    for i, rater in enumerate(raters, 1):
        if set(rater) != set(key):
            gaps.append(f"rater {i} labels {sorted(rater)} != package labels {sorted(key)}")
    if not all(r.get("context_isolated") for r in rater_raw):
        gaps.append("a rater call was not isolated")
    cases = json.loads((HERE / "cases/auditor_probe_v8.json").read_text(encoding="utf-8"))["cases"]
    if [r["id"] for r in probe["results"]] != [c["id"] for c in cases] or probe["errors"]:
        gaps.append("probe results do not cover every registered case without error")
    if probe.get("expectations_sha256") != sha["cases/auditor_probe_v8.json"] or \
            probe.get("roles_module_sha256") != sha["roles_v8.py"]:
        gaps.append("probe ran with other cases or prompts than registered")
    if len(company["results"]) != 10 or company["errors"] or \
            company.get("expectations_sha256") != sha["cases/company_samples_v8.json"] or \
            company.get("selected_rows_sha256") != reg["company_rows_sha256"]:
        gaps.append("company samples incomplete, or other expectations or snippets than registered")
    return gaps


def decide(prereg, key, analysis, raters, probe, company, rater_raw=()):
    reg = prereg["registered"]
    items = {}
    for label, src in key.items():
        rows = [r[label] for r in raters if label in r]
        if len(rows) != len(raters):
            continue
        flags = [bool(r.get("violations")) for r in rows]
        rules = [{v["rule"] for v in r.get("violations") or []} for r in rows]
        items[label] = {**src, "click": statistics.mean(float(r["click_appeal"]) for r in rows),
                        "click_by_rater": [r["click_appeal"] for r in rows],
                        "reading": statistics.mean(float(r["reading_value"]) for r in rows),
                        "reading_by_rater": [r["reading_value"] for r in rows],
                        "violation": "both" if all(flags) else ("disputed" if any(flags) else "none"),
                        "same_rule_both": bool(rules) and bool(set.intersection(*rules)),
                        "violations_by_rater": [r.get("violations") or [] for r in rows]}

    def finals(names):
        return [v for v in items.values() if v["which"] == "final" and v["run"] in names]

    runs = {r["run"]: r for r in analysis}
    v6, v8 = finals(reg["v6_baseline"]), finals(reg["v8_conflict"])
    v8_all = finals(reg["v8_conflict"] + [reg["v8_normal"]])
    v8_runs = [runs[n] for n in reg["v8_conflict"] if n in runs]
    normal = runs.get(reg["v8_normal"])
    m1_v6 = median((runs[n]["m1"] or {}).get("auditor_share") for n in reg["v6_baseline"] if n in runs)
    m1_v8 = median((r["m1"] or {}).get("auditor_share") for r in v8_runs)
    probe_must = [r for r in probe["results"] if r["expect"] == "must"]
    probe_free = [r for r in probe["results"] if r["expect"] == "no_block"]
    company_clear = [r for r in company["results"] if r["class"] == "clear"]
    gaps = completeness(prereg, analysis, key, raters, probe, company, rater_raw)
    med = {"click_v6": median(v["click"] for v in v6), "click_v8": median(v["click"] for v in v8),
           "reading_v6": median(v["reading"] for v in v6), "reading_v8": median(v["reading"] for v in v8),
           "m1_v6": m1_v6, "m1_v8": m1_v8,
           "click_by_rater_v6": [median(v["click_by_rater"][i] for v in v6) for i in range(len(raters))],
           "click_by_rater_v8": [median(v["click_by_rater"][i] for v in v8) for i in range(len(raters))]}
    ge = lambda a, b: a is not None and b is not None and a >= b
    conditions = {
        "1_v8_finals_compliant": bool(v8_all) and all(
            runs[v["run"]]["m4"]["machine_checks_all_pass"] and runs[v["run"]]["m4"]["must_rule_text_unchanged_from_v5"]
            for v in v8_all) and all(v["violation"] != "both" for v in v8_all),
        "2_no_must_probe_let_through": bool(probe_must) and all(r.get("as_expected") for r in probe_must)
                                       and len(company_clear) == 5 and all(r.get("matches_expectation") for r in company_clear)
                                       and probe["claude_cli_context_isolated"] and company["claude_cli_context_isolated"],
        "3_converged_at_least_2_of_3": sum(r["converged_within_limit"] for r in v8_runs) >= 2,
        "4_normal_v8_passes": bool(normal) and normal["converged_within_limit"] and normal["m4"]["machine_checks_all_pass"],
        "5_no_round_for_should_only": bool(v8_runs) and all((r["tiers"] or {}).get("rounds_back_without_must") == 0
                                                            for r in v8_runs + ([normal] if normal else [])),
        "6_no_block_probes_not_blocked": bool(probe_free) and all(r.get("as_expected") for r in probe_free),
        "7_click_not_lower": ge(med["click_v8"], med["click_v6"]),
        "8_reading_not_lower": ge(med["reading_v8"], med["reading_v6"]),
        "9_m1_not_higher": ge(m1_v6, m1_v8),
    }
    return {"items": items, "medians": med, "incomplete": gaps, "conditions": conditions,
            "adopt_v8": not gaps and all(conditions.values()),
            # A claim of better balance needs the improvement margin the v7 plan used, not just non-inferiority.
            "balance_claim_allowed": m1_v6 is not None and m1_v8 is not None and m1_v8 <= m1_v6 - BALANCE_CLAIM_MARGIN,
            "v6_same_raters": {"finals_both_violating": sum(v["violation"] == "both" for v in v6),
                               "drift_run": next((v for v in items.values() if v["run"] == reg["v6_drift"]
                                                  and v["which"] == "final"), None)}}


def score(args):
    prereg = json.loads(Path(args.prereg).read_text(encoding="utf-8"))
    key = json.loads(Path(args.key).read_text(encoding="utf-8"))["labels"]
    analysis = json.loads(Path(args.analysis).read_text(encoding="utf-8"))["runs"]
    probe = json.loads((Path(args.probe) / "probe_results.json").read_text(encoding="utf-8"))
    company = json.loads((Path(args.company) / "probe_results.json").read_text(encoding="utf-8"))
    raw = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.raw or []]
    result = decide(prereg, key, analysis, [load_rating(p) for p in args.ratings], probe, company, raw)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: result[k] for k in ("medians", "incomplete", "conditions", "adopt_v8", "balance_claim_allowed",
                                             "v6_same_raters")}, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    a = sub.add_parser("analyze"); a.add_argument("runs", nargs="+"); a.add_argument("--out")
    p = sub.add_parser("package")
    p.add_argument("--item", action="append", required=True)
    for name in ("--package", "--reversed", "--key"):
        p.add_argument(name, required=True)
    p.add_argument("--seed", type=int, required=True)
    s = sub.add_parser("score")
    for name in ("--prereg", "--key", "--analysis", "--probe", "--company"):
        s.add_argument(name, required=True)
    s.add_argument("--ratings", nargs=2, required=True); s.add_argument("--raw", nargs="*"); s.add_argument("--out")
    args = ap.parse_args()
    if args.command == "analyze":
        rows = [analyze(d) for d in args.runs]
        result = {"window": WINDOW, "adopt_run": ADOPT_RUN, "runs": rows}
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.out:
            Path(args.out).write_text(text + "\n", encoding="utf-8", newline="\n")
        print(json.dumps([{k: r[k] for k in ("run", "prompt_version", "rounds", "converged_within_limit", "m1")}
                          | {"tiers": {k: (r["tiers"] or {}).get(k) for k in ("rounds_back_without_must", "suggestions")}}
                          for r in rows], ensure_ascii=False, indent=1))
    elif args.command == "package":
        package(args)
    else:
        score(args)


if __name__ == "__main__":
    main()
