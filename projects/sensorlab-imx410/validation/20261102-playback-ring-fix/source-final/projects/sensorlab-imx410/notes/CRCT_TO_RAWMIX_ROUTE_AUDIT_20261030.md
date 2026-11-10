# CRCT → RawMix 直接串流：有限離線查核

2026-10-30。沒有相機操作。本輪只查已知CRCT出口selector與原廠RawMix入口，沒有搜尋全部SoC路由。

**沒有在本輪查核範圍找到可把CRCT直接送進SIG/FPNR、略過DRAM的已知selector。這不是硬體不可能的結論。**

- `C0635CA8`與`C0635CD0`（`out/decomp/full/blk_c06.c:46597`、`:46609`）以`(old & ~7) | enum`寫入
  `300F06B0/300F06D0`，已知caller的enum為0…5（setter本身沒有另mask參數）。`C031DCE0..C031E060`對應的原廠除錯名稱是
  `CrctGain/Crmf/Vbin/Hbin/Hbin2/SpcToBufA`；這是在選a0/a7的**來源抽頭**，不是任意目的端。
  `C0325228`路徑結構是a0/a7/a1 enable、抽頭、bin、RWZM與bypass；已解結構沒有SIG/FPNR目的端選項。
  來源：`research/imaging-hw/notes/CRCT_REDUCTION_PATHS.md:31–76`、
  `CRCT_PATH_SELECTOR_SOLVED.md:69–99`。
- bufa1現有出口名為`CrctRwzmToBufA`。這解釋RWZM為何能在寫入影像記憶體之前縮寬；
  不能據此推定FPNR也在同一條前端串流上。
- 已找到的RawMix公開caller `XC_SigproRawMix C0426ED0`
  （`out/decomp/full/blk_c04.c:25627–25701`）取兩個image object的buffer，要求尺寸與格式相同，
  將兩個地址交給`C01A9B20 → C0132D20`。
  後者建立RAW input DMA，來源地址最終落bank1 shadow `30260144/30260148`，
  格式/行距落`302600B4/302600BC`；已知路線是記憶體讀入。
  來源：`blk_c01.c:33907–34060`及`projects/isp-lab/rmix/native-abi.txt:9–65`。

因此可說「目前已解、可呼叫的RawMix路徑以DRAM地址輸入」；不能說「整顆SoC一定只能經DRAM」。
要建立直接sensor→FPNR路線，仍需找到原生source mux／sequencer route使FPNR吃CRCT串流，
或原廠實際caller證明此連接；只有兩單元同在ISP、寫入FPNR係數、或缺少DMA活動，都不足以證明可達。
即使未來找到這個接點，兩路同色水平對齊及輸出縮寬仍要另證；RawMix混合兩張同尺寸輸入本身不會變成H2/H3。

同輪sensor低資源候選已保存於`LOW_RESOURCE_H14_PATHS_20261030.md`。
3B／2F+Family-A14僅是有限覆蓋缺口，lowest-resource不代表最可能成功；維持現有sensor Vbin。
本輪到此結束，沒有提出未有來源的mux值或新的上機動作。
