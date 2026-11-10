from pathlib import Path
import os,sys,io,json,unittest
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
sys.path[:0]=[str(ROOT/'projects/sensorlab-imx410/qs'),str(ROOT/'projects/qs-container')]
import test_slqs as S
import test_qs_page as P
import test_qsct as Q
src=(ROOT/'projects/qs-container/qsct.c').read_text()
checks=[('hidden_title', '                        sm = qc_blank(s); approx = 0;\n                        if (lk == QSC_LOCK_SMALL_SHUT)', '                        l = qc_blank(s); sm = qc_blank(s); approx = 0;\n                        if (lk == QSC_LOCK_SMALL_SHUT)'),
        ('stuck_small_lock','if (lk == QSC_LOCK_SMALL_SHUT) small_lock_width = 120u;', 'small_lock_width = 120u;')]
rows=[]
for name,old,new in checks:
    assert src.count(old)==1
    mutant=HERE/(name+'.c');mutant.write_text(src.replace(old,new))
    os.environ['QSCT_SRC']=str(mutant)
    Q._built.clear();S._built.clear()
    log=io.StringIO();r=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(S.RatioTile))
    (HERE/(name+'.log')).write_text(log.getvalue())
    row=dict(name=name,tests=r.testsRun,failures=len(r.failures),errors=len(r.errors));rows.append(row)
    assert row['failures'] and not row['errors'],row
os.environ.pop('QSCT_SRC');os.environ['QSCT_QS_MUTATE']='lockright';Q._built.clear();S._built.clear()
log=io.StringIO();r=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName('Tiles.test_small_qs_lock_position_and_binding',P))
(HERE/'right_shift.log').write_text(log.getvalue())
row=dict(name='right_shift',tests=r.testsRun,failures=len(r.failures),errors=len(r.errors));rows.append(row)
assert row['failures'] and not row['errors'],row
(HERE/'negative-checks.json').write_text(json.dumps(rows,indent=2)+'\n');print(json.dumps(rows,indent=2))
