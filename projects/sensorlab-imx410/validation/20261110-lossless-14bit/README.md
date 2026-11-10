# Lossless 0.3.2test：放行 14-bit（2026-11-10，離線）

Bei：「讓 lossless 支援 14bit」。**沒碰相機／USB／卡，沒 commit。** 設計與證據：
[fpSup/lossless/LOSSLESS_14BIT.md](../../../../fpSup/lossless/LOSSLESS_14BIT.md)；調查：[notes/LOSSLESS_14BIT.md](../../notes/LOSSLESS_14BIT.md)。

## 改動（`changes.diff`，`source-before/` → `source-after/`）

- `fpSup/lossless/control.c`：`capture_eligible` 收 10/12/**14**；新增列距閘 `((width×bits)>>3) & 3` → UNSUPPORTED。
- `fpSup/lossless/native/codec_job.c`：`fpl_codec_source_bytes` 同一條列距閘（回 0 → 不 hold，RAW）。
- `fpSup/lossless/native/workspace_layout.h`：註解。
- `fpSup/loader-v4/names_v4.py`（本機、未追蹤）：LOSS `0.3.1` → `0.3.2test`；`build_v4_lossless.py` 只改註解。
- 測試：`tests/test_control.py`、`tests/test_direct_control_arm.py`、`binding/binding_fixture.c`、
  `native/test_rec_workspace.py`、`test_codec_job.py`、`test_producer_facts.py`、`test_frame_hold.py`＋`frame_hold_fixture.c`
  （可設下一次 reset 的幾何／格式）、`test_workspace_layout.py`、`test_card_emulation.py`，新增 `native/test_lossless14_roundtrip.py`。
  以前把 14 當「不支援」例子的地方改用 16（或寬 1928 的 14）。
- 筆記：`fpSup/lossless/LOSSLESS_14BIT.md`（新）、`README.md` 加日期段、Sensor Lab `notes/LOSSLESS_14BIT.md` §5。
- **列距閘測試開關**（Bei 同日追加，見下節）：`control.h`（`FPL_TEST_PITCH` = ready bit 30）、`control.c`
  （閘加 `&& !(ready & FPL_TEST_PITCH)`；`fpl_can_enable` 主體移到 always_inline 的 `can_enable`，行為不變）、
  `codec_job.[ch]`（`fpl_codec_input.pitch_any`、`fpl_codec_source_bytes_test`、job `misaligned`）、
  `frame_hold.[ch]`（`pitch_test`、`pitch_forced`）、`card.c`（`pitch_test` 字、readiness 帶 bit 30、`start_hold` 帶進兩條 lane）、
  `build_card.py` FIELDS、`build_v4_lossless.py`（輸出 `layout.json` 與 `build.json` 的 `pitch_test_switch`）、`card_status.py`（印一行）；
  測試 fixture：`codec_job_fixture.c`（knob 20、field 119）、`frame_hold_fixture.c`（`fpl_fixture_pitch`、field 37）。
  `source-mid/` = 加開關之前的首版 0.3.2test 的 `control.c`／`codec_job.c`（給 `default_equivalence.py` 比）。
- **Sensor Lab 的 slqs.c／dcres.html 沒改**（理由見 LOSSLESS_14BIT.md §6-3）。merge-v4、worktrees 沒碰。

## 建置

```
python3 -B fpSup/lossless/build_v4_lossless.py --out <新的空目錄>
```

`build/Lossless_v0.3.2test.BIN`（含開關）：31,232 B，block 249,904 B，
**sha256 `a174779d57132975581cf08233b8d20a35748c82d3ff21bc4b1549be91f7c047`**，另有 `build/layout.json`、`build/build.json`。
兩次建置位元相同（build.json 也相同）。只換 payload，loader／AutoRun 不受影響。
首版（無開關，sha256 `7f1675c1…c07fc27f784`）留在 `build/first-no-switch/`，已被取代。

## 列距閘測試開關（Bei 2026-11-10 追加）

| | 位址（本 BIN） |
|---|---|
| state | 掃 0xC072E064..0xC072EFB4 找 `"FLPC"`（0x43504C46）＝記錄 +32；state = 記錄 +36 的字 |
| **開關 `pitch_test`** | **state + 0x2C41C**（u32；1 = 硬壓、其他 = 正式行為；開機 0、不存） |
| 計數（本段不對齊仍壓成功的幀） | state + 0x153D0（lane A）+ state + 0x2A640（lane B），每次 REC 歸零 |
| 該段實際用的值 | state + 0x153CC |

偏移每次建置會變，以該 BIN 的 `build.json` → `pitch_test_switch` 為準。用法與 1928 上機節：LIVE_PROTOCOL §3。
預設 0 與首版逐決策相同：`python3 -B default_equivalence.py` → 148,010 個決策一致。
⚠ Sensor Lab 寬一律 16 的倍數（`a16`），UI 錄不出 1928；上機那節要先有別的來源。

## 測試（全部 host／ARM 編譯／Unicorn，2026-11-10）

| 套件 | 結果 |
|---|---|
| `lossless/tests`（discover：control 36、ARM direct control 11（含開關）、ARM pipeline 8 …） | 79 OK |
| `lossless`：`test_v4_lossless test_card_emulation test_v3_lossless`（含 Unicorn 開關 → readiness） | 67 OK |
| `lossless/binding/test_binding` | 30 OK |
| `lossless/native` discover（全部） | 491 跑、466 OK；25 errors 全是 `test_native_variable`（它是要 `--seg0 --shared-probe` 參數的 CLI 腳本，discover 收進來就是錯，跟本次無關） |
| 其中 `test_lossless14_roundtrip`（真 6048×4040 14-bit 幀，LibRaw 逐樣本相同＋header_tag 3 個突變） | 6 OK，約 15 s |

開關的突變（都會被抓到）：control「忽略開關」「開關也放寬位深」；codec_job「忽略開關」「非 0 就算開」
「從不標 misaligned」「submit 不帶開關」；frame_hold「開關沒送到引擎」「hold 忽略開關（兩個方向）」「不對齊幀不計數」。
card 端由 Unicorn 直接呼叫卡裡編好的 readiness：開關 0/1/2/0xFFFFFFFF → 0x7E / 0x4000007E / 0x7E / 0x7E。

突變（新守衛都會被抓到）：control 的 14 位深（還原成 10/12 → test_control 41 failures）、
control 列距閘（14 與 10 各一，test_control 內建）、codec_job 列距閘（MutationTests `misreads 14-bit rows 8 mod 16`）、
round-trip 對 header_tag 的 `offsets from the old header`／`leaves Compression at 1`／`tables swapped`。

韌體事實（Unicorn 執行 `out/seg0_c0000000.bin`）：
`C0135D40(w,·,1)` 列距 = 14w/8（Sensor Lab 全部 1:1 14-bit 寬）、6056 寬多 2 bytes；
`C062FFF8` 寫 `300D006C = bits×w/16`、`300D0040` 位深選擇 1/2/0 = 12/14/10。

## 上機

未做。程序：[LIVE_PROTOCOL.md](LIVE_PROTOCOL.md)。離線唯一沒證到的一環：引擎讀 format 1 的位元排列 = DNG 的 MSB-first（看第一個壓縮幀即知）。
