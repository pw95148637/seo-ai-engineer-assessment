# 真實GPU里程碑｜2026-10-15

手機驗證已解除，Internet on。預檢已實跑、Quick Save完成，原始含輸出的下載Notebook見preflight-executed.ipynb。

- Python 3.13.15，torch 2.11.0+cu128，cuda_available=True。
- 2張Tesla T4，各15636037632 bytes顯存；模型只使用device0。
- Qwen/Qwen3-8B revision b968826d9c46dd6066d109eabc6255188de91218。
- 4-bit NF4、fp16，模型載入134.433706716秒；allocated 6076724736 bytes。
- transformers4.57.6、accelerate1.14.0、bitsandbytes0.50.2。
- 真實生成：「審核文章時，必須提供具體且可核對的證據，以確保資訊的準確性與可靠性。」

本結果只證明模型載入與中文生成，尚不代表SEO診斷品質或微調成功。pip提示gradio/diffusers相依衝突，預檢不使用兩者且生成通過。

帳號互動GPU上限1：預檢session已停止，正式Notebook執行中。train12答案與合成測試已在Kaggle通過。單卡LoRA已完成2 epochs/6 steps，134.4877秒，train_loss=2.4975620905558267；原始實測Notebook為training-completed.ipynb。訓練函式通過adapter變動斷言後正常返回，一致性實驗正在執行；尚未讀取holdout。第一次雙卡失敗另存training-attempt01-failed.ipynb。

嘗試下載preflight-evidence.zip，瀏覽器回傳路徑後檔案未同步至工作目錄，不將其列為已保存證據；已成功保存的含輸出Notebook為權威證據。
