"""Automatic checks fixed before holdout use.

train_gate: in-sample train12 self-check plus ID14 consistency, compared with train targets.
item_flags(row, obj) without a target: reference-free flags for holdout reports (no labels).
Heuristics only; they do not replace semantic review or prove accuracy."""
import re

CRITICAL = {'SEO_FALSE', 'STUFFING', 'YMYL_RISK', 'EXPERIENCE_UNVERIFIED'}
KNOWN_CATEGORIES = {'Mortgage', 'Casino'}
LAW_DOMAIN = {'TW_873': 'Mortgage', 'TW_874': 'Mortgage', 'TW_266': 'Casino'}
TOPIC_DOMAIN = {'F_APR': 'Mortgage', 'M_PIP': 'Mortgage'}
KNOWN_STATUTES = {'873', '874', '266'}
SELF_REPORT = re.compile(r'(我|我們|筆者|本人|小編|作者)[^。！？!?\n]{0,12}?(實測|測試|試過|試用|親身|親自|經驗|心得|使用過|操作過|體驗|玩過|申請過|辦過)|實測|親測|親身|親自')
RISK = re.compile(r'風險|风险|警示|警語|揭露|免責|法律後果|法律責任')
# "沒風險"、"不會有風險"、"風險較低" are claims; deleting them is a fix, not a removal of disclosure.
NEGATED = re.compile(r'(沒有?|毫無|無|零|不會有|不存在|不|低)(任何)?$')
CLAIM_AFTER = re.compile(r'^(較低|很低|極低|很小|極小|不大|不高|為零|可控|不存在)')
DROP = re.compile(r'刪除|刪去|刪掉|移除|拿掉|去掉|省略|淡化|弱化|少提|減少提及|(避免|不要|不必|無須|無需|不需要?)(使用|提及|提到|出現|寫|強調|保留|提)')
OVERSTATE = re.compile(r'(過度|過於|太過)(強調|渲染|誇大|著墨)')
SHRINK = re.compile(r'(減少|縮減|降低)[^，。]{0,3}(風險|警示|警語)[^，。]{0,4}(說明|描述|提示|揭露|段落|字眼|篇幅|內容|提醒|資訊)')
PROHIBIT = re.compile(r'(避免|不要|勿|不得|不可|切勿|別|不應|不宜|不能|禁止|不該)$')
DESCRIBES = re.compile(r'(原文|文章|作者|片段|本文|內文|該文|此文)(中|裡|內)?(已|有|過度|刻意|明顯)?$')
# Words between the verb and the risk word that start a new action/purpose: the risk word is not the verb's object.
BREAK = re.compile(r'並|而|再|改|補|加|新增|保留|說明|附|明示|提醒|揭露|提示|以|但|卻|同時|導致|造成|忽略')
POST_BREAK = re.compile(r'並|而|再|改|補|加|新增|但|卻|同時|後')
QUOTES = '「」『』"\'“”《》 '
OPINION = re.compile(r'個人意見|個人觀點|僅供參考|意見或建議|非專業建議')
FAKE_WORDS = re.compile(r'造假|說謊|捏造|虛構|謊稱|假冒')
STATUTE = re.compile(r'第\s*(\d{1,4})\s*條|(\d{2,4})\s*條')
NON_TW = re.compile(r'民法典|人民法院|人民幣|中華人民共和國|銀保監')
SIMPLIFIED = set('这们个为说风险证应关时会对发经过还没认实详细标题词让该进与务问间页网据')
MANUAL_REVIEW = [
    'explanation忠於所引知識卡，未誇大條文、未由片段推論整站',
    '建議直接修正所指缺失且可執行，未新增無關要求，必要風險揭露仍保留',
    '三溫度建議語意不互相矛盾',
    '繁體中文自然、台灣法域正確',
    'SEO_FALSE／UNSUPPORTED_CLAIM／YMYL_RISK判別合理；分數排序合理（14、7最低，20最高）',
    '未把缺證據說成造假，未替作者捏造自述經驗',
]


def self_report(text):
    return bool(SELF_REPORT.search(text))


def calls_fake(text):
    """Calls the author a liar/faker; negated forms such as 不能判定造假 are fine."""
    return any(not re.search(r'不|非|未|無法|沒有', text[max(0, m.start() - 6):m.start()]) for m in FAKE_WORDS.finditer(text))


def removes_risk(text):
    """True when advice asks to drop, avoid or soften risk/legal disclosure, with the verb before
    (刪除風險警示) or after (風險警語可以省略) the risk word. Deleting a "no risk" claim
    (沒風險、不會有風險、風險較低), prohibitions (不得刪除風險警示), purpose or added-action clauses
    (刪除保證字眼以降低誤導風險、刪除保證過件並補上風險說明) and descriptions of the article are not removals."""
    for clause in re.split(r'[。；;，,！!？?\n]', text):
        for m in SHRINK.finditer(clause):
            if not PROHIBIT.search(clause[:m.start()]):
                return True
        for m in RISK.finditer(clause):
            head, tail = clause[:m.start()], clause[m.end():]
            if NEGATED.search(head.rstrip(QUOTES)) or CLAIM_AFTER.search(tail):
                continue
            window = len(head) - 14
            for pattern, check_prohibit in ((DROP, True), (OVERSTATE, False)):
                for d in pattern.finditer(head):
                    if d.start() < window or DESCRIBES.search(head[:d.start()]):
                        continue
                    if check_prohibit and PROHIBIT.search(head[:d.start()]):
                        continue
                    if not BREAK.search(head[d.end():]):
                        return True
            for d in DROP.finditer(tail):
                if d.start() > 10 or PROHIBIT.search(tail[:d.start()]) or POST_BREAK.search(tail[:d.start()]):
                    continue
                if re.match(r'(了|掉)?(以|來|$)', tail[d.end():]):
                    return True
    return False


def item_flags(row, obj, target=None):
    """List of {level, code, detail}. level 'hard' blocks the train gate; 'soft' needs review."""
    out = []

    def add(level, code, detail=''):
        out.append(dict(level=level, code=code, detail=detail))
    if obj is None:
        add('hard', 'INVALID_JSON', 'no valid JSON after allowed attempts')
        return out
    article = row['Content Snippet (文章片段)']
    cat = row.get('Category', '')
    codes = [r['code'] for r in obj['Reasons']]
    for r in obj['Reasons']:
        if r['code'] == 'EXPERIENCE_UNVERIFIED':
            if not self_report(article):
                add('hard', 'FALSE_EXPERIENCE', r['quote'][:60])
            elif not self_report(r['quote']):
                add('soft', 'EXPERIENCE_QUOTE_WITHOUT_SELF_REPORT', r['quote'][:60])
            if calls_fake(r['explanation']):
                add('soft', 'UNVERIFIED_CALLED_FAKE', r['explanation'][:60])
        for s in r['source_ids']:
            if cat in KNOWN_CATEGORIES and LAW_DOMAIN.get(s, cat) != cat:
                add('hard', 'CROSS_DOMAIN_LAW', f"{r['code']} cites {s} for {cat}")
            if cat in KNOWN_CATEGORIES and TOPIC_DOMAIN.get(s, cat) != cat:
                add('soft', 'OFF_TOPIC_SOURCE', f"{r['code']} cites {s} for {cat}")
        if r['code'] in ('SEO_FALSE', 'STUFFING') and not any(s.startswith('G_') for s in r['source_ids']):
            add('soft', 'SEO_REASON_WITHOUT_G_SOURCE', f"{r['code']} cites {r['source_ids'] or 'no card'}")
        if len(r['source_ids']) > 3:
            add('hard', 'SOURCE_DUMP', f"{r['code']} cites {len(r['source_ids'])} cards")
        elif len(r['source_ids']) > 2:
            add('soft', 'MANY_SOURCES', f"{r['code']} cites {len(r['source_ids'])} cards")
    for a in obj['Actionable Advice']:
        if removes_risk(a):
            add('hard', 'RISK_DISCLOSURE_REMOVAL', a[:80])
        if OPINION.search(a):
            add('soft', 'OPINION_LABEL_AS_FIX', a[:80])
    if len(obj['Reasons']) > 3:
        add('soft', 'REASONS_OVER_3', str(len(obj['Reasons'])))
    if len(obj['Actionable Advice']) > 3:
        add('soft', 'ADVICE_OVER_3', str(len(obj['Actionable Advice'])))
    text = ' '.join([r['explanation'] for r in obj['Reasons']] + obj['Actionable Advice'])
    unknown = sorted({n for m in STATUTE.finditer(text) for n in m.groups() if n and n not in KNOWN_STATUTES})
    if unknown:
        add('soft', 'UNVERIFIED_STATUTE', ','.join(unknown))
    if NON_TW.search(text):
        add('soft', 'NON_TW_LEGAL_TERM', NON_TW.search(text).group())
    simp = ''.join(sorted({c for c in text if c in SIMPLIFIED}))
    if simp:
        add('soft', 'SIMPLIFIED_CHARS', simp)
    if target is not None:
        tcodes = {r['code'] for r in target['Reasons']}
        for c in sorted((tcodes & CRITICAL) - set(codes)):
            add('hard', 'REQUIRED_CODE_MISSED', c)
        for c in sorted(tcodes - CRITICAL - set(codes)):
            add('soft', 'CODE_MISSED', c)
        if not target['Reasons'] and set(codes) & CRITICAL:
            add('hard', 'CLEAN_ITEM_FLAGGED', ','.join(sorted(set(codes) & CRITICAL)))
        if 'YMYL_RISK' in tcodes and target['Score'] <= 29 and obj['Score'] > 29:
            add('hard', 'SEVERE_SCORE_TOO_HIGH', f"{obj['Score']} > 29 (target {target['Score']})")
        elif abs(obj['Score'] - target['Score']) > 20:
            add('soft', 'SCORE_FAR_FROM_TARGET', f"{obj['Score']} vs {target['Score']}")
    return out


def flag_text(flags):
    return ';'.join(f"{f['level']}:{f['code']}" for f in flags)


def train_gate(rows, selfcheck_results, consistency, targets):
    """Gate before freeze. In-sample by construction: necessary, not sufficient."""
    by_id = {r['ID']: r for r in rows}
    hard, soft, items, runs = [], [], [], []

    def collect(where, flags):
        for f in flags:
            (hard if f['level'] == 'hard' else soft).append(dict(f, where=where))
    if selfcheck_results is None:
        hard.append(dict(level='hard', code='SELFCHECK_MISSING', detail='train12 self-check not run', where='train12'))
    else:
        if [r['ID'] for r in selfcheck_results] != [r['ID'] for r in rows]:
            hard.append(dict(level='hard', code='SELFCHECK_INCOMPLETE', detail='IDs differ from train12', where='train12'))
        for res in selfcheck_results:
            flags = item_flags(by_id[res['ID']], res.get('parsed'), targets[res['ID']])
            if not res.get('first_pass_valid'):
                flags.append(dict(level='soft', code='FIRST_PASS_INVALID', detail='needed one JSON repair'))
            obj = res.get('parsed') or {}
            items.append(dict(ID=res['ID'], Score=obj.get('Score'), target_score=targets[res['ID']]['Score'],
                              codes=[r['code'] for r in obj.get('Reasons', [])],
                              target_codes=[r['code'] for r in targets[res['ID']]['Reasons']], flags=flag_text(flags)))
            collect(f"train ID{res['ID']}", flags)
    cid = consistency['ID']
    if sorted(r['temperature'] for r in consistency['runs']) != [0.2, 0.5, 0.8]:
        hard.append(dict(level='hard', code='CONSISTENCY_INCOMPLETE', detail='expected temperatures 0.2/0.5/0.8', where=f'consistency ID{cid}'))
    for run in consistency['runs']:
        flags = item_flags(by_id[cid], run.get('parsed'), targets[cid])
        obj = run.get('parsed') or {}
        runs.append(dict(temperature=run['temperature'], Score=obj.get('Score'),
                         codes=[r['code'] for r in obj.get('Reasons', [])], flags=flag_text(flags)))
        collect(f"consistency ID{cid} T{run['temperature']}", flags)
    s = consistency.get('summary', {})
    if s.get('score_range') is not None and s['score_range'] > 10:
        soft.append(dict(level='soft', code='SCORE_RANGE_OVER_10', detail=str(s['score_range']), where=f'consistency ID{cid}'))
    if any(p.get('code_jaccard') is not None and p['code_jaccard'] < 1 for p in s.get('pairs', [])):
        soft.append(dict(level='soft', code='CODE_SET_DIFFERS', detail='pairwise Jaccard < 1', where=f'consistency ID{cid}'))
    valid = [r for r in (selfcheck_results or [])]
    return dict(status='PASS' if not hard else 'FAIL',
                scope='In-sample: train12 targets and ID14 were used for training/prompt design. Necessary, not sufficient; holdout untouched.',
                selfcheck_first_pass_valid=f"{sum(bool(r.get('first_pass_valid')) for r in valid)}/{len(valid)}",
                selfcheck_final_valid=f"{sum(bool(r.get('final_valid')) for r in valid)}/{len(valid)}",
                consistency_valid=f"{sum(r.get('parsed') is not None for r in consistency['runs'])}/{len(consistency['runs'])}",
                hard_failures=hard, soft_flags=soft, items=items, consistency_runs=runs, manual_review=MANUAL_REVIEW)
