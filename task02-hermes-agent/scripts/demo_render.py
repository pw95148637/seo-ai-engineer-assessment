#!/usr/bin/env python3
"""Render a demo_record.py capture to a 1280x720 MP4: real terminal screens plus chapter cards, captions and labels.

The terminal area shows exactly the pane screens tmux captured (text and colours, original pane geometry); this
script never rewrites their content. It adds, outside the terminal area: a top bar (title, optional rehearsal
banner, playback speed, real elapsed time), a caption band, full-screen chapter cards at storyboard markers, and an
optional title/outro card. Long waits play at a fixed higher speed and the top bar says so for every such frame.

  python scripts/demo_render.py --capture demo/v07/rehearsal/capture --storyboard demo/v07/storyboard-rehearsal.json \
      --out demo/v07/rehearsal.mp4 --snapshots 4,20,45

Writes OUT (H.264, yuv420p), OUT.srt (captions and chapter titles) and OUT.timeline.json (where each chapter and
each fast-forward interval sits in video and in real time). Needs Pillow and ffmpeg on PATH (or --ffmpeg).
"""
from bisect import bisect_right
from pathlib import Path
import argparse, json, re, shutil, subprocess, sys, unicodedata

from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
TOP, BOTTOM, SIDE = 34, 104, 10
BG = (13, 17, 23)
FG = (209, 213, 219)
BAR = (22, 27, 34)
MUTED = (139, 148, 158)
ACCENT = (86, 212, 221)
AMBER = (242, 180, 60)
GREEN = (87, 196, 107)
BORDER = (48, 54, 61)
PALETTE = [(45, 51, 59), (244, 112, 103), (107, 217, 104), (229, 192, 123), (108, 182, 255), (220, 189, 251),
           (86, 212, 221), (209, 213, 219), (99, 110, 123), (255, 147, 138), (141, 219, 140), (242, 204, 96),
           (150, 208, 255), (238, 220, 255), (139, 233, 253), (255, 255, 255)]
SGR = re.compile(r'\x1b\[([0-9;:]*)m')
OTHER_ESC = re.compile(r'\x1b(?:\[[0-9;?]*[A-Za-ln-z]|\][^\x07]*\x07|[()][0-9A-B])')
FONT_CANDIDATES = dict(
    mono=['C:/Windows/Fonts/consola.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'],
    mono_bold=['C:/Windows/Fonts/consolab.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf'],
    cjk=['C:/Windows/Fonts/msjh.ttc', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'],
    cjk_bold=['C:/Windows/Fonts/msjhbd.ttc', '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'],
    emoji=['C:/Windows/Fonts/seguiemj.ttf'])  # optional: wide symbols the CJK font lacks (e.g. 🎰)


def find_font(kind):
    for path in FONT_CANDIDATES[kind]:
        if Path(path).exists():
            return path
    raise SystemExit(f'no font for {kind}; looked at ' + ', '.join(FONT_CANDIDATES[kind]))


def cell_width(ch):
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in 'WF' else 1


def plain(line):
    return OTHER_ESC.sub('', SGR.sub('', line))


# Terminal screen model ------------------------------------------------------------------------------------------
class Style:
    __slots__ = ('fg', 'bg', 'bold', 'dim', 'under', 'rev')

    def __init__(self):
        self.fg = self.bg = None
        self.bold = self.dim = self.under = self.rev = False

    def key(self):
        return (self.fg, self.bg, self.bold, self.dim, self.under, self.rev)

    def apply(self, params):
        codes = [int(x) if x.isdigit() else 0 for x in re.split('[;:]', params)] if params else [0]
        i = 0
        while i < len(codes):
            c = codes[i]
            if c == 0:
                self.__init__()
            elif c == 1:
                self.bold = True
            elif c == 2:
                self.dim = True
            elif c == 4:
                self.under = True
            elif c == 7:
                self.rev = True
            elif c == 22:
                self.bold = self.dim = False
            elif c == 24:
                self.under = False
            elif c == 27:
                self.rev = False
            elif 30 <= c <= 37:
                self.fg = c - 30
            elif 90 <= c <= 97:
                self.fg = c - 90 + 8
            elif c == 39:
                self.fg = None
            elif 40 <= c <= 47:
                self.bg = c - 40
            elif 100 <= c <= 107:
                self.bg = c - 100 + 8
            elif c == 49:
                self.bg = None
            elif c in (38, 48) and i + 1 < len(codes):
                target = 'fg' if c == 38 else 'bg'
                if codes[i + 1] == 5 and i + 2 < len(codes):
                    setattr(self, target, ('256', codes[i + 2]))
                    i += 2
                elif codes[i + 1] == 2 and i + 4 < len(codes):
                    setattr(self, target, ('rgb', codes[i + 2], codes[i + 3], codes[i + 4]))
                    i += 4
            i += 1


def color256(n):
    if n < 16:
        return PALETTE[n]
    if n < 232:
        n -= 16
        steps = [0, 95, 135, 175, 215, 255]
        return steps[n // 36], steps[(n // 6) % 6], steps[n % 6]
    v = 8 + (n - 232) * 10
    return v, v, v


def resolve(c, default, bold=False):
    if c is None:
        return default
    if isinstance(c, int):
        return PALETTE[c + 8 if bold and c < 8 else c]
    if c[0] == '256':
        return color256(c[1])
    return c[1:]


def parse_line(line):
    """Cells of one captured line: (char, width, style key)."""
    cells, st, pos = [], Style(), 0
    line = OTHER_ESC.sub('', line)
    for m in SGR.finditer(line):
        for ch in line[pos:m.start()]:
            cells.append((ch, cell_width(ch), st.key()))
        st.apply(m.group(1))
        pos = m.end()
    for ch in line[pos:]:
        cells.append((ch, cell_width(ch), st.key()))
    return cells


class Fonts:
    def __init__(self, size):
        self.size = size
        self.mono = ImageFont.truetype(find_font('mono'), size)
        self.mono_bold = ImageFont.truetype(find_font('mono_bold'), size)
        self.cjk = ImageFont.truetype(find_font('cjk'), size)
        self.cjk_bold = ImageFont.truetype(find_font('cjk_bold'), size)
        self.cell_w = self.mono.getlength('M')
        asc, desc = self.mono.getmetrics()
        self.asc, self.desc = asc, desc
        emoji = next((p for p in FONT_CANDIDATES['emoji'] if Path(p).exists()), None)
        self.emoji = ImageFont.truetype(emoji, size) if emoji else None
        self._notdef = self._sig('\U000f0000')
        self._cjk_notdef = self._sig('\U000f0000', self.cjk)
        self._has = {}
        self._cjk_has = {}

    def _sig(self, ch, font=None):
        img = Image.new('L', (self.size * 2, self.size * 2))
        ImageDraw.Draw(img).text((0, 0), ch, font=font or self.mono, fill=255)
        return img.tobytes()

    def in_cjk(self, ch):
        """True if the CJK font has a real glyph for `ch`; otherwise the emoji font (if any) draws it."""
        if ch not in self._cjk_has:
            self._cjk_has[ch] = self._sig(ch, self.cjk) != self._cjk_notdef
        return self._cjk_has[ch]

    def in_mono(self, ch):
        """True if the mono font has a real glyph for `ch` (not its .notdef box)."""
        if ch.isascii():
            return True
        if ch not in self._has:
            self._has[ch] = self._sig(ch) != self._notdef
        return self._has[ch]


class TerminalRenderer:
    def __init__(self, layout, area):
        self.layout = layout
        self.cols, self.rows = layout['cols'], layout['rows']
        x0, y0, aw, ah = area
        cell_h = int(ah // self.rows)
        size = 30
        while size > 8:
            f = ImageFont.truetype(find_font('mono'), size)
            asc, desc = f.getmetrics()
            if f.getlength('M') * self.cols <= aw and asc + desc <= cell_h - 1:
                break
            size -= 1
        self.f = Fonts(size)
        self.cell_h = cell_h
        self.cw = self.f.cell_w
        tw = self.cw * self.cols
        self.x0 = x0 + (aw - tw) / 2
        self.y0 = y0 + (ah - cell_h * self.rows) / 2
        self.title_font = ImageFont.truetype(find_font('cjk_bold'), max(11, int(cell_h * 0.62)))
        self.base = int(round((cell_h - (self.f.asc + self.f.desc)) / 2 + self.f.asc))

    def draw(self, img, screens):
        d = ImageDraw.Draw(img)
        for pane in self.layout['panes']:
            top, left, width, height = pane['top'], pane['left'], pane['width'], pane['height']
            by = self.y0 + (top - 1) * self.cell_h
            bx = self.x0 + left * self.cw
            d.rectangle([bx, by, bx + width * self.cw, by + self.cell_h - 1], fill=BAR)
            d.line([bx, by + self.cell_h - 1, bx + width * self.cw, by + self.cell_h - 1], fill=BORDER)
            d.text((bx + 6, by + self.cell_h / 2), pane.get('title', pane['name']), font=self.title_font, fill=MUTED,
                   anchor='lm')
            for r, cells in enumerate(screens.get(pane['name'], [])[:height]):
                self.draw_row(d, bx, self.y0 + (top + r) * self.cell_h, cells, width)

    def draw_row(self, d, x0, y, cells, width):
        col, run, run_col, run_key = 0, [], 0, None

        def flush():
            if run:
                fg, bg, bold, dim, under, rev = run_key
                color = self.fg_color(run_key)
                font = self.f.mono_bold if bold else self.f.mono
                d.text((x0 + run_col * self.cw, y + self.base), ''.join(run), font=font, fill=color, anchor='ls')
                if under:
                    d.line([x0 + run_col * self.cw, y + self.base + 2, x0 + (run_col + len(run)) * self.cw,
                            y + self.base + 2], fill=color)

        for ch, w, key in cells:
            if col >= width:
                break
            if w == 0:
                continue
            fg, bg, bold, dim, under, rev = key
            back = resolve(fg, FG, bold) if rev else (resolve(bg, None) if bg is not None else None)
            if back is not None:
                d.rectangle([x0 + col * self.cw, y, x0 + (col + w) * self.cw, y + self.cell_h - 1], fill=back)
            if w == 1 and self.f.in_mono(ch) and ch != ' ':
                if run and (key != run_key or run_col + len(run) != col):
                    flush()
                    run = []
                if not run:
                    run_col, run_key = col, key
                run.append(ch)
            else:
                flush()
                run = []
                if ch != ' ' and self.f.emoji and not self.f.in_cjk(ch):
                    span = w * self.cw
                    font = self.f.emoji
                    gw = font.getlength(ch)
                    if gw > span:
                        font = ImageFont.truetype(font.path, max(6, int(self.f.size * span / gw)))
                        gw = font.getlength(ch)
                    d.text((x0 + col * self.cw + (span - gw) / 2, y + self.base), ch, font=font, anchor='ls',
                           embedded_color=True)
                elif ch != ' ':
                    font = self.f.cjk_bold if bold else self.f.cjk
                    gw = font.getlength(ch)
                    span = w * self.cw
                    if gw > span:  # a narrow cell with a wide fallback glyph: shrink to fit
                        font = ImageFont.truetype(find_font('cjk_bold' if bold else 'cjk'),
                                                  max(6, int(self.f.size * span / gw)))
                        gw = font.getlength(ch)
                    d.text((x0 + col * self.cw + (span - gw) / 2, y + self.base), ch, font=font,
                           fill=self.fg_color(key), anchor='ls')
            col += w
        flush()

    def fg_color(self, key):
        fg, bg, bold, dim, under, rev = key
        color = resolve(bg, BG) if rev else resolve(fg, FG, bold)
        if dim:
            color = tuple(int(c * 0.55 + b * 0.45) for c, b in zip(color, BG))
        return color


# Overlays --------------------------------------------------------------------------------------------------------
class UI:
    def __init__(self):
        cjk, bold = find_font('cjk'), find_font('cjk_bold')
        self.f = {n: ImageFont.truetype(bold if b else cjk, s) for n, (s, b) in dict(
            bar=(16, True), pill=(15, True), label=(16, True), cap=(23, False), step=(26, True), title=(44, True),
            sub=(25, False), req=(21, True), note=(17, False), line=(22, False)).items()}

    def wrap(self, text, font, width, max_lines=3):
        lines, cur = [], ''
        for ch in str(text):
            if ch == '\n':
                lines.append(cur)
                cur = ''
                continue
            if font.getlength(cur + ch) > width and cur:
                lines.append(cur)
                cur = ch.lstrip()
            else:
                cur += ch
        if cur:
            lines.append(cur)
        return lines[:max_lines]

    def pill(self, d, xy_right, text, fill, fg=(13, 17, 23), anchor_right=True):
        font = self.f['pill']
        tw = font.getlength(text)
        x1, y = xy_right
        x0 = x1 - tw - 20 if anchor_right else x1
        d.rounded_rectangle([x0, y, x0 + tw + 20, y + 24], radius=12, fill=fill)
        d.text((x0 + 10, y + 12), text, font=font, fill=fg, anchor='lm')
        return x0

    def top_bar(self, img, story, speed=None, elapsed=None):
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, W, TOP - 1], fill=BAR)
        d.text((SIDE + 4, TOP / 2), story.get('header', ''), font=self.f['bar'], fill=FG, anchor='lm')
        x = SIDE + 12 + self.f['bar'].getlength(story.get('header', ''))
        if story.get('banner'):
            self.pill(d, (x + 8, 5), story['banner'], AMBER, anchor_right=False)
        right = W - SIDE - 4
        if elapsed is not None:
            m, s = divmod(int(elapsed), 60)
            text = f'實際經過 {m:02d}:{s:02d}'
            d.text((right, TOP / 2), text, font=self.f['bar'], fill=MUTED, anchor='rm')
            right -= self.f['bar'].getlength(text) + 12
        if speed is not None:
            label = '×1 即時' if speed == 1 else f'×{speed:g} 快轉'
            self.pill(d, (right, 5), label, GREEN if speed == 1 else AMBER)

    def caption(self, img, label, text):
        d = ImageDraw.Draw(img)
        y0 = H - BOTTOM
        d.rectangle([0, y0, W, H], fill=(9, 12, 16))
        d.line([0, y0, W, y0], fill=BORDER)
        if label:
            d.text((SIDE + 8, y0 + 18), label, font=self.f['label'], fill=ACCENT, anchor='lm')
        lines = self.wrap(text or '', self.f['cap'], W - 2 * SIDE - 16, 2)
        for i, line in enumerate(lines):
            d.text((SIDE + 8, y0 + 50 + i * 32), line, font=self.f['cap'], fill=FG, anchor='lm')

    def card(self, story, card):
        img = Image.new('RGB', (W, H), BG)
        d = ImageDraw.Draw(img)
        self.top_bar(img, dict(story, header=story.get('header', '')))
        y = 190
        if card.get('step'):
            d.text((120, y), card['step'], font=self.f['step'], fill=ACCENT, anchor='lm')
            y += 62
        for line in self.wrap(card.get('title', ''), self.f['title'], W - 240, 2):
            d.text((120, y), line, font=self.f['title'], fill=(255, 255, 255), anchor='lm')
            y += 64
        d.line([120, y, 300, y], fill=ACCENT, width=3)
        y += 40
        for line in self.wrap(card.get('sub', ''), self.f['sub'], W - 240, 3):
            d.text((120, y), line, font=self.f['sub'], fill=FG, anchor='lm')
            y += 40
        if card.get('req'):
            y += 12
            d.text((120, y), card['req'], font=self.f['req'], fill=AMBER, anchor='lm')
            y += 40
        for line in card.get('lines', []):
            for row in self.wrap(line, self.f['line'], W - 240, 2):
                d.text((120, y), row, font=self.f['line'], fill=FG, anchor='lm')
                y += 34
            y += 6
        if card.get('note'):
            d.text((120, H - 60), card['note'], font=self.f['note'], fill=MUTED, anchor='lm')
        return img


# Timeline --------------------------------------------------------------------------------------------------------
def load_capture(capture):
    layout = json.loads((capture / 'layout.json').read_text(encoding='utf-8'))
    frames = [json.loads(x) for x in (capture / 'frames.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
    frames.sort(key=lambda f: f['t'])
    return layout, frames


def find_markers(frames, segments):
    out = []
    for seg in segments:
        t = next((f['t'] for f in frames if f['pane'] == seg.get('pane', 'viewer')
                  and any(seg['marker'] in plain(x) for x in f['lines'])), None)
        if t is None:
            print(f'warning: marker {seg["marker"]!r} not found; segment skipped', file=sys.stderr)
            continue
        out.append((t, seg))
    out.sort(key=lambda x: x[0])
    return out


def merged_speed(story, seg):
    s = dict(base=1.0, idle_gap=4.0, idle_speed=6.0, lead=1.5, min_ff=1.0)
    s.update(story.get('speed') or {})
    s.update((seg or {}).get('speed') or {})
    return s


def check_text(story):
    """Captions and card text the renderer would cut off or break inside an ASCII word; returns the problem count."""
    ui, problems = UI(), 0
    cap_w, card_w = W - 2 * SIDE - 16, W - 240

    def check(where, text, font, width, max_lines):
        nonlocal problems
        rows = ui.wrap(text, ui.f[font], width, 99)
        bad = [f'{len(rows)} lines > {max_lines}, the rest is cut'] if len(rows) > max_lines else []
        bad += [f'word split {a[-8:]!r} | {b[:8]!r}' for a, b in zip(rows, rows[1:])
                if a and b and a[-1].isascii() and a[-1].isalnum() and b[0].isascii() and b[0].isalnum()]
        problems += bool(bad)
        print(('!! ' if bad else 'ok ') + where + ('：' + '；'.join(bad) if bad else ''))

    def card(where, c):
        check(where + ' title', c.get('title', ''), 'title', card_w, 2)
        check(where + ' sub', c.get('sub', ''), 'sub', card_w, 3)
        for i, line in enumerate(c.get('lines', [])):
            check(f'{where} line {i + 1}', line, 'line', card_w, 2)

    for name in ('title_card', 'outro_card'):
        if story.get(name):
            card(name, story[name])
    for seg in [story.get('intro') or {}] + story.get('segments', []):
        if seg.get('card'):
            card(f'{seg.get("marker", "intro")} card', seg['card'])
        for i, c in enumerate(seg.get('captions', [])):
            check(f'{seg.get("marker", "intro")} caption {i + 1}', c, 'cap', cap_w, 2)
    check('end_caption', story.get('end_caption', ''), 'cap', cap_w, 2)
    return problems


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--capture', help='directory written by demo_record.py')
    p.add_argument('--storyboard', required=True)
    p.add_argument('--out')
    p.add_argument('--fps', type=float)
    p.add_argument('--ffmpeg', default=shutil.which('ffmpeg') or 'ffmpeg')
    p.add_argument('--snapshots', help='comma-separated video seconds to save as PNG next to OUT')
    p.add_argument('--crf', type=int, default=20)
    p.add_argument('--check-text', action='store_true',
                   help='only report storyboard text that would be cut off or split mid-word; exit 1 if any')
    a = p.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if a.check_text:
        return 1 if check_text(json.loads(Path(a.storyboard).read_text(encoding='utf-8'))) else 0
    if not (a.capture and a.out):
        p.error('--capture and --out are required unless --check-text')

    capture, out = Path(a.capture), Path(a.out)
    story = json.loads(Path(a.storyboard).read_text(encoding='utf-8'))
    layout, frames = load_capture(capture)
    fps = a.fps or story.get('fps', 12)
    t_end = max(layout.get('duration') or 0, frames[-1]['t'] if frames else 0)
    change_times = sorted({f['t'] for f in frames})
    markers = find_markers(frames, story.get('segments', []))
    ui = UI()
    term = TerminalRenderer(layout, (SIDE, TOP + 4, W - 2 * SIDE, H - TOP - BOTTOM - 8))
    snaps = sorted(float(x) for x in a.snapshots.split(',')) if a.snapshots else []
    snap_dir = out.with_suffix('')
    if snaps:
        snap_dir = Path(str(snap_dir) + '_frames')
        snap_dir.mkdir(parents=True, exist_ok=True)

    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [a.ffmpeg, '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', f'{fps:g}',
           '-i', '-', '-c:v', 'libx264', '-preset', 'medium', '-crf', str(a.crf), '-pix_fmt', 'yuv420p',
           '-movflags', '+faststart', str(out)]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    state = dict(n=0, cap=None)
    srt, timeline = [], dict(capture=str(capture), fps=fps, chapters=[], speed_intervals=[], cards=[])

    def caption_tick(text, v):
        cur = state['cap']
        if cur is None or cur['text'] != text:
            state['cap'] = cur = dict(start=v, end=v, text=text)
            srt.append(cur)
        cur['end'] = v + 1 / fps

    def emit(img):
        v = state['n'] / fps
        while snaps and snaps[0] <= v:
            img.save(snap_dir / f'frame_{snaps.pop(0):07.2f}s.png')
        enc.stdin.write(img.tobytes())
        state['n'] += 1

    def emit_card(card, seconds, label):
        img = ui.card(story, card)
        start = state['n'] / fps
        for _ in range(int(round(seconds * fps))):
            emit(img)
        timeline['cards'].append(dict(label=label, video_start=round(start, 2), video_end=round(state['n'] / fps, 2)))
        srt.append(dict(start=start, end=state['n'] / fps, text=(card.get('step', '') + ' ' + card.get('title', '')).strip()))
        state['cap'] = None

    if story.get('title_card'):
        emit_card(story['title_card'], story['title_card'].get('seconds', 4), 'title')

    screens = {}
    parsed = {}
    fi = 0
    r = 0.0
    mi = 0
    seg = story.get('intro') or {}
    seg_v0 = state['n'] / fps
    term_img = None
    dirty = True
    last_speed, speed_start = None, None
    chapter = dict(label=seg.get('label', ''), video_start=round(seg_v0, 2), real_start=0.0)

    def close_speed(now_v, now_r):
        if last_speed is not None and last_speed != 1:
            timeline['speed_intervals'][-1].update(video_end=round(now_v, 2), real_end=round(now_r, 2))

    while r <= t_end:
        if mi < len(markers) and r >= markers[mi][0]:
            close_speed(state['n'] / fps, r)
            last_speed = None
            chapter.update(video_end=round(state['n'] / fps, 2), real_end=round(r, 2))
            timeline['chapters'].append(chapter)
            seg = markers[mi][1]
            if seg.get('card'):
                emit_card(seg['card'], seg['card'].get('seconds', 2.5), seg.get('label', ''))
            seg_v0 = state['n'] / fps
            chapter = dict(label=seg.get('label', ''), marker=seg['marker'], video_start=round(seg_v0, 2),
                           real_start=round(markers[mi][0], 2))
            mi += 1
            continue
        while fi < len(frames) and frames[fi]['t'] <= r:
            f = frames[fi]
            key = (f['pane'], fi)
            screens[f['pane']] = parsed.setdefault(key, [parse_line(x) for x in f['lines']])
            fi += 1
            dirty = True
        if dirty:
            term_img = Image.new('RGB', (W, H), BG)
            term.draw(term_img, screens)
            dirty = False
        sp = merged_speed(story, seg)
        i = bisect_right(change_times, r) - 1
        a_t = change_times[i] if i >= 0 else 0.0
        b_t = change_times[i + 1] if i + 1 < len(change_times) else t_end
        # Fast-forward a wait only when the sped-up stretch lasts at least min_ff video seconds, so labels don't flicker.
        idle = (b_t - a_t > sp['idle_gap'] and (b_t - a_t - sp['lead']) / sp['idle_speed'] >= sp['min_ff']
                and r >= a_t + sp['lead'])
        speed = sp['idle_speed'] if idle else sp['base']
        v = state['n'] / fps
        if speed != last_speed:
            close_speed(v, r)
            if speed != 1:
                timeline['speed_intervals'].append(dict(speed=speed, video_start=round(v, 2), real_start=round(r, 2)))
            last_speed = speed
        caps = seg.get('captions') or ['']
        k = min(int((v - seg_v0) / seg.get('caption_seconds', story.get('caption_seconds', 6))), len(caps) - 1)
        caption_tick(caps[k], v)
        img = term_img.copy()
        ui.top_bar(img, story, speed, r)
        ui.caption(img, seg.get('label', ''), caps[k])
        emit(img)
        step = speed / fps
        if b_t > r and r + step > b_t and speed != sp['base']:
            r = b_t  # never skip past a screen change while fast-forwarding
        else:
            r += step
    close_speed(state['n'] / fps, t_end)
    chapter.update(video_end=round(state['n'] / fps, 2), real_end=round(t_end, 2))
    timeline['chapters'].append(chapter)
    if term_img is not None:
        img = term_img.copy()
        ui.top_bar(img, story, None, t_end)
        ui.caption(img, seg.get('label', ''), story.get('end_caption', '（錄影結束畫面）'))
        for _ in range(int(round(story.get('end_hold', 3) * fps))):
            emit(img)
    if story.get('outro_card'):
        emit_card(story['outro_card'], story['outro_card'].get('seconds', 5), 'outro')
    enc.stdin.close()
    if enc.wait() != 0:
        raise SystemExit('ffmpeg failed')
    total = state['n'] / fps
    timeline.update(video_seconds=round(total, 2), real_seconds=round(t_end, 2))

    def ts(x):
        ms = int(round(x * 1000))
        return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'

    items = [(c['start'], c['end'], c['text']) for c in srt if c['text'] and c['end'] > c['start']]
    Path(str(out) + '.srt').write_text(''.join(f'{i}\n{ts(s)} --> {ts(e)}\n{t}\n\n' for i, (s, e, t) in enumerate(items, 1)),
                                       encoding='utf-8')
    Path(str(out) + '.timeline.json').write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(out=str(out), video_seconds=round(total, 1), real_seconds=round(t_end, 1),
                          chapters=[(c['label'], c['video_start']) for c in timeline['chapters']],
                          fast_forward=[(x['speed'], x['video_start'], x.get('video_end')) for x in timeline['speed_intervals']]),
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
