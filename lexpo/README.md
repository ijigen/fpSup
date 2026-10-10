# LExpo — shutter speeds past 30 s

A Loader v3 sup. In M and S modes the shutter-speed dial offers 40" to 500"(1/3-stop ladder: 40/50/60/80/100/125/160/200/250/320/400/500 s) instead of
stopping at 30". One word patched, plus a one-shot live-view hook that runs the camera's own
picker refresh (rebuild + list-changed event) on the first live-view frame.
Details:
[`projects/lexpo-sup.md`](../projects/lexpo-sup.md).

Build the sup:

    python3 -B lexpo/build_v3_lexpo.py --out /some/empty/dir          # 30LEXPO.BIN

Build a standalone test card (AutoRun.txt + fpSup/ with loader, shell, sup):

    python3 -B lexpo/build_v3_lexpo.py --out /some/empty/dir --card

Run the emulated tests (needs unicorn and the reference image at
`<repo>/../out/MAIN_c0000000.bin`):

    cd fpSup/lexpo && python3 -B -m unittest test_v3_lexpo

Follow [`SUP_BUILD_RULES.en.md`](../SUP_BUILD_RULES.en.md) for builds; notify
the user before camera testing and obtain authorization for that run.
