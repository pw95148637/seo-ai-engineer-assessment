---
name: prompt-chain
description: 執行第一題提示詞鏈：關鍵字 → 微意圖 → 玩家視角長文 → E-E-A-T/YMYL 自我修正 → 定稿與對照組。主對話當主控，每步交給新的 subagent，依關卡檢查、退回修正，再進下一步。使用者說「跑提示詞鏈」「執行第一題」或輸入 /prompt-chain 時使用；使用者確認品質後說「產出交付成品」時執行第 11 步。
---

# 提示詞鏈主控

你是這條鏈的主控。目標是用最少的人工介入，產出一篇通過 E-E-A-T／YMYL 自我修正、讀起來像台灣資深玩家獨立心得的最終文章，並留下可審查的過程紀錄。

流程的設計依據：品質主要來自輸入（事先查證的來源與作者本人的經驗）和「沒參與的人把全文從頭讀一遍」；寫作只需要一次，審核依會出錯的類型分給三位平行進行，修正一次整合，最後一步一定是檢查而不是修改。

## 你的職責

- **不親自寫各階段內容。** 每一步用 Agent 工具開一個新的 subagent（預設 general-purpose），交給它：該步 prompt 檔全文、輸入檔的路徑（prompt 的「輸入」已列出）、（重試時）你的具體修正意見。每步用新脈絡，寫的人不審自己。
- **每步做關卡判斷。** 通過就進下一步；不通過就把具體問題（引用原句、對應哪條標準）交回該步重做，每步最多重試 2 次。
- **等每個 subagent 完成、讀過產出再進下一步。** 互不依賴的步驟在同一則訊息同時開多個 subagent。非互動執行（`claude -p`）時，寫完 `run-summary.md` 之前不要結束回合，避免背景中的 subagent 隨工作階段一起中斷。
- **記錄。** 每步結束時在 `outputs/run-log.md` 追加一段：步驟、第幾次嘗試、關卡結果、你給的修正意見、決定，以及 subagent 回報的 token 數與耗時。派 subagent 時把它的 agent id、組別、步驟記進 `outputs/agents.json`（格式見 `tools/cost_report.py --help`），供成本換算。

## 什麼時候停下來問使用者

作者在線時最多停兩次：第 3 步作者訪談、第 6 步作者確認。另外兩種情況才停：某一步重試 2 次仍不過關；或你發現題目、作者經驗或法律風險上需要使用者本人判斷的事。

## 參數

- 關鍵字：預設「娛樂城」。
- 選題：使用者有指定意圖就用；否則由你在第 2 步決定。
- 作者經驗：`inputs/experience.md`。

## 步驟

0. **準備**
   - 確認 `prompts/`、`style-guide.md`、`evidence-pack.md`、`tools/` 存在。
   - `outputs/` 已存在且有內容時，先改名為 `outputs-<版本>/`，版本取自它的 `run-log.md` 開頭；同名資料夾已存在時加 `-2`、`-3`。
   - 建立 `outputs/run-log.md`，寫入開始時間、參數，以及系統版本（`SYSTEM_CHANGELOG.md` 最後一個版本）。把 `prompts/`、這份 SKILL 與 `style-guide.md` 複製到 `outputs/system/`，讓這次的產出日後可以對照當時的系統重現。

1. **A 微意圖建模**：subagent 執行 `prompts/A.md` → `outputs/A.md`。
   關卡：至少 4 個意圖；每個都有可查證據（網址或證據包代號）；各意圖的「下一步決定」不同；有 SEO 競爭邏輯；沒有捏造的搜尋量或排名。用 WebFetch 抽查 2 條 A 標為「已開啟」的新來源，核對短引；網站擋抓取時換一條。標為已開啟、實際內容卻對不上的，退回。
   同一關鍵字、`evidence-pack.md` 沒有改過時，可以沿用上一次執行的 `A.md` 與 `decision-log.md`：複製過來，在 run-log 註明沿用來源，並在 decision-log 補一句作者經驗的變動是否影響選題。

2. **選題（你負責）**：依四個準則選定一個意圖：證據強度、讀者的決定是否明確、競爭缺口、作者經驗能支撐到什麼程度。YMYL 風險無法控制的意圖直接排除（例如誠實回答會把讀者推向違法選項），難以控制的只當必要段落。寫 `outputs/decision-log.md`：選了誰、為什麼、放棄了誰、給 B 段的範圍與限制。
   選題後即可啟動對照組 1（第 9 步）。

3. **作者經驗**
   - 不足以支撐選定意圖、或 `inputs/experience.md` 不存在：subagent 執行 `prompts/B1.md` → `outputs/B1-questions.md`。
     - 互動執行：把題目一次列給使用者，回答原文附加到 `inputs/experience.md`（標明日期與題目摘要，不改寫）。依回答寫下第一人稱的使用限制，放在該檔的「使用限制」節，標明是整理而非原話。
     - 非互動執行：不等待。在 `decision-log.md` 註明作者經驗的缺口，B 段只用既有經驗與第三方來源。
   - 足夠：在 `decision-log.md` 註明理由，直接進第 4 步。
   作者經驗定案後即可啟動對照組 2（第 9 步）。

4. **B2 寫作**：subagent 執行 `prompts/B2.md` → `outputs/B-draft.md`，新來源摘錄附加到 `outputs/sources-added.md`。
   關卡：
   - `python tools/check_article.py outputs/B-draft.md --quotes evidence-pack.md inputs/experience.md outputs/A.md outputs/sources-added.md` 通過；找不到逐字出處的引文逐條確認。
   - 你讀全文確認：有試玩情境與有標準的客觀評論；有可重算的計算（自己重算）；第一人稱都對得到 `inputs/experience.md` 原文並遵守使用限制；不推薦平台、不保證出金。

5. **C1 三份審核（同時派出）**：三個新 subagent（都沒參與寫作），各自只拿自己 prompt 列出的輸入：
   - `prompts/C1-facts.md` → `outputs/C-audit-facts.md`：事實、計算、法律、讀者安全、缺漏、競爭情報、權威性。核對用的來源摘錄附加到 `outputs/sources-added.md`。
   - `prompts/C1-experience.md` → `outputs/C-audit-experience.md`：第一人稱逐句對作者原文。
   - `prompts/C1-reader.md` → `outputs/C-audit-reader.md`：讀者視角的口吻、結構與易懂。不給它任何來源，它看到的就是讀者看到的。
   分三份是因為三種錯誤需要的資料不同，而且讀者視角的審核者一旦拿到來源，就會用查核者的眼光讀，看不出文章像查核報告。
   關卡：每個問題都有依據與原句；作者經驗審核逐句對照、沒有抽查；讀者視角沒有建議刪掉讀者安全需要的內容。空泛或只挑字詞的退回。

6. **作者確認**：`C-audit-experience.md` 列出需要作者確認的事時，互動執行就把題目一次列給使用者，回答原文附加到 `inputs/experience.md` 的「審核後確認」節；非互動執行不等待，C2 用審核者建議的保守寫法。沒有就跳過。

7. **C2 整合修正**：新 subagent 執行 `prompts/C2.md` → `outputs/C-revised.md`、`outputs/C-changes.md`。
   關卡：
   - 三份審核的每個問題都有處理或不採用的理由；衝突的取捨說得通。
   - 新增來源用 WebFetch 抽查可開。
   - `python tools/check_article.py outputs/C-revised.md --quotes evidence-pack.md inputs/experience.md outputs/A.md outputs/sources-added.md --numbers-from outputs/B-draft.md` 通過；找不到逐字出處的引文逐條確認；`numbers_dropped` 列出的每個數字都要在 C-changes 找得到理由。
   - 正文沒有查證過程與重複的免責句。

8. **C3 全文複審**：新 subagent（沒參與寫作、審核與修正）執行 `prompts/C3.md` → `outputs/C-recheck.md`。C3 只審不改。依結論：
   - **可以定稿**：你確認沒有未解決的嚴重或中級問題、有優化成果的前後對照後，把 `outputs/C-revised.md` 複製成 `outputs/final.md`。
   - **小修**：
     1. 把 `C-revised.md` 備份成 `C-revised-pre-fix.md`。
     2. 新 subagent 執行 `prompts/C2.md`，只改 C-recheck 列出的句子。
     3. 你產生兩份檔的逐字差異，跑同一個 `check_article.py`（`--numbers-from` 指向備份）。
     4. 新 subagent 執行 `prompts/C4.md` → `outputs/C-verify.md`，你提供備份與差異的路徑。
     5. 全部 PASS 就定稿。有 FAIL 時，把 FAIL 的改法交回同一個流程再做一次，仍不過就停下來問使用者。
   - **退回 C2**：先把 `C-recheck.md` 複製成 `C-recheck-1.md` 保留，把要修的問題交回第 7 步（C2 以 `C-revised.md` 為底稿），修完由新的 C3 再審一次。最多退回 1 次；第二次 C3 仍不能定稿就停下來問使用者。
   不論哪條路，最後一步都是檢查（C3 或 C4），不是修改。

9. **公平對照**：不預設提示詞鏈一定比較好。對照組都寫第 2 步選定的同一個意圖（把 prompt 裡的 `{INTENT}` 換成意圖一句話）。
   - 對照組 1（只給題目的單一 prompt）：選題後啟動。subagent 用 `isolated`（`.claude/agents/isolated.md`，不載入 CLAUDE.md），只收 `prompts/baseline.md` → `outputs/baseline.md`。它不讀任何檔，上一次執行同一意圖的結果可以沿用。
   - 對照組 2（同資料單一 prompt）：作者經驗定案後啟動。general-purpose subagent 收 `prompts/baseline-informed.md`，可讀 `evidence-pack.md`、`inputs/experience.md`、`style-guide.md`，可上網 → `outputs/baseline-informed.md`、`outputs/baseline-informed-notes.md`。它和鏈拿到相同的資料與準則，比較的是「分步驟＋關卡」本身；作者經驗或證據包改過就要重跑。
   - 上一版系統的定稿：`outputs-<版本>/` 有同一意圖的 `final.md` 時，一起盲評，比較系統版本。
   - 盲評：`python tools/make_blind.py <要比較的文章> --judges 3` 為三位評審各自洗牌代號，副本在 `outputs/blind/judge-N/`，對應表在 `outputs/blind-mapping.json`。每位評審是新的 `isolated` subagent，只收 `prompts/review-blind.md` 全文、自己的 `outputs/blind/judge-N/`，以及可核對的 `inputs/experience.md`、`evidence-pack.md`、`style-guide.md` → `outputs/review-blind-N.md`。
   - 彙整：`python tools/aggregate_reviews.py outputs/review-blind-1.md outputs/review-blind-2.md outputs/review-blind-3.md` 還原代號、算平均與缺陷數；`python tools/check_article.py <各篇> --compare` 量機械指標；`python tools/cost_report.py outputs/agents.json --transcripts <subagents 目錄> --by-step > outputs/cost.md` 依牌價（含快取）換算成本。subagent 紀錄在 Claude Code 設定目錄的 `projects/<專案>/<工作階段>/subagents/`。
   - 在 `outputs/comparison.md` 寫結論：三位評審的逐項分數、平均與分歧；評審列出的缺陷與盲評後的核對結果；各組的成本與耗時；鏈在哪些面向更好、哪些沒有、可能原因。結果不利於鏈也照實寫。
   - 評審列出的定稿缺陷，你逐條回到來源核對。成立的走第 8 步的小修流程（C2 只改那幾句 → 差異 → C4），不成立的在 comparison 寫明證據。

10. **收尾**：寫 `outputs/run-summary.md`，包含：
    - 每步的嘗試次數、關卡結果、主要修正（表格）
    - 選題理由與作者經驗摘要
    - 最終文章的機械指標與 C3 結論
    - 盲評結果與成本
    - 依 `CLAUDE.md` 品質標準自評：最影響品質的 3 個問題、追到哪個 prompt 或關卡、建議怎麼改

    最後回報使用者：`outputs/final.md` 路徑、三句結論、仍需人判斷的事。

11. **交付成品**（使用者確認品質後）：依 `CLAUDE.md`「交付成品」產出 `deliverable/`。內容逐項取自最新的 `outputs/`、`SYSTEM_CHANGELOG.md` 與各版產出，不憑記憶摘要；依 `style-guide.md`「三、交付文件與簡報」寫。`prompts.md` 用 `python tools/export_prompts.py > deliverable/prompts.md` 產生，不手抄。

## 原則

- 關卡是最低標準。看得出明顯能更好的地方，可以具體要求重做。
- 不放寬關卡讓產出過關，也不替 subagent 改寫。
- 作者的第一手經驗只來自 `inputs/experience.md` 的作者原文；超出的情境必須有真實來源。
