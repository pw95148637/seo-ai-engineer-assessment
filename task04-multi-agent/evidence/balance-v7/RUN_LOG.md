# v7 實驗執行紀錄

只記事實：時間（台北）、步驟、目錄、狀態、是否重跑。判準見 `PREREGISTRATION.md`，雜湊見 `prereg.json`。

- 2026-10-17T00:16:05+08:00 登錄完成，此前沒有任何 v7 模型呼叫。
- 2026-10-17T00:16:23+08:00 步驟 1 開始：`run_claude.py --scenario forced_conflict --prompts v7 --out evidence/runtime-claude-conflict-v7-1`
- 2026-10-17T00:18:50+08:00 步驟 1 結束：exit 0，狀態 approved_provisional，輪數 2，角色呼叫 4，機器檢查全過 True
- 2026-10-17T00:18:50+08:00 步驟 2 開始：`run_claude.py --scenario forced_conflict --prompts v6 --out evidence/runtime-claude-conflict-v6-run3`
- 2026-10-17T00:21:05+08:00 步驟 2 結束：exit 0，狀態 approved_provisional，輪數 2，角色呼叫 4，機器檢查全過 True
- 2026-10-17T00:21:05+08:00 步驟 3 開始：`run_claude.py --scenario forced_conflict --prompts v7 --out evidence/runtime-claude-conflict-v7-2`
- 2026-10-17T00:23:56+08:00 步驟 3 結束：exit 0，狀態 approved_provisional，輪數 2，角色呼叫 4，機器檢查全過 True
- 2026-10-17T00:23:56+08:00 步驟 4 開始：`run_claude.py --scenario forced_conflict --prompts v7 --out evidence/runtime-claude-conflict-v7-3`
- 2026-10-17T00:25:59+08:00 步驟 4 結束：exit 0，狀態 approved_provisional，輪數 2，角色呼叫 4，機器檢查全過 True
- 2026-10-17T00:25:59+08:00 步驟 5 開始：`run_claude.py --scenario normal --prompts v7 --out evidence/runtime-claude-normal-v7`
- 2026-10-17T00:27:03+08:00 步驟 5 結束：exit 0，狀態 approved_provisional，輪數 1，角色呼叫 2，機器檢查全過 True
- 2026-10-17T00:27:03+08:00 五個步驟全部執行完畢。
- 2026-10-17T00:28:17+08:00 依登錄種子 20261017 產生盲評包 `evidence/balance-v7/blind/package.md`（7 份），對照表另存 `evidence/balance-v7/blind-key/key.json`。打亂結果恰好把三份 v7 定稿排在 A、B、C；判準與種子不變，另在 repo 外提供同標籤、順序相反的版本，供第二位評審使用以抵銷順序效應，是否採用由主對話決定。
- 2026-10-17T00:33:00+08:00 寫好 M3 計分與採用判定程式 `score_blind.py`（在任何評分結果出現之前），只用合成資料測試過；計分方式照 `PREREGISTRATION.md` 的 M3 定義。
- 2026-10-17 盲評由主對話另派兩位沒看過任何內容的評審完成，原文存在 `ratings/`。第一位用 `package.md`（登錄的順序）；第二位用同標籤、順序相反的版本（`rater2-reversed.json`），用來抵銷三份 v7 定稿剛好排在 A–C 的順序效應。這個呈現方式不在登錄中，判準與計分程式不變。
- 2026-10-17 以 `score_blind.py` 依登錄條件判定，結果存在 `decision.json`：`adopt_v7` 為 false。條件 1 不成立（兩份 v7 定稿被兩位評審一致判為 LEGAL 違規），條件 2 到 5 成立。依登錄，對外仍以 v6 為主。
