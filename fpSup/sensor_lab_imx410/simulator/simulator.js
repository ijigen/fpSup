/* Browser adapter only. Recipe calculation and QR encoding run the camera's C
 * sources through WebAssembly or the local server. */
'use strict';
const simulator = {info: null, state: 'connecting', cells: new Set(), requests: new Map(),
  errors: new Map(), qr: new Map(), qrRequests: new Set(), timer: null, scheduled: null, backend: null};
const browserEngine = typeof SensorLabWasm !== 'undefined';

async function simulatorJSON(path) {
  if (browserEngine) {
    simulator.backend ||= SensorLabWasm.load();
    const backend = await simulator.backend;
    const [route, query] = path.split('?'), params = new URLSearchParams(query);
    if (route === '/api/info') return backend.info();
    if (route === '/api/qualities') return backend.qualities(...['dcw','dch','rw','rh'].map(k => Number(params.get(k))));
    if (route === '/api/qr') return backend.qr(params.get('code'));
    throw new Error('Unknown simulator operation');
  }
  const response = await fetch(path, {cache: 'no-store', signal: AbortSignal.timeout(10000)});
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function simulatorStatus() {
  const el = document.getElementById('connection');
  if (!simulator.info) {
    el.textContent = simulator.state === 'connecting' ? 'Loading the simulation engine…'
      : browserEngine ? 'The simulation engine could not load. Please reload this page.'
      : 'Preset preview only. Open the local simulator server to use custom dimensions and QR codes.';
    return;
  }
  const key = qualityKey(), error = simulator.errors.get(key);
  const detail = error ? 'The calculation could not complete. Please reload.'
    : !simulator.cells.has(key) ? 'Calculating recipes…'
    : !allQuals() ? 'No recipes are available for these dimensions.' : 'Dimensions and recipes are up to date';
  el.textContent = `SensorLab v${simulator.info.version} · ${browserEngine ? 'Browser' : 'Local'} simulation\n${detail}`;
  el.style.whiteSpace = 'pre-line';
}

function simulatorDrawQR(code) {
  const el = document.getElementById('qr-matrix');
  if (!el || el.dataset.code !== code) return;
  const data = simulator.qr.get(code);
  if (!data) {
    if (!simulator.info) {
      el.textContent = 'QR';
      el.style.color = '#000';
      return;
    }
    if (simulator.qrRequests.has(code)) return;
    simulator.qrRequests.add(code);
    simulatorJSON(`/api/qr?code=${encodeURIComponent(code)}`).then(result => {
      if (result.size !== 37 || result.modules.length !== 37 ||
          result.modules.some(row => row.length !== 37 || row.some(v => v !== 0 && v !== 1)))
        throw new Error('Invalid QR matrix');
      simulator.qr.set(code, result);
      if (simulator.qr.size > 64) simulator.qr.delete(simulator.qr.keys().next().value);
      simulatorDrawQR(code);
    }).catch(() => {
      const current = document.getElementById('qr-matrix');
      if (current && current.dataset.code === code) {
        current.textContent = 'QR code unavailable';
        current.style.color = '#000';
      }
    }).finally(() => simulator.qrRequests.delete(code));
    return;
  }
  // Native V5-L: 37 modules + a two-module border = the camera's 205 px square.
  let path = '';
  data.modules.forEach((row, y) => row.forEach((dark, x) => {
    if (dark) path += `M${x+2} ${y+2}h1v1h-1z`;
  }));
  el.innerHTML = `<svg viewBox="0 0 41 41" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><rect width="41" height="41" fill="white"/><path d="${path}" fill="black"/></svg>`;
}

function simulatorLoadCell(key) {
  if (simulator.cells.has(key) || simulator.requests.has(key) || simulator.errors.has(key)) return;
  const r = res();
  const params = new URLSearchParams({dcw: S.dcW, dch: S.dcH, rw: r.w, rh: r.h});
  const request = simulatorJSON(`/api/qualities?${params}`).then(data => {
    if (data.key !== key || !(Array.isArray(data.case) || typeof data.case?.err === 'string'))
      throw new Error('Wrong recipe cell');
    FPSDATA.cases[key] = data.case;
    FPSDATA.nominal[key] = data.nominal;
    FPSDATA.clk = data.clk; FPSDATA.vmax_max = data.vmax_max;
    simulator.cells.add(key);
    // A response for an older crop is cached only. It must never lower the FPS
    // or replace the selection of the crop that the user has since moved to.
    if (qualityKey() === key) { fixFps(); render(); }
  }).catch(error => {
    simulator.errors.set(key, error.message);
    if (qualityKey() === key) simulatorStatus();
  }).finally(() => simulator.requests.delete(key));
  simulator.requests.set(key, request);
}

function simulatorRender() {
  simulatorStatus();
  const details = document.getElementById('mode-link');
  if (details) details.href = '../' + (qrCode() ? '#' + qrCode() : '');
  const code = qrVisible() && qrCode();
  if (code) simulatorDrawQR(code);
  if (!simulator.info) return;
  const key = qualityKey();
  if (simulator.scheduled !== key) {
    clearTimeout(simulator.timer);
    simulator.scheduled = key;
    simulator.timer = setTimeout(() => simulatorLoadCell(key), 40);
  }
}

async function simulatorConnect() {
  if (!/^https?:$/.test(location.protocol)) {
    simulator.state = 'offline'; simulatorRender(); return;
  }
  try {
    simulator.info = await simulatorJSON('/api/info');
    if (!simulator.info.version || !simulator.info.core_fingerprint) throw new Error('Not a simulator server');
    simulator.state = 'ready';
    // Presets remain a file:// fallback only; the selected C engine calculates
    // every requested cell from its exact C-source snapshot.
    FPSDATA.cases = {}; FPSDATA.nominal = {};
    render();
  } catch (_) {
    simulator.info = null; simulator.state = 'offline'; simulatorRender();
  }
}
simulatorConnect();
