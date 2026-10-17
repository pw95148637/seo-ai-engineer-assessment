# SEO AI 工程師測驗：四題的程式、證據與重現方式

王正頡的作答。四題的完整報告、簡報與 AI 對話紀錄是 Google 文件，入口是寄給公司的四題總覽；這個 repo 放程式、測試、真實執行的原始輸出與重現步驟。

| 目錄 | 題目 | 內容 |
|---|---|---|
| [`task01-prompt-chain/`](task01-prompt-chain/) | 一、提示詞鏈（20%） | 一個指令跑完的提示詞鏈（Claude Code skill）：各步 prompt、關卡與重試規則、寫作準則、事先查證的來源、文章檢查與盲評工具；A／B／C 結果、最終文章、架構圖、理論依據與迭代紀錄 |
| [`task02-hermes-agent/`](task02-hermes-agent/) | 二、Hermes 自主 SEO 競爭情報 Agent（30%） | 官方 Hermes 固定版本加唯讀研究 plugin、控制器、證據庫、lessons 帳本與研究記憶、判準先寫好的評估（與 Hermes 原生學習的三組對照、延伸到第 10 次的兩兩盲評、研究記憶組與對照組各 10 次）、68 次真實執行的 trace、Demo 影片（`demo/v09/`） |
| [`task03-local-llm-audit/`](task03-local-llm-audit/) | 三、Local LLM SEO 內容審核（25%） | Kaggle Notebook 產生器、審核與格式檢查程式、凍結鎖、8 筆測試與事後分析的原始輸出與重算程式；[Kaggle 評估 Notebook](https://www.kaggle.com/code/pw95148637/soulo-work03-v3-eval) |
| [`task04-multi-agent/`](task04-multi-agent/) | 四、多代理人協作與衝突處理（25%） | asyncio 狀態機、兩個角色的提示詞與分級審核規則（不能協商的 MUST 與可以協商的建議）、程式檢查、Claude CLI adapter、真實協商、Auditor 探測與判準先寫好的改版實驗的原始輸出 |

每題目錄都有自己的 README，寫明架構、結果、限制與重現命令。最快的核對方式是各題的離線測試，不需要 GPU 或任何帳號；第三、四題要先安裝套件（需要網路），第三題另需從公司資料表重建資料：

```bash
cd task02-hermes-agent && python -m unittest discover -s tests -v       # 191 項，只用標準函式庫
cd task03-local-llm-audit                                                # 依該題 README「重現」：安裝套件，再做第 0 到 2 步（重建資料、離線檢查、重算指標）
cd task04-multi-agent && pip install -r requirements.txt && python -m unittest -v   # 91 項
```

Windows 上請先設定 `PYTHONUTF8=1`。

## 這個 repo 不包含的東西

- **測驗題目原文**：題目由公司提供，不公開轉載。
- **公司提供的 20 筆文章 CSV**：第三題用 `scripts/fetch_data.py` 從公司提供的資料表重建，並逐檔核對雜湊。
- **AI 對話紀錄**：內容包含作者的個人背景，以 Google 文件提供給公司，連結在四題總覽。
- **第一題的作者經驗訪談原文**（`inputs/experience.md`）：同上，屬於個人資訊；換成自己的經驗後即可重跑整條鏈。第一題 README 提到的 `第一題指引.md` 內含題目原文，也不收。
- **第一題每次執行的完整紀錄**（`outputs/`、`outputs-v1/`、`outputs-v3/`：各步產出、審核、盲評與當時的系統快照）：審核紀錄逐句引用作者訪談，以 Drive 上的壓縮檔提供給公司，連結在四題總覽。數字與結論都整理在 `task01-prompt-chain/deliverable/`；少數幾句作者經驗的細節在公開版改成中性寫法。
- 模型權重、登入憑證與 Hermes 執行環境：依各題 README 自行安裝與登入。
