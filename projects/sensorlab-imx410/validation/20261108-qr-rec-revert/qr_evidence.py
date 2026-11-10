import sys; sys.path.insert(0, '.')
import test_qrscan as T, test_slqs as S
t = T.RecAfterScan()
for model in (False, True):
    c = T.boot(descriptor=True); c.answer = {'stock_parse': 1}
    fa, fb = t.pair(c)
    T.restore(c, fa, 2); c.layout()
    a = S.ap_status(c)
    print('model_session', model)
    print(' A committed: result %d carrier %d FR %d rec_pick %s' % (a['result'], a['carrier'], c.w(S.FR_WORD), t.rec_pick(c)))
    c.model_session = model
    c.put(T.QRT_OBJ_VT, T.QRT_VT_STOCK); h = T.handler(c, phase=0); T.call_slot(c, 'v72', h); c.put(h + 0x30, 1)
    n0 = S.ap_status(c)['commits']
    T.Page.run_v62(t, c, T.stock_bytes((T.URL + T.pack(fb)).encode()), h=h)
    b = S.ap_status(c)
    print(' after v62 (on page): ap_rc %d commits +%d carrier %d FR %d' % (S.sqt(c, 21) if False else b['result'], b['commits'] - n0, b['carrier'], c.w(S.FR_WORD)))
    T.call_slot(c, 'v73', h)
    print(' after v73 (page exit): FR %d' % c.w(S.FR_WORD))
    n1 = S.ap_status(c)['commits']; p = S.sqt(c, 20)
    c.layout(); c.layout()
    b = S.ap_status(c)
    print(' after QS leave x2: pushes +%d commits +%d result %d owed %d carrier %d FR %d fields==B %s rec_pick %s' % (
        S.sqt(c, 20) - p, b['commits'] - n1, b['result'], b['owed'], b['carrier'], c.w(S.FR_WORD), T.fields_now(c) == fb, t.rec_pick(c)))
