// The pre-0.0.5test QR corpus: every preset recipe of the 0.0.4test fps_data.js (validation/20261110-vertical-margin/
// before-sources/fps_data.js, the pre-margin core) encoded by the page's own qrFields (bit-identical to the camera's
// qr_fields, test_web / test_qrdec) at three rates: its maximum (pick 30), the highest common rate it reaches
// (pick 0..28) and a tuned rate 10 fine steps below its maximum (pick 29).  Run: node gen_corpus.js > corpus.json
'use strict';
const fs = require('node:fs'), path = require('node:path');
const P = path.join(__dirname, '..', '..', '..', 'preview');
const OLD = path.join(__dirname, '..', '..', '..', 'validation', '20261110-vertical-margin', 'before-sources', 'fps_data.js');
let src = fs.readFileSync(path.join(P, 'test_client.js'), 'utf8');
const tail = src.match(/^const DCMAP = .*$\n^const site = .*$/m)[0];
src = src.slice(0, src.indexOf('\ntest(')) + '\n' + tail;
src = src.replace(/__dirname/g, JSON.stringify(P)).replace("path.join(" + JSON.stringify(P) + ", 'fps_data.js')", JSON.stringify(OLD))
  .replace(/^const test = require\('node:test'\);$/m, '');
eval(src + `
const out = [];
for (const [key, recipes] of Object.entries(FPS.cases)) {
  if (!Array.isArray(recipes)) continue;
  const [dc, wh] = key.split(':'), [rw, rh] = wh.split('x').map(Number);
  for (const [, , name] of recipes) for (const mode of [0, 1, 2]) {
    const a = site();
    a.run(\`S.dcW = \${DCMAP[dc][0]}; S.dcH = \${DCMAP[dc][1]}; S.memory = {}; setRes0(\${rw}, \${rh});
      S.recipe = \${JSON.stringify(name)}; S.recipeD = FPSDATA.cases[\${JSON.stringify(key)}].find(r => r[2] === \${JSON.stringify(name)})[3];
      S.kh = 1; S.kv = 1; S.km = 0; S.fine = false; S.fpsCustom = null;
      { const q = allQuals().find(q => q.q === \${JSON.stringify(name)}), top = Math.min(q.max, 1000);
        if (\${mode} === 0) S.fps = top;
        else if (\${mode} === 1) S.fps = STD.filter(f => f <= top + 5e-4).pop() || top;
        else { S.fps = top; S.fine = true; S.fps = fineStep(S.fps, -1, true); fineExit(); } }
      render();\`);
    if (a.run('(curRecipe() || {}).q') !== name) continue;
    const f = a.value('qrFields()'), names = a.value('QR_FIELDS.map(x => x[0])');
    if (f) out.push({cell: key, recipe: name, mode, f: names.map(k => f[k])});
  }
}
process.stdout.write(JSON.stringify(out));
`);
