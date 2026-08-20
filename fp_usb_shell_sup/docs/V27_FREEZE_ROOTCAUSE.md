# SIGMA fp Ver 5.02 — v27 USB-shell 凍結根因(完整分析)

> 目標:釘死「v27 USB-shell 注入後會凍結」的確切韌體原因。
> 本文從 6 條實機行為特徵反推,收斂到單一機制,並全部反編碼確認。
> EA 為 ARM 位址(base 0xC0000000),file_off = EA − 0xC0000000。信心:**[C]** 反編確認 · **[I]** 推論 · **[P]** 需上機。
> 姊妹文件:注入/傳輸細節 `SHELL_COEXIST.md`、`USB_COMPLETION_PATHS.md`、`TASK_PRIORITY_MAP.md`。

---

## 0. 一句話根因
**v27 worker 手動 `DALEPENA(0x2100C720) |= 0x600` 未經 gate 地永久佔有 EP05(ctx5 OUT)/EP84(ctx4 IN),完全不參與韌體的 USB link/device 狀態機。** 相機只在「主機把 DWC3 link 撐在 U0 且原生 config 沒被重跑」時活著。任何一次 link 拆除/轉換(idle-suspend / 錄影 reconfig / 關機軟斷線)都會撞上 worker 的主動 arming + DCTL link-recovery 請求 → DEPCMD busy-spin / link 打架 → 該完成的東西(imaging IRQ,或關機的 usbTask/EndTransfer)卡住 → **IRQ 0x34 livelock → 整機凍**,只能拔電池。**「一段時間後」= 到第一次 link 轉換的延遲,不是內部計數器。**

---

## 1. 六條實機行為特徵
1. AutoRun 執行後**沒接 daemon**,一段時間後 → **凍**。
2. **接了 daemon,rec** → **凍**。
3. AutoRun 注入完成、沒接 daemon → **可以 rec**,但一段時間後 → 同 #1 凍。
4. AutoRun 注入**完成前**就可 rec;注入仍完成雙閃,但一段時間後 → 同 #1 凍。
5. **只要連上 daemon,就長時間不凍 —— 除非 rec。**
6. **連過 daemon → 不管直接關機或拔線後關機,都凍;沒連 daemon → 即使注入完成,也能正常關機。**

---

## 2. 單一機制(全部反編碼確認)
撐著相機不凍的,是**主機把 DWC3 link 保持在 U0**(活躍態)+ **原生 config 沒被重跑**。破其中之一 → wedge。

### 觸發源 A:idle-suspend(無 daemon)
- worker re-arm 時 StartXfer 走 `FUN_c01e6f98 @0xC01E6F98`,設 **DCTL `0x2100C704 |= 0x100`(ULSTCHNGREQ,裝置端請求喚醒)** + 清 GCTL `0x2100C200 & 0x140` power-down。 [C]
- 主機 suspend 的是**沒被認領的介面**(無 daemon → 沒發 remote-wakeup feature)→ **主機無視裝置喚醒**,PHY 卡 U3。
- DEPCMD `CMDACT(0x400)` 永不清 → `FUN_c01e6a48 @0xC01E6A48` **busy-spin 到 60000 逾時** → GCTL power-bit 一直 toggle + 一直請求喚醒 → **裝置喚醒 vs 主機 suspend 的 livelock** → IRQ 0x34 打爆 → 凍。 [C 碎片 / I 為終態]

### 觸發源 B:錄影(原生 USB reconfig)
- `ChangeMovieRecording @0xC035C9A0` → 錄影旗標 `0xC347E08F` → SysNoRemain(mask `0x100080`)→ `DelayableUsbConnectingObserver @0xC0498F40` 重設 USB session → 重跑 config 端點 init **`FUN_c01e62a8(0) @0xC01E62A8`**,其結尾**硬設 `DALEPENA 0x2100C720 = 0x3`、shadow `0xC31E398C = 0x3`**,**清掉 worker 的 0x600 → EP05/EP84 在硬體層被停用**。 [C]
- worker 不知道、繼續 arm 已停用端點 → CMDACT 永不清 → 同 60s spin → 同 livelock。**daemon 也救不了**(端點已停用)。
- config-gated DALEPENA resync(`blk_c01.c:138229`,只在 `DAT_c31e396c != 0` 時)只會把 HW←shadow=0x3,**永遠不會還原 0x600**,反而確認停用。 [C]

### 觸發源 C:關機(軟斷線拆除)
- USB session dispatch `FUN_c0031910 @0xC0031910` 會**同步阻塞等 usbTask()**(`blk_c00.c:41206`)→ USB task 卡住則關機步驟掛。 [C]
- 拆除自己的 EndTransfer `FUN_c01e6d48 @0xC01E6D48` → `FUN_c01e6a48` **busy-spin DEPCMD**(60000)。 [C]
- worker 的 StartXfer 設 DCTL `|= 0x100`(link recovery)**去打架關機的 `RUN=0` 軟斷線**(DCTL `0x2100C704 &= 0x7fffffff`,`blk_c01:134409/134453`)→ link 永不 settle 成 disconnect → usbTask 卡 → 關機掛。 [C]
- 相關:device-event dispatcher `FUN_c01e7498 @0xC01E7498`(disconnect 0x001→-4;reset 0x002→EndTransfer ep1..6 + cleanup `FUN_c01e67f8 @0xC01E67F8`);USB deinit `FUN_c01e3318(3) @0xC01E3318`(state `0xC31E3748=0`,喚醒 flag bit `0x80000000`)。 [C]

---

## 3. 六條線索 ↔ 一個機制
| 線索 | 觸發源 | 為什麼 |
|---|---|---|
| 1,3,4 無 daemon → 凍 | A idle-suspend | link idle → suspend,worker 硬喚醒 vs 主機不理 → livelock。時間 = suspend 逾時 |
| 5 連 daemon → 穩,除非 rec | (無轉換) | 主機撐 link 在 U0,DEPCMD 秒完成,config 不重跑 → DALEPENA 保 0x600 |
| 2,3,4 rec → 凍 | B 錄影 reconfig | `FUN_c01e62a8(0)` 把 DALEPENA 打回 0x3、停用端點 → worker arm 死端點 → wedge |
| 6 連過 daemon 關機凍;沒連乾淨 | C 關機拆除 | 連 daemon 時 worker 忙(主動 arm + link-recovery)撞拆除;沒連時 worker 閒(50s wait 裡)→ 拆除先完成 |

**「連過 daemon」留下的持久狀態(拔線後仍在)**:`arm_in` StartXfer(9) **沒先 EndTransfer(4)** → EP84 留在「armed 未結束」;worker 進了 active re-arm loop。沒連 daemon 從沒進 arm_in → ctx4 乾淨。 [C]

---

## 4. 排除的假設(全部確認非真兇)
- **gyro hook `0xC00D0794`**:在 GyroData task `FUN_c00d0738 @156614`(pri 20,50Hz 非 2500)。注入 hook 是 **one-shot 自我還原**(寫回原指令 `0xFA046FD7`、保留 r0)→ 穩態零開銷。**不是它。** [C]
- **watchdog**:全韌體**零** watchdog/wdt/heartbeat 符號;`FUN_c000ea54` 是 cache-invalidate 非餵狗;唯一 USB semaphore `0xC31E3A88` 等 TMO_FEVR(餓死它啥都不做);症狀是「凍+live view 還在+要拔電池」→ watchdog 會**重開機**不是凍 → **根本沒 watchdog。** [C]
- **優先權餓死**:worker pri 28,比所有關鍵任務(Gyro 20/usbctrl 12/usb_ds 14/AF 14)都低,搶不到 → 凍結走 IRQ-0x34 livelock,繞過 task 優先權。 [C]
- **慢累積**:rsc-idx 平衡不洩漏(EndTransfer 釋放、StartTransfer 重取 `0xC31E3A30+phys*4`);event ring 每 IRQ 排空;wait-timeout 不觸發任何事。**是單發 wedge,不是 N 次累積。** [C]

---

## 5. 關鍵 EA 索引
| 項目 | EA |
|---|---|
| worker 手設 DALEPENA 0x600 | v27 echo handler 0xC072DF00(FUN_c01e62a9(4/5)+`0x2100C720|=0x600`) |
| DALEPENA HW / shadow | `0x2100C720` / `0xC31E398C` |
| config re-init(rec 打回 0x3) | `FUN_c01e62a8(0) @0xC01E62A8` |
| config-gated resync | `blk_c01.c:138229`(`if DAT_c31e396c!=0 && HW!=shadow → HW=shadow`) |
| DEPCMD busy-spin | `FUN_c01e6a48 @0xC01E6A48`(`while(DEPCMD&0x400)`,60000) |
| StartXfer link-recovery | `FUN_c01e6f98 @0xC01E6F98`(DCTL `0x2100C704|=0x100`) |
| GCTL power bracket | `FUN_c01e6758`/`FUN_c01e67b0`(GCTL `0x2100C200&0x140`) |
| 軟斷線 RUN=0 | DCTL `0x2100C704 &= 0x7fffffff`(`blk_c01:134409/134453`) |
| session dispatch(阻塞 usbTask) | `FUN_c0031910 @0xC0031910` |
| device-event dispatcher | `FUN_c01e7498 @0xC01E7498` |
| reset/disconnect cleanup | `FUN_c01e67f8 @0xC01E67F8` |
| USB deinit | `FUN_c01e3318(3) @0xC01E3318` |
| link-health gate helper | `FUN_c01e40d0 @0xC01E40D0`(>0 = configured) |
| 狀態格 | state `0xC31E3748`(3=running,4=suspend,0=off);pending event `0xC31E3900`;config `0xC31E396C` |
| ISR | `FUN_c01e3660 @0xC01E3660`(IRQ 0x34) |
| 錄影旗標 / admission | `0xC347E08F`;`DelayableUsbConnectingObserver 0xC0498F40`;release `FUN_c00180a0 @0xC00180A0`;SysNoRemain `FUN_c0017920 @0xC0017920`(mask 0x100080) |

---

## 6. 修法方向(gate/disarm on link-down)
worker 每次 arm 前必須全數通過,否則 EndTransfer 兩端 + disarm + 純 `tk_dly` poll(**不 StartXfer、不發 link-recovery 請求**):
- `FUN_c01e40d0() > 0`(configured)
- `[0xC31E3748] == 3`(running,非 4=suspend / 0=off)
- `[0xC31E3900] == 0`(無 pending device event)
- `(0x2100C720 & 0x600) == 0x600`(**我們的端點還沒被停用** ← 抓錄影 reconfig)
- `0x2100C720 == 0xC31E398C`(DALEPENA HW 與 shadow 同步)

轉換後**只在 configured 時**、經 admission(SysNoRemain 0x100080 observer / 錄影旗標清)才重新啟用 0x600 + re-arm。另補 `arm_in` 前的 EndTransfer(4)(EP84 不像 EP05 的 arm_out 會自癒)。這一套同時讓 **suspend / 錄影 / 關機**三種轉換都乾淨。

---

## 7. 信心帳
- **[C]**:全部 EA、DALEPENA 0x600↔0x3、DCTL 打架、兩個關機阻塞面、排除項(watchdog/gyro/優先權/累積)。
- **[I]**:這些碎片組成的確切 IRQ-0x34 livelock = 觀測到的凍結。
- **[P]**:凍結當下讀 `0x2100C704`(DCTL)/`0x2100C70C`(DSTS link state)/`0x2100C40C`(GEVNTCOUNT)/worker STATE markers 驗證預測值 —— 實務上難(凍時 worker 不能 peek,需另闢讀取路徑)。

**結論:根因錨定 —— 單一機制、6 條全自洽、替代假設全排除,唯一缺口是難取得的凍結當下 live probe。**
