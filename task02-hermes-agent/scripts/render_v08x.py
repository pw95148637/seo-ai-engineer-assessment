"""Markdown tables of evaluation/v08x/verdict.json (written by evaluate_v08x.py --compare); reads only, prints to stdout.

python scripts/render_v08x.py > /tmp/tables.md
"""
from pathlib import Path
import json, sys

TASK = Path(__file__).resolve().parents[1]
ARMS = (('control', 'C', '對照'), ('ledger', 'L', '帳本'), ('native', 'N', '原生'))


def fmt(v):
    return '—' if v is None else f'{v:,}' if isinstance(v, int) else str(v)


def render(v):
    rows, out = v['rows'], []
    out.append('| 次 | 對照：呼叫／成本 | 帳本：呼叫／成本 | 原生：呼叫／成本／研究＋回顧 |')
    out.append('|---:|---|---|---|')
    for k in range(1, 11):
        cells = []
        for arm, x, _ in ARMS:
            r = rows.get(f'{x}{k}')
            if not r:
                cells.append('未執行')
                continue
            cell = f'{fmt(r["calls"])}／{fmt(r["cost"])}'
            if arm == 'native':
                cell += f'／{fmt(r["cost_learning"])}'
            cells.append(cell + ('（隔離失敗）' if r['isolation'] else ''))
        out.append(f'| {k} | ' + ' | '.join(cells) + ' |')
    out.append('')
    for field, title in (('tool_calls', '總工具呼叫'), ('seconds', '耗時（秒）'), ('offsite_pages', '站外頁'),
                         ('claims', '主張數'), ('fetches', '讀頁數（research_fetch）'), ('pages', '目標頁')):
        out.append(f'| 組 | {title}：第 1–5 次 | 第 6–10 次 |')
        out.append('|---|---|---|')
        for arm, x, name in ARMS:
            vals = [fmt((rows.get(f'{x}{k}') or {}).get(field)) for k in range(1, 11)]
            out.append(f'| {name} | {"、".join(vals[:5])} | {"、".join(vals[5:])} |')
        out.append('')
    j = v['judgment']
    out.append('| 項目 | 帳本 | 原生 |')
    out.append('|---|---|---|')
    for key, title in (('verdict', '機械判定（第 10 次對第 1 次與對照）'), ('product', '成品判定（兩兩盲評）')):
        out.append(f'| {title} | {j["ledger"].get(key)} | {j["native"].get(key)} |')
    for key, title in (('maintained', '第 6–10 次找頁維持在對照最小值以下'), ('cost_within_control', '第 6–10 次成本在對照範圍內')):
        out.append(f'| {title} | {j["ledger"][key]["verdict"]} | {j["native"][key]["verdict"]} |')
    for arm in ('ledger', 'native'):
        d = j[arm].get('dimensions')
        if d:
            out.append(f'| {arm} 維度 | 自比 {d["self"]} | 對照 {d["control"]} |')
    out.append('')
    b = j['control_band']
    out.append(f'對照 C1–C10 範圍：呼叫 {b["calls"]}，成本 {b["cost"]}，中位數 {fmt(j["control_cost_median"])}，'
               f'F2 門檻 {fmt(round(j["fail_cost"]) if j["fail_cost"] else None)}；'
               f'C1–C5 {j["control_half_bands"]["C1-C5"]}，C6–C10 {j["control_half_bands"]["C6-C10"]}。')
    if v.get('pairwise'):
        out.append('')
        out.append('| 比較 | R1 | R2 | R3 | 多數 |')
        out.append('|---|---|---|---|---|')
        det = v['pairwise']['reviewers']
        for pair, votes in v['pairwise']['votes'].items():
            cells = [f'{det[r]["pairs"][pair]["preferred"]}（{det[r]["pairs"][pair]["strength"]}）' for r in
                     ('R1', 'R2', 'R3')]
            out.append(f'| {pair} | ' + ' | '.join(cells) + f' | {v["pairwise"]["majority"][pair]} |')
    return '\n'.join(out)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    print(render(json.loads((TASK / 'evaluation' / 'v08x' / 'verdict.json').read_text(encoding='utf-8'))))
