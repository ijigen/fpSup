# console

A live view of what the camera is doing — autofocus state, IMU, exposure, face
and tracking boxes — read straight out of memory over the USB shell.

即時顯示相機正在做什麼 —— 對焦狀態、IMU、曝光、人臉與追蹤框 ——
全部透過 USB shell 直接從記憶體讀出來。

| file | what it is |
|---|---|
| `fpstate.py` | The address table and the reader. Roughly forty live cells: gyro ring, accelerometer cache, gain and ISO, AF drive/area/route, the two contrast bands, peak tracking, body-motion flag, tracking box<br>位址表與讀取器。約四十個即時欄位:陀螺 ring、加速計快取、增益與 ISO、AF 驅動/區域/路由、兩個對比頻帶、峰值追蹤、機身移動旗標、追蹤框 |
| `dashboard.html` | The browser view<br>瀏覽器介面 |

**Not runnable as-is.** It reads through the retired worker's `mem read`
command. On [fp USB Shell v2](../fp_usb_shell/) the same cells are reachable with
`shl mem get <addr>,,<len>`, so the address table is the part that carries over
unchanged — and that table is the valuable half.

**目前不能直接跑。** 它是透過已退役的 worker `mem read` 指令讀的。
在 [fp USB Shell v2](../fp_usb_shell/) 上,同樣那些欄位用
`shl mem get <addr>,,<len>` 就讀得到,所以**位址表是原封不動可以沿用的部分** ——
而那張表正是有價值的那一半。
