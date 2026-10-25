"""ISPL capture memory -> records (shared by the host tool and test_card.py).
Fork of projects/imx410-lab/sup/imxl_records.py (sha256 c380e39b...): ix_cap v2,
the block log.

The sink fills the lent chunks front to back with no gaps, so their
concatenation is one stream:  [ix_rec 32 B][bytes of data][pad to 4] ...
ix_rec = magic "IXR1", seq, cl, bytes, ncookie, t_us, copy_us, nseg.
A record's data is exactly what ULWR would have written to the card starting
at cluster `cl`: whole DNG files, each padded to a cluster.
"""
import struct

REC_MAGIC = 0x31525849          # "IXR1"
CAP_MAGIC = 0x4C505349          # "ISPL"
CAP_VERSION = 4
REC = struct.Struct('<8I')
FIELDS = ('magic', 'seq', 'cl', 'bytes', 'ncookie', 't_us', 'copy_us', 'nseg')

# ix_cap, mirrored from ix_wr.h (version 4: + the LV sampler, + CDNG after the stop)
CAP_HEAD = ('magic', 'version', 'mode', 'nchunk')
MAX_CHUNK = 32
HOST = ('keep_first', 'every_us', 'log_addr', 'log_max', 'ctl', 'start_ms', 'rec_ms')
CAP_TAIL = ('ci', 'coff', 'used', 'n_rec', 'n_full', 'n_discard', 'n_sd',
            't_first', 't_last', 'copy_us', 'copy_max_us',
            'n_skip', 'log_n', 't_arm', 't_rec', 't_stop', 'n_press',
            'ctl_line', 'rs_started', 'rs_saved', 'install_at_arm',
            'lv_push', 'lv_every_us', 'lv_lag', 'lv_max',               # host-written
            'lv_t_last', 'lv_n_sent', 'lv_n_skip', 'lv_n_bad', 'lv_n_err', 'lv_last_reg', 'lv_last_addr',
            'cd_go', 'cd_after_ms', 'cd_max',                          # host-written
            'cd_state', 'cd_lo', 'cd_hi', 'cd_found', 'cd_newest_n', 'cd_sent', 'cd_skip', 'cd_us',
            'cd_newest0', 'cd_newest1', 'cd_newest2', 'cd_newest3', 'cd_newest4')   # 20 bytes of DateTime
O_CHUNK = 16
O_HOST = O_CHUNK + 8 * MAX_CHUNK
O_TAIL = O_HOST + 4 * len(HOST)
CAP_BYTES = O_TAIL + 4 * len(CAP_TAIL)
OFF = {k: O_HOST + 4 * i for i, k in enumerate(HOST)} | {k: O_TAIL + 4 * i for i, k in enumerate(CAP_TAIL)}
CTL = {'idle': 0, 'armed': 1, 'rec': 2, 'done': 3, 'fail_start': 4, 'fail_stop': 5}
SH_LINES = {1: 'recstate ena', 2: 'recstate init', 3: 'key MOVON', 4: 'recstate movrecstwai',
            5: 'recstate movsavewai', 6: 'recstate disa'}
LOG = struct.Struct('<4I')                    # ix_logline: seq, t_us, ncookie, bytes
MODES = {'sd': 0, 'capture': 1, 'discard': 2}


def parse_cap(raw):
    """ix_cap bytes -> dict (chunks as a list of (addr, len))."""
    d = dict(zip(CAP_HEAD, struct.unpack_from('<4I', raw, 0)))
    d['chunks'] = [struct.unpack_from('<2I', raw, O_CHUNK + 8 * i) for i in range(MAX_CHUNK)]
    d.update(zip(HOST, struct.unpack_from(f'<{len(HOST)}I', raw, O_HOST)))
    d.update(zip(CAP_TAIL, struct.unpack_from(f'<{len(CAP_TAIL)}I', raw, O_TAIL)))
    return d


def log_lines(raw, n):
    """The block log: [{seq, t_us, ncookie, bytes}] for every block the writer took."""
    return [dict(zip(('seq', 't_us', 'ncookie', 'bytes'), LOG.unpack_from(raw, 16 * i))) for i in range(n)]


def records(stream, used):
    """Yield one dict per record in stream[:used]; raises on a broken chain."""
    pos = 0
    while pos < used:
        if used - pos < REC.size:
            raise ValueError(f'truncated header at {pos}')
        r = dict(zip(FIELDS, REC.unpack_from(stream, pos)))
        if r['magic'] != REC_MAGIC:
            raise ValueError(f'bad magic {r["magic"]:#x} at {pos}')
        start = pos + REC.size
        r['data'] = bytes(stream[start:start + r['bytes']])
        if len(r['data']) != r['bytes']:
            raise ValueError(f'record {r["seq"]} runs past the end')
        pos = start + ((r['bytes'] + 3) & ~3)
        yield r
    if pos != used:
        raise ValueError(f'records end at {pos}, sink says {used}')


def disk_image(recs, heap_lba, spc, sector=512):
    """{byte offset on the medium: data}, as ULWR would have laid it down."""
    return {((r['cl'] - 2) * spc + heap_lba) * sector: r['data'] for r in recs}
