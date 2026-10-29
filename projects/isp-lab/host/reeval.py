#!/usr/bin/env python3
"""Re-run case.py on finished runs whose push/ now lives only in evidence.tar.zst (nightrun drops the raw copy).

    reeval.py RUN [RUN ...]       each: unpack push/ to a temp dir, case.build there, copy case.json + shots back
"""
import pathlib, shutil, subprocess, sys, tempfile
import case, evidence_jxl

for arg in sys.argv[1:]:
    run = pathlib.Path(arg).resolve()
    if (run / 'push').is_dir():
        c = case.build(run)
    else:
        if not (run / 'evidence.tar.zst').exists() and not (run / 'EVIDENCE.json').exists():
            print('skip', run.name); continue
        with tempfile.TemporaryDirectory(prefix='reeval-') as tmp:
            t = pathlib.Path(tmp) / run.name
            t.mkdir()
            evidence_jxl.unpack(run, t, ['push', 'applied.json'])
            c = case.build(t)
            shutil.copy2(t / 'case.json', run / 'case.json')
            if (t / 'shots').exists():
                shutil.rmtree(run / 'shots', ignore_errors=True)
                shutil.copytree(t / 'shots', run / 'shots')
    print(run.name, c.get('verdict'), c.get('checks'), flush=True)
