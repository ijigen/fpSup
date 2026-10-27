CDNG Image 0.2.11 — 第三種 Temporal JXL，2026-10-27
每組最多 8 幀沿時間重排，與單幀候選比較，保留較小者；直接輸出單一 .cdngt。
macOS 用 Mount archive／Open archive… 按需還原掛載，保留原有兩種輸出。
完整 CINEMA 335.29s，230 幀選時間壓縮；不保證比單幀模式快或每段素材更小。
全部 1,553 檔讀回及實際掛載通過，另修正 exFAT 解出資料夾的改名相容性。
詳細驗證、數值與平台限制：validation/TemporalJXL-0.2.11.txt。

CDNG Image 0.2.10 — JPEG XL 進度與記憶體修正，2026-10-27
首次 Metal 編譯期間顯示準備狀態與活動指示；百分比仍依真實完成檔數計算。
逐批釋放 GPU 暫存，移除重複 RAW 配置；保留原有無損壓縮設定與完整核對。
Samsong 完整 1,553 檔讀回核對與 15 張獨立 RAW 抽驗通過，取消／錯誤清理通過。
首次編譯仍可能需要數十秒。JPEG XL DMG 的 Resolve 轉換掛載尚未接好；Resolve 工作請選 LJ92。
詳細證據與限制：validation/JXLProgress-0.2.10.txt。

CDNG Image 0.2.9 — Metal 共用分塊統計，2026-10-26
同一批 Samsong/CINEMA、Smallest／Max、8 workers 與完整核對，兩版預熱後交錯各三次：
0.2.8 中位數 13.77s → 0.2.9 12.23s，總耗時減少 11.17%，3/3 組較快。
1,553 檔完整來源／RAW／輸出雜湊一致，DMG 均為 4,720,229,727 bytes，品質與壓縮率維持。
限同輪負載與暖快取條件，不與先前約 7.93s 直接比較；局部統計加速不等於整批加速。
詳細配對秒數、限制與驗證：validation/LJ92SharedHistogram-0.2.9.txt。

CDNG Image 0.2.8 — 壓縮期間暫停預覽解碼，2026-10-26
取消排隊預覽並停用播放，保留畫面與片段勾選，避免預覽持續爭用壓縮資源。
壓縮核心沿用 0.2.6；全部 1,553 個輸出檔案與體積一致，完整核對保留。未宣稱新編碼器加速。
新的效能審視與共用統計原型證據：validation/LJ92Reassessment-20261026.txt。

CDNG Image 0.2.6 — LJ92 完整流程加速，2026-10-26
同一批 Samsong/CINEMA、Smallest／Max、8 workers 與完整核對，三次交錯測試中位數 14.60s → 7.93s，總耗時減少 45.7%。
全部 1,553 個輸出檔案逐位元組一致，DMG 體積與壓縮率不變。詳見 validation/LJ92Throughput-0.2.6.txt。

CDNG Image 0.2.5 — 2026-10-26 Metal／CPU 資料流優化

  相同 Max、完整核對，Samsong/CINEMA 與同磁碟交錯各三次：總時間中位數 23.39s → 18.44s，耗時減少 21.2%。
  全部 1,553 個保存檔案逐位元組一致，壓縮率、RAW 品質與中繼資料不變。
  Metal 批次計算候選分塊；編碼輸入使用頁面對齊共享緩衝，省去輸入複製。
  以確切大小下界省去必定不能勝出的第二候選；所有可能改善體積的候選與最終核對保留。
  來源解碼重用 tile 緩衝。這是局部零拷貝，搜尋來源上傳與 DNG 封裝仍有複製。
  Mac 程式：release/CDNG Image 0.2.5.app。
  條件與限制：validation/LJ92Throughput-0.2.5.txt；不保證其他素材有固定加速比。

以下保留先前版本記錄。

CDNG Image 0.2.4 — 2026-10-26 LJ92 輸出加速

  保留壓縮率優先 Smallest／Max、完整搜尋及全部無損核對。
  同批 Samsong/CINEMA、同磁碟，0.2.3／0.2.4 交錯各三次：總時間中位數 26.35s → 23.78s，減少 9.7%。
  全部 1,553 個保存檔案逐位元組相同，壓縮率與 RAW 品質不變。
  優化來源 LJ92 解碼查表與位元讀取，省去 Metal 輸出的中間緩衝及複製。
  Mac 程式：release/CDNG Image 0.2.4.app。
  測試條件與限制：validation/LJ92Throughput-0.2.4.txt；不保證其他素材有固定加速比。

以下保留先前版本記錄。

CDNG Image 0.2.3 — 2026-10-26 壓縮率優先

  恢復 Smallest／Max 為介面與命令列的預設，不再自動降低壓縮搜尋程度。
  優化速度時保留最小體積模式的預測與分塊搜尋，以及完整無損核對。
  以同一批素材、相同 RAW 像素及中繼資料保存要求，檢查 DNG 總位元組是否不大於 slimRAW。
  DNG 壓縮資料與映像檔額外空間分開統計；通過的素材範圍須以實測證據為準。
  0.2.2 的 28.7% 時間差包含改用 Faster，不是同壓縮率設定的速度提升；撤回作為優化成果的說法。
  保留減少重複計算、複製與映像檔讀寫的改進，以及 Start 至完成的 00.00s 計時。
  Mac 程式：release/CDNG Image 0.2.3.app。
  CINEMA 實測：1,543 幀 DNG 比此次 slimRAW 輸出小 11.33 MB（0.2400%），全部 RAW 像素一致。
  對照 slimRAW 當前 Lossless 設定，Maximum 關閉；不是最高壓縮或所有素材的保證。
  證據見 validation/RatioPriority-0.2.3.txt。

以下保留 0.2.1 與更早版本記錄。

CDNG Image 0.2.1 — 2026-10-26 修正

  修正 Samsong 等不支援 RENAME_EXCL 的 exFAT 磁碟在完成後回報 os error 45。
  開始寫入前先檢查相容性；不支援時以獨佔建立的新檔直接寫入，沒有額外整包複製。
  此情況會在壓縮途中看到正式檔名；等顯示 Done 後再開啟。取消或失敗會清除未完成檔案。
  若程式或系統被強制中止，仍可能留下未完成檔案。
  新增 00.00s 格式的耗時顯示，包含準備、壓縮、打包、核對與暫停，完成後保留。
  Mac 程式：release/CDNG Image 0.2.1.app；保留工作區其他 agent 已加入的功能。
  Samsong 實測：Metal LJ92＋DMG、原生映像檔校驗、三幀獨立 RAW 比對、拒絕覆寫及取消清理通過。
  本次證據：validation/exfat-fix-20261026/。

以下保留 0.1.4 歷史說明，部分功能與介面已由後續版本調整。

CDNG Image 0.1.4 — Rust 原生版

0.1.4 Metal 直接編碼與核對排程
  Metal 執行每像素預測、統計及 JPEG 壓縮位元流，不再只用於預測搜尋。
  壓縮、RAW 核對與映像檔寫入持續並行，不必等待整批影格完成。
  加速 CPU 的雙通道 RAW 解碼核對；仍逐幀完整驗證。
  新增「邊壓縮邊核對」與「全部壓完後核對」。預設同步核對，在本次素材較快。
  128 幀的平衡模式三次中位數：同步 2.25 秒，集中核對 2.48 秒；條件見 Performance.txt。

0.1.3 壓縮核心改善
  修正 Huffman 權重、採用較少邊界填補的分塊，加速 JPEG 位元流與 Apple 晶片校驗。
  快速模式固定使用 Bayer 同色預測；平衡與最小體積模式保留預測搜尋。
  介面預設最多 8 個並行工作，可依電腦與素材調整。
  本次同機測試，平衡模式由 7.58 秒降至 3.26 秒；slimRAW 含校驗為 2.48 秒，仍然較快。
  此結果限於測試資料與條件，詳見 Performance.txt。

0.1.2 效能改善
  合併 GPU 區塊工作、加速無損編碼、RAW 拆讀與雜湊。
  只對最後選用的重新編碼 DNG 做完整逐像素核對；保留原檔時維持原始檔案位元組。
  預覽完成即更新畫面，減少等待介面輪詢的延遲。
  詳細速度與測試條件見 Performance.txt。

0.1.1 修正
  修正載入預覽後滑鼠移入視窗可能造成的閃退；進度條改用有限的視窗可用寬度。

啟動
  Mac：開啟 release/CDNG Image 0.1.4.app。無需 Python。
  Windows／NVIDIA：原始碼包內有 Build Rust Windows CUDA.cmd。
  Windows／CUDA 目前提供實作與建置入口，尚未經 NVIDIA 實機驗證，未提供已驗證的 Windows 執行檔。

使用
  1. 選擇上層素材資料夾，程式遞迴列出含 DNG 的片段資料夾。
  2. 點片段名稱查看畫面；可播放、拖幀、逐幀前後查看。
  3. 勾選要保存的片段。預設全選，可全部排除後逐一選取。
  4. 選擇 ISO 儲存位置、壓縮程度與 Metal／CPU 運算方式，再開始打包。
  5. 完成後雙擊 ISO 或按「掛載映像檔」，從掛載位置匯入 Resolve。

片段與排除
  每個直接含有 .dng／.DNG 的資料夾視為一個片段，依檔名排序。
  取消勾選會排除該片段的 DNG，以及其資料夾內的音訊、附檔。
  上層共用檔案仍會保留；更深層、獨立勾選的片段可單獨保存。
  重新整理同一資料夾會保留現有勾選，新片段預設選取。
  ISO 內的 _CDNG_IMAGE_MANIFEST.json 記錄實際保存檔案、排除清單、校驗碼與 RAW 像素雜湊。

預覽
  直接讀取原始或既有無損壓縮 DNG，不會更動素材。
  快速 Bayer 預覽會依中繼資料調整白平衡，並自動調整亮度以利辨認片段。
  播放採約 8 次／秒的取樣預覽；拖幀與逐幀按鈕可查看指定幀。
  預覽供選片使用，不是 Resolve 的完整色彩處理或調色判斷基準。

壓縮
  快速：固定預測，優先節省處理時間。
  平衡：搜尋多種 Bayer 預測。
  最小體積：增加預測與分塊搜尋；會花更多時間。
  三種皆保留原本儲存的 RAW 像素值、位元深度與解讀所需中繼資料。
  支援重新壓縮已無損壓縮的 DNG；結果較大時保留原檔。
  也可選擇「原檔打包」，逐位元保留完整檔案。
  已有良好無損壓縮的來源，重新壓縮可能沒有額外收益；僅需保存及掛載時可使用原檔打包。
  原始素材保持不動，拒絕覆寫既有 ISO；取消或失敗會清除本次未完成檔案。

GPU 與多工
  Rust 核心負責編碼、多幀並行處理、ISO 寫入與校驗。
  Metal 執行 GPU 整數預測、統計及 JPEG 位元流編碼；CPU 準備少量編碼表，並負責 RAW 解碼核對與 ISO。
  CUDA 目前仍為 GPU 預測／統計＋CPU 編碼，尚未移植此次 Metal 直接編碼，也未經 NVIDIA 實機驗證。
  快速模式採固定預測，選用 Metal 時仍由 GPU 編碼。
  可選 1／2／4／8／16／32 個並行工作；預設最多 8 個，可依素材與電腦調整。
  記憶體隨同時處理幀數增加，不會預先載入整段影片。

RAW 核對時機
  邊壓縮邊核對：預設；一幀完成後，核對與後續影格、ISO 寫入持續並行。
  全部壓完後核對：先寫入未完成的映像檔，再逐幀讀回、解碼並核對原始 RAW 像素雜湊。
  兩種均完整核對，通過後才發布最終 ISO；取消或驗證失敗會清除本次未完成檔案。
  集中核對需要額外讀取，在本次 SSD 素材約慢 10%；其他儲存裝置可能不同。
  RAW 解碼核對目前由 CPU 執行，沒有宣稱已完成 Metal RAW 解碼器。

映像檔
  ISO9660 + Joliet，DNG 壓完後直接寫入同一映像檔，沒有另一份完整解壓素材暫存。
  掛載時由剪輯軟體依需解碼各幀；不需先把整包素材解開。
  ISO 本身有目錄與區塊對齊成本，因此單幀測試的 ISO 可能比裡面的 DNG 大一些。
  映像檔總體可超過 4 GiB；單一內含檔案目前須小於 4 GiB。
  長檔名每段最多 64 個 BMP Unicode 字元；不支援符號連結與 Windows 不相容檔名。

支援範圍
  目前針對 classic little-endian、單一 RAW IFD、單通道 Bayer 的 SIGMA fp CinemaDNG。
  未壓縮來源須為單 strip；也支援經驗證的 Lossless JPEG（Compression=7）輸入。
  8／10／12／14／16 bit 經合成資料的獨立 TIFF 解碼比對。
  真實相機與 Resolve 的實測素材為 12 bit SIGMA fp；其他相機或特殊 DNG 不能一概保證。
  非預設像素交錯、SubIFD 影像、移出原始表頭的中繼資料等不支援情形會停止，避免遺失資料。
  壓縮採 Lossless JPEG；直接將 JXL 封入 Bayer DNG 的實驗未通過，正式版未啟用 JXL。
  無損指 RAW 像素值相同；重新編碼後的 DNG 檔案位元組不會與來源完全相同。

驗證
  詳細結果見 release/Validation.txt。
  Metal：Apple M1 Max、64 GB、macOS 27.0 實測。
  Resolve 21.0.4.5 可從掛載 ISO 匯入序列並輸出畫面。
  Windows 原生掛載、Windows 程式與 CUDA GPU 尚待該平台實測。

建置
  Rust stable、C/C++ 編譯工具。
  Mac：在 rust 目錄執行 cargo build --release --locked，Metal 已內建。
  Windows CUDA：Rust MSVC、Visual Studio C++ Build Tools、NVIDIA CUDA Toolkit；從 x64 Developer Command Prompt 執行建置檔。
  CUDA 目標為具備 Compute Capability 7.5 或更新的 NVIDIA GPU。
  GPU 啟動時先比對 GPU／CPU 整數預測；Metal 再做小批次 GPU 編碼與 CPU 解碼核對，驗證不符會停止。
  ljpeg 使用 rust/vendor/ljpeg 的本地修改版本；修改紀錄見該目錄 CDNG-CHANGES.txt。

命令列
  cdng-image pack SOURCE OUTPUT.iso --backend metal --effort balanced --workers 8
  cdng-image pack SOURCE OUTPUT.iso --exclude-clip "A001_002" --exclude-clip "A001_009"
  cdng-image pack SOURCE OUTPUT.iso --backend metal --raw-check-after-pack
  cdng-image gui SOURCE
  cdng-image preview frame.dng preview.ppm

專案
  rust/ 為正式程式；cdng_image/native/ 為 Metal／CUDA 原生後端。
  根目錄 Python 程式與舊啟動檔是開發原型，正式 Mac 程式無 Python 依賴。
  原始碼包不含私人相機影格；部分開發測試需要另備測試素材。

參考
  https://github.com/ablzkv/cinemadng-sigmafp-compressor/releases/tag/v0.1.0
  https://www.slimraw.com/userguide.html
  Adobe Digital Negative Specification 1.7.1.0，尤其頁 21 的 lossless JPEG 內部幾何規則。
  本工具自行實作 DNG／ISO 邏輯，沒有複製前述 GitHub 專案未授權的原始碼。
