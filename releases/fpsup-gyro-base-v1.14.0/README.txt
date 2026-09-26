fpGyroSup Base v1.14.0 -- SIGMA fp firmware Ver.5.02 only

WHAT CHANGED SINCE v1

  Built from the same code as fpGyroSup v1.14.0, and numbered with it.

  - Every firmware word this card changes is recorded when it loads
    and written back when the camera powers off, by the shared loader.
    Turning the camera off with the power switch keeps the firmware in
    memory -- it is a warm restart -- and until now the logger's hooks
    stayed in it, pointing at memory the next boot gives to someone
    else.  The logger no longer carries a power-off routine of its own.
  - This card starts the ordinary way on every boot.  The instant start
    and the short cold start are packaging: build the card on the
    fpSup-Merge page (Gyro-Base) and tick Fast Start 2.  Gyro-Base and
    the Gyro (gcsv) edition cannot be combined: they hook the same
    places.

  NOTE  The write-back runs as part of a normal power-off.  If the
        camera loses power without one -- a frozen camera with the
        battery pulled -- it does not run.

Put AutoRun.txt and fpSup.BIN in the root of the SD card the camera boots
from, and make sure there is a folder called

    GYRO

in the root of EVERY volume you record to -- the SD card and, if you record
to one, the USB SSD as well.  The camera writes the log beside the clip, on
the same disk, and it will not create the folder for you: making a directory
writes to the file system, and the only two moments it could do that are
while a take is starting (which froze the camera) or at boot, when it can
only guess which disk you will actually use.  One empty folder, once, is the
honest price.

Then record.  Each take writes

    \GYRO\A001_037.GYR    beside    \CINEMA\A001_037

64 bytes of header and then nothing but 8-byte records, gyro and
accelerometer interleaved in the order they happened.  Convert with

    ./gyro/gyr7.py A001_037.GYR --gcsv A001_037.gcsv

If a take produces no .GYR, the folder is missing on that volume.  Nothing
else is wrong and nothing else needs doing.  Formatting a card removes it,
so put it back after you format.

This card carries the stream and nothing else: no gcsv on the camera, no
lens profile, no USB shell.  If you would rather the camera wrote the .gcsv and
the .json for you and left no .GYR at all, that is the main fpGyroSup release,
in the same folder.

    https://ijigen.github.io/fpSup/gyro/web/     convert in a browser
    ./gyro/gyr7.py                               convert on the command line

----------------------------------------------------------------
中文摘要

fpGyroSup Base v1.14.0 —— 與 fpGyroSup v1.14.0 同一份程式、同一個版號。

- 把 AutoRun.txt 與 fpSup.BIN 放在開機用 SD 卡的根目錄,並在**每個錄影用的磁碟**
  (SD 卡,以及外接 SSD)根目錄建一個空資料夾 GYRO。每一段錄影會在 \GYRO\ 寫一個
  與片段同名的 .GYR(陀螺儀與加速度計的原始紀錄),之後用 gyro/gyr7.py 或瀏覽器轉換器
  轉成 .gcsv。沒有產生 .GYR,就是那個磁碟少了 GYRO 資料夾。
- 這次的變更:卡片改過的每個韌體字,由共用 loader 在關機時寫回;記錄器不再自己帶關機程式。
  撥電源開關是暖開機,以前記錄器的 hook 會留到下一次開機、指向已經換人的記憶體。
- 這張卡每次開機都走一般的 AutoRun。瞬開與快開請到 fpSup-Merge 頁面選 Gyro-Base 並勾
  Fast Start 2。Gyro-Base 與 Gyro(gcsv 版)不能合併:兩者掛在同樣的位置。
- 注意:寫回是在正常關機時執行;當機後拔電池就不會執行。
- 不帶 USB shell。僅限韌體 Ver.5.02。
