# 原生PTP停止後的連線檢查

使用者確認LCD為正常即時畫面、未錄影，隨後明確要求「關掉mac 原生ptp應用」。本次重新核對主機，沒有fpshd或PTPCamera；唯一相關原生程序為icdd PID633。

正常結束PID633後，KeepAlive立刻啟動PID6769。已核對gui/501/com.apple.icdd的程式路徑。嘗試bootout這次登入中的服務遭macOS SIP拒絕（exit150），不是自動審批拒絕。沒有改永久啟動設定或SIP。改以SIGSTOP暫停再次核對的icdd PID6769，ps狀態T；因此程序仍存在，但沒有執行。恢復時必須先核對當前PID與程式路徑，再發SIGCONT，不能將歷史PID當現況。

持有共用flock、啟動唯一自有fpshd PID6806（timeout2000ms）後，只做一次`TMO 2000 SHL ping`。2.264秒後仍為LIBUSB_ERROR_TIMEOUT、moved=0/64。PTP停止沒有證實修復控制通道，也不能據此宣稱LCD凍結或USB描述資料修復失敗。

已透過host QUIT正常結束本次服務並釋放鎖。沒有讀寫卡檔、改相機記憶體／設定、錄影、CAPTURE、USB reset或相機重啟；尚未部署候選。使用者被請求保持USB連接並實體關機再開機一次，等待新的開機核對。icdd維持使用者要求的暫停狀態。
