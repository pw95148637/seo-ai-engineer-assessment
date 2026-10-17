# 設計細節

架構圖與總覽在 [README](../README.md)。本文件寫研究策略、控制規則、lessons 帳本的資料結構與狀態機，以及評估設計。

## 研究策略

模型收到網站與關鍵字後，先讀 `research_status`（預算與適用的 lessons），自行提出值得查證的假設，再選工具。優先查「能改變競爭行動、不確定、又能低成本查證」的資訊：首頁與目錄結構、目標詞頁的 title/H1/內容/內鏈/canonical、轉介目的地、公開索引摘要。不全站抓取；兩步沒有新證據或預算到限就收斂。

off-page 分三種來源，證據強度由弱到強：目標頁的出站連結（`outbound_hosts`，只說明它連去哪裡）、公開索引列出的站外頁（搜尋摘要）、實際讀到的站外頁（`research_offpage`，確認是否連到或提及目標站並記下錨文字與上下文）。模型用網域或品牌名搜尋站外提及，再挑少量結果讀取。公開索引看不到完整 backlinks，報告不宣稱完整。

報告每項主張標 kind（observation＝已知、inference＝推論、unknown＝未知）與 section（on_page、off_page、other）；on_page 與 off_page 各至少一項，`<run>-report.md` 把兩段各自分成已知、推論、未知三欄。搜尋摘要不等於原頁，出站連結不等於 backlinks，沒有 Search Console 或流量資料就不推測成效。

## 控制規則（由程式直接阻擋）

- `research_fetch` 只讀 HTTPS、操作者允許的網域；私人 IP、localhost 與未允許網域拒絕；每次轉址重新檢查網域與 robots。
- `research_offpage` 只讀本 run 搜尋結果列出的站外網址（host 須與列出的完全相同），目標站本身拒絕（改用 `research_fetch`）；每 run 最多 4 頁，與直接 HTTP 共用 30 次預算；轉址只能留在同一 host 或其 www. 對應；每個站外 origin 先讀 robots.txt；DNS 必須在本機解析成公開 IP，不用代理端解析；只回傳連到目標站的連結（網址、錨文字、rel）與至多 3 段提及上下文，不回傳頁面全文，全文存進證據庫，`research_evidence` 讀站外快照時必須帶關鍵字、只回傳片段。站外頁轉址到其他網站時以 `offpage_redirect_off_host` 停止，這是第三方網站的行為，不學成 lesson。
- 伺服器即使在要求 `Accept-Encoding: identity` 後仍回傳 gzip/deflate，控制器在大小上限內解壓後存快照，證據 meta 記錄 `decoded_from`；壓縮內容本身超過上限或串流不完整時拒收，不存被截短的頁面。
- 所有 HTTPS 連線在連上後再檢查一次對方位址是否為公開 IP（經設定的代理時對方是代理本身，不檢查）。
- robots.txt 不是 200/404/410 時停止；禁止的路徑不抓；403/429 保存並回傳 Retry-After，不自動重試。
- 直接 HTTP 30 次（含 robots 與轉址）、工具 40 次、900 秒、單回應 2MB、同站間隔 2 秒；搜尋 5 次，每次官方 DDGS worker 30 秒上限。
- XML 含 DOCTYPE/ENTITY 拒絕解析；回應過大拒收。
- finish：observation/inference 必須引用本輪、雜湊相符的證據；非 200 證據只能用在 `topic=access`；section 只能是 on_page、off_page、other，plugin 執行時要求 on_page 與 off_page 各至少一項。檢查只保證來源存在與完整，不保證語意支持。
- 事件表記錄每次請求的發起者（model 或 controller）與通道（direct 或 offpage），計分時只把模型自己的讀取算作命中，並用通道稽核站外請求是否都來自先前的搜尋結果、是否先讀過允許它的 robots.txt。

## lessons 帳本

存在每個 run root 的 `research.sqlite`，程式在 `src/lessons.py`。

| 表 | 內容 |
|---|---|
| `lessons` | id、kind（failure_pattern／discovery_path／human_feedback）、key、host、scope（host／general）、status、statement（由程式模板產生，供人工檢視）、data（JSON）、expires |
| `lesson_support` | 每個 run 對某 lesson 的支持（+1）或反例（−1）、證據 id、epoch |
| `lesson_history` | 每次狀態變更：舊狀態、新狀態、actor（controller 或 human:名字）、run、原因 |
| `feedback` | 人工標註：run、項目（claim:N／action:N／run）、標籤、理由、範圍、審查者、產生的 lesson |

狀態機：

```text
failure_pattern:  candidate --(第 2 個 run 重現)--> active --(同類成功)--> revoked
                  active --(7 天無新支持)--> expired ; revoked/expired --(之後再 2 個 run 重現)--> active
discovery_path:   (讀到目標詞頁) --> active --(重抓 404/410/不符/robots 禁止)--> revoked ; 7 天到期
human_feedback:   (人工標註) --> active
任何狀態 --(人工 veto)--> vetoed（終止，之後只累積證據不改狀態）
```

`epoch` 在每次撤銷或到期時加一，只有之後收集的支持能讓 lesson 恢復，避免舊證據把撤銷的 lesson 拉回來。

學習由 runner 在判定 run 為 research_complete 之後呼叫 `learn_run`，每個 run 最多一次，只對以 memory 模式且未凍結啟動的 run 生效，讀取的是該 run 的事件與證據：

- 失敗：搜尋依快照分為有結果、無結果（含只回空白佔位結果）、錯誤（逾時、限流）；無結果依查詢是否含 `site:` 分類，錯誤不學。`tool_error` 只接受固定清單內的控制器拒絕碼（例如 `error_is_not_page_content`、`host_not_allowed`）；傳輸錯誤、DNS、robots 未知與預算用盡不學。lesson 的 key 只來自這兩份固定清單，頁面或模型文字無法命名 lesson。
- 發現路徑：只看模型自己抓的頁面（控制器重驗抓的不算），取第一個符合目標詞頁規則的 HTML；來源是更早讀過、含此網址連結的頁面（記錄錨文字），並記錄讀過幾份 sitemap、幾份列出此頁。
- 目標詞頁規則：網址最後一段或 title/H1 以空白、`｜`、`-`、`:` 切開後的某一段等於關鍵字；網址查詢參數含關鍵字的頁面、`/search/`、`/tag/` 下的頁面不算；分類頁仍算，因為常是網站自行設計的關鍵字入口。以空白切分時，「富遊 娛樂城」這類標題仍會命中，兩組計分同樣受影響。
- candidate 與 active 都有 7 天效期；過期後再收到支持時先記為 expired，再從新的 epoch 重新計數。
- 一次學習在單一資料庫交易內完成；任何一步出錯就整批回滾，runner 回報 `learning_failed`，評估腳本拒絕重試並要求修程式後重新登錄計畫。

提供時（`research_status` 第一次呼叫）：過期者不提供；發現路徑只給同網站，且先由控制器重抓（最多 4 條），結果與證據 id 一起提供；失敗模式在只觀察過其他網站時標為 `transfer_hint`；人工回饋依 scope。凍結的 run 只過濾、不寫入任何狀態變更。

提供給模型的 statement 在提供當下由 `data` 與本 run 的重抓結果產生，寫成下一步該做什麼，不寫過去的發現：

- 發現路徑重抓成功：「目標頁 X 已由控制器在本輪開始時重抓，HTTP 200 且 title/H1 符合（evidence_id E），直接用 research_evidence 讀取與引用」。重抓不確定時改請模型自行讀取。
- 失敗模式：「research_search 不要用 site:，改用不含 site: 的查詢」並附次數；控制器拒絕類寫成「避免：規則」。
- 人工回饋：前綴「審查標準（寫本輪主張時套用；原句是過去被標註的例子，不需重查）」。

原因：報告只能引用本 run 的證據，lesson 裡的過去發現（例如「讀了 4 份 sitemap，0 份列出此頁」）模型必須重查才能引用。v0.6 的 R2、R3 因此各讀 sitemap 6 次並重抓已確認的兩個目標頁，抵銷了省下的呼叫。過去的發現仍留在 `data`（`sitemaps_checked`、`anchor` 等）供稽核；舊版本存下的 statement 不會再提供給模型。

## 評估設計

- **v0.5（封存負結果）**：`evidence/live-agent-evaluation/`，三組各一次，記憶組成本較高且沒讀到目標詞頁。`evaluation/v05-rescore.json` 以 v0.6 計分重算，僅作說明，不作 v0.6 比較基準。
- **v0.6（已完成，not_proven）**：`evaluation/plan-v06.json` 寫明步驟順序、每步模式與是否學習、保留站規則與結果、計分欄位、改善與失敗標準、盲評格式、重試規則與程式指紋。`scripts/evaluate_v06.py` 依序執行並拒絕：計畫或程式被改、跳步、重跑已完成的步驟、超過一次重試。該計畫鎖定 v0.6 程式，在目前程式上 `--verify` 會回報程式已變更；要重驗 v0.6 須取出 v0.6 的 commit。
- **v0.7（已完成，learning not_proven、offpage not_achieved）**：`evaluation/plan-v07.json` 與 `scripts/evaluate_v07.py`。兩組都跑 v0.7 程式並凍結：記憶組（`R4`）從 v0.6 累積帳本的複本開始（計畫記錄其 SHA-256，複製前核對），對照組（`B2`）從空帳本開始；保留站 casinobase.tw 也跑了兩組（`HB2` 空帳本、`HM2` 帳本複本）。標準分三類：off-page 能力（C1–C4）、學習（L1–L5）、失敗（F1–F4），另有保留站 H1–H2。結果：記憶組第 2 次工具呼叫就讀到目標頁（對照組第 9 次），不重抓已確認頁、不讀 sitemap，但 tokens 多 15.9%（L4 不成立），保留站覆蓋分數較低（H1 不成立）；每組只有 1 項附證據的站外已知（C1、C2 不成立）；失敗標準都不成立。判定與依據見 `evaluation/v07/VERDICT.md`。
- **v0.8（正式結果）**：`evaluation/plan-v08.json` 與 `scripts/evaluate_v08.py`，設計在 `evaluation/plan-v08-design.md`。三組（對照、lessons 帳本、Hermes 原生記憶與 skill）從空白狀態在 2030.tw 各跑 5 次、逐輪交錯，第 5 次比自己的第 1 次與對照組（對照組 5 次的範圍當雜訊），凍結後到保留站檢查傷害；學到的內容另交盲評分類。成本主指標改為未命中快取的輸入＋輸出。結果：帳本 improved、原生 regression、原生對帳本 ledger_better，依據見 `evaluation/v08/VERDICT.md`。
- **計分**（`src/scoring.py`）：目標詞頁是否由模型讀到、首次讀到前的工具呼叫數、失敗搜尋、第一次 finish 是否被退、非 200 引用、HTTP 次數（分模型與控制器）、tokens、已失效 lesson 是否被提供（以 `lesson_history` 獨立核對）；v0.7 加上 sitemap 讀取次數、重抓控制器已確認頁的次數、各 section 主張數、off-page 已知數（分全部、引用站外證據、引用確認連到目標站的站外頁）、站外請求稽核。語意支持另匯出盲評包，移除組別標記並附快照；盲評除 unsupported、scope_error 外，另依附在包內的評分表給 on-page、off-page、行動可執行性、已知／推論／未知區分各 0–2 分，並數出有快照支持的 off-page 已知項。
- **合成元件檢查**（`scripts/evaluate_memory.py`）：假網站與固定腳本策略，只驗證帳本機制。

## 已知限制

- 模型避開某個失敗做法後就不再產生反例，該 lesson 只能靠到期或人工否決重新開放。
- 控制器重驗會消耗直接請求預算（每條發現路徑約 1 次）。
- off-page 覆蓋取決於免金鑰搜尋索引列出哪些頁；網域字串本身常撞到同名的股票代號或年份，品牌名查詢較有效。
- 經設定的 HTTPS 代理連線時，對外位址由代理解析，控制器只能檢查代理本身；這不是完整的網路沙箱。
- 每組一次、live 來源會漂移；評估結果只能說明這次觀察，不能推論因果。
- DNS 由執行環境解析；這不是完整的網路出口沙箱。
