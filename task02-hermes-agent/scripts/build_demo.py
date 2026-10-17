"""Build a five-minute, captioned replay of saved REAL execution evidence.

This is explicitly a replay, not a screen recording or a fabricated live session.
Needs Pillow, ffmpeg, and a CJK font supplied with --font (not distributed here).
"""
import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
from PIL import Image, ImageDraw, ImageFont


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--font',required=True)
    a=p.parse_args()
    task=Path(__file__).resolve().parents[1]
    evidence=task/'evidence'
    evaluation=json.loads((evidence/'live-agent-evaluation/results.json').read_text())
    if len(evaluation['results'])!=3:raise SystemExit('All three actual model groups must finish first.')
    runs=evidence/'autonomous-research'
    db=sqlite3.connect(runs/'research.sqlite')
    actual=db.execute('SELECT id FROM runs WHERE status="finished" ORDER BY created').fetchall()
    if len(actual)<2:raise SystemExit('Two completed real runs required.')
    memory=db.execute('SELECT status,reason FROM memory WHERE host="2030.tw"').fetchone()
    db.close()
    demo_run=evidence/'live-agent-evaluation/baseline'
    rid=evaluation['results'][0]['run_id']
    usage=json.loads((demo_run/(rid+'-usage.json')).read_text())
    db=sqlite3.connect(demo_run/'research.sqlite')
    calls=[json.loads(v) for (v,) in db.execute('SELECT data FROM events WHERE run=? AND kind="tool_call" ORDER BY id',(rid,))]
    db.close()
    table=[]
    for row in evaluation['results']:
        table.append(f"{row['mode']}：{row['requests']} HTTP｜{row['searches']} 搜尋｜{row['usage'].get('session_total_tokens')} tokens")
    review_path=evidence/'live-agent-evaluation/source-review.json'
    conclusion=json.loads(review_path.read_text()).get('conclusion','未完成語意來源複核，不能宣稱改善。') if review_path.exists() else '未完成語意來源複核，不能宣稱改善。'
    from urllib.parse import unquote
    selected=[c for c in calls if c['name']=='research_status' or '/wordcup/' in c['args'].get('url','') or c['name']=='research_finish']
    chosen=[c['name']+' '+unquote(c['args'].get('url','')) for c in selected[:7]]
    pages=[
        ('真正 Hermes 自主 SEO 研究',20,[
            '目標：研究 2030.tw 的娛樂城／3A娛樂城競爭策略',
            '模型自行選工具、找證據、修正判斷、提交報告。',
            '本片重播已保存的真實紀錄；沒有模擬模型輸出。',
            '模型：gpt-6.1-sol｜OpenAI Codex 訂閱 OAuth',
            '不含憑證；沒有付費 API 或額外 credits。']),
        ('架構與責任',25,[
            'Hermes＋模型：拆問題、提出假設、決定下一步',
            '五個唯讀工具：status / fetch / search / evidence / finish',
            '控制器：robots、精確 host、請求／時間／大小上限',
            'SQLite＋原始快照：URL、HTTP、時間、SHA-256',
            '策略記憶：同站、兩次完成觀察、七天有效',
            'Evaluation：品質與成本分開，保留負結果']),
        ('先驗證模型真的能呼叫工具',25,[
            '官方 Hermes commit：311155fade43…',
            '獨立 profile 正常 OAuth，未採用其他 Session 登入。',
            'smoke：模型自行呼叫 research_status',
            '2 次成功模型呼叫｜4,331 tokens｜included',
            '證據：evidence/model-tool-smoke/',
            '展示 baseline：'+str(usage['session_api_calls'])+' 次模型呼叫，已提交 controller 報告']),
        ('自主研究：原始工具順序',35,chosen[:7]+['完整順序與 purpose 見該 run 的 trace.json。']),
        ('證據如何支持與限制判斷',30,[
            '直接 HTTP：首頁、robots、sitemap、文章原頁',
            '公開索引：只代表當次返回的標題與摘要',
            '搜尋有成功也有逾時；逾時不代表內容不存在。',
            '每筆原文保存 hash；模型引用以 evidence_id 追蹤。',
            'ID／hash 檢查不能保證語意支持，仍做來源複核。',
            '原報告：'+rid+'-report.json']),
        ('有反證，才修正原先假設',25,[
            '抽樣未見 3A，不推成「全站不存在」。',
            '舊語意 URL 回應現行內容，不只憑 slug 判定失效。',
            '體育文章有資料，不概括為所有頁面都是空白導流。',
            '出站註冊連結，不當成本站 backlinks 證明。',
            '這些判斷保留在原始報告與實際來源中。']),
        ('最終研究與可執行性複核',35,[
            '已觀察：體育入口連到 /wordcup/ 娛樂城目錄。',
            'Agent 直接讀到娛樂城、3A 及提款／出金長尾頁。',
            '跨品牌抽樣共用註冊目的地；轉換成效仍未知。',
            '推論：關鍵字覆蓋、模板長尾與共用轉介。',
            '我方先驗證需求，再做透明比較與品牌查證試點。',
            '沒有交易證據不寫親測；不假設可取得對手 GSC。']),
        ('Memory：從候選到採納',30,[
            '第一次完成研究：sitemap 策略為 candidate',
            '第二次完成研究：狀態 '+str(memory[0]),
            '依據：兩次直接來源觀察；只建議 URL 發現順序。',
            '不把索引 URL 數量當內容品質、排名或流量。',
            '記憶只限相同 host、七天有效，反例可撤銷。',
            '實際模型對照凍結學習，避免組間污染。']),
        ('真實模型對照：結果如實保存',40,table+[
            conclusion,
            '每組一次；live 來源可能漂移，不能宣稱統計顯著。',
            '人工元件評估另有品質下降負結果，沒有混作改善。']),
        ('失效、限制與重現',35,[
            '真實 host 拒絕、搜尋逾時與修正全部保留。',
            '39 tests：預算、robots、假引用、hash、錯誤記憶等',
            '大回傳量曾膨脹 context；v0.5 支援精簡與精確片段。',
            '所有對照使用相同 v0.5；不把節流算成記憶效果。',
            '重現入口：README、scripts/setup_research.sh',
            '憑證不在交付包；需正常登入後再跑模型。'])
    ]
    out=task/'demo';frames=out/'frames';frames.mkdir(parents=True,exist_ok=True)
    def font(size,weight):
        value=ImageFont.truetype(a.font,size)
        try:value.set_variation_by_axes([weight])
        except (OSError,ValueError):pass  # Static fonts already use their selected face.
        return value
    titlefont=font(44,600);bodyfont=font(29,400);smallfont=font(20,400)
    def wrap(draw,text,width):
        lines=[];line=''
        for char in text:
            if draw.textlength(line+char,font=bodyfont)>width:
                lines.append(line);line=char
            else:line+=char
        if line:lines.append(line)
        return lines
    subtitles=[];timeline=[];elapsed=0
    for i,(title,duration,lines) in enumerate(pages,1):
        im=Image.new('RGB',(1280,720),'#101b2e');draw=ImageDraw.Draw(im)
        draw.rectangle((0,0,15,720),fill='#4ed9bd')
        draw.text((58,36),f'{i:02d} / 10',font=smallfont,fill='#4ed9bd')
        draw.text((58,80),title,font=titlefont,fill='white')
        y=168
        for line in lines:
            for text in wrap(draw,line,1150):
                draw.text((58,y),text,font=bodyfont,fill='#e1e9f4');y+=40
            y+=11
        if y>652:raise SystemExit(f'Page {i} overflows ({y}); shorten text.')
        draw.line((58,660,1220,660),fill='#38506e',width=2)
        draw.text((58,678),'真實執行紀錄重播｜非即時畫面｜完整證據見交接包',font=smallfont,fill='#b0c1d8')
        frame=frames/f'{i:02d}.png';im.save(frame)
        timeline.extend([f"file 'frames/{i:02d}.png'",f'duration {duration}'])
        def stamp(t):return f'{t//3600:02d}:{t//60%60:02d}:{t%60:02d},000'
        subtitles.append(f'{i}\n{stamp(elapsed)} --> {stamp(elapsed+duration)}\n{title}\n')
        elapsed+=duration
    timeline.append("file 'frames/10.png'")
    (out/'timeline.txt').write_text('\n'.join(timeline)+'\n')
    (out/'captions.srt').write_text('\n'.join(subtitles))
    (out/'README.md').write_text('本片為真實Hermes執行證據的字幕重播，非即時螢幕錄影、非虛構模型示範。無旁白。來源為evidence/autonomous-research及live-agent-evaluation；原始工具順序、模型訊息、來源快照與評估結果均可核對。\n')
    subprocess.run(['ffmpeg','-y','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i',str(out/'timeline.txt'),'-t','300','-vf','fps=10','-c:v','libx264','-preset','fast','-pix_fmt','yuv420p','-movflags','+faststart',str(out/'Hermes_Task02_Demo.mp4')],check=True)
    print(out/'Hermes_Task02_Demo.mp4')


if __name__=='__main__':main()
