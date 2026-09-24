# 2026-09-24 撤回 / Withdrawn

A major bug was found, so these four releases and the fpSup-Merge page that
bundled them were withdrawn on 2026-09-24:

| withdrawn | back to |
|---|---|
| fpsup-gyro-v1.13 (+ `fp-gyro-sup-v1.13.zip`) | fpsup-gyro-v1.12.1 |
| fpsup-usbshell-v3.2.0 | fpsup-usbshell-v3.1.1 |
| fpsup-og3k-v0.2.5a | fpsup-og3k-v0.2.4a |
| fpsup-og2k-v0.1.2a | fpsup-og2k-v0.1.1a |

fpSup-Merge (`tools/card-composer/`) is back to the page from before
84ebcff, which bundles the four versions on the right.

The bytes are kept here unchanged, for investigation. Their git tags were
deleted, because a tag exists only for a folder in `releases/`
(releases/TAGS.md). Do not use these cards.

發現重大 bug,以上四個版本與內含它們的 fpSup-Merge 頁面於 2026-09-24 撤回,
退回右欄的版本。檔案原樣保留在這裡供調查;tag 已刪除。**請勿使用這些卡。**

## 2026-09-25

The bug was gyro v1.13's alone; it is fixed in **fpsup-gyro-v1.13.1**. What it
was: [HOOKS_AT_POWER_OFF.md](../../HOOKS_AT_POWER_OFF.md).

The other three were withdrawn with it but were not implicated, and are back in
`releases/` unchanged, tags restored: **fpsup-og3k-v0.2.5a**, **fpsup-og2k-v0.1.2a**,
**fpsup-usbshell-v3.2.0**. fpSup-Merge is the 84ebcff page again and bundles
them with gyro v1.13.1. Only gyro v1.13 stays here.

問題只在 gyro v1.13,修正版是 **fpsup-gyro-v1.13.1**;原因見
[HOOKS_AT_POWER_OFF.md](../../HOOKS_AT_POWER_OFF.md)。另外三個與此無關,已原樣搬回
`releases/` 並補回 tag;fpSup-Merge 恢復 84ebcff 的頁面,打包它們與 gyro v1.13.1。
這裡只剩 gyro v1.13。
