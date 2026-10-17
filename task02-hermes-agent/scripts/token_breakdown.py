#!/usr/bin/env python3
"""Post-hoc, cache-aware cost of the v0.7 runs, recomputed from saved evidence (no model, no network).

  python scripts/token_breakdown.py [--json]

Reads evidence/v07-api-calls/agent-log-api-calls.txt (the Hermes agent.log "API call #" lines of the four v0.7
sessions; `cache=HIT/IN` is the prompt-cache hit count of that call, absent means 0), matches each session to its
step in evaluation/v07/steps.json by start time, checks the per-call totals against evaluation/v07/scores/, and
reads evidence/v07-usage/usage-log.jsonl for the ChatGPT Session usage before and after each step.

The registered v0.7 metric is total tokens (input + output); this breakdown is an analysis after the verdict and
does not change it.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import argparse, json, re

TASK = Path(__file__).resolve().parents[1]
LOG = TASK / 'evidence' / 'v07-api-calls' / 'agent-log-api-calls.txt'
STEPS = TASK / 'evaluation' / 'v07' / 'steps.json'
SCORES = TASK / 'evaluation' / 'v07' / 'scores'
USAGE = TASK / 'evidence' / 'v07-usage' / 'usage-log.jsonl'
SESSION = re.compile(r'\[(\d{8}_\d{6})_\w+\]')
CALL = re.compile(r'API call #(\d+):.*?\bin=(\d+) out=(\d+) total=(\d+)(?:.*?\bcache=(\d+)/(\d+))?')
LOG_TZ = timezone(timedelta(hours=8))  # agent.log timestamps and session ids are local time (Asia/Taipei)
LABELS = dict(R4='2030.tw 記憶組', B2='2030.tw 對照組', HB2='保留站 對照組', HM2='保留站 記憶組')


def read_calls():
    sessions, calls = {}, {}
    for line in LOG.read_text(encoding='utf-8').splitlines():
        m = SESSION.search(line)
        if not m:
            continue
        sid = m.group(0)
        sessions[sid] = datetime.strptime(m.group(1), '%Y%m%d_%H%M%S').replace(tzinfo=LOG_TZ)
        c = CALL.search(line)
        if c:
            n, inp, out, total, hit, of = c.groups()
            if of is not None and int(of) != int(inp):
                raise SystemExit(f'cache denominator differs from input: {line}')
            calls.setdefault(sid, []).append(dict(n=int(n), inp=int(inp), out=int(out), total=int(total),
                                                  cached=int(hit or 0)))
    return sessions, calls


def usage_points():
    rows = [json.loads(x) for x in USAGE.read_text(encoding='utf-8').splitlines() if x.strip()]
    session = {r['label']: next(w['used_percent'] for w in r['usage']['windows'] if w['label'] == 'Session') for r in rows}
    before = dict(R4='before-R4', B2='before-B2', HB2='before-HB2', HM2='after-HB2')  # HM2 started right after HB2's reading
    return {k: session[f'after-{k}'] - session[before[k]] for k in before}


def breakdown():
    sessions, calls = read_calls()
    steps = {x['step']: datetime.fromisoformat(x['started']) for x in json.loads(STEPS.read_text(encoding='utf-8'))
             if x.get('run_id')}
    usage = usage_points()
    out = {}
    for step in ('R4', 'B2', 'HB2', 'HM2'):
        sid = min(sessions, key=lambda s: abs((sessions[s] - steps[step]).total_seconds()))
        if abs((sessions[sid] - steps[step]).total_seconds()) > 30:
            raise SystemExit(f'no Hermes session near the start of {step}')
        cs = calls[sid]
        total = sum(c['total'] for c in cs)
        scored = json.loads((SCORES / f'{step}.json').read_text(encoding='utf-8'))['tokens']['total']
        if total != scored:
            raise SystemExit(f'{step}: log total {total} differs from the score {scored}')
        inp, outp, cached = sum(c['inp'] for c in cs), sum(c['out'] for c in cs), sum(c['cached'] for c in cs)
        out[step] = dict(label=LABELS[step], total=total, input=inp, cached=cached, cached_share=round(cached / inp, 4),
                         uncached_input=inp - cached, output=outp, uncached_plus_output=inp - cached + outp,
                         session_points=usage[step], calls=cs)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--json', action='store_true', help='print the full breakdown, per call included, as JSON')
    a = p.parse_args()
    b = breakdown()
    if a.json:
        print(json.dumps(b, ensure_ascii=False, indent=2))
        return
    head = ('組別', '總 tokens', '輸入', '快取命中', '命中率', '未命中輸入', '輸出', '未命中輸入＋輸出', 'Session 點數')
    print(' | '.join(head))
    for k, r in b.items():
        print(' | '.join([r['label'], f'{r["total"]:,}', f'{r["input"]:,}', f'{r["cached"]:,}', f'{r["cached_share"]:.0%}',
                          f'{r["uncached_input"]:,}', f'{r["output"]:,}', f'{r["uncached_plus_output"]:,}',
                          f'{r["session_points"]:g}']))
    for site, mem, ctl in (('2030.tw', 'R4', 'B2'), ('保留站', 'HM2', 'HB2')):
        m, c = b[mem], b[ctl]
        print(f'{site}：記憶組總 tokens 比對照組 {m["total"] / c["total"] - 1:+.1%}；'
              f'未命中輸入＋輸出 {m["uncached_plus_output"] / c["uncached_plus_output"] - 1:+.1%}')


if __name__ == '__main__':
    main()
