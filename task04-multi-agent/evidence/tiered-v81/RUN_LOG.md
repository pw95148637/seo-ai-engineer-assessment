# v8.1 實驗執行紀錄

只記事實：時間（台北）、步驟、目錄、狀態、是否重跑。判準見 `PREREGISTRATION.md`，雜湊見 `prereg.json`。

- 2026-10-17T21:22:28+08:00 登錄完成（離線測試 83 項通過），此前沒有任何 v8.1 模型呼叫。
- 2026-10-17T21:22:38+08:00 步驟 1 開始：`run_claude.py --scenario forced_conflict --prompts v81 --out evidence/runtime-claude-conflict-v81-1`
- 2026-10-17T21:27:01+08:00 步驟 1 結束：exit 0，狀態 approved_provisional，輪數 3，角色呼叫 6，機器檢查全過 True
- 2026-10-17T21:27:01+08:00 步驟 2 開始：`run_claude.py --scenario forced_conflict --prompts v8 --out evidence/runtime-claude-conflict-v8-4`
- 2026-10-17T21:30:53+08:00 步驟 2 結束：exit 0，狀態 approved_provisional，輪數 3，角色呼叫 6，機器檢查全過 True
- 2026-10-17T21:30:53+08:00 步驟 3 開始：`run_claude.py --scenario forced_conflict --prompts v81 --out evidence/runtime-claude-conflict-v81-2`
- 2026-10-17T21:35:13+08:00 步驟 3 結束：exit 0，狀態 approved_provisional，輪數 3，角色呼叫 6，機器檢查全過 True
- 2026-10-17T21:35:13+08:00 步驟 4 開始：`run_claude.py --scenario forced_conflict --prompts v81 --out evidence/runtime-claude-conflict-v81-3`
- 2026-10-17T21:39:26+08:00 步驟 4 結束：exit 0，狀態 approved_provisional，輪數 3，角色呼叫 6，機器檢查全過 True
- 2026-10-17T21:39:26+08:00 步驟 5 開始：`run_claude.py --scenario normal --prompts v81 --out evidence/runtime-claude-normal-v81`
- 2026-10-17T21:42:01+08:00 步驟 5 結束：exit 0，狀態 approved_provisional，輪數 2，角色呼叫 4，機器檢查全過 True
- 2026-10-17T21:42:01+08:00 登錄的步驟執行完畢。
- 2026-10-17T21:42:30+08:00 analyze 與 package 完成（13 份大綱，種子 20261019）；開始盲評與判讀。
- 2026-10-17T21:46:17+08:00 兩位評審完成（各 13 份，隔離檢查通過）；判讀：沒有任何不採納的建議，未呼叫模型。以 eval_v81.py 判定：adopt_v81 為 false，完整性缺項 0。
