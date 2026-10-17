"""Draw the report and slide figures in deliverable/img/ from recorded data (no model, no GPU).

python scripts/make_deliverable_figures.py   (Windows: set PYTHONUTF8=1; needs Pillow and the Noto Sans TC font)
Reads evaluation/holdout8-comparison.json (run scripts/compare_holdout.py first), the post-freeze results
(evaluation/posthoc-results.json, evaluation/posthoc14b-results.json), the eval and 14B kernels' outputs, the split
manifest, the frozen lock, prompt and supervised answers. Counts are computed from those files and every quoted model,
prompt or article sentence is checked to be a verbatim substring of them; only layout text is fixed here.
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
POSTHOC14B = TASK / 'evaluation' / 'posthoc14b-results.json'  # post-freeze 14B comparison (scripts/posthoc14b_analysis.py)
EVAL_OUT = TASK / 'kaggle-retrieved' / 'soulo-work03-v3-eval' / 'work03' / 'outputs'
TRAIN_OUT = TASK / 'kaggle-retrieved' / 'soulo-work03-v3b-train' / 'work03' / 'outputs'
KAGGLE_14B = TASK / 'kaggle-retrieved' / 'soulo-work03-posthoc-14b' / 'posthoc14b'
KAGGLE_FP16 = TASK / 'kaggle-retrieved' / 'soulo-work03-posthoc-fp16' / 'posthoc'
REFERENCE = TASK / 'evaluation' / 'holdout8-reference.jsonl'
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
    def __init__(self, w, h, min_size=28):
        """min_size: smallest text allowed, per docs/DELIVERABLE_FORMAT.md (30 px for figures shared with the
        report, 28 px for full-width slide figures); smaller text stops the run."""
        self.w, self.h, self.min_size = w, h, min_size
        self.im = Image.new('RGB', (w * S, h * S), BG)
        self.d = ImageDraw.Draw(self.im)

    # ---- shapes (all coordinates in output pixels)
    def rect(self, x, y, w, h, fill=None, outline=None, width=2, radius=14):
        self.d.rounded_rectangle([x * S, y * S, (x + w) * S, (y + h) * S], radius=radius * S, fill=fill,
                                 outline=outline, width=width * S if outline else 0)

    def dashed_rect(self, x, y, w, h, color, width=3, radius=14, dash=16, gap=10):
        r = radius
        for (x0, y0, x1, y1) in ((x + r, y, x + w - r, y), (x + r, y + h, x + w - r, y + h),
                                 (x, y + r, x, y + h - r), (x + w, y + r, x + w, y + h - r)):
            length = abs(x1 - x0) + abs(y1 - y0)
            pos = 0
            while pos < length:
                end = min(pos + dash, length)
                t0, t1 = pos / length, end / length
                self.line([(x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0), (x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1)],
                          color, width)
                pos += dash + gap
        for (cx, cy, a0) in ((x + r, y + r, 180), (x + w - r, y + r, 270), (x + w - r, y + h - r, 0),
                             (x + r, y + h - r, 90)):
            self.d.arc([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], a0, a0 + 90, fill=color,
                       width=width * S)

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
        smallest = min([size] + [r[1]['size'] for r in runs if not isinstance(r, str) and 'size' in r[1]])
        if smallest < self.min_size:
            raise SystemExit(f'text below {self.min_size} px: {runs!r}')
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
    return comp, items, raw, split, lock


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
            ('我的做法', '規則寫進 prompt、事實寫成知識卡，\n格式交給程式；另跑不載微調的對照')]
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
    The main line runs left to right: train, freeze, test inference, report. Green is the model's judgement, black
    outlines are program checks, grey boxes are data. Scoring sits in its own dashed block outside the notebooks; its
    arrows lead only into the comparison, so the reference never reaches the model."""
    n_train, n_test = len(split['train_ids']), len(split['holdout_ids'])
    n_locked = len(lock['hashes'])
    W, H = 1600, 788
    c = Canvas(W, H, min_size=30)
    JUDGE, GUARD = ACCENT, INK

    def tag(x, y, text, fill):
        w = 150
        c.rect(x, y, w, 44, fill=fill, radius=22)
        c.text(x, y + 1, w, [(text, {'weight': 'Bold', 'color': '#FFFFFF'})], size=30, gap=1.4, align='center')

    def box(x, y, w, h, title, sub=None, fill=CARD, outline=LINE, width=2, top=None):
        c.rect(x, y, w, h, fill=fill, outline=outline, width=width)
        th = c.text(0, 0, w - 36, [(title, {'weight': 'Bold'})], size=34, draw=False)
        sh = c.text(0, 0, w - 36, sub, size=30, draw=False) if sub else 0
        if (top or 0) + th + sh > h:
            raise SystemExit(f'box {title!r} overflows')
        ty = y + (h - th - sh) / 2 if top is None else y + top
        c.text(x + 18, ty, w - 36, [(title, {'weight': 'Bold'})], size=34, align='center')
        if sub:
            c.text(x + 18, ty + th, w - 36, sub, size=30, align='center', color=INK)

    def guarded(x, y, w, h, title, sub, outline, label):
        box(x, y, w, h, title, sub, fill=TINT if outline == JUDGE else '#FFFFFF', outline=outline, width=3, top=66)
        tag(x + (w - 150) / 2, y + 14, label, outline)

    # the two notebooks, side by side
    nb_bottom = 540
    c.rect(8, 8, 580, nb_bottom - 8, fill='#F7F9F8', radius=18)
    c.rect(604, 8, W - 612, nb_bottom - 8, fill='#F7F9F8', radius=18)
    c.text(30, 30, 540, [('訓練 Notebook', {'weight': 'Bold', 'color': MUTED})], size=32)
    c.text(30, 78, 540, '不掛載測試資料', size=30, color=MUTED)
    c.text(1000, 30, 570, [('評估 Notebook', {'weight': 'Bold', 'color': MUTED})], size=32)
    c.text(1000, 78, 570, '載入凍結的系統，不呼叫雲端 API', size=30, color=MUTED)

    # main line: train -> freeze -> test inference (model, then program check) -> report
    top, h = 200, 210
    mid = top + h / 2
    box(26, top, 264, h, f'{n_train} 篇訓練文章', '調整 prompt、\n知識卡與微調')
    guarded(350, top, 216, h, '凍結', f'{n_locked} 個檔案\n記下雜湊', GUARD, '程式把關')
    ex, ew = 640, 320
    guarded(ex, top, ew, h, 'Qwen3-8B', '找缺失、定嚴重度，\n先寫理由再給分', JUDGE, '模型判斷')
    fx, fw = 1020, 250
    guarded(fx, top, fw, h, '程式檢查', '格式、引句、\n分數區間', GUARD, '程式把關')
    gx_, gw = 1340, 232
    box(gx_, top, gw, h, '審核報告', 'HTML 與\nDataFrame')
    c.arrow(290 + 8, mid, 350 - 8, mid, width=4, size=20)
    c.arrow(566 + 8, mid, ex - 8, mid, width=4, size=20)
    c.arrow(ex + ew + 8, mid, fx - 8, mid, width=4, size=20)
    c.arrow(fx + fw + 8, mid, gx_ - 8, mid, color=ACCENT, width=4, size=20)
    c.text(fx + fw, mid - 52, gx_ - fx - fw, [('通過', {'color': ACCENT, 'weight': 'Medium'})], size=30,
           align='center')
    c.curve_arrow((fx + 90, top + h + 4), (fx + 40, 490), (ex + ew - 40, 490), (ex + ew - 90, top + h + 8),
                  color=WARN, width=4)
    c.text(ex + 120, 478, fx + fw - ex - 240, [('不符：退回重寫一次', {'color': WARN, 'weight': 'Medium'})], size=30,
           align='center')

    # test data enters the evaluation notebook only after the hashes match
    box(ex, 24, ew, 100, f'{n_test} 篇測試文章')
    c.arrow(ex + ew / 2, 124 + 8, ex + ew / 2, top - 8, color=GUARD, width=4, size=20)
    c.lock(ex + ew / 2 + 34, 162, 30, GUARD)
    c.text(ex + ew / 2 + 56, 140, 200, [('雜湊相符才讀', {'weight': 'Medium'})], size=30)

    # scoring: outside the notebooks, after the report exists; nothing flows back
    sy, sh_ = 562, 218
    c.dashed_rect(8, sy, W - 16, sh_, color=MUTED, radius=18)
    c.text(30, sy + 26, 580, [('Notebook 外的評分', {'weight': 'Bold', 'color': MUTED})], size=32)
    c.text(30, sy + 74, 580, '結果不回饋模型與 prompt', size=30, color=MUTED)
    by, bh = sy + 44, 152
    box(ex, by, 440, bh, '參考判斷', '另一個 AI 在看到輸出前寫好', fill='#FFFFFF')
    box(1160, by, 412, bh, '事後比對', 'AI 判定準確、部分準確、\n偏差，我逐筆覆核', fill='#FFFFFF')
    c.arrow(ex + 440 + 8, by + bh / 2, 1160 - 8, by + bh / 2, width=4, size=20)
    c.arrow(gx_ + gw / 2, top + h + 8, gx_ + gw / 2, by - 4, width=4, size=20)
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
    c = Canvas(W, H, min_size=30)
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


def width(text, size, weight='Regular'):
    return font(size, weight).getlength(text) / S


def chip(c, x, y, text, fill, fg='#FFFFFF', size=28, h=46, pad=20):
    """Pill label sized to its text; returns its width."""
    w = width(text, size, 'Bold') + 2 * pad
    c.rect(x, y, w, h, fill=fill, radius=h / 2)
    c.text(x, y + (h - size * 1.42) / 2, w, [(text, {'weight': 'Bold', 'color': fg})], size=size, align='center')
    return w


def slide_tag(c, x, y, text, fill):
    """Square-cornered tag that says whether a slide shows the formal result or a post-freeze comparison; its shape
    keeps it apart from the round status chips. Returns its width."""
    w, h = width(text, 30, 'Bold') + 36, 48
    c.rect(x, y, w, h, fill=fill, radius=6)
    c.text(x, y + (h - 30 * 1.42) / 2, w, [(text, {'weight': 'Bold', 'color': '#FFFFFF'})], size=30, align='center')
    return w


def mean_seconds(path):
    """Mean generation seconds per article, repairs included, from a holdout jsonl."""
    rows = [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]
    return sum(a['seconds'] for r in rows for a in r['attempts']) / len(rows)


def heavier_than_both(path):
    """Items whose highest severity is above both the main and the alternative reference reading."""
    rank = {'none': 0, 'minor': 1, 'major': 2, 'critical': 3}
    ref = {r['ID']: r for r in map(json.loads, REFERENCE.read_text(encoding='utf-8').splitlines()) if r}
    out = []
    for r in map(json.loads, Path(path).read_text(encoding='utf-8').splitlines()):
        sev = max((rank[x['severity']] for x in r['parsed']['Reasons']), default=0)
        main = rank[ref[r['ID']]['max_severity'] or 'none']
        alt = ref[r['ID']].get('alternative_reading')
        if sev > main and (not alt or sev > rank[alt.get('max_severity') or 'none']):
            out.append(r['ID'])
    return out


def fig_scorecard(comp, items):
    """Slide: the original task's check items, scored on the frozen system only (its own result on the 8 test items)."""
    s = comp['summary']['adapter']
    t = comp['targeted_checks']['adapter']
    seo, exp = t['seo_false_detected'], t['fake_experience_id12']
    need = [i for i, it in items.items() if 'YMYL_RISK' in it['adapter']['ref_codes']]
    hit = [i for i in need if 'YMYL_RISK' in items[i]['adapter']['codes']]
    first, total = comp['contract_validity']['holdout']['adapter']['first_pass'].split('/')
    cons = comp['training_rounds']['v3b_adapter']
    assert set(cons['consistency_id14_scores']) == {0} and set(cons['consistency_code_jaccard']) == {1.0}
    assert s['severity_lower_than_main'] == 0
    occurrences = comp['facts']['id3_keyword_occurrences']
    status = {'做到': ACCENT, '有限': MUTED, '不足': WARN}
    rows = [('做到', '植入的錯誤 SEO 理論被指出', f'{sum(seo.values())} / {len(seo)}', '都判為錯誤；ID 4 寫出 Google 的做法'),
            ('做到', '自述經驗只說無法查證', f"{int(exp['experience_unverified'] and not exp['called_fake'])} / 1",
             'EEAT：沒把缺少證據當成造假'),
            ('做到', '該標 YMYL 的文章有標到', f'{len(hit)} / {len(need)}', '保證獲利的賭博廣告判最重等級'),
            ('做到', 'JSON 第一次就符合格式', f'{first} / {total}', '引句、知識卡、分數區間由程式檢查'),
            ('有限', '三種 temperature 代碼與分數相同', f"{len(cons['consistency_id14_scores'])} 次相同",
             '只測 1 篇、三次都 0 分；建議方向一致'),
            ('不足', '不該標 YMYL 卻標了',
             f"{len(t['ymyl_on_items_without_ymyl_in_reference'])} / {len(t['items_without_ymyl_in_reference'])}",
             '正確的二胎申請說明、反詐提醒也被標'),
            ('不足', '嚴重度比參考主判讀重', f"{s['severity_higher_than_main']} / {s['n']}",
             f"連替代判讀也算，仍有 {s['n'] - s['severity_match_main_or_alt']} 篇偏重"),
            ('不足', '關鍵字堆疊被指出', f"{int(t['stuffing_id3'])} / 1", f'重複 {occurrences} 次，只看到賭博主題')]
    c = Canvas(1920, 846)
    # the same top-left label marks the formal result here and the post-freeze comparisons on the next slides
    v = comp['verdicts']['adapter']
    pw = slide_tag(c, 30, 4, '正式結果', KEY)
    c.text(30 + pw + 22, 4 + (48 - 34 * 1.42) / 2, 1500,
           [(f"凍結的系統在 {s['n']} 篇測試上：準確 {len(v['準確'])}、部分準確 {len(v['部分準確'])}、"
             f"偏差 {len(v['偏差'])}", {'weight': 'Bold'})], size=34)
    cx = [30, 190, 950, 1220]
    for x, head in zip(cx[1:], ['原題檢核項', '結果', '這代表什麼']):
        c.text(x, 68, 640, [(head, {'weight': 'Bold', 'color': MUTED})], size=30)
    assert s['severity_lower_than_main'] == 0  # so every severity that matches neither reading is heavier
    assert '8' in t['ymyl_on_items_without_ymyl_in_reference'] and '17' in t['ymyl_on_items_without_ymyl_in_reference']
    y, rh = 114, 78
    for k, (st, label, value, meaning) in enumerate(rows):
        if k % 2 == 0:
            c.rect(20, y, 1880, rh, fill=CARD, radius=12)
        col = status[st]
        c.rect(cx[0] + 16, y + (rh - 52) / 2, 120, 52, fill=col, radius=26)
        c.text(cx[0] + 16, y + (rh - 52) / 2 + 3, 120, [(st, {'weight': 'Bold', 'color': '#FFFFFF'})], size=30,
               align='center')
        c.text(cx[1], y + (rh - 51) / 2, 740, [(label, {'weight': 'Medium'})], size=36)
        c.text(cx[2], y + (rh - 62) / 2, 260, [(value, {'weight': 'Bold', 'color': col})], size=44)
        c.text(cx[3], y + (rh - 45) / 2, 680, meaning, size=32)
        y += rh + 6
    if y + 4 + 30 * 1.42 > 846:
        raise SystemExit('scorecard overflows')
    c.text(30, y + 4, 1860, '參考判斷由另一個 AI 在看到輸出前寫好；逐筆判定由 AI 撰寫、我覆核', size=30, color=MUTED)
    c.save('slide-scorecard.png')


def fig_sources(comp, items, post, post14, prompt, targets, train_cmp):
    """Slide: where the bias comes from. One baseline (8B, 4-bit, no adapter) and three runs that each change one
    condition, on three bias measures where fewer is better; below, the reasons, written as inferences with evidence."""
    sysm = post14['systems']
    base, fp = sysm['qwen3_8b_4bit_no_adapter'], sysm['qwen3_8b_fp16_no_adapter']
    ad, q14 = sysm['qwen3_8b_4bit_adapter_frozen'], sysm['qwen3_14b_4bit_no_adapter']
    # The 14B results file restates the earlier runs; they must agree with the files that first reported them.
    keys = ('severity_higher_than_main', 'score_mae_vs_typical')
    for m, ref in ((ad, comp['summary']['adapter']), (base, comp['summary']['base'])):
        assert all(m[k] == ref[k] for k in keys), (m, ref)
    p_fp = post['systems']['fp16_no_adapter']
    assert all(fp[k] == p_fp[k] for k in keys + ('ymyl_flagged_without_ymyl_in_main',))
    assert post14['reading'] == 'direction_unclear' and q14['stuffing_on_3'] and not base['stuffing_on_3']
    n_diff = sum(items[i]['adapter']['verdict'] != items[i]['base']['verdict'] for i in items)
    n = comp['summary']['adapter']['n']
    n_clean = len(base['items_without_ymyl_in_main'])
    left = q14['ymyl_flagged_without_ymyl_in_main']
    runs = (EVAL_OUT / 'holdout_base.jsonl', KAGGLE_FP16 / 'holdout_fp16.jsonl', EVAL_OUT / 'holdout.jsonl',
            KAGGLE_14B / 'holdout_14b.jsonl')
    both = [len(heavier_than_both(r)) for r in runs]  # row order below: base, 16-bit, fine-tuned, 14B
    for k, arm in ((0, 'base'), (2, 'adapter')):  # agrees with compare_holdout.py where it reports the same thing
        ss = comp['summary'][arm]
        assert ss['severity_lower_than_main'] == 0 and both[k] == n - ss['severity_match_main_or_alt'], (arm, both)
    rows = [('基準', '8B、4-bit、不載微調', None, base),
            ('量化', '改成 16 位元（不量化）', None, fp),
            ('微調', '載入微調＝凍結的系統', f'逐筆判定只差 {n_diff} 篇', ad),
            ('模型', '換成 Qwen3-14B', 'ID 3 抓到堆疊', q14)]
    metrics = [('嚴重度比參考主判讀重', f'共 {n} 篇；括號內連替代判讀也算', lambda m: m['severity_higher_than_main'], n, str),
               ('分數與參考的平均差距', '單位：分', lambda m: m['score_mae_vs_typical'], 30, one_decimal),
               ('不該標 YMYL 卻標了', f'{n_clean} 篇中的篇數', lambda m: len(m['ymyl_flagged_without_ymyl_in_main']),
                n_clean, str)]
    BASE_C, TRACK = '#9AA3A0', '#E6EBE9'
    W, H = 1920, 846
    c = Canvas(W, H)
    lx, mx0, mw, mg, track = 30, 600, 400, 25, 240
    slide_tag(c, lx, 4, '凍結後對照', MUTED)  # same spot as the formal-result label on the scorecard
    c.text(lx, 55, 560, '只改一個條件；直線是基準，越少越好', size=28, color=MUTED)
    for j, (head, unit, *_r) in enumerate(metrics):
        x = mx0 + j * (mw + mg)
        c.text(x, 4, mw, [(head, {'weight': 'Bold', 'color': MUTED})], size=30)
        c.text(x, 46, mw, unit, size=28, color=MUTED)
    y0, rh = 96, 86
    for r, (tag, label, sub, m) in enumerate(rows):
        y = y0 + r * rh
        if r == 0 or tag == '模型':
            c.rect(20, y + 3, W - 40, rh - 6, fill=CARD if r == 0 else TINT, radius=12)
        c.rect(lx + 8, y + (rh - 44) / 2, 92, 44, fill=BASE_C if r == 0 else INK, radius=22)
        c.text(lx + 8, y + (rh - 44) / 2 + 1, 92, [(tag, {'weight': 'Bold', 'color': '#FFFFFF'})], size=28,
               align='center')
        if sub:
            c.text(lx + 118, y + 6, 500, [(label, {'weight': 'Bold'})], size=32)
            c.text(lx + 118, y + 48, 500, sub, size=28, color=MUTED)
        else:
            c.text(lx + 118, y + (rh - 45) / 2, 500, [(label, {'weight': 'Bold'})], size=32)
        for j, (_h, _u, get, top, fmt) in enumerate(metrics):
            x = mx0 + j * (mw + mg)
            v, b = get(m), get(base)
            col = BASE_C if r == 0 or v == b else (ACCENT if v < b else WARN)
            by = y + (rh - 30) / 2
            c.rect(x, by, track, 30, fill=TRACK, radius=6)
            bw = max(8, v / top * track)
            c.rect(x, by, bw, 30, fill=col, radius=6)
            if r:  # baseline tick inside the track, so the changed rows read against the baseline
                bx = x + b / top * track
                c.line([(bx, by - 8), (bx, by + 38)], color=INK, width=3)
            lx2 = x + track + 16
            c.text(lx2, y + (rh - 54) / 2, 140, [(fmt(v), {'weight': 'Bold', 'color': INK if r else MUTED})], size=38)
            if j == 0:  # severity counted against both readings, next to the main-reading count
                tx = lx2 + width(fmt(v), 38, 'Bold') + 6
                c.text(tx, y + (rh - 40) / 2, mw - (tx - x) + mg, f'（{both[r]}）', size=28, color=MUTED)
            if tag == '模型' and j == 2:
                tx = lx2 + width(fmt(v), 38, 'Bold') + 10
                c.text(tx, y + (rh - 40) / 2, W - 20 - tx, '剩 ID ' + '、'.join(sorted(left, key=int)), size=28,
                       color=MUTED)
    fy = y0 + 4 * rh + 6
    fh = c.text(lx, fy, W - 60, [(f'16 位元與 14B 是看過這 {n} 篇後才跑，同一個 prompt 各跑一次，只看方向，不是系統成績；'
                                  f'YMYL 從 {len(base["ymyl_flagged_without_ymyl_in_main"])} 篇降到 {len(left)} 篇，'
                                  '依事前規則是方向不明確', {'color': MUTED})], size=28, gap=1.36)
    # reasons: inferences, each tied to evidence that is checked against the source files
    verbatim(prompt, '只是談到貸款、賭博、法律等高風險主題')
    codes = {}
    for r in targets:
        for code in {x['code'] for x in r['target']['Reasons']}:
            codes[code] = codes.get(code, 0) + 1
    assert len(codes) == 5, codes
    ex = post14['excerpts']
    borderline = set(re.findall(r"'(\d+)'", re.search(r"YMYL_BORDERLINE = \{([^}]*)\}", (
        ROOT_FROZEN / 'scripts' / 'selfcheck.py').read_text(encoding='utf-8')).group(1)))
    assert borderline == {'5', '10'}
    no_ymyl = [r['ID'] for r in targets
               if r['ID'] not in borderline and 'YMYL_RISK' not in {x['code'] for x in r['target']['Reasons']}]
    flagged = {arm: [i for i in no_ymyl if 'YMYL_RISK' in train_cmp[i][f'{arm}_codes']] for arm in ('adapter', 'base')}
    assert len(flagged['adapter']) == len(flagged['base'])
    assert set(base['ymyl_flagged_without_ymyl_in_main']) - set(left) == {'8', '12'}
    assert '否認' in ex['17']['qwen3_14b']['Reasons'][0]['explanation']
    assert any('引導讀者參與' in x['explanation'] for x in ex['3']['qwen3_14b']['Reasons'] if x['code'] == 'YMYL_RISK')
    reasons = [('8B 較難照帶例外的規則判',
                'prompt 寫明只談主題不算 YMYL，8B 仍照主題標；同一個 prompt 給 14B，ID 8、12 不再被標，'
                '嚴重度也較準。'),
               ('12 筆微調沒改變這點',
                f'每種代碼只有 {min(codes.values())} 到 {max(codes.values())} 個訓練例子；明確沒有 YMYL 的 {len(no_ymyl)} 篇'
                f"訓練文章，有、無微調都標了 {len(flagged['adapter'])} 篇。"),
               ('規則寫法可能也有問題', '14B 仍把 ID 3 的單純推薦讀成引導參與，定義留有解讀空間；ID 17 讀反警語，原因分不開。')]
    ry = fy + fh + 14
    c.text(lx, ry, 900, [('為什麼：我的推論', {'weight': 'Bold', 'color': ACCENT})], size=32)
    cy, gap = ry + 52, 24
    cw = (W - 40 - 2 * gap) / 3
    ch = H - cy - 10
    for k, (head, body) in enumerate(reasons):
        x = 20 + k * (cw + gap)
        c.rect(x, cy, cw, ch, fill=WARN_TINT if k == 2 else TINT, radius=14)
        c.text(x + 26, cy + 16, cw - 52, [(head, {'weight': 'Bold', 'color': WARN if k == 2 else ACCENT})], size=32)
        h = c.text(x + 26, cy + 66, cw - 52, body, size=32, gap=1.42)
        if cy + 66 + h > H - 14:
            raise SystemExit(f'reason card {k} overflows')
    c.save('slide-sources.png')


# Qwen3-8B attention shapes from the model's config.json on Hugging Face (hidden_size 4096, 32 query heads and 8
# key/value heads of head_dim 128, 36 layers). Used only to count the LoRA parameters; checked against the number of
# adapter tensors the training run reports and, when the adapter file was downloaded, against its tensor shapes.
QWEN3_8B = dict(layers=36, hidden=4096, q_out=32 * 128, v_out=8 * 128)


def lora_setup():
    """LoRA settings as written in the frozen workflow.py, and the parameter count they imply for Qwen3-8B."""
    src = (ROOT_FROZEN / 'scripts' / 'workflow.py').read_text(encoding='utf-8')
    m = re.search(r"LoraConfig\(r=(\d+),lora_alpha=(\d+),lora_dropout=([\d.]+),target_modules=\[([^\]]+)\]", src)
    q = re.search(r"BitsAndBytesConfig\(load_in_4bit=True,bnb_4bit_quant_type='nf4',bnb_4bit_use_double_quant=True,"
                  r"bnb_4bit_compute_dtype=torch\.float16\)", src)
    t = re.search(r"per_device_train_batch_size=(\d+),gradient_accumulation_steps=(\d+),fp16=True", src)
    assert m and q and t and 'prepare_model_for_kbit_training(model,use_gradient_checkpointing=True)' in src
    assert 'labels=[-100]*len(a)+b' in src  # prompt tokens are masked: loss on the answer only
    r, alpha, dropout = int(m.group(1)), int(m.group(2)), float(m.group(3))
    targets = [x.strip().strip("'") for x in m.group(4).split(',')]
    assert targets == ['q_proj', 'v_proj']
    a = QWEN3_8B
    per_layer = r * (a['hidden'] + a['q_out']) + r * (a['hidden'] + a['v_out'])
    params = a['layers'] * per_layer
    tensors = a['layers'] * len(targets) * 2
    adapter = TRAIN_OUT / 'adapter' / 'adapter_model.safetensors'
    if adapter.exists():  # not in git; verify when present
        import struct
        with open(adapter, 'rb') as f:
            head = json.loads(f.read(struct.unpack('<Q', f.read(8))[0]))
        head.pop('__metadata__', None)
        counted = 0
        for v in head.values():
            k = 1
            for d in v['shape']:
                k *= d
            counted += k
        assert (counted, len(head)) == (params, tensors), (counted, len(head))
    return dict(r=r, alpha=alpha, dropout=dropout, targets=targets, params=params, tensors=tensors,
                batch=int(t.group(1)), accum=int(t.group(2)))


def fig_method(comp, post):
    """Slide: how quantization and fine-tuning were done, why, and what came of it (frozen system's own runs)."""
    model = read_json(TRAIN_OUT / 'model.json')
    vram = read_json(TRAIN_OUT / 'hardware.json')['devices'][0]['vram_bytes'] / 2 ** 30
    training = read_json(TRAIN_OUT / 'training.json')
    lora = lora_setup()
    assert training['changed_adapter_tensors'] == lora['tensors']
    n_params = model['parameters']
    gib = {'16 位元權重': n_params * 2 / 2 ** 30, '4-bit 模型': model['footprint_bytes'] / 2 ** 30}
    rows = [json.loads(x) for x in (EVAL_OUT / 'holdout.jsonl').read_text(encoding='utf-8').splitlines() if x]
    gib['4-bit 審核峰值'] = max(a['peak_gpu_bytes'] for r in rows for a in r['attempts']) / 2 ** 30
    secs = mean_seconds(EVAL_OUT / 'holdout.jsonl')
    cfg = training['config']
    epochs = cfg['epochs']
    logs = [x for x in training['logs'] if 'loss' in x]
    per_epoch = [sum(x['loss'] for x in logs if e < x['epoch'] <= e + 1) / sum(1 for x in logs if e < x['epoch'] <= e + 1)
                 for e in range(epochs)]
    assert training['global_step'] == len(logs) == epochs * 12 // (lora['batch'] * lora['accum'])
    fp = post['systems']['fp16_no_adapter']
    n_diff = sum(it['adapter']['verdict'] != it['base']['verdict'] for it in comp['items'])
    share = lora['params'] / n_params * 100

    c = Canvas(1920, 846)
    gap = 30
    cw = (1920 - 40 - gap) / 2
    lab_w = 110

    def row(x, y, label, body, col, size=32):
        chip(c, x + 28, y + 2, label, col, size=28, h=44, pad=16)
        return c.text(x + 28 + lab_w, y, cw - 56 - lab_w, body, size=size, gap=1.4)

    # quantization
    x, y = 20, 10
    c.rect(x, y, cw, 826, fill=CARD, radius=16)
    c.text(x + 28, y + 18, cw - 56, [('量化：4-bit 載入單張 T4', {'weight': 'Bold', 'color': ACCENT})], size=38)
    yy = y + 92
    yy += row(x, yy, '設定', 'bitsandbytes 4-bit NF4、雙重量化、運算用 fp16', INK) + 30
    # memory bars against one T4
    c.text(x + 28, yy, cw - 56, [('GPU 記憶體（GiB）', {'color': MUTED})], size=28)
    yy += 48
    bx, bw, top = x + 28 + 230, cw - 56 - 230 - 90, 16
    t4x = bx + vram / top * bw
    for k, (name, v) in enumerate(gib.items()):
        by = yy + k * 72
        c.text(x + 28, by, 230, name, size=28)
        col = WARN if v > vram else ACCENT
        c.rect(bx, by + 8, min(v, top) / top * bw, 32, fill=col, radius=6)
        c.text(bx + min(v, top) / top * bw + 10, by, 90, [(f'{v:.1f}', {'weight': 'Bold', 'color': col})], size=28)
    c.line([(t4x, yy - 6), (t4x, yy + 3 * 72)], color=INK, width=3)
    c.text(t4x - 260, yy + 3 * 72 + 2, 520, [(f'單張 T4 {vram:.1f}', {'weight': 'Bold'})], size=28, align='center')
    yy += 3 * 72 + 76
    yy += row(x, yy, '理由', '16 位元放不進一張 T4。NF4 的刻度依權重常見的分布設計，雙重量化連縮放常數也壓縮；'
                           'T4 沒有原生 bf16，所以用 fp16', INK) + 30
    assert fp is post['systems']['fp16_no_adapter']  # the 16-bit run had no adapter
    yy += row(x, yy, '結果', f'每篇審核約 {secs:.0f} 秒。凍結後用 16 位元、不載微調重跑，不該標 YMYL 的 '
                           f"{len(fp['items_without_ymyl_in_main'])} 篇仍標 {len(fp['ymyl_flagged_without_ymyl_in_main'])} 篇；\n"
                           '依事前規則，多標不是量化造成', WARN)
    if yy > 826:
        raise SystemExit('quantization card overflows')

    # fine-tuning
    x = 20 + cw + gap
    lr = f"{cfg['learning_rate']:.0e}".replace('e-0', 'e-')
    c.rect(x, y, cw, 826, fill=CARD, radius=16)
    c.text(x + 28, y + 18, cw - 56, [('微調：4-bit 底模上的 LoRA', {'weight': 'Bold', 'color': ACCENT})], size=38)
    yy = y + 92
    yy += row(x, yy, '設定', f"r={lora['r']}、alpha {lora['alpha']}、dropout {lora['dropout']:g}，只加在 q_proj、v_proj",
              INK, size=30) + 22
    c.text(x + 28 + lab_w, yy, cw - 56 - lab_w,
           [(f"{lora['params'] / 1e4:.0f} 萬個參數", {'weight': 'Bold', 'size': 50}),
            (f'　佔全部 {n_params / 1e8:.0f} 億的 {share:.3f}%', {'color': MUTED})], size=30)
    yy += 100
    yy += row(x, yy, '做法', '底模維持 4-bit 不動，只訓練旁加的小矩陣；loss 只算答案，不算 prompt、知識卡與文章',
              INK, size=30) + 28
    yy += row(x, yy, '訓練', f'12 筆 AI 寫的監督答案；每 {lora["batch"] * lora["accum"]} 筆更新一次，'
                           f"{epochs} 輪共 {training['global_step']} 步，學習率 {lr} 逐步遞減", INK, size=30) + 28
    yy += row(x, yy, '理由', '只有 12 筆，學習率刻意不調高：背下答案會讓只看訓練資料的自動檢查假性通過',
              INK, size=30) + 28
    yy += row(x, yy, '結果', '每輪平均 loss ' + ' → '.join(f'{v:.2f}' for v in per_epoch)
              + f'；判斷沒學會，測試的逐筆判定和不載微調只差 {n_diff} 篇', WARN, size=30)
    if yy > 826:
        raise SystemExit('fine-tuning card overflows')
    c.save('slide-method.png')


def fig_next(items, post14, prompt):
    """Slide: the two YMYL errors 14B still makes (next to the frozen 8B), how the definition could change, and the
    cost of moving to 14B and the need for new data."""
    ex = post14['excerpts']
    a3, kw = items['3']['Article'], items['3']['Keyword']
    k3 = a3.count(kw)

    def q14(i, code):
        rs = [x for x in ex[i]['qwen3_14b']['Reasons'] if x['code'] == code]
        assert rs, (i, code)
        return rs[0]

    def sev_label(r):
        return {'YMYL_RISK': 'YMYL', 'STUFFING': '堆疊'}[r]

    r17, r3 = q14('17', 'YMYL_RISK'), q14('3', 'YMYL_RISK')
    assert [x['code'] for x in ex['3']['qwen3_14b']['Reasons']] == ['STUFFING', 'YMYL_RISK']
    lead = verbatim(prompt, '引導讀者實際參與可能違法的活動')
    # ID 3 first: its reason points at a definition that can be read loosely; ID 17's cause cannot be separated
    rows = [('3', f'ID 3｜同一個關鍵字重複 {k3} 次', f"參考：關鍵字堆疊 {items['3']['adapter']['ref_severity']}", None,
             f"14B：堆疊＋YMYL {r3['severity']} · {ex['3']['qwen3_14b']['Score']} 分",
             '「' + verbatim(r3['explanation'], '引導讀者參與違法活動卻未交代風險') + '」',
             f'「{lead}」限於原文給出註冊、儲值、出金、下注等步驟', '單純推薦不算'),
            ('17', 'ID 17｜反詐騙提醒', '參考：沒有缺失', '「' + items['17']['Article'] + '」',
             f"14B：YMYL {r17['severity']} · {ex['17']['qwen3_14b']['Score']} 分",
             '「' + verbatim(r17['explanation'], '否認了正規平台客服在特定情境下可能詢問驗證碼的可能性') + '」',
             '警語裡的絕對說法是提醒，不算否認風險', '原因也可能是沒讀懂否定句，這次分不開')]
    c = Canvas(1920, 846)
    c1x, c1w, c2x, c2w, c3x, c3w = 30, 680, 740, 640, 1410, 480
    c.text(c1x + 26, 4, c1w, [('原文與參考判斷', {'weight': 'Bold', 'color': MUTED})], size=30)
    pw = slide_tag(c, c2x, 0, '凍結後對照', MUTED)
    c.text(c2x + pw + 16, 4, c2w - pw - 16, [('凍結的系統（8B）與 14B', {'weight': 'Bold', 'color': WARN})], size=30)
    c.text(c3x, 4, c3w, [('YMYL 定義可以改成', {'weight': 'Bold', 'color': ACCENT})], size=30)
    y, rh = 52, 262
    for iid, head, ref, art, chip14, why14, fix, fix_note in rows:
        a = items[iid]['adapter']
        assert a['codes'] == ['YMYL_RISK']
        c.rect(c1x, y, 1890 - c1x, rh, fill=CARD, radius=14)
        c.rect(c1x, y, 10, rh, fill=WARN, radius=4)
        c.text(c1x + 26, y + 10, c1w - 30, [(head, {'weight': 'Bold'})], size=32)
        c.text(c1x + 26, y + 58, c1w - 30, [(ref, {'weight': 'Bold', 'color': ACCENT})], size=32)
        if art is None:
            art = [('「', {})] + [(p, {'bg': HIGHLIGHT} if p == kw else {})
                                 for p in re.split(f'({re.escape(kw)})', a3) if p] + [('」', {})]
        h = c.text(c1x + 26, y + 108, c1w - 30, art, size=32, gap=1.36)
        if 108 + h > rh:
            raise SystemExit(f'ID {iid} article overflows')
        chip(c, c2x, y + 12, f"8B：YMYL {a['severity']} · {a['score']} 分", WARN_TINT, fg=WARN)
        chip(c, c2x, y + 68, chip14, WARN)
        h = c.text(c2x, y + 128, c2w - 10, why14, size=32, gap=1.36)
        if 128 + h > rh:
            raise SystemExit(f'ID {iid} 14B reason overflows')
        h = c.text(c3x, y + 14, c3w - 10, [(fix, {'weight': 'Medium'})], size=32, gap=1.4)
        c.text(c3x, y + 26 + h, c3w - 10, fix_note, size=30, color=INK)
        y += rh + 12
    # next steps beyond the definition: the cost of 14B and validation on new data
    sysm = post14['systems']
    s14 = mean_seconds(KAGGLE_14B / 'holdout_14b.jsonl')
    s8 = mean_seconds(EVAL_OUT / 'holdout_base.jsonl')
    peak = post14['run_14b']['peak_gpu_bytes_max'] / 2 ** 30
    j14 = sysm['qwen3_14b_4bit_no_adapter']
    cards = [('改用 14B 的取捨', f'單張 T4 推論放得下（峰值 {peak:.1f} GiB）；每篇約 {s14:.0f} 秒，同樣不載微調的 8B '
                              f"約 {s8:.0f} 秒；JSON 第一次只過 {j14['json_first_pass']}/{len(items)}，靠重寫才全部合格；"
                              'T4 上預期無法微調。'),
             ('用新資料驗證', f'這 {len(items)} 篇已用於評估與兩次事後分析。下一輪先累積數十筆人工標註，'
                           '含沒有缺失的文章與邊界案例，用來驗證定義與模型的修改；微調等資料夠了再評估。')]
    cy, gap = y + 4, 30
    cw = (1890 - c1x - gap) / 2
    ch = 846 - cy - 10
    for k, (head, body) in enumerate(cards):
        x = c1x + k * (cw + gap)
        c.rect(x, cy, cw, ch, fill=TINT, radius=14)
        c.text(x + 28, cy + 16, cw - 56, [(head, {'weight': 'Bold', 'color': ACCENT})], size=32)
        h = c.text(x + 28, cy + 66, cw - 56, body, size=32, gap=1.4)
        if cy + 66 + h > 846 - 12:
            raise SystemExit(f'next-step card {k} overflows')
    c.save('slide-next.png')


def main():
    comp, items, raw, split, lock = load()
    post, post14 = read_json(POSTHOC), read_json(POSTHOC14B)
    prompt = (ROOT_FROZEN / 'system_prompt.txt').read_text(encoding='utf-8')
    targets = [json.loads(line) for line in (ROOT_FROZEN / 'data' / 'train_targets.jsonl').read_text(
        encoding='utf-8').splitlines() if line.strip()]
    train_cmp = {it['ID']: it for it in read_json(TRAIN_OUT / 'baseline_comparison.json')['items']}
    fig_problem(split, lock)
    fig_architecture(split, lock)
    fig_method(comp, post)
    fig_output(items, raw, comp)
    fig_scorecard(comp, items)
    fig_doc_scores(comp, items)
    fig_sources(comp, items, post, post14, prompt, targets, train_cmp)
    fig_next(items, post14, prompt)


if __name__ == '__main__':
    sys.exit(main())
