# 實體重開機後核對（2026-11-01）

使用者確認已實體關機再開機一次。主機USB sessionID由1819722253193改為1857588374451，沒有其他fpshd／PTPCamera，icdd仍為T（暫停）。只在持有共用flock時啟動唯一自有fpshd PID6958，送一次等待2000ms的原生ping，2.171秒後仍回frame0 LIBUSB_ERROR_TIMEOUT、moved=0/64。前置檢查因此停在第一步，沒有送出後續狀態、記憶體或檔案讀取。

正常關閉本次daemon後，保持lease，從已審閱的host/lsdesc.c在暫存目錄重建純主機描述讀取程式；它只開裝置並讀取主機所見的active configuration，沒有claim介面、送shell、寫卡、USB reset或變更配置。讀到SuperSpeed、interface0 class06/01/01、config57bytes、EP01/82 bulk1024、EP83 interrupt64。這是主機所見的配置，不把它冒充實機RAM、線路GET_DESCRIPTOR回覆或USB修復失敗證據。開發控制服務未回覆，當前LOAD.LOG／boot與卡上版本仍未知。

所有自有服務已正常關閉，共用鎖已釋放，沒有相機記憶體或卡檔寫入、錄影、CAPTURE、程式重啟或USB reset；這次實體重開機由使用者執行，之後沒有再要求重複開關。候選仍未部署。icdd依使用者要求維持暫停。

主機外接磁碟僅見Samsong 2TB，未讀取其檔案或視為相機SD卡。按專案USB模式原生分析，Mass Storage可將SD卡直接掛載，因此已請使用者切換Mass Storage，或改用讀卡機，以先備份與核對真正卡片的啟動檔、LOAD.LOG與設定，再決定部署。等待使用者完成該步。
