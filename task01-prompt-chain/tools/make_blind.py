#!/usr/bin/env python3
"""建立盲評副本：每位評審各自隨機指派代號，對應表另存，評審只拿到自己的資料夾。

用法：
  python tools/make_blind.py outputs/final.md outputs/baseline.md outputs/baseline-informed.md --judges 3

產出：
  outputs/blind/judge-N/X.md、Y.md、Z.md …（每位評審的代號順序各自獨立洗牌；重跑會清掉舊的 outputs/blind/）
  outputs/blind-mapping.json   代號 → 原檔，供 aggregate_reviews.py 還原（不給評審）
"""
import argparse
import json
import random
import shutil
import sys
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8")

LABELS = "XYZWVU"


def main():
    ap = argparse.ArgumentParser(description="建立盲評副本與代號對應表")
    ap.add_argument("files", nargs="+", help=f"要盲評的文章，2–{len(LABELS)} 篇")
    ap.add_argument("--judges", type=int, default=3, help="評審人數（預設 3）")
    args = ap.parse_args()
    files = [Path(a) for a in args.files]
    if not 2 <= len(files) <= len(LABELS):
        ap.error(f"需要 2–{len(LABELS)} 篇文章")
    missing = [str(f) for f in files if not f.exists()]
    if missing:
        ap.error(f"找不到：{missing}")

    out_root = Path("outputs/blind")
    if out_root.exists():
        shutil.rmtree(out_root)
    rng = random.SystemRandom()
    mapping = {}
    for j in range(1, args.judges + 1):
        order = files[:]
        rng.shuffle(order)
        judge_dir = out_root / f"judge-{j}"
        judge_dir.mkdir(parents=True)
        mapping[f"judge-{j}"] = {}
        for label, src in zip(LABELS, order):
            shutil.copyfile(src, judge_dir / f"{label}.md")
            mapping[f"judge-{j}"][label] = src.as_posix()
    Path("outputs/blind-mapping.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(mapping, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
