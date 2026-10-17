#!/usr/bin/env python3
"""Draw the report and slide figures in deliverable/img/ from recorded data (no model, no network).

  python scripts/make_figures.py [--chrome PATH]

Each figure is an HTML page drawn at a fixed CSS size and captured with headless Chrome, so the text uses the Noto Sans
TC font installed on the machine. Numbers come from evaluation/v08/verdict.json; the report excerpt is checked to be a
verbatim substring of the round-5 report of the lessons-ledger arm. Sizes follow docs/DELIVERABLE_FORMAT.md:
slide-architecture.png is shared with doc.md (1600 px wide, smallest text 30 px); the other three sit on the right of a
split slide and are also used in doc.md (1600 x 1070, smallest text 36 px). The script refuses to write a figure whose
HTML declares a smaller font size.
"""
import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
OUT = TASK / 'deliverable' / 'img'
V08 = TASK / 'evaluation' / 'v08'

INK, MUTED, LINE = '#1F2A30', '#5F6B70', '#C9D3D0'
BLUE, BLUE_TINT = '#2463A6', '#EAF2FB'
GREEN, GREEN_TINT, GREEN_DARK = '#0E8A6A', '#E3F1EC', '#0B5E49'
AMBER, AMBER_TINT = '#A86A00', '#FFF4DB'
MODEL, GUARD, HUMAN = '#5A3E8C', '#46545B', '#B5451B'
CONTROL, LEDGER, NATIVE = '#7B868B', GREEN, '#7A4FB8'
BAD = '#A33A1D'
CHROME = ['C:/Program Files/Google/Chrome/Application/chrome.exe',
          'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
          'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
          '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
          '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome']

PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;padding:0;background:#fff}}
body{{width:{w}px;height:{h}px;position:relative;overflow:hidden;font-family:"Noto Sans TC";color:#1F2A30}}
{css}</style></head><body>{body}</body></html>"""


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def num(n):
    return f'{n:,}'


# Architecture (doc and slide 3) ------------------------------------------------------------------------------------
def architecture(series):
    ledger, native = series['ledger'], series['native']
    l1, l5 = ledger[0]['calls'], ledger[4]['calls']
    median = sorted(p['cost'] for p in series['control'])[2]
    ratio = f"{native[4]['cost'] / median:.2f}"
    css = """
.box{position:absolute;box-sizing:border-box;border:4px solid;border-radius:18px;padding:14px 20px}
.res{background:#EAF2FB;border-color:#2463A6}.learn{background:#E3F1EC;border-color:#0E8A6A}
.eval{background:#FFF4DB;border-color:#A86A00}
.h{font-size:36px;font-weight:700;line-height:1.25}
.b{font-size:30px;line-height:1.38}
.r{font-size:30px;font-weight:700;line-height:1.38;margin-top:6px}
.tag{display:inline-block;font-size:30px;font-weight:700;line-height:1.35;padding:0 12px;border-radius:10px;
     margin:6px 0 4px;color:#fff}
.model{background:#5A3E8C}.guard{background:#46545B}.human{background:#B5451B}
.ext{background:#fff;color:#46545B;border:3px solid #8A969B;padding:0 10px}
.lbl{position:absolute;font-size:30px;font-weight:700;line-height:1;color:#46545B;white-space:nowrap}
.legend{position:absolute;top:16px;left:40px;font-size:30px;font-weight:700;line-height:1.3;white-space:nowrap}
.legend span{display:inline-block;margin-right:44px}
.legend i{display:inline-block;width:26px;height:26px;border-radius:6px;margin-right:12px;vertical-align:-3px}
svg{position:absolute;left:0;top:0}"""
    arrow = '<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="#46545B" stroke-width="5" marker-end="url(#a){}"/>'

    def both(x1, y1, x2, y2):
        return arrow.format(x1, y1, x2, y2, '" marker-start="url(#s)')

    def one(x1, y1, x2, y2):
        return arrow.format(x1, y1, x2, y2, '')
    svg = ('<svg width="1600" height="960"><defs>'
           '<marker id="a" markerWidth="16" markerHeight="16" refX="13" refY="8" orient="auto" '
           'markerUnits="userSpaceOnUse"><path d="M0,0 L16,8 L0,16 z" fill="#46545B"/></marker>'
           '<marker id="s" markerWidth="16" markerHeight="16" refX="3" refY="8" orient="auto" '
           'markerUnits="userSpaceOnUse"><path d="M16,0 L0,8 L16,16 z" fill="#46545B"/></marker></defs>'
           + both(476, 195, 564, 195) + both(1076, 195, 1154, 195)
           + both(255, 312, 255, 378) + both(700, 312, 700, 378)
           + one(1076, 282, 1154, 400) + one(1360, 506, 1360, 560)
           + one(255, 738, 255, 670) + one(820, 738, 820, 670) + '</svg>')

    def box(cls, x, y, w, h, inner):
        return f'<div class="box {cls}" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px">{inner}</div>'

    def lbl(x, y, text):
        return f'<div class="lbl" style="left:{x}px;top:{y}px">{text}</div>'
    body = (
        '<div class="legend">'
        f'<span><i style="background:{BLUE}"></i>研究：Agent 自己做，程式把關</span>'
        f'<span><i style="background:{GREEN}"></i>學習：兩種做法，實測比較</span>'
        f'<span><i style="background:{AMBER}"></i>評估：判準先寫好並鎖定</span></div>'
        + svg
        + box('res', 40, 84, 436, 228, '<div class="h">Hermes ＋ LLM</div><span class="tag model">模型判斷</span>'
              '<div class="b">決定查什麼、何時收斂<br>報告分已知、推論、未知</div>')
        + box('res', 564, 84, 512, 228, '<div class="h">六個唯讀工具＋控制器</div><span class="tag guard">程式把關</span>'
              '<div class="b">robots、允許網域、預算上限<br>引用必須對得上本次原文</div>')
        + box('res', 1154, 84, 406, 228, '<div class="h">2030.tw 與公開搜尋</div><span class="tag ext">外部資料</span>'
              '<div class="b">頁面內容只當資料，<br>不當指令</div>')
        + box('learn', 40, 378, 436, 292, '<div class="h">Hermes 原生學習</div><span class="tag model">模型判斷</span>'
              '<span class="b" style="margin-left:14px">僅比較實驗</span>'
              '<div class="b">研究後模型回顧對話，<br>自己寫 skill 與記憶</div>'
              f'<div class="r" style="color:{BAD}">實測：沒變快，成本為<br>對照中位數 {ratio} 倍：退步</div>')
        + box('learn', 564, 378, 512, 292, '<div class="h">lessons 帳本（自製）</div><span class="tag guard">程式把關</span>'
              '<div class="b">只記控制器量到的事實<br>與人工審查，用前重抓</div>'
              f'<div class="r" style="color:{GREEN_DARK}">實測：找目標頁 {l1} → {l5} 次呼叫<br>省下的預算轉去查證：改善</div>')
        + box('res', 1154, 378, 406, 128, '<div class="h">證據庫</div>'
              '<div class="b">存原文快照與 SHA-256</div>')
        + box('eval', 1154, 560, 406, 380, '<div class="h">判準先鎖定的評估</div><span class="tag guard">程式計分＋盲評</span>'
              '<div class="b">三組從零各跑 5 次<br>第 5 次對第 1 次<br>與不學習的對照組<br>沒學過的保留站查傷害<br>報告與學到的內容盲評</div>')
        + box('learn', 40, 738, 1036, 202, '<div class="h">人工審查　<span class="tag human" style="margin:0">人決定</span></div>'
              '<div class="b" style="margin-top:8px">標出沒有依據的主張，回饋給兩種學習；<br>本實驗由 Claude 在作者授權下代審；登入、授權與發布由人決定</div>')
        + lbl(278, 330, '回顧／載入') + lbl(722, 330, '量測寫入／重抓交出')
        + lbl(1384, 518, '讀證據計分') + lbl(278, 689, '審查回饋') + lbl(843, 689, '審查回饋'))
    return dict(name='slide-architecture.png', w=1600, h=960, min_px=30, css=css, body=body)


# Report excerpt (slide 4) ------------------------------------------------------------------------------------------
def report_excerpt(report_text):
    items = [
        ('已知', BLUE, ['首頁「線上娛樂城推薦」連到/wordcup/；該樞紐直接連到3a娛樂城及娛樂城目標頁'],
         '證據 c6fbcd7d、b8ae1633、ad974c98'),
        ('已知', BLUE, ['3A頁有出金半小時到一小時、最低入金1000元及手機版、客服FAQ等說法',
                       '因此不能稱兩頁完全沒有實用資訊或風險提醒。'],
         '證據 ad974c98、db55111b'),
        ('推論', MODEL, ['兩個目標頁共同採用特色、遊戲、出金安全、註冊、優惠、客服、FAQ、總結等段落骨架',
                       '這支持模板化關鍵字覆蓋的推論，不能確認生成方式、全站重複比例或Google懲罰。'],
         '證據 ad974c98、db55111b'),
        ('未知', MUTED, ['本輪未確認正向站外提及，不能據此宣稱沒有backlinks。'], None),
        ('行動', GREEN, ['若我方適合承接，先做少量證據型頁：娛樂城主詞頁提供可重現的比較方法、條款與風險矩陣'], None),
    ]
    for _, _, parts, _ in items:
        for part in parts:
            if part not in report_text:
                raise SystemExit(f'excerpt is not verbatim in the report: {part}')
    css = """
.cap{position:absolute;left:56px;top:30px;font-size:36px;color:#5F6B70;font-weight:700}
.card{position:absolute;left:40px;top:100px;width:1520px;height:930px;box-sizing:border-box;background:#F6F8F7;
      border:3px solid #C9D3D0;border-radius:20px;padding:34px 40px}
.row{display:flex;gap:28px;margin-bottom:34px}
.chip{flex:0 0 auto;font-size:36px;font-weight:700;color:#fff;border-radius:12px;padding:2px 16px;height:fit-content}
.t{font-size:36px;line-height:1.45}
.ev{font-size:36px;line-height:1.4;color:#5F6B70;font-family:Consolas,"Noto Sans TC",monospace;margin-top:6px}"""
    rows = ''.join(
        f'<div class="row"><div class="chip" style="background:{color}">{label}</div><div>'
        f'<div class="t">{"……".join(esc(p) for p in parts)}</div>'
        + (f'<div class="ev">{ev}</div>' if ev else '') + '</div></div>'
        for label, color, parts, ev in items)
    body = '<div class="cap">lessons 帳本組第 5 次的報告（節錄，原文照錄）</div>' + f'<div class="card">{rows}</div>'
    return dict(name='slide-report.png', w=1600, h=1070, min_px=36, css=css, body=body)


# Line charts (slides 5 and 6) --------------------------------------------------------------------------------------
def line_chart(name, title, series, field, lo, hi, step, band, fmt, threshold=None, callout=None):
    w, h = 1600, 1070
    x0, x1, y0, y1 = 210, 1270, 200, 940
    sx = lambda r: x0 + (r - 1) * (x1 - x0) / 4
    sy = lambda v: y1 - (v - lo) * (y1 - y0) / (hi - lo)
    out = [f'<svg width="{w}" height="{h}" font-family="Noto Sans TC">']
    out.append(f'<text x="40" y="60" font-size="36" font-weight="700" fill="{INK}">{esc(title)}</text>')
    legend = [('不學習的對照組', CONTROL, '12 8', 40), ('lessons 帳本', LEDGER, '', 430), ('Hermes 原生', NATIVE, '', 790)]
    for label, color, dash, lx in legend:
        out.append(f'<line x1="{lx}" y1="122" x2="{lx + 56}" y2="122" stroke="{color}" stroke-width="7" '
                   f'stroke-dasharray="{dash}"/>')
        out.append(f'<text x="{lx + 70}" y="134" font-size="36" fill="{INK}">{esc(label)}</text>')
    b_lo, b_hi = band
    out.append(f'<rect x="{x0}" y="{sy(b_hi)}" width="{x1 - x0}" height="{max(sy(b_lo) - sy(b_hi), 6)}" '
               f'fill="#E6EAEB"/>')
    v = lo
    while v <= hi:
        y = sy(v)
        out.append(f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="{LINE}" stroke-width="2"/>')
        out.append(f'<text x="{x0 - 18}" y="{y + 12}" font-size="36" fill="{MUTED}" text-anchor="end">{fmt(v)}</text>')
        v += step
    for r in range(1, 6):
        out.append(f'<text x="{sx(r)}" y="{y1 + 62}" font-size="36" fill="{INK}" text-anchor="middle">第 {r} 次</text>')
    out.append(f'<text x="{x0 + 14}" y="{sy(b_hi) - 14 if field == "calls" else sy(b_lo) + 44}" font-size="36" '
               f'fill="{MUTED}">對照組範圍</text>')
    ends = []
    if threshold:
        value = threshold[0]
        out.append(f'<line x1="{x0}" y1="{sy(value)}" x2="{x1}" y2="{sy(value)}" stroke="{BAD}" stroke-width="4" '
                   f'stroke-dasharray="14 10"/>')
        ends.append([sy(value), BAD, f'門檻 {fmt(value)}'])
        out.append(f'<text x="660" y="{sy(value) + 56}" font-size="36" fill="{BAD}">{esc(threshold[1])}</text>')
    for arm, color, dash, label in (('control', CONTROL, '12 8', '對照'), ('native', NATIVE, '', '原生'),
                                    ('ledger', LEDGER, '', '帳本')):
        vals = [p[field] for p in series[arm]]
        pts = ' '.join(f'{sx(r)},{sy(v)}' for r, v in enumerate(vals, 1))
        out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="7" stroke-dasharray="{dash}" '
                   f'stroke-linejoin="round"/>')
        for r, v in enumerate(vals, 1):
            out.append(f'<circle cx="{sx(r)}" cy="{sy(v)}" r="11" fill="{color}"/>')
        ends.append([sy(vals[-1]), color, f'{label} {fmt(vals[-1])}'])
    ends.sort()
    for i in range(1, len(ends)):  # keep end labels at least one line apart
        ends[i][0] = max(ends[i][0], ends[i - 1][0] + 46)
    for y, color, text in ends:
        out.append(f'<text x="{x1 + 26}" y="{y + 12}" font-size="36" font-weight="700" fill="{color}">{esc(text)}</text>')
    if callout:
        cx, cy, text, color = callout
        out.append(f'<text x="{cx}" y="{cy}" font-size="40" font-weight="700" fill="{color}">{esc(text)}</text>')
    out.append('</svg>')
    return dict(name=name, w=w, h=h, min_px=36, css='svg{position:absolute;left:0;top:0}', body=''.join(out))


# Rendering ---------------------------------------------------------------------------------------------------------
def smallest_font(html):
    sizes = [int(x) for x in re.findall(r'font-size:\s*(\d+)px', html)]
    sizes += [int(x) for x in re.findall(r'font-size="(\d+)"', html)]
    return min(sizes)


def render(fig, chrome, tmp):
    html = PAGE.format(w=fig['w'], h=fig['h'], css=fig['css'], body=fig['body'])
    small = smallest_font(html)
    if small < fig['min_px']:
        raise SystemExit(f"{fig['name']}: smallest text {small}px is below {fig['min_px']}px")
    page = Path(tmp) / (fig['name'] + '.html')
    page.write_text(html, encoding='utf-8')
    shot = Path(tmp) / fig['name']
    subprocess.run([chrome, '--headless=new', '--disable-gpu', '--hide-scrollbars', '--force-device-scale-factor=1',
                    f"--window-size={fig['w']},{fig['h']}", f'--user-data-dir={Path(tmp) / "profile"}',
                    f'--screenshot={shot}', page.as_uri()], check=True, capture_output=True, timeout=120)
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(shot, OUT / fig['name'])
    print(f"{OUT / fig['name']}  {fig['w']}x{fig['h']}  smallest text {small}px")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--chrome', help='path to Chrome or Edge')
    args = ap.parse_args()
    chrome = args.chrome or next((c for c in CHROME if Path(c).exists()), None) or shutil.which('google-chrome')
    if not chrome:
        raise SystemExit('Chrome not found; pass --chrome')
    verdict = read(V08 / 'verdict.json')
    series = verdict['series']
    l5 = next(e for e in read(V08 / 'steps.json') if e['step'] == 'L5' and e.get('settled'))
    report = (TASK / l5['root'] / f"{l5['run_id']}-report.md").read_text(encoding='utf-8')
    band = verdict['control_band']
    native = series['native']
    median = sorted(p['cost'] for p in series['control'])[2]
    figures = [
        architecture(series),
        report_excerpt(report),
        line_chart('slide-calls.png', '讀到目標頁之前的工具呼叫（次，越少越快）', series, 'calls', 0, 10, 2,
                   band['calls'], str, callout=(560, 690, '帳本組第 2 次起只要 1 次', GREEN_DARK)),
        line_chart('slide-cost.png', '每次研究的成本：未命中快取的輸入＋輸出（tokens，越低越省）', series, 'cost',
                   40000, 90000, 10000, band['cost'], num,
                   threshold=(round(median * 1.3), f'退步門檻＝對照中位數 {num(median)} × 1.3'),
                   callout=(480, 250, f'原生第 5 次是對照中位數的 {native[4]["cost"] / median:.2f} 倍', BAD)),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        for fig in figures:
            render(fig, chrome, tmp)


if __name__ == '__main__':
    main()
