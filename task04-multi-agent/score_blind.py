"""M3 and the final adoption decision for the v7 experiment (see evidence/balance-v7/PREREGISTRATION.md).

Reads two raters' JSON arrays (as asked for in the blind package), the label key and analysis.json.
Click appeal per outline = mean of the two raters; an outline counts as violating only if both raters
list at least one violation (one rater only = disputed, reported). No model calls.

usage: python score_blind.py --key <key.json> --analysis <analysis.json> --ratings <r1.json> <r2.json> [--out result.json]
"""
import argparse
import json
import statistics
from pathlib import Path


def load_rating(path):
    text = Path(path).read_text(encoding="utf-8").strip()
    start, end = text.find("["), text.rfind("]")
    return {row["label"]: row for row in json.loads(text[start:end + 1])}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", required=True)
    ap.add_argument("--analysis", required=True)
    ap.add_argument("--ratings", nargs=2, required=True)
    ap.add_argument("--out")
    args = ap.parse_args()
    key = json.loads(Path(args.key).read_text(encoding="utf-8"))["labels"]
    analysis = {r["run"]: r for r in json.loads(Path(args.analysis).read_text(encoding="utf-8"))["runs"]}
    raters = [load_rating(p) for p in args.ratings]

    items = {}
    for label, src in key.items():
        rows = [r[label] for r in raters]
        flags = [bool(r.get("violations")) for r in rows]
        items[label] = {**src, "click": statistics.mean(float(r["click_appeal"]) for r in rows),
                        "click_by_rater": [r["click_appeal"] for r in rows],
                        "violation": "both" if all(flags) else ("disputed" if any(flags) else "none"),
                        "violations_by_rater": [r.get("violations") or [] for r in rows]}

    def group(version):
        return [v for v in items.values() if v["which"] == "final" and v["prompt_version"] == version]

    v6, v7 = group("v6"), group("v7")
    v7_runs = [r for r in analysis.values() if r["scenario"] == "forced_conflict" and r["prompt_version"] == "v7"]
    v6_runs = [r for r in analysis.values() if r["scenario"] == "forced_conflict" and r["prompt_version"] == "v6"]
    normal_v7 = [r for r in analysis.values() if r["scenario"] == "normal" and r["prompt_version"] == "v7"]
    m1_v6 = statistics.median(r["m1"]["auditor_share"] for r in v6_runs if r["m1"])
    m1_v7 = statistics.median(r["m1"]["auditor_share"] for r in v7_runs if r["m1"])
    conditions = {
        "1_v7_finals_compliant": all(r["m4"]["machine_checks_all_pass"] and r["m4"]["policy_unchanged"]
                                     for r in v7_runs if r["converged_within_limit"])
                                 and all(v["violation"] != "both" for v in v7),
        "2_converged_at_least_2_of_3": sum(r["converged_within_limit"] for r in v7_runs) >= 2,
        "3_m1_lower_by_0.15": m1_v7 <= m1_v6 - 0.15,
        "4_click_not_lower": statistics.median(v["click"] for v in v7) >= statistics.median(v["click"] for v in v6),
        "5_normal_v7_passes": bool(normal_v7) and all(r["m4"]["machine_checks_all_pass"] and r["converged_within_limit"]
                                                       for r in normal_v7),
    }
    result = {"items": items,
              "medians": {"click_v6_finals": statistics.median(v["click"] for v in v6),
                          "click_v7_finals": statistics.median(v["click"] for v in v7),
                          "m1_v6": m1_v6, "m1_v7": m1_v7},
              "conditions": conditions, "adopt_v7": all(conditions.values())}
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)


if __name__ == "__main__":
    main()
