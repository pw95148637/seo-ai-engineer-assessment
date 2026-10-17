"""v0.7 pre-registered evaluation: off-page research and rewritten lesson guidance.

python scripts/evaluate_v07.py --make-plan --model gpt-6.1-sol   # once, before any v0.7 model run
python scripts/evaluate_v07.py --verify                          # plan hash, code fingerprint, v0.6 ledger hash
python scripts/evaluate_v07.py --step R4 [--dry-run] [--retry]   # steps in plan order
python scripts/evaluate_v07.py --compare                         # verdict from scores and blind review

Both arms run v0.7 code. R4 starts from a copy of the frozen v0.6 ledger; B2 starts from an empty one.
v0.6 plans, runs and scores are read only to copy that ledger and pick the holdout; they are not v0.7 data.
"""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
import argparse, hashlib, json, sqlite3, subprocess, sys, tempfile
TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK))
from src.research_core import Research, Failure
from src.scoring import open_ro, score_run, write_blind_packet, RUBRIC
from src.lessons import Ledger

PLAN, OUT = 'evaluation/plan-v07.json', 'evaluation/v07'
V06_PLAN, V06_HOLDOUT = 'evaluation/plan-v06.json', 'evaluation/v06/holdout-choice.json'
LEDGER_SOURCE = 'evaluation/v06/runs/2030-series'
HERMES_COMMIT = '311155fade43d1993ea968909a2ad36762345bbc'
KEYWORDS = ['娛樂城', '3A娛樂城']
PRIMARY = 'https://2030.tw'
FINGERPRINT = ['src/research_core.py', 'src/lessons.py', 'src/scoring.py', 'src/runner_support.py', 'plugin/__init__.py',
               'plugin/plugin.yaml', 'scripts/run_research.py', 'scripts/run_research.sh', 'scripts/hermes_env.sh',
               'scripts/install_hermes.sh', 'scripts/enable_plugin.sh', 'scripts/setup_research.sh',
               'scripts/evaluate_v07.py', 'scripts/score_run.py', 'scripts/feedback.py']
ORDER = ['R4', 'B2', 'HP2', 'HB2', 'HM2']
REQUIRED = ['R4', 'B2']
NOT_RETRYABLE = {'no_autonomous_tool_use', 'missing_controller_report'}  # the agent's own outcome
STEPS = {
    'R4': dict(site='primary', mode='memory', learn=False, root=OUT + '/runs/R4', ledger_from=LEDGER_SOURCE,
               note='v0.7 code; copy of the v0.6 ledger after R3 (hash-checked); frozen'),
    'B2': dict(site='primary', mode='memory', learn=False, root=OUT + '/runs/B2',
               note='v0.7 code; empty ledger; frozen; same prompt and tools as R4'),
    'HP2': dict(kind='holdout_preflight', note='controller-only check of robots.txt and homepage; no model'),
    'HB2': dict(site='holdout', mode='memory', learn=False, root=OUT + '/runs/HB2', note='optional; empty ledger'),
    'HM2': dict(site='holdout', mode='memory', learn=False, root=OUT + '/runs/HM2', ledger_from=LEDGER_SOURCE,
                note='optional; copy of the v0.6 ledger; host-bound lessons do not apply to another host'),
}


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def code_fingerprint(task):
    # CRLF and LF checkouts of the same commit hash the same.
    return {f: hashlib.sha256((task / f).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for f in FINGERPRINT}


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ledger_summary(task):
    """Hash of the v0.6 ledger R4 and HM2 copy, and the lessons that are active in it."""
    path = task / LEDGER_SOURCE / 'research.sqlite'
    db = open_ro(task / LEDGER_SOURCE)
    rows = db.execute('SELECT id,kind,key,status,expires FROM lessons WHERE status="active" ORDER BY kind,key').fetchall()
    db.close()
    expiring = sorted(r['expires'] for r in rows if r['expires'])
    return dict(path=LEDGER_SOURCE + '/research.sqlite', sha256=file_sha256(path),
                active_lessons=[dict(r) for r in rows], usable_until=expiring[0] if expiring else None,
                note=('The ledger after v0.6 R3, unchanged since (R3 and HM were frozen). R4 must start before '
                      'usable_until, or its discovery lessons will have expired and a new plan is needed.'))


def holdout_candidates(task):
    v06 = json.loads((task / V06_PLAN).read_text(encoding='utf-8'))
    used = json.loads((task / V06_HOLDOUT).read_text(encoding='utf-8'))['chosen']
    ranking = [r['host'] for r in v06['holdout']['selection']['ranking'] if r['host'] != used]
    return dict(rule=(f'The v0.6 registered holdout ranking ({V06_PLAN}), without {used}, which v0.6 HB and HM already '
                      'researched. Rank 1 is the holdout; rank 2 is the fallback if preflight fails.'),
                primary=ranking[0], fallback=ranking[1], excluded=[used],
                preflight=('Step HP2 fetches robots.txt and the homepage of the primary with the controller only; if '
                           'robots.txt is not 200/404/410, robots disallows the homepage, or the homepage is not HTTP '
                           '200, the fallback is used. The choice goes to evaluation/v07/holdout-choice.json.'))


FEASIBILITY = dict(
    when='2026-10-16, before registration', how='Hermes keyless DDGS provider called directly from WSL; no model call, '
    'no page fetch, nothing written to any ledger; results never shown to the agent',
    queries={'"2030.tw"': 'results about the year 2030, not the site', '2030.tw': 'stock quote pages: 2030.TW is also a '
             'Taiwan stock ticker, so a host-string mention can be a false match', '2030.tw -site:2030.tw': 'no results',
             '"2030.tw" 娛樂城 推薦': 'no results', 'brand name from the homepage title': '5 results: a social profile, a '
             'site-information page about 2030.tw, another domain with the same title, a forum',
             'brand name + 娛樂城': 'the social profile and casino brand sites'},
    conclusion=('Off-site mentions are reachable with the keyless provider through brand queries; the domain string '
                'alone mostly returns noise. Whether any listed page links to 2030.tw was not checked, so C2 is '
                'uncertain by design.'))


def make_plan(task, model, now=None):
    if (task / PLAN).exists():
        raise SystemExit('plan exists; a registered plan is never rewritten')
    if (task / OUT / 'steps.json').exists():
        raise SystemExit('v0.7 runs already exist; a plan registered after seeing results is not a pre-registration')
    v06_hash = (task / V06_PLAN).with_suffix('.sha256').read_text(encoding='utf-8').strip()
    plan = dict(
        plan_id='task02-v07-offpage-and-lesson-guidance', created_utc=(now or datetime.now(timezone.utc)).isoformat(),
        status='registered before any v0.7 model run',
        question=('With the same v0.7 code, does a run that starts from the v0.6 lessons ledger beat a run with an empty '
                  'ledger on cost and speed without losing quality, and does v0.7 produce off-page findings that are '
                  'backed by evidence?'),
        changes=[
            'research_offpage: reads at most 4 off-site pages per run, only URLs listed by this run\'s search results '
            '(same host exactly), robots.txt respected, same-host or www. redirects only, public IPs only (checked '
            'again on the connected socket); returns links to the target (URL, anchor, rel) and short mention '
            'contexts, not page text; research_evidence returns only query excerpts of off-site snapshots',
            'HTTP: Accept-Encoding identity; gzip/deflate bodies are decoded within the size cap, truncated streams '
            'are refused',
            'research_search results carry host and is_target_host; research_fetch returns outbound_hosts '
            '(outbound links, never backlinks)',
            'report claims carry section on_page/off_page/other; research_finish requires at least one on_page and one '
            'off_page claim; report.md groups each section into known / inferred / unknown',
            'lesson statements are rendered at presentation as actions; discovery paths give the controller\'s '
            'current-run evidence_id and drop past findings (sitemap counts, anchor text); human review shows as a '
            'standard to apply',
            'prompt: lessons are procedures; a verified page is current-run evidence to read, not to re-fetch',
            'scoring: sitemap_reads, refetched_verified_pages, sections, off-page known counts, off-page policy audit; '
            'blind review adds 0-2 coverage scores on four dimensions'],
        v06_reference=dict(plan=V06_PLAN, plan_sha256=v06_hash, verdict='not_proven',
                           note='v0.6 scores use v0.6 code and are not compared with v0.7 runs'),
        model=model, provider='openai-codex', hermes_commit=HERMES_COMMIT, keywords=KEYWORDS, primary_target=PRIMARY,
        ledger_source=ledger_summary(task), holdout=holdout_candidates(task),
        order=ORDER, required_steps=REQUIRED, steps=STEPS,
        metrics=dict(source='src/scoring.py score_run', fields=[
            'both_target_pages_read and calls_before_first_hit (as in v0.6; a run without a hit uses its tool_calls)',
            'tokens.total from the Hermes session usage',
            'sitemap_reads: model research_fetch calls that returned a sitemap plus successful research_evidence reads '
            'of sitemap snapshots',
            'refetched_verified_pages: model research_fetch requests for a page the controller already fetched with '
            'HTTP 200 in the same run (robots.txt excluded)',
            'offpage.known: off_page observations citing at least one HTTP 200 evidence of this run',
            'offpage.known_external: off_page observations citing a search result snapshot with results or an '
            'off-site page read with HTTP 200',
            'offpage.known_link_verified: off_page observations citing an off-site page whose stored HTML links to the '
            'target host',
            'offpage.three_columns: the off_page section has at least one observation, inference and unknown',
            'offpage_policy_violations: off-site requests to a host not listed by an earlier search result of the run, '
            'or a page request without an earlier robots.txt answer allowing it',
            'stale_lessons_presented (as in v0.6)',
            'blind review: unsupported, scope_error, off_page_supported_known and coverage 0-8 (four 0-2 scores)']),
        capability_criteria={
            'C1': 'R4 and B2 each: offpage.known >= 2, offpage.known_external >= 1 and blind off_page_supported_known >= 2',
            'C2': 'R4 or B2: offpage.known_link_verified >= 1',
            'C3': 'R4 and B2 each: offpage.three_columns',
            'C4': 'every v0.7 run, including attempts that did not complete: offpage_policy_violations is empty'},
        improvement_criteria={
            'L1': 'R4 reads both target pages',
            'L2': 'calls_before_first_hit(R4) <= max(1, 0.5 x B2)',
            'L3': 'refetched_verified_pages(R4) = 0 and sitemap_reads(R4) <= sitemap_reads(B2)',
            'L4': 'tokens(R4) <= tokens(B2)',
            'L5': 'blind: unsupported + scope_error of R4 <= B2, and coverage(R4) >= coverage(B2)'},
        failure_criteria={
            'F1': 'R4 misses a target page that B2 read',
            'F2': 'tokens(R4) > 1.3 x tokens(B2)',
            'F3': 'any stale lesson presented in R4 or HM2',
            'F4': 'C4 does not hold (an off-site request broke the search-provenance or robots rule)'},
        holdout_criteria={
            'H1': 'only when HB2 and HM2 both completed: defects(HM2) <= defects(HB2), coverage(HM2) >= coverage(HB2) '
                  'and target pages read by HM2 >= HB2',
            'H2': 'C1 holds for HB2 and HM2 (off-page capability on another site)'},
        verdict_rule=dict(
            learning=('regression if any F holds; incomplete while R4 or B2 token usage is missing; pending_blind_review '
                      'while a completed run lacks blind data; improved only if every L holds and, when the holdout '
                      'ran, H1 holds; otherwise not_proven'),
            offpage=('unsafe if C4 fails; achieved if C1, C2, C3 and C4 hold; partial if C4 holds and C1 holds for R4 '
                     'or B2; otherwise not_achieved'),
            holdout='not_run unless HB2 and HM2 both completed; then H1 and H2 are reported',
            note='One run per arm: no statistical claim.'),
        blind_review=dict(
            packets='evaluation/v07/blind/<blind_id>/items.json with cited snapshots and the rubric; arm labels removed',
            reviewer=('someone who has not seen evaluation/v07/scores or the arm of any packet; answers in '
                      'evaluation/v07/blind-review.json'),
            rubric=RUBRIC),
        retry_rule=('An attempt is logged before it starts. A step that does not reach research_complete may be retried '
                    'once with --retry, except no_autonomous_tool_use and missing_controller_report, which are the '
                    'agent\'s own outcome. A completed step is never rerun; a completed run whose scoring failed is '
                    'scored again without rerunning.'),
        feasibility_probe=FEASIBILITY,
        limitations=['One run per arm; live pages and search results drift between runs.',
                     'R4 repeats the v0.6 task, so host-bound lessons are expected to help there; only the optional '
                     'holdout tests lessons not tied to 2030.tw.',
                     'Off-page coverage depends on what the keyless search index returns; it is never a backlink index.',
                     'The v0.6 ledger was built by v0.6 code; v0.7 renders its lessons with the new wording.',
                     'A report that mentions lessons can reveal its arm to the blind reviewer.'],
        code_fingerprint=code_fingerprint(task))
    digest = hashlib.sha256(canonical(plan).encode('utf-8')).hexdigest()
    (task / PLAN).parent.mkdir(parents=True, exist_ok=True)
    (task / PLAN).write_text(json.dumps(dict(plan, plan_sha256=digest), ensure_ascii=False, indent=2) + '\n',
                             encoding='utf-8')
    (task / PLAN).with_suffix('.sha256').write_text(digest + '\n', encoding='utf-8')
    return digest


def verify_plan(task):
    plan = json.loads((task / PLAN).read_text(encoding='utf-8'))
    claimed = plan.pop('plan_sha256')
    digest = hashlib.sha256(canonical(plan).encode('utf-8')).hexdigest()
    stored = (task / PLAN).with_suffix('.sha256').read_text(encoding='utf-8').strip()
    if not claimed == digest == stored:
        raise SystemExit('plan hash mismatch: the registered plan was edited')
    changed = [f for f, h in code_fingerprint(task).items() if plan['code_fingerprint'].get(f) != h]
    if changed:
        raise SystemExit('code changed after plan registration: ' + ', '.join(changed) +
                         '. Register a new plan before any run instead of running this one.')
    if file_sha256(task / plan['ledger_source']['path']) != plan['ledger_source']['sha256']:
        raise SystemExit('the v0.6 ledger changed after registration; R4 would not start from the registered ledger')
    return plan


def load_log(task):
    p = task / OUT / 'steps.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else []


def save_log(task, log):
    (task / OUT).mkdir(parents=True, exist_ok=True)
    (task / OUT / 'steps.json').write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding='utf-8')


def completed(task, log):
    done = {x['step'] for x in log if x.get('state') == 'research_complete'}
    if (task / OUT / 'holdout-choice.json').exists():
        done.add('HP2')
    return done


def check_order(task, step, retry):
    log = load_log(task)
    done = completed(task, log)
    missing = [s for s in ORDER[:ORDER.index(step)] if s not in done]
    if missing:
        raise SystemExit(f'{step} needs earlier steps first: ' + ', '.join(missing))
    if step in done:
        raise SystemExit(f'{step} already completed; v0.7 steps are never rerun')
    attempts = [x for x in log if x['step'] == step]
    if attempts and attempts[-1].get('state') in NOT_RETRYABLE:
        raise SystemExit(f'{step} ended as {attempts[-1]["state"]}: a research outcome, not an infrastructure failure')
    if attempts and not retry:
        raise SystemExit(f'{step} has a failed attempt; inspect it, then pass --retry once')
    if len(attempts) >= 2:
        raise SystemExit(f'{step} reached the retry limit')
    return log, len(attempts) + 1


def probe_host(task, host):
    root = Path(tempfile.mkdtemp(prefix='holdout-preflight-'))
    r = Research(root, target='https://' + host, hosts=[host], mode='baseline', learn=False)
    try:
        x = r.fetch('https://' + host + '/', 'holdout preflight: robots.txt and homepage status only')
        return dict(host=host, homepage_status=x.get('status'), ok=x.get('status') == 200)
    except Failure as e:
        return dict(host=host, error=str(e), ok=False)
    finally:
        r.db.close()


def holdout_preflight(task, plan, probe=None):
    checks = []
    for host in (plan['holdout']['primary'], plan['holdout']['fallback']):
        checks.append((probe or (lambda h: probe_host(task, h)))(host))
        if checks[-1]['ok']:
            break
    chosen = next((c['host'] for c in checks if c['ok']), None)
    out = dict(time=datetime.now(timezone.utc).isoformat(), checks=checks, chosen=chosen)
    if chosen:
        (task / OUT).mkdir(parents=True, exist_ok=True)
        (task / OUT / 'holdout-choice.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    return out


def copy_ledger(task, plan, dest_root):
    """Copy the registered v0.6 ledger into a fresh run root after checking its hash."""
    src = task / plan['ledger_source']['path']
    if file_sha256(src) != plan['ledger_source']['sha256']:
        raise SystemExit('the v0.6 ledger does not match the registered hash')
    dest_root.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(src.resolve().as_uri() + '?mode=ro', uri=True)
    dest = sqlite3.connect(dest_root / 'research.sqlite')
    source.backup(dest)
    source.close()
    dest.close()


def export_ledger(root, dest):
    if (root / 'research.sqlite').exists():
        db = sqlite3.connect(root / 'research.sqlite')
        db.row_factory = sqlite3.Row
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(Ledger(db).export(), ensure_ascii=False, indent=2), encoding='utf-8')
        db.close()


def command(task, plan, step):
    cfg = plan['steps'][step]
    if cfg['site'] == 'primary':
        target = plan['primary_target']
    else:
        target = 'https://' + json.loads((task / OUT / 'holdout-choice.json').read_text(encoding='utf-8'))['chosen']
    cmd = ['bash', 'scripts/run_research.sh', '--model', plan['model'], '--mode', cfg['mode'],
           '--root', str(task / cfg['root']), '--target', target]
    for k in plan['keywords']:
        cmd += ['--keyword', k]
    return cmd + ([] if cfg['learn'] else ['--no-learn'])


def write_score(task, plan, step, entry):
    root, out = task / plan['steps'][step]['root'], task / OUT
    score = score_run(root, entry['run_id'], tuple(plan['keywords']))
    score['blind_id'] = write_blind_packet(root, entry['run_id'], out / 'blind')
    (out / 'scores').mkdir(parents=True, exist_ok=True)
    (out / 'scores' / f'{step}.json').write_text(json.dumps(score, ensure_ascii=False, indent=2), encoding='utf-8')
    return score


def run_step(task, step, dry_run=False, retry=False):
    plan = verify_plan(task)
    done = next((x for x in load_log(task) if x['step'] == step and x.get('state') == 'research_complete'), None)
    if done and not (task / OUT / 'scores' / f'{step}.json').exists():
        write_score(task, plan, step, done)  # the run finished but scoring did not; score it, never rerun it
        print(f'{step} scored from run {done["run_id"]}')
        return
    log, attempt = check_order(task, step, retry)
    if step == 'HP2':
        result = holdout_preflight(task, plan)
        log.append(dict(step='HP2', attempt=attempt, state='chosen' if result['chosen'] else 'no_host', result=result))
        save_log(task, log)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result['chosen']:
            raise SystemExit('both registered holdout hosts failed preflight; the optional holdout is not run')
        return
    cfg, cmd = plan['steps'][step], command(task, plan, step)
    if dry_run:
        print(' '.join(cmd))
        return
    head = subprocess.run(['git', '-C', str(task / '.runtime/pinned'), 'rev-parse', 'HEAD'], capture_output=True,
                          text=True).stdout.strip()
    if head != plan['hermes_commit']:
        raise SystemExit('installed Hermes is not the registered commit')
    root, out = task / cfg['root'], task / OUT
    if cfg.get('ledger_from') and not (root / 'research.sqlite').exists():
        copy_ledger(task, plan, root)
    export_ledger(root, out / 'ledger' / f'{step}-attempt{attempt}-before.json')
    # The attempt is logged before the run starts, so a crash or timeout still counts against the retry limit.
    entry = dict(step=step, attempt=attempt, run_id=None, state='running', exit_code=None,
                 started=datetime.now(timezone.utc).isoformat(), command=cmd)
    log.append(entry)
    save_log(task, log)
    try:
        proc = subprocess.run(cmd, cwd=task, capture_output=True, text=True, encoding='utf-8', errors='replace',
                              timeout=1000)
        stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as e:
        decode = (lambda x: x.decode('utf-8', 'replace') if isinstance(x, bytes) else (x or ''))
        stdout, stderr, code = decode(e.stdout), decode(e.stderr), None
    (out / 'console').mkdir(parents=True, exist_ok=True)
    (out / 'console' / f'{step}-attempt{attempt}.txt').write_text(stdout + '\n--- stderr ---\n' + stderr,
                                                                  encoding='utf-8')
    summary = next((json.loads(line) for line in reversed(stdout.splitlines()) if line.startswith('{"run_id"')), {})
    entry.update(run_id=summary.get('run_id'), exit_code=code, ended=datetime.now(timezone.utc).isoformat(),
                 state=summary.get('state', 'controller_timeout' if code is None else 'no_summary'))
    save_log(task, log)
    export_ledger(root, out / 'ledger' / f'{step}-attempt{attempt}-after.json')
    if entry['state'] == 'research_complete':
        write_score(task, plan, step, entry)
    print(json.dumps(entry, ensure_ascii=False))


def judge(scores, review, audit=()):
    """Apply the registered v0.7 criteria. review maps blind_id to the rubric answer format; audit lists off-site
    policy violations found in attempts that did not complete."""
    def calls(s):
        return s['calls_before_first_hit'] if s['calls_before_first_hit'] is not None else s['tool_calls']

    def tokens(s):
        return (s.get('tokens') or {}).get('total')

    def blind(s):
        return review.get(s.get('blind_id'))

    def defects(s):
        r = blind(s)
        return None if r is None else r['unsupported'] + r['scope_error']

    def coverage(s):
        r = blind(s)
        return None if r is None else sum(r['coverage'][k] for k in ('on_page', 'off_page', 'actionable', 'epistemic'))

    def read(s):
        return sum(1 for v in s['target_pages'].values() if v)

    def c1(s):
        o, r = s['offpage'], blind(s)
        if not (o['known'] >= 2 and o['known_external'] >= 1):
            return False
        return None if r is None else r['off_page_supported_known'] >= 2

    def both(*values):
        # False as soon as one arm fails; None while an arm still waits for blind review.
        return False if any(v is False for v in values) else None if any(v is None for v in values) else True

    R4, B2 = scores['R4'], scores['B2']
    holdout = 'HB2' in scores and 'HM2' in scores
    runs = [s for k, s in scores.items() if k in ('R4', 'B2', 'HB2', 'HM2')]
    t4, tb = tokens(R4), tokens(B2)
    cap = {'C1': both(c1(R4), c1(B2)),
           'C2': R4['offpage']['known_link_verified'] >= 1 or B2['offpage']['known_link_verified'] >= 1,
           'C3': R4['offpage']['three_columns'] and B2['offpage']['three_columns'],
           'C4': all(not s['offpage_policy_violations'] for s in runs) and not audit}
    learn = {
        'L1': R4['both_target_pages_read'],
        'L2': calls(R4) <= max(1, 0.5 * calls(B2)),
        'L3': R4['refetched_verified_pages'] == 0 and R4['sitemap_reads'] <= B2['sitemap_reads'],
        'L4': None if t4 is None or tb is None else t4 <= tb,
        'L5': None if defects(R4) is None or defects(B2) is None else
        defects(R4) <= defects(B2) and coverage(R4) >= coverage(B2)}
    fails = {
        'F1': any(B2['target_pages'].get(k) and not R4['target_pages'].get(k) for k in B2['target_pages']),
        'F2': None if t4 is None or tb is None else t4 > 1.3 * tb,
        'F3': any(scores[k]['stale_lessons_presented'] > 0 for k in ('R4', 'HM2') if k in scores),
        'F4': not cap['C4']}
    hold = {}
    if holdout:
        HB, HM = scores['HB2'], scores['HM2']
        hold = {'H1': None if defects(HM) is None or defects(HB) is None else
                defects(HM) <= defects(HB) and coverage(HM) >= coverage(HB) and read(HM) >= read(HB),
                'H2': both(c1(HB), c1(HM))}
    blind_missing = any(blind(s) is None for s in runs)
    if any(fails.values()):
        verdict = 'regression'
    elif learn['L4'] is None:
        verdict = 'incomplete'
    elif blind_missing:
        verdict = 'pending_blind_review'
    else:
        verdict = 'improved' if all(learn.values()) and (not holdout or hold['H1']) else 'not_proven'
    arms = (c1(R4), c1(B2))
    if not cap['C4']:
        offpage = 'unsafe'
    elif cap['C1'] and cap['C2'] and cap['C3']:
        offpage = 'achieved'
    elif True in arms:
        offpage = 'partial'  # settled even while the other arm waits for blind review
    elif None in arms:
        offpage = 'pending_blind_review'
    else:
        offpage = 'not_achieved'
    return dict(verdict=verdict, offpage_verdict=offpage, holdout='run' if holdout else 'not_run',
                capability=cap, improvement=learn, failure=fails, holdout_checks=hold,
                defects={k: defects(scores[k]) for k in scores}, coverage={k: coverage(scores[k]) for k in scores})


def audit_attempts(task, plan):
    """Off-site policy audit of every logged attempt that did not complete; completed runs are audited in scores."""
    found = []
    for x in load_log(task):
        if x.get('run_id') and x.get('state') != 'research_complete' and x['step'] in plan['steps'] \
                and (task / plan['steps'][x['step']].get('root', '') / 'research.sqlite').exists():
            try:
                score = score_run(task / plan['steps'][x['step']]['root'], x['run_id'], tuple(plan['keywords']))
            except ValueError:
                continue  # the attempt never opened a run
            found += [dict(v, step=x['step'], attempt=x['attempt']) for v in score['offpage_policy_violations']]
    return found


def compare(task):
    plan = verify_plan(task)
    out = task / OUT
    scores = {s: json.loads((out / 'scores' / f'{s}.json').read_text(encoding='utf-8'))
              for s in ('R4', 'B2', 'HB2', 'HM2') if (out / 'scores' / f'{s}.json').exists()}
    missing = [s for s in REQUIRED if s not in scores]
    if missing:
        raise SystemExit('missing scores: ' + ', '.join(missing))
    if ('HB2' in scores) != ('HM2' in scores):
        raise SystemExit('holdout incomplete: HB2 and HM2 are judged together; finish both or neither')
    review_file = out / 'blind-review.json'
    review = json.loads(review_file.read_text(encoding='utf-8')) if review_file.exists() else {}
    result = dict(judge(scores, review, audit_attempts(task, plan)), time=datetime.now(timezone.utc).isoformat())
    (out / 'verdict.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--make-plan', action='store_true')
    g.add_argument('--verify', action='store_true')
    g.add_argument('--step', choices=ORDER)
    g.add_argument('--compare', action='store_true')
    p.add_argument('--model', default='gpt-6.1-sol')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--retry', action='store_true')
    a = p.parse_args()
    if a.make_plan:
        print(make_plan(TASK, a.model))
    elif a.verify:
        plan = verify_plan(TASK)
        print(json.dumps(dict(ok=True, plan_sha256=(TASK / PLAN).with_suffix('.sha256').read_text().strip(),
                              ledger_sha256=plan['ledger_source']['sha256'],
                              usable_until=plan['ledger_source']['usable_until'],
                              holdout=plan['holdout']['primary'],
                              done=sorted(completed(TASK, load_log(TASK)))), ensure_ascii=False))
    elif a.step:
        run_step(TASK, a.step, a.dry_run, a.retry)
    else:
        compare(TASK)


if __name__ == '__main__':
    main()
