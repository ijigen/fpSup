# v0.7.25test 虛擬模式壞點修正 —— 離線證據（2026-11-03，未上機、未部署）

設計與結論：[notes/DEFECT_VIRTUAL_MODES.md](../../notes/DEFECT_VIRTUAL_MODES.md)。

- `geometry.py hot` → `hot_g7.json`：G7 暗場（BUFA0，DEFC 之前）的熱點，以感光元件 receiver 座標記錄。
- `geometry.py cover` → `cover.json`：換算後的表覆蓋 97–98 %；修正前 DEFC 拿到的原樣表 97 只有 0.5–0.8 %。
- `geometry.py dng`（用 cdng venv 跑）→ `dng_null.json`：有光場景的 DNG 在預測位置上沒有訊號，不能當證據。
- `pre-change/`：v0.7.24test 的 ap.c／ap.h，給負向對照用。`negative_control.txt` 是新測試套在舊程式碼上的結果：9 項失敗。
- `default-build/`：預設 BIN `SensorLab-IMX410_v0.7.25test.BIN`，186,364 B，sha256 `6872f068…4193`，block 566,784 B。
- 測試：`python3 -B tools/test.py full --no-mutants` 全綠；apply 突變 91 個中 87 個被抓到。另外 4 個（#48、54、56、61）的突變文字在修改前的 ap.c 就已經找不到，是既有問題，不是這次造成的。

## 上機（2026-11-03 下午，v0.7.25test 已部署並讀回比對）

配方：DC 6048×4040 → 3024×2020（key 1、1×1），模式 231。鏡頭蓋上，IMXB 代換 SHS 4、30 dB（3965），每段錄 2 s。腳本 `live/dark.py`，熱點判斷用 `live/hot.py`：第 2、3 幀都超過 median + 12×MAD。

| 段 | 版本／條件 | clip | 穩定熱點 | 最大值 |
|---|---|---|---|---|
| a | v0.7.25test | A001_063 | 3 | 457 |
| a2 | v0.7.25test（重錄） | A001_065 | 3 | 451 |
| b | v0.7.25test + `imager defect_collect_off 1` | A001_066 | 98 | 992 |
| c | v0.7.24test（原樣表 97） | A001_064 | 95 | 992 |

- `live/overlap.py`：c 的 95 個熱點中，a2 修掉 92 個；a2 剩下的 3 個都在 c 裡面。b 和 c 共有 91 個。
- 狀態：commit 後 `defc = 1`、`defc_builds = 1`、`defc_last = 1`，錄影後 `defc_loads = 1`。待機時 `0x300F0D84` 是原廠表（0x013B8851）。待機跑的是原廠模式 8，模式 231 只在錄影時才換上，所以表是在 REC 開始時才交給 DEFC。原計畫第 2 步寫「LV 重載就會增加」是錯的。
- commit_us 116–120 ms，含換算器的時間。
- **凍結 1 次**：第一段 (a) 錄影正常結束（50 幀、xmp 298 B），停錄 10 s 後 LV 仍在跑模式 8，3 張 DNG 也下載完成。之後的第一個 `mem get` 就沒有回應，相機凍結，Bei 手動重開。後來帶逐步探針重跑 a2、b、c，三段都沒有凍結（v0.7.25 共 3 段、v0.7.24 1 段）。原因未明，只發生過一次，不能排除和 v0.7.25 有關。
- **連續 10 段**（f01–f10，A001_067–076，同一個 commit）：10 段都沒有凍結，每段錄完 5 s 後都回到 CINE 即時畫面，`defc_loads` 0 → 10。v0.7.25 合計 13 段，凍結 1 次（第一段 A001_063），之後沒有再重現。
- **垂直合併配方**（OG 6048×4040 → 3024×2020，鏡頭蓋上，方法同上）：

| 配方 | 新版（clip） | 關 DEFC（clip） |
|---|---|---|
| 12v2（key 10，模式 230） | 4（A001_077） | 99（A001_078） |
| 14v2（key 22，HMAX 911，模式 231） | 8（A001_079） | 132（A001_080） |

  修正前原樣表在這兩個配方上完全錯位（離線覆蓋 0.5–0.6 %）。兩段都沒有凍結。
- **凍結第 2 次（沒有錄影）**：14v2 錄完後，Bei 把格式切回原廠 FHD，回到 CINE 即時畫面。`where` 和 `status get` 都正常，下一筆 `mem get` 開始拿到空值，shell 逾時。Bei 自己重開。
  - 至此 v0.7.25test 凍結 2 次：一次在錄影後下載 DNG 時，一次在切回原廠格式後的待機中。v0.7.24test 今天沒有凍結過，但只錄過 1 段。
  - 嫌疑（推論，未證實）：`c0310740` 的暫存從 class 10（CinemaDNG 幀緩衝的通道）配置，我們在 commit 時呼叫它，**LV 還在跑**（呼叫在 `ap_lv_stop` 之前）。原廠只在 >0.5 s 靜態拍照時用它，那時 LV 是停的。這次測試中 Bei 切了很多次配方，`defc_builds` 達到 19。
  - 原廠 FHD 的對照段還沒錄。
- **重現測試（同一天稍晚，重開後）**：`repro/cycle.py 50`。待機中 50 輪「原廠 commit（sq_test 22）→ 推送配方（sq_test 19，14v2）」，交替模式 230/231，每輪都重算一次壞點表（`defc_builds` 51，commit 135–152 ms），每輪之後都探 shell：沒有凍結，30 s 後仍正常。之後接著錄 2 段並下載 DNG（A001_081、082），也沒有凍結。**兩次凍結都沒能重現。**
  - 旁證：LUT 那條線在 SensorLab **停用**時也遇過一次 `mem get` 回 0（`LOAD_DONE_US reads zero`），重試就好；第二次凍結剛開始的第一個症狀也是這個。
  - 我的腳本出過一次錯：sup 的載入位址會隨開機而變（一次是 C51892C0），`apst.py` 把位址寫死，有一次 callfn 呼叫了錯的位址（位址偏了 0x100），之後重開清掉。兩次凍結發生時，位址都核對過是對的（LOAD.LOG 都是 C51891C0），所以凍結不是這個錯造成的。`repro/cycle.py` 改成從 LOAD.LOG 讀位址。
