"""Offline index of the fp Ver.5.02 main image (ARM-mode code only).

Builds, once, a cache of constant references (LDR literal, MOVW/MOVT pairs,
ADR) and direct calls (BL/BLX imm), then answers queries:

    python3 fwidx.py str <regex>          strings matching regex + who loads them
    python3 fwidx.py refs <hex>           instructions that materialise a constant
    python3 fwidx.py callers <hex>        BL/BLX sites targeting a function
    python3 fwidx.py func <hex>           function start containing an address
    python3 fwidx.py dis <hex> [n]        disassemble from address (n insns)
    python3 fwidx.py fdis <hex>           disassemble whole function (to next push)
    python3 fwidx.py calls <hex>          direct callees of the function at hex

Thumb code is not decoded; treat "no refs" as "no ARM-mode refs".
"""
import os
import re
import sys

import numpy as np

BASE = 0xC0000000
CODE_END = 0xC0724000
IMAGE = os.environ.get(
    "FP_MAIN", os.path.join(os.path.dirname(__file__), "../../../../out/MAIN_c0000000.bin"))
CACHE = os.environ.get("FP_IDX_CACHE", "/tmp/precap_fwidx.npz")

_img = None


def image():
    global _img
    if _img is None:
        with open(IMAGE, "rb") as fh:
            _img = fh.read()
    return _img


def u32(addr):
    off = addr - BASE
    return int.from_bytes(image()[off:off + 4], "little")


def cstr(addr, limit=200):
    off = addr - BASE
    end = image().find(b"\0", off, off + limit)
    return image()[off:end if end >= 0 else off + limit].decode("latin1")


def build():
    words = np.frombuffer(image()[:CODE_END - BASE], dtype="<u4").astype(np.int64)
    pcs = BASE + np.arange(len(words), dtype=np.int64) * 4
    cond_ok = (words >> 28) != 0xF

    # BL imm (cond != 1111) and BLX imm (1111101H)
    imm24 = words & 0xFFFFFF
    simm = np.where(imm24 & 0x800000, imm24 - 0x1000000, imm24) << 2
    is_bl = cond_ok & ((words & 0x0F000000) == 0x0B000000)
    is_blx = (words & 0xFE000000) == 0xFA000000
    tgt = pcs + 8 + simm + np.where(is_blx, ((words >> 24) & 1) * 2 + 1, 0)
    call_mask = is_bl | is_blx
    calls_src, calls_dst = pcs[call_mask], tgt[call_mask]

    ref_src, ref_val, ref_kind = [], [], []

    # LDR Rt,[PC,#+-imm12]
    is_ldrlit = cond_ok & ((words & 0x0F7F0000) == 0x051F0000)
    up = (words >> 23) & 1
    imm12 = words & 0xFFF
    lit_addr = pcs + 8 + np.where(up == 1, imm12, -imm12)
    m = is_ldrlit & (lit_addr >= BASE) & (lit_addr < BASE + len(image()) - 4)
    img_words = np.frombuffer(image()[:len(image()) // 4 * 4], dtype="<u4")
    vals = img_words[((lit_addr[m] - BASE) // 4).astype(np.int64)].astype(np.int64)
    ref_src.append(pcs[m]); ref_val.append(vals); ref_kind.append(np.full(m.sum(), 1))

    # ADR (ADD/SUB Rd, PC, #rot)
    for opc, sign in ((0x028F0000, 1), (0x024F0000, -1)):
        is_adr = cond_ok & ((words & 0x0FFF0000) == opc)
        rot = ((words >> 8) & 0xF) * 2
        imm8 = words & 0xFF
        val = ((imm8 >> rot) | (imm8 << (32 - rot))) & 0xFFFFFFFF
        val = np.where(rot == 0, imm8, val)
        ref_src.append(pcs[is_adr]); ref_val.append(pcs[is_adr] + 8 + sign * val[is_adr])
        ref_kind.append(np.full(is_adr.sum(), 2))

    # MOVW/MOVT pairs: match MOVT to the nearest preceding MOVW on same Rd (<=16 insns)
    is_movw = cond_ok & ((words & 0x0FF00000) == 0x03000000)
    is_movt = cond_ok & ((words & 0x0FF00000) == 0x03400000)
    imm16 = ((words >> 4) & 0xF000) | (words & 0xFFF)
    rd = (words >> 12) & 0xF
    movw_idx = np.nonzero(is_movw)[0]
    movt_idx = np.nonzero(is_movt)[0]
    pair_src, pair_val = [], []
    last = {}
    wi = 0
    for ti in movt_idx:
        while wi < len(movw_idx) and movw_idx[wi] < ti:
            last[int(rd[movw_idx[wi]])] = int(movw_idx[wi])
            wi += 1
        r = int(rd[ti])
        w = last.get(r)
        if w is not None and ti - w <= 16:
            pair_src.append(pcs[w]); pair_val.append(int(imm16[w]) | (int(imm16[ti]) << 16))
    ref_src.append(np.array(pair_src, dtype=np.int64))
    ref_val.append(np.array(pair_val, dtype=np.int64))
    ref_kind.append(np.full(len(pair_src), 3))

    # function starts: STMDB sp!, {..., lr}  /  push {lr} single (STR lr,[sp,#-4]!)
    is_push = ((words & 0xFFFF4000) == 0xE92D4000) | (words == 0xE52DE004)
    np.savez_compressed(
        CACHE,
        calls_src=calls_src, calls_dst=calls_dst,
        ref_src=np.concatenate(ref_src), ref_val=np.concatenate(ref_val),
        ref_kind=np.concatenate(ref_kind),
        push=pcs[is_push])


def idx():
    if not os.path.exists(CACHE) or os.path.getmtime(CACHE) < os.path.getmtime(__file__):
        build()
    return np.load(CACHE)


def func_start(addr):
    push = idx()["push"]
    i = np.searchsorted(push, addr, side="right") - 1
    return int(push[i]) if i >= 0 else None


def func_end(start):
    push = idx()["push"]
    i = np.searchsorted(push, start, side="right")
    return int(push[i]) if i < len(push) else start + 0x400


def refs(value):
    d = idx()
    m = d["ref_val"] == value
    return sorted(int(x) for x in d["ref_src"][m])


def callers(target):
    d = idx()
    return sorted(int(x) for x in d["calls_src"][d["calls_dst"] == target])


def callees(start):
    d = idx()
    end = func_end(start)
    m = (d["calls_src"] >= start) & (d["calls_src"] < end)
    return sorted(set(int(x) for x in d["calls_dst"][m]))


def dis(addr, count=40, thumb=False):
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB if thumb else capstone.CS_MODE_ARM)
    off = addr - BASE
    lines = []
    for ins in md.disasm(image()[off:off + count * 4], addr):
        note = ""
        if ins.mnemonic.startswith("ldr") and "[pc, #" in ins.op_str:
            mt = re.search(r"\[pc, #(-?0x[0-9a-f]+|-?\d+)\]", ins.op_str)
            if mt:
                lit = ins.address + 8 + int(mt.group(1), 0)
                val = u32(lit)
                note = f"  ; ={val:#010x}"
                if BASE <= val < BASE + len(image()):
                    s = cstr(val, 60)
                    if len(s) >= 4 and s.isprintable():
                        note += f' "{s}"'
        lines.append(f"{ins.address:08x}  {ins.mnemonic:8s} {ins.op_str}{note}")
        if len(lines) >= count:
            break
    return lines


def data_refs(value):
    """Aligned 32-bit words anywhere in the image equal to value."""
    words = np.frombuffer(image()[:len(image()) // 4 * 4], dtype="<u4")
    return [BASE + int(i) * 4 for i in np.nonzero(words == value)[0]]


def vtables_of(class_name):
    """Itanium RTTI: name <- typeinfo(+4) <- vtable(+4 = typeinfo slot)."""
    out = []
    for name_addr, s in strings("^(\\d+)?" + re.escape(class_name) + "$"):
        name_ptr = name_addr
        for ti_slot in data_refs(name_ptr):
            typeinfo = ti_slot - 4
            for vt_slot in data_refs(typeinfo):
                if vt_slot < CODE_END:
                    continue
                out.append((s, typeinfo, vt_slot + 4))
    return out


def strings(regex):
    pat = re.compile(regex.encode())
    for m in re.finditer(rb"[\x20-\x7e]{4,}", image()):
        if pat.search(m.group()):
            yield BASE + m.start(), m.group().decode()


def main(argv):
    cmd, arg = argv[1], argv[2] if len(argv) > 2 else None
    if cmd == "str":
        for addr, s in strings(arg):
            rs = refs(addr)
            fs = sorted(set(func_start(r) for r in rs))
            print(f"{addr:08x} {s[:90]!r}  refs={[hex(r) for r in rs][:6]} funcs={[hex(f) for f in fs if f][:6]}")
    elif cmd == "refs":
        for r in refs(int(arg, 16)):
            print(f"{r:08x}  in func {func_start(r):#010x}")
    elif cmd == "callers":
        for c in callers(int(arg, 16)):
            print(f"{c:08x}  in func {func_start(c):#010x}")
    elif cmd == "func":
        s = func_start(int(arg, 16))
        print(f"{s:#010x} .. {func_end(s):#010x}")
    elif cmd == "dis":
        print("\n".join(dis(int(arg, 16), int(argv[3]) if len(argv) > 3 else 40)))
    elif cmd == "fdis":
        s = int(arg, 16)
        n = (func_end(s) - s) // 4
        print("\n".join(dis(s, min(n, 600))))
    elif cmd == "dref":
        for r in data_refs(int(arg, 16)):
            print(f"{r:08x}")
    elif cmd == "vt":
        n = int(argv[3]) if len(argv) > 3 else 24
        for name, ti, vt in vtables_of(arg):
            print(f"{name}: typeinfo {ti:#010x} vtable(fn0) {vt:#010x}")
            for k in range(n):
                fn = u32(vt + 4 * k)
                if not (BASE <= fn < CODE_END):
                    break
                print(f"   +{4 * k:#04x}  {fn:#010x}")
    elif cmd == "calls":
        for c in callees(int(arg, 16)):
            print(f"{c:#010x}")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
