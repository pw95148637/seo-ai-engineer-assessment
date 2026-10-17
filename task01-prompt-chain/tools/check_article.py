#!/usr/bin/env python3
"""文章機械檢查：只量字面特徵，不判斷內容真假或品質（那是主控與 C 段的工作）。

文章的格式約定（B2、C2 的 prompt 已寫明）：
- 開頭與結尾的揭露句都包含「不推薦任何平台」。
- 文末來源段以「資料來源」為標題（# 標題或粗體皆可），之後的內容不算正文。

用法：
  python tools/check_article.py outputs/B-draft.md
  python tools/check_article.py outputs/final.md outputs/baseline.md --compare
  python tools/check_article.py outputs/B-draft.md --quotes evidence-pack.md inputs/experience.md
  python tools/check_article.py outputs/C-revised.md --numbers-from outputs/B-draft.md
未通過時 exit 1（--compare 一律 exit 0）。--quotes 只列出找不到逐字出處的引文，不影響 pass。
--numbers-from 用於修正步驟：列出原稿正文有、修正後正文少掉的數字，不影響 pass，交給主控判斷是刪了事實還是合理精簡。
"""
from collections import Counter
import argparse
import json
import re
import sys
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8")

AI_PHRASES = [
    "作為一個AI", "作為一個 AI", "身為語言模型", "作為語言模型", "我無法提供",
    "值得一提的是", "不可否認", "事實上", "總而言之", "綜上所述", "總的來說", "整體而言",
    "令人驚艷", "無與倫比", "超乎想像", "極致", "完美", "頂級", "穩定出金", "秒到帳",
    "希望這篇對你有幫助", "讓我們一起", "心跳加速", "腦袋一片空白", "五味雜陳", "如坐針氈",
    "進行一個", "信息", "視頻", "質量", "賬號", "充值",
    "首選", "必玩", "好康", "福利滿滿",
]
DISCLOSURE_KEY = "不推薦任何平台"
BODY_MIN = 3000
REFS_HEADING = re.compile(r"^(#+\s*|\*\*)?(資料來源|參考資料|寫作方式)")
QUOTE_MIN = 6  # 短於此的引文多半是術語或畫面字樣，不比對


def split_main(text):
    """回傳資料來源段之前的全文（含標題與揭露句）。"""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if REFS_HEADING.match(line.strip()):
            return "\n".join(lines[:i])
    return text


def split_body(text):
    """去掉標題行、揭露句所在行與資料來源段，剩下正文。"""
    return "\n".join(
        line for line in split_main(text).splitlines()
        if not line.strip().startswith("#") and DISCLOSURE_KEY not in line
    )


def norm(s):
    return re.sub(r"\s+", "", s)


def quote_check(body, sources):
    existing = [p for p in sources if Path(p).exists()]
    corpus = norm("\n".join(Path(p).read_text(encoding="utf-8") for p in existing))
    quotes = [q for q in re.findall(r"「([^」]+)」", body) if len(norm(q)) >= QUOTE_MIN]
    return {
        "sources_missing": [p for p in sources if p not in existing],
        "quotes_checked": len(quotes),
        "not_found_verbatim": sorted({q for q in quotes if norm(q) not in corpus}),
    }


NUMBER = re.compile(r"[−-]?\d[\d,]*(?:\.\d+)?%?")


def numbers_dropped(body, before_path):
    """原稿正文出現、編輯後正文少掉的數字（含次數差）。"""
    before = Counter(NUMBER.findall(split_body(Path(before_path).read_text(encoding="utf-8"))))
    after = Counter(NUMBER.findall(body))
    return {n: c for n, c in (before - after).items()}


def measure(path, sources, numbers_from=None):
    text = Path(path).read_text(encoding="utf-8")
    main = split_main(text)
    body = split_body(text)
    unquoted = re.sub(r"「[^」]*」|『[^』]*』|“[^”]*”|\"[^\"]*\"", "", body).replace(" ", "")
    hits = {p: unquoted.count(p.replace(" ", "")) for p in AI_PHRASES if p.replace(" ", "") in unquoted}
    # 揭露位置以「資料來源段之前」的長度為分母，來源清單再長也不影響結尾判斷
    positions = [round(m.start() / max(len(main), 1), 3) for m in re.finditer(DISCLOSURE_KEY, main)]
    result = {
        "file": str(path),
        "body_cjk_chars": len(re.findall(r"[一-鿿]", body)),
        "disclosure_positions": positions,
        "ai_phrase_hits_outside_quotes": hits,
        "exclamation_marks": body.count("！") + body.count("!"),
        "first_second_last_pattern": len(re.findall(r"首先.{0,200}?其次.{0,200}?最後", body, re.S)),
        "links": len(re.findall(r"https?://", text)),
    }
    result["checks"] = {
        "body_at_least_3000": result["body_cjk_chars"] >= BODY_MIN,
        "disclosure_at_start_and_end": len(positions) >= 2 and positions[0] < 0.15 and positions[-1] > 0.85,
        "no_ai_phrases": not hits,
        "no_exclamation": result["exclamation_marks"] == 0,
    }
    result["pass"] = all(result["checks"].values())
    if sources:
        result["quote_check"] = quote_check(body, sources)
    if numbers_from:
        result["numbers_dropped"] = numbers_dropped(body, numbers_from)
    return result


def main():
    ap = argparse.ArgumentParser(description="文章機械檢查（字數、揭露位置、AI 腔字詞、驚嘆號、引文出處）")
    ap.add_argument("files", nargs="+", help="要檢查的文章")
    ap.add_argument("--compare", action="store_true", help="多篇並列比較主要指標")
    ap.add_argument("--quotes", nargs="+", metavar="SOURCE", default=[],
                    help="比對正文「」引文是否逐字出自這些來源檔；不存在的檔案略過並列在 sources_missing")
    ap.add_argument("--numbers-from", metavar="BEFORE",
                    help="列出這份原稿正文有、受檢文章正文少掉的數字（用於只改口吻的編輯步驟）")
    args = ap.parse_args()
    results = [measure(f, args.quotes, args.numbers_from) for f in args.files]
    if args.compare:
        keys = ["body_cjk_chars", "disclosure_positions", "ai_phrase_hits_outside_quotes",
                "exclamation_marks", "first_second_last_pattern", "links", "pass"]
        print(json.dumps({k: {r["file"]: r[k] for r in results} for k in keys}, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(results[0] if len(results) == 1 else results, ensure_ascii=False, indent=2))
    return 0 if all(r["pass"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
