# fpSup-Merge v4

Loader v4 的合併頁(2026-10-24 使用者指示另開；`tools/merge-v3/` 與網站入口不動)。

```text
python3 -B tools/merge-v4/build_inputs_v4.py --out tools/merge-v4/inputs/v4-YYYYMMDD   # 新快照(不覆蓋舊的)
python3 -B tools/merge-v4/build_catalogue_v4.py                                       # 寫 index.html
node tools/merge-v4/test_merge_v4.js
node tools/merge-v4/test_ui_v4.js
python3 -B -m unittest discover -s tools/merge-v4 -p test_version_history.py
```

和 v3 頁的差別：
- **產品全部來自一份快照** `inputs/v4-20261027/`(2026-10-27:Gyro2 版號改 0.2.1;10-25 那份起：選單掉鍵修正、頁尾固定、sup 檔名帶版本):`build_inputs_v4.py` 跑各產品自己的 v4 builder
  (`loader-v4/ports.py`、`ports_jose.py`、`lossless/build_v4_lossless.py`、`screenflip/build_v4_flip.py`、
  `projects/rawview/build/build_v4_rawview.py`、`projects/open-gate/build/res-custom-v4/build_v4_rescustom.py`),
  manifest 記每個檔的 size/sha256 與 builder 原始碼雜湊。v3 的 release 只當版本紀錄，不讀產品。
- **fpSup 頁一律附上**(使用者：關掉的話 Lossless 開關、Res-Custom 檔案頁就沒地方用):
  每張卡都有 `fpSup/SUPMGR.BIN`、`fpSup/UI/FPSUP.BIN`、`fpSup/UI/SUPMGR.BIN`;勾選框顯示為已勾、不可取消。沒有 v3 的 `ALLSUPS.BIN`。
- **開機檔**:`loader-v4/build_v4.py` 的 `boot_card(splash, instant, fast, slim, ui)`,四組(瞬間啟動 × 快速啟動)。
  預設瞬間啟動開、快速啟動關。LOADER.BIN 尾端是空的停用清單(FSDS)。
- 檔名沒有 v3 的數字前綴(DSQZ、FCAP、FLIP、GYR2、LOSS、RAWV、RESCUS、SHELL、STOPFX、TAPZ、ULWR),載入順序 = 檔名順序；
  頁面自檢改成 FSB4 檔頭(48 B)。Loader v4 不載入 v3 sup,README 提醒先刪卡上整個舊 `fpSup`。

驗證範圍(2026-10-24;**`b` 快照的 LOADER、SUPMGR、RESCUS、GYR2、LOSS 已改過，下面「與上機卡相同」只對第一份快照成立**):
- 全選 zip 的每個 sup、RCD、UI 檔與當天上機那張卡逐位元組相同(`fpSup/loader-v4/README.md`「已上線 sup 的 v4 第一次上機」),
  只有開機檔依勾選不同(上機卡多了開機計時標記)。例外:`SHELL.BIN` 是帶 burst15 的移植版，上機時用的是卡上原本那份。
- 未上機：錄影(ULWR、Gyro2 每幀、Lossless 壓縮)、快速啟動組合、Jose 兩個功能本身、ScreenFlip 實際翻轉。
- 本機頁面，未 commit、未發布；網站入口仍指向 merge-v3。
