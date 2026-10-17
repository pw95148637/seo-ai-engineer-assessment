# holdout8 參考判斷

用途：作為第三題8筆保留資料的比對基準，檢查模型是否抓到應標缺失、是否過度標記。逐筆的引用句、正確知識、不應扣分處與替代判讀見 `holdout8-reference.jsonl`。

**這是AI獨立標註，不是公司gold；作者在看過模型輸出後逐筆覆核，全部同意（見 `holdout8-human-review.md`）。** 判讀有爭議的篇章列出兩種合理判讀，比對時兩者都算合理。

## 參考判斷

| ID | 類別 | 應標代碼 | 最高等級 | 分數區間（典型值） | 關鍵點 | 信心 |
|---|---|---|---|---|---|---|
| 2 | Casino | YMYL_RISK | critical | 0–20（8） | 「保證 100% 獲利」「穩賺不賠」保證獲利，並導流參與賭博（TW_266） | 高 |
| 12 | Casino | EXPERIENCE_UNVERIFIED | minor | 65–80（72） | 「我實際註冊後」自述經驗，未具名平台、無日期或紀錄；不能直接判為造假（G_HELP） | 高 |
| 3 | Casino | STUFFING | major | 30–42（33） | 47字內「娛樂城推薦」出現5次，無資訊（G_SPAM） | 高 |
| 17 | Casino | 無 | none | 85–95（90） | 反詐提醒正確實用；替代判讀：UNSUPPORTED_CLAIM minor 75–84 | 中 |
| 8 | Mortgage | 無 | none | 85–95（90） | 二胎申請文件敘述符合台灣實務，是檢查過度標記的乾淨樣本 | 高 |
| 9 | Mortgage | SEO_FALSE | major | 30–45（35） | 植入錯誤SEO：白字隱藏關鍵字「可以騙過 Google」；官方政策明列為垃圾手法（G_SPAM） | 高 |
| 1 | Casino | YMYL_RISK | major | 40–59（50） | 「小額出金測試」引導實際參與網路賭博，以外國執照暗示可信，未交代刑法266條風險（TW_266）；替代判讀：UNSUPPORTED_CLAIM minor 65–80 | 中 |
| 4 | Casino | SEO_FALSE | major | 30–42（33） | 植入錯誤SEO：Meta Keywords 是「最核心因素」；Google不使用此標記（G_META） | 高 |

可選的附加代碼：ID 2、3 可另列 UNSUPPORTED_CLAIM（「最強」「最棒」無依據），ID 12 可另列 UNSUPPORTED_CLAIM（「PTT 評價兩極」無來源）。列或不列都不算錯，但不得取代主代碼。

## 比對時要注意

- **原題三項檢核對應**：虛假或未驗證經驗看 ID 12；法律常識與過度承諾看 ID 2、1；植入的錯誤SEO理論看 ID 4、9；關鍵字堆疊看 ID 3。
- **過度標記檢查**：ID 8、17 應判無缺失或最多 minor；ID 12 不應標 YMYL_RISK；ID 9 的「我建議」不是自述經驗；ID 4 不因娛樂城主題標 YMYL_RISK。
- **severity 爭議**：ID 9、4 主判 major，若模型給 critical（15–29 或 20–29）屬可辯護的次要判讀，代碼正確仍算抓到錯誤理論。ID 1 主判 major，給 minor 的 UNSUPPORTED_CLAIM 也可辯護，但完全不標屬漏判。
- **知識卡限制**：G_SPAM 的卡片文字只寫 keyword stuffing；ID 9 的依據是同一官方頁面的〈Hidden text and link abuse〉段落（明列 white text on a white background）。ID 1 另附菲律賓2024年底取消離岸博弈執照的新聞來源，屬補充，不要求模型知道，正式引用前需再核原始公告。

## 標註方法

- **獨立**：標註時沒有讀取任何模型輸出、audit report 或其他版本的 outputs。
- **輸入**：`kaggle-retrieved/soulo-work03-v3-eval/work03/data/holdout8.csv`、`system_prompt.txt`（代碼與等級定義）、`schema.json`、`knowledge.json`、`data/train_targets.jsonl`（12筆，用來對齊尺度）、公司原題任務三。
- **尺度對齊**：critical 對照 train ID 7（保證過件，15）、14（淡化法拍，12）、19（字數保證第一頁，28）；major 對照 ID 13（H1重複20次，35）、15（引導註冊領體驗金，50）、16（關鍵字三連重複，32）；minor 對照 ID 5（實測三個月，62）、10（「純屬娛樂」，74）、6、11、18；無缺失對照 ID 20（95）。
- **引用檢查**：所有 `quote` 與替代判讀的候選引用句都以程式比對，確認是原文子字串。
- **外部查核（2026-10-16）**：Google 垃圾內容政策頁（hidden text 與 keyword stuffing 段落、違規後果）、Google Search Central 2009 年〈Google does not use the keywords meta tag in web ranking〉、PAGCOR 2024 年取消 POGO 執照的新聞報導。
- **輸入檔 SHA-256**：holdout8.csv `818b491f…7a9106`、system_prompt.txt `9b5734ef…1ce8b4`、knowledge.json `1fcbb5ed…ba1616`、train_targets.jsonl `622fa83a…3b57cc`。
