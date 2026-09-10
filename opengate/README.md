# fpSup Open Gate — fpsup-opengate-test

版本：**fpsup-opengate-test**

狀態：**實機測試版，不是正式 release**

這是一份給 **SIGMA fp 韌體 Ver.5.02** 的冷開機測試版。它只寫 RAM，不寫 flash；
移除測試 `AutoRun.txt` 並完整斷電重開，就會回到原廠內容。

這版包含已由實機驗證的最小因果集合：

- FHD/29.97 的三張 picker 表改選 sensor mode 117。
- mode 117 的 VMAX 改為 7280，輸出約 29.97003 fps。
- profile 122 的 live/record、H/V 四個 RWZM 值由 `0x640` 改成 unity `0x400`。
- 在 `0xC043A19C` 掛上已驗證的 v4 幾何 hook，把 DNG／producer envelope 改成
  3032×2012；hook 是整份腳本的最後一個記憶體修改。

已證明不控制 DNG canvas/producer 的 movie/still 尺寸下游複本沒有放進來；三個獨立
診斷 hook 全部移除。v4 functional hook 自己原有的 `FA00–FA0F` 四個 telemetry words
仍然保留。

## 安裝與第一次測試

1. 確認機身韌體是 **Ver.5.02**。這份 AutoRun 在產生時核對過本機 Ver.5.02
   韌體映像，但 AutoRun 語言本身沒有執行期版本 guard，不能用在其他版本。
2. 完全關機、拔電池，使用讀卡器操作 SD 卡。不要從目前仍掛著 hook 的 USB shell
   上傳這個檔案。
3. 備份 SD 根目錄原有的 `AutoRun.txt`，以及同一套件的 `VSHL.BIN`／`PGEN.BIN`
   （若存在）。先移走舊 `AutoRun.txt`，再把本資料夾的 `AutoRun.txt` 複製到卡片根目錄。
   這個測試版本身只需要單一 `AutoRun.txt`。
4. 執行 `sync`，從卡片回讀確認檔案是 32,768 bytes，且 SHA-256 與 `MANIFEST.txt`
   完全相同，再安全退出卡片。
5. 保持 USB 線拔除，再裝回電池冷開機。
6. 等螢幕顯示 `fpOGtest!`。這只代表腳本跑到結尾，不代表機身版本或每一個 word 已被
   執行期驗證。
7. 進入 CINE，重新選一次 **CinemaDNG / FHD / 29.97p**。若原本已在這組設定，先切到
   另一解析度再切回 FHD，讓 picker、profile 與 RawInfo 在補丁完成後重新建立。
8. 先錄一段很短的測試。預期單幀 DNG 是 3032×2012，檔案約 9,229,824 bytes，且有效
   影像應填滿畫布，不再只有左上角約 1936×1288 的小畫面。

若要在錄影前確認，可在 banner 出現後才接 USB，並只用 direct `mem get` 回讀：

| 位址 | 預期值 |
|---|---:|
| `C0B59A28` | `00041C70` |
| `C0BE5888` / `C0BE5A28` / `C0BE5BC8` | `00000075` |
| `C0BD9A34` / `C0BE1684` / `C0BD9EFC` / `C0BE1B4C` | `00000400` |
| `C043A19C` | `EB0BD597` |
| `C072FA00` | 重選模式後應大於 `00000000`（v4 hook hit count） |

## USB 限制

v4 payload 使用 `0xC072F800–0xC072F8E8`，log words 使用 `0xC072FA00–0xC072FA0F`。
這與 host 端工具的暫存工作區重疊。hook 生效期間：

- 可以使用只送 firmware shell 指令的直接 `mem get`／`mem set`。
- **不可使用** `getfile.py`、`putfile.py`、`inject.py`、`callfn.py`，也不可執行任何會
  覆寫 `0xC072F800–0xC072FB00` 的 helper。
- DNG 請在完整關機後，改用讀卡器取出。

## 還原

完全關機、拔電池，以讀卡器移除這份 `AutoRun.txt`，或放回原本成套備份的 boot files，
再冷開機。所有 open-gate 修改都只存在 RAM。

建置與內容雜湊請看 `MANIFEST.txt`。產生器是同一資料夾的 `build_test_autorun.py`。

## 測試結果請記錄

每次只錄短片，保留下列結果，方便判斷 producer 是否真的解除 1936×1288 限制：

- 是否正常看到 `fpsup-opengate-test` README 所述的 `fpOGtest!` 完成提示。
- 上表九個 patch words 是否全部吻合，以及 `C072FA00` hit count 是否開始增加。
- 第一個 DNG 的實際檔案大小、`ImageWidth`、`ImageLength`、`RowsPerStrip`、
  `StripByteCounts`。
- 解碼後有效畫面是否填滿 3032×2012；若仍只在左上角，記下內容邊界的實測寬高。
- 是否能連續錄製與正常停止，以及是否出現凍結、花屏或掉幀。

任一 RAM 值不符、沒有完成提示或機身行為異常時，不要開始長錄；完整斷電並依「還原」
步驟移除 AutoRun。

## 從源碼重建

倉庫不包含相機韌體。將自行取得的 Ver.5.02 `MAIN_c0000000.bin` 傳給產生器：

```sh
python3 opengate/build_test_autorun.py --firmware /path/to/MAIN_c0000000.bin
```

產生器會先核對完整韌體 SHA-256、九個原廠 words 與空白 code cave，再組譯 payload、
驗證地址及順序，最後產生固定 32 KiB 的 `opengate/AutoRun.txt`。
