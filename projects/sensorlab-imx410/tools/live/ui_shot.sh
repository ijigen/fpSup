#!/bin/zsh
# ui_shot.sh N [tag] -- take one screenshot and fetch it BY NUMBER (SS__N.JPG), never from a `dir` listing
# (the listing is truncated: live-v1 "no screenshot" was SS__2577 vs 2763).  N = the next number (last one + 1).
# Never during recording or playback (no USB then).  Output: /tmp/fp_ui/<time>-<tag>-SS<N>.jpg
set -e
N=$1; TAG=${2:-shot}
[[ -z $N ]] && { echo "usage: ui_shot.sh N [tag]"; exit 2; }
SH=/Users/dido/Developer.localized/SIGMAfp_re/fpSup/fp_usb_shell
NAME=$(printf 'SS__%04d.JPG' $N); OUT=/tmp/fp_ui/$(date +%H%M%S)-$TAG-SS$(printf %04d $N).jpg
mkdir -p /tmp/fp_ui
$SH/host/fpsh key CAPTUREON >/dev/null; $SH/host/fpsh key CAPTUREOFF >/dev/null
# getfile without --size looks the file up in `dir` (truncated: never found) -> ask with a size bound, read the real
# length from its reply, then fetch exactly that (v1-live 10-30 shot.sh)
for i in {1..12}; do
  sleep 1.5
  L=$(cd $SH && python3 -B getfile.py "\\DCIM\\100SIGMA\\$NAME" /tmp/fp_ui/probe.jpg --size 600000 2>&1 | sed -n 's/.*file length is \([0-9]*\).*/\1/p')
  [[ -z $L ]] && continue
  if (cd $SH && python3 -B getfile.py "\\DCIM\\100SIGMA\\$NAME" $OUT --size $L >/dev/null 2>&1) && [[ -s $OUT ]]; then echo $OUT; exit 0; fi
done
echo "SS $N not readable after 18 s (wrong number? check the last SS on the card by number, not by dir)"; exit 1
