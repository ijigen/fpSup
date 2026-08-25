# DFD hook-push — 相機主動推綠通道 AF-band 資料(高速、零 stall)

把資料從 fp 取出來,改用**相機端 hook-push**(worker 主動 arm ctx4 TRB + StartTransfer 把 buffer 推出 EP84 IN),
取代慢又會 stall 的 host-pull(read_mem 分塊 / RAWGRAB)。

## 成果(實測)
- **hook-push:0.125 ms/幀,零 stall**(BATCHPUSH 100 幀 err=SUCCESS)。對比 RAWGRAB **86 ms/grab + 會 stall EP84**(要拔線復原)→ **快約 680 倍**。
- **綠通道 AF-band 逐線能量**(256 線)經 hook-push live 串出,`dfd_live.py` 在瀏覽器畫 live 曲線。

## 檔案
| 檔 | 說明 |
|---|---|
| `push_n.S` | 批次推 N 幀常式:每幀 arm ctx4 TRB(bufptr/size/ctrl=0x813)→ StartTransfer(9)→ wait(4)。FN_WAIT 每幀同步 host bulk-IN(無 per-grab 命令、無 usleep、無 stall)。注入 @0xC072F600。 |
| `push_green.S` | 同上,但每幀讀 fresh 綠 band buffer 指標(*(0xC3404768))、驗證 0x40000000–0x60000000、**零拷貝**直接 arm ctx4 指向它;無效推 fallback 0x50000000。 |
| `dfd_live.py` | Live web 工作台(http://localhost:8771/):配速 BATCHPUSH 抓綠 band + peek mposm/peakNow,畫 live profile。 |
| `../daemon/fpshelld.c` | 加了 **`BATCHPUSH <framesize> <nframes>`** 命令(見下)。 |

## 指令 / 用法
```bash
# 1) 起 daemon(含 BATCHPUSH)
cd <daemon>; make; ./fpshelld --arm-wait 4 --inter-wait-ms 40 --limit 0

# 2) 注入 push_green(組譯 -> mem set 到 0xC072F600)。words 見 push_green.S 組譯輸出。
#    (armv7 clang 組譯,extract .text,逐字 `mem set 0xC072F600+i*4 <word>`)

# 3) 推 N 幀綠 band(半按 AF-C 讓綠源有資料):
echo "BATCHPUSH 1024 100" | nc -U /tmp/fpshell.sock     # 或用 socket client
#    -> 存 /tmp/batchpush.bin(N × 1024 bytes,每 1024 = 256 線 int32 綠 band)
#    回應含 perframe ms / MBps / err

# 4) live 工作台:
python3 dfd_live.py    # 開瀏覽器 http://localhost:8771/,半按 AF + MF 掃焦看 profile
```

## BATCHPUSH 命令(daemon)
`BATCHPUSH <framesize> <nframes>`:設 push_N 參數(STATE+0x70=N,+0x74=0x50000000,+0x78=framesize)→
送 `call 0xC072F600`(EP05,觸發 N 次推)→ 連續 bulk-IN N×framesize(每幀由 push_N 的 FN_WAIT 同步)→
存 `/tmp/batchpush.bin`,回報 frames / bytes / perframe ms / MBps / err。

## 關鍵位址
- ctx4(EP84 IN)TRB ptr cell `0xC31E3274`;TRB ctrl `0x813`;size 24-bit(≤16MB)
- StartTransfer `FUN_c01e6b80(9)`;wait `FUN_c01e4e80(4)`
- 綠 band DMA descriptor 表 `0xC340474C`(slot1 bufptr @+0x1C=`0xC3404768`,256 線 int32/幀)
- 對焦:mposm `0xC3291958`、peakNow `0xC32915C4`、g_afpos `0xC32914E0`
- ⚠️ 綠 band DMA 只在 AF-C 主動計算(半按 AF)時才填。

## 穩定卡
`../autorun/AutoRun.STABLE-recsafe-10fe9125.txt` = canonical 穩定 shell(composite PTP+vendor + pre-disarm hook)。
