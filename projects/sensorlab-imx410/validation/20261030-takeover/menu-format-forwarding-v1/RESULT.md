# Private format refresh candidate (offline)

The original MV_RecordingFormat controller registers callback C057A598 at C057A448 (name C0D1972C). Subscription C05D9EB8 has one descriptor+0x18 slot: a second subscriber returns 2 and preserves its owner. The previous Python fixture incorrectly allowed multiple subscribers; the corrected fixture rejects the old implementation (native-callback-red.log).

The new native page change events on B2_5 and MainB2 send SLM_Refresh=-1 then 1. Only that private variable is subscribed. Its positive callback refreshes models/locks; it never applies settings. The original format controller remains installed and executes before the declared page-event model. Format actions are decoded from the composed bytes loaded from the compiled sup, not substituted by hard-coded test actions.

Validation: 8 runtime cases; 5 compiled mutants caught after successful compilation; 10 page structure cases; 7 page mutants caught; 3 actual ARM FPUI/native parser cases. Every check passed. Registry/modelCSV and GUI event scheduling remain declared Python models; actual GUI rendering/scheduling requires camera validation. No camera/USB/card access was made by this work.

Default candidate: 181168 bytes; SHA-256 9be786babffa9db501bee5c75f252d4f5c1e63226fbb0de305e228d7e607e552. Compared with the previous default, +652 bytes. Settings schema unchanged; record/state/DMA offsets move with the image. It contains a blank default settings record and must not replace a saved-settings deployment build.

The observed live ready=1, result=0, updates=11 excludes a first-initialization failure in that trial. The subscription conflict is a separate proven defect, not proof of a camera crash or of the cause of an earlier transport timeout.
