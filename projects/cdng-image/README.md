# CDNG Image

把 CinemaDNG 片段無損壓成一個映像檔（LJ92 DMG、JPEG XL DMG 或 Temporal JXL `.cdngt`），每一幀都還原核對過才算完成。LJ92 DMG 掛載後 Resolve、Lightroom 都能直接讀。

Losslessly packs CinemaDNG clips into one image (LJ92 DMG, JPEG XL DMG or Temporal JXL `.cdngt`); every frame is restored and checked before it counts as done.

## 下載 / Download

**macOS（Apple Silicon，macOS 12 以上）：[CDNG Image 0.2.11](download/CDNG%20Image-0.2.11-macOS-arm64.zip?raw=1)**
（sha256 `dde53eb81bfcd77df2ca669bbb88e6a3dc16b8bc86a4bb4f951e4045d165e1f8`）

程式沒有經過 Apple 公證，第一次打開會被擋。解壓後對 app 按右鍵 →「打開」，或在終端機執行：

The app is not notarized. Right-click → Open the first time, or run:

```
xattr -dr com.apple.quarantine "CDNG Image 0.2.11.app"
```

Windows 目前沒有現成的程式，要自己用 `Build Rust Windows CUDA.cmd` 從原始碼建（需要 NVIDIA 顯卡與 CUDA）。

## 注意 / Notes

- 每個版本的改動與實測數字在 [README.txt](README.txt)。
- JPEG XL DMG 還不能給 Resolve 用；要進 Resolve 請選 LJ92。
- 首次用 Metal 壓縮要先編譯，可能等幾十秒。
- 壓好之後原檔要不要刪由你決定，程式不會自己刪。

## 從原始碼建 / Build

```
cd rust && cargo build --release --locked
```
