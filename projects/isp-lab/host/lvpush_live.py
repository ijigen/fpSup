#!/usr/bin/env python3
"""LV through the built-in push engine, live (standby): ISPC's sampler pushes
the last finished LCD ring slot every --every-ms, --count of them, and
push_rx collects them over LISTEN83 (fpshd 3.3.0).  Then the sampler is
switched off again and the counters are saved.

    lvpush_live.py OUT_DIR [--every-ms 250] [--count 8]
"""
import argparse, hashlib, json, pathlib, sys, time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ispl, push_rx                                         # noqa: E402

FIELDS = ('lv_push', 'lv_every_us', 'lv_lag', 'lv_max', 'lv_t_last', 'lv_n_sent', 'lv_n_skip',
          'lv_n_bad', 'lv_n_err', 'lv_last_reg', 'lv_last_addr')


def set_words(p, at, words):
    """mem set with readback, around a cache flush on each side (ispl.flush)."""
    ispl.flush()
    for _ in range(8):
        for k, v in words:
            p.mem_set(at + ispl.R.OFF[k], v)
        if all(p.mem_get(at + ispl.R.OFF[k])[0] == v for k, v in words):
            break
    else:
        raise SystemExit(f'{words} did not stick')
    ispl.flush()


def capture(out, every_ms=250, count=8, quiet_ms=1000):
    """Bounded standby trial; preserve the report and disable sampling on errors."""
    deadline = every_ms * (count + 1) + max(2000, every_ms + 1000) + 2000
    if not 20 <= every_ms <= 10000 or not 1 <= count <= 64 or deadline > 600000 or quiet_ms < 0:
        raise ValueError('require every-ms 20..10000, count 1..64, deadline <=600 s, quiet-ms >=0')
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError('use a new, empty output directory for each trial')
    ispl.use_ctl_only()
    p = ispl.P()
    ispl.not_recording(p)
    info = ispl.build()
    at = ispl.cap_addr(ispl.block_addr(), info)
    before = ispl.read_cap(p, at)
    if before['ctl'] not in (ispl.R.CTL['idle'], ispl.R.CTL['done']):
        raise RuntimeError('control task is active or failed: inspect it before a standby trial')
    if before['lv_push'] and (not before['lv_max'] or before['lv_n_sent'] < before['lv_max']):
        raise RuntimeError('another LV sampler is active')
    if before['lv_n_sent'] + count > 0xFFFFFFFF:
        raise RuntimeError('LV counter would wrap')
    rep = {'cap_at': at, 'expected_sup_sha256': info.get('sha256'),
           'tool_sha256': hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
           'requested': {'every_ms': every_ms, 'count': count, 'quiet_ms': quiet_ms},
           'before': {k: before[k] for k in FIELDS}, 'cleanup_ok': False}
    failure = cleanup_failure = None
    try:
        set_words(p, at, [('lv_push', 0), ('lv_every_us', every_ms * 1000), ('lv_lag', 0),
                          ('lv_max', before['lv_n_sent'] + count)])
        set_words(p, at, [('lv_push', 1)])                   # last: the sampler starts now
        t0 = time.monotonic()
        end, _, stats = push_rx.listen(out, count * ((16 << 20) + push_rx.HDR),
                                      max(2000, every_ms + 1000), deadline, quiet_ms=quiet_ms)
        rep.update(end=end, stats=stats, listen_s=time.monotonic() - t0)
    except BaseException as exc:
        failure = exc
        rep['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        if isinstance(failure, push_rx.ListenerUnsettled):
            rep['cleanup_error'] = 'not attempted: LISTEN83 completion is uncertain'
        else:
            try:
                set_words(p, at, [('lv_push', 0)])
                after = ispl.read_cap(p, at)
                rep['after'] = {k: after[k] for k in FIELDS}
                rep['cleanup_ok'] = after['lv_push'] == 0
                if not rep['cleanup_ok']:
                    raise RuntimeError('sampler did not disable')
            except BaseException as exc:
                cleanup_failure = exc
                rep['cleanup_error'] = f'{type(exc).__name__}: {exc}'
        if not failure and not cleanup_failure:
            stats, end = rep['stats'], rep['end']
            rep['ok'] = (end['reason'] in ('idle', 'full', 'deadline') and
                         stats['images'] == count and
                         not any(stats[k] for k in ('skipped_bytes', 'resyncs', 'torn', 'seq_gaps', 'leftover')) and
                         after['lv_n_sent'] - before['lv_n_sent'] == count and
                         all(after[k] == before[k] for k in ('lv_n_skip', 'lv_n_bad', 'lv_n_err')))
        else:
            rep['ok'] = False
        (out / 'lvpush.json').write_text(json.dumps(rep, indent=1))
    if failure:
        raise failure
    if cleanup_failure:
        raise cleanup_failure
    if not rep['ok']:
        raise RuntimeError(f'LV trial incomplete; inspect {out / "lvpush.json"}')
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=pathlib.Path)
    ap.add_argument('--every-ms', type=int, default=250)
    ap.add_argument('--count', type=int, default=8)
    ap.add_argument('--quiet-ms', type=int, default=1000)
    a = ap.parse_args()
    rep = capture(a.out, a.every_ms, a.count, a.quiet_ms)
    print(json.dumps({k: rep[k] for k in ('ok', 'end', 'stats', 'cleanup_ok', 'after')}))


if __name__ == '__main__':
    main()
