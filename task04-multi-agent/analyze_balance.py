"""Who wrote the final outline, and did the Planner negotiate? Reads run directories only; no model calls.

M1 (Auditor share): fraction of the final title + sections (whitespace removed) covered by
    WINDOW-character windows that appear in an Auditor `revision` of round r and in no Planner text
    (drafts, negotiation_note, responses) of rounds <= r. Lower means the Planner wrote more itself.
    Also reported for the title alone.
M2 (two-way negotiation), per finding of round r that has a Planner draft in round r+1:
    adopted  the next draft contains >= ADOPT_RUN contiguous characters covered by that finding's
             Auditor-originated windows;
    kept     otherwise, the quoted line is still in the next draft verbatim;
    own      otherwise (the Planner removed or rewrote it in its own words).
    defence_accepted = kept findings whose quote the next Auditor did not reject again.
    Planner-declared actions (v7 `responses`) are counted too, for reference only.
M4 (compliance, machine part) and M5 (convergence) come from state.json, verification.json and metadata.json.

usage: python analyze_balance.py <run_dir> [<run_dir> ...] [--out result.json]
"""
import argparse
import json
import re
import statistics
from pathlib import Path

WINDOW = 6       # characters; long enough that shared stock words such as 娛樂城推薦 (5) do not count
ADOPT_RUN = 10   # contiguous characters of Auditor-originated text that mark a finding as adopted
FORBIDDEN = ("穩賺不賠", "保證出金")
V6_POLICY_SHA256 = "437a61a9a9748fe9c336e8d0056ced7b425c2bef3b25ddf82022e73bf4c07373"


def norm(text):
    return re.sub(r"\s+", "", text or "")


def draft_text(draft):
    return norm((draft or {}).get("title", "") + "".join((draft or {}).get("sections", [])))


def planner_text(output):
    extra = (output.get("negotiation_note") or "") + "".join(
        (r.get("wording") or "") + (r.get("quote") or "") for r in output.get("responses") or [])
    return draft_text(output) + norm(extra)


def auditor_windows(revision, prior):
    rev = norm(revision)
    return {rev[i:i + WINDOW] for i in range(len(rev) - WINDOW + 1) if rev[i:i + WINDOW] not in prior}


def coverage(text, windows):
    covered = [False] * len(text)
    for j in range(len(text) - WINDOW + 1):
        if text[j:j + WINDOW] in windows:
            for k in range(j, j + WINDOW):
                covered[k] = True
    return covered


def longest_run(flags):
    best = run = 0
    for f in flags:
        run = run + 1 if f else 0
        best = max(best, run)
    return best


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
        for f in auditors[r]["findings"]:
            w = auditor_windows(f["revision"], prior)
            all_windows |= w
            row = {"round": r, "quote": f["quote"], "rule": f["rule"], "outcome": None}
            if r + 1 in planners:
                nxt = draft_text(planners[r + 1])
                if longest_run(coverage(nxt, w)) >= ADOPT_RUN:
                    row["outcome"] = "adopted"
                elif norm(f["quote"]) in nxt:
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
        m1 = {"auditor_share": round(sum(coverage(text, all_windows)) / len(text), 4),
              "auditor_share_title": round(sum(coverage(title, all_windows)) / len(title), 4),
              "chars": len(text)}
    judged = [x for x in findings_out if x["outcome"]]
    declared = {}
    for r, out in planners.items():
        for resp in out.get("responses") or []:
            declared[resp.get("action")] = declared.get(resp.get("action"), 0) + 1
    m2 = {"findings_with_next_draft": len(judged),
          "adopted": sum(x["outcome"] == "adopted" for x in judged),
          "kept": sum(x["outcome"] == "kept" for x in judged),
          "own": sum(x["outcome"] == "own" for x in judged),
          "defence_accepted": sum(bool(x.get("defence_accepted")) for x in judged),
          "own_or_accepted_defence_ratio": round(
              (sum(x["outcome"] == "own" for x in judged) + sum(bool(x.get("defence_accepted")) for x in judged))
              / len(judged), 4) if judged else None,
          "planner_declared_actions": declared}
    checks = verification.get("checks", {})
    m4 = {"status": state["status"], "machine_checks_all_pass": bool(checks) and all(checks.values()),
          "failed_checks": [k for k, v in checks.items() if not v],
          "policy_unchanged": meta.get("policy_sha256") == V6_POLICY_SHA256,
          "final_literal_guard_clear": bool(final) and not any(t in final["title"] + "".join(final["sections"])
                                                               for t in FORBIDDEN)}
    return {"run": root.name, "scenario": state["scenario"],
            "prompt_version": meta.get("prompt_version", "v6"),
            "rounds": state["iteration"], "converged_within_limit": state["status"] == "approved_provisional",
            "m1": m1, "m2": m2, "m4": m4, "findings": findings_out}


def summarize(rows):
    out = {}
    for version in sorted({r["prompt_version"] for r in rows if r["scenario"] == "forced_conflict"}):
        group = [r for r in rows if r["scenario"] == "forced_conflict" and r["prompt_version"] == version]
        shares = [r["m1"]["auditor_share"] for r in group if r["m1"]]
        ratios = [r["m2"]["own_or_accepted_defence_ratio"] for r in group if r["m2"]["own_or_accepted_defence_ratio"] is not None]
        out[version] = {"runs": len(group),
                        "converged": sum(r["converged_within_limit"] for r in group),
                        "m1_auditor_share_median": statistics.median(shares) if shares else None,
                        "m2_own_or_accepted_defence_ratio_median": statistics.median(ratios) if ratios else None}
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--out")
    args = ap.parse_args()
    rows = [analyze(d) for d in args.runs]
    result = {"window": WINDOW, "adopt_run": ADOPT_RUN, "runs": rows, "summary": summarize(rows)}
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"summary": result["summary"],
                      "per_run": [{k: r[k] for k in ("run", "prompt_version", "rounds", "converged_within_limit")}
                                  | {"m1": r["m1"], "m2": {k: v for k, v in r["m2"].items() if k != "planner_declared_actions"}}
                                  for r in rows]}, ensure_ascii=False, indent=1))
