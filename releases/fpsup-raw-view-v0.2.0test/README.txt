================================================================
 fpsup-raw-view  v0.2.0test
 SIGMA fp — RAW monitoring: the LCD shows what 12-bit CinemaDNG records
================================================================

English below the line of dashes; 中文在後面。
Illustrated explainer (EN / 简 / 繁):
  https://ijigen.github.io/fpSup/explainers/raw-view.html

WHAT IT IS

  Adds "RAW" as the 17th row of the COLOR menu. With it selected
  and the camera recording CinemaDNG 12-bit, live view shows the
  RAW the camera is about to record, not a finished picture:

  - Standby uses the recording gain. What clips on the screen
    clips in the DNG, and what does not, does not.
  - Sensor saturation is display white at every ISO.
  - Two curves, chosen with the box on the right of the RAW row
    (the box shows SA or GA):
      SA  Latitude, Stop Aligned: the per-ISO latitude of the fp
          (stops above and below 18% grey) spread over the screen
          with Rec.709's own stop spacing.
      GA  Latitude, Gray Aligned: the "LA - SIGMA Rec709" curves of
          SIGMA fp Rec709 LUT & Operations Guide v3 (Ole Berek).
    Both use the latitude figures from that guide.

  Two settings on the AEL page do something different in RAW:

  - Contrast: how the bottom of the latitude is shown. Monitoring
    only; the CinemaDNG is not affected.
      0     all 12.5 stops fit on the screen. The live view can
            resolve only about 10.9 stops below clipping, so the
            bottom ~1.6 stops show as fine noise dots: dots mean
            there is detail, pure black means crushed.
      +0.2  only the 10.9 stops the live view resolves; the bottom
            ~1.6 stops go black and the rest get more room.
  - Saturation: whether the camera's colour calibration is used.
      0     the default. No calibration on screen, and the
            CinemaDNG is exactly the same as a normal recording.
      +0.2  the camera's own calibration matrix (the one the other
            colour modes use) is applied on screen AND written into
            the CinemaDNG ColorMatrix tags, so Resolve shows the
            colours you monitored. The raw pixels are not changed.
  - Sharpness is held at 0 while RAW is on.

  The recorded raw data is not altered.

  **Firmware Ver.5.02 only.** Test build.

WHAT CHANGED SINCE v0.1.0test

  - SA follows Rec.709's stop spacing instead of equal height per
    stop.
  - Contrast is now 0 / +0.2 (bottom 1.6 stops shown / dropped).
  - Saturation is now 0 / +0.2 (no matrix / full calibration); it
    was 0..5 as an amount of the matrix.
  - Entry 0 of every curve is pure black, so crushed shadows always
    read black (v0.1.0test showed SA at ISO 100 about 11% grey there).
  - The box on the RAW row shows SA / GA instead of -5 / +5.

TWO CARDS IN THIS FOLDER

  Ordinary card (this folder):  AutoRun.txt + fpSup.BIN
      Every start runs the AutoRun: a progress bar, then the
      banner fpSup-RAW-v0.2.0test!

  Fast Start 2 (FastStart2/):   AutoRun.txt + fpSup.BIN + FPSUPUI/
      After the first start, a restart with the power switch loads
      about 1.4 s after power-on without the AutoRun and shows the
      four-box screen; a cold start runs a short AutoRun. It stores
      the loader in the camera's settings block, which survives a
      battery pull. Power off with the USB cable UNPLUGGED -- with
      it attached the next start is always a cold one.
      Updating from v0.1.0test's Fast Start 2 card: the first start
      after copying may still run the old one; judge from the start
      after that.

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
  - The RAW choice, Contrast and Saturation are not kept across a
    power-off: the colour mode comes back as OFF; select RAW again.
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
 fpsup-raw-view  v0.2.0test
 SIGMA fp —— RAW 監看:螢幕顯示 12-bit CinemaDNG 實際錄到的東西
----------------------------------------------------------------

圖解說明(EN / 简 / 繁):
  https://ijigen.github.io/fpSup/explainers/raw-view.html

這是什麼

  在 COLOR(色彩模式)選單加上第 17 列「RAW」。選到它、而且錄影格式是
  CinemaDNG 12-bit 時,即時影像顯示的是即將錄下的 RAW,而不是修飾過的畫面:

  - 待機使用錄影時的增益:螢幕上過曝的地方 DNG 也過曝,沒過曝的就沒有。
  - 每個 ISO 的感光元件飽和 = 顯示白。
  - 兩條曲線,用 RAW 列右側的框選(框上顯示 SA 或 GA):
      SA  Latitude — Stop Aligned:fp 各 ISO 的寬容度(中灰以上、以下幾檔),
          依 Rec.709 本身的檔距鋪在螢幕上。
      GA  Latitude — Gray Aligned:SIGMA fp Rec709 LUT & Operations Guide v3
          (Ole Berek)的「LA - SIGMA Rec709」曲線。
    兩者都用這份指南的寬容度數據。

  RAW 時 AEL 頁有兩項作用不同:

  - 對比度:寬容度底部怎麼顯示。只影響監看,CinemaDNG 不受影響。
      0     12.5 檔全部放進螢幕。預覽在削波以下只分得出約 10.9 檔,
            所以最底約 1.6 檔以細小噪點出現:有點就是有細節,純黑才是壓死。
      +0.2  只放預覽分得出的 10.9 檔;最底約 1.6 檔變黑,其餘檔位更寬。
  - 飽和度:要不要用相機的色彩校正。
      0     預設。螢幕不套校正,CinemaDNG 與一般錄下的檔案完全相同。
      +0.2  螢幕套用相機自己的校色矩陣(其他色彩模式用的那一組),
            同一組也寫進 CinemaDNG 的 ColorMatrix,Resolve 顯示的顏色與監看一致。
            RAW 像素本身不動。
  - RAW 時清晰度固定為 0。

  錄下的 RAW 資料不會被改動。

  **僅限韌體 Ver.5.02。** 測試版。

與 v0.1.0test 的差別

  - SA 改依 Rec.709 的檔距,不再是每檔一樣高。
  - 對比度改為 0 / +0.2(顯示/捨去最底 1.6 檔)。
  - 飽和度改為 0 / +0.2(不套/完整校色);原本是 0..5 的套用程度。
  - 每條曲線的第 0 格都是純黑,壓死的暗部一定顯示黑
    (v0.1.0test 的 SA 在 ISO 100 那裡約是 11% 灰)。
  - RAW 列右側的框顯示 SA / GA,不再是 -5 / +5。

這個資料夾裡有兩張卡

  一般卡(本資料夾):     AutoRun.txt + fpSup.BIN
      每次開機都跑 AutoRun:進度條,然後顯示 fpSup-RAW-v0.2.0test!

  Fast Start 2(FastStart2/): AutoRun.txt + fpSup.BIN + FPSUPUI/
      第一次開機之後,撥電源開關重開時約 1.4 秒就載入、不跑 AutoRun,
      顯示四格畫面;冷開機跑短版 AutoRun。會把 loader 存進相機設定區
      (拔電池也會留著)。關機時請**拔掉 USB 線**——插著線關機,下次一定是冷開機。
      從 v0.1.0test 的 Fast Start 2 卡更新:複製後第一次開機可能仍跑舊版,
      請以再下一次開機為準。

  兩個 zip 裡是同樣的檔案,各一張卡。

安裝

  1. 把卡的檔案複製到相機開機用的 SD 卡**根目錄**
     (Fast Start 2 要連 FPSUPUI 資料夾一起)。
  2. 不插 USB 線開機。
  3. 錄影格式選 CinemaDNG 12-bit,COLOR 選單 → 第 17 列 RAW。

限制

  - 只支援 CinemaDNG 12-bit。MOV 與 8/10-bit 不支援。
    UHD 錄的是 8-bit CinemaDNG:UHD 下開始錄影時畫面會亮約一檔。
  - 關機後不會記住 RAW、對比度與飽和度:色彩模式會回到 OFF,需要重新選 RAW。
  - 在 QS(快速設定)選 OFF 不會離開 RAW;請在 COLOR 選單選 OFF 或其他模式。
  - 場景有亮部時,自動曝光可能比原廠暗 1~2 EV:即時影像現在有 12-bit 錄影
    同樣的高光空間。
  - 不在 fpSup-Merge 裡,不能在那裡合併。

移除

  刪掉檔案(或拔卡),然後關機。卡片改過的每個韌體字,會在相機關機時寫回。
  Fast Start 2 留在設定區的 loader 沒有卡就不會做任何事。
