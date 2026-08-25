# firmware map

逆向基礎建設 —— 韌體格式、子系統地圖、任務 ABI、狀態來源。

**狀態:持續累積,是其他所有項目的地基**

---

## 目標

這一項不是產品。它是讓上面每一個專案能動的共同基礎:
韌體長什麼樣、哪個子系統在哪、怎麼安全地在裡面跑自己的程式。

## 已確認

- **韌體格式** —— `FP__V502.BIN` 的結構、分段、載入位址(`MAIN` @ `0xC0000000`)
- **任務建立 ABI 已實機驗證** —— `tk_cre_tsk 0xC0016A58` + `tk_sta_tsk 0xC0016BC0`,
  descriptor `{exinf, tskatr=0x41, entry, itskpri, stksz, dsname[8]}`。
  **`stksz` 絕對不能超過 0x2000** —— 堆疊池是共用的,調大會弄壞其他任務(踩過)。
  `Cyc` 那組(`0xC01F885C`/`0xC01F8D90`)會凍結相機,不要用
- **檔案 API** —— 開檔模式 1=讀、7/6/0xF=寫且可覆寫、**`0x402` 檔案已存在就失敗**;
  `0xC0366020` 是 **close 不是 flush**;open 回 0 是失敗,必須回讀才算寫成功
- **子系統地圖**、**即時相機狀態來源**、**韌體隱藏功能調查**、**簽章/完整性分析**
- **shell 指令表**:`display` 表在 `0xC0BB1410`,每項 12 bytes `{name, help, fn}`

## 紀律(付出代價換來的)

- 凍結之後**先讀卡** —— hook 寫下去的資料還在
- 新程式碼**先直接呼叫一次**再掛上去
- **一次只改一件事**;混變因會讓失敗無法歸因
- 判斷要以**乾淨開機**後的第一次讀數為準,不要用被實驗擾動過的狀態

## 相關筆記

`FORMAT`、`FIRMWARE_INVENTORY`、`SUBSYSTEMS`、`TASK_ABI_VERIFIED`、`TASK_PRIORITY_MAP`、
`CAMERA_STATE_SOURCES`、`SECURITY`、`HIDDEN_FEATURES`、`SHELL_COMMANDS`
