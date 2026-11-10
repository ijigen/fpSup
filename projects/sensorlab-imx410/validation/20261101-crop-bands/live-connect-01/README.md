# 2026-11-01 LCD驗收連線前置檢查

使用者回覆可以接上USB並看實體LCD。主機新鮮辨識SIGMA fp，沒有既有fpshd／相機測試程序；本次持有共用flock並啟動唯一自有fpshd 3.3.0。IOUSB顯示UsbExclusiveOwner為本次服務PID6654。

首次主機PING回ERR ping。核對owner、服務與USB清單後，僅做一次原生唯讀`ping native-check`，回覆frame0 LIBUSB_ERROR_TIMEOUT、moved=0/64。沒有繼續跑前置記憶體讀取、檔案清單、備份或部署；沒有卡檔／記憶體寫入、錄影、CAPTURE、相機重啟或USB reset。

這證明當下控制通道沒有回覆，不能推斷是LCD凍結、卡片版本或USB描述資料損壞。尚未核對當前boot與owned card，因此不符合runtime描述資料修復guard，不做恢復寫入。

已向使用者詢問當前LCD是正常待機、USB選擇畫面或無反應。等待期間未重送相機操作；本次自有daemon已經用host QUIT正常結束，共用鎖已釋放。owner.json中的PID是本次歷史紀錄，現在狀態以owner-released.json為準。LCD驗收與候選部署均未開始。
