#!/usr/bin/env python3
"""Draw the report and slide figures in deliverable/img/ from recorded data (no model, no network).

  python scripts/make_figures.py [--chrome PATH]

Each figure is an HTML page drawn at a fixed CSS size and captured with headless Chrome, so the text uses the Noto Sans
TC font installed on the machine. Numbers come from evaluation/v09/verdict.json; the report excerpt is checked to be a
verbatim substring of the round-10 report of the learning arm. Sizes follow docs/DELIVERABLE_FORMAT.md:
slide-architecture.png is shared with doc.md (1600 px wide, smallest text 30 px); the other two sit on the right of a
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
V09 = TASK / 'evaluation' / 'v09'

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


# Architecture (doc and slide 4) ------------------------------------------------------------------------------------
# What the system is, not how it was evaluated: colours mark who acts (person, model, program, data only the program
# writes, evaluation, outside world); the comparison runs and their arms are described in doc.md and the deck.
ROLE = {
    'human': ('#FBECE6', '#B5451B'), 'model': ('#F1ECF8', '#5A3E8C'), 'program': ('#EAF2FB', '#2463A6'),
    'data': ('#E3F1EC', '#0E8A6A'), 'eval': ('#FFF4DB', '#A86A00'), 'outside': ('#FFFFFF', '#8A969B'),
}


def architecture():
    w, h = 1600, 940
    css = """
.box{position:absolute;box-sizing:border-box;border:4px solid;border-radius:18px;padding:14px 18px}
.h{font-size:36px;font-weight:700;line-height:1.25;margin-bottom:6px}
.b{font-size:30px;line-height:1.38}
.m{font-size:30px;line-height:1.38;color:#5F6B70}
.p{position:absolute;left:52px;font-size:30px;line-height:1.38}
.lbl{position:absolute;font-size:30px;font-weight:700;line-height:1;color:#46545B;white-space:nowrap}
.legend{position:absolute;top:22px;left:30px;font-size:30px;font-weight:700;line-height:1.3;white-space:nowrap}
.legend span{display:inline-block;margin-right:38px}
.legend i{display:inline-block;width:26px;height:26px;border-radius:6px;margin-right:10px;vertical-align:-3px;
          border:3px solid;box-sizing:border-box}
svg{position:absolute;left:0;top:0}"""
    ink = '#46545B'
    line = '<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="%s" stroke-width="5" marker-end="url(#a){}"/>' % ink

    def one(x1, y1, x2, y2):
        return line.format(x1, y1, x2, y2, '')

    def both(x1, y1, x2, y2):
        return line.format(x1, y1, x2, y2, '" marker-start="url(#s)')

    def box(role, x, y, bw, bh, inner):
        bg, border = ROLE[role]
        return (f'<div class="box" style="left:{x}px;top:{y}px;width:{bw}px;height:{bh}px;background:{bg};'
                f'border-color:{border}">{inner}</div>')

    def lbl(x, y, text):
        return f'<div class="lbl" style="left:{x}px;top:{y}px">{text}</div>'

    # Columns: person 30-280 | model and memory 380-760 | program and evidence 920-1270 | outside and evaluation 1350-1570
    # Rows: research 96-346 | memory and evidence 426-676 | hand-back 756-916
    r1, r2, r3 = 221, 551, 836
    svg = (f'<svg width="{w}" height="{h}"><defs>'
           f'<marker id="a" markerWidth="16" markerHeight="16" refX="13" refY="8" orient="auto" '
           f'markerUnits="userSpaceOnUse"><path d="M0,0 L16,8 L0,16 z" fill="{ink}"/></marker>'
           f'<marker id="s" markerWidth="16" markerHeight="16" refX="3" refY="8" orient="auto" '
           f'markerUnits="userSpaceOnUse"><path d="M16,0 L0,8 L16,16 z" fill="{ink}"/></marker></defs>'
           + one(280, r1, 380, r1)          # person sets the scope
           + both(760, r1, 920, r1)         # model calls tools
           + both(1270, r1, 1350, r1)       # controller reads the web
           + one(1095, 346, 1095, 426)      # controller stores originals
           + one(920, r2, 760, r2)          # after the run the controller writes memory
           + one(570, 426, 570, 346)        # re-checked memory goes to the model
           + one(280, r2, 380, r2)          # person reviews or vetoes
           + one(1270, r2, 1350, r2)        # evaluation reads the evidence
           + one(1095, 676, 1095, 756)      # hand-back list from the record
           + one(920, r3, 280, r3)          # decisions go back to the person
           + '</svg>')
    legend = ''.join(f'<span><i style="background:{ROLE[r][0]};border-color:{ROLE[r][1]}"></i>{t}</span>'
                     for r, t in (('human', '人決定'), ('model', '模型判斷'), ('program', '程式'),
                                  ('data', '只由程式寫入的資料'), ('eval', '評估'), ('outside', '外部')))
    person = (box('human', 30, 96, 250, 820, '<div class="h">人</div>')
              + '<div class="p" style="top:160px">研究對象<br>預算、網域<br>登入、付費</div>'
              + '<div class="p" style="top:510px">人工審查<br>否決經驗</div>'
              + '<div class="p" style="top:795px">採納建議<br>對外發布</div>')
    body = (
        f'<div class="legend">{legend}</div>' + svg + person
        + box('model', 380, 96, 380, 250, '<div class="h">Hermes＋LLM</div>'
              '<div class="b">決定讀什麼、何時收斂<br>報告分已知、推論、未知</div>'
              '<div class="m">內建記憶與 skill：關閉</div>')
        + box('program', 920, 96, 350, 250, '<div class="h">唯讀工具＋控制器</div>'
              '<div class="b">robots、網域、預算<br>引用要對得上原文<br>越界直接擋下</div>')
        + box('outside', 1350, 96, 220, 250, '<div class="h">2030.tw<br>公開搜尋</div>'
              '<div class="b">只當資料，<br>不當指令</div>')
        + box('data', 380, 426, 380, 250, '<div class="h">帳本＋研究記憶</div>'
              '<div class="b">帳本：目標頁位置、<br>失敗做法、人工審查<br>研究記憶：上次報告的<br>發現、未讀頁、未知項</div>')
        + box('data', 920, 426, 350, 250, '<div class="h">證據庫與報告</div>'
              '<div class="b">原文快照＋SHA-256<br>報告只能引用這裡</div>')
        + box('eval', 1350, 426, 220, 250, '<div class="h">評估</div>'
              '<div class="b">判準先鎖定<br>AI 盲評</div>')
        + box('program', 920, 756, 350, 160, '<div class="h">交還人類清單</div>'
              '<div class="b">研究後另外執行</div>')
        + lbl(301, r1 - 48, '設定') + lbl(780, r1 - 48, '呼叫工具') + lbl(1280, r1 - 48, '讀取')
        + lbl(1112, 371, '存原文') + lbl(588, 371, '重抓確認後交出')
        + lbl(765, r2 - 48, '研究後寫入') + lbl(301, r2 - 48, '審查') + lbl(1280, r2 - 48, '計分')
        + lbl(530, r3 - 48, '待人決定'))
    return dict(name='slide-architecture.png', w=w, h=h, min_px=30, css=css, body=body)


# Report excerpt (slide 3) ------------------------------------------------------------------------------------------
def report_excerpt(report_text):
    # (label, color, verbatim parts, evidence line, cut before the first part, cut after the last part).
    # Every cut, inside or at either end, is shown as an ellipsis so the excerpt never reads as a whole sentence.
    items = [
        ('已知', BLUE, ['3A、泛詞與富有頁結構化資料均混入相同MLB NewsArticle及指向MLB URL的WebPage；'
                       '3A正文顯示9月24日更新，Article dateModified為9月29日。'],
         '證據 05426b25、e9b41939、ffe6c810', False, False),
        ('已知', BLUE, ['反證：3A缺點頁實際談手機卡頓、APP更新、KYC等待一至兩天、高流水及客服轉交等待',
                       '不能稱完全無實用資訊或風險揭露，這些仍只是站方敘述，未核實為平台實況。'],
         '證據 2022feb1、e9b41939、ffe6c810', False, False),
        ('推論', MODEL, ['以分類、相關推薦內鏈及重複CTA集中導流的策略推論。未證明這套安排有效'], None, True, True),
        ('未知', MUTED, ['完整backlinks、錨文字與rel分布、付費或PBN關係、歷史外鏈及其排名貢獻皆未知。'], None, True, False),
        ('行動', GREEN, ['僅在可取得可公開引用的正式條款時製作58888等優惠頁，逐項說明資格、有效期、流水計算、適用遊戲與提領限制'],
         None, False, True),
    ]
    for _, _, parts, _, lead, trail in items:
        for part in parts:
            if part not in report_text:
                raise SystemExit(f'excerpt is not verbatim in the report: {part}')
        start = report_text.find(parts[0])
        end = report_text.find(parts[-1]) + len(parts[-1])
        if lead != (report_text[start - 1] not in '\n-： '):
            raise SystemExit(f'leading ellipsis flag does not match the report: {parts[0]}')
        if trail != (report_text[end - 1] != '。'):
            raise SystemExit(f'trailing ellipsis flag does not match the report: {parts[-1]}')
    css = """
.cap{position:absolute;left:56px;top:30px;font-size:36px;color:#5F6B70;font-weight:700}
.card{position:absolute;left:40px;top:100px;width:1520px;height:930px;box-sizing:border-box;background:#F6F8F7;
      border:3px solid #C9D3D0;border-radius:20px;padding:30px 40px}
.row{display:flex;gap:28px;margin-bottom:20px}
.chip{flex:0 0 auto;font-size:40px;font-weight:700;color:#fff;border-radius:12px;padding:2px 16px;height:fit-content}
.t{font-size:40px;line-height:1.4}
.ev{font-size:36px;line-height:1.4;color:#5F6B70;font-family:Consolas,"Noto Sans TC",monospace;margin-top:4px}"""
    rows = ''.join(
        f'<div class="row"><div class="chip" style="background:{color}">{label}</div><div>'
        f'<div class="t">{"……" if lead else ""}{"……".join(esc(p) for p in parts)}{"……" if trail else ""}</div>'
        + (f'<div class="ev">{ev}</div>' if ev else '') + '</div></div>'
        for label, color, parts, ev, lead, trail in items)
    body = '<div class="cap">帶經驗的組第 10 次的報告（節錄，原文照錄）</div>' + f'<div class="card">{rows}</div>'
    return dict(name='slide-report.png', w=1600, h=1070, min_px=36, css=css, body=body)


# Cumulative pages (slide 6) ----------------------------------------------------------------------------------------
def cumulative_chart(rows):
    w, h = 1600, 1070
    x0, x1, y0, y1 = 150, 1230, 200, 920
    lo, hi, step = 0, 25, 5
    sx = lambda r: x0 + (r - 1) * (x1 - x0) / 9
    sy = lambda v: y1 - (v - lo) * (y1 - y0) / (hi - lo)
    # (prefix, color, dash, end label, legend): the learning arm differs by the whole bundle, not the memory alone.
    series = [('C', CONTROL, '12 8', '不學習', '不學習的組'),
              ('L', LEDGER, '', '帶經驗', '帶經驗的組（發現路徑、審查回饋、研究記憶）')]
    out = [f'<svg width="{w}" height="{h}" font-family="Noto Sans TC">',
           f'<text x="40" y="60" font-size="36" font-weight="700" fill="{INK}">'
           '十次研究累積讀過的不重複站內頁（頁，越多越廣）</text>']
    for i, (_, color, dash, _, legend) in enumerate(series):
        lx = 40 + i * 380
        out.append(f'<line x1="{lx}" y1="122" x2="{lx + 56}" y2="122" stroke="{color}" stroke-width="7" '
                   f'stroke-dasharray="{dash}"/>')
        out.append(f'<text x="{lx + 70}" y="134" font-size="36" fill="{INK}">{legend}</text>')
    v = lo
    while v <= hi:
        y = sy(v)
        out.append(f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="{LINE}" stroke-width="2"/>')
        out.append(f'<text x="{x0 - 18}" y="{y + 12}" font-size="36" fill="{MUTED}" text-anchor="end">{v}</text>')
        v += step
    for r in (1, 4, 7, 10):
        out.append(f'<text x="{sx(r)}" y="{y1 + 62}" font-size="36" fill="{INK}" text-anchor="middle">第 {r} 次</text>')
    ends = []
    for prefix, color, dash, label, _ in series:
        vals = [rows[f'{prefix}{r}']['cumulative_onsite'] for r in range(1, 11)]
        pts = ' '.join(f'{sx(r)},{sy(v)}' for r, v in enumerate(vals, 1))
        out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="7" stroke-dasharray="{dash}" '
                   f'stroke-linejoin="round"/>')
        for r, v in enumerate(vals, 1):
            out.append(f'<circle cx="{sx(r)}" cy="{sy(v)}" r="11" fill="{color}"/>')
        ends.append([sy(vals[-1]), color, f'{label} {vals[-1]}'])
    ends.sort()
    for i in range(1, len(ends)):
        ends[i][0] = max(ends[i][0], ends[i - 1][0] + 46)
    for y, color, text in ends:
        out.append(f'<text x="{x1 + 26}" y="{y + 12}" font-size="36" font-weight="700" fill="{color}">{esc(text)}</text>')
    last = rows['C10']['cumulative_onsite']
    flat = min(r for r in range(1, 11) if all(rows[f'C{k}']['cumulative_onsite'] == last for k in range(r, 11)))
    out.append(f'<text x="{sx(flat) - 40}" y="{sy(last) + 70}" font-size="36" font-weight="700" fill="{MUTED}">'
               f'不學習的組第 {flat} 次後沒有再讀到新頁</text>')
    out.append('</svg>')
    return dict(name='slide-cumulative.png', w=w, h=h, min_px=36, css='svg{position:absolute;left:0;top:0}',
                body=''.join(out))


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
    verdict = read(V09 / 'verdict.json')
    l10 = next(e for e in read(V09 / 'steps.json') if e['step'] == 'L10' and e.get('settled'))
    report = (TASK / l10['root'] / f"{l10['run_id']}-report.md").read_text(encoding='utf-8')
    figures = [
        architecture(),
        report_excerpt(report),
        cumulative_chart(verdict['rows']),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        for fig in figures:
            render(fig, chrome, tmp)


if __name__ == '__main__':
    main()
