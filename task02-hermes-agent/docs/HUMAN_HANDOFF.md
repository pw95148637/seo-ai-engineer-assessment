# 交還人類的時機

原題 C 問哪些事一定要人核准。答案分兩層：登入與額度、付費、對外發布或修改網站、否決經驗，以及研究對象與預算，永遠由人決定，由「只給唯讀工具」與控制器規則實現，不靠模型自律；其餘的決定在每次研究後由 `scripts/handoff_queue.py` 從執行紀錄列成清單，寫明要人決定什麼、為什麼、證據在哪、可以怎麼處理。

## 每次研究後的清單

```bash
python scripts/handoff_queue.py <研究目錄>                                # 最新一次執行，Markdown 印到畫面
python scripts/handoff_queue.py <研究目錄> --run 2f7174e7 --out <資料夾>   # 寫出 <run>-handoff.md 與 <run>-handoff.json
```

`<研究目錄>` 是開跑時 `run_research.sh --root` 指定的目錄。程式以唯讀方式讀其中的 `research.sqlite` 與 runner 留下的 `<run>-outcome.json`、`-preflight.json`、`-hermes.json`、`-review.json`，不改帳本；開跑前就停止、控制器沒有紀錄的執行也會列出。每一項寫要決定什麼、為什麼交給人、依據（事件、lesson、evidence 編號）、不處理時會怎樣，以及處理方式與指令。經驗被否決、行動建議被標註、整份報告標為已審查之後重新產出，對應項目會移到「已處理」。

清單是事後審查。經驗變動在列出時已經生效，人能做的是否決；行動建議、預算、允許網域與資料授權則要人決定後才會發生。

| 類別 | 需要決定 | 視需要處理 | 紀錄 |
|---|---|---|---|
| 開跑前檢查 | 未登入、限流、工具清單不符、操作者暫停 | 研究沒有正常完成、沒有學習紀錄 | 只做了開跑前檢查 |
| 經驗變動 | 新啟用的 lesson、Hermes 原生學習寫入 skill 或 memory | 候選 lesson、曾啟用後被撤銷、研究記憶新增的發現、研究記憶重驗時撤銷了發現 | 其他撤銷、到期、續期，研究記憶的重驗結果 |
| 這次使用的經驗 | | 有發現路徑重抓沒有確認 | 其餘 |
| 研究受限之處 | 私人位址或非 HTTPS 請求、證據雜湊不符、被網站拒絕後又請求同一頁 | 預算用完、越界、robots、內容格式、網站拒絕存取、搜尋有一半以上沒有結果 | 其餘工具錯誤 |
| 報告被退回 | 退回原因含證據雜湊不符 | 其餘 | |
| 未知項 | | 全部，依需要的資料分類 | |
| 行動建議 | P0 | 涉及法規或合規的建議（標為需要法務或決策者）、其餘 | |

## 五個時機

### 開跑前

- **誰觸發**：操作者執行 `scripts/run_research.sh`。
- **程式在哪裡擋**：`scripts/run_research.py` 用 `src/runner_support.py` 的 `readiness` 檢查登入、限流與工具清單，未就緒就以 exit 2 停止、不呼叫模型；`.runtime/pause-model-runs` 存在時也不開跑。操作者指定研究的網站、關鍵字與 `research_fetch` 的允許網域（`--target`、`--keyword`、`--allow-host`）；預算寫在 `src/research_core.py` 的 `Limits`，搜尋 5 次的上限寫在 `Research.search`。評估時 `scripts/evaluate_v09.py` 在每次執行前後讀 ChatGPT 用量，Session 或 Weekly 到 90% 就不開跑，等額度重置；不使用備用額度或付費。
- **真實紀錄**：`evidence/auth-preflight/` 是未登入時的檢查，`blocker` 為 `oauth_required`，沒有呼叫模型，清單範例列為需要決定；`evidence/pause-gate-check/` 是操作者暫停的紀錄。v0.9 評估途中 Session 用量到 92%，程式停在最後兩次研究之前，額度重置後才接著跑（`evaluation/v09/usage-log.jsonl`）。
- **人怎麼處理**：完成裝置登入（`scripts/login_hermes.sh`）、等額度重置、決定研究對象與預算。

### 研究中

- **誰觸發**：Agent 的每一次工具呼叫。研究中不等人：越界的請求由控制器直接拒絕，Agent 改走其他做法，人在研究後從清單看到被拒的內容。
- **程式在哪裡擋**：`src/research_core.py`。`Research.url` 檢查 HTTPS、允許網域與私人位址；`research_offpage` 不受允許網域限制，但只能讀這次搜尋結果列出的網址，每次最多 4 頁，轉址只限同一網站；`fetch` 檢查 robots.txt；`raw`、`call`、`search` 檢查請求、工具呼叫、時間與搜尋次數；控制器自己重抓經驗與研究記憶的頁面另有 10 次額度，不占模型的 30 次。`research_fetch` 遇到 403、429 保存回應並回傳 Retry-After，控制器不自動重試；模型不再重試靠研究 prompt 要求，清單會標出重試。
- **真實紀錄**：v0.8 帳本組 5 次研究都用滿 5 次搜尋，第 1 次的 5 次搜尋有 4 次沒有結果，其中 3 次是 DDGS 回報 `No results found`。第 2 次 `research_offpage` 想讀兩份 PDF，被 `unsupported_content_type` 拒絕（event 91、97）。允許網域的邊界：v0.5 還沒有站外工具時，Agent 用 `research_fetch` 讀 `https://3aaa.com.tw/` 被 `host_not_allowed` 拒絕（`evidence/autonomous-research/research.sqlite` event 43）；v0.8 第 3 次研究經 `research_offpage` 讀了同一網站，因為它出現在這次的搜尋結果裡（ledger-series event 160–166）。
- **人怎麼處理**：決定是否放寬預算、加入允許網域、授權付費資料源，或接受限制。

### 報告提交時

- **誰觸發**：Agent 呼叫 `research_finish`。
- **程式在哪裡擋**：`Research.finish` 檢查格式、observation 與 inference 必須引用本輪且雜湊相符的證據、非 200 的證據只能用在 `topic=access` 的主張、on_page 與 off_page 各至少一項。不通過就退回，Agent 修正後重交，退回紀錄留在 events 表。
- **真實紀錄**：v0.5 無記憶組（run `d19217ae`）第一次提交引用了失敗來源，被 `error_is_not_page_content` 退回（event 305），修正後接受（event 307），見範例清單的 H3。v0.8 的 18 份報告都在第一次提交就被接受。
- **人怎麼處理**：控制器不檢查語意，所以人看最後接受的版本是否只是為了通過檢查而改寫；有問題用 `feedback.py label` 標註主張，沒問題用 `feedback.py ok` 記錄。

### 經驗寫入後

- **誰觸發**：runner 判定 research_complete 後呼叫 `learn_run`；開啟 Hermes 原生學習時，還有 Hermes 研究結束後的背景回顧。
- **程式在哪裡擋**：`src/lessons.py`。lesson 只由控制器量測與人工審查產生，模型沒有寫入路徑。發現路徑讀到目標頁就啟用，失敗模式要 2 個研究重現才啟用，兩者都不等人核准，保護靠使用前重抓、反例撤銷與 7 天到期；否決用 `feedback.py veto`，否決後不再自動恢復。Hermes 原生學習寫的是 Hermes 自己的 skill 與 memory，不經這些檢查；runner 在回顧前把儲存複製到 `<run>-pre-review/`，清單附上撤回的指令。
- **研究記憶**（`--research-memory`，`src/research_memory.py`）：報告被接受後，引用的全是雜湊有效站內頁的已知與推論存成發現（候選），取代上一份報告的發現；下一次研究開始時控制器重抓這些頁面，頁面沒變才交給模型並轉為使用中，頁面變了改列待重讀，404、410 或 robots 禁止就撤銷。清單把「研究記憶新增 N 條發現」列為視需要處理，逐條列出發現與編號，附否決指令；「研究記憶的重驗」列出這次重抓幾頁、幾條仍成立、幾條撤銷，有撤銷時升為視需要處理。發現是模型自己的主張，控制器只確認頁面沒變，所以要人抽查。
- **真實紀錄**：v0.8 帳本組第 1 次研究後，控制器啟用兩條發現路徑（lesson `dfb379fdb342`、`98d867029fed`），第 2 次起 Agent 第 2 個工具呼叫就讀到目標頁；清單把這兩條列為需要決定。第 5 次研究後，不含 `site:` 的搜尋失敗經驗（`dc86bf8b9498`）回到候選，再重現一次就自動啟用。控制器把 DDGS 回報的 `No results found` 算成研究方法失敗（逾時與限流不算），第 5 次那唯一一次失敗正是這個回報，是查詢不好還是索引沒回應要人判斷，所以清單列為視需要處理。清單列出查詢原文，也看得出控制器把排除用的 `-site:` 算成 `site:` 查詢（`search_feature`），「不要用 site:」這條經驗因此每次都被 `-site:` 查詢的成功撤銷；v0.9 已修正這個分類。v0.9 帶經驗的組第 10 次研究後，清單列出研究記憶新增的 9 條發現，以及開始時重抓 8 頁（控制器請求 9 次）、9 條發現仍成立、沒有撤銷。原生學習組第 2 次研究後，Hermes 的回顧修改了 `public-evidence-seo-research` skill，清單列為需要決定（`evaluation/v08/runs/N2/a1`）。
- **人怎麼處理**：確認或否決新啟用的經驗；判斷候選經驗是否先否決；抽查研究記憶新增的發現，不實或說太滿的用 `feedback.py veto` 停用；確認或撤回 Hermes 寫入的 skill；用 `feedback.py label` 把報告裡的問題寫成之後研究套用的審查標準。

### 行動建議之後

- **誰觸發**：報告被接受。
- **程式在哪裡擋**：Agent 沒有修改網站、發布內容或對外聯絡的工具，行動建議只存在報告裡。清單把 P0 列為需要決定；P0 與涉及法規、合規的建議都標為需要法務或決策者，並列出觸發的詞。
- **真實紀錄**：v0.8 帳本組第 5 次的 P0 建議是先確認營運與內容適用的法域、年齡限制、個資與責任博彩要求，清單列為需要決定的第一項。
- **人怎麼處理**：決定是否採納、由誰執行；不採納的用 `feedback.py label --target action:N` 寫成之後研究的審查標準。

## 範例

範例都從封存的執行紀錄唯讀產生，放在 `evaluation/handoff-examples/`。處理方式裡的指令指向複本，不要對正式紀錄執行；要試指令先複製：v0.9 的 `cp -r evaluation/v09/runs/ledger-series runs/v09-ledger-copy`，v0.8 的 `cp -r evaluation/v08/runs/ledger-series runs/v08-ledger-copy`，v0.5 的 `cp -r evidence/live-agent-evaluation/baseline runs/v05-baseline-copy`。

| 檔案 | 執行 | 需要決定／視需要處理／紀錄 | 最值得先看 |
|---|---|---|---|
| `2f7174e7c3f04f35bd74b4c1d2c29af4-handoff.md` | v0.9 帶經驗的組第 10 次 | 1／7／4 | H2：研究記憶新增的 9 條發現；H10：開始時的重驗 |
| `4eab193d244d46e7ad35dc4e17a52689-handoff.md` | v0.8 帳本組第 1 次 | 3／7／1 | H1、H2：從空白帳本第一次啟用的兩條發現路徑 |
| `d8594fca7f904132a15b9f868b38353a-handoff.md` | v0.8 帳本組第 5 次 | 1／5／3 | H1：P0 法域建議；H2：再重現一次就啟用的搜尋失敗候選 |
| `d19217ae0c174d1a8dee6b423a6986da-handoff.md` | v0.5 無記憶組 | 1／6／2 | H3：被退回一次的報告 |
| `3871420e91cc4bbfbcc509f8f780b272-handoff.md` | 未登入時的開跑前檢查 | 1／0／0 | H1：沒有呼叫模型 |

清單反映產出當下的帳本。回頭產出較早的研究時，每條 lesson 會另列之後的狀態變化，例如第 1 次清單裡的搜尋失敗候選，寫出它在第 2 次被撤銷、第 5 次又回到候選。

## 限制

- **人工審查由 Claude 在使用者授權下代審**。v0.8 與 v0.9 唯一一條人工審查經驗是 v0.6 人工標註的原文，由評估程式原樣複製進帳本（不經 `feedback.py`），帳本的審查者欄位照實記錄；目前沒有真人逐項處理清單的紀錄。
- **經驗啟用不等人核准**。清單讓啟用被看見，但下一次研究在人看過之前就會使用新經驗；研究記憶的發現也一樣，下一次開始時只要頁面沒變就交給模型。改成核准後才生效要改 `src/lessons.py` 與 `src/research_memory.py`，它們在 v0.9 計畫的程式指紋內，要先登錄新計畫。
- **清單要手動產出**。`scripts/run_research.py` 同樣在指紋內，研究結束時還不會自動呼叫清單。
- **分類用關鍵詞判斷**。未知項的資料分類與行動建議的法規標記會誤判，例如「合規轉換」也會被標為需要法務；清單同時列出觸發的詞與原文供人核對。
- **沒有「確認經驗」與「恢復經驗」的指令**。接受就是不操作；被撤銷的經驗只能等量測重新累積。
- **放寬預算要改程式**。`Limits` 沒有命令列參數，搜尋上限寫死在 `Research.search`。
