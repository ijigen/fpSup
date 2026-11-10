# CAPTUREON → INTR_REC_SCREENSHOT：精確離線橋接

2026-10-30；只讀 Ver.5.02 ROM，無 USB／相機／產品修改。`test_capture_key_dispatch.py` **8/8 PASS**，完整結果與 ROM SHA-256 在 `capture-key-dispatch.json`；root 獨立重跑亦 **8/8 PASS**（`capture-key-dispatch-root.json`、`root-key-dispatch-tests.txt`）。關鍵原字與 ARM 反組譯在 `capture-key-dispatch.asm.txt`。

本結果補齊先前 `live/native-composition-followup.md` 缺少的按鍵事件橋接。它不判定實體 LCD、截圖 source／stride 或本輪未驗收候選的原因。

## 已證實的鏈

| 階段 | 精確位置與效果 | 證據範圍 |
|---|---|---|
| shell key 名稱 | `C2F207D0`（key table `C2F205C0` 的 index 44）是 `{name=C0BB7C8C="CAPTUREON", physical=0x3B, callback=0}`；CAPTUREOFF 在 `C2F207DC`，physical `0x3C` | 原始 seg1 table；原生 lookup 與 shell command 執行 |
| shell 送件 | shell command `C03F5DC0`，`C03F5FD0 → C03F5730` 查名字，`C03F6024 → C02DBAF0` 取得 notifier，`C03F6028` 讀 key，`C03F602C → C02DBBE8 → C02DBFF0 → C01F8D24` 送 4 bytes，timeout 3000 | 原生 shell／strcmp／strncmp／送件橋接；RTOS queue 出口 stub |
| notifier worker | `C02DC0A8` 由 `C02DC030 → C01F8B50` 收件、加鎖，再 `C02DC138` 掃 7 個 observer，呼叫其 vptr `+0xC` | worker／排程只做 source review；原生 7-observer dispatch 有執行，註冊狀態由 fixture 明確建立 |
| physical → GUI | DeviceOperationObserver 原始 vptr `C0CFD550` 的 `+0xC = C0515960`。`C2F23F54 = {0x3B,0x18,0,-1,C0515A28}`；OFF 下一列用 `C0515AB0`。`C0515A28 → C0516950 → C05166E8` 建 44-byte GUI packet：word 0 `0x18`、byte 4 press `1`／release `0` | 原生 observer、map、packet 建立；GUI filter/coalescing 明定 inactive，locks／log／queue append／notify stub |
| GUI callback 初始化 | `C05123D8` 的 MOVW/MOVT 建立 table base `C2F23848`；`C05124FC` 將 `C05114E0` 寫到 `base+0xBC = C2F23904`，配對 GUI code 在 `C2F23900 = 0x18` | 原生完整 initializer 執行並檢查寫入 |
| current screen 分派 | `C0510EB8` 掃同一 table，`C0510FA0` 間接呼叫 callback。`C05114E0` 從 screen `+8` 的 vptr 讀 `+0x6C`，將 GUI packet `+4` 交 handler。standby vptr `C0CD7960` 與 QS vptr `C0CD1234` 的原字皆指到 `C0451478` | 原生 current-screen table dispatch、wrapper、原始 standby／QS vtable；screen pre-notification、observer／mode getter stub |
| capture handler | `CommonEventHandler_w71c1__v25` `C0451478`：只在 press 非零且 `C04B6818` eligibility 真時，呼叫 `C04B67E0` 取 capture state，然後 `C04B6B00` | 原生按下／放開分支；eligibility／state ownership 為明確 fixture |
| RecMgr bridge | `C04B6B00` 取得 `state=C04B6A28()`；非零則呼叫 display-mode 邊界，接著 `C0370CF8` 取 RecMgr、`C0371428(recMgr,(state^1)&0xFF,1)`。`C0371428` 讀原 vptr `C0B9928C+0x7C = C0372688` | 原生 bridge／虛擬呼叫；state 判定、display side effect／singleton getter stub |
| screenshot event 建立 | `C0372688`（`XC_RecMgrImpl__v29`）清 0xBC bytes，word0=`0x18`、byte4=`1`、byte10=`state^1`、byte11=`1`、word14=`0`；`C03726D4 → C03A0798(cameraFunction,request)` | 原生 memset 與完整 constructor；CameraFunction 佇列出口 stub，逐 byte 比對 request |
| event 命名／handler | seg1 event-name table `C2F1FA78[0x18] = C0B9FD5A = "INTR_REC_SCREENSHOT"`。CameraFunction table `C0B9E034 + 0x18*16 = C0B9E1B4 = {0x18,0,-1,C03A1F78}`。`0x19` 下一列為 SAVE_FILE handler `C03A1FE0` | 原字表與字串精確 assertion；不把 GUI 的 `0x18` 與 RecMgr 的 `0x18` 當成同一 enum 的假設 |
| CameraFunction 真 handler | `C03A1F78` 清 0x168-byte request，word4=`0x18`、wordC=`1`，把原 request `+10/+11/+14` 複製到 `+15C/+15D/+160`，`C03A1FC0 → C0388990` 取 recording-function owner，`C03A1FC8 → C03A9558` 送件 | 原生指令精確 xref；此 fixture **不執行**這一段，producer 後段由同目錄其他 fixture 接續 |

`C03A0798` 實作查表、filter、配置 0xC0 request、copy 0xBC 並 enqueue；CameraFunction worker `C03A34A8` 收件後呼叫 `C03A3398`，再以 `C0B9E034` 選 handler。這是 queue 出口後的 source 證據，並非本 fixture 的執行覆蓋。

## 可重用的最小執行單元

`KeyDispatch` 使用相同 ROM 加 **seg1 C2EF6E00 overlay**，只准執行列出的 native function ranges／具名 stubs，未知程式或不允許的寫入直接失敗；每次呼叫檢查 SP 與 r4–r11 守恆。MAIN 在 C2F2xxxx 的 bytes 仍是壓縮來源，不能把未 overlay 的垃圾當 table。

`physical(0x3B)` 走原生 notifier observer dispatch，回傳精確的 GUI packet；`dispatch(packet, 'standby'|'qs')` 走原生 `C0510EB8`、stock vtable、capture handler 與 RecMgr constructor。`requests` 保留 `C03A0798` 收到的原始 0xBC bytes，供下游 handler fixture 直接接續。成功案例覆蓋兩種 screen、兩種 capture state；另有 release／ineligible 零送件與未知 code 拒絕。shell command 另以原生 `C03F5DC0` 驗證 RTOS 出口真的收到 `0x3B/0x3C`。

GUI worker 的排程／policy 優先序、真實 observer 註冊與 screen 生命周期不在這個有界單元內；本 fixture 沒有宣稱抓到當時相機的 eligibility 或 state。此 fixture 可交接的最小執行接點是 **C03A1F78 的 0xBC → 0x168 轉包**，其後接 `C03A9558` 與 recording-function 的事件 dispatch；毋須再猜泛用固定 1024×682 routine。同目錄 screenshot producer 後段的獨立證據應與本報告共同閱讀。

## Source 交叉檢查位置

- `out/decomp/full/blk_c02.c:138920`（physical submit）、`:139129`（RTOS enqueue）、`:139166`（worker）、`:139191`（observer dispatch）。
- `out/decomp/full/blk_c05.c:13590`（DeviceOperationObserver）、`:14252`（GUI packet）、`:14362`（press packet）、`:10431`（EventMessageMgr worker）、`:10510`（current screen dispatch）。小 wrapper 與 callback initializer 未出現在這份 decomp，用原字反組譯。
- `out/decomp/full/blk_c04.c:57416`（capture handler）、`:137693`（capture request bridge）。
- `out/decomp/full/blk_c03.c:77987`（RecMgr virtual bridge）、`:79126`（constructor）、`:110241`（CameraFunction enqueue）、`:111921`（event dispatch）。`C03A1F78` 小 handler 同樣需原字反組譯。

重跑：`/usr/bin/python3 -B projects/sensorlab-imx410/validation/20261030-lv-aspect-fix/offline-capture/test_capture_key_dispatch.py --json projects/sensorlab-imx410/validation/20261030-lv-aspect-fix/offline-capture/capture-key-dispatch.json`。
