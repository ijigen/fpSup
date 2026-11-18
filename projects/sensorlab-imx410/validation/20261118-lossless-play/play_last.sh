#!/bin/zsh
# Play the newest clip in the camera with keys only: PLAY (enter playback), OK (play),
# NO USB for $1 seconds (default 15), PLAY (leave), wait, ping.  Nothing is read while in playback.
# A key whose reply does not come is not sent again (2026-11-18: around playback the replies of
# delivered keys time out); every call is given 5 s.
F=/Users/dido/Developer.localized/SIGMAfp_re/fpSup/fp_usb_shell/host/fpsh
call() { $F "$@" & local p=$!; ( sleep 5; kill $p 2>/dev/null ) & local w=$!; wait $p 2>/dev/null; kill $w 2>/dev/null; }
$F ping || exit 1
$F status get is_recording | grep -q -- '-> 0' || { echo recording; exit 1; }
call key PLAYON; sleep 0.15; call key PLAYOFF; sleep 6
call key OKON; sleep 0.15; call key OKOFF; sleep ${1:-15}
call key PLAYON; sleep 0.15; call key PLAYOFF; sleep 15
for n in 1 2 3 4; do $F ping && break; sleep 5; done
python3 -B /Users/dido/Developer.localized/SIGMAfp_re/fpSup/fp_usb_shell/ui_drive.py where 2>&1 | head -1
