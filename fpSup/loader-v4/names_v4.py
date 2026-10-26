"""The v4 sups' names on the card (the user 2026-10-25): each one's display name
(its header's, SupManager's and the fpSup page row's), its file base and its
version.  The card file is <base>_v<version>.BIN -- the version rides on the
file name; the core loads the newest of one name, SupManager shows
"<display> (<version>)" (sloader4.c cand_cmp, supmgr.c label).

Every builder and the merge page take the names from here.  SUPMGR.BIN,
LOADER.BIN, UI\\*.BIN and the data folders (RESCUS\\, LUT\\) keep their names."""

# sup_id: (display name, file base, version).  2026-10-25 (the user): the last v3
# release's, "test" dropped; the last digit +1 where v4 changed the code (the
# byte-identical ports -- Unlock Writer, Stop-FX, Early Flush, USB-Shell -- keep theirs)
SUPS = {
    'BKLT': ('LCD Backlight', 'Backlight', '0.1.0test'),
    'RCUS': ('RES-Custom', 'RES-Custom', '0.1.5'),
    'LOSS': ('Lossless', 'Lossless', '0.3.1'),
    'ULWR': ('Unlock Writer', 'UnlockWriter', '0.1.0test'),
    'STFX': ('Stop-FX', 'Stop-FX', '0.1.0'),
    'GYR2': ('Gyro2', 'Gyro2', '0.2.1'),   # last release v0.2.0 (build 6, on main's releases/)
    'RAWV': ('RAW-View', 'RAW-View', '0.3.1'),
    'FLIP': ('Screen Flip', 'ScreenFlip', '0.1.1'),
    'DSQZ': ('Desqueeze', 'Desqueeze', '0.1.5'),
    'TAPZ': ('Tap To Zoom', 'TapToZoom', '0.1.1'),
    'SHEL': ('USB-Shell', 'USB-Shell', '3.4.0'),
    'FCAP': ('Early Flush', 'EarlyFlush', '0.1.0'),
}

DISPLAY_MAX = 23      # sloader4.c struct sup disp[24]
FILE_MAX = 39         # sloader4.c NAME_MAX - 1


def display(sup_id):
    return SUPS[sup_id][0]


def version(sup_id):
    return SUPS[sup_id][2]


def file_name(sup_id):
    """'Gyro2_v0.1.0.BIN'."""
    _d, base, ver = SUPS[sup_id]
    return f'{base}_v{ver}.BIN'


for _k, (_d, _b, _v) in SUPS.items():
    assert len(_d) <= DISPLAY_MAX and len(file_name(_k)) <= FILE_MAX, _k
