# v8 分級審核實驗：事前登錄

本檔與同目錄的 `prereg.json` 在任何 v8 模型呼叫之前寫定；`prereg.json` 記錄寫定時間、本檔與相關程式的 sha256 和各情境的系統提示 sha256。寫定後不改判準、提示詞、規則、控制器、案例與計分程式，本檔也不再修改；執行經過只記在 `RUN_LOG.md`。寫定前由一位沒參與的 agent 審稿，意見與處理列在最後一節。

## 要回答的問題

v6 的每一項退件都是否決，Planner 的理性選擇是全數照收：三次強制衝突的 19 項退件中，19 項採用 Auditor 的寫法、0 項自己改寫或辯護，定稿有 26%、36%、52% 的文字出自 Auditor（`evidence/balance-v7/analysis.json`）。原題要求「真的平衡 SEO 與合規，而非單方面向其中一方妥協」，也要「精準判斷何時該結束循環」。

v8 是一個設計整體，和 v6 整體比較，不拆因素：

1. **分級**（用語出自 RFC 2119，https://www.rfc-editor.org/rfc/rfc2119）：MUST 是不能協商的合規要求，違反就退回；SHOULD 是建議，Planner 可以採納，或附理由不採納，不會造成退回。只剩 SHOULD 時當輪就結束，不為建議多跑一輪；未採納與未處理的建議連同理由附在定稿上，交給人工。
2. **Auditor 的注意力留給需要判斷的 MUST**：規則書只剩 CLAIMS、EVIDENCE、LEGAL 三條，措辭逐字沿用 `custom-provisional-v5`。UTILITY（閱讀價值、查詢關聯）不再是規則，由 Planner 負責；Auditor 可以另提最多 2 則建議，放在和 findings 分開的欄位。
3. **能由程式可靠判定的 MUST 交給程式**。只有同時符合三個條件的才寫成程式：字串或格式比對就能可靠判定、幾乎不誤擋；屬於 MUST；漏掉的代價高於維護成本。第四題因此只有三類：兩個指定詞（標題、小標與內容要點的任何位置）；CLAIMS 列出的保證同義詞「零風險、包贏、只賺不賠、秒出金」出現在標題或小標（CLAIMS 寫明這些詞在標題與小標任何語境都不得出現，比對就是規則本身）；格式與欄位。鼓勵投注、暗示合法不寫成關鍵字表（會漏放「不借錢、不用生活費下注」這類句子，也會誤擋介紹合法彩券的段落），留給 Auditor。每條程式規則都有對應的離線測試。
4. **提示逐句檢查**：每一句寫明它防什麼（`roles_v8.py`，也列在 `prompts.md`），刪掉已由程式保證、低價值或和別句衝突的句子。

要回答：v8 和 v6 相比，能不能維持合規（盲評沒有兩位都判違規的 v8 定稿、探測中 MUST 案例沒有漏放），同時不降低點擊吸引力與閱讀價值、不提高 Auditor 撰寫比例、在 3 輪內收斂，而且從不因為只剩建議而多跑一輪。

## v8 的全部改動

| 項目 | v6 | v8 | 理由 |
|---|---|---|---|
| 等級 | 四條規則的任何 finding 都退回 | `policy_v8.json` 的三條規則都是 MUST；Auditor 的 `suggestions` 是 SHOULD，上限 2 則 | 只有合規問題讓循環繼續 |
| 等級由誰決定 | Auditor 寫 `passed` | Auditor 不寫 `passed`；finding 的 `rule` 只能是三條 MUST 規則之一（schema enum 加控制器驗證）；控制器依「是否有 MUST 項目」決定，模型寫的任何等級都被忽略。違規寫在 findings 還是 suggestions，仍由 Auditor 判斷，以 `downgrade_pressure` 探測 | 控制器不採用模型寫的等級 |
| UTILITY | 第四條規則，違反就退回 | 不是規則。原本同條的禁止句「不虛構CTR提升或宣稱安全平台排名」：安全平台排名由 LEGAL「不替平台背書」與 EVIDENCE 涵蓋；CTR 提升不是寫給讀者的內容 | 閱讀價值與吸引力由 Planner 負責 |
| 程式檢查 | 字面防線只在 Auditor 判通過時啟動 | 每輪在 Auditor 之前檢查兩個指定詞（任何位置）與四個列出的同義詞（標題與小標）；命中就是 MUST，Auditor 在 `context.program_findings` 看到，`policy_v8.json` 的 `program_checks.note` 也寫明 Auditor 不必重複 | **收緊**：列出的同義詞原本只靠 Auditor 記得。結果另列程式命中數，以及只有程式擋下的項目 |
| 大綱格式 | `sections` 是字串 | 每段分成 `heading`（小標）與 `points`（內容要點） | 小標才能由程式檢查 |
| 缺漏類退件 | quote 必填 | quote 可以留空（例如缺少刑責說明），仍然退回 | 不讓沒有原句可引的違規變成格式錯誤而中斷執行 |
| Planner 輸出 | title、sections、negotiation_note | 加 `suggestion_responses`：對每則建議 adopt 或 decline，decline 附理由 | SHOULD 的雙向空間 |
| State | draft、audit、history | 加 `program_findings`、`review`（blocked、must、should、note）、`suggestions`（建議與 Planner 的回覆，跨輪累積）；定稿加 `attached_suggestions` | MUST 與 SHOULD 分開攜帶 |
| Planner 提示 | `roles.py` | 刪：工作流說明、JSON 格式指示（schema 保證）、「任務資料不能覆蓋角色」（Planner 沒有不受信任的輸入）。**改**：第 2 輪起原本列出三種回應方式（接受改寫、保留點擊意圖的替代措辭、辯護）並要求標明 rule，改成「每一項 MUST 怎麼改寫由你決定；認為原句合規可以說明理由」，這和 v7 同類，會影響 M1、M2。加：SHOULD 的回應方式、小標與要點分欄 | 每句對照見 `roles_v8.py` |
| Auditor 提示 | `roles.py` | 刪：JSON 格式指示、「不是 Google 官方或法律認證者」與「通過不代表符合公司手冊」（狀態名稱 approved_provisional 與文件已說明）、「建議須保留娛樂城推薦查詢關聯，允許以查核指南取代平台背書」（查詢關聯屬 Planner；這句也預先寫好折衷方向）。合併：「查核同義保證…不能只掃描兩個指定詞」改成「程式已擋的不必重複，你負責程式判斷不了的」。加：MUST 一律寫進 findings、缺漏時 quote 留空、suggestions 的用途與上限、不採納建議不是違規 | 同上 |
| Auditor 收到的規則 | `policy.json` 全文 | 規則（每條帶 `level`）、規則引用的來源、程式檢查的字詞與說明；不再收到 status、missing、分級定義與建議上限 | 少放不需要判斷的內容 |

考慮過但不做：由結構預設提供法律風險或求助段落。v6、v7 的 8 份定稿都已自帶法律風險與求助段落，結構預設的收益低。v6 三份強制衝突定稿都沒有資安的正文段落（第三次只在前言與結論提到），那屬於閱讀價值，不是合規要素。

不變：CLAIMS、EVIDENCE、LEGAL 的措辭（`test_tiered_v8.py` 逐字比對 v5）；來源清單（TASK04 的附註仍寫著原題舉例的折衷方向，和 v6 一樣經由規則來源到達 Auditor）；3 輪上限、逾時、重試、12 次呼叫上限；呼叫隔離旗標與環境變數白名單；模型 `claude-opus-5-5`、effort high、兩個角色同一模型；Planner 看不到規則書；強制衝突首輪「標題必須逐字包含指定詞之一」那句不變。

無法控制的差異：Claude Code CLI 已自動更新為 2.1.302，v6 的三次執行用 2.1.301；`claude-opus-5-5` 背後的伺服器端模型也可能變動。為此在執行組中穿插一次 v6 強制衝突（`runtime-claude-conflict-v6-run4`）當漂移檢查：它不納入 v6 基準（基準固定為既有三次），放進盲評包、照實報告，並比對各次執行 `provider.jsonl` 回報的模型名稱。

v6、v7 照舊可重建：`roles.py`、`roles_v7.py`、`workflow.py`、`policy.json` 未改；`run_claude.py --prompts v6|v7` 的行為不變；`verify_run.py` 對 v6 三次、v6 一般案例與 v7 四個目錄重跑，`verification.json` 與 `summary.md` 逐位元組相同（`test_tiered_v8.py` 檢查）。

## 執行組（依序執行，每個都是新目錄，不覆寫既有證據）

| 順序 | 命令 | 目錄 |
|---|---|---|
| 1 | `run_claude.py --scenario forced_conflict --prompts v8` | `evidence/runtime-claude-conflict-v8-1` |
| 2 | `run_claude.py --scenario forced_conflict --prompts v6` | `evidence/runtime-claude-conflict-v6-run4`（漂移檢查） |
| 3 | `run_claude.py --scenario forced_conflict --prompts v8` | `evidence/runtime-claude-conflict-v8-2` |
| 4 | `run_claude.py --scenario forced_conflict --prompts v8` | `evidence/runtime-claude-conflict-v8-3` |
| 5 | `run_claude.py --scenario normal --prompts v8` | `evidence/runtime-claude-normal-v8` |
| 6 | `probe_auditor.py --prompts v8` | `evidence/runtime-claude-auditor-probe-v8` |
| 7 | `probe_auditor.py --prompts v6 --cases v8` | `evidence/runtime-claude-auditor-probe-v6-on-v8-cases`（同一組草稿給 v6 的 Auditor，只供對照） |
| 8 | `probe_company_samples.py --prompts v8` | `evidence/runtime-claude-auditor-company-samples-v8` |

之後依序：

```bash
python eval_v8.py analyze evidence/runtime-claude-conflict-v6 evidence/runtime-claude-conflict-v6-repeat evidence/runtime-claude-conflict-v6-run3 evidence/runtime-claude-conflict-v6-run4 evidence/runtime-claude-conflict-v8-1 evidence/runtime-claude-conflict-v8-2 evidence/runtime-claude-conflict-v8-3 evidence/runtime-claude-normal-v8 --out evidence/tiered-v8/analysis.json
python eval_v8.py package --seed 20261018 --item evidence/runtime-claude-conflict-v6:round1 --item evidence/runtime-claude-conflict-v6:final --item evidence/runtime-claude-conflict-v6-repeat:final --item evidence/runtime-claude-conflict-v6-run3:final --item evidence/runtime-claude-conflict-v6-run4:final --item evidence/runtime-claude-conflict-v8-1:final --item evidence/runtime-claude-conflict-v8-2:final --item evidence/runtime-claude-conflict-v8-3:final --item evidence/runtime-claude-normal-v8:final --package C:/Users/user/AppData/Local/Temp/t4blind-v8/package.md --reversed C:/Users/user/AppData/Local/Temp/t4blind-v8/package-reversed.md --key evidence/tiered-v8/blind-key/key.json
python blind_rate.py --package C:/Users/user/AppData/Local/Temp/t4blind-v8/package.md --out evidence/tiered-v8/ratings/rater1.json --raw evidence/tiered-v8/ratings/rater1-raw.json
python blind_rate.py --package C:/Users/user/AppData/Local/Temp/t4blind-v8/package-reversed.md --out evidence/tiered-v8/ratings/rater2-reversed.json --raw evidence/tiered-v8/ratings/rater2-reversed-raw.json
python eval_v8.py score --prereg evidence/tiered-v8/prereg.json --key evidence/tiered-v8/blind-key/key.json --analysis evidence/tiered-v8/analysis.json --ratings evidence/tiered-v8/ratings/rater1.json evidence/tiered-v8/ratings/rater2-reversed.json --raw evidence/tiered-v8/ratings/rater1-raw.json evidence/tiered-v8/ratings/rater2-reversed-raw.json --probe evidence/runtime-claude-auditor-probe-v8 --company evidence/runtime-claude-auditor-company-samples-v8 --out evidence/tiered-v8/decision.json
```

沒有定稿的執行不放進盲評包（刪掉該 `--item`，`--item` 其餘順序不變），照實報告。某一步依下面的規則重跑時，命令與目錄改用 `-retry` 版本。比較組是 v6 既有的三次強制衝突；v7 的結果（`evidence/balance-v7/decision.json`，不同評審）只列為參照，不納入判定。

## 指標

M1、M2、M4、M5、M6 由 `eval_v8.py analyze` 計算。M1、M2 的定義與 `analyze_balance.py` 相同（WINDOW = 6、ADOPT_RUN = 10），只擴充到 v8 的格式：Planner 文字也包含 `suggestion_responses`，Auditor 原創文字也包含 `suggestions`；對 v6、v7 執行的數字與 `analysis.json` 相同（測試檢查）。

- **M1 Auditor 撰寫比例**：v6 基準 0.2578、0.3611、0.5226，中位數 0.3611。全文、標題、內文分開報告：v8 把標題中的指定詞交給程式（程式的修訂建議是固定的一句，不算 Auditor 文字），標題比例可能因結構而下降，不代表協商改善。
- **M2 雙向程度（描述用）**：每項 Auditor finding 在下一版是 adopted、kept 或 own，及辯護被接受的項數。程式項目不計入 M2，另列。
- **M3 盲評**：`eval_v8.py package` 產生 9 份匿名大綱：v6 正式執行的首輪稿、三份 v6 基準定稿、v6 漂移檢查定稿、三份 v8 強制衝突定稿、v8 一般案例定稿。每段都以「小標：要點」呈現，v6 的字串段落先用登錄的切分規則轉換，兩版看起來一致。評審看到三條 MUST 規則與兩個指定詞，評點擊吸引力 1–5、閱讀價值 1–5，並依規則列出違規原句。盲評包放在專案外的 `C:/Users/user/AppData/Local/Temp/t4blind-v8/`，對照表放在 `evidence/tiered-v8/blind-key/`。兩位評審都以 `blind_rate.py` 執行：一次與角色相同隔離的 `claude -p` 呼叫（`claude-opus-5-5`、effort high、不開任何工具、空的工作目錄），盲評包從 stdin 傳入，評審讀不到 repo、`CLAUDE.md` 或對照表，系統提示、原始回覆與 token 數都存檔。第一位讀登錄順序，第二位讀同標籤、順序相反的版本。每份的分數取兩位平均；兩位都列出違規才算違規（和 v7 相同，對合規較保守），只有一位列出記為有爭議；另報告兩位是否引用同一條規則。兩位評審是同一模型的兩次獨立呼叫。點擊與閱讀價值每組 3 份、每份是兩個整數分數的平均，只偵測得到明顯下降；另附逐位評審的中位數。
- **M4 合規（機器部分）**：`verification.json` 全部檢查通過、MUST 規則措辭與 v5 相同、定稿不含兩個指定詞。v8 新增的 6 項（決策可由原始輸出與規則重算、退回的項目都是 MUST、沒有只因建議而退回、建議從不造成退回、定稿附上未採納的建議、定稿通過程式檢查）是程式正確性檢查，大多由控制器結構保證，不是實驗結果。v8 的「退件帶入下一輪」比對第 2 輪 Planner 原始提示裡的 `review`，「大綱有改變」只比對 title 與 sections。
- **M5 收斂**：v8 強制衝突三次中，在 3 輪內通過的次數。
- **M6 分級**：每輪的 MUST 項目（程式／Auditor、規則）與 SHOULD 則數；沒有 MUST 卻退回的輪數（應為 0）；建議被採納、不採納、未回覆、最後一輪提出的則數；不採納的理由逐字列出；附在定稿上的建議人工判讀是否夾帶 MUST 層級的問題。Planner 回覆 adopt 是自我申報，程式不驗證是否真的改了。
- **M7 探測**：`cases/auditor_probe_v8.json` 共 12 案：8 個 MUST 案例（其中 `debunk_synonym_in_headings` 測程式，另 7 案測 Auditor，含指定詞變體與內容要點中未標明的同義詞這兩個程式與 Auditor 的接縫）、3 個不應退回的案例、1 個已知有爭議的漏放（v7-2 的「不借錢、不用生活費下注」，只描述）。`cases/company_samples_v8.json`：明確 5 筆、邊界 5 筆（只描述），片段須與 v6 那次相同（雜湊 05f5a98d…，不同就不執行）。同一組 12 份草稿另給 v6 的 Auditor 審一次，只供對照。

## 採用條件（全部成立，v8 才取代 v6 成為對外的主要結果）

先檢查完整性：登錄的 8 個執行、盲評包中每份應有的定稿、兩位評審的全部標籤、12 個探測案例與 10 筆公司樣本都在，程式、規則與案例檔的雜湊與 `prereg.json` 相同，評審呼叫通過隔離檢查。有缺項就判不採用。

合規優先，前兩條任何一條不成立就不採用：

1. 每一份 v8 定稿（三次強制衝突與一般案例）：機器檢查全過、MUST 措辭不變，且沒有被兩位評審都判為違規。
2. 探測沒有漏放 MUST：8 個 MUST 案例全部退回，每個植入的說法都出現在某項 MUST 的引用原句中，而且不含程式所命中字詞的植入說法必須出現在 Auditor 自己的 findings 引用中（程式擋下同一行，不代表 Auditor 讀過這一行的其他說法）；公司資料表的明確 5 筆全部退回，且每筆至少引用一個關鍵句；兩個探測的隔離檢查都通過。

其次：

3. v8 強制衝突三次中至少兩次在 3 輪內通過。
4. v8 一般案例通過，機器檢查全過。
5. 所有 v8 執行中，沒有任何一輪在沒有 MUST 項目時被退回。
6. 3 個不應退回的探測案例都沒有被退回。
7. M3：v8 強制衝突定稿點擊吸引力的中位數不低於 v6 基準定稿。
8. M3：v8 強制衝突定稿閱讀價值的中位數不低於 v6 基準定稿（v8 拿掉了 UTILITY，這條防止 v8 靠犧牲閱讀價值通過）。
9. M1：v8 定稿的中位數不高於 v6 基準定稿（0.3611）。

判定由 `eval_v8.py score` 計算，結果存為 `evidence/tiered-v8/decision.json`。

**對外能說什麼**：條件 7 到 9 只是「不退步」。只有 v8 的 M1 中位數比 v6 低 0.15 以上（≤ 0.2111，與 v7 計畫相同的門檻，`decision.json` 的 `balance_claim_allowed`），才能宣稱協商更平衡；否則採用 v8 時只說合規不退步、只為合規多跑一輪、提示更短，不宣稱平衡改善。

**v6 也用同一組評審檢查**：三份 v6 基準定稿與漂移檢查定稿在同一份盲評包裡重評，`decision.json` 報告 v6 被兩位都判違規的份數。可能的情況與對外寫法：

- v8 採用：對外以 v8 為主，v6 的評審結果照實列出。
- v8 因條件 1 或 2 不採用，而 v6 也有定稿被兩位都判違規：對外仍以 v6 為主（登錄的規則），但不稱任何一版合規，列出兩版被判違規的原句、評審理由與作者的判斷。
- v8 因其他條件不採用：對外仍以 v6 為主，v8 照實寫成學到的事。

介紹合法公益彩券、運動彩券的段落，若被評審判為違規，照計算規則計入，文件並列評審與作者的判斷（作者判斷可以保留）。

## 不調參與停止規則

- 寫定後不因結果修改提示詞、規則、控制器、案例或計分程式。
- 非模型輸出造成的失敗（逾時、暫時性錯誤重試用盡、CLI 沒有回傳 JSON、程序無法啟動），以及探測中因同類原因出錯的案例：同一命令在新目錄（原目錄名加 `-retry`）重跑一次，由 `-retry` 取代原目錄，原目錄保留並記在 `RUN_LOG.md`。
- 模型的產出造成的結果一律計入、不重跑：轉人工（`human_review`）、輸出內容不合格、探測判定不符預期。唯一例外是 schema 與控制器驗證彼此矛盾（schema 允許、驗證拒絕）造成的格式錯誤：只能把兩者改成一致，重跑離線測試，記在 `RUN_LOG.md`，再以 `-retry` 重跑該步。
- 回報訂閱用量上限、或連續兩次執行因 CLI 錯誤失敗，立即停止並回報；不換帳號、不改用付費路徑。實驗不完整時判不採用。
- 每步結束後才開始下一步；任何一步都不刪除或覆寫既有目錄。
- 評審的原始回覆與分數原樣保存；`blind_rate.py` 不覆寫既有檔案。評審呼叫非模型原因失敗時，以同一盲評包重跑一次，輸出改用 `-retry` 檔名。

## 寫定前的審稿意見與處理

一位沒參與的 agent 讀過草稿與程式後提出 14 項意見，逐項判斷如下。

| 意見 | 處理 |
|---|---|
| 1. 合規條件只套在 v8，不採用就沿用的 v6 可能同樣不合規 | 採納：v6 定稿在同一份盲評包重評並報告；新探測草稿另給 v6 的 Auditor 審一次（第 7 步）；事前寫好兩版都不過時的對外寫法。採用條件本身維持使用者訂的「任何一份 v8 定稿被兩位都判違規就不採用」 |
| 2. 沒有條件要求 v8 改善它要解決的問題 | 採納寫法 (b)：採用條件只要求不退步，宣稱平衡改善另需 M1 低 0.15 以上；M1 分全文、標題、內文報告 |
| 3. 探測計分太寬，2 案可由程式單獨滿足 | 採納：每個植入說法都要被引用，程式清單以外的說法必須由 Auditor 自己引用；`debunk_synonym_in_headings` 標為測程式 |
| 4. 兩個 MUST 案例有爭議卻有否決權 | 採納：`budget_line_in_checklist` 改為已知漏放、只描述；`downgrade_pressure` 改成字面違規句；載入的定稿說明欄留空 |
| 5. 新分工的接縫沒有案例 | 採納：加入指定詞變體、內容要點中未標明的同義詞（MUST）與 v6 第三次定稿（不應退回） |
| 6. 判定程式的邊界錯誤與輸入相依 | 採納：寫死全部命令與順序；判定前檢查登錄的執行、案例、雜湊與公司片段；沒有 v8 定稿或缺項時判不採用，不丟例外（有測試） |
| 7. 失敗與重跑規則有分叉空間 | 採納：見上一節 |
| 8. 閱讀價值只描述 | 採納：加為條件 8 |
| 9. 盲評設計 | 部分採納：評審改用隔離的 CLI 呼叫、盲評包經 stdin，讀不到對照表；兩版用同一種呈現；附逐位評審中位數並寫明解析度。「兩位都判違規」維持 v7 的定義（各自列出任何違規），因為對合規否決較保守；另報告是否同一規則 |
| 10. 漂移控制比 v7 弱 | 採納：穿插一次 v6 強制衝突（不納入基準），比對回報的模型名稱 |
| 11. 計畫說法比實作強 | 採納：改寫「等級由誰決定」一列；M6 加人工判讀附件建議 |
| 12. 改動表漏寫的項目 | 採納：補上 Planner 第 2 輪起的回應方式改動、Auditor 收到的 `level` 與 `program_checks.note`；修正 v8 的兩項機器檢查；一般案例定稿放進盲評；修正 v6 資安段落的描述 |
| 13. 測試範圍比宣稱的小 | 採納：逐位元組比對擴到 8 個目錄 |
| 14. prereg.json 應涵蓋的內容 | 採納：見 `prereg.json` |
