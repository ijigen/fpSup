# 2026-10-29 媒體偵測三個讀法:上機驗證(唯讀)

相機:SIGMA fp 5.02.0.V91,SD 卡在機內,未插 SSD;待機 live view。Bei 已授權。
工具:`fpSup/fp_usb_shell/callfn.py`(借 echo,參數讀回才 arm)、`putfile.sh/mem_get`。
沒有 mem set 到設定區、沒有錄影/S1/S2/MOV。結束時 echo 槽已還原(`0xC03D99A0`)、`echo hi` 正常。
原始輸出:同目錄 `run1.txt`、`run2.txt`、`run3.txt`、`setting_help.txt`。

## 0. 原生 shell 交叉比對

```
>> version          rel version = 5.02.0.V91
>> sdcard sdmode    sdmode  UHS-II
>> sdcard slot      slot now slot = sd0
>> setting get cam_Current_Storage   -> 0      (鏡像 0xC3758C30,stale,見 §3)
>> setting get cam_is_bulk_write     -> 0      (鏡像 0xC3758C34,stale,見 §3)
```

## 1. 先 mem get 靜態物件(callfn 之前)

```
C2F20884: 00000001                        目前 slot(C0407E20 回傳它)
C351EF78: 00000001 00000000 00000001      guard: slot1 物件(+0x2C0)、slot5 物件(+0x2C8)都已建好
C351EE18: C3760CA4 0 0 0 0 0 C0B97A04 01000101 ...   drv(1):+0x18 vtable、+0x1C=01 +0x1D=01
C351ECB8: C3760C9C C3425858 0 0 0 0 C2E3CF78 00000000 ... drv(5):+0x1C=00 +0x1D=00
vtable C0B97A04 +0x24 = C036BD00(drv5 的 vtable C2E3CF78 +0x24 也是 C036BD00)
```

## 2. callfn(run1.txt)

```
call 0xC0407E20         -> 1            工具檢查 getter
call 0xC0366A98(1)      -> 0xC351EE18   drv(SD)
call 0xC0366A98(5)      -> 0xC351ECB8   drv(SSD)
call 0xC0518410(5)      -> 0            SSD 就緒 = 0(未插,符合預期)
call 0xC036BD00(drv1)   -> 3            SD bus mode = UHS-II  ==  sdcard sdmode ✓
```

## 3. MediaSelect(run2.txt、run3.txt)

```
fac = [C31CAA80] = C31AC59C ;  fac vtable 在 fac+4(不是 +0)= C07397D8
vt+0x354 = C0085370  (就是 return fac+0x1578)
call C0085370(fac)                    -> item = C31ADB14
item: 000000C1 00000100 C31AC540 C0743428 0 0 C31AE3B0 000000FE   (vtable 在 item+0xC)
item vt +0x18..+0x28: C00812A8 C0081538 C0081958 C0081D28 C00AB768
call C0081538(item)   [vt+0x1C, 選項數] -> 1
call C00913F8(item,0xFFFF,1,0x80000001)  -> 0
call C006D530(item,0)                    -> 0      ← 有效 MediaSelect = SD
call C00812A8(item,0) [vt+0x18, 存值指標] -> C31B06B4 ; [C31B06B4] = 1   ← 使用者存的是 SSD
call C00AB768(item,1,0) [vt+0x28, 依媒體修正] -> 0
call C0518490(1) [drv+0x1D 掛載] -> 1 ;  C0518490(5) -> 0
[C31AE3B0] byte+1 = 0   (vt+0x28 第一道閘:非零就直接回存值)
CameraMgrSetting(0xC31F865C+0x40)+0x98 = 0 (Current_Storage) ; +0x9C byte = 1 (bulk)
```

解讀:存值 = 1(SSD),但 SSD 沒掛載 → vt+0x28 修正成 0(SD);C006D530 走快取路徑
(item+5 = 1 → 回 item+0x14 = 0)。live 的 Current_Storage=0、bulk=1 與「v==0 → bulk=1」一致。
`setting get` 讀的是 readcam 鏡像(0xC3758B98 起),沒 readcam 過所以是 0,不能拿來比。
選單截圖沒做成:`ui_drive.py shot` 回 "no new screenshot appeared"(DCIM 已有 >2500 張、
dir 回覆被截斷 —— getfile-dir 假陰性),禁用 S1 下不進選單。

## 4. 待插 SSD 後重跑(開機後才插)

```
cd fpSup/fp_usb_shell
python3 -c "from putfile import sh; print(sh('sdcard slot'))"
python3 -c "
from callfn import call
from putfile import mem_get
call(0xC0407E20)
d5=call(0xC0366A98,5)[1]; print(hex(d5), [hex(x) for x in mem_get(d5+0x18,2)])
call(0xC0518410,5); call(0xC0518490,5)
call(0xC006D530,0xC31ADB14,0)
p=call(0xC00812A8,0xC31ADB14,0)[1]; print(hex(mem_get(p,1)[0]))
print([hex(x) for x in mem_get(0xC31ADB14,6)])
call(0xC00AB768,0xC31ADB14,1,0)
"
```
預期:SSD 就緒 1、C006D530 回 1。若 C006D530 仍回 0 而 C00AB768 回 1,代表 item 快取
(item+5/+0x14)沒在插拔時失效 → sup 不能用 C006D530,要自己算(見 §5 的 recipe B)。

## §5 C 寫法（磁碟滿時沒寫進來，2026-10-29 補）
```c
/* drv(slot) = ((void*(*)(int))0xC0366A98)(slot);  只能傳 1 或 5（裡層 C036D4D0 只接受 1/5，2/3 會 assert 卡死） */
ssd_ready = ((u8(*)(int))0xC0518410)(5);                 /* = *(u8*)(drv(5)+0x1C) */
d = drv(1); vt = *(u32*)(d+0x18);
sd_mode = ((int(*)(void*))*(u32*)(vt+0x24))(d);          /* 0 無效 / 1 Normal / 2 UHS-I / 3 UHS-II；ioctl 0x115，在任務脈絡呼叫 */
/* MediaSelect 寫法 A（原廠鏈；fac 的 vtable 在 fac+4，item 的在 item+0xC） */
fac = *(u8**)0xC31CAA80;  fvt = *(u32*)(fac+4);
item = ((u8*(*)(void*))*(u32*)(fvt+0x354))(fac);         /* = fac+0x1578 */
ivt = *(u32*)(item+0xC);
n = ((u32(*)(void*))*(u32*)(ivt+0x1C))(item);  if (!n) bail;   /* n=0 時 C00913F8 assert 卡死 */
idx = ((u32(*)(void*,u32,u32,u32))0xC00913F8)(item,0xFFFF,n,0x80000001);
ms = ((int(*)(void*,u32))0xC006D530)(item, idx);         /* 0=SD 1=SSD（item 快取） */
/* 寫法 B（不靠 item 快取，邏輯同 C00AB768） */
raw = *((u32*(*)(void*,u32))*(u32*)(ivt+0x18))(item,0);
sd = ((u8(*)(int))0xC0518490)(1); ssd = ((u8(*)(int))0xC0518490)(5);   /* drv+0x1D = 掛載 */
ms = (sd && !ssd) ? 0 : (ssd && !sd) ? 1 : raw;
```
媒體 = `ssd_ready && ms == 1` ? SSD : SD（照原廠格率選單）；SD 再用 sd_mode 選 R（UHS-II 240 / UHS-I 87）。
SSD 那一半待 Bei 開機後插 SSD 再驗（item 快取插拔後會不會更新）。

## §6 SSD(2026-10-29 21:00–21:04,未偵測到 SSD,序列未跑)

原始輸出:`run4_presence.txt`。只做唯讀 mem get + 三個 getter,沒有 drv()、沒有 item 呼叫。

```
>> version          rel version = 5.02.0.V91
>> sdcard slot      slot now slot = sd0
C2F20884: 1
drv(5) C351ECB8: C3760C9C C3425858 0 0 0 0 C2E3CF78 00000000   (+0x1C=0 +0x1D=0)
drv(1) C351EE18: C3760CA4 0 0 0 0 0 C0B97A04 01000101
輪詢 drv5+0x1C 每 20 s × 7(21:00:53–21:02:53):全部 0
call 0xC0407E20 -> 1 ; call 0xC0518410(5) -> 0 ; call 0xC0518490(5) -> 0
echo hi -> hi(shell 正常,未重開機)
```
結論:約 2 分鐘內 SSD 未就緒/未掛載 —— 不是方法 A/B 的問題,是 SSD 沒進來。§4 的 A/B 判定仍待驗。

離線補充(未上機):SSD vtable C2E3CF78 +0x24 = C036BD00(與 SD 同一支,ioctl 0x115,
SSD 上意義未定)、+0x28 = C06AFC40:`if !drv+0x1D return 0; h = vt+0x14(d); ioctl(h,0x1001,&out) ? 0 : out`
—— 預期即 link Mbps;兩支都先看 +0x1D(掛載),未掛載直接回 0,呼叫安全。
SD vtable +0x28 是 C036BD88(不同)。

重跑:插好 SSD(開機後)、確認 `sdcard slot`/drv5+0x1C 非零,再跑同目錄 `ssd_run.py`
(§4 序列 + SSD vt+0x24/+0x28 + SD 端 + item 重推導;item vtable 與 C0085370 有 assert,
n==0 不呼叫 C00913F8,drv() 只用字面 1/5)。
