"""Markdown tables of evaluation/v09/verdict.json (written by evaluate_v09.py --compare); reads only, prints to stdout.

python scripts/render_v09.py
"""
from pathlib import Path
import json, sys

TASK = Path(__file__).resolve().parents[1]


def fmt(v):
    return '—' if v is None else f'{v:,}' if isinstance(v, int) else str(v)


def render(v):
    rows, out = v['rows'], []
    out.append('| 次 | 對照：找頁／成本／讀站內頁／累積／新頁主張 | 帳本：找頁／成本／讀站內頁／累積／新頁主張／記憶（發現·候選·未知）／解決未知 |')
    out.append('|---:|---|---|')
    for k in range(1, 11):
        cells = []
        for arm in 'CL':
            r = rows.get(f'{arm}{k}')
            if not r:
                cells.append('未執行')
                continue
            cell = '／'.join(fmt(r.get(f)) for f in ('calls', 'cost', 'onsite_count', 'cumulative_onsite', 'new_page_claims'))
            if arm == 'L':
                m = r.get('memory') or {}
                cell += f'／{fmt(m.get("findings"))}·{fmt(m.get("candidates"))}·{fmt(m.get("unknowns"))}' \
                        f'／{len(r.get("resolved_unknowns") or [])}'
            cells.append(cell + ('（隔離失敗）' if r['isolation'] else ''))
        out.append(f'| {k} | ' + ' | '.join(cells) + ' |')
    out.append('')
    for field, title in (('tool_calls', '總工具呼叫'), ('seconds', '耗時（秒）'), ('requests_total', 'HTTP 請求（模型＋控制器）'),
                         ('offsite_pages', '站外頁'), ('cited_claims', '已知＋推論主張'), ('total', '總 tokens'),
                         ('pages', '目標頁')):
        out.append(f'| 組 | {title}：第 1–10 次 |')
        out.append('|---|---|')
        for arm, name in (('C', '對照'), ('L', '帳本')):
            out.append(f'| {name} | {"、".join(fmt((rows.get(f"{arm}{k}") or {}).get(field)) for k in range(1, 11))} |')
        out.append('')
    j = v['judgment']
    out.append(f'- 判定：{j.get("verdict")}；成品：{j.get("product")}；不學習的第 1 對第 10 次：'
               f'{j.get("first_vs_tenth_without_learning")}')
    out.append(f'- F：{j.get("failure")}；L8–L10 成本中位數 {fmt(j.get("late_cost_median"))}，門檻 '
               f'{fmt(round(j["fail_cost"]) if j.get("fail_cost") else None)}（對照中位數 {fmt(j.get("control_cost_median"))}）')
    out.append(f'- 探索 E1：{j["exploration"]}；新頁主張 E2：{j["novelty"]}')
    out.append(f'- 解決的未知（帳本各次）：{j["unknowns"]["resolved"]}；讀了的未讀候選：{j["candidates_read"]}')
    out.append(f'- 盲評洩漏風險：{j.get("blinding_risk")}；實際展示的 run：{j.get("shown_runs")}')
    if v.get('pairwise'):
        det = v['pairwise']['reviewers']
        out.append('')
        out.append('| 比較 | R1 | R2 | R3 | 多數 |')
        out.append('|---|---|---|---|---|')
        for pair in v['pairwise']['votes']:
            cells = [f'{det[r]["pairs"][pair]["preferred"]}（{det[r]["pairs"][pair]["strength"]}）' for r in ('R1', 'R2', 'R3')]
            out.append(f'| {pair} | ' + ' | '.join(cells) + f' | {v["pairwise"]["majority"][pair]} |')
    return '\n'.join(out)


def memory_table(task, v):
    """Research memory per ledger run: what the run was shown, and the findings in the ledger after it learned."""
    out = ['| 次 | 交給模型：仍有效／待重讀／撤銷／未讀候選／未知項 | 重抓頁數（控制器請求） | 讀了的候選 | 學完後的發現：候選／有效／被取代／撤銷 |',
           '|---:|---|---|---|---|']
    for k in range(1, 11):
        r = v['rows'].get(f'L{k}')
        if not r:
            continue
        m = r.get('memory') or {}
        after = sorted((task / 'evaluation' / 'v09' / 'ledger').glob(f'L{k}-attempt*-after.json'))
        counts = {}
        if after:
            for x in json.loads(after[-1].read_text(encoding='utf-8'))['lessons']:
                if x['kind'] == 'finding':
                    counts[x['status']] = counts.get(x['status'], 0) + 1
        shown = '／'.join(fmt(m.get(f)) for f in ('findings', 'recheck', 'revoked', 'candidates', 'unknowns')) if m else '—'
        out.append(f'| {k} | {shown} | {fmt(r.get("controller_requests"))} | {fmt(r.get("candidates_read"))} | '
                   + '／'.join(str(counts.get(s, 0)) for s in ('candidate', 'active', 'superseded', 'revoked')) + ' |')
    return '\n'.join(out)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    verdict = json.loads((TASK / 'evaluation' / 'v09' / 'verdict.json').read_text(encoding='utf-8'))
    print(render(verdict))
    print()
    print(memory_table(TASK, verdict))
