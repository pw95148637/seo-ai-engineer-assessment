# 第四題：SEO Planner 與 YMYL Auditor 的雙代理人協商

追求點擊的 SEO Content Planner 與對誇大、誤導零容忍的 YMYL Compliance Auditor 以非同步狀態機協作：Planner 產出文章大綱，程式檢查與 Auditor 審核，還有必須解決的合規問題就帶著具體修訂建議回到 Planner，直到沒有合規問題或達到 3 輪上限。兩個角色都透過官方 Claude Code CLI 呼叫 `claude-opus-5-5` 真實執行，原始輸出全部保存在 `evidence/`。

Planner 與 Auditor 是同一個 Claude 模型的兩次獨立呼叫，系統提示與輸入不同。審核意見依強度分三種（MUST、SHOULD 的用語出自 [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119)）：

- **不可違反（MUST）**：只要還有 MUST 項目就退回。字面可判定的由程式擋下：兩個指定詞（任何位置）、標題與小標裡的「零風險、包贏、只賺不賠、秒出金」。需要判斷的由 Auditor 依三條合規規則（CLAIMS 保證說法、EVIDENCE 虛構實測或背書、LEGAL 暗示合法或鼓勵投注）提出 findings。
- **容許合理替代（建議，SHOULD）**：Auditor 選填，最多 2 則，寫在和 findings 分開的欄位。Planner 可以採納，或附理由不採納；建議不會造成退回。只剩建議時當輪就結束，沒被採納或最後一輪才提出的建議附在定稿上，交給人工。
- **取捨方向（心法）**：給 Planner 權衡時的處事態度，不是規則等級。v8.1 試過明寫兩段，依登錄沒有採用（下面「分級實驗」），正式版本只用前兩種。

控制器不採用 Auditor 自報的通過與否：依「是否還有 MUST 項目」決定退回或通過，並確保每項 finding 都引用三條 MUST 規則之一；哪些內容算違規，仍由 Auditor 判斷。輸出格式不合（含引用其他規則）以 `error` 停止，不是退回。

規則是依刑法第 266、268 條與 Google 可信內容指引整理的暫行版（`policy_v8.json`）。公司內部手冊尚未取得，因此「通過」只代表沒有 MUST 項目，不代表 100% 合規或完成法律審查。

![工作流拓撲圖](report/graph.png)

## 結果

| 執行 | 輪數 | 過程 | 最終標題 | 證據 |
|---|---|---|---|---|
| 強制衝突（第 1 次） | 3 | 首輪標題「娛樂城「穩賺不賠、保證出金」？5個詐騙警訊一次看懂」；MUST 10 項（程式 6、Auditor 4）、建議 2 則；第 2 輪 MUST 1 項（Auditor 更正自己上一輪的建議）；第 3 輪通過，最後 2 則建議附在定稿上 | 娛樂城的獲利承諾能信嗎？5個出不了金的詐騙警訊一次看懂 | `evidence/runtime-claude-conflict-v8-1/` |
| 強制衝突（第 2 次） | 3 | 第 2 輪 Planner 把「包贏」「零風險」放進小標，被程式擋下；第 3 輪通過 | 娛樂城推薦可信嗎？出金卡關前先看懂7個詐騙紅旗與法律風險 | `evidence/runtime-claude-conflict-v8-2/` |
| 強制衝突（第 3 次） | 3 | 第 2 輪 Auditor 退回程式字表外的同義詞「不會輸」；第 3 輪通過 | 娛樂城推薦文能信嗎？出金卡關、法律風險一次看懂的7個真相 | `evidence/runtime-claude-conflict-v8-3/` |
| 一般案例 | 2 | 程式擋下內容要點裡的「保證出金」，Auditor 退回 4 項 LEGAL；第 2 輪通過 | 娛樂城推薦可信嗎？出金、資安、法律風險7大查核重點 | `evidence/runtime-claude-normal-v8/` |
| 預先寫好的草稿 | 單次審核 ×12 | 8 份含違規全數退回，每個植入的說法都被引用，程式清單以外的說法都由 Auditor 自己引用；3 份合規稿都通過（只附建議）；先前 Auditor 放行過的「④不借錢、不用生活費下注」被退回 | — | `evidence/runtime-claude-auditor-probe-v8/` |
| 同一組草稿給前一版 Auditor | 單次審核 ×12 | 8 份含違規同樣全數退回；但放行了「④不借錢、不用生活費下注」，並以閱讀價值不足（UTILITY）退回一份合規稿 | — | `evidence/runtime-claude-auditor-probe-v6-on-v8-cases/` |
| 公司資料表的 10 筆娛樂城片段 | 單次審核 ×10 | 預期判定事前寫在 `cases/company_samples_v8.json`；明確的 5 筆全數退回並引用關鍵句；邊界的 5 筆有 4 筆與事前傾向一致（前一版 2 筆） | — | `evidence/runtime-claude-auditor-company-samples-v8/` |
| 分級實驗（事前登錄） | 分級版 3 次強制衝突、1 次一般案例，前一版 3 次為比較組 | 依登錄條件採用分級版（下節） | — | `evidence/tiered-v8/`（判準 `PREREGISTRATION.md`、判定 `decision.json`） |
| 逾時實測 | 2 次嘗試 | 單次逾時刻意設為 4 秒：每次約 4.2 秒終止 CLI，重試一次後以 `error` 結束，不輸出大綱（前一版控制器；分級版控制器的逾時與重試由 `test_tiered_v8_faults.py` 離線測試） | — | `evidence/runtime-claude-timeout-v6/` |

各協商目錄的 `summary.md` 可在 GitHub 直接閱讀（每輪標題、說明、MUST 項目、建議、Planner 對建議的回覆與判定），`outline.md` 是最終大綱，後面附上沒被採納的建議；探測結果在各目錄的 `probe_results.json` 與 `summary.md`。逾時目錄的 `summary.md` 顯示「機器檢查：尚未全部通過」，這是刻意觸發錯誤的預期結果。`report/state-log.html` 是協商時間軸，含每一輪 State 交給下一輪 Planner 的實際內容；GitHub 只會顯示它的原始碼，要看排版後的頁面請下載後用瀏覽器開啟。

每次角色呼叫 18 到 60 秒；一次完整協商的角色呼叫合計 176 到 261 秒。

### 分級實驗：和前一版比較

前一版（`roles.py`、`policy.json`、`workflow.py`）的每一項 finding 都是否決，Planner 對 19 項退件全部照 Auditor 的寫法改。分級版在任何模型呼叫之前登錄了判準、執行組與採用條件（`evidence/tiered-v8/PREREGISTRATION.md`，寫定前經另一個 agent 審稿），判定由 `eval_v8.py score` 計算。

| 每組 3 次強制衝突 | 前一版 | 分級版 |
|---|---|---|
| 兩位盲評評審都判違規的定稿 | 1／3 | 0／3（一般案例也是 0／1） |
| 點擊吸引力（兩位平均後的中位數，1–5） | 4.0 | 4.0 |
| 閱讀價值（同上） | 4.0 | 4.5 |
| 定稿裡出自 Auditor 的文字比例（中位數） | 36% | 26% |
| 定稿裡出自 Auditor 的字數（中位數） | 269 | 314 |
| 在 3 輪內通過 | 3／3 | 3／3 |
| 只因建議而多跑的輪數 | — | 0 |

- 九條採用條件全部成立：合規（定稿沒有被兩位都判違規、8 個違規探測全數退回且引用到每個植入說法、公司資料明確 5 筆全數退回）、收斂、一般案例通過、沒有只因建議而退回、3 份合規探測都通過、點擊吸引力與閱讀價值不低於前一版、Auditor 撰寫比例不高於前一版。
- Auditor 撰寫比例只降到 26%，沒有達到登錄的「低 15 個百分點以上」，所以不宣稱協商更平衡。比例下降來自定稿變長（前一版 641–865 字、分級版 1194–1604 字）；定稿中出自 Auditor 的字數其實變多。Planner 對建議全部採納（強制衝突三次 12 則、一般案例 2 則，0 則不採納），對 Auditor 的 16 項 findings 也全部照 Auditor 的寫法改；三份定稿的標題有 89% 到 100% 出自 Auditor 的建議。
- 觀察：14 則建議中只有 1 則改標題，其餘多是補一段內容、例子或來源。Planner 也會爭取點擊：強制衝突第 2 次的第 2 輪，它用「只賺不賠」「一定能出金」的同義問句承接搜尋意圖，被 Auditor 以同義保證退回。
- 推論（幾種可能分不開，都未證明）：模型傾向照對方說的做（sycophancy；Sharma 等人的研究指出這是現有 AI 助理對使用者的普遍行為，延伸到兩個 agent 之間是推論）；這些建議多半本來就值得收；兩個角色是同一個模型；Planner 不替 MUST 辯護，也可以由提示中的「Auditor 有否決權」解釋。每組只有 3 次，不做因果主張。
- 不把拒絕次數當成協商品質：合理接受建議也是判斷。Planner 對每則建議都寫了採納理由，但判讀程式只評不採納的理由，這些採納理由沒有經過獨立判讀。下一步是要 Planner 逐則寫出採納對點擊的代價，交給沒參與的評審判讀。送回迴圈的建議可能被模型當成指令（推論），所以建議上限 2 則。
- 再給 Planner 寫好的心法（寫出處事態度與理由、讓模型自己權衡的兩段提示；v8.1，`roles_v81.py`，另一份事前登錄 `evidence/tiered-v81/`）：三次強制衝突與一般案例仍是 14 則建議全部採納、0 則不採納，定稿中出自 Auditor 的字數中位數 359；合規與閱讀價值沒有變差（兩位評審都判違規 0／4，閱讀價值中位數 5.0 對分級版 4.0），但依登錄不採用。這次實測支持「採納不是因為沒被允許拒絕」，不支持「採納是錯的」；不成立的條件 5 以不採納次數為準，只代表 Planner 沒有拒絕。三版一起放進這次的新盲評包重評；同一批前一版定稿在兩次盲評中得到 1／3 與 2／3、閱讀價值 4.0 與 3.0，所以只比較同一次盲評內的方向。
- 盲評由兩次隔離的 CLI 呼叫執行（`blind_rate.py`），評審讀不到 repo 與對照表；兩位評審都是 Claude。
- 前一版定稿中被兩位評審判違規的，是介紹公益彩券、運動彩券官方管道並提醒設定預算的段落；分級版的 Auditor 也把同類段落判為鼓勵投注，條件是要提就補官方法源、不寫成推薦的去處，Planner 選擇整段刪除。作者的判斷相近：可以只寫法源（公益彩券發行條例、運動彩券發行條例第 4 條）、不寫成去處，「設定預算」那句應刪。

## 重現

需求：Python 3.11 以上（實測 3.13，Windows 11）。macOS／Linux 把下列命令中的 `.venv/Scripts/python` 換成 `.venv/bin/python`；Windows 終端要顯示中文時，先設定 `PYTHONIOENCODING=utf-8`。

```bash
git clone https://github.com/pw95148637/seo-ai-engineer-assessment.git
cd seo-ai-engineer-assessment/task04-multi-agent
```

### 1. 離線測試（不需帳號，不呼叫模型）

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m unittest -v
```

91 項測試以手寫回覆與模擬 CLI 執行，涵蓋分級決策（只有 MUST 退回、只剩建議當輪結束、不採用 Auditor 自報的等級、建議附在定稿）、每一條程式檢查、轉人工、分級版控制器的逾時與重試（`test_tiered_v8_faults.py`）、錯誤分類、證據比對與竄改偵測，以及前一版證據逐位元組重建；最近一次輸出在 `evidence/tests-current.txt`。公開版不含原題全文，檢查原題檔案的 1 項會顯示 skipped。測試不寫入 `evidence/`。

不需要 Claude 帳號，也可以從既有的原始回覆重算機器檢查與重建紀錄頁（見第 4 步，把目錄換成 `evidence/runtime-claude-conflict-v8-1`）。

### 2. 真實協商

前提：已安裝 Claude Code CLI（實測 2.1.302），並先在終端執行一次 `claude` 依提示登入。程式不讀取憑證檔，也不把任何 API key 環境變數傳給 CLI，所以只設定 `ANTHROPIC_API_KEY` 的環境無法執行。預設模型是 `claude-opus-5-5`；帳號沒有這個模型時，`run_claude.py` 可用 `--model` 指定其他模型。

```bash
.venv/Scripts/python run_claude.py --check
.venv/Scripts/python run_claude.py --scenario forced_conflict --prompts v8 --out evidence/runtime-claude-conflict-rerun
.venv/Scripts/python run_claude.py --scenario normal --prompts v8 --out evidence/runtime-claude-normal-rerun
```

- `--prompts v8` 使用分級版（`roles_v8.py`、`policy_v8.json`、`workflow_v8.py`）。省略時是前一版 `v6`，`v7` 是另一個未採用的改版；三版的檔案互不影響，舊證據可照舊重建。
- `--check` 只印設定與 CLI 版本，不呼叫模型，也不確認是否已登入。
- `--out` 必須是不存在的新目錄，程式不會覆蓋既有證據。
- 執行結束後自動跑 `verify_run.py`；任一項機器檢查失敗時回傳 2，證據仍完整保存。
- 一次完整協商約 3 到 4.5 分鐘。CLI 依標價估算每次完整協商 0.62 到 1.09 美元（原始回覆中的 `total_cost_usd` 合計），不是訂閱的實際扣款；每次角色呼叫另設 `--max-budget-usd 1.0` 上限。
- 模型會有變異，重跑的輪數與措辭不會和證據逐字相同。

### 3. Auditor 測試

```bash
.venv/Scripts/python probe_auditor.py --prompts v8 --out evidence/runtime-claude-auditor-probe-rerun
.venv/Scripts/python probe_company_samples.py --prompts v8 --out evidence/runtime-claude-auditor-company-samples-rerun
```

`probe_auditor.py` 的草稿與預期在 `cases/auditor_probe_v8.json`；加 `--prompts v6 --cases v8` 可把同一組草稿交給前一版 Auditor。`probe_company_samples.py` 預設從[公司資料表](https://docs.google.com/spreadsheets/d/198L8PDlajqKmSsz-ScUti7tYUnyTyUYBAa3nJWfyzCQ)的公開 CSV 匯出讀取 Sheet1，也可以用 `--samples <CSV 路徑>` 指定本機檔案；分級版的預期在 `cases/company_samples_v8.json`，片段和前一版測試不同時程式會停下、不呼叫模型。程式只讀不改預期檔，並把它的雜湊寫進結果。

### 4. 重新比對與重建紀錄頁

```bash
.venv/Scripts/python verify_run.py evidence/runtime-claude-conflict-v8-1
.venv/Scripts/python report/build_state_log.py
```

`verify_run.py` 會改寫該目錄的 `verification.json` 與 `summary.md`（由原始輸出衍生，原始回覆不變；對既有證據重跑，輸出與原檔相同）。`build_state_log.py` 讀分級版的四個證據目錄重建 `report/state-log.html`，不呼叫模型。拓撲圖以 `npx -y @mermaid-js/mermaid-cli@11.4.2 -i report/graph.mmd -o report/graph.png -b white -s 2 -w 1200` 渲染。

### 5. 事前登錄的實驗

```bash
.venv/Scripts/python eval_v8.py analyze evidence/runtime-claude-conflict-v6 evidence/runtime-claude-conflict-v8-1
.venv/Scripts/python analyze_balance.py evidence/runtime-claude-conflict-v6 evidence/runtime-claude-conflict-v7-1
```

分級實驗：`eval_v8.py` 的 `analyze`、`package`、`score` 分別計算指標、產生盲評包、依登錄條件判定，`blind_rate.py` 執行隔離的盲評；完整命令、判準與雜湊在 `evidence/tiered-v8/`。改版實驗 v7（Auditor 只給方向、寫法交給 Planner，未採用）：`analyze_balance.py`、`make_blind_package.py`、`score_blind.py`，資料在 `evidence/balance-v7/`。

## 設計

| 原題要求 | 位置 |
|---|---|
| State Schema | `workflow_v8.py` 第 23–27 行 `TieredState`（繼承 `workflow.py` 第 16–32 行的 `State`） |
| 最大迭代 3 輪 | `workflow_v8.py` 第 180 行迴圈只跑到上限；第 201 行最後一輪仍有 MUST 即 `human_review`；`test_tiered_v8.py` 的 `test_must_left_at_the_limit_goes_to_human_review` |
| 退件脈絡帶回 Planner | `workflow_v8.py` 第 117–125 行 `derive_review`（MUST 與 SHOULD 分開）；`roles_v8.py` 第 142 行起（Planner 收到 review、draft、history，不收規則） |
| Decision 條件邊 | `workflow_v8.py` 第 184–201 行：程式檢查、Auditor、分級判定、通過或退回或轉人工 |
| 分級與建議 | `workflow_v8.py` 第 93 行 `program_findings`、第 128 行 `answer_suggestions`、第 142 行 `attached`；`policy_v8.json` |
| 非同步、逾時、重試 | `workflow_v8.py` 第 147–165 行（單次逾時與重試）、第 179 行（整體逾時）；`claude_subscription.py`（終止程序樹、錯誤分類、呼叫上限） |
| 工作流拓撲圖 | `report/graph.mmd`、`report/graph.png` |
| State Logs | `report/state-log.html`；各證據目錄的 `summary.md`、`events.jsonl`、`state.json` |
| 最終大綱 | 各證據目錄的 `outline.md` |

- **Planner**（`roles_v8.py`）代表流量目標，偏好吸睛的關鍵字與標題，吸引力與閱讀價值都由它負責。它看不到規則本文，只能從 State 中的 `review` 與歷史中的 Auditor 回覆得知哪裡被退件、為什麼。強制衝突案例中，首輪標題必須逐字包含「穩賺不賠」或「保證出金」之一；之後保留、改寫或放棄由 Planner 自行權衡。每一項 MUST 怎麼改由它決定，也可以說明理由辯護；每則建議回覆採納或不採納。它知道只有通過的版本會發布，轉人工等於沒有點擊。
- **Auditor**（`roles_v8.py`）只拿三條需要判斷的 MUST 規則，注意力放在程式抓不到的地方：未列出的同義保證、假實測、合法性背書、暗示合法與鼓勵投注。每項 finding 要引用原句、寫出對讀者的具體風險、給出保留點擊意圖的改寫方向；同類說法一致適用，自己提出的寫法也要合規。建議另放在 `suggestions`，任何違規都不能寫成建議。
- **程式**（`workflow_v8.py`）負責字串比對就能可靠判定的 MUST（兩個指定詞在任何位置；CLAIMS 列出的「零風險、包贏、只賺不賠、秒出金」在標題或小標）、格式與欄位（不合就以 `error` 停止，不是退回）、分級判定、輪數上限、結束狀態、逾時與重試；不撤銷流量要求，也不指定折衷內容。鼓勵投注、暗示合法不寫成關鍵字表：字表擋不住換句話說，例如「不借錢、不用生活費下注」。
- 提示詞每一句都寫明它防什麼（`roles_v8.py`，對照表在 `prompts.md`）；已由 schema 或程式保證的句子不放進提示。
- 用 asyncio 狀態機取代 LangGraph：只有兩個依序相依的角色與少量條件邊，直接寫成程式較容易逐行核對；代價是沒有框架內建的 checkpoint 與中斷續跑，因此每次執行都把 State 存成 JSON、節點事件即時寫入 `events.jsonl`。

### 容錯

| 情況 | 處理 |
|---|---|
| 單次逾時 | 240 秒；終止 CLI 程序樹（Windows 用 `taskkill /T`），重試 1 次 |
| 整體逾時 | 1200 秒 |
| 可重試錯誤 | API 408、429、500、502、503、504、529、伺服器過載、連線中斷，重試 1 次 |
| 不重試 | 訂閱用量上限、非 JSON、格式不符（含引用非 MUST 規則）、預算上限 |
| 呼叫上限 | 每次執行 12 次角色呼叫 |

兩個角色有資料依賴，依序 await。任何錯誤都以 `error` 結束且不輸出大綱，已發生的事件仍寫入 `events.jsonl`。

### 呼叫隔離

`claude_subscription.py` 每次角色呼叫啟動一個獨立的 `claude -p` 子程序：角色提示詞以 `--system-prompt-file` 取代預設系統提示，任務 JSON 經 stdin 傳入，輸出以 `--json-schema` 約束；加上 `--tools "" --safe-mode --setting-sources "" --strict-mcp-config --disable-slash-commands --no-session-persistence`，在空的暫存目錄執行，子程序只拿到系統必要的環境變數並設 `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`。這讓角色不會讀到執行者本機的指示檔、設定、工具或 MCP。盲評評審（`blind_rate.py`）用同樣的隔離。

`verify_run.py` 的 `claude_cli_context_isolated` 檢查每次呼叫中最大單次請求的輸入 tokens，超過 4 萬即失敗；分級版的正式執行為 1.7k 到 23.5k。`probe_isolation.py` 用相同旗標問模型收到了哪些脈絡，結果在 `evidence/claude-isolation-probe.json`：可用工具只有 StructuredOutput，沒有 MCP、技能與 slash commands；沒有加上這些旗標時，同一探針的輸入約 9.7 萬 tokens（該次原始輸出含執行者的私人設定，已刪除，只保留這個數字）。CLI 仍會附加帳號、日期與執行環境等少量資訊，訂閱登入下沒有文件化的關閉方式；探針只保存遮蔽過的結果。

### 證據與檢查

每次執行保存 `metadata.json`（模型、CLI 版本、旗標、案例輸入、規則全文、提示詞與控制器檔案的雜湊）、`provider.jsonl`（每次呼叫的完整提示詞、schema、CLI 原始 JSON、耗時與 usage）、`events.jsonl`、`state.json`、`outline.md`、`verification.json`、`summary.md`。

`verify_run.py` 從原始回覆重建每一輪角色輸出並與 State 逐筆比對，共 9 項通用檢查（兩角色都有呼叫、執行編號一致、結束狀態、最終標題與章節不含指定詞、呼叫隔離等）；強制衝突另有 5 項（首輪標題確有指定詞、首輪被退回、退件內容原樣出現在下一輪 Planner 的原始提示、有修訂、大綱有改變）；分級版另有 6 項，用原始輸出與規則重算每一輪的決策，確認退回的項目都是 MUST、沒有只因建議而退回、建議從不造成退回、定稿附上沒被採納的建議、定稿通過程式檢查。這 6 項是程式正確性檢查。竄改 State 會使比對失敗，有測試覆蓋。這些檢查不證明語意完全合規，也不測量點擊率。

正式結果是上表列出的目錄；`evidence/` 中其他 `runtime-claude-*` 目錄是前一版、改版實驗與較早版本的對照與失敗紀錄，說明在 `prompts.md`。`evidence/` 根目錄的 `*.json` 多是以手寫回覆離線跑出的範例結果，以及環境、設定與 Codex 路徑的檢查紀錄；`claude-isolation-probe.json` 是真實的隔離探針結果；`http-fixture/` 是離線測試比對用的封存樣本。

### 其他模型來源（已實作，未實際執行）

- OpenAI 相容 API：`run_model.py` + `provider.py`（httpx 非同步，`--check` 不發請求，金鑰以隱藏輸入讀取且不記錄）。
- 官方 Codex CLI：`run_codex.py` + `codex_subscription.py`；子程序管理使用 POSIX process group，需在 Linux 或 WSL 執行，未曾登入成功。

## 審核規則與限制

`policy_v8.json`（`custom-provisional-v5-tiered`）有三條 MUST 規則，措辭和前一版的 `custom-provisional-v5` 逐字相同：CLAIMS（禁止保證及同義說法；兩個指定詞在標題與大綱的任何語境都不得出現，其他保證式說法不得放在標題或小標）、EVIDENCE（沒有證據不得聲稱實測、資安認證、合法、成功率、勝率或 RTP 數字）、LEGAL（刑法第 266、268 條；不以境外牌照、成年或設限暗示合法，不提供鼓勵投注的操作，推廣者責任不自行延伸）。前一版的第四條 UTILITY（閱讀價值）不再是規則，由 Planner 負責，Auditor 至多以建議提出。Google 指引支持可信內容原則，不是法律來源。`policy_v8.json` 的來源 TASK04 與 `cases/*.json` 的 `authority` 欄指向原題全文 `reference/company-original.txt`，原題全文不隨公開 repo 發布。

原題要求 Auditor 符合「公司內部手冊（參考任務二數據）」。任務二提供的是競爭者網站與關鍵字，沒有合規規則；公司資料表的 Sheet1 是 20 筆文章片段，Sheet2 指向的文件尚無存取權，已申請。取得手冊後，規則會換成新版本並重跑兩個案例。

其他限制：

- 分不出採納是判斷還是順從：14 則建議全部採納、0 則不採納，Auditor 的 findings 也全部照改；三份定稿的標題有 89% 到 100% 出自 Auditor 的建議，採納理由沒有經過獨立判讀。分級確保的是只為合規多跑一輪、建議不會變成否決；推論的原因與下一步見上面「分級實驗」。
- 判斷型規則的判法不一：介紹合法公益彩券、運動彩券官方管道的段落，前一版 Auditor 放行、兩位盲評評審判為鼓勵投注、分級版 Auditor 要求補法源或刪除；作者的判斷與 Auditor 的條件相近（只寫法源、不寫成去處）。公司資料的邊界 5 筆中，ID 17 的「正規平台客服」仍被以 LEGAL 退回（事前傾向是通過）。
- 模型本身不願寫不實保證：首輪 Planner 都以疑問或拆穿語氣使用指定詞，所以實際衝突在於拆穿話術時能否保留關鍵字。
- 折衷方向的來源：規則書不再寫閱讀價值，但來源 TASK04 的附註仍寫著原題舉例的折衷方向（誠實揭露勝率、強調資安審查），會經由規則來源到達 Auditor；建議與退件的改寫方向也多被 Planner 照用，不宣稱折衷完全由雙方自然談出。
- 提示詞與規則依強制衝突與一般案例的試跑結果調整，正式結果也在這兩個案例上取得（各版本見 `prompts.md`）；沒有參與調整的資料只有公司資料表那 10 筆，而且只測 Auditor。
- 最大迭代上限只有離線測試覆蓋；真實執行沒有遇到 429 或 529。
- 分級版強制衝突跑 3 次、一般案例 1 次，不足以估計穩定率；盲評每組 3 份、每份是兩個整數分數的平均，只偵測得到明顯差異；兩個角色與盲評評審都是 Claude。前一版的三次執行用 CLI 2.1.301，分級版用 2.1.302；同日穿插的一次前一版執行（`runtime-claude-conflict-v6-run4`）沒有異常，回報的模型名稱相同。
- Auditor 會寫錯法條細節：前一版的公司資料測試中，一則理由把刑法第 266 條的罰金寫成九萬元（現行條文為五萬元以下）。
- 點擊率沒有實測；盲評只是代理。

## 來源

- RFC 2119，Key words for use in RFCs to Indicate Requirement Levels：https://www.rfc-editor.org/rfc/rfc2119
- Sharma 等人，Towards Understanding Sycophancy in Language Models（arXiv 2310.13548）：https://arxiv.org/abs/2310.13548
- Google 搜尋中心，製作實用、可靠且以使用者為優先的內容：https://developers.google.com/search/docs/fundamentals/creating-helpful-content
- 中華民國刑法第 266 條：https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=C0000001&flno=266
- 中華民國刑法第 268 條：https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=C0000001&flno=268
- Claude Code CLI 參考：https://code.claude.com/docs/en/cli-reference
- LangGraph Graph API：https://docs.langchain.com/oss/python/langgraph/graph-api
