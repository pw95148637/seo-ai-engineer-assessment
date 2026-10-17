# 任務三：以本地 LLM 審核中文 SEO 文章

在 Kaggle 的單張 T4 上以 4-bit 載入 Qwen3-8B，讓模型模擬「Google 官方 SEO 品質審核員」（角色模擬，不代表 Google）審核中文 SEO 文章片段，輸出含分數、扣分原因與具體建議的 JSON，再整理成 HTML 報表與 pandas DataFrame。公司提供的 20 筆文章以固定亂數切成 12 筆訓練資料與 8 筆測試資料；模型、prompt 與程式凍結之後，評估 Notebook 才讀測試資料。

- 報告：完整報告（逐筆審核與技術反思，給一般讀者的版本）、簡報
- Kaggle：[訓練 Notebook](https://www.kaggle.com/code/pw95148637/soulo-work03-v3b-train)、[評估 Notebook](https://www.kaggle.com/code/pw95148637/soulo-work03-v3-eval)、事後分析 Notebook：[16 位元對照與微調前後的誤差](https://www.kaggle.com/code/pw95148637/soulo-work03-posthoc-fp16)、[Qwen3-14B 對照](https://www.kaggle.com/code/pw95148637/soulo-work03-posthoc-14b)

## 結果

| 指標（8 筆測試資料） | 凍結的微調版本 | 同一模型不載入微調權重 |
|---|---|---|
| JSON 第一次就符合格式 | 8/8 | 8/8 |
| 判定：準確／部分準確／偏差 | 3／2／3 | 2／3／3 |
| 植入的錯誤 SEO 理論標成 `SEO_FALSE` | 2/2 | 2/2 |
| 參考主判讀沒有 YMYL 卻被標 `YMYL_RISK` | 4/6 | 4/6 |
| 分數落在參考區間：主判讀／含替代判讀 | 1/8／4/8 | 1/8／4/8 |

參考判斷由另一個 AI 在看到模型輸出前標註，逐筆判定由 AI 讀過輸出後寫成，兩者都不是公司標準答案；作者看過模型輸出與判定後逐筆覆核，全部同意（屬於確認，不是獨立標註，見 `evaluation/holdout8-human-review.md`）。模型抓得到錯誤 SEO 理論與無法查證的自述經驗；主要偏差是沒有保證或引導的賭博、貸款文章也常被標 YMYL，嚴重度偏高，漏標一篇關鍵字堆疊；微調幾乎沒有增量。全部指標在 `evaluation/holdout8-comparison.json`，說明見完整報告。

## 重現

以下命令都在本目錄執行。需要 Python 3.13（實測 3.13.14）與三個套件：

```bash
pip install jsonschema==4.26.0 nbformat==5.11.1 pandas==2.3.3
```

Windows 先設定 UTF-8 模式：PowerShell 用 `$env:PYTHONUTF8='1'`，cmd 用 `set PYTHONUTF8=1`。

### 0. 補齊公司資料

```bash
python scripts/fetch_data.py
```

20 筆文章來自公司的[公開資料表](https://docs.google.com/spreadsheets/d/198L8PDlajqKmSsz-ScUti7tYUnyTyUYBAa3nJWfyzCQ/edit)。repo 若沒有附 `data/*.csv`，這支程式會下載資料表、依 `data/split-manifest.json` 的 seed 重建 12／8 切分，並補上 `kaggle-retrieved/` 內比對程式要讀的副本；檔案已存在時只核對雜湊、不下載。最後一行應為 `PASS`；資料表內容若被改過，雜湊不符會直接停止。

### 1. 離線檢查（不需 GPU，約 10 秒）

```bash
python scripts/validate_data.py           # 重現 12／8 切分，輸出 "status": "PASS"
python scripts/workflow.py check-targets  # 12 筆監督答案符合格式
python scripts/test_workflow.py           # 格式契約、重寫規則、自動檢查與歷次真實輸出的回歸測試
python scripts/check_contract.py          # 13 個合成案例：1 個有效、12 個應被拒收
python scripts/verify_notebook.py         # 兩個 Notebook 與設定一致、沒有嵌入測試文章
```

後四個命令的最後一行都以 `PASS` 開頭。

### 2. 重算 8 筆測試資料的指標（不需 GPU）

```bash
python scripts/compare_holdout.py
```

主要輸入是 `kaggle-retrieved/soulo-work03-v3-eval/` 中從 Kaggle 下載的實際輸出、`evaluation/holdout8-reference.jsonl`（參考判斷）與 `evaluation/holdout8-review.csv`（逐筆判定）；彙整訓練歷程時另外讀各次訓練的下載輸出、`outputs/experiments/initial/`、`data/` 與 `knowledge.json`。它重新寫出 `evaluation/holdout8-comparison.json`、`report/holdout8-audit.csv` 與 `report/holdout8-audit.html`。輸出與 repo 內的檔案逐位元組相同，執行後 `git status` 不會出現變更。開頭兩行印出兩組的摘要，例如 `adapter verdicts {'準確': 3, '部分準確': 2, '偏差': 3}`。

另外四個選用命令：

- `python scripts/regate.py kaggle-retrieved/soulo-work03-v3b-train/work03`：用現行的自動檢查重判凍結版本的訓練輸出，應為 `"status": "FAIL"`、`"hard_total_excl_contract": 4`，這是凍結決定的依據。
- `python scripts/posthoc_analysis.py`：依 `evaluation/posthoc-plan.md` 重算凍結後的事後分析（16 位元對照與微調前後的誤差），讀 `kaggle-retrieved/soulo-work03-posthoc-fp16/` 的下載輸出，寫出 `evaluation/posthoc-results.json`。
- `python scripts/posthoc14b_analysis.py`：依 `evaluation/posthoc14b-plan.md` 重算凍結後的 Qwen3-14B 對照（同一個凍結 prompt 換成較大的模型），讀 `kaggle-retrieved/soulo-work03-posthoc-14b/` 的下載輸出，寫出 `evaluation/posthoc14b-results.json`。
- `python scripts/make_deliverable_figures.py`：從 `compare_holdout.py` 與兩個事後分析的結果、下載的輸出重畫報告與簡報的圖到 `deliverable/img/`，需要 Pillow 與 Noto Sans TC 字型（`NotoSansTC-VF.ttf`）。

`report/holdout8-audit.html` 下載後用瀏覽器開啟，可排序、篩選；表格也可用 `pandas.read_csv('report/holdout8-audit.csv', encoding='utf-8-sig')` 讀成 DataFrame。

### 3. 在 Kaggle 重跑兩階段流程（需要 GPU）

需要已完成手機驗證的 Kaggle 帳號（才能用 GPU 與網路）、Kaggle API 憑證與 `pip install kaggle==2.2.4`。Kaggle CLI 一律用 `python -P -m kaggle` 執行，避免目前目錄的檔名遮蔽標準函式庫。每週 GPU 配額可用 `python -P -m kaggle quota` 查詢；訓練約 25 分鐘、評估約 11 分鐘。

1. **建立測試資料集。** 建一個只含 `data/holdout8.csv` 的資料夾，執行 `python -P -m kaggle datasets init -p <資料夾>`，在產生的 `dataset-metadata.json` 填入自己的 id 與標題，再執行 `python -P -m kaggle datasets create -p <資料夾>`。資料集預設為私人。
2. **執行訓練 Notebook。** 把 `kaggle/train/kernel-metadata.json` 的 `id` 改成 `<你的帳號>/<名稱>-train`，執行 `python -P -m kaggle kernels push -p kaggle/train`。這個 Notebook 部署模型、微調、做三種 temperature 的一致性測試與 12 筆自我檢查，最後寫出凍結鎖 `frozen.json`；它不掛載測試資料，開頭會檢查。
3. **下載訓練輸出到新的空目錄**，並閱讀自動檢查結果：`python -P -m kaggle kernels output <你的帳號>/<名稱>-train -p <空目錄>`，結果在 `<空目錄>/work03/outputs/train_gate.json`。
4. **凍結並產生評估 Notebook。** 執行 `python scripts/build_notebook.py --lock <空目錄>/work03/outputs/frozen.json`。自動檢查未通過時必須加 `--accept-failed-gate "<理由>"`。程式會核對本機的 prompt、知識卡、設定、監督答案與程式和凍結鎖相同，有任何改動就拒絕產生；凍結後只允許改量測與報表程式，且必須加 `--accept-code-change "<理由>"`。產生的 `kaggle/eval/work03_eval.ipynb` 內嵌凍結鎖的雜湊。
5. **執行評估 Notebook。** 在 `kaggle/eval/kernel-metadata.json` 把 `id` 改成你的評估 kernel 名稱，`dataset_sources` 改成步驟 1 的資料集，`kernel_sources` 改成步驟 2 的訓練 kernel。執行 `python scripts/verify_notebook.py` 確認通過，再執行 `python -P -m kaggle kernels push -p kaggle/eval`。評估 Notebook 先核對凍結鎖、全部凍結檔案與測試資料的雜湊，相符才讀測試資料；凍結的微調版本與不載入微調權重的對照各跑一次 8 筆。
6. **下載評估輸出到另一個新的空目錄。** 審核結果在 `work03/outputs/`：`holdout.jsonl`、`audit_report.html`、`audit_report.csv`、`holdout_comparison.csv`、`metrics.json`。

注意事項：

- 產生評估 Notebook 之後，**不要再 push 訓練 kernel**。`kernel_sources` 只寫 kernel 名稱時，Kaggle 會掛載它最新一次的輸出；重新 push 會讓凍結鎖對不上，評估會在讀測試資料前停止。
- `kaggle kernels output` 一律下載最新版本，請下載到新的空目錄，不要覆蓋 `kaggle-retrieved/`。
- 本 repo 的 `kaggle/eval/kernel-metadata.json` 指向已完成的評估 kernel，`kaggle/train/kernel-metadata.json` 指向一個沒有用過的名稱；重跑前務必換成自己的名稱。

## 檔案導覽

| 位置 | 內容 |
|---|---|
| `system_prompt.txt`、`schema.json`、`knowledge.json` | 凍結的 prompt、JSON schema、8 張附官方網址的知識卡 |
| `run_config.json` | 模型版本、訓練與生成設定 |
| `data/` | 切分紀錄 `split-manifest.json`、12 筆監督答案 `train_targets.jsonl`；公司資料的 CSV 若沒有附上，由 `fetch_data.py` 補齊 |
| `scripts/workflow.py` | 所有 Kaggle 階段：部署測試、微調、一致性、自我檢查、凍結、凍結核對、審核、報表 |
| `scripts/audit_io.py` | 輸出格式的強制檢查：schema、引句是原文、來源存在、分數落在嚴重度區間 |
| `scripts/selfcheck.py` | 凍結前的自動檢查與報表上的提示旗標 |
| `scripts/build_notebook.py`、`scripts/verify_notebook.py` | 產生與檢查兩階段 Notebook |
| `scripts/compare_holdout.py` | 8 筆測試資料的離線比對與全部指標 |
| `scripts/fetch_data.py`、`scripts/validate_data.py` | 補齊與核對公司資料及切分 |
| `kaggle/` | 送到 Kaggle 的 Notebook 與設定 |
| `kaggle-retrieved/` | 從 Kaggle 下載的實際輸出，各次執行分開保存；微調權重不進版控，凍結版本的權重雜湊記在 `soulo-work03-v3b-train/work03/outputs/frozen.json`，第一輪的記在 `RETRIEVAL.json` |
| `evaluation/` | 參考判斷、逐筆判定與全部指標 |
| `report/` | 工程版的逐筆審核報告與技術反思（含內部版本代號），以及互動 HTML 與 CSV；給一般讀者的版本是上方的 Google 文件 |
| `evidence/` | prompt 迭代紀錄 `PROMPT-ITERATION.md`、離線檢查輸出、部署測試紀錄 |
| `outputs/experiments/` | 第一輪微調的實際輸出與中止版 prompt，回歸測試與重算會讀取 |
| `deliverable/` | 報告與簡報的稿件與圖 |

## 限制

- 只有 8 筆測試資料，指標只描述這 8 筆。
- 參考判斷與逐筆判定都由 AI 產生，作者的逐筆覆核在看過輸出後進行，屬於確認；12 筆監督答案也由 AI 協作撰寫，不是公司提供的標準答案。
- 凍結前的自動檢查沒有全部通過，凍結依據的是事前定好的停損規則：第三版 prompt 仍未通過就不再修改，凍結失敗項較少的版本。
- 在 Kaggle 重新訓練與生成，不保證得到與本 repo 逐字相同的輸出；離線重算保證的是從同一份輸出得到同樣的指標。
