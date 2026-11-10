"""Test-only caches for the QS container / SensorLab suites (never used by a builder that writes a BIN).

    cached(name, fn, *args, key=(), subprocesses=False, **kw)

returns fn(*args, **kw), from disk when nothing it depends on changed.  What it depends on is recorded the first time
it runs (a manifest), not declared:

  * every Python module loaded from this repo (their source files);
  * every file the build opened for reading (audit hook 'open'), e.g. out/seg0_c0000000.bin, nbu_sets.json;
  * every clang compile it ran: the exact header set, from the same command re-run with -M (only on a miss);
  * `key`, the arguments, and the environment variables a mutation run uses (a value that is a file: its bytes).

A hit needs every manifest file unchanged: same size and mtime_ns, or else the same bytes (sha256).  A build that ran
any other subprocess (python, node ...) is not stored unless `subprocesses=True` says its inputs are all in `key`.

    SL_TESTCACHE=1        read and write (default)
    SL_TESTCACHE=ro       read only (mutation runs: their builds are one-offs)
    SL_TESTCACHE=refresh  ignore what is stored, rebuild, store (tools/test.py full does this once, before fanning out)
    SL_TESTCACHE=0        off
    SL_TESTCACHE_DIR      where (default projects/sensorlab-imx410/tools/.testcache)

Also: memo(fn) for in-process memoisation, and image_once(path) (the firmware image read once per process).
"""
import functools
import hashlib
import os
import pathlib
import pickle
import shlex
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1].parent
DIR = pathlib.Path(os.environ.get('SL_TESTCACHE_DIR') or ROOT / 'projects' / 'sensorlab-imx410' / 'tools' / '.testcache')
ENV_KEYS = ('SLQS_SRC', 'SLQS_BUILD_SRC', 'SLQS_RUNNER', 'QSCT_SRC', 'QSCT_MUTATE', 'QSCT_QS_MUTATE', 'QSCT_MENU_BACK',
            'AP_SRC', 'SL_ROOT')
VERSION = 1
_TMP = tuple(str(pathlib.Path(p).resolve()) for p in {tempfile.gettempdir(), '/tmp', '/private/tmp', '/var/folders',
                                                        '/private/var/folders'})
_SKIP = tuple({sys.prefix, sys.base_prefix, sys.exec_prefix, os.path.expanduser('~/Library/Python'),
               '/Library/Developer', '/usr', '/System', '/dev'})


def mode():
    return os.environ.get('SL_TESTCACHE', '1')


def _sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def _entry(path):
    st = os.stat(path)
    return (path, st.st_size, st.st_mtime_ns, _sha(path))


def _fresh(entry):
    path, size, mtime, digest = entry
    try:
        st = os.stat(path)
    except OSError:
        return False
    if (st.st_size, st.st_mtime_ns) == (size, mtime):
        return True
    return st.st_size == size and _sha(path) == digest


# --------------------------------------------------------------------------------------------- recording
class _Rec:
    active = None                               # the recording in progress (builds do not nest here)
    seen = set()                                # every file read in this process since this module was imported


# read at import by modules loaded before this one (O.image(), nbu_stock, the camera image): always in a manifest
ALWAYS = [ROOT / 'out' / 'MAIN_c0000000.bin', ROOT / 'out' / 'seg0_c0000000.bin', ROOT / 'research' / 'ui' / 'nbu_sets.json']


def _audit(event, args):
    if event == 'open':
        p, m = args[0], args[1]
        if isinstance(p, (str, bytes, os.PathLike)) and (m is None or ('w' not in str(m) and 'a' not in str(m)
                                                                       and '+' not in str(m) and 'x' not in str(m))):
            p = os.fsdecode(p)
            _Rec.seen.add(p)
            if _Rec.active is not None:
                _Rec.active['opened'].add(p)
        return
    r = _Rec.active
    if r is None:
        return
    if event == 'subprocess.Popen':
        argv = [os.fsdecode(a) for a in (args[1] if isinstance(args[1], (list, tuple)) else shlex.split(args[1]))]
        r['procs'].append((argv, args[2]))


_hooked = []


def _hook():
    if not _hooked:
        sys.addaudithook(_audit)
        _hooked.append(1)


def _clang_deps(argv, cwd):
    """the files a clang compile read: the same command with -M (dependency list, no object)"""
    out, skip = [], False
    for a in argv:
        if skip:
            skip = False
            continue
        if a == '-o':
            skip = True
            continue
        if a in ('-c', '-S'):
            continue
        out.append(a)
    with tempfile.TemporaryDirectory(prefix='tcdep-') as t:
        d = pathlib.Path(t) / 'x.d'
        p = subprocess.run(out + ['-M', '-MF', str(d)], cwd=cwd, capture_output=True, text=True)
        if p.returncode:
            return None
        text = d.read_text().replace('\\\n', ' ')
    files = []
    for line in text.splitlines():
        if ':' in line:
            files += [f.replace('\\ ', ' ') for f in line.split(':', 1)[1].split()]
    return [str(pathlib.Path(cwd or '.', f).resolve()) for f in files]


def _manifest(rec, mods_before):
    paths = set()
    for m in list(sys.modules.values()):
        f = getattr(m, '__file__', None)
        if f and f.endswith('.py') and str(pathlib.Path(f).resolve()).startswith(str(ROOT)):
            paths.add(str(pathlib.Path(f).resolve()))
    for p in rec['opened'] | _Rec.seen | {str(a) for a in ALWAYS}:
        if p.endswith('.pkl') and str(DIR) in p:
            continue
        try:
            rp = str(pathlib.Path(p).resolve())
        except (OSError, RuntimeError):
            continue
        if rp.startswith(_TMP) or rp.startswith(_SKIP) or rp.endswith('.pyc') or not os.path.isfile(rp):
            continue
        paths.add(rp)
    for argv, cwd in rec['procs']:
        exe = os.path.basename(argv[0]) if argv else ''
        if exe.startswith('clang') and any(a in ('-c', '-S') for a in argv):
            deps = _clang_deps(argv, cwd)
            if deps is None:
                return None
            paths.update(d for d in deps if not d.startswith(('/Library/Developer', '/usr/', '/System')))
        elif exe.startswith('clang'):
            continue                              # a link / objcopy-style step: its inputs are our own temp files
        elif not rec['subprocesses']:
            return None                           # an unknown tool: its inputs are not known
    return sorted(_entry(p) for p in paths if os.path.isfile(p))


def _key(name, args, kw, key):
    env = []
    for k in ENV_KEYS:
        v = os.environ.get(k)
        if v is not None:
            env.append((k, v, _sha(v) if os.path.isfile(v) else None))
    raw = repr((VERSION, name, args, sorted(kw.items()), key, env, sys.version_info[:2]))
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def file_key(*paths):
    """(path, sha256) of each file: for `key=` when a builder takes its source from a module attribute"""
    return tuple((str(p), _sha(p) if os.path.isfile(p) else None) for p in paths)


def cached(name, fn, *args, key=(), subprocesses=False, **kw):
    m = mode()
    if m == '0' or _Rec.active is not None:
        return fn(*args, **kw)
    f = DIR / f'{name}-{_key(name, args, kw, key)}.pkl'
    if m != 'refresh' and f.exists():
        try:
            with open(f, 'rb') as fh:
                stored = pickle.load(fh)
            if all(_fresh(e) for e in stored['manifest']):
                return stored['value']
        except Exception:                         # a damaged entry is a miss
            pass
    _hook()
    rec = dict(opened=set(), procs=[], subprocesses=subprocesses)
    before = set(sys.modules)
    _Rec.active = rec
    try:
        value = fn(*args, **kw)
    finally:
        _Rec.active = None
    if m in ('1', 'refresh'):
        man = _manifest(rec, before)
        if man is not None:
            DIR.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=DIR, prefix='.w-')
            try:
                with os.fdopen(fd, 'wb') as fh:
                    pickle.dump(dict(manifest=man, value=value), fh, protocol=pickle.HIGHEST_PROTOCOL)
                os.replace(tmp, f)
            except Exception:
                pathlib.Path(tmp).unlink(missing_ok=True)
                raise
    return value


# --------------------------------------------------------------------------------------------- in-process
def memo(fn):
    """fn memoised on its arguments for this process (deterministic builders called once per camera boot)"""
    if getattr(fn, '_tc_memo', False):
        return fn
    cache = {}

    @functools.wraps(fn)
    def w(*a, **kw):
        k = repr((a, sorted(kw.items())))
        if k not in cache:
            cache[k] = fn(*a, **kw)
        return cache[k]
    w._tc_memo = True
    return w


_PathT = type(pathlib.Path())


class OncePath(_PathT):
    """a Path whose read_bytes() reads the file once per process (the 47 MiB firmware image, per camera boot)"""
    _bytes = {}

    def read_bytes(self):
        k = str(self)
        if k not in OncePath._bytes:
            OncePath._bytes[k] = super().read_bytes()
        return OncePath._bytes[k]


def image_once(path):
    return path if isinstance(path, OncePath) else OncePath(str(path))


# --------------------------------------------------------------------------------------------- emulation caps
EMU_IPS = 10_000_000          # the wall-clock cap assumes at least this many instructions per second (we see 100-300 M)


def emu_start(mu, begin, until, count):
    """mu.emu_start(begin, until, count=count), but by default with a wall-clock cap of count / EMU_IPS seconds instead
    of the instruction counter: unicorn's counter instruments every instruction and makes the QS tests 4-5x slower.
    Code that returns is unaffected (no test call comes near its cap: SL_EMU_LOG lists the ones that stop early).
    SL_EMU_COUNT=1 restores the instruction counter exactly."""
    if os.environ.get('SL_EMU_COUNT') == '1':
        kw = dict(count=count)
    else:
        kw = dict(timeout=max(1, count * 1_000_000 // EMU_IPS))
    try:
        mu.emu_start(begin, until, **kw)
    finally:
        log = os.environ.get('SL_EMU_LOG')
        if log:
            from unicorn.arm_const import UC_ARM_REG_PC
            pc = mu.reg_read(UC_ARM_REG_PC)
            if pc != until & ~1:
                with open(log, 'a') as f:
                    f.write(f'{os.getpid()} begin {begin:#x} until {until:#x} stopped {pc:#x} {kw}\n')


_hook()
