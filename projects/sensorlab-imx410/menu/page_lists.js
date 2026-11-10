// The spec page's own lists (preview/dcres.html, read only), for the menu rows' tests.
//
//   node page_lists.js PAGE.html FPS_DATA.js STATES.json
//
// STATES.json: [{dcW, dcH, res: {w, h} | null, resK, resRatio, fps, fpsCustom, fine}, ...]
// For every state: the DC / RES / FPS footer options exactly as the page builds them (opts / sel / v), so
// menu_lists.py (the menu's reference) can be required to list the same rows.  Nothing is written.
'use strict';
const fs = require('fs');
const [page, dataFile, statesFile] = process.argv.slice(2, 5);
const html = fs.readFileSync(page, 'utf8');
const script = html.split('<script>\n')[1].split('</script>')[0];
const logic = script.split('// ---- render')[0];
const data = fs.readFileSync(dataFile, 'utf8');
const states = JSON.parse(fs.readFileSync(statesFile, 'utf8'));
const body = data + '\n' + logic + `
const out = [];
for (const st of states) {
  S.dcW = st.dcW; S.dcH = st.dcH;
  S.resCustom = st.res || null; S.resK = st.resK || null; S.resRatio = st.resRatio === undefined ? 1/3 : st.resRatio;
  S.fps = st.fps; S.fpsCustom = st.fpsCustom || null; S.fine = !!st.fine; S.recipe = null; S.recipeD = null;
  const r = res();
  out.push({dc: {opts: DC.opts().map(o => o.l), sel: DC.sel(), v: DC.v()},
            res: {opts: RES.opts().map(o => o.l), sel: RES.sel(), v: String(RES.v()), w: r.w, h: r.h},
            fps: {opts: FPS.opts().map(o => ({l: o.l, na: !!o.na, custom: !!o.custom, mark: !!o.mark})),
                  sel: FPS.sel(), v: String(FPS.v()), q: !!quals()}});
}
return out;
`;
process.stdout.write(JSON.stringify(new Function("states", body)(states)));
