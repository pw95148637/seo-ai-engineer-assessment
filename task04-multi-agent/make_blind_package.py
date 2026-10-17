"""Build the blind-rating package for M3: anonymised outlines in shuffled order plus the rating
instructions, and a separate key that maps labels back to runs. No model calls.

The package holds only article text (title and sections) and the unchanged policy rules: no run IDs,
file names, dates, round numbers or prompt versions. Give raters the package only, never the key.

usage: python make_blind_package.py --item <run_dir>:final|round1 [...] --package <file.md> --key <file.json> --seed N
"""
import argparse
import json
import random
import string
from pathlib import Path

HERE = Path(__file__).resolve().parent

INSTRUCTIONS = """# 文章大綱評分

下面有 {n} 份「娛樂城推薦」文章大綱（標題與段落要點），順序隨機，以英文字母標示。請逐份獨立評分，不要回頭依其他份調整分數。

## 1. 點擊吸引力（1 到 5 分）

假設你是在 Google 搜尋「娛樂城推薦」的台灣讀者：搜尋結果先看到標題，點進來後看到這份大綱。你多想點進來並讀下去？

- 1：完全不想點
- 3：普通
- 5：非常想點

只評吸引力，不管內容是否合規。附一句理由。

## 2. 合規

依下面四條規則，列出大綱中違反規則的原句（逐字引用）、規則代號與理由；沒有違規就給空陣列。只看標題與大綱本身。

{rules}

## 輸出

只回傳一個 JSON 陣列，每份一個物件：

```
[{{"label": "A", "click_appeal": 3, "click_reason": "一句理由", "violations": [{{"quote": "原句", "rule": "CLAIMS", "reason": "理由"}}]}}]
```

## 大綱
"""


def rules_text(policy):
    lines = [f"- **{r['id']}**：{r['instruction']}" for r in policy["rules"]]
    lines.append(f"- 兩個指定詞（literal_guard_terms）：{'、'.join(policy['literal_guard_terms'])}")
    return "\n".join(lines)


def outline(run_dir, which):
    state = json.loads((Path(run_dir) / "state.json").read_text(encoding="utf-8"))
    meta = json.loads((Path(run_dir) / "metadata.json").read_text(encoding="utf-8"))
    if which == "final":
        draft = state["final"]
        if not draft:
            raise SystemExit(f"{run_dir} has no final outline")
    else:
        draft = next(e["output"] for e in state["history"] if e["node"] == "planner" and e["iteration"] == 1)
    return {"title": draft["title"], "sections": draft["sections"]}, {
        "run": Path(run_dir).name, "which": which, "prompt_version": meta.get("prompt_version", "v6"),
        "status": state["status"]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--item", action="append", required=True, help="<run_dir>:final or <run_dir>:round1")
    ap.add_argument("--package", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--seed", type=int, required=True)
    args = ap.parse_args()
    if Path(args.package).resolve().parent == Path(args.key).resolve().parent:
        raise SystemExit("keep the key outside the package folder")
    items = []
    for spec in args.item:
        run_dir, which = spec.rsplit(":", 1)
        items.append(outline(run_dir, which))
    random.Random(args.seed).shuffle(items)
    policy = json.loads((HERE / "policy.json").read_text(encoding="utf-8"))
    parts = [INSTRUCTIONS.format(n=len(items), rules=rules_text(policy))]
    key = {"seed": args.seed, "labels": {}}
    for label, (text, source) in zip(string.ascii_uppercase, items):
        body = "\n".join(f"{i}. {s}" for i, s in enumerate(text["sections"], 1))
        parts.append(f"### 稿 {label}\n\n**標題：{text['title']}**\n\n{body}\n")
        key["labels"][label] = source
    Path(args.package).parent.mkdir(parents=True, exist_ok=True)
    Path(args.key).parent.mkdir(parents=True, exist_ok=True)
    Path(args.package).write_text("\n".join(parts), encoding="utf-8", newline="\n")
    Path(args.key).write_text(json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {args.package} ({len(items)} outlines) and {args.key}")


if __name__ == "__main__":
    main()
