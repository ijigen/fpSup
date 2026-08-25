# power sup

[English](#english) | [繁體中文](#繁體中文)

Boot / PTP USB-C power delivery and power saving.
**Status: early — the charging mechanism is solved**

開機／PTP USB-C 供電與省電。**狀態:充電機制剛解出,省電尚未研究**

---

## English

### Goal

Work out the full set of conditions under which the fp draws power from USB-C,
and whether standby or recording consumption can be reduced.

### Proven (2026-08-25)

Charging is **not a gadget class**. It is the power fields of the configuration
descriptor, selected by a speed/power-class index at `*(0xC3078BAC)` from two
tables:

```
FUN_c0032320() → 0xC072AF6C[idx]  = bMaxPower
FUN_c0032348() → 0xC072AF80[idx]  = bmAttributes

idx        0        1        2        3        4
bMaxPower  1        0        0x32     0xFA     0x1C2
           (2mA)    (0mA)    100mA    500mA    900mA
bmAttr     0xC0     0xC0     0x80     0x80     0x80
           self     self     bus      bus      bus
```

- `0xC0` is self-powered — running on the battery and asking the host for nothing.
  `0x80` is bus-powered, which is what makes the host grant current
- 500 mA is the USB 2.0 ceiling, 900 mA the SuperSpeed one
- **A downgrade rule** at `0xC0032E34`: when emitting the other-speed
  configuration, a `bMaxPower` of `0x1C2` or `0xFA` is rewritten to `0x32`
  (100 mA)
- `usb chg` writes 4 into the menu setting and the gadget takes mode `0x11`
  (`FUN_c0031858`), which registers no function at all — the port exists purely to
  draw current

Two other power-related tables, not to be confused with the above:

- **USB Type-C data role** at `0xC0BC7BD8` → `FUN_c01f5138`: `device`, `host15`,
  `drp15` (dual role), `trysnk15` (prefer sink)
- **USB host mode** at `0xC0BC7BB8` → `FUN_c002fb10`: `hmsc` / `hoff` — the camera
  acting as a USB host for a stick

### Not done

- The real conditions and limits for charging while operating
- Power saving and standby consumption
- Reading battery state

---

## 繁體中文

### 目標

搞清楚 fp 從 USB-C 取電的完整條件,以及有沒有辦法降低待機/錄影功耗。

### 已確認(2026-08-25)

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

- **USB Type-C 資料角色** `0xC0BC7BD8` → `FUN_c01f5138`:`device` / `host15` /
  `drp15`(雙角色)/ `trysnk15`(偏好受電)
- **USB host 模式** `0xC0BC7BB8` → `FUN_c002fb10`:`hmsc` / `hoff` —— 相機自己當 host 掛隨身碟

### 未做

- 邊充電邊運作的實際條件與上限
- 省電 / 待機功耗
- 電池狀態讀取

---

**Notes / 相關筆記:** `USB_MODES_COMPLETE`
