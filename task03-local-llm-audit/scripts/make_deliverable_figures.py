"""Draw the report and slide figures in deliverable/img/ from recorded data (no model, no GPU).

python scripts/make_deliverable_figures.py   (Windows: set PYTHONUTF8=1; needs Pillow and the Noto Sans TC font)
Reads evaluation/holdout8-comparison.json (run scripts/compare_holdout.py first), the eval kernel's holdout-raw.jsonl,
the split manifest, the frozen lock and the training log. Counts are computed from those files and every quoted model
or article sentence is checked to be a verbatim substring of them; only layout text is fixed here.
Sizes follow docs/DELIVERABLE_FORMAT.md: slide-architecture.png and holdout-scores-v2.png are shared with the report
(1600 px wide, text 30 px or larger); the other slide-*.png are 1920 px wide with text of 28 px or more."""
import json
import os
from decimal import Decimal, ROUND_HALF_UP
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

TASK = Path(__file__).resolve().parents[1]
OUT = TASK / 'deliverable' / 'img'
COMPARISON = TASK / 'evaluation' / 'holdout8-comparison.json'
POSTHOC = TASK / 'evaluation' / 'posthoc-results.json'  # post-freeze analysis (scripts/posthoc_analysis.py)
EVAL_OUT = TASK / 'kaggle-retrieved' / 'soulo-work03-v3-eval' / 'work03' / 'outputs'
TRAIN_OUT = TASK / 'kaggle-retrieved' / 'soulo-work03-v3b-train' / 'work03' / 'outputs'
SPLIT = TASK / 'data' / 'split-manifest.json'
ROOT_FROZEN = TRAIN_OUT.parent  # frozen bundle (prompt, knowledge) as retrieved from the train kernel

# Deck palette (scripts/build_office.py) plus a warm ramp for severity.
BG, INK, MUTED, ACCENT, TINT = '#FFFFFF', '#1F2A30', '#5F6B70', '#0E8A6A', '#EEF4F2'
WARN, WARN_TINT, LINE, CARD, CODE_BG = '#B5651D', '#FBEFE6', '#C9D3D0', '#F6F8F7', '#F3F5F4'
HIGHLIGHT, KEY, GREY_TILE, PARTIAL = '#FFE7A0', '#0B6B53', '#B9C3C0', '#8CC2B1'
SEVERITY = [('critical', '0–29', '#8F3A1C', '#FFFFFF'), ('major', '30–59', '#C46F34', '#FFFFFF'),
            ('minor', '60–84', '#E7BE82', INK), ('無缺失', '85–100', '#BFE0D4', INK)]
S = 2  # supersampling factor: draw at 2x, downsample for smooth edges

NO_START = set('，。、；：！？」』）》】,.;:!?)]}%')
NO_END = set('「『（《【([{')


def find_font():
    windir = Path(os.environ.get('WINDIR', 'C:/Windows'))
    for p in (windir / 'Fonts' / 'NotoSansTC-VF.ttf',
              Path.home() / 'AppData/Local/Microsoft/Windows/Fonts/NotoSansTC-VF.ttf',
              Path('/usr/share/fonts/truetype/noto/NotoSansTC-VF.ttf'),
              Path('/usr/share/fonts/opentype/noto/NotoSansTC-VF.ttf'),
              Path.home() / 'Library/Fonts/NotoSansTC-VF.ttf'):
        if p.exists():
            return p
    raise SystemExit('Need the Noto Sans TC variable font (NotoSansTC-VF.ttf)')


FONT_PATH = find_font()
_fonts = {}


def font(size, weight='Regular'):
    key = (size, weight)
    if key not in _fonts:
        f = ImageFont.truetype(str(FONT_PATH), size * S)
        f.set_variation_by_name(weight)
        _fonts[key] = f
    return _fonts[key]


def read_json(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def verbatim(source, part):
    if part not in source:
        raise SystemExit(f'not a verbatim excerpt: {part!r}')
    return part


class Canvas:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.im = Image.new('RGB', (w * S, h * S), BG)
        self.d = ImageDraw.Draw(self.im)

    # ---- shapes (all coordinates in output pixels)
    def rect(self, x, y, w, h, fill=None, outline=None, width=2, radius=14):
        self.d.rounded_rectangle([x * S, y * S, (x + w) * S, (y + h) * S], radius=radius * S, fill=fill,
                                 outline=outline, width=width * S if outline else 0)

    def line(self, pts, color=MUTED, width=4):
        self.d.line([(x * S, y * S) for x, y in pts], fill=color, width=width * S, joint='curve')

    def head(self, x, y, angle_from, color, size=20):
        import math
        a = math.atan2(y - angle_from[1], x - angle_from[0])
        left = (x - size * math.cos(a) + size * 0.55 * math.sin(a), y - size * math.sin(a) - size * 0.55 * math.cos(a))
        right = (x - size * math.cos(a) - size * 0.55 * math.sin(a), y - size * math.sin(a) + size * 0.55 * math.cos(a))
        self.d.polygon([(x * S, y * S), (left[0] * S, left[1] * S), (right[0] * S, right[1] * S)], fill=color)

    def arrow(self, x0, y0, x1, y1, color=MUTED, width=4, size=20):
        import math
        a = math.atan2(y1 - y0, x1 - x0)
        self.line([(x0, y0), (x1 - size * 0.8 * math.cos(a), y1 - size * 0.8 * math.sin(a))], color, width)
        self.head(x1, y1, (x0, y0), color, size)

    def curve_arrow(self, p0, c0, c1, p1, color=WARN, width=4, size=20):
        pts = []
        for i in range(61):
            t = i / 60
            x = (1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * c0[0] + 3 * (1 - t) * t ** 2 * c1[0] + t ** 3 * p1[0]
            y = (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * c0[1] + 3 * (1 - t) * t ** 2 * c1[1] + t ** 3 * p1[1]
            pts.append((x, y))
        cut = max(i for i, (x, y) in enumerate(pts) if ((x - p1[0]) ** 2 + (y - p1[1]) ** 2) ** 0.5 >= size * 0.8)
        self.line(pts[:cut + 1], color, width)
        self.head(p1[0], p1[1], pts[cut], color, size)

    def lock(self, cx, cy, s, color):
        body_w, body_h = s * 0.62, s * 0.46
        bx, by = cx - body_w / 2, cy - body_h / 2 + s * 0.12
        self.d.arc([(cx - s * 0.2) * S, (by - s * 0.34) * S, (cx + s * 0.2) * S, (by + s * 0.12) * S], 180, 360,
                   fill=color, width=max(2, int(s * 0.09)) * S)
        self.d.line([((cx - s * 0.2) * S, (by - s * 0.12) * S), ((cx - s * 0.2) * S, by * S)], fill=color,
                    width=max(2, int(s * 0.09)) * S)
        self.d.line([((cx + s * 0.2) * S, (by - s * 0.12) * S), ((cx + s * 0.2) * S, by * S)], fill=color,
                    width=max(2, int(s * 0.09)) * S)
        self.rect(bx, by, body_w, body_h, fill=color, radius=max(2, int(s * 0.06)))

    # ---- text
    @staticmethod
    def _tokens(runs, size, weight, color):
        out = []
        for run in runs:
            text, style = (run, {}) if isinstance(run, str) else run
            st = {'size': size, 'weight': weight, 'color': color, 'bg': None}
            st.update(style)
            for u in re.findall(r'[A-Za-z0-9_.%+\-–/:#@&]+|[ \t]+|\n|.', text):
                out.append((u, st))
        return out

    def _layout(self, runs, width, size, weight, color, indent=0, cont_indent=0):
        lines, cur, cur_w = [], [], 0.0
        limit = width
        for tok, st in self._tokens(runs, size, weight, color):
            if tok == '\n':
                lines.append(cur)
                cur, cur_w = [], 0.0
                continue
            f = font(st['size'], st['weight'])
            tw = f.getlength(tok) / S
            first = not lines
            avail = limit - (indent if first else cont_indent)
            if cur and cur_w + tw > avail and not tok.isspace():
                carry = []
                if tok in NO_START and cur:
                    carry.append(cur.pop())
                    while carry[0][0] in NO_START and cur:
                        carry.insert(0, cur.pop())
                while cur and cur[-1][0] in NO_END:
                    carry.insert(0, cur.pop())
                while cur and cur[-1][0].isspace():
                    cur.pop()
                lines.append(cur)
                cur = carry
                cur_w = sum(font(s2['size'], s2['weight']).getlength(t2) / S for t2, s2 in cur)
            if not cur and tok.isspace() and lines:
                continue
            cur.append((tok, st))
            cur_w += tw
        if cur:
            lines.append(cur)
        return lines

    def text(self, x, y, width, runs, size=32, weight='Regular', color=INK, gap=1.42, align='left', indent=0,
             cont_indent=0, draw=True):
        """Lay out rich text in a box of the given width; returns the height used. runs: str or [(text, style)]."""
        runs = [runs] if isinstance(runs, str) else runs
        lines = self._layout(runs, width, size, weight, color, indent, cont_indent)
        line_h = size * gap
        if draw:
            for i, ln in enumerate(lines):
                lw = sum(font(st['size'], st['weight']).getlength(t) / S for t, st in ln)
                lx = x + (indent if i == 0 else cont_indent)
                if align == 'center':
                    lx = x + (width - lw) / 2
                elif align == 'right':
                    lx = x + width - lw
                top = y + i * line_h
                base = top + line_h / 2 + size * 0.36
                cx = lx
                spans = []
                for t, st in ln:
                    tw = font(st['size'], st['weight']).getlength(t) / S
                    if st['bg']:
                        if spans and spans[-1][2] == st['bg'] and abs(spans[-1][1] - cx) < 0.5:
                            spans[-1][1] = cx + tw
                        else:
                            spans.append([cx, cx + tw, st['bg']])
                    cx += tw
                for a, b, bg in spans:
                    self.rect(a - 4, top + line_h * 0.08, b - a + 8, line_h * 0.84, fill=bg, radius=6)
                cx = lx
                for t, st in ln:
                    f = font(st['size'], st['weight'])
                    self.d.text((cx * S, base * S), t, font=f, fill=st['color'], anchor='ls')
                    cx += f.getlength(t) / S
        return len(lines) * line_h

    def save(self, name):
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / name
        self.im.resize((self.w, self.h), Image.LANCZOS).save(path, optimize=True)
        print('wrote', path.relative_to(TASK))


# ---------------------------------------------------------------- data

def load():
    comp = read_json(COMPARISON)
    items = {it['ID']: it for it in comp['items']}
    raw = {}
    for line in (EVAL_OUT / 'holdout-raw.jsonl').read_text(encoding='utf-8').splitlines():
        r = json.loads(line)
        if r['attempt'] == 0:
            raw[r['ID']] = r['result']['raw']
    split = read_json(SPLIT)
    lock = read_json(TRAIN_OUT / 'frozen.json')
    training = read_json(TRAIN_OUT / 'training.json')
    return comp, items, raw, split, lock, training


# ---------------------------------------------------------------- figures

def one_decimal(x):
    """Round half up, as the report text does (21.25 -> 21.3)."""
    return str(Decimal(str(x)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))


def fig_problem(split, lock):
    """Slide 2: what the task asks, what makes it hard, and the approach; the 12/8 split as a picture."""
    n_train, n_test = len(split['train_ids']), len(split['holdout_ids'])
    c = Canvas(1920, 740)
    cols = [('原題要的', '本地模型像資深編輯審文章，\n用 JSON 給分數、原因、建議'),
            ('難處', f'只有 {n_train + n_test} 篇、沒有標準答案；\n{n_train} 篇資料，微調能學的很少'),
            ('我的做法', '規則寫進 prompt、事實寫成知識卡，\n格式交給程式；微調另做對照')]
    cw, gx = 586, 56
    x0 = (1920 - 3 * cw - 2 * gx) / 2
    for k, (head, body) in enumerate(cols):
        x = x0 + k * (cw + gx)
        col = WARN if k == 1 else ACCENT
        c.rect(x, 20, cw, 8, fill=col, radius=4)
        c.text(x, 44, cw, head, size=40, weight='Bold', color=col)
        c.text(x, 112, cw, body, size=34, gap=1.5)

    # 20 articles: train tiles and locked test tiles
    tile, tg, group_gap = 70, 12, 100
    w_train = n_train * tile + (n_train - 1) * tg
    w_test = n_test * tile + (n_test - 1) * tg
    tx = (1920 - w_train - group_gap - w_test) / 2
    ty = 290
    for i in range(n_train):
        c.rect(tx + i * (tile + tg), ty, tile, tile, fill=ACCENT, radius=12)
    gx0 = tx + w_train + group_gap
    for i in range(n_test):
        x = gx0 + i * (tile + tg)
        c.rect(x, ty, tile, tile, fill=GREY_TILE, radius=12)
        c.lock(x + tile / 2, ty + tile / 2, tile * 0.62, '#FFFFFF')
    c.text(tx, ty + tile + 18, w_train, [(f'{n_train} 篇訓練文章', {'weight': 'Bold', 'color': ACCENT})], size=36,
           align='center')
    c.text(tx, ty + tile + 72, w_train, '調 prompt、知識卡、微調，都只看這裡', size=32, align='center')
    c.text(gx0, ty + tile + 18, w_test, [(f'{n_test} 篇測試文章', {'weight': 'Bold', 'color': MUTED})], size=36,
           align='center')
    c.text(gx0, ty + tile + 72, w_test, '凍結之後才交給模型，只用來出報告', size=32, align='center')
    c.rect(30, 576, 1860, 140, fill=TINT, radius=16)
    c.text(30, 576 + (140 - 54) / 2, 1860,
           [('為什麼要鎖：', {'weight': 'Bold', 'color': ACCENT}),
            f'看著這 {n_test} 篇的結果回頭改，它們就變成訓練資料，報告的準確率不再可信'], size=36, align='center')
    c.save('slide-problem.png')


def fig_architecture(split, lock):
    """Shared by the report and slide 3 (1600 px wide, text 30 px or larger).
    Every element answers one of: how data flows and who judges; what code guards; why the test set stays clean."""
    n_train, n_test = len(split['train_ids']), len(split['holdout_ids'])
    n_locked = len(lock['hashes'])
    W, H = 1600, 770
    c = Canvas(W, H)
    JUDGE, GUARD = ACCENT, INK

    def tag(x, y, text, fill):
        w = 150
        c.rect(x, y, w, 44, fill=fill, radius=22)
        c.text(x, y + 1, w, [(text, {'weight': 'Bold', 'color': '#FFFFFF'})], size=30, gap=1.4, align='center')

    def box(x, y, w, h, title, sub=None, fill=CARD, outline=LINE, width=2, top=None):
        c.rect(x, y, w, h, fill=fill, outline=outline, width=width)
        th = c.text(0, 0, w - 36, [(title, {'weight': 'Bold'})], size=34, draw=False)
        sh = c.text(0, 0, w - 36, sub, size=30, draw=False) if sub else 0
        ty = y + (h - th - sh) / 2 if top is None else y + top
        c.text(x + 18, ty, w - 36, [(title, {'weight': 'Bold'})], size=34, align='center')
        if sub:
            c.text(x + 18, ty + th, w - 36, sub, size=30, align='center', color=INK)

    # lanes
    c.rect(8, 8, W - 16, 204, fill='#F7F9F8', radius=18)
    band2_bottom = 650
    c.rect(8, 236, W - 16, band2_bottom - 236, fill='#F7F9F8', radius=18)
    c.text(1150, 48, 430, [('訓練 Notebook', {'weight': 'Bold', 'color': MUTED})], size=32)
    c.text(1150, 96, 430, f'只看 {n_train} 篇', size=30, color=MUTED)
    c.text(26, 546, 330, [('評估 Notebook', {'weight': 'Bold', 'color': MUTED})], size=32)
    c.text(26, 592, 330, '不呼叫雲端 API', size=30, color=MUTED)

    # training lane
    box(26, 26, 400, 166, f'{n_train} 篇訓練文章', '調 prompt、知識卡、微調')
    cx, cy, cw_, ch = 520, 26, 560, 166
    box(cx, cy, cw_, ch, f'凍結 {n_locked} 個檔案', 'prompt、知識卡、權重記下雜湊', fill='#FFFFFF', outline=GUARD,
        width=3, top=64)
    tag(cx + (cw_ - 150) / 2, cy + 12, '程式把關', GUARD)
    c.arrow(426 + 8, 106, cx - 8, 106, width=4, size=20)

    # evaluation lane
    dx, dy, dw, dh = 26, 330, 260, 150
    box(dx, dy, dw, dh, f'{n_test} 篇測試文章')
    ex, ey, ew, eh = 370, 290, 380, 230
    box(ex, ey, ew, eh, 'Qwen3-8B', '找缺失、定嚴重度，\n先寫理由再給分', fill=TINT, outline=JUDGE, width=3, top=66)
    tag(ex + (ew - 150) / 2, ey + 14, '模型判斷', JUDGE)
    fx, fy, fw, fh = 834, 290, 380, 230
    box(fx, fy, fw, fh, '程式檢查', '格式、引句、\n知識卡、分數區間', fill='#FFFFFF', outline=GUARD, width=3, top=66)
    tag(fx + (fw - 150) / 2, fy + 14, '程式把關', GUARD)
    gx_, gy, gw, gh = 1296, 330, 280, 150
    box(gx_, gy, gw, gh, '審核報告', '有、無微調各一份')
    # the comparison with the reference happens outside the notebook, below the evaluation lane
    hx, hy, hw, hh = 1060, 674, 516, 84
    box(hx, hy, hw, hh, '參考判斷（看到輸出前寫好）', fill='#FFFFFF', outline=LINE)
    c.text(700, hy + (hh - 45) / 2, 340, [('Notebook 外', {'color': MUTED, 'weight': 'Bold'})], size=30,
           align='right')

    # flows
    c.arrow(cx + 70, cy + ch + 6, dx + dw / 2, dy - 8, color=GUARD, width=4, size=20)
    c.lock(440, 252, 30, GUARD)
    c.text(462, 228, 330, [('雜湊相符才讀', {'weight': 'Medium'})], size=30)
    c.arrow(cx + 300, cy + ch + 6, ex + ew - 60, ey - 8, color=MUTED, width=4, size=20)
    c.text(cx + 300 + 18, 222, 400, '載入凍結的規則與權重', size=30, color=MUTED)
    c.arrow(dx + dw + 8, dy + dh / 2, ex - 8, dy + dh / 2, width=4, size=20)
    c.arrow(ex + ew + 8, ey + eh / 2, fx - 8, fy + eh / 2, width=4, size=20)
    c.arrow(fx + fw + 8, gy + gh / 2, gx_ - 8, gy + gh / 2, color=ACCENT, width=4, size=20)
    c.text(fx + fw + 6, gy + gh / 2 - 50, 90, [('通過', {'color': ACCENT, 'weight': 'Medium'})], size=30,
           align='center')
    c.curve_arrow((fx + 90, fy + fh + 4), (fx + 40, 590), (ex + ew - 40, 590), (ex + ew - 90, ey + eh + 8),
                  color=WARN, width=4)
    c.text(ex + 120, 590, fx + fw - ex - 240, [('不符：退回重寫一次', {'color': WARN, 'weight': 'Medium'})], size=30,
           align='center')
    c.arrow(gx_ + gw / 2, hy - 8, gx_ + gw / 2, gy + gh + 8, color=MUTED, width=4, size=20)
    c.text(gx_ + gw / 2 + 14, gy + gh + 60, 120, '比對', size=30, color=MUTED)
    c.save('slide-architecture.png')


def fig_output(items, raw, comp):
    it = items['4']
    article = it['Article']
    out = raw['4']
    parsed = json.loads(out)
    reason = parsed['Reasons'][0]
    ref = it['adapter']
    c = Canvas(1920, 900)
    # left: article, reference and verdict
    lx, lw = 30, 640
    c.text(lx, 18, lw, [('測試文章 ID 4', {'weight': 'Bold'}), ('　8 篇測試之一', {'color': MUTED})], size=34)
    hi = verbatim(article, 'Meta Keywords 標籤，這在 2026 年是決定 Google 排名的最核心因素')
    pre, post = article.split(hi)
    runs = ['「' + pre, (hi, {'bg': HIGHLIGHT}), post + '」']
    art_h = c.text(0, 0, lw - 64, runs, size=38, gap=1.5, draw=False)
    c.rect(lx, 82, lw, art_h + 52, fill=TINT, radius=16)
    c.text(lx + 32, 82 + 26, lw - 64, runs, size=38, gap=1.5)
    ry = 82 + art_h + 52 + 36
    alt = f"{ref['alt_severity']} {ref['alt_range'][0]}–{ref['alt_range'][1]} 分"
    c.text(lx, ry, lw, [('參考判斷', {'weight': 'Bold'}), ('（另一個 AI 事先寫好）', {'color': MUTED})], size=32)
    ry += 54
    ry += c.text(lx, ry, lw, [('錯誤 SEO 理論', {'weight': 'Medium'}),
                              f"，{ref['ref_severity']} {ref['ref_range'][0]}–{ref['ref_range'][1]} 分；\n"
                              f"{alt} 也說得通"], size=32)
    # why critical is defensible: the prompt's own critical definition (quoted verbatim)
    crit = verbatim((ROOT_FROZEN / 'system_prompt.txt').read_text(encoding='utf-8'), '對排名、獲利、核貸等結果作無依據的絕對承諾')
    ry += 10 + c.text(lx, ry + 10, lw, [('prompt 的 critical 也包含「', {'color': MUTED}), (crit, {'color': MUTED}),
                                        ('」', {'color': MUTED})], size=30)
    ry += 24
    c.rect(lx, ry, 290, 70, fill=ACCENT, radius=35)
    c.text(lx, ry + 11, 290, [(f"判定：{ref['verdict']}", {'weight': 'Bold', 'color': '#FFFFFF'})], size=34,
           align='center')
    ry += 70 + 28
    terms = comp['chinese_usage']['mainland_terms_in_explanation_and_advice']['adapter']['terms']
    used = [t for t in terms if '4' in terms[t]['ids']]
    advice = parsed['Actionable Advice'][0]
    for t in used:
        verbatim(advice, t)
    c.text(lx, ry, lw, [('不足：', {'weight': 'Bold', 'color': WARN}),
                        f"建議裡的「{'、'.join(used)}」是中國大陸用語，台灣慣用「"
                        + '、'.join(terms[t]['taiwan'] for t in used) + '」'], size=30, color=INK)
    # right: the raw JSON, wrapped for the slide
    jx, jw = 730, 1160
    c.text(jx, 18, jw, [('模型輸出', {'weight': 'Bold'}), ('　JSON 原文，只為版面換行', {'color': MUTED})], size=34)
    c.rect(jx, 82, jw, 800, fill=CODE_BG, radius=16)
    marks = {verbatim(out, '"SEO_FALSE"'): {'bg': HIGHLIGHT, 'weight': 'Bold'},
             verbatim(out, '"critical"'): {'bg': HIGHLIGHT, 'weight': 'Bold'},
             verbatim(out, '25'): {'bg': HIGHLIGHT, 'weight': 'Bold'},
             verbatim(out, 'Google 不使用 meta keywords 標籤作為索引或排名依據'): {'bg': HIGHLIGHT}}
    assert reason['code'] == 'SEO_FALSE' and reason['severity'] == 'critical' and parsed['Score'] == 25
    pattern = '|'.join(re.escape(k) for k in sorted(marks, key=len, reverse=True))
    y = 82 + 22
    size, step = 30, 18
    for line in out.split('\n'):
        stripped = line.lstrip(' ')
        indent = 28 + (len(line) - len(stripped)) // 2 * step
        runs = []
        m = re.match(r'("[^"]+")(:\s*)(.*)$', stripped)
        rest = stripped
        if m:
            runs += [(m.group(1), {'color': KEY, 'weight': 'Medium'}), (m.group(2), {})]
            rest = m.group(3)
        pos = 0
        for mm in re.finditer(pattern, rest):
            if mm.start() > pos:
                runs.append((rest[pos:mm.start()], {}))
            runs.append((mm.group(0), marks[mm.group(0)]))
            pos = mm.end()
        if pos < len(rest):
            runs.append((rest[pos:], {}))
        y += c.text(jx, y, jw - 40, runs or [('', {})], size=size, gap=1.36, indent=indent,
                    cont_indent=indent + step)
    if y > 82 + 800:
        raise SystemExit(f'JSON overflows its panel: {y}')
    c.save('slide-output.png')


def fig_finetune(comp, training, split, items_, post):
    order_ = ['準確', '部分準確', '偏差']
    v = comp['verdicts']
    levels = [('準確', ACCENT, '#FFFFFF'), ('部分準確', PARTIAL, INK), ('偏差', WARN, '#FFFFFF')]
    counts = {s: [len(v[s][lv]) for lv, _, _ in levels] for s in ('adapter', 'base')}
    diff = sorted(set(v['adapter']['準確']) ^ set(v['base']['準確']))
    assert len(diff) == 1, diff
    avb = comp['adapter_vs_base']
    mae_a = one_decimal(comp['summary']['adapter']['score_mae_vs_typical'])
    mae_b = one_decimal(comp['summary']['base']['score_mae_vs_typical'])
    n = comp['summary']['adapter']['n']
    c = Canvas(1920, 846)
    # left: the one comparison, verdict counts per arm
    c.text(30, 16, 1100, [(f'{n} 篇測試的逐筆判定', {'weight': 'Bold'})], size=36)
    bx, bwid, bh = 330, 800, 104
    unit = bwid / n
    rows = [('adapter', '有微調', None, 104), ('base', '無微調', '同一個 prompt', 300)]
    for key, label, sub, y in rows:
        c.text(30, y + (bh - 54) / 2 - (20 if sub else 0), 280, [(label, {'weight': 'Bold'})], size=38)
        if sub:
            c.text(30, y + 64, 290, sub, size=28, color=MUTED)
        x = bx
        for (lv, fill, fg), cnt in zip(levels, counts[key]):
            w = cnt * unit
            c.rect(x + 3, y, w - 6, bh, fill=fill, radius=10)
            c.text(x, y + (bh - 48) / 2, w, [(f'{lv} {cnt}', {'weight': 'Bold', 'color': fg})], size=34,
                   align='center')
            x += w
    # connector from one boundary to the other: the single article that moved
    x_lo = bx + counts['base'][0] * unit
    x_hi = bx + counts['adapter'][0] * unit
    mid = (104 + bh + 300) / 2
    c.line([(x_hi, 104 + bh + 6), (x_hi, mid), (x_lo, mid), (x_lo, 300 - 6)], color=INK, width=4)
    c.text(x_hi + 20, mid - 24, 760, [(f'只差 1 篇：ID {diff[0]}', {'weight': 'Bold'}),
                                      ('　無微調多標一個錯代碼', {'color': MUTED})], size=30)
    legend = [('準確', ACCENT, '該標的都標到、沒有多標，嚴重度也合理'),
              ('部分準確', PARTIAL, '抓到缺失，但多標、理由偏主題或判得太重'),
              ('偏差', WARN, '漏掉缺失，或沒問題的文章被扣到 major 以上')]
    ly = 488
    for lv, fill, desc in legend:
        c.rect(30, ly + 10, 30, 30, fill=fill, radius=6)
        c.text(80, ly, 1060, [(lv + '：', {'weight': 'Bold'}), desc], size=32)
        ly += 64
    # what the prompt iterations taught (train articles only), in place of a repeated disclaimer
    c.rect(20, ly + 12, 1130, 846 - ly - 24, fill=CARD, radius=14)
    c.text(46, ly + 28, 1080, [('prompt 的心得：', {'weight': 'Bold'}),
                               '先寫理由再給分，否認法拍風險的文章由 55 改判 0 分，\n'
                               '但嚴重度普遍膨脹；YMYL 的定義改了兩版，過度標記仍在。'], size=30, gap=1.4)
    # right: three supporting numbers
    px = 1240
    c.rect(px - 44, 20, 4, 806, fill=LINE, radius=2)
    # same prompt with and without the adapter on the 12 training articles (frozen train output)
    train_cmp = {it['ID']: it for it in read_json(TRAIN_OUT / 'baseline_comparison.json')['items']}
    t10 = train_cmp['10']
    assert t10['target_score'] == 74 and t10['adapter_score'] == 0
    better = {'adapter': [], 'base': []}
    for it in avb['differing_items']:
        va, vb = items_[it['ID']]['adapter'], items_[it['ID']]['base']
        ra = order_.index(va['verdict']), abs(va['score_distance_main'])
        rb = order_.index(vb['verdict']), abs(vb['score_distance_main'])
        better['adapter' if ra < rb else 'base'].append(it['ID'])
    assert len(avb['differing_items']) == n - avb['same_code_set'] and all(len(v) == 1 for v in better.values())
    stats = [(f"{avb['same_code_set']} / {n} 篇", '有、無微調兩版的問題代碼相同',
              f"另 2 篇方向相反：\nID {better['adapter'][0]} 有微調較好，ID {better['base'][0]} 無微調較好"),
             (f'{mae_a} 對 {mae_b} 分', '分數與參考的平均差距', f'有微調 {mae_a}、無微調 {mae_b}，越小越好'),
             (f"ID 10：{t10['target_score']} → {t10['adapter_score']} 分", f"訓練過的 {len(split['train_ids'])} 篇也沒學會",
              f"答案 {t10['target_score']} 分，微調版給 {t10['adapter_score']} 分；\n"
              f"答案部分的誤差只從 {post['train_target_loss']['ce_base']:.2f} 降到 {post['train_target_loss']['ce_adapter']:.2f}")]
    sy = 34
    for k, (big, label, sub) in enumerate(stats):
        c.text(px, sy, 660, [(big, {'weight': 'Bold', 'color': WARN if k == 2 else INK})], size=58)
        c.text(px, sy + 92, 660, [(label, {'weight': 'Bold'})], size=34)
        c.text(px, sy + 144, 660, sub, size=30, color=MUTED)
        sy += 272
    c.save('slide-finetune.png')


def fig_doc_scores(comp, items):
    """Report figure (1600 px wide, text 30 px or larger): each test article's score against the reference ranges."""
    order = [('2', '保證獲利'), ('9', '白字隱藏關鍵字'), ('4', 'Meta Keywords'), ('12', '自述註冊經驗'),
             ('1', '小額出金測試'), ('3', '關鍵字重複 5 次'), ('17', '反詐騙提醒'), ('8', '二胎申請文件')]
    assert sorted(i for i, _ in order) == sorted(items)
    ADAPTER, BASE_C, REF_MAIN, REF_ALT = '#1F5FAD', '#E07B39', '#9AA3A0', '#DCE1DF'
    verdict_col = {'準確': ACCENT, '部分準確': '#3E8C78', '偏差': WARN}
    below = sum(1 for i, _ in order if items[i]['adapter']['score'] < items[i]['adapter']['ref_range'][0])
    above = sum(1 for i, _ in order if items[i]['adapter']['score'] > items[i]['adapter']['ref_range'][1])
    W, row_h = 1600, 84
    top = 176
    H = top + row_h * len(order) + 130
    c = Canvas(W, H)
    c.text(20, 10, W - 40, [(f'有微調的分數 {len(order)} 筆中 {below} 筆低於參考主判讀區間，'
                             f'{"沒有一筆" if above == 0 else f"{above} 筆"}高於', {'weight': 'Bold'})], size=34)
    # legend
    lx = 20
    for kind, label in (('main', '參考主判讀區間'), ('alt', '替代判讀區間'), ('a', '有微調'), ('b', '無微調')):
        if kind in ('main', 'alt'):
            c.rect(lx, 76, 46, 22, fill=REF_MAIN if kind == 'main' else REF_ALT, radius=4)
        else:
            col = ADAPTER if kind == 'a' else BASE_C
            c.d.ellipse([(lx + 12) * S, 76 * S, (lx + 34) * S, 98 * S], fill=col)
        c.text(lx + 56, 64, 260, label, size=30)
        lx += 56 + c.text(0, 0, 400, label, size=30, draw=False) * 0 + 34 * len(label) * 0.95 + 40
    px0, px1 = 440, 1380
    sx = (px1 - px0) / 100

    def X(v):
        return px0 + v * sx

    # severity bands
    for lo, hi, name in ((0, 29, 'critical'), (30, 59, 'major'), (60, 84, 'minor'), (85, 100, '無缺失')):
        c.text(X(lo), 120, (hi - lo + 1) * sx, [(name, {'color': MUTED})], size=30, align='center')
    for v in (30, 60, 85):
        c.line([(X(v) - sx / 2, 166), (X(v) - sx / 2, top + row_h * len(order))], color=LINE, width=2)
    c.text(px1 + 10, 120, 210, [('有微調判定', {'color': MUTED})], size=30)
    y = top
    for k, (iid, short) in enumerate(order):
        a, b = items[iid]['adapter'], items[iid]['base']
        if k in (3, 5):
            c.line([(20, y), (W - 20, y)], color=LINE, width=2)
        c.text(20, y + (row_h - 45) / 2, 400, [(f'ID {iid}  ', {'weight': 'Bold'}), short], size=30)
        mid = y + row_h / 2
        if a['alt_range']:
            lo, hi = a['alt_range']
            c.rect(X(lo), mid - 12, (hi - lo) * sx, 24, fill=REF_ALT, radius=4)
        lo, hi = a['ref_range']
        c.rect(X(lo), mid - 12, (hi - lo) * sx, 24, fill=REF_MAIN, radius=4)
        for score, col, dy in ((a['score'], ADAPTER, -22), (b['score'], BASE_C, 22)):
            cxp = X(score)
            c.d.ellipse([(cxp - 12) * S, (mid + dy - 12) * S, (cxp + 12) * S, (mid + dy + 12) * S], fill=col)
        c.text(px1 + 30, y + (row_h - 45) / 2, 200, [(a['verdict'], {'weight': 'Bold',
                                                                    'color': verdict_col[a['verdict']]})], size=30)
        y += row_h
    for v in (0, 20, 40, 60, 80, 100):
        c.text(X(v) - 40, y + 10, 80, str(v), size=30, color=MUTED, align='center')
    c.text(px0, y + 58, px1 - px0, '分數（0–100，越高代表缺失越少）', size=30, color=MUTED, align='center')
    c.save('holdout-scores-v2.png')


def fig_scorecard(comp, items):
    """Original-task check items, frozen fine-tuned system next to the same prompt without fine-tuning."""
    def arm(s):
        t = comp['targeted_checks'][s]
        seo = t['seo_false_detected']
        exp = t['fake_experience_id12']
        need_ymyl = [i for i, it in items.items() if 'YMYL_RISK' in it['adapter']['ref_codes']]
        hit_ymyl = [i for i in need_ymyl if 'YMYL_RISK' in items[i][s]['codes']]
        clean = t['items_without_ymyl_in_reference']
        first, total = comp['contract_validity']['holdout'][s]['first_pass'].split('/')
        return [(sum(seo.values()), len(seo)),
                (int(exp['experience_unverified'] and not exp['called_fake']), 1),
                (len(hit_ymyl), len(need_ymyl)),
                (len(t['ymyl_on_items_without_ymyl_in_reference']), len(clean)),
                (int(t['stuffing_id3']), 1),
                (int(first), int(total))]

    a, b = arm('adapter'), arm('base')
    occurrences = comp['facts']['id3_keyword_occurrences']
    rows = [('植入的錯誤 SEO 理論被指出', '都判為錯誤；ID 4 寫出 Google 的做法', True),
            ('自述經驗只說無法查證', 'EEAT：沒把缺少證據當成造假', True),
            ('該標 YMYL 的文章有標到', '保證獲利的賭博廣告判最重等級', True),
            ('不該標 YMYL 卻標了', '越少越好；只談到賭博、貸款也被標', False),
            ('關鍵字堆疊被指出', f'重複 {occurrences} 次，只看到賭博主題', False),
            ('JSON 第一次就符合格式', '引句、知識卡、分數區間由程式檢查', True)]
    c = Canvas(1920, 846)
    cx = [30, 200, 840, 1040, 1250]
    for x, head in zip(cx[1:], ['原題檢核項', '有微調', '無微調', '這代表什麼']):
        c.text(x, 8, 600, [(head, {'weight': 'Bold', 'color': MUTED})], size=30)
    y, rh = 62, 110
    for k, ((label, meaning, good), va, vb) in enumerate(zip(rows, a, b)):
        if k % 2 == 0:
            c.rect(20, y, 1880, rh, fill=CARD, radius=12)
        col = ACCENT if good else WARN
        c.rect(cx[0] + 16, y + (rh - 54) / 2, 120, 54, fill=col, radius=27)
        c.text(cx[0] + 16, y + (rh - 54) / 2 + 3, 120, [('做到' if good else '不足', {'weight': 'Bold', 'color': '#FFFFFF'})],
               size=30, align='center')
        c.text(cx[1], y + (rh - 51) / 2, 620, [(label, {'weight': 'Medium'})], size=36)
        for x, (num, den) in ((cx[2], va), (cx[3], vb)):
            c.text(x, y + (rh - 65) / 2, 200, [(f'{num} / {den}', {'weight': 'Bold', 'color': col})], size=46)
        c.text(cx[4], y + (rh - 46) / 2, 640, meaning, size=32)
        y += rh + 6
    cons = comp['training_rounds']['v3b_adapter']
    assert len(set(cons['consistency_id14_scores'])) == 1 and set(cons['consistency_code_jaccard']) == {1.0}
    c.text(30, y + 22, 1860, [('一致性：', {'weight': 'Bold'}),
                              '只用 1 篇訓練文章，三種 temperature（隨機程度）各審一次，代碼與分數相同；三次都是 0 分，已到下限'],
           size=30, color=MUTED)
    c.save('slide-scorecard.png')


def fig_ymyl(items, facts, post):
    def expl(i, part):
        return verbatim(' '.join(r['explanation'] for r in items[i]['adapter']['reasons']), part)

    a3, kw = items['3']['Article'], items['3']['Keyword']
    assert a3.count(kw) == facts['id3_keyword_occurrences']
    rows = [('ID 17｜反詐騙提醒', '「' + items['17']['Article'] + '」', '17',
             '「' + expl('17', '該句話否定了詐騙行為的風險') + '」'),
            ('ID 8｜二胎申請文件', '「' + items['8']['Article'] + '」', '8',
             '「' + expl('8', '未說明此貸款可能涉及高風險') + '」'),
            (f"ID 3｜同一個關鍵字重複 {a3.count(kw)} 次", None, '3',
             '沒提重複，只說「' + expl('3', '文章主動推薦娛樂城，可能涉及網路賭博') + '」')]
    labels = {'none': '沒有缺失', 'STUFFING': '關鍵字堆疊'}
    c = Canvas(1920, 800)
    c1x, c1w, c2x, c2w, c3x, c3w = 30, 900, 960, 640, 1620, 270
    c.text(c1x + 28, 8, c1w, [('原文', {'weight': 'Bold', 'color': MUTED})], size=30)
    c.text(c2x, 8, c2w, [('模型的判斷', {'weight': 'Bold', 'color': WARN})], size=30)
    c.text(c3x, 8, c3w, [('參考判斷', {'weight': 'Bold', 'color': ACCENT})], size=30)
    y, rh = 56, 166
    for head, art, iid, model in rows:
        a = items[iid]['adapter']
        c.rect(c1x, y, 1890 - c1x, rh, fill=CARD, radius=14)
        c.rect(c1x, y, 10, rh, fill=WARN, radius=4)
        c.text(c1x + 28, y + 10, c1w - 40, [(head, {'weight': 'Bold'})], size=32)
        if art is None:
            art = [('「', {})] + [(p, {'bg': HIGHLIGHT} if p == kw else {})
                                 for p in re.split(f'({re.escape(kw)})', a3) if p] + [('」', {})]
        c.text(c1x + 28, y + 58, c1w - 36, art, size=30, gap=1.36)
        chip = f"YMYL 風險 · {a['severity']} · {a['score']} 分"
        assert a['codes'] == ['YMYL_RISK']
        c.rect(c2x, y + 12, 440, 50, fill=WARN, radius=25)
        c.text(c2x, y + 14, 440, [(chip, {'weight': 'Bold', 'color': '#FFFFFF'})], size=30, align='center')
        c.text(c2x, y + 74, c2w - 10, model, size=30, gap=1.36)
        ref_code = a['ref_codes'][0] if a['ref_codes'] else 'none'
        ref = labels[ref_code] + ('' if ref_code == 'none' else f" {a['ref_severity']}")
        c.text(c3x, y + 14, c3w, [(ref, {'weight': 'Bold', 'color': ACCENT})], size=30)
        c.text(c3x, y + 58, c3w, f"{a['ref_range'][0]}–{a['ref_range'][1]} 分", size=30, color=MUTED)
        y += rh + 10
    fp, b4 = post['systems']['fp16_no_adapter'], post['systems']['base_4bit_no_adapter']
    assert post['reading_a'].startswith('YMYL over-flagging is not caused by 4-bit quantization')
    # what to do next, and what the post-freeze 16-bit comparison showed
    by, bh = y + 8, 800 - y - 18
    bands = [(c1x, 920, '下一步', ACCENT, TINT,
              '程式先抽出重複次數、保證用語、第一人稱自述，模型只判斷被標出的句子；每種代碼設嚴重度上限。效果需要另外驗證。'),
             (970, 920, '事後對照：16 位元不量化', WARN, WARN_TINT,
              f"不該標 YMYL 的 {len(fp['items_without_ymyl_in_main'])} 篇仍標了 {len(fp['ymyl_flagged_without_ymyl_in_main'])} 篇"
              f"（4-bit 是 {len(b4['ymyl_flagged_without_ymyl_in_main'])} 篇），量化不是主因；其他 8B 模型沒有實測。")]
    for x, w, head, col, fill, body in bands:
        c.rect(x, by, w, bh, fill=fill, radius=14)
        c.text(x + 28, by + 18, w - 56, [(head, {'weight': 'Bold', 'color': col})], size=34)
        c.text(x + 28, by + 72, w - 56, body, size=32, gap=1.4)
    c.save('slide-ymyl.png')


def main():
    comp, items, raw, split, lock, training = load()
    fig_problem(split, lock)
    fig_architecture(split, lock)
    fig_output(items, raw, comp)
    fig_scorecard(comp, items)
    fig_doc_scores(comp, items)
    post = read_json(POSTHOC)
    fig_finetune(comp, training, split, items, post)
    fig_ymyl(items, comp['facts'], post)


if __name__ == '__main__':
    sys.exit(main())
