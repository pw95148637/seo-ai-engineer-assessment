#!/usr/bin/env python3
"""依 Claude API 牌價（含快取折扣）換算每組 subagent 的等值成本。

每個 subagent 的完整紀錄是 Claude Code 寫在專案設定目錄下的 JSONL（`<設定目錄>/projects/<專案>/<工作階段>/subagents/agent-<id>.jsonl`），
每次呼叫都記了一般輸入、快取寫入（5 分鐘／1 小時）、快取讀取與輸出四種 token。本工具只加總這些用量欄位，不讀內容。

用法：
  python tools/cost_report.py outputs/agents.json --transcripts <subagents 目錄> [<另一個目錄> ...] [--by-step]

outputs/agents.json：{"<agent id>": ["<組別>", "<步驟>"], ...}，主控派 subagent 時記錄。
結果是依牌價的等值成本，不代表實際帳單（訂閱方案的扣費方式不同），也不含主控對話本身。
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8")

# USD / 1M tokens：輸入、輸出、快取讀取。快取寫入：5 分鐘 1.25 倍輸入價、1 小時 2 倍。
# 來源：Claude API 模型價目（2026-10-06）與 prompt caching 文件。
PRICE = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
}
KEYS = ("input", "write_5m", "write_1h", "cache_read", "output")


def calls(path):
    """每則回應一筆用量（同一回應的串流紀錄以 ID 去重，取最後一筆）。"""
    per = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        msg = rec.get("message") if isinstance(rec, dict) else None
        if not isinstance(msg, dict) or not msg.get("usage"):
            continue
        u = msg["usage"]
        cc = u.get("cache_creation") or {}
        w5, w1 = int(cc.get("ephemeral_5m_input_tokens") or 0), int(cc.get("ephemeral_1h_input_tokens") or 0)
        if not (w5 or w1):
            w5 = int(u.get("cache_creation_input_tokens") or 0)
        per[msg.get("id") or rec.get("uuid")] = {
            "model": msg.get("model"), "input": int(u.get("input_tokens") or 0), "write_5m": w5, "write_1h": w1,
            "cache_read": int(u.get("cache_read_input_tokens") or 0), "output": int(u.get("output_tokens") or 0)}
    return per.values()


def usd(c, cached=True):
    pin, pout, pcr = PRICE[c["model"]]
    if not cached:
        return ((c["input"] + c["write_5m"] + c["write_1h"] + c["cache_read"]) * pin + c["output"] * pout) / 1e6
    return (c["input"] * pin + c["write_5m"] * pin * 1.25 + c["write_1h"] * pin * 2
            + c["cache_read"] * pcr + c["output"] * pout) / 1e6


def main():
    ap = argparse.ArgumentParser(description="依 API 牌價（含快取）換算各組 subagent 的等值成本")
    ap.add_argument("agents", type=Path, help='agent id 對照表，例如 {"a1b2…": ["chain", "C1"]}')
    ap.add_argument("--transcripts", nargs="+", type=Path, required=True, help="subagents 紀錄目錄")
    ap.add_argument("--by-step", action="store_true", help="另列每個 subagent 的組別、步驟與成本")
    args = ap.parse_args()
    agents = json.loads(args.agents.read_text(encoding="utf-8"))

    groups = defaultdict(lambda: defaultdict(float))
    steps = []
    missing, unknown_models = [], set()
    for aid, (group, step) in agents.items():
        found = [d / f"agent-{aid}.jsonl" for d in args.transcripts if (d / f"agent-{aid}.jsonl").exists()]
        if not found:
            missing.append(aid)
            continue
        step_usd = 0.0
        for c in calls(found[0]):
            if c["model"] not in PRICE:
                unknown_models.add(c["model"])
                continue
            g = groups[group]
            for k in KEYS:
                g[k] += c[k]
            g["usd"] += usd(c)
            g["usd_no_cache"] += usd(c, cached=False)
            step_usd += usd(c)
        steps.append((group, step, step_usd))

    print("| 組別 | 一般輸入 | 快取寫入 5m | 快取寫入 1h | 快取讀取 | 輸出 | 等值成本（USD） | 若不用快取 |")
    print("|---|---|---|---|---|---|---|---|")
    for group, g in groups.items():
        print(f"| {group} | " + " | ".join(f"{g[k]:,.0f}" for k in KEYS)
              + f" | {g['usd']:.2f} | {g['usd_no_cache']:.2f} |")
    if args.by_step:
        print("\n| 組別 | 步驟 | 等值成本（USD） |")
        print("|---|---|---|")
        for group, step, u in steps:
            print(f"| {group} | {step} | {u:.2f} |")
    if missing:
        print(f"\n找不到紀錄：{missing}")
    if unknown_models:
        print(f"\n沒有牌價、未計入的模型：{sorted(unknown_models)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
