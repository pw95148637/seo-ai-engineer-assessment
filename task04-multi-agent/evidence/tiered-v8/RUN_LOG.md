# v8 實驗執行紀錄

只記事實：時間（台北）、步驟、目錄、狀態、是否重跑。判準見 `PREREGISTRATION.md`，雜湊見 `prereg.json`。

- 2026-10-17T18:14:50+08:00 登錄完成（離線測試 73 項通過），此前沒有任何 v8 模型呼叫。
- 2026-10-17T18:14:58+08:00 步驟 1 開始：`run_claude.py --scenario forced_conflict --prompts v8 --out evidence/runtime-claude-conflict-v8-1`
- 2026-10-17T18:18:43+08:00 步驟 1 結束：exit 0，狀態 approved_provisional，輪數 3，角色呼叫 6，機器檢查全過 True
- 2026-10-17T18:18:43+08:00 步驟 2 開始：`run_claude.py --scenario forced_conflict --prompts v6 --out evidence/runtime-claude-conflict-v6-run4`
- 2026-10-17T18:20:52+08:00 步驟 2 結束：exit 0，狀態 approved_provisional，輪數 2，角色呼叫 4，機器檢查全過 True
- 2026-10-17T18:20:52+08:00 步驟 3 開始：`run_claude.py --scenario forced_conflict --prompts v8 --out evidence/runtime-claude-conflict-v8-2`
- 2026-10-17T18:25:13+08:00 步驟 3 結束：exit 0，狀態 approved_provisional，輪數 3，角色呼叫 6，機器檢查全過 True
- 2026-10-17T18:25:13+08:00 步驟 4 開始：`run_claude.py --scenario forced_conflict --prompts v8 --out evidence/runtime-claude-conflict-v8-3`
- 2026-10-17T18:28:19+08:00 步驟 4 結束：exit 0，狀態 approved_provisional，輪數 3，角色呼叫 6，機器檢查全過 True
- 2026-10-17T18:28:19+08:00 步驟 5 開始：`run_claude.py --scenario normal --prompts v8 --out evidence/runtime-claude-normal-v8`
- 2026-10-17T18:31:15+08:00 步驟 5 結束：exit 0，狀態 approved_provisional，輪數 2，角色呼叫 4，機器檢查全過 True
- 2026-10-17T18:31:15+08:00 步驟 6 開始：`probe_auditor.py --prompts v8 --out evidence/runtime-claude-auditor-probe-v8`
- 2026-10-17T18:37:25+08:00 步驟 6 結束：exit 0，摘要 {"must_cases_as_expected": "8/8", "no_block_cases_as_expected": "3/3", "claude_cli_context_isolated": true, "errors": []}
- 2026-10-17T18:37:25+08:00 步驟 7 開始：`probe_auditor.py --prompts v6 --cases v8 --out evidence/runtime-claude-auditor-probe-v6-on-v8-cases`
- 2026-10-17T18:42:27+08:00 步驟 7 結束：exit 0，摘要 {"must_cases_as_expected": "8/8", "no_block_cases_as_expected": "2/3", "claude_cli_context_isolated": true, "errors": []}
- 2026-10-17T18:42:27+08:00 步驟 8 開始：`probe_company_samples.py --prompts v8 --out evidence/runtime-claude-auditor-company-samples-v8`
- 2026-10-17T18:47:31+08:00 步驟 8 結束：exit 0，摘要 {"clear_cases_matching": "5/5", "claude_cli_context_isolated": true}
- 2026-10-17T18:47:31+08:00 登錄的步驟執行完畢。
- 2026-10-17T18:48:12+08:00 analyze 與 package 完成（9 份大綱，種子 20261018）；開始盲評。
- 2026-10-17T18:50:27+08:00 兩位評審完成（各 9 份，隔離檢查通過，輸入約 14.3k tokens）；以 eval_v8.py score 判定。
- 2026-10-17T18:50:35+08:00 判定完成：decision.json 的 adopt_v8 為 true（完整性檢查無缺項，九條條件全部成立）；balance_claim_allowed 為 false。
- 2026-10-17T20:57:34+08:00 更正：上面最後三行原本寫成 UTC 時間配 +08:00 標記（10:48:12、10:50:27、10:50:35），已改為台北時間 18:48:12、18:50:27、18:50:35；其他行與各 JSON 的時間正確。
