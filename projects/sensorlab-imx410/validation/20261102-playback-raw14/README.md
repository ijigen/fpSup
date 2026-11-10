# 14-bit 回放花屏調查（未修復，2026-11-02）

使用者回報：選到片段已花屏，不會凍結；S16 2K / 29.97 / 14b 1x1。舊 v0.7.13 實際上只驗證到 TIFF、profile、canvas 與 prepare，未驗證像素解包。29.97 是原廠支援類別，低於 23 fps 的另一個拒播條件不能解釋本案。

native-format-probe.json 由原廠 ROM 的 C0436360、C02DA870、C04356B0、C04358D0 實際執行取得：canvas 0x10008 的 metadata enum 回落 0（12-bit）；無 high bit 的 8 則為 enum 1（14-bit）。緩衝大小函式兩種 14 代碼均採 16-bit 大小。此項是格式路徑不一致的證據，不等同於真實輸入列距／DMA 解包已查明。C0436180 經 C0438268 / C0046080 寫 RAW metadata；尚未證明這就是本案花屏原因。未直接改 enum 或低階暫存器，未新增 CPU 全幅轉換。

media.json 是兩份真實 14-bit DNG 的來源／雜湊；media/ 僅為 128 KiB 標頭前綴，不能稱為完整可播放 DNG。第二份經既有 evidence_jxl.py 解包為完整原位元組，再核對原始 SHA。repacked side archive 的 hash 與舊 ARCHIVE.json 不相同是正常的；初版提取腳本因此中止，已修正。

baseline.json 只含第一份資料的 bits / fps 替代矩陣，明列 synthetic_bits_rate；不把其低速失敗當成本案根因。不是使用者最新花屏片段。native-format-probe 的 2096x1240 是合成幾何，也不是宣稱取得使用者片段的確切尺寸。

本輪只進行離線讀取／研究；未操作相機、USB、daemon 或 SD。SensorLab v0.7.14test 另行交付比例排版調整，apply/ap.c 與 v0.7.13test 相同，14-bit 花屏仍待追查。
