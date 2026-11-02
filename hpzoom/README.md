# HpZoom — half-press magnification for manual lenses

A Loader v3 sup. In MF mode with Auto Magnification OFF: half-press S1 to
magnify, release to unmagnify; the live view is B&W while magnified and
stills stay colour. Details: [`projects/hpzoom-sup.md`](../projects/hpzoom-sup.md).

Build the sup:

    python3 -B hpzoom/build_v3_hpzoom.py --out /some/empty/dir          # 20HPZOOM.BIN
    python3 -B hpzoom/build_v3_hpzoom.py --out /some/empty/dir --no-bw  # 20HPZOMNB.BIN

Build a standalone test card (AutoRun.txt + fpSup/ with loader, shell, sup):

    python3 -B hpzoom/build_v3_hpzoom.py --out /some/empty/dir --card

Run the emulated tests (needs unicorn and the reference image at
`<repo>/../out/MAIN_c0000000.bin`):

    cd fpSup/hpzoom && python3 -B -m unittest test_v3_hpzoom

Follow [`SUP_BUILD_RULES.en.md`](../SUP_BUILD_RULES.en.md) for builds; notify
the user before camera testing and obtain authorization for that run.
