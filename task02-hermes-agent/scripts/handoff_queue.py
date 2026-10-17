"""Human handoff queue for one research run.

Lists what a person has to decide after the run, why the agent cannot decide it, where the evidence is, and the
commands that act on it. It reads research.sqlite read-only, plus the runner files next to it (<run>-outcome.json,
-preflight.json, -hermes.json, -review.json), and never changes the ledger; only the commands it prints do.

python scripts/handoff_queue.py RUN_ROOT_OR_SQLITE [--run RUN_ID_OR_PREFIX] [--out DIR] [--json] [--command-root PATH]

Without --out the Markdown goes to stdout (--json prints the JSON instead); --out writes <run>-handoff.md and
<run>-handoff.json. The default run is the latest one, including runs stopped before the controller started, which
exist only as runner files.
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse, hashlib, json, re, sqlite3, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.lessons import LABELS, RULES, norm_url
from src.runner_support import HERMES_WRITE_TOOLS

SEARCH_LIMIT = 5  # fixed in research_core.Research.search; the start event does not log it
CATEGORIES = {'preflight': '開跑前檢查', 'lesson_change': '經驗變動', 'lessons_in_use': '這次使用的經驗',
              'limit': '研究受限之處', 'report_rejection': '報告被退回', 'unknown': '未知項', 'action': '行動建議'}
PRIORITIES = {'decide': '需要決定', 'review': '視需要處理', 'info': '紀錄'}
BUDGETS = {'requests': 'HTTP 請求', 'calls': '工具呼叫', 'searches': '搜尋', 'offpage': '站外頁', 'seconds': '時間'}
BUDGET_ERRORS = {'request_budget': 'requests', 'tool_call_budget': 'calls', 'search_budget': 'searches',
                 'offpage_budget': 'offpage', 'time_budget': 'seconds', 'insufficient_search_time': 'seconds'}
# research_offpage counts against its budget only after these checks pass (a missing argument fails even earlier).
OFFPAGE_PRECHECK = {'purpose_required', 'invalid_mention', 'offpage_not_from_search', 'offpage_target_host', 'offpage_budget'}
REFUSED = {401: '需要登入', 403: '拒絕存取', 407: '代理需要驗證', 429: '請求過多', 451: '因法律理由不提供'}
CONTENT_ERRORS = {'unsupported_content_type', 'response_too_large', 'content_decoding', 'unsupported_content_encoding',
                  'xml_entity_forbidden', 'redirect_limit', 'redirect_missing_location'}
FINISH_TEXT = {'evidence_integrity': '引用的快照與帳本記錄的雜湊不同，證據可能被改動'}
KEEP = ('維持限制', None)
BOUNDARY = {
    'host_not_allowed': dict(
        label='網址不在允許清單', priority='review',
        decision='決定是否把這個網域加入允許清單，或接受只讀目前的網域。',
        why='允許清單決定 research_fetch 能讀哪些網站，放寬等於擴大 Agent 的行動範圍，只能由操作者決定。站外頁要經 research_offpage，且只限這次搜尋列出的網址。',
        options=[KEEP, ('加入允許清單：下次開跑時加 `--allow-host <網域>`', None)]),
    'https_only': dict(
        label='非 HTTPS 或帶帳密的網址', priority='decide',
        decision='檢查觸發這個請求的頁面或搜尋結果。',
        why='這類請求不應放寬；出現時可能是頁面內容誘導 Agent 去讀別的地方，要人看來源。',
        options=[KEEP, ('檢查來源頁是否含誘導指令', None)]),
    'private_address': dict(
        label='私人或本機位址', priority='decide',
        decision='檢查觸發這個請求的頁面或搜尋結果。',
        why='讀內網或本機位址可能洩漏內部資料，這類請求不應放寬；出現時可能是頁面內容誘導，要人看來源。',
        options=[KEEP, ('檢查來源頁是否含誘導指令', None)]),
    'offpage_not_from_search': dict(
        label='站外網址不在這次搜尋結果裡', priority='review',
        decision='確認是否需要讀這個站外頁；需要時由人自己查看。',
        why='站外讀取以搜尋結果為界，避免模型或頁內指令讓 Agent 讀任意網址；例外要人決定。',
        options=[KEEP, ('由人自行查看該頁，把結論寫進人工審查', None)]),
    'offpage_target_host': dict(
        label='用站外工具讀目標站', priority='info',
        decision='不需要決定；Agent 改用 research_fetch 即可。',
        why='這是工具用錯，不涉及授權。', options=[('不處理', None)]),
    'offpage_redirect_off_host': dict(
        label='站外頁轉址到其他網站', priority='info',
        decision='不需要決定；轉址目的地不在搜尋結果裡，控制器停止讀取。',
        why='跟去其他網站等於讀了搜尋沒列出的網址。', options=[('不處理', None)]),
    'robots_disallow': dict(
        label='robots.txt 禁止', priority='review',
        decision='接受限制，或由人向網站方取得授權、改用合法資料源。',
        why='是否繞過網站的抓取規則是法律與商譽判斷，不交給 Agent；控制器一律不抓。',
        options=[KEEP, ('取得授權或改用合法資料源後，由人調整研究範圍', None)]),
    'robots_unknown': dict(
        label='robots.txt 狀態不明', priority='review',
        decision='接受限制，或由人確認網站的抓取規則後再研究。',
        why='robots.txt 讀不到（不是 200、404 或 410）時無法確認是否允許抓取，控制器停止讀取該網站；要不要另找途徑由人判斷。',
        options=[KEEP, ('由人確認抓取規則或取得授權', None)]),
    'dns_unavailable': dict(
        label='DNS 解析失敗', priority='info',
        decision='不需要決定；多半是網路環境問題。',
        why='無法確認對方是公開位址時，控制器不連線。', options=[('不處理；反覆出現時檢查執行環境的網路', None)]),
}
UNKNOWN_GROUPS = [  # first match is the group; later matches are listed as also involved
    ('backlink', '完整反向連結', re.compile(r'backlink|反向連結|入站|referring|外鏈|外部連結|錨文字分布', re.I),
     '接受只用公開索引，或授權付費反向連結索引、Common Crawl 的網站連結圖。',
     '公開索引看不到完整反向連結；新資料源有費用或處理成本，要人授權。'),
    ('owner_data', '競爭者的排名、流量與轉換', re.compile(r'排名|流量|點擊|曝光|轉換|營收|收入|Search Console|GSC|分析帳號|收錄|索引', re.I),
     '接受為未知，或授權付費的第三方估算工具。',
     '這些是競爭者的私有資料，Agent 沒有合法取得途徑；第三方工具要付費，而且只是估算。'),
    ('our_site', '我方網站資料', re.compile(r'我方|我們的'),
     '提供我方網域、Search Console 與內容清單，或維持只研究競爭者。',
     '我方資料要我方帳號授權，Agent 沒有登入能力。'),
    ('legal', '法律、金流與契約', re.compile(r'法律|法規|法域|合法|法遵|合規|牌照|執照|監管|契約|佣金|KYC|年齡|個資', re.I),
     '交給法務判斷是否需要查證、怎麼查。',
     '牌照、法律實體、契約與出入金說法的查證涉及法規與實際金流，Agent 不能也不應代為查證。'),
    ('measurement', '需要額外量測', re.compile(r'Core Web Vitals|CWV|速度|實測|行動版|結構化資料|robots|sitemap|逐頁', re.I),
     '決定是否放寬預算，或另用量測工具（例如 PageSpeed、結構化資料測試）。',
     '要多花請求預算或使用外部服務，屬於成本取捨。'),
    ('other', '其他', None, '決定是否值得追查、用什麼資料。', '沒有對應的現成資料源，要人判斷價值與成本。'),
]
LEGAL = re.compile(r'法域|法規|法律|合法|法遵|合規|年齡|未成年|個資|隱私|責任博彩|牌照|執照|監管|KYC', re.I)
PRIORITY_TAG = re.compile(r'^\s*P(\d)(?!\d)')
RUN_FILE = re.compile(r'([0-9a-f]{32})-(preflight|outcome)\.json')
EMOJI = re.compile('[\U0001F000-\U0001FAFF\u2600-\u27BF]\ufe0f?')  # Hermes decorates review actions
FIXED_RULES = [
    dict(matter='登入與用量額度',
         how='使用者自己在瀏覽器完成裝置登入。runner 開跑前檢查登入、限流與工具清單，未就緒就以 exit 2 停止、不呼叫模型。Agent 沒有登入或查用量的工具。',
         where='scripts/login_hermes.sh、scripts/run_research.py、src/runner_support.py 的 readiness'),
    dict(matter='付費',
         how='Agent 沒有付費 API 金鑰或付費工具；搜尋用 Hermes 內建的免金鑰 DDGS。加入付費資料源要改控制器程式，由人授權費用。',
         where='plugin/__init__.py、src/research_core.py'),
    dict(matter='對外發布或修改網站',
         how='平常的研究只有六個唯讀研究工具：HTTP 只送不帶內容的 GET，research_finish 只把報告寫進研究目錄；沒有 shell、檔案或瀏覽器工具。比較 Hermes 原生學習時另加 Hermes 的 memory 與 skills 工具，只寫 Hermes 自己的儲存。實際工具清單與預期不同時 runner 拒絕開跑。',
         where='src/research_core.py 的 HTTP、src/runner_support.py 的 HERMES_MODES、scripts/run_research.py 的 build_agent'),
    dict(matter='否決經驗與人工審查',
         how='lesson 只由控制器量測與人工審查產生，模型沒有寫入帳本的工具。人工標註與否決用 feedback.py，要寫審查者與理由；否決後不再自動恢復。',
         where='src/lessons.py 的 Ledger.add_feedback、Ledger.veto，scripts/feedback.py'),
    dict(matter='研究對象與預算',
         how='操作者開跑時指定網站、關鍵字與 research_fetch 的允許網域；research_offpage 只讀這次搜尋列出的站外網址，每次最多 4 頁。預算寫在控制器，每次工具呼叫都檢查。Agent 沒有修改它們的工具。',
         where='scripts/run_research.py 的 --target、--keyword、--allow-host，src/research_core.py 的 Limits 與 Research.search'),
]


# Loading ----------------------------------------------------------------------------------------------------------
def locate(path):
    """research.sqlite and its run root from either path."""
    p = Path(path)
    return (p / 'research.sqlite', p) if p.is_dir() else (p, p.parent)


def connect_ro(db_path):
    # Read-only URI: the queue must never touch a ledger that may be frozen evaluation evidence.
    db = sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    return db


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def runner_runs(root):
    """Runs the runner wrote files for, timed by file modification; a run stopped before the controller started
    (failed preflight, operator pause, failed initialization) has no row in research.sqlite."""
    out = {}
    for f in Path(root).glob('*-*.json'):
        m = RUN_FILE.fullmatch(f.name)
        if m:
            t = datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat()
            out[m.group(1)] = max(out.get(m.group(1), ''), t)
    return out


def pick_run(known, run):
    if not known:
        raise ValueError('no runs: the folder has neither ledger runs nor runner files')
    if run is None:
        return max(known, key=lambda r: known[r])
    found = [r for r in known if r.startswith(run)]
    if len(found) != 1:
        raise ValueError(f'run {run!r} matches {len(found)} runs')
    return found[0]


def load(db_path, run=None, root=None):
    """Everything the queue reads about one run."""
    db_path = Path(db_path)
    root = Path(root) if root else db_path.parent
    ctx = dict(events=[], searches={}, other_events={}, lessons={}, has_ledger=False, history=[], support=[],
               feedback=[])
    known = runner_runs(root)
    db = connect_ro(db_path) if db_path.exists() else None
    try:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} if db else set()

        def table(name, sql, args=()):
            return [dict(r) for r in db.execute(sql, args)] if name in tables else []  # older ledgers lack lessons

        db_runs = {r['id']: r for r in table('runs', 'SELECT * FROM runs')}
        known.update({rid: r['created'] for rid, r in db_runs.items()})
        run_id = pick_run(known, run)
        ctx['run'] = db_runs.get(run_id) or dict(id=run_id, host=None, mode=None, status='not_started', created=known[run_id])
        if run_id in db_runs:
            ctx['events'] = [(r['id'], r['kind'], json.loads(r['data'])) for r in
                             table('events', 'SELECT id,kind,data FROM events WHERE run=? ORDER BY id', (run_id,))]
            paths = {r['id']: r['path'] for r in table('evidence', 'SELECT id,path FROM evidence')}
            for r in table('events', "SELECT id,data FROM events WHERE kind='search_response' ORDER BY id"):
                d = json.loads(r['data'])  # every run, so lesson support from earlier runs can show its query
                ctx['searches'][d.get('evidence_id')] = dict(query=d.get('query', ''), outcome=search_outcome(d),
                                                             status=d.get('status'), event=r['id'],
                                                             error=search_error(root, paths.get(d.get('evidence_id')), d))
            ctx['other_events'] = {r['id']: json.loads(r['data']) for r in table(
                'events', "SELECT id,data FROM events WHERE kind IN ('tool_error','tool_call') ORDER BY id")}
            ctx['lessons'] = {r['id']: dict(r, data=json.loads(r['data'] or '{}'))
                              for r in table('lessons', 'SELECT * FROM lessons')}
            ctx['has_ledger'] = 'lessons' in tables
            ctx['history'] = table('lesson_history', 'SELECT * FROM lesson_history ORDER BY id')
            ctx['support'] = table('lesson_support', 'SELECT * FROM lesson_support ORDER BY id')
            ctx['feedback'] = table('feedback', 'SELECT * FROM feedback WHERE run=? ORDER BY id', (run_id,))
    finally:
        if db:
            db.close()
    events = ctx['events']
    last = lambda kind: next(((i, d) for i, k, d in reversed(events) if k == kind), (None, None))
    ctx['start'] = last('start')[1] or {}
    ctx['report_event'], ctx['report'] = last('report')
    if ctx['report'] is None:
        ctx['report'] = read_json(root / f'{run_id}-report.json')
    ctx['presented_event'], ctx['presented'] = last('lessons_presented')
    ctx['learning_event'], ctx['learning'] = last('learning')
    for name in ('outcome', 'preflight', 'review', 'hermes'):
        ctx[name] = read_json(root / f'{run_id}-{name}.json')
    ctx['pre_review'] = (root / f'{run_id}-pre-review').is_dir()
    ctx['calls'] = group_calls(events)
    # Only finish calls that reached the controller were judged; calls stopped by a gate are budget or time limits.
    ctx['finish_errors'] = [(eid, err) for c in ctx['calls'] if c['name'] == 'research_finish' and c['logged']
                            for eid, err in [call_error(c)] if err is not None]
    return ctx


def search_outcome(d):
    return d.get('outcome') or ('ok' if d.get('status') == 200 else 'error')


def search_error(root, path, d):
    """The provider's own words for a failed search, read from the stored snapshot."""
    if d.get('status') == 200 or not path:
        return ''
    try:
        return str(json.loads((Path(root) / path.replace('\\', '/')).read_text(encoding='utf-8')).get('error', ''))[:100]
    except (OSError, ValueError, AttributeError):
        return ''


def group_calls(events):
    """Tool calls in order, each with the events it caused; calls stopped before logging stand alone."""
    calls, current = [], None
    for eid, kind, d in events:
        if kind == 'tool_call':
            current = dict(event=eid, name=d.get('name'), args=d.get('args') or {}, logged=True, events=[])
            calls.append(current)
        elif kind == 'tool_error' and d.get('call_logged', True) is False:
            current = dict(event=eid, name=d.get('name'), args={}, logged=False, events=[(eid, kind, d)])
            calls.append(current)
        elif current is not None:
            current['events'].append((eid, kind, d))
    return calls


def call_error(call):
    return next(((eid, d) for eid, kind, d in call['events'] if kind == 'tool_error'), (None, None))


def code_of(error):
    return str(error.get('error', '')).split(':')[0]


def call_target(call):
    a = call['args']
    return a.get('url') or a.get('query') or a.get('evidence_id') or ''


def same_page(url):
    return re.sub(r'^(https?://)www\.', r'\1', norm_url(url or ''))


# Helpers ----------------------------------------------------------------------------------------------------------
def quote(s):
    return f'"{s}"' if re.search(r'[\s"\'<>|&;()]', s) else s


def feedback_cmd(root, *args):
    return ' '.join(['python', 'scripts/feedback.py', '--root', quote(root), *args])


def veto_cmd(root, lesson_id):
    return feedback_cmd(root, 'veto', '--lesson', lesson_id, '--reason', '"<理由>"', '--reviewer', '"<審查者>"')


def label_cmd(root, run_id, target, label='unsupported'):
    return feedback_cmd(root, 'label', '--run', run_id, '--target', target, '--label', label,
                        '--reason', '"<理由>"', '--reviewer', '"<審查者>"')


def short(text, n=60):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= n else text[:n] + '…'


def when(ts):
    return f'{ts[:10]} {ts[11:16]} UTC' if ts and len(ts) >= 16 else (ts or '')


def item(category, priority, title, decision, why, evidence, if_no_action, options, **refs):
    return dict(category=category, priority=priority, title=title, decision=decision, why_human=why,
                evidence=list(evidence), if_no_action=if_no_action,
                options=[dict(choice=c, command=cmd) for c, cmd in options], refs=refs)


def search_line(s, eid):
    detail = (f'HTTP 200，沒有可用的結果' if s['status'] == 200 and s['outcome'] != 'ok' else
              f'HTTP {s["status"]}' + (f'：{s["error"]}' if s['error'] else ''))
    return f'搜尋「{s["query"]}」→ {s["outcome"]}（{detail}，evidence {eid}）'


def describe_evidence(ctx, eid):
    if isinstance(eid, str) and eid.startswith('event:'):
        n = int(eid.split(':')[1])
        err = ctx['other_events'].get(n, {})
        call = next((c for c in ctx['calls'] if any(e == n for e, _, _ in c['events'])), None)
        target = f' {call_target(call)}' if call else ''
        return f'event {n}：{err.get("name", "")} 被拒（{err.get("error", "")}）{target}'
    s = ctx['searches'].get(eid)
    if s:
        return search_line(s, eid)
    return f'evidence {eid}'


def fmt_use(u):
    if u['used'] is None:
        return f'上限 {u["limit"]} 秒'
    over = u['limit'] is not None and u['used'] > u['limit']
    return f'{u["used"]}/{u["limit"]}' + (f'（超過上限的 {u["used"] - u["limit"]} 次被拒）' if over else '')


# Items ------------------------------------------------------------------------------------------------------------
def preflight_items(ctx):
    out, pf, oc, start, rid = [], ctx['preflight'], ctx['outcome'], ctx['start'], ctx['run']['id']
    state = (oc or {}).get('state')
    if pf and not pf.get('ready'):
        out.append(item(
            'preflight', 'decide', f'開跑前檢查未通過：{pf.get("blocker") or "not ready"}',
            '處理登入、額度或工具清單後再開跑。',
            '登入與額度只能由人處理，Agent 沒有相關工具；工具清單不符代表執行環境和檢查過的不同。',
            [f'{rid}-preflight.json：logged_in={pf.get("logged_in")}、rate_limited={pf.get("rate_limited")}、'
             f'實際工具 {len(pf.get("actual_tools") or [])} 個、預期 {len(pf.get("expected_tools") or [])} 個']
            + ([f'{rid}-outcome.json：state={state}、exit_code={oc.get("exit_code")}'] if oc else []),
            '不會呼叫模型。',
            [('重新登入：`bash scripts/login_hermes.sh --new`', None), ('等額度重置後再跑', None),
             ('工具清單不符：先查 plugin 與 Hermes 版本', None)]))
    elif state == 'paused_by_operator':
        out.append(item(
            'preflight', 'decide', '操作者暫停了模型執行', '決定何時恢復。',
            '暫停由操作者建立 `.runtime/pause-model-runs` 觸發，恢復也只能由人決定。',
            [f'{rid}-outcome.json：state={state}、exit_code={oc.get("exit_code")}'], '不會呼叫模型。',
            [('恢復：刪除 `.runtime/pause-model-runs` 後重跑', None), ('維持暫停', None)]))
    elif state == 'ready':
        out.append(item('preflight', 'info', '只做了開跑前檢查', '不需要決定。', '這是 `--check-only`，不呼叫模型。',
                        [f'{rid}-outcome.json：state=ready'], '沒有研究。', [('不處理', None)]))
    elif state and state not in ('research_complete', 'smoke_complete'):
        out.append(item(
            'preflight', 'review', f'研究沒有正常完成：{state}',
            '決定是否重跑。', '沒完成的研究不學習，也沒有可用的報告；重跑會再花模型額度，要人決定。',
            [f'{rid}-outcome.json：state={state}、exit_code={oc.get("exit_code")}'],
            '這次研究不會留下經驗。', [('重跑', None), ('不重跑', None)]))
    if (ctx['has_ledger'] and start.get('mode') == 'memory' and start.get('learning') and ctx['report_event']
            and state in (None, 'research_complete') and ctx['learning'] is None):
        out.append(item(
            'preflight', 'review', '這次研究沒有學習紀錄',
            '確認 runner 是否執行了學習。',
            '學習只在 runner 判定 research_complete 後執行；學習出錯會整批回滾，要人檢查原因。',
            ['events 表沒有 kind=learning 的事件'], '這次的量測不會進入帳本。', [('檢查 runner 輸出', None)]))
    return out


def run_cutoff(ctx):
    """The last moment this run wrote to the ledger; later history rows belong to later runs or to people."""
    rid = ctx['run']['id']
    times = [ctx['run']['created'] or '', (ctx['presented'] or {}).get('time') or '']
    times += [h['time'] for h in ctx['history'] if h['run'] == rid]
    times += [s['time'] for s in ctx['support'] if s['run'] == rid]
    return max(times)


def lesson_change_items(ctx):
    run_id, root = ctx['run']['id'], ctx['root_cmd']
    start, shown = ctx['run']['created'], (ctx['presented'] or {}).get('time')
    cutoff = run_cutoff(ctx)
    hist = {}
    for h in ctx['history']:
        # Learning rows carry the run; re-verification at research_status time writes run=None inside the run window.
        at_start = h['run'] is None and shown and start <= h['time'] <= shown
        if h['actor'] == 'controller' and (h['run'] == run_id or at_start):
            hist.setdefault(h['lesson'], []).append(h)
    # Research memory adds summary rows without a lesson id to the learning event; memory_items reports them.
    changes = {c['lesson']: c for c in (ctx['learning'] or {}).get('changes', []) if 'lesson' in c}
    out = []
    for lid in dict.fromkeys([*changes, *hist]):
        rows, change, lesson = hist.get(lid, []), changes.get(lid), ctx['lessons'].get(lid) or {}
        if lesson.get('kind') == 'finding':
            continue  # research memory findings: memory_items lists them together
        old = rows[0]['old'] if rows else change['status']
        new = rows[-1]['new'] if rows else change['status']
        reason = change['reason'] if change else rows[-1]['reason']
        created = bool(rows) and rows[0]['old'] is None
        key, kind, data = lesson.get('key') or (change or {}).get('key', lid), lesson.get('kind', ''), lesson.get('data', {})
        support = [s for s in ctx['support'] if s['lesson'] == lid and s['run'] == run_id]
        pos = [e for s in support if s['polarity'] == 1 for e in json.loads(s['evidence'])]
        neg = [e for s in support if s['polarity'] == -1 for e in json.loads(s['evidence'])]
        evidence = [f'lesson {lid}（{kind}）：{key}', f'控制器紀錄的理由：{reason}']
        if rows and all(r['run'] is None for r in rows):
            evidence.append('這是研究開始時控制器重驗或到期檢查造成的變動')
        if kind == 'discovery_path':  # its support is the target page listed here
            evidence.append(f'目標頁 {data.get("target_url")}，第一次讀到的 evidence {data.get("evidence_id")}；'
                            f'入口頁 {data.get("source_url") or "無（直接輸入網址）"}')
        else:
            evidence += [f'失敗：{describe_evidence(ctx, e)}' for e in pos]
            evidence += [f'反例：{describe_evidence(ctx, e)}' for e in neg]
        later = [h for h in ctx['history'] if h['lesson'] == lid and h['time'] > cutoff and h['old'] != h['new']]
        evidence += [f'之後：{when(h["time"])} {("run " + h["run"][:8]) if h["run"] else h["actor"].removeprefix("human:")}'
                     f' 把它從 {h["old"]} 改為 {h["new"]}（{short(h["reason"], 70)}）' for h in later]
        evidence.append(f'帳本目前狀態：{lesson.get("status")}'
                        + (f'，效期到 {when(lesson["expires"])}' if lesson.get('expires') else ''))
        effect = (f'引導 Agent 直接讀「{data.get("keyword")}」目標頁' if kind == 'discovery_path'
                  else f'提醒 Agent：{lesson.get("statement") or key}')
        veto = ('否決（永久停用，之後不會自動恢復）', veto_cmd(root, lid))
        if new == 'active' and old != 'active':
            why = ('經驗由控制器依量測自動啟用，不等人核准，下一次研究就會使用。量測只確認「讀到了」或「失敗了」，'
                   '不能判斷它是否值得當成之後的預設做法。')
            if kind == 'discovery_path':
                why += '每次使用前控制器會重抓確認，頁面消失或標題不符就自動撤銷。'
            it = item('lesson_change', 'decide', f'啟用經驗：{key}',
                      f'確認或否決這條經驗。它從下一次研究起出現在 research_status，{effect}。', why, evidence,
                      '經驗維持啟用；7 天沒有新支持會到期，遇到反例或重抓失敗會撤銷。', [('接受：不需操作', None), veto])
        elif new == 'candidate':
            m = re.match(r'(\d+) run', reason or '')
            n = int(m.group(1)) if m else len(data.get('runs', []))
            judge = ('控制器把搜尋回報「沒有結果」算成研究方法失敗（逾時與限流不算）；免金鑰搜尋有時對正常的查詢也回報沒有結果，'
                     '是查詢不好還是索引暫時沒回應，要人判斷。' if data.get('tool') == 'research_search'
                     else '要人判斷 Agent 該學成「避開這種做法」，還是其實該放寬控制器規則。')
            it = item('lesson_change', 'review', f'候選經驗：{key}',
                      '決定是否先否決。它還沒被採用，不會出現在研究中。',
                      f'失敗模式要在 2 個研究中重現才啟用，目前 {n} 個；再重現就自動啟用，不經人核准。' + judge,
                      evidence, '維持候選；再有一個研究重現就自動啟用，7 天沒有新支持就到期。',
                      [('等更多量測：不需操作', None), ('否決（阻止它自動啟用）', veto_cmd(root, lid))])
        elif new == 'revoked' and old == 'revoked':
            it = item('lesson_change', 'info', f'已撤銷的經驗再次記錄：{key}',
                      '不需要決定；列出供核對。', '撤銷後的失敗與反例照常計數，狀態不變。', evidence,
                      '維持撤銷。', [('不處理', None), veto])
        elif new == 'revoked':
            was_active = old == 'active'
            it = item('lesson_change', 'review' if was_active else 'info', f'撤銷經驗：{key}',
                      '檢查之前用過它的研究是否被誤導。' if was_active else '不需要決定；列出供核對撤銷理由。',
                      '撤銷由反例或重抓失敗自動觸發。' + ('它曾經啟用，之前的研究照它行動過。' if was_active else
                                                    ('它在這次研究中新建，同一次就遇到反例。' if created else '')),
                      evidence, '維持撤銷；之後要再有 2 個研究重現才會恢復。', [('不處理', None), veto])
        elif new == 'expired':
            it = item('lesson_change', 'info', f'經驗到期：{key}', '不需要決定。', '7 天沒有新支持，控制器讓它到期。',
                      evidence, '維持到期；之後要重新累積支持。', [('不處理', None), veto])
        elif new == 'vetoed':
            it = item('lesson_change', 'info', f'已否決的經驗又收到量測：{key}', '不需要決定。',
                      '否決是最終狀態，控制器只累積證據，不改狀態。', evidence, '維持否決。', [('不處理', None)])
        else:
            it = item('lesson_change', 'info', f'經驗續期：{key}', '不需要決定。', '新的支持讓效期延長。', evidence,
                      '照常使用。', [('不處理', None), veto])
        it['refs'].update(lesson=lid, old=old, new=new, created=created)
        veto_row = next((h for h in ctx['history'] if h['lesson'] == lid and h['new'] == 'vetoed'), None)
        if veto_row and new != 'vetoed':
            it['handled'] = (f'已由 {veto_row["actor"].removeprefix("human:")} 否決（{when(veto_row["time"])}）：'
                             f'{veto_row["reason"]}')
        out.append(it)
    return out


def memory_items(ctx):
    """v0.9 research memory: findings the run added from its accepted report, and what the controller re-checked at
    the start of the run (kept, sent back to re-reading, revoked)."""
    rid, root = ctx['run']['id'], ctx['root_cmd']
    findings = {lid: l for lid, l in ctx['lessons'].items() if l.get('kind') == 'finding'}
    if not findings:
        return []
    added = [lid for lid, l in findings.items() if (l.get('data') or {}).get('run') == rid]
    replaced = sorted({h['lesson'] for h in ctx['history'] if h['lesson'] in findings and h['new'] == 'superseded'
                       and h['run'] == rid})
    shown = next((d for _, k, d in ctx['events'] if k == 'memory_presented'), None)
    out = []
    if shown:
        revoked = shown.get('revoked') or []
        evidence = [f'控制器在研究開始時重抓 {shown.get("checked_pages")} 頁（控制器請求 {shown.get("controller_requests")} 次）：'
                    f'{len(shown.get("findings") or [])} 條發現的頁面仍成立、{len(shown.get("recheck") or [])} 條待重讀、'
                    f'{len(revoked)} 條撤銷；另列 {len(shown.get("candidates") or [])} 個未讀站內頁、'
                    f'{len(shown.get("unknowns") or [])} 個上次的未知項']
        evidence += [f'撤銷 finding {lid}：{short(findings.get(lid, {}).get("statement"), 80)}' for lid in revoked]
        out.append(item('lesson_change', 'review' if revoked else 'info', '研究記憶的重驗',
                        '檢查被撤銷的發現是否曾誤導之前的研究。' if revoked else '不需要決定；列出供核對。',
                        '重驗只看頁面是否還在、內容是否大致不變，不判斷發現本身是否正確。', evidence,
                        '照常；撤銷的發現不再出現。', [('不處理', None)], lessons=revoked))
    if added:
        evidence = [f'finding {lid}：{short(findings[lid].get("statement"), 90)}（狀態 {findings[lid].get("status")}）'
                    for lid in added]
        if replaced:
            evidence.append(f'取代了上一份報告的 {len(replaced)} 條發現')
        out.append(item('lesson_change', 'review', f'研究記憶新增 {len(added)} 條發現',
                        '抽查新發現；不實或說太滿的用否決停用。',
                        '發現來自 Agent 自己的報告，控制器只確認每個引用都是雜湊有效的站內頁，不確認內容正確。'
                        '下一次研究開始時控制器會重抓頁面，仍成立才交給模型，重驗通過後轉為 active，不經人核准。',
                        evidence, '下一次研究會看到仍成立的發現，並在上面往下挖。',
                        [('接受：不需操作', None), ('否決其中一條（把 <lesson> 換成上面的 finding 編號）',
                                                   veto_cmd(root, '<lesson>'))], lessons=added))
    return out


def native_learning_items(ctx):
    """Hermes' own memory and skill writes when its learning is on: they skip the ledger's checks entirely."""
    review, hermes, rid = ctx['review'], ctx['hermes'] or {}, ctx['run']['id']
    if (ctx['outcome'] or {}).get('hermes_learning') not in ('learn', 'feedback') and review is None:
        return []
    writes = {}
    for m in hermes.get('messages') or []:
        for t in m.get('tool_calls') or []:
            name = (t.get('function') or {}).get('name')
            if name in HERMES_WRITE_TOOLS:
                writes[name] = writes.get(name, 0) + 1
    actions = (review or {}).get('actions') or []
    evidence = [f'研究中呼叫 Hermes 寫入工具：' + ('、'.join(f'{k} {v} 次' for k, v in writes.items()) or '沒有')]
    if review:
        evidence.append(f'{rid}-review.json：背景回顧 completed={review.get("completed")}、timed_out={review.get("timed_out")}、'
                        f'result={review.get("result")}')
        evidence += [f'回顧動作：{EMOJI.sub("", a).strip()}' for a in actions]
    if ctx['pre_review']:
        evidence.append(f'{rid}-pre-review/：研究結束、回顧開始前的 skill 與 memory 檔案（manifest.json 有雜湊）')
    profile = Path(str((ctx['preflight'] or {}).get('hermes_home') or '<profile>')).name
    restore = (f'python -c "from pathlib import Path; from src.hermes_homes import restore; '
               f"restore(Path('{ctx['root_cmd']}/{rid}-pre-review'), Path('.runtime/user/profiles/{profile}'), Path('.'))\"")
    return [item('lesson_change', 'decide' if writes or actions else 'info', f'Hermes 原生學習寫入：{(review or {}).get("result") or "無回顧紀錄"}',
                 '確認或撤回 Hermes 寫進自己 skill 與 memory 的內容。之後用同一個 profile 的研究都會載入它們。',
                 'Hermes 的回顧不經控制器量測，也不等人核准就寫入；寫的是通用方法還是網站事實、對不對，只有人能判斷。'
                 'lessons 帳本的重驗、反例撤銷與到期都不適用於它，Hermes 也沒有否決單一 skill 的指令。',
                 evidence, '之後的研究照常載入。',
                 [('接受：不需操作', None),
                  ('撤回這次回顧的寫入（在保有 .runtime 的執行環境、任務根目錄執行）', restore if ctx['pre_review'] else None)],
                 native=True)]


def lessons_in_use_items(ctx):
    p = ctx['presented']
    if not p or not p.get('lessons'):
        return []
    lines, options, unsure = [], [], False
    for x in p['lessons']:
        lesson = ctx['lessons'].get(x['id']) or {}
        v = x.get('verification') or {}
        origin = next((h['actor'] for h in ctx['history'] if h['lesson'] == x['id']), '')
        parts = [f'適用 {x.get("applies")}', f'效期 {when(x["expires"]) if x.get("expires") else "無"}']
        if v:
            parts.insert(1, f'開始時重抓 {v.get("result")}' + (f'（evidence {v["evidence_id"]}）' if v.get('evidence_id') else ''))
            unsure = unsure or v.get('result') != 'ok'
        if lesson.get('kind') == 'human_feedback':
            parts.append(f'人工審查，帳本記錄的審查者為 {origin.removeprefix("human:")}；沒有效期，只能由人否決')
        if lesson.get('status') == 'vetoed':
            parts.append('之後已被否決')
        lines.append(f'lesson {x["id"]}（{lesson.get("kind", "")}）{x.get("key")}：' + '，'.join(parts))
        if lesson.get('status') != 'vetoed':
            options.append((f'否決 {x["id"]}', veto_cmd(ctx['root_cmd'], x['id'])))
    return [item('lessons_in_use', 'review' if unsure else 'info', f'這次研究使用的經驗（{len(lines)} 條）',
                 '確認這些經驗仍然可信，不可信的就否決。',
                 '經驗會改變 Agent 先讀什麼、避開什麼、怎麼寫主張。發現路徑每次使用前由控制器重抓確認；人工審查經驗沒有效期。',
                 lines + [f'event {ctx["presented_event"]}（lessons_presented）'], '之後的研究照常使用。',
                 [('不處理', None)] + options, event=ctx['presented_event'])]


def usage(ctx):
    limits, ev = ctx['start'].get('limits', {}), ctx['events']
    count = lambda kind: sum(1 for _, k, _ in ev if k == kind)
    reqs = [d for _, k, d in ev if k == 'request']

    def offpage_counted(call):
        if not call['logged']:
            return False
        _, err = call_error(call)
        return err is None or (code_of(err) not in OFFPAGE_PRECHECK and err.get('error_type') != 'KeyError')
    own = 'controller_requests' in limits  # v0.9: the controller's re-checks have their own budget
    ctl = sum(1 for d in reqs if d.get('actor') == 'controller')
    return dict(
        controller=dict(used=ctl, limit=limits.get('controller_requests')) if own else None,
        requests=dict(used=len(reqs) - (ctl if own else 0), limit=limits.get('requests'),
                      by=dict(model=sum(1 for d in reqs if d.get('actor', 'model') == 'model' and d.get('channel', 'direct') == 'direct'),
                              offpage=sum(1 for d in reqs if d.get('channel') == 'offpage'),
                              controller=sum(1 for d in reqs if d.get('actor') == 'controller'))),
        calls=dict(used=count('tool_call') + sum(1 for c in ctx['calls'] if not c['logged']), limit=limits.get('calls')),
        searches=dict(used=count('search_request'), limit=SEARCH_LIMIT),
        offpage=dict(used=sum(1 for c in ctx['calls'] if c['name'] == 'research_offpage' and offpage_counted(c)),
                     limit=limits.get('offpage')),
        seconds=dict(used=None, limit=limits.get('seconds')))


def limit_items(ctx):
    out, use = [], ctx['usage']
    errors = [(c, *call_error(c)) for c in ctx['calls']]
    errors = [(c, eid, err) for c, eid, err in errors
              if err is not None and not (c['name'] == 'research_finish' and c['logged'])]
    budget_hits = {}
    for c, eid, err in errors:
        if code_of(err) in BUDGET_ERRORS:
            budget_hits.setdefault(BUDGET_ERRORS[code_of(err)], []).append(f'event {eid}：{c["name"]} 被拒（{err["error"]}）')
    for key, label in BUDGETS.items():
        u = use[key]
        full = u['limit'] is not None and u['used'] is not None and u['used'] >= u['limit']
        if not (full or key in budget_hits):
            continue
        source = '上限固定在 `Research.search`' if key == 'searches' else '上限取自 start 事件的 limits'
        out.append(item(
            'limit', 'review', f'預算用完：{label} {fmt_use(u)}',
            '決定下次是否放寬這項預算，或接受目前的覆蓋範圍。',
            '預算是操作者為時間、請求與成本設的上限；Agent 只能在上限內取捨，不能自己加。',
            [f'用量 {fmt_use(u)}（{source}）'] + budget_hits.get(key, []),
            '下次研究用同樣的預算。',
            [('維持', None), ('放寬：改 `src/research_core.py` 的 `Limits`（搜尋上限在 `Research.search`）。'
                             '這是程式變更，正式評估前要先登錄新計畫', None)], budget=key))
    grouped = {}
    for c, eid, err in errors:
        code = code_of(err)
        if code in BUDGET_ERRORS:
            continue
        group = code if code in BOUNDARY else ('content' if code in CONTENT_ERRORS else
                                                ('integrity' if code == 'evidence_integrity' else 'other'))
        grouped.setdefault(group, []).append(f'event {eid}：{c["name"]} {short(call_target(c), 90)} → {err["error"]}')
    for group, lines in grouped.items():
        if group in BOUNDARY:
            b = BOUNDARY[group]
            out.append(item('limit', b['priority'], f'控制器拒絕：{b["label"]}（{len(lines)} 次）', b['decision'], b['why'],
                            lines, '下次遇到同樣情況仍會拒絕。', b['options'], code=group))
        elif group == 'content':
            out.append(item('limit', 'review', f'控制器拒絕：內容格式不支援（{len(lines)} 次）',
                            '決定是否需要支援這類內容（例如 PDF），或接受略過。',
                            '支援新格式要改控制器，並重新評估解析風險與大小上限，屬於工程與風險取捨。',
                            lines, '這類內容仍會被略過。', [('接受略過', None), ('排入控制器改版', None)], code='content'))
        elif group == 'integrity':
            out.append(item('limit', 'decide', f'證據快照雜湊不符（{len(lines)} 次）', '檢查研究目錄的快照是否被改動。',
                            '快照與帳本記錄的雜湊不同，表示證據可能被改過；Agent 無法判斷原因。',
                            lines, '引用這些快照的主張無法通過檢查。', [('檢查 snapshots/ 與 evidence 表', None)],
                            code='evidence_integrity'))
        else:
            out.append(item('limit', 'info', f'其他工具錯誤（{len(lines)} 次）', '不需要決定；反覆出現時檢查工具或網路。',
                            '多半是參數錯誤、網路問題或研究已結束後的呼叫，Agent 會改用其他做法。', lines, '不影響之後的研究。',
                            [('不處理', None)], code='other'))
    out += refusal_items(ctx) + search_items(ctx)
    for eid, kind, d in ctx['events']:
        if kind == 'proxy_dns':
            out.append(item('limit', 'info', 'DNS 經代理解析', '不需要決定。',
                            '本機 DNS 解析失敗，允許網域改由設定的 HTTPS 代理解析；這是執行環境的限制，代理不是網路沙箱。',
                            [f'event {eid}：{d.get("host")}'], '照常執行。', [('不處理', None)], event=eid))
            break
    return out


def refusal_items(ctx):
    responses = [(eid, d) for eid, k, d in ctx['events'] if k == 'response']
    requests = [(eid, d) for eid, k, d in ctx['events'] if k == 'request']
    lines, retried = [], False
    for eid, d in responses:
        if d.get('status') not in REFUSED or d.get('url', '').endswith('/robots.txt'):  # robots.txt shows as robots_unknown
            continue
        again = [r for r, q in requests if r > eid and same_page(q.get('url')) == same_page(d.get('url'))
                 and q.get('actor', 'model') == 'model']
        retried = retried or bool(again)
        retry_after = (d.get('headers') or {}).get('retry-after')
        lines.append(f'event {eid}：HTTP {d["status"]}（{REFUSED[d["status"]]}）{d.get("url")}，evidence {d.get("evidence_id")}'
                     + (f'，Retry-After {retry_after}' if retry_after else '')
                     + (f'；模型之後又請求同一頁（event {", ".join(map(str, again))}）' if again else ''))
    if not lines:
        return []
    why = '控制器保存回應、不自動重試、不繞過；是否另找途徑取得資料是法律與商譽判斷。'
    if retried:
        why += '模型在被拒後又請求同一頁：研究 prompt 要求不重試，控制器沒有硬性阻擋，要人確認這是否可接受。'
    return [item('limit', 'decide' if retried else 'review', f'網站拒絕存取（{len(lines)} 次）',
                 '接受限制，或由人向網站方取得授權、改用合法資料源。', why, lines, '下次研究仍會被拒。',
                 [KEEP, ('取得授權或改用合法資料源', None)], retried=retried)]


def search_items(ctx):
    rows = [(eid, d) for eid, k, d in ctx['events'] if k == 'search_response']
    bad = [(eid, d) for eid, d in rows if search_outcome(d) != 'ok']
    if not bad:
        return []
    lines = [f'event {eid}：' + search_line(ctx['searches'].get(d.get('evidence_id')) or dict(
        query=d.get('query', ''), outcome=search_outcome(d), status=d.get('status'), error=''), d.get('evidence_id'))
             for eid, d in bad]
    return [item('limit', 'review' if 2 * len(bad) >= len(rows) else 'info',
                 f'搜尋沒有結果或失敗：{len(bad)}/{len(rows)} 次',
                 '接受免金鑰搜尋的覆蓋限制，或授權付費搜尋、反向連結資料源。',
                 'Agent 只能用現有的免金鑰索引；新的資料源可能有費用與使用條款，要人授權。',
                 lines, '下次仍用同一個免金鑰索引。',
                 [('接受', None), ('授權新資料源：改控制器程式，正式評估前要先登錄新計畫', None)])]


def rejection_items(ctx):
    errors = ctx['finish_errors']
    if not errors:
        return []
    codes = [code_of(err) for _, err in errors]
    lines = [f'event {eid}：{err["error"]}（{RULES.get(c) or FINISH_TEXT.get(c, "控制器拒收")}）'
             for (eid, err), c in zip(errors, codes)]
    accepted = ctx['report_event'] is not None
    rid, root = ctx['run']['id'], ctx['root_cmd']
    lines.append(f'最後接受的報告：event {ctx["report_event"]}，{rid}-report.md' if accepted else '沒有被接受的報告')
    tampered = 'evidence_integrity' in codes
    it = item('report_rejection', 'decide' if tampered else 'review',
              f'報告被退回 {len(errors)} 次，最後{"已接受" if accepted else "沒有被接受"}',
              ('先檢查研究目錄的快照是否被改動，' if tampered else '') +
              '檢查最後接受的版本是否只是為了通過檢查而改寫，例如刪掉引用或把主張改成未知。',
              '控制器只檢查格式、引用存在與雜湊，不檢查語意；修正是否合理要人看。' +
              ('有快照雜湊不符，證據可能被改過，Agent 無法判斷原因。' if tampered else ''), lines,
              '報告照目前版本保留' + ('，退回的紀錄會成為失敗模式的量測。' if ctx['start'].get('learning')
                                    and ctx['start'].get('mode') == 'memory' else '。'),
              [('沒有問題', feedback_cmd(root, 'ok', '--run', rid, '--reviewer', '"<審查者>"')),
               ('標註有問題的主張（N 是報告中的順序）', label_cmd(root, rid, 'claim:N'))])
    ok = next((f for f in ctx['feedback'] if f['label'] == 'reviewed_ok'), None)
    if ok:
        it['handled'] = f'已由 {ok["reviewer"]} 標為已審查（{when(ok["time"])}）'
    return [it]


def unknown_items(ctx):
    report = ctx['report'] or {}
    entries = [(f'claim:{i}', c.get('text', '')) for i, c in enumerate(report.get('claims') or [], 1)
               if c.get('kind') == 'unknown']
    entries += [(f'unknowns[{i}]', u) for i, u in enumerate(report.get('unknowns') or [], 1)]
    if not entries:
        return []
    groups = {}
    for ref, text in entries:
        hits = [g for g in UNKNOWN_GROUPS if g[2] is None or g[2].search(text)]
        primary, also = hits[0], [g[1] for g in hits[1:] if g[2] is not None]
        groups.setdefault(primary[0], []).append(f'{ref}：{short(text, 120)}' + (f'（也涉及：{"、".join(also)}）' if also else ''))
    lines, options = [], []
    for key, label, _, decision, why in UNKNOWN_GROUPS:
        if key not in groups:
            continue
        lines.append(f'【{label}】{why}')
        lines += groups[key]
        if key == 'backlink':
            pages = [d for _, k, d in ctx['events'] if k == 'offpage']
            if pages:
                lines.append(f'這次 research_offpage 讀了 {len(pages)} 頁，連到目標站 '
                             f'{sum(1 for d in pages if d.get("links_to_target"))} 頁、提及目標網域 '
                             f'{sum(1 for d in pages if d.get("host_mentions"))} 頁')
        options.append((f'{label}：{decision}', None))
    return [item('unknown', 'review', f'未知項 {len(entries)} 項，需要的資料分成 {len(options)} 類',
                 '逐類決定要授權什麼資料，或接受為未知。',
                 '補齊未知項通常需要帳號、付費資料、我方網站資料或法務判斷，都要人授權；各類的原因寫在依據的分類標題。',
                 lines + ['分類依關鍵詞判斷，可能分錯；原文在報告的 unknowns 與 kind=unknown 的主張'],
                 '下次研究仍是未知。', options + [('接受全部為未知', None)])]


def action_items(ctx):
    report, rid, root = ctx['report'] or {}, ctx['run']['id'], ctx['root_cmd']
    labelled = {f['target']: f for f in ctx['feedback']}
    out, rest = [], []
    for i, a in enumerate(report.get('actions') or [], 1):
        text, reason, target = a.get('action', ''), a.get('reason', ''), f'action:{i}'
        m = PRIORITY_TAG.match(text)
        tag = f'P{m.group(1)}' if m else None
        terms = sorted(set(LEGAL.findall(text + ' ' + reason)), key=(text + ' ' + reason).find)
        done = labelled.get(target)
        if tag == 'P0' or terms:
            # P0 is a priority call on our resources; legal terms only mark who must look, so they stay optional.
            why = 'Agent 沒有修改網站或對外發布的工具，建議只能由人執行。'
            if tag == 'P0':
                why += 'Agent 把它排為 P0（最優先），優先順序牽涉我方資源，要人核可。'
            if terms:
                why += f'內容涉及法規或合規（觸發詞：{"、".join(terms)}），要法務或決策者確認。'
            it = item('action', 'decide' if tag == 'P0' else 'review', f'第 {i} 項（需要法務或決策者）：{short(text, 50)}',
                      '交法務或決策者確認後，再決定是否執行。', why,
                      [f'{target}：{text}', f'理由：{reason}'], '不會執行。',
                      [('採納：由人排入工作並執行', None),
                       ('不採納並標註理由（成為之後研究的審查標準）', label_cmd(root, rid, target, 'scope_error'))],
                      target=target, tag=tag, legal_terms=terms)
            if done:
                it['handled'] = f'已由 {done["reviewer"]} 標為 {done["label"]}（{when(done["time"])}）'
            out.append(it)
        else:
            rest.append((i, text, reason, target, done))
    if rest:
        lines = []
        for i, text, reason, target, done in rest:
            lines.append(f'{target}：{text}' + (f'（已由 {done["reviewer"]} 標為 {done["label"]}）' if done else ''))
            lines.append(f'　理由：{reason}')
        it = item('action', 'review', f'其他行動建議 {len(rest)} 項',
                  '逐項決定是否採納並排入工作。',
                  'Agent 沒有修改網站或對外發布的工具，建議只能由人執行；是否值得做是我方的資源取捨。',
                  lines, '不會執行。',
                  [('採納：由人排入工作並執行', None),
                   ('不採納並標註理由（N 換成項次）', label_cmd(root, rid, 'action:N', 'scope_error'))],
                  targets=[r[3] for r in rest])
        if all(r[4] for r in rest):
            it['handled'] = '每一項都已標註'
        out.append(it)
    return out


# Queue ------------------------------------------------------------------------------------------------------------
def build_queue(db_path, run=None, root=None, command_root=None, label=None):
    db_path = Path(db_path)
    ctx = load(db_path, run, root)
    ctx['root_cmd'] = command_root or Path(root or db_path.parent).as_posix()
    ctx['usage'] = usage(ctx)
    items = (preflight_items(ctx) + lesson_change_items(ctx) + memory_items(ctx) + native_learning_items(ctx)
             + lessons_in_use_items(ctx)
             + limit_items(ctx) + rejection_items(ctx) + unknown_items(ctx) + action_items(ctx))
    order = list(PRIORITIES)
    items.sort(key=lambda x: (bool(x.get('handled')), order.index(x['priority'])))  # stable: category order kept
    for n, x in enumerate(items, 1):
        x['id'] = f'H{n}'
    run_row, start, rid, pf = ctx['run'], ctx['start'], ctx['run']['id'], ctx['preflight']
    preflight = None
    if pf:
        actual, expected = set(pf.get('actual_tools') or []), set(pf.get('expected_tools') or [])
        preflight = dict(ready=pf.get('ready'), blocker=pf.get('blocker'), logged_in=pf.get('logged_in'),
                         rate_limited=pf.get('rate_limited'), tools=len(actual), tools_match=actual == expected)
    reviews = [dict(target=f['target'], label=f['label'], reviewer=f['reviewer'], time=f['time'], lesson=f['lesson'])
               for f in ctx['feedback']]
    open_items = [x for x in items if not x.get('handled')]
    return dict(
        schema='handoff-queue/1',
        source=dict(db=label or str(db_path), run=rid,
                    sha256=hashlib.sha256(db_path.read_bytes()).hexdigest() if db_path.exists() else None),
        run=dict(id=rid, host=run_row.get('host'), created=run_row.get('created'), started=bool(start),
                 mode=start.get('mode', run_row.get('mode')), learning=start.get('learning'),
                 keywords=start.get('keywords', []), status=run_row.get('status'),
                 outcome=(ctx['outcome'] or {}).get('state'), hermes_learning=(ctx['outcome'] or {}).get('hermes_learning'),
                 report_accepted=ctx['report_event'] is not None, report_rejections=len(ctx['finish_errors']),
                 preflight=preflight, human_reviews=reviews),
        usage=ctx['usage'],
        summary=dict(by_priority={p: sum(1 for x in open_items if x['priority'] == p) for p in PRIORITIES},
                     by_category={c: dict(items=sum(1 for x in items if x['category'] == c),
                                          decide=sum(1 for x in open_items if x['category'] == c and x['priority'] == 'decide'))
                                  for c in CATEGORIES},
                     handled=len(items) - len(open_items)),
        command_root=ctx['root_cmd'],
        items=items,
        fixed_rules=FIXED_RULES)


# Markdown ---------------------------------------------------------------------------------------------------------
def render_markdown(q):
    r, u, s = q['run'], q['usage'], q['summary']
    lines = [f'# 交還人類清單：run {r["id"][:8]}' + (f'（{r["host"]}）' if r['host'] else ''), '']
    if r['started']:
        facts = [f'研究 `{r["id"]}`，{when(r["created"])} 開始，模式 {r["mode"]}，學習{"開啟" if r["learning"] else "關閉"}']
        if r['hermes_learning'] and r['hermes_learning'] != 'off':
            facts.append(f'Hermes 原生學習 {r["hermes_learning"]}')
        if r['outcome']:
            facts.append(f'結果 {r["outcome"]}')
        facts.append('報告' + ('沒有被接受' if not r['report_accepted'] else
                             ('第一次提交就被接受' if not r['report_rejections'] else f'被退回 {r["report_rejections"]} 次後接受')))
        lines.append('，'.join(facts) + '。')
    else:
        lines.append(f'執行 `{r["id"]}` 沒有進入研究：控制器沒有任何紀錄' + (f'，結果 {r["outcome"]}' if r['outcome'] else '') + '。')
    pf = r['preflight']
    if pf:
        lines.append('開跑前檢查：' + ('通過' if pf['ready'] else f'未通過（{pf["blocker"]}）') +
                     f'，{"已" if pf["logged_in"] else "未"}登入，{"限流中" if pf["rate_limited"] else "未限流"}，'
                     f'工具 {pf["tools"]} 個{"，與預期相同" if pf["tools_match"] else "，與預期不同"}。')
    if r['started']:
        by = u['requests']['by']
        kinds = (('model', '模型直接讀取'), ('offpage', '站外頁')) + (() if u['controller'] else (('controller', '控制器重驗'),))
        split = '、'.join(f'{name} {by[k]}' for k, name in kinds if by[k])
        parts = [f'HTTP 請求 {fmt_use(u["requests"])}' + (f'（{split}）' if split else '')]
        if u['controller']:
            parts.append(f'控制器重驗 {fmt_use(u["controller"])}（另計額度）')
        parts += [f'{BUDGETS[k]} {fmt_use(u[k])}' for k in ('calls', 'searches', 'offpage') if u[k]['limit'] is not None]
        if u['seconds']['limit']:
            parts.append(f'時間上限 {u["seconds"]["limit"]} 秒')
        lines.append('用量：' + '、'.join(parts) + '。')
    for h in r['human_reviews']:
        lines.append(f'人工審查紀錄：{h["target"]} 標為 {LABELS.get(h["label"], h["label"])}（{h["reviewer"]}，{when(h["time"])}）。')
    bp = s['by_priority']
    lines += ['', f'需要決定 {bp["decide"]} 項、視需要處理 {bp["review"]} 項、紀錄 {bp["info"]} 項'
              + (f'、已處理 {s["handled"]} 項' if s['handled'] else '') + '；每一項都寫了不處理時會怎樣。'
              + ('經驗變動在列出時已經生效，人能做的是否決；行動建議、預算、允許網域與資料授權要人決定後才會發生。'
                 if r['started'] else ''), '',
              '| 類別 | 項數 | 需要決定 |', '|---|---:|---:|']
    lines += [f'| {name} | {s["by_category"][c]["items"]} | {s["by_category"][c]["decide"]} |' for c, name in CATEGORIES.items()]
    if any('feedback.py' in (o['command'] or '') for x in q['items'] for o in x['options']):
        lines += ['', f'處理方式裡的 feedback.py 指令會改寫 `{q["command_root"]}` 的帳本：`veto` 永久停用一條經驗，`label` 新增'
                      '一條給之後研究套用的審查標準，`ok` 記錄整份報告已審查。理由最多 200 字，不能含網址或斜線。']
    if any(x['category'] == 'action' for x in q['items']):
        lines.append('行動建議沒有引用欄位；依據的事實要回到報告的主張與 evidence 核對。')
    sections = [(name, [x for x in q['items'] if x['priority'] == p and not x.get('handled')]) for p, name in PRIORITIES.items()]
    sections.append(('已處理', [x for x in q['items'] if x.get('handled')]))
    for name, rows in sections:
        if not rows:
            continue
        lines += ['', f'## {name}']
        for x in rows:
            lines += ['', f'### {x["id"]}｜{CATEGORIES[x["category"]]}｜{x["title"]}', '']
            if x.get('handled'):
                lines.append(f'- **已處理**：{x["handled"]}')
            lines += [f'- **要決定**：{x["decision"]}', f'- **為什麼交給人**：{x["why_human"]}', '- **依據**：']
            lines += [f'  - {e}' for e in x['evidence']]
            lines += [f'- **不處理時**：{x["if_no_action"]}', '- **處理方式**：']
            lines += [f'  - {o["choice"]}' + (f'：`{o["command"]}`' if o['command'] else '') for o in x['options']]
    lines += ['', '## 固定由人決定的事', '',
              '下列事項不論清單內容都由人決定。它們由「只給唯讀工具」與控制器規則實現，不靠模型自律。', '',
              '| 事項 | 怎麼做到 | 程式位置 |', '|---|---|---|']
    lines += [f'| {f["matter"]} | {f["how"]} | {f["where"]} |' for f in q['fixed_rules']]
    sha = q['source']['sha256']
    lines += ['', f'來源：`{q["source"]["db"]}`' + (f'（SHA-256 `{sha}`）' if sha else '（沒有 research.sqlite）') +
              '，由 `scripts/handoff_queue.py` 唯讀產生。']
    return '\n'.join(lines) + '\n'


def main(argv=None):
    p = argparse.ArgumentParser(description='Human handoff queue for one research run (read-only).')
    p.add_argument('path', help='run root directory or its research.sqlite')
    p.add_argument('--run', help='run id or unique prefix; default: the latest run')
    p.add_argument('--out', help='directory for <run>-handoff.md and <run>-handoff.json')
    p.add_argument('--json', action='store_true', help='print JSON instead of Markdown when --out is not given')
    p.add_argument('--command-root', help='--root shown in the feedback.py commands; default: the run root')
    a = p.parse_args(argv)
    db_path, root = locate(a.path)
    if not root.is_dir():
        p.error(f'no run folder at {a.path}')
    shown_root = Path(a.path) if Path(a.path).is_dir() else Path(a.path).parent  # as typed, for copy-paste
    try:
        q = build_queue(db_path, a.run, root, a.command_root or shown_root.as_posix(), label=Path(a.path).as_posix())
    except ValueError as e:
        p.error(str(e))
    md, js = render_markdown(q), json.dumps(q, ensure_ascii=False, indent=2) + '\n'
    if a.out:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / f'{q["run"]["id"]}-handoff.md').write_text(md, encoding='utf-8')
        (out / f'{q["run"]["id"]}-handoff.json').write_text(js, encoding='utf-8')
        print(out / f'{q["run"]["id"]}-handoff.md')
    else:
        sys.stdout.buffer.write((js if a.json else md).encode('utf-8'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
