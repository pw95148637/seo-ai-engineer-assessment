# v8.1 Planner 工作原則實驗：事前登錄

本檔與同目錄的 `prereg.json` 在任何 v8.1 模型呼叫之前寫定；`prereg.json` 記錄寫定時間、相關檔案與各情境系統提示的 sha256。寫定後不改判準、提示詞與計分程式，本檔也不再修改；執行經過只記在 `RUN_LOG.md`。寫定前由一位沒參與的 agent 審稿，意見與處理列在最後一節。

## 要回答的問題

v8 讓建議（SHOULD）不能擋下稿子，Planner 仍採納全部 14 則、0 則不採納，Auditor 的 16 項 findings 也全部照 Auditor 的寫法改（`evidence/tiered-v8/analysis.json`）。推論是一面倒主要來自模型傾向照對方說的做，不只是流程結構。另一個要先寫明的事實：v8 的 Auditor 文字比例（M1）比 v6 低，是因為定稿變長（v6 641–865 字、v8 1194–1604 字）；定稿中出自 Auditor 的字數其實變多（中位數 v6 269 字、v8 314 字）。

v8.1 檢驗：在 v8 的分級之上，給 Planner 寫好的工作原則，能否讓 Planner 有依據地不採納部分建議、讓定稿中出自 Auditor 的字數變少，同時不漏放違規、不明顯降低點擊吸引力與閱讀價值。分級是這件事的前提：MUST 仍由程式與 Auditor 擋，Planner 對建議堅持己見不會讓違規過關。

## 唯一的提示改動

`roles_v81.py`：Planner 從第 2 輪起多兩段工作原則。寫法是心法而不是照做的規則：寫出要的處事態度與為什麼，雙向的判準寫在同一段，讓模型思考後自行權衡；不寫 if-then 清單、做法或折衷答案。措辭由使用者定稿，逐字使用：

1. 「讀者最終看到的是定稿，點擊與閱讀價值由你代表；你放棄的部分，流程中沒有其他角色會替讀者爭取。因此，Auditor 的意見，尤其是建議，是供你依自身判斷權衡的參考，而非必須執行的指令：有依據時，說明理由並維持原寫法；對方的意見正確時，就予以採納。為了讓對方滿意而讓步，或為了表現主見而反對，都不是在替讀者做判斷。」
2. 「合規問題應確實修正，但修正的對象是被指出的問題本身。讓讀者願意點擊、讀得下去的其餘部分仍由你負責，不必因為一處被退回就把整份大綱改得保守，也不應只替換幾個字敷衍。」

位置：第 2 輪起，接在 v8 既有的「negotiation_note 逐項回應 review.must…」之後、流量要求提醒之前。第 1 輪還沒有任何意見，與 v8 逐字相同，兩版的起點一致。

不變：Planner 第 1 輪的提示、Auditor 的提示、`policy_v8.json`、`workflow_v8.py`（程式檢查、分級判定、3 輪上限、逾時與重試）、輸出格式、呼叫隔離、模型 `claude-opus-5-5`、effort high、CLI 2.1.302。`test_tiered_v81.py` 檢查：拿掉兩段原則後 Planner 的提示與 v8 逐字相同、原則的位置、第 1 輪與 Auditor 的系統提示和兩個角色收到的 State 內容與 v8 相同、輸出 schema 相同、提示中沒有「資安」「勝率」這類原題舉例的答案。

程式的其他改動：`run_claude.py` 加 `--prompts v81` 選項（v6、v7、v8 的行為不變）；新增 `eval_v81.py`（判定）、`judge_declines.py`（判讀不採納的理由）、`test_tiered_v81.py`。沿用 `eval_v8.py`、`blind_rate.py`、`verify_run.py`、`claude_subscription.py`、`analyze_balance.py`，雜湊都記在 `prereg.json`。

Auditor 探測與公司資料樣本不重跑：它們只把固定草稿交給 Auditor，而 Auditor 的提示、規則與程式檢查都和 v8 相同（`prereg.json` 記錄兩者的 Auditor 系統提示雜湊相同），重跑只會量到抽樣雜訊。v8.1 新增的風險在 Auditor 收到的輸入：原則 1 的範圍包含 MUST，Planner 可能更常替邊界句辯護，Auditor 可能被說服。這只靠 4 份定稿、兩位評審與下面條件 1 的加嚴規則把關。

## 執行組（依序執行，每個都是新目錄，不覆寫既有證據）

| 順序 | 命令 | 目錄 |
|---|---|---|
| 1 | `run_claude.py --scenario forced_conflict --prompts v81` | `evidence/runtime-claude-conflict-v81-1` |
| 2 | `run_claude.py --scenario forced_conflict --prompts v8` | `evidence/runtime-claude-conflict-v8-4`（同時段的 v8 對照，不進採用條件） |
| 3 | `run_claude.py --scenario forced_conflict --prompts v81` | `evidence/runtime-claude-conflict-v81-2` |
| 4 | `run_claude.py --scenario forced_conflict --prompts v81` | `evidence/runtime-claude-conflict-v81-3` |
| 5 | `run_claude.py --scenario normal --prompts v81` | `evidence/runtime-claude-normal-v81` |

之後依序：

```bash
python eval_v8.py analyze evidence/runtime-claude-conflict-v6 evidence/runtime-claude-conflict-v6-repeat evidence/runtime-claude-conflict-v6-run3 evidence/runtime-claude-conflict-v8-1 evidence/runtime-claude-conflict-v8-2 evidence/runtime-claude-conflict-v8-3 evidence/runtime-claude-normal-v8 evidence/runtime-claude-conflict-v8-4 evidence/runtime-claude-conflict-v81-1 evidence/runtime-claude-conflict-v81-2 evidence/runtime-claude-conflict-v81-3 evidence/runtime-claude-normal-v81 --out evidence/tiered-v81/analysis.json
python eval_v8.py package --seed 20261019 --item evidence/runtime-claude-conflict-v6:round1 --item evidence/runtime-claude-conflict-v6:final --item evidence/runtime-claude-conflict-v6-repeat:final --item evidence/runtime-claude-conflict-v6-run3:final --item evidence/runtime-claude-conflict-v8-1:final --item evidence/runtime-claude-conflict-v8-2:final --item evidence/runtime-claude-conflict-v8-3:final --item evidence/runtime-claude-normal-v8:final --item evidence/runtime-claude-conflict-v8-4:final --item evidence/runtime-claude-conflict-v81-1:final --item evidence/runtime-claude-conflict-v81-2:final --item evidence/runtime-claude-conflict-v81-3:final --item evidence/runtime-claude-normal-v81:final --package C:/Users/user/AppData/Local/Temp/t4blind-v81/package.md --reversed C:/Users/user/AppData/Local/Temp/t4blind-v81/package-reversed.md --key evidence/tiered-v81/blind-key/key.json
python blind_rate.py --package C:/Users/user/AppData/Local/Temp/t4blind-v81/package.md --out evidence/tiered-v81/ratings/rater1.json --raw evidence/tiered-v81/ratings/rater1-raw.json
python blind_rate.py --package C:/Users/user/AppData/Local/Temp/t4blind-v81/package-reversed.md --out evidence/tiered-v81/ratings/rater2-reversed.json --raw evidence/tiered-v81/ratings/rater2-reversed-raw.json
python judge_declines.py --runs evidence/runtime-claude-conflict-v81-1 evidence/runtime-claude-conflict-v8-4 evidence/runtime-claude-conflict-v81-2 evidence/runtime-claude-conflict-v81-3 evidence/runtime-claude-normal-v81 --seed 20261019 --out evidence/tiered-v81/declines/judgments.json --raw evidence/tiered-v81/declines/judge-raw.json --key evidence/tiered-v81/declines/key.json
python eval_v81.py --prereg evidence/tiered-v81/prereg.json --key evidence/tiered-v81/blind-key/key.json --analysis evidence/tiered-v81/analysis.json --ratings evidence/tiered-v81/ratings/rater1.json evidence/tiered-v81/ratings/rater2-reversed.json --raw evidence/tiered-v81/ratings/rater1-raw.json evidence/tiered-v81/ratings/rater2-reversed-raw.json --judgments evidence/tiered-v81/declines/judgments.json --judge-key evidence/tiered-v81/declines/key.json --judge-raw evidence/tiered-v81/declines/judge-raw.json --out evidence/tiered-v81/decision.json
```

沒有定稿的執行不放進盲評包（刪掉該 `--item`，其餘順序不變），照實報告。某一步依下面的規則重跑時，命令與目錄改用 `-retry` 版本。

## 盲評：重新評一次

v6、v8、v8.1 的定稿放進同一份新的盲評包，由兩位新的評審一起評（13 份：v6 正式執行的首輪稿、三份 v6 定稿、三份 v8 定稿與 v8 一般案例、同時段的 v8 對照定稿、三份 v8.1 定稿與 v8.1 一般案例）。選擇重評而不重用 v8 的分數，是因為點擊與閱讀價值是相對的判斷，同一組評審在同一份包裡比較才公平。評審設定沿用 v8：`blind_rate.py` 的隔離 CLI 呼叫（`claude-opus-5-5`、effort high、不開工具、空工作目錄、盲評包經 stdin），第一位讀登錄順序，第二位讀同標籤、順序相反的版本；呈現方式、規則與評分欄位和 v8 的盲評包相同。

v8 的採用依它自己的登錄已經判定，不因這次重評改變。新包裡 v8 定稿的評分照實報告；若有 v8 定稿被兩位新評審都判違規，對外並列兩次盲評的結果與原句，不改變 v8 的判定。

## 不採納理由的判讀

條件 5 不只看 Planner 有沒有回 decline。不採納的建議交給 `judge_declines.py`：一次與角色相同隔離的 CLI 呼叫，項目匿名、依種子打亂，v8.1 與同時段 v8 對照的項目混在一起，審閱者不知道版本、執行或預期結果。判準在執行前寫在程式中：

- (a) 理由有沒有針對這份大綱，說出採納建議會對讀者的點擊意願或閱讀價值造成什麼具體影響（只是表態、只談流程或規則、與這份大綱無關都算沒有）；
- (b) 被拒絕的建議是不是其實在處理三條 MUST 規則禁止的問題。

另由程式檢查：被拒絕的建議，它的 Auditor 文字是否仍以 10 字以上的連續片段出現在下一版（名義上拒絕、實際照抄）。

## 指標

由 `eval_v8.py analyze` 計算，定義與 v8 實驗相同：M1 Auditor 撰寫比例（全文、標題、內文）、定稿中出自 Auditor 的字數（比例 × 定稿字數；v6 中位數 269、v8 314）、M2（Auditor findings 在下一版是 adopted、kept 或 own，辯護被接受的項數；v8 是 own 0、辯護 0，列為主要描述指標）、M4 機器檢查、M5 收斂、M6 分級（建議被採納、不採納、未回覆、最後一輪提出的則數，不採納的理由逐字列出）。M3 盲評與不採納理由的判讀見上兩節。點擊與閱讀價值每組 3 份、每份是兩個整數分數的平均，只偵測得到 1.0 以上的下降；逐位評審的中位數照報。

## 採用條件（全部成立，v8.1 才取代 v8 成為對外的主要結果）

先檢查完整性：登錄的執行（或依規則取代它的 `-retry` 版本，須記在 `RUN_LOG.md`）、盲評包中每份應有的定稿、兩位評審的全部標籤都在；v8.1 每一次角色呼叫送出的系統提示雜湊與 `prereg.json` 登錄值相同；`roles_v81.py`、`roles_v8.py`、`workflow_v8.py` 與規則的雜湊相同；CLI 版本是 2.1.302、回報的模型是 `claude-opus-5-5`；兩位評審讀的是不同的包、呼叫成功且通過隔離檢查；判讀呼叫成功且通過隔離檢查。有缺項就判不採用。

合規優先，第一條不成立就不採用：

1. 每一份 v8.1 定稿（三次強制衝突與一般案例）：機器檢查全過、MUST 措辭不變，沒有被兩位評審都判為違規；而且 Planner 辯護、Auditor 接受而保留下來的 MUST 原句，只要任一位評審判為違規，這條就不成立。

其次（條件 5 到 8 只用強制衝突的三份定稿；某次沒收斂時，以剩下兩次計算，中位數即平均）：

2. v8.1 強制衝突三次中至少兩次在 3 輪內通過。
3. v8.1 一般案例通過，機器檢查全過。
4. 所有 v8.1 執行中，沒有任何一輪在沒有 MUST 項目時被退回。
5. v8.1 已收斂的強制衝突中，至少兩次有一則以上的不採納：判讀為 (a) 是、(b) 否，而且沒有被照抄進下一版。
6. 定稿更多出自 Planner：M1 中位數比 v6 低 0.15 以上（≤ 0.2111），而且定稿中出自 Auditor 的字數中位數低於 v8（314 字）。
7. 點擊吸引力：v8.1 中位數不低於 v8 中位數減 0.5（下降一整分才否決）。
8. 閱讀價值：同上。

判定由 `eval_v81.py` 計算，存為 `evidence/tiered-v81/decision.json`。

**對外能說什麼**：

- 採用時，對外以 v8.1 為主，寫成「分級讓反駁變安全、原則讓反駁發生」。但若同時段的 v8 對照也出現判讀通過的不採納（`decision.json` 的 `control_v8_judged_good_declines` 不為空），就不宣稱原則讓反駁發生，只寫觀察到的差異。
- 不採用時，對外仍以 v8 為主，v8.1 照實寫成學到的事，並寫明連明示原則都無法克服的程度（不採納的則數、判讀結果、M1 與字數的變化）。

## 已知的限制與審稿意見中未改的部分

- 原則 1 的「Auditor 的意見，尤其是建議……而非必須執行的指令」範圍包含 MUST，和 v8 既有的「review.must 是必須解決的合規問題」語氣不同，可能讓 Planner 多爭 MUST、耗掉輪數；「尤其是建議」也直接對準條件 5。原則的措辭由使用者定稿，不改；風險由條件 1 的加嚴、條件 2 的收斂要求與條件 5 的獨立判讀承擔，結果照實報告。
- 兩個角色、兩位評審與判讀者都是 Claude；每組 3 次，不做因果主張。

## 不調參與停止規則

- 寫定後不因結果修改提示詞或計分程式。
- 非模型輸出造成的失敗（逾時、暫時性錯誤重試用盡、CLI 沒有回傳 JSON、程序無法啟動）：同一命令在 `-retry` 目錄重跑一次，由 `-retry` 取代原目錄，原目錄保留，`RUN_LOG.md` 記下原因。
- 模型的產出造成的結果一律計入、不重跑：轉人工、輸出內容不合格。
- 回報用量上限或連續兩次執行因錯誤失敗，立即停止並回報；不換帳號、不改用付費路徑。實驗不完整時判不採用。
- 每步結束後才開始下一步；不刪除或覆寫既有目錄；評審與判讀的原始回覆原樣保存，程式不覆寫既有檔案。紀錄的時間由 Python 產生（台北時間）。

## 寫定前的審稿意見與處理

| 意見 | 處理 |
|---|---|
| 1. 條件 5 量到的是有沒有回 decline，不是有依據地堅持；理由由知道預期的人判讀 | 採納：改由不知道版本與預期的獨立判讀（`judge_declines.py`，判準事前寫定），只計已收斂、判讀通過、沒被照抄的不採納 |
| 2. 點擊與閱讀「不低於 v8」解析度太粗，同品質時約四成機率被雜訊否決 | 採納：改成不低於 v8 減 0.5，寫明只偵測得到 1.0 以上的下降，逐位評審中位數照報 |
| 3. M1 門檻太鬆，且受定稿長度干擾（v8 的 M1 下降完全來自篇幅） | 採納：條件 6 加上「出自 Auditor 的字數中位數低於 v8」；M2 的自寫與辯護列為主要描述指標；v8 的篇幅效應寫進問題陳述 |
| 4. `-retry` 重跑會讓完整性檢查判不採用 | 採納：`-retry` 取代登錄的執行（須記在 `RUN_LOG.md`），有測試 |
| 5. 沒比對實際送出的提示、`roles_v8.py`、CLI 版本與回報的模型 | 採納：完整性檢查逐次比對系統提示雜湊，並比對 `roles_v8.py`、CLI 版本與模型 |
| 6. 沒有同時段的 v8 對照 | 採納：穿插一次 v8 強制衝突（第 2 步），放進盲評與判讀，不進採用條件；它也出現判讀通過的不採納時，不宣稱原則讓反駁發生 |
| 7. Planner 更會辯護，Auditor 可能被說服 | 採納：條件 1 加嚴（被接受的辯護句只要一位評審判違規就不成立），並寫明這個風險只靠 4 份定稿把關 |
| 8. 原則的範圍、理由不對稱與禁止句 | 不改措辭（使用者定稿，逐字使用）；風險寫進限制，由條件 1、2、5 承擔。審稿之後使用者把兩段改寫成一般書面語，意思不變，未再送審 |
| 9. 計畫與程式沒對齊 | 採納：寫明條件 5 到 8 只用強制衝突定稿、沒收斂時的計算、v8 定稿被新評審判違規時的寫法 |
| 10. 改動清單漏列 `run_claude.py` 與新檔 | 採納：見「唯一的提示改動」末段與 `prereg.json` |
| 11. 測試範圍 | 採納：逐字比對拿掉原則後的提示與原則位置、判定的正向路徑與逐條翻轉、`-retry`、照抄檢查、判讀輸入不洩漏版本 |
