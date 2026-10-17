"""Real-Auditor probe on the company's own sample sheet (Sheet1, Category = Casino).

Expected verdicts are pre-registered in cases/company_samples.json before any run; this
script only reads them, never edits them, and stores their hash with the results.
Snippets are read from the sheet (or a local CSV export) and not copied into the repo
as a file; they appear only inside the prompts and replies, as in any other evidence.
"""
import argparse, asyncio, csv, hashlib, io, json, sys
from datetime import datetime, timezone
from pathlib import Path
from claude_subscription import ClaudeDualRoleAgent, DEFAULT_EFFORT, DEFAULT_MODEL, cli_version
from provider import JsonlLog
from verify_run import ISOLATION_TOKEN_CEILING, request_context_tokens
from workflow import ProviderError, State, TransientError, snapshot

HERE = Path(__file__).resolve().parent
EXPECT = HERE / "cases/company_samples.json"

def load_rows(samples, url):
    if samples:
        text = Path(samples).read_text(encoding="utf-8-sig")
    else:
        import httpx
        response = httpx.get(url, follow_redirects=True, timeout=30)
        response.raise_for_status()
        text = response.content.decode("utf-8-sig")
    return {row["ID"].strip(): row for row in csv.DictReader(io.StringIO(text))}

def draft_for(row):
    return {"title": row["Target Keyword"].strip(),
            "sections": [row["Content Snippet (文章片段)"].strip()],
            "negotiation_note": "title 是這段文字的目標關鍵字，原文沒有標題；sections 只有一段既有文章的內文，不是小標。"}

def score(sample, verdict):
    quotes = " ".join(f["quote"] for f in verdict["findings"])
    quoted = [t for t in sample.get("key_terms", []) if t in quotes]
    if sample["class"] == "clear":
        expected = sample["expect_pass"]
        matches = verdict["passed"] == expected and (expected or bool(quoted))
    else:
        expected = sample["lean_pass"]
        matches = verdict["passed"] == expected
    return {"expected_pass": expected, "matches_expectation": matches, "key_terms_quoted": quoted,
            "rules_cited": sorted({f["rule"] for f in verdict["findings"]})}

async def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True, help="New directory; never overwrites earlier evidence")
    p.add_argument("--samples", help="Local CSV export of Sheet1; default downloads the public export")
    args = p.parse_args()
    expect_bytes = EXPECT.read_bytes()
    plan = json.loads(expect_bytes.decode("utf-8"))
    rows = load_rows(args.samples, plan["source"]["csv_export"])
    selected = [(s, rows[s["id"]]) for s in plan["samples"]]
    if any(row["Category"].strip() != "Casino" for _, row in selected):
        raise SystemExit("Sample sheet changed: a selected ID is no longer a Casino row")
    out = Path(args.out); out.mkdir(parents=True, exist_ok=False)
    policy = json.loads((HERE / "policy.json").read_text(encoding="utf-8"))
    log = JsonlLog(out / "provider.jsonl")
    agent = ClaudeDualRoleAgent(policy, log, max_calls=len(selected))
    started = datetime.now(timezone.utc).isoformat()
    results = []
    for sample, row in selected:
        s = State(request=f"審核一段既有的「{row['Target Keyword'].strip()}」文章內文是否符合暫行規則。",
                  initial_instruction="", scenario="normal", mode="llm_runtime",
                  policy_version=policy["version"], iteration=1)
        s.draft = draft_for(row)
        item = {"id": sample["id"], "class": sample["class"], "run_id": s.run_id, "draft": s.draft}
        try:
            verdict = await asyncio.wait_for(agent("auditor", snapshot(s)), 240)
        except (ProviderError, TransientError, TimeoutError) as e:
            results.append({**item, "error": f"{type(e).__name__}: {e}"}); continue
        results.append({**item, "verdict": verdict, **score(sample, verdict)})
    raw = out / "provider.jsonl"
    records = [json.loads(x) for x in raw.read_text(encoding="utf-8").splitlines()] if raw.exists() else []
    tokens = [request_context_tokens(json.loads(r["response_text"])) for r in records
              if r.get("returncode") == 0 and not r.get("error")]
    clear = [r for r in results if r["class"] == "clear"]
    summary = {
        "note": "Snippets come from the company sheet; expected verdicts were pre-registered in cases/company_samples.json; verdicts are real Auditor replies (provider.jsonl).",
        "started_at": started, "cli_version": cli_version(), "model": DEFAULT_MODEL, "effort": DEFAULT_EFFORT,
        "expectations_file": "cases/company_samples.json", "expectations_preregistered_at": plan["preregistered_at"],
        "expectations_sha256": hashlib.sha256(expect_bytes).hexdigest(),
        "roles_py_sha256": hashlib.sha256((HERE / "roles.py").read_bytes()).hexdigest(),
        "policy_version": policy["version"],
        "samples_source": args.samples or plan["source"]["csv_export"],
        "selected_rows_sha256": hashlib.sha256(json.dumps([row for _, row in selected], ensure_ascii=False,
                                                          sort_keys=True).encode("utf-8")).hexdigest(),
        "claude_cli_context_isolated": bool(tokens) and all(t < ISOLATION_TOKEN_CEILING for t in tokens),
        "max_request_context_tokens_per_call": tokens,
        "clear_cases_matching": f"{sum(r.get('matches_expectation', False) for r in clear)}/{len(clear)}",
        "errors": [r["id"] for r in results if "error" in r],
        "results": results}
    (out / "probe_results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    lines = ["# 公司資料表樣本：Auditor 判定", "",
             f"預期判定：`cases/company_samples.json`（{plan['preregistered_at']} 登錄，sha256 {summary['expectations_sha256'][:12]}）。"
             f"明確案例一致：{summary['clear_cases_matching']}；隔離檢查：{summary['claude_cli_context_isolated']}。", "",
             "| ID | 類別 | 事前預期 | Auditor | 一致 | 引用規則 |", "|---|---|---|---|---|---|"]
    for r in results:
        if "error" in r:
            lines.append(f"| {r['id']} | {r['class']} | — | 錯誤：{r['error']} | — | — |"); continue
        lines.append(f"| {r['id']} | {'明確' if r['class'] == 'clear' else '邊界'} | "
                     f"{'通過' if r['expected_pass'] else '退回'} | {'通過' if r['verdict']['passed'] else '退回'} | "
                     f"{'是' if r['matches_expectation'] else '否'} | {'、'.join(r['rules_cited']) or '—'} |")
    for r in results:
        if "verdict" not in r: continue
        lines += ["", f"## ID {r['id']}", f"片段：{r['draft']['sections'][0]}", f"Auditor 回應：{r['verdict']['note']}"]
        lines += [f"- {f['quote']}：{f['reason']}；建議：{f['revision']}（{f['rule']}）" for f in r["verdict"]["findings"]]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    for r in results:
        print(json.dumps({k: r.get(k) for k in ("id", "class", "expected_pass", "matches_expectation",
                                                "rules_cited", "key_terms_quoted", "error")}, ensure_ascii=False))
    print(json.dumps({"clear_cases_matching": summary["clear_cases_matching"],
                      "claude_cli_context_isolated": summary["claude_cli_context_isolated"]}))
    return 0 if summary["claude_cli_context_isolated"] and not summary["errors"] else 2

if __name__ == "__main__":
    sys.stdout.reconfigure(errors="backslashreplace")
    raise SystemExit(asyncio.run(main()))
