#!/usr/bin/env python3
"""Readable terminal view of one Hermes research run, for recording the Demo. Read-only.

Live data sources, both written while the run is in progress:
  * RUN_ROOT/research.sqlite, table `events`: the controller commits one row per tool call, HTTP request and
    response, search, lessons presentation, report and learning step (src/research_core.py, Research.event).
  * Hermes agent.log (HERMES_HOME/logs/agent.log): one line per model API call and per tool completion.
The model's commentary and final answer exist only in RUN_ID-hermes.json, which the runner writes after the
conversation ends; the closing pages show them and say where they come from.

Subcommands
  events          live view (default) or --replay of a finished run: ledger, steps, report, score, ledger change
  hermes-log      formatted live tail (or --replay) of Hermes agent.log for a second pane
  replay-console  rehearsal only: print a finished step's original command, wait, then its console output

Examples
  python3 scripts/demo_live_view.py events --root RUN_ROOT --hermes-log .runtime/user/logs/agent.log
  python3 scripts/demo_live_view.py hermes-log --log .runtime/user/logs/agent.log
  python3 scripts/demo_live_view.py events --root evaluation/v06/runs/2030-series --replay \
      --steps evaluation/v06/steps.json --step R3 --hermes-log .runtime/user/logs/agent.log --banner '演練：重播 v0.6 R3'
"""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit
import argparse, json, re, shlex, shutil, sqlite3, sys, time, unicodedata

OFFPAGE_TOPICS = (r'(?i)off.?page|backlink|link.?profile|referr|external|outbound|mention|brand|social|serp|rank|'
                  r'search|index|reputation|外部|站外|反向|外鏈|提及|社群|排名|收錄|聲譽|索引|搜尋')
LOG_LINE = re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),(\d{3}) (\w+) (?:\[(\w+)\] )?([\w.]+): (.*)$')
API_CALL = re.compile(r'API call #(\d+):.*?\bin=(\d+) out=(\d+) total=(\d+) latency=([\d.]+)s')
TOOL_DONE = re.compile(r'(?:tool (\w+) completed|Tool (\w+) returned error) \(([-\d.]+)s')
LOG_NOISE = ('OpenAI client created', 'OpenAI client closed', 'Codex stream first', 'memory trim',
             'Cached context length', 'Auxiliary auto-detect', 'capability_check')
STYLE = dict(reset='\033[0m', bold='\033[1m', dim='\033[2m', red='\033[31m', green='\033[32m', yellow='\033[33m',
             blue='\033[34m', magenta='\033[35m', cyan='\033[36m', white='\033[37m', bgreen='\033[1;32m',
             bred='\033[1;31m', byellow='\033[1;33m', bcyan='\033[1;36m', bmagenta='\033[1;35m')
KIND_ZH = {'observation': '觀察', 'inference': '推論', 'unknown': '未知'}
SECTION_ZH = {'on_page': '站內', 'off_page': '站外', 'other': '其他'}
STATUS_ZH = {'active': '使用中', 'candidate': '候選', 'revoked': '已撤銷', 'expired': '已到期', 'vetoed': '人工否決',
             'superseded': '已被取代'}
PRIORITY_ZH = {'decide': '需要決定', 'review': '視需要處理', 'info': '紀錄'}


# Text layout ---------------------------------------------------------------------------------------------------
def cell_width(ch):
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in 'WF' else 1


def text_width(s):
    return sum(cell_width(c) for c in s)


def clip(s, width):
    """Cut to `width` terminal cells, marking the cut with an ellipsis."""
    s = ' '.join(str(s).split())
    if text_width(s) <= width:
        return s
    out, used = [], 0
    for ch in s:
        if used + cell_width(ch) > width - 1:
            break
        out.append(ch)
        used += cell_width(ch)
    return ''.join(out) + '…'


def wrap(s, width, max_lines=None, first_width=None):
    """Wrap plain text (no escape codes) to terminal cells; the first line may be narrower."""
    s = ' '.join(str(s).split())
    lines, cur, used = [], [], 0
    limit = first_width if first_width is not None else width
    for ch in s:
        w = cell_width(ch)
        if used + w > limit:
            lines.append(''.join(cur).rstrip())
            cur, used = ([], 0) if ch == ' ' else ([ch], w)
            limit = width
            continue
        cur.append(ch)
        used += w
    if cur:
        lines.append(''.join(cur).rstrip())
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        last_width = first_width if (max_lines == 1 and first_width is not None) else width
        lines[-1] = clip(lines[-1] + '…', last_width)
    return lines or ['']


def pad(s, cells):
    return s + ' ' * max(0, cells - text_width(s))


def readable_url(url, host=None):
    """Decode percent-encoding; drop scheme and the run's own host to save width."""
    url = unquote(str(url))
    parts = urlsplit(url)
    if host and parts.hostname == host:
        return (parts.path or '/') + ('?' + parts.query if parts.query else '')
    return url.replace('https://', '').replace('http://', '')


def decode_urls(text):
    return re.sub(r'https?://\S+?(?=[（）()，。、\s]|$)', lambda m: unquote(m.group(0)), str(text))


class Out:
    def __init__(self, color=True):
        self.color = color

    def size(self):
        s = shutil.get_terminal_size((120, 30))
        return max(60, s.columns), max(10, s.lines)

    def paint(self, text, style=None):
        if not style or not self.color:
            return text
        return ''.join(STYLE[x] for x in style.split()) + text + STYLE['reset']

    def write(self, text='', style=None):
        sys.stdout.write(self.paint(text, style) + '\n')
        sys.stdout.flush()

    def block(self, text, style=None, prefix='', first=None, max_lines=None, label='', label_style=None):
        """Print wrapped plain `text`; `first`/`prefix` lead the first/other lines, `label` is a coloured tag."""
        width = self.size()[0] - 1
        first = prefix if first is None else first
        lines = wrap(text, width - text_width(prefix), max_lines,
                     first_width=width - text_width(first) - text_width(label))
        for i, line in enumerate(lines):
            lead = self.paint(first, 'dim') + self.paint(label, label_style) if i == 0 else prefix
            sys.stdout.write(lead + self.paint(line, style) + '\n')
        sys.stdout.flush()

    def rule(self, title, style='bold'):
        width = self.size()[0] - 1
        text = '== ' + title + ' '
        self.write(text + '=' * max(3, width - text_width(text)), style)

    def clear(self):
        sys.stdout.write('\033[2J\033[H')
        sys.stdout.flush()


# Project helpers (read-only imports; the view degrades if the controller code changes) ----------------------------
class Project:
    def __init__(self, task_root):
        sys.path.insert(0, str(task_root))
        self.snapshot_info = self.keyword_page = self.score_run = None
        self.rules = {}
        self.notes = []
        try:
            from src.research_core import snapshot_info
            self.snapshot_info = snapshot_info
        except Exception as exc:
            self.notes.append('snapshot_info unavailable: ' + type(exc).__name__)
        try:
            from src.lessons import keyword_page, RULES
            self.keyword_page, self.rules = keyword_page, dict(RULES)
        except Exception as exc:
            self.notes.append('keyword_page unavailable: ' + type(exc).__name__)
        try:
            from src.scoring import score_run
            self.score_run = score_run
        except Exception as exc:
            self.notes.append('score_run unavailable: ' + type(exc).__name__)
        self.html = self.structured_data = self.image_links = self.handoff = None
        try:
            from src.research_core import HTML, structured_data, image_links
            self.html, self.structured_data, self.image_links = HTML, structured_data, image_links
        except Exception as exc:
            self.notes.append('page extras unavailable: ' + type(exc).__name__)
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location('handoff_queue', Path(task_root) / 'scripts' / 'handoff_queue.py')
            self.handoff = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.handoff)
        except Exception as exc:
            self.handoff = None
            self.notes.append('handoff_queue unavailable: ' + type(exc).__name__)

    def hits(self, info, keywords, host):
        if not info or info.get('kind') != 'html' or info.get('status') != 200:
            return []
        if urlsplit(info['url']).hostname != host:
            return []
        if self.keyword_page:
            return [k for k in keywords if self.keyword_page(info['url'], info.get('title'), info.get('h1'), k)]
        return [k for k in keywords if k.casefold() in (info.get('title', '') + info.get('h1', '')).casefold()]


def connect_ro(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    return db


def table_exists(db, name):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def ledger_snapshot(db):
    """Lessons, support counts and feedback as plain dicts; tolerant of schema changes."""
    if not table_exists(db, 'lessons'):
        return dict(lessons=[], feedback=[])
    lessons = []
    for r in db.execute('SELECT * FROM lessons ORDER BY kind,key'):
        d = dict(r)
        try:
            d['data'] = json.loads(d.get('data') or '{}')
        except ValueError:
            d['data'] = {}
        if table_exists(db, 'lesson_support'):
            d['support_runs'] = db.execute(
                'SELECT COUNT(DISTINCT run) FROM lesson_support WHERE lesson=? AND polarity=1 AND epoch=?',
                (d['id'], d['data'].get('epoch', 0))).fetchone()[0]
        lessons.append(d)
    feedback = [dict(r) for r in db.execute('SELECT * FROM feedback ORDER BY id')] if table_exists(db, 'feedback') else []
    return dict(lessons=lessons, feedback=feedback)


def memory_snapshot(db):
    """Research memory held by a ledger (v0.9): findings, pages read, links seen but not read, latest unknowns."""
    if not table_exists(db, 'site_pages'):
        return None
    read = {r[0] for r in db.execute('SELECT norm FROM site_pages')}
    unread = {r[0] for r in db.execute('SELECT norm FROM site_links')} - read
    last = db.execute('SELECT run FROM open_unknowns ORDER BY id DESC LIMIT 1').fetchone()
    return dict(findings=db.execute("SELECT COUNT(*) FROM lessons WHERE kind='finding' AND status IN ('candidate','active')")
                .fetchone()[0], pages=len(read), unread=len(unread),
                unknowns=db.execute('SELECT COUNT(*) FROM open_unknowns WHERE run=?', (last[0],)).fetchone()[0] if last else 0)


def load_ledger_json(path):
    d = json.loads(Path(path).read_text(encoding='utf-8'))
    for lesson in d.get('lessons', []):
        if lesson.get('support_runs') is None and isinstance(lesson.get('data'), dict) and lesson['data'].get('runs'):
            lesson['support_runs'] = len(lesson['data']['runs'])
    return d


def parse_time(s):
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def log_time(date, ms, tz):
    return datetime.strptime(date, '%Y-%m-%d %H:%M:%S').replace(microsecond=int(ms) * 1000, tzinfo=tz)


def local_tz(offset_hours):
    if offset_hours is None:
        return datetime.now().astimezone().tzinfo
    from datetime import timedelta
    return timezone(timedelta(hours=offset_hours))


# Events view ---------------------------------------------------------------------------------------------------
class EventsView:
    def __init__(self, args):
        self.a = args
        self.out = Out(not args.no_color)
        self.proj = Project(Path(args.task_root).resolve())
        self.root = Path(args.root)
        self.db_path = self.root / 'research.sqlite'
        self.keywords = args.keyword or ['娛樂城', '3A娛樂城']
        self.rid = args.run_id
        self.host = None
        self.cfg = {}
        self.calls = 0
        self.call_names = []
        self.last_fetch = None
        self.hit = {}
        self.presented = []
        self.ledger_rows = {}
        self.before = None
        self.learning = None
        self.finish_seen = False
        self.report = None
        self.rejections = []
        self.api_tokens = 0
        self.proxy_note = False
        self.t_start = None
        self.offpage = re.compile(args.offpage_topics)
        self.shown = set()
        self.memory_eids = {}
        self.memory_candidates = set()

    # helpers
    def stamp(self, when=None):
        if self.t_start is None:
            return '+--:--'
        sec = max(0, int((when if when is not None else self.now()) - self.t_start))
        return f'+{sec // 60:02d}:{sec % 60:02d}'

    def now(self):
        return time.monotonic() if not self.a.replay else self.replay_clock

    def once(self, key):
        """True if `key` was already shown; marks it shown."""
        seen = key in self.shown
        self.shown.add(key)
        return seen

    def evidence_row(self, db, eid):
        return db.execute('SELECT * FROM evidence WHERE id=?', (eid,)).fetchone() if isinstance(eid, str) else None

    def info(self, db, eid):
        r = self.evidence_row(db, eid)
        if not r or not self.proj.snapshot_info:
            return None
        try:
            return self.proj.snapshot_info(self.root, r)
        except Exception:
            return None

    def line(self, text, style=None, when=None, label='', label_style=None):
        self.out.block(text, style, prefix=' ' * 8, first=self.stamp(when) + '  ', label=label, label_style=label_style)

    def sub(self, text, style=None, max_lines=None):
        self.out.block(text, style, prefix=' ' * 10, first=' ' * 8 + '→ ', max_lines=max_lines)

    def note(self, text, style='yellow', max_lines=2):
        self.out.block(text, style, prefix=' ' * 10, first=' ' * 8 + '└ ', max_lines=max_lines)

    # section 1
    LEDGER_RULE = ('規則：lessons 只由控制器量測或人工審查寫入，模型沒有寫入路徑；有範圍與效期，與新證據衝突時以新證據為準。'
                   'discovery 類與研究記憶的發現，交給模型前都由控制器重抓確認。')

    def show_ledger(self, snap, source, after_rows=2):
        """One screen: title, [1/5] rule, one row per lesson, rule text, plus `after_rows` lines the caller prints next.

        Every row is clipped to the pane width, and lessons that do not fit collapse into one "另 N 條" row, so the
        title and the [1/5] marker never scroll out of a short pane (the renderer finds chapters by that marker).
        """
        o = self.out
        o.clear()
        self.header()
        o.rule('[1/5] 記憶帳本：本 run 開始前的 lessons（Memory / Learning）', 'bcyan')
        self.ledger_rows = {x['id']: x for x in snap.get('lessons', [])}
        lessons = [x for x in snap.get('lessons', []) if x.get('kind') != 'finding']  # findings: one memory line below
        mem = snap.get('memory')
        width, height = o.size()[0] - 1, o.size()[1]

        def summary(items):
            c = {}
            for x in items:
                c[x.get('status')] = c.get(x.get('status'), 0) + 1
            return ' · '.join(f'{STATUS_ZH.get(k, k)} {v}' for k, v in sorted(c.items(), key=lambda kv: kv[0] != 'active'))

        o.write(clip(f'共 {len(lessons)} 條（{summary(lessons) or "空"}）· 人工回饋 {len(snap.get("feedback", []))} 筆 · '
                     f'{source}', width), 'dim')
        if mem:
            o.write(clip(f'研究記憶：上一份報告的發現 {mem["findings"]} 條 · 讀過的站內頁 {mem["pages"]} 頁 · '
                         f'看過但沒讀的站內連結 {mem["unread"]} 個 · 上次的未知項 {mem["unknowns"]} 項', width), 'bgreen')
        rule_rows = wrap(self.LEDGER_RULE, width)
        # Rows left for lessons: pane height minus title (and banner), [1/5] rule, summary, memory line, rule text, the
        # caller's trailing lines and the cursor row after the last newline.
        room = height - (2 if self.a.banner else 1) - 2 - (1 if mem else 0) - len(rule_rows) - after_rows - 1
        if not lessons:
            o.write('帳本是空的：這是第一次處理這個工作，沒有可用經驗。', 'yellow')
        order = sorted(lessons, key=lambda x: (x.get('status') != 'active', x.get('status') != 'candidate', x.get('kind', '')))
        shown = order if len(order) <= room else order[:max(0, room - 1)]
        for x in shown:
            status = STATUS_ZH.get(x.get('status'), x.get('status'))
            style = 'green' if x.get('status') == 'active' else ('yellow' if x.get('status') == 'candidate' else 'dim')
            extra = []
            if x.get('support_runs'):
                extra.append(f'支持 {x["support_runs"]} run')
            if x.get('expires') and x.get('status') in ('active', 'candidate'):
                extra.append('效期至 ' + x['expires'][5:10])
            # The v0.6 review record names the reviewer with an internal role word; the screen says who wrote it.
            text = ' · '.join(extra + [decode_urls(x.get('statement') or x.get('key', '')).replace('總控Claude', 'Claude')])
            head = pad(status, 9) + pad(x.get('kind', '?'), 16) + x['id'][:6] + '  '
            o.write(o.paint(head, style) + clip(text, width - text_width(head)))
        if len(shown) < len(order):
            rest = order[len(shown):]
            o.write(f'另 {len(rest)} 條（{summary(rest)}）未列出；完整內容見來源帳本', 'dim')
        for row in rule_rows:
            o.write(row, 'dim')

    def header(self):
        title = 'Hermes 研究即時檢視器（唯讀）· 資料：research.sqlite events ＋ Hermes agent.log'
        self.out.write(clip(title, self.out.size()[0] - 1), 'bold')
        if self.a.banner:
            self.out.write(clip(self.a.banner, self.out.size()[0] - 1), 'byellow')

    # section 2-3: events
    def on_event(self, db, kind, d, when=None):
        o = self.out
        if kind == 'start':
            self.cfg = d
            self.host = urlsplit(d.get('target', '')).hostname
            self.t_start = when if when is not None else self.now()
            o.write()
            o.rule('[2/5] 自主研究與工具使用：Hermes 每一步（控制器逐筆寫入）', 'bcyan')
            lim = d.get('limits') or {}
            learn = '開（完成後由控制器學習）' if d.get('learning') else '關（凍結帳本）'
            o.block(f'run {self.rid[:8]} · 模式 {d.get("mode")} · 學習 {learn} · 目標 {d.get("target")} · 關鍵字 '
                    + '、'.join(d.get('keywords') or self.keywords), 'dim')
            offpage = f' · 站外頁 {lim["offpage"]} 頁' if lim.get('offpage') is not None else ''
            o.block(f'預算：HTTP {lim.get("requests")} 次 · 工具呼叫 {lim.get("calls")} 次 · 搜尋 5 次{offpage} · '
                    f'{lim.get("seconds")} 秒；只讀允許的 host，遵守 robots.txt', 'dim')
            if d.get('required_sections'):
                o.block('報告必須包含的段落：' + '、'.join(d['required_sections']) + '（缺段落時控制器退回報告）', 'dim')
            return
        if kind == 'tool_call':
            self.tool_call(db, d, when)
        elif kind == 'request':
            if d.get('actor') == 'controller' and not self.presented:
                pass  # shown with its response
        elif kind == 'response':
            self.response(db, d, when)
        elif kind == 'extracted':
            self.extracted(db, d, when)
        elif kind == 'search_request':
            pass
        elif kind == 'search_response':
            self.search_response(db, d)
        elif kind == 'lessons_presented':
            self.lessons_presented(d, when)
        elif kind == 'memory_presented':
            self.memory_presented(db, d, when)
        elif kind == 'tool_error':
            self.tool_error(d)
        elif kind == 'report':
            self.report_event(db, d)
        elif kind == 'offpage':
            self.sub(f'站外頁訊號：連到目標網站 {d.get("links_to_target", 0)} 次 · 提及目標 {d.get("host_mentions", 0)} 次'
                     '（只代表這一頁，不是完整 backlinks）', 'green', 2)
        elif kind == 'learning':
            self.learning = d
        elif kind == 'proxy_dns':
            if not self.proxy_note:
                self.note('DNS 由設定的 HTTPS proxy 解析（只連允許清單內的 host）', 'dim')
                self.proxy_note = True
        else:
            self.line(clip(json.dumps(d, ensure_ascii=False), 200), 'dim', when, f'[{kind}] ', 'dim')

    def tool_call(self, db, d, when):
        o = self.out
        name, args = d.get('name'), d.get('args') or {}
        self.calls += 1
        self.call_names.append(name)
        n = f'#{self.calls}'
        if name == 'research_fetch':
            url = args.get('url', '')
            self.last_fetch = url
            self.line(readable_url(url, self.host), None, when, f'{n} research_fetch ', 'bcyan')
            if args.get('purpose'):
                o.block('目的：' + args['purpose'], 'white', prefix=' ' * 10, first=' ' * 8 + '  ', max_lines=2)
            self.lesson_match_url(url)
            if unquote(url).rstrip('/').casefold() in self.memory_candidates:
                self.note('這是研究記憶列出、之前沒讀過的站內頁', 'yellow')
        elif name == 'research_offpage':
            url = args.get('url', '')
            self.last_fetch = url
            mention = f'（找提及「{args["mention"]}」）' if args.get('mention') else ''
            self.line(readable_url(url) + mention, None, when, f'{n} research_offpage ', 'bmagenta')
            if args.get('purpose'):
                o.block('目的：' + args['purpose'], 'white', prefix=' ' * 10, first=' ' * 8 + '  ', max_lines=2)
        elif name == 'research_search':
            q = args.get('query', '')
            self.line(q, None, when, f'{n} research_search ', 'bmagenta')
            self.lesson_match_query(q)
        elif name == 'research_evidence':
            r = self.evidence_row(db, args.get('evidence_id'))
            what = readable_url(r['url'], self.host) if r else str(args.get('evidence_id'))[:8]
            q = f'，在其中找「{args["query"]}」' if args.get('query') else ''
            self.line(f'回查已存證據 {what}{q}', None, when, f'{n} research_evidence ', 'bcyan')
            used = False
            for lesson in self.presented:
                if (lesson.get('verification') or {}).get('evidence_id') == args.get('evidence_id'):
                    self.note(f'直接使用控制器本輪重抓確認的證據（lesson {lesson["id"][:6]}），不必再抓一次', 'yellow')
                    used = True
            if not used and args.get('evidence_id') in self.memory_eids:
                self.note('讀研究記憶的發現所在頁：控制器本輪剛重抓，頁面沒變', 'yellow')
            info = self.info(db, args.get('evidence_id'))
            for k in self.proj.hits(info, self.keywords, self.host):
                self.first_hit(k)
        elif name == 'research_status':
            self.line('查看剩餘預算與帳本 lessons', None, when, f'{n} research_status ', 'bcyan')
        elif name == 'research_finish':
            if not self.finish_seen:
                self.finish_seen = True
                o.write()
                o.rule('[3/5] 依證據收斂：提交報告，控制器逐項核對引用（Evidence-based Decision）', 'bcyan')
            rep = args.get('report') or {}
            claims = [c for c in rep.get('claims') or [] if isinstance(c, dict)]
            kinds = {k: sum(c.get('kind') == k for c in claims) for k in KIND_ZH}
            self.line(f'提交報告：{len(claims)} 項主張（觀察 {kinds["observation"]} · 推論 {kinds["inference"]} · '
                      f'未知 {kinds["unknown"]}）、{len(rep.get("actions") or [])} 項行動、{len(rep.get("unknowns") or [])} 項待查',
                      None, when, f'{n} research_finish ', 'bcyan')
        else:
            self.line(clip(json.dumps(args, ensure_ascii=False), 90), None, when, f'{n} {name} ', 'bcyan')

    def lesson_match_url(self, url):
        for lesson in self.presented:
            row = self.ledger_rows.get(lesson.get('id'), {})
            target = (row.get('data') or {}).get('target_url')
            if target and unquote(target).rstrip('/').casefold() == unquote(url).rstrip('/').casefold():
                v = lesson.get('verification') or {}
                again = '；控制器本輪已重抓並交出 evidence_id，這次是再抓一次' if v.get('evidence_id') else ''
                self.note(f'這是帳本 lesson {lesson["id"][:6]} 記載的目標頁（{lesson.get("key")}）{again}', 'yellow')

    def lesson_match_query(self, q):
        for lesson in self.presented:
            key = lesson.get('key', '')
            if key.endswith('|site_operator'):
                where = '本站' if lesson.get('applies') == 'this_host' else '其他站（' + str(lesson.get('applies')) + '）'
                if 'site:' in q.casefold():
                    self.note(f'仍使用 site:；帳本 lesson {lesson["id"][:6]} 記錄 site: 查詢在{where}多次無結果', 'yellow')
                elif not self.once('no_site'):
                    self.note(f'未使用 site:（帳本 lesson {lesson["id"][:6]} 記錄 site: 查詢在{where}多次無結果）', 'dim', 1)

    def response(self, db, d, when):
        status = d.get('status')
        actor = d.get('actor', 'model')
        url = d.get('url', '')
        is_robots = url.endswith('/robots.txt')
        if actor == 'controller':
            if is_robots:
                self.line(f'讀 robots.txt → HTTP {status}', 'dim', when, '控制器 ', 'yellow')
            elif status != 200:
                self.line(f'重抓帳本目標頁 {readable_url(url, self.host)} → HTTP {status}', None, when, '控制器 ', 'yellow')
            return
        if is_robots and self.last_fetch and not self.last_fetch.endswith('/robots.txt'):
            self.sub(f'先依規則讀 robots.txt → HTTP {status}', 'dim')
            return
        if status in (301, 302, 303, 307, 308):
            self.sub(f'HTTP {status} 轉址 → {readable_url((d.get("headers") or {}).get("location", "?"), self.host)}', 'yellow')
        elif status != 200:
            self.sub(f'HTTP {status}（錯誤頁不能當內容證據）', 'red')

    def extracted(self, db, d, when):
        info = self.info(db, d.get('evidence_id')) or {}
        r = self.evidence_row(db, d.get('evidence_id'))
        url = r['url'] if r else ''
        if d.get('actor') == 'controller':
            if 'research memory' in (d.get('purpose') or ''):
                self.line(f'重抓研究記憶的頁面 {readable_url(url, self.host)} → HTTP 200', 'dim', when, '控制器 ', 'yellow')
                return
            ok = self.proj.hits(info, self.keywords, self.host)
            verdict = ('符合「' + '」「'.join(ok) + '」目標頁') if ok else '不符合關鍵字頁'
            self.line(f'重抓帳本目標頁 {readable_url(url, self.host)} → HTTP 200，{verdict}', None, when, '控制器 ', 'yellow')
            return
        kind, links = d.get('kind'), d.get('links_count', 0)
        if kind == 'html':
            title = clip(info.get('title', ''), 46)
            self.sub(f'HTTP 200 · HTML · {links} 個連結 · title「{title}」', 'green', 2)
            extra = self.page_extras(r)
            if extra:
                self.sub(extra, 'dim', 2)
            for k in self.proj.hits(info, self.keywords, self.host):
                self.first_hit(k)
        elif kind == 'sitemap':
            self.sub(f'HTTP 200 · sitemap · 列出 {links} 個網址', 'green')
        else:
            self.sub(f'HTTP 200 · {kind} · {links} 個連結', 'green')

    def page_extras(self, r):
        """Structured data and image links of a stored page, as the v0.9 tools pass them to the model."""
        if not r or not self.proj.html:
            return ''
        try:
            h = self.proj.html(r['url'])
            h.feed((self.root / r['path']).read_bytes().decode('utf-8', 'replace'))
            sd = self.proj.structured_data(h.jsonld)['objects']
            imgs, _ = self.proj.image_links(h, lambda host: bool(self.host) and (host == self.host or host.endswith('.' + self.host)))
        except Exception:
            return ''
        parts = []
        if sd:
            names = []
            for x in sd:
                n = x['type'][0] + (f'（{x["faq_questions"]} 題）' if 'faq_questions' in x else '')
                if n not in names:
                    names.append(n)
            parts.append('結構化資料：' + '、'.join(names[:5]))
        ext = [x for x in imgs if not x['internal']]
        if ext:
            x = ext[0]
            rel = f' {"/".join(x["rel"])}' if x['rel'] else ''
            parts.append(f'圖片連結：「{x["alt"] or x["file"]}」→ {x["host"]}{rel}' + (f' 等 {len(ext)} 個' if len(ext) > 1 else ''))
        return ' · '.join(parts)

    def memory_presented(self, db, d, when):
        findings = d.get('findings') or []
        self.memory_eids = {e: f['id'] for f in findings for e in f.get('evidence_ids') or []}
        cands = d.get('candidates') or []
        self.memory_candidates = {unquote(u).rstrip('/').casefold() for u in cands}
        self.line(f'把研究記憶交給模型：仍成立的發現 {len(findings)} 條（頁面本輪重抓沒變，附本輪證據編號）· '
                  f'待重讀 {len(d.get("recheck") or [])} · 撤銷 {len(d.get("revoked") or [])} · 沒讀過的站內頁 {len(cands)} · '
                  f'上次的未知項 {len(d.get("unknowns") or [])}', 'yellow', when, '控制器 ', 'yellow')
        width = self.out.size()[0] - 12
        ids = [f['id'] for f in findings]
        text = {}
        if ids:
            text = {r['id']: r['statement'] for r in db.execute(
                f'SELECT id,statement FROM lessons WHERE id IN ({",".join("?" * len(ids))})', ids)}
        for f in findings[:3]:
            self.out.write(' ' * 10 + self.out.paint(clip('發現 ' + decode_urls(text.get(f['id'], f['id'])), width), 'green'))
        if len(findings) > 3:
            self.out.write(' ' * 10 + self.out.paint(f'另 {len(findings) - 3} 條發現', 'dim'))
        if cands:
            self.out.write(' ' * 10 + self.out.paint(clip('沒讀過：' + '、'.join(readable_url(u, self.host) for u in cands[:4])
                                                          + (f' 等 {len(cands)} 頁' if len(cands) > 4 else ''), width), 'cyan'))
        texts = []
        try:
            cur = db.execute('SELECT created FROM runs WHERE id=?', (self.rid,)).fetchone()
            row = db.execute('SELECT o.run FROM open_unknowns o JOIN runs r ON r.id=o.run WHERE r.created<? '
                             'ORDER BY o.id DESC LIMIT 1', (cur['created'],)).fetchone() if cur else None
            if row:
                texts = [x for (x,) in db.execute('SELECT text FROM open_unknowns WHERE run=? ORDER BY position', (row[0],))]
        except sqlite3.Error:
            texts = []
        for i, x in enumerate(texts[:2], 1):
            self.out.write(' ' * 10 + self.out.paint(clip(f'未知 u{i}：' + x, width), 'dim'))

    def first_hit(self, k):
        if k in self.hit:
            return
        self.hit[k] = self.calls
        self.out.write(' ' * 8 + self.out.paint(f'* 讀到「{k}」目標頁（第 {self.calls} 次工具呼叫）', 'bgreen'))

    def search_response(self, db, d):
        outcome = d.get('outcome') or ('ok' if d.get('status') == 200 else 'error')
        info = self.info(db, d.get('evidence_id')) or {}
        hosts = []
        for u, _ in info.get('anchors') or []:
            h = urlsplit(u).hostname
            if h and h not in hosts:
                hosts.append(h)
        if outcome == 'ok':
            rows = [urlsplit(u).hostname or '' for u, _ in info.get('anchors') or []]
            own = sum(1 for h in rows if self.host and (h == self.host or h.endswith('.' + self.host)))
            split = f'（{self.host} 自身 {own} 筆、其他網域 {len(rows) - own} 筆）' if rows else ''
            self.sub(f'{d.get("result_count", len(hosts))} 筆索引摘要{split} · 網域：' + '、'.join(hosts[:5]), 'green', 2)
            if not self.once('snippet'):
                self.note('摘要不等於讀過原頁；站外網域只能經搜尋摘要觀察', 'dim', 1)
        elif outcome == 'no_results':
            self.sub('索引回報沒有結果（no_results）', 'yellow')
        else:
            self.sub('搜尋供應商錯誤或逾時（error，不算研究方法失敗）', 'red')

    def lessons_presented(self, d, when):
        self.presented = d.get('lessons') or []
        if self.cfg.get('mode') != 'memory':
            self.line(f'本 run 是 {self.cfg.get("mode")} 對照組：不提供 lessons', None, when, '控制器 ', 'yellow')
            return
        if not self.presented:
            self.line('帳本沒有適用本站的 lessons：模型從零開始研究', None, when, '控制器 ', 'yellow')
            return
        verified = [x for x in self.presented if x.get('verification')]
        ok = sum(1 for x in verified if (x.get('verification') or {}).get('result') == 'ok')
        self.line(f'把 {len(self.presented)} 條 lessons 交給模型'
                  + (f'（其中 {len(verified)} 條目標頁剛重抓，{ok} 條確認仍有效）' if verified else ''), 'yellow', when,
                  '控制器 ', 'yellow')
        for x in self.presented:
            v = x.get('verification') or {}
            tail = f' · 重抓 {v.get("result")}' if v else ''
            self.out.write(' ' * 10 + self.out.paint(clip(f'{x["id"][:6]} {x.get("key")} · {x.get("applies")}{tail}',
                                                          self.out.size()[0] - 12), 'dim'))

    def tool_error(self, d):
        err = str(d.get('error', ''))
        code = err.split(':')[0]
        why = self.proj.rules.get(code, '')
        gate = '' if d.get('call_logged', True) else '（閘門擋下，工具未執行）'
        if d.get('name') == 'research_finish':
            self.rejections.append(code)
            self.sub(f'控制器退回報告：{err}{gate}' + (f'；{why}' if why else '') + '。模型必須修正後重交', 'bred', 3)
        else:
            self.sub(f'控制器擋下 {d.get("name")}：{err}{gate}' + (f'；{why}' if why else ''), 'bred', 3)

    def report_event(self, db, rep):
        o = self.out
        self.report = rep
        o.write(' ' * 8 + o.paint('→ 控制器接受報告：結構正確、每項觀察與推論都引用本輪證據、非 200 來源只放 access 類。', 'bgreen'))
        o.block('（控制器只核對 ID、雜湊與結構；引用是否真的支持主張，另由不看分數的盲評檢查）', 'dim', prefix=' ' * 10)
        o.write(' ' * 8 + o.paint('每項主張引用的證據（都可回溯到本輪快照與 SHA-256）：', 'bold'))
        width = o.size()[0] - 1
        for i, c in enumerate([c for c in rep.get('claims') or [] if isinstance(c, dict)], 1):
            ids = c.get('evidence_ids') or []
            urls, snippets = [], 0
            for e in ids:
                r = self.evidence_row(db, e)
                if r and r['url'].startswith('search:'):
                    snippets += 1
                elif r:
                    urls.append(readable_url(r['url'], self.host))
            if snippets:
                urls.append(f'搜尋摘要 {snippets} 份')
            tag = KIND_ZH.get(c.get('kind'), c.get('kind'))
            sec = SECTION_ZH.get(c.get('section'), '') if 'section' in c else ''
            head = f'{i:>2} {tag}{"·" + sec if sec else ""} {c.get("topic", "")}：'
            src = f'{len(ids)} 份證據 ' + '、'.join(urls[:4]) + ('…' if len(urls) > 4 else '') if ids else '不需引用（未知）'
            o.write(' ' * 10 + o.paint(clip(head + src, width - 10), 'cyan'))
            o.write(' ' * 13 + clip(c.get('text', ''), width - 13))
            self.pace(self.a.pace)

    # closing pages
    def pace(self, seconds):
        if seconds > 0:
            time.sleep(seconds)

    def pages(self, marker_title, lines, pause):
        """Clear and print `lines` in screen-sized pages under one header, pausing between pages."""
        o = self.out
        cap = max(4, o.size()[1] - 2)
        while lines and not lines[-1][0].strip():
            lines = lines[:-1]  # a trailing spacer must not spill onto an otherwise empty page
        groups = []  # an item and its continuation lines stay on one page
        for line in lines:
            joins = len(line) > 2 and line[2] is True
            after_head = groups and len(groups[-1][-1]) > 2 and groups[-1][-1][2] == 'head'
            if groups and (joins or after_head):
                groups[-1].append(line)
            else:
                groups.append([line])
        chunks, cur = [], []
        for g in groups:
            if cur and len(cur) + len(g) > cap:
                chunks.append(cur)
                cur = []
            cur += g
        chunks = (chunks + [cur]) if cur or not chunks else chunks
        for i, chunk in enumerate(chunks):
            o.clear()
            o.rule(marker_title + ('' if i == 0 else f'（續 {i + 1}/{len(chunks)}）'), 'bcyan')
            for line in chunk[:cap]:
                o.write(line[0], line[1])
            self.pace(pause)

    def fmt(self, text, style=None, indent=0, max_lines=None, first=None, glue=False):
        """Wrapped page lines (text, style, continuation); `glue` keeps the item on the previous item's page."""
        width = self.out.size()[0] - 1 - indent
        rows = wrap(text, width - (text_width(first) if first else 0), max_lines)
        lead = first or ''
        out = []
        for i, row in enumerate(rows):
            pad = ' ' * indent + (lead if i == 0 else ' ' * text_width(lead))
            out.append((pad + row, style, i > 0 or glue))
        return out

    def closing(self, db):
        rid = self.rid
        outcome = self.read_json(self.root / f'{rid}-outcome.json') or {}
        hermes = self.read_json(self.root / f'{rid}-hermes.json') or {}
        o = self.out
        o.write()
        o.write(' ' * 8 + o.paint(f'run 結束：state={outcome.get("state")} · exit={outcome.get("exit_code")} · '
                                  f'成功 API 呼叫 {outcome.get("successful_api_calls")}', 'bold'))
        self.pace(self.a.page_pause / 2)
        self.commentary_page(hermes)
        self.analysis_pages(hermes)
        self.learning_pages(db)
        o.write()
        o.write('== 檢視器結束（END）==', 'bold')

    @staticmethod
    def read_json(path):
        try:
            return json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None

    def commentary_page(self, hermes):
        lines, turn = [], 0
        for m in hermes.get('messages') or []:
            if m.get('role') != 'assistant':
                continue
            turn += 1
            texts = [c.get('text', '') for it in m.get('codex_message_items') or []
                     if it.get('type') == 'message' and it.get('phase') == 'commentary' for c in it.get('content') or []]
            if not texts and m.get('content') and m.get('tool_calls'):
                texts = [m['content']]
            for t in texts:
                t = re.sub(r'[*`#]', '', t)
                lines += self.fmt(t, None, 2, 5, f'第 {turn} 回合：')
                lines.append(('', None))
        if not lines:
            return
        lines.insert(0, ('模型在研究途中寫下的假設與修正（commentary；取自 hermes.json，run 結束後才寫出）', 'dim'))
        self.pages('[3/5] 依證據收斂：模型怎麼形成假設、找反證、修正判斷', lines, self.a.page_pause)

    def analysis_pages(self, hermes):
        rep = self.report or {}
        claims = [c for c in rep.get('claims') or [] if isinstance(c, dict)]
        final = hermes.get('final_response') or ''
        lines = []
        if not self.report:
            lines.append(('本 run 沒有被控制器接受的報告；以下只有模型的最終回覆（若有）。這是研究結果，不重跑。', 'bred'))
        concl = re.search(r'##\s*結論\s*\n(.*?)(?=\n##\s|\Z)', final, re.S)
        if concl or final:
            text = re.sub(r'[*`>|#]', '', (concl.group(1) if concl else final)).strip()
            lines.append(('結論（模型最終回覆）', 'bold', 'head'))
            lines += self.fmt(text, 'white', 2, 5)
            lines.append(('', None))
        known = [c for c in claims if c.get('kind') != 'unknown']
        by_field = any('section' in c for c in claims)
        groups = {s: [c for c in known if self.section(c) == s] for s in ('on_page', 'off_page', 'other')}
        rule = '依模型標的 section' if by_field else '依 topic 名稱分組；舊版報告沒有 section 欄位'
        heads = dict(on_page='On-page 發現（競爭者站內）', off_page='Off-page 發現（站外頁、索引與連結）', other='其他發現')
        for s in ('on_page', 'off_page', 'other'):
            if s == 'other' and not groups[s]:
                continue
            lines.append((f'{heads[s]}：{len(groups[s])} 項' + (f'（{rule}）' if s == 'on_page' else ''), 'bold', 'head'))
            for c in groups[s]:
                lines += self.fmt(c.get('text', ''), None, 2, 2, f'[{KIND_ZH.get(c.get("kind"))}·{c.get("topic", "")}] ')
        if not groups['off_page']:
            lines.append(('  本輪沒有 off-page 主張；相關缺口見下方「仍未知」。', 'yellow'))
        unknowns = [str(u) for u in rep.get('unknowns') or []] + [c.get('text', '') for c in claims if c.get('kind') == 'unknown']
        if unknowns:
            lines.append((f'仍未知（{len(unknowns)} 項，報告明列）', 'bold', 'head'))
            for u in unknowns:
                lines += self.fmt(u, 'dim', 2, 1, '- ')
        self.pages('[4/5] 最終競爭分析：競爭者做了什麼、我們還不知道什麼', lines, self.a.page_pause)
        acts = []
        for i, a in enumerate([a for a in rep.get('actions') or [] if isinstance(a, dict)], 1):
            acts += self.fmt(a.get('action', ''), 'white', 2, 3, f'{i}. ')
            acts += self.fmt('理由：' + str(a.get('reason', '')), 'dim', 5, 2, glue=True)
        if acts:
            acts.insert(0, ('以下是給「我們自己的網站」評估的行動，不是對競爭者的修改建議。', 'dim'))
            self.pages('[4/5] 行動建議：值得優先採取的競爭行動', acts, self.a.page_pause)

    def section(self, claim):
        """Claim section as the controller normalises it; topic regex only for reports without a section field."""
        if 'section' in claim:
            s = str(claim.get('section') or 'other').strip().lower().replace('-', '_').replace(' ', '_')
            return {'onpage': 'on_page', 'offpage': 'off_page'}.get(s, s if s in SECTION_ZH else 'other')
        return 'off_page' if self.offpage.search(str(claim.get('topic', ''))) else 'on_page'

    def learning_pages(self, db):
        lines = []
        score = None
        if self.proj.score_run:
            try:
                score = self.proj.score_run(self.root, self.rid, tuple(self.keywords))
            except Exception as exc:
                lines.append((f'score_run 無法計算：{type(exc).__name__}', 'red'))
        if score:
            lines.append(('score_run（src/scoring.py，只讀 research.sqlite 與快照）', 'dim'))
            tp = score.get('target_pages') or {}
            both = '是' if score.get('both_target_pages_read') else '否'
            where = '；'.join(f'{k} 第 {v["call"]} 次' for k, v in tp.items() if v) or '都沒讀到'
            lines.append((f'兩個目標詞頁都讀到：{both}（{where}）', 'bgreen' if score.get('both_target_pages_read') else 'bred'))
            lines.append((f'首次讀到目標頁前的工具呼叫：{score.get("calls_before_first_hit")} 次 · '
                          f'兩頁都讀到：第 {score.get("calls_until_both_hit")} 次 · 工具呼叫共 {score.get("tool_calls")} 次', None))
            fk = score.get('failed_search_kinds') or {}
            lines.append((f'搜尋 {score.get("searches")} 次，失敗 {score.get("failed_searches")}（無結果 {fk.get("no_results", 0)}、'
                          f'供應商錯誤 {fk.get("error", 0)}）· HTTP {score.get("http_requests")} 次（控制器 '
                          f'{score.get("http_requests_controller")}）', None))
            rej = score.get('finish_rejections') or []
            lines.append((f'報告提交 {score.get("finish_attempts")} 次' + (f'，被退回 {len(rej)} 次：{"、".join(map(str, rej))}' if rej else '，第一次就被接受')
                          + f' · 主張 {score.get("claims")} · 行動 {score.get("actions")}', None))
            tok = score.get('tokens') or {}
            lines.append((f'交給模型的 lessons {score.get("lessons_presented")} 條，其中已失效 {score.get("stale_lessons_presented")} 條 · '
                          f'tokens {tok.get("total") or 0:,}（API 呼叫 {tok.get("api_calls")} 次）', None))
            if 'sitemap_reads' in score or 'refetched_verified_pages' in score:
                lines.append((f'sitemap 讀取 {score.get("sitemap_reads")} 次 · 重抓控制器已確認的頁面 '
                              f'{score.get("refetched_verified_pages")} 次（lesson 改寫後想減少的兩種成本）', None))
            off = score.get('offpage')
            if isinstance(off, dict):
                sec = score.get('sections') or {}
                lines.append((f'報告段落：站內 {sec.get("on_page", 0)} · 站外 {sec.get("off_page", 0)} · 其他 {sec.get("other", 0)}；'
                              f'站外主張 {off.get("claims")}（觀察 {off.get("observation")} · 推論 {off.get("inference")} · '
                              f'未知 {off.get("unknown")}）', None))
                lines.append((f'讀站外頁 {off.get("pages_fetched")} 頁，其中 {off.get("pages_linking_to_target")} 頁連到目標；'
                              f'有站外證據的站外觀察 {off.get("known_external")} 項，其中連結已核對 {off.get("known_link_verified")} 項 · '
                              f'站外讀取規則違反 {len(score.get("offpage_policy_violations") or [])} 次', None))
        compare = []
        for spec in self.a.compare or []:
            label, _, path = spec.partition('=')
            s = self.read_json(path)
            if s:
                compare.append((label, s))
        if compare and score:
            compare.append(('本 run', score))
            lines.append(('', None))
            lines.append(('與先前 run 對照（先前 run 取自各自的分數檔）', 'bold', 'head'))
            cols = (26, 16, 12, 10, 11)
            head = ('run', '首次命中前呼叫', '兩頁都讀到', '失敗搜尋', '成本')
            lines.append(('  ' + ''.join(pad(h, w) for h, w in zip(head, cols)), 'dim', True))
            for label, s in compare:
                tok = (s.get('tokens') or {}).get('cost') or (s.get('tokens') or {}).get('total') or 0
                row = (clip(label, 25), str(s.get('calls_before_first_hit')), '是' if s.get('both_target_pages_read') else '否',
                       f'{s.get("failed_searches")}/{s.get("searches")}', f'{tok:,}')
                lines.append(('  ' + ''.join(pad(v, w) for v, w in zip(row, cols)), 'bold' if label == '本 run' else None, True))
        if lines:
            self.pages('[5/5] 學習與評估：這次表現如何（score_run）', lines, self.a.page_pause)
        self.pages('[5/5] 學習與評估：run 後帳本變化', self.ledger_change(db), self.a.page_pause)
        self.handoff_pages()

    def ledger_change(self, db):
        lines = []
        after = load_ledger_json(self.a.ledger_after) if self.a.ledger_after else ledger_snapshot(db)
        before = {x['id']: x for x in (self.before or {}).get('lessons', [])}
        now = {x['id']: x for x in after.get('lessons', [])}
        if not self.cfg.get('learning'):
            lines.append(('本 run 以 --no-learn 凍結帳本：控制器不從本 run 學習。', 'yellow'))
        all_changes = (self.learning or {}).get('changes') or []
        changes = [c for c in all_changes if 'lesson' in c]
        memory = {k: v for c in all_changes if 'lesson' not in c for k, v in c.items()}
        new_findings = [x for x in now.values() if x.get('kind') == 'finding' and (x.get('data') or {}).get('run') == self.rid]
        if memory or new_findings:
            replaced = sum(1 for lid, x in now.items() if x.get('kind') == 'finding' and x.get('status') == 'superseded'
                           and (before.get(lid) or {}).get('status') in ('candidate', 'active'))
            lines.append((f'研究記憶（研究結束後由控制器寫入）：新增 {len(new_findings)} 條發現（候選，下次開跑前重抓確認）、'
                          f'取代上一份報告的 {replaced} 條；記下這次讀的站內頁 {memory.get("pages", 0)} 頁、'
                          f'報告的未知項 {memory.get("unknowns", 0)} 項', 'bold', 'head'))
            for x in new_findings:
                lines += self.fmt(decode_urls(x.get('statement') or ''), 'green', 2, 1, '新發現 ')
            lines.append(('', None))
        if changes:
            lines.append((f'控制器學習（learning 事件，{len(changes)} 項）：', 'bold'))
            for c in changes:
                lines += self.fmt(f'{c.get("key")} → {STATUS_ZH.get(c.get("status"), c.get("status"))}：{c.get("reason")}',
                                  'green', 2, 2, f'{str(c.get("lesson"))[:6]} ')
        diffs = []
        for lid, x in now.items():
            if x.get('kind') == 'finding':
                continue  # summarized above
            old = before.get(lid)
            if not old:
                diffs.append((f'新增 {lid[:6]} {x.get("key")}（{STATUS_ZH.get(x.get("status"), x.get("status"))}）', 'green'))
            elif old.get('status') != x.get('status'):
                diffs.append((f'{lid[:6]} {x.get("key")}：{STATUS_ZH.get(old.get("status"))} → {STATUS_ZH.get(x.get("status"), x.get("status"))}', 'yellow'))
            elif old.get('expires') != x.get('expires') and x.get('expires'):
                diffs.append((f'{lid[:6]} {x.get("key")}：效期更新至 {x["expires"][:10]}', 'dim'))
            elif None not in (old.get('support_runs'), x.get('support_runs')) and old['support_runs'] != x['support_runs']:
                diffs.append((f'{lid[:6]} {x.get("key")}：支持 run {old.get("support_runs") or 0} → {x.get("support_runs") or 0}', 'dim'))
        for lid in before:
            if lid not in now and before[lid].get('kind') != 'finding':
                diffs.append((f'{lid[:6]} 已不在帳本', 'red'))
        lines.append(('帳本前後比對（lessons 表）：', 'bold'))
        if diffs:
            for t, s in diffs:
                lines += self.fmt(t, s, 2, 2)
        else:
            lines.append(('  沒有任何 lesson 新增、改狀態或改效期。', None))
        plain = [x for x in now.values() if x.get('kind') != 'finding']
        active = [x for x in plain if x.get('status') == 'active']
        lines.append((f'run 後：{len(plain)} 條 lessons，使用中 {len(active)} 條。下一個 run 開始時，discovery 類與研究記憶的發現會先被控制器重抓確認。', 'dim'))
        lines.append((self.a.proof, 'dim'))
        return lines

    def handoff_pages(self):
        if not self.proj.handoff or not self.rid:
            return
        try:
            q = self.proj.handoff.build_queue(self.db_path, self.rid, self.root)
        except Exception as exc:
            self.out.write(f'handoff_queue 無法產生：{type(exc).__name__}', 'red')
            return
        lines = [('研究結束後，程式從這次的執行紀錄列出要人決定的事；Agent 沒有能自己處理這些事的工具。', 'dim')]
        for x in q['items']:
            style = 'byellow' if x['priority'] == 'decide' else ('yellow' if x['priority'] == 'review' else 'dim')
            lines += self.fmt(x['title'], style, 0, 1, f'[{PRIORITY_ZH.get(x["priority"], x["priority"])}] ')
            if x['priority'] != 'info':
                lines += self.fmt(x['decision'], None, 4, 1, glue=True)
        self.pages('[5/5] 交還人類：研究後要人決定的事（scripts/handoff_queue.py）', lines, self.a.page_pause)

    # runtime loops
    def run(self):
        if self.a.replay:
            return self.replay()
        return self.live()

    def live(self):
        o = self.out
        o.clear()
        self.header()
        launch = datetime.now(timezone.utc).isoformat()
        deadline = time.monotonic() + self.a.max_wait
        log = LogFollower(self.a.hermes_log, from_end=True) if self.a.hermes_log else None
        if self.a.ledger_db and Path(self.a.ledger_db).exists():
            src = connect_ro(self.a.ledger_db)
            self.before = ledger_snapshot(src)
            self.before['memory'] = memory_snapshot(src)
            src.close()
            self.show_ledger(self.before, self.a.ledger_db + '（本 run 由此複製）')
        else:
            o.write('等待 research.sqlite……', 'dim')
        o.write()
        o.write('等待新的 run 開始（執行命令在最下方窗格）……', 'dim')
        db, last_id, sizes, pending = None, 0, [], []
        while time.monotonic() < deadline:
            if db is None and self.db_path.exists():
                # The evaluation may be copying a ledger into this file; read it only once its size is stable.
                sizes = (sizes + [self.db_path.stat().st_size])[-3:]
                if len(sizes) == 3 and len(set(sizes)) == 1:
                    try:
                        db = connect_ro(self.db_path)
                        if self.before is None:
                            self.before = ledger_snapshot(db)
                            self.show_ledger(self.before, str(self.db_path))
                            o.write()
                            o.write('等待新的 run 開始（執行命令在最下方窗格）……', 'dim')
                    except sqlite3.Error:
                        db = None
            if db is not None:
                try:
                    if not self.rid and table_exists(db, 'runs'):
                        # A run created after launch; runs copied with a ledger are older.
                        row = db.execute('SELECT id FROM runs WHERE created>=? ORDER BY created LIMIT 1', (launch,)).fetchone()
                        if row:
                            self.rid = row['id']
                    if self.rid:
                        # Model lines go before the tool events they triggered, but never before the run header.
                        pending += log.poll() if log else []
                        if self.t_start is not None:
                            for item in pending:
                                self.on_log(item)
                            pending = []
                        finished = (self.root / f'{self.rid}-outcome.json').exists()
                        for r in db.execute('SELECT id,kind,data FROM events WHERE run=? AND id>? ORDER BY id',
                                            (self.rid, last_id)).fetchall():
                            last_id = r['id']
                            self.on_event(db, r['kind'], json.loads(r['data']))
                            if r['kind'] == 'start':
                                for item in pending:
                                    self.on_log(item)
                                pending = []
                        if finished:
                            if log:
                                for item in log.poll():
                                    self.on_log(item)
                            self.closing(db)
                            return 0
                except sqlite3.OperationalError:
                    pass  # writer holds the lock; read again on the next tick
            time.sleep(self.a.interval)
        o.write('等待逾時：沒有看到 run 結束（outcome 檔）', 'bred')
        return 1

    def on_log(self, item):
        kind, data = item
        if kind == 'api':
            self.api_tokens += data['total']
            self.out.write(self.out.paint(f'{self.stamp(data.get("mono"))}  [模型] 第 {data["n"]} 回合 {data["latency"]}s · '
                                          f'輸入 {data["inp"]:,} / 輸出 {data["out"]:,} tokens · 累計 {self.api_tokens:,}', 'blue'))
        elif kind == 'turn_end':
            self.out.write(self.out.paint(f'{self.stamp(data.get("mono"))}  [模型] 對話結束：{data["reason"]}', 'blue'))

    def replay(self):
        a = self.a
        if a.steps and a.step:
            entry = next(x for x in json.loads(Path(a.steps).read_text(encoding='utf-8'))
                         if x['step'] == a.step and x.get('run_id'))
            self.rid = self.rid or entry['run_id']
            t0, t_end = parse_time(entry['started']), parse_time(entry['ended'])
        else:
            t0 = t_end = None
        db = connect_ro(self.db_path)
        rows = [(r['id'], r['kind'], json.loads(r['data'])) for r in
                db.execute('SELECT id,kind,data FROM events WHERE run=? ORDER BY id', (self.rid,))]
        tz = local_tz(a.log_utc_offset)
        log_items = read_log_window(a.hermes_log, t0, t_end, tz) if a.hermes_log and t0 else []
        times = event_times(rows, log_items, t0)
        t0 = t0 or min(t for t in times if t)
        t_end = t_end or max(t for t in times if t)
        self.before = load_ledger_json(a.ledger_before) if a.ledger_before else ledger_snapshot(db)
        self.before.setdefault('memory', memory_snapshot(db))
        self.replay_clock = 0.0
        self.out.clear()
        self.show_ledger(self.before, a.ledger_before or str(self.db_path), after_rows=0)
        time.sleep(a.pre)
        items = [((t - t0).total_seconds(), 1, ('event', r)) for t, r in zip(times, rows)]
        items += [((x['time'] - t0).total_seconds() - 0.05, 0, ('log', x)) for x in log_items if x['kind'] in ('api', 'turn_end')]
        items.sort(key=lambda x: (x[0], x[1]))
        start = time.monotonic()
        for offset, _, (what, payload) in items:
            wait = start + max(0.0, offset) / a.speed - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.replay_clock = max(0.0, offset)
            if what == 'event':
                eid, kind, d = payload
                if kind == 'start':
                    self.on_event(db, kind, d, when=0.0)
                    self.t_start = 0.0
                else:
                    self.on_event(db, kind, d, when=self.replay_clock)
            else:
                payload = dict(payload, mono=self.replay_clock)
                self.on_log((payload['kind'], payload))
        wait = start + (t_end - t0).total_seconds() / a.speed - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.replay_clock = (t_end - t0).total_seconds()
        self.closing(db)
        return 0


def read_log_window(path, t0, t_end, tz, margin=5.0):
    """Parsed agent.log lines of the run's Hermes session inside [t0, t_end]."""
    out, session = [], None
    for raw in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        m = LOG_LINE.match(raw)
        if not m:
            continue
        when = log_time(m.group(1), m.group(2), tz)
        if (when - t0).total_seconds() < -margin or (when - t_end).total_seconds() > margin:
            continue
        tag, msg = m.group(4), m.group(6)
        if session is None and 'conversation turn: session=' in msg:
            session = tag
        if tag and session and tag != session:
            continue
        out.append(parse_log_message(when, m.group(3), tag, m.group(5), msg))
    return out


def parse_log_message(when, level, tag, logger, msg):
    item = dict(time=when, level=level, tag=tag, logger=logger, msg=msg, kind='other')
    m = API_CALL.search(msg)
    if m:
        item.update(kind='api', n=int(m.group(1)), inp=int(m.group(2)), out=int(m.group(3)), total=int(m.group(4)),
                    latency=m.group(5))
    m = TOOL_DONE.search(msg)
    if m:
        item.update(kind='tool_done', name=m.group(1) or m.group(2), duration=float(m.group(3)))
    if 'Turn ended: reason=' in msg:
        item.update(kind='turn_end', reason=msg.split('reason=', 1)[1].split(' ')[0])
    return item


def event_times(rows, log_items, t0=None):
    """Wall time per event: own timestamp when present; a tool call starts at its logged completion minus duration."""
    done = [x for x in log_items if x['kind'] == 'tool_done']
    used = [False] * len(done)
    times, last = [], None
    from datetime import timedelta
    for _, kind, d in rows:
        t = parse_time(d.get('time')) if isinstance(d, dict) else None
        if kind == 'start' and t is None:
            t = t0
        if kind == 'tool_call':
            for i, x in enumerate(done):
                if not used[i] and x['name'] == d.get('name'):
                    used[i] = True
                    t = x['time'] - timedelta(seconds=max(0.0, x['duration']))
                    break
        if t is None:
            t = last
        if last and t and t < last:
            t = last
        times.append(t)
        last = t or last
    first = next((t for t in times if t), None)
    return [t or first for t in times]


# Hermes log pane -----------------------------------------------------------------------------------------------
class LogFollower:
    def __init__(self, path, from_end=True):
        self.path = Path(path)
        self.pos = self.path.stat().st_size if (from_end and self.path.exists()) else 0
        self.buf = ''
        self.tz = local_tz(None)

    def lines(self):
        if not self.path.exists():
            return []
        size = self.path.stat().st_size
        if size < self.pos:
            self.pos = 0  # rotated
        with open(self.path, 'rb') as f:
            f.seek(self.pos)
            data = f.read()
        self.pos += len(data)
        self.buf += data.decode('utf-8', errors='replace')
        *done, self.buf = self.buf.split('\n')
        return done

    def poll(self):
        out = []
        for raw in self.lines():
            m = LOG_LINE.match(raw)
            if m:
                item = parse_log_message(log_time(m.group(1), m.group(2), self.tz), m.group(3), m.group(4), m.group(5), m.group(6))
                if item['kind'] in ('api', 'turn_end'):
                    out.append((item['kind'], dict(item, mono=time.monotonic())))
        return out


def format_log(raw, width, color):
    m = LOG_LINE.match(raw)
    if not m:
        return None
    level, logger, msg = m.group(3), m.group(5), m.group(6)
    if any(n in msg for n in LOG_NOISE):
        return None
    msg = re.sub(r'\bmodel=\S+ provider=\S+ ', '', msg)
    msg = re.sub(r' id=resp_\w+', '', msg)
    msg = re.sub(r' thread=\S+', '', msg)
    short = logger.split('.')[-1]
    text = f'{m.group(1)[11:]} {short:<17} {msg}'
    style = {'WARNING': 'yellow', 'ERROR': 'red'}.get(level)
    if 'API call #' in msg:
        style = 'blue'
    elif 'Turn ended' in msg:
        style = 'bgreen'
    lines = wrap(text, width - 1, 2)
    o = Out(color)
    return '\n'.join(o.paint(x, style) for x in lines)


def hermes_log(args):
    out = Out(not args.no_color)
    width = out.size()[0]
    if args.replay:
        tz = local_tz(args.log_utc_offset)
        if args.steps and args.step:
            entry = next(x for x in json.loads(Path(args.steps).read_text(encoding='utf-8')) if x['step'] == args.step)
            t0, t_end = parse_time(entry['started']), parse_time(entry['ended'])
        else:
            t0, t_end = parse_time(args.since), parse_time(args.until)
        session = None
        rows = []
        for raw in Path(args.log).read_text(encoding='utf-8', errors='replace').splitlines():
            m = LOG_LINE.match(raw)
            if not m:
                continue
            when = log_time(m.group(1), m.group(2), tz)
            if not (-5 <= (when - t0).total_seconds() <= (t_end - t0).total_seconds() + 5):
                continue
            if session is None and 'conversation turn: session=' in m.group(6):
                session = m.group(4)
            if m.group(4) and session and m.group(4) != session:
                continue
            rows.append(((when - t0).total_seconds(), raw))
        time.sleep(args.pre)
        start = time.monotonic()
        for offset, raw in rows:
            wait = start + max(0.0, offset) / args.speed - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            text = format_log(raw, width, not args.no_color)
            if text:
                sys.stdout.write(text + '\n')
                sys.stdout.flush()
        time.sleep(args.linger)
        return 0
    follower = LogFollower(args.log, from_end=True)
    out.write(f'tail {args.log}（只顯示新行；略去連線細節行）', 'dim')
    deadline = time.monotonic() + args.max_wait
    while time.monotonic() < deadline:
        for raw in follower.lines():
            text = format_log(raw, width, not args.no_color)
            if text:
                sys.stdout.write(text + '\n')
                sys.stdout.flush()
        time.sleep(0.2)
    return 0


def replay_console(args):
    out = Out(not args.no_color)
    entry = next(x for x in json.loads(Path(args.steps).read_text(encoding='utf-8')) if x['step'] == args.step)
    out.write(f'演練：不呼叫模型。以下是 {args.label} 已執行步驟 {args.step} 的原始命令與輸出。', 'byellow')
    time.sleep(args.pre)
    out.write('$ ' + ' '.join(shlex.quote(c) for c in entry['command']), 'bold')
    duration = (parse_time(entry['ended']) - parse_time(entry['started'])).total_seconds()
    time.sleep(duration / args.speed)
    text = Path(args.console).read_text(encoding='utf-8').split('\n--- stderr ---')[0].strip()
    out.write(text)
    out.write(f'[{args.step} 結束 exit={entry.get("exit_code")}]', 'bold')
    time.sleep(args.linger)
    return 0


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    e = sub.add_parser('events', help='controller events view')
    e.add_argument('--root', required=True, help='run root that holds research.sqlite')
    e.add_argument('--run-id', help='follow this run (default: the first run that starts after launch)')
    e.add_argument('--task-root', default=str(Path(__file__).resolve().parents[1]),
                   help='checkout whose src/ is imported read-only (use the WSL copy that runs the evaluation)')
    e.add_argument('--hermes-log', help='Hermes agent.log; adds one line per model API call')
    e.add_argument('--ledger-db', help='live: show this research.sqlite as the starting ledger (the copy source)')
    e.add_argument('--keyword', action='append')
    e.add_argument('--compare', action='append', help='LABEL=score.json from an earlier run, shown next to this run')
    e.add_argument('--offpage-topics', default=OFFPAGE_TOPICS, help='regex on claim topic for the off-page group')
    e.add_argument('--banner', help='line shown under the title, e.g. a rehearsal notice')
    e.add_argument('--proof', default='如何證明進步：判準先鎖定的評估比較帶經驗與不學習的兩組，判定與依據見各版的 VERDICT 或 RESULT。',
                   help='closing line on the ledger page: where the evaluation verdict is')
    e.add_argument('--page-pause', type=float, default=8.0, help='seconds each closing page stays on screen')
    e.add_argument('--pace', type=float, default=1.0, help='seconds between claim lines after the report')
    e.add_argument('--interval', type=float, default=0.3)
    e.add_argument('--max-wait', type=float, default=1800)
    e.add_argument('--no-color', action='store_true')
    e.add_argument('--replay', action='store_true', help='replay a finished run with its original pacing')
    e.add_argument('--steps', help='replay: steps.json that holds the run id and start/end times')
    e.add_argument('--step', help='replay: step name in steps.json')
    e.add_argument('--speed', type=float, default=1.0, help='replay speed factor')
    e.add_argument('--pre', type=float, default=10.0, help='replay: seconds the ledger stays before the run starts')
    e.add_argument('--ledger-before', help='replay: ledger export JSON before the run')
    e.add_argument('--ledger-after', help='replay: ledger export JSON after the run')
    e.add_argument('--log-utc-offset', type=float, help='hours; agent.log timestamps are local time (default: system)')
    h = sub.add_parser('hermes-log', help='formatted tail of Hermes agent.log')
    h.add_argument('--log', required=True)
    h.add_argument('--replay', action='store_true')
    h.add_argument('--steps')
    h.add_argument('--step')
    h.add_argument('--since')
    h.add_argument('--until')
    h.add_argument('--speed', type=float, default=1.0)
    h.add_argument('--pre', type=float, default=0.0)
    h.add_argument('--linger', type=float, default=600)
    h.add_argument('--max-wait', type=float, default=3600)
    h.add_argument('--log-utc-offset', type=float)
    h.add_argument('--no-color', action='store_true')
    c = sub.add_parser('replay-console', help='rehearsal: original command and console output of a finished step')
    c.add_argument('--steps', required=True)
    c.add_argument('--step', required=True)
    c.add_argument('--console', required=True)
    c.add_argument('--label', default='v0.6')
    c.add_argument('--speed', type=float, default=1.0)
    c.add_argument('--pre', type=float, default=0.0)
    c.add_argument('--linger', type=float, default=600)
    c.add_argument('--no-color', action='store_true')
    a = p.parse_args()
    try:
        if a.cmd == 'events':
            return EventsView(a).run()
        if a.cmd == 'hermes-log':
            return hermes_log(a)
        return replay_console(a)
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
