"""The firmware words the AutoRun changes, on their own.

They used to live in build_autorun.py, which runs when imported -- so a
script that wanted only this list rebuilt AutoRun.txt as a side effect, in
whichever mode was the default. That happened twice in one evening, once
replacing a loader build with a classic one nobody asked for.
"""

PATCHES = [
    (0xC0CF3740, 0xFFFFFF03,
     "PTP interface template: {bNumEndpoints, class, subclass, protocol}",
     "03/06/01/01 -> 03/ff/ff/ff.  Lengths and the endpoint set are untouched;",
     "this only stops the host's PTP stack from claiming interface 0 before the",
     "shell daemon can."),
    (0xC0CF3780, 0x02830507, "EP 0x83, SuperSpeed: interrupt -> bulk"),
    (0xC0CF3784, 0x00000400, "EP 0x83, SuperSpeed: wMaxPacketSize 64 -> 1024, bInterval 11 -> 0"),
    (0xC0CF3758, 0x00033006, "its SuperSpeed companion: bMaxBurst 0 -> 3"),
    (0xC0CF375C, 0x00000000, "its SuperSpeed companion: wBytesPerInterval 64 -> 0"),
    (0xC0CF3798, 0x02830507, "EP 0x83, full speed: interrupt -> bulk"),
    (0xC0CF379C, 0x00000040, "EP 0x83, full speed: bInterval 100 -> 0"),
]

SCREEN = [
    (0xC0BB1208, 0xFFFFF8B2, "text colour"),
    (0xC03E46A0, 0xE3A05078, "mov r5,#120 — x, clear of the battery indicator"),
    (0xC03E4698, 0xE3A08010, "mov r8,#16  — y"),
]

BAR_WIDTH = 8
