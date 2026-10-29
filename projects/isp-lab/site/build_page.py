#!/usr/bin/env python3
"""ISP custom verification page: every validation/*/case.json (host/case.py) as one card.

    build_page.py [OUT_DIR]          default: site/out  ->  OUT_DIR/isp-custom.html + OUT_DIR/isp-custom-shots/<run>/...

Style follows fpSup/explainers/imx410-lab-sim.html (the IMX410 custom page). Each card: the experiment's Want, the
formula's prediction against the DNG, the field-of-view check, the four checkpoints (standby LV, focus LV,
recording LV, CDNG) as thumbnails linking to the full-size pictures, and links to RESULTS.md / the lossless archive.
"""
import html, json, os, pathlib, shutil, sys

HERE = pathlib.Path(__file__).resolve().parent
VALIDATION = HERE.parent / 'validation'
CHECKPOINTS = (('standby_lv', '待機 LV'), ('focus_lv', '對焦 LV（半按）'), ('mag_lv', '對焦 LV（放大）'),
               ('rec_lv', '錄影中 LV'), ('cdng', 'CDNG'))
CHECK_NAMES = {'size': '尺寸', 'bits': '位深', 'fov': '視野', 'rec_lv': '錄影中 LV 範圍', 'lv_colour': 'LV 顏色',
               'aspect': 'LV 比例', 'cfa': 'Bayer 相位', 'frames': '逐幀畫面'}


def failed(case):
    return [CHECK_NAMES[k] for k in CHECK_NAMES if (case.get('checks') or {}).get(k) is False]

CSS = """
:root { --bg:#eef1f4; --panel:#fbfcfd; --ink:#18212b; --mute:#5d6a78; --line:#d4dbe3; --accent:#2b55c9;
  --pass:#1d7f52; --fail:#b8352a; --pass-bg:#e2f2ea; --fail-bg:#f8e1de;
  --f-ui:"Noto Sans TC","PingFang TC",system-ui,sans-serif; --f-mono:"IBM Plex Mono",ui-monospace,monospace; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#12161b; --panel:#1a2027; --ink:#e3e8ee;
  --mute:#93a0ae; --line:#2c353f; --accent:#7d9cf0; --pass:#5cc493; --fail:#ef8a7f; --pass-bg:#16301f; --fail-bg:#3a1c19; } }
* { box-sizing:border-box; } body { margin:0; background:var(--bg); color:var(--ink); font-family:var(--f-ui); }
header, main { max-width:1100px; margin:0 auto; padding:16px; }
h1 { font-size:1.4rem; margin:8px 0; } .lede { color:var(--mute); line-height:1.6; font-size:.95rem; }
.case { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:16px; margin:16px 0; }
.head { display:flex; flex-wrap:wrap; gap:8px 16px; align-items:baseline; }
.head h2 { font-size:1.1rem; margin:0; } .badge { font-weight:700; padding:2px 10px; border-radius:99px; font-size:.85rem; }
.pass { color:var(--pass); background:var(--pass-bg); } .fail { color:var(--fail); background:var(--fail-bg); }
table { border-collapse:collapse; margin:10px 0; font-family:var(--f-mono); font-size:.85rem; }
td, th { border-bottom:1px solid var(--line); padding:4px 10px 4px 0; text-align:left; }
.shots { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:10px; margin-top:10px; }
.shot { border:1px solid var(--line); border-radius:8px; overflow:hidden; background:var(--bg); }
.shot img { width:100%; display:block; } .shot .cap { font-size:.8rem; padding:6px 8px; color:var(--mute); }
.missing { display:flex; align-items:center; justify-content:center; min-height:110px; color:var(--mute); font-size:.85rem; }
.note { font-size:.9rem; line-height:1.6; color:var(--ink); } a { color:var(--accent); }
.wrap { overflow-x:auto; } .sum td.ok { color:var(--pass); font-weight:700; } .sum td.bad { color:var(--fail); font-weight:700; }
"""


def esc(x):
    return html.escape(str(x))


def card(run, case, shots_rel):
    exp = case.get('experiment', {})
    want = exp.get('want', {})
    verdict = case.get('verdict')
    badge = f'<span class="badge {verdict}">{"通過" if verdict == "pass" else "未通過"}</span>' if verdict else ''
    rows = []
    if want:
        rows.append(('讀出', '×'.join(map(str, want.get('window', [])))))
        rows.append(('錄影合併', '×'.join(map(str, want.get('bin', [])))))
        rows.append(('RWZM', ' / '.join(str(1024 if z == 1023 else z) for z in want.get('zoom', []))))
        rows.append(('位深', want.get('bits')))
    if case.get('predicted'):
        p, m = case['predicted'], case['measured']
        rows.append(('錄影尺寸 預測 → 實測', f"{p['rec'][0]}×{p['rec'][1]} → {m['rec'][0]}×{m['rec'][1]}"))
        if m.get('act'):
            rows.append(('可見區 預測 → 實測', f"{p['act'][0]}×{p['act'][1]} → {round(m['act'][0])}×{round(m['act'][1])}"))
    chk = case.get('checks') or {}
    if chk.get('fov_r') is not None:
        rows.append(('視野相關（對待機 LV）', f"r = {chk['fov_r']}"))
    cd = (case.get('checkpoints') or {}).get('cdng') or {}
    if cd.get('cfa_frames'):
        rows.append(('逐幀 Bayer 相位', ' '.join('✓' if ok else '✗' for ok in cd['cfa_frames'])))
    if cd.get('frame_r'):
        rows.append(('逐幀視野 r', ' '.join('—' if r is None else f'{r:.2f}' for r in cd['frame_r'])))
    if failed(case):
        rows.append(('未過項目', '、'.join(failed(case))))
    table = '<table>' + ''.join(f'<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>' for k, v in rows) + '</table>'
    tiles = []
    for key, label in CHECKPOINTS:
        cp = (case.get('checkpoints') or {}).get(key)
        if cp and cp.get('shot'):
            thumb = f'{shots_rel}/{pathlib.Path(cp["shot"]).name}'
            full = f'{shots_rel}/full/{pathlib.Path(cp["shot"]).name}'
            dims = f"{cp.get('w', '')}×{cp.get('h', '')}"
            tiles.append(f'<a class="shot" href="{esc(full)}"><img loading="lazy" src="{esc(thumb)}" '
                         f'alt="{esc(label)}"><div class="cap">{esc(label)} · {esc(dims)}</div></a>')
        else:
            tiles.append(f'<div class="shot"><div class="missing">{esc(label)}：尚未擷取</div></div>')
    if cd.get('bad_shot'):
        name = pathlib.Path(cd['bad_shot']).name
        tiles.append(f'<a class="shot" href="{esc(shots_rel)}/full/{esc(name)}"><img loading="lazy" '
                     f'src="{esc(shots_rel)}/{esc(name)}" alt="壞幀"><div class="cap">第一個壞幀（CDNG）</div></a>')
    links = []
    if case.get('results_md'):
        links.append(f'<a href="{esc(shots_rel)}/RESULTS.md">結果說明</a>')
    if (VALIDATION / run / 'evidence.tar.zst').exists():
        links.append(f'<a href="{esc(shots_rel)}/evidence.tar.zst">原檔（無損壓縮）</a>')
    elif (VALIDATION / run / 'EVIDENCE.json').exists():
        links.append(f'<a href="{esc(shots_rel)}/evidence.cdngt">原檔 CDNG（JXL 無損）</a> · '
                     f'<a href="{esc(shots_rel)}/evidence.side.tar.zst">其餘檔案</a>（evidence_jxl.py unpack 還原）')
    title = exp.get('name') or exp.get('experiment', run)
    sub = f"{exp.get('experiment', '')} · 殼 {exp.get('route', '')}"
    return (f'<section class="case" id="{esc(run)}"><div class="head"><h2>{esc(title)}</h2>{badge}'
            f'<span class="note">{esc(sub)} · {esc(run)}</span></div>{table}<div class="shots">{"".join(tiles)}</div>'
            f'<p class="note">{" · ".join(links)}</p></section>')


def summary_row(run, case):
    exp = case.get('experiment', {})
    want = exp.get('want', {})
    p, m = case.get('predicted') or {}, case.get('measured') or {}
    fmt = lambda v: '×'.join(map(str, v)) if v else '—'
    n = sum(1 for v in (case.get('checkpoints') or {}).values() if v and v.get('shot'))
    v = case.get('verdict')
    cls = 'ok' if v == 'pass' else 'bad'
    return (f'<tr><td><a href="#{esc(run)}">{esc(exp.get("name") or exp.get("experiment", run))}</a></td>'
            f'<td>{esc(" / ".join(str(1024 if z == 1023 else z) for z in want.get("zoom", [])))}</td>'
            f'<td>{esc(fmt(p.get("rec")))}</td><td>{esc(fmt(m.get("rec")))}</td>'
            f'<td>{esc((case.get("checks") or {}).get("fov_r", "—"))}</td><td>{n}/5</td>'
            f'<td class="{cls}">{"通過" if v == "pass" else "未通過" if v else "—"}</td>'
            f'<td>{esc("、".join(failed(case)))}</td></tr>')


def link(src, dst):
    """Hard link instead of a copy: the evidence archives are ~50 MB each and a copy doubled them (10-28, 38 GB)."""
    if dst.exists():
        if dst.stat().st_ino == src.stat().st_ino:
            return
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def current_runs():
    """{run: matrix case} for the run that stands for each current matrix case: a pass installed with exactly what
    the formula installs today (diffs and vmode), else the latest run of that id. Everything else is history
    (10-28: P1's rec LV before the lvout hook and P5's 14-bit HMAX 870 runs looked like current failures)."""
    sys.path.insert(0, str(HERE.parent / 'host'))
    import isp_custom as IC
    cases = json.loads((HERE.parent / 'host' / 'matrix.json').read_text())
    runs = {}
    for cj in sorted(VALIDATION.glob('*-FHD60_C*/case.json')):
        runs.setdefault(cj.parent.name.split('FHD60_C')[1], []).append(cj.parent)
    pick = {}
    for c in cases:
        rs = runs.get(c['id'], [])
        if not rs:
            continue
        p = IC.plan('FHD60:C' + c['id'])
        cur = sorted(map(tuple, p['diffs']))
        good = [r for r in rs if json.loads((r / 'case.json').read_text()).get('verdict') == 'pass'
                and (a := json.loads((r / 'applied.json').read_text()))
                and sorted(map(tuple, a['diffs'])) == cur and a.get('vmode') == p['vmode']]
        pick[(good or rs)[-1].name] = c
    return pick, len(cases)


def build(out):
    out.mkdir(parents=True, exist_ok=True)
    current, n_matrix = current_runs()
    cards, rows, old_cards, old_rows = [], [], [], []
    for cj in sorted(VALIDATION.glob('*/case.json')):
        run = cj.parent.name
        case = json.loads(cj.read_text())
        dst = out / 'isp-custom-shots' / run
        if (cj.parent / 'shots').exists():
            shutil.copytree(cj.parent / 'shots', dst, dirs_exist_ok=True)
        dst.mkdir(parents=True, exist_ok=True)
        for f in ('RESULTS.md', 'evidence.tar.zst', 'ARCHIVE.json', 'evidence.cdngt', 'evidence.side.tar.zst',
                  'EVIDENCE.json'):
            if (cj.parent / f).exists():
                link(cj.parent / f, dst / f)
            elif (dst / f).exists():                                # repacked by evidence_jxl: drop the stale copy
                (dst / f).unlink()
        cur = run in current
        (cards if cur else old_cards).append(card(run, case, f'isp-custom-shots/{run}'))
        (rows if cur else old_rows).append(summary_row(run, case))
    n_pass = sum(1 for r in current if json.loads((VALIDATION / r / 'case.json').read_text()).get('verdict') == 'pass')
    head = ('<tr><th>實驗</th><th>RWZM</th><th>錄影尺寸 預測</th><th>實測</th>'
            '<th>視野 r</th><th>檢查點</th><th>判定</th><th>未過項目</th></tr>')
    page = f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="description" content="ISP custom 驗證：每組設定由公式算出 profile，實際錄影後比對 DNG 尺寸、視野與四個檢查點。">
<title>ISP Custom 驗證</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Noto+Sans+TC:wght@400;500;700&display=swap">
<style>{CSS}</style></head><body>
<header><h1>ISP Custom 驗證</h1>
<p class="lede">每個案例都由同一條公式產生：目標尺寸 → Want → 整列 profile（65 字），在待機時裝進 RAM，
接著真實錄影（丟棄模式，不寫卡），由相機主動推回錄影中 LV 與 CDNG。判定同時看 DNG 尺寸是否符合公式，
以及畫面視野是否與待機 LV 一致（尺寸對但只錄到一角，仍算未通過）。CDNG 縮圖是彩色（每個 RGGB 四格一像素、
依 DNG 的白平衡）；每一幀都檢查 Bayer 相位與畫面，有壞幀就另外附上第一個壞幀。</p></header>
<main><h2>現行公式：{n_pass} / {n_matrix} 通過</h2>
<p class="note">每個 matrix 案例只列一次：用今天的公式安裝、且通過的那一次；沒有的話列最新一次。
{len(current)} 組有結果。舊公式與研究用的執行收在最下面「歷史」。</p>
<div class="wrap"><table class="sum">{head}{''.join(rows)}</table></div>{''.join(cards)}
<details><summary>歷史：{len(old_rows)} 次執行（舊公式、掃描、A/B）</summary>
<div class="wrap"><table class="sum">{head}{''.join(old_rows)}</table></div>{''.join(old_cards)}</details>
</main></body></html>"""
    (out / 'isp-custom.html').write_text(page)
    return out / 'isp-custom.html', len(cards)


if __name__ == '__main__':
    out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / 'out'
    p, n = build(out)
    print(f'{p}: {n} cases')
