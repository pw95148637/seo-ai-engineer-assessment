# v7 平衡協商實驗：事前登錄

本檔與同目錄的 `prereg.json` 在任何 v7 模型呼叫之前寫定；`prereg.json` 記錄寫定時間、本檔與相關程式的 sha256。寫定後不改判準、不改提示詞，本檔也不再修改；執行經過只記在 `RUN_LOG.md`。

## 要回答的問題

v6 的強制衝突能收斂，但協商偏向 Auditor：兩次正式執行中，Planner 對 13 項退件全部採用 Auditor 的寫法，沒有一項自寫或辯護（M2），定稿有 26% 與 36% 的文字出自 Auditor 的建議（M1）。v7 要檢驗：讓 Auditor 只給合規的邊界與方向、由 Planner 負責寫法並逐項回應（接受、反提案或辯護），能否讓定稿更多出自 Planner，同時不放寬合規、不降低點擊吸引力，也仍在 3 輪內收斂。

## 固定不變的部分

- 審核規則 `policy.json`（`custom-provisional-v5`，sha256 開頭 437a61a9）與控制器 `workflow.py`（3 輪上限、字面防線、逾時與重試）都不改。
- v6 的提示詞 `roles.py` 不改；v7 的提示詞在 `roles_v7.py`，由 `run_claude.py --prompts v7` 選用。差異只有 `roles_v7.py` 開頭註解列出的三點；提示詞不寫入原題舉例的答案（`test_balance_v7.py` 檢查「資安」「勝率」不在兩個角色的系統提示中）。
- 模型 `claude-opus-5-5`、effort high、Claude Code CLI 2.1.301，兩個角色同一模型；呼叫隔離旗標與 v6 相同。

## 執行組（依序執行，每個都是新目錄，不覆寫既有證據）

| 順序 | 命令 | 目錄 |
|---|---|---|
| 1 | `run_claude.py --scenario forced_conflict --prompts v7` | `evidence/runtime-claude-conflict-v7-1` |
| 2 | `run_claude.py --scenario forced_conflict --prompts v6` | `evidence/runtime-claude-conflict-v6-run3` |
| 3 | `run_claude.py --scenario forced_conflict --prompts v7` | `evidence/runtime-claude-conflict-v7-2` |
| 4 | `run_claude.py --scenario forced_conflict --prompts v7` | `evidence/runtime-claude-conflict-v7-3` |
| 5 | `run_claude.py --scenario normal --prompts v7` | `evidence/runtime-claude-normal-v7` |

v6 的比較組是三次強制衝突：既有的 `runtime-claude-conflict-v6`、`runtime-claude-conflict-v6-repeat`，加上第 2 步。

## 指標

M1、M2、M4、M5 由 `analyze_balance.py` 計算（定義寫在該檔開頭；WINDOW = 6 字元、ADOPT_RUN = 10 字元），結果存為 `evidence/balance-v7/analysis.json`。

- **M1 Auditor 撰寫比例**：定稿標題與各段（去空白）中，被 Auditor 某輪 revision 裡、且不見於該輪以前任何 Planner 文字（草稿、negotiation_note、responses）的 6 字元片段覆蓋的比例。越低代表 Planner 自己寫得越多。
- **M2 雙向程度（描述用，不作為採用條件）**：每一項有下一版草稿的退件，分成 adopted（下一版含 10 字元以上連續的 Auditor 原創文字）、kept（原句仍在）、own（Planner 自己改寫）；另計 kept 之後下一輪 Auditor 沒再退回的項數（辯護被接受）。v7 另列 Planner 自己申報的 accept／counter／defend 數量，只供參照。
- **M3 盲評**：由 `make_blind_package.py --seed 20261017` 產生匿名、打亂順序的盲評包，內容是 v6 正式執行的首輪稿、三份 v6 定稿與 v7 的定稿（沒有定稿的執行不放入），只含標題與段落和不變的四條規則。對照表另存在不同資料夾。由主對話派兩位沒看過任何內容的評審獨立評分：點擊吸引力 1–5 分，以及依規則列出違規原句。每份的吸引力分數取兩位評審的平均；兩位都列出違規才算該份違規，只有一位列出記為有爭議並照實報告。
- **M4 合規（機器部分）**：`verification.json` 的機器檢查全過、規則雜湊與 v6 相同、定稿不含兩個指定詞。
- **M5 收斂**：v7 強制衝突三次中，在 3 輪內通過的次數。

## v6 基準（執行前以同一程式計算既有兩次）

| 執行 | 輪數 | M1 全文 | M1 標題 | M2 adopted／kept／own | 辯護被接受 |
|---|---|---|---|---|---|
| runtime-claude-conflict-v6 | 3 | 0.2578 | 0.75 | 7／0／0 | 0 |
| runtime-claude-conflict-v6-repeat | 2 | 0.3611 | 0.8571 | 6／0／0 | 0 |

第三次 v6（第 2 步）執行後以同一程式補算，v6 的中位數取三次。

## 採用條件（全部成立，v7 才取代 v6 成為對外的主要結果）

1. 每一次產出定稿的 v7 強制衝突：機器檢查全過、規則雜湊不變，且沒有被兩位評審都判為違規。
2. M5：v7 強制衝突三次中至少兩次在 3 輪內通過。
3. M1：v7 定稿的中位數比三份 v6 定稿的中位數低 0.15 以上。
4. M3：v7 定稿吸引力分數的中位數不低於 v6 定稿的中位數。
5. v7 一般案例通過，機器檢查全過。

任何一條不成立：對外仍以 v6 為主，v7 的結果照實寫成學到的事。

## 不調參與停止規則

- 提示詞寫定後不因結果修改。只有格式或 schema 錯誤（例如 CLI 回報結構化輸出無效）可以修正一次，並在新目錄（原目錄名加 `-retry`）重跑該步，修正內容與原因記在同目錄的 `RUN_LOG.md`。
- 回報訂閱用量上限、或連續兩次執行因 CLI 錯誤失敗，立即停止並回報；不換帳號、不改用付費路徑。
- 每步結束後才開始下一步；任何一步都不刪除或覆寫既有目錄。
