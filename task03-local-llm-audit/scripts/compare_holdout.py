"""Offline: compare the frozen v3b holdout8 outputs (adapter and no-adapter base) with the AI reference labels.

python scripts/compare_holdout.py            (Windows: set PYTHONUTF8=1)
Reads only retrieved Kaggle outputs, evaluation/holdout8-reference.jsonl (independent AI labels written before
reading any model output; not company gold) and evaluation/holdout8-review.csv (per-item semantic verdicts written
after reading the outputs). Writes evaluation/holdout8-comparison.json, report/holdout8-audit.csv and
report/holdout8-audit.html. Never writes into kaggle-retrieved/. No model or GPU is used.
DataFrame: pandas.read_csv('report/holdout8-audit.csv', encoding='utf-8-sig')."""
import csv, difflib, hashlib, html, importlib.util, json, re, sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK / 'scripts'))
from audit_io import max_severity  # noqa: E402
import selfcheck  # noqa: E402  eval-time checker (identical to the eval bundle copy, asserted below)
from workflow import data, targets, knowledge_ids, jsonl, read  # noqa: E402

KR = TASK / 'kaggle-retrieved'
EVAL = KR / 'soulo-work03-v3-eval' / 'work03'
V2 = KR / 'soulo-work03-v2-train' / 'work03'
V3B = KR / 'soulo-work03-v3b-train' / 'work03'
V1 = TASK / 'outputs' / 'experiments' / 'initial'
REF = TASK / 'evaluation' / 'holdout8-reference.jsonl'
REVIEW = TASK / 'evaluation' / 'holdout8-review.csv'
OUT_JSON = TASK / 'evaluation' / 'holdout8-comparison.json'
OUT_CSV = TASK / 'report' / 'holdout8-audit.csv'
OUT_HTML = TASK / 'report' / 'holdout8-audit.html'
HOLDOUT_SHA = '818b491f19541c7703cc311afd498fe1169c223a1c03fb4902e275b46b7a9106'
FROZEN_SELFCHECK_SHA = '627bb2d208ea03ea7498ab51b558c51f64d90afa1b9a1a0e6973036e6f6cc80c'
CODES = ['YMYL_RISK', 'EXPERIENCE_UNVERIFIED', 'STUFFING', 'SEO_FALSE', 'UNSUPPORTED_CLAIM']
RANK = {'none': 0, 'minor': 1, 'major': 2, 'critical': 3}
# Mainland usage written in Traditional characters, with the Taiwan term. Counted in explanation + advice only.
MAINLAND = {'質量': '品質', '搜索': '搜尋', '用戶': '使用者', '鏈接': '連結', '信息': '資訊', '視頻': '影片',
            '軟件': '軟體', '默認': '預設', '網絡': '網路', '優化排名': '提升排名'}
SYSTEMS = {'adapter': 'holdout.jsonl', 'base': 'holdout_base.jsonl'}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def norm_text(p):
    return Path(p).read_text(encoding='utf-8').replace('\r\n', '\n')


def load_frozen_selfcheck():
    """Checker locked in the v3b train bundle, loaded only after its hash matches the declared frozen sha256."""
    p = V3B / 'scripts' / 'selfcheck.py'
    assert sha(p) == FROZEN_SELFCHECK_SHA, 'frozen selfcheck.py hash mismatch'
    spec = importlib.util.spec_from_file_location('selfcheck_frozen', p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def holdout_rows():
    p = EVAL / 'data' / 'holdout8.csv'
    assert sha(p) == HOLDOUT_SHA, 'holdout8.csv bytes changed'
    with p.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    assert [r['ID'] for r in rows] == read(EVAL / 'data' / 'split-manifest.json')['holdout_ids']
    return rows


def text_of(obj, part):
    if not obj:
        return ''
    if part == 'explanation':
        return '\n'.join(r['explanation'] for r in obj['Reasons'])
    return '\n'.join(obj['Actionable Advice'])


def mainland_terms(objs):
    hits = {}
    for i, obj in objs:
        t = text_of(obj, 'explanation') + '\n' + text_of(obj, 'advice')
        for k in MAINLAND:
            n = t.count(k)
            if n:
                hits.setdefault(k, {'taiwan': MAINLAND[k], 'count': 0, 'ids': []})
                hits[k]['count'] += n
                hits[k]['ids'].append(i)
    return dict(total=sum(v['count'] for v in hits.values()), items=len({i for v in hits.values() for i in v['ids']}), terms=hits)


def compare_item(ref, obj):
    req, acc = set(ref['codes']), set(ref['acceptable_extra_codes'])
    alt = ref.get('alternative_reading')
    alt_codes = set(alt['codes']) if alt else set()
    codes = [r['code'] for r in obj['Reasons']]
    cset = set(codes)
    sev = max_severity(obj) or 'none'
    score = obj['Score']
    rng = ref['score_range']
    in_main = rng['min'] <= score <= rng['max']
    in_alt = bool(alt) and alt['score_range']['min'] <= score <= alt['score_range']['max']
    missed = sorted(req - cset)
    unexpected_main = sorted(cset - req - acc)
    unexpected_any = sorted(cset - req - acc - alt_codes)
    sev_main = sev == ref['max_severity']
    sev_alt = bool(alt) and sev == alt['max_severity']
    main_ok = not missed and not unexpected_main and sev_main and in_main
    alt_ok = bool(alt) and alt_codes <= cset and cset <= req | acc | alt_codes and sev_alt and in_alt
    dist = lambda lo, hi: 0 if lo <= score <= hi else min(abs(score - lo), abs(score - hi))
    d_main = dist(rng['min'], rng['max'])
    d_any = min(d_main, dist(alt['score_range']['min'], alt['score_range']['max'])) if alt else d_main
    if main_ok:
        level = 'main_reading_match'
    elif alt_ok:
        level = 'alternative_reading_match'
    elif not req:
        level = 'clean_item_flagged' if RANK[sev] >= RANK['major'] else 'clean_item_minor_flag'
    elif missed:
        level = 'required_code_missed'
    else:
        level = 'codes_hit_severity_or_score_off'
    return dict(codes=codes, severity=sev, score=score, n_reasons=len(codes), n_advice=len(obj['Actionable Advice']),
                sources=[r['source_ids'] for r in obj['Reasons']], ref_codes=sorted(req), ref_acceptable=sorted(acc),
                ref_severity=ref['max_severity'], ref_range=[rng['min'], rng['max']], ref_typical=rng['typical'],
                alt_codes=sorted(alt_codes), alt_severity=alt['max_severity'] if alt else None,
                alt_range=[alt['score_range']['min'], alt['score_range']['max']] if alt else None,
                missed=missed, unexpected_main=unexpected_main, unexpected_incl_alt=unexpected_any,
                severity_main=sev_main, severity_main_or_alt=sev_main or sev_alt,
                severity_direction=RANK[sev] - RANK[ref['max_severity']],
                score_in_main=in_main, score_in_main_or_alt=in_main or in_alt,
                score_error_vs_typical=score - rng['typical'], score_distance_main=d_main, score_distance_main_or_alt=d_any,
                severity_score_match_ignoring_extra_codes=not missed and sev_main and in_main,
                mechanical_level=level)


def code_pr(items, lenient=False):
    out, tp_all, fp_all, fn_all = {}, 0, 0, 0
    for c in CODES:
        tp = fp = fn = 0
        for it in items:
            ignore = set(it['ref_acceptable']) | (set(it['alt_codes']) if lenient else set())
            has, want = c in it['codes'], c in it['ref_codes']
            tp += has and want
            fp += has and not want and c not in ignore
            fn += want and not has
        out[c] = dict(support=tp + fn, predicted_counted=tp + fp, tp=tp, fp=fp, fn=fn,
                      precision=round(tp / (tp + fp), 3) if tp + fp else None,
                      recall=round(tp / (tp + fn), 3) if tp + fn else None)
        tp_all, fp_all, fn_all = tp_all + tp, fp_all + fp, fn_all + fn
    out['micro'] = dict(tp=tp_all, fp=fp_all, fn=fn_all, precision=round(tp_all / (tp_all + fp_all), 3),
                        recall=round(tp_all / (tp_all + fn_all), 3))
    return out


def summarize(items):
    n = len(items)
    errs = [it['score_error_vs_typical'] for it in items]
    return dict(
        n=n,
        code_set_exact_main=sum(not it['missed'] and not it['unexpected_main'] for it in items),
        required_codes_all_hit=sum(not it['missed'] for it in items if it['ref_codes']),
        items_with_required_codes=sum(bool(it['ref_codes']) for it in items),
        severity_match_main=sum(it['severity_main'] for it in items),
        severity_match_main_or_alt=sum(it['severity_main_or_alt'] for it in items),
        severity_higher_than_main=sum(it['severity_direction'] > 0 for it in items),
        severity_lower_than_main=sum(it['severity_direction'] < 0 for it in items),
        score_in_main_range=sum(it['score_in_main'] for it in items),
        score_in_main_or_alt_range=sum(it['score_in_main_or_alt'] for it in items),
        score_mae_vs_typical=round(sum(abs(e) for e in errs) / n, 2),
        score_mean_signed_error_vs_typical=round(sum(errs) / n, 2),
        mechanical_levels={k: [it['ID'] for it in items if it['mechanical_level'] == k]
                           for k in sorted({it['mechanical_level'] for it in items})},
        code_precision_recall_strict=code_pr(items),
        code_precision_recall_alt_codes_ignored=code_pr(items, lenient=True))


def selfcheck_round(bundle, sc_name, rows, T, ids):
    sc = jsonl(bundle / 'outputs' / sc_name)
    cons = read(bundle / 'outputs' / 'consistency.json')
    g = selfcheck.train_gate(rows, sc, cons, T, ids)
    parsed = {r['ID']: r.get('parsed') for r in sc}
    clear = [i for i, t in T.items() if i not in selfcheck.YMYL_BORDERLINE and 'YMYL_RISK' not in {r['code'] for r in t['Reasons']}]
    err = {i: abs(p['Score'] - T[i]['Score']) for i, p in parsed.items() if p}
    flag_counts = {}
    for f in g['hard_failures'] + g['soft_flags']:
        flag_counts[f"{f['level']}:{f['code']}"] = flag_counts.get(f"{f['level']}:{f['code']}", 0) + 1
    by_id = {r['ID']: r for r in rows}
    current = lambda row, p: bool(p) and not selfcheck.contract_flags(row, p, ids)
    return dict(
        selfcheck_file=sc_name,
        own_contract_first=f"{sum(bool(r['first_pass_valid']) for r in sc)}/{len(sc)}",
        own_contract_final=f"{sum(bool(r['final_valid']) for r in sc)}/{len(sc)}",
        current_contract_final=f"{sum(current(by_id[r['ID']], r.get('parsed')) for r in sc)}/{len(sc)}",
        consistency_valid=g['consistency_valid'],
        consistency_current_contract=f"{sum(current(by_id[cons['ID']], r.get('parsed')) for r in cons['runs'])}/{len(cons['runs'])}",
        consistency_id14_scores=[(r.get('parsed') or {}).get('Score') for r in cons['runs']],
        consistency_code_jaccard=[p.get('code_jaccard') for p in cons.get('summary', {}).get('pairs', [])],
        consistency_advice=[(r.get('parsed') or {}).get('Actionable Advice') for r in cons['runs']],
        hard_excl_contract=sorted(f"{f['where']}:{f['code']}" for f in g['hard_failures'] if f['code'] != 'CONTRACT_INVALID'),
        flag_counts=flag_counts,
        distinct_scores=sorted({p['Score'] for p in parsed.values() if p}),
        score_mae_vs_targets=round(sum(err.values()) / len(err), 1), score_mae_n=len(err),
        id14_id7_scores={i: (parsed[i] or {}).get('Score') for i in ('14', '7')},
        ymyl_on_clear=f"{sum(bool(parsed[i]) and 'YMYL_RISK' in {r['code'] for r in parsed[i]['Reasons']} for i in clear)}/{len(clear)}",
        mainland_terms=mainland_terms([(i, p) for i, p in parsed.items()]))


def training_rounds():
    rows, T, ids = data('train12'), targets(), knowledge_ids()
    by_id = {r['ID']: r for r in rows}
    rounds = {}
    v1c = read(V1 / 'consistency.json')
    v1t = read(V1 / 'training.json')
    v1flags = {}
    for run in v1c['runs']:
        for f in selfcheck.item_flags(by_id['14'], run.get('parsed'), T['14']):
            v1flags[f"{f['level']}:{f['code']}"] = v1flags.get(f"{f['level']}:{f['code']}", 0) + 1
    rounds['v1'] = dict(
        steps=v1t['global_step'], train_loss=round(v1t['metrics']['train_loss'], 3), changed_adapter_tensors=v1t['changed_adapter_tensors'],
        note='Only the ID14 three-temperature run exists for v1 (no train12 self-check); flags recomputed with the current checker',
        consistency_code_jaccard=[p.get('code_jaccard') for p in v1c['summary']['pairs']],
        consistency_parsed=f"{sum(r.get('parsed') is not None for r in v1c['runs'])}/{len(v1c['runs'])}",
        consistency_current_contract=f"{sum(bool(r.get('parsed')) and not selfcheck.contract_flags(by_id['14'], r['parsed'], ids) for r in v1c['runs'])}/{len(v1c['runs'])}",
        consistency_id14_scores=[(r.get('parsed') or {}).get('Score') for r in v1c['runs']],
        id14_codes=[[x['code'] for x in (r.get('parsed') or {}).get('Reasons', [])] for r in v1c['runs']],
        max_sources_per_reason=max(len(x['source_ids']) for r in v1c['runs'] for x in (r.get('parsed') or {}).get('Reasons', [])),
        id14_flag_counts=v1flags)
    for name, bundle, sc in (('v2', V2, 'train_selfcheck.jsonl'), ('v3b_adapter', V3B, 'train_selfcheck.jsonl'),
                             ('v3b_base', V3B, 'train_selfcheck_base.jsonl')):
        r = selfcheck_round(bundle, sc, rows, T, ids)
        t = read(bundle / 'outputs' / 'training.json')
        if name != 'v3b_base':
            r.update(steps=t['global_step'], train_loss=round(t['metrics']['train_loss'], 3),
                     train_runtime_s=round(t['metrics']['train_runtime'], 1), changed_adapter_tensors=t['changed_adapter_tensors'])
        else:
            r['note'] = 'Same v3 prompt without adapter; consistency fields belong to the adapter run'
        rounds[name] = r
    log = (KR / 'soulo-work03-v3-train' / 'soulo-work03-v3-train.log').read_text(encoding='utf-8')
    m = re.search(r'OutOfMemoryError: CUDA out of memory\. Tried to allocate ([0-9.]+ GiB)', log)
    rounds['v3'] = dict(oom=bool(m), tried_to_allocate=m.group(1) if m else None,
                        outputs=sorted(p.name for p in (KR / 'soulo-work03-v3-train' / 'work03' / 'outputs').iterdir()))
    return rounds


def load_review():
    if not REVIEW.exists():
        return {}
    with REVIEW.open(encoding='utf-8-sig', newline='') as f:
        return {(r['system'], r['ID']): r for r in csv.DictReader(f)}


def main():
    assert norm_text(TASK / 'scripts' / 'selfcheck.py') == norm_text(EVAL / 'scripts' / 'selfcheck.py'), 'local selfcheck.py differs from the eval bundle'
    frozen = load_frozen_selfcheck()
    rows = holdout_rows()
    refs = {r['ID']: r for r in jsonl(REF)}
    assert sorted(refs) == sorted(r['ID'] for r in rows)
    review = load_review()
    results = {s: {r['ID']: r for r in jsonl(EVAL / 'outputs' / f)} for s, f in SYSTEMS.items()}
    per_item, items_by_sys, disclosure_diffs, flag_audit = [], {s: [] for s in SYSTEMS}, [], []
    for row in rows:
        i, ref = row['ID'], refs[row['ID']]
        rec = dict(ID=i, Category=row['Category'], Keyword=row['Target Keyword'], Article=row['Content Snippet (文章片段)'],
                   ref_confidence=ref['confidence']['level'])
        for s in SYSTEMS:
            res = results[s][i]
            obj = res['parsed']
            assert obj is not None and res['final_valid'], f'{s} ID{i} has no valid output'
            c = compare_item(ref, obj)
            c['ID'] = i
            c['first_pass_valid'], c['final_valid'], c['attempts'] = res['first_pass_valid'], res['final_valid'], len(res['attempts'])
            c['pretty_printed_raw'] = res['attempts'][0]['raw'].lstrip().startswith('{\n')
            # Count rules written in system_prompt.txt but not enforced by schema.json/audit_io:
            # at most 3 reasons, at most 2 cards per reason, advice count <= max(1, reasons).
            c['prompt_count_violations'] = (([f"{len(obj['Reasons'])} reasons > 3"] if len(obj['Reasons']) > 3 else [])
                                            + [f"{r['code']} cites {len(r['source_ids'])} cards > 2" for r in obj['Reasons'] if len(r['source_ids']) > 2]
                                            + ([f"{len(obj['Actionable Advice'])} advice > {max(1, len(obj['Reasons']))}"]
                                               if len(obj['Actionable Advice']) > max(1, len(obj['Reasons'])) else []))
            flags = selfcheck.item_flags(row, obj) + selfcheck.raw_flags(res['attempts'], obj)
            c['auto_flags'] = [f"{f['level']}:{f['code']}" for f in flags]
            for f in flags:
                if f['code'] == 'FALSE_EXPERIENCE':
                    flag_audit.append(dict(system=s, ID=i, flag='hard:FALSE_EXPERIENCE',
                                           self_report_regex_on_article=selfcheck.self_report(row['Content Snippet (文章片段)']),
                                           reference_codes=ref['codes'],
                                           reference_quote=next((k['quote'] for k in ref['key_issues'] if k['code'] == 'EXPERIENCE_UNVERIFIED'), None),
                                           checker_false_positive='EXPERIENCE_UNVERIFIED' in ref['codes'],
                                           cause='SELF_REPORT regex (fixed on train12) lists 實測/心得/體驗… but not 註冊/感受, so 「我實際註冊後最直觀的感受」 is not recognised as a self-report'))
            c['calls_experience_fake'] = any(selfcheck.calls_fake(r['explanation']) for r in obj['Reasons'] if r['code'] == 'EXPERIENCE_UNVERIFIED')
            for a in obj['Actionable Advice']:
                fz, ev = frozen.removes_risk(a), selfcheck.removes_risk(a)
                if fz != ev:
                    disclosure_diffs.append(dict(system=s, ID=i, advice=a, frozen=fz, eval=ev))
            c['reasons'], c['advice'] = obj['Reasons'], obj['Actionable Advice']
            rv = review.get((s, i), {})
            c['verdict'] = rv.get('verdict')
            c['review'] = {k: v for k, v in rv.items() if k not in ('system', 'ID')}
            if c['verdict'] == '準確' and c['missed']:
                raise SystemExit(f'review says 準確 but {s} ID{i} missed {c["missed"]}')
            if c['verdict'] == '準確' and c['mechanical_level'] not in ('main_reading_match', 'alternative_reading_match'):
                c['verdict_note'] = 'verdict 準確 although the mechanical match is ' + c['mechanical_level'] + '; see review text'
            rec[s] = c
            items_by_sys[s].append(c)
        a, b = rec['adapter'], rec['base']
        rec['adapter_vs_base'] = dict(
            same_codes=set(a['codes']) == set(b['codes']), same_severity=a['severity'] == b['severity'], score_diff=a['score'] - b['score'],
            explanation_similarity=round(difflib.SequenceMatcher(None, text_of({'Reasons': a['reasons']}, 'explanation'), text_of({'Reasons': b['reasons']}, 'explanation')).ratio(), 3),
            advice_similarity=round(difflib.SequenceMatcher(None, '\n'.join(a['advice']), '\n'.join(b['advice'])).ratio(), 3))
        per_item.append(rec)

    def has(rec, s, code):
        return code in rec[s]['codes']
    by_id = {r['ID']: r for r in per_item}
    checks = {}
    for s in SYSTEMS:
        checks[s] = dict(
            seo_false_detected={i: has(by_id[i], s, 'SEO_FALSE') for i in ('4', '9')},
            fake_experience_id12=dict(experience_unverified=has(by_id['12'], s, 'EXPERIENCE_UNVERIFIED'),
                                      called_fake=by_id['12'][s]['calls_experience_fake'], also_ymyl=has(by_id['12'], s, 'YMYL_RISK'),
                                      severity=by_id['12'][s]['severity'], score=by_id['12'][s]['score']),
            ymyl_on_clean_8_17={i: has(by_id[i], s, 'YMYL_RISK') for i in ('8', '17')},
            ymyl_on_items_without_ymyl_in_reference=sorted(r['ID'] for r in per_item if 'YMYL_RISK' not in r[s]['ref_codes'] and has(r, s, 'YMYL_RISK')),
            items_without_ymyl_in_reference=sorted(r['ID'] for r in per_item if 'YMYL_RISK' not in r[s]['ref_codes']),
            stuffing_id3=has(by_id['3'], s, 'STUFFING'),
            guarantee_id2_critical=by_id['2'][s]['severity'] == 'critical')
    verdicts = {s: {v: sorted((r['ID'] for r in per_item if r[s]['verdict'] == v), key=lambda x: [r['ID'] for r in per_item].index(x))
                    for v in ('準確', '部分準確', '偏差')} for s in SYSTEMS}
    def mean_review(s, key):
        v = [int(it['review'][key]) for it in items_by_sys[s] if it['review'].get(key, '') != '']
        return round(sum(v) / len(v), 2) if len(v) == 8 else None
    review_scores = {s: dict(mean_source_support_0_2=mean_review(s, 'source_support_0_2'), mean_advice_actionability_0_2=mean_review(s, 'advice_actionability_0_2'),
                             advice_0=[it['ID'] for it in items_by_sys[s] if it['review'].get('advice_actionability_0_2') == '0'],
                             advice_2=[it['ID'] for it in items_by_sys[s] if it['review'].get('advice_actionability_0_2') == '2']) for s in SYSTEMS}
    validity = {s: dict(first_pass=f"{sum(it['first_pass_valid'] for it in items_by_sys[s])}/8",
                        final=f"{sum(it['final_valid'] for it in items_by_sys[s])}/8",
                        repairs_needed=sum(it['attempts'] > 1 for it in items_by_sys[s]),
                        prompt_count_rules_met=f"{sum(not it['prompt_count_violations'] for it in items_by_sys[s])}/8",
                        prompt_count_violations={it['ID']: it['prompt_count_violations'] for it in items_by_sys[s] if it['prompt_count_violations']},
                        pretty_printed_raw=f"{sum(it['pretty_printed_raw'] for it in items_by_sys[s])}/8") for s in SYSTEMS}
    rounds = training_rounds()
    keyword_count = by_id['3']['Article'].count(by_id['3']['Keyword'])
    out = dict(
        scope='holdout8, frozen v3b (lock 8ab9b7ae…), adapter vs same-prompt no-adapter base, greedy decoding. Reference = independent AI labels written before reading any model output; not company gold, not human reviewed. n=8: descriptive only, no general accuracy claim.',
        inputs={str(p.relative_to(TASK).as_posix()): sha(p) for p in (EVAL / 'data' / 'holdout8.csv', EVAL / 'outputs' / 'holdout.jsonl',
                EVAL / 'outputs' / 'holdout_base.jsonl', REF) + ((REVIEW,) if REVIEW.exists() else ())},
        contract_validity=dict(holdout=validity, train_rounds={k: {x: v.get(x) for x in ('own_contract_first', 'own_contract_final', 'current_contract_final', 'consistency_valid', 'consistency_parsed', 'consistency_current_contract') if x in v}
                                                                for k, v in rounds.items() if k != 'v3'},
                               note='own_contract = the contract that round ran with (v1/v2 had no severity field); current_contract = re-checked against the frozen v3 contract. Holdout ran with the v3 contract. prompt_count_rules = limits written in the prompt but not enforced by the contract. Validity is format, not accuracy.'),
        summary={s: summarize(items_by_sys[s]) for s in SYSTEMS},
        verdicts=verdicts,
        review_scores=review_scores,
        review_note='verdicts and 0–2 scores are an AI review written after reading the outputs (evaluation/holdout8-review.csv), not human gold',
        targeted_checks=checks,
        adapter_vs_base=dict(
            same_code_set=sum(r['adapter_vs_base']['same_codes'] for r in per_item), same_severity=sum(r['adapter_vs_base']['same_severity'] for r in per_item),
            same_score=sum(r['adapter_vs_base']['score_diff'] == 0 for r in per_item),
            abs_score_diff_le_5=sum(abs(r['adapter_vs_base']['score_diff']) <= 5 for r in per_item),
            differing_items=[dict(ID=r['ID'], adapter=[r['adapter']['score'], r['adapter']['severity'], r['adapter']['codes']],
                                  base=[r['base']['score'], r['base']['severity'], r['base']['codes']]) for r in per_item
                             if not (r['adapter_vs_base']['same_codes'] and r['adapter_vs_base']['same_severity'] and abs(r['adapter_vs_base']['score_diff']) <= 5)],
            mean_explanation_similarity=round(sum(r['adapter_vs_base']['explanation_similarity'] for r in per_item) / 8, 3),
            mean_advice_similarity=round(sum(r['adapter_vs_base']['advice_similarity'] for r in per_item) / 8, 3)),
        auto_flag_audit=flag_audit,
        risk_disclosure_checker_frozen_vs_eval=dict(advice_checked=sum(len(r[s]['advice']) for r in per_item for s in SYSTEMS),
                                                    differences=disclosure_diffs,
                                                    flagged_by_eval=[dict(system=s, ID=r['ID']) for r in per_item for s in SYSTEMS if any(selfcheck.removes_risk(a) for a in r[s]['advice'])]),
        chinese_usage=dict(mainland_terms_in_explanation_and_advice={s: mainland_terms([(it['ID'], {'Reasons': it['reasons'], 'Actionable Advice': it['advice']}) for it in items_by_sys[s]]) for s in SYSTEMS},
                           simplified_char_flags={s: sum('soft:SIMPLIFIED_CHARS' in it['auto_flags'] for it in items_by_sys[s]) for s in SYSTEMS},
                           non_tw_legal_term_flags={s: sum('soft:NON_TW_LEGAL_TERM' in it['auto_flags'] for it in items_by_sys[s]) for s in SYSTEMS}),
        facts=dict(id3_keyword_occurrences=keyword_count, id3_snippet_chars=len(by_id['3']['Article'])),
        training_rounds=rounds,
        items=per_item)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    write_csv(per_item)
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(render_html(out, refs), encoding='utf-8')
    sys.stdout.reconfigure(errors='replace')
    for s in SYSTEMS:
        sm = out['summary'][s]
        print(s, 'verdicts', {k: len(v) for k, v in verdicts[s].items()}, '| code-set exact', sm['code_set_exact_main'], '| sev main/alt',
              sm['severity_match_main'], sm['severity_match_main_or_alt'], '| score main/alt', sm['score_in_main_range'], sm['score_in_main_or_alt_range'],
              '| MAE', sm['score_mae_vs_typical'], '| micro P/R', sm['code_precision_recall_strict']['micro']['precision'], sm['code_precision_recall_strict']['micro']['recall'])
    print('wrote', OUT_JSON.relative_to(TASK).as_posix(), OUT_CSV.relative_to(TASK).as_posix(), OUT_HTML.relative_to(TASK).as_posix())


def flat_codes(c):
    return ','.join(c['codes']) or '無'


def write_csv(per_item):
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    cols = ['ID', 'Category', 'Article', 'ref_codes', 'ref_severity', 'ref_range', 'ref_alt', 'ref_confidence']
    for s in SYSTEMS:
        cols += [f'{s}_{k}' for k in ('score', 'severity', 'codes', 'verdict', 'mechanical_level', 'score_in_main_or_alt', 'source_support_0_2', 'advice_actionability_0_2', 'auto_flags', 'reasons', 'advice')]
    cols += ['cause_tags', 'explanation', 'base_note']
    with OUT_CSV.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in per_item:
            a = r['adapter']
            d = dict(ID=r['ID'], Category=r['Category'], Article=r['Article'], ref_codes=','.join(a['ref_codes']) or '無',
                     ref_severity=a['ref_severity'], ref_range=f"{a['ref_range'][0]}–{a['ref_range'][1]}",
                     ref_alt=(f"{','.join(a['alt_codes'])} {a['alt_severity']} {a['alt_range'][0]}–{a['alt_range'][1]}" if a['alt_range'] else ''),
                     ref_confidence=r['ref_confidence'], cause_tags=a['review'].get('cause_tags', ''),
                     explanation=a['review'].get('accurate_or_bias_explanation', ''), base_note=r['base']['review'].get('accurate_or_bias_explanation', ''))
            for s in SYSTEMS:
                c = r[s]
                d.update({f'{s}_score': c['score'], f'{s}_severity': c['severity'], f'{s}_codes': flat_codes(c), f'{s}_verdict': c['verdict'] or '',
                          f'{s}_mechanical_level': c['mechanical_level'], f'{s}_score_in_main_or_alt': c['score_in_main_or_alt'],
                          f'{s}_source_support_0_2': c['review'].get('source_support_0_2', ''), f'{s}_advice_actionability_0_2': c['review'].get('advice_actionability_0_2', ''),
                          f'{s}_auto_flags': ';'.join(c['auto_flags']),
                          f'{s}_reasons': json.dumps(c['reasons'], ensure_ascii=False), f'{s}_advice': json.dumps(c['advice'], ensure_ascii=False)})
            w.writerow(d)


def render_html(out, refs):
    e = lambda v: html.escape('' if v is None else str(v))
    sa, sb = out['summary']['adapter'], out['summary']['base']
    va, vb = out['verdicts']['adapter'], out['verdicts']['base']
    pa, pb = sa['code_precision_recall_strict'], sb['code_precision_recall_strict']
    ck = out['targeted_checks']

    def ratio(n, d):
        """Two decimals straight from the counts, half up; re-rounding the stored 3-decimal value shows 5/11 as 0.46."""
        return '–' if not d else str((Decimal(n) / Decimal(d)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    prec = lambda x: ratio(x['tp'], x['tp'] + x['fp'])
    rec = lambda x: ratio(x['tp'], x['tp'] + x['fn'])

    def kpi(label, a, b, note=''):
        return f'<tr><th scope="row">{e(label)}</th><td>{a}</td><td>{b}</td><td class="note">{e(note)}</td></tr>'
    kpis = ''.join([
        kpi('判定 準確／部分準確／偏差', f"{len(va['準確'])}／{len(va['部分準確'])}／{len(va['偏差'])}", f"{len(vb['準確'])}／{len(vb['部分準確'])}／{len(vb['偏差'])}", '逐筆判定見下表；由 AI 判定，不是人工標準答案'),
        kpi('建議可執行性平均（0–2）', out['review_scores']['adapter']['mean_advice_actionability_0_2'], out['review_scores']['base']['mean_advice_actionability_0_2'],
            '0分：有微調 ' + (','.join(out['review_scores']['adapter']['advice_0']) or '無') + '；無微調 ' + (','.join(out['review_scores']['base']['advice_0']) or '無')),
        kpi('來源支持平均（0–2）', out['review_scores']['adapter']['mean_source_support_0_2'], out['review_scores']['base']['mean_source_support_0_2'], '引用的知識卡是否支持該原因'),
        kpi('JSON 格式合格（第一次／重寫後）', out['contract_validity']['holdout']['adapter']['first_pass'] + '／' + out['contract_validity']['holdout']['adapter']['final'],
            out['contract_validity']['holdout']['base']['first_pass'] + '／' + out['contract_validity']['holdout']['base']['final'], 'JSON schema、原文引句、來源ID、Score落在最高severity區間'),
        kpi('prompt數量上限（原因≤3、每原因卡片≤2、建議數≤原因數）', out['contract_validity']['holdout']['adapter']['prompt_count_rules_met'], out['contract_validity']['holdout']['base']['prompt_count_rules_met'],
            '程式沒有強制這三條；違反：有微調 ID ' + (','.join(out['contract_validity']['holdout']['adapter']['prompt_count_violations']) or '無') + '；無微調 ID ' + (','.join(out['contract_validity']['holdout']['base']['prompt_count_violations']) or '無')),
        kpi('應標代碼全數命中', f"{sa['required_codes_all_hit']}/{sa['items_with_required_codes']}", f"{sb['required_codes_all_hit']}/{sb['items_with_required_codes']}", '有應標缺失的6筆'),
        kpi('代碼集合完全吻合（主判讀）', f"{sa['code_set_exact_main']}/8", f"{sb['code_set_exact_main']}/8", '無漏標、無多標（可選附加代碼不算多標）'),
        kpi('代碼 micro precision／recall', f"{prec(pa['micro'])}／{rec(pa['micro'])}", f"{prec(pb['micro'])}／{rec(pb['micro'])}", '樣本小，只作描述'),
        kpi('最高嚴重度一致（主判讀／含替代判讀）', f"{sa['severity_match_main']}／{sa['severity_match_main_or_alt']}", f"{sb['severity_match_main']}／{sb['severity_match_main_or_alt']}", ''),
        kpi('嚴重度高於主判讀', f"{sa['severity_higher_than_main']}/8", f"{sb['severity_higher_than_main']}/8", '等級膨脹；沒有一筆低於主判讀'),
        kpi('分數落在參考區間（主／含替代）', f"{sa['score_in_main_range']}／{sa['score_in_main_or_alt_range']}", f"{sb['score_in_main_range']}／{sb['score_in_main_or_alt_range']}", ''),
        kpi('分數與典型值平均絕對誤差', sa['score_mae_vs_typical'], sb['score_mae_vs_typical'], f"平均偏差 {sa['score_mean_signed_error_vs_typical']}／{sb['score_mean_signed_error_vs_typical']}（負值＝給分偏低）"),
        kpi('錯誤SEO理論 ID4、9 標SEO_FALSE', '／'.join('是' if v else '否' for v in ck['adapter']['seo_false_detected'].values()), '／'.join('是' if v else '否' for v in ck['base']['seo_false_detected'].values()), ''),
        kpi('ID12 自述經驗標EXPERIENCE_UNVERIFIED、未稱造假', '是' if ck['adapter']['fake_experience_id12']['experience_unverified'] and not ck['adapter']['fake_experience_id12']['called_fake'] else '否',
            '是' if ck['base']['fake_experience_id12']['experience_unverified'] and not ck['base']['fake_experience_id12']['called_fake'] else '否', '兩者都另加主題式YMYL_RISK'),
        kpi('沒有缺失的 ID8、17 被標YMYL_RISK', f"{sum(ck['adapter']['ymyl_on_clean_8_17'].values())}/2", f"{sum(ck['base']['ymyl_on_clean_8_17'].values())}/2", ''),
        kpi('參考無YMYL卻被標YMYL_RISK', f"{len(ck['adapter']['ymyl_on_items_without_ymyl_in_reference'])}/{len(ck['adapter']['items_without_ymyl_in_reference'])}",
            f"{len(ck['base']['ymyl_on_items_without_ymyl_in_reference'])}/{len(ck['base']['items_without_ymyl_in_reference'])}", 'IDs ' + ','.join(ck['adapter']['ymyl_on_items_without_ymyl_in_reference'])),
        kpi('ID3 關鍵字堆疊標STUFFING', '是' if ck['adapter']['stuffing_id3'] else '否', '是' if ck['base']['stuffing_id3'] else '否', f"「娛樂城推薦」在{out['facts']['id3_snippet_chars']}字中出現{out['facts']['id3_keyword_occurrences']}次"),
    ])
    pr_rows = ''.join(f"<tr><th scope='row'>{c}</th><td>{pa[c]['support']}</td><td>{pa[c]['tp']}/{pa[c]['fp']}/{pa[c]['fn']}</td><td>{prec(pa[c])}</td><td>{rec(pa[c])}</td>"
                      f"<td>{pb[c]['tp']}/{pb[c]['fp']}/{pb[c]['fn']}</td><td>{prec(pb[c])}</td><td>{rec(pb[c])}</td></tr>" for c in CODES)

    def sysblock(c):
        reasons = ''.join(f"<li><b>{e(r['code'])}</b> <i>{e(r['severity'])}</i>「{e(r['quote'])}」{e(r['explanation'])} <small>[{e(','.join(r['source_ids']))}]</small></li>" for r in c['reasons'])
        adv = ''.join(f'<li>{e(a)}</li>' for a in c['advice'])
        return f"<p class='h'>Reasons</p><ul>{reasons}</ul><p class='h'>Actionable Advice</p><ul>{adv}</ul><p class='flags'>AutoFlags：{e(';'.join(c['auto_flags']) or '無')}</p>"
    rows = []
    for r in out['items']:
        a, b, ref = r['adapter'], r['base'], refs[r['ID']]
        alt = f"<br><small>替代：{e(','.join(a['alt_codes']))} {e(a['alt_severity'])} {a['alt_range'][0]}–{a['alt_range'][1]}</small>" if a['alt_range'] else ''
        refkey = ''.join(f"<li><b>{e(k['code'])}</b>「{e(k['quote'])}」{e(k['issue'])}<br><small>正確知識：{e(k['correct_knowledge'])}</small></li>" for k in ref['key_issues']) or '<li>無應標缺失</li>'
        snf = ''.join(f'<li>{e(x)}</li>' for x in ref['should_not_flag'])
        verdict_cls = {'準確': 'ok', '部分準確': 'mid', '偏差': 'bad'}
        rows.append(
            f"<tr data-va='{e(a['verdict'])}' data-vb='{e(b['verdict'])}'><td data-v='{e(r['ID'])}'>{e(r['ID'])}</td><td>{e(r['Category'])}</td><td class='art'>{e(r['Article'])}</td>"
            f"<td>{e(','.join(a['ref_codes']) or '無')}<br>{e(a['ref_severity'])} {a['ref_range'][0]}–{a['ref_range'][1]}{alt}<br><small>信心：{e(r['ref_confidence'])}</small></td>"
            f"<td data-v='{a['score']}'><b>{a['score']}</b> {e(a['severity'])}<br>{e(flat_codes(a))}</td>"
            f"<td data-v='{b['score']}'><b>{b['score']}</b> {e(b['severity'])}<br>{e(flat_codes(b))}</td>"
            f"<td><span class='v {verdict_cls.get(a['verdict'], '')}'>{e(a['verdict'])}</span></td><td><span class='v {verdict_cls.get(b['verdict'], '')}'>{e(b['verdict'])}</span></td>"
            f"<td class='why'>{e(a['review'].get('accurate_or_bias_explanation'))}<br><small>原因標籤：{e(a['review'].get('cause_tags'))}</small></td>"
            f"<td>{e(a['review'].get('source_support_0_2'))}／{e(a['review'].get('advice_actionability_0_2'))}<br><small>{e(a['review'].get('advice_note'))}</small></td>"
            f"<td><details><summary>展開</summary><p class='h'>參考判斷（AI標註）</p><ul>{refkey}</ul><p class='h'>不應標</p><ul>{snf}</ul>"
            f"<p class='h'>有微調輸出</p>{sysblock(a)}<p class='h'>無微調輸出（同 prompt）</p>{sysblock(b)}"
            f"<p class='h'>無微調的差異</p><p>{e(b['review'].get('accurate_or_bias_explanation'))}</p></details></td></tr>")
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>8 筆測試資料的審核對照</title>
<style>
:root{{--bg:#fff;--fg:#1f2328;--muted:#59636e;--line:#d1d9e0;--head:#f6f8fa;--ok:#1a7f37;--mid:#9a6700;--bad:#cf222e}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#0d1117;--fg:#e6edf3;--muted:#9198a1;--line:#3d444d;--head:#151b23;--ok:#3fb950;--mid:#d29922;--bad:#f85149}}}}
:root[data-theme="dark"]{{--bg:#0d1117;--fg:#e6edf3;--muted:#9198a1;--line:#3d444d;--head:#151b23;--ok:#3fb950;--mid:#d29922;--bad:#f85149}}
body{{background:var(--bg);color:var(--fg);font-family:system-ui,"Noto Sans TC","Microsoft JhengHei",sans-serif;margin:0 auto;padding:16px;max-width:1500px;line-height:1.5}}
h1{{font-size:1.4rem;margin:.2rem 0}} h2{{font-size:1.1rem;margin-top:1.6rem}}
.lead{{color:var(--muted);margin:.3rem 0 1rem}}
.wrap{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;font-size:14px}}
td,th{{border:1px solid var(--line);padding:6px 8px;vertical-align:top;text-align:left}}
thead th{{background:var(--head);cursor:pointer;white-space:nowrap}} th[scope=row]{{background:var(--head);font-weight:600}}
.note,small{{color:var(--muted)}} .art{{min-width:16em}} .why{{min-width:20em}}
.v{{font-weight:700}} .ok{{color:var(--ok)}} .mid{{color:var(--mid)}} .bad{{color:var(--bad)}}
.h{{font-weight:600;margin:.6rem 0 .2rem}} ul{{margin:.2rem 0;padding-left:1.2rem}} .flags{{color:var(--muted);font-size:13px}}
.ctl{{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}} .ctl input,.ctl select{{padding:6px;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:4px}} .ctl input{{flex:1;min-width:12em}}
</style></head><body>
<h1>8 筆測試資料的審核對照：凍結的微調版本與同一個 prompt 無微調</h1>
<p class="lead">Qwen3-8B 4-bit 加 LoRA 微調，凍結後一次執行，greedy 解碼。參考判斷由另一個 AI 在看到模型輸出前寫好，<b>不是公司標準答案；作者看過輸出後逐筆覆核並同意</b>；逐筆判定由 AI 讀過輸出後寫成。只有 8 筆，數字只描述這 8 筆。點表頭排序，可用文字或判定篩選。</p>
<h2>彙總</h2>
<div class="wrap"><table><thead><tr><th>指標</th><th>有微調（凍結版本）</th><th>無微調（同 prompt）</th><th>說明</th></tr></thead><tbody>{kpis}</tbody></table></div>
<h2>每類代碼 precision／recall（主判讀；可選附加代碼不計）</h2>
<div class="wrap"><table><thead><tr><th>代碼</th><th>應標筆數</th><th>有微調 TP/FP/FN</th><th>P</th><th>R</th><th>無微調 TP/FP/FN</th><th>P</th><th>R</th></tr></thead><tbody>{pr_rows}</tbody></table></div>
<h2>逐筆</h2>
<div class="ctl"><input id="q" placeholder="篩選：ID、代碼、文字"><select id="fv"><option value="">有微調判定：全部</option><option>準確</option><option>部分準確</option><option>偏差</option></select></div>
<div class="wrap"><table id="t"><thead><tr><th>ID</th><th>類別</th><th>原文</th><th>參考判斷</th><th>有微調</th><th>無微調</th><th>有微調判定</th><th>無微調判定</th><th>原因分析（有微調）</th><th>來源支持／建議可用（0–2）</th><th>完整輸出</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<p class="lead">產生方式：<code>python scripts/compare_holdout.py</code>（只讀 kaggle-retrieved 原始輸出與 evaluation/ 參考及審核檔）。DataFrame：<code>pandas.read_csv('report/holdout8-audit.csv', encoding='utf-8-sig')</code>。</p>
<script>
const q=document.getElementById('q'),fv=document.getElementById('fv'),tb=document.querySelector('#t tbody');
function f(){{const s=q.value.toLowerCase(),v=fv.value;for(const r of tb.rows){{r.style.display=(r.textContent.toLowerCase().includes(s)&&(!v||r.dataset.va===v))?'':'none'}}}}
q.oninput=f;fv.onchange=f;
document.querySelectorAll('#t thead th').forEach((h,i)=>{{let asc=true;h.onclick=()=>{{const rs=[...tb.rows];rs.sort((x,y)=>{{const a=x.cells[i].dataset.v??x.cells[i].textContent,b=y.cells[i].dataset.v??y.cells[i].textContent,n=parseFloat(a)-parseFloat(b);return(isNaN(n)?a.localeCompare(b,'zh-Hant'):n)*(asc?1:-1)}});asc=!asc;rs.forEach(r=>tb.appendChild(r))}}}});
</script></body></html>"""


if __name__ == '__main__':
    main()
