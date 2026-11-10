# Lossless × Sensor Lab 真 14-bit（2026-11-10，離線）

問題（Bei）：「Lossless 應該能收 14bit 吧？他會丟掉嗎」。
結論：**不會丟、不會壞檔；目前出貨的 Lossless 看到 14-bit 就整段不壓，照原廠錄未壓縮 14-bit DNG。**
引擎本身做得到 14-bit，只差 control 的一道閘＋上機驗證。

標記：[驗] 讀碼／模擬實跑；[推] 推論。

## 0. 出貨的是哪份碼

- `fpSup/lossless/build_v4_lossless.py` 在 scratchpad 重建，sha256 `feae1253…3a7930`，**與 `fpSup/tools/merge-v4/inputs/v4-20261027/Lossless_v0.3.1.BIN` 位元相同** [驗]。
- 編進去的單元（`build_card.UNITS` 扣掉 `V3_ONLY`，加 `menu_row4.c`）：`control.c`、`frame_pipeline.c`、`native/` 的
  `workspace_layout / raw_workspace / rec_workspace / producer_facts / rec_hook / codec_job / header_tag / frame_hold /
  flush_site / play_decode / record_diag / menu_row4 / card.c` ＋ `card.S` [驗]。`ui_control.c` 不在裡面。
- README 說「rec_workspace 沒裝在 REC 呼叫點」是舊段落：測試卡／v4 的 `card.c` 的 `fpl_card_rec`（掛 C03A33C8）確實走
  `fpl_rec_hook_call → fpl_rec_workspace_prepare` [驗]。「錄影控制拒絕 14-bit」這句仍然成立（下面）。

## 1. 位數從哪來、真 14 時看到什麼

- **不看原廠位深設定，也不看 DNG tag。** 唯一來源是 `producer_facts.c`：REC 準備時
  `C0437140(&obj, 2, settings, 3)` 取描述子，`obj[8]`（+0x20，Sigpro 格式碼）經 `format_bits` → 0/1/2/3/4 = 12/14/16/10/8 [驗]。
- Sensor Lab 真 14（1:1，平面碼 +0x84 = 8）：res-lab `20261004-raw14/R86_DESCRIPTOR_AUDIT.md` 用實際 card 在模擬裡跑原廠
  描述子建構，平面碼 8 → 描述子 +0x20 / +0x24 **都是 1**，strip bytes = packed-14 [驗，舊版 Sensor Lab、錄影分支的參數]。
  所以 Lossless 看到的是 **format 1 → bits 14**，雖然原廠設定仍是 12。
  - [推] Lossless 的查詢參數（mode 2、kind 3）跟 R86 用的錄影分支不同，沒單獨在現行 v4 Sensor Lab 上跑過。
    但不管查到 0 還是 1，結果都安全（見 §2 第二道閘）。
- 12-bit 容器配方（RWZM／CRCT 縮放的 14-bit AD）平面碼 (7,7) → format 0 → Lossless 當 12-bit 正常壓縮 [推，沿用 APPLY_DESIGN §13]。

## 2. 14-bit 時的結果

兩道閘，都是「不壓、照原廠錄」，不會用錯位深去壓：

1. **REC 時**：`control.c capture_eligible` 只收 `bits == 10 || 12` → `FPL_UNSUPPORTED`；`rec_workspace_prepare`
   已先呼叫過原廠 `C03A2438`，回 0 但 `native_result` 非 0 → `card.c` 走 `rec_raw`：**回傳原廠結果、整段原廠 RAW**，
   不配置 workspace、不起 hold、不要 IFD tag（`tag_want` 保持 0）[驗 碼]。
2. **每幀**：就算 REC 時查到的是 format 0，`frame_hold.c eligible()` 用 `fpl_producer_facts_match` 比對每幀
   `frame+0x10` 描述子的寬／高／格式，format 1 ≠ 0 → 該幀不 hold、原樣送出 [驗 碼＋`test_frame_hold`「a frame of another format is not held」]。
   這情況只是白配一份 12-bit 尺寸的 workspace。
- 編碼器不會被餵錯位深：`codec_job.c` 直接把 `seen.format` 當引擎位深碼（Sigpro 0..3 與 C062FE40 0..3 同序）[驗]。

**模擬**（scratchpad `ll14/`，用出貨原始碼＋`rec_hook_fixture.c` 改出 format 1 與 packed-14 raster，readiness 設成卡上斷言的 0x7E）[驗]：

| 案例 | dispatch | 原廠 prepare | native_result | admitted / refused | last | 配置 |
|---|---|---|---|---|---|---|
| 12-bit 1936×1090 | 1 | 1 次 | 1 | 1 / 0 | OK | 有 |
| 14-bit 3024×2010 | 0 | 1 次 | 1 | 0 / 1 | UNSUPPORTED | 無 |
| 14-bit 4176×2174 | 0 | 1 次 | 1 | 0 / 1 | UNSUPPORTED | 無 |
| 8-bit | 0 | 1 次 | 1 | 0 / 1 | UNSUPPORTED | 無 |

（fixture 的 raster 只模擬 format 0/1，所以 10-bit 那列不具意義，未列。）
既有測試全過：`test_rec_workspace`（含 `test_14bit_budget_does_not_bypass_control_rejection`）16、`test_producer_facts` 23、
`test_frame_hold` 157、`test_codec_job` 38、`tests/test_control` 33、`test_v4_lossless` 10。

使用者看到的：Lossless 開著、錄真 14 → **檔案正常、但沒壓縮、沒有任何提示**。

## 3. 硬體能不能 14-bit

- 能。原廠靜態 DNG 就是 **14-bit Compression=7、256×256 tile**（`_SDI0011.DNG` 6064×4042，WhiteLevel 16383）
  [驗，research/imaging-hw/notes/HW_LOSSLESS_JPEG_CODEC.md、RAW_COMPRESSION_RESEARCH.md]。
- 引擎位深分支 `FUN_c062fff8`：code 0/1/2/3 = 12/14/16/10，其他值直接失敗（沒有 8-bit）[驗，LOSSLESS_DEVELOPMENT_SUMMARY.md]。
- 速度約 1 px/clock、與位深無關；但 14-bit 壓縮比較差（靜態樣本 1.67–2.08:1，12-bit 約 2.5:1）[驗 同上]。
- Julien R120 曾在錄影做 RAW14＋壓縮（`C04A1788` 強制 DATA+），R16x 拿掉、只留 12-bit [驗 upstream CHANGELOG]；拿掉原因沒寫。

**要正式支援 14-bit 需要：**
1. `control.c capture_eligible` 放行 14（producer_facts、codec_job、workspace_layout 已經有 14 的路）。
2. 確認 Sensor Lab 平面碼 8 的 BUFA 輸出就是引擎吃的 packed-14 列距（含 `C0135D40` 的尾列規則、`codec_job` 的 source_bytes 檢查）[推，TRUE14_2X_RESEARCH 有 packed14／u16 疑問]。
3. 16 MiB 單幀上限與輸出緩衝要用 14-bit 壓縮比重算（大畫幅可能超）。
4. 測試：host 加 14-bit 幾何的 codec_job／frame_hold 案例＋突變；上機錄一段 1:1 真 14，解 LJ92 tile 與未壓縮同場景比對逐位元、Resolve 開檔、BlackLevel（Sensor Lab 的 H_BLK 回 14）。
5. 這是改 Lossless 產品行為，要 Bei 定。

## 4. MB/s 格的 LL

**不對。** `qs/slqs.c:984` 與 `preview/dcres.html:423` 只在 `b == 8` 時顯示 `LL —`，真 14 會顯示 `LL ~N`，
但實際上 Lossless 會整段不壓。建議改成 `b == 8u || b == 14u`（網頁同步），並更新 `test_slqs.py` 那兩條突變。
BITDEPTH_8_10.md 的 open question 5 已記過這件事；本筆記確認出貨版行為。若之後 Lossless 放行 14，再拿掉。

## 5. 後續：Lossless 0.3.2test 放行 14（同日，離線）

`control.c` 放行 14＋列距閘（寬 ≡ 8 mod 16 的 10/14-bit 拒絕：引擎列距 `bits×w/8`、點陣列補到 4 bytes）。
真幀 6048×4040 round-trip 逐位元（LibRaw），未上機。細節：`fpSup/lossless/LOSSLESS_14BIT.md`；
紀錄與上機程序：`validation/20261110-lossless-14bit/`。
§4 的建議（`b == 14` 顯示 `LL —`）在 0.3.2test 不需要了；格子的 14-bit 比率（+2 bpp）已對，
但 `LL_MAX_FRAME` 16 MiB 規則對 v0.3.x 不成立，留給上機後決定，本次沒改 slqs.c／dcres.html。
