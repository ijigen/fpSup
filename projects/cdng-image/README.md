# CDNG Image

把 CinemaDNG 片段無損壓成一個映像檔（LJ92 DMG 或 JPEG XL DMG），每一幀都還原核對過才算完成。LJ92 DMG 掛載後 Resolve、Lightroom 都能直接讀。

Losslessly packs CinemaDNG clips into one image (LJ92 DMG or JPEG XL DMG); every frame is restored and checked before it counts as done.

## 下載 / Download

**macOS（Apple Silicon，macOS 12 以上）：[CDNG Image 0.2.14](https://raw.githubusercontent.com/ijigen/fpSup/main/projects/cdng-image/download/CDNG%20Image-0.2.14-macOS-arm64.zip)**
（sha256 `96267bca27963af2cedd8c89ac8e67f0070a2c73952588c471246ae67611193e`）

程式沒有經過 Apple 公證，第一次打開會被擋。解壓後對 app 按右鍵 →「打開」，或在終端機執行：

The app is not notarized. Right-click → Open the first time, or run:

```
xattr -dr com.apple.quarantine "CDNG Image 0.2.14.app"
```

Windows 目前沒有現成的程式，要自己用 `Build Rust Windows CUDA.cmd` 從原始碼建（需要 NVIDIA 顯卡與 CUDA）。

## 注意 / Notes

- 0.2.14 起只輸出兩種 DMG（LJ92、JPEG XL）；不再建立 Temporal JXL `.cdngt`，舊版的 `.cdngt` 和 `.cdngj` 仍可開啟、掛載。其他平台輸出 ISO。
- 每個版本的改動與實測數字在 [README.txt](README.txt)。
- JPEG XL DMG（0.2.12 起）請在程式內選 **Open archive…** 或壓縮完成後選 **Mount archive**，讀取時會還原為普通 DNG。Finder 直接雙擊 DMG 仍是系統原生掛載，不會啟動動態解壓；舊版產生的 JPEG XL DMG 也可用新版程式開啟。
- **Correct OG3K row alignment when mounting** 預設關閉；啟用後對符合 SIGMA fp OG3K 3024×2010／3008×2000 裁切特徵的影格，在讀取時校正。校正需要插值，掛載視圖的 RAW 像素會改變，保存的封存與來源檔完全不改。選項適用本程式的 LJ92／JPEG XL DMG、`.cdngj` 與 `.cdngt`；沒有符合的影格則維持原樣並顯示提示。改選項後需退出再重新掛載。
- 片段列表支援 Shift 範圍選取、Cmd／Ctrl 加選、拖曳框選，以及 Include／Exclude 批次勾選。框選只標示範圍，按 Exclude 才排除壓縮。
- 掛載名稱採用輸出檔名。原生 DMG 的 Joliet 卷名最多 16 字；程式動態掛載支援較長名稱。
- 首次用 Metal 壓縮要先編譯，可能等幾十秒。
- 壓好之後原檔要不要刪由你決定，程式不會自己刪。

## 從原始碼建 / Build

```
cd rust && cargo build --release --locked
```
