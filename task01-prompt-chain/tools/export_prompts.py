#!/usr/bin/env python3
"""把 prompts/ 各步 prompt 全文依鏈的順序組成一份 Markdown，供交付與簡報使用。

用法：
  python tools/export_prompts.py > deliverable/prompts.md
"""
import argparse
import sys
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8")

ORDER = [
    ("階段 A", ["A"]),
    ("階段 B", ["B1", "B2"]),
    ("階段 C", ["C1-facts", "C1-experience", "C1-reader", "C2", "C3", "C4"]),
    ("對照實驗", ["baseline", "baseline-informed", "review-blind"]),
]


def main():
    ap = argparse.ArgumentParser(description="匯出各步 prompt 全文")
    ap.add_argument("--dir", default="prompts", help="prompt 目錄（預設 prompts）")
    args = ap.parse_args()
    root = Path(args.dir)
    listed = {name for _, names in ORDER for name in names}
    extra = sorted(p.stem for p in root.glob("*.md") if p.stem not in listed)
    if extra:
        sys.exit(f"prompts/ 有未列入順序的檔案：{extra}，請更新 ORDER")

    out = [
        "# 提示詞鏈各步 prompt 全文",
        "",
        "以下是 `prompts/` 各檔原文，依鏈的執行順序排列。主控把整份 prompt 交給新的 subagent，"
        "再視需要附上執行時的具體約束（例如選定的意圖、作者經驗的使用限制），那些約束記在每次執行的 `run-log.md`。"
        "每步的關卡（通過條件）寫在 `.claude/skills/prompt-chain/SKILL.md`。",
        "",
    ]
    for section, names in ORDER:
        out += [f"## {section}", ""]
        for name in names:
            text = (root / f"{name}.md").read_text(encoding="utf-8").strip()
            out += [f"### `prompts/{name}.md`", "", "```text", text, "```", ""]
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
