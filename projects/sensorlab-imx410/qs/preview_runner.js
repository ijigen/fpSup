// Runs the preview's own logic (preview/dcres.html: the script before "// ---- render" and the input handlers
// closeSub / moveFocus / act) in node, without a DOM, over scripted key sequences, and prints the visible state
// after every step as JSON.  The page is the spec: test_slqs.py requires the C client to show the same.
//
//   node preview_runner.js PAGE.html FPSDATA.json SEQUENCES.json [--cells]
//
// --cells: also list every DC x RES cell the page looked FPSDATA up for (so the test can generate them).
'use strict';
const fs = require('fs');
const [page, dataFile, seqFile] = process.argv.slice(2, 5);
const wantCells = process.argv.includes('--cells');
const html = fs.readFileSync(page, 'utf8');
const script = html.split('<script>\n')[1].split('</script>')[0];
const logic = script.split('// ---- render')[0];
const input = script.split('// ---- input')[1].split('\n').slice(1).join('\n').split('document.querySelectorAll')[0];
const FPSDATA = JSON.parse(fs.readFileSync(dataFile, 'utf8'));
const seqs = JSON.parse(fs.readFileSync(seqFile, 'utf8'));

const body = logic + '\nfunction render() {}\n' + input + `
const cells = {};
const _allQuals = allQuals;
allQuals = function () { const r = res(); cells[dcName() + ':' + r.w + 'x' + r.h] = [S.dcW, S.dcH, r.w, r.h]; return _allQuals(); };
function snap() {
  const L = layout();
  const tiles = L.map((f, i) => {
    if (!f) return null;
    let s = f.s(), approx = false; if (Array.isArray(s)) [s, approx] = s;
    return {t: f.t, v: String(f.v()), s: s || '', approx: !!approx};
  });
  const f = L[S.focus];
  let foot = null;
  if (f && f === FPS && S.fine) { const Q = quals(); foot = {spin: f3(S.fps), mark: !!Q.find(q => same(q.max, S.fps))}; }
  else if (f && f.spin) foot = {spin: String(f.v()), mark: false};
  else if (f) foot = {opts: f.opts().map(o => ({l: o.l, s: o.s || '', mark: !!o.mark, custom: !!o.custom, na: !!o.na,
                                                 approx: !!o.approx})), sel: f.sel()};
  return {tiles, focus: S.focus, sub: S.sub, open: S.open, fine: S.fine, foot,
          S: {dcW: S.dcW, dcH: S.dcH, fps: S.fps, fpsCustom: S.fpsCustom, recipe: S.recipe, kh: S.kh, kv: S.kv, km: S.km,
              res: res(), rec: (curRecipe() || {}).q || null}};
}
const out = [];
for (const seq of seqs) {
  for (const k of Object.keys(S)) delete S[k];
  Object.assign(S, JSON.parse(INIT));
  const states = [snap()];
  for (const k of seq.keys) {
    if (k.startsWith('focus:')) { if (S.fine) fineExit(); S.focus = +k.slice(6); }
    else act(k);
    states.push(snap());
  }
  out.push({name: seq.name, states});
}
return {out, cells};
`;
const INIT_SRC = logic.match(/const S = (\{[\s\S]*?\});\s*\/\/ memory/);
if (!INIT_SRC) throw new Error('initial S not found');
const f = new Function('FPSDATA', 'INIT', 'document', 'seqs', body);
const init = JSON.stringify(new Function('return ' + INIT_SRC[1])());
const res = f(FPSDATA, init, {}, seqs);
process.stdout.write(JSON.stringify(wantCells ? res : res.out));
