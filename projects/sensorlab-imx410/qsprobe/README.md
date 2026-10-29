# SensorLab-IMX410 QS probe(分段探針,不是產品)

目的:在原廠「自訂 QS」編輯器(`MV_QSMENU_QSn`,頁 `Y2_3C` / `Y2_3C_ShutterAngle`)的功能清單加四個新功能
**DC / RES / FPS / QUAL**,一段一段上機驗證機制。原廠 QS 頁本身不動(**NBU 影格這一輪不做**),新 id 背後沒有行為。
SensorLab 不會和 RES-Custom 同時開。

依據:`projects/qs-touch/notes/QS_ADD_FUNCTION_RESEARCH.md`(機制)、`research/ui/CUSTOM_QS.md` §1–2、
`projects/rawview/README.md`「設定關機存檔路徑」。韌體 Ver.5.02。**全部離線完成:沒碰相機、沒寫卡。**

## 檔案

| 檔 | 內容 |
|---|---|
| `qsprobe.c` | sup 本體(v4、`-fropi` Thumb、只有 .text)。同一份原始碼,階段由建置寫進 config |
| `build_qsprobe.py` | 建置:`python3 -B build_qsprobe.py --out out`(三段)、`--stage N`、`--stock-keys`、`--no-emit` |
| `test_qsprobe.py` | unicorn 測試(真 v4 核心 + 真映像)與 `--mutate` |
| `out/fpSup/SLQSProbe{1,2,3}_v0.1.0.BIN` | 私有字串標籤版(預設) |
| `out-stockkeys/fpSup/…` | 備案:標籤用原廠 KEY(1107 DC 裁切 / 1116 解析度 / 1118 格率 / 1114 格式),不經私有字串 |

| 產物 | bytes | sha256 |
|---|---|---|
| `SLQSProbe1_v0.1.0.BIN` | 13408 | `2bf95445cbb354a8…` |
| `SLQSProbe2_v0.1.0.BIN` | 13408 | `32c142406c27ce89…` |
| `SLQSProbe3_v0.1.0.BIN` | 13488 | `8509d6d1ebcb0174…` |

完整 sha256 與位移在 `out/build.json`。三個檔 sup_id 都是 `SLQP`:**卡上一次只放一個**(放兩個也只會載入字母序第一個)。
需要有 fpSup 頁的 v4 LOADER.BIN(私有字串的解析 hook 在核心的 UI 版裡);共用 loader 位元組沒有動。

## 每一段改了什麼

| | 階段 1 | 階段 2 | 階段 3 |
|---|---|---|---|
| CSV 四份 `Y2_3_CINE{,_W91C1,_angle,_angle_W91C1}.cvm` 經共用取檔處理器(C05E5BEC)的複本各加 4 列:`33..36, 49..52, <原廠圖示>, <KEY>, S` | ✓ | ✓ | ✓ |
| 編輯器清單游標上限 `Visible`(obj 0x1116)controlValue max 31 → 35,兩頁各一處(頁面複本,0xC28B8F10 / 0xC29818C0) | ✓ | ✓ | ✓ |
| KEY = 私有字串 id(`DC`/`RES`/`FPS`/`QUAL` 的非快取位址,10 位十進位),整塊 `borrow` | ✓ | ✓ | ✓ |
| 轉換器 `[0xC37B7728]` 換成 vtable 複本(含前 8 bytes),只改 +0x344(CINE 表):下一層的表 + {54,49}{55,50}{56,51}{57,52};STILL 表(+0x340)不動 | | ✓ | ✓ |
| 存檔替換:`0xC0088C60 bl FUN_c0088660` → 序列化前把兩組 8 格(影像 +0x23E8、+0x2700)裡的 54..57 換成占位 **0(拍攝模式)**,複製完立刻放回 RAM;記錄寫進本 BIN | | | ✓ |
| RecommendedSetting(QR)讀取 `0xC053DBF8 bl FUN_c0061b08` → 54..57 回傳 0 | | | ✓ |
| 開機:BIN 記錄說是我們的格、且 RAM 仍是占位 0 → 放回 54..57;CINE 時重發 `MV_QSMENU_QS1..8` | | | ✓ |

- 所有寫入點先 `claim`(轉換器指標、兩個 bl 都是 `SL_CHAIN`,取檔處理器 `SL_SHARED_UI`,同 raw-view),任何一個被拒就 RELEASE、什麼都沒寫;
  關機時核心把它們寫回原廠(暖開機殘留的舊 vtable 指標在 claim 時就被修回原廠,再接到它上面)。
- 安裝順序:claims → 準備(vtable 複本、撞號檢查、cave veneer)→ 存檔 hook → 開機還原 → 換 vtable → CSV。存檔 hook 永遠比 54..57 先到。
- **接層**:`[0xC37B7728]` 已不是原廠(別的 sup 先接了)就複製那一份、+0x344 先呼叫下一層再附加。下一層的表裡已有 54..57 或 UI 49..52 → 不裝(RELEASE,LOAD.LOG `QSP 2 00030000 …`)。
- BIN 記錄:檔案位移 `rec_off`(階段 3 = 0x3448),20 字 `{'QSR1', 占位, 16 格 id, FNV, 0}`;寫回前 `file_is` 比前 48 bytes,
  不是自己(被 SupManager 改名/刪掉/換掉)就不寫、絕不建檔;錄影中不寫(下次存檔再寫,flash 照樣是乾淨的)。

### 狀態(`mem get` 讀)

LOAD.LOG 的 `LOADED` 行給區塊位址 B;我們的一行是 `QSP <段> <result<<16|csv_result> <下一層 vtable> <restored<<16|key_patched>`
(全 0/`…0010` = 階段 1 正常:16 個 KEY 補好)。狀態在 B + `state_off`(1/2:0x3480,3:0x34C0):
+0 `QRUN`、+8 result(0 好;1 vtable claim、2 vtable 不像、3 撞號、4/5 存檔/QR claim、6 chain、7 cave)、
+12 CSV 結果(fpui 錯誤碼 | 第幾塊<<8;0x10 = borrow 失敗)、+56 下一層 vtable、+2244 saves、+2252 sanitized、
+2260 restored、+2264 stale、+2268 writes、+2272 write_fails、+2276 why(2 不是自己的檔、3 I/O)、+2280 錄影中略過。
設定影像兩組 8 格:`mem get 0xC31B07A4,,32`(+0x23E8)與 `mem get 0xC31B0ABC,,32`(+0x2700)。

## 上機步驟(照慣例:先告訴 Bei、廣播相機使用權;每段只換一個 BIN,冷開機)

先備份卡上 `\fpSup\`,把其他 SLQSProbe* 移走;不要和 RES-Custom 同卡。

### 階段 1(證實研究 §3.1)
1. 放 `SLQSProbe1_v0.1.0.BIN`,開機,讀 LOAD.LOG:有 `QSP 1 00000000 00000000 00000010`。
2. 進原廠自訂 QS 編輯器(CINE),選一格,清單往右捲到最後:耳機音量之後應有 **DC、RES、FPS、QUAL** 四項(圖示借原廠的裁切/解析度/格率/格式)。
   - 文字空白 → 換 `out-stockkeys` 版再看一次(私有字串在這個清單沒被解析,是新發現,記下來)。
   - 列畫出來但游標到不了 / 只到 32 → 清單列實例數另有上限(風險 3)。
3. 選 DC 放進某格 → **預期該格變成「拍攝模式」**,`mem get` 那格 = 0(+0x2700 或 +0x23E8 那組,記下是哪一組 = CINE 組)。
4. 這一段 flash 不會有新 id(轉換器把 49 轉成 0),可以正常關機。

### 階段 2(轉換器)
1. 換 `SLQSProbe2`,開機,LOAD.LOG `QSP 2 00000000 C2DEAD7C 00000010`。
2. 選 DC/RES/FPS/QUAL 各放一格 → 編輯器**顯示並保留**我們的項目(離開再進仍在);`mem get` 那格 = 54..57。
   QS 畫面那格沒有影格(這輪不做),顯示舊圖或空白是預期的。其他格、STILL 不受影響。
3. **關機前一定要把那幾格改回原廠功能**:階段 2 沒有存檔替換,關機會把 54..57 寫進 flash(離線負對照測試證明了)。
   忘了改的話照下面「還原」做,**不要**按「建立 QR code」。

### 階段 3(存檔替換)
1. 換 `SLQSProbe3`,開機,LOAD.LOG `QSP 3 00000000 C2DEAD7C 00000010`。
2. 放 DC 進第 3 格、QUAL 進第 7 格 → 撥開關關機(這時 v2 存檔:flash 拿到 0,BIN 記錄 2 格)→ 開機:
   編輯器仍是 DC/QUAL;狀態 restored = 2、LOAD.LOG 最後一欄 `00020010`。
3. 證明 flash 沒有新 id:SupManager 停用 SLQSProbe3 → 關機 → 開機:那兩格顯示「拍攝模式」(不是空白、不當機)。
   再啟用 → 關機 → 開機:回到 DC/QUAL(記錄還在)。
4. 停用期間把那格改成別的原廠功能(例 WB)→ 再啟用:那格保持 WB(stale = 1,不蓋掉使用者的選擇)。
5. QR:**這一段也先不要按「建立 QR code」**。離線證明了 QR 讀取點會看到 0,但 QR 路徑本身沒上機看過,要不要驗另外決定。

## 還原(某格存著我們的 id,sup 停用或拔掉)

- 預期:編輯器與 QS 那格顯示**拍攝模式**(轉換器查不到就給 UI 0)。在編輯器把那格換成任何原廠功能,正常關機一次就寫回 flash。
- 只有階段 2 關機後 flash 才可能真的有 54..57;階段 3 的 flash 只會有 0。
- **永遠不要在 flash 可能有 54..57 時按「建立 QR code」**(RecommendedSetting 匯出 `FUN_c0548208` 查不到會 assert + 無窮迴圈 = 卡死)。

## 存檔路徑:涵蓋與未確認

已涵蓋(靜態 RE + 模擬):
- **關機存檔**:`SaveOnPowerOffObserver__v1` 0xC00789B0 → v9(快照回存)→ v2 0xC0088BB0 → `bl FUN_c0088660`(0xC0088C60)把 0x4F00 影像複製進 flash 緩衝,
  之後 `FUN_c0022820` 才寫 NAND。`FUN_c0088660` 在映像裡**只有這一個呼叫者**、沒有指標引用(測試 `test_only_one_call_site_feeds_the_flash_buffer` 釘住)。
- **shell `menu save`**:同一個 v2(不寫 NAND)。
- **重置**(`MenuSettingStorage_w71c1::v3` 預設值蓋影像、`XC_SettingSaveDataMgrCore::v1` 預設值蓋緩衝;PTP 0x6D 重置走這些):寫入的是預設值,沒有我們的 id;下一次存檔記錄跟著變成空。
- **RAM 快照**(v5/v8 存、v6/v9 回存,0x58D4 / 0xB1A0):只在 RAM,回存後由下一次 v2 清掉。
- **RecommendedSetting / QR**(`FUN_c053db98` 的 16 個呼叫):唯一讀 QS 格的地方是 0xC053DBF8,已改成回傳占位。
- `FUN_c0061b08` 的其他呼叫者全部列過:編輯器 v95/交換(C0471148/C0473B40)、三個 8 格通知迴圈(C0477938/C048C7D8/C04CB864)、QS v18(C0580490/C0580500)
  都經轉換器 → UI;shell 除錯指令 `SetFunction`(C0401CE4)只印數字。沒有 Thumb 呼叫者。

未確認:
- 走**通用 item 存取**(item 0xD3 的 vt+0x18 / `FUN_c00b81e8` 依 id 分派,不經 `FUN_c0061b08`)讀 QS 格的路徑,例如 PTP 的通用屬性讀取 —— 沒有逐一追。
- 自訂模式 C1–C3 的 0x9C0 bank:QS 格在影像 +0x23E8/+0x2700,不在 bank 區(+0x4F00..),推定不受影響,沒有實機看。
- 兩組 8 格(+0x23E8 / +0x2700)哪組是 CINE:沒定,所以兩組都處理;階段 1 步驟 3 會知道。
- 關機時存檔回呼與核心寫回回呼的先後:依 raw-view 的實機經驗(同一個 C0088C60 點)存檔在前;本探針沒上機驗。

## 離線測試

```
cd projects/sensorlab-imx410/qsprobe
python3 -B -m unittest test_qsprobe          # 27 項,約 25 s
python3 -B test_qsprobe.py --mutate          # 19 個突變,每個都要讓測試失敗
```

真的部分:v4 核心(UI 版)、AutoRun loader、探針 BIN、韌體映像裡的 `FUN_c058c4d0`、`FUN_c06c7bc0`/`FUN_c06c7b28`/`FUN_c06d0fa0`/`FUN_c06ce6f0`、
原廠 vtable 函式、`FUN_c0088660`、核心的字串解析/借用 hook。Python 模型:`C0057AE8`、`C0058340`(CINE 與否)、`FUN_c0061b08`(讀模型選的那組)、
guard 兩支、memcpy、校驗、檔案 API、F_SEEK、UI app(變數發佈)。

| 類 | 測試 |
|---|---|
| 階段 1 | 四份 CSV 原廠部分逐位元不變、各 36 列、新列 NO/ID/圖示正確、KEY 經核心解析 hook 回到 `DC/RES/FPS/QUAL` 且已 borrow;兩頁上限 35;轉換器未動:UI 49..52 → internal 0、internal 54..57 → UI 0;`--stock-keys` 版 |
| 階段 2 | vtable 複本只差 +0x344;UI↔internal 雙向(49..52↔54..57)與全部 51 對原廠對照;未知 id(UI 53/60/0xFFFF、internal 58/99)→ 0;STILL 不擴;關機寫回原廠;暖開機殘留指標先修再接;接在前一層(alpha 58↔53)上兩層都通;前一層撞號 → 我們 RELEASE;負對照:只有階段 2 時存檔把 55 寫進 flash |
| 階段 3 | hooks 已裝並記入 journal、關機全部回原廠;存檔後 flash 緩衝沒有 54..57、只動我們的 3 個字、RAM 放回;記錄寫進本 BIN(header 不變、沒建檔),下一次開機從「flash 狀態」還原並重發 8 個 `MV_QSMENU`;停用期間被改的格不蓋;記錄壞掉什麼都不還原;記錄只在變化時寫;檔案被換掉/刪掉不寫不建;錄影中延後記錄但照樣清;QR 讀取看到 0;兩個存檔層串接;靜態:`FUN_c0088660` 只有 C0088C60 一個呼叫者、QR 讀取只有 C053DBF8 |

## 風險

1. **私有字串 KEY**:編輯器清單的 KEY 欄是否經 `C05E5B58` 解析、能否吃 10 位數(≤ 2147483647),沒上機;不行就用 `out-stockkeys`。
2. **轉換器是所有 GUI 共用的單例**(341 個 slot 照原樣複製),複本錯一格會壞全部選單;測試只比對了整份位元組與 QS 兩個表。
3. 清單列數:只改了 `Visible` 上限;ListItem 是否依 CSV 列數複製、箭頭顯示的事件(31)都還是 32 列的值(右箭頭在第 32 項就熄,外觀問題)。
4. 占位用 0 = 拍攝模式:使用者若在停用期間自己把那格設成拍攝模式,再啟用時會被當成「我們的」放回。
5. 開機重發 `MV_QSMENU_QSn` 是從 loader 的入口(非 UI 執行緒)呼叫 `C0593F30`;`--no-emit` 可關。
6. 存檔 hook 在關機時寫 SD(同 res-custom / raw-view 的做法);寫失敗只影響記錄(下次開機那格是拍攝模式),flash 永遠乾淨。
7. 取檔處理器 C05E5BEC:原廠字或已有 claim 才 claim;別的 sup 沒 claim 就裝了(LUT 目前如此)時我們不 claim,關機不寫回由它負責。
8. QS 畫面那格(NBU 影格)沒做:選了我們的 id 的那格在 QS 頁上顯示什麼未定義(舊圖/空白)。
9. **階段 2 上機(10-28)第 2 格卡住**:圖/名字列停在拍攝模式是 `Icon01_CINE` 事件 range 0..48 的資料閘門(預期內);
   按鍵全無反應的原因未定(焦點掉進 List 容器 vs GUI 任務卡住),先用唯讀檢查分辨,救回用原廠 `menu SetFunction <internal>`
   (寫死第 2 格)。另:QS 頁 49 那格轉盤會改耳機音量(keys clip 保持)。全部見
   `projects/qs-touch/notes/QS_EDITOR_ID_PATHS.md`;定案前不要再讓 49..52 留在格子裡測試。
