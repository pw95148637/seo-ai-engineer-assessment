"""Adoption decision for the v8.1 experiment (evidence/tiered-v81/PREREGISTRATION.md). No model calls.

Metrics come from `eval_v8.py analyze`, the blind package from `eval_v8.py package`, decline judgments from
`judge_declines.py`; this file applies the v8.1 conditions. v8.1 is compared with v8 (click, reading value, the
Auditor's absolute share of the final text) and with v6 (M1) on ratings from one new package in which the v6, v8
and v8.1 finals are rated together by the same two raters.

usage: python eval_v81.py --prereg prereg.json --key key.json --analysis analysis.json
                          --ratings r1.json r2.json --raw r1-raw.json r2-raw.json
                          --judgments judgments.json --judge-key key.json --judge-raw raw.json --out decision.json
"""
import argparse
import json
import statistics
from pathlib import Path
from analyze_balance import ADOPT_RUN, auditor_windows, coverage, longest_run, norm
from eval_v8 import draft_text, load_rating, median, planner_text

import hashlib
HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "evidence"
BALANCE_MARGIN = 0.15        # M1 below v6 by this much (same margin as the v7 and v8 plans)
RATING_MARGIN = 0.5          # click and reading: v8.1 fails only if its median is a full point below v8


def rate_items(key, raters):
    items = {}
    for label, src in key.items():
        rows = [r[label] for r in raters if label in r]
        if len(rows) != len(raters) or not rows:
            continue
        flags = [bool(r.get("violations")) for r in rows]
        rules = [{v["rule"] for v in r.get("violations") or []} for r in rows]
        items[label] = {**src, "click": statistics.mean(float(r["click_appeal"]) for r in rows),
                        "click_by_rater": [r["click_appeal"] for r in rows],
                        "reading": statistics.mean(float(r["reading_value"]) for r in rows),
                        "reading_by_rater": [r["reading_value"] for r in rows],
                        "violation": "both" if all(flags) else ("disputed" if any(flags) else "none"),
                        "same_rule_both": bool(set.intersection(*rules)),
                        "violations_by_rater": [r.get("violations") or [] for r in rows]}
    return items


def resolve(registered, runs):
    """A registered run may be replaced by its '-retry' rerun (non-model failure, logged in RUN_LOG.md)."""
    return registered + "-retry" if registered + "-retry" in runs else registered


def call_records(run_dir):
    path = EVIDENCE / run_dir / "provider.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


def prompt_class(record, scenario):
    rnd = "round1" if record["iteration"] == 1 else "round2plus"
    return f"v81_{record['role']}_{scenario}_{rnd}"


def completeness(prereg, analysis, key, raters, rater_raw, judge_raw, run_log):
    reg, sha = prereg["registered"], prereg["file_sha256"]
    runs = {r["run"]: r for r in analysis}
    names = {g: [resolve(n, runs) for n in reg[g]] for g in ("v6_baseline", "v8_conflict", "v81_conflict")}
    single = {g: resolve(reg[g], runs) for g in ("v8_normal", "v8_control", "v81_normal")}
    expected = names["v6_baseline"] + names["v8_conflict"] + names["v81_conflict"] + list(single.values())
    gaps = []
    if sorted(runs) != sorted(expected):
        gaps.append(f"analysis runs {sorted(runs)} != registered {sorted(expected)}")
    for name in runs:
        if name.endswith("-retry") and name not in run_log:
            gaps.append(f"{name}: rerun not recorded in RUN_LOG.md")
    for name in names["v81_conflict"] + [single["v81_normal"]]:
        run = runs.get(name)
        if not run:
            continue
        h = run.get("hashes", {})
        if (h.get("roles_module_sha256"), h.get("controller_module_sha256"), h.get("policy_sha256")) != (
                sha["roles_v81.py"], sha["workflow_v8.py"], prereg["policy_v8_sha256"]):
            gaps.append(f"{name}: code or policy hash differs from registration")
        if run.get("cli_version") != prereg["fixed"]["cli_version"] or run.get("models_returned") != [prereg["fixed"]["model"]]:
            gaps.append(f"{name}: CLI version or returned model differs from registration")
        for record in call_records(name):
            want = prereg["system_prompt_sha256"].get(prompt_class(record, run["scenario"]))
            if record["request"]["system_prompt_sha256"] != want:
                gaps.append(f"{name}: a {record['role']} call sent a system prompt other than the registered one")
                break
    if hashlib.sha256((HERE / "roles_v8.py").read_bytes()).hexdigest() != sha.get("roles_v8.py"):
        gaps.append("roles_v8.py changed after registration")
    finals = {(s["run"], s["which"]) for s in key.values()}
    need = names["v6_baseline"] + names["v8_conflict"] + [single["v8_normal"]] + [
        n for n in names["v81_conflict"] + [single["v81_normal"], single["v8_control"]]
        if (runs.get(n) or {}).get("converged_within_limit")]
    gaps += [f"{n}: final missing from the blind package" for n in need if (n, "final") not in finals]
    gaps += [f"rater {i} labels differ from the package" for i, r in enumerate(raters, 1) if set(r) != set(key)]
    if len(rater_raw) != len(raters) or not all(r.get("context_isolated") and r.get("returncode") == 0 for r in rater_raw):
        gaps.append("a rater call failed, was not isolated, or its raw reply is missing")
    if len({r.get("package_sha256") for r in rater_raw}) != len(rater_raw):
        gaps.append("both raters read the same package file")
    if judge_raw is None or (judge_raw.get("returncode") not in (None, 0)) or judge_raw.get("context_isolated") is False:
        gaps.append("decline judge missing, failed or not isolated")
    return gaps, names, single


def copied_after_decline(run_dir):
    """Declined suggestions whose Auditor text still appears (>= ADOPT_RUN chars) in the next draft."""
    state = json.loads((EVIDENCE / run_dir / "state.json").read_text(encoding="utf-8"))
    planners = {e["iteration"]: e["output"] for e in state["history"] if e["node"] == "planner"}
    out = []
    for x in state.get("suggestions", []):
        if x["status"] != "declined" or x["round"] + 1 not in planners:
            continue
        prior = "".join(planner_text(planners[i]) for i in planners if i <= x["round"])
        windows = auditor_windows(x["suggestion"], prior)
        if longest_run(coverage(draft_text(planners[x["round"] + 1]), windows)) >= ADOPT_RUN:
            out.append(x["id"])
    return out


def kept_defences(run):
    """MUST quotes the Planner kept and the next Auditor did not reject again (a defence that was accepted)."""
    return [norm(f["quote"]) for f in run["findings"] if f.get("outcome") == "kept" and f.get("defence_accepted")]


def decide(prereg, key, analysis, raters, rater_raw, judgments=(), judge_key=None, judge_raw=None, run_log=""):
    gaps, names, single = completeness(prereg, analysis, key, raters, rater_raw, judge_raw, run_log)
    items = rate_items(key, raters)
    runs = {r["run"]: r for r in analysis}

    def finals(group):
        return [v for v in items.values() if v["which"] == "final" and v["run"] in group]

    v6, v8, v81 = finals(names["v6_baseline"]), finals(names["v8_conflict"]), finals(names["v81_conflict"])
    v81_all = finals(names["v81_conflict"] + [single["v81_normal"]])
    v81_runs = [runs[n] for n in names["v81_conflict"] if n in runs]
    normal = runs.get(single["v81_normal"])

    # Condition 5: declines that an independent judge found reader-specific and not about a MUST problem,
    # from converged runs, and not copied into the next draft anyway.
    verdict = {j["id"]: j for j in judgments}
    good = {}
    for item in (judge_key or {}).get("items", []):
        j = verdict.get(item["id"])
        run = runs.get(item["run"])
        if not j or not run or not run["converged_within_limit"]:
            continue
        if j["reader_specific_reason"] and not j["involves_must"] and item["suggestion_id"] not in copied_after_decline(item["run"]):
            good.setdefault(item["run"], []).append(item["suggestion_id"])
    declined_runs = [r["run"] for r in v81_runs if good.get(r["run"])]
    control_good = good.get(single["v8_control"], [])

    def covered(names_):
        return median(round(runs[n]["m1"]["auditor_share"] * runs[n]["m1"]["chars"]) for n in names_
                      if n in runs and runs[n]["m1"])

    m1 = {g: median((runs[n]["m1"] or {}).get("auditor_share") for n in names[k] if n in runs)
          for g, k in (("v6", "v6_baseline"), ("v8", "v8_conflict"), ("v81", "v81_conflict"))}
    chars = {g: covered(names[k]) for g, k in (("v6", "v6_baseline"), ("v8", "v8_conflict"), ("v81", "v81_conflict"))}
    med = {"click_v6": median(v["click"] for v in v6), "click_v8": median(v["click"] for v in v8),
           "click_v81": median(v["click"] for v in v81), "reading_v6": median(v["reading"] for v in v6),
           "reading_v8": median(v["reading"] for v in v8), "reading_v81": median(v["reading"] for v in v81),
           "m1": m1, "auditor_chars_in_final": chars,
           "click_by_rater_v8": [median(v["click_by_rater"][i] for v in v8) for i in range(len(raters))],
           "click_by_rater_v81": [median(v["click_by_rater"][i] for v in v81) for i in range(len(raters))],
           "reading_by_rater_v8": [median(v["reading_by_rater"][i] for v in v8) for i in range(len(raters))],
           "reading_by_rater_v81": [median(v["reading_by_rater"][i] for v in v81) for i in range(len(raters))]}

    # Condition 1 extra: a MUST sentence kept by an accepted defence fails if either rater flags it.
    flagged_defences = []
    for v in v81_all:
        run = runs.get(v["run"])
        if not run:
            continue
        quotes = [norm(x["quote"]) for vs in v["violations_by_rater"] for x in vs]
        for kept in kept_defences(run):
            if any(kept and (kept in q or q in kept) for q in quotes if q):
                flagged_defences.append({"run": v["run"], "quote": kept})

    ok = lambda a, b, margin=0.0: a is not None and b is not None and a >= b - margin
    conditions = {
        "1_v81_finals_compliant": bool(v81_all) and all(
            runs[v["run"]]["m4"]["machine_checks_all_pass"] and runs[v["run"]]["m4"]["must_rule_text_unchanged_from_v5"]
            for v in v81_all if v["run"] in runs) and all(v["violation"] != "both" for v in v81_all) and not flagged_defences,
        "2_converged_at_least_2_of_3": sum(r["converged_within_limit"] for r in v81_runs) >= 2,
        "3_normal_v81_passes": bool(normal) and normal["converged_within_limit"] and normal["m4"]["machine_checks_all_pass"],
        "4_no_round_for_should_only": bool(v81_runs) and all((r["tiers"] or {}).get("rounds_back_without_must") == 0
                                                             for r in v81_runs + ([normal] if normal else [])),
        "5_judged_decline_in_2_of_3": len(declined_runs) >= 2,
        "6_authorship_moved_to_planner": m1["v6"] is not None and m1["v81"] is not None
                                         and m1["v81"] <= m1["v6"] - BALANCE_MARGIN
                                         and chars["v8"] is not None and chars["v81"] is not None and chars["v81"] < chars["v8"],
        "7_click_not_a_point_below_v8": ok(med["click_v81"], med["click_v8"], RATING_MARGIN),
        "8_reading_not_a_point_below_v8": ok(med["reading_v81"], med["reading_v8"], RATING_MARGIN),
    }
    return {"items": items, "medians": med, "incomplete": gaps, "conditions": conditions,
            "adopt_v81": not gaps and all(conditions.values()),
            "judged_good_declines": good, "declined_runs": declined_runs,
            "control_v8_judged_good_declines": control_good,
            "principles_claim_allowed": not gaps and len(declined_runs) >= 2 and not control_good,
            "flagged_defences": flagged_defences,
            "same_package_both_violating": {
                "v6": sum(v["violation"] == "both" for v in v6),
                "v8": sum(v["violation"] == "both" for v in finals(names["v8_conflict"] + [single["v8_normal"]])),
                "v8_control": sum(v["violation"] == "both" for v in finals([single["v8_control"]])),
                "v81": sum(v["violation"] == "both" for v in v81_all)}}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("--prereg", "--key", "--analysis", "--judgments", "--judge-key", "--judge-raw"):
        ap.add_argument(name, required=True)
    ap.add_argument("--ratings", nargs=2, required=True)
    ap.add_argument("--raw", nargs=2, required=True)
    ap.add_argument("--run-log", default=str(HERE / "evidence/tiered-v81/RUN_LOG.md"))
    ap.add_argument("--out")
    args = ap.parse_args()
    read = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))
    result = decide(read(args.prereg), read(args.key)["labels"], read(args.analysis)["runs"],
                    [load_rating(p) for p in args.ratings], [read(p) for p in args.raw],
                    read(args.judgments), read(args.judge_key), read(args.judge_raw),
                    Path(args.run_log).read_text(encoding="utf-8"))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: result[k] for k in ("medians", "incomplete", "conditions", "adopt_v81", "judged_good_declines",
                                             "control_v8_judged_good_declines", "principles_claim_allowed",
                                             "flagged_defences", "same_package_both_violating")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
