# fpSup Open Gate — fpsup-opengate-test

版本：**fpsup-opengate-test**

狀態：**實機測試版，不是正式 release**

## 簡單說明

這個測試版讓 SIGMA fp 以 3032×2012 的 3:2 畫布錄製 CinemaDNG。輸出畫布的轉換點
已經找到，現在要確認 RWZM 改成 unity 後，有效 Bayer 內容能否真正填滿整個畫布。

目前狀態與已知限制：

- 僅適用 **SIGMA fp 韌體 Ver.5.02**。
- 尚未製作獨立選單；功能寄生在 **CINE / CinemaDNG / 12-bit / FHD / 29.97p**。
- live view 目前會有閃爍問題。
- 機身回放無法正常顯示測試素材；請用電腦檢查 DNG。
- AutoRun 只修改 RAM，不寫 flash。移除 AutoRun 並完整斷電即可還原。

## 測試方式

### 1. 安裝

1. 確認機身韌體是 **Ver.5.02**。
2. 完全關機、拔電池，以讀卡器操作 SD 卡。
3. 備份卡片根目錄既有的 `AutoRun.txt`；若原套件還有 `VSHL.BIN`、`PGEN.BIN`，請整組
   備份。不要從仍掛著舊 hook 的 USB shell 上傳測試檔。
4. 將本資料夾的 `AutoRun.txt` 放到 SD 卡根目錄。這個版本只需要這一個檔案。
5. 執行 `sync`，從卡片回讀確認檔案是 32,768 bytes，SHA-256 為：

   ```text
   032e2562e86d12db3085bac14b3ceab0abd71dc13e018e5d7542e145679ea790
   ```

6. 安全退出卡片，保持 USB 拔除，裝回電池並冷開機。

### 2. 啟動測試模式

1. 等螢幕顯示 `fpOGtest!`。這只表示 AutoRun 已執行到結尾，不等於每一個 word 都已回讀
   驗證。
2. 進入 CINE，設定為 **CinemaDNG / 12-bit / FHD / 29.97p**。
3. 若開機時本來已是這組設定，先切到其他解析度，再切回 FHD，讓 picker、profile 與
   RawInfo 在補丁完成後重新建立。

需要在錄影前確認時，可在相機仍待機時才接 USB，並且只用 direct `mem get` 回讀：

| 位址 | 預期值 |
|---|---:|
| `C0B59A28` | `00041C70` |
| `C0BE5888` / `C0BE5A28` / `C0BE5BC8` | `00000075` |
| `C0BD9A34` / `C0BE1684` / `C0BD9EFC` / `C0BE1B4C` | `00000400` |
| `C043A19C` | `EB0BD597` |
| `C072FA00` | 重選模式後應大於 `00000000`（v4 hook hit count） |

回讀完成後先拔除 USB，再開始錄影。錄影期間不要送任何 shell 指令。

### 3. 錄製

1. 先錄一段很短的測試，不要直接進行長錄。
2. 錄影期間觀察 live view 閃爍程度、是否能正常停止，以及是否出現凍結、花屏或掉幀。
3. 素材會寫入卡片的 `/Movie/fpSup/opengate/`。
4. 機身回放目前無法正常顯示，這是已知限制，不要用機身回放判定 DNG 是否損壞。

### 4. 取檔與判定

1. 完全關機後取出 SD 卡，以讀卡器取得 DNG；不要在 hook 生效時使用 USB `getfile.py`。
2. 至少檢查第一張、中間一張與最後一張 DNG。
3. 預期 DNG envelope 為 3032×2012，單幀檔案約 9,229,824 bytes。
4. 檢查 `ImageWidth`、`ImageLength`、`RowsPerStrip`、`StripByteCounts`。
5. 用電腦解碼後，確認有效畫面是否填滿 3032×2012。若仍縮在左上角，請量出有效內容
   的實際寬高；前一輪約為 1936×1288。

測試結果請記錄：

- 九個 patch words 與 `C072FA00` hit count。
- DNG 實際檔案大小與上述 TIFF/DNG 標籤。
- 有效內容的實測邊界。
- live view 閃爍情況。
- 是否正常開始／停止，以及是否凍結、花屏或掉幀。

任一 patch word 不符、沒有 `fpOGtest!`、或機身出現異常時，不要繼續長錄；完整斷電並
依下方方式還原。

## USB 安全限制

v4 payload 使用 `0xC072F800–0xC072F8E8`，telemetry 使用
`0xC072FA00–0xC072FA0F`，與 host 工具的暫存工作區重疊。hook 生效期間：

- 只在待機、錄影前，以 direct `mem get` 回讀上表地址。
- 不要用 generic `mem set` 熱改測試狀態；需要重試時完整斷電重開。
- 禁止使用 `getfile.py`、`putfile.py`、`inject.py`、`callfn.py`，以及任何會覆寫
  `0xC072F800–0xC072FB00` 的 helper。
- 開始錄影前拔除 USB；錄影期間不送任何 shell 指令。
- DNG 一律在完整關機後使用讀卡器取得。

## 還原

完全關機、拔電池，以讀卡器移除測試 `AutoRun.txt`，或放回原本成套備份的 boot files，
再冷開機。所有 open-gate 修改都只存在 RAM。

## 實作摘要

- FHD/29.97 的三張 picker 表改選 sensor mode 117。
- mode 117 的 VMAX 改為 7280，輸出約 29.97003 fps。
- profile 122 的 live/record、H/V 四個 RWZM 值由 `0x640` 改成 unity `0x400`。
- 在 `0xC043A19C` 掛上 v4 幾何 hook，把 DNG／producer envelope 改成 3032×2012；
  hook 是整份 AutoRun 最後一個 `mem set`。
- 已證明不控制 DNG canvas/producer 的 movie/still 尺寸下游複本沒有放入。
- 沒有獨立診斷 hook；只保留 v4 functional hook 內建的四個 telemetry words。

mode 117 時序、picker、v4 envelope 與 RWZM unity 引發的硬體 policy 切換都已在實機
觀察到；最終 Bayer 內容是否填滿 3032×2012，正是本測試要回答的問題。

## 從源碼重建

倉庫不包含相機韌體。將自行取得的 Ver.5.02 `MAIN_c0000000.bin` 傳給產生器：

```sh
python3 opengate/build_test_autorun.py --firmware /path/to/MAIN_c0000000.bin
```

產生器會核對完整韌體 SHA-256、九個原廠 words 與空白 code cave，再組譯 payload、驗證
地址及順序，最後產生固定 32 KiB 的 `opengate/AutoRun.txt`。完整雜湊見
[`MANIFEST.txt`](MANIFEST.txt)。
