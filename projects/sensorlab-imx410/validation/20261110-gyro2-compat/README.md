# Gyro2 0.2.1 × Sensor Lab-IMX410 0.0.5test 相容性(離線,2026-11-10)

沒碰相機、沒改產品原始碼。證據等級:**[驗]** 讀了程式碼、跑了計算或有實拍資料;**[推]** 推論。

## 先更正題目的前提

**Gyro2 不寫 `\GYRO\*.json`,也不寫 `.gcsv`。** [驗] `projects/gyro2-sup/src/gyr2.S`(v4 = `-DGYR2_V4` +
`gyr2_row4.c`,`fpSup/loader-v4/ports.py`)只有兩種寫入:每張 CinemaDNG 的 MakerNote tag `0x4653` 裡的 FSG2 區塊,以及
設定列寫回自己的 BIN。json 與 gcsv 是舊的 Gyro1(`fpSup/gyro/gcsv_json.S`)的輸出,而 Gyro1 不是 v4 sup
(`names_v4.py` 裡沒有它)。

Gyro2 每幀存的是原始值:`mode`、`hmax`(TIM +4)、`read_w`(META +4)、`lines`(META +8)、`bin_h`(META +0x44)、
`bin_v`(META +0x48)、校正焦距,以及陀螺、水平儀和 Vd 事件。讀出時間、裁切範圍、focal_px 和 fps 都由外掛
`tools/gyroflow-plugins/common/src/fsg2.rs` 算出來:

- 讀出時間 = `hmax × lines / 72 MHz`
- 裁切 = `(min(w × bin_h, 6000), min(lines × bin_v, 4000))`,置中
- focal_px = `DefaultCrop 寬 × mm / (35.9 × crop_w / 6000)`
- fps = DNG FrameRate(0xC764)

所以下面判定的是「相機寫的原始值,加上外掛的算法」。

## Sensor Lab 下相機拿到的是誰的列 [驗]

- `F_TIMING 0xC0320FC8` 呼叫 `C0320BA0`,`F_GEOM 0xC0321028` 呼叫 `C0320B38`(反組譯),兩者正是 Sensor Lab hook 的
  `lk_tim`、`lk_meta`(`apply/ap.c`)。所以模式 230/231 讀到的是 Sensor Lab 自己的 TIM/META 列,也就是 `smc.create(plan)`。
  `core.c` 與 Python 逐位元相同(`core/test_core.py`)。
- `SENSOR_MODE_FN 0xC032C720` 會轉呼叫 `C03212F8`(目前模式)。Gyro2 在**第一幀**的 notify 才讀(`frame` → `mode_info`),
  不在按下 REC 的瞬間讀,所以沒有 Gyro1 那種模式切換的競爭。
- **實拍端到端吻合**(`validation/20261102-hirate-playback-diagnosis/media`,SL v0.7.x + Gyro2 build 6):
  A001_273/274/275 的區塊是 `mode 231 hmax 330 w 2016 lines 672 bin 3/3`,DNG FrameRate 是 1200000/4147 = 289.366。
  `recipes.py` 對同一個 recipe(3x6fast,6048×4040 → 1008×672)算出的 smc 列是 hmax 330、vmax 754、w 2016、h 672、
  +0x44 3、+0x48 3,fps 289.3658,**逐欄相同**。0.0.5test 的 lookup hook 與 smc 規則沒變;vertical margin 只動 RWZM 和 rec,
  不動 TIM/META。

## 各項判定

| # | 項目 | 判定 | 依據 |
|---|---|---|---|
| 1 | 讀出時間(RS) | **正確**(比實際記錄的列多 0~1.5 %) | [驗] 見下表。META h = `out_h`(感光元件真正送進 ISP、記錄所用的列),不含 over 的空列和 V3 margin |
| 1b | Sensor Lab UI 的 `rs` 與 Gyro2 差 1.3~5 % | 不是 Gyro2 的錯 | [驗] SL 的 `rs = hmax × receiver_lines`,包含畫面下方 `over` 19~52 列空列和 V3 上方的 margin;畫面內的捲簾只算記錄到的列 |
| 1c | 舊 json 的 `frame_readout_time` | 不適用 | Gyro2 不寫 json |
| 2 | fps | **正確** | [驗] 外掛用 DNG FrameRate,而 SL 有 hook recrate `C00C9BD0`(A001_273 是 289.366 = 72e6/(330×754))。Gyro2 定 tag 大小時也呼叫 `C00C9BD0`,拿到真實格率(tag 565 B = 4 幀 × 9 筆,與計算相同)。Vd 間距 8.67 筆,預期 8.638,外掛的 1 % 檢查會過。gcsv 的「×1000」不適用 |
| 3a | crop 寬 / focal_px | **正確**(±1 %,跟原廠一樣的近似) | [驗] `+0x44` = 感光元件水平合併 `mh`,`w × mh` ≈ DC 寬(CRCT 是 ISP 端,不影響涵蓋範圍)。focal_px 與真值的比 = (vis/rec) × (涵蓋寬/min(crop_w,6000)):UHD −0.41 %、OG 2x2 +0.27 %、3x2/3x3 0.00 %、V3 1x3 −0.87 %、14b +0.53 %、3x6 −0.79 % |
| 3b | crop 高 | **錯**(只影響 metadata) | [驗] Gyro2 把 META `+0x48` 當垂直合併數,但它其實是 `vadd`(smc 規則:`1→1, 2→2, 3→2, 6→3`),真正的 vbin 在 `+0x50`。3x3、1x3、2x3 少 1/3,3x6 少一半。**原廠 3x3 模式 8、134 也一樣錯**,不是 Sensor Lab 造成的,只是 SL 讓更多 recipe 走到 v3/v6。外掛只把 crop_h 放進 CaptureArea(IBIS 樞軸用),fp 沒有 IBIS,所以 [推] 對防震結果沒有影響 |
| 4a | 模式偵測 | **正確** | [驗] 見上;slot 不會在錄影中切換(`ap_commit` 在 `ap_busy()` 時不做) |
| 4b | 方向 / CINE 模式 hook | 不適用 | [驗] Gyro2 的 orientation 欄位固定是 0、沒有模式 hook(`FUN_c0058308` 是 Gyro1 的)。直拿方向與 SL 無關 |
| 4c | 開始/停止、時間基準 | **正確**,但有一個 Gyro2 自己的 bug,見下 | [驗] 273/275 的區塊首尾相接,frame_seq 從 0 開始,第一幀有 F_FIRST,而且有 Vd 事件。SL 現行版不丟幀(v0.7.26 的 drop 已拿掉) |
| 4d | 時間軸跑到幀前面(A001_274) | **錯**(Gyro2) | 現象 [驗];成因 [推]。見下 |
| 4e | A001_276–284 沒有 GTAG | **未知** | [驗] MakerNote 97 個 tag,273–275 是 98 個,也就是 tag 根本沒加。276 和 275 中間隔了 31 分鐘,很可能換了開機或卡,或 Gyro2 那列是 OFF。檔案裡分不出是哪一種 |
| 4f | hook 共存 / SL_EXCL | **正確** | [驗] Gyro2 只 claim `C050D4C8`(CHAIN)和 `C0125480`(EXCL,Vd),SL 的 ~40 個位址都不碰這兩個。Gyro2 的 tag observer 掛 Subject,不改程式碼。兩邊都沒 hook `0xC03790B8`;SL 的 `C0379180` 只在 REC-delay TEST build 裡有。11-08 實機 LOAD.LOG:Gyro2_v0.2.1 LOADED、claims 2,與 SL 0.0.3test 同卡 |
| 4g | 記憶體 / pool | **正確** | [推] 兩邊都只用 loader 給的自有 block(Gyro2 ≈ 57 KB BSS),沒有固定位址,也不用 pool |
| 4h | DNG 表頭空間 | **正確**(餘量小) | [推] SL 不加 tag。最壞情況是 14b 約 19 fps 開 Lossless:GTAG ≈ 3.5 KB,加上原廠 0x1339D、LinTable 0x20C、Lossless ≤ 2252 B,約 85.0 KB,上限是 0x15400(87,040 B),剩約 2 KB |

### RS / 裁切數字(`recipes.py`,輸出在 `recipes.out.txt`)

| recipe(0.0.5test 的 pick) | hmax | META w×h | +44/+48/+50 | Gyro2 RS | 記錄列 RS | SL `rs` | Gyro2 crop | 實際涵蓋 |
|---|---|---|---|---|---|---|---|---|
| UHD 1x1 12b 3856×2170 | 445 | 3856×2170 | 1/1/1 | 13411.8 µs | 13411.8(0.00 %) | 13733.2 | 3856×2170 | 3856×2170 |
| OG 6048×4040 → 3024×2020,2x2 | 445 | 3024×2014 | 2/2/2 | 12447.6 | 12447.6(0.00 %) | 12670.1 | 6000×4000 | 6048×4028 |
| 2K 3x2(6048×3402 → 2016×1134) | 445 | 2016×1702 | 3/2/2 | 10519.3 | 10457.5(+0.59 %) | 10680.0 | 6000×3404 | 6048×3384 |
| 2K 3x3(同上) | 445 | 2016×1134 | 3/**2**/3 | 7008.8 | 7008.8(0.00 %) | 7169.4 | 6000×**2268** | 6048×3402 |
| 2K 1x3 V3(→ 2032×1090) | 445 | 6048×1134 | 1/**2**/3 | 7008.8 | 6947.3(+0.88 %) | 7373.4 | 6000×**2268** | 5995×3372 |
| 6048×4040 1:1 14b | 911 | 6048×4040 | 1/1/1 | 51117.2 | 51117.2(0.00 %) | 51775.2 | 6000×4000 | 6048×4040 |
| 3x6fast → 1008×672(A001_273 這一類) | 330 | 2016×672 | 3/**3**/6 | 3080.0 | 3034.2(+1.51 %) | 3171.7 | 6000×**2016** | 6048×3972 |

「記錄列 RS」= hmax × rec_h × Zv/1024 ÷ 72 MHz,也就是 DNG 實際涵蓋的列的捲簾時間。
各 recipe 的 fps = 72e6/(hmax × vmax),跟 Gyro1 的 `hmax(vmax−1)+tail` 一樣,因為 SL 的 tail = hmax。

## 錯的兩項:原因與最小修法(只寫,沒做)

### A. crop 高:讀錯欄位(Gyro2)

- **期望值 vs 算出來的值**:3x3 是 6048×3402 vs 6000×2268;V3 1x3 是 5995×3372 vs 6000×2268;3x6 是 6048×3972 vs 6000×2016。
- **原因**:`mode_info` 讀 `ldrh r6, [r0, #0x48]`,那個欄位是 vadd,不是 vbin。
- **修法(Gyro2 相機端,1 個立即數)**:`+0x48` 改成 `+0x50`。順便把水平改讀 `+0x4C`;在原廠 70 個模式與 SL 的列上,`+0x4C` 都等於 `+0x44`。外掛不用改,區塊格式也不變。
- 外掛端修不了:vadd 2 可能代表 vbin 2,也可能是 3。
- 優先度低:fp 沒有 IBIS,這個欄位只進 metadata。

### B. 串流位置超過幀的 mark 之後就一路往前跑(Gyro2,在 SL 289 fps 下實拍出現)

- **證據** [驗]:A001_274 第 115 幀的 `base_idx` 是 2679,同一設定的 A001_273 是 1255(預期約 250 + 114 × 8.64 ≈ 1235)。
  `frame_mark` 是 64159,也就是 u16 的 −1377:這個區塊的開頭在幀的 mark **之後** 1377 筆(0.55 s),`n` 停在上限 36,而且 flags 是 0,沒有標 LOST。
- **機制** [驗,程式碼]:`frame` 用 `sub r2, r6, r7; cmp r2, r1; addhi r6, r7, r1` 給 n 設上限。一旦 `V_PREV > mark`,差值是負數,
  無號比較當成「超過上限」,於是 r6 = r7 + 36。之後每一幀都往前多走 36 − 8.6 ≈ 27 筆,再也追不回來;
  ≥ W 的部分從 ring 以模數讀出,讀到的是舊的一圈。從 1377 ÷ 27 推算,大約從第 65 幀開始。
- **觸發** [推]:snapshot 與 drain 都會用「距離上次 drain 的時間」補整圈,補的圈數可能不一致,一旦 mark 往回退就觸發。
  為什麼是高格率、高負載(SL 289 fps)才出現,沒有證實。
- **最小修法(Gyro2)**:在 `40:` 的上限比較之前加一道保護:`subs r2, r6, r7` 為負時,令 `r7 = r6`(空區塊)並 `orr r5, #F_LOST`,讓串流重新對齊 mark,而不是往前衝。另外要查 snapshot 和 drain 的補圈算法是否一致。
- **影響**:發生之後那段的陀螺時間錯 0.5 秒以上,而且資料是舊的,外掛照用不會報錯。

## 要上機確認的項目(Gyro2 要在 SupManager 重新開啟,由 Bei 決定)

最小程序(SL 0.0.5test + Gyro2 0.2.1,錄影中不碰 USB,停錄等 10 s 以上):

1. 3x6fast 1008×672,約 289 fps,錄 3 段、每段約 5 s,一邊錄一邊慢慢水平搖。目的:重現 B,同時看 276–284 那類小畫面是否有 GTAG。
2. 2K 3x3(6048×3402 → 2016×1134)錄 1 段 5 s,對著直立邊緣橫搖。目的:用 `fpSup/gyro/rolling_shutter.py` 實測 RS,應約 7.0 ms。
3. 6048×4040 1:1 14b、Lossless ON,錄 1 段 3 s。目的:確認表頭空間與 GTAG 都在。
4. 每段都抓全部幀的表頭(`projects/gyro2-sup/fetch_heads.py`),再跑
   `python3 -B decode_evidence.py --take <段落資料夾>`。
   通過條件:每幀都有區塊、`mark` 不為負、區塊首尾相接、mode/hmax/w/lines 與 `recipes.py` 相同、Vd 間距 = 2499.466/fps。
5. 外掛載入其中一段(`cargo test real_fp_clip_dir -- --ignored`,`FP_CLIP_DIR=...`)不報 Vd/fps 錯誤。

## 檔案

- `recipes.py`:SL recipe → smc 的 TIM/META → Gyro2 會存的值,與 SL 的 rs、記錄列、實際涵蓋比較。輸出在 `recipes.out.txt`。
- `decode_evidence.py`:解 DNG 裡的 FSG2(用 `projects/gyro2-sup/fsg2.py`)。`--take DIR` 檢查一整段。11-02 實拍的結果在 `evidence.out.txt`。
