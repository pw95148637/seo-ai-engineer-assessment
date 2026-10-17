#!/usr/bin/env python3
"""彙整盲評分數：讀各評審檔末尾的 JSON 分數區塊，依對應表還原成原檔，輸出逐評審與平均的 Markdown 表。

用法：
  python tools/aggregate_reviews.py outputs/review-blind-1.md outputs/review-blind-2.md outputs/review-blind-3.md

評審檔 outputs/review-blind-N.md 對應 outputs/blind/judge-N/；對應表讀 outputs/blind-mapping.json（由 make_blind.py 產生）。
JSON 區塊格式（評審依 prompts/review-blind.md 附在檔末）：
  {"X": {"細節重視": 4, "讀者價值": 5, "真人感": 3, "誠實與可信": 5, "YMYL 安全": 5}, "Y": {...}}
"""
import argparse
import json
import re
import sys
from pathlib import Path
from statistics import mean

for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8")

ITEMS = ["細節重視", "讀者價值", "真人感", "誠實與可信", "YMYL 安全"]
DEFECTS = "缺陷數"  # 評審列出的具體缺陷條數，舊評審檔沒有時不輸出
MAPPING = Path("outputs/blind-mapping.json")


def load_scores(review_path, mapping):
    text = Path(review_path).read_text(encoding="utf-8")
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", text, re.S)
    if not blocks:
        sys.exit(f"{review_path} 沒有 JSON 分數區塊")
    raw = json.loads(blocks[-1])
    judge = "judge-" + re.search(r"(\d+)\.md$", str(review_path)).group(1)
    return judge, {mapping[judge][label]: scores for label, scores in raw.items()}


def main():
    ap = argparse.ArgumentParser(description="彙整盲評分數並還原代號")
    ap.add_argument("reviews", nargs="+", help="評審檔 outputs/review-blind-N.md（檔名結尾的數字對應 judge-N）")
    ap.add_argument("--mapping", type=Path, default=MAPPING, help=f"代號對應表（預設 {MAPPING}）")
    args = ap.parse_args()
    if not args.mapping.exists():
        ap.error(f"找不到 {args.mapping}，請先執行 tools/make_blind.py")
    mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
    per_judge = dict(load_scores(p, mapping) for p in args.reviews)
    articles = sorted({a for s in per_judge.values() for a in s})

    lines = ["| 項目 | " + " | ".join(articles) + " |", "|---|" + "---|" * len(articles)]
    for item in ITEMS + ["總分"]:
        cells = []
        for a in articles:
            vals = [s[a][item] if item != "總分" else sum(s[a][i] for i in ITEMS) for s in per_judge.values()]
            cells.append(f"{mean(vals):.1f}（{'／'.join(str(v) for v in vals)}）")
        lines.append(f"| {item} | " + " | ".join(cells) + " |")
    if all(DEFECTS in s[a] for s in per_judge.values() for a in articles):
        cells = []
        for a in articles:
            vals = [s[a][DEFECTS] for s in per_judge.values()]
            cells.append(f"{mean(vals):.1f}（{'／'.join(str(v) for v in vals)}）")
        lines.append(f"| {DEFECTS} | " + " | ".join(cells) + " |")
    print("平均（括號內依序為 " + "、".join(per_judge) + "）\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
