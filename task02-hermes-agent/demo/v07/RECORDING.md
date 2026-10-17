# 第二題 Demo：R4 真實執行錄影

## 現況（R4 已錄製，Demo 已定稿）

R4 是真實 run：在 WSL 的 `~/soulo/task02-hermes` 用 `record_r4.sh` 執行 `python3 scripts/evaluate_v07.py --step R4`，同一次執行同時錄成 Demo，取代 `demo/Hermes_Task02_Demo.mp4`（v0.5 字幕重播）。

**已完成：**
- 錄製：2026-10-16 09:35 UTC，擷取 298 秒；run 本身 182 秒，一次完成（research_complete）。擷取在 `demo/v07/r4/capture/`，五個章節標記都在。
- 轉檔：`Hermes_Task02_Demo_v07.mp4`，289.8 秒（4:50），1280×720、H.264、12 fps；字幕 `Hermes_Task02_Demo_v07.mp4.srt`，時間軸 `.timeline.json`，抽樣畫面 `Hermes_Task02_Demo_v07_frames/`。研究段以實際速度播放，只有兩次長的模型等待快轉（54 秒的回合 ×3、40 秒的回合 ×2），空白換頁 ×6。
- 各段起點（影片秒數，含章節卡）：片頭 0、① 11.6、② 38.8、③ 142.4、④ 188.7、⑤ 238.8、片尾 279.8。
- 字幕依實際畫面寫成：控制器重抓帳本目標頁並交出 evidence_id；模型用 `research_offpage` 讀了一頁站外頁；報告第一次提交就被接受。⑤ 段先陳述這次的量測與跨版本對照，再寫同版空帳本對照組的結果（第 9 次呼叫才讀到目標頁；這次的總 tokens 比它多 16%，扣掉快取命中後約少 20%，屬判定後的分析）與判定「學習未證明改善」；片尾卡寫判定、判定後的快取分析兩個數字（2030.tw 約少 20%、保留站約多 11%）、後續 v0.8 結果見文件，以及證據位置。
- 開場帳本頁固定一屏：每條 lesson 一列，放不下的收成「另 N 條」；live 模式在 120×16 窗格同時看得到標題列與 `[1/5]`。檢查方式：WSL 開 120×16 的私用 tmux，執行 `demo_live_view.py events --task-root . --root /tmp/no-run --ledger-db evaluation/v06/runs/2030-series/research.sqlite --max-wait 20`，3 秒後 `capture-pane -p`。
- 對照表的列名用白話：「上一版 空帳本首跑」「上一版 無記憶對照」「上一版 凍結帳本」，分別是 v0.6 的 R1、B1、R3。
- 結尾頁最後的空行不再換出一張空白頁；轉檔時 CJK 字型沒有的寬字元（例如 🎰）改用 Segoe UI Emoji 繪製。這次的擷取仍有一張空白換頁，影片以 ×6 帶過。

片尾卡只改 `storyboard-r4.json` 的 `outro_card` 後重新轉檔：解碼後第 0–3340 幀與原版逐像素相同，片尾卡前 16 幀因 H.264 編碼參照有最多 2/255 的差異，片長與字幕檔不變。

改字幕時只改 `storyboard-r4.json` 再轉檔（不動擷取，約一分鐘），改完先跑 `--check-text`。

## 管線

| 步驟 | 程式 | 在哪裡跑 | 做什麼 |
|---|---|---|---|
| 檢視 | `scripts/demo_live_view.py` | WSL | 唯讀。逐筆讀控制器寫進 `research.sqlite` 的事件，印成易讀的步驟；結束後印報告、score_run 指標與帳本變化 |
| 錄製 | `scripts/demo_record.py` | WSL | 開一個私用 tmux（`-L soulo-demo`），分成三個窗格。每 0.25 秒用 `tmux capture-pane -e` 擷取各窗格畫面（文字與顏色），有變化才存入 `frames.jsonl`；`pipe-pane` 另存原始位元組 |
| 轉檔 | `scripts/demo_render.py` | Windows | 把擷取畫成 1280×720 MP4（Pillow＋ffmpeg）；加上章節卡、字幕、倍率與實際經過時間；另輸出 `.srt` 與 `.timeline.json` |

畫面有三個窗格，由上而下：

1. **檢視器**：讀本 run 的 `research.sqlite`。
2. **Hermes `agent.log`**：即時 tail，略去連線細節行。
3. **執行命令**：實際跑 `evaluate_v07.py --step R4` 的窗格。

### 資料來源

**run 進行中即時更新的資料：**
- `evaluation/v07/runs/R4/research.sqlite` 的 `events` 表：`Research.event` 每筆都 commit。內容包括 tool_call 與模型寫的 purpose、request／response 的 HTTP 狀態、extracted 的連結數、search 結果、offpage 訊號、lessons_presented、tool_error、report。
- Hermes `agent.log`：每次模型 API 呼叫的 tokens 與延遲、每次工具完成、DDGS 搜尋結果數。

**run 結束後才寫出的資料：**
- `RUN_ID-hermes.json`：含模型途中的 commentary（待驗假設與修正）及最終回覆。
- `-usage.json` 與 `-outcome.json`。

檢視器在結尾頁才顯示這幾份檔案的內容，並在畫面上寫明來源。

### 檢視器怎麼判定 lesson 有沒有被用到

只標可以機械判定的事實：
- 模型讀的網址等於某條 discovery lesson 記載的目標頁。
- 模型用 `research_evidence` 讀控制器本輪重抓的證據。
- 查詢有沒有用 `site:`，帳本是否記錄過 site: 查詢失敗。

畫面只陳述這些事實，不宣稱因果。

### 快轉規則

只快轉沒有畫面變化的等待。每段有基準倍率 `base`。若兩次畫面變化相隔超過 `idle_gap` 秒，先以基準倍率播 `lead` 秒，其餘以 `idle_speed` 播放；快轉段不足 `min_ff` 秒時不快轉，避免標示閃動。

每一幀右上角都標出當下倍率（`×1 即時`／`×6 快轉`）與實際經過時間。`.timeline.json` 列出每段快轉在影片中與實際時間中的起訖。

## 錄製前

1. 確認 v0.7 計畫已登錄，並同步到 WSL。`bash demo/v07/record_r4.sh` 會先跑 `python3 scripts/evaluate_v07.py --verify`，失敗就停止。
2. 確認登入與額度，避免錄到一半被限流：

   ```bash
   cd ~/soulo/task02-hermes && source scripts/hermes_env.sh
   python "$task_root/.runtime/pinned/hermes" usage --provider openai-codex --json
   ```

   R4 約用一個 v0.6 研究 run 的量：約 3 個百分點的 Session，約 30 萬 tokens。
3. 確認沒有其他 run 正在寫 `evaluation/v07/`，也沒有其他人在用 `tmux -L soulo-demo`。錄影開始時會關掉這個私用 tmux server，不影響其他 tmux。

## 錄製（WSL）

```bash
bash /mnt/c/Users/user/Desktop/SEO/tasks/task02-hermes/demo/v07/record_r4.sh
```

腳本的動作：
1. 先跑 `--verify`。
2. 把擷取寫到 `demo/v07/r4/capture/`；目錄已有錄影就拒絕執行。
3. 命令窗格先等 15 秒，讓檢視器顯示 R4 開始時的帳本（也就是 R4 複製的 v0.6 帳本），再執行 `python3 scripts/evaluate_v07.py --step R4`。
4. 檢視器印出「檢視器結束」且命令結束後再留 6 秒，然後收掉 tmux。

全程約 4–6 分鐘；run 本身最多 16 分鐘。

**選用：** 想同時在另一個 WSL 終端唯讀觀看，可執行 `tmux -L soulo-demo attach -r -t demo`。`-r` 是唯讀，不要在畫面裡打字。

**run 失敗時**（登入、額度、網路）：錄影照樣保留，它是失敗證據。依 `evaluate_v07.py` 的規則修好環境後重試一次，並錄到新目錄：`RETRY=1 bash record_r4.sh /mnt/c/Users/user/Desktop/SEO/tasks/task02-hermes/demo/v07/r4-retry/capture`。Agent 自己沒用工具、沒交報告，屬研究結果，不能重試。

## 轉檔（Windows）

```bash
cd C:/Users/user/Desktop/SEO/tasks/task02-hermes
python scripts/demo_render.py --capture demo/v07/r4/capture --storyboard demo/v07/storyboard-r4.json \
  --out demo/v07/Hermes_Task02_Demo_v07.mp4 --snapshots 10,60,120,180,240,290
```

- 程式會印出影片長度、各章節起點與快轉區間，並把抽樣畫面存到 `demo/v07/Hermes_Task02_Demo_v07_frames/`。
- 目標約 5 分鐘。太長就提高該段的 `idle_speed`（等待的快轉倍率）；太短就降低它，研究段最多以實際速度播放（`base` 1），不放慢。
- 只改倍率與字幕，**不改擷取檔**，然後重新轉檔；轉檔約十幾秒。
- 抽幾張畫面檢查：中文正常、章節卡位置對、倍率標示合理、字幕與畫面一致。
- 改字幕後先跑 `python scripts/demo_render.py --storyboard demo/v07/storyboard-r4.json --check-text`：列出會被截斷或把英文字拆到兩行的字幕與卡片文字，全部 ok 再轉檔。

## 字幕

完整字句在 `storyboard-r4.json`。每段用檢視器印出的一行當標記（例如 `#11 research_offpage`、`值得優先採取的競爭行動（續 2/2）`），那一行出現時換字幕，所以同一章可以有好幾個標記；有 `card` 的標記才放章節卡。寫法：先講看到的結果與意義，機制隨後；不出現內部代號，R4 第一次出現時說明它是哪一組；判定以 `evaluation/v07/VERDICT.md` 為準。

| 段 | 原題項目 | 畫面 | 字幕重點 |
|---|---|---|---|
| 片頭 | 全部 | 標題卡 | 官方 Hermes（固定 commit）加唯讀工具；這次執行帶著上一版帳本、學習凍結；三個窗格；tmux 真實擷取、倍率標示 |
| ① | Memory / Learning | 開始前帳本 | 帳本裡有哪幾類經驗；只由控制器量測與審查寫入；審查回饋由 Claude 在使用者授權下代審 |
| ② | Agent 自主研究、Tool Use | 每一步工具呼叫 | 控制器重抓並交出 evidence_id；模型直接讀證據命中目標頁；查詢被股票代號干擾後改查品牌名；站外頁規則與結果；預算 |
| ③ | Evidence-based Decision | 報告提交與核對、模型途中的假設與修正 | 第一次就被接受；觀察／推論／未知分開；控制器只核對結構，語意由盲評；假設 → 反證 → 修正 |
| ④ | 最終競爭分析與行動建議 | 結論、站內／站外發現、仍未知、行動 | 結論與限度；站內反證；未知明列；行動只針對我方網站、依優先順序 |
| ⑤ | Memory / Learning | score_run 指標、對照表、帳本變化 | 這次的量測；與上一版對照；同版空帳本對照組找頁較慢、總 tokens 較少，但扣掉快取命中後較多；判定未證明改善；帳本凍結無變化 |
| 片尾 | 全部 | 判定與證據卡 | 判定（學習未證明改善、站外未達標、沒有退步）；判定後的快取分析（2030.tw 約少 20%、保留站約多 11%，判定不變）；後續 v0.8 結果見文件；證據路徑 |

## 交付時一起保留

- `demo/v07/Hermes_Task02_Demo_v07.mp4`，以及同名 `.srt`、`.timeline.json`。
- `demo/v07/r4/capture/`：`layout.json`、`frames.jsonl`、`raw-*.log`、`pane-*.sh`，可重新轉檔與稽核。
- 舊的 `demo/Hermes_Task02_Demo.mp4` 留作 v0.5 字幕重播的封存。

## 演練（v0.6 R3 重播，只測管線）

```bash
bash /mnt/c/Users/user/Desktop/SEO/tasks/task02-hermes/demo/v07/rehearse.sh          # WSL，約 3.6 分鐘，不呼叫模型
python scripts/demo_render.py --capture demo/v07/rehearsal/capture \
  --storyboard demo/v07/storyboard-rehearsal.json --out demo/v07/rehearsal.mp4   # Windows
```

上方檢視器與中間日誌窗格是重播：依 v0.6 R3 的原始時間戳重新印出已存事件與 `agent.log` 行。標題列、窗格標題與片頭都標示「演練：重播 v0.6 R3」。這段影片不是最終 Demo。

**2026-10-16 結果：** `rehearsal.mp4` 為 1280×720、H.264、12 fps，長 56.3 秒，由 218.9 秒的擷取轉成。研究段 ×5，等待模型 ×15，結尾頁 ×2–2.5。五個章節卡都落在正確的標記上。擷取與抽樣畫面分別在 `rehearsal/capture/` 與 `rehearsal_frames/`。

前兩版演練抓到並已修正的問題：
- `↳` 在 Consolas 與微軟正黑體都沒有字形，畫成方框，已改用 `└`。
- 快轉倍率每零點幾秒切換一次，已加 `min_ff`。
- 分頁會把一項主張或對照表切成兩半，已改成同一項目與段落標題同頁。
- 保留站誤寫「此站」，lesson 只在 2030.tw 觀察過，已依 `applies` 改寫。

**live 模式另外測過：** 用 scratch 模擬器把 R3 的事件與 `agent.log` 行依原時間寫進新的 run 目錄，先複製帳本，與 evaluate_v07 相同。檢視器能：
- 在複製帳本裡找出新 run，靠 `runs.created` 判斷，不會誤抓 v0.6 的舊 run。
- 以 `--ledger-db` 先顯示帳本。
- 在 run 結束後印出結尾頁。

這個模擬器只放 scratch，不進 repo。

## 限制

- 模型的 commentary 只寫進 `hermes.json`，run 結束後才看得到。研究途中的畫面只有控制器事件與 Hermes 日誌，看不到模型的文字思路。
- 擷取頻率 4 Hz。同一個 0.25 秒內連續印出的中間狀態不會各自成幀，但最後畫面都在；`raw-*.log` 保留完整輸出。
- 舊版報告沒有 `section` 欄位時，站內／站外依 topic 名稱分組，畫面會註明。v0.7 報告依模型標的 section 分組。
- 對照表的先前 run 取自 v0.6 分數檔。這四欄的計算方式在 v0.7 沒有改，但兩邊的程式版本不同，只能當參考。
