# 交還人類清單：run 2f7174e7（2030.tw）

研究 `2f7174e7c3f04f35bd74b4c1d2c29af4`，2026-10-17 11:16 UTC 開始，模式 memory，學習開啟，結果 research_complete，報告第一次提交就被接受。
開跑前檢查：通過，已登入，未限流，工具 6 個，與預期相同。
用量：HTTP 請求 5/30（模型直接讀取 1、站外頁 4）、控制器重驗 9/10（另計額度）、工具呼叫 17/40、搜尋 5/5、站外頁 2/4、時間上限 900 秒。

需要決定 1 項、視需要處理 7 項、紀錄 4 項；每一項都寫了不處理時會怎樣。經驗變動在列出時已經生效，人能做的是否決；行動建議、預算、允許網域與資料授權要人決定後才會發生。

| 類別 | 項數 | 需要決定 |
|---|---:|---:|
| 開跑前檢查 | 0 | 0 |
| 經驗變動 | 3 | 0 |
| 這次使用的經驗 | 1 | 0 |
| 研究受限之處 | 2 | 0 |
| 報告被退回 | 0 | 0 |
| 未知項 | 1 | 0 |
| 行動建議 | 5 | 1 |

處理方式裡的 feedback.py 指令會改寫 `runs/v09-ledger-copy` 的帳本：`veto` 永久停用一條經驗，`label` 新增一條給之後研究套用的審查標準，`ok` 記錄整份報告已審查。理由最多 200 字，不能含網址或斜線。
行動建議沒有引用欄位；依據的事實要回到報告的主張與 evidence 核對。

## 需要決定

### H1｜行動建議｜第 1 項（需要法務或決策者）：P0：先確認我方目標地區的法律與內容合規邊界，盤點自己的網站、索引及查詢基線；本階段不製作未核實的註…

- **要決定**：交法務或決策者確認後，再決定是否執行。
- **為什麼交給人**：Agent 沒有修改網站或對外發布的工具，建議只能由人執行。Agent 把它排為 P0（最優先），優先順序牽涉我方資源，要人核可。內容涉及法規或合規（觸發詞：法律、合規），要法務或決策者確認。
- **依據**：
  - action:1：P0：先確認我方目標地區的法律與內容合規邊界，盤點自己的網站、索引及查詢基線；本階段不製作未核實的註冊推薦或優惠承諾。
  - 理由：我方網址與合規條件未知；先設可發布範圍及成效基線，避免把競爭者做法視為安全或有效。成本低至中，屬必要前置，不是已確認的SEO增益。
- **不處理時**：不會執行。
- **處理方式**：
  - 採納：由人排入工作並執行
  - 不採納並標註理由（成為之後研究的審查標準）：`python scripts/feedback.py --root runs/v09-ledger-copy label --run 2f7174e7c3f04f35bd74b4c1d2c29af4 --target action:1 --label scope_error --reason "<理由>" --reviewer "<審查者>"`

## 視需要處理

### H2｜經驗變動｜研究記憶新增 9 條發現

- **要決定**：抽查新發現；不實或說太滿的用否決停用。
- **為什麼交給人**：發現來自 Agent 自己的報告，控制器只確認每個引用都是雜湊有效的站內頁，不確認內容正確。下一次研究開始時控制器會重抓頁面，仍成立才交給模型，重驗通過後轉為 active，不經人核准。
- **依據**：
  - finding b109a6146a0c：首頁公開定位為MLB/NBA、世界盃與運彩，導覽有線上娛樂城推薦；/wordcup/列出品牌、評價、優惠、玩法、安全出金等分類，以及3A、娛樂城核心頁。2502篇及53頁是站方顯示…（狀態 candidate）
  - finding a3d8e88f47f1：娛樂城、3A核心頁及本輪新抽查富有頁均HTTP200，title/H1帶各自關鍵字、自指canonical、robots index/follow，並有Article及五題FAQP…（狀態 candidate）
  - finding ee93c1bbaa0c：娛樂城、3A及新抽查富有頁沿用平台特色、遊戲、出金、註冊、優惠、客服六節與五題FAQ框架；58888頁改為手機、體育、百家樂三節與三題FAQ。因此支持樣本模板化，不支持全站逐字相同…（狀態 candidate）
  - finding 316871b5e86c：泛詞娛樂城頁正文沒有具名平台比較表；3A老虎機送58888頁將整串長尾當平台名稱，未交代58888資格、活動期限、流水、提領上限或對應條款來源。3A頁自稱實玩數月及半小時至一小時出…（狀態 candidate）
  - finding 1ed5681a6767：反證：3A缺點頁實際談手機卡頓、APP更新、KYC等待一至兩天、高流水及客服轉交等待；泛詞及富有頁也提醒優惠條款或提領限制。不能稱完全無實用資訊或風險揭露，這些仍只是站方敘述，未核…（狀態 candidate）
  - finding 51e1bc0c7614：3A、泛詞與富有頁結構化資料均混入相同MLB NewsArticle及指向MLB URL的WebPage；3A正文顯示9月24日更新，Article dateModified為9月…（狀態 candidate）
  - finding 1cffbeb2f9ca：3A、泛詞與富有頁主要註冊CTA指向https://don0911.3a1788.bet/?st=wg2030，回傳rel nofollow、圖片alt為WG娛樂城；58888頁同…（狀態 candidate）
  - finding 5ffd4fb936e4：樣本支持體育入口連接泛詞、品牌、問題及優惠長尾，以分類、相關推薦內鏈及重複CTA集中導流的策略推論。未證明這套安排有效；我方更值得評估意圖完成度及資料可查證性，而非模仿頁量。（狀態 candidate）
  - finding c03d0a6e9141：當前/article/responsible-ai-008-audrey-tang/為HTTP200世足資格賽內容，canonical仍為該科技語意路徑；只支持當前路徑與內容語意不…（狀態 candidate）
  - 取代了上一份報告的 9 條發現
- **不處理時**：下一次研究會看到仍成立的發現，並在上面往下挖。
- **處理方式**：
  - 接受：不需操作
  - 否決其中一條（把 <lesson> 換成上面的 finding 編號）：`python scripts/feedback.py --root runs/v09-ledger-copy veto --lesson <lesson> --reason "<理由>" --reviewer "<審查者>"`

### H3｜研究受限之處｜預算用完：搜尋 5/5

- **要決定**：決定下次是否放寬這項預算，或接受目前的覆蓋範圍。
- **為什麼交給人**：預算是操作者為時間、請求與成本設的上限；Agent 只能在上限內取捨，不能自己加。
- **依據**：
  - 用量 5/5（上限固定在 `Research.search`）
- **不處理時**：下次研究用同樣的預算。
- **處理方式**：
  - 維持
  - 放寬：改 `src/research_core.py` 的 `Limits`（搜尋上限在 `Research.search`）。這是程式變更，正式評估前要先登錄新計畫

### H4｜未知項｜未知項 7 項，需要的資料分成 5 類

- **要決定**：逐類決定要授權什麼資料，或接受為未知。
- **為什麼交給人**：補齊未知項通常需要帳號、付費資料、我方網站資料或法務判斷，都要人授權；各類的原因寫在依據的分類標題。
- **依據**：
  - 【完整反向連結】公開索引看不到完整反向連結；新資料源有費用或處理成本，要人授權。
  - claim:12：站外未知：未確認有效入站來源或正向品牌提及；完整backlinks、錨文字與rel分布、付費或PBN關係、歷史外鏈及其排名貢獻皆未知。（也涉及：競爭者的排名、流量與轉換）
  - unknowns[1]：五次公開搜尋與兩個站外負對照仍未找到經確認的競爭者正向站外提及或入站來源，不是完整backlink調查。
  - 這次 research_offpage 讀了 2 頁，連到目標站 0 頁、提及目標網域 0 頁
  - 【競爭者的排名、流量與轉換】這些是競爭者的私有資料，Agent 沒有合法取得途徑；第三方工具要付費，而且只是估算。
  - claim:13：競爭者實際流量、排名成效、CTR、轉換、完整索引、CWV與全站模板重複比例未知；平台合法性、安全性、優惠及出金資訊、CTA最終落地亦未核實。我方網站、合規條件、資源及基線未提供，行動僅供我方條件式評估，未修改任何網站。（也涉及：我方網站資料、法律、金流與契約、需要額外量測）
  - unknowns[3]：競爭者流量、排名成效、CTR、轉換、完整索引、CWV及全站模板重複比例未知。（也涉及：需要額外量測）
  - 【我方網站資料】我方資料要我方帳號授權，Agent 沒有登入能力。
  - unknowns[5]：我方網站網址、合規條件、預算、人力與成效基線未知；成本級別是相對規劃，非實際報價。（也涉及：法律、金流與契約）
  - 【法律、金流與契約】牌照、法律實體、契約與出入金說法的查證涉及法規與實際金流，Agent 不能也不應代為查證。
  - unknowns[4]：平台合法性、安全性、出金與優惠真實有效性、CTA最終落地及合作契約未知。
  - 【其他】沒有對應的現成資料源，要人判斷價值與成本。
  - unknowns[2]：科技語意網址的歷史內容、所有權變化及舊連結承接仍未驗證。
  - 分類依關鍵詞判斷，可能分錯；原文在報告的 unknowns 與 kind=unknown 的主張
- **不處理時**：下次研究仍是未知。
- **處理方式**：
  - 完整反向連結：接受只用公開索引，或授權付費反向連結索引、Common Crawl 的網站連結圖。
  - 競爭者的排名、流量與轉換：接受為未知，或授權付費的第三方估算工具。
  - 我方網站資料：提供我方網域、Search Console 與內容清單，或維持只研究競爭者。
  - 法律、金流與契約：交給法務判斷是否需要查證、怎麼查。
  - 其他：決定是否值得追查、用什麼資料。
  - 接受全部為未知

### H5｜行動建議｜第 3 項（需要法務或決策者）：P1：僅在可取得可公開引用的正式條款時製作58888等優惠頁，逐項說明資格、有效期、流水計算、適用遊…

- **要決定**：交法務或決策者確認後，再決定是否執行。
- **為什麼交給人**：Agent 沒有修改網站或對外發布的工具，建議只能由人執行。內容涉及法規或合規（觸發詞：法律），要法務或決策者確認。
- **依據**：
  - action:3：P1：僅在可取得可公開引用的正式條款時製作58888等優惠頁，逐項說明資格、有效期、流水計算、適用遊戲與提領限制；無法核實則明示未確認或不發布獨立頁。
  - 理由：競爭者58888樣本沒有回答優惠核心條件。精準頁的潛在差異化高，但資料取得成本及法律限制需先估，不用頁數當品質。
- **不處理時**：不會執行。
- **處理方式**：
  - 採納：由人排入工作並執行
  - 不採納並標註理由（成為之後研究的審查標準）：`python scripts/feedback.py --root runs/v09-ledger-copy label --run 2f7174e7c3f04f35bd74b4c1d2c29af4 --target action:3 --label scope_error --reason "<理由>" --reviewer "<審查者>"`

### H6｜行動建議｜第 5 項（需要法務或決策者）：P2：我方以可引用的消費風險資料表、條款異動紀錄或原創研究建立站外內容資產，再向主題相關且願意獨立審…

- **要決定**：交法務或決策者確認後，再決定是否執行。
- **為什麼交給人**：Agent 沒有修改網站或對外發布的工具，建議只能由人執行。內容涉及法規或合規（觸發詞：合規），要法務或決策者確認。
- **依據**：
  - action:5：P2：我方以可引用的消費風險資料表、條款異動紀錄或原創研究建立站外內容資產，再向主題相關且願意獨立審核的媒體及社群進行合規接洽；記錄實際來源、錨文字、rel及引用上下文，不買精準錨文字或PBN。
  - 理由：本輪未證實競爭者外鏈打法，不能照抄推測；先小規模驗證編輯引用價值。內容成本中至高、拓展成本中，與是否取得高品質相關引用分開評估。
- **不處理時**：不會執行。
- **處理方式**：
  - 採納：由人排入工作並執行
  - 不採納並標註理由（成為之後研究的審查標準）：`python scripts/feedback.py --root runs/v09-ledger-copy label --run 2f7174e7c3f04f35bd74b4c1d2c29af4 --target action:5 --label scope_error --reason "<理由>" --reviewer "<審查者>"`

### H7｜行動建議｜第 6 項（需要法務或決策者）：P2：我方試點發布後用自己的Search Console與分析工具追蹤查詢對頁面、索引、曝光、點擊及…

- **要決定**：交法務或決策者確認後，再決定是否執行。
- **為什麼交給人**：Agent 沒有修改網站或對外發布的工具，建議只能由人執行。內容涉及法規或合規（觸發詞：合規），要法務或決策者確認。
- **依據**：
  - action:6：P2：我方試點發布後用自己的Search Console與分析工具追蹤查詢對頁面、索引、曝光、點擊及合規轉換；保留修改紀錄，設定可比較的觀察窗再決定擴寫或合併。
  - 理由：只能用我方授權資料衡量自身結果；未提供基線前不設定虛構流量目標，不把競爭者公開結構當成效果證明。
- **不處理時**：不會執行。
- **處理方式**：
  - 採納：由人排入工作並執行
  - 不採納並標註理由（成為之後研究的審查標準）：`python scripts/feedback.py --root runs/v09-ledger-copy label --run 2f7174e7c3f04f35bd74b4c1d2c29af4 --target action:6 --label scope_error --reason "<理由>" --reviewer "<審查者>"`

### H8｜行動建議｜其他行動建議 2 項

- **要決定**：逐項決定是否採納並排入工作。
- **為什麼交給人**：Agent 沒有修改網站或對外發布的工具，建議只能由人執行；是否值得做是我方的資源取捨。
- **依據**：
  - action:2：P1：我方先做娛樂城泛詞與3A品牌兩個不同意圖的內容試點；泛詞提供有來源、明示未知欄位的比較方法及風險判讀，3A頁集中身份核對、條款來源、出金限制、爭議與查核日期。
  - 　理由：競爭者泛詞缺具名比較，品牌頁實玩數字缺可追溯紀錄。以來源覆蓋率、問題完成度及人工驗收判品質；研究成本中至高，優先於大量鋪頁，無排名保證。
  - action:4：P1：稽核我方模板的canonical、可索引設定、正文與JSON-LD實體及日期一致性；設一個意圖一個主頁，相關文章用問題導向內鏈，僅標記正文確有內容的schema。
  - 　理由：競爭者樣本可見MLB與娛樂城結構化語意混雜；這是我方可預防的品質問題，不代表我方也有同樣錯誤或修正必然提升排名。成本低至中。
- **不處理時**：不會執行。
- **處理方式**：
  - 採納：由人排入工作並執行
  - 不採納並標註理由（N 換成項次）：`python scripts/feedback.py --root runs/v09-ledger-copy label --run 2f7174e7c3f04f35bd74b4c1d2c29af4 --target action:N --label scope_error --reason "<理由>" --reviewer "<審查者>"`

## 紀錄

### H9｜經驗變動｜已撤銷的經驗再次記錄：failure|research_search|plain

- **要決定**：不需要決定；列出供核對。
- **為什麼交給人**：撤銷後的失敗與反例照常計數，狀態不變。
- **依據**：
  - lesson 91597b6a9458（failure_pattern）：failure|research_search|plain
  - 控制器紀錄的理由：counterexample: 3 successful call(s) with feature plain in run 2f7174e7c3f04f35bd74b4c1d2c29af4
  - 失敗：搜尋「"2030玩運彩" -site:2030.tw」→ no_results（HTTP 503：DuckDuckGo search failed: DDGSException: No results found.，evidence 8e77f66fa5f1406c8f8765a19556f058）
  - 失敗：搜尋「"2030.tw/article"」→ no_results（HTTP 503：DuckDuckGo search failed: DDGSException: No results found.，evidence dd515cc7807f44389d988717dfc21b7f）
  - 反例：搜尋「"2030.tw" -site:2030.tw」→ ok（HTTP 200，evidence 53d51e0ba5084b619a040196cf5ba622）
  - 反例：搜尋「"https://2030.tw" -site:2030.tw -site:yahoo.com」→ ok（HTTP 200，evidence 5250872cbb4348c79ac6d6e315ee63d6）
  - 反例：搜尋「"2030.tw" 科技 -site:2030.tw -股票 -股市 -Froch -yahoo」→ ok（HTTP 200，evidence c31d014826cd4c39983dfec5d4f3bdab）
  - 帳本目前狀態：revoked
- **不處理時**：維持撤銷。
- **處理方式**：
  - 不處理
  - 否決（永久停用，之後不會自動恢復）：`python scripts/feedback.py --root runs/v09-ledger-copy veto --lesson 91597b6a9458 --reason "<理由>" --reviewer "<審查者>"`

### H10｜經驗變動｜研究記憶的重驗

- **要決定**：不需要決定；列出供核對。
- **為什麼交給人**：重驗只看頁面是否還在、內容是否大致不變，不判斷發現本身是否正確。
- **依據**：
  - 控制器在研究開始時重抓 8 頁（控制器請求 9 次）：9 條發現的頁面仍成立、0 條待重讀、0 條撤銷；另列 12 個未讀站內頁、7 個上次的未知項
- **不處理時**：照常；撤銷的發現不再出現。
- **處理方式**：
  - 不處理

### H11｜這次使用的經驗｜這次研究使用的經驗（3 條）

- **要決定**：確認這些經驗仍然可信，不可信的就否決。
- **為什麼交給人**：經驗會改變 Agent 先讀什麼、避開什麼、怎麼寫主張。發現路徑每次使用前由控制器重抓確認；人工審查經驗沒有效期。
- **依據**：
  - lesson 08856145cf1e（discovery_path）discovery|2030.tw|3a娛樂城：適用 this_host，開始時重抓 ok（evidence 05426b25670647919e70845418e3e0fe），效期 2026-10-24 09:10 UTC
  - lesson d94869ffa2dc（discovery_path）discovery|2030.tw|娛樂城：適用 this_host，開始時重抓 ok（evidence e9b41939d6e149d4a2d220ce1c5b33c6），效期 2026-10-24 09:10 UTC
  - lesson 38b7cba20063（human_feedback）feedback|8cad8d54a03c4f94a716e7653b5b3112|claim:8|unsupported|1：適用 general，效期 無，人工審查，帳本記錄的審查者為 總控Claude（使用者授權代審）；沒有效期，只能由人否決
  - event 594（lessons_presented）
- **不處理時**：之後的研究照常使用。
- **處理方式**：
  - 不處理
  - 否決 08856145cf1e：`python scripts/feedback.py --root runs/v09-ledger-copy veto --lesson 08856145cf1e --reason "<理由>" --reviewer "<審查者>"`
  - 否決 d94869ffa2dc：`python scripts/feedback.py --root runs/v09-ledger-copy veto --lesson d94869ffa2dc --reason "<理由>" --reviewer "<審查者>"`
  - 否決 38b7cba20063：`python scripts/feedback.py --root runs/v09-ledger-copy veto --lesson 38b7cba20063 --reason "<理由>" --reviewer "<審查者>"`

### H12｜研究受限之處｜搜尋沒有結果或失敗：2/5 次

- **要決定**：接受免金鑰搜尋的覆蓋限制，或授權付費搜尋、反向連結資料源。
- **為什麼交給人**：Agent 只能用現有的免金鑰索引；新的資料源可能有費用與使用條款，要人授權。
- **依據**：
  - event 628：搜尋「"2030玩運彩" -site:2030.tw」→ no_results（HTTP 503：DuckDuckGo search failed: DDGSException: No results found.，evidence 8e77f66fa5f1406c8f8765a19556f058）
  - event 634：搜尋「"2030.tw/article"」→ no_results（HTTP 503：DuckDuckGo search failed: DDGSException: No results found.，evidence dd515cc7807f44389d988717dfc21b7f）
- **不處理時**：下次仍用同一個免金鑰索引。
- **處理方式**：
  - 接受
  - 授權新資料源：改控制器程式，正式評估前要先登錄新計畫

## 固定由人決定的事

下列事項不論清單內容都由人決定。它們由「只給唯讀工具」與控制器規則實現，不靠模型自律。

| 事項 | 怎麼做到 | 程式位置 |
|---|---|---|
| 登入與用量額度 | 使用者自己在瀏覽器完成裝置登入。runner 開跑前檢查登入、限流與工具清單，未就緒就以 exit 2 停止、不呼叫模型。Agent 沒有登入或查用量的工具。 | scripts/login_hermes.sh、scripts/run_research.py、src/runner_support.py 的 readiness |
| 付費 | Agent 沒有付費 API 金鑰或付費工具；搜尋用 Hermes 內建的免金鑰 DDGS。加入付費資料源要改控制器程式，由人授權費用。 | plugin/__init__.py、src/research_core.py |
| 對外發布或修改網站 | 平常的研究只有六個唯讀研究工具：HTTP 只送不帶內容的 GET，research_finish 只把報告寫進研究目錄；沒有 shell、檔案或瀏覽器工具。比較 Hermes 原生學習時另加 Hermes 的 memory 與 skills 工具，只寫 Hermes 自己的儲存。實際工具清單與預期不同時 runner 拒絕開跑。 | src/research_core.py 的 HTTP、src/runner_support.py 的 HERMES_MODES、scripts/run_research.py 的 build_agent |
| 否決經驗與人工審查 | lesson 只由控制器量測與人工審查產生，模型沒有寫入帳本的工具。人工標註與否決用 feedback.py，要寫審查者與理由；否決後不再自動恢復。 | src/lessons.py 的 Ledger.add_feedback、Ledger.veto，scripts/feedback.py |
| 研究對象與預算 | 操作者開跑時指定網站、關鍵字與 research_fetch 的允許網域；research_offpage 只讀這次搜尋列出的站外網址，每次最多 4 頁。預算寫在控制器，每次工具呼叫都檢查。Agent 沒有修改它們的工具。 | scripts/run_research.py 的 --target、--keyword、--allow-host，src/research_core.py 的 Limits 與 Research.search |

來源：`evaluation/v09/runs/ledger-series`（SHA-256 `b3da656e8220318fa9888765016f39a2e43ccdd16f6ecaabe348c372582384de`），由 `scripts/handoff_queue.py` 唯讀產生。
