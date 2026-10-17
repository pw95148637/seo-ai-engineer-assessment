"""v0.6 pre-registered learning evaluation: plan, ordered steps and verdict.

python scripts/evaluate_v06.py --make-plan --model gpt-6.1-sol   # once, before any real run
python scripts/evaluate_v06.py --verify                          # plan hash and code fingerprint
python scripts/evaluate_v06.py --step R1 [--dry-run] [--retry]   # steps in plan order
python scripts/evaluate_v06.py --compare                         # verdict from scores and blind review

A step refuses to start when the plan hash or code fingerprint changed, an earlier step is
missing, or the step already completed. Archived v0.5 results are read only for the holdout rule.
"""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
import argparse, hashlib, json, sqlite3, subprocess, sys, tempfile
TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK))
from src.research_core import Research, Failure, snapshot_info
from src.scoring import open_ro, score_run, write_blind_packet
from src.lessons import Ledger

PLAN, OUT = 'evaluation/plan-v06.json', 'evaluation/v06'
HERMES_COMMIT = '311155fade43d1993ea968909a2ad36762345bbc'
KEYWORDS = ['娛樂城', '3A娛樂城']
PRIMARY = 'https://2030.tw'
FINGERPRINT = ['src/research_core.py', 'src/lessons.py', 'src/scoring.py', 'src/runner_support.py', 'plugin/__init__.py',
               'plugin/plugin.yaml', 'scripts/run_research.py', 'scripts/run_research.sh', 'scripts/hermes_env.sh',
               'scripts/install_hermes.sh', 'scripts/enable_plugin.sh', 'scripts/setup_research.sh',
               'scripts/evaluate_v06.py', 'scripts/score_run.py', 'scripts/feedback.py']
ARCHIVE = ['evidence/autonomous-research', 'evidence/live-agent-evaluation/baseline',
           'evidence/live-agent-evaluation/history', 'evidence/live-agent-evaluation/memory']
SERIES = OUT + '/runs/2030-series'
ORDER = ['R1', 'HF', 'R2', 'B1', 'R3', 'HP', 'HB', 'HM']
NOT_RETRYABLE = {'no_autonomous_tool_use', 'missing_controller_report'}  # the agent's own outcome
STEPS = {
    'R1': dict(site='primary', mode='memory', learn=True, root=SERIES, note='empty ledger; learns'),
    'HF': dict(kind='human_feedback', on='R1', root=SERIES, note='reviewer labels R1 report with scripts/feedback.py'),
    'R2': dict(site='primary', mode='memory', learn=True, root=SERIES, note='sees R1 lessons and feedback; learns'),
    'B1': dict(site='primary', mode='baseline', learn=False, root=OUT + '/runs/B1', note='same code, no lessons'),
    'R3': dict(site='primary', mode='memory', learn=False, root=SERIES, note='ledger frozen'),
    'HP': dict(kind='holdout_preflight', note='controller-only check of robots.txt and homepage; no model'),
    'HB': dict(site='holdout', mode='baseline', learn=False, root=OUT + '/runs/HB', note='no lessons'),
    'HM': dict(site='holdout', mode='memory', learn=False, root=OUT + '/runs/HM', ledger_from=SERIES,
               note='copy of the ledger after R3, frozen; host-bound lessons do not apply to another host'),
}


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def code_fingerprint(task):
    # CRLF and LF checkouts of the same commit hash the same.
    return {f: hashlib.sha256((task / f).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for f in FINGERPRINT}


def select_holdout(task, target_host='2030.tw', keyword='娛樂城'):
    """Rank result hosts in archived search snapshots whose query is exactly the head keyword."""
    seen, used, counts, broad = set(), [], {}, {}
    for d in ARCHIVE:
        db = open_ro(task / d)
        for r in db.execute("SELECT * FROM evidence WHERE url='search:ddgs' AND status=200 ORDER BY rowid").fetchall():
            if r['id'] in seen:
                continue
            seen.add(r['id'])
            query = json.loads(r['meta']).get('query', '')
            info = snapshot_info(task / d, r) or {'anchors': []}
            hosts = [(urlsplit(u).hostname or '').lower().removeprefix('www.') for u, _ in info['anchors']]
            ranked = [(i + 1, h) for i, h in enumerate(hosts) if h and h != target_host]
            if keyword in query and 'site:' not in query:
                for h in {h for _, h in ranked}:
                    b = broad.setdefault(h, [0, 0])
                    b[0] += 1
                    b[1] += '3a' in query.casefold()
            if query.replace('"', '').strip() != keyword:
                continue
            used.append(dict(evidence_id=r['id'], run=r['run'], query=query, archive=d))
            for rank, h in ranked:
                c = counts.setdefault(h, dict(host=h, snapshots=set(), ranks=[]))
                c['snapshots'].add(r['id'])
                c['ranks'].append(rank)
        db.close()
    order = sorted(counts.values(), key=lambda c: (-len(c['snapshots']), sum(c['ranks']) / len(c['ranks']), c['host']))
    ranking = [dict(host=c['host'], snapshots=len(c['snapshots']), mean_rank=round(sum(c['ranks']) / len(c['ranks']), 2))
               for c in order]
    top_broad = [dict(host=h, snapshots=n, with_3a_brand_query=b)
                 for h, (n, b) in sorted(broad.items(), key=lambda x: (-x[1][0], x[0]))[:3]]
    return dict(
        rule=(f'Archived DDGS snapshots (status 200) whose query, without quotes, equals exactly "{keyword}"; '
              f'count distinct snapshots listing each result host (www. removed), excluding {target_host}; '
              'ties by mean result rank, then host name. Rank 1 is the holdout; rank 2 is the fallback.'),
        snapshots=used, ranking=ranking[:5], primary=ranking[0]['host'], fallback=ranking[1]['host'],
        alternative_rule_not_used=dict(
            rule=f'any query containing "{keyword}" without site:', top=top_broad,
            why_not=('Its leader is counted mostly in queries naming the 3A brand, which measures brand navigation '
                     'rather than competition for the head keyword. The registered rule follows the instruction '
                     'to use the 「娛樂城」 search snapshots; both rules were computed before registration.')),
        reading=('Only result host names and ranks were read to compute this; no holdout page content was read '
                 'before the plan was registered.'))


def make_plan(task, model, now=None):
    if (task / PLAN).exists():
        raise SystemExit('plan exists; a registered plan is never rewritten')
    if (task / OUT / 'steps.json').exists():
        raise SystemExit('v0.6 runs already exist; a plan registered after seeing results is not a pre-registration')
    plan = dict(
        plan_id='task02-v06-lessons-evaluation', created_utc=(now or datetime.now(timezone.utc)).isoformat(),
        status='registered before any v0.6 model run',
        question=('Does the lessons ledger make the third run on the same task better than the first run and a '
                  'same-time no-memory run, without hurting quality on a held-out site?'),
        v05_results=('evidence/live-agent-evaluation stays an archived negative result (memory did not improve). '
                     'None of its runs, scores or ledgers are v0.6 data.'),
        model=model, provider='openai-codex', hermes_commit=HERMES_COMMIT, keywords=KEYWORDS, primary_target=PRIMARY,
        holdout=dict(selection=select_holdout(task), preflight=(
            'Step HP fetches robots.txt and the homepage of the rank-1 host with the controller only. If robots.txt is '
            'not 200/404/410, robots disallows the homepage, or the homepage is not HTTP 200, rank 2 is used. The '
            'choice is written to evaluation/v06/holdout-choice.json and applies to HB and HM.')),
        order=ORDER, steps=STEPS,
        human_feedback=dict(
            who='The user, or the coordinating agent when the user delegates; the reviewer name is stored.',
            how='scripts/feedback.py label|ok|veto on the R1 run in the series root',
            rules=['Labels: unsupported, scope_error, or reviewed_ok when nothing is wrong.',
                   'Reasons are at most 200 characters with no URL or path, so feedback cannot hand over answers.',
                   'scope general only for errors that do not depend on 2030.tw specifics.']),
        metrics=dict(source='src/scoring.py score_run', fields=[
            'both_target_pages_read: model read (fetch or research_evidence) an HTTP 200 page on the target host '
            'whose URL slug or a title/H1 segment equals the keyword; on-site search pages do not count',
            'calls_before_first_hit: model tool calls before the first target page read; when no page is read the '
            'run total tool_calls is used', 'failed_searches: searches without any result URL (timeout, error, no results or empty placeholder); '
            'failed_search_kinds splits no_results from error',
            'first_finish_rejected', 'tokens.total from the Hermes session usage', 'http_requests (model + controller)',
            'failed_source_citations', 'stale_lessons_presented: lessons shown while revoked, vetoed, expired or '
            'never active, checked against lesson_history']),
        improvement_criteria={
            'I1': 'R3 reads both target pages',
            'I2': 'calls_before_first_hit(R3) <= 0.5 x R1 and <= 0.5 x B1',
            'I3': 'failed_searches(R3) = 0',
            'I4': 'tokens(R3) <= tokens(B1)',
            'I5': 'blind review: unsupported + scope_error defects of R3 <= B1',
            'I6': 'holdout: defects(HM) <= defects(HB) and target pages read by HM >= HB',
            'I7': 'holdout: failed_searches(HM) < failed_searches(HB), or both 0'},
        failure_criteria={
            'F1': 'R3 misses a target page that B1 read',
            'F2': 'tokens(R3) > 1.3 x tokens(B1)',
            'F3': 'any stale lesson presented in R1, R2, R3 or HM'},
        verdict_rule=('regression if any F holds; incomplete while R3 or B1 token usage is missing; '
                      'pending_blind_review while I5/I6 lack review data; improved only if every I holds; otherwise '
                      'not_proven. One run per arm: no statistical claim.'),
        blind_review=dict(
            packets='evaluation/v06/blind/<blind_id>/items.json with cited snapshots; arm labels removed',
            reviewer='someone who has not seen evaluation/v06/scores; answers per packet in '
                     'evaluation/v06/blind-review.json as {blind_id: {"unsupported": n, "scope_error": n, "notes": ""}}'),
        retry_rule=('An attempt is logged before it starts. A step that does not reach research_complete may be '
                    'retried once with --retry, except no_autonomous_tool_use and missing_controller_report, which are '
                    'the agent\'s own outcome. Only research_complete runs teach the ledger, so a failed attempt adds '
                    'no support. A completed step is never rerun; a completed run whose scoring failed is scored again '
                    'without rerunning.'),
        limitations=['One run per arm; live pages and search results drift between runs.',
                     'R1-R3 repeat the same task, so host-bound lessons are expected to help there; the holdout tests '
                     'only lessons that are not tied to 2030.tw.',
                     'score_run measures coverage and cost; semantic support depends on the blind review.',
                     'A memory-arm report may still mention lessons and so reveal its arm to the blind reviewer.',
                     'I3 counts search timeouts too, so provider outages can fail it without any learning effect.'],
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
    return plan


def load_log(task):
    p = task / OUT / 'steps.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else []


def completed(task, log):
    done = {x['step'] for x in log if x.get('state') == 'research_complete'}
    r1 = next((x['run_id'] for x in log if x['step'] == 'R1' and x.get('state') == 'research_complete'), None)
    series = task / SERIES / 'research.sqlite'
    if r1 and series.exists():
        db = open_ro(task / SERIES)
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='feedback'").fetchone() and                 db.execute('SELECT 1 FROM feedback WHERE run=?', (r1,)).fetchone():
            done.add('HF')
        db.close()
    if (task / OUT / 'holdout-choice.json').exists():
        done.add('HP')
    return done


def check_order(task, step, retry):
    log = load_log(task)
    done = completed(task, log)
    missing = [s for s in ORDER[:ORDER.index(step)] if s not in done]
    if missing:
        raise SystemExit(f'{step} needs earlier steps first: ' + ', '.join(missing))
    if step in done:
        raise SystemExit(f'{step} already completed; v0.6 steps are never rerun')
    attempts = [x for x in log if x['step'] == step]
    if attempts and attempts[-1].get('state') == 'learning_failed':
        raise SystemExit(f'{step}: ledger learning failed (rolled back); fix the code and register a new plan')
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
    sel = plan['holdout']['selection']
    checks = []
    for host in (sel['primary'], sel['fallback']):
        checks.append((probe or (lambda h: probe_host(task, h)))(host))
        if checks[-1]['ok']:
            break
    chosen = next((c['host'] for c in checks if c['ok']), None)
    out = dict(time=datetime.now(timezone.utc).isoformat(), checks=checks, chosen=chosen)
    if chosen:
        (task / OUT).mkdir(parents=True, exist_ok=True)
        (task / OUT / 'holdout-choice.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    return out


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


def save_log(task, log):
    (task / OUT).mkdir(parents=True, exist_ok=True)
    (task / OUT / 'steps.json').write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding='utf-8')


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
    if step == 'HF':
        raise SystemExit('HF is a human step: python scripts/feedback.py --root ' + SERIES + ' list --run <R1 run_id>')
    if step == 'HP':
        result = holdout_preflight(task, plan)
        log.append(dict(step='HP', attempt=attempt, state='chosen' if result['chosen'] else 'no_host', result=result))
        save_log(task, log)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result['chosen']:
            raise SystemExit('both registered holdout hosts failed preflight; register a new plan before any holdout run')
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
        root.mkdir(parents=True, exist_ok=True)
        src, dest = sqlite3.connect(task / cfg['ledger_from'] / 'research.sqlite'), sqlite3.connect(root / 'research.sqlite')
        src.backup(dest)
        src.close()
        dest.close()
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


def judge(scores, review):
    """Apply the registered criteria. review maps blind_id to {'unsupported': n, 'scope_error': n}."""
    def calls(s):
        return s['calls_before_first_hit'] if s['calls_before_first_hit'] is not None else s['tool_calls']

    def tokens(s):
        return (s.get('tokens') or {}).get('total')

    def defects(s):
        r = review.get(s.get('blind_id'))
        return None if r is None else r['unsupported'] + r['scope_error']

    def read(s):
        return sum(1 for v in s['target_pages'].values() if v)

    R1, B1, R3, HB, HM = (scores[k] for k in ('R1', 'B1', 'R3', 'HB', 'HM'))
    t3, tb = tokens(R3), tokens(B1)
    d = {k: defects(scores[k]) for k in ('R3', 'B1', 'HB', 'HM')}
    checks = {
        'I1': R3['both_target_pages_read'],
        'I2': calls(R3) <= 0.5 * calls(R1) and calls(R3) <= 0.5 * calls(B1),
        'I3': R3['failed_searches'] == 0,
        'I4': None if t3 is None or tb is None else t3 <= tb,
        'I5': None if d['R3'] is None or d['B1'] is None else d['R3'] <= d['B1'],
        'I6': None if d['HM'] is None or d['HB'] is None else d['HM'] <= d['HB'] and read(HM) >= read(HB),
        'I7': HM['failed_searches'] < HB['failed_searches'] or HM['failed_searches'] == HB['failed_searches'] == 0}
    fails = {
        'F1': any(B1['target_pages'].get(k) and not R3['target_pages'].get(k) for k in B1['target_pages']),
        'F2': None if t3 is None or tb is None else t3 > 1.3 * tb,
        'F3': any(scores[k]['stale_lessons_presented'] > 0 for k in ('R1', 'R2', 'R3', 'HM'))}
    if any(fails.values()):
        verdict = 'regression'
    elif checks['I4'] is None:
        verdict = 'incomplete'  # token usage missing for R3 or B1
    elif checks['I5'] is None or checks['I6'] is None:
        verdict = 'pending_blind_review'
    else:
        verdict = 'improved' if all(checks.values()) else 'not_proven'
    return dict(verdict=verdict, improvement=checks, failure=fails, defects=d)


def compare(task):
    verify_plan(task)
    out = task / OUT
    scores = {s: json.loads((out / 'scores' / f'{s}.json').read_text(encoding='utf-8'))
              for s in ('R1', 'R2', 'B1', 'R3', 'HB', 'HM') if (out / 'scores' / f'{s}.json').exists()}
    missing = [s for s in ('R1', 'R2', 'B1', 'R3', 'HB', 'HM') if s not in scores]
    if missing:
        raise SystemExit('missing scores: ' + ', '.join(missing))
    review_file = out / 'blind-review.json'
    review = json.loads(review_file.read_text(encoding='utf-8')) if review_file.exists() else {}
    result = dict(judge(scores, review), time=datetime.now(timezone.utc).isoformat())
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
                              holdout=plan['holdout']['selection']['primary'],
                              done=sorted(completed(TASK, load_log(TASK)))), ensure_ascii=False))
    elif a.step:
        run_step(TASK, a.step, a.dry_run, a.retry)
    else:
        compare(TASK)


if __name__ == '__main__':
    main()
