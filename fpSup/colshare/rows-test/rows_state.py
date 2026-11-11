#!/usr/bin/env python3
"""COL-Share 列數測試版:上機時讀狀態(唯讀 mem get)與按 COLOR 鍵。不寫記憶體、不呼叫韌體函式。

    cd fpSup/fp_usb_shell
    python3 -B ../colshare/rows-test/rows_state.py state     # 列數、active、游標、假客戶記得的列、getter 筆數、AEL 範圍
    python3 -B ../colshare/rows-test/rows_state.py color     # COLOR 鍵一下(COLORON / COLOROFF),等 2 s

state 的欄位(colshare.c struct cols;位移依 getter 筆數算出的 CS_MAX):
  rows     L->n         清單上現有的額外列(所有客戶加總,上限 CS_MAX)
  active   L->active    0 = 原廠模式,j = 第 j 個額外列(GUI 15 + j)
  cur      L->cur       COLOR 選單游標的 GUI 列(15 = OFF,16.. = 額外列)
  pend     L->pend      選單裡剛選、還沒經 setter 的列(1 = OFF,j + 1 = 第 j 列)
  menu     L->menu      ColorButtonMenu 開著 = 1
  tpick    假客戶記得的列(key + 1;選單關閉時 on_pick 寫)
"""
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'fp_usb_shell'))
import putfile as P            # noqa: E402  (mem_get: read-only)
import ui_drive as U           # noqa: E402

SETTER = 0xC0075CF4            # bl -> COL-Share's veneer {ldr ip; ldr pc; context; stub}
GCNT = 0xC06C07D8              # mov r2, #16 + CS_MAX
ADV = 0xC1D6ED48               # AEL page range: BE 15 + CS_MAX
RUN_MAGIC = 0x4E55524C


def ctx():
    w = P.mem_get(SETTER, 1)[0]
    if w >> 24 != 0xEB:
        raise SystemExit(f'setter site {w:08X}: not patched -- COL-Share is not loaded (read \\fpSup\\LOAD.LOG)')
    off = ((w & 0xFFFFFF) ^ 0x800000) - 0x800000
    v = (SETTER + 8 + off * 4) & 0xFFFFFFFF
    return P.mem_get(v + 8, 1)[0]


def state():
    L = ctx()
    magic, n, active, pend, cur, menu = P.mem_get(L, 6)
    cnt = P.mem_get(GCNT, 1)[0] & 0xFF
    cs_max = cnt - 16
    tc = L + 888 + 32 * (cs_max - 4) + 12 * (cs_max + 1) + 4      # struct cols .tc (rows-test builds only)
    tmagic, _api, tsup = P.mem_get(tc, 3)
    tpick = P.mem_get(tc + 52, 1)[0] if tmagic == 0x31434C43 and tsup == 0x54535443 else None
    adv = struct.unpack('>f', struct.pack('<I', P.mem_get(ADV, 1)[0]))[0]
    print(f'magic {"ok" if magic == RUN_MAGIC else hex(magic)}  CS_MAX {cs_max}  rows {n}  active {active}  cur {cur}  '
          f'pend {pend}  menu {menu}  tpick {tpick if tpick is not None else "(no test client)"}  '
          f'getter {cnt}  AEL range {adv:g}')


def color():
    U.sh('key', 'COLORON'); time.sleep(0.15); U.sh('key', 'COLOROFF'); time.sleep(2)


if __name__ == '__main__':
    {'state': state, 'color': color}.get(sys.argv[1] if len(sys.argv) > 1 else 'state', state)()
