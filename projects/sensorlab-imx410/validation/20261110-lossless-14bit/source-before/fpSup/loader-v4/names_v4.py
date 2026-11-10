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
    'BKLT': ('LCD Backlight', 'Backlight', '0.1.1test'),
    'RCUS': ('RES-Custom', 'RES-Custom', '0.1.6'),
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
    # 2026-11-07 (Bei): renamed and restarted at 0.0.1test for the first merge-page release; content =
    # SensorLab-IMX410 v0.7.39test / QS Container v0.3.8 (only the header name changes).  QSCT keeps its sup_id.
    # 0.0.2test candidates (2026-11-07): QS FPS AEL = in-place fine again (QS-Share API 9: fine + sub on one function)
    # SL41 0.0.3test (2026-11-08): CinemaDNG 8 / 10-bit (stock BIT row; needs QS-Share 0.0.2test as before)
    # SL41 0.0.4test (2026-11-08): the QS FORMAT dial picks the stock bit depth (the menu BIT row's setter)
    'SL41': ('Sensor Lab-IMX410', 'SensorLab-IMX410', '0.0.4test'),
    'QSCT': ('QS-Share', 'QS-Share', '0.0.2test'),
    # 2026-11-07 (Bei): the native COLOR list's added rows, shared by LUT / RAW-View (fpSup/colshare/DESIGN.md)
    'COLS': ('COL-Share', 'COL-Share', '0.0.1test'),
    # 2026-11-08 (Bei): Andy_hal9000's rear-wheel decoder v6 (fpSup/dialfix/reference/v6); the v1-based
    # DIALFIX.BIN was never released.  "test" until the sup form has been on the camera.
    'DIAL': ('Dial Fix', 'DialFix', '0.2.0test'),
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
