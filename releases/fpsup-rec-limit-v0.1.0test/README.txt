================================================================
 Recording time limit  fpsup-rec-limit-v0.1.0test
 SIGMA fp Ver.5.02 only -- Loader v3 card
================================================================

WHAT IT IS

  Raises the two-hour limit on one recording to eight hours.

  The fp stops a movie after two hours. That limit is two numbers in
  the firmware's data, not code, and this card changes those two
  numbers to 28800 s (8 h). Everything else stays as stock: heat,
  free space, a card that stops taking writes and the battery still
  stop recording exactly as before. Nothing is written to the camera;
  take the card out and the two hours are back after the next
  power-on.

  - No menu entry: it is in effect from the moment the card loads.
  - It works for both recording paths: H.264 (MOV) and CinemaDNG.
  - If another card product already holds those two numbers, this
    one is skipped at start and nothing is changed.

  中文:
  把單次錄影的兩小時上限提高到八小時。

  fp 錄影到兩小時就停。那個上限是韌體裡的兩個數字(資料,不是程式碼),
  這張卡把這兩個數字改成 28800 秒(8 小時)。其他一切照原廠:溫度、容量、
  卡片寫不進去、電池,都照原來的方式停止錄影。不寫入相機;拔掉卡、下次
  開機,兩小時就回來了。

  - 沒有選單項目:載入後即生效。
  - MOV(H.264)與 CinemaDNG 兩條錄影路徑都有效。
  - 若卡上其他產品已經佔了那兩個數字,本產品會在啟動時被跳過,什麼都不改。

HOW TO USE

  Copy AutoRun.txt and the fpSup folder to the root of the SD card and
  start the camera.  To combine with other fpSup products released for
  Loader v3, copy their fpSup folders over this one: every product
  carries the same LOADER.BIN and UI frames, and its own 46RECLM.BIN.

  Upgrading from an older (single fpSup.BIN) card: delete the old
  fpSup.BIN from the card root.  A card from before Loader v3 cannot be
  mixed with this one.

  Nothing to set. Record as usual.

WHAT CHANGED

  - First release.

WHAT HAS BEEN VERIFIED

  On the camera (SIGMA fp Ver.5.02):

  - A build for 60 s stopped at exactly 60 s, and one for 900 s at
    exactly 900 s. Those two are the proof that these two numbers are
    the cap, and that the new value takes effect.
  - The 8 h value recorded past two hours: REC counter still running
    at 2:01:09, then a 4:02:54.6 MOV (1920x1080 / 23.976, 349,440
    frames, 109.4 GB) and a 6:06:25.9 CinemaDNG sequence (527,133
    frames, 1.712 TB). Both stopped because the medium was full, not
    because of the clock. At the full medium the camera did not
    freeze: the display went to sleep and the camera stayed usable.

  Offline (this release's own bytes, MANIFEST.txt hashes): the Unicorn
  tests check the header, both patched words, the journal holding the
  stock 7200 s, the loader writing it back at power-off, no task and no
  file write, and SL_RELEASE with nothing written when another sup
  already holds either word.

  Not verified on the camera for this release: UHD and frame rates
  other than 1920x1080 / 23.976, and a CinemaDNG run at a frame rate
  high enough to reach the patched frame budget before the card fills.

  One older build stopped a recording at 108 min (2026-10-25) with the
  value in place; it has not been reproduced (see
  projects/rec-limit-sup.md, "Open"). Nothing here explains it yet, so
  do not assume the cap is gone under every possible sequence of
  events.
