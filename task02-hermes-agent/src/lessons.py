"""Lessons ledger. Only controller measurements and human review create or change lessons.

The model has no write path here: lessons are built from controller events, HTTP status, titles and
human input, never from report claims or page instructions. (The v0.9 research memory, src/research_memory.py,
keeps re-checkable report findings in the same table under kind "finding"; applicable() never shows them.) Lesson keys come from fixed lists, so
page or model text cannot name a lesson. Every lesson keeps its source runs, evidence ids and a
status history so a wrong lesson can be traced, revoked or vetoed.
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlsplit
import json, re, uuid

TTL = timedelta(days=7)
# Deterministic controller rejections caused by the model's own choice. Infrastructure noise
# (transport errors, DNS, unknown robots, budgets) is not a lesson about research method.
RULES = {
    'error_is_not_page_content': '引用非 200 來源（失敗頁或失敗搜尋）只能放在 topic=access 的主張',
    'claim_needs_evidence': 'observation/inference 必須引用本輪 evidence_ids',
    'cross_run_citation': '只能引用本輪取得的證據',
    'unknown_evidence': '引用的 evidence_id 不存在',
    'claim_schema': '每項主張需有 text 與 kind（observation、inference 或 unknown）',
    'report_schema': '報告需有 claims 與 actions 兩個清單',
    'action_schema': '每項行動需有 action 與 reason',
    'host_not_allowed': 'research_fetch 只能讀允許清單內的 host；站外頁改用 research_offpage（限本輪搜尋結果列出的網址）',
    'robots_disallow': 'robots.txt 禁止的路徑不能抓取',
    'https_only': '只能讀 https 網址',
    'private_address': '不能讀私人或本機位址',
    'unsupported_content_type': '只能讀文字、HTML、XML 或 JSON',
    'section_invalid': '主張的 section 只能是 on_page、off_page 或 other',
    'section_missing': '報告需至少各有一項 on_page 與 off_page 主張；沒有站外證據時寫 off_page 的 unknown',
    'offpage_not_from_search': 'research_offpage 只能讀本輪 research_search 結果列出的站外網址',
    'offpage_target_host': '目標站本身用 research_fetch 讀，不用 research_offpage',
    'offpage_query_required': '站外頁快照用 research_evidence 讀取時要帶 query，只回傳片段',
}
# Shown before a human review lesson: it is a standard to apply, not a past finding to re-check.
FEEDBACK_PREFIX = '審查標準（寫本輪主張時套用；原句是過去被標註的例子，不需重查）：'
LABELS = {'unsupported': '證據不支持', 'scope_error': '範圍錯誤', 'reviewed_ok': '已審查無問題'}
# Feedback must not hand the agent answers it did not find: no URL and no slash next to text.
ANSWER_LEAK = re.compile(r'https?://|www\.|\w[/／]|[/／]\w', re.I)
SPLIT = re.compile(r'[\s｜|\-–—:：/]+')
ARCHIVE_SEGMENTS = {'search', 'tag', 'tags'}  # listing pages that echo the keyword
SCHEMA = '''
CREATE TABLE IF NOT EXISTS lessons(id TEXT PRIMARY KEY,kind TEXT,key TEXT UNIQUE,host TEXT,scope TEXT,status TEXT,
  statement TEXT,data TEXT,updated TEXT,expires TEXT);
CREATE TABLE IF NOT EXISTS lesson_support(id INTEGER PRIMARY KEY,lesson TEXT,run TEXT,host TEXT,polarity INTEGER,
  evidence TEXT,time TEXT,epoch INTEGER);
CREATE TABLE IF NOT EXISTS lesson_history(id INTEGER PRIMARY KEY,lesson TEXT,time TEXT,old TEXT,new TEXT,actor TEXT,
  run TEXT,reason TEXT);
CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY,time TEXT,run TEXT,target TEXT,label TEXT,reason TEXT,
  scope TEXT,reviewer TEXT,lesson TEXT);
'''


def keyword_page(url, title, h1, keyword):
    """A keyword's own page: exact URL slug or an exact title/H1 segment.

    Plain containment would also accept brand pages such as 富遊娛樂城 for 娛樂城. Pages whose URL
    query carries the keyword, and search or tag listings, only echo the requested term.
    """
    k = keyword.casefold()
    parts = urlsplit(url)
    segments = [s.casefold() for s in unquote(parts.path).split('/') if s]
    if k in unquote(parts.query).casefold() or ARCHIVE_SEGMENTS & set(segments[:-1]):
        return False
    return (segments[-1:] == [k]) or k in {t.casefold() for t in SPLIT.split(f'{title or ""} {h1 or ""}') if t}


def classify_search(result):
    """ok: at least one result with a URL; no_results: the index answered with nothing; error: timeout or failure."""
    data = result.get('data') if isinstance(result, dict) else None
    web = data.get('web') if isinstance(data, dict) else None
    if result.get('success') and any(isinstance(w, dict) and w.get('url') for w in web or []):
        return 'ok'
    if result.get('success') or 'no results' in str(result.get('error', '')).casefold():
        return 'no_results'
    return 'error'


def norm_url(url):
    return unquote(url).rstrip('/').casefold()


SITE_OPERATOR = re.compile(r'(?<![-\w])site:', re.I)  # site:host, not the -site:host exclusion


def search_feature(query):
    return 'site_operator' if SITE_OPERATOR.search(query) else 'plain'


class Ledger:
    def __init__(self, db, clock=None):
        self.db = db
        self.now = clock or (lambda: datetime.now(timezone.utc))
        self.batch = False
        db.executescript(SCHEMA)

    def commit(self):
        if not self.batch:
            self.db.commit()

    def ts(self):
        return self.now().isoformat()

    def _row(self, r):
        return dict(r, data=json.loads(r['data'])) if r else None

    def get(self, lesson_id):
        return self._row(self.db.execute('SELECT * FROM lessons WHERE id=?', (lesson_id,)).fetchone())

    def by_key(self, key):
        return self._row(self.db.execute('SELECT * FROM lessons WHERE key=?', (key,)).fetchone())

    def _set(self, lesson, status, actor, run, reason, **fields):
        fields.update(status=status, updated=self.ts())
        if 'data' in fields:
            fields['data'] = json.dumps(fields['data'], ensure_ascii=False)
        self.db.execute('UPDATE lessons SET ' + ','.join(f'{k}=?' for k in fields) + ' WHERE id=?',
                        (*fields.values(), lesson['id']))
        if lesson['status'] != status:
            self.db.execute('INSERT INTO lesson_history(lesson,time,old,new,actor,run,reason) VALUES(?,?,?,?,?,?,?)',
                            (lesson['id'], self.ts(), lesson['status'], status, actor, run, reason))
        self.commit()

    def _create(self, kind, key, host, scope, status, actor, run, reason, statement='', data=None, expires=None):
        lid = uuid.uuid4().hex[:12]
        self.db.execute('INSERT INTO lessons VALUES(?,?,?,?,?,?,?,?,?,?)', (lid, kind, key, host, scope, status, statement,
                        json.dumps(data or {}, ensure_ascii=False), self.ts(), expires))
        self.db.execute('INSERT INTO lesson_history(lesson,time,old,new,actor,run,reason) VALUES(?,?,?,?,?,?,?)',
                        (lid, self.ts(), None, status, actor, run, reason))
        self.commit()
        return self.get(lid)

    def _support(self, lesson, run, host, polarity, evidence):
        # epoch rises on each revocation or expiry, so only support gathered afterwards can re-activate a lesson.
        self.db.execute('INSERT INTO lesson_support(lesson,run,host,polarity,evidence,time,epoch) VALUES(?,?,?,?,?,?,?)',
                        (lesson['id'], run, host, polarity, json.dumps(evidence, ensure_ascii=False), self.ts(),
                         lesson['data'].get('epoch', 0)))

    def _retire(self, lesson, status, actor, run, reason, data=None):
        data = dict(data or lesson['data'])
        data['epoch'] = data.get('epoch', 0) + 1
        self._set(lesson, status, actor, run, reason, data=data)

    def _expire_if_due(self, lesson, run):
        if lesson['status'] in ('candidate', 'active') and lesson['expires'] and lesson['expires'] <= self.ts():
            self._retire(lesson, 'expired', 'controller', run, 'TTL reached without new support')
            return self.get(lesson['id'])
        return lesson

    def _runs(self, lesson):
        return self.db.execute('SELECT DISTINCT run,host FROM lesson_support WHERE lesson=? AND polarity=1 AND epoch=?',
                               (lesson['id'], lesson['data'].get('epoch', 0))).fetchall()

    # Learning from one completed run -------------------------------------------------
    def learn_from_run(self, run, host, keywords, page_info):
        """Record measured failures and verified discovery paths of `run` in one transaction; return the changes."""
        self.batch = True
        try:
            changes = self._learn(run, host, keywords, page_info)
            self.db.commit()
            return changes
        except Exception:
            self.db.rollback()  # a failed learning step leaves the ledger as it was
            raise
        finally:
            self.batch = False

    def _learn(self, run, host, keywords, page_info):
        changes = []
        events = [(i, k, json.loads(d)) for i, k, d in
                  self.db.execute('SELECT id,kind,data FROM events WHERE run=? ORDER BY id', (run,))]
        obs = {}
        for eid, kind, d in events:
            if kind == 'search_response':
                info = page_info(d.get('evidence_id')) or {}
                outcome = info.get('search_outcome') or ('ok' if d.get('status') == 200 else 'error')
                if outcome != 'error':  # timeouts and rate limits are infrastructure, not method
                    o = obs.setdefault(('research_search', search_feature(d.get('query', ''))), dict(fail=[], ok=[]))
                    o['ok' if outcome == 'ok' else 'fail'].append(d.get('evidence_id'))
            elif kind == 'tool_error' and d.get('error_type') == 'Failure':
                code = str(d.get('error', '')).split(':')[0]
                if code in RULES:
                    obs.setdefault((d.get('name'), code), dict(fail=[], ok=[]))['fail'].append(f'event:{eid}')
        for (tool, feature), o in obs.items():
            key = f'failure|{tool}|{feature}'
            lesson = self.by_key(key)
            if not lesson and not o['fail']:
                continue  # successes alone never create a lesson
            if not lesson:
                lesson = self._create('failure_pattern', key, host, 'host', 'candidate', 'controller', run,
                                      'first measured failure', data=dict(tool=tool, feature=feature, fails=0,
                                                                          alternative=[0, 0]))
            lesson = self._expire_if_due(lesson, run)
            if o['fail']:
                self._support(lesson, run, host, 1, o['fail'])
            if o['ok']:
                self._support(lesson, run, host, -1, o['ok'])
            changes.append(self._update_failure(self.get(lesson['id']), run, o, obs.get(('research_search', 'plain'))))
        changes += self._learn_discovery(events, run, host, keywords, page_info)
        self.commit()
        return [c for c in changes if c]

    def _update_failure(self, lesson, run, o, plain):
        data = lesson['data']
        data['fails'] += len(o['fail'])
        if lesson['key'].endswith('|site_operator') and plain and o['fail']:
            data['alternative'] = [data['alternative'][0] + len(plain['ok']),
                                   data['alternative'][1] + len(plain['ok']) + len(plain['fail'])]
        if lesson['status'] == 'vetoed':  # a human veto is final; keep counting evidence only
            self._set(lesson, 'vetoed', 'controller', run, '', data=data)
            return None
        if o['ok']:
            reason = f'counterexample: {len(o["ok"])} successful call(s) with feature {data["feature"]} in run {run}'
            self._retire(lesson, 'revoked', 'controller', run, reason, data)
            return dict(lesson=lesson['id'], key=lesson['key'], status='revoked', reason=reason)
        rows = self._runs(lesson)
        runs, hosts = sorted({r[0] for r in rows}), sorted({r[1] for r in rows})
        data.update(runs=runs, hosts=hosts)
        status = 'active' if len(runs) >= 2 else 'candidate'
        scope = 'general' if len(hosts) >= 2 else 'host'
        reason = f'{len(runs)} run(s) reproduced {lesson["key"]} on {len(hosts)} host(s)'
        self._set(lesson, status, 'controller', run, reason, data=data, scope=scope,
                  statement=failure_statement(data), expires=(self.now() + TTL).isoformat())
        return dict(lesson=lesson['id'], key=lesson['key'], status=status, reason=reason)

    def _learn_discovery(self, events, run, host, keywords, page_info):
        # Only pages the model itself fetched count; controller re-verification must not confirm its own lesson.
        model_ids = {d.get('evidence_id') for _, k, d in events if k == 'response' and d.get('actor', 'model') == 'model'}
        search_ids = {d.get('evidence_id') for _, k, d in events if k == 'search_response'}
        order = [r[0] for r in self.db.execute('SELECT id FROM evidence WHERE run=? ORDER BY rowid', (run,))
                 if r[0] in model_ids | search_ids]
        pages = {e: p for e, p in ((e, page_info(e)) for e in order) if p}
        sitemaps = [p for p in pages.values() if p['kind'] == 'sitemap']
        changes = []
        for k in keywords:
            hit = next((e for e in order if e in pages and pages[e]['kind'] == 'html'
                        and urlsplit(pages[e]['url']).hostname == host
                        and keyword_page(pages[e]['url'], pages[e]['title'], pages[e]['h1'], k)), None)
            if not hit:
                continue  # only a page the model read with HTTP 200 and a matching title/H1 teaches a path
            target = pages[hit]
            # The entry page must be on the same host: an off-site page linking in is not a discovery path.
            source = next(((e, text) for e in order[:order.index(hit)] if e in pages
                           and urlsplit(pages[e]['url']).hostname == host
                           for u, text in pages[e]['anchors'] if norm_url(u) == norm_url(target['url'])), None)
            data = dict(keyword=k, target_url=target['url'], evidence_id=hit, title=target['title'][:120],
                        h1=target['h1'][:120], source_url=pages[source[0]]['url'] if source else None,
                        source_kind=pages[source[0]]['kind'] if source else 'typed_or_memory',
                        anchor=(source[1] or '')[:60] if source else None, sitemaps_checked=len(sitemaps),
                        sitemaps_listing_target=sum(norm_url(target['url']) in {norm_url(u) for u in s['locs']}
                                                    for s in sitemaps))
            key = f'discovery|{host}|{k.casefold()}'
            lesson = self.by_key(key) or self._create('discovery_path', key, host, 'host', 'candidate', 'controller',
                                                      run, 'target page read')
            self._support(lesson, run, host, 1, [hit])
            status = 'vetoed' if lesson['status'] == 'vetoed' else 'active'
            reason = f'run {run} read {k} page: HTTP 200 and title/H1 match'
            self._set(lesson, status, 'controller', run, reason, data=dict(data, epoch=lesson['data'].get('epoch', 0)),
                      statement=discovery_statement(host, data), expires=(self.now() + TTL).isoformat())
            changes.append(dict(lesson=lesson['id'], key=key, status=status, reason=reason))
        return changes

    # Presenting lessons to the next run ----------------------------------------------
    def applicable(self, host, verify, persist=True, max_verify=4):
        """Lessons for `host`. Discovery paths are re-fetched before use; failed checks revoke them."""
        out, verified = [], 0
        rows = self.db.execute('SELECT * FROM lessons WHERE status="active" ORDER BY kind,key').fetchall()
        for lesson in map(self._row, rows):
            if lesson['kind'] == 'finding':
                continue  # research memory findings are re-verified and shown by src/research_memory.py
            if lesson['expires'] and lesson['expires'] <= self.ts():
                if persist:
                    self._retire(lesson, 'expired', 'controller', None, 'TTL reached without new support')
                continue
            item = dict(id=lesson['id'], key=lesson['key'], kind=lesson['kind'], statement=lesson['statement'],
                        expires=lesson['expires'], support_runs=len(self._runs(lesson)))
            if lesson['kind'] == 'discovery_path':
                if lesson['host'] != host or verified >= max_verify:
                    continue
                verified += 1
                result, reason, evidence_id = verify(lesson)
                if result == 'fail':
                    if persist:
                        self._retire(lesson, 'revoked', 'controller', None, 're-verification failed: ' + reason)
                    continue
                if result == 'ok' and persist:
                    self._set(lesson, 'active', 'controller', None, '', expires=(self.now() + TTL).isoformat())
                # Rendered now from data and this run's check, so lessons stored by older versions never show
                # past findings (sitemap counts, anchor text) that the model would have to re-verify to cite.
                item.update(applies='this_host', verification=dict(result=result, reason=reason, evidence_id=evidence_id),
                            statement=discovery_guidance(lesson['data'], result, reason, evidence_id))
            elif lesson['kind'] == 'failure_pattern':
                hosts = lesson['data'].get('hosts', [])
                item['applies'] = 'general' if lesson['scope'] == 'general' else (
                    'this_host' if host in hosts else 'transfer_hint: observed only on ' + ', '.join(hosts) + '; verify here')
                hint = (f'只在 {"、".join(hosts)} 觀察到，這個網站還沒驗證過；可先少量試用再決定：'
                        if item['applies'].startswith('transfer_hint') else '')
                item['statement'] = hint + failure_statement(lesson['data'])
            elif lesson['scope'] == 'general' or lesson['host'] == host:
                item['applies'] = lesson['scope']
                if lesson['kind'] == 'human_feedback':
                    item['statement'] = FEEDBACK_PREFIX + lesson['statement']
            else:
                continue
            out.append(item)
        return out

    # Human review ---------------------------------------------------------------------
    def add_feedback(self, run, target, label, reason, reviewer, scope='host'):
        if label not in LABELS:
            raise ValueError('label must be one of ' + ', '.join(LABELS))
        if scope not in ('host', 'general') or not reviewer:
            raise ValueError('scope must be host or general; reviewer is required')
        reason = (reason or '').strip()
        if label != 'reviewed_ok' and not reason:
            raise ValueError('reason is required')
        if len(reason) > 200 or ANSWER_LEAK.search(reason):
            raise ValueError('reason must be at most 200 characters and contain no URL, path or slash')
        run_row = self.db.execute('SELECT host FROM runs WHERE id=?', (run,)).fetchone()
        report = self.db.execute('SELECT data FROM events WHERE run=? AND kind="report" ORDER BY id DESC', (run,)).fetchone()
        if not run_row or not report:
            raise ValueError('run has no accepted report')
        prefix = f'feedback|{run}|{target}|{label}'
        same = self.db.execute('SELECT status FROM lessons WHERE key LIKE ?', (prefix + '%',)).fetchall()
        if label != 'reviewed_ok' and any(r[0] != 'vetoed' for r in same):
            raise ValueError('this item already has this label; veto that lesson first to replace it')
        key = f'{prefix}|{len(same) + 1}'
        lesson_id = None
        if label != 'reviewed_ok':
            text = report_item(json.loads(report[0]), target)
            statement = (f'人工審查（{reviewer}）把 run {run[:8]} 的 {target} 標為「{LABELS[label]}」：{reason}。'
                         f'該項原文：「{text[:160]}」')
            lesson_id = self._create('human_feedback', key, run_row[0], scope, 'active', 'human:' + reviewer, run,
                                     reason, statement, dict(target=target, label=label, run=run))['id']
        self.db.execute('INSERT INTO feedback(time,run,target,label,reason,scope,reviewer,lesson) VALUES(?,?,?,?,?,?,?,?)',
                        (self.ts(), run, target, label, reason, scope, reviewer, lesson_id))
        self.commit()
        return lesson_id

    def veto(self, lesson_id, reason, reviewer):
        lesson = self.get(lesson_id)
        if not lesson or not reason or not reviewer:
            raise ValueError('existing lesson, reason and reviewer are required')
        self._set(lesson, 'vetoed', 'human:' + reviewer, None, reason)

    def export(self):
        lessons = [dict(self._row(r), history=[dict(h) for h in self.db.execute(
            'SELECT time,old,new,actor,run,reason FROM lesson_history WHERE lesson=? ORDER BY id', (r['id'],))])
            for r in self.db.execute('SELECT * FROM lessons ORDER BY kind,key')]
        return dict(lessons=lessons, feedback=[dict(r) for r in self.db.execute('SELECT * FROM feedback ORDER BY id')])


def report_item(report, target):
    kind, _, number = target.partition(':')
    items = report.get({'claim': 'claims', 'action': 'actions'}.get(kind, ''), [])
    if not number.isdigit() or not 1 <= int(number) <= len(items):
        raise ValueError('target must be claim:N or action:N from the run report (1-based)')
    item = items[int(number) - 1]
    return str(item.get('text') or item.get('action') or '')


# Statements say what to do next. Past findings (page facts, sitemap counts) stay in the lesson data for audit:
# the report may cite only this run's evidence, so a finding inside a lesson invites re-checking it.
def failure_statement(d):
    runs, hosts = len(d.get('runs', [])), '、'.join(d.get('hosts', []))
    if d['tool'] == 'research_search' and d['feature'] == 'site_operator':
        alt = (f'；同批不含 site: 的查詢 {d["alternative"][0]}/{d["alternative"][1]} 次有結果'
               if d['alternative'][1] else '')
        return (f'research_search 不要用 site:，改用不含 site: 的查詢（{runs} 個 run 共 {d["fails"]} 次沒有結果{alt}）。'
                f'觀察站點：{hosts}。')
    if d['tool'] == 'research_search':
        return (f'不含 site: 的 research_search 在 {runs} 個 run 共 {d["fails"]} 次沒有結果：換詞組或縮短查詢，'
                f'不要重送同一查詢。觀察站點：{hosts}。')
    return (f'遵守：{RULES[d["feature"]]}（{runs} 個 run 中 {d["tool"]} 共 {d["fails"]} 次因此被控制器拒絕）。'
            f'觀察站點：{hosts}。')


def discovery_statement(host, d):
    return f'{host} 的「{d["keyword"]}」目標頁：{d["target_url"]}（讀到時 HTTP 200，title/H1 符合）。'


def discovery_guidance(d, result, reason, evidence_id):
    """What the model should do with a discovery path, given the controller's check in this run."""
    if result == 'ok':
        return (f'「{d["keyword"]}」目標頁 {d["target_url"]}：控制器已在本輪開始時重抓，HTTP 200 且 title/H1 符合'
                f'（evidence_id {evidence_id}）。這是本輪證據：直接用 research_evidence 讀取與引用，不必重新 fetch 或另行確認。')
    return (f'「{d["keyword"]}」目標頁上次位於 {d["target_url"]}；控制器本輪重抓沒有確認（{reason}）。'
            '需要時用 research_fetch 讀這個網址。')
