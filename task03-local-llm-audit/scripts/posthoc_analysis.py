"""Score the post-hoc runs exactly as pre-registered in evaluation/posthoc-plan.md (no GPU, no model).

python scripts/posthoc_analysis.py   (Windows: set PYTHONUTF8=1)
Reads the downloaded output of kernel pw95148637/soulo-work03-posthoc-fp16 from kaggle-retrieved/soulo-work03-posthoc-fp16/,
the existing eval outputs (frozen 4-bit with adapter, 4-bit without adapter) and the reference judgments, and writes
evaluation/posthoc-results.json. Uses the same item comparison as compare_holdout.py; adds no new verdicts."""
import hashlib
import json
import sys
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK / 'scripts'))
from compare_holdout import compare_item, summarize, holdout_rows, EVAL, REF  # noqa: E402

PLAN = TASK / 'evaluation' / 'posthoc-plan.md'
POST = TASK / 'kaggle-retrieved' / 'soulo-work03-posthoc-fp16' / 'posthoc'
OUT = TASK / 'evaluation' / 'posthoc-results.json'


def jsonl(p):
    return [json.loads(s) for s in Path(p).read_text(encoding='utf-8').splitlines() if s.strip()]


def system(results, refs, ids):
    by = {r['ID']: r for r in results}
    assert sorted(by) == sorted(ids), 'run does not cover the 8 test articles'
    items, invalid = [], []
    for i in ids:
        r = by[i]
        if r['parsed'] is None:
            invalid.append(i)
            continue
        items.append(dict(ID=i, **compare_item(refs[i], r['parsed'])))
    s = summarize(items) if items else {}
    no_ymyl = [i for i in ids if 'YMYL_RISK' not in refs[i]['codes']]
    flagged = {it['ID'] for it in items if 'YMYL_RISK' in it['codes']}
    codes = {it['ID']: set(it['codes']) for it in items}
    return dict(
        json_first_pass=sum(r['first_pass_valid'] for r in results), json_final=sum(r['final_valid'] for r in results),
        invalid_ids=invalid,
        code_set_exact_main=s.get('code_set_exact_main'), required_codes_all_hit=s.get('required_codes_all_hit'),
        items_with_required_codes=s.get('items_with_required_codes'),
        ymyl_flagged_total=len(flagged), ymyl_flagged_without_ymyl_in_main=sorted(flagged & set(no_ymyl)),
        items_without_ymyl_in_main=no_ymyl,
        severity_match_main=s.get('severity_match_main'), severity_higher_than_main=s.get('severity_higher_than_main'),
        score_in_main_range=s.get('score_in_main_range'), score_in_main_or_alt_range=s.get('score_in_main_or_alt_range'),
        score_mae_vs_typical=s.get('score_mae_vs_typical'),
        seo_false_on_4_9={i: 'SEO_FALSE' in codes.get(i, set()) for i in ('4', '9')},
        stuffing_on_3='STUFFING' in codes.get('3', set()),
        experience_on_12='EXPERIENCE_UNVERIFIED' in codes.get('12', set()),
        items=[dict(ID=it['ID'], codes=it['codes'], severity=it['severity'], score=it['score']) for it in items])


def agreement(a, b):
    A = {x['ID']: x for x in a['items']}
    B = {x['ID']: x for x in b['items']}
    common = sorted(set(A) & set(B))
    return dict(compared=len(common),
                same_code_set=sum(set(A[i]['codes']) == set(B[i]['codes']) for i in common),
                same_max_severity=sum(A[i]['severity'] == B[i]['severity'] for i in common),
                differing=[dict(ID=i, fp16=[A[i]['score'], A[i]['severity'], A[i]['codes']],
                                base_4bit=[B[i]['score'], B[i]['severity'], B[i]['codes']])
                           for i in common if set(A[i]['codes']) != set(B[i]['codes']) or A[i]['severity'] != B[i]['severity']])


def reading_a(fp16, base):
    """Pre-registered rule for experiment A."""
    over = len(fp16['ymyl_flagged_without_ymyl_in_main'])
    better_codes = (fp16['code_set_exact_main'] or 0) - (base['code_set_exact_main'] or 0) >= 2
    if over <= 1 and better_codes:
        return 'quantization may be an important factor in YMYL over-flagging'
    if over >= 3:
        return 'YMYL over-flagging is not caused by 4-bit quantization; 16-bit does the same on these 8 items'
    return 'direction unclear'


def reading_b(red):
    """Pre-registered rule for experiment B."""
    if red < 0.05:
        return 'fine-tuning barely changed the fit to the supervised answers'
    if red <= 0.30:
        return 'fine-tuning moved the model closer to the supervised answers, but this did not turn into different judgments on the test items'
    return 'fine-tuning clearly changed the fit while behaviour barely changed; behaviour is driven mainly by the base model and prompt'


def main():
    plan_sha = hashlib.sha256(PLAN.read_bytes()).hexdigest()
    run_sha = (POST / 'plan_sha256.txt').read_text(encoding='utf-8').strip()
    assert run_sha == plan_sha, 'the Kaggle run embedded a different plan'
    refs = {r['ID']: r for r in jsonl(REF)}
    ids = [r['ID'] for r in holdout_rows()]
    out = EVAL / 'outputs'
    systems = {'fp16_no_adapter': system(jsonl(POST / 'holdout_fp16.jsonl'), refs, ids),
               'base_4bit_no_adapter': system(jsonl(out / 'holdout_base.jsonl'), refs, ids),
               'frozen_4bit_adapter': system(jsonl(out / 'holdout.jsonl'), refs, ids)}
    loss = json.loads((POST / 'train_target_loss.json').read_text(encoding='utf-8'))
    env = json.loads((POST / 'fp16_env.json').read_text(encoding='utf-8'))
    res = dict(
        scope='Post-hoc analysis after the freeze, run as pre-registered in evaluation/posthoc-plan.md. '
              'n=8 test items: direction only. Nothing in the frozen system or its reported results changes.',
        plan_sha256=plan_sha, fp16_env=env, systems=systems,
        fp16_vs_base_4bit=agreement(systems['fp16_no_adapter'], systems['base_4bit_no_adapter']),
        reading_a=reading_a(systems['fp16_no_adapter'], systems['base_4bit_no_adapter']),
        train_target_loss={k: loss[k] for k in ['answer_tokens', 'ce_base', 'ce_adapter', 'relative_reduction']},
        train_target_loss_items=loss['items'],
        reading_b=reading_b(loss['relative_reduction']))
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    for k, s in systems.items():
        print(k, {x: s[x] for x in ['json_first_pass', 'code_set_exact_main', 'ymyl_flagged_total',
                                     'ymyl_flagged_without_ymyl_in_main', 'severity_higher_than_main',
                                     'score_in_main_range', 'score_mae_vs_typical']})
    print('fp16 vs 4-bit base', {k: v for k, v in res['fp16_vs_base_4bit'].items() if k != 'differing'})
    print('A:', res['reading_a'])
    print('B:', res['train_target_loss'], res['reading_b'])


if __name__ == '__main__':
    main()
