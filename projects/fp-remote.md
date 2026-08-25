# fpRemote

外部無線橋接與低解析度串流,以及透過 PTP 的外部控制。

**狀態:PTP 外控有實質進度,無線橋接尚未開始**

---

## 目標

讓相機可以被外部裝置控制與監看:指令走 PTP,畫面走低解析度串流,
中間用一個無線橋接器。

## 已確認 —— PTP 外控

- **vendor opcode 表**:`0x9016`–`0x9038` 是 SetCamDataGrp 系列,
  `0x9032` = SetCamDataGroupFocus,`0x94xx` 是 GIMBAL 群
- **酬載格式是 TLV**(parser `FUN_c0501350` / `FUN_c0501508`):
  `+0x04` count,之後每筆 12 bytes `{u16 tag, ..., value}`
- **GIMBAL 指令名稱表**已抽出(`0xC0CF4D30`–`0xC0CF5050`):
  OpenApplication / CloseApplication / GetParameter / ShiftParameter / SetGpsParam …
- **PTP 在錄影期間仍可下指令** —— 這是它最有價值的性質
- PTP 的資料路徑:每次現場武裝一個 TRB 再同步等待,沒有常駐 ring;
  EP 0x83 是事件用的 interrupt 端點(SS 下 `bInterval=11` → 128 ms 一次,只適合通知)

## 未做

- 無線橋接硬體與協定
- 低解析度串流路徑(可用偵測影像通道 `0xC375D8C0`,320×240 灰階,已驗證可 hook-push)
- 外部控制端的 app

## 相關筆記

`PTP_OPCODES`、`PTP_CINEMADNG`、`PTP_FOCUS_RECORDING`、`PTP_READ_USER_EXPOSURE`、
`GIMBAL_MANUAL`、`GHIDRA_GIMBAL_CHECKLIST`、`IMAGE_CHANNELS`
