# SensorLab-IMX410 QS：DC、RES、FPS、RECIPE、FORMAT（選擇與顯示階段）v0.2.0test

`fpSup/SensorLab-IMX410_v0.2.0test.BIN`（sup_id `SL41`，72 980 B）。用戶端，搭配 **QS 容器 v0.2.2（API 4）**
（`projects/qs-container/out/fpSup/QSContainer_v0.2.2.BIN`）。規格：**`../preview/dcres.html`**（Bei 認可的網頁版，以它為準）
與 `../QS_DC_RES_SPEC.md`。
**這一階段只選擇與顯示**：不裝任何感光元件／ISP 設定。之後的「套用」接在 `slqs.c` 的 `sq_apply()`（見下）。
全部離線：沒碰相機、沒碰 USB、沒寫卡；共用 loader 位元組與其他產品沒動；v0.1.0test 的 BIN 與 `out/build.json` 留著沒蓋掉
（新的是 `out/build-0.2.0test.json`）。

| 檔 | 內容 |
|---|---|
| `slqs.c` | 用戶端本體，跟 C 核心同一個編譯單元（`#include core.c`） |
| `build_slqs.py` | `python3 -B build_slqs.py --out out`；`link_flat()` 把 `.text` 與唯讀資料排成一塊、自己解 Thumb 呼叫與 `-fropi` 的 MOVW/MOVT，需要載入時重定位的一律拒絕 |
| `preview_runner.js` | 在 node 裡跑網頁版自己的程式（`// ---- render` 之前的邏輯＋`act`/`moveFocus`/`closeSub`），輸出每一步的畫面狀態 |
| `test_slqs.py` | unicorn 測試（真 v4 核心＋真容器 v0.2.2＋本 BIN＋真映像）、與網頁版逐步比對、`--mutate`、`--timing` |
| `slqs_ref.py` | v0.1.0test 的 Python 參考（DC/RES 舊版），已由網頁版取代，留作紀錄 |

## 功能

| 功能（清單標籤） | 格子 | 轉盤 | AEL |
|---|---|---|---|
| DC（`DC`） | DC 圖示、`HD`/`CUSTOM`、`35.9 × 20.2 mm` | 常見裁切，到頭停住 | 子 QS：DC、WIDTH、HEIGHT、RATIO |
| RES（`RES`） | RES. 圖示、K 標籤/`CUSTOM`、**看到的尺寸**`·`倍率（recipe 少幾列時黃色） | 清單由小到大 | 子 QS：RES、WIDTH、HEIGHT、RATIO |
| FPS（`SL FPS`） | 原廠 FPS 外觀、`59.94`、`• 32 recipes` | 常用格率到 1000，達不到的反灰並跳過；recipe 最高點有點狀底線 | **細調**：K 那種 `◀ 59.954 ▶`，前轉盤 VMAX ±1、後轉盤 10 步 |
| RECIPE（`RECIPE`） | 標題文字 RECIPE、`11b 3x6`/`CUSTOM`、`RS 3.13 ms` | 只在可用的預設 recipe（ISP 1x1）之間 | 子 QS：RECIPE、ADC、SENSOR HDC/VDC/HBIN/VBIN、ISP HBIN/VBIN（7 格） |
| FORMAT（`SL FORMAT`） | 原廠 FORMAT 外觀、`DNG`、`12bit`/`14bit`（跟 recipe 的 AD） | 無 | 無；選項列 `DNG | MOV`，MOV 反灰 |

行為跟網頁版逐條相同（網頁版 10-29 修正全部在內：比例鎖記住上鎖當下的比例並吸附預設、固定 K 以標籤記住、
小 DC 暫用 ×1 不忘倍率、細調每步數字必變、細調值只留一個並插回清單、選的 recipe 不被覆蓋、ISP bin 核心 × SOFT/STD
共用模式、反灰寫原因 `no 3x1`／`needs 12bit`／`not at this RES`、RWZM 0.5% 內寫 1:1、RS 兩位小數）。
介面字只用英文與原廠字串；`CUSTOM` 用大寫（原廠粗體字形只有大寫）。

**recipe 在相機上算**：任何 DC×RES（含自訂）都由 C 核心 `core_qualities_tol(DC, RES, 不設上限, 2%)` 現算
（= `isp-lab/host/quality.py` 逐位元），4 格快取。網頁版的 FPSDATA 只是替身。

**原廠 FORMAT 格不能借**：原廠格的值是 `Icon02` 自己的影格、選項列是它 holder 的 keyEvent（直接寫 `MV_RecordingFormat` 原廠設定），
容器只畫自己 id（≥49）的格子。所以 FORMAT 是我們自己的功能（放進編輯器取代原廠 FORMAT 格），只顯示、不寫原廠設定。

## 計算成本（unicorn，`python3 -B test_slqs.py --timing`）

| DC×RES | recipes | 指令數 | 堆疊 |
|---|---|---|---|
| OG 1K | 58 | 4.03 M | 2 472 B |
| HD 2K | 36 | 4.35 M | 2 472 B |
| S35 0.7K | 58 | 5.29 M | 2 472 B |
| OG 6K | 3 | 3.32 M | 2 472 B |

一次 3–5 M 指令；A9 在快取別名上大約 1 指令/週期，約 10 ms 級（**沒量過**；非快取別名慢約 50 倍會到 0.3 s，
BIN 有 `SL_F_CACHED_OK`）。只在換 DC/RES 而快取沒有時算一次（4 格 LRU），FPS／RECIPE 的轉盤不重算。

## 記錄（本 BIN 自己的）

`rec_off`（`out/build-0.2.0test.json`）65 字：`{'SLQ2', 2, DC 寬高, 兩個鎖, DC/RES 鎖定比例, 倍率, K 標籤, 自訂 RES, 記憶數,
fps 分子分母, 細調值, 選的 recipe + 它的 7 個參數, 兩軸核心, 模式, 8 × {裁切, RES}, FNV}`。
**只在容器的 `leave()`（每次換版面：關 QS、進選單）寫**，有改才寫；轉盤不寫卡。模式 7 原地覆寫＋讀回比對；
寫前 `file_is` 比對前 48 bytes，不是自己就不寫、絕不建檔；錄影中不寫（五個功能錄影中也鎖住）。

## 「套用」的接點

`sq_apply()`（`slqs.c`）：每次 `leave()` 時算出有效選擇——DC、RES、有效 recipe 的 readout key／HMAX、所選格率的 VMAX 步
（`fps_at(VMAX) ≤ 所選` 的最小 VMAX）、兩軸核心與模式——存在 `st->applied`，目前**不寫任何硬體**。
下一步在這裡接：`core_quality_plan(q, CLK, hm×VMAX)` → `core_smc_create`（感光元件模式），`core_quality_spec` →
`core_isp_plan`/`core_isp_row`（ISP），核心與 SOFT/STD → BINFILT。

## 離線測試

```
cd projects/sensorlab-imx410/qs
python3 -B -m unittest test_slqs          # 30 項，約 150 s（要 node）
python3 -B test_slqs.py --mutate --part=0/4   # 四份可以平行跑；34 個突變全部被抓到，每一項測試至少被一個突變打掉（slqs.c、build_slqs.py、preview_runner.js；2 個等價突變不列，見 MUTANTS 註解）
python3 -B test_slqs.py --timing
```

| 類 | 內容 |
|---|---|
| Preview（14 個腳本） | 網頁版在 node 裡跑同一串按鍵，每一步比對：前 5 格（自訂 QS 版面）或子 QS 每一格的大字、小字、黃色；子 QS 標題；焦點格的選項列（標籤、小字、黃、點狀底線、黃色細調值、反灰、目前那個；超過 16 個時比對同一個 15 項視窗）或數字轉輪。FPSDATA 由 `preview/gen_fps.py fpsdata()` 現產生，腳本走到的自訂 DC×RES 也產生（同一份 Python）。另一項檢查腳本真的走到了：SQ、細調與細調值、反灰、黃色 RES、14bit、反灰原因、ISP bin、CUSTOM recipe、自訂 DC、切換點標記 |
| Exact | JavaScript 的 double：`a16(W×r)`／`ev(H×r)` 每個偶數寬高 × 5 個倍率、mm 每個偶數 px、kLabel、`(w/h).toFixed(3)`、鎖定時的 `Math.round(w/asp)`／`(h×asp)` 與 `|p.w/p.h − asp| < 0.002`，全部對 node |
| Tiles | 開 QS 的五格、RECIPE 子 QS 7 項（第 7 項用 UI 72）、FORMAT 沒有轉盤且 MOV 反灰 |
| Record | 只在 leave() 寫、下次開機還原（含 FPS／recipe／核心）、壞記錄 → 預設、不是自己的檔／不見了 → 不寫不建、錄影中鎖住不寫、原廠設定不動 |
| Apply | `sq_apply` 只在 leave() 跑；有效 recipe 的 HMAX 與 VMAX 步對 `quality.py` |
| Build | 平面影像不需重定位；指標表會被 `link_flat` 拒絕 |

## 上機步驟（照慣例：先告訴 Bei 並等回覆、廣播相機使用權；錄影中與回放中不碰 USB；不按「建立 QR code」）

需要：v4 LOADER.BIN（fpSup 頁版）、**QSContainer_v0.2.2.BIN**、**SensorLab-IMX410_v0.2.0test.BIN**。
卡上不要同時留 QSContainer v0.2.1／SensorLab v0.1.0test（同 sup_id，新版會贏，但別留）；不放 ZQS。
v0.2.1 的格子記錄不會被 v0.2.2 讀 → 編輯器要重新放。

1. 讀 `\fpSup\` 清單、備份 LOAD.LOG；記下 CINE 兩組 8 格（`mem get 0xC31B0ABC,,32`）與 SetMovRecFormat／Size／Framerate。
2. `fl del` 舊的 v0.2.1／v0.1.0test，部署（讀回比對）：
   `python3 -B fpSup/fp_usb_shell/v3/deploy_v3.py projects/qs-container/out --only fpSup/QSContainer_v0.2.2.BIN`
   `python3 -B fpSup/fp_usb_shell/v3/deploy_v3.py projects/sensorlab-imx410/qs/out --only fpSup/SensorLab-IMX410_v0.2.0test.BIN`
3. `ui_drive.py reboot`。LOAD.LOG：兩個都 LOADED。進一次選單後狀態：N 5、qs_ready 1、qs_vars 148。
4. 編輯器（CINE）：放成 `SL FORMAT, DC, RES, SL FPS, RECIPE` 在第 1–5 格（清單最後五列）。離開到 LV。
5. `key QSON`，每一步截圖（`ui_drive.py shot`）：
   - 五格都有值；RECIPE 標題是文字；小字是**灰色系統字**（v0.2.2 改的：字形圖不吃顏色）；`CUSTOM` 這種太寬的值用系統字。
   - FPS 格：轉盤走常用格率，高過上限的跳過；下方反灰的是灰字，recipe 最高點下面有點線，`• N recipes` 在切換點出現。
   - FPS 按 **AEL**：版面不變、下方變 `◀ 59.940 ▶`、提示列**不顯示**（v0.2.2 預設）；前轉盤一步、**後轉盤十步**（容器 v0.2.2 分前後轉盤，上機確認 BR/BL 的方向）；
     再按 AEL：細調值黃色插進清單。細調中左右移焦點 → 也離開細調。
   - RECIPE：轉盤只走可用的；FPS 調高讓選的 recipe 不可用 → 顯示別的，FPS 調回來 → 回到原本選的。
   - RECIPE 按 AEL：8 格（RECIPE＋7 項，第 8 格是 ISP VBIN）；ADC 換成 14bit 時 FPS 自動降、FORMAT 變 14bit；
     SENSOR HBIN 的反灰項小字寫原因（`no 3x1`、`needs ...`）；ISP HBIN 轉到 3 有核心與 SOFT。
   - DC/RES 子 QS：RATIO 格標題是 `RATIO`、鎖頭圖在**值的位置**；WIDTH −1 再 +1 回到原值且比例不飄（live 3 的 1.778→1.781）。
   - 子 QS 第 1 格標題是文字（live 3 的 `RES.` 偏右）。
6. **MENU 的新規則（live 3）**：子 QS 或細調裡按 **AEL** 回上層；按 MENU 是原廠 MENU（關 QS、開選單），容器在換版面時把子 QS 收掉。
   看：AEL 回上層焦點回原格；MENU 之後再開 QS 是使用者的 8 格、`sub_open` −1。之後 `status` 確認 shell 還在
   （live 3 的 shell 卡住跟 MENU 的關係未證實——**MENU 這步做完先查 shell**，卡住就停）。
7. 關 QS、進選單（觸發 `leave()`）→ 讀卡上 BIN 的記錄（`rec_off`）有寫；重開機選擇都在（含 FPS、recipe、核心）。
   `mem get` 兩組 8 格與原廠 Format／Size／Framerate = 第 1 步（原廠設定沒變）。
8. 錄影鎖（**Bei 手動**）：錄影中 QS 五格反灰、轉盤與 AEL 不動作。停錄 10 秒後才接 USB。

收尾：編輯器把五格換回原廠功能，讀回兩組 8 格。

## 離線證明不了的

1. 畫面本身：灰色系統字小字、點狀底線（`. . . . . .` 一個 drawText）、灰／黃標籤、鎖頭在值的位置、長小字縮到 208 px 寬 30 號字是否放得下
   （RECIPE CUSTOM 的小字很長，例 `11b 1x1 ISP 3x3 · RS 15.84 ms`）。
2. `core_qualities` 在相機上的時間（只有指令數）與 UI 執行緒的堆疊夠不夠（量到 2.5 KB）。
3. 後轉盤碼 3/4 的方向（資料照原廠 BR = −1、BL = +1）。
4. **ISP bin 的 STD 模式在相機上選不到**：網頁版要直接點另一個模式的選項才換模式，相機沒有點選、轉盤只在目前模式內走。要 Bei 決定（例如轉盤走完 SOFT 接著走 STD）。
5. MENU 回上層：live 3 看到 MENU 同時跑了原廠 MENU；v0.2.2 預設不再接 MENU（見容器 README），子 QS／細調裡沒有提示（沒有原廠的「AEL 退回」字串）。要不要另找方法讓 MENU 回上層，待 Bei 決定。
