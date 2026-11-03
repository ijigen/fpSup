/* The simulator page as the camera's QR landing page (site/README.md):
 *  - #<37-char code> -> the camera's selection loaded into the simulator state (S); unrepresentable fields are listed
 *  - every change -> location.hash = the page's own qrPack payload (history.replaceState, no history entries)
 *  - the mode details (frame diagram, binning, kernel, speed/data) and EN / 简 / 繁 for everything outside the
 *    simulated camera screen, whose tiles keep the camera's own English labels.
 * Loaded before the simulator's inline script. Its functions read that script's globals (S, QR_FIELDS, qrPack, res,
 * curRecipe, ...) only when called, so the spec logic in dcres.html stays untouched. Pure parts run in Node tests. */
'use strict';
(function (global) {
// ---- strings ---------------------------------------------------------------------------------------------------
const I18N = {
  en: {
    sro: 'Readout', dcrop: 'DC crop', bySensor: 'sensor', byRx: 'SoC receiver', roPending: '(engine…)',
    roPendingT: 'Shown once the simulation engine has planned this recipe.',
    sroT: (w, h, mh, mv, win) => `The sensor reads whole native lines (${w} px after its ${mh}×${mv} bin) and ${h} rows, ${win ? 'windowed to the DC height' : 'full height'}: it cannot crop to any width.`,
    dcropT: 'The SoC receiver cuts the DC out of the lines the sensor sends.',
    rsPan: 'Pan', rsOff: 'Off', rsSlow: 'Slow', rsFast: 'Fast', rsCompare: 'Compare with stock FHD (dashed)',
    rsLean: 'Rolling shutter: the last row is read RS after the first. During a pan of v frame widths per second the bottom of the frame is shifted v × RS frame widths against the top, so verticals lean. Slow = 1, fast = 4 frame widths per second.',
    rsNow: (rs, p, st, sp) => `RS ${rs} ms → bottom shifted ${p}% of width\nstock FHD ${st} ms → ${sp}%`,
    hSim: 'Quick Set simulator', ledeDefault: 'Quick Set simulator. The QR code in SensorLab’s QS opens this page with your camera’s settings.',
    ledeCamera: 'Loaded from the camera’s QR code. Change anything in the simulator and the address follows.',
    ledeEdited: 'Your changes are in the address: share it, or reload to come back here.',
    ledeLoading: 'Loading the camera’s settings…',
    bad: r => `This code could not be read (${r}). Showing the simulator’s default instead.`,
    rlength: 'wrong length — perhaps only part of it was scanned', rchars: 'it contains characters a SensorLab code never uses',
    rcrc: 'checksum mismatch', rpad: 'non-canonical padding', rversion: 'unsupported version — perhaps a newer SensorLab',
    rfield: 'a setting is out of range',
    inexact: 'The simulator cannot show this code exactly. The details below are the camera’s values; the simulator shows the nearest it can:',
    diff: (n, c, s) => `${n}: camera ${c} · simulator ${s}`, noRecipe: 'No recipe for this selection, so there are no details to show.',
    loading: 'Loading simulator…',
    howTo: 'Click or tap a tile to select it; click it again (or the AEL chip) for more options, the chip again to go back. ◀ ▶ on the selected tile or the mouse wheel step it; « » or Shift+wheel step ten. Click an option below to apply it. The QS chip opens and closes the Quick Set.',
    bgNote: 'The background illustrates crop and output geometry. Use the circle to see stretching or squashing. Image quality, recording and playback are not simulated. Tiles keep the camera’s own English labels.',
    more: 'More options', back: 'Back', qrAria: 'QR code for the current settings', qrUnavailable: 'QR code unavailable',
    engineLoading: 'Loading the simulation engine…', engineFailed: 'The simulation engine could not load. Please reload this page.',
    presetOnly: 'Preset preview only. Open the local simulator server to use custom dimensions and QR codes.',
    calcFailed: 'The calculation could not complete. Please reload.', calculating: 'Calculating recipes…',
    noRecipes: 'No recipes are available for these dimensions.', upToDate: 'Dimensions and recipes are up to date',
    engine: (v, b) => `SensorLab v${v} · ${b ? 'Browser' : 'Local'} simulation`,
    stLock: 'lock', stFree: 'free', stVisible: 'visible', stTarget: 'target', stCustom: 'custom', stRatio: 'ratio',
    stFine: 'fine adjustment', stRate: 'custom rate', stNone: 'none', stMemory: 'Remembered custom RES',
    hFrame: 'Where the picture comes from', hMerge: 'Sensor binning', hKernel: 'ISP bin kernel', hStats: 'Speed and data',
    sensor: 'Sensor', sdc: 'Sensor DC', sbin: 'Sensor bin', idc: 'ISP DC', iscale: 'ISP scale', rec: 'Recording',
    sdcT: 'The rows and columns the sensor reads.', sbinT: (h, v) => `${h}×${v} same-colour pixels summed on the sensor.`,
    idcT: 'The part of the binned frame the ISP keeps.', iscaleT: (b, z) => `ISP bin ${b}, RWZM ${z}, down to the recording size.`,
    vis: (w, h) => `Visible (DNG DefaultCrop) ${w}×${h}.`, none: 'none', frameCap: 'One scale for every stage, each centred where the camera puts it: a box is that stage’s pixel grid (sensor, binned or recorded pixels), so a later stage is never bigger. A stage the same size as the one before is drawn slightly inset. Solid = a stage; dashed = how a stage is squeezed into the next.', dashedKey: 'dashed = squeezed into next', sameSize: 'same size',
    merge1: '1×1: every pixel read as is — sharpest, most data.',
    mergeN: (h, v) => `${h}×${v}: ${h} across and ${v} down of the same colour become one on the sensor — smaller, cleaner, faster to read.`,
    sumUp: 'summed', toOne: '→ 1 output', kernelOn: (k, m) => `The ISP weights 3 neighbouring same-colour pixels by [${k}] (${m}). A heavier centre is sharper; flatter is softer and cleaner.`,
    kernelOff: 'No ISP binning in this mode; only scaling.', noBin: 'no bin',
    fps: 'Frame rate', unc: 'Uncompressed', ll: 'Lossless est.', rs: 'Rolling shutter', actual: f => `fps (exact ${f})`,
    media: m => m === 'SSD' ? 'on SSD' : `on SD ${m}`, rsCap: 'Rolling shutter: the time from reading the first row to the last. Shorter skews less in fast motion.',
    thisMode: 'This mode', stockFhd: 'Stock FHD 29.97', tuned: 'tuned', recipeMax: 'recipe maximum',
    fields: {ver: 'version', dcw: 'DC width', dch: 'DC height', rw: 'RES width', rh: 'RES height', fps: 'FPS pick', vmax: 'VMAX',
      hmax: 'HMAX', ad: 'ADC', mh: 'sensor H bin', mv: 'sensor V bin', hbin: 'ISP H bin', vbin: 'ISP V bin', key: 'readout key',
      kh: 'H kernel', kv: 'V kernel', km: 'kernel mode', rcustom: 'recipe CUSTOM', visw: 'visible width', vish: 'visible height',
      rs: 'rolling shutter µs', fmt: 'format', rescustom: 'RES CUSTOM', scw: 'sensor crop width', sch: 'sensor crop height',
      ww: 'ISP window width', wh: 'ISP window height'} },
  hans: {
    sro: '读出', dcrop: 'DC 裁切', bySensor: '传感器', byRx: 'SoC 接收器', roPending: '（引擎…）',
    roPendingT: '模拟引擎算出此配方后显示。',
    sroT: (w, h, mh, mv, win) => `传感器读出整条原生行（${mh}×${mv} 合并后 ${w} px）与 ${h} 行，${win ? '按 DC 高度开窗' : '全高'}：宽度无法任意裁切。`,
    dcropT: 'SoC 接收器从传感器送来的行中裁出 DC。',
    rsPan: '摇镜', rsOff: '关', rsSlow: '慢', rsFast: '快', rsCompare: '与原厂 FHD 比较（虚线）',
    rsLean: '卷帘：最后一行比第一行晚 RS 读出。以每秒 v 个画面宽摇镜时，画面底部相对顶部偏移 v × RS 个画面宽，垂直线因此倾斜。慢 = 每秒 1 个画面宽，快 = 4 个。',
    rsNow: (rs, p, st, sp) => `RS ${rs} ms → 底部偏移画面宽 ${p}%\n原厂 FHD ${st} ms → ${sp}%`,
    hSim: '快速设置模拟器', ledeDefault: '快速设置模拟器。相机上 SensorLab QS 里的二维码会带着你的设置打开这一页。',
    ledeCamera: '已载入相机二维码里的设置。在模拟器里改任何东西，网址会跟着更新。',
    ledeEdited: '你的修改已写进网址：可以分享，或重新加载回到这里。',
    ledeLoading: '正在载入相机设置…',
    bad: r => `这段码读不出来（${r}），下面是模拟器的默认设置。`,
    rlength: '长度不对，可能只扫到一部分', rchars: '含有 SensorLab 码不会用的字符', rcrc: '校验码不符', rpad: '结尾填充位不正确',
    rversion: '版本不支持，可能是较新的 SensorLab', rfield: '有设置超出范围',
    inexact: '模拟器无法完全重现这段码。下方详情是相机的值，模拟器显示最接近的设置：',
    diff: (n, c, s) => `${n}：相机 ${c} · 模拟器 ${s}`, noRecipe: '这组选择没有配方，没有详情可显示。',
    loading: '正在加载模拟器…',
    howTo: '点或轻触格子选中它；再点一次（或点 AEL）打开更多选项，再点 AEL 返回。选中格子的 ◀ ▶ 或鼠标滚轮调整，« » 或 Shift+滚轮一次调十格。点下方选项即套用。QS 按钮开关快速设置。',
    bgNote: '背景只示意裁切与输出形状，用圆形看拉伸或压扁。不模拟画质、录像与回放。格子里保留相机上的英文标签。',
    more: '更多选项', back: '返回', qrAria: '当前设置的二维码', qrUnavailable: '二维码无法生成',
    engineLoading: '正在加载模拟引擎…', engineFailed: '模拟引擎加载失败，请重新加载此页。',
    presetOnly: '只有预设数据。自定义尺寸与二维码需要本机模拟服务。',
    calcFailed: '计算未能完成，请重新加载。', calculating: '正在计算配方…',
    noRecipes: '这组尺寸没有可用配方。', upToDate: '尺寸与配方已是最新',
    engine: (v, b) => `SensorLab v${v} · ${b ? '浏览器' : '本机'}模拟`,
    stLock: '锁定', stFree: '自由', stVisible: '可见', stTarget: '目标', stCustom: '自定义', stRatio: '比例',
    stFine: '微调中', stRate: '自定帧率', stNone: '无', stMemory: '记住的自定义 RES',
    hFrame: '画面从哪里来', hMerge: '传感器像素合并', hKernel: 'ISP 合并核', hStats: '速度与数据量',
    sensor: '传感器', sdc: 'Sensor DC', sbin: 'Sensor bin', idc: 'ISP DC', iscale: 'ISP 缩放', rec: '录像',
    sdcT: '传感器实际读出的行列范围。', sbinT: (h, v) => `传感器内把水平 ${h}、垂直 ${v} 个同色像素相加成一个。`,
    idcT: 'ISP 从合并后的画面里保留的部分。', iscaleT: (b, z) => `ISP 合并 ${b}、RWZM ${z}，缩到录像尺寸。`,
    vis: (w, h) => `可见范围（DNG DefaultCrop）${w}×${h}。`, none: '无', frameCap: '所有阶段同一比例，按相机实际位置居中：每个框是该阶段的像素网格（传感器、合并后或录像像素），后面的阶段不会更大。与前一阶段同尺寸时略向内缩以便分辨。实线 = 阶段；虚线 = 这一阶段如何被压缩进下一阶段。', dashedKey: '虚线 = 压缩进下一阶段', sameSize: '同尺寸',
    merge1: '1×1：每个像素原样读出，最锐利、数据量最大。',
    mergeN: (h, v) => `${h}×${v}：水平 ${h}、垂直 ${v} 个同色像素在传感器里合成一个，画面变小、噪点更低、读得更快。`,
    sumUp: '同色相加', toOne: '→ 1 个输出', kernelOn: (k, m) => `ISP 把相邻 3 个同色像素按 [${k}] 加权合成一个（${m}）。中间权重越大越锐利，越平均越柔、越干净。`,
    kernelOff: '这个模式没有用 ISP 合并，只做缩放。', noBin: '不合并',
    fps: '帧率', unc: '未压缩', ll: 'Lossless 预估', rs: '卷帘', actual: f => `fps（实际 ${f}）`,
    media: m => m === 'SSD' ? '以 SSD 计' : `以 SD ${m} 计`, rsCap: '卷帘（rolling shutter）= 从第一行读到最后一行的时间，越短，快速运动越不歪。',
    thisMode: '这个模式', stockFhd: '原厂 FHD 29.97', tuned: '微调', recipeMax: '配方上限',
    fields: {ver: '版本', dcw: 'DC 宽', dch: 'DC 高', rw: 'RES 宽', rh: 'RES 高', fps: 'FPS 选项', vmax: 'VMAX', hmax: 'HMAX',
      ad: 'ADC', mh: '传感器水平合并', mv: '传感器垂直合并', hbin: 'ISP 水平合并', vbin: 'ISP 垂直合并', key: '读出 key',
      kh: '水平合并核', kv: '垂直合并核', km: '合并核模式', rcustom: '配方 CUSTOM', visw: '可见宽', vish: '可见高',
      rs: '卷帘 µs', fmt: '格式', rescustom: 'RES CUSTOM', scw: '传感器裁切宽', sch: '传感器裁切高', ww: 'ISP 窗口宽', wh: 'ISP 窗口高'} },
  hant: {
    sro: '讀出', dcrop: 'DC 裁切', bySensor: '感光元件', byRx: 'SoC 接收器', roPending: '（引擎…）',
    roPendingT: '模擬引擎算出此配方後顯示。',
    sroT: (w, h, mh, mv, win) => `感光元件讀出整條原生列（${mh}×${mv} 合併後 ${w} px）與 ${h} 列，${win ? '依 DC 高度開窗' : '全高'}：寬度無法任意裁切。`,
    dcropT: 'SoC 接收器從感光元件送來的列中裁出 DC。',
    rsPan: '搖鏡', rsOff: '關', rsSlow: '慢', rsFast: '快', rsCompare: '與原廠 FHD 比較（虛線）',
    rsLean: '捲簾：最後一列比第一列晚 RS 讀出。以每秒 v 個畫面寬搖鏡時，畫面底部相對頂部偏移 v × RS 個畫面寬，垂直線因此傾斜。慢 = 每秒 1 個畫面寬，快 = 4 個。',
    rsNow: (rs, p, st, sp) => `RS ${rs} ms → 底部偏移畫面寬 ${p}%\n原廠 FHD ${st} ms → ${sp}%`,
    hSim: '快速設定模擬器', ledeDefault: '快速設定模擬器。相機上 SensorLab QS 裡的 QR code 會帶著你的設定打開這一頁。',
    ledeCamera: '已載入相機 QR code 裡的設定。在模擬器裡改任何東西，網址會跟著更新。',
    ledeEdited: '你的修改已寫進網址：可以分享，或重新載入回到這裡。',
    ledeLoading: '正在載入相機設定…',
    bad: r => `這段碼讀不出來（${r}），下面是模擬器的預設設定。`,
    rlength: '長度不對，可能只掃到一部分', rchars: '含有 SensorLab 碼不會用的字元', rcrc: '檢查碼不符', rpad: '結尾填充位不正確',
    rversion: '版本不支援，可能是較新的 SensorLab', rfield: '有設定超出範圍',
    inexact: '模擬器無法完全重現這段碼。下方詳情是相機的值，模擬器顯示最接近的設定：',
    diff: (n, c, s) => `${n}：相機 ${c} · 模擬器 ${s}`, noRecipe: '這組選擇沒有配方，沒有詳情可顯示。',
    loading: '正在載入模擬器…',
    howTo: '點或輕觸格子選取；再點一次（或點 AEL）開啟更多選項，再點 AEL 返回。選取格子的 ◀ ▶ 或滑鼠滾輪調整，« » 或 Shift+滾輪一次調十格。點下方選項即套用。QS 按鈕開關快速設定。',
    bgNote: '背景只示意裁切與輸出形狀，用圓形看拉伸或壓扁。不模擬畫質、錄影與回放。格子裡保留相機上的英文標籤。',
    more: '更多選項', back: '返回', qrAria: '目前設定的 QR code', qrUnavailable: 'QR code 無法產生',
    engineLoading: '正在載入模擬引擎…', engineFailed: '模擬引擎載入失敗，請重新載入此頁。',
    presetOnly: '只有預設資料。自訂尺寸與 QR code 需要本機模擬服務。',
    calcFailed: '計算未能完成，請重新載入。', calculating: '正在計算配方…',
    noRecipes: '這組尺寸沒有可用配方。', upToDate: '尺寸與配方已是最新',
    engine: (v, b) => `SensorLab v${v} · ${b ? '瀏覽器' : '本機'}模擬`,
    stLock: '鎖定', stFree: '自由', stVisible: '可見', stTarget: '目標', stCustom: '自訂', stRatio: '比例',
    stFine: '微調中', stRate: '自訂幀率', stNone: '無', stMemory: '記住的自訂 RES',
    hFrame: '畫面從哪裡來', hMerge: '感光元件像素合併', hKernel: 'ISP 合併核', hStats: '速度與資料量',
    sensor: '感光元件', sdc: 'Sensor DC', sbin: 'Sensor bin', idc: 'ISP DC', iscale: 'ISP 縮放', rec: '錄影',
    sdcT: '感光元件實際讀出的列與欄。', sbinT: (h, v) => `感光元件內把水平 ${h}、垂直 ${v} 個同色像素相加成一個。`,
    idcT: 'ISP 從合併後的畫面裡留下的部分。', iscaleT: (b, z) => `ISP 合併 ${b}、RWZM ${z}，縮到錄影尺寸。`,
    vis: (w, h) => `可見範圍（DNG DefaultCrop）${w}×${h}。`, none: '無', frameCap: '所有階段同一比例，依相機實際位置置中：每個框是該階段的像素網格（感光元件、合併後或錄影像素），後面的階段不會更大。與前一階段同尺寸時略向內縮以便分辨。實線 = 階段；虛線 = 這一階段如何被壓縮進下一階段。', dashedKey: '虛線 = 壓縮進下一階段', sameSize: '同尺寸',
    merge1: '1×1：每個像素原樣讀出，最銳利、資料量最大。',
    mergeN: (h, v) => `${h}×${v}：水平 ${h}、垂直 ${v} 個同色像素在感光元件裡合成一個，畫面變小、雜訊更低、讀得更快。`,
    sumUp: '同色相加', toOne: '→ 1 個輸出', kernelOn: (k, m) => `ISP 把相鄰 3 個同色像素依 [${k}] 加權合成一個（${m}）。中間權重越大越銳利，越平均越柔、越乾淨。`,
    kernelOff: '這個模式沒有用 ISP 合併，只做縮放。', noBin: '不合併',
    fps: '每秒幀數', unc: '未壓縮', ll: 'Lossless 預估', rs: '捲簾', actual: f => `fps（實際 ${f}）`,
    media: m => m === 'SSD' ? '以 SSD 計' : `以 SD ${m} 計`, rsCap: '捲簾（rolling shutter）= 從第一列讀到最後一列的時間，越短，快速移動越不歪。',
    thisMode: '這個模式', stockFhd: '原廠 FHD 29.97', tuned: '微調', recipeMax: '配方上限',
    fields: {ver: '版本', dcw: 'DC 寬', dch: 'DC 高', rw: 'RES 寬', rh: 'RES 高', fps: 'FPS 選項', vmax: 'VMAX', hmax: 'HMAX',
      ad: 'ADC', mh: '感光元件水平合併', mv: '感光元件垂直合併', hbin: 'ISP 水平合併', vbin: 'ISP 垂直合併', key: '讀出 key',
      kh: '水平合併核', kv: '垂直合併核', km: '合併核模式', rcustom: '配方 CUSTOM', visw: '可見寬', vish: '可見高',
      rs: '捲簾 µs', fmt: '格式', rescustom: 'RES CUSTOM', scw: '感光元件裁切寬', sch: '感光元件裁切高', ww: 'ISP 視窗寬', wh: 'ISP 視窗高'} } };
let LANG = '';
try { LANG = global.localStorage.getItem('sl410-lang') || ''; } catch (e) { LANG = ''; }
if (!I18N[LANG]) LANG = 'en';                     // English by default, whatever the browser language
function tr(key, ...args) {
  const v = I18N[LANG][key] ?? I18N.en[key];
  return typeof v === 'function' ? v(...args) : v ?? key;
}
function setLang(lang) {
  if (!I18N[lang]) return;
  LANG = lang;
  try { global.localStorage.setItem('sl410-lang', lang); } catch (e) { /* private mode: this visit only */ }
}

// ---- the camera's code (qs/slqs.c "QR"): fields MSB first, CRC-8 0x07 over 213 bits, one 0 pad bit, base64url ------
const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
function crc8(bits) { let c = 0; for (const b of bits) { const top = (c >> 7) ^ b; c = (c << 1) & 0xFF; if (top) c ^= 0x07; } return c; }
const DIMENSIONS = ['dcw', 'dch', 'rw', 'rh', 'scw', 'sch', 'ww', 'wh', 'visw', 'vish'];
function decodeRecipe(code) {                     // {fields} or {error: length|chars|crc|pad|version|field}
  const nbits = QR_FIELDS.reduce((a, f) => a + f[1], 0), nch = Math.ceil((nbits + 8) / 6);
  if (typeof code !== 'string' || code.length !== nch) return {error: 'length'};
  if (/[^A-Za-z0-9_-]/.test(code)) return {error: 'chars'};
  const bits = [...code].flatMap(ch => { const v = B64.indexOf(ch); return [5, 4, 3, 2, 1, 0].map(i => v >> i & 1); });
  let pos = 0; const take = n => { let v = 0; for (let i = 0; i < n; i++) v = v * 2 + bits[pos++]; return v; };
  const f = {}; for (const [k, n] of QR_FIELDS) f[k] = take(n);
  if (take(8) !== crc8(bits.slice(0, nbits))) return {error: 'crc'};
  if (!bits.slice(pos).every(b => b === 0)) return {error: 'pad'};
  if (f.ver !== 1) return {error: 'version'};
  if (!(f.ad < 3 && f.fps < 31 && f.kh < KERNELS.length && f.kv < KERNELS.length && f.hmax && f.vmax &&
        f.mh && f.mv && f.hbin && f.vbin && DIMENSIONS.every(k => f[k] > 0))) return {error: 'field'};
  return {fields: f};
}

// ---- what a code means (ported from the former mode viewer, site/README.md) -----------------------------------------
// v1 records the requested RES and actual ISP window, not zoom itself. Rebuild core.c q_isp's visible-tolerance zoom,
// including its <1026 unity and bin3 rule.
function ispZoom(f) {
  const bw = Math.max(f.ww, Math.floor(f.dcw / f.mh));
  const bh = Math.max(f.wh, Math.floor(f.dch / f.mv / 2) * 2);
  const z = (src, bin, dst) => { const n = Math.floor(Math.floor(src / bin) * 1024 / dst); return n < 1026 ? 1024 : n; };
  let h = f.hbin === 3 || bw > f.rw ? z(bw, f.hbin, f.rw) : 1024;
  let v = f.vbin === 3 || bh > f.rh ? z(bh, f.vbin, f.rh) : 1024;
  if ((f.hbin === 3 || f.vbin === 3) && h === 1024 && v === 1024) h = v = 1025;
  return [h, v];
}
const SENSOR = [6048, 4040], CLK = 72e6;
function describe(f) {
  const M = Object.assign({}, f);
  M.zoom = ispZoom(f);
  M.adBits = [11, 12, 14, 12][f.ad]; M.fpsExact = CLK / (f.hmax * f.vmax);
  // This is the current SensorLab recording policy, not a claim about every ISP path.
  M.recordBits = M.adBits === 14 && M.zoom.every(z => z === 1024) && f.hbin === 1 && f.vbin === 1 ? 14 : 12;
  M.recW = f.visw + 16; M.recH = f.vish + 10;     // v1 carries each recipe's own DNG DefaultCrop
  M.fpsLabel = f.fps < 29 ? String(STD[f.fps]) : '';
  M.k = KERNELS[f.kh] || KERNELS[1]; M.mode = f.km ? 'STD' : 'SOFT';
  M.bw = Math.floor(f.scw / f.mh); M.bh = Math.floor(f.sch / f.mv);          // the binned frame (sensor output)
  M.winW = Math.min(f.ww || M.bw, M.bw); M.winH = Math.min(f.wh || M.bh, M.bh); // the ISP window inside it
  M.dcName = (DCS.find(d => d[1] === f.dcw && d[2] === f.dch) || ['Custom'])[0];
  M.fpsText = M.fpsLabel || M.fpsExact.toFixed(3);
  return M;
}
function dataRates(M) { // Conservative lossless estimate; recorded depth and actual raster match QS.
  const b = M.recordBits, px = M.recW * M.recH, fu = px * b / 8 + 79184;
  const one = M.mh * M.mv === 1 && M.hbin * M.vbin === 1 && M.zoom.every(z => z <= 1028);
  const B = Math.min(b, 5.0 + 2 * (b === 14) + 1.5 * one);
  const u = M.fpsExact * fu / 1e6, ll = M.fpsExact * Math.min(fu, px * B / 8 + 81000) / 1e6;
  return {u, ll, duty: ll / 240};
}

// ---- the frame diagram: ONE scale, every stage at its real position inside the previous one (Bei 11-04) ------------
// Each solid box is that stage's pixel grid at the same drawing scale: sensor px, the sensor's crop, binned px (the
// sensor's output), the ISP's window in binned px, recorded px. Every step keeps or reduces the pixel count, so boxes
// only shrink or stay equal. Positions: the code carries no offsets, and the camera centres every window (the sensor
// crop on the array, the ISP window in the binned frame, the scaled picture), so each box is centred in its parent;
// that is the real geometry, and it is what makes a crop visible as a smaller box inside a bigger one.
// A stage the same size as its parent (sensor = DC at OG, no ISP crop...) cannot be told apart at true size, so it is
// drawn INSET px smaller on every side, in its own colour, and its key says "same size"; a stage the data puts a few px
// larger (alignment rounding) is treated the same way while its key keeps the true numbers.
// Crops (sensor -> DC, binned frame -> ISP DC) are just the smaller box inside the bigger one. Deformations (sensor
// binning: DC -> binned frame; ISP bin + RWZM: ISP DC -> recording) get dashed connectors from the source to the result
// in that step's key colour (Bei 11-04): nothing changes -> none; one axis changes -> one line at the middle of each
// changed side (left + right for a width change, top + bottom for a height change); both change -> corner to corner.
// Labels are a colour-keyed list under the drawing, so no line ever crosses one. Drawn back to front.
const FS = 12, ROW = 20, MIN = 2, MARGIN = 6, INSET = 3, HEAD_GAP = 2.5;
function textWidth(s, size = FS) {               // generous: Plex Mono / Menlo advance 0.6 em, CJK a full em
  let w = 0; for (const ch of String(s)) w += /[①-⓿⺀-鿿＀-￯]/.test(ch) ? size : size * 0.62;
  return w;
}
// The sensor cannot crop to any width: a readout key has a few native line widths (core.c core_readout_plan: fmt =
// the narrowest whose line covers the crop); the sensor reads that whole line (binned), and rows either windowed
// (0003 = 1, start 0022/0023) or full height; the SoC receiver then cuts the DC out. `ro` is that plan, from the C core
// (host_bridge.c preview_readout via WebAssembly or the local server); null until it arrives. Sizes in sensor px.
const FULL_LINE = [6064, 4040];                 // the widest native line x every row: the area any readout can cover
function frameStages(M, ro) {
  const read = ro ? [ro.fmt_w * ro.mh, ro.out_h * ro.mv] : FULL_LINE;
  return [
    {size: FULL_LINE, text: `${tr('sensor')} ${FULL_LINE[0]}×${FULL_LINE[1]}`, fill: '--sensor', stroke: '--dim'},
    {size: read, pending: !ro, offset: ro && ro.windowed ? [null, ro.start - (ro.win_top || 56)] : null, fill: '--fill5', stroke: '--g',
      text: ro ? `① ${tr('sro')} ${read[0]}×${read[1]}` : `① ${tr('sro')} ${tr('roPending')}`},
    {size: [M.scw, M.sch], text: `② ${tr('dcrop')} ${M.scw}×${M.sch}`, fill: '--fill', stroke: '--sig'},
    {size: [M.bw, M.bh], text: `③ ${tr('sbin')} ${M.mh}×${M.mv} → ${M.bw}×${M.bh}`, fill: '--fill3', stroke: '--warn'},
    {size: [M.winW, M.winH], text: `④ ${tr('idc')} ${M.winW}×${M.winH}`, fill: '--fill2', stroke: '--info'},
    {size: [M.recW, M.recH], text: `⑤ ${tr('rec')} ${M.recW}×${M.recH}`, fill: '--fill4', stroke: '--b'}];
}
function frameLayout(M, narrow, ro = null) {
  const stages = frameStages(M, ro), span = narrow ? 340 : 560, s = (span - 2 * MARGIN) / FULL_LINE[0];
  const rects = [], dashed = [], labels = [];
  stages.forEach((st, k) => {
    const p = rects[k - 1];
    let w = Math.max(MIN, st.size[0] * s), h = Math.max(MIN, st.size[1] * s);
    const same = !!p && !st.pending && st.size[0] >= stages[k - 1].size[0] && st.size[1] >= stages[k - 1].size[1];
    if (p) {                                       // never bigger; equal (or rounding-larger) -> inset
      if (w > p.w - 2 * INSET) w = Math.max(MIN, Math.min(w, p.w - 2 * INSET));
      if (h > p.h - 2 * INSET) h = Math.max(MIN, Math.min(h, p.h - 2 * INSET));
      w = Math.min(w, p.w); h = Math.min(h, p.h);
    }
    const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
    const x = p ? p.x + (p.w - w) / 2 : MARGIN;   // centred, or at the sensor's real window start row
    const y = !p ? MARGIN : st.offset && st.offset[1] !== null ? clamp(p.y + st.offset[1] * s, p.y, p.y + p.h - h) : p.y + (p.h - h) / 2;
    rects.push({x, y, w, h, fill: st.fill, stroke: st.stroke, k, same, scaled: [st.size[0] * s, st.size[1] * s]});
  });
  const steps = [                                 // [source stage, result stage, x ratio, y ratio]
    [2, 3, M.mh, M.mv], [4, 5, M.winW / M.recW, M.winH / M.recH]];
  for (const [from, to, rx, ry] of steps) {
    const a = rects[from], b = rects[to];
    // An axis changes when the data scales it AND the drawing shows it (more than the equal-size inset).
    const chX = Math.abs(rx - 1) > 0.02 && a.w - b.w > 2 * INSET + 0.5, chY = Math.abs(ry - 1) > 0.02 && a.h - b.h > 2 * INSET + 0.5;
    const line = (x1, y1, tx, ty, at) => {          // the arrowhead sits HEAD_GAP short of the result's edge / corner
      const len = Math.hypot(tx - x1, ty - y1), g = Math.min(HEAD_GAP, len / 3);
      dashed.push({x1, y1, x2: tx - (tx - x1) / len * g, y2: ty - (ty - y1) / len * g, tx, ty, from, to, at, stroke: stages[to].stroke});
    };
    if (chX && chY) for (const [cx, cy] of [[0, 0], [1, 0], [0, 1], [1, 1]])       // both: corner to corner
      line(a.x + cx * a.w, a.y + cy * a.h, b.x + cx * b.w, b.y + cy * b.h, 'c' + cx + cy);
    else if (chX) for (const c of [0, 1])          // width only: the middles of the left and right sides
      line(a.x + c * a.w, a.y + a.h / 2, b.x + c * b.w, b.y + b.h / 2, c ? 'right' : 'left');
    else if (chY) for (const c of [0, 1])          // height only: the middles of the top and bottom sides
      line(a.x + a.w / 2, a.y + c * a.h, b.x + b.w / 2, b.y + c * b.h, c ? 'bottom' : 'top');
  }
  const bottom = MARGIN + FULL_LINE[1] * s;         // the sensor box: the same for every selection
  const rows = stages.map((st, k) => ({text: st.text + (rects[k].same ? ` · ${tr('sameSize')}` : ''), stroke: st.stroke, fill: st.fill, k}));
  rows.push({text: tr('dashedKey'), stroke: '--dim', dash: true});   // always: a fixed number of rows = a fixed height
  rows.forEach((r, i) => labels.push({...r, x: MARGIN, y: bottom + 12 + i * ROW, w: 22 + textWidth(r.text), h: ROW - 4}));
  const W = span;                                  // a fixed drawing box per breakpoint (the tests keep every key inside)
  const H = labels[labels.length - 1].y + ROW - 4 + MARGIN;
  return {W, H, rects, dashed, labels, scale: s};
}
function frameSVG(L) {                            // back to front: solid boxes (outer first), dashed connectors, the key
  const P = [];
  for (const r of L.rects) P.push(`<rect class="stage" x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}" fill="var(${r.fill})" stroke="var(${r.stroke})" stroke-width="${r.k ? 1.5 : 2}"/>`);
  const heads = [...new Set(L.dashed.map(d => d.stroke))];   // one arrowhead marker per step colour
  if (heads.length) P.push('<defs>' + heads.map(c => `<marker id="ah${c}" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="4" markerHeight="4" orient="auto"><path d="M0 0L10 5L0 10z" fill="var(${c})"/></marker>`).join('') + '</defs>');
  for (const d of L.dashed) P.push(`<line class="deform" x1="${d.x1}" y1="${d.y1}" x2="${d.x2}" y2="${d.y2}" stroke="var(${d.stroke})" stroke-width="1.5" stroke-dasharray="5 4" marker-end="url(#ah${d.stroke})"/>`);
  for (const l of L.labels) P.push(`<g class="key"><rect x="${l.x + 1}" y="${l.y + 3}" width="14" height="10" fill="${l.dash ? 'none' : `var(${l.fill})`}" stroke="var(${l.stroke})" stroke-width="1.5"${l.dash ? ' stroke-dasharray="3 2"' : ''}/>` +
    `<text x="${l.x + 22}" y="${l.y + 12}" font-size="${FS}" font-weight="600" fill="var(--ink)">${esc(l.text)}</text></g>`);
  return P.join('');
}
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'})[c]);

// ---- page state: the hash <-> the simulator --------------------------------------------------------------------------
const PAGE = {pending: null, applied: null, error: null, inexact: [], baseline: undefined, edited: false};
function applyStart(f) {                          // DC, RES and kernels now; FPS and recipe once the cell's recipes exist
  S.dcW = f.dcw; S.dcH = f.dch; S.dcAsp = f.dcw / f.dch; S.memory = {};
  if (f.dcw < WMIN || f.dcw > WMAX || f.dcw % 16 || f.dch < HMIN || f.dch > HMAX || f.dch % 2) setDC0(f.dcw, f.dch);
  setRes0(f.rw, f.rh);
  const r = res(); S.resAsp = r.w / r.h;
  S.kh = f.kh; S.kv = f.kv; S.km = f.km;
  PAGE.pending = f;
}
function resolvePending() {                       // the camera's recipe and frame rate, by identity, not by "nearest"
  const f = PAGE.pending, key = qualityKey();
  if (!f || !(key in FPSDATA.cases)) return;
  const R = recipes(), ad = [11, 12, 14][f.ad];
  const q = R.find(q => q.hm === f.hmax && q.d.key === KEY_NAMES[f.key] && q.d.ad === ad && q.d.mh === f.mh && q.d.mv === f.mv &&
    q.d.hbin === f.hbin && q.d.vbin === f.vbin && q.d.scw === f.scw && q.d.sch === f.sch && q.d.win[0] === f.ww && q.d.win[1] === f.wh);
  S.recipe = q ? q.q : null;
  S.recipeD = q ? q.d : {ad, mh: f.mh, mv: f.mv, hbin: f.hbin, vbin: f.vbin, scw: f.scw, sch: f.sch};
  S.fpsCustom = null; S.fine = false;
  const exact = FPSDATA.clk / (f.hmax * f.vmax);
  if (f.fps < 29) S.fps = STD[f.fps];
  else if (f.fps === 30 && q) {                   // the recipe maximum whose VMAX the camera recorded
    const vm = g => Math.max(q.lo, Math.min(FPSDATA.vmax_max, Math.ceil(FPSDATA.clk / (q.hm * g) - 1e-9)));
    const m = quals() ? fpsList().find(o => o.mark && vm(o.f) === f.vmax) : null;
    S.fps = m ? m.f : exact;
  } else {                                        // a tuned rate: the rate that VMAX gives, kept as the one custom slot
    S.fps = exact;
    if (quals() && !fpsList().some(o => !o.custom && same(o.f, exact))) S.fpsCustom = exact;
  }
  PAGE.pending = null; PAGE.applied = f;
  const now = qrCode(), mine = now ? decodeRecipe(now).fields : null;
  PAGE.inexact = QR_FIELDS.map(([k]) => k).filter(k => !mine || mine[k] !== f[k]).map(k => [k, f[k], mine ? mine[k] : null]);
  PAGE.baseline = now;
}
function syncHash() {                              // the address follows every change, without history entries
  if (PAGE.pending) return;
  const now = qrCode();
  if (!now) return;
  if (PAGE.baseline === undefined) PAGE.baseline = now;   // the first settled view (default, or after a bad code)
  if (!PAGE.edited && now === PAGE.baseline) return;
  PAGE.error = null; PAGE.inexact = []; PAGE.edited = true;
  if (global.location.hash.slice(1) !== now && global.history && global.history.replaceState)
    global.history.replaceState(null, '', '#' + now);
}
function pageInit() {
  const h = global.location.hash.slice(1);
  if (h === 'recipe') { S.focus = 4; return; }    // test hook: open with RECIPE focused
  if (!h) return;
  const d = decodeRecipe(h);
  if (d.error) PAGE.error = d.error; else applyStart(d.fields);
}
function pageBeforeRender() { resolvePending(); }
function detailFields() {                          // what the details show: the camera's code, or the current selection
  if (PAGE.pending) return PAGE.pending;
  if (PAGE.inexact.length && !PAGE.edited) return PAGE.applied;
  const now = qrCode();
  return now ? decodeRecipe(now).fields : null;
}
function fieldText(k, v) {
  if (v === null || v === undefined) return '—';
  if (k === 'fps') return v < 29 ? String(STD[v]) : v === 30 ? tr('recipeMax') : tr('tuned');
  if (k === 'ad') return [11, 12, 14][v] ? [11, 12, 14][v] + '-bit' : String(v);
  if (k === 'key') return KEY_NAMES[v] || '#' + v;
  return String(v);
}

// ---- rendering -------------------------------------------------------------------------------------------------------
const el = id => global.document.getElementById(id);
const T = (x, y, s, a = '', sz = 13) => `<text x="${x}" y="${y}" font-size="${sz}" ${a}>${s}</text>`;
function currentReadout() {                     // the C core's readout plan of the current recipe, when it is the details' one
  if (PAGE.pending || (PAGE.inexact.length && !PAGE.edited)) return null;
  const c = curRecipe(), key = qualityKey(), list = FPSDATA.cases[key], ro = FPSDATA.readout && FPSDATA.readout[key];
  if (!c || !Array.isArray(list) || !ro) return null;
  const i = list.findIndex(r => r[2] === c.q);
  return i >= 0 && ro[i] ? {...ro[i], win_top: FPSDATA.win_top} : null;
}
function drawFrame(M) {
  const ro = currentReadout(), L = frameLayout(M, (global.innerWidth || 1024) < 700, ro), svg = el('frame');
  svg.setAttribute('viewBox', `0 0 ${L.W} ${L.H}`);
  svg.setAttribute('aria-label', `${tr('sdc')} ${M.scw}×${M.sch} → ${tr('sbin')} ${M.bw}×${M.bh} → ${tr('idc')} ${M.winW}×${M.winH} → ${tr('rec')} ${M.recW}×${M.recH}`);
  svg.innerHTML = frameSVG(L);
  const [zh, zv] = M.zoom.map(z => z / 1024);
  const zs = zh === 1 && zv === 1 ? '1:1' : `1/${zh.toFixed(3)} × 1/${zv.toFixed(3)}`;
  const ib = M.hbin * M.vbin === 1 ? tr('none') : `${M.hbin}×${M.vbin} [${M.k}] ${M.mode}`;
  el('legend').innerHTML = [
    ['s0', `① ${tr('sro')} · ${tr('bySensor')}`, ro ? tr('sroT', ro.fmt_w, ro.out_h, ro.mh, ro.mv, ro.windowed) : tr('roPendingT')],
    ['s1', `② ${tr('dcrop')} · ${tr('byRx')}`, tr('dcropT')],
    ['s2', `③ ${tr('sbin')} · ${tr('bySensor')}`, tr('sbinT', M.mh, M.mv)],
    ['s3', `④ ${tr('idc')} · ISP`, tr('idcT')],
    ['s4', `⑤ ${tr('iscale')} · ISP`, `${tr('iscaleT', ib, zs)} ${tr('vis', M.visw, M.vish)}`]]
    .map(([c, h, s]) => `<div class="${c}"><b>${h}</b>${s}</div>`).join('');
}
function drawMerge(M) {
  const n = 6, c = 30, ox = 20, oy = 14, col = (x, y) => (y % 2 ? (x % 2 ? 'b' : 'g') : (x % 2 ? 'g' : 'r')), P = [];
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++)
    P.push(`<rect x="${ox + x * c}" y="${oy + y * c}" width="${c - 2}" height="${c - 2}" rx="3" fill="var(--${col(x, y)})" opacity=".55"/>`);
  for (let j = 0; j < M.mv; j++) for (let i = 0; i < M.mh; i++) { const x = 2 * i, y = 2 * j; if (x >= n || y >= n) continue;
    P.push(`<rect x="${ox + x * c - 1}" y="${oy + y * c - 1}" width="${c}" height="${c}" rx="4" fill="none" stroke="var(--ink)" stroke-width="2.5"/>`); }
  P.push(T(ox + n * c + 14, oy + 22, `${M.mh}×${M.mv}`, 'font-weight="600"', 22), T(ox + n * c + 14, oy + 44, tr('sumUp'), 'fill="var(--dim)"', 12),
    T(ox + n * c + 14, oy + 64, tr('toOne'), 'fill="var(--dim)"', 12));
  el('merge').innerHTML = P.join('');
  el('mergeCap').textContent = M.mh * M.mv === 1 ? tr('merge1') : tr('mergeN', M.mh, M.mv);
}
function drawKernel(M) {
  if (M.hbin * M.vbin === 1) { el('kernel').innerHTML = T(150, 100, '1:1', 'text-anchor="middle" font-weight="600"', 34) +
    T(150, 130, tr('noBin'), 'text-anchor="middle" fill="var(--dim)"', 13); el('kernelCap').textContent = tr('kernelOff'); return; }
  const k = M.k.split(',').map(Number), s = k.reduce((a, b) => a + b, 0), mx = Math.max(...k), P = [], bw = 60, base = 170;
  k.forEach((w, i) => { const h = 130 * w / mx, x = 40 + i * (bw + 20);
    P.push(`<rect x="${x}" y="${base - h}" width="${bw}" height="${h}" rx="4" fill="var(--info)" opacity=".85"/>`,
      T(x + bw / 2, base + 20, w, 'text-anchor="middle"'), T(x + bw / 2, base - h - 8, `${Math.round(100 * w / s)}%`, 'text-anchor="middle" fill="var(--dim)"', 11)); });
  el('kernel').innerHTML = P.join('');
  el('kernelCap').textContent = tr('kernelOn', M.k, M.mode);
}
function drawStats(M, live) {       // notes/MBPS_TILE_RESEARCH.md v2, conservative
  // The current selection uses the MB/s tile's own estimate (tile grid, chosen media), so the page shows one number;
  // a camera code the simulator cannot reproduce falls back to the code-only estimate.
  const r = live ? rates() : null, media = r ? MEDIA[S.media ?? 1][0] : 'UHS-II';
  const {u, ll, duty} = r ? {u: r.u, ll: r.ll, duty: r.dl} : dataRates(M);
  const stat = (k, v, s, bar) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div>${bar || ''}</div>`;
  const bar = `<div class="bar"><i class="${duty > 1 ? 'over' : duty > .75 ? 'hot' : ''}" style="width:${Math.min(100, duty * 100)}%"></i></div>`;
  el('stats').innerHTML = [stat(tr('fps'), M.fpsText, M.fpsLabel ? tr('actual', M.fpsExact.toFixed(3)) : 'fps'), stat(tr('unc'), Math.round(u), 'MB/s'),
    stat(tr('ll'), `~${Math.round(ll)}`, `MB/s · ${tr('media', media)} ${Math.round(duty * 100)}%`, bar), stat(tr('rs'), (M.rs / 1000).toFixed(2), 'ms')].join('');
  const max = 30, x0 = 150, W = 420, row = (y, lab, ms, cls) => T(0, y + 12, lab, 'fill="var(--dim)"', 12) +
    `<rect x="${x0}" y="${y}" width="${W * Math.min(ms, max) / max}" height="16" rx="3" fill="var(${cls})"/>` + T(x0 + W * Math.min(ms, max) / max + 6, y + 13, `${ms.toFixed(1)} ms`, '', 12);
  el('rs').innerHTML = row(18, tr('thisMode'), M.rs / 1000, '--info') + row(52, tr('stockFhd'), 10.556, '--sensor');   // FHD: mode 106, measured
}
// ---- rolling shutter in the live view: the static lean a horizontal pan would cause (no animation, Bei 11-04) --------
// The last row is read RS after the first, so during a pan of v frame widths per second the bottom row shows the scene
// shifted v × RS frame widths against the top row (to the left for a pan to the right). Applied as a skew about the
// frame's centre row in sensor coordinates: shift (sensor px) = v × RS × DC width over the DC height.
const PAN = {off: 0, slow: 1, fast: 4}, STOCK_FHD_RS_MS = 10.556;   // frame widths per second; stock FHD: mode 106, measured
let PAN_MODE = 'slow', COMPARE = false;
try { const p = global.localStorage.getItem('sl410-pan'); if (p in PAN) PAN_MODE = p; } catch (e) { /* default */ }
function rsSkew(rsMs, v, W, H) {                  // k: the skewX factor (x' = x + k (y - centre)); frac: bottom shift / width
  const frac = v * rsMs / 1000;
  return {frac, shift: frac * W, k: -frac * W / H};
}
function drawRolling() {
  const g = el('scene-g'), ghost = el('ghost');
  if (!g || !ghost) return;
  const c = curRecipe(), v = PAN[PAN_MODE], cy = SENSOR[1] / 2, rs = c ? c.d.rs_ms : 0;
  const m = rsSkew(rs, v, S.dcW, S.dcH), st = rsSkew(STOCK_FHD_RS_MS, v, S.dcW, S.dcH);
  const matrix = k => k ? `matrix(1 0 ${k} 1 ${-k * cy} 0)` : '';
  g.setAttribute('transform', matrix(m.k));
  ghost.setAttribute('transform', matrix(st.k));
  ghost.style.display = COMPARE && v ? '' : 'none';
  global.document.querySelectorAll('[data-pan]').forEach(b => b.setAttribute('aria-pressed', b.dataset.pan === PAN_MODE));
  const box = el('rs-compare'); if (box) box.checked = COMPARE;
  el('rs-now').textContent = tr('rsNow', c ? rs.toFixed(2) : '—', (100 * m.frac).toFixed(2), STOCK_FHD_RS_MS.toFixed(2), (100 * st.frac).toFixed(2));
}
function setPan(mode, compare) {
  if (mode in PAN) { PAN_MODE = mode; try { global.localStorage.setItem('sl410-pan', mode); } catch (e) { /* this visit */ } }
  if (compare !== undefined) COMPARE = !!compare;
}
function pageRender() {
  syncHash();
  drawRolling();
  const doc = global.document;
  if (doc.documentElement) doc.documentElement.lang = LANG === 'en' ? 'en' : LANG === 'hans' ? 'zh-Hans' : 'zh-Hant';
  doc.querySelectorAll('[data-t]').forEach(e => { e.textContent = tr(e.dataset.t); });
  doc.querySelectorAll('[data-th]').forEach(e => { e.innerHTML = tr(e.dataset.th); });
  doc.querySelectorAll('.lang button').forEach(b => b.setAttribute('aria-pressed', b.dataset.l === LANG));
  const f = detailFields(), M = f ? describe(f) : null;
  el('lede').textContent = PAGE.pending ? tr('ledeLoading') : PAGE.edited ? tr('ledeEdited') : PAGE.applied ? tr('ledeCamera') : tr('ledeDefault');
  const notice = PAGE.error ? tr('bad', tr('r' + PAGE.error)) : PAGE.inexact.length && !PAGE.edited ? tr('inexact') : '';
  // Once shown, the notice keeps its space when it clears (no layout jump on the first change); only hidden.
  if (notice) el('notice').hidden = false;
  el('notice').style.visibility = notice ? 'visible' : 'hidden';
  if (notice) el('notice').innerHTML = esc(notice) + (PAGE.error ? '' : '<ul>' + PAGE.inexact.map(([k, c, s]) =>
    `<li>${esc(tr('diff', (I18N[LANG].fields || I18N.en.fields)[k], fieldText(k, c), fieldText(k, s)))}</li>`).join('') + '</ul>');
  el('details').style.visibility = M ? '' : 'hidden';    // keeps its space: no jump when a selection has no recipe
  el('title').textContent = M ? `${M.dcName} · ${M.rw}×${M.rh} · ${M.fpsText}p` : 'SensorLab-IMX410';
  if (!M) { el('chips').style.visibility = 'hidden'; return; }
  el('chips').style.visibility = '';
  // Fixed widths (mono ch, sized for the longest value), so a changed value never rewraps the row.
  el('chips').innerHTML = [[9, `DC <b>${M.dcName}</b>`], [13, `RES <b>${M.rw}×${M.rh}</b>`], [10, `DNG <b>${M.recordBits}</b>-bit`],
    [10, `ADC <b>${M.adBits}</b>-bit`], [10, `sensor <b>${M.mh}×${M.mv}</b>`], [7, `ISP <b>${M.hbin * M.vbin === 1 ? '—' : M.hbin + '×' + M.vbin}</b>`],
    [11, `RS <b>${(M.rs / 1000).toFixed(1)}</b> ms`]].map(([w, s]) => `<span class="chip" style="min-width:calc(${w}ch + 22px)">${s}</span>`).join('');
  drawFrame(M); drawMerge(M); drawKernel(M); drawStats(M, !PAGE.pending && !(PAGE.inexact.length && !PAGE.edited));
}
function pageBind() {                              // header language buttons; a hand-edited hash reloads the page
  const doc = global.document;
  doc.querySelectorAll('.lang button').forEach(b => b.addEventListener('click', () => { setLang(b.dataset.l); render(); }));
  doc.querySelectorAll('[data-pan]').forEach(b => b.addEventListener('click', () => { setPan(b.dataset.pan); render(); }));
  const box = el('rs-compare'); if (box) box.addEventListener('change', () => { setPan(null, box.checked); render(); });
  global.addEventListener('hashchange', () => { if (global.location.hash.slice(1) !== (qrCode() || '')) global.location.reload(); });
  let rz; global.addEventListener('resize', () => { clearTimeout(rz); rz = setTimeout(render, 150); });
}
Object.assign(global, {tr, pageInit, pageBeforeRender, pageRender, pageBind});
global.SiteRecipe = {I18N, PAGE, decodeRecipe, describe, dataRates, ispZoom, frameLayout, frameSVG, frameStages, textWidth, crc8, setLang, rsSkew, setPan, PAN, STOCK_FHD_RS_MS,
  lang: () => LANG};
})(globalThis);
