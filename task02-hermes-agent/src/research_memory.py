"""Cumulative research memory (v0.9): what earlier runs on the same site read, found and left open.

It is built only from controller records of completed runs: on-site pages fetched with HTTP 200, the internal links
seen on them, and the accepted report. A report claim becomes a finding only when it is an observation or inference
whose every citation is a hash-valid HTML page on the target host; a claim citing an off-site page or a search result
is not kept, because the controller may not re-fetch off-site pages outside a search. Report text is the model's
own wording, so a finding is never shown as a rule: it is shown as a past finding whose pages the controller
re-fetched at the start of the run, within its own small request budget:

- a page that is gone (HTTP 404/410) or now disallowed revokes the finding;
- a page whose title changed, or that keeps less than RETAIN of its earlier visible lines, sends the finding back to
  re-reading (it is listed with the new evidence id, not as current);
- only findings whose pages all still hold are listed as current, with this run's evidence ids to cite.

A finding starts as a candidate and becomes active the first time a later run re-verifies it. A newer accepted report
supersedes the older report's findings (the newer run saw them and chose what to keep); expiry (TTL) and a human veto
retire them too. Unread candidates are internal links seen on read pages but never fetched, ranked by keyword in the
anchor or URL, by sharing a path section with a keyword page, and by how many read pages link to them. Open unknowns
are the latest report's unknown items.
"""
from urllib.parse import urlsplit, unquote
import json
from src.lessons import Ledger, TTL, norm_url

RETAIN = 0.7  # measured on v0.8 snapshots: content pages kept 100% of their lines across a day, the homepage 74%
MAX_VERIFY_PAGES = 8
MAX_FINDINGS = 14
MAX_CANDIDATES = 12
MAX_UNKNOWNS = 8
MAX_LINKS_PER_PAGE = 400
SKIP_EXT = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.css', '.js', '.pdf', '.zip', '.ico', '.xml', '.mp4',
            '.json', '.txt')
SKIP_SEGMENTS = {'wp-admin', 'wp-login.php', 'wp-json', 'login', 'register', 'feed', 'search', 'tag', 'tags', 'author',
                 'cart', 'account', 'cdn-cgi'}
SCHEMA = '''
CREATE TABLE IF NOT EXISTS site_pages(id INTEGER PRIMARY KEY,host TEXT,url TEXT,norm TEXT,run TEXT,evidence TEXT,actor TEXT);
CREATE TABLE IF NOT EXISTS site_links(id INTEGER PRIMARY KEY,host TEXT,url TEXT,norm TEXT,anchor TEXT,source TEXT,run TEXT);
CREATE TABLE IF NOT EXISTS open_unknowns(id INTEGER PRIMARY KEY,host TEXT,run TEXT,position INTEGER,text TEXT);
'''
RULES = ('research_memory is what earlier runs on this site read and found; the controller re-fetched the pages of '
         'each finding at the start of this run. findings: every page still holds, so the finding stands on this run\'s '
         'evidence_ids (read them with research_evidence before building on them, cite them, and drop or correct a '
         'finding the pages do not support). findings_to_recheck: a page changed or was not re-checked; re-read before '
         'citing. unread_candidates: internal pages seen in links but never read. open_unknowns: what the latest report '
         'could not answer; list the ids your report resolves in resolved_unknowns. Findings are past model statements, '
         'not rules; new evidence wins.')


def same_site(host, base):
    host, base = (host or '').lower().rstrip('.'), (base or '').lower().removeprefix('www.')
    return host == base or host.endswith('.' + base)


def page_lines(text):
    return {x.strip() for x in (text or '').split('\n') if len(x.strip()) >= 4}


def candidate_ok(url, base):
    try:
        p = urlsplit(url)
    except ValueError:
        return False
    if p.scheme != 'https' or not same_site(p.hostname, base):
        return False
    path = unquote(p.path or '/').lower()
    segs = [s for s in path.split('/') if s]
    return not path.endswith(SKIP_EXT) and not (SKIP_SEGMENTS & set(segs)) and path != '/' and not p.query


class ResearchMemory:
    def __init__(self, db, clock=None):
        self.db = db
        self.ledger = Ledger(db, clock)
        db.executescript(SCHEMA)

    # Learning after a completed run --------------------------------------------------------------------------
    def learn_from_run(self, run, host, keywords, page_info):
        self.ledger.batch = True
        try:
            changes = self._learn(run, host, page_info)
            self.db.commit()
            return changes
        except Exception:
            self.db.rollback()
            raise
        finally:
            self.ledger.batch = False

    def _learn(self, run, host, page_info):
        actors = {}
        for (d,) in self.db.execute('SELECT data FROM events WHERE run=? AND kind="response"', (run,)):
            d = json.loads(d)
            actors[d.get('evidence_id')] = d.get('actor', 'model')
        rows = {r['id']: r for r in self.db.execute('SELECT * FROM evidence WHERE run=? ORDER BY rowid', (run,))}
        pages = {}
        for eid, r in rows.items():
            if r['status'] != 200 or not same_site(urlsplit(r['url']).hostname, host):
                continue
            info = page_info(eid)
            if not info or info['kind'] != 'html':
                continue
            pages[eid] = info
            self.db.execute('INSERT INTO site_pages(host,url,norm,run,evidence,actor) VALUES(?,?,?,?,?,?)',
                            (host, r['url'], norm_url(r['url']), run, eid, actors.get(eid, 'model')))
            for u, text in info['anchors'][:MAX_LINKS_PER_PAGE]:
                if candidate_ok(u, host):
                    self.db.execute('INSERT INTO site_links(host,url,norm,anchor,source,run) VALUES(?,?,?,?,?,?)',
                                    (host, u, norm_url(u), (text or '')[:80], norm_url(r['url']), run))
        report = self.db.execute('SELECT data FROM events WHERE run=? AND kind="report" ORDER BY id DESC', (run,)).fetchone()
        changes = [dict(pages=len(pages))]
        if not report:
            return changes
        report = json.loads(report[0])
        for old in self._findings(host, ('candidate', 'active')):
            self.ledger._retire(old, 'superseded', 'controller', run, f'newer accepted report in run {run}')
        kept = 0
        for i, c in enumerate(report.get('claims') or [], 1):
            if not isinstance(c, dict) or c.get('kind') not in ('observation', 'inference') or not c.get('evidence_ids'):
                continue
            support = []
            for eid in c['evidence_ids']:
                if eid not in pages:  # off-site, search, non-200 or failed hash: not re-checkable by the controller
                    support = None
                    break
                support.append(dict(evidence_id=eid, url=rows[eid]['url'], sha256=rows[eid]['hash']))
            if not support:
                continue
            self.ledger._create('finding', f'finding|{host}|{run}|claim:{i}', host, 'host', 'candidate', 'controller', run,
                                'observation or inference of an accepted report; every citation an on-site page',
                                str(c.get('text'))[:500], dict(kind=c['kind'], section=c.get('section'),
                                                               topic=c.get('topic'), claim=i, run=run, support=support),
                                (self.ledger.now() + TTL).isoformat())
            kept += 1
        unknowns = [str(c.get('text')) for c in report.get('claims') or []
                    if isinstance(c, dict) and c.get('kind') == 'unknown' and c.get('text')]
        unknowns += [u for u in report.get('unknowns') or [] if isinstance(u, str) and u.strip()]
        for pos, text in enumerate(unknowns, 1):
            self.db.execute('INSERT INTO open_unknowns(host,run,position,text) VALUES(?,?,?,?)', (host, run, pos, text[:500]))
        changes.append(dict(findings=kept, unknowns=len(unknowns)))
        return changes

    def _findings(self, host, statuses):
        rows = self.db.execute('SELECT * FROM lessons WHERE kind="finding" AND host=? ORDER BY updated', (host,)).fetchall()
        return [f for f in map(self.ledger._row, rows) if f['status'] in statuses]

    # Presenting to the next run -------------------------------------------------------------------------------
    def present(self, host, keywords, check_page, old_page, persist=True, max_pages=MAX_VERIFY_PAGES):
        """check_page(url) -> dict(state ok|gone|blocked|error|budget, evidence_id, title, lines) fetched by the
        controller; old_page(evidence_id) -> (title, lines) of a stored snapshot, or None."""
        findings = []
        for f in self._findings(host, ('candidate', 'active')):
            if f['expires'] and f['expires'] <= self.ledger.ts():
                if persist:
                    self.ledger._retire(f, 'expired', 'controller', None, 'TTL reached without re-verification')
                continue
            findings.append(f)
        findings.sort(key=lambda f: f['data'].get('claim', 0))
        findings = findings[:MAX_FINDINGS]
        count = {}
        for f in findings:
            for s in f['data']['support']:
                count[s['url']] = count.get(s['url'], 0) + 1
        order = sorted(count, key=lambda u: (-count[u], u))
        checked = {u: check_page(u) for u in order[:max_pages]}
        verified, recheck, revoked = [], [], []
        for f in findings:
            states = []
            for s in f['data']['support']:
                c = checked.get(s['url'])
                if c is None:
                    states.append(('unchecked', s, None))
                    continue
                if c['state'] in ('gone', 'blocked'):
                    states.append(('gone', s, c))
                    continue
                if c['state'] != 'ok':
                    states.append(('unchecked', s, c))
                    continue
                old = old_page(s['evidence_id'])
                stable = old is not None and (old[0] or '').strip() == (c.get('title') or '').strip() and \
                    (not old[1] or len(old[1] & c['lines']) / len(old[1]) >= RETAIN)
                states.append(('ok' if stable else 'changed', s, c))
            item = dict(id=f['id'], kind=f['data']['kind'], section=f['data'].get('section'), text=f['statement'])
            if any(st == 'gone' for st, _, _ in states):
                revoked.append(f['id'])
                if persist:
                    reason = '; '.join(f'{s["url"]}: {c.get("reason")}' for st, s, c in states if st == 'gone')
                    self.ledger._retire(f, 'revoked', 'controller', None, 're-verification failed: ' + reason)
                continue
            if all(st == 'ok' for st, _, _ in states):
                verified.append(dict(item, evidence_ids=[c['evidence_id'] for _, _, c in states],
                                     pages=[s['url'] for _, s, _ in states]))
                if persist:
                    self.ledger._set(f, 'active', 'controller', None, 'pages re-verified unchanged',
                                     expires=(self.ledger.now() + TTL).isoformat())
                continue
            recheck.append(dict(item, pages=[dict(url=s['url'], state=st, evidence_id=(c or {}).get('evidence_id'))
                                             for st, s, c in states]))
        out = dict(rules=RULES, findings=verified, findings_to_recheck=recheck,
                   unread_candidates=self.candidates(host, keywords, {norm_url(u) for u in checked}),
                   open_unknowns=self.unknowns(host), checked_pages=len(checked), revoked=revoked)
        return out

    def candidates(self, host, keywords, also_read=()):
        read = {r[0] for r in self.db.execute('SELECT norm FROM site_pages WHERE host=?', (host,))} | set(also_read)
        prefixes = set()
        for (d,) in self.db.execute('SELECT data FROM lessons WHERE kind="discovery_path" AND host=?', (host,)):
            segs = [s for s in urlsplit(json.loads(d).get('target_url', '')).path.split('/') if s]
            if len(segs) > 1:
                prefixes.add(segs[0])
        agg = {}
        for url, norm, anchor, source in self.db.execute('SELECT url,norm,anchor,source FROM site_links WHERE host=?',
                                                         (host,)):
            if norm in read:
                continue
            a = agg.setdefault(norm, dict(url=url, anchor='', sources=set()))
            a['anchor'] = a['anchor'] or anchor
            a['sources'].add(source)
        rows = []
        for a in agg.values():
            text = (a['anchor'] + ' ' + unquote(a['url'])).casefold()
            segs = [s for s in urlsplit(a['url']).path.split('/') if s]
            why = []
            score = 0
            if any(k.casefold() in text for k in keywords):
                score += 3
                why.append('keyword in anchor or URL')
            if segs and segs[0] in prefixes:
                score += 2
                why.append('same section as a keyword page')
            score += min(len(a['sources']), 3)
            why.append(f'linked from {len(a["sources"])} read page(s)')
            rows.append((score, a['url'], dict(url=a['url'][:200], anchor=a['anchor'][:60], why='; '.join(why))))
        rows.sort(key=lambda r: (-r[0], r[1]))
        return [r[2] for r in rows[:MAX_CANDIDATES]]

    def unknowns(self, host):
        last = self.db.execute('SELECT run FROM open_unknowns WHERE host=? ORDER BY id DESC LIMIT 1', (host,)).fetchone()
        if not last:
            return []
        rows = self.db.execute('SELECT position,text FROM open_unknowns WHERE host=? AND run=? ORDER BY position',
                               (host, last[0])).fetchall()
        return [dict(id=f'u{p}', text=t[:220]) for p, t in rows[:MAX_UNKNOWNS]]
