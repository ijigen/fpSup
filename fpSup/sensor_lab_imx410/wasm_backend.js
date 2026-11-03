/* The camera's unchanged C core and QR encoder, compiled to WebAssembly.
 * This file only marshals inputs/outputs; recipe arithmetic stays in C. */
(function (global) {
  'use strict';
  const scriptURL = typeof document !== 'undefined' && document.currentScript
    ? document.currentScript.src : null;

  async function create(bytes, manifest) {
    const {instance} = await WebAssembly.instantiate(bytes, {});
    const api = instance.exports;
    if (api.preview_quality_size() !== manifest.fields.length * 4 ||
        api.preview_clock() !== manifest.clk || api.preview_vmax_max() !== manifest.vmax_max)
      throw new Error('SensorLab engine and manifest do not match. Reload the page.');
    const decoder = new TextDecoder();
    function cstring(pointer) {
      const memory = new Uint8Array(api.memory.buffer);
      let end = pointer;
      while (end < memory.length && memory[end]) end++;
      if (!pointer || end === memory.length) throw new Error('Invalid engine string');
      return decoder.decode(memory.subarray(pointer, end));
    }
    return {
      async info() { return {...manifest.info, runtime: 'wasm'}; },
      async qualities(dcw, dch, rw, rh) {
        const c = manifest.constants;
        for (const [name, v, low, high, step] of [
          ['dcw', dcw, c.WMIN, c.WMAX, 16], ['dch', dch, c.HMIN, c.HMAX, 2],
          ['rw', rw, c.WMIN, dcw, 16], ['rh', rh, c.HMIN, dch, 2]]) {
          if (!Number.isInteger(v) || v < low || v > high || v % step)
            throw new Error(`${name} must be ${low}..${high}, aligned to ${step}`);
        }
        const n = api.wasm_qualities(dcw, dch, rw, rh, c.TOL_NUM, c.TOL_DEN);
        let rows = [];
        if (n < 0 || n > c.MAXR) rows = {err: `core result ${n}`};
        else {
          const values = new Int32Array(api.memory.buffer, api.wasm_rows(), n * manifest.fields.length);
          for (let i = 0; i < n; i++) {
            const q = Object.fromEntries(manifest.fields.map((field, j) => [field, values[i * manifest.fields.length + j]]));
            const recipe = {key: cstring(api.preview_key_name(q.key)), mh: q.mh, mv: q.mv, ad: q.ad,
              hbin: q.hbin, vbin: q.vbin, scw: q.cw, sch: q.ch, sw: q.sw, sh: q.sh,
              win: [q.win_w, q.win_h], zoom: [q.zh, q.zv], path: cstring(api.preview_path_name(q.path)),
              rs_ms: q.rs_us / 1000, rec: [q.rec_w, q.rec_h], vis: [q.vis_w, q.vis_h]};
            let label = `${q.ad}b ${q.mh}x${q.mv}`;
            if (q.hbin !== 1 || q.vbin !== 1) label += ` h${q.hbin}v${q.vbin}`;
            rows.push([q.hm, q.vmin_lo, label, recipe]);
          }
        }
        const preset = manifest.dc_names.find(p => p.w === dcw && p.h === dch);
        return {key: `${preset ? preset.name : `C${dcw}x${dch}`}:${rw}x${rh}`, case: rows,
          nominal: [rw - manifest.margin[0], rh - manifest.margin[1]], clk: manifest.clk, vmax_max: manifest.vmax_max};
      },
      // The readout plan of every recipe of a cell (same order as qualities()): what the sensor sends.
      async readout(dcw, dch, rw, rh) {
        const cell = await this.qualities(dcw, dch, rw, rh);
        if (!Array.isArray(cell.case)) return {key: cell.key, readout: null, win_top: api.preview_win_top()};
        const out = cell.case.map((_, i) => {
          const v = new Int32Array(api.memory.buffer, api.wasm_readout(i), 10);
          return v[0] ? null : {fmt_w: v[1], line_w: v[2], raster_w: v[3], out_h: v[4], mh: v[5], mv: v[6],
            windowed: v[7], start: v[8], y_skip: v[9]};
        });
        return {key: cell.key, readout: out, win_top: api.preview_win_top()};
      },
      async qr(code) {
        if (typeof code !== 'string' || !new RegExp(`^[A-Za-z0-9_-]{${manifest.constants.QR_CHARS}}$`).test(code))
          throw new Error('Invalid recipe code');
        const data = new TextEncoder().encode(manifest.info.qr_url + code + '\0');
        if (data.length > api.wasm_url_capacity()) throw new Error('QR URL is too long');
        new Uint8Array(api.memory.buffer, api.wasm_url(), data.length).set(data);
        const size = api.wasm_qr();
        if (size !== manifest.constants.QR_N) throw new Error('Camera QR encoder rejected this payload');
        const pixels = new Uint8Array(api.memory.buffer, api.wasm_qr_output(), size * size);
        return {size, modules: Array.from({length: size}, (_, y) => Array.from(pixels.subarray(y * size, (y + 1) * size)))};
      }
    };
  }

  async function load(base = new URL('.', scriptURL || location.href)) {
    const [manifestResponse, wasmResponse] = await Promise.all([
      fetch(new URL('wasm_info.json', base), {cache: 'no-cache'}),
      fetch(new URL('sensorlab.wasm', base), {cache: 'no-cache'})
    ]);
    if (!manifestResponse.ok || !wasmResponse.ok) throw new Error('Could not load the SensorLab engine');
    const [manifest, bytes] = await Promise.all([manifestResponse.json(), wasmResponse.arrayBuffer()]);
    if (global.crypto && global.crypto.subtle) {
      const hash = Array.from(new Uint8Array(await global.crypto.subtle.digest('SHA-256', bytes)), v => v.toString(16).padStart(2, '0')).join('');
      if (hash !== manifest.wasm_sha256) throw new Error('SensorLab engine download is stale. Reload the page.');
    }
    return create(bytes, manifest);
  }
  global.SensorLabWasm = {load, create};
})(globalThis);
