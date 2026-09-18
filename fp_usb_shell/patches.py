"""The firmware words the AutoRun changes, on their own.

They used to live in build_autorun.py, which runs when imported -- so a
script that wanted only this list rebuilt AutoRun.txt as a side effect, in
whichever mode was the default. That happened twice in one evening, once
replacing a loader build with a classic one nobody asked for.
"""

# Two different jobs, and they used to be one list.  The first patch is what
# makes the channel reachable at all: with the interface still declaring itself
# PTP, the host's own PTP stack claims interface 0 before the daemon can, and
# every command comes back LIBUSB_ERROR_ACCESS.  The other six shape EP 0x83
# for hook-push, which only a USB-attached development session does.
#
# A card that carries the shell needs the first and not the other six.  They
# were bundled, and --no-ep-patches dropped all seven, so the first debug card
# anyone tried to talk to could not be talked to (macOS: ptpcamerad had it).
IFACE = [
    (0xC0CF3740, 0xFFFFFF03,
     "PTP interface template: {bNumEndpoints, class, subclass, protocol}",
     "03/06/01/01 -> 03/ff/ff/ff.  Lengths and the endpoint set are untouched;",
     "this only stops the host's PTP stack from claiming interface 0 before the",
     "shell daemon can."),
]

PUSH = [
    (0xC0CF3780, 0x02830507, "EP 0x83, SuperSpeed: interrupt -> bulk"),
    (0xC0CF3784, 0x00000400, "EP 0x83, SuperSpeed: wMaxPacketSize 64 -> 1024, bInterval 11 -> 0"),
    (0xC0CF3758, 0x00033006, "its SuperSpeed companion: bMaxBurst 0 -> 3"),
    (0xC0CF375C, 0x00000000, "its SuperSpeed companion: wBytesPerInterval 64 -> 0"),
    (0xC0CF3798, 0x02830507, "EP 0x83, full speed: interrupt -> bulk"),
    (0xC0CF379C, 0x00000040, "EP 0x83, full speed: bInterval 100 -> 0"),
]


# DRAM self-refresh is what keeps the injection cave alive across a soft power
# off, and the firmware's built-in window is 900 seconds: 0xC00239C8,
# `mov r0, #0x384`, stored to [obj+0x6C] by the SelfRefreshSetting constructor
# at 0xC0023948.
#
# `sys selfStopTime` cannot raise it.  The getter at 0xC0024310 reads the
# configured value into r4 and then throws it away, because 0xC0024358 is a
# hardcoded `mov r0, #0` that makes the "use the configured value" test always
# false.  That reads as a compile-time-disabled feature rather than a bug; the
# dead branch's own ceiling is 0xA8C0 = 43200 s = 12 h.
#
# Patching the constructor's default beats enabling the configured path.  The
# configured value lives in BSS, which the boot zeroes (0xC3000000..0xC38D6FB0),
# so a warm boot that skips the AutoRun would silently fall back to 900 seconds
# -- the exact case this exists to serve.  This is code: it sits in the firmware
# image in DRAM and survives the warm boot it is for.
#
# 0xA800 = 43008 s = 11.95 h, the largest ARM-encodable immediate under the
# firmware's own 43200-second ceiling.
#
# NOT free: self-refresh draws current the whole time the camera is off.  Off
# by default; --retain-ram turns it on.
#
# UNVERIFIED: that 900 s is the power-off retention window at all.  It was read
# statically out of a config the `sys selfConfig` command prints, next to poff /
# eco / sleep.  The cheap check is to leave the camera off past the window and
# see whether the cave survives.  See
# research/firmware/notes/DRAM_SELF_REFRESH_AND_WARM_BOOT.md.
RETAIN = [
    (0xC00239C8, 0xE3A00B2A,
     "SelfRefreshSetting default stop time: mov r0,#0x384 (900 s, 15 min) ->",
     "mov r0,#0xA800 (43008 s, 11.95 h).  Holds DRAM in self-refresh across a",
     "soft power-off for twelve hours instead of fifteen minutes, which is what",
     "lets a warm boot find the cave already loaded."),
]

PATCHES = IFACE + PUSH        # both, for a USB development build

SCREEN = [
    (0xC0BB1208, 0xFFFFF8B2, "text colour"),
    (0xC03E46A0, 0xE3A05078, "mov r5,#120 — x, clear of the battery indicator"),
    (0xC03E4698, 0xE3A08010, "mov r8,#16  — y"),
]

BAR_WIDTH = 8
