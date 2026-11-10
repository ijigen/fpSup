# Sensor 水平 3B／2F 與 14-bit 組合的覆蓋盤點（離線）

> **用途與優先順序更正**：使用者提醒既有sensor測試已很完整；重新核對IMX410_RULES §36、§42、§43、§67、§72–74後，
> 這兩格未找到直接保存資料仍是盤點事實，但不構成新的可行性線索，不能據此把sensor重測重新排成主線。
> 沒有新的原廠配置、可解義控制或其他正向證據時，保留此盤點，不重跑既有掃描。此決定不宣稱每個組合都已形式上排除。

**結論：在本次限定查核的腳本與保存資料中，未找到 `0001=3B` 或 `2F` 搭配 Family-A14 的直接測試。**
已測的39／38／3A不能直接代替這兩個格式碼。這是測試覆蓋缺口，不是它們能輸出RAW14的證據。
本輪只讀資料，沒有相機操作、模式修改或新試驗。

## 實際覆蓋

| 格式／垂直組 | Family／接收端 | 狀態與直接來源 |
|---|---|---|
| 39 + mode98 V2 | Family-A14、HMAX911、RX12 | 已測，近定值4094/3837：`captures/l7/t2a`；`l7.py` 的t2分支 |
| 38、3A + mode98 V2 | Family-A14、HMAX911、RX14 | 已測，近定值14611/13958：`captures/l7/t2b_0x38`、`t2b_0x3A` |
| 39 + mode98 V2 | normal、HMAX445、RX12 | 正常對照：`captures/l7/t2ref` |
| 3A + mode10 V1 | Family-A14、HMAX911、RX14 | 已測，定值、連續兩幀SHA相同、無Bayer：`captures/w14_sweep/w14_3A/{regs,frame,BAYER}.json` 與 `eval.json`。此項 `rx=null`，保留全寬接收窗，並非3B的縮寬配置 |
| 3B + V1 | normal、HMAX445、RX12 | 已測有圖：`captures/bins/h2_3B/regs.json` 明確只有0001=3B與005D=05，沒有Family-A14；matrix_r2的12h2也通過 |
| 3B + V3 | normal／fast、RX12 | matrix_r2有圖；後續另發現V3視窗的週期性暗列，不能把舊matrix通過當所有裁切均正常 |
| **3B + V1/V2/V3** | **Family-A14，RX14或RX12** | **未找到直接保存測試** |
| 2F + V1 | normal／fast、RX12 | 舊matrix曾判通過，但後續full_v1發現R/B在黑位、只有G；已撤出可用類別 |
| 2F + V2 + PAIR | normal／fast、RX12 | 已測可用：matrix_r2 `12h3v2p` 的linearity／rowphase／burst通過 |
| 2F + V3 | normal／fast、RX12 | 原廠3×3與保存對照，正常 |
| **2F + V2/V3** | **Family-A14，RX14或RX12** | **未找到直接保存測試** |

`matrix.py:16–17` 的14-bit清單只有01/03/15/16/18/1A/1B/2B/3A/3D/3E；
`captures/w14_sweep/cells.json` 與實際目錄相符，沒有3B或2F。
`readout_cfg.py:93–105` 只在normal／fast迴圈建立3B和2F；14-bit只建立29的V2/V3。
限定盤點另外包括l7、bins、matrix_r1/r2的plan／regs metadata，以及相關腳本和筆記。

`IMX410_RULES.md:1132` 的3A=3B來自12-bit模式掃描。它支持兩者在該配置的幾何相似，
不能推定換Family／接收位深後仍完全等價。L7 §6與TRUE14_2X_RESEARCH早期「水平14不可行」
應縮為「上述已測組合失敗」；§67「除了29/2B沒有別的格式」也超出了實際掃描覆蓋。

## 可供有限補試的幾何依據

- 3B nominal3032寬、2F nominal2016寬都有RX12原始資料。水平合併後內容在接收行左側，
  不應沿用全寬置中的接收窗；`IMX410_RULES.md:1473`記錄此問題曾讓首次工具誤判失敗。
- 3B／2F本身不自動配對兩列；V2必須保留已驗證的PAIR組。39會自行配對，不能直接套39的
  mode98垂直合成代替3B。`readout_cfg.py:106–109`、`IMX410_RULES.md:1471`。
- 2F + V1的缺紅藍已在 `IMX410_RULES.md:1620–1623` 更正；使用者已有sensor Vbin，
  因此可先沿用已知14v2／14v3的垂直組，再只改水平格式。V2的PAIR保持；V3先避開已知壞的sensor window。
- 不預設14-bit接收可行：3B／2F在原廠都是12-bit word配置。Family-A14加RX14可能只造成
  transport解碼不匹配；RX12的對照可區分這一點，但RX12出圖不等於達成RAW14。
- HMAX先保持911；不把「縮寬」等同可以縮短14-bit線時間。前後各保留29 +同垂直組的RAW14對照。
- RAW14 row packing要按**實際BUFA格式及line_words readback**配置／解碼／檢查guard。
  3032不能直接假設完整packed14行；需裁至可整除16的有效寬（例如3024），並經native window
  路徑驗證實際輸出。舊直接寫end欄位的L7 capture實際wpr=1319，與把3024代入公式的1323不同，
  顯示殘留接收起點／偏移會影響最後寬度，不能直接照抄其數字而略過readback。
- 可先只保留數百列，不改sensor Vbin，減少緩衝需求；輸出長度用實際pitch×height，非nominal尺寸。
  必須檢查R/G/B、連續幀差異與黑位／高光；舊Bayer「兩綠相等」檢查曾漏掉2F的缺色。

這支持設計兩個格式碼的有限對照；沒有提供自動掃描器、相機執行授權或成功保證。
即使14-bit容器的low2非零，也要排除CRCT增益生成的小數位。`L7_14BIT.md:173–174`的
12-bit sensor→BUFA14對照已有99.5% low2非零，所以單看餘數不足以證明sensor真的保留14-bit量化。

另須更新術語：`IMX410_RULES.md:1116`後續實測顯示0001=29配完整normal Family-A仍能輸出14-bit，
因此本報告稱「Family-A14配置」，不把設定名稱當成ADC實際位寬的量測結論。
