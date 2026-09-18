#!/usr/bin/env python3
"""Host-only static evidence and fixed-width recipe; never produces a deployable page.

Inputs are explicit and hash-pinned. This does not emulate firmware, send events,
connect a camera, or modify the canonical page builder. Capstone is a disassembler.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct

BASE = 0xC0000000
SEG1_BASE = 0xC2EF6E00
SEG0_SHA = "aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622"
SEG1_SHA = "0dcaca8f5441fe4ddc6ed801cb888e325df4e76006e4f53a1c3219809b22ce7b"
DONOR_START, DONOR_END = 0xC216C8B8, 0xC2172BC6
DONOR_SHA = "33eca8104f7ab0630c7544e9769f6daaa7d0bc6c62856805379ea9ef0d70b48b"
POOL, POOL_END = 0xC18C0474, 0xC18EB48C
WIDTH = 320

# Only typed float fields, selected by their native property masks. No searching
# and replacing equal numeric words. Rect width is dimension 2, size width is 0.
GEOMETRY = {
    0xC216D3A7: [(32, 532.0, 704.0, "position.x"), (40, 492.0, 1024.0, "size.w")],
    0xC216DB92: [(44, 492.0, 320.0, "rect.w")],
    0xC21700DD: [(44, 492.0, 320.0, "rect.w")],
    0xC2172574: [(44, 492.0, 320.0, "rect.w")],
    0xC216DD36: [(32, -15.0, 81.0, "position.x")],
    0xC21701CD: [(32, -15.0, 81.0, "position.x")],
    0xC216DD72: [(45, 444.0, 180.0, "rect.w")],
    0xC2170209: [(45, 444.0, 180.0, "rect.w")],
}
CLIPS = {
    0xC216D565: [(0, "position", 0, 704.0), (0, "size", 0, 1024.0)],
    0xC216DBC6: [(1, "rect", 2, 320.0)],
    0xC216DDA7: [(0, "position", 0, 81.0), (1, "rect", 2, 180.0)],
    0xC2170111: [(1, "rect", 2, 320.0)],
    0xC217023E: [(0, "position", 0, 81.0), (1, "rect", 2, 180.0)],
    0xC21725A8: [(1, "rect", 2, 320.0)],
}
REMOVED = (0xC216CF50, 0xC216CF7D)


def check(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def word(data, offset=0):
    check(0 <= offset <= len(data) - 4, "word out of bounds")
    return struct.unpack_from(">I", data, offset)[0]


def slice_va(source, lo, hi):
    check(BASE <= lo <= hi <= BASE + len(source), "VA out of bounds")
    return source[lo - BASE:hi - BASE]


def pool_string(source, offset):
    address = POOL + offset
    check(POOL <= address < POOL_END, "pool reference out of bounds")
    end = source.find(b"\0", address - BASE, POOL_END - BASE)
    check(end >= 0, "unterminated pool string")
    return source[address - BASE:end].decode("utf-8")


def records(source):
    result = {}
    cursor = DONOR_START
    while cursor < DONOR_END:
        size = word(source, cursor - BASE + 4)
        check(size >= 8 and cursor + size <= DONOR_END, "invalid donor record extent")
        result[cursor] = slice_va(source, cursor, cursor + size)
        cursor += size
    check(cursor == DONOR_END, "donor record extent mismatch")
    return result


def decode_clip(source, data):
    check(word(data) == 0x1000A, "not an animation clip")
    cursor, properties = 28, []
    for _ in range(word(data, 12)):
        count, kind, component, name, dimension = struct.unpack_from(">5I", data, cursor)
        check(kind == 1, "fixed-width clip must contain only floats")
        keys = []
        for i in range(count):
            key = cursor + 20 + i * 10
            check(key + 10 <= len(data), "truncated clip key")
            check(data[key] <= 1 and data[key + 1] <= 1, "unknown key tangent flag")
            keys.append({"offset": key + 6, "time": word(data, key + 2),
                         "value": struct.unpack_from(">f", data, key + 6)[0]})
        properties.append({"component": component, "property": pool_string(source, name),
                           "dimension": dimension, "keys": keys})
        cursor += 20 + count * 10
    check(cursor == len(data), "unconsumed clip bytes")
    return properties


def component_counts(source, record_map):
    counts = Counter()
    for data in record_map.values():
        if word(data) in (0x10004, 0x10005, 0x10006, 0x10009, 0x1000A, 0x1000E):
            counts[pool_string(source, word(data, 8))] += 1
    return counts


def fixed_width_recipe(source):
    """Return in-memory recipe only, retaining address-keyed original records.

    It must run before source-address loss. The canonical builder remains
    responsible for ID remapping, private strings, OFF/ON binding, complete page
    headers, record offsets and all deployability gates.
    """
    check(sha(slice_va(source, DONOR_START, DONOR_END)) == DONOR_SHA, "donor fingerprint mismatch")
    original = records(source)
    result = dict(original)
    edits = []
    for address, fields in GEOMETRY.items():
        data = bytearray(result[address])
        for offset, expected, replacement, role in fields:
            old = struct.unpack_from(">f", data, offset)[0]
            check(old == expected, "base geometry source mismatch")
            struct.pack_into(">f", data, offset, replacement)
            edits.append({"address": f"0x{address:08X}", "offset": offset, "role": role,
                          "old": old, "new": replacement})
        result[address] = bytes(data)

    # Keep all group/key allocation counts unchanged; freeze each typed key so
    # accidental future animation of this local group cannot restore stock width.
    clips = []
    for address, expected_properties in CLIPS.items():
        data = bytearray(result[address])
        properties = decode_clip(source, data)
        actual = [(p["component"], p["property"], p["dimension"]) for p in properties]
        check(actual == [p[:3] for p in expected_properties], "width clip schema mismatch")
        for prop, expected in zip(properties, expected_properties):
            for key in prop["keys"]:
                struct.pack_into(">f", data, key["offset"], expected[3])
            clips.append({"address": f"0x{address:08X}", "component": expected[0],
                          "property": expected[1], "dimension": expected[2], "constant": expected[3],
                          "key_count": len(prop["keys"]), "first_key": prop["keys"][0],
                          "last_key": prop["keys"][-1]})
        result[address] = bytes(data)

    action = original[0xC216CA4D]
    check(word(action) == 0x10009 and word(action, 32) == 1 and len(action) == 41,
          "sync action shape mismatch")
    check(pool_string(source, word(action, 8)) == "controlAppState" and
          pool_string(source, word(action, 36)) == "submenu_05", "sync action source mismatch")
    # Native constructor defaults prop1 to true. Explicitly select BOTH false
    # booleans: prop1 app-sync-request, prop5 view-state-event. No request string.
    data = bytearray(action[:32] + struct.pack(">III", 0x22, 0, 0))
    struct.pack_into(">I", data, 4, len(data))
    result[0xC216CA4D] = bytes(data)

    for address in REMOVED:
        del result[address]
    root = bytearray(result[0xC216C948])
    check(word(root) == 0x10003 and word(root, 8) == 16 and word(root, 20) == 19459,
          "MenuItem_Select declaration mismatch")
    struct.pack_into(">I", root, 8, 15)
    result[0xC216C948] = bytes(root)

    old_counts = component_counts(source, original)
    new_counts = component_counts(source, result)
    delta = {name: new_counts[name] - old_counts[name] for name in old_counts
             if old_counts[name] != new_counts[name]}
    check(delta == {"appVariableChangeEvent": -1, "controlAnimation": -1}, "component budget delta mismatch")
    verify_isolation(source, result)
    return result, {"width": WIDTH, "width_units": "native 1024-wide UI coordinate space",
                    "choice": "fixed host design value, not language-dependent stock width",
                    "base_fields": edits, "constant_clips": clips,
                    "removed_records": [f"0x{x:08X}" for x in REMOVED],
                    "record_count_delta": -2, "object_count_delta": 0,
                    "component_budget_delta": delta, "group_clip_key_budget_delta": 0,
                    "root_component_count": {"old": 16, "new": 15},
                    "sync_action": {"address": "0xC216CA4D", "mask": "0x22", "length": 44,
                                    "app_sync_request": False, "view_state_event": False}}


def verify_isolation(source, result):
    check(all(x not in result for x in REMOVED), "shared width watcher/action remains")
    action = result[0xC216CA4D]
    check(len(action) == 44 and word(action, 4) == 44 and word(action, 32) == 0x22 and
          word(action, 36) == 0 and word(action, 40) == 0, "sync is not explicitly inert")
    check(word(result[0xC216C948], 8) == 15, "owner component count not reduced")
    for address, fields in GEOMETRY.items():
        for offset, _, expected, _ in fields:
            check(struct.unpack_from(">f", result[address], offset)[0] == expected,
                  "fixed base geometry mismatch")
    for address, fields in CLIPS.items():
        properties = decode_clip(source, result[address])
        for prop, expected in zip(properties, fields):
            check(all(key["value"] == expected[3] for key in prop["keys"]),
                  "width animation could restore nonconstant geometry")


def native_dispatch(source, seg1):
    import capstone
    from capstone import arm_const as arm
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    md.detail = True
    registers, writes = {}, {}
    instructions = list(md.disasm(slice_va(source, 0xC05123D8, 0xC0512738), 0xC05123D8))
    check(len(instructions) * 4 == 0x360, "initializer disassembly incomplete")
    for ins in instructions:
        op = ins.operands
        if ins.mnemonic in ("movw", "movt"):
            check(op[0].type == arm.ARM_OP_REG and op[1].type == arm.ARM_OP_IMM, "unexpected mov")
            if ins.mnemonic == "movw":
                registers[op[0].reg] = op[1].imm
            else:
                check(op[0].reg in registers, "movt without initialized low half")
                registers[op[0].reg] = registers[op[0].reg] & 0xFFFF | op[1].imm << 16
        elif ins.mnemonic == "str":
            check(op[0].type == arm.ARM_OP_REG and op[1].type == arm.ARM_OP_MEM and
                  op[1].mem.index == 0 and not ins.writeback, "unexpected store")
            address = registers[op[1].mem.base] + op[1].mem.disp
            check(0xC2F2384C <= address <= 0xC2F23A7C and (address - 0xC2F2384C) % 8 == 0,
                  "initializer write outside callback slots")
            check(address not in writes, "duplicate callback store")
            writes[address] = registers[op[0].reg]
        else:
            check(ins.mnemonic == "bx" and ins.op_str == "lr" and ins.address == 0xC0512734,
                  "initializer is not the bounded immediate-store sequence")
    entries = []
    for index in range(70):
        address = 0xC2F23848 + index * 8
        event, raw_callback = struct.unpack_from("<II", seg1, address - SEG1_BASE)
        check(event and raw_callback == 0, "raw event table shape changed")
        entries.append({"event": event, "slot": f"0x{address + 4:08X}",
                        "callback": f"0x{writes[address + 4]:08X}"})
    check(len(writes) == 71 and struct.unpack_from("<I", seg1, 0xC2F23A78 - SEG1_BASE)[0] == 0,
          "callback table sentinel/count mismatch")
    check(entries[69] == {"event": 68, "slot": "0xC2F23A74", "callback": "0xC0511BB0"},
          "event 0x44 callback mismatch")
    vtable = 0xC0CD1C1C
    check(struct.unpack_from("<I", source, vtable + 0x124 - BASE)[0] == 0xC0451C08,
          "MainRec2 event consumer changed")
    check(struct.unpack_from("<I", source, vtable + 0x160 - BASE)[0] == 0xC0453248,
          "MainRec2 type1 consumer changed")
    spans = []
    for lo, hi, mode, role in (
        (0xC05123D8, 0xC0512738, capstone.CS_MODE_ARM, "startup callback table writes"),
        (0xC0511BB0, 0xC0511BD4, capstone.CS_MODE_ARM, "event44 payload thunk"),
        (0xC0510DA0, 0xC0510EB8, capstone.CS_MODE_ARM, "8-byte table dispatch"),
        (0xC0510F78, 0xC0511000, capstone.CS_MODE_ARM, "current-handler dispatch"),
        (0xC0451C5C, 0xC0451CB0, capstone.CS_MODE_ARM, "payload type1 dispatch"),
        (0xC0453248, 0xC0453264, capstone.CS_MODE_ARM, "return1 handler"),
        (0xC05F1398, 0xC05F1440, capstone.CS_MODE_THUMB, "controlAppState send gates"),
        (0xC05F1440, 0xC05F14A8, capstone.CS_MODE_THUMB, "controlAppState true default"),
        (0xC05F1170, 0xC05F11EE, capstone.CS_MODE_THUMB, "ApplyFrame requires variable name"),
    ):
        blob = slice_va(source, lo, hi)
        decoder = capstone.Cs(capstone.CS_ARCH_ARM, mode)
        spans.append({"start": f"0x{lo:08X}", "end": f"0x{hi:08X}", "role": role,
                      "sha256": sha(blob), "disassembly": [f"{i.address:08X} {i.mnemonic} {i.op_str}"
                      for i in decoder.disasm(blob, lo)]})
    return {"callback_table_initialized_by_code_not_relocation": True,
            "active_entries": entries, "initializer_stores_including_sentinel": len(writes),
            "event44": entries[69], "handler_vtable": f"0x{vtable:08X}",
            "event_slot": "0x124", "type1_slot": "0x160", "type1_return": 1,
            "all_runtime_hook_handlers_proven_inert": False, "spans": spans}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seg0", type=Path, required=True)
    parser.add_argument("--seg1", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="optional new JSON file; overwrite refused")
    args = parser.parse_args()
    source, seg1 = args.seg0.read_bytes(), args.seg1.read_bytes()
    check(len(source) == 49245696 and sha(source) == SEG0_SHA, "seg0 fingerprint mismatch")
    check(len(seg1) == 236032 and sha(seg1) == SEG1_SHA, "seg1 fingerprint mismatch")
    _, recipe = fixed_width_recipe(source)
    evidence = {"host_only": True, "source_sha256": SEG0_SHA, "seg1_sha256": SEG1_SHA,
                "native_dispatch": native_dispatch(source, seg1), "recipe": recipe,
                "source_sha_after": sha(args.seg0.read_bytes()),
                "deployable": False, "camera_render_navigation_or_rec_tested": False,
                "private_setting_binding_implemented_here": False}
    check(evidence["source_sha_after"] == SEG0_SHA, "source changed during verification")
    content = json.dumps(evidence, indent=2) + "\n"
    if args.output:
        with args.output.open("x") as stream:
            stream.write(content)
        print(json.dumps({"output": str(args.output.resolve()), "status": "PASS", "width": WIDTH,
                          "event44_callback": "0xC0511BB0", "deployable": False}))
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
