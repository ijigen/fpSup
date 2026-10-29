# SensorLab-IMX410 core(C 版公式)

把兩條 Python 公式移植成 freestanding C,要在 fp 上跑，並且跟 Python 逐位元相同:

| Python(唯讀 import,不修改) | C 入口 |
|---|---|
| `imx410-lab/readout_cfg.py` `plan()` | `core_readout_plan()` |
| `imx410-lab/smc.py` `create()`(TIM/META/R28/R38/R14/R68/REG/R10 八張表) | `core_smc_create()` |
| `isp-lab/host/isp_formula.py` `plan()` / `row()` | `core_isp_plan()` / `core_isp_row()` |
| `isp-lab/host/isp_formula.py` `min_line_clk()` + `quality.line_hmax()`(R11) | `core_line_hmax()` |
| `isp-lab/host/quality.py` `qualities()` / `vmax_range()` / `settings()` | `core_qualities()` / `core_quality_plan()` / `core_quality_spec()` |

`quality.py` 是 matrix.py 原本的每格邏輯(readout + R11 HMAX、isp RWZM、R2 1025、WIDEN 16 重試、精確 RES、pick)搬出來的共用版;
matrix.py 現在呼叫它(`matrix.json` 重產後逐位元組相同)。`core_qualities(cw, ch, ow, oh, cap)` 回傳每個品質
(merge × AD 11/12/14 × CRCT hbin×vbin)最快的 readout 變體、`hm`、`vmin`(matrix 的 fps_max)、`vmin_lo`(planner 的 0016 退路下限)、
cap 下的 `vmax` 與 `fps_milli`;fps 在 VMAX = vmin_lo..16384 每一步都是 `CD_CLK / (hm * VMAX)`,
`core_quality_plan(q, CD_CLK, hm * VMAX)` 給該步的完整 readout plan(之後照常 smc / isp)。

**R16(10-29)**:readout 對 DC 開不了窗(3x6/3x6fast 只能全高、V3 視窗邊距超出可讀列)時，改讀全高、TIM 只留 DC 的列(置中、偶數):
`core_readout_plan(..., hdr, rows, out)` 的 `rows`(<0 = None)= Python `readout_cfg.plan(..., hdr, rows)`,`core_quality.rows`(-1 = 無)。
全高幀比 DC 矮(新 V3 在 4032)就不給。細節與待上機項目:`isp-lab/notes/R16_CANDIDATES.md`。

**看到的尺寸與寬容(10-29)**:`core_qualities_tol(..., tol_num, tol_den, ...)` = `quality.qualities(..., tol)`
(`tol_den` 0 = None,即原本的 `core_qualities`)。每軸比 RES 少 tol 以內的 recipe 也列出(`short_ok`),R16 在全高幀只差 tol 以內時
整幀照收(`r16_rows(tol)`),RWZM 取 DC 在 readout 格點上的大小(`isp(nom)`,短的那軸只少列、不拉伸)。
每個 recipe 多給:`lines`(receiver 行數)、`vis_w`/`vis_h`(自己的看到的尺寸 = rec − 16×10)、`rs_us`(`round(rolling_ms, 3)`×1000,
Python 浮點逐位元);名義尺寸是 RES − 16×10。`core_js_fixed()` = JavaScript `toFixed`(QS 顯示用),`core_short_ok`/`core_r16_rows` 給窮舉測試。
float 的 tol 用有理數(0.02 = 1/50…),`test_core.py` 對每個測到的 tol 窮舉證明兩個比較式與 Python float 相同。

檔案:`core.h`(API、錯誤碼、屬性 enum)、`core.c`、`export_core.py` → `core_data.h`(產生的)、`test_core.py`。

## 怎麼跑

```
python3 -B export_core.py            # 只重產 core_data.h
python3 -B test_core.py              # 重產 core_data.h + 編 host/ARM + 全部比對(約 115 秒)
python3 -B test_core.py --mutants    # 再加 18 個 core.c 突變，每個都必須讓比對失敗(--quick 約 95 秒)
```

`test_core.py` 每次都先從**當下的** Python 重產 `core_data.h`,比的也是當下的 Python;
公式被別人改了之後重跑，差在哪裡會直接列出來。純資料的改動(規則表、readout 表、常數)重產即可;
`mode_rules.EXACT` 新增欄位或改公式，C 會回 `CORE_E_EXACT` 或比對失敗，要手動移植 `core.c` 的 `exact()`。

## 資料區(core_data.h,全部 const rodata,-fropi 下 PC 相對存取)

| 陣列 | 內容 |
|---|---|
| `CD_*` 常數 | SENSOR_H、WIN_TOP/BOTTOM、VMAX_MAX、CLK、V3_MARGIN(**匯出當下的環境變數值**)、V3_SKIP(_ON)、V3_FULL_SKIP、LINE_SHORT |
| `cd_ro[40]` + `cd_key_name` | 每個 readout key:mh/mv/bits/donor/hmin/over/centre/v016/v016_min/fast_set/new/y0/rows_full/cls、格式字(≤4)、extra 暫存器區段 |
| `cd_pairs` / `cd_v3win` | extra 暫存器組(V2/V3/V6/PAIR/BINNED/FULL)、V3_WIN |
| `cd_base_x0/y0`、`cd_vadd`、`cd_r10` | smc 的小表(-1 = Python 會 KeyError) |
| `cd_reg_order[161]`、`cd_fast[77]` | REG 表暫存器順序、fast Family A(`bins.diff('8','139')`) |
| `cd_rules[325]` | smc.fit() 的每個欄位:{表, 種類, 位元組偏移, 參數};種類 exact/const/cat/lin/byte/nearest |
| `cd_cat`/`cd_cat_ent`、`cd_lin`/`cd_lin_ent` | cat 查表(1~2 個屬性鍵)、lin 有理數規則(p/q·x + r/s,截斷) |
| `cd_stock[70]`、`cd_near` | 'nearest' 要的原廠模式 cls/寬/高與每欄位 70 個值 |
| `cd_defect`、`cd_defect_fb`、`CD_K_*` | mode_rules 的 DEFECT_DIR / FALLBACK、R28 四個常數(有理數) |
| `cd_qual[40]`、`cd_qbins`、`CD_LINE_PX_*`、`CD_Q_*`、`CD_SRC_MAX_H` | quality.QUAL 順序(key、ISP bits、AD)、CRCT bin 順序、R11 的 29/2、NEAR_UNITY / WIDEN / SENSOR_W、R12 預覽來源列數 1710 |

C 不做任何 fit,只照表求值。目前 fit 結果:exact 82、const 116、cat 126、lin 1、byte 0、nearest 0。

## 大小(clang armv7a-none-eabi,cortex-a9 Thumb,-O2 -fropi,soft float)

`.text` 18 334 B(加 quality 前 17 374;udiv64 / dratio 改 noinline 省掉的比新增的多,否則是 25 824)、`.rodata` 21 312 B、`.data/.bss` 0;沒有未定義符號(不需要 libgcc 的 `__aeabi_*`),
重定位只有 PC 相對(MOVW/MOVT_PREL、THM_CALL;PREL31 只在 `.ARM.exidx`,打包時丟掉即可)。

## 浮點怎麼處理

C 裡沒有任何 float,也沒有 `/`、`%`(A9 沒有除法器，全部走 `udiv64`):
- `sw = cw/mh` 這類比較改成整數不等式(`lw*mh >= cw`、`1000*lw*mh >= 995*cw`、`ch < 4040-2mv`),測試對 cw/ch 0..40000、每個 key 窮舉證明等價。
- R28 的 `W*0.949/16` 等用 K 的有理數(949/1000…)，寬高 0..65535 窮舉證明與 Python 逐值相同。
- `round(CLK/(hm*fps))`、`round(4040/mv)`、fpsn `round(CLK/(hm*vmax))`:用整數模擬 IEEE double(`dratio/dmul/dround`),
  每一步都跟 Python 的 float 一樣捨入。**不能只用有理數**:例如 f12v3、HMAX 400、fps 52800/1001,精確值 3412.5,
  Python 因浮點誤差得 3413,有理數 half-even 得 3412(測試實際抓到過)。fps 以 num/den 傳入，先取最近的 double,
  所以 `2997/100` 等於 Python 的 `29.97`,`30000/1001` 等於 Python 的 `30000/1001`。
- `fbits(scale)`:整數轉 IEEE single 的 RNE,0..2^20 + 20 萬個隨機 u32 證明。
- quality 的 `round(fps, 3)`(pick 的比較鍵):double 的精確值 ×1000 再 half-even(`dround_milli`);`fps_max > cap` 用 double 比較。

## 比對結果(全部 0 不符)

| 比對 | 筆數 |
|---|---|
| matrix.json 1109 筆 + `matrix.cases()` 現跑 1109 筆:plan 全欄位、smc 八表逐位元組 + attrs、isp plan words、65 字 row | 各 1109 |
| 40 個 key × 裁切 × 輸出 × 18 種 fps(+ v016/hmax/hdr 變化)的接受/拒絕與原因 | 1 557 541(接受 215 218) |
| 上面每個不同的接受 plan 做 smc | 52 141 |
| 密集 fps 掃描(k/1000、k/1001) | 996 670 |
| smc 合成 plan(奇數寬、短行、1.7/2.0 邊界、fpsn 平手、與 fast set 重疊的寫入、非表格暫存器) | 6 000 |
| isp 隨機 Spec(zoom 含 1023/1024/1025/8191/8192、bin 1/3 與錯誤值、bits 8/10/12/14 與 11) | 100 000(row 10 000) |
| quality R11:40 key × sw 0..10000 | 400 040 |
| quality 預設 DC×RES(32 格):cap 59.94 的結果 = matrix.json 639 筆逐欄;無 cap 639 筆;每品質 VMAX 步的 plan + spec | 各 639(settings 4 083) |
| quality 隨機 2000 格(扁平、極小、奇數、空 RES、RES 比裁切寬 16、多種 cap)+ 400 格 cap 貼近 fps_max(±0.005…0.05) | 4 988 + 38 508 品質 |
| quality 逐 VMAX 步(扁平裁切幾個品質，每一步 vmax 等於步) | 146 045 |
| quality:每個 Python case 照 readout args 重放 = 它的 plan(HMAX / VMAX / 0016 / id) | 全部 case |
| 證明:r28 65 536、fbits 1 248 579、float 模擬 476 690、round() 平手 150 000、readout 不等式 6 400 000、round(fps,3) 331 093 | |

寬容(10-29):預設 32 格 × tol 0.02／0.005／0 逐欄位、全高裁切 × 5 個 tol、隨機 400 格;`short_ok` 與 `r16_rows` 的 float 式對有理數窮舉
(246 萬)、C 的兩個式子對 Python 窮舉(205 萬)、`toFixed` 28 萬筆(含精確平手)。突變 62/62(寬容 11 個:不做 nom、短的不收、任何短都收、
邊界不含等號、R16 不收短幀／任何短幀都收、nom 列不取偶、nom 用加寬後的裁切、邊 16×8、RS 截斷、toFixed 平手取偶)。

突變:51/51 被抓到(R16 11 個:不做、留整幀、列數進位、幀比 DC 矮也給、裁在頂端、奇數相位、y0 不動、視窗也裁、奇數列、WIDEN 忘了裁、重放忘了裁;R12 C(fh == fv) 的樣式 10-29 對回 c_fits;R12 6 個:binned C、B、D 的 k、C(fh == fv)、E1 各自不看來源列數,1710 → 1709;quality 13 個:R11 floor 邊界、R11 取整、R11 用 sw、無 WIDEN、1x1 也 WIDEN、平手給後者、RES 容差、fps_max == cap 也用 cap 規劃、fps 鍵截斷、
不排回 matrix 順序、_z 0.1 %、無 0016 退路下限、全高列數不設上限;原本 18 個:裁切容差、視窗起點 mod 4、round 平手、vmax 改用有理數、浮點 guard bit、空白重試、V3 邊界、
hd 邊界、R28 捨入、cat 第二鍵、fpsn 截斷、fast set 順序、短行 x0 偶數、D 比例、RWZM 8192、1334 吸附、14-bit plane、fbits 捨入)。

## 沒涵蓋的

- 字串欄位:plan 的 `id`(`config_id`,含 `fps:g` 格式)、`name`、`ev`,smc 的 `how`。C 只出數值。
- `nearest`、`byte` 規則種類已實作，但目前 fit 沒有這類欄位，所以沒有資料能驗證它們。
- `WINROWS`(視窗超出可讀列)在目前的表下 grid 從未觸發;`V3_SKIP_ON` 分支是死碼(False),有實作但沒測到。
- Spec.scale 只收整數(Python 可收 float);v016 用負數代表 None。

## 發現的 Python 怪處(只回報，沒改)

1. `smc.value` 的 lin 規則一律 `int()` 截斷，但 `reconstruct.try_lin` 擬合時也接受「四捨五入」;若哪天擬合出需要四捨五入的規則，smc 會差 1 而不會報錯(目前唯一的 lin 是 REG 0x0016 = f5c/2,沒影響)。
2. `readout_cfg.V3_MARGIN` 讀環境變數:同一組輸入的 plan 會隨環境而變;C 版固定為匯出當下的值。
3. plan 算出 `rows.TIM_line` / `R38_words`,但 `smc.create` 完全沒用(只有 readout_export 用)。
4. `vmax = round(CLK/(hm*fps))` 在精確平手時結果取決於浮點誤差(上面的 3413 例);`round()` 又是 banker's rounding(fpsn 112.5 → 112)。
5. `plan()` 對 ow=0 / oh=0 不先擋，最後算 rwzm 才丟 `ZeroDivisionError`(不是 ValueError),只接 ValueError 的呼叫端(如 `matrix.cases`)遇到會直接崩(目前的 DC 不會走到)。
6. `isp_formula.plan` 的 bits 不在 PLANE 時丟 `KeyError`,不是 `NotPossible`;C 回 `CORE_E_LOOKUP`。
7. `attrs_from_plan` 固定 acq/crop/cont = 0、mode = -1,所以 mode_rules 的 HAND / rep / v33 分支對新模式永遠不生效(C 直接當 0;匯出時有檢查 -1 不在那些表裡)。
8. ~~R11 用 `sw = cw // mh`~~ **已修(10-28)**:R11 改用 isp 實際處理的 raster 寬(plan 的 `raster_w` = ceil16(sw),3032 照 plan);
   raster 與 HMAX 無關，所以先不帶 hmax 規劃一次取 raster。40 key × cw 16..6064 有 615 個 readout 的 HMAX +1(12fastW / f12v2 / f12v3
   在 cw 5793.. 起 400→401…,f12w18 系在 4929.. 起 340→341…);預設格不受影響,matrix.json 不變。
9. **R2 1025 是死碼**:窮舉 raster 寬(16 的倍數與 3032)× RES 寬 × hbin,只要 zh=1024(才會用 1025),zh=1025 就讓 rec 寬 < RES,
   精確 RES 必然不過;matrix.json 與隨機 4000 格裡沒有任何 zoom 含 1025 的品質。`min(rh, most_h)` 的夾限也只改變被拒的路徑(突變等價，已拿掉)。
10. ~~args 帶 cap、plan 卻是 fps_max~~ **已修(10-28)**:拿掉 `abs(fps - cap) < 0.01`;只有真的用 cap 規劃(fps_max > cap)的 plan 的 args 才帶 cap,
   否則帶 None。test_core 檢查每個 case(預設、隨機、cap 貼近與等於 fps_max)照 args 重放 `readout_cfg.plan(*args)` 的 HMAX / VMAX / 0016 / id
   都跟 case 的 plan 相同;test_matrix 也加了同一檢查。
11. **matrix 的 fps_max 不是 planner 的上限**:fps=None 用 donor 的 0016;給 fps 時 planner 會退到 v016_min(12、3x3fast、12w18/w03/w2C),
   VMAX 可再低到 `vmin_lo`。pick 比的是前者;C 兩個都給。
12. **pick 用 round(fps, 3)**:差 < 0.0005 fps 就算平手、取 key 名排序第一個;cap 下全都到 59.94 時尤其常見(隨機 3000 格平手 3.6 萬次),
   所以 cap 下選到的不一定是 headroom 最大的變體。
13. 極小裁切 / 空 RES(`cw // mh == 0`、`ow == 0`…)時 `quality.qualities` 直接丟 `ZeroDivisionError`(跟 matrix 一樣只接 ValueError);C 回 `CORE_E_ZERO`。
   負數或 cap < 1 fps Python 沒定義,C 回 `CORE_E_INPUT`。
14. R12 沒有管 E3:E3 的來源列數是 H / 3,H > 5130 時超過 1710 也照走 E3(quality 的 window ≤ 4042 不會走到，任意 Spec 會)。
