# COL-Share 列數測試(DESIGN.md P4,2026-11-10,離線完成、未上機)

> **後續(2026-11-10 同日)**:19 列上機通過;產品改成 12 列,CSV/圖示複本改成機上依列配置(不再有額外 FPUI 區塊、BIN 不存 N² 份 CSV)。
> 下面 §1 的 #2、#3、#5 已不是限制;現況見 `../README.md`「12 列」。

問題:原生 COLOR 清單(COLOR 鍵與 MENU 路徑都是 ColorButtonMenu)經 COL-Share 最多能放幾個額外列?
答案(離線):**理論上限 19 列**,卡住它的是「沒人用的 86×74 圖示名稱」只有 19 個(含 set_flash_1)。
產品今天是 4 列(`CS_MAX`);只改常數最多 5 列(FPUI 區塊 8 個檔案);加「多個 FPUI 區塊」後在 64 KB 常駐預算內最多 12 列;
13–19 列要再把 CSV 改成機上產生(或接受 >64 KB 常駐、不錄 MOV)。相機上的清單繪製/捲動只驗過 20 列(16+4),5 列以上要上機看。

## 1. 每個限制與它允許多少

| # | 限制 | 在哪 | 允許 | 改法 |
|---|---|---|---|---|
| 1 | 額外列陣列 `CS_MAX` | `colshare.c`(eff/guitab/rec/row_*/label_at/donor_stock…)、`colshare_ui.MAX_ROWS` | 產品 4 | 常數(現在 `-DCS_MAX=N`,`build_colshare.py --rows N`) |
| 2 | **FPUI 區塊一次最多 8 個檔案**(`fpui_stock.c MAX_FILES`) | 3 份 CSV + N 個圖示同一區塊 | **N ≤ 5** | 程式:圖示放到額外 FPUI 區塊(測試版已做,`CS_EXTRA_BLOCKS`);或改共用 `MAX_FILES`(進入點堆疊 +28 B/檔) |
| 3 | 共用檔案重導表容量 32(`options.FV_CAPACITY`,第一個 hook 的 sup 決定;COL-Share 檔名排最前) | FSFV 表 | 3+N+Res-Custom 9(解析度 1+位元深度 2+格率 6)≤ 32 → **N ≤ 20**;卡上沒別人 29 | 資料:hook_fv 的容量參數(≤ 256);測試版用 64 |
| 4 | **沒人用的 86×74 圖示名稱**(donor) | 映像 2006 個 .xci 裡,名稱只出現在 NBR 目錄的 86×74 只有 19 個(含 4 個已用的、set_flash_1) | **N ≤ 19** | 再多要用非 86×74 的名稱(約 237 個沒人用,但「換掉內容、尺寸不同」未驗) |
| 5 | 常駐 64 KB(DESIGN §7 錄影預算) | BIN 存 3×(N+1) 份 CSV(O(N²))+每列約 0.9 KB 圖示 | **N ≤ 12**(12 = 62.2 KB、13 > 64 KB、19 = 90.2 KB) | 程式:sync 時機上組 CSV(省掉 N²);測試版放寬到 128 KB,**不可錄 MOV** |
| 6 | asm `add rX, r3, #imm`(最大位移 root_stock = 192+24N ≤ 1020) | `colshare.c` stub | N ≤ 34 | 程式:改 `ldr =literal` |
| 7 | `struct cols` 每列 +32 B,`STATE` 2048 | build | N ≤ ~34(測試版 4096) | 常數 |
| 8 | getter 筆數 `mov r2, #16+N`(imm8) | `C06C07D8` | N ≤ 239 | — |
| 9 | GUI 值:原廠 0..15,我們 16..15+N(全部 = enum 0xC + active) | GUI↔enum 表 | 無上限;`LV_ColorMode` 16–25 撞單色圖示 → stub_ml 收成 15(≥16 全收) | — |
| 10 | 頁面複本:6 個列數上限 + Effect 框 = BE 15+N;文字終點 500+33N | ColorButtonMenu FPUI page | 浮點,無實際上限 | 資料 |
| 11 | 大標籤 clip(Text 121)16+N 格,時間 500+33(j+1)−1 | `C1D66BC8` + 標頭 budget 字 | j < 108 時仍落在自己的 GUI 時間之前 | 資料 |
| 12 | AEL 頁範圍 `C1D6ED48` BE 15+N(映像原地字) | `ADV_NEW` | 浮點 | 常數(測試版由 build 算) |
| 13 | 每個 FPUI 區塊字串 ≤ 64 | `MAX_STRINGS` | 1+N ≤ 64 | — |
| 14 | 客戶 4 個、每客戶記錄 8 筆 | `CS_CLIENTS`/`CS_RECS` | 單一客戶要寫 ISP 的列 ≤ 8(LUT) | 常數 |
| 15 | 圖示複本堆積 13.3 KB/列 | `fst_alloc`(memmgr class 0) | 19 列 ≈ 253 KB,不認為是限制 | — |
| 16 | ListItem 列實例數(fp-native-ui 規則 7) | COLOR 條的 ListItem(obj 15)沒有實例數屬性(它的 0x1000E 是 controlValue max 0.0) | 列由 CSV 複製;實機 20 列可 | 上機確認 > 20 |
| 17 | 每列 controlValueEvent+controlFocus(規則 8) | 只適用 kind 16 popup;COLOR 的 List 14 是 `appVariableEvent CM_COLAJ_ColorMode` + 範圍事件 0–14 / ==14 | 不需要每列一組(17、20 列實機可) | — |
| 18 | 捲動(「> 6 列沒先例」) | 那是 popup;COLOR 條 List 14 有 `scrollEvent`、`is-value-loop`,920 px / 92 px ≈ 10 格可見,原廠 16 格本來就捲 | 有先例 | 上機看 > 20 |
| 19 | QS 色彩清單 | QS holder max 15 | 不放我們的列(設計 §5) | — |

COLOR 鍵與 MENU 路徑是同一頁(ColorButtonMenu),限制相同;QS 不在範圍內。

**結論**:離線卡住的是 #4(19 個 donor);產品要過 4 列,依序要做 #1 常數、#2 多區塊(程式)、#3 容量(資料);
要過 12 列還要 #5 機上組 CSV(程式)。19 之後要非 86×74 的 donor,再來是 #3(20/29)與 #6/#7(34)。

## 2. 測試版(產品不變)

- `build_colshare.py --rows N` → `rows-test/out/rowsN/COL-Share_v0.0.1test.BIN`(同檔名、同 sup_id,上卡就取代產品;SupManager 顯示 `COL-Share TN`)。
  - `CS_MAX=N`;內建假客戶 `CTST`(order 1000,排在 RAW-View 0、LUT 100 之後):N 列「TEST 1」..「TEST N」,
    圖示 = BIN 自己的佔位圖磚(各寫 TEST j,互不相同),沒有 ±框、沒有記錄 → **選到時 ISP root 一字不動**;選擇只在 RAM(冷開機回 OFF)。
  - 第 6 列起的圖示放額外 FPUI 區塊(每塊 ≤ 8 檔);重導表容量 64;AEL 範圍 BE 15+N;常駐上限放寬 128 KB。
  - donor 順序:原 4 個 → menu_cropZoom_highest/lowestLimit → menu_isoAuto_highest/lowestLimit → set_cropZoom_1_00..5_0(10 個)→ set_flash_1。
    第 5 個以後**沒用 `gui image log` 確認過**:DC 裁剪 / ISO 自動上限頁出現 TEST 圖磚 = 該 donor 有人用。
- 不帶 `--rows` 的建置與今天逐位元組相同(sha256 `f5d0a9e6…`,測試釘住);`colshare.c` 只多了 `#ifndef` 常數、asm 位移改成巨集(CS_MAX 4 時斷言等於舊數字)、`#if` 包住的測試碼。
- 備份:`projects/lut-sup/private/src-snapshot-20261110-rowstest/colshare/`(改動前的整個目錄)。

| N | 檔案 | 常駐 | 額外區塊 | AEL 字 | 備註 |
|---|---|---|---|---|---|
| 5 | 34288 B | 38400 B | 0 | `0000A041` | 單一區塊的極限 |
| 8 | 44304 B | 48448 B | 1 | `0000B841` | |
| 12 | 58084 B | 62208 B | 1 | `0000D841` | 64 KB 內最多 |
| 19 | 86128 B | 90240 B | 2 | `00000842` | 最大;>64 KB,不錄 MOV |

sha256 在各 `out/rowsN/build.json`。

### 離線測試

```
cd fpSup/colshare && python3 -B rows-test/test_rows.py          # 約 90 s,6 個測試,N = 5、8、12、19
python3 -B -m unittest test_colshare && python3 -B mutate_colshare.py   # 產品(本次也重跑:20 OK;突變樣式全在)
cd ../lut && python3 -B -m unittest test_clist_native                   # 12 OK
```

`test_rows.py` 在 unicorn 上跑真的 COL-Share 與韌體映像(LUT 卡拿掉 LUT.BIN、換測試版 BIN):載入、getter 16+N、GUI 表、
AEL 字;三份 CSV 複本、N 個互不相同的圖示、表容量、每區塊 ≤ 8 檔;頁面複本逐筆走完、**物件 id 唯一且與原廠同一組**、
7 個上限 = 15+N、文字終點、clip 16+N 格時間嚴格遞增、每列標籤 = TEST j;每列都能選、root 不動、關選單後客戶記得、
OFF 的 GUI 各出現一次;15+N+1 不是列、QS 的 15 不選列。突變抽查:把 `cmp ip, #16+N` 改回 #20、拿掉額外區塊,都被抓到。

## 3. 上機步驟(給協調者;先廣播相機使用權,用完廣播 released)

工作目錄 `fpSup/fp_usb_shell`。每個 N(建議順序 5 → 8 → 12 → 19)做一輪:

```sh
N=8; B=../colshare/rows-test/out/rows$N/COL-Share_v0.0.1test.BIN
python3 -B putfile.py $B '\fpSup\COL-Share_v0.0.1test.BIN'          # 部署(短蓋長時工具會先刪)
python3 -B getfile.py '\fpSup\COL-Share_v0.0.1test.BIN' /tmp/fp_rows_rb.bin && shasum -a 256 /tmp/fp_rows_rb.bin
#   必須等於 rows-test/out/rows$N/build.json 的 sha256;不等就不要重開
python3 -B ui_drive.py reboot                                          # 冷開機(shell reboot)
python3 -B getfile.py '\fpSup\LOAD.LOG' /tmp/fp_rows_load.log && grep -i 'COL-Share\|LUT\|RAW' /tmp/fp_rows_load.log | tail
#   COL-Share 那行:第 1 欄 0A(LOADED)、第 3 欄 18(十六進位 = 24 個 claim:16 點 + C05E5BEC + root 6 組 + C05E2200)
python3 -B ../colshare/rows-test/rows_state.py state
#   CS_MAX N、rows N、active 0、tpick 0、getter 16+N、AEL range 15+N
```

LUT、RAW-View 可以留在卡上:它們的列排在前面(RAW 0、LUT 100),額外列總數仍是 N(超過的 TEST 列不出現)。
要看到剛好 N 個 TEST 列,就在 SYSTEM → All Sups 停用 LUT、RAW-View(或另插一張只有 COL-Share 的卡);**不要用 `fl del` 刪它們**。

**A. COLOR 鍵**(每一步截圖並 Read):

```sh
python3 -B ../colshare/rows-test/rows_state.py color                  # 開 COLOR 條
python3 -B ui_drive.py shot:N$N-open
python3 -B ../colshare/rows-test/rows_state.py state                  # cur = 游標所在 GUI;用 LEFT/RIGHT 走到 cur 15(OFF)
python3 -B ui_drive.py shot:N$N-off                                    # 游標在 OFF
python3 -B ui_drive.py RIGHT shot:N$N-r1                               # 第 1 個額外列(cur 16)
#   之後每次 RIGHT 一張,直到第 N 個:shot:N$N-r2 … shot:N$N-rN
python3 -B ../colshare/rows-test/rows_state.py state                  # menu 1、cur 15+N
python3 -B ui_drive.py OK wait1 shot:N$N-picked                        # 選最後一列並關閉
python3 -B ../colshare/rows-test/rows_state.py state                  # active N、tpick N(或 N − LUT/RAW 列數)
python3 -B ../colshare/rows-test/rows_state.py color && python3 -B ui_drive.py shot:N$N-reopen   # 重開:游標在最後一列
python3 -B ui_drive.py RIGHT shot:N$N-wrap                             # 最後一列再右 = 環狀回第一個原廠列
python3 -B ui_drive.py MENU                                            # 取消關閉
```

**B. MENU 路徑**:`ui_drive.py MENU`,用 `where`/`shot` 找到 SHOOT 裡的「色彩模式(Color)」列,`RIGHT` 開(`where` 的 screen 應是 ColorButtonMenu),
同 A 從 OFF 往右走到最後一列每步截圖、`OK` 選最後一列、`S1` 回 LV,再走一次進去確認游標仍在最後一列。最後選回原廠模式(例 STD)再 `OK`,`rows_state` 看 active 0。

**C. 只在 N = 19 加做**:`gui image log` 開著,逛 SHOOT 的 DC 裁剪、ISO 自動上限頁:出現 TEST 圖磚或 log 載入 cropZoom/isoAuto 名稱 = 那個 donor 有人用(記下名稱)。

**通過**(每個 N):
- 條上原廠 16 格後面有 N 格(或 RAW/LUT + TEST 共 N 格),每格圖示不同、寫著自己的名字;條下大字是 `TEST j`(不是 Off);
- 每次 RIGHT 只移一格(cur +1)、游標格始終看得見(條會捲);最後一列 RIGHT 回到第一個原廠列(環狀,cur 0);
- `OK` 選最後一列後不跳回 OFF;重開時游標在那一列;`rows_state` 的 active/tpick 一致;LV 色彩與 OFF 相同(TEST 列不寫 ISP);
- MENU 路徑結果相同;選回原廠模式後 active 0;
- LOAD.LOG 沒有 `COL-Share: install failed`。

**失敗的樣子與意思**:
- 某格之後就沒有格子、游標也到不了 → 列實例數/CSV(規則 7);記下最後能到的 GUI(`rows_state` 的 cur)。
- 游標數字在動(cur 變)但畫面不動/看不到 → 捲動或每列事件(規則 8),記錄 N 與第幾格開始。
- 大字變回 `Off` → 標籤 clip;圖示是原廠圖案或空白 → donor/重導(第幾個 donor)。
- `OK` 後跳回 OFF → 某個上限沒跟著抬(頁面浮點或 AEL 字)。
- LOAD.LOG `install failed`、COLOR 條只有 16 格 → 安裝失敗(FPUI 區塊或記憶體);回報 N。
- 畫面卡住:先 `ui_drive.py S1`,不行才 `ui_drive.py reboot`;不要繼續按方向鍵。

**收尾**:放回產品 BIN 並冷開機,確認 LOAD.LOG:

```sh
python3 -B putfile.py ../COL-Share_v0.0.1test.BIN '\fpSup\COL-Share_v0.0.1test.BIN'   # 產品(sha256 f5d0a9e6…)
python3 -B getfile.py '\fpSup\COL-Share_v0.0.1test.BIN' /tmp/fp_rows_rb.bin && shasum -a 256 /tmp/fp_rows_rb.bin
python3 -B ui_drive.py reboot
```

結果寫進 `projects/lut-sup/validation/2026111x-colshare-rows-*/`(截圖、LOAD.LOG、每個 N 通過到第幾列)。
19 列版常駐 > 64 KB:**不要拿它錄 MOV**。
