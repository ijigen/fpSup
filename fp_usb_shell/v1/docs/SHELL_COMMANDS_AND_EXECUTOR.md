# SIGMA fp — Debug/Factory Shell 指令表(AutoRun 能玩什麼)

fp Ver.5.02。AutoRun.txt 開機時無條件執行這些 shell 指令,**無權限閘**。
指令表 @ROM `0xc0bac14c`(seg0 off 0xbac14c),`{char name[0x14]; void* handler}` stride 0x18,**77 條**,NULL 結尾。
dispatcher `FUN_c03d9c20`(tokenize → memcmp 名稱 → `handler(printfn, argc-1, &argv[1])`)。
AutoRun 路徑:`XC_ShellScriptAutoRun @c03da3f8` → `FUN_c03da758("_AutoRun.txt",1)` → shell task `FUN_c03da178`。
> ⚠️ 相關安全:讀 = 安全;RAM/MMIO poke = 頂多當到重開機;**`prom write` = 非揮發,可能毀校準/變磚 —— 動前先 `prom readfile` 全備份**。

═══════════════════════════════════════════════════════════════
## ★ 寫入原語(突破上限的關鍵,全部 CONFIRMED)
═══════════════════════════════════════════════════════════════
| 指令 | 語法 | 作用 / reach |
|---|---|---|
| **mem set** | `mem set [addr] [data]` | **任意 32-bit 記憶體/MMIO poke**。handler `FUN_c03fa010`,直接 `*addr=data`(blk_c03:171070),**僅檢查 4-byte 對齊,無範圍限制**。可達 DRAM/SRAM/**SoC 週邊暫存器(0x3xxxxxxx)**。字組粒度。 |
| **i2c w** | `i2c w [dev] [reg] [data] [cnt]` 或 `i2c [name] w …` | **I2C 匯流排寫入**任一裝置(影像感光元件、PMIC…)。handler `FUN_c03e98d0`,payload ≤0x10 bytes。`i2c list` 列裝置、`i2c r` 讀。 |
| **prom write** | `prom write [id] [srcAddr] [size]` / `prom writefile [id] [path]` | **EEPROM/serial-flash(校準區)非揮發寫入**。handler `FUN_c0406190`。`prom read/readfile` 讀出。⚠️ 高風險。 |
| **port set** | `port set [PORT_NAME] high\|low` | 具名 GPIO 驅動。`port get` 讀。 |
| mem get | `mem get [start,,size]` | RAM/MMIO hexdump 到 console |
| mem save | `mem save [path] [start,,size]` | RAM→SD(我們一直用的唯讀 dump) |

**→ 結論:有 `mem set` = 有任意 poke = 這台 fp 開機時基本上「可軟改機」。**

═══════════════════════════════════════════════════════════════
## 功能 / 限制 / 模式 / 校準
═══════════════════════════════════════════════════════════════
**`menu [Setter] [value]`**(`FUN_c0402f98`,表 `0xc0bbb0fc`,~65 setter)—— 直接寫作用中設定:
- **ISO**:`SetIsoHigh` / `SetIsoLow` / `SetIso` / `SetIsoStep` / `SetIsoHigh/LowSensitivitySupport` / `SetIsoBinningSupport`
- **快門**:`SetShutterSpeedLimitHigh` / `SetShutterSpeedLimitLow` / `SetShutterAngle[LimitLow]` / `SetIsBulbMode`
- **光圈**:`SetFnum` / `SetFnumOpen` / `SetFnumClose`
- **連拍/驅動**:`SetContinuousShootingSpeed` / `SetDriveMode` / `SetIntervalRec*`
- **AE**:`SetExpMode/MeteringMode/Comp/CompHdr` / `SetProgramShiftSupport` / `SetAeBracket*`
- **AF**:`SetFocusPosition/Mode/Area/AreaSize` / `SetIsPreAf` / `SetFullTimeAfSupport` / `SetFaceDetectMode` / `SetFocusLimitter` / `SetExpansionAfSupport`
- `menu dump/load/save/reset/factoryReset`

**`imager set_gain_state [flag]`**(`FUN_c03f52e8`)—— 感光元件讀出 / **RAW bit-depth 模式**:
`0`default `1`acq `2`movie `3`through+acq `4`movie_raw **`5`movie_raw_10bit `6`movie_raw_12bit `7`movie_raw_8bit** `8`數位增益off。
→ **直接接你的 CinemaDNG bit-depth 議題**(flag 6 = movie RAW 12-bit)。

**`adj imager set/get/disp/sim`**(`FUN_c03dc1a0`)—— 感光元件調整/校準資料讀寫。`imu` = 陀螺/OIS offset 校準。
**`pic` / `optic`**(`FUN_c0404e98`,表 `0xc0bc00e8`)—— ISP 逐功能 `0 auto/1 force_off/2 test`:`distortion`/`aberration`/`shading`/`3ddnr`/`monofilter`/`tbsd`/測試圖樣 `set`。→ 可強制關校正、開測試圖樣(服務模式)。
**`ae flck 50\|60\|off`**、`sdcard readOnly/format/mnt`、`pw_save eco/sleep/poff`、`fwup`(韌體更新)、`setconfig`/`setting`。

═══════════════════════════════════════════════════════════════
## 資料萃取(唯讀)
═══════════════════════════════════════════════════════════════
- `mem get` / `mem save` —— RAM/MMIO
- `prom read [id] [size]` / `prom readfile [id] [size] [path]` —— **校準 PROM dump**(→ 色彩科學:WB/CCM 校準值可能在此)
- `play cinelog / cinelogone / cinelognow`(`FUN_c04057c8`)—— **CinemaDNG log/幀擷取**;`play cinemagraph edit load/save`、`yuv_read`
- `qr dump_yuv / dump_y8`(`FUN_c0407298`)—— dump YUV/Y8 影像緩衝
- `pic sig_dsccal`(訊號處理中途資料)、`pic print_cp/print_tag`(cDNG/tag)
- `ctrl mediaOut [path]`(緩衝→檔)、`ctrl save_log/errstk/errlog`
- `analyzer tskmon_out`、`tkos skdump/tsklist/stkchk`

═══════════════════════════════════════════════════════════════
## 完整 77 條(名稱 → handler)
═══════════════════════════════════════════════════════════════
記憶體/CPU/RTOS:`mem`c03fa2a8 `memmgr`c03fa878 `ddr`c03dfb40 `dbg`c03e0430 `drcv`c03dff50 `runtime`c0407da0 `status`c040fe78 `sys`c040fa58 `analyzer`c0410da8 `ts`c0418388 `tsd`c0410638 `tkos`c0411fb8 `port`c0405e18 `pmctest`c0405cd8 `ppmgr`c03e7070 `reboot`c0405dd8 `rebootf`c0405df8 `poff`c0405d60 `pw_save`c0405fd0 `echo`c03d99a0 `#`c03d99f0 `help`c03e9598
匯流排/裝置/韌體:`i2c`c03e9628 `prom`c0406690 `device`c03e2070 `dfi`c03e24e8 `detect`c03e13e8 `model`c03df298 `version`c03df218 `versioncheck`c041fcf8 `setconfig`c03df2d0 `setting`c041e330 `fwup`c03e73b0 `cam`c03db748 `adc`c03dba40 `battery`c03dead8
影像/感光/ISP/錄放:`imager`c03f52e8 `adj`c03dc1a0 `optic`c04037d8 `pic`c0404e98 `wb`c0420218 `still`c040f130 `movrec`c0403558 `rec`c04074e8 `recstate`c0407ba8 `rectmlg`c0407748 `play`c04057c8 `qr`c0407298
曝光/AF/AE/鏡頭:`menu`c0402f98 `ae`c03dc8e8 `af`c03dd020 `lens`c03f8cc0 `levelgauge`c03f8e98 `imu`c03ea2f8
閃燈/LED/I-O/UI/儲存:`strb`c040f7f0 `extstrb`c03e66e0 `fl`c03e6bb8 `led`c03f60c8 `usb`c0419028 `uart`c0419548 `gps`c03e7bd8 `audio`c03de338 `key`c03f5dc0 `touch`c0412958 `ui`c0419bc8 `gui`c03e8f98 `display`c03e5510 `evf_bri`c03e2f58 `event`c03e5a28 `ptp`c0406c30 `sdcard`c040b4d0 `dir`c03e2980 `mkdir`c03e2d00 `time`c04112c0 `ctrl`c040d538 `sg3`c040b800

═══════════════════════════════════════════════════════════════
## 開機時可用性(AutoRun 觸發早)
═══════════════════════════════════════════════════════════════
- **立即可用**(純 CPU/記憶體,不需子系統):`mem set/get/save`、`port set/get`、`reboot`、`ddr`、RTOS 內省。**最高價值的 `mem set`/`port` 開機就能用**。
- **需驅動已 init**:`i2c`、`prom`、`imager`/`adj`/`imu`、`pic`/`optic`/`play`/`qr`、`rec`/`movrec`、`menu Set*`。開機太早跑可能 no-op 或作用在未初始化狀態;到達對應 runtime 狀態後才可靠。逐子系統 init 順序 vs AutoRun 時機未逐一追。

═══════════════════════════════════════════════════════════════
## 未解 / 待追
═══════════════════════════════════════════════════════════════
1. 沒有明確的「影片錄影時間上限」指令 —— `rectmlg` 只存 tag 字串;上限可能是 `menu`/`setconfig` 值而非獨立指令。
2. I2C bus/address map、哪個 `i2c list` 名稱 = 影像感光元件 vs PMIC(需讀 `FUN_c030c610` 裝置表)。
3. `prom` device-id → 實體零件對應(哪個 id 是校準 EEPROM,需 `FUN_c0041f78` registry)。
4. 逐子系統 init 順序 vs AutoRun 精確時機(硬體指令在觸發當下是否安全)。

關鍵 ROM:指令表 `0xc0bac14c`;dispatcher `FUN_c03d9c20`;mem write `FUN_c03fa010`(store @blk_c03:171070);addr parser `FUN_c03f9dd8`;i2c write `FUN_c03e98d0`;prom write `FUN_c0406190`;imager `FUN_c03f52e8`;menu 表 `0xc0bbb0fc`。

## ===== FULL SHELL OVER USB — forward to firmware shell executor (2026-08-20) =====
Instead of the worker reimplementing commands, forward the received command string to the firmware's
native shell command executor → any of the 77 top commands (+ sub-commands) work over USB.

Executor: **FUN_c03d9c20 @0xC03D9C20** — (r0=shell_ctx*, r1=char* line). Tokenizes on space (strtok
FUN_c067986c, delim " " @0xC0BABB9C, ≤20 tokens), matches token[0] against the command table, calls
handler(ctx, argc=ntok-1, argv=&tokens[1]); not-found → ctx[0]("not found cmd \"%s\"\n", cmd).
- line must be WRITABLE + persist (strtok NULs it; argv points into it).
Command table: **0xC0BAC14C**, 77 entries, stride 0x18 = {char name[0x14] inline, void* handler @+0x14};
end = handler==0. Walker FUN_c03d9bc8 @0xC03D9BC8, accessor FUN_c03db5a0, name-cmp FUN_c01f575c (strncmp 0x14).
Contains: mem→0xC03FA2A8, ctrl→0xC040D538, display→0xC03E5510, movrec→0xC0403558, memmgr→0xC03FA878,
echo→0xC03D99A0. Two-tier: sub-tables walked by FUN_c03db840 @0xC03DB840 (handler @+8), same (ctx,argc,argv).
Global ctx singleton: **0xC3756904** (init FUN_c03d9a10, one-shot guard 0xC3756938; already inited at boot).
ctx[0] = output callback (varargs printf). Default sink FUN_c000ee60 (UART). USE THE GLOBAL CTX for capture
(nested outputs use hardcoded 0xC3756904). Sink push FUN_c03d9ac0(ctx,fn) / pop FUN_c03d9b20(ctx), depth cap 4.
vsnprintf for a custom sink = FUN_c0013f48(buf,size,fmt,&a1).

RECIPE (injected worker per received `line`):
  if(*(void**)0xC3756904==0) FUN_c03d9a10(0xC3756904);      // one-time
  cap_off=0; FUN_c03d9ac0(0xC3756904,&my_sink);             // push capture sink
  FUN_c03d9c20(0xC3756904, line);                            // EXECUTE
  FUN_c03d9b20(0xC3756904);                                  // pop → restore UART
  // send cap[0..cap_off] over USB
  my_sink(fmt,a1,a2,a3){ n=FUN_c0013f48(cap+cap_off,CAPSZ-cap_off,fmt,&a1); if(n>0)cap_off+=n; return n; }

SAFETY: strtok is per-task TLS (safe from worker task). Global ctx output-stack is shared — serialize (don't
run concurrent with active serial-console cmd; REPL usually blocked on its input). Blocking cmds (ctrl sleep,
movrec, file-IO) just block the worker (OK). DO-NOT-FORWARD: reboot/rebootf/poff/pw_save/fwup (reset/brick),
raw-capture (imager createraw / still-raw / RAWGRAB — hangs camera). Prefer a first-token ALLOWLIST.
REPL that normally drives it: FUN_c03d9d18 (reads 256B line → FUN_c03d9c20(0xC3756904,buf)), loop FUN_c03d9dd8.
[Agent auto-safety-review was refused upstream; content is standard RE, no injection; verify before deploy.]

## ===== MILESTONE: gated shell-forward worker DEPLOYED + WORKING (2026-08-21) =====
New worker (camera/shell_rw_worker.S, built to dist/AutoRun.swap-gated-shell.txt via build_swap.py,
worker @0xC072E000, STATE 0xC072F000, gyro hook 0xEB197619) VALIDATED ON HARDWARE:
- Enumerated cleanly past double-blink (NO freeze) — the freeze fix = endpoint-enable (ag_admitted:
  FUN_c01e62a9(4/5)+DALEPENA 0x600) must run AFTER the USB_STATE>=2 gate (post-enumeration), NOT right after
  GO. Doing it pre-enumeration froze at double-blink (attempt 1). Fixed: admission_gate falls to round_loop;
  round_loop's DALEPENA-0x600 gate does the first enable only once state>=2.
- mem read serves (0xC0000000 -> 18f09fe5).
- FULL SHELL OVER USB works: "shl <cmd>" forwards to FUN_c03d9c20 with capture sink. Verified live:
  `shl echo hello`->"hello \n"; `shl help`->"shell usage..."; `shl display colorbar 1 0`-> CAMERA SCREEN
  ACTUALLY TURNED TO COLORBARS + returned "display colorbar \nok 1 0x00000000..."; `shl mem`->usage. Any of
  the 77 firmware shell commands run over USB with captured output.
- For first bring-up the SysNoRemain observer was REMOVED (isolation); recording still handled by round_loop's
  DALEPENA-0x600 + REC_FLAG gate. GO set by cave_entry idle-check (REC_FLAG==0). Re-add observer later.
NOT YET tested: recording gate (shl movrec -> should NOT freeze), long output (single 44B frame truncates —
multi-frame TODO). c32 baseline (d9c5c9db) still on card as fallback; swap SHA 30bc6a3a.
