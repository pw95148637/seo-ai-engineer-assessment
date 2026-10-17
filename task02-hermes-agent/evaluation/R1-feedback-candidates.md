# R1 人工回饋材料

請你逐項看 R1 報告：主張或行動沒有來源支持就標 `unsupported`，把競爭者與我方網站混淆、或超出公開證據範圍就標 `scope_error`；全部沒問題就記一筆 `ok`。標註會成為 R2、R3 在 `research_status` 看到的 lesson。完成後通知總控執行 R2。

下表由 Claude Code 依快照整理，只列疑點，沒有替你標註。本檔刻意不放分數，避免影響之後的盲評。

## 要執行的命令

開 Ubuntu 終端機執行（Windows 工作樹的 `evaluation/v06/` 只是複本，在那裡改不會生效）：

```bash
cd ~/soulo/task02-hermes
R=evaluation/v06/runs/2030-series
RUN=8cad8d54a03c4f94a716e7653b5b3112

# 看報告原文與目前的 lessons
python3 scripts/feedback.py --root $R list --run $RUN

# 某項沒有來源支持
python3 scripts/feedback.py --root $R label --run $RUN --target claim:N --label unsupported --reason "理由" --reviewer 你的名字

# 某項混淆競爭者與我方網站，或超出公開證據
python3 scripts/feedback.py --root $R label --run $RUN --target action:N --label scope_error --reason "理由" --reviewer 你的名字

# 全部沒問題時（已標過任何一項就不必再記）
python3 scripts/feedback.py --root $R ok --run $RUN --reviewer 你的名字
```

否決 lesson 不能撤回，否決後 R2、R3、HM 都不會再看到它；只在你判斷該 lesson 是錯的時候使用：

```bash
python3 scripts/feedback.py --root $R veto --lesson <lesson id> --reason "理由" --reviewer 你的名字
```

- 理由最多 200 字，不能含網址、路徑或斜線（程式會拒絕），例如寫「引用頁沒有提到出金時間」。理由會原文顯示給下一個 run，請描述錯在哪裡，不要寫出答案。
- 預設只套用在 2030.tw。錯誤與網站無關時加 `--scope general`，保留站的 HM 也會看到。
- 同一項同一標籤只能標一次；要改，先否決那條 lesson 再重標。
- `--reviewer` 寫實際審查者；由總控代填時寫明代填。

## 報告項目與疑點

證據代號是 evidence_id 前 8 碼，對照見最後一節。快照在 `evaluation/v06/runs/2030-series/snapshots/<完整 evidence_id>.txt`。

| 項目 | 摘要 | 引用證據 | 整理者看到的疑點 |
|---|---|---|---|
| claim:1 | 首頁定位為運彩與體育，以「線上娛樂城推薦」連到 `/wordcup/`，不以 3A 為主題 | 1e365e4a | 快照相符，無疑點 |
| claim:2 | `/wordcup/` 有品牌、評價、優惠、玩法、安全出金分類，自稱 2502 篇（未驗證） | 73a15afd | 快照相符，無疑點 |
| claim:3 | 兩個目標頁皆 200、title 對應、canonical 指向自己、`index, follow`，有編輯部與更新日期 | 8cbea41c、a0f2a387 | 快照相符（3A 頁 2026-09-24 更新、主詞頁 2026-10-09） |
| claim:4 | 四個抽樣頁章節結構相同，都連到同一個 3A 外部註冊網址；目錄頁註冊網址帶不同參數 | 73a15afd、8cbea41c、a0f2a387、fb694ab9、ad7150a2 | 四頁都連到同一註冊網址，屬實。目錄頁另有第二個註冊目的地（wg1888 網域），主張沒提到，描述不完整 |
| claim:5 | 推論：體育入口 → 娛樂城目錄 → 品牌與長尾頁 → 外部註冊的導流設計；不代表流量或成效 | 1e365e4a、73a15afd、8cbea41c、ad7150a2 | 推論範圍有限定，無疑點 |
| claim:6 | 3A 主頁自述出金半小時到一小時，出金速度頁自述 15 到 30 分鐘，都沒有測試紀錄；長尾頁有套整串關鍵字的 FAQ | 8cbea41c、ad7150a2 | 兩個時間與該 FAQ 都在快照中，無疑點 |
| claim:7 | 推論：時間差異不能判為造假，但樣本顯示證據透明度與意圖區隔不足的競爭機會 | 8cbea41c、ad7150a2、fb694ab9 | 用語保守。引用富遊頁，但主張沒用到它的內容 |
| claim:8 | 反證：3A 頁有入金門檻、手機版、客服 FAQ、作者與更新標示；主詞頁提醒洗碼量與提領限制 | 8cbea41c、a0f2a387 | 大致相符。「作者」其實只是「2030編輯部」團隊署名，不是具名作者 |
| claim:9 | robots 只擋 `/wp-admin/` 並宣告 sitemap 索引；page-sitemap 沒有 `/wordcup/`；post-sitemap2 被截斷、其他分片未查 | 3fdae3a3、a08ad0bf、02cec170、cbc4f992 | 結論保守，沒有錯。工具回傳的文字確實截在 3 萬字，但網址清單完整（274 個，沒有 `/wordcup/`）；另有 4 份分片未讀 |
| claim:10 | 未知：搜尋無法建立排名證據；無結果不代表沒收錄或零流量 | 無（unknown 類） | 與搜尋快照相符（2 次無結果、1 次只回空白欄位、2 次只有其他網域）。可引用搜尋證據但沒有引用 |
| claim:11 | 未知：流量、CTR、轉換、backlinks、網域歷史；出站連結不是入站連結 | 無（unknown 類） | 不是錯誤。off-page 只列為未知，沒有嘗試用公開搜尋找站外提及；原題要求 on-page 與 off-page 策略，這部分偏薄 |
| action:1 | 我方：先確認目標市場與導流的法律合規，建立我方 GSC 與兩組查詢基線 | — | 範圍正確，無疑點 |
| action:2 | 我方：少量有證據的意圖頁，主詞頁講選擇標準與風險，3A 頁講品牌辨識、條款、出金限制 | — | 依據為 claim:4、claim:6。是否適合我方定位取決於 action:1，報告已列為前置 |
| action:3 | 我方：公開證據與更正制度，不以 SSL 或 KYC 單獨保證合法或安全 | — | 四個抽樣頁都拿 SSL、KYC 當安全論據，有依據，但這個依據沒有寫進任何主張 |
| action:4 | 我方：目錄、主頁、品牌頁內鏈；3A 出金先做專節；不讓不同品牌共用易誤認的 CTA | — | CTA 建議的依據是富遊頁連到 3A 註冊網址（claim:4），無疑點 |
| action:5 | 我方：實測狀態碼、canonical、robots、sitemap、CWV，不憑本次資料指控競爭者 | — | 範圍正確，無疑點 |
| action:6 | 我方：發布後用 GSC 按週追蹤，4 至 8 週檢視；未有證據前不做大量長尾或買連結 | — | 「4 至 8 週」是建議值，不來自證據；報告已寫明不是排名承諾 |

整理者的看法（僅供參照）：沒有找到明顯沒有來源支持、或混淆競爭者與我方網站的項目；疑點多是描述不完整，或依據沒有寫進主張。

## R1 學到的 lessons

| lesson id | 類型與狀態 | 內容 | 整理者看到的疑點 |
|---|---|---|---|
| ffec787a4d7d | 發現路徑，active | 「娛樂城」目標頁經 `/wordcup/` 的連結到達；讀過的 3 份 sitemap 都沒列出此頁 | 錨文字含行銷文案，已截 60 字並標為不可信，無疑點 |
| c5209a7fcd25 | 發現路徑，active | 「3A娛樂城」目標頁經 `/wordcup/` 的連結到達；3 份 sitemap 都沒列出此頁 | 同上 |
| d2e93aa70fca | 失敗模式，candidate（第 2 個 run 重現才會生效） | 含 `site:` 的搜尋 3 次都沒有結果；不含 `site:` 的 2 次都有結果 | 3 次中有 2 次是搜尋套件回報「No results found」例外，程式依設計算成「無結果」而非「錯誤」。這也可能是搜尋供應商處理 `site:` 的方式，不一定代表索引裡沒有該站頁面 |

## 證據代號對照

| 代號 | 完整 evidence_id | 來源 | HTTP |
|---|---|---|---|
| 1e365e4a | 1e365e4a72f04e4791b50a083f98f8bb | 首頁 | 200 |
| 73a15afd | 73a15afdb0fd46f59c440a89406c9acd | `/wordcup/` 娛樂城目錄 | 200 |
| 8cbea41c | 8cbea41c2aa84026be7abd943652ca7e | 3a娛樂城 頁 | 200 |
| a0f2a387 | a0f2a3876e41435ca0754f7297a56d42 | 娛樂城 頁 | 200 |
| fb694ab9 | fb694ab935a941c3926d156532148d8c | 富遊娛樂城 頁 | 200 |
| ad7150a2 | ad7150a251aa44dfbdce34c59c7adbca | 3a娛樂城出金速度 頁 | 200 |
| 3fdae3a3 | 3fdae3a3603f4b30b25806d2c78bcabe | robots.txt | 200 |
| a08ad0bf | a08ad0bf970d45e2b8cf7dd6f179e6bf | sitemap_index.xml | 200 |
| 02cec170 | 02cec170625b402e987fe67e8c2ef903 | page-sitemap.xml | 200 |
| cbc4f992 | cbc4f9925de049a4be49716225e11154 | post-sitemap2.xml | 200 |
