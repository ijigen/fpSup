QS Container v0.3.0 / API 5 — offline implementation, 2026-10-30

qsc.h keeps the API 4 function/table layout and appends open() to qsc_api.
Check api->version >= 5 before accessing it.

open(api, sup_id, name, QSC_OPEN_SUB or QSC_OPEN_FINE) returns 1 when queued,
0 when rejected. It runs on the UI thread and does not change screens. The
last accepted request wins; an invalid request leaves it intact. The request
is consumed once on the QS-only focus callback, after the menu transitions
to QS. Recording, non-CINE and client state locks are checked both when
queueing and consuming. A failed recheck discards the request.

A function absent from the user's eight slots gets a temporary standalone
sub-QS or fine tile. AEL returns to the user's eight slots, focused on tile 1.
A present function returns to its own tile. Leaving the layout closes fine
and sub modes. Pending menu requests survive that transition until QS focus.

QSC_F_REPLACE(12/21/23/25) replaces the stock DC/FORMAT/RES/FPS tile only
while CINE QS is active. The registered function retains its dynamic ID;
only the display variables and focused QS ID are mapped. Settings and saved
stock slots are unchanged. CSV rows for replacement functions are hidden;
other functions, including MB/s, QR and RECIPE, keep their registration IDs
and remain selectable. Duplicate and unsupported replacement IDs are refused.
Existing explicitly assigned dynamic slots still work, using the previous
placeholder/writeback mechanism. There is no replacement on/off switch yet.

Activation uses the proven QS-only qc_guid path, not the unverified layout
identity fields. Any following layout load disables mapping and restores
the slot display variables before the original layout loader runs. A later
native focus refresh is mapped again. Whether the very first frame briefly
shows stock tiles, native asynchronous event timing and touch behavior still
require physical-camera validation. The offline test rig models GUI variable
posts and key dispatch; it executes compiled ARM and the existing firmware
conversion paths, and independently checks the page/key animation bytes.
No camera, USB, card, loader change, installation or deployment was involved.

Run from projects/qs-container:
  python3 -B build_qsct.py --out out-takeover-v030
  python3 -B -m unittest -v test_api5 test_qsct test_qs_page
  python3 -B test_api5.py --mutate

The default full suite has one expected skip for the optional MENU_BACK=1
mode. On this macOS host Unicorn requires the approved offline unsandboxed
runner because sandboxed JIT initialization terminates with SIGILL.

Build: out-takeover-v030/fpSup/QSContainer_v0.3.0.BIN
Metadata: out-takeover-v030/build-0.3.0.json
Evidence: validation/api5-offline-20261030/
The older README.md sections describe earlier versions and live observations.
Their raw state offsets predate the API pointer appended in v0.3.0; use the
computed layout in test_qs_page.py for the current container.
