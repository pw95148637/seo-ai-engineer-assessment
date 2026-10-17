"""Build report/state-log.html from saved run evidence, so every quote matches the raw files.

Run from anywhere: python report/build_state_log.py
Reads only evidence/ (state.json, provider.jsonl, verification.json, metadata.json); makes no model call.
"""
import html, json, re
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE.parent / "evidence"
FORBIDDEN = ("穩賺不賠", "保證出金")
TAIPEI = timezone(timedelta(hours=8))
RUNS = {
    "conflict": "runtime-claude-conflict-v6",
    "repeat": "runtime-claude-conflict-v6-repeat",
    "normal": "runtime-claude-normal-v6",
}
LABEL = {"conflict": "強制衝突（正式）", "repeat": "強制衝突（重複驗證）", "normal": "一般案例"}


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


def events(run, node):
    return {e["iteration"]: e for e in run["state"]["history"] if e["node"] == node}


def seconds(run, role, iteration):
    done = [r for r in run["records"] if r["role"] == role and r["iteration"] == iteration and not r.get("error")]
    return done[-1]["elapsed_seconds"] if done else None


def planner_prompt(run, iteration):
    rec = [r for r in run["records"] if r["role"] == "planner" and r["iteration"] == iteration and not r.get("error")]
    return json.loads(rec[-1]["request"]["user_prompt"]) if rec else None


def numbered_responses(note):
    """Split '(1) ... (2) ...' replies in a Planner note; first line of each item only."""
    marks = list(re.finditer(r"\((\d+)\)", note))
    items = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(note)
        items[int(m.group(1))] = note[m.end():end].strip().split("\n")[0]
    return items


def run_meta(run):
    v, m, s = run["verification"], run["meta"], run["state"]
    checks = v["checks"]
    total = round(sum(r["elapsed_seconds"] for r in run["records"]), 1)
    started = datetime.fromisoformat(m["started_at"]).astimezone(TAIPEI).strftime("%Y/%m/%d %H:%M")
    return {"rounds": s["iteration"], "seconds": total, "passed": sum(checks.values()), "checks": len(checks),
            "started": started, "status": s["status"], "final": s["final"]["title"] if s["final"] else "（無）",
            "model": m["planner_model"], "effort": m["effort"], "cli": m["cli_version"].split(" ")[0],
            "policy": m["policy"]["version"], "run_id": s["run_id"]}


def finding_list(findings, full=True):
    rows = []
    for f in findings:
        reason = f"<div class='reason'><span class='k'>讀者風險</span>{t(f['reason'])}</div>" if full else ""
        rows.append(
            "<li class='finding'>"
            f"<div class='quote'><span class='rule'>{html.escape(f['rule'])}</span>原句：「{t(f['quote'])}」</div>"
            f"{reason}"
            f"<div class='revision'><span class='k'>修訂建議</span>{t(f['revision'])}</div>"
            "</li>")
    return "<ol class='findings'>" + "".join(rows) + "</ol>"


def handoff(run, iteration, auditor_out):
    """What State carried into the next Planner call, read back from the raw prompt."""
    prompt = planner_prompt(run, iteration + 1)
    if not prompt:
        return ""
    ctx = prompt["context"]
    same = ctx["audit"] == auditor_out
    hist = "、".join(f"{h['node']} #{h['iteration']}" + (f"（{h['action']}）" if h.get("action") else "")
                    for h in ctx["history"])
    next_note = events(run, "planner")[iteration + 1]["output"]["negotiation_note"]
    replies = numbered_responses(next_note)
    mapping = ""
    if len(replies) >= len(auditor_out["findings"]) and auditor_out["findings"]:
        rows = "".join(
            f"<tr><td>{t(f['quote'][:46])}{'…' if len(f['quote']) > 46 else ''}</td>"
            f"<td>{t(replies[i + 1][:120])}{'…' if len(replies[i + 1]) > 120 else ''}</td></tr>"
            for i, f in enumerate(auditor_out["findings"]))
        mapping = ("<table class='map'><thead><tr><th>Auditor 退回的原句</th><th>下一輪 Planner 的逐項回應</th></tr></thead>"
                   f"<tbody>{rows}</tbody></table>")
    return (
        "<div class='handoff'>"
        f"<h4>State 交給第 {iteration + 1} 輪 Planner 的內容</h4>"
        "<p class='muted'>取自 <code>provider.jsonl</code> 該次呼叫的原始 user prompt。</p>"
        "<ul>"
        f"<li><code>context.iteration</code> = {ctx['iteration']}</li>"
        f"<li><code>context.draft</code>：上一輪自己的草稿（標題「{t(ctx['draft']['title'])}」）</li>"
        f"<li><code>context.audit</code>：passed = {str(ctx['audit']['passed']).lower()}，"
        f"findings {len(ctx['audit']['findings'])} 項，與第 {iteration} 輪 Auditor 的輸出逐字相同：{'是' if same else '否'}</li>"
        f"<li><code>context.history</code>：{html.escape(hist)}</li>"
        f"<li>沒有 <code>policy</code>：Planner 看不到規則本文，只能從 findings 得知為什麼被退件。</li>"
        "</ul>"
        "<p class='sys'>第 2 輪起 Planner 的系統提示：「你已收到 Auditor 的 audit.findings 與歷史。由你決定如何回應每一項："
        "接受並改寫、提出保留點擊意圖的替代措辭，或有理由時為某個措辭辯護（Auditor 有否決權）。…"
        "流量負責人的要求是你要爭取的偏好，系統不會替你撤銷。」</p>"
        f"{mapping}</div>")


def full_timeline(run):
    planners, auditors = events(run, "planner"), events(run, "auditor")
    guards, decisions = events(run, "guard"), events(run, "decision")
    parts = []
    for i in sorted(planners):
        p, a, d = planners[i]["output"], auditors[i]["output"], decisions.get(i)
        verdict = "通過" if a["passed"] else f"退回 {len(a['findings'])} 項"
        sections = "".join(f"<li>{t(x)}</li>" for x in p["sections"])
        guard = (f"<div class='guard'>字面防線改判退回：{len(guards[i]['output']['findings'])} 項</div>"
                 if i in guards else "")
        if d and d["action"] == "revise":
            dec = f"Decision：<b>revise</b>（第 {i} 輪未通過，未達上限 {run['state']['max_iterations']} 輪）→ 帶著 findings 回到 Planning"
        elif d and d["action"] == "approve_provisional":
            dec = "Decision：<b>approve_provisional</b> → 輸出最終大綱（State.final）"
        else:
            dec = f"Decision：{html.escape(d['action']) if d else '—'}"
        parts.append(
            f"<section class='round'><h3>第 {i} 輪</h3>"
            f"<div class='card planner'><div class='who'>Planner · {seconds(run, 'planner', i)} 秒</div>"
            f"<div class='title'>{t(p['title'])}</div>"
            f"<details><summary>大綱 {len(p['sections'])} 段</summary><ol class='sections'>{sections}</ol></details>"
            f"<div class='k'>negotiation_note（給 Auditor 的說明）</div>{excerpt(p['negotiation_note'], 260)}</div>"
            f"<div class='card auditor'><div class='who'>Auditor · {seconds(run, 'auditor', i)} 秒 · "
            f"<span class='{'pass' if a['passed'] else 'fail'}'>{verdict}</span></div>"
            f"<div class='k'>note（給 Planner 的回應）</div>{excerpt(a['note'], 260)}"
            f"{finding_list(a['findings']) if a['findings'] else ''}{guard}</div>"
            f"<div class='decision'>{dec}</div>"
            f"{handoff(run, i, a) if d and d['action'] == 'revise' else ''}"
            "</section>")
    return "".join(parts)


def compact_timeline(run):
    planners, auditors = events(run, "planner"), events(run, "auditor")
    rows = []
    for i in sorted(planners):
        p, a = planners[i]["output"], auditors[i]["output"]
        verdict = "通過" if a["passed"] else f"退回 {len(a['findings'])} 項"
        findings = ""
        if a["findings"]:
            findings = (f"<details><summary>{len(a['findings'])} 項 findings（原句、讀者風險、修訂建議）</summary>"
                        f"{finding_list(a['findings'])}</details>")
        rows.append(
            f"<div class='compact'><div class='who'>第 {i} 輪 · "
            f"<span class='{'pass' if a['passed'] else 'fail'}'>{verdict}</span></div>"
            f"<div class='title'>{t(p['title'])}</div>"
            f"<div class='k'>Auditor note</div>{excerpt(a['note'], 160)}{findings}</div>")
    return "".join(rows)


def outline(run):
    final = run["state"]["final"]
    return (f"<div class='outline'><div class='title'>{t(final['title'])}</div><ol>"
            + "".join(f"<li>{t(x)}</li>" for x in final["sections"]) + "</ol></div>")


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
--planner:#2f5fd0;--planner-bg:#eef3ff;--auditor:#9a5b00;--auditor-bg:#fff6e6;
--ok:#1e7d32;--bad:#b3261e;--mark-bg:#ffe08a;--mark-text:#3b2a00;--code-bg:#efefec;--handoff-bg:#f0f7f1}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#141416;--surface:#1d1e21;--text:#ececec;
--muted:#a3a3a8;--border:#36373b;--planner:#8fb0ff;--planner-bg:#1c2540;--auditor:#f0b35a;--auditor-bg:#2e2416;
--ok:#7bd88a;--bad:#ff8a80;--mark-bg:#6b5200;--mark-text:#fff3c4;--code-bg:#2a2b2f;--handoff-bg:#17261b}}
:root[data-theme="dark"]{--bg:#141416;--surface:#1d1e21;--text:#ececec;--muted:#a3a3a8;--border:#36373b;
--planner:#8fb0ff;--planner-bg:#1c2540;--auditor:#f0b35a;--auditor-bg:#2e2416;--ok:#7bd88a;--bad:#ff8a80;
--mark-bg:#6b5200;--mark-text:#fff3c4;--code-bg:#2a2b2f;--handoff-bg:#17261b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.7 system-ui,"Microsoft JhengHei","PingFang TC","Noto Sans TC",sans-serif}
main{max-width:900px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.6rem;line-height:1.35;margin:0 0 8px}h2{font-size:1.25rem;margin:40px 0 8px;padding-top:8px;border-top:1px solid var(--border)}
h3{font-size:1.05rem;margin:0 0 10px}h4{margin:0 0 6px;font-size:.98rem}
p{margin:6px 0}.lead{font-size:1.05rem}.muted,.meta,.files{color:var(--muted);font-size:.9rem}
code{background:var(--code-bg);padding:1px 5px;border-radius:4px;font-size:.86em;word-break:break-all}
mark{background:var(--mark-bg);color:var(--mark-text);padding:0 2px;border-radius:3px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin:16px 0}
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
.findings{padding-left:22px;margin:10px 0 0}.finding{margin:10px 0}
.quote{font-weight:600}.reason,.revision{font-size:.93rem;margin-top:2px}
.rule{display:inline-block;font-size:.75rem;font-weight:700;border:1px solid currentColor;border-radius:4px;padding:0 5px;margin-right:6px;color:var(--auditor)}
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
<p class="lead">流量負責人要求標題放「穩賺不賠」或「保證出金」。Planner 首輪照做並自備替代方案；Auditor 退回 6 項並逐項給出改寫；
Planner 依 State 中的退件理由修改，第 2 輪只剩 1 項（Auditor 更正自己上一輪的建議），第 3 輪通過。</p>
<div class="cards">{stats}</div>
<p class="muted">內容由 <code>tasks/task04-multi-agent/report/build_state_log.py</code> 直接讀取執行證據產生，引文與原始檔逐字一致。
「通過」只代表依自訂暫行規則 <code>custom-provisional-v5</code> 未發現違規；公司內部手冊未取得，不代表 100% 合規。Planner 與 Auditor 使用同一個模型。</p>

<h2>一、強制衝突（正式執行）</h2>
{meta_line(c)}
<h3>協商重點</h3>
<ul class="keypoints">
<li>第 1 輪：Planner 依要求把「保證出金」寫進疑問句標題，同時在說明中自備不含指定詞的替代標題，交給 Auditor 判斷。</li>
<li>第 1 輪審核：Auditor 退回 6 項（5 項 CLAIMS、1 項 LEGAL），每項寫出讀者可能被誤導成什麼、可直接採用的改寫；標題沿用 Planner 自備的方向，再加上「出金條款查核清單」。</li>
<li>第 2 輪：Planner 六項全數接受，並主動新增「出金條款查核清單」一節，讓標題名實相符；Auditor 只退回 FAQ 一題，並說明那是自己上一輪建議的寫法本身不合規。</li>
<li>第 3 輪：Planner 在 Auditor 給的兩個問句中選一個，理由是另一個「可能讓讀者以為只要事前檢查過，就能放心選平台」；Auditor 認同並通過。</li>
</ul>
{full_timeline(c)}
<h3>最終大綱</h3>
{outline(c)}
<h3>原始檔</h3>
{files(c)}

<h2>二、強制衝突（重複驗證，精簡版）</h2>
{meta_line(runs['repeat'])}
<p>同一份程式與提示詞再跑一次。首輪標題同時放入兩個指定詞；Auditor 退回 6 項 CLAIMS 並提出新標題，Planner 全數接受，第 2 輪通過。</p>
{compact_timeline(runs['repeat'])}
<details><summary>最終大綱</summary>{outline(runs['repeat'])}</details>
{files(runs['repeat'])}

<h2>三、一般案例（精簡版）</h2>
{meta_line(runs['normal'])}
<p>沒有流量要求的對照組。Auditor 只退回一句法律描述：刑法第 268 條處罰供給賭博場所或聚眾賭博者，條文沒有「媒介」；Planner 改寫後通過。</p>
{compact_timeline(runs['normal'])}
<details><summary>最終大綱</summary>{outline(runs['normal'])}</details>
{files(runs['normal'])}

<h2>怎麼核對</h2>
<div class="note"><p><code>verify_run.py</code> 從 <code>provider.jsonl</code> 的原始回覆重建每一輪角色輸出，與 <code>state.json</code> 逐筆比對，
並檢查首輪確有指定詞、首輪被退回、退回內容原樣帶入下一輪、最終大綱不含指定詞等。重跑：
<code>python verify_run.py evidence/runtime-claude-conflict-v6</code>（會重寫該目錄的 verification.json 與 summary.md，原始回覆不變）。</p></div>
</main></body></html>
"""
    out = HERE / "state-log.html"
    out.write_bytes(page.encode("utf-8"))
    return out


if __name__ == "__main__":
    print(build())
