# 第二題 Demo：v0.9 帶經驗的組另跑一次的真實錄影

## 現況（已錄製、已轉檔）

這支影片錄的是一次真實研究：v0.9 評估結束後，用帶經驗那組（發現路徑＋審查回饋＋研究記憶）第 10 次結束時的帳本複本，在 2030.tw 另跑一次並同時錄影。評估證據 `evaluation/v09/` 只被讀取，沒有改動；這次研究不是評估中的 20 次之一，不計入判定。

- **研究**：run `c498391f8cea4ed0afd34808a0354209`，research_complete、exit 0；8 次模型呼叫、19 次工具呼叫，第 2 次工具呼叫就讀到目標頁；報告第一次提交就被接受（13 項主張：觀察 9、推論 2、未知 2；7 項行動）。
- **帳本複本**：WSL `runs/demo-v09/ledger-series`。錄影腳本複製 `evaluation/v09/runs/ledger-series` 的資料庫與快照，先核對資料庫雜湊等於 `evaluation/v09/steps.json` 裡第 10 次的 `ledger_after_sha256`，不符就停止。Hermes home `v09-demo-a1`，`--hermes-learning off`（Hermes 內建學習關閉），`--research-memory`（研究記憶開啟）。
- **錄製**：2026-10-17 13:34:21–13:40:11 UTC，擷取 350 秒（`capture/`）。研究 run 13:34:50 UTC 建立，命令 13:38:03 UTC 結束。
- **用量**：ChatGPT Session 6% → 9%，Weekly 46% → 46%（`capture.usage-before.json`、`capture.usage-after.json`）；兩次讀數都顯示 2 次 banked resets，沒有使用。總 tokens 345,476，其中命中提示快取 272,128；未命中快取的輸入＋輸出 73,348（`run/c498391f…-usage.json`）。
- **這次研究的檔案**：`run/` 有報告（`-report.md`、`-report.json`）、trace、`-hermes.json`（含模型途中的 commentary 與最終回覆）、用量、結果、預檢、system prompt、研究後的帳本 `research.sqlite` 與 23 個頁面快照。
- **成片**：`Hermes_Task02_Demo_v09.mp4`，314.9 秒（5:15），1280×720、H.264、12 fps，8.8 MB；字幕 `Hermes_Task02_Demo_v09.mp4.srt`，時間軸 `Hermes_Task02_Demo_v09.mp4.timeline.json`，抽樣畫面 `Hermes_Task02_Demo_v09_frames/`。

## 時間軸

影片時間含章節卡。原題要求展示的五項：自主研究、Tool Use、Evidence-based Decision、最終競爭分析與行動建議、Memory / Learning。

| 影片 | 段落 | 原題項目 | 畫面與字幕 |
|---|---|---|---|
| 0:00 | 片頭卡 | 全部 | 官方 Hermes 加唯讀研究工具；模型決定查什麼，程式（控制器）負責範圍、預算、證據與經驗寫入；三個窗格與錄影方式 |
| 0:11 | ① 開始前的經驗 | Memory / Learning | 帳本：兩個目標頁網址、一則人工審查回饋、失敗經驗；研究記憶：9 條發現、讀過的 24 頁、425 個沒讀過的站內連結、7 個未知項；命令開始研究 |
| 0:38 | ② 自主研究與工具使用 | 自主研究、Tool Use | 模型先查預算與經驗；控制器讀 robots.txt、重抓兩個目標頁與研究記憶的頁面 |
| 1:01 | ② 研究記憶交給模型 | Memory / Learning | 頁面都沒變：9 條發現附這次的證據編號交給模型，另附 12 個沒讀過的站內頁與 7 個未知項 |
| 1:08 | ② 讀頁與搜尋 | 自主研究、Tool Use | 第 2、3 次工具呼叫讀到目標頁；網域搜尋被台股代號干擾；改讀研究記憶列出的未讀頁，讀頁工具交出結構化資料與圖片連結 |
| 1:30 | ② 往下查 | 自主研究 | 回讀研究記憶的發現所在頁；以網址與「科技」搜尋舊網址線索 |
| 1:47 | ② 站外 | Tool Use | 兩份 PDF 被控制器以格式不支援擋下；兩個 HTML 站外頁沒有連到或提及 2030.tw；54 秒的模型回合以 ×5 播放 |
| 2:17 | ③ 依證據收斂 | Evidence-based Decision | 報告第一次就被接受；控制器只核對證據編號、雜湊與結構，語意交給盲評；39 秒的最終回覆以 ×4 播放；run 結束 |
| 2:50 | ③ 假設與修正 | 自主研究、Evidence-based Decision | 模型途中寫下的假設、依新樣本的修正（58888 頁換模板、3A 缺點頁談風險）、站外結論「沒有確認有效的入站來源」 |
| 3:08 | ④ 競爭分析 | 最終競爭分析 | 結論與切入點；站內證據與反證；站外只有陰性樣本；7 個未知項 |
| 3:40 | ④ 行動建議 | 行動建議 | 7 項行動都針對我方網站，依 P0、P1、P2 排序，含 4 到 8 週的檢視方式 |
| 3:59 | ⑤ 這次的量測與對照 | Memory / Learning | 第 2 次工具呼叫讀到目標頁、19 次工具呼叫、3 條經驗都沒失效；對照評估中帶經驗第 1 次與不學習第 10 次都到第 9 次才讀到，成本介於兩者之間 |
| 4:22 | ⑤ 寫入經驗 | Memory / Learning | 研究記憶新增 9 條發現（候選）並取代上一份；PDF 被擋記成候選經驗；兩條目標頁經驗效期重新起算 |
| 4:40 | ⑤ 交還人類 | Memory / Learning（含人工回饋路徑） | 程式列出要人決定的事：P0 行動、新發現抽查與否決、預算與 PDF、未知項需要的資料 |
| 5:01 | 片尾卡 | 全部 | v0.9 評估的判定：帶經驗第 10 次勝第 1 次 3:0（明顯）；同一輪勝不學習 3:0（些微）；不學習第 1 次勝第 10 次 3:0（些微）；累積 24 對 13 頁；評審是三位 Claude agent |

各段在影片與實際時間中的起訖，以及每段快轉，見 `.timeline.json` 的 `chapters` 與 `speed_intervals`。

## 管線

| 步驟 | 程式 | 在哪裡跑 | 做什麼 |
|---|---|---|---|
| 檢視 | `scripts/demo_live_view.py` | WSL | 唯讀。逐筆讀控制器寫進 `research.sqlite` 的事件印成步驟；結束後印報告、score_run 指標、與評估分數的對照、帳本與研究記憶的變化、交還人類清單 |
| 錄製 | `scripts/demo_record.py` | WSL | 私用 tmux（`-L soulo-demo`）三個窗格，每 0.25 秒用 `capture-pane -e` 擷取畫面，有變化才存入 `frames.jsonl`；`pipe-pane` 另存原始位元組 |
| 轉檔 | `scripts/demo_render.py` | Windows | 把擷取畫成 1280×720 MP4；加章節卡、字幕、倍率與實際經過時間；另輸出 `.srt` 與 `.timeline.json` |

窗格由上而下：檢視器（這次研究的 `research.sqlite`）、Hermes `agent.log`、實際執行的命令。命令窗格跑的是 `scripts/run_research.sh --mode memory --research-memory --hermes-learning off`（完整命令在 `capture/layout.json` 的 `commands.main`）。

檢視器只標可以機械判定的事實：模型讀的網址等於帳本記載的目標頁；模型用 `research_evidence` 讀控制器這次重抓的證據；讀的頁是研究記憶列出、之前沒讀過的候選；讀的頁是研究記憶發現所在、控制器這次剛重抓且沒變的頁。畫面不宣稱因果。模型途中的 commentary 寫在 `-hermes.json`，run 結束後才印出。

## 錄製（WSL）

```bash
bash /mnt/c/Users/user/Desktop/SEO/tasks/task02-hermes/demo/v09/record_v09.sh
```

腳本依序：
1. 跑 `python3 scripts/evaluate_v09.py --verify`，失敗就停止。
2. 擷取目錄已有錄影、或 `runs/demo-v09/ledger-series` 已存在，就拒絕執行（不覆寫既有的錄影與帳本複本）。
3. 複製第 10 次結束時的帳本與快照，核對雜湊；建立學習關閉的 Hermes home `v09-demo-a1`。
4. 讀用量；Session 到 90% 以上就停止，等重置。不使用 banked resets、credits 或任何付費。
5. 錄製：命令窗格先等 15 秒，讓檢視器顯示開始前的帳本與研究記憶，再執行研究；檢視器結尾每頁停 9 秒（`--page-pause 9`），報告逐項間隔 1.2 秒（`--pace 1.2`），對照表列帶經驗第 10 次、不學習第 10 次、帶經驗第 1 次的評估分數。
6. 結束後再讀一次用量。

錄完後把這次研究的報告、trace、帳本與快照從 WSL 的帳本複本複製到 `demo/v09/run/`。

## 轉檔（Windows）

```bash
cd C:/Users/user/Desktop/SEO/tasks/task02-hermes
python scripts/demo_render.py --storyboard demo/v09/storyboard-v09.json --check-text
python scripts/demo_render.py --capture demo/v09/capture --storyboard demo/v09/storyboard-v09.json \
  --out demo/v09/Hermes_Task02_Demo_v09.mp4 --snapshots 10,60,120,180,240,290
```

- 第一行列出會被截斷或把英文字拆到兩行的字幕與卡片文字，全部 ok 再轉檔。
- 轉檔約一分半，不改擷取檔；程式印出影片長度、各章節起點與快轉區間。
- 改長度只動 storyboard 的倍率（`idle_speed`、`lead`）與字幕。研究段最多以實際速度播放（`base` 1），不放慢。

### 快轉規則

只快轉沒有畫面變化的等待。兩次畫面變化相隔超過 `idle_gap`（4 秒）時，先以實際速度播 `lead` 秒，其餘以該段的 `idle_speed` 播放；快轉段不足 `min_ff`（1 秒）就不快轉。每一幀右上角標出倍率與實際經過時間。

命令窗格在等待模型時每 0.25 秒更新一次進度動畫，storyboard 以 `"idle_ignore": ["main"]` 讓它的變化不算畫面變化，動畫照樣畫出。沒有這一行時，每次等待都會被動畫打斷，不會快轉；v0.7 的 storyboard 沒有這一行，用目前的 `demo_render.py` 重新轉出的 v0.7 影片與 repo 裡的版本逐位元組相同。

這支影片的快轉：開場命令啟動後的等待 ×3；研究記憶交給模型後、以及②段後半 5–10 秒的模型等待 ×2；54 秒的模型回合 ×5；39 秒的最終回覆 ×4；最後一頁 ×2。檢視器結尾每頁 9 秒是檢視器的設定，不是研究時間。

## 字幕

完整字句在 `storyboard-v09.json`。每段用檢視器印出的一行當標記（例如 `#5 research_fetch`、`新發現`），那一行第一次出現時換字幕；有 `card` 的標記才放章節卡。

- 字幕只寫當下畫面看得到的事，數字取自畫面或 `run/`、`evaluation/v09/RESULT.md`。
- 不出現評估中的組別代號；「帶經驗的組」第一次出現在片尾卡時寫明是發現路徑＋審查回饋＋研究記憶。
- 人工審查回饋寫明由 Claude 在使用者授權下代審；片尾卡寫明評審是三位沒看過分數與計畫的 Claude agent，同一輪的勝出只標些微。

## 交付時一起保留

- `Hermes_Task02_Demo_v09.mp4` 與同名 `.srt`、`.timeline.json`、`_frames/`。
- `capture/`（`layout.json`、`frames.jsonl`、`raw-*.log`、`pane-*.sh`）：可重新轉檔與稽核。
- `run/`、`capture.usage-*.json`、`record_v09.sh`、`storyboard-v09.json`。

## 限制

- **不是評估中的 20 次之一**：評估結束後另跑，接著第 10 次的帳本，相當於帶經驗那組的第 11 次；判定只依 `evaluation/v09/`。
- **只有一次**：這次的成本 73,348 高於評估中帶經驗第 10 次的 70,843，低於不學習第 10 次的 86,688；單次的數字不代表平均。
- **研究記憶的重驗全部通過**：網站沒有變，待重讀與撤銷都是 0，影片看不到這兩條路徑。
- **快轉**：等待以 ×2–×5 播放並在畫面標示，研究段沒有剪接；`.timeline.json` 列出每段快轉在影片與實際時間中的起訖。開場的「準備」只有約 1 秒，因為檢視器 1 秒內就印出帳本頁。
- **畫面限制**：命令窗格只有 3 列，命令開頭被捲出畫面，只看得到結尾的 `--hermes-learning off --research-memory`。擷取頻率 4 Hz，同一個 0.25 秒內連續印出的中間狀態不會各自成幀，`raw-*.log` 保留完整輸出。
- **模型的思路**：commentary 只寫進 `-hermes.json`，研究途中的畫面只有控制器事件與 Hermes 日誌，假設與修正要到 run 結束後才印出。
