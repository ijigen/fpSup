================================================================
 fpsup-raw-view  v0.1.0test
 SIGMA fp — RAW monitoring: the LCD shows what 12-bit CinemaDNG records
================================================================

English below the line of dashes; 中文在後面。

WHAT IT IS

  Adds "RAW" as the 17th row of the COLOR menu. With it selected
  and the camera recording CinemaDNG 12-bit, live view shows the
  RAW the camera is about to record, not a finished picture:

  - Standby uses the recording gain. What clips on the screen
    clips in the DNG, and what does not, does not.
  - Per ISO, sensor saturation is display white and the official
    shadow floor is display black.
  - Two curves, chosen with the box on the right of the RAW row:
      SA (-5)  Latitude, Stop Aligned: every stop the same height,
               so screen level reads as stops above the floor.
      GA (+5)  Latitude, Gray Aligned: the "LA - SIGMA Rec709"
               curves of SIGMA fp Rec709 LUT & Operations Guide v3.
  - Saturation on the AEL page, 0..5, sets how much of the
    colour-calibration matrix is applied (0 none, 5 all of it).
    Above 0 the same matrix is also written into the CinemaDNG
    ColorMatrix tags; the raw pixel data is never changed.
    Contrast and Sharpness are held at 0 while RAW is on.

  The recorded raw data is not altered: RAW on against RAW off,
  same scene, gave a pixel ratio of 0.998 and the same count of
  saturated pixels.

  **Firmware Ver.5.02 only.** Test build.

TWO CARDS IN THIS FOLDER

  Ordinary card (this folder):  AutoRun.txt + fpSup.BIN
      Every start runs the AutoRun: a progress bar, then the
      banner fpSup-RAW-v0.1.0test!

  Fast Start 2 (FastStart2/):   AutoRun.txt + fpSup.BIN + FPSUPUI/
      After the first start, a restart with the power switch loads
      about 1.4 s after power-on without the AutoRun and shows the
      four-box screen; a cold start runs a short AutoRun. It stores
      the loader in the camera's settings block, which survives a
      battery pull. Power off with the USB cable UNPLUGGED -- with
      it attached the next start is always a cold one.

  The two zips hold the same files, one card each.

INSTALL

  1. Copy the card's files to the ROOT of the SD card the camera
     boots from (for Fast Start 2, the FPSUPUI folder too).
  2. Start the camera with the USB cable unplugged.
  3. Recording format CinemaDNG, 12-bit. COLOR menu -> row 17, RAW.

LIMITS

  - CinemaDNG 12-bit only. MOV and 8/10-bit are not supported.
    UHD records 8-bit CinemaDNG: in UHD the screen jumps about one
    stop brighter when recording starts.
  - The RAW choice is not kept across a power-off: the colour mode
    comes back as OFF; select RAW again.
  - Choosing OFF in Quick Set does not leave RAW; choose OFF (or
    another mode) in the COLOR menu.
  - Auto exposure can meter up to 1-2 EV darker than stock in
    scenes with bright highlights: live view now has the highlight
    room 12-bit recording has.
  - Not part of fpSup-Merge; it cannot be combined there.

REMOVE

  Delete the files (or take the card out) and switch the camera off.
  Every firmware word the card changed is written back as the
  camera powers off. A Fast Start 2 loader left in the settings
  block does nothing without its card.

----------------------------------------------------------------
 fpsup-raw-view  v0.1.0test
 SIGMA fp —— RAW 監看:螢幕顯示 12-bit CinemaDNG 實際錄到的東西
----------------------------------------------------------------

這是什麼

  在 COLOR(色彩模式)選單加上第 17 列「RAW」。選到它、而且錄影格式是
  CinemaDNG 12-bit 時,即時影像顯示的是即將錄下的 RAW,而不是修飾過的畫面:

  - 待機使用錄影時的增益:螢幕上過曝的地方 DNG 也過曝,沒過曝的就沒有。
  - 依 ISO,感光元件飽和 = 顯示白,官方暗部底線 = 顯示黑。
  - 兩條曲線,用 RAW 列右側的框選:
      SA(-5) Latitude — Stop Aligned:每一檔一樣高,
             螢幕亮度可以直接讀成「距暗部底線幾檔」。
      GA(+5) Latitude — Gray Aligned:依 SIGMA fp Rec709 LUT &
             Operations Guide v3 的「LA - SIGMA Rec709」曲線。
  - AEL 頁的飽和度 0..5 = 校色矩陣套用的程度(0 不套、5 全套)。
    大於 0 時同一組矩陣也寫進 CinemaDNG 的 ColorMatrix;RAW 像素本身不動。
    RAW 時對比與清晰度固定為 0。

  錄下的 RAW 資料不會被改動:同一場景 RAW 開與關各錄一段,
  像素比值 0.998,飽和像素數相同。

  **僅限韌體 Ver.5.02。** 測試版。

這個資料夾裡有兩張卡

  一般卡(本資料夾):     AutoRun.txt + fpSup.BIN
      每次開機都跑 AutoRun:進度條,然後顯示 fpSup-RAW-v0.1.0test!

  Fast Start 2(FastStart2/): AutoRun.txt + fpSup.BIN + FPSUPUI/
      第一次開機之後,撥電源開關重開時約 1.4 秒就載入、不跑 AutoRun,
      顯示四格畫面;冷開機跑短版 AutoRun。會把 loader 存進相機設定區
      (拔電池也會留著)。關機時請**拔掉 USB 線**——插著線關機,下次一定是冷開機。

  兩個 zip 裡是同樣的檔案,各一張卡。

安裝

  1. 把卡的檔案複製到相機開機用的 SD 卡**根目錄**
     (Fast Start 2 要連 FPSUPUI 資料夾一起)。
  2. 不插 USB 線開機。
  3. 錄影格式選 CinemaDNG 12-bit,COLOR 選單 → 第 17 列 RAW。

限制

  - 只支援 CinemaDNG 12-bit。MOV 與 8/10-bit 不支援。
    UHD 錄的是 8-bit CinemaDNG:UHD 下開始錄影時畫面會亮約一檔。
  - 關機後不會記住 RAW:色彩模式會回到 OFF,需要重新選 RAW。
  - 在 QS(快速設定)選 OFF 不會離開 RAW;請在 COLOR 選單選 OFF 或其他模式。
  - 場景有亮部時,自動曝光可能比原廠暗 1~2 EV:即時影像現在有 12-bit 錄影
    同樣的高光空間。
  - 不在 fpSup-Merge 裡,不能在那裡合併。

移除

  刪掉檔案(或拔卡),然後關機。卡片改過的每個韌體字,會在相機關機時寫回。
  Fast Start 2 留在設定區的 loader 沒有卡就不會做任何事。
