# 只依train12的提示詞迭代

監督答案、prompt與檢查都只依train12設計；holdout8未讀取、未推論、未作語意檢視。每一輪的gate都是in-sample檢查，只能當凍結的必要條件。

## 第一輪（v1 prompt，已在Kaggle實跑）

LoRA完成6 steps、144個張量變動。train ID14三溫度JSON均有效，分數59/55/55，問題代碼Jaccard皆1，但語意未通過：文章沒有自述實測，三次仍全部標EXPERIENCE_UNVERIFIED；T0.5建議「避免使用『風險』等字眼」，與必要風險揭露衝突；T0.5在房貸文章引用刑法266條卡；否認法拍的重大財務風險仍給中等分數；每個原因貼4至5張來源卡。格式與代碼一致不代表內容正確，這是保留的負結果。

原始輸出：outputs/experiments/initial/（training.json、consistency.json、system_prompt.txt）。

## 第二輪（v2 prompt，已在Kaggle實跑）

v2對策：EXPERIENCE_UNVERIFIED只用於明確自述；不得建議刪除風險揭露；每原因最多2張卡並限定各卡主題；由最嚴重區間判分；最多3項建議。ID13監督分數由25調為35。超參數不變（2 epochs、r8 q/v、1e-4）。

實跑：kernel `pw95148637/soulo-work03-v2-train`，Output取回於`kaggle-retrieved/soulo-work03-v2-train/`（本機以`workflow.py check-freeze`核對31個鎖定檔全部相符，candidate lock sha256 4ca74d97…）。6 steps、196.996秒、loss 2.72→2.53（train_loss 2.533），144個張量變動。自檢JSON首次12/12、三溫度3/3；gate FAIL，8項hard。

已修好的：首輪的FALSE_EXPERIENCE、SOURCE_DUMP、CROSS_DOMAIN_LAW三類全部消失。

仍失敗，逐筆讀`train_selfcheck-raw.jsonl`與`consistency.json`的原始輸出後的判斷：

|現象|實際輸出|原因|
|---|---|---|
|分數只有三檔|12筆：85×6（20、6、15、10、18、11）、55×4（5、14、7、13）、25×2（16、19）；ID14三溫度都是55|v2要求依序輸出Score、Reasons、Actionable Advice，Score是第一個生成的值，模型還沒寫出任何原因就先決定分數，只能落在區間錨點。原因與分數也沒有連動：給85的6筆都列了扣分原因（5筆2個、ID20 1個），85卻是「無重大缺失」區間|
|ID14、ID7給55|ID14自己寫「淡化了抵押物被法拍的法律風險」，ID7寫「淡化了貸款風險與法律後果」，正是prompt中0–29區間的描述，分數卻是55|同上：分數先於理由生成；0–29的條件寫成具體例句，8B 4-bit模型在第一個token無法把例句對應到這兩篇|
|YMYL_RISK過度標記|12筆中11筆有YMYL_RISK，只有ID13沒有；標註無YMYL的9筆中8筆被標。理由多為「未明確說明」「未明確揭示」「未明確警示」（20、16、6、11、18），或主題本身：ID15「文章提及「娛樂城」，屬於高風險內容」|v2定義「淡化財務或法律後果」被讀成「沒寫足風險」；YMYL一詞本身指主題類別；「主題高風險本身不是扣分理由」只寫在評分段落，沒寫進代碼定義|
|乾淨的ID20被扣分|「未明確說明此條文並非所有情況都會立即法拍」，建議「避免使用「必須明白的法律後果」等可能被誤解為保證結果的語句」|v2為ID14寫的補救句「法律程序應保留適用條件，不能說欠款必然立即法拍」加上TW_873卡的但書，被套到一篇正確陳述法條的文章，並把法律後果的提醒當成要刪的字眼|
|ID5漏標EXPERIENCE_UNVERIFIED|代碼YMYL_RISK，explanation卻寫「文章自述親身經歷，但未提供具體證據……屬於未驗證的經驗敘述」|判斷內容正確、代碼錯：v2對EXPERIENCE_UNVERIFIED幾乎只寫限制（何時不得用），YMYL又是預設代碼|
|固定2原因、3建議|11筆2個原因、12筆都是3項建議；監督答案是1個原因、1項建議。第3項常抄prompt規則：「保留風險揭露（或法律警示），不得刪除或掩蓋」出現在ID6、15、5、10，ID19也有「保留風險揭露」；ID10的賭博文章建議「避免聲稱「不看條件保證核貸」」|「最多3項」被當成配額；prompt的範例句被直接抄進不相關的文章|

LoRA效果可忽略：監督答案是緊湊JSON、1原因、1建議、ID14為12分，自檢輸出仍是縮排JSON、2原因、3建議、55分，loss只降到2.53。行為主要由prompt決定。知識卡內容正確，不是主因。

## 第三輪（v3 prompt）

|v2問題|v3做法|凍結前自動檢查（scripts/selfcheck.py、audit_io.py）|
|---|---|---|
|分數先於理由、三檔、ID14／7=55|輸出鍵順序改為Reasons→Score→Actionable Advice；每個原因依序含code、quote、explanation、source_ids、severity，Reasons由重到輕排列，只列一項時須是最嚴重的缺失；Score須落在最高severity區間：critical 0–29、major 30–59、minor 60–84、沒有原因85–100。critical定義為「原文明確作出會讓讀者據以做出錯誤金錢或法律決定的說法，或對排名、獲利、核貸等結果作無依據的絕對承諾」|audit_io.validate拒收Score與最高severity不一致的輸出；錯誤訊息要求Reasons與severity保持不變、只改Score，模型有唯一一次修正，程式不改分。gate以現行契約重驗已存輸出（CONTRACT_INVALID，hard）；SEVERE_SCORE_TOO_HIGH（ID14、7須0–29）維持hard；SCORE_BEFORE_REASONS、SEVERITY_CHANGED_IN_REPAIR（soft）確認「先寫證據再給分」與修正輪沒有靠降級過關|
|YMYL過度標記|YMYL_RISK只標原文主動給出會讓讀者在金錢、法律或健康上受損的說法（保證、否認或淡化具體後果、引導參與可能違法的活動卻不交代風險）；quote須是那句話本身；正確的法律、費用或風險說明不是；只談高風險主題或沒列全部風險也不是|YMYL_OVERFLAG（hard）：明確無YMYL的7筆（20、6、11、13、16、18、19）中超過1筆被標。ID5（為流水倍數背書）、ID10（稱娛樂城純屬娛樂）標YMYL說得通，只記soft YMYL_BORDERLINE；其他筆記soft YMYL_NOT_IN_TARGET|
|ID5代碼錯|EXPERIENCE_UNVERIFIED改為正面定義（第一人稱自述且缺日期、方法或紀錄），並寫明自述經驗的問題不改標YMYL_RISK；無自述不得使用的限制保留|REQUIRED_CODE_MISSED、FALSE_EXPERIENCE（hard）不變|
|建議淡化法律後果|不得建議刪除、省略或淡化法律後果、風險警語或揭露；可以建議改寫得更清楚、補適用條件或來源；刪除不實保證不在此限|RISK_DISCLOSURE_REMOVAL（hard）不變|
|配額與抄寫|只列實際缺失、同一缺失只列一次；每項建議對應一個原因，項數不超過原因數，沒有缺失時1項；不得把指示原句當建議；刪除v2中為ID14、ID7寫的具體例句|ADVICE_PADDING（soft）取代ADVICE_OVER_3；SEVERITY_DIFFERS（soft）|
|STUFFING與SEO_FALSE混用|STUFFING限片段本身出現的重複；主張重複關鍵字有效屬SEO_FALSE|REQUIRED_CODE_MISSED（ID13須SEO_FALSE）不變|
|卡片誤用（ID7用TW_873／874、ID5用F_APR）|各卡主題寫得更窄：TW_873限抵押物拍賣、TW_874限清償順位、F_APR限借貸成本與利率比較、M_PIP限住宅市場統計|CROSS_DOMAIN_LAW（hard）、OFF_TOPIC_SOURCE（soft）不變|

監督答案只加severity並改鍵順序，分數、代碼、引句、說明與建議都沒有改（scripts/prepare_targets.py重產並比對）。12筆的severity：critical 14、7、19；major 15、16、13；minor 6、5、10、18、11；ID20無原因。全部與三級定義及原分數相符。監督答案都只有0或1個原因，與prompt容許最多3項不一致；改成多原因等於新寫標註，沒有做，改以「由重到輕、只列一項時須最嚴重」補足。

prompt與train12的文字重疊只有一般詞（保證獲利、清償順位、內容品質、法律後果、Google、SEO），沒有train文章的句子或ID。

v2真實輸出交給v3 gate（`python scripts/regate.py kaggle-retrieved/soulo-work03-v2-train/work03 --out evidence/v2-outputs-on-v3-gate.json`）：FAIL，hard計CONTRACT_INVALID 15（沒有severity）、SEVERE_SCORE_TOO_HIGH 5、YMYL_OVERFLAG 1（明確無YMYL的7筆中6筆被標：20、6、16、19、18、11）、RISK_DISCLOSURE_REMOVAL、CLEAN_ITEM_FLAGGED、REQUIRED_CODE_MISSED各1；15筆輸出都記SCORE_BEFORE_REASONS。把v2 ID14的原因標為critical而保留其55分，validate拒收並指出須在0–29（test_workflow.py固定此測試）。

訓練：epochs 2→3（約9 steps），learning rate 1e-4與max_length 3072不變。v2的adapter連輸出格式都沒改變；多3步有助模型採用新的鍵順序與severity，但預期行為改善主要仍來自prompt。提高learning rate會讓in-sample gate靠背誦通過，又沒有train內部切分可驗證更強設定。為了不把prompt的效果算到微調頭上，train kernel另以同一prompt、不載入adapter跑一次train12（workflow.py baseline，輸出train_selfcheck_base.jsonl與baseline_comparison.json，列入鎖）。v3 prompt為1870至1895 tokens，最長訓練序列2009 tokens（scripts/verify_round1_tokens.py，以固定revision的tokenizer計算），低於3072；生成時1895+768低於context上限4096。

v3定稿前另由一個未參與設計的agent審閱prompt與gate（只讀train12、監督答案、v2輸出與程式）。採用：修正輪只改Score、YMYL的quote須是有害那句、critical定義改寫、Reasons由重到輕、STUFFING與SEO_FALSE分界、YMYL_OVERFLAG改為只計明確無YMYL的7筆、無adapter對照、SCORE_BEFORE_REASONS旗標、CRITICAL集合改名REQUIRED_CODES。

這仍是prompt、監督格式與訓練步數一起調整，不是固定adapter的純prompt因果實驗；無adapter對照只能界定LoRA在train12上的增量。v3是否改正，只能看v3實跑。不要拿in-sample gate反覆調prompt。

## Prompt版本

|版本|位置|sha256|狀態|
|---|---|---|---|
|v1|outputs/experiments/initial/system_prompt.txt|731f70ac…|第一輪實跑|
|v2中止版|outputs/experiments/v2-interrupted/system_prompt.txt|f916f489…|舊Notebook版本3在1/6步取消|
|v2|kaggle-retrieved/soulo-work03-v2-train/work03/system_prompt.txt|ce9490a5…|v2-train實跑，gate FAIL|
|v3|system_prompt.txt|9b5734ef…|v3-train訓練第0步OOM；v3b-train實跑，gate FAIL，依停損規則凍結|

## v3-train 執行失敗與 v3b（2026/10/16）

`soulo-work03-v3-train` v1 在訓練第0步 CUDA OOM（T4 14.56 GiB；已配置12.48 GiB，再要求1.11 GiB）。原因：v3 prompt 較長（最長序列2009 tokens），全序列 fp32 logits（約2009×151936×4 bytes≈1.2 GiB）及其梯度超出餘量。Output 與 log 保存在 `kaggle-retrieved/soulo-work03-v3-train/`，只有 preflight 產物，沒有 adapter 或模型評估結果。

v3b 只改記憶體，不改 prompt、targets、知識卡與超參數：
- `AnswerOnlyTrainer`：prompt token 本來就被 label 遮罩，改為只從第一個答案位置起計算 logits（`logits_to_keep`），loss 以 `num_items_in_batch` 正規化，數學上與原本只計答案 token 的 loss 相同。
- 子程序設 `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` 減少碎片。
- 新 slug `soulo-work03-v3b-train`；eval 的 kernel_sources 改指 v3b-train。

## v3b-train實跑結果

kernel `pw95148637/soulo-work03-v3b-train`，Output取回於`kaggle-retrieved/soulo-work03-v3b-train/`（本機check-freeze 34檔相符，lock sha256 8ab9b7ae…，2026-10-16T04:13:27Z）。9 steps、360.5秒、train_loss 2.30、144個張量變動，全程約24.5分。自檢契約有效首次與最終都是11/12：ID7首次缺severity，修正輪補上severity（critical）卻保留45分，仍不在0–29。三溫度3/3有效，ID14三次都是0分critical，代碼Jaccard皆1。鎖內gate FAIL，6項hard。

改善的：分數在理由之後生成，SCORE_BEFORE_REASONS消失；ID14 0分、ID19 25分、ID16 35分；虛構經驗、來源堆疊、跨領域法條沒有再出現。

仍失敗的：
- 等級膨脹：ID5、10、15判critical給0分（標註62、74、50）；ID20、6、11、18判major給45–50（標註95、70、84、78）。
- YMYL過度標記：明確無YMYL的7筆中5筆（20、6、16、18、11），含乾淨的ID20。
- ID5又把自述經驗標成YMYL_RISK，漏EXPERIENCE_UNVERIFIED。
- ID7修正輪沒照指示只改分數。

同prompt無adapter（baseline_comparison.json）：首次有效12/12，ID5有標EXPERIENCE_UNVERIFIED，ID7給25分critical；但ID7引用TW_266（CROSS_DOMAIN_LAW），ID20建議把「必須明白的法律後果」改成「有助於」的語氣（弱化警語）。在train12上LoRA沒有可見增量，ID5、ID7反而較差；行為仍主要由prompt決定。以上都是in-sample。

## 看到v3b結果後才修的checker誤判（RISK_DISCLOSURE_REMOVAL）

鎖內兩項RISK_DISCLOSURE_REMOVAL都是ID14的建議：自檢「建議修改原文，避免否認或淡化法律風險，例如增加說明抵押物可能被拍賣的條件與程序，並提醒讀者應諮詢專業法律意見。」與T0.5「……避免否認或淡化法律後果，並補充抵押物拍賣的法律風險……」。兩句都在要求增加揭露，判成刪除是checker錯誤。

原因：removes_risk只看淡化、刪除等動詞緊鄰的前文是否為避免、不要等禁止詞。「避免否認或淡化」的禁止詞與「淡化」之間隔著並列的「否認或」，於是被當成建議淡化。「避免淡化風險」原本就在應放行清單，這是同一規則漏了並列，不是放寬。反方向同樣有此漏洞：「風險警示不得省略或刪除」原本也會被擋。

修正（scripts/selfcheck.py的PROHIBIT）：禁止詞後可接若干個「否認、隱瞞、掩蓋、誇大、渲染、淡化、弱化、省略、刪除、刪去、移除、拿掉、忽略、迴避」之一＋「或／或是／或者／、／和／及／與」，再接刪除類動詞，整串都在禁止範圍內；其他詞不算並列（「避免冗長並淡化」「不要堆砌、移除」仍擋），「分別、個別、特別」等詞裡的「別」不算禁止詞。沒有採用「同句另有補充揭露才放行」的條件，因為既有規則對「避免淡化風險」本來就不要求補充。

第一版修正允許任意兩字並列，由未參與設計的agent審閱時找出7句真正的刪除建議會被放行（如「建議將標題與內文分別精簡、刪除風險警示段落」「避免重複、省略法律警示」），另有一句修正前就漏擋的「建議分別刪除風險警示與免責聲明」；在讀holdout前改為上述封閉動詞集並排除「別」的複合詞。

驗證：原有18句應擋、17句應放行全部維持。新增應放行5句（兩句v3b實際建議、「風險警示不得省略或刪除」「避免誇大或淡化風險」「避免否認、淡化法律風險」），新增應擋13句（「建議否認或淡化法拍風險，以免嚇跑讀者」「不要否認風險，但可以淡化法律後果」「避免冗長並淡化風險說明」「淡化或省略法律後果以提升轉換」「參考別人的做法和刪除風險警示」及審閱找出的8句）。v1、v2、v3b（含無adapter）全部96句不重複的實際建議分別交給修正前後的checker，判定改變的只有上述兩句；仍被擋的3句（v1 T0.5「避免使用『風險』等字眼」、v2與v3b無adapter的ID20「避免使用『必須明白的法律後果』……」）都是真正的刪除或弱化。把修正撤回時test_workflow.py會失敗。修正不影響凍結選擇：修正前v3b 6項也少於v2 9項。

## 凍結選擇（依事前停損規則）

v3仍FAIL，依HANDOFF既定規則不再改prompt、監督答案、知識卡或超參數，用同一份修正後gate（scripts/regate.py）重判兩版，凍結hard較少者；v2的CONTRACT_INVALID（v2格式沒有severity）不計。

|項目|v2|v3b（adapter）|v3b無adapter（參考，不是候選）|
|---|---|---|---|
|hard（不計CONTRACT_INVALID）|9：SEVERE_SCORE_TOO_HIGH 5（ID14、7與三溫度）、YMYL_OVERFLAG、RISK_DISCLOSURE_REMOVAL（ID20）、CLEAN_ITEM_FLAGGED、REQUIRED_CODE_MISSED|4：CLEAN_ITEM_FLAGGED、REQUIRED_CODE_MISSED、INVALID_JSON、YMYL_OVERFLAG|4：RISK_DISCLOSURE_REMOVAL、CLEAN_ITEM_FLAGGED、CROSS_DOMAIN_LAW、YMYL_OVERFLAG|
|Score與標註的平均絕對誤差|16.6（12筆）|31.9（11筆，ID7無效；以最後一次45分計入為31.8）|25.5（12筆）|
|ID14／ID7（標註12／15）|55／55|0／無效|0／25|
|ID14三溫度|55/55/55|0/0/0|－|
|標YMYL_RISK|11/12；明確無YMYL的7筆中6|9/12；7筆中5|10/12；7筆中5|

凍結v3b。平均絕對誤差反而v2最低：v2分數集中在25/55/85，對中段標註誤差小，卻正好在最關鍵的ID14、7給55；v3b把嚴重案例判對，但把YMYL一律當critical，造成等級膨脹。誤差只作報告比較，不改事前選擇規則。

逐筆（分數、最高severity、代碼；EXP=EXPERIENCE_UNVERIFIED、UNSUP=UNSUPPORTED_CLAIM）：

|ID|標註|v2|v3b|v3b無adapter|
|---|---|---|---|---|
|20|95 無|85 YMYL|50 major YMYL,UNSUP|50 major YMYL,UNSUP|
|6|70 minor UNSUP|85 YMYL,UNSUP|45 major YMYL,UNSUP|50 major YMYL,UNSUP|
|15|50 major YMYL|85 YMYL,UNSUP|0 critical YMYL|0 critical YMYL|
|5|62 minor EXP|55 YMYL,UNSUP|0 critical YMYL|50 major YMYL,EXP|
|10|74 minor UNSUP|85 YMYL,UNSUP|0 critical YMYL|0 critical YMYL|
|14|12 critical YMYL|55 YMYL,UNSUP|0 critical YMYL|0 critical YMYL|
|16|32 major STUFFING|25 STUFFING,YMYL|35 major STUFFING,YMYL|35 major STUFFING,YMYL|
|19|28 critical SEO_FALSE|25 SEO_FALSE,YMYL|25 critical SEO_FALSE|25 critical SEO_FALSE|
|7|15 critical YMYL|55 YMYL,UNSUP|無效|25 critical YMYL,UNSUP|
|13|35 major SEO_FALSE|55 SEO_FALSE,STUFFING|25 critical SEO_FALSE|25 critical SEO_FALSE|
|18|78 minor UNSUP|85 YMYL,UNSUP|50 major YMYL,UNSUP|45 major YMYL,UNSUP|
|11|84 minor UNSUP|85 YMYL,UNSUP|45 major YMYL,UNSUP|50 major YMYL,UNSUP|

證據：evidence/regate-v2.json、regate-v3b.json、regate-v3b-base.json（取代修正前的v2-outputs-on-v3-gate.json）；命令與輸出見evidence/offline-checks-v3b-freeze.txt。

## 凍結後的程式變更與eval設計

- 鎖用v3b Kaggle輸出的frozen.json，沒有對下載的bundle重跑gate或freeze。鎖內gate FAIL，eval Notebook的「本次凍結決定」寫明「train gate未通過即凍結，依事前停損規則」。
- 凍結後只改三個量測與eval檔：selfcheck.py（上述修正）、workflow.py（無adapter對照、比較報表、宣告式凍結核對）、test_workflow.py（測試）。build_notebook.py以`--accept-code-change`記錄理由，並把每檔凍結前後sha256嵌入eval Notebook；Kaggle上check-freeze依此逐檔核對，其餘31檔（prompt、知識卡、設定、監督答案、audit_io契約、train輸出、adapter）仍須與鎖相同。workflow.py採預設拒絕：每個頂層敘述都以AST與凍結版比對，只豁免報表（report、report_html、audit_records）、check_freeze、eval串接（evaluate、holdout_run、evaluate_base）與CLI選項；串接另以記錄式假模型演練，確認先跑adapter再跑base、generate只收(tok, model, msg)。第一版只比對10個生成函式，審閱指出模組層包裝或串接內改溫度會漏掉，已改。
- eval先跑凍結adapter（holdout.jsonl），再以同prompt、同解碼與修正規則跑無adapter（holdout_base.jsonl），各在獨立process；報告另出audit_report_base.csv、holdout_comparison.csv、HTML對照段，metrics.json含base。base失敗或不完整不影響adapter報告。三溫度不在eval重跑。
