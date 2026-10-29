"""fps data for the SensorLab QS preview: per preset DC x RES, every quality's HMAX, VMAX floor and recipe
(read-only use of quality.py).  Run from anywhere:

    python3 -B gen_fps.py OUT.json [--js fps_data.js] [--tol 0.02]

fpsdata(cells) is the same for any list of cells (the QS client's tests add custom DC x RES).

cases[key] = [[hm, lo, q, recipe], ...] with recipe = {key, mh, mv, ad, hbin, vbin, scw, sch, sw, sh, win, zoom, path,
rs_ms}: scw x sch the sensor crop the readout reads (R16: the full height it reads before the TIM keeps the DC's
rows; WIDEN: the crop + 16), sw x sh its output, win / zoom / path the isp Spec / plan, rs_ms the rolling shutter =
readout_cfg.plan rolling_ms = HMAX x receiver lines / 72 MHz (every line the sensor sends: image rows + over, the
whole frame for full height / R16, the window + V3 margin for a window).

Visible tolerance (QS_DC_RES_SPEC 看到的尺寸與寬容, isp-lab notes/VISIBLE_TOLERANCE.md): --tol (default 0.02) takes
the recipes whose raster is at most tol short of the clean RES per axis.  recipe.rec = the raster it records,
recipe.vis = its own visible size (DNG DefaultCrop = rec - 16 x 10: the RES shown while it is selected);
nominal["DC:WxH"] = [vw, vh] = the clean raster - 16 x 10 (remembered, restored by a full recipe).  The key stays the
clean raster.  --tol off = exact RES only (no rec / vis / nominal).
"""
import json, pathlib, subprocess, sys, time
HOST = pathlib.Path(__file__).resolve().parents[2] / 'isp-lab' / 'host'
sys.path.insert(0, str(HOST))
import quality as Q                                                  # noqa: E402
PAGE = pathlib.Path(__file__).resolve().parent / 'dcres.html'


def preset_lists():
    """[(name, W, H, [(w, h)...])] from the page's own resList (node)"""
    js = PAGE.read_text().split('<script>')[1].split('// ---- state')[0]
    return json.loads(subprocess.run(['node', '-e', 'const f=new Function(process.argv[1]+"; return {DCS,resList};")();'
        'console.log(JSON.stringify(f.DCS.map(([n,W,H])=>[n,W,H,f.resList(W,H,n).map(i=>[i.w,i.h])])))', js],
        capture_output=True, text=True, check=True).stdout)


def case(W, H, w, h, tol):
    """the page's FPSDATA case for one DC x RES: [[hm, lo, q, recipe], ...] (or {'err': ...})"""
    try:
        cs = Q.qualities(W, H, w, h, tol=tol)
    except Exception as e:
        return {'err': type(e).__name__}
    qs = []
    for c in cs:
        lo, vmin, vmax = Q.vmax_range(c)
        mg, ad, hb, vb = Q.quality_of(c)
        a = c['readout']
        mh, mv = (int(x) for x in mg.split('x'))
        rec = dict(key=a[0], mh=mh, mv=mv, ad=int(ad), hbin=hb, vbin=vb, scw=a[1], sch=a[2], sw=a[3], sh=a[4],
                   win=c['window'], zoom=c['zoom'], path=c['path'], rs_ms=round(Q.settings(c)[0]['rolling_ms'], 3))
        if tol is not None:
            rec.update(rec=c['rec'], vis=c['visible'])
        qs.append([Q.hmax_of(c), lo, f"{ad}b {mg}" + (f" h{hb}v{vb}" if (hb, vb) != (1, 1) else ''), rec])
    return qs


def fpsdata(cells, tol=0.02, log=False):
    """cells: [(key "DC:wxh", W, H, w, h)] -> the page's FPSDATA object"""
    out, nominal, t0 = {}, {}, time.time()
    for key, W, H, w, h in cells:
        out[key] = case(W, H, w, h, tol)
        if tol is not None and not isinstance(out[key], dict):
            nominal[key] = Q.visible_of((w, h))
        if log:
            print(key, len(out[key]), f'{time.time()-t0:.0f}s', file=sys.stderr, flush=True)
    data = {'clk': Q.RCF.CLK, 'vmax_max': Q.RCF.VMAX_MAX, 'cases': out}
    if tol is not None:
        data.update(tol=tol, nominal=nominal)
    return data


def main():
    a = sys.argv[sys.argv.index('--tol') + 1] if '--tol' in sys.argv else '0.02'
    tol = None if a == 'off' else float(a)
    cells = [(f'{n}:{w}x{h}', W, H, w, h) for n, W, H, rs in preset_lists() for w, h in rs]
    data = fpsdata(cells, tol, log=True)
    json.dump(data, open(sys.argv[1], 'w'))
    if '--js' in sys.argv:
        open(sys.argv[sys.argv.index('--js') + 1], 'w').write(
            '// generated from projects/isp-lab/host/quality.py (qualities + vmax_range + settings) by gen_fps.py; '
            '[hmax, vmax floor, quality, recipe {key, mh, mv, ad, hbin, vbin, scw, sch, sw, sh, win, zoom, path, rs_ms, rec, vis}]; '
            'rec = raster, vis = its DefaultCrop (the RES shown when picked); nominal[case] = clean raster - 16x10\n'
            'const FPSDATA = ' + json.dumps(data, separators=(',', ':')) + ';\n')


if __name__ == '__main__':
    main()
