import sys, pathlib, subprocess, tempfile, hashlib
sys.path.insert(0, '/Users/dido/Developer.localized/SIGMAfp_re/codex')
from build_stage5_autorun import extract_and_relocate, words
HERE = pathlib.Path('/Users/dido/Developer.localized/SIGMAfp_re/codex/fpshell_tool')
LOAD=0xC072E000; STATE=0xC072F000; HOOK=0xC00D0794

# 1) assemble + extract new worker
with tempfile.TemporaryDirectory() as d:
    obj=pathlib.Path(d)/'w.o'
    r=subprocess.run(['clang','-target','armv7-none-eabi','-c',str(HERE/'camera/shell_rw_worker.S'),'-o',str(obj)],capture_output=True,text=True)
    if r.returncode: sys.stderr.write(r.stderr); sys.exit(1)
    code=extract_and_relocate(obj)
w=words(code)
print(f"worker: {len(code)}B, {len(w)} words, end=0x{LOAD+len(code):08X} (STATE=0x{STATE:08X})")
assert LOAD+len(code) <= STATE, "OVERFLOW STATE!"

# 2) read c32 baseline (1-indexed lines)
base=(HERE/'dist/AutoRun.c32-baseline-d9c5c9db.txt').read_text().splitlines()
L=lambda n: base[n-1]  # 1-indexed
# validate anchors from recipe
def chk(n,sub,label):
    assert sub in L(n), f"ANCHOR FAIL line {n} ({label}): expected '{sub}' got '{L(n)[:60]}'"
    print(f"  anchor L{n} OK: {label}")
chk(700,"0xC00D0794","gyro hook")
chk(734,"ctrl sleep 30000","30s")
chk(710,"0xC04DC618","builder hook install")
chk(792,"0xC072F010 0x00000001","GO set")
chk(785,"echo","echo trigger")
chk(668,"0xC072F000","STATE init start")
chk(9,"0xC072723C","builder handler start")
chk(725,"0xC31E38C8","ctx4 config")
# region G (old worker) anchors

# 3) gyro hook BL via formula (proven)
act = 0xEB000000 | (((LOAD-(HOOK+8))>>2)&0xFFFFFF)
print(f"gyro hook BL 0xC00D0794->0x{LOAD:08X} = 0x{act:08X}")

# 4) build output: keep/remove/replace by recipe
KEEP_RANGES=[(1,6),(9,56),(668,699),(703,703),(713,721),(725,730),(741,741),(793,794)]
# region G replaced; gyro hook retargeted; builder hook (710) kept but must be LAST
worker_lines=["# === Claude swap: new gated+shell-forward worker @0x%08X (STATE 0x%08X) ==="%(LOAD,STATE)]
worker_lines+=[f"mem set 0x{LOAD+i*4:08X} 0x{x:08X}" for i,x in enumerate(w)]

out=[]
def emit_keep(a,b):
    for n in range(a,b+1): out.append(L(n))
# assemble in order: preamble+builder handler+STATE, worker code, memmgr buf, ctx config, gyro hook, builder hook LAST, tail
emit_keep(1,6)                 # display preamble
emit_keep(9,56)                # builder handler code+literals (enumeration)
out.append("")
out+=worker_lines              # NEW worker @0xC072E000 (replaces region G 321-667)
out.append("")
emit_keep(668,699)             # STATE zero-init
out.append(L(703))             # memmgr bufmem get (BUF_PTR)
emit_keep(725,730)             # ctx4/ctx5 config
out.append(L(741))             # ctx4 mode=2 restore
out.append(f"# gyro one-shot hook -> new cave_entry@0x{LOAD:08X}")
out.append(f"mem set 0x{HOOK:08X} 0x{act:08X}")
out.append(f"# builder hook install LAST (enumeration)")
out.append(L(710))             # builder hook 0xC04DC618 (LAST)
emit_keep(713,721)             # display cues + READY save (diag)
emit_keep(793,794)             # host window + WORKER.BIN save

text='\n'.join(out)+'\n'
dest=HERE/'dist/AutoRun.swap-gated-shell.txt'
dest.write_text(text)
print(f"\nWROTE {dest.name}: {len(out)} lines SHA={hashlib.sha256(text.encode()).hexdigest()[:16]}")
print("worker mem-set lines:", sum(1 for l in out if l.startswith('mem set 0xC072E0') or l.startswith('mem set 0xC072E1') or (l.startswith('mem set 0xC072E') and int(l.split()[2],16)!=0)))
# sanity: no leftover DEADBEEF / old handlers / 30s / GO-set / echo
for bad in ["DEADBEEF","ctrl sleep 30000","0xC072F010 0x00000001","0xC30257B0","0xC0BAC2","0xC072DF"]:
    hits=[i for i,l in enumerate(out) if bad in l]
    print(f"  leftover '{bad}': {len(hits)} (should be 0)")
