"""test_qrscan MUTANTS, with the stale Tile.test_ael_go_needs_api7_and_no_recording (expects container API 8, is 9)
left out so a mutant is only 'caught' by a real failure"""
import os, pathlib, shutil, subprocess, sys, tempfile
HERE = pathlib.Path('.').resolve(); sys.path.insert(0, str(HERE))
import test_qrscan as T, build_slqs as BS
only = sys.argv[1:]
tests = ['Install', 'Restore.test_each_derived_field_mismatch_is_refused_and_named', 'Decoder', 'Page',
         'Tile.test_the_dial_hint_flag_only_where_the_dials_act', 'Tile.test_the_qr_function_asks_for_the_read_page', 'RecAfterScan']
src = (HERE / 'slqs.c').read_text(); surv = []
for name, a, b in T.MUTANTS:
    if only and not any(o in name for o in only): continue
    assert src.count(a) == 1, name
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', SL_TESTCACHE='ro')
    with tempfile.TemporaryDirectory(prefix='qrscan-mut-') as t:
        env['PYTHONPYCACHEPREFIX'] = t
        m = pathlib.Path(t) / 'slqs.c'; m.write_text(src.replace(a, b))
        shutil.copy(HERE / 'qrdec.c', pathlib.Path(t) / 'qrdec.c'); env['SLQS_SRC'] = str(m)
        try: BS.compile_text(m)
        except BS.BuildError as e: print('BAD', name, str(e)[:200], flush=True); surv.append(name); continue
        r = subprocess.run([sys.executable, '-B', '-m', 'unittest', '-q', *('test_qrscan.' + x for x in tests)], cwd=HERE, env=env, capture_output=True, text=True)
        caught = r.returncode != 0 and ('FAILED' in r.stderr or 'Error' in r.stderr)
    print(('caught   ' if caught else 'SURVIVED ') + name, flush=True)
    if not caught: surv.append(name)
print('survived:', surv)
