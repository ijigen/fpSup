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

## 2026-09-25: the bug, and what replaced these

The bug was in gyro v1.13 alone: after an ordinary power-off the next boot
froze with any card in the slot. Two causes, both fixed in e87eae2 -- the gyro
cursor started at 0 instead of "unarmed", and the hooks' bodies (in the pool
since v1.13) could fire while the camera shut down; they are now taken out at
power-off. The fix shipped as **fpsup-gyro-v1.13.1**, and fpSup-Merge bundles
it. The other three were withdrawn with it but were not implicated: a card with
only the shared stage2 did not freeze.

問題只在 gyro v1.13:一般關機後,只要插著卡,下次開機就凍結。兩個原因都在
e87eae2 修掉 —— 游標初值是 0 而不是「未武裝」,以及 hook 本體(v1.13 起在池裡)
在關機途中仍會觸發,現在關機時會先拆掉。修正版是 **fpsup-gyro-v1.13.1**,
fpSup-Merge 已改為打包它。另外三個是一起撤回的,但與此無關:只帶共用 stage2
的卡不會凍結。
