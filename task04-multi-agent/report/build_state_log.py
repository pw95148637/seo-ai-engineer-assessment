"""Build report/state-log.html from saved v8 run evidence, so every quote matches the raw files.

Run from anywhere: python report/build_state_log.py
Reads only evidence/ (state.json, provider.jsonl, verification.json, metadata.json); makes no model call.
The page shows the tiered runs: MUST items (code check or Auditor) that send a draft back, SHOULD suggestions the
Planner adopts or declines, and what State handed to the next Planner, read back from the raw prompt.
"""
import html, json, re
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE.parent / "evidence"
FORBIDDEN = ("穩賺不賠", "保證出金")
TAIPEI = timezone(timedelta(hours=8))
RUNS = {
    "conflict": "runtime-claude-conflict-v8-1",
    "repeat2": "runtime-claude-conflict-v8-2",
    "repeat3": "runtime-claude-conflict-v8-3",
    "normal": "runtime-claude-normal-v8",
}
LABEL = {"conflict": "強制衝突（第 1 次）", "repeat2": "強制衝突（第 2 次）", "repeat3": "強制衝突（第 3 次）",
         "normal": "一般案例"}
STATUS = {"adopted": "採納", "declined": "不採納", "unanswered": "未回覆", "open": "最後一輪提出，附在定稿上"}


def load(run):
    d = EVIDENCE / run
    read = lambda name: json.loads((d / name).read_text(encoding="utf-8"))
    records = [json.loads(x) for x in (d / "provider.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    return {"dir": run, "state": read("state.json"), "records": records,
            "verification": read("verification.json"), "meta": read("metadata.json")}


def t(text):
    """Escape, highlight the two forbidden words, keep line breaks."""
    out = html.escape(text)
    for word in FORBIDDEN:
        out = out.replace(word, f"<mark>{word}</mark>")
    return out.replace("\n", "<br>")


def excerpt(text, limit, label="展開全文"):
    if len(text) <= limit:
        return f"<p>{t(text)}</p>"
    return (f"<p>{t(text[:limit])}…</p>"
            f"<details><summary>{label}（{len(text)} 字）</summary><p>{t(text)}</p></details>")


def section_text(s):
    return s if isinstance(s, str) else "：".join(x for x in (s["heading"], s["points"]) if x)


def events(run, node):
    return {e["iteration"]: e for e in run["state"]["history"] if e["node"] == node}


def seconds(run, role, iteration):
    done = [r for r in run["records"] if r["role"] == role and r["iteration"] == iteration and not r.get("error")]
    return done[-1]["elapsed_seconds"] if done else None


def planner_prompt(run, iteration):
    rec = [r for r in run["records"] if r["role"] == "planner" and r["iteration"] == iteration and not r.get("error")]
    return json.loads(rec[-1]["request"]["user_prompt"]) if rec else None


def replies_by_id(note):
    """Map 'M1-1、M1-3：...' lines in a Planner note to each MUST id; first line of each reply only."""
    out = {}
    for line in note.splitlines():
        m = re.match(r"^((?:M\d+-\d+[、,，\s]*)+)[：:](.*)$", line.strip())
        if m:
            for ident in re.findall(r"M\d+-\d+", m.group(1)):
                out[ident] = m.group(2).strip()
    return out


def run_meta(run):
    v, m, s = run["verification"], run["meta"], run["state"]
    checks = v["checks"]
    total = round(sum(r["elapsed_seconds"] for r in run["records"]), 1)
    started = datetime.fromisoformat(m["started_at"]).astimezone(TAIPEI).strftime("%Y/%m/%d %H:%M")
    return {"rounds": s["iteration"], "seconds": total, "passed": sum(checks.values()), "checks": len(checks),
            "started": started, "status": s["status"], "final": s["final"]["title"] if s["final"] else "（無）",
            "model": m["planner_model"], "effort": m["effort"], "cli": m["cli_version"].split(" ")[0],
            "policy": m["policy"]["version"], "run_id": s["run_id"]}


def must_list(items, full=True):
    rows = []
    for f in items:
        who = "程式" if f["source"] == "program" else "Auditor"
        reason = f"<div class='reason'><span class='k'>讀者風險</span>{t(f['reason'])}</div>" if full else ""
        rows.append(
            "<li class='finding'>"
            f"<div class='quote'><span class='rule'>{html.escape(f['id'])} {who}・{html.escape(f['rule'])}</span>"
            f"原句：「{t(f['quote'])}」</div>{reason}"
            f"<div class='revision'><span class='k'>修訂建議</span>{t(f['revision'])}</div></li>")
    return "<ol class='findings'>" + "".join(rows) + "</ol>"


def should_list(items, answers=None):
    answers = answers or {}
    rows = []
    for x in items:
        a = answers.get(x["id"])
        reply = (f"<div class='revision'><span class='k'>下一輪 Planner</span>{'採納' if a['action'] == 'adopt' else '不採納'}："
                 f"{t(a.get('reason', ''))}</div>") if a else ""
        rows.append(f"<li class='finding'><div><span class='rule should'>{html.escape(x['id'])} SHOULD</span>"
                    f"{t(x['suggestion'])}</div>{reply}</li>")
    return "<ol class='findings'>" + "".join(rows) + "</ol>"


def handoff(run, iteration, review):
    """What State carried into the next Planner call, read back from the raw prompt."""
    prompt = planner_prompt(run, iteration + 1)
    if not prompt:
        return ""
    ctx = prompt["context"]
    same = ctx.get("review") == review
    hist = "、".join(f"{h['node']} #{h['iteration']}" + (f"（{h['action']}）" if h.get("action") else "")
                    for h in ctx["history"])
    replies = replies_by_id(events(run, "planner")[iteration + 1]["output"]["negotiation_note"])
    rows = "".join(
        f"<tr><td>{html.escape(f['id'])}・{'程式' if f['source'] == 'program' else 'Auditor'}<br>"
        f"{t(f['quote'][:40])}{'…' if len(f['quote']) > 40 else ''}</td>"
        f"<td>{t(replies.get(f['id'], '（說明中沒有逐項回應）')[:110])}"
        f"{'…' if len(replies.get(f['id'], '')) > 110 else ''}</td></tr>"
        for f in review["must"])
    mapping = ("<table class='map'><thead><tr><th>退回的原句（MUST）</th><th>下一輪 Planner 的逐項回應</th></tr></thead>"
               f"<tbody>{rows}</tbody></table>") if review["must"] else ""
    n_prog = sum(f["source"] == "program" for f in review["must"])
    return (
        "<div class='handoff'>"
        f"<h4>State 交給第 {iteration + 1} 輪 Planner 的內容</h4>"
        "<p class='muted'>取自 <code>provider.jsonl</code> 該次呼叫的原始 user prompt。</p>"
        "<ul>"
        f"<li><code>context.iteration</code> = {ctx['iteration']}</li>"
        f"<li><code>context.draft</code>：上一輪自己的草稿（標題「{t(ctx['draft']['title'])}」）</li>"
        f"<li><code>context.review.must</code>：{len(review['must'])} 項必須解決（程式 {n_prog}、Auditor "
        f"{len(review['must']) - n_prog}）；<code>context.review.should</code>：{len(review['should'])} 則建議；"
        f"與第 {iteration} 輪的判定逐字相同：{'是' if same else '否'}</li>"
        f"<li><code>context.history</code>：{html.escape(hist)}</li>"
        "<li>沒有 <code>policy</code>：Planner 看不到規則本文，只能從 review 得知為什麼被退件。</li>"
        "</ul>"
        "<p class='sys'>第 2 輪起 Planner 的系統提示：「review.must 是必須解決的合規問題，未解決就不會發布：每一項怎麼改寫由你決定；"
        "認為原句其實合規可以說明理由，Auditor 有否決權。review.should 是建議，不會讓稿子退回：在 suggestion_responses "
        "對每一則回覆 adopt 或 decline，decline 寫出理由。…」</p>"
        f"{mapping}</div>")


def responses(run, iteration):
    p = events(run, "planner").get(iteration + 1)
    return {r["id"]: r for r in (p["output"].get("suggestion_responses") or [])} if p else {}


def verdict(review):
    if not review["must"]:
        return "<span class='pass'>通過</span>（只剩建議，當輪結束）"
    n_prog = sum(f["source"] == "program" for f in review["must"])
    return f"<span class='fail'>退回：MUST {len(review['must'])} 項</span>（程式 {n_prog}、Auditor {len(review['must']) - n_prog}）"


def full_timeline(run):
    planners, auditors, decisions = events(run, "planner"), events(run, "auditor"), events(run, "decision")
    parts = []
    for i in sorted(planners):
        p, a, d = planners[i]["output"], auditors[i]["output"], decisions[i]
        review = d["review"]
        sections = "".join(f"<li>{t(section_text(x))}</li>" for x in p["sections"])
        if d["action"] == "revise":
            dec = (f"Decision：<b>revise</b>（還有 MUST 項目，未達上限 {run['state']['max_iterations']} 輪）"
                   "→ review.must 與 review.should 經 State 回到 Planning")
        elif d["action"] == "approve_provisional":
            dec = "Decision：<b>approve_provisional</b>（沒有 MUST 項目）→ 輸出最終大綱，附上沒被採納或最後一輪提出的建議"
        else:
            dec = f"Decision：{html.escape(d['action'])}"
        mine = p.get("suggestion_responses") or []
        answered = "".join(f"<li>{html.escape(r['id'])}：{'採納' if r['action'] == 'adopt' else '不採納'}，{t(r.get('reason', ''))}</li>"
                           for r in mine)
        parts.append(
            f"<section class='round'><h3>第 {i} 輪</h3>"
            f"<div class='card planner'><div class='who'>Planner · {seconds(run, 'planner', i)} 秒</div>"
            f"<div class='title'>{t(p['title'])}</div>"
            f"<details><summary>大綱 {len(p['sections'])} 段</summary><ol class='sections'>{sections}</ol></details>"
            f"<div class='k'>negotiation_note（給 Auditor 的說明）</div>{excerpt(p['negotiation_note'], 260)}"
            + (f"<div class='k'>suggestion_responses（對上一輪建議的回覆）</div><ul class='answers'>{answered}</ul>" if mine else "")
            + "</div>"
            f"<div class='card auditor'><div class='who'>程式檢查與 Auditor · {seconds(run, 'auditor', i)} 秒 · {verdict(review)}</div>"
            f"<div class='k'>note（Auditor 給 Planner 的回應）</div>{excerpt(a['note'], 260)}"
            f"{must_list(review['must']) if review['must'] else ''}"
            + (f"<div class='k'>建議（SHOULD，不會造成退回）</div>{should_list(review['should'], responses(run, i))}"
               if review["should"] else "")
            + "</div>"
            f"<div class='decision'>{dec}</div>"
            f"{handoff(run, i, review) if d['action'] == 'revise' else ''}"
            "</section>")
    return "".join(parts)


def compact_timeline(run):
    planners, auditors, decisions = events(run, "planner"), events(run, "auditor"), events(run, "decision")
    rows = []
    for i in sorted(planners):
        p, a, review = planners[i]["output"], auditors[i]["output"], decisions[i]["review"]
        details = ""
        if review["must"]:
            details += (f"<details><summary>{len(review['must'])} 項 MUST（原句、讀者風險、修訂建議）</summary>"
                        f"{must_list(review['must'])}</details>")
        if review["should"]:
            details += (f"<details><summary>{len(review['should'])} 則建議與 Planner 的回覆</summary>"
                        f"{should_list(review['should'], responses(run, i))}</details>")
        rows.append(
            f"<div class='compact'><div class='who'>第 {i} 輪 · {verdict(review)}</div>"
            f"<div class='title'>{t(p['title'])}</div>"
            f"<div class='k'>Auditor note</div>{excerpt(a['note'], 160)}{details}</div>")
    return "".join(rows)


def outline(run):
    final = run["state"]["final"]
    notes = final.get("attached_suggestions") or []
    attached = ("<div class='k'>附在定稿上的建議</div><ul class='answers'>" + "".join(
        f"<li>{html.escape(x['id'])}（{STATUS[x['status']]}）{t(x['suggestion'])}</li>" for x in notes) + "</ul>") if notes else ""
    return (f"<div class='outline'><div class='title'>{t(final['title'])}</div><ol>"
            + "".join(f"<li>{t(section_text(x))}</li>" for x in final["sections"]) + f"</ol>{attached}</div>")


def files(run):
    base = f"tasks/task04-multi-agent/evidence/{run['dir']}/"
    names = ("summary.md", "outline.md", "state.json", "events.jsonl", "provider.jsonl", "verification.json", "metadata.json")
    return "<p class='files'>" + "　".join(f"<code>{base}{n}</code>" for n in names) + "</p>"


def meta_line(run):
    m = run_meta(run)
    return (f"<p class='meta'>{m['started']}（台北）· {m['model']}，effort {m['effort']}，Claude CLI {m['cli']} · "
            f"規則 {m['policy']} · {m['rounds']} 輪 · 角色呼叫合計 {m['seconds']} 秒 · "
            f"機器檢查 {m['passed']}/{m['checks']} · 終止狀態 <code>{m['status']}</code></p>")


CSS = """
:root{--bg:#f7f7f5;--surface:#ffffff;--text:#1d1d1f;--muted:#5f6368;--border:#dedede;
--planner:#2f5fd0;--planner-bg:#eef3ff;--auditor:#9a5b00;--auditor-bg:#fff6e6;--should:#2d6a4f;
--ok:#1e7d32;--bad:#b3261e;--mark-bg:#ffe08a;--mark-text:#3b2a00;--code-bg:#efefec;--handoff-bg:#f0f7f1}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#141416;--surface:#1d1e21;--text:#ececec;
--muted:#a3a3a8;--border:#36373b;--planner:#8fb0ff;--planner-bg:#1c2540;--auditor:#f0b35a;--auditor-bg:#2e2416;--should:#7fd1a8;
--ok:#7bd88a;--bad:#ff8a80;--mark-bg:#6b5200;--mark-text:#fff3c4;--code-bg:#2a2b2f;--handoff-bg:#17261b}}
:root[data-theme="dark"]{--bg:#141416;--surface:#1d1e21;--text:#ececec;--muted:#a3a3a8;--border:#36373b;
--planner:#8fb0ff;--planner-bg:#1c2540;--auditor:#f0b35a;--auditor-bg:#2e2416;--should:#7fd1a8;--ok:#7bd88a;--bad:#ff8a80;
--mark-bg:#6b5200;--mark-text:#fff3c4;--code-bg:#2a2b2f;--handoff-bg:#17261b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.7 system-ui,"Microsoft JhengHei","PingFang TC","Noto Sans TC",sans-serif}
main{max-width:900px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.6rem;line-height:1.35;margin:0 0 8px}h2{font-size:1.25rem;margin:40px 0 8px;padding-top:8px;border-top:1px solid var(--border)}
h3{font-size:1.05rem;margin:0 0 10px}h4{margin:0 0 6px;font-size:.98rem}
p{margin:6px 0}.lead{font-size:1.05rem}.muted,.meta,.files{color:var(--muted);font-size:.9rem}
code{background:var(--code-bg);padding:1px 5px;border-radius:4px;font-size:.86em;overflow-wrap:anywhere}
mark{background:var(--mark-bg);color:var(--mark-text);padding:0 2px;border-radius:3px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:16px 0}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 14px}
.stat .n{font-size:1.05rem;font-weight:600}.stat .final{margin-top:6px;font-size:.92rem}
.keypoints li{margin:4px 0}
.round{position:relative;margin:22px 0;padding-left:18px;border-left:3px solid var(--border)}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 14px;margin:10px 0}
.card.planner{border-left:4px solid var(--planner);background:var(--planner-bg)}
.card.auditor{border-left:4px solid var(--auditor);background:var(--auditor-bg)}
.who{font-weight:600;font-size:.92rem;color:var(--muted);margin-bottom:4px}
.planner .who{color:var(--planner)}.auditor .who{color:var(--auditor)}
.title{font-weight:700;font-size:1.05rem;margin:2px 0 6px}
.k{display:inline-block;font-size:.8rem;font-weight:600;color:var(--muted);margin-right:6px}
.pass{color:var(--ok)}.fail{color:var(--bad)}
.findings{padding-left:22px;margin:10px 0 0}.finding{margin:10px 0}.answers{margin:4px 0;padding-left:20px;font-size:.93rem}
.quote{font-weight:600}.reason,.revision{font-size:.93rem;margin-top:2px}
.rule{display:inline-block;font-size:.75rem;font-weight:700;border:1px solid currentColor;border-radius:4px;padding:0 5px;margin-right:6px;color:var(--auditor)}
.rule.should{color:var(--should)}
.decision{margin:8px 0;padding:6px 12px;border-radius:8px;border:1px dashed var(--border);font-size:.93rem}
.handoff{background:var(--handoff-bg);border:1px solid var(--border);border-radius:10px;padding:12px 14px;margin:10px 0}
.handoff ul{margin:6px 0;padding-left:20px}.sys{font-size:.9rem;color:var(--muted)}
.map{width:100%;border-collapse:collapse;margin-top:8px;font-size:.88rem}
.map th,.map td{border:1px solid var(--border);padding:6px 8px;vertical-align:top;text-align:left}
.compact{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:10px 14px;margin:10px 0}
.outline{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 16px}
.outline ol{padding-left:22px}.outline li{margin:6px 0}
.sections{padding-left:22px;font-size:.92rem}
details{margin:6px 0}summary{cursor:pointer;color:var(--muted);font-size:.9rem}
.note{border:1px solid var(--border);border-radius:10px;padding:10px 14px;background:var(--surface);font-size:.93rem}
@media (max-width:560px){.round{padding-left:10px}.map{font-size:.82rem}}
"""


def build():
    runs = {k: load(v) for k, v in RUNS.items()}
    stats = "".join(
        f"<div class='stat'><div class='muted'>{LABEL[k]}</div>"
        f"<div class='n'>{run_meta(r)['rounds']} 輪 · {run_meta(r)['seconds']} 秒 · 檢查 {run_meta(r)['passed']}/{run_meta(r)['checks']}</div>"
        f"<div class='final'>{t(run_meta(r)['final'])}</div></div>" for k, r in runs.items())
    c = runs["conflict"]
    page = f"""<!doctype html>
<html lang="zh-Hant-TW"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>協商狀態紀錄</title><style>{CSS}</style></head><body><main>
<h1>SEO Planner 與 YMYL Auditor 的協商紀錄（State Log）</h1>
<p class="lead">流量負責人要求標題放「穩賺不賠」或「保證出金」。審核意見分兩級：MUST（程式檢查與 Auditor 依三條合規規則提出）未解決就退回；
SHOULD（Auditor 選填的建議，最多 2 則）由 Planner 採納或附理由不採納，不會造成退回。只剩建議時當輪結束，建議附在定稿上。</p>
<div class="cards">{stats}</div>
<p class="muted">內容由 <code>tasks/task04-multi-agent/report/build_state_log.py</code> 直接讀取執行證據產生，引文與原始檔逐字一致。
「通過」只代表依自訂暫行規則 <code>custom-provisional-v5-tiered</code> 沒有 MUST 項目；公司內部手冊未取得，不代表 100% 合規。Planner 與 Auditor 使用同一個模型。</p>

<h2>一、強制衝突（第 1 次，完整紀錄）</h2>
{meta_line(c)}
<h3>協商重點</h3>
<ul class="keypoints">
<li>第 1 輪：Planner 把兩個指定詞寫進疑問句標題，並在說明中提出兩個退路（改成質疑句型，或把關鍵字移到小標）。程式檢查擋下 6 項（5 處指定詞，以及小標裡的「包贏」）；Auditor 另外退回 4 項：同一個小標裡程式沒擋到的「保證獲利」「穩賺」，以及 3 處 LEGAL（牌照查核會被讀成查得到就能玩、「先看完條款再決定」、介紹公益彩券與運動彩券的段落）。兩個退路都被否決。</li>
<li>第 2 輪：Planner 放棄指定詞，逐項回應 10 項 MUST，採納 2 則建議（建議的標題與一份待查核清單）。Auditor 只退回 1 項，並寫明那是自己上一輪建議的寫法不合規。</li>
<li>第 3 輪：Planner 改寫那個小標並採納另外 2 則建議；沒有 MUST 項目，當輪通過。Auditor 這一輪又提了 2 則建議，依設計不為建議多跑一輪，直接附在定稿上交給人工。</li>
<li>Planner 全程沒有不採納任何建議，也沒有替任何一項 MUST 辯護。</li>
</ul>
{full_timeline(c)}
<h3>最終大綱</h3>
{outline(c)}
<h3>原始檔</h3>
{files(c)}

<h2>二、強制衝突（第 2、3 次，精簡版）</h2>
{meta_line(runs['repeat2'])}
<p>同一份程式與提示詞再跑兩次。第 2 次的第 2 輪，Planner 把「包贏」「零風險」放進小標，被程式擋下；Auditor 另外退回 FAQ 問句裡的「只賺不賠」「一定能出金」。</p>
{compact_timeline(runs['repeat2'])}
<details><summary>最終大綱</summary>{outline(runs['repeat2'])}</details>
{files(runs['repeat2'])}
{meta_line(runs['repeat3'])}
<p>第 3 次的第 2 輪，Auditor 退回小標裡的「不會輸」：意思等同「包贏」，但不在程式的字表裡。</p>
{compact_timeline(runs['repeat3'])}
<details><summary>最終大綱</summary>{outline(runs['repeat3'])}</details>
{files(runs['repeat3'])}

<h2>三、一般案例（精簡版）</h2>
{meta_line(runs['normal'])}
<p>沒有流量要求的對照組。程式擋下內容要點裡當成警訊列出的「保證出金」；Auditor 另外退回 4 項 LEGAL，第 2 輪通過。</p>
{compact_timeline(runs['normal'])}
<details><summary>最終大綱</summary>{outline(runs['normal'])}</details>
{files(runs['normal'])}

<h2>怎麼核對</h2>
<div class="note"><p><code>verify_run.py</code> 從 <code>provider.jsonl</code> 的原始回覆重建每一輪角色輸出，與 <code>state.json</code> 逐筆比對；
再用原始輸出與規則重算每一輪的決策，檢查退回的項目都是 MUST、沒有任何一輪只因建議而退回、定稿附上沒被採納的建議。重跑：
<code>python verify_run.py evidence/runtime-claude-conflict-v8-1</code>（會重寫該目錄的 verification.json 與 summary.md，原始回覆不變）。</p></div>
</main></body></html>
"""
    out = HERE / "state-log.html"
    out.write_bytes(page.encode("utf-8"))
    return out


if __name__ == "__main__":
    print(build())
