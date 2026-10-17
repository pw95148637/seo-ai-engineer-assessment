"""Research-authored supervision for train12 only; never read holdout."""
import csv,json
from pathlib import Path
R=Path(__file__).resolve().parents[1]
# score, severity (band: critical 0-29, major 30-59, minor 60-84; None = no reasons 85-100), code, quoted span, explanation, advice, source IDs
spec={
'20':(95,None,None,'','','保留法拍風險說明，附民法873條來源及查核日期。',['TW_873']),
'6':(70,'minor','UNSUPPORTED_CLAIM','銀行利率通常落在 2%-5%，遠低於民間代書','缺少日期、產品與比較樣本，無法支持通用利率區間；這不等於數字已被證偽。','補具日期的銀行產品與適用條件，並比較總費用年百分率。',['F_APR']),
'15':(50,'major','YMYL_RISK','1.註冊帳號 2.完成實名認證 3.聯繫客服領取體驗金','直接引導參與，未交代賭博財物法律風險，認證亦不能證明平台可信。','改為條款與風險辨識，指出台灣網路賭博財物可能涉及刑法266條，依個案判斷。',['TW_266']),
'5':(62,'minor','EXPERIENCE_UNVERIFIED','實測三個月','僅有自述而無可核對紀錄；不能直接判定造假。15–20倍合理的說法也缺少判準。','補測試日期、方法與紀錄；無實測則改為情境說明，刪去合理倍數背書。',['G_HELP']),
'10':(74,'minor','UNSUPPORTED_CLAIM','真實的娛樂城純屬娛樂','反詐提醒有價值，但純娛樂的概括忽略財務與法域風險，絕對否認任何預測技術亦超過可核對證據。','保留避開保證獲利群組的提醒，改為無法驗證預測能力，不替平台作合法可靠背書。',['TW_266']),
'14':(12,'critical','YMYL_RISK','債務隨便還都可以，銀行不會隨便拍賣你的房子的','淡化還款與抵押物風險，可能誤導借貸決策；到期未清償可聲請法拍。','刪除沒風險及隨便還款話術，說明法拍可能與還款能力、費用及順位檢查。',['TW_873']),
'16':(32,'major','STUFFING','房屋二胎房屋二胎房屋二胎','不自然重複且沒有新增資訊；最好的服務亦缺乏比較證據。','自然使用關鍵字，改寫申請文件、條件、費用及風險；刪去無證據的最佳宣稱。',['G_SPAM']),
'19':(28,'critical','SEO_FALSE','只要字數超過一萬字，不論內容品質，一定能排到第一頁','不存在固定字數即可保證排名的規則，也不能把字數說成唯一排名標準。','刪除RankBrain字數公式，依讀者問題和內容價值決定篇幅。',['G_HELP']),
'7':(15,'critical','YMYL_RISK','不看信用、不看財力，只要有房子保證過件','授信結果被說成保證，0.1%未明示期間與條件，無法反映真實負擔。','刪除保證過件與全台最低，明示計息期間、費用、APR、條件及審核限制。',['F_APR']),
'13':(35,'major','SEO_FALSE','將關鍵字放在 H1 標籤內重複 20 次','沒有固定重複次數提高權威或排名的依據，反有不自然堆疊問題。','用準確清楚的H1描述主題，刪去20次公式及排名承諾。',['G_SPAM']),
'18':(78,'minor','UNSUPPORTED_CLAIM','參考內政部最新的不動產資訊平台數據，以獲取最客觀的市場行情','住宅市場統計不等同個人二胎利率報價，需交代指標用途，不以機關名稱替代證據。','區分市場背景與個人借款成本，附指標日期並比較銀行報價與APR。',['M_PIP','F_APR']),
'11':(84,'minor','UNSUPPORTED_CLAIM','因此利率通常較高','順位可以支持風險方向，但不能單憑法條證明市場利率，仍需同條件報價比較。','保留順位解釋，附民法874條並保留法定優先權例外；利率比較另附產品與日期。',['TW_874'])}
rows=list(csv.DictReader((R/'data/train12.csv').open(encoding='utf-8-sig',newline='')))
assert {r['ID'] for r in rows}==set(spec)
with (R/'data/train_targets.jsonl').open('w',encoding='utf-8',newline='') as f:
 for row in rows:
  score,severity,code,quote,why,advice,sources=spec[row['ID']]
  reasons=[] if code is None else [dict(code=code,quote=quote,explanation=why,source_ids=sources,severity=severity)]
  # Key order is the generation order the model is trained on: evidence and severity before Score.
  target={'Reasons':reasons,'Score':score,'Actionable Advice':[advice]}
  f.write(json.dumps({'ID':row['ID'],'target':target,'provenance':{'author':'AI-assisted research in this Work','human_reviewed':False,'official_gold':False,'sources':sources}},ensure_ascii=False)+'\n')
print('12 train-only supervised targets written; no holdout read')
