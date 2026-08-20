# fp_usb_shell_sup — SIGMA fp USB Shell

[English](#english) | [繁體中文](#繁體中文)

---

## English

A **USB shell for the SIGMA fp** (firmware Ver 5.02): run the camera's own firmware shell
commands over the USB vendor interface. Injected via `AutoRun.txt` (RAM patch at boot, no reflash),
driven by a small host daemon.

**Headline capability:** `shl <cmd>` forwards ANY of the 77 firmware shell commands to the native
shell executor and returns the captured output. Live-verified — `shl display colorbar 1 0` turned the
camera screen to colorbars over USB.

### Folders
| folder | contents |
|---|---|
| `autorun/` | `AutoRun.full-shell.txt` (gated worker + `shl` full-shell forward) · `AutoRun.v27-stable.txt` (minimal stable fallback: mem read/set only) |
| `daemon/` | `fpshelld.c` host daemon (owns the vendor interface, serialises clients, EP05 OUT / EP84 IN) · `PROTOCOL.md` |
| `worker/` | `shell_rw_worker.S` camera-side worker · `build_swap.py` (+ `build_stage5_autorun.py`) that assembles it into a deployable AutoRun · `imu_snapshot.S` + `build_imu_snapshot.py` — a position-independent IMU-gather blob injected at runtime via `mem set` (no autorun change) |
| `console/` | `fpstate.py` live web console + `dashboard.html` — reads camera state over the shell and serves it at `http://localhost:8770/` (gyro / accel level / exposure / AF / tracking / faces) |
| `docs/` | `V27_FREEZE_ROOTCAUSE.md` (why the shell froze the camera, fully diagnosed) · `SHELL_COMMANDS_AND_EXECUTOR.md` (command set + the `FUN_c03d9c20` executor ABI) |

**Live console.** `console/fpstate.py` turns the shell into a monitoring dashboard. The IMU cards
(gyroscope in dps, accelerometer in g, electronic level) are driven by a fast `/imu.json` path: one
injected snapshot routine (`worker/imu_snapshot.S`) gathers gyro-latest + accel XYZ in a single `call`,
drained in one `mem read` — 2 transactions (~10 Hz), no autorun change. Note: gyro's ring cursor `*(rb)`
is an ABSOLUTE pointer; the latest sample is at `*(rb) - 4` (samples at `rb+4 + n*8`, `pad==0`).

### Use
1. Copy `autorun/AutoRun.full-shell.txt` to a fast UHS-II SD card as `AutoRun.txt`.
2. Boot the fp. At the "connect USB" cue (two flashes), plug into the host.
3. Run the daemon: `fpshelld --arm-wait 40 --limit 0` (owns the vendor interface, opens `/tmp/fpshell.sock`).
4. Send commands to the socket:
   - `mem read <hexaddr> <declen>` / `mem set <hexaddr> <hexval>` — direct memory (bounded ranges).
   - **`shl <cmd>`** — forward `<cmd>` to the firmware shell, e.g. `shl echo hi`, `shl display colorbar 1 0`,
     `shl help`. Output is captured and returned (single 44-byte frame today).

### Status (honest)
- ✅ **Full shell over USB works** (live-verified).
- ✅ **v27 freeze root cause fully diagnosed** — un-gated persistent ownership of the DWC3 endpoints
  colliding with USB link transitions (idle-suspend / record reconfig / shutdown teardown). See docs.
- ✅ **link-health gate** survives idle-suspend (no freeze).
- ❌ **Recording while the shell is connected still freezes** — a structural problem: the worker's
  persistently-armed transfer collides with recording's endpoint teardown. Fix is architectural
  (observer-driven pre-disarm, or don't persistently own the endpoints). Do NOT record while connected;
  and do not forward `movrec` / reboot / fwup over `shl`.

### Safety
Injection is RAM/MMIO only (no NAND/flash writes) → worst case is a freeze, recovered by a battery pull;
it does not brick or damage the camera. Keep `AutoRun.v27-stable.txt` as a fallback. 16GB test card only.

---

## 繁體中文

**SIGMA fp 的 USB shell**(韌體 Ver 5.02):透過 USB vendor 介面下相機自己的韌體 shell 命令。
用 `AutoRun.txt`(開機時 RAM patch,不需重刷韌體)注入,主機端用一個小 daemon 驅動。

**核心能力:** `shl <cmd>` 把 77 個韌體 shell 命令中的任何一個轉發給原生 shell 執行器,並回傳輸出。
實機驗證 —— 一個 `shl display colorbar 1 0` 讓相機螢幕真的變彩色條。

### 資料夾
| 資料夾 | 內容 |
|---|---|
| `autorun/` | `AutoRun.full-shell.txt`(gated worker + `shl` 全 shell 轉發)· `AutoRun.v27-stable.txt`(最小穩定 fallback:只有 mem read/set) |
| `daemon/` | `fpshelld.c` 主機 daemon(獨佔 vendor 介面、序列化 client、EP05 OUT / EP84 IN)· `PROTOCOL.md` |
| `worker/` | `shell_rw_worker.S` 相機端 worker · `build_swap.py`(+ `build_stage5_autorun.py`)組成可部署 AutoRun · `imu_snapshot.S` + `build_imu_snapshot.py` —— 一個 position-independent 的 IMU 抓取 blob,執行時用 `mem set` 注入(不改 autorun) |
| `console/` | `fpstate.py` 即時 web 控制台 + `dashboard.html` —— 透過 shell 讀相機狀態,開在 `http://localhost:8770/`(gyro / accel 水平儀 / 曝光 / AF / 追蹤 / 人臉) |
| `docs/` | `V27_FREEZE_ROOTCAUSE.md`(shell 為何會凍住相機,完整診斷)· `SHELL_COMMANDS_AND_EXECUTOR.md`(命令集 + `FUN_c03d9c20` 執行器 ABI) |

**即時控制台。** `console/fpstate.py` 把 shell 變成監控 dashboard。IMU 卡片(gyro dps、accel g、電子水平儀)
走一條快路 `/imu.json`:注入一個 snapshot 常式(`worker/imu_snapshot.S`),一次 `call` 把 gyro 最新樣本 +
accel XYZ 打包,一次 `mem read` 拿回 —— 2 transactions(~10 Hz)、不改 autorun。注意:gyro ring 的 cursor
`*(rb)` 是**絕對指標**,最新樣本在 `*(rb) - 4`(樣本位於 `rb+4 + n*8`,`pad==0` 驗證對齊)。

### 使用
1. 把 `autorun/AutoRun.full-shell.txt` 複製到快的 UHS-II SD 卡,命名為 `AutoRun.txt`。
2. 開機。看到「連 USB」提示(雙閃)時接上主機。
3. 起 daemon:`fpshelld --arm-wait 40 --limit 0`(獨佔 vendor 介面,開 `/tmp/fpshell.sock`)。
4. 對 socket 送命令:
   - `mem read <hexaddr> <declen>` / `mem set <hexaddr> <hexval>` —— 直接記憶體(範圍受限)。
   - **`shl <cmd>`** —— 轉發 `<cmd>` 給韌體 shell,例:`shl echo hi`、`shl display colorbar 1 0`、
     `shl help`。輸出被 capture 回傳(目前單一 44-byte frame)。

### 狀態(誠實)
- ✅ **全 shell over USB 可用**(實機驗證)。
- ✅ **v27 凍結根因完整診斷** —— worker 未 gate 地永久佔有 DWC3 端點,撞上 USB link 轉換
  (idle-suspend / 錄影 reconfig / 關機拆除)。見 docs。
- ✅ **link-health gate** 撐過 idle-suspend(不凍)。
- ❌ **shell 連著時錄影仍會凍** —— 結構性問題:worker 永久 armed 的傳輸撞上錄影的端點拆除。
  修法是架構級(observer 預先 disarm,或不永久佔有端點)。**連著時不要錄影**;`shl` 也不要轉發
  `movrec` / reboot / fwup。

### 安全
注入只碰 RAM/MMIO(不寫 NAND/flash)→ 最壞是凍結,拔電池即可復原,不會變磚或損壞相機。
保留 `AutoRun.v27-stable.txt` 當 fallback。僅用 16GB 測試卡。
