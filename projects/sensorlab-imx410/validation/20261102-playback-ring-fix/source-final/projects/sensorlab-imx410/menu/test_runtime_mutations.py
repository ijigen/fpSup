"""Strict compiled mutants for high-risk menu event contracts (offline only)."""
import io
import pathlib
import tempfile
import unittest
import test_runtime as T

HERE=pathlib.Path(__file__).resolve().parent
MUTANTS=(
    ('request survives return to menu','if (st->menu.ready) *slm_request() = 0;','(void)st;',
     'test_custom_reselection_queues_open_and_recording_refuses'),
    ('recording guard omitted','row >= m->count[k] || busy() ||','row >= m->count[k] ||',
     'test_recording_rejects_confirmed_preset_before_state_changes'),
    ('self updates subscribed instead of confirmation','(uintptr_t)SLM_PICK[k], (uintptr_t)slm_changed',
     '(uintptr_t)SLM_VALUE[k], (uintptr_t)slm_changed','test_native_models_private_confirm_and_silent_sync'),
    ('private refresh pulse ignored',
     'if (W(d + 8u) == 1u && st->menu.ready) slm_publish(st, busy() || slm_format_locked() || st->menu.result);',
     '(void)d; (void)st;', 'test_format_notification_unlocks_same_page_without_applying_settings'),
    # v0.7.1test (live v1 item 3 froze the camera): nothing but recording inside the popup's change event
    ('menu pick pushes synchronously (v0.7.0test)','    m->owed++;\n',
     '    m->owed++;\n    sq_push(st);\n    ap_idle(st->ap_mem);\n    slm_sync(st);\n',
     'test_confirm_event_only_records_and_leave_applies'),
    ('menu pick commits in the event','    m->owed++;\n','    m->owed++;\n    sq_push(st);\n',
     'test_confirm_event_only_records_and_leave_applies'),
    ('menu pick rewrites the models in the event','    m->owed++;\n','    m->owed++;\n    slm_sync(st); m->owed = 1;\n',
     'test_confirm_event_only_records_and_leave_applies'),
    ('menu pick never applied at leave','    m->owed = 0;                                      /* the rows',
     '    m->owed = 1;                                      /* the rows',
     'test_confirm_event_only_records_and_leave_applies'),
    ('format event rewrites the models',
     'if (W(d + 8u) == 1u && st->menu.ready) slm_publish(st, busy() || slm_format_locked() || st->menu.result);',
     'if (W(d + 8u) == 1u) slm_sync(st);', 'test_format_notification_unlocks_same_page_without_applying_settings'),
    ('stale row after an earlier pick not checked','if (m->owed && !slm_row_valid(st, k, &r))',
     'if (0 && !slm_row_valid(st, k, &r))','test_stale_row_after_an_earlier_pick_is_checked'),
    ('native format callback slot claimed','(uintptr_t)"SLM_Refresh", (uintptr_t)slm_format_changed',
     '(uintptr_t)"MV_RecordingFormat", (uintptr_t)slm_format_changed',
     'test_format_notification_unlocks_same_page_without_applying_settings'),
    ('FPS CUSTOM opens on the FPS tile, not FINE','k == 2u ? QSC_OPEN_SUB_AT(0) : QSC_OPEN_SUB',
     'k == 2u ? QSC_OPEN_SUB : QSC_OPEN_SUB','test_fps_custom_opens_the_fps_sub_qs_on_fine'),
    ('FPS CUSTOM still asks for fine mode','k == 2u ? QSC_OPEN_SUB_AT(0) : QSC_OPEN_SUB',
     'k == 2u ? QSC_OPEN_FINE : QSC_OPEN_SUB','test_fps_custom_opens_the_fps_sub_qs_on_fine'),
    ('first-MENU setup builds the models twice','    slm_publish(st, busy() || slm_format_locked());\n    st->lt[14]',
     '    slm_sync(st);\n    st->lt[14]','test_first_layout_writes_each_native_model_once_and_times_leave'),
    ('first leave times not kept','    if (!st->lt[7]) {','    if (0) {',
     'test_first_layout_writes_each_native_model_once_and_times_leave','slqs.c'),
    # v0.7.2test (live2 SS2784): a 4-digit row text is a .nloc string id (1000 = Off)
    ('4-digit FPS row text sent as a string id','    if (n != 4u || t[n]) return t;\n','    return t;\n',
     'test_native_models_private_confirm_and_silent_sync'),
    ('pause not honoured','    if (st->push_pause) { st->lt[15]++; return; }','    if (st->push_pause) { st->lt[15]++; }',
     'test_pause_keeps_stock_across_layouts','slqs.c'),
)

@T.S.SKIP
class Mutations(unittest.TestCase):
    def test_each_compiled_mutant_fails_its_contract_assertion(self):
        original=T.S.BS.SOURCE
        source=original.read_text();runtime=(HERE/'slm_runtime.h').read_text()
        try:
            for label,old,new,test,*where in MUTANTS:
                with self.subTest(label=label), tempfile.TemporaryDirectory(prefix='slm-mutant-') as td:
                    in_c=where==['slqs.c']
                    self.assertEqual((source if in_c else runtime).count(old),1)
                    path=pathlib.Path(td)
                    (path/'slqs.c').write_text(source.replace(old,new,1) if in_c else source)
                    (path/'slm_runtime.h').write_text(runtime if in_c else runtime.replace(old,new,1))
                    T.S.BS.SOURCE=path/'slqs.c';T.S._built.clear()
                    T.S.blob() # Compilation failures never count as detection.
                    capture=io.StringIO()
                    cls=T.MenuBridge if hasattr(T.MenuBridge,test) else T.FirstMenu
                    r=unittest.TextTestRunner(stream=capture).run(cls(test))
                    self.assertFalse(r.errors,capture.getvalue())
                    self.assertFalse(r.skipped,capture.getvalue())
                    self.assertGreaterEqual(len(r.failures),1,capture.getvalue())   # one per subTest
                    print('caught compiled mutant:',label,flush=True)
        finally:
            T.S.BS.SOURCE=original;T.S._built.clear()

if __name__=='__main__':unittest.main()
