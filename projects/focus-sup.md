# focus sup

DFD、焦點模型、鏡頭控制與外部追焦。

**狀態:韌體側研究深入,收集器尚未建**

---

## 目標

理解 fp 的對焦系統到足以在外部重建它:讀得到焦點狀態、驅動得了對焦、
並且能自己算出景深資訊(DFD)。

## 已確認

- **AF-C 消耗 Bayer 綠通道高頻能量**,由 SIG 引擎 `0x30050000` 產生
- **兩段式銳利度指標可直接讀取** —— `saf_jdat_h` `0xC32985E8` / `saf_jdat_l` `0xC32986B4`。
  所以 DFD 收集器 = 掃焦 + 讀統計 + 讀 mposm,**完全不需要把 Bayer 影格搬出來**
- **綠通道 AF band 已能即時串流**(`dfd_live.py`),0.125 ms/frame 零 stall
- **鏡頭資料走韌體 API** —— 借 `FUN_c03554a0` + `FUN_c0355de0`/CmdRead,
  它們會拿匯流排 mutex(所以只能在任務脈絡呼叫,不能在中斷裡)。
  block id 索引 ROM 表 `0xC0B94364`;LUMIX 鏡頭沒有 SIGMA 的 DFD 區塊,但自己有一組在 `0x001500`
- **鏡頭資料程式已端到端驗證** —— 建立 `\LENS` 目錄、讀 block 0x2d/0x0a、
  解析焦距與最近對焦距離、檔名淨化、寫檔後回讀確認
- PTP 對焦指令 `0x9032` SetCamDataGroupFocus,欄位已逐 tag 解出

## 未解

- **錄影中對焦被擋** —— handler 只在 `captureState[0x220]==0 && [0x7c]==0`(閒置)才驅動
- DFD 收集器本身還沒寫

## 相關筆記

`AUTOFOCUS`、`AF_COMPLETE`、`AF_AE_INTERNALS`、`AF_LIVE_STATE_MAP`、`DFD_VIA_AF_STATS`、
`FACE_EYE_AF`、`FOCUS_DISTANCE_PRINCIPLE`、`FOCUS_POSITION_DOMAIN`、`PTP_FOCUS`、
`LENS_BLOCK_API`、`LENS_DATA_ACCESS`、`LENS_CALIBRATION`、`DISTCONVERTER_MATH`
