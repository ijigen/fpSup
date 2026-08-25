# Firmware shell command reference

[English](#english) | [繁體中文](#繁體中文)

The SIGMA fp carries a debug/factory shell with **77 top-level commands**. An
`AutoRun.txt` on the SD card runs them at boot with no permission gate, and
[fp USB Shell](../fp_usb_shell/) forwards any of them over USB with `shl <cmd>`.

SIGMA fp 內建一個 debug/factory shell,共 **77 條頂層指令**。SD 卡上的 `AutoRun.txt`
在開機時無條件執行它們(沒有權限閘),而 [fp USB Shell](../fp_usb_shell/) 可以用
`shl <cmd>` 把任何一條透過 USB 轉發過去。

---

## English

### Where the table is

```
table       0xC0BAC14C   { char name[0x14]; void *handler; }  stride 0x18, 77 entries, NULL-terminated
dispatcher  FUN_c03d9c20  tokenise -> memcmp the name -> handler(printfn, argc-1, &argv[1])
AutoRun     XC_ShellScriptAutoRun @0xC03DA3F8 -> FUN_c03da758("_AutoRun.txt", 1) -> shell task FUN_c03da178
```

Sub-command tables hang off the individual handlers and vary in shape; `display`'s,
for example, is at `0xC0BB1410` with 12-byte entries of `{name, help, fn}`.

### How the usage text below was obtained

Every command marked with its usage text was **asked on a live camera** over the
USB shell — this is the firmware's own help, not a reconstruction. Commands that
could reboot the camera, write non-volatile storage, drive hardware, change
settings, or drop the USB channel were **not invoked**; they are listed with what
they are and why they were skipped.

### Safety

Reading is safe. A RAM or MMIO poke is at worst a reboot. **`prom write` is
non-volatile** and can destroy calibration — back the whole thing up with
`prom readfile` before going anywhere near it.

---

## 繁體中文

### 指令表在哪

```
指令表    0xC0BAC14C   { char name[0x14]; void *handler; }  stride 0x18,77 條,NULL 結尾
分派器    FUN_c03d9c20  tokenize → memcmp 名稱 → handler(printfn, argc-1, &argv[1])
AutoRun   XC_ShellScriptAutoRun @0xC03DA3F8 → FUN_c03da758("_AutoRun.txt", 1) → shell task FUN_c03da178
```

子指令表掛在各自的 handler 下,格式不一;例如 `display` 的在 `0xC0BB1410`,
每項 12 bytes `{name, help, fn}`。

### 下面的用法從哪來

凡是附了用法的指令,都是**在實機上問出來的** —— 那是韌體自己印的說明,不是我們重建的。
可能重開機、寫非揮發儲存、驅動硬體、改設定,或會切斷 USB 通道的指令**沒有執行**,
它們只列出是什麼、以及為什麼跳過。

### 安全

讀取是安全的。RAM / MMIO poke 最壞就是重開機。**`prom write` 是非揮發的**,
可能毀掉校準資料 —— 靠近它之前先用 `prom readfile` 全部備份。

---

## The 77 commands / 77 條指令

### `adc`

`handler 0xC03DBA40`

```
[usage]
  device command : show support device list 
    input: adc list 
  device command : read from i2c with device name 
    input: adc <device name> 
    input: adc <device name> <interval:dec> <count:dec>
  ex1:once) >adc temp_battery 
  ex2:10 times at 10 ms interval) >adc temp_battery 10 10 
  <interval> = 5-100 ms, <count> = max 20 times
```

### `adj`

`handler 0xC03DC1A0`

**Not invoked — adjustment and calibration data / 調整與校準資料**

### `ae`

`handler 0xC03DC8E8`

```
flck       flicker test
  pline      disp pline. arg[0] = 0:ACQ, 1:MONIT, arg[1] = 0:Apex, 1:Not Apex
  exp        disp exposure. 0:ACQ, 1:MONIT
  fix        fix exposure settings.
  ylevel     disp current ylevel.
```

### `af`

`handler 0xC03DD020`

```
print      toggle show the log or not
  dbg        af dbg integer(1st digit) integer(2nd digit)
  msr        Measure
  get        af information acquisition.
```

### `analyzer`

`handler 0xC0410DA8`

```
tskmon_start  start task monitor.
  tskmon_stop  stop task monitor.
  tskmon_out  output task monitor.
  tskmon_top  output current.
  set_logger on or off
ex) Display results in shell 
 >analyzer tskmon_start [option]
 >analyzer tskmon_stop shell
ex) Save result to media 
 >analyzer tskmon_start [option]
 >analyzer tskmon_stop \\DBG_TASK.txt 
ex) Save result to media 
 >analyzer tskmon_start [option]
 >analyzer tskmon_stop 
 >analyzer tskmon_out \\DBG_TASK.txt 
ex) How to link analyzer 
please type >make help
  start option 
  arg 0 tskCount
  arg 1 splitCount
  arg 2 timePreFix
  arg 3 lineBufSize
  arg 4 monitor time(ms)
  arg 5 output file path
ex) analyzer tskmon_start 100000 1000 1000000 100 2000 \\DBG_TASK.txt
```

### `audio`

`handler 0xC03DE338`

```
usage 
   audio mic [int or ext]      : change to [internal or external] mic 
   audio mic chk               : output mic type 
   audio rec start <file path> : start recording (linear PCM format) ex: audio rec start \\test.wav
   audio rec stop              : stop recording 
   audio play media <file path> (sp_vol) : start playing (linear PCM format) ex: audio play \\test.wav 0x38
   audio play beep <id> (vol_level) : start playing beep with/without volume(0xAB to 0x00) ex: audio play beep focus 0x00
   audio param filter           : Set filter params
   audio param alc             : Set ALC params 
   audio codec vol             : Set volume 
   audio codec pga             : Set PGA volume 
   audio codec micb            : Set MICboost volume 
   audio dngpb start <file path> : start playing (linear PCM format) ex: audio play start \\test.wav
   audio dngpb stop              : stop playing
```

### `battery`

`handler 0xC03DEAD8`

```
        500 < [interval] < 10000 ms 
exit : PRESS CAMERA KEY or DIAL
```

### `cam`

`handler 0xC03DB748`

```
start      camera scheduler each stop integer(1st digit)
  stop       camera scheduler each stop integer(1st digit)
  ls         camera scheduler start log
  le         camera scheduler end log
```

### `ctrl`

`handler 0xC040D538`

```
mediaOut   path ex.) \\SAMPLE\\TEST.TXT
  mediaOutTest mediaOutのストレステストを行う。mediaOutのエラー切り分け用 
  mediaIn    path ex.) \\TEST.TXT
  bufferIn   listname
  keyIn      id(0~3), keyID(eXC_EventMessage), iskeyOnOff,isKeyDisable, cmd...
  sleep      ms
  timmem     ex.) timmem [memory no]
  timclr     ex.) timclr [memory no]
  timmemwai  ex.) timmemwai [memory no] [wait time(sec)]
  setmedia   paths ex.) \\TEST1.TXT \\TEST2.TXT
  getmedia   
  errstk     Dump Error Stack
  errlink    print Error Link Addr
  errlog     print Error Log
  save_log   print saved log in nand
  t_assert   test assert
  t_abort    test abort
  t_null     test nullfunc call
  t_zero     test zero div
```

### `dbg`

`handler 0xC03E04D0`

```
disp_mess  Toggle Display Debug Message
  write_out_script Writting out some command sequence to test.txt
```

### `ddr`

`handler 0xC03DFB40`

```
lw         last write : ddr lw [address] (Up to 8 can be set)
  lr         last read  : ddr lr [address]
  w          write log  : ddr w [start_address] [end_address]
  s          stop       : ddr s
  m          mem deadbeef : ddr m [XC_MEMTYPE] 
[tips]  
  Enter the address in hexadecimal. (0x is not required)
  XZ01 can not log the CPU
```

### `detect`

`handler 0xC03E13E8`

**Not invoked — detection engine control / 偵測引擎控制**

### `device`

`handler 0xC03E2070`

```
rc         rc <on/off/s1/s2/push/press/up>: rc status
  mic        mic <on/off>: mic status
  evf        evf <on/off/a_in/a_out/d_e/d_l>: evf status
  strb       strb <on/off>: strb status
```

### `dfi`

`handler 0xC03E24E8`

```
invalid sub command
  analyze    (partition ID)
  load       (partition ID)
```

### `dir`

`handler 0xC03E2980`

```
.
2026/08/25  05:41:28 <DIR>                .Spotlight-V100
2026/08/25  08:56:00                14116 AutoRun.txt
2026/08/25  23:15:12 <DIR>                CINEMA
```

### `display`

`handler 0xC03E5510`

```
first of all ,set ctrl target monitor and layer : >>monitor 
  monitor    (MonitorNum0-1),(layer0-1)
  hdmi       (on:1,off:0)
  lcd        (on:1,off:0)
  lcdTune    
  colorbar   (on:1,off:0) (pattern)
  zoom       (h=640),(v=480),(addr)
  hdmi_onoff (on:1,off:0)
  hdmi_mask  (set mask:1-n, all clr mask:0)
  hdmi_mask_str ON/OFF [option]
  hdmi_edid  setting debug edid
  reset      reset shellmode config
  osd        (on:1,off:0) (color ex::0xffff0000 32bitRed) 
  osdPalette (on:1,off:0) path ex.) \\dump.pal 
  image      (on:1,off:0) (MonitorNum0-1)
  osdfile    path ex.) \\SAMPLE\\TEST.TIF (layer0-1) (MonitorNum0-1) (h) (v) (offset)
  text       (message)
  faceframe  ON : rect{ 0 1 2 3 } , OFF : {}
  focusarea  (on:1,off:0)
  capture    path ex.) \\SAMPLE\\dump.xci ,sel : main(1),sub(2),both(3), compress : none(0),RLE(1),LZ4(2)
  palette    sel : main(1),sub(2),both(3) , isRgb : yuv(0),rgb(1) ,path(for Dump) 
  peaking    (on:1,off:0) (thresh 0~) (normal:0,custom:1)
  address    (count 0~)
  get_out    displ
```

### `drcv`

`handler 0xC03DFF50`

```
Input error
```

### `echo`

`handler 0xC03D99A0`

*No usage text; takes no arguments or prints nothing. / 沒有用法輸出,可能不吃參數或不列印。*

### `event`

`handler 0xC03E5A28`

```
send       send [event] [param]
  getattr    getattr [filter]: output attribute each sub state.
```

### `evf_bri`

`handler 0xC03E2F58`

```
OK
```

### `extstrb`

`handler 0xC03E66E0`

```
test       basic test
  print      toggle show the log or not
  print_with_eve toggle show the log or not
  print_state print ext strb state
  start      task start
  stop       task stop
  flash      flash when task runnning
  toggle     Toggle some setting,
  manual_flash test emmiting manual flash
  param      set get params
```

### `fl`

`handler 0xC03E6BB8`

```
rename     rename [src] [dest]
  del        delete file(currently not working)
  delDir     delete Directory(currently not working)
  createdmy  file create :cinemaDNG
  deloneimg  delete file topFrame
  delCinemaDng delete file CinemaDNG
  delall     delete All file
```

### `fwup`

`handler 0xC03E73B0`

**Not invoked — firmware update path / 韌體更新路徑**

### `gps`

`handler 0xC03E7BD8`

```
set        set: re-set gps info(get and set)
  get_ifd    get: get gps ifd info
  get_pos    get: get gps position/orientation
  clr        clr: clear gps info
  has        has: check if gps has valid info
```

### `gui`

`handler 0xC03E8F98`

```
geti       geti <name>: get variable (int)
  getf       getf <name>: (float)
  gets       gets <name>: (string)
  seti       seti <name>: set variable (int)
  setf       setf <name>: (float)
  sets       sets <name>: (string)
  send       send <AppSyncReqName>
  key        key <eXC_GuiControlType> <eXC_GuiKeyType> <on_off>
  lang       lang <language_id>: change language
 0:ja, 1:en, 2:de_DE, 3:fr_FR, 4:es_ES, 5:it_IT, 6:zh_CN, 7:zh_TW, 8:ko, 9:ru 
 10:nl_BE, 11:pl, 12:pt_PT, 13:da, 14:sv_SE, 15:nn_NO, 16:fi
  lang       lang mode <0/1>: change language mode 
  scr        scr log <0/1>, scr set <screen name>
  req        req log <0/1>: request log mode
  time       time log <0/1>: update/render proc time log mode
  area       area log <0/1>: draw area log mode
  image      image log <0/1>: load image log mode
  trace      trace log <0/1>: trace log mode
  val        val : value function
  mem        get memory information
  gc         gc execution
  ver        get gui version
```

### `help`

`handler 0xC03E9598`

```
shell usage 
 command   : [command] [param1]  [param2] .... [option] [enter]
 up / down : history (max = 30 ) 
command list 
  adc
  adj
  ae
  af
  analyzer
  audio
  battery
  cam
  ctrl
  dbg
  ddr
  detect
  device
  dfi
  dir
  display
  drcv
  echo
  event
  evf_bri
  extstrb
  fl
  fwup
  gps
  gui
  help
  i2c
  imager
  imu
  key
  led
  lens
  levelgauge
  log
  mem
  memmgr
  menu
  mkdir
  model
  movrec
  optic
  pic
  play
  pmctest
  poff
  port
  ppmgr
  ptp
  prom
  pw_save
  qr
  reboot
  rebootf
  recstate
  rec
  rectmlg
  runtime
  sdcard
  setconfig
  setting
  sg3
  status
  strb
  sys
  still
  time
  touch
  tkos
  ts
  tsd
  uart
  ui
  usb
  version
  versioncheck
  wb
  #
option list 
  loop[integer]  repeat command specified times
```

### `i2c`

`handler 0xC03E9628`

**Not invoked — writes the I2C bus (sensor, PMIC) / 會寫 I2C 匯流排**

### `imager`

`handler 0xC03F54E8`

**Not invoked — sensor readout and gain state / 感光元件讀出與增益狀態**

### `imu`

`handler 0xC03EA2F8`

```
cmd : 0 gyro adjustment
cmd : 1 gyro output
     cpu : 0 use mainarm
           1 use subarm
           2 use subarm ring buf
     device_id : sampling device id(=0,1,2,...)
     interval : sampling interval[msec]
     count : sampling count
cmd : 2 get gyro offset
```

### `key`

`handler 0xC03F5DC0`

**Not invoked — injects key events / 注入按鍵事件**

### `led`

`handler 0xC03F60C8`

```
    normal
    charging
    firmup
    movrec
    format
    medinit
    stillwr
    movwrite
    still2
    playlock
    playmark
    playrot
    playdel
    chargerr
    feeding
    output led mode list 
    <no> = 0...n, <level> = 0:low, n:high 
    ex) >led 0 1 
         LED no 0 is on
```

### `lens`

`handler 0xC03F8CC0`

```
sh         (pattern) (0(default):single, 1:burst
  init       
  down       
  getfedge   0(default):inf, 1:near
  cnvfpos    (dist=1000)
  cnvfdist   (pos=1000)
  setfpos    (pos=1000)
  getfpos    Get focus position
  setfinf    Set focus position to infinity
  fc         (pattern) (0(default):scan, 1:scan
  ir         (pattern) (0(default):test
  cnvav      Conver to valid aperture value
  setav      (av=4096(AVx1024)) [spd(AVx1024/frame)]
  getav      Get aperture value
  fwup       (filename=lensfirm.bin) [-f:force]
  clrc       clear cache
  print      toggle show the log or not
  mc         Attach SigmaMountConverter?
  isabs      is Abs Positioning?
  ver        Get current system version
  dof        Get dof pls
  getdata    Get Lens data
  emulate    Set Emulate
  read       cmd read (ex:lens read 0x151e00 30)
  tr         (on/off) no1 no2 ... no10
```

### `levelgauge`

`handler 0xC03F8E98`

```
level gauge command
  check:   check level gauge params (ori, yaw, pitch, roll)
```

### `log`

`handler 0xC03F9C38`

```
usage 
 Log [command] [flag] 
Log Command List 
  act        Active log flag
  inact      Inactive log flag
  expand     Expand log size
  out        Output log data
  mode       Change to the mode to output logs in timely
  modesave   Change to the shellmode 
  level      Set log level
  time       swich time ms or us
  toggle_print Toggle logging with printing realtime or without printing
  clear      clear log data
  info       ロガーの設定状況やメモリ確保状況を表示する
  analyzer   ログ分析を併用する。トグルします。
Log FlagList 
  INIT  0 
  UI  1 
  RECMGR  2 
  CAMERAMGR  3 
  DATAMGR  4 
  OSIF  5 
  IMGCTL  6 
  MOVIE  7 
  LENS  8 
  AE  9 
  MEDIA  10 
  DISP  11 
  FILEMGR  12 
  GUI  13 
  BATTERY  14 
  EVENT  15 
  SIGPRO  16 
  MENU  17 
  RAWSIM  18 
  AWB  19 
  USB  20 
  DEVOPE  21 
  AF  22 
  RECMGR2  23 
  PLAY  24 
  LED  25 
  PIC  26 
  OPT  27 
  ADJ  28 
  BURST  29 
  DRAW  30 
  MEMMGR  31 
  AUDIO  32 
  POWER  33 
  STRB  34 
  GPS  35
```

### `mem`

`handler 0xC03FA2A8`

```
[usage]
  memory write                  : mem set [address] [data] 
  memory read start_address     : mem get [start address,,] 
  memory read start-end address : mem get [start address,end address,] 
  memory read start-start+size  : mem get [start address,,size] 
  memory save start-end address : mem save [path] [start address,end address,] 
  memory save start-start+size  : mem save [path] [start address,,size]
```

### `memmgr`

`handler 0xC03FA878`

```
ERR shl
```

### `menu`

`handler 0xC0402F98`

**Not invoked — writes live camera settings / 直接寫作用中設定**

### `mkdir`

`handler 0xC03E2D00`

```
usage : mkdir [path]
```

### `model`

`handler 0xC03DF298`

```
ERR shl
```

### `movrec`

`handler 0xC0403558`

**Not invoked — movie recording control / 錄影控制**

### `optic`

`handler 0xC04037D8`

```
set        次に続くオプションに値をセット
  get        次に続くオプションの値を得る
```

### `pic`

`handler 0xC0404E98`

```
set        (pattern) (0:off, 1:only tag 2(default):reset
  inputparam (pattern) (0(default):auto, 1:fix
  tbsd       (pattern) (0:off, 1:adjust(default), 2:test, 3:auto, 4:user adjust, 5:get_status
  distortion (pattern) (0(default):auto, 1:force_off, 2:test_mode
  aberration (pattern) (0(default):auto, 1:force_off, 2:test_mode
  shading    (pattern) (0(default):auto, 1:force_off, 2:test_mode
  3ddnr      (pattern) (0(default):auto, 1:force_off, 2:debug_mode, 3:input_mode
  monofilter (pattern) (param)(0:off(default), 1:off_debug_mode, 2:grayscale, 3:binalization (0<param<15), 4:dither_dot
  sig_dsccal Dumping out some data in signal process
  print_cp   Printing cDNG playing info
  print_tag  Printing pic_data When writing tags.
```

### `play`

`handler 0xC04057C8`

**Not invoked — playback control / 播放控制**

### `pmctest`

`handler 0xC0405CD8`

**Not invoked — power-management test / 電源管理測試**

### `poff`

`handler 0xC0405D60`

**Not invoked — powers the camera off / 會關機**

### `port`

`handler 0xC0405E18`

**Not invoked — drives GPIO pins / 直接驅動 GPIO**

### `ppmgr`

`handler 0xC03E7070`

```
sync        
  list        
  erase      Bulk delete
  slot       slot chk
  filter     display filter list
```

### `ptp`

`handler 0xC0406C30`

```
log        ptp log
  sts_chg    send state change command
  focus_comp send Focus Driving Complete command
  capt       disp capt status
  cmd        send command
```

### `prom`

`handler 0xC0406690`

**Not invoked — EEPROM / calibration store — `prom write` is non-volatile / 校準區,`prom write` 非揮發**

### `pw_save`

`handler 0xC0405FD0`

```
sleep      enter led sleep
  poff       enter power off
  eco        enter eco mode
```

### `qr`

`handler 0xC0407298`

```
test       qrcode library test
  decode_log qrcode decode log
  dump_yuv   dump yuv when qrcode decode
  dump_y8    dump y8 when qrcode decode
  play_make  qr make [write data] : make qr code and display
  play_read  qr play_read         : read qr code from play image
  lv_read    qr lv_read           : read qr code from lv
```

### `reboot`

`handler 0xC0405DD8`

**Not invoked — reboots the camera / 會重開機**

### `rebootf`

`handler 0xC0405DF8`

**Not invoked — forced reboot / 強制重開機**

### `recstate`

`handler 0xC0407BA8`

```
ena        Enable RecState
  disa       Disable RecState
  init       Set Initial Value
  movrecstwai Waiting for Movie Rec Start
  movsavewai Waiting for Movie storage
  stillsavewai Waiting for Still storage
  savewai    Waiting for Still/Movie storage
```

### `rec`

`handler 0xC04074E8`

**Not invoked — starts and stops recording / 開始與停止錄影**

### `rectmlg`

`handler 0xC04077A0`

```
addtimeset  LogFile Infomation Get
  setfilename LogFile Set Name
```

### `runtime`

`handler 0xC0407DA0`

```
bounds     
  nil1       
  nil2
```

### `sdcard`

`handler 0xC040B4D0`

```
slot       Second Argument
   no input =Get Now slot
   sd0      =Set SdCard
   ext      =Set External storage
  test       test [slot]
  test2      test2 [slot] [bufsize]                  (Write,Read,Diff)*offset
  test3      test3 [slot] [bufsize] [loop num]       (Write,Read)*loop
  test4      test4 [slot] [bufsize]                  (Write,Read)*offset
  test5      test5 [slot] [au] [bufsize] [filename]  (Write loop, Read loop)
  test6      test6 [slot] [filecount]                (Disk full)
  test_rw    test_rw [slot] [bufsize]                (Write,Read,Seek,Discard,Delete)test
  size       size [slot]
  fnum       fnum [slot]
  sdmode     
  format     format [slot]
  checkinit  checkinit [slot]
  chkop      
  readOnly   readOnly [on|off] [path] : Change attributes | readOnly time : Measure time
  mnt        mnt [slot]  : Mount
  umnt       umnt [slot] : UnMount
```

### `setconfig`

`handler 0xC03DF2D0`

**Not invoked — writes configuration / 寫入設定**

### `setting`

`handler 0xC041E330`

```
read       setting read          : Read all parameter value
  get        setting get [param name]                        : Get specific parameter value
  get        setting get [param name] [index]                : Get specific array parameter value
  set        setting set [param name] [param value]          : Set specific parameter value
  set        setting set [param name] [index] [param value]  : Set specific array parameter value
  write      setting write        : Write all parameter value
  load       setting load          : load all parameter from FlashValue
  save       setting save          : save all parameter from FlashValue
  readcom    setting readcom       : Read XC_CommonSaveData and print it
  readcam    CameraSetting read    : Read all parameter value
  writecam   CameraSetting write  : Write all parameter value
param list 
  cam_still_imagesize.h
  cam_still_imagesize.v
  cam_movie_imagesize.h
  cam_movie_imagesize.v
  cam_frame_rate
  cam_aspect
  exp_mode
  iso
  iso_high
  iso_low
```

### `sg3`

`handler 0xC040B800`

**Not invoked — undocumented / 未知**

### `status`

`handler 0xC040FE78`

```
get        status get [param name]                        : Get specific parameter value
  get        status get [param name] [index]                : Get specific array parameter value
param list 
  is_recording
  app_current
  app_lv_attribute
```

### `strb`

`handler 0xC040F7F0`

```
dump       eval dump
  wait
```

### `sys`

`handler 0xC040FA58`

```
selfrefresh sys selfrefresh [on/off]
  selfStopTime sys selfStopTime 600 : [unit = sec / 0 = default setting]
  selfConfig output selfRefresh Setting
```

### `still`

`handler 0xC040F130`

**Not invoked — still capture / 靜態拍攝**

### `time`

`handler 0xC04112C0`

```
set        >time set YYYY/MM/DD hh:mm:ss
  get        >time get
  utc_offset >time utc_offset [+3:00/-5:30...]
  summer_time >time summer_time [+1:00/+0:00]
  reset      >time reset
  tickm      >time get ticktimer ms
  ticku      >time get ticktimer us
  tickmstr   >time get ticktimer ms Measurement Start
  tickmstp   >time get ticktimer ms Measurement Stop
```

### `touch`

`handler 0xC0412958`

```
tap        tap [x] [y]
  dtap       dtap [x] [y]
  drag       drag [start x] [start y] [end x] [end y] [point num]
  th         th [threshold type] [value]
```

### `tkos`

`handler 0xC0411FB8`

```
tsklist    display task list
  skdump     dump task stack : tkos skdump [tsk_id / tsk_name] [data max:unit=byte, option(default=0x200)]
  stkchk     check task stack : tkos stkchk
  mtx        ref mtx : tkos mtx [all]
  task       control tasks
  minth      check interrupt handler : tkos minth on/off/print
```

### `ts`

`handler 0xC0418388`

```
ram        (dst) (src) (original size)                                       : RAM to RAM
  nand       (part id (str)) (dst) (work) (comp size) (original size) (offset) : NAND to RAM
```

### `tsd`

`handler 0xC0410638`

```
threshold  set threshold 
  temp       Get the temperature
```

### `uart`

`handler 0xC0419548`

```
uart <baudrate>       : set baudrate (example: uart 115200)
uart def              : set default baudrate
uart force <baudrate> : set baudrate (no check)
uart info             : print current baudrate
```

### `ui`

`handler 0xC0419BC8`

```
log        log <on/off>
  detect_log detect ui log <on/off>
  rload      load <file name> <bank:0-6> <load sys set:0/1>: load setting bin file
  rsave      save <file name> <title name:16> <icon name:2>: save setting bin file
  rdump      dump qr preview from current buffer
  rget       get recommend setting type
  rlog       rlog <on/off>: recommend load / save log ctrl
```

### `usb`

`handler 0xC0419028`

**Not invoked — switches USB mode — would drop this very channel / 切換 USB 模式,會斷掉這條通道**

### `version`

`handler 0xC03DF218`

```
model       = w71c1 
xc version  = V91 
rel version = 5.02.0.V91  
git hash    = 13aa621060efff11aaba9b21ad925005302605cf
```

### `versioncheck`

`handler 0xC041FCF8`

**Not invoked — version enforcement / 版本檢查**

### `wb`

`handler 0xC0420218`

```
fp         set fullpower(center 1/4) mode
  cl         clear all debug mode
  dbg        wb dbg integer(1st digit) integer(2nd digit)
  rec_arg    change arguments from recmgr to specified value
  get_kelvin get kelvin and tint (works on only w71c1)
```

### `#`  — comment / 註解

`handler 0xC03D99F0`

*No usage text; takes no arguments or prints nothing. / 沒有用法輸出,可能不吃參數或不列印。*

