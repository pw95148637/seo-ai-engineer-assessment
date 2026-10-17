# 第一次訓練實測失敗與修正

原始紀錄：training-attempt01-failed.ipynb，保存後才修改執行方式。

8B預檢成功，但Trainer看到兩張GPU後採用torch.nn.parallel.data_parallel；訓練第0/4步於bitsandbytes CUDA fallback出現CUBLAS_STATUS_NOT_SUPPORTED，尚無adapter或訓練成功證據。

修正只涉及硬體執行：子程序指定CUDA_VISIBLE_DEVICES=0，維持單卡4-bit方案。資料、監督答案、prompt與訓練超參數未依holdout調整。修正後預期為batch1/累積4，12筆×2 epochs共6 optimizer steps；成功與否仍以實際training.json及權重變化為準。

不能只由此trace斷言全部cuBLAS錯誤均來自DataParallel；單卡重跑是針對已觀察到的執行方式作驗證。
