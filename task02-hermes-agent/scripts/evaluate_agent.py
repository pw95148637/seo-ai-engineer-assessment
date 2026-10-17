"""Actual Hermes ablation on the repeated live task, not a held-out SEO benchmark.

All groups receive identical source-backed seed DBs, model, prompt and tool limits.
Each gets a separate directory and learning is frozen. Live source drift is saved,
not hidden. Semantic claim quality requires a separate source-support audit.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time


def summarize(root):
    outcomes = list(root.glob('*-outcome.json'))
    latest = max(outcomes, key=lambda p: p.stat().st_mtime)
    result = json.loads(latest.read_text())
    rid = result['run_id']
    usage = root / (rid + '-usage.json')
    result['usage'] = json.loads(usage.read_text()) if usage.exists() else {}
    db = sqlite3.connect(root / 'research.sqlite')
    events = [(k, json.loads(v)) for k, v in db.execute(
        'SELECT kind,data FROM events WHERE run=? ORDER BY id', (rid,))]
    result.update(requests=sum(k == 'request' for k, _ in events),
                  searches=sum(k == 'search_request' for k, _ in events),
                  tool_calls=sum(k == 'tool_call' for k, _ in events),
                  tool_errors=sum(k == 'tool_error' for k, _ in events))
    report = root / (rid + '-report.json')
    result['claim_count'] = len(json.loads(report.read_text())['claims']) if report.exists() else 0
    result['current_sources'] = [dict(zip(('url','status','sha256'), row)) for row in db.execute(
        'SELECT url,status,hash FROM evidence WHERE run=? ORDER BY url', (rid,))]
    result['observations_after'] = db.execute('SELECT count(*) FROM observations').fetchone()[0]
    db.close()
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--seed-root', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--model', required=True)
    p.add_argument('--execute', action='store_true')
    a = p.parse_args()
    seed, output = Path(a.seed_root).resolve(), Path(a.output).resolve()
    if output.exists():
        p.error('Use a fresh output directory; existing results are never overwritten.')
    db = sqlite3.connect(seed / 'research.sqlite')
    active = db.execute('SELECT host,status,expires,reason FROM memory WHERE status="active"').fetchall()
    if not active:
        p.error('Seed must contain memory learned from completed research runs.')
    count = db.execute('SELECT count(*) FROM observations').fetchone()[0]
    output.mkdir(parents=True)
    # SQLite backup gives each group exactly the same committed starting DB.
    for mode in ('baseline', 'history', 'memory'):
        root = output / mode
        root.mkdir()
        dest = sqlite3.connect(root / 'research.sqlite')
        db.backup(dest)
        dest.close()
        shutil.copytree(seed / 'snapshots', root / 'snapshots')
    db.close()
    plan = {'kind':'actual_model_live_repeated_task_ablation', 'model':a.model,
            'modes':['baseline','history','memory'], 'order':['baseline','history','memory'],
            'repetitions_per_group':1, 'independent_holdout':False, 'live_sources':True,
            'learning':False, 'observations_before':count, 'active_memory':active,
            'quality_metrics':['completed report','source support of material claims','unsupported claims','coverage of on-page/off-page/unknowns'],
            'cost_metrics':['HTTP requests','search calls','model API calls','tokens','elapsed seconds'],
            'success_rule':'Cost reduction only counts with comparable independently audited evidence quality; one run per group cannot establish statistical improvement.',
            'limitations':['Same task repeated; no cross-site generalization claim','Live source and search drift possible','Semantic audit is not automated by ID/hash validation']}
    frozen = json.dumps(plan, ensure_ascii=False, sort_keys=True)
    (output / 'plan.json').write_text(frozen)
    (output / 'plan.sha256').write_text(hashlib.sha256(frozen.encode()).hexdigest()+'\n')
    if not a.execute:
        print('Plan saved; --execute runs the authorized subscription model.')
        return
    task = Path(__file__).resolve().parents[1]
    rows = []
    for mode in plan['order']:
        start = time.monotonic()
        root = output / mode
        with (root / 'console.txt').open('w') as log:
            proc = subprocess.run(['bash',str(task/'scripts/run_research.sh'),
                                   '--model',a.model,'--mode',mode,'--root',str(root),'--no-learn'],
                                  stdout=log,stderr=subprocess.STDOUT,timeout=1000)
        row = summarize(root)
        row.update(mode=mode,process_exit=proc.returncode,elapsed_seconds=time.monotonic()-start)
        if row['observations_after'] != count:
            raise RuntimeError('Frozen evaluation unexpectedly changed observation count')
        rows.append(row)
        (output/'results.json').write_text(json.dumps({'plan':plan,'results':rows,'conclusion':'Await source-support audit; no improvement claim yet.'},ensure_ascii=False,indent=2))
        print(json.dumps({'mode':mode,'state':row['state'],'tokens':row['usage'].get('session_total_tokens')}),flush=True)
        if row['state']=='paused_by_operator':
            break


if __name__ == '__main__':
    main()
