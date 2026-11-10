# 不經大量 COPY 的水平 RAW14 候選（離線覆核）

> **後續實機結果優先**：H1 已完成5階段／10幀的獨立a0擷取，保住每幀來源後水平÷3有效。
> mux3 bypass與兩筆原廠÷3核最低兩位皆零，前後Crmf保留14-bit低位。
> 因此本文下方「H1尚未取得像素／精度」已由這批樣本更新為「已測a0 H1配置只有12-bit內容」。
> 沒有測完整BufA7→SIG工作，也沒有排除所有未知設定。見 [H1實機報告](../validation/h1-live-20261030/README.md)。

> **優先順序修正（使用者提醒sensor已完整測試後）**：既有sensor工作包含0001全值掃描、14-bit候選格式、
> Family A交叉設定、水平／垂直組合、接收窗、線性／顏色／連拍驗證與失敗結果更正。
> 3B／2F＋Family-A14沒有直接保存案例只是有限覆蓋缺口，沒有新正向線索，不再據此把sensor重測排第一。
> 後續以packed14融合CPU／NEON完整流程與實機成本為主；RWZM只保留有原廠依據的有限對照；
> RAW_ZOOM／BEIS先補控制語義。H1下方舊順位與sensor補測建議保留為歷史，受本段更新。

2026-10-30。全程離線，未操作相機。後續新增原 ROM 路由重播與純量打包模型，證據範圍見下文。
使用者的垂直 binning 已由 sensor 完成；
以下只評估水平縮寬，且區分「保留14-bit資訊」「全視野縮寬」「等權平均」三個不同門檻。

**現有資料沒有證實低成本的全視野 H2/H3 RAW14 硬體路徑。新增發現：原廠另一個收流入口
確實會選 H1、開 BufA7 gate；6 個原 ROM 設定案例通過，尚無像素或精度證據。**
sensor 的3B／2F仍是14-bit覆蓋缺口；CPU 原地 packed14 H2/H3 已完成純量模型驗證，未測速。

## 1. Sensor 3B／2F：最低搬運成本，但14-bit支持偏弱

直接來源新增覆核：`projects/imx410-lab/offline/zcam/zcam_readout_regs.csv`。
其 header 第1行把 MODE1 標為6064×4040 adc12、MODE19標為3032×4040 adc12。
**逐列比較兩張完整寫入表，唯一差異是第11行 `0001=2A → 3B`**；其餘寫入（包括ADC/垂直組）相同。
這支持3B是原廠已有的水平H2格式選擇，而不是需要CPU重排的模式；不支持3B可輸出14-bit word。

同一CSV第11行：29/2B是兩個14-bit模式；2A/2C、2F、39、3B同時被正常12-bit與快速11-bit ADC使用。
所以不能把數值的奇偶或某一位元直接解讀成ADC位深。`29→2A`、`2B→2C`的相鄰關係不是
可推廣的bitwidth開關；`39−1=38`、`3B−1=3A`先前已試失敗，2F的鄰碼沒有新的正向證據。

Sony flyer的本地來源摘錄（`notes/WEB_IMX410.md:103–130`）與上述表一致：

- 14-bit輸出word只有6064×4040與4160×2160的模式0/3。
- H2-only模式19/20、H2V2模式17/18、H3V3模式6/7，輸出word均為12。
- 這是已列出的模式，不是未公開組合不存在的證明。

其他獨立原廠表也沒有14-bit binned模式：ZWO只有29/2A/39，ToupTek只有29/39/2F
（`notes/ASTRO_IMX410.md:102–113`）。QHY甚至只寫29而不寫Family A（同檔`:83`）。
早期`SENSOR_REGISTER_DECODE.md:48–59`把Family A稱作位深組，是模式共變關係；它本身也明說不是因果證明。
後來`IMX410_RULES.md:1114–1117`實測29搭整組normal Family A仍有正常14-bit接收與原來線時序限制，
至少說明**換Family A不能單獨指定輸出位深**。該舊紀錄以mod4稱「真14」的部分仍應與下述證據門檻分開。

已測／未測的精確覆蓋見 `SENSOR_H14_AUDIT_20261030.md`：3B與2F搭Family-A14均沒有找到直接保存案例。
先前39/38/3A的失敗不能形式上代替3B/2F，但目前也沒有一個原廠14-bit donor使用這兩碼。
若sensor固定送12-bit word，即使內部ADC能用更多位，後端換14-bit容器也不能取回沒傳出的資訊。

最小補查應分兩層，而不是一開始就宣稱驗到14-bit：

1. **先辨識資料流是否成立。** 沿用已驗14v2或14v3的垂直組及HMAX911，只換3B或2F；
   用原廠receiver link/packing路徑配置窄窗，回讀實際pitch/height，先抓少量列。
   29同垂直組作前後對照；3B/2F的normal/RX12作已知格式對照；Family-A14下的RX14與RX12
   分別用來區分格式不符與完全無有效資料。RX12有圖不是14-bit成功。
2. **有有效圖後才辨識精度與取樣核。** 至少有R/G/B有效訊號、正確完整水平視野、連續幀差異、
   黑位到高光的線性與飽和行為。真14-bit需知道進入會改變數值的CRCT階段之前的量化／低位資訊；
   或先驗證RAW14 sensor pattern的1DN步階與插入位置，才拿它作受控對照。
   現有pattern fixtures全是12-bit，不能憑它們假定有1DN14來源。

V2必須保留PAIR：2F/3B本身不替兩列配對（`IMX410_RULES.md:1471`）。2F+V1的缺R/B已撤回
（`:1620–1623`）；使用者已有Vbin，應沿V2/V3，不要重測已知不合適的V1。14-bit幀的實際
packing、buffer上限與原廠receiver重新初始化是必要條件，不能直接照抄舊L7的MMIO數字。

**即使位深成功，也還不是精確平均。** 3B的時間雜訊比同尺寸數位平均高約13%，被推測為非等權
（約3:1）或部分取樣（`IMX410_RULES.md:1003–1018`）；這是影像測量推論，不是已解出的硬體公式。
原廠3×3也沒有證實等權九點平均。後續需用固定曝光、具已知相位的空間圖樣與1×基準估計各相位貢獻，
不可只看輸出寬度或宣稱sensor bin名稱即等權平均。sensor內建pattern若在bin之後產生，也不能驗證sensor採樣核。

## 2. 不需要中間影像的 /3：CRCT第一級 Hbin 尚未取得有效樣本

直接串流路徑在原廠結構上存在：sensor receiver → CRCT → a0/a7 mux → BUFA。
`C0635CA8/C0635CD0`把mux寫到`300F06B0/06D0`，enum3為Hbin、enum4為Hbin2。
H1的控制是`300F0840`與核`300F0850…`，H2是`300F08C0/08C4`；RWZM是另一組`300F0900`。
來源：`research/imaging-hw/notes/CRCT_REDUCTION_PATHS.md:31–76`，以及更新的
`CRCT_PATH_SELECTOR_SOLVED.md:14–19,80–99`。

Hbin2已取得真縮寬但低兩位皆零的樣本；Hbin mux3未取得有效影像，不能視為已量過或已成功。
直接證據位置：`TRUE14_2X_RESEARCH.md:365–391`與其引用的`validation/2026-10-30-tc/LOG.md`。
先前只追 `C0325228` 而寫成「原廠只在停用視窗寫mux3」的結論已被下列另一個入口訂正；
**已找到選 H1 並開 BufA7 gate 的原生設定鏈，但仍沒有有效 H1 像素、RAW14 精度或完整 DMA 證據。**
要得到完整視野確實縮為1/3、CFA與穩定幀都成立的資料，才能再做精度判定。

### 本輪新增：原廠 H1 → BufA7 路由與每幀覆寫來源

- `profile+0x38 → C0434EF8 cfg+0xEC → C01D1630 → C31DF650 → C01D4578` 提供 frame route。
  route `0x10` 在 `C01CB388` 選 BufA7；`C017E138` 寫 `300F06D0=3`，產生 route pair
  `[3,0x4C000]`，並經真正的 `C0180418` 設 `30182050|=0x100`。
- `profile.preview_hbin +0x58 → cfg+0x9C → C31DF600 → C01D36E0 → C01CABA0 → C017FAA0`
  是另一條每幀 H1 控制來源；V 對應 `profile+0xC4 → cfg+0xA0 → C31DF604`。
  `C01C26F8` 迴圈透過 `C01CAB48(...,0x10)` 重做此配置。只手寫 `0840=1` 或只改錄影欄位，
  若預覽來源 enum0，後續就會清掉 H1 低兩位；這與 T-C 現象相容，沒有該輪 calltrace 證明因果。
- route `0x40` 會明確把水平操作移給 Hbin2；route `0x10` 沒有這個搬移。
  `C01CB388` 的幾何算式可由 hbin enum1 得到寬÷3，vbin enum0 維持高度；本輪未執行此幾何函式。
- 原廠有17筆route0x10 donor，但preview全是H3V3、plane7或10，沒有RAW14 H1 donor。
  前置 `C0179360` 靜態可見plane8→format1，BufA7走 `C014A708/C014A5B8` 幾何與格式設定
  （`blk_c01.c:65365–65379,65491–65525`）。這只是RAW14容器入口，尚未重播該前置完整鏈，
  更不是已完成的RAW14 H1錄影。下一步要連同來源控制、DMA與SIG消費者一起審核。
- `C032D9A0` 的另一個「僅水平合併移往 H2」分支要 sensor descriptor `+0xFC` 非零；
  fp IMX410 的 ROM descriptor `C2F1E654+0xFC` 實際是0，不能列成目前必然阻擋。
- 原 ROM 的 `C0633B30 / C017FAA0 / C017E138 / C0180418` 共6案例重播通過，
  包含兩筆原廠核、H1/H2/Crmf路由對照、來源enum1保留／enum0清除H1控制。
  來源與報告：[h1-route-native-20261030](../validation/h1-route-native-20261030/report.json)。
  frame descriptor 是人工依靜態選擇規則建立；memset、IRQ、BUFA準備、route builder/submit為明示stub，
  MMIO只是模擬記憶體。不證明時脈、DMA完成、還原、像素或真14。

直接來源：`out/decomp/full/blk_c01.c:68004–68209,69655–69664,111175,117256–117268,117534–117649,121868`；
`blk_c04.c:35698,35729`。`C0134058(0x80)` 只標為原廠準備輔助，不當作已解的 H1 clock enable。

這條不需COPY分流或RawMix中間平面，資源條件有吸引力，但不能把「tap尚未測成」當作它能保14。
已見原廠核是加權核（如[1 2 1]/4），也不能直接稱為三點等權平均。
Julien Acquaviva的「RAW-path /3 column bin」沒有原始配置／樣本可對照，仍不能指定它就是H1、Hbin2或HSEP。

**receiver本身的窄窗不是/3。** `3010000C`是以12像素為單位的START/END，實測只是crop，
內容與原圖相應位置相關1.000（`IMX410_RULES.md:984–992`）。12-pixel單位不能解讀成平均／抽取倍率。
目前限定查核沒有找到receiver另有保持完整視野的/3參數。

## 3. RWZM：仍是串流，參數缺口比新增搬運鏈小

已證實的原廠完整setter `C0101C30`預設flags16/24=1/1，常用`C0633E60`整字寫enable會把兩旗標清掉；
partial setter `C0634038`能保留旗標且獨立設H/V phase。`C017F990`有phase512的原廠caller。
來源：`../validation/rwzm-setters-20261030/README.md:9–36`，其8-case真ROM proof。

這提供已知來源的有限參數對照，沒有額外全圖COPY。H2的phase512可能形成等權取樣，
但CFA相位與實際tap尚待驗；flags也沒有位深語意的正向證據。H3更不能假定兩點內插就是三個同色點平均。
已測RWZM配置仍會丟低兩位。這條可保留為小範圍參數研究，不能藉未知旗標宣稱有14-bit模式。
現成輸入只有sensor，無已實作的memory→RWZM已知RAW14圖樣路徑；非零low2仍可能由12-bit內插生成。

## 4. CPU 原地 packed14 融合：可離線證明的替代方案

把解包、同色平均、重打包放在同一小塊，省掉完整 u16 影像與完整目的平面。
H2 每32樣本56B→16樣本28B；H3 每48樣本84B→16樣本28B。6048寬皆整除。
H3用三個同色樣本，`((a+b+c+1)*43691)>>17` 等於四捨五入除3；乘積需32-bit。
與 HSEP mode2 的兩端取樣語義不同。

[離線純量模型](../tools/rwzm14/prove_packed_h14_inplace.py) 已跑3840個frame案例，
覆蓋兩種輸入／輸出packing、H2/H3、寬6048、多列、CFA、ramp、低位與高光、padding、
緊密輸出及保原stride；原地結果與獨立bit-string參考逐像素相同，非輸出區與guard保持。
另窮舉49150種H3加總，兩個故意先丟低2位的反例均被抓到。
精確stdout保存在 [packed_h14_inplace-results.json](../tools/rwzm14/packed_h14_inplace-results.json)。
BUFA格式是MSB位流存於little-endian 32-bit words；RMIX endian1則是MSB byte stream，均非MIPI RAW14。

原地合約只允許：DMA已完成、整個frame獨占、src/dst同基址、目的列距介於緊密輸出與來源列距之間，
按列／塊正向且每塊先完整讀完再寫。這不是任意重疊、並行DMA或共享錄影ring的安全證明。
現有NEON u16核心仍要求disjoint；新模型未編ARM、未接consumer/cache、未測速。

寄存器融合的外部影像緩衝讀寫下界：6048×2020 H2為32.07MB/幀、24p約770MB/s；
6048×1330 H3為18.77MB/幀、24p約450MB/s。未含sensor寫入、writer再讀、cache/spill／小塊暫存成本，
不是已量到的DRAM吞吐。若採純量參考的小塊暫存，不可直接宣稱達到該寄存器下界。

## 建議順位

按「省相機資源、證據缺口是否有限」排序，而不是成功機率估算：

1. **CRCT H1 原生 route0x10＋一致的preview控制來源**：已有啟用與gate設定證據，
   先離線補齊格式、裁切／DMA幾何及資源所有權；有效像素與14-bit仍未知。
2. **一次性補完sensor3B／2F+Family-A14覆蓋**：成本最低、前提有已知12-bit模式；
   但原廠模式表與既有Family A結果均未支持它會送14-bit。先判有效transport，過了才花力氣證位深／核。
3. **RWZM原廠flags＋phase的有限對照**：現成串流路線，證位深與證平均分開；需要更好的受控來源。

CPU融合模型可平行作為算術已驗、速度未知的軟體方案；不是另一次上機授權。

HSEP在現有原生路線已做bypass對照：bypass保留RAW14，開H2/H3變成4的倍數
（`TRUE14_2X_RESEARCH.md:558–584`）。沒有新的已知精度控件前，不應把原樣HSEP重測排在前面。
RawMix+COPY仍是後備，已有36-case描述符證據，但分流提交／中間RAM／頻寬成本高。

若可以接受視野變窄，`0001=2B`的4160 crop及receiver水平裁切已有14-bit方向，且不需每像素運算；
它只是裁切，沒有完成使用者所要的全視野水平binning。保持29+既有Vbin、水平後製也能避開機內算術，
代價是仍寫入全寬資料，不能稱為降低相機寫入頻寬的方案。

共同證據門檻：12-bit sensor→RAW14 BUFA的既有T0已出現99.5%非零low2
（`notes/L7_14BIT.md:173–174`）。所有候選都不能只用14-bit檔頭、容器、直方圖低位均勻或輸出尺寸宣稱保真14。
