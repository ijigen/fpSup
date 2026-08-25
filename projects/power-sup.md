# power sup

開機／PTP USB-C 供電與省電。

**狀態:充電機制剛解出,省電尚未研究**

---

## 目標

搞清楚 fp 從 USB-C 取電的完整條件,以及有沒有辦法降低待機/錄影功耗。

## 已確認(2026-08-25)

充電**不是一個 gadget 類別**,是 config 描述元的電源欄位,依 `*(0xC3078BAC)` 這個
速度／電源等級索引查兩張表:

```
FUN_c0032320() → 0xC072AF6C[idx]  = bMaxPower
FUN_c0032348() → 0xC072AF80[idx]  = bmAttributes

idx        0        1        2        3        4
bMaxPower  1        0        0x32     0xFA     0x1C2
           (2mA)    (0mA)    100mA    500mA    900mA
bmAttr     0xC0     0xC0     0x80     0x80     0x80
           self     self     bus      bus      bus
```

- `0xC0` = self-powered(吃電池,不跟主機要電);`0x80` = bus-powered,主機才會撥電流
- 500 mA 是 USB 2.0 上限,900 mA 是 SuperSpeed 上限
- **降級規則** `0xC0032E34`:輸出 other-speed config 時,`bMaxPower` 若是 `0x1C2` 或 `0xFA`
  一律改寫成 `0x32`(100 mA)
- `usb chg` 把選單設定寫成 4,gadget 走 mode `0x11`(`FUN_c0031858`,完全不註冊功能),
  連接埠只剩取電用途

另外兩張跟電有關但不同的表:
- **USB Type-C 資料角色** `0xC0BC7BD8` → `FUN_c01f5138`:`device` / `host15` / `drp15`(雙角色)/ `trysnk15`(偏好受電)
- **USB host 模式** `0xC0BC7BB8` → `FUN_c002fb10`:`hmsc` / `hoff` —— 相機自己當 host 掛隨身碟

## 未做

- 邊充電邊運作的實際條件與上限
- 省電 / 待機功耗
- 電池狀態讀取

## 相關筆記

`USB_MODES_COMPLETE`
