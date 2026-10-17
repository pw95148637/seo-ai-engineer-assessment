"""Score the post-hoc 14B run exactly as pre-registered in evaluation/posthoc14b-plan.md (no GPU, no model).

python scripts/posthoc14b_analysis.py   (Windows: set PYTHONUTF8=1)
Reads the downloaded output of kernel pw95148637/soulo-work03-posthoc-14b from kaggle-retrieved/soulo-work03-posthoc-14b/,
the existing 8B outputs (4-bit without adapter, 4-bit frozen adapter, 16-bit without adapter) and the reference
judgments, and writes evaluation/posthoc14b-results.json. Item comparison is compare_holdout.compare_item via
posthoc_analysis.system; adds no new verdicts."""
import hashlib
import json
import sys
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK / 'scripts'))
from compare_holdout import holdout_rows, EVAL, REF, RANK  # noqa: E402
from posthoc_analysis import system, jsonl  # noqa: E402

PLAN = TASK / 'evaluation' / 'posthoc14b-plan.md'
PLAN_SHA256 = '90e52e6443cabe7503fd7420624a09109bb6bb64f2351bb511ad0382deb4fd69'
POST = TASK / 'kaggle-retrieved' / 'soulo-work03-posthoc-14b' / 'posthoc14b'
FP16 = TASK / 'kaggle-retrieved' / 'soulo-work03-posthoc-fp16' / 'posthoc' / 'holdout_fp16.jsonl'
OUT = TASK / 'evaluation' / 'posthoc14b-results.json'
CLEAN = ('8', '17')            # main reading: no defect at all
GAMBLING_OTHER = ('12', '3')   # gambling context, main reading has another defect
EXCERPT_IDS = ('3', '17', '8')


def reading(over, guard):
    """Pre-registered rule (plan: 判讀規則)."""
    if over >= 3:
        return 'still_topic_flagging'
    if over <= 1 and guard:
        return 'clear_improvement'
    if over <= 1:
        return 'fewer_ymyl_overall_direction_unclear'
    return 'direction_unclear'


READING_TEXT = {
    'still_topic_flagging': '14B 仍依主題多標：模型從 8B 換成 14B，在這 8 筆上沒有消除 YMYL 過度標記；原因較可能在 prompt 或任務框架，'
                            '而不只是 8B 能力不足。更大的模型或改寫框架是否有效，這次沒有驗證。',
    'clear_improvement': '明顯改善：同一個 prompt，14B 分得出談到高風險主題與作出有害說法；在這 8 筆上，8B 的過度標記主要來自模型能力不足，'
                         'prompt 的定義足以讓較大的模型照做。',
    'fewer_ymyl_overall_direction_unclear': 'YMYL 整體標得較少，不能算分辨能力變好；方向不明確。',
    'direction_unclear': '方向不明確。',
}


def excerpt(result):
    p = result['parsed']
    if p is None:
        return dict(valid=False, raw=[a['raw'] for a in result['attempts']])
    return dict(valid=True, Score=p['Score'],
                Reasons=[{k: r[k] for k in ('code', 'severity', 'quote', 'explanation', 'source_ids')} for r in p['Reasons']],
                advice=p['Actionable Advice'], first_pass_valid=result['first_pass_valid'])


def main():
    plan_sha = hashlib.sha256(PLAN.read_bytes()).hexdigest()
    assert plan_sha == PLAN_SHA256, 'the plan file changed after it was registered'
    run_sha = (POST / 'plan_sha256.txt').read_text(encoding='utf-8').strip()
    assert run_sha == plan_sha, 'the Kaggle run embedded a different plan'
    refs = {r['ID']: r for r in jsonl(REF)}
    ids = [r['ID'] for r in holdout_rows()]
    out = EVAL / 'outputs'
    raw = {'qwen3_14b_4bit_no_adapter': jsonl(POST / 'holdout_14b.jsonl'),
           'qwen3_8b_4bit_no_adapter': jsonl(out / 'holdout_base.jsonl'),
           'qwen3_8b_fp16_no_adapter': jsonl(FP16),
           'qwen3_8b_4bit_adapter_frozen': jsonl(out / 'holdout.jsonl')}
    systems = {k: system(v, refs, ids) for k, v in raw.items()}
    big, base = systems['qwen3_14b_4bit_no_adapter'], systems['qwen3_8b_4bit_no_adapter']
    codes = {it['ID']: set(it['codes']) for it in big['items']}
    sev = {it['ID']: it['severity'] for it in big['items']}

    over = big['ymyl_flagged_without_ymyl_in_main']
    guard = dict(id2_ymyl='YMYL_RISK' in codes.get('2', set()),
                 id1_main_or_alt_code=bool({'YMYL_RISK', 'UNSUPPORTED_CLAIM'} & codes.get('1', set())))
    key = reading(len(over), all(guard.values()))
    split = dict(clean_flagged=[i for i in CLEAN if i in over], gambling_other_flagged=[i for i in GAMBLING_OTHER if i in over],
                 others_flagged=[i for i in over if i not in CLEAN + GAMBLING_OTHER])
    checkpoints = {
        '3': dict(stuffing='STUFFING' in codes.get('3', set()), ymyl='YMYL_RISK' in codes.get('3', set())),
        '17': dict(ymyl='YMYL_RISK' in codes.get('17', set()), max_severity=sev.get('17'),
                   minor_or_less=RANK.get(sev.get('17'), 9) <= RANK['minor']),
        '8': dict(ymyl='YMYL_RISK' in codes.get('8', set()), max_severity=sev.get('8'),
                  minor_or_less=RANK.get(sev.get('8'), 9) <= RANK['minor']),
    }

    A = {x['ID']: x for x in big['items']}
    B = {x['ID']: x for x in base['items']}
    common = sorted(set(A) & set(B), key=ids.index)
    tok_big = {r['ID']: r['attempts'][0]['input_tokens'] for r in raw['qwen3_14b_4bit_no_adapter'] if r['attempts']}
    tok_base = {r['ID']: r['attempts'][0]['input_tokens'] for r in raw['qwen3_8b_4bit_no_adapter'] if r['attempts']}
    agreement = dict(compared=len(common),
                     same_code_set=sum(set(A[i]['codes']) == set(B[i]['codes']) for i in common),
                     same_max_severity=sum(A[i]['severity'] == B[i]['severity'] for i in common),
                     same_input_tokens=sum(tok_big.get(i) == tok_base.get(i) for i in ids),
                     differing=[dict(ID=i, qwen3_14b=[A[i]['score'], A[i]['severity'], A[i]['codes']],
                                     qwen3_8b_4bit=[B[i]['score'], B[i]['severity'], B[i]['codes']])
                                for i in common if set(A[i]['codes']) != set(B[i]['codes']) or A[i]['severity'] != B[i]['severity']])

    by = {k: {r['ID']: r for r in v} for k, v in raw.items()}
    excerpts = {i: dict(qwen3_14b=excerpt(by['qwen3_14b_4bit_no_adapter'][i]),
                        qwen3_8b_4bit_no_adapter=excerpt(by['qwen3_8b_4bit_no_adapter'][i])) for i in EXCERPT_IDS}
    env = json.loads((POST / 'env_14b.json').read_text(encoding='utf-8'))
    attempts = [a for r in raw['qwen3_14b_4bit_no_adapter'] for a in r['attempts']]
    run = dict(attempts=len(attempts), repaired_ids=[r['ID'] for r in raw['qwen3_14b_4bit_no_adapter'] if len(r['attempts']) > 1],
               runtime_errors=[r['ID'] for r in raw['qwen3_14b_4bit_no_adapter'] if r.get('runtime_error')],
               generation_seconds_sum=round(sum(a['seconds'] for a in attempts), 1),
               peak_gpu_bytes_max=max(a['peak_gpu_bytes'] for a in attempts),
               output_tokens_mean=round(sum(a['output_tokens'] for a in attempts) / len(attempts), 1),
               eos_reached_all=all(a['eos_reached'] for a in attempts))

    res = dict(
        scope='Post-hoc analysis after the freeze, run as pre-registered in evaluation/posthoc14b-plan.md. '
              'n=8 test items, one greedy run: direction only. Nothing in the frozen system or its reported results changes.',
        plan_sha256=plan_sha, env_14b=env, run_14b=run, systems=systems,
        primary=dict(flagged_without_ymyl_in_main=over, count=len(over), of=len(big['items_without_ymyl_in_main']),
                     baseline_8b_4bit_no_adapter=base['ymyl_flagged_without_ymyl_in_main']),
        guard=guard, reading=key, reading_text=READING_TEXT[key], flagged_split=split, checkpoints=checkpoints,
        qwen3_14b_vs_8b_4bit_no_adapter=agreement, excerpts=excerpts)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')

    cols = ['json_first_pass', 'json_final', 'code_set_exact_main', 'required_codes_all_hit', 'ymyl_flagged_total',
            'ymyl_flagged_without_ymyl_in_main', 'severity_match_main', 'severity_higher_than_main', 'score_in_main_range',
            'score_in_main_or_alt_range', 'score_mae_vs_typical', 'seo_false_on_4_9', 'stuffing_on_3', 'experience_on_12']
    for c in cols:
        print(c.ljust(36), ' | '.join(str(systems[k][c]) for k in systems))
    print('items (ID: score severity codes)')
    for k, s in systems.items():
        print(' ', k, '; '.join(f"{x['ID']}:{x['score']} {x['severity']} {','.join(x['codes'])}" for x in s['items']))
    print('primary', res['primary'], 'guard', guard)
    print('reading', key, '-', READING_TEXT[key])
    print('split', split)
    print('checkpoints', checkpoints)
    print('14B vs 8B 4-bit', {k: v for k, v in agreement.items() if k != 'differing'})
    for d in agreement['differing']:
        print('  ', d)
    print('run', run)


if __name__ == '__main__':
    main()
