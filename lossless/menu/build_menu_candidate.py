#!/usr/bin/env python3
"""Build a non-deployable, gated MainB2 page candidate from pinned seg0.

Outputs are a resource fragment, private string pool and evidence manifest.
No firmware image, VSHL, AutoRun, transport, or runtime adapter is produced.
"""

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys


_SCRIPT_PARENTS = Path(__file__).resolve().parents
_AUDIT_CANDIDATES = [_SCRIPT_PARENTS[index] / "research/ui/tools/native_ui_audit.py"
                     for index in (3, 2) if len(_SCRIPT_PARENTS) > index]
DEFAULT_AUDIT = next((path for path in _AUDIT_CANDIDATES if path.is_file()), _AUDIT_CANDIDATES[0])
NAMES = ("MainB2.fpLossless.gated.page", "MainB2.fpLossless.strings", "manifest.json")
OWNER_OFFSETS = {0x10004: 20, 0x10005: 20, 0x10006: 24,
                 0x10009: 20, 0x1000A: 20, 0x1000E: 20}
MASK_OFFSETS = {0x10004: 28, 0x10005: 28, 0x10006: 32,
                0x10009: 32, 0x1000E: 28}
DESCRIPTORS = {
    "objectBase": (0xC2DFF5F4, ["position", "size", "angle", "scale", "transform-origin", "opacity",
                               "is-visible", "do-clip", "tab-index", "is-tab-group", "tab-group-focus-rule",
                               "is-active", "is-render-group"]),
    "appVariableEvent": (0xC2E000A0, ["type", "variable-name", "component-id", "property-name",
                                     "property-subindex", "decimal-places"]),
    "appVariableChangeEvent": (0xC2E001B0, ["variable-name", "type", "equal-value", "greater-than-value",
                                           "lower-than-value", "range-lowerlimit-value", "range-upperlimit-value",
                                           "equal-string"]),
    "controlAppState": (0xC2E0122C, ["sync-request", "app-sync-request", "to-uic", "skip-anim",
                                    "send-all-shared-context", "view-state-event", "essential", "to-all-shared-context"]),
    "controlAnimation": (0xC2E0108C, ["operation", "animationset-owner", "animationset", "interval",
                                     "do-descent", "speed", "overwrite-loop", "loop-nb", "apply-frame"]),
    "controlFocus": (0xC2E01474, ["operation", "object-id", "do-loop", "layout-item-index", "focus-variable"]),
    "controlAppVariable": (0xC2E01340, ["destination-variable", "source-type", "source-variable", "object-id",
                                      "component-name", "component-tag", "component-property", "value"]),
    "changePropertyByControl": (0xC2E0177C, ["object-id", "component-name", "component-tag",
                                            "component-property", "formula", "decimal-places"]),
    "controlTimer": (0xC2E015C0, ["object-id", "operation"]),
    "controlValue": (0xC2E027C8, ["min-value", "max-value", "value", "is-value-loop", "terminal-type"]),
    "controlValueEvent": (0xC2E02944, ["type", "equal-value", "greater-than-value", "lower-than-value",
                                      "range-lowerlimit-value", "range-upperlimit-value", "previous-type",
                                      "previous-equal-value", "previous-greater-than-value", "previous-lower-than-value",
                                      "previous-range-lowerlimit-value", "previous-range-upperlimit-value"]),
    "focusEvent": (0xC2E02CAC, ["type"]),
    "keyEvent": (0xC2E02D14, ["type", "keys", "keycode", "args", "do-propagate"]),
    "screenEvent": (0xC2E02E10, ["type"]),
    "timerEvent": (0xC2E02F14, ["timeout", "repeat"]),
    "drawImage": (0xC2E031E0, ["image", "do-modulate-color", "color", "do-perspective", "perspective-distance",
                              "perspective-origin", "perspective-rotation"]),
    "drawRect": (0xC2E033E0, ["color", "do-fill", "fill-paint", "border-width", "border-paint",
                             "corner-radius-top-left", "corner-radius-top-right", "corner-radius-bottom-left",
                             "corner-radius-bottom-right"]),
    "drawText": (0xC2E035AC, ["text", "font-setting", "font-size", "unit", "horz-align", "vert-align", "direction",
                             "is-single-line", "do-kerning", "pad-left", "pad-top", "pad-right", "pad-bottom", "color",
                             "outline-color", "outline-width", "outline-mode", "do-gradient", "gradient-color",
                             "gradient-direction", "do-shadow", "shadow-color", "shadow-offset", "shadow-blur",
                             "truncation-mode", "wrap-mode", "repeat", "repeat-spacing", "offset", "text-decoration"]),
}
# Each is a verified typed field, not a search-and-replace rule.
PRIVATE_FIELDS = {
    0x204E14D: (40, "MV_AudioRecord", "MV_fpLossless"),
    0x204E187: (36, "MV_AudioRecord", "MV_fpLossless"),
    0x204E1B4: (54, "MV_AudioRecord", "MV_fpLossless"),
    0x204F183: (36, "MV_AudioRecord", "MV_fpLossless"),
    0x204F23C: (36, "MV_AudioRecord", "MV_fpLossless"),
    0x204E6C6: (36, "B2_6", "fpLossless_UNRESOLVED_jump"),
    0x204EC7A: (36, "SUB_MV_AudioRecord", "fpLossless_UNRESOLVED_submenu"),
    0x204ED97: (36, "SUB_MV_AudioRecord", "fpLossless_UNRESOLVED_submenu"),
    0x2054060: (32, "0326_C", "fpLossless"),
}
PROFILES = {
    "audio-gated": {
        "page_start": 0x2030364, "page_end": 0x2055DB0,
        "page_sha256": "10ed690e589bf7899ca022a3f108116d6a25ff9579081cd637e6ba8bcc99bc41",
        "start": 0x204DACA, "end": 0x205460A, "root_id": 122,
        "donor_sha256": "006113cce5bb460973e5934e02e1fe8d3d32c7fb325160cd8bbd46abd3cf3fb3",
        "private_fields": PRIVATE_FIELDS, "literal_records": [0x2054060],
        "geometry_clip": 0x204DB16, "pure_select": False,
    },
    "pure-select-gated": {
        "page_start": 0x214A0C0, "page_end": 0x217CDEE,
        "page_sha256": "8f5008dd58b5dcaef14226245f78822c6b05c038e939b56bb1ff5939238189be",
        "start": 0x216C8B8, "end": 0x2172BC6, "root_id": 19457, "source_parent": 196,
        "donor_sha256": "33eca8104f7ab0630c7544e9769f6daaa7d0bc6c62856805379ea9ef0d70b48b",
        "private_fields": {
            0x216CEB3: (40, "ST_CableRelease", "MV_fpLossless"),
            0x216CEE8: (36, "ST_CableRelease", "MV_fpLossless"),
            0x216CF15: (54, "ST_CableRelease", "MV_fpLossless"),
            0x216D8F2: (36, "ST_CableRelease", "MV_fpLossless"),
            0x216D986: (36, "ST_CableRelease", "MV_fpLossless"),
            0x216CA4D: (36, "submenu_05", "fpLossless_UNRESOLVED_row_state"),
            0x216DD72: (32, "1304", "OFF"),
            0x2170209: (32, "1305", "ON"),
            0x2172640: (32, "1303_S", "Lossless RAW"),
            0x21727CD: (32, "1304", "OFF"),
        },
        "literal_records": [0x216DD72, 0x2170209, 0x2172640, 0x21727CD],
        "geometry_clip": 0x216C904, "geometry_base": 0x216C8DC,
        "binary_value_record": 0x216D3EB,
        "text_animation_values": {
            0x2172735: {"1303_S_R": "Lossless RAW", "1303_S": "Lossless RAW"},
            0x21728BE: {"1304_R": "OFF", "1305": "ON"},
        },
        "pure_select": True,
    },
}
PROFILES["pure-fixed-gated"] = deepcopy(PROFILES["pure-select-gated"])
PROFILES["pure-fixed-gated"]["fixed_popup"] = True
del PROFILES["pure-fixed-gated"]["private_fields"][0x216CA4D]
SHARED_CALLS = {0x216CA1B: (37, "Footer"), 0x216D533: (37, "Footer"),
                0x216CB0F: (55, "UpDown"), 0x216CB95: (55, "UpDown")}
SHARED_RECORDS = [
    (0x217B6A4, 0x205465E, 1207, "6f8b51030a8860ffc4827b3191e5778e4288eb5ac26053fbd125751b48ae08d8", "Footer group"),
    (0x217BB5B, 0x2054B15, 94, "1b23fa8e3e9c82c64892ebc44883835426c89519cb93098af290b1d7d74b8731", "FooterSelect group"),
    (0x215002B, 0x20360F7, 65, "3705817b07268d6b43a5b4b050caf50d312563ee9765e5cac8340aaf28e849b4", "UpDown group"),
    (0x214FE1A, 0x2035EE6, 188, "365b09cac659d39414d4b68d51763ca84ccd850c3714985daf8546e85799523c", "owner55 clip29"),
    (0x217BD26, 0x2054CE0, 538, "965edff2eeaea03e4066c3774af3612125d24a7881d0a3517c9e5a3f3715d62e", "owner19499 clip2"),
    (0x217BFCD, 0x2054F87, 598, "93e2b07d2ecd8d1563e2bdd4df4f8d69eda97e5f87c8bb4d0143ca25895ca4d1", "owner19500 clip2"),
]


class CandidateError(ValueError):
    pass


def check(condition, message):
    if not condition:
        raise CandidateError(message)


def u32(data, offset):
    check(0 <= offset <= len(data) - 4, "u32 outside record")
    return struct.unpack_from(">I", data, offset)[0]


def words(*values):
    return struct.pack(">%dI" % len(values), *values)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_audit(path):
    path = Path(path).resolve()
    spec = importlib.util.spec_from_file_location("_fplossless_native_ui_audit", path)
    check(spec is not None and spec.loader is not None, "cannot load audit module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    # Compile explicitly so loading shared read-only tooling creates no __pycache__ there.
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


class PrivatePool:
    """Preserve original offsets in an independent, byte-identical pool prefix."""

    def __init__(self, original):
        self.data = bytearray(original)
        self.original_length = len(original)
        self.added = {}

    def resolve(self, offset):
        check(0 <= offset < len(self.data), "string reference outside private pool")
        end = self.data.find(b"\0", offset)
        check(end >= offset, "unterminated private string")
        try:
            return self.data[offset:end].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CandidateError("invalid private UTF-8") from exc

    def intern(self, value):
        check(value and "\0" not in value, "invalid private name")
        if value not in self.added:
            self.data.extend(b"\0" * (-len(self.data) % 4))
            self.added[value] = len(self.data)
            self.data.extend(value.encode("utf-8") + b"\0")
            self.data.extend(b"\0" * (-len(self.data) % 4))
        return self.added[value]


def allocate_ids(all_ids, donor_ids):
    """Allocate only after checking the complete page namespace; no stock IDs assumed."""
    existing = set(all_ids)
    check(existing and len(existing) == len(all_ids), "duplicate/empty source object namespace")
    check(all(0 < object_id < 0x10000 for object_id in existing), "source ID outside bounded 16-bit namespace")
    check(len(set(donor_ids)) == len(donor_ids), "duplicate donor object ID")
    check(set(donor_ids) <= existing, "donor object is not in MainB2")
    start = max(existing) + 1
    # Stay in the stock observed 16-bit range; do not assume packed consumers accept 32 bits.
    check(start + len(donor_ids) <= 0x10000, "no bounded 16-bit ID range available")
    mapping = {old: start + i for i, old in enumerate(donor_ids)}
    check(not (set(mapping.values()) & existing), "allocated ID collision")
    return mapping


def load_property_schemas(source):
    """Read verified LE native descriptors; serialized property values remain BE."""
    result = {}
    for component, (address, names) in DESCRIPTORS.items():
        fields = []
        for index, expected in enumerate(names):
            kind, pointer, default = struct.unpack_from("<III", source, address - 0xC0000000 + index * 12)
            offset = pointer - 0xC0000000
            check(0 <= offset < len(source), "descriptor name pointer outside seg0")
            end = source.find(b"\0", offset)
            check(end >= offset, "unterminated descriptor name")
            name = source[offset:end].decode("utf-8")
            check(name == expected, "native descriptor name fingerprint mismatch")
            fields.append({"kind": kind, "name": name, "default_raw": default})
        result[component] = fields
        if component in ("drawImage", "drawRect", "drawText"):
            # FUN_c05d5670 resolves these final two fields for drawable type 4.
            # C05D5E30 adds two to the constructor's declared property count.
            for address, expected, expected_kind in ((0xC2DFFC00, "rect", 5), (0xC2DFFBF4, "layout", 10)):
                kind, pointer, default = struct.unpack_from("<III", source, address - 0xC0000000)
                offset = pointer - 0xC0000000
                check(0 <= offset < len(source), "drawable common descriptor pointer outside seg0")
                end = source.find(b"\0", offset)
                check(end >= offset, "unterminated drawable descriptor")
                name = source[offset:end].decode("utf-8")
                check(name == expected and kind == expected_kind, "drawable common descriptor mismatch")
                fields.append({"kind": kind, "name": name, "default_raw": default})
    return result


def validate_shared_dependencies(source, audit, donor_page, target_page, resolve):
    source_objects = audit.parse_objects(donor_page, resolve)
    target_objects = audit.parse_objects(target_page, resolve)
    source_records = {r.offset: r for r in donor_page}
    target_records = {r.offset: r for r in target_page}
    for object_id, parent, name, children in ((37, 1, "Footer", 2), (55, 56, "HeaderActiveTab", 3)):
        expected = (object_id, parent, name, children)
        for objects in (source_objects, target_objects):
            obj = objects[object_id]
            check((obj["id"], obj["parent_id"], obj["name"], obj["child_count"]) == expected,
                  "shared UI object identity mismatch")
    evidence = []
    for old, target, length, expected_hash, role in SHARED_RECORDS:
        check(old in source_records and target in target_records, "shared dependency is not a whole record")
        a, b = source_records[old].data, target_records[target].data
        check(len(a) == length and a == b and digest(a) == expected_hash, "shared dependency byte fingerprint mismatch")
        evidence.append({"source": audit.address(old), "target": audit.address(target),
                         "length": length, "sha256": expected_hash, "role": role})
    for record, (owner, group) in SHARED_CALLS.items():
        check(u32(source, record + 36) == owner and resolve(u32(source, record + 40)) == group,
              "shared dependency callsite mismatch")
    return evidence


class Remapper:
    def __init__(self, pool, mapping, original_ids, schemas=None, profile=None, shared_calls=None):
        self.pool, self.mapping, self.original_ids = pool, mapping, set(original_ids)
        self.changes, self.object_fields, self.string_fields, self.unresolved = [], [], [], []
        self.insertions = []
        self.schemas = schemas or {}
        self.profile = profile or PROFILES["audio-gated"]
        self.shared_calls = shared_calls or {}
        self.decoded_property_records = []

    def write(self, data, source, offset, value, role):
        old = u32(data, offset)
        if old != value:
            struct.pack_into(">I", data, offset, value)
            self.changes.append({"source_record": "0x%08X" % (0xC0000000 + source),
                                 "field_offset": offset, "role": role, "old": old, "new": value})

    def write_byte(self, data, source, offset, value, role):
        check(0 <= offset < len(data) and 0 <= value < 256, "byte field outside bounds")
        old = data[offset]
        if old != value:
            data[offset] = value
            self.changes.append({"source_record": "0x%08X" % (0xC0000000 + source),
                                 "field_offset": offset, "width": 1, "role": role, "old": old, "new": value})

    def object_field(self, data, source, offset, role, allow_zero=False):
        old = u32(data, offset)
        reparent = self.profile["pure_select"] and source == self.profile["start"] and role == "parent_id"
        if reparent:
            check(old == self.profile["source_parent"], "cross-page donor root parent mismatch")
            new, scope = 116, "explicit_reparent_to_mainb2"
        else:
            check(old in self.original_ids or (allow_zero and old == 0),
                  "unresolved typed object ID %d at %X+%d" % (old, source, offset))
            shared = source in self.shared_calls and offset == 36 and role == "property_object_id:animationset-owner"
            if shared:
                check(old == self.shared_calls[source][0], "shared callsite owner mismatch")
            elif self.profile["pure_select"]:
                check(old in self.mapping or (allow_zero and old == 0),
                      "foreign-page typed object reference %d at %X+%d (%s) must not be retained" % (old, source, offset, role))
            new = self.mapping.get(old, old)
            scope = "verified_shared_ui_dependency" if shared else ("cloned_object" if old in self.mapping else "original_page_or_null")
        self.write(data, source, offset, new, role)
        self.object_fields.append({"source_record": "0x%08X" % (0xC0000000 + source),
                                   "field_offset": offset, "role": role, "old": old, "new": new,
                                   "scope": scope})

    def string_field(self, data, source, offset, role, optional=False):
        value = u32(data, offset)
        if optional and value == 0xFFFFFFFF:
            return
        text = self.pool.resolve(value)
        self.string_fields.append({"source_record": "0x%08X" % (0xC0000000 + source),
                                   "field_offset": offset, "role": role,
                                   "pool_offset": value, "text": text})

    def group(self, data, source):
        states, transitions, count = (u32(data, i) for i in (8, 12, 16))
        check(transitions == 0, "donor group transitions require a typed schema")
        if self.profile.get("fixed_popup") and source == 0x216D1FF:
            check(states == 1 and count == 6, "fixed popup group signature mismatch")
            for offset in (20, 28):
                check(self.pool.resolve(u32(data, offset)) == "submenu_width_NoIcon",
                      "fixed popup local group source mismatch")
                self.write(data, source, offset, self.pool.intern("fpLossless_FixedWidth"),
                           "private_fixed_geometry_group")
        self.string_field(data, source, 20, "group_name")
        self.object_field(data, source, 24, "group_owner")
        cursor = 28
        for _ in range(states):
            check(cursor + 21 <= len(data), "truncated group state")
            self.string_field(data, source, cursor, "group_state_name")
            cursor += 21
        check(cursor + count * 8 + 8 == len(data), "unexpected donor group extent")
        for _ in range(count):
            self.object_field(data, source, cursor, "group_clip_owner")
            cursor += 8  # The clip ID is component-local, not an object ID.
        self.string_field(data, source, cursor, "group_tail_name")
        self.object_field(data, source, cursor + 4, "group_tail_object", allow_zero=True)

    def clip(self, data, source):
        cursor = 28
        for _ in range(u32(data, 12)):
            count, kind, component, name, dimension = struct.unpack_from(">5I", data, cursor)
            check(kind in (0, 1, 2), "unsupported animation type")
            self.string_field(data, source, cursor + 12, "animated_property_name")
            property_name = self.pool.resolve(name)
            # Audited donor properties do not encode object IDs in their numeric keys.
            check(property_name in {"is-visible", "position", "color", "rect", "size", "text", "type"},
                  "unclassified animated property: " + property_name)
            for index in range(count):
                key = cursor + 20 + 10 * index
                check(key + 10 <= len(data), "truncated animation key")
                check(data[key] <= 1 and data[key + 1] <= 1, "unhandled tangent key")
                if kind == 2:
                    replacements = self.profile.get("text_animation_values", {}).get(source)
                    if replacements is not None and property_name == "text":
                        old_text = self.pool.resolve(u32(data, key + 6))
                        check(old_text in replacements, "text animation source label mismatch")
                        self.write(data, source, key + 6, self.pool.intern(replacements[old_text]), "literal_text_animation")
                    self.string_field(data, source, key + 6, "animation_string_value")
                if source == self.profile["geometry_clip"] and not self.profile["pure_select"] and property_name == "position" and dimension == 1 and u32(data, key + 2) == 66:
                    check(kind == 1 and u32(data, key + 6) == 0x43220000, "donor CINE y mismatch")
                    self.write(data, source, key + 6, 0x43730000, "cine_row_y_162_to_243")
                if source == self.profile["geometry_clip"] and self.profile["pure_select"] and property_name == "is-visible":
                    time, old = u32(data, key + 2), u32(data, key + 6)
                    check((time, old) in ((0, 1), (66, 0)), "pure donor visibility source mismatch")
                    self.write(data, source, key + 6, 1 - old, "still_hidden_cine_visible")
            cursor += 20 + count * 10
        check(cursor == len(data), "unconsumed clip bytes")

    def properties(self, data, source, component, mask_offset):
        if component not in self.schemas:
            return False
        schema = self.schemas[component]
        check(u32(data, 12) == len(schema), "serialized/native property count mismatch")
        cursor, mask, fields = mask_offset, 0, []
        widths = {0: 4, 1: 4, 2: 4, 3: 4, 4: 16, 5: 16, 6: 8, 7: 12,
                  8: 16, 9: 4, 10: 4, 11: 5, 12: 4, 13: 4, 14: 4}
        # Decode the entire body before mutating any typed property references.
        for index, prop in enumerate(schema):
            if index % 32 == 0:
                mask = u32(data, cursor)
                remaining = min(32, len(schema) - index)
                check(mask >> remaining == 0, "property mask sets bits beyond descriptor count")
                cursor += 4
            if not (mask >> (index % 32)) & 1:
                continue
            kind = prop["kind"]
            check(kind in widths, "unknown native property type")
            check(cursor + widths[kind] <= len(data), "truncated typed property")
            fields.append((cursor, kind, prop["name"]))
            cursor += widths[kind]
        check(cursor == len(data), "typed property body extent mismatch")
        for offset, kind, name in fields:
            if kind == 14:
                self.object_field(data, source, offset, "property_object_id:" + name, allow_zero=True)
            elif kind in (11, 12, 13):
                self.string_field(data, source, offset, "property_string:" + name, optional=True)
        self.decoded_property_records.append({"source_record": "0x%08X" % (0xC0000000 + source),
                                              "component": component, "typed_property_count": len(fields),
                                              "body_fully_consumed": True})
        return True

    def transform(self, record):
        data, source, tag = bytearray(record.data), record.offset, record.tag
        if tag == 0x10003:
            check(len(data) == 36, "unexpected object declaration length")
            self.object_field(data, source, 20, "object_id")
            self.object_field(data, source, 24, "parent_id", allow_zero=True)
            if source == self.profile["start"]:
                self.write(data, source, 28, self.pool.intern("fpLossless_Row_GATED"), "private_row_name")
            self.string_field(data, source, 28, "object_name")
        elif tag == 0x1000B:
            self.group(data, source)
        elif tag in OWNER_OFFSETS:
            if source == self.profile.get("geometry_base"):
                check(u32(data, 28) == 1 and u32(data, 32) == 0 and u32(data, 36) == 0x43220000,
                      "pure donor base position mismatch")
                self.write(data, source, 36, 0x43730000, "cine_row_base_y_162_to_243")
            if source == self.profile.get("binary_value_record"):
                check(tag == 0x1000E and len(data) == 36 and u32(data, 28) == 8 and u32(data, 32) == 1,
                      "pure donor List controlValue signature mismatch")
                inserted = words(0, 0x3F800000, 0)
                data[32:32] = inserted  # min=0, max=1, initial=0; loop remains 1.
                self.insertions.append({"source_record": "0x%08X" % (0xC0000000 + source),
                                        "field_offset": 32, "length": len(inserted), "hex": inserted.hex(),
                                        "role": "explicit_binary_list_float_properties",
                                        "values": {"min-value": 0.0, "max-value": 1.0, "value": 0.0}})
                self.write(data, source, 28, 15, "explicit_binary_list_value_mask")
                self.write(data, source, 4, len(data), "expanded_binary_value_record_length")
            self.object_field(data, source, OWNER_OFFSETS[tag], "component_owner")
            self.string_field(data, source, 8, "component_kind")
            self.string_field(data, source, 20 if tag == 0x10006 else 16,
                              "component_instance_name", optional=True)
            if source in self.profile["private_fields"]:
                offset, expected, replacement = self.profile["private_fields"][source]
                check(self.pool.resolve(u32(data, offset)) == expected,
                      "private field source mismatch at %X+%d: expected %s, got %s" %
                      (source, offset, expected, self.pool.resolve(u32(data, offset))))
                self.write(data, source, offset, self.pool.intern(replacement), "private_string_redirect")
                self.string_field(data, source, offset, "private_string_redirect")
            if source in self.profile["literal_records"]:
                check(data[36] == 1, "source label is not resolver-enabled")
                self.write_byte(data, source, 36, 0, "literal_text_not_variable_resolver")
            if tag == 0x1000A:
                self.clip(data, source)
            else:
                mask_offset = MASK_OFFSETS[tag]
                check(mask_offset + 4 <= len(data), "component lacks property mask")
                component = self.pool.resolve(u32(data, 8))
                if self.properties(data, source, component, mask_offset):
                    return bytes(data)
                # Do not treat every equal numeric word as an object or string reference.
                # Remaining property bodies need component-specific typed schemas.
                self.unresolved.append({"code": "UNTYPED_COMPONENT_PROPERTY_BODY",
                                        "source_record": "0x%08X" % (0xC0000000 + source),
                                        "component": component,
                                        "property_mask": "0x%08X" % u32(data, mask_offset),
                                        "body_offset": mask_offset + 4,
                                        "body_length": len(data) - mask_offset - 4,
                                        "action": "preserved_unclassified_bytes; gate_not_passed"})
        else:
            raise CandidateError("no donor schema for tag 0x%X" % tag)
        return bytes(data)


def extend_header(record, header, delta):
    """Keep original budget arrays, including reserved capacity, and append clone needs."""
    out = bytearray(record.data[:20])
    struct.pack_into(">I", out, 8, header["objects"] + delta["objects"])
    names = list(header["component_counts"])
    check(set(delta["component_counts"]) <= set(names), "donor introduces unknown component kind")
    for index, name in enumerate(names):
        original_ref = record.word(20 + index * 8)
        out.extend(words(original_ref, header["component_counts"][name] + delta["component_counts"].get(name, 0)))
    for name, added in (("groups", delta["group_budgets"]),
                        ("clip_property_counts", delta["clip_property_counts"]),
                        ("property_key_counts", delta["property_key_counts"]),
                        ("trailing_budget", [])):
        values = header[name] + added
        out.extend(words(len(values)))
        for value in values:
            out.extend(words(*value) if isinstance(value, list) else words(value))
    struct.pack_into(">I", out, 4, len(out))
    return bytes(out)


def extend_mode_change(record, new_root):
    data = bytearray(record.data)
    check((u32(data, 8), u32(data, 12), u32(data, 16), len(data)) == (2, 0, 6, 126),
          "stock ModeChange signature mismatch")
    data[118:118] = words(new_root, 1)
    struct.pack_into(">I", data, 16, 7)
    struct.pack_into(">I", data, 4, len(data))
    return bytes(data)


def build_candidate(source, audit, profile_name="pure-fixed-gated"):
    evidence = audit.audit_bytes(source)  # Whole-image hash gate before any transform.
    check(profile_name in PROFILES, "unknown donor profile")
    profile = PROFILES[profile_name]
    stock = audit.records(source, audit.PAGE_START, audit.PAGE_END)
    by_offset = {record.offset: record for record in stock}
    check(digest(source[profile["page_start"]:profile["page_end"]]) == profile["page_sha256"], "donor page hash mismatch")
    check(digest(source[profile["start"]:profile["end"]]) == profile["donor_sha256"], "donor subtree hash mismatch")
    donor_page = audit.records(source, profile["page_start"], profile["page_end"])
    donor = [r for r in donor_page if profile["start"] <= r.offset < profile["end"]]
    original_pool = source[audit.POOL:audit.POOL_END]
    pool = PrivatePool(original_pool)
    all_objects = audit.parse_objects(stock, pool.resolve)
    donor_objects = audit.parse_objects(donor, pool.resolve)
    check(donor[0].offset == profile["start"] and donor[-1].offset + len(donor[-1].data) == profile["end"],
          "donor is not a whole-record subtree")
    fixed_popup = None
    if profile.get("fixed_popup"):
        recipe_path = Path(__file__).with_name("verify_recipe.py")
        spec = importlib.util.spec_from_file_location("fplossless_fixed_popup_recipe", recipe_path)
        check(spec is not None and spec.loader is not None, "fixed popup recipe unavailable")
        recipe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(recipe)
        prepared, fixed_popup = recipe.fixed_width_recipe(source)
        fixed_popup["recipe_sha256"] = digest(recipe_path.read_bytes())
        fixed_popup["prepared_records"] = [
            {"source_record": audit.address(record.offset), "original_length": len(record.data),
             "original_sha256": digest(record.data),
             "prepared_length": len(prepared.get(record.offset + 0xC0000000, b"")),
             "prepared_sha256": digest(prepared[record.offset + 0xC0000000])
                 if record.offset + 0xC0000000 in prepared else None}
            for record in donor if prepared.get(record.offset + 0xC0000000) != record.data]
        donor = [audit.Record(record.offset, prepared[record.offset + 0xC0000000]) for record in donor
                 if record.offset + 0xC0000000 in prepared]
    namespace = set(all_objects) | set(donor_objects)
    mapping = allocate_ids(list(namespace), list(donor_objects))
    property_schemas = load_property_schemas(source)
    shared_evidence = validate_shared_dependencies(source, audit, donor_page, stock, pool.resolve) if profile["pure_select"] else []
    remapper = Remapper(pool, mapping, namespace, property_schemas, profile, SHARED_CALLS if shared_evidence else None)
    clone = [(record, remapper.transform(record)) for record in donor]
    source_header = audit.parse_header(donor_page[0], pool.resolve)
    source_groups = [r for r in donor_page if r.tag == 0x1000B]
    group_indexes = [i for i, r in enumerate(source_groups) if profile["start"] <= r.offset < profile["end"]]
    source_clips = [audit.parse_clip(r, pool.resolve) for r in donor if r.tag == 0x1000A]
    delta = {"objects": len(donor_objects), "component_counts": audit.component_counts(donor, pool.resolve),
             "source_group_budget_indexes": group_indexes,
             "group_budgets": [source_header["groups"][i] for i in group_indexes],
             "clip_property_counts": [len(c["properties"]) for c in source_clips],
             "property_key_counts": [len(p["keys"]) for c in source_clips for p in c["properties"]]}
    new_header = extend_header(stock[0], evidence["allocation_header"], delta)
    new_root = mapping[profile["root_id"]]
    parts, locations = [], []
    cursor = 0

    def append(original, data, provenance):
        nonlocal cursor
        locations.append({"source_record": audit.address(original.offset),
                          "candidate_offset": cursor, "length": len(data),
                          "provenance": provenance, "sha256": digest(data)})
        parts.append(data)
        cursor += len(data)

    for record in stock:
        if record.offset == audit.DONOR_END:
            for original, data in clone:
                append(original, data, "cloned_fourth_row_gated")
        if record.offset == audit.PAGE_START:
            data = new_header
        elif record.offset == audit.B2_OBJECT:
            data = bytearray(record.data)
            check(u32(data, 16) == 6, "stock B2 child count mismatch")
            struct.pack_into(">I", data, 16, 7)
            data = bytes(data)
        elif record.offset == audit.MODE_CHANGE:
            data = extend_mode_change(record, new_root)
        else:
            data = record.data
        append(record, data, "stock_modified" if data != record.data else "stock_unchanged")
    candidate = b"".join(parts)
    parsed = audit.records(candidate, 0, len(candidate))
    objects = audit.parse_objects(parsed, pool.resolve)
    counts = Counter(obj["parent_id"] for obj in objects.values())
    check(len(objects) == len(all_objects) + len(donor_objects) and len(parsed) == len(stock) + len(donor),
          "candidate structure count mismatch")
    check(all(counts[obj["id"]] == obj["child_count"] for obj in objects.values()), "candidate child counts inconsistent")
    check(objects[new_root]["parent_id"] == 116 and objects[116]["child_count"] == 7, "fourth root not connected in resource graph")
    check(set(mapping.values()).isdisjoint(all_objects), "candidate IDs collide with stock")
    after_header = audit.parse_header(parsed[0], pool.resolve)
    check(after_header["objects"] == len(objects), "object lookup budget mismatch")
    check(pool.data[:len(original_pool)] == original_pool, "original string offsets changed")
    for key in ("groups", "clip_property_counts", "property_key_counts", "trailing_budget"):
        before = evidence["allocation_header"][key]
        check(after_header[key][:len(before)] == before, "original allocation reservation changed")
    clone_offset = next(row["candidate_offset"] for row in locations if row["provenance"] == "cloned_fourth_row_gated")
    unresolved = deepcopy(remapper.unresolved)
    if not profile["pure_select"]:
        unresolved.append({"code": "PURE_TOGGLE_NOT_PROVEN", "detail": "Inherited MenuItem_SelectJump; known Audio jump/submenu targets redirected to deliberately unresolved private names."})
    elif not profile.get("fixed_popup"):
        unresolved.append({"code": "PRIVATE_ROW_STATE_UNRESOLVED", "detail": "The submenu_05 width entry exists on MainB2, but page-dependent sizing and full queued dispatch are not proven; isolated as fpLossless_UNRESOLVED_row_state pending a private row-state handler."})
    if profile.get("fixed_popup"):
        check(not any(field["text"] == "submenu_width" or "UNRESOLVED" in field["text"]
                      for field in remapper.string_fields), "fixed row retains shared width or unresolved request")
        check(not any("UNRESOLVED" in name for name in pool.added),
              "fixed row added unresolved private string")
    unresolved.extend([
        {"code": "PRIVATE_VARIABLE_UNREGISTERED", "detail": "MV_fpLossless name exists in private pool only; this builder performs no registry initialization or callback attachment."},
        {"code": "NAVIGATION_NOT_PROVEN", "detail": "MENU_Level1 and controlFocus typed fields are remapped, but runtime traversal, expression evaluation and remaining action bodies are unverified."},
        {"code": "PRIVATE_LABEL_RENDERING_NOT_PROVEN", "detail": "Literal Lossless RAW/OFF/ON strings use resolver flag 0; native font rendering and layout remain untested."},
        {"code": "NO_RUNTIME_RESOURCE_ADAPTER", "detail": "Resource fragment has no NBU index/loader registration, hook, allocator execution or startup/lifetime adapter."},
        {"code": "NATIVE_ALLOCATION_NOT_EXECUTED", "detail": "Static C05E6400 header trace sums all budget arrays into one arena-size request, without retaining arrays or an ordinal budget cursor; append preserves that aggregate, but allocator success/camera capacity is untested."},
    ])
    manifest = {
        "schema_version": 1, "kind": "gated_offline_mainb2_page_candidate", "profile": profile_name,
        "status": "BLOCKED_NOT_DEPLOYABLE", "deployable": False,
        "runtime_tested": False, "camera_accessed": False,
        "source": {"seg0_sha256": evidence["input"]["sha256"],
                   "page_sha256": evidence["page"]["sha256"],
                   "donor_page_sha256": profile["page_sha256"], "donor_sha256": profile["donor_sha256"],
                   "donor_start": audit.address(profile["start"]), "donor_end_exclusive": audit.address(profile["end"])},
        "outputs": {NAMES[0]: {"length": len(candidate), "sha256": digest(candidate)},
                    NAMES[1]: {"length": len(pool.data), "sha256": digest(pool.data)}},
        "structural_checks": {"fourth_row_in_serialized_graph": True,
                              "private_ids_collision_checked_against_all_mainb2_objects": True,
                              "all_declared_child_counts_match": True,
                              "stock_pool_prefix_preserved": True,
                              "stock_allocation_reservations_preserved": True,
                              "complete_typed_payload_remap": not remapper.unresolved,
                              "pure_select_widget_structure": profile["pure_select"],
                              "private_fixed_popup_without_stock_sync": bool(profile.get("fixed_popup")),
                              "pure_toggle_runtime_verified": False, "native_focus_navigation": False},
        "new_row": {"root_id": new_root, "parent_id": 116, "cine_y": 243,
                    "widget_kind": "MenuItem_Select" if profile["pure_select"] else "MenuItem_SelectJump",
                    "candidate_offset": clone_offset, "length": sum(len(data) for _, data in clone),
                    "object_id_map": {str(old): new for old, new in mapping.items()}},
        "string_pool": {"format": "nul_terminated_utf8_offsets; original_pool_prefix_plus_private_strings",
                        "original_length": len(original_pool), "original_sha256": digest(original_pool),
                        "added": pool.added,
                        "unclassified_property_string_refs": "not inferred; covered by per-record unresolved gates"},
        "budget": {"before_header_length": len(stock[0].data), "after_header_length": len(new_header),
                   "objects": after_header["objects"], "group_entries": len(after_header["groups"]),
                   "clip_entries": len(after_header["clip_property_counts"]),
                   "property_entries": len(after_header["property_key_counts"]),
                   "donor_delta": delta},
        "record_locations": locations, "typed_changes": remapper.changes,
        "typed_insertions": remapper.insertions,
        "shared_ui_dependency_evidence": shared_evidence,
        "typed_object_fields": remapper.object_fields, "typed_string_fields": remapper.string_fields,
        "decoded_property_records": remapper.decoded_property_records,
        "native_property_schemas": property_schemas,
        "fixed_popup": fixed_popup,
        "unresolved": unresolved,
        "non_outputs": ["firmware image", "VSHL", "AutoRun", "installer", "transport", "runtime hooks"],
    }
    return candidate, bytes(pool.data), manifest


def write_artifacts(directory, candidate, pool, manifest):
    directory = Path(directory)
    check(not directory.exists(), "output directory must be new; refusing to overwrite")
    # Pre-encode evidence before creating any outputs; no generated source/installer files.
    encoded = json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"
    directory.mkdir()
    for name, data in zip(NAMES, (candidate, pool, encoded)):
        with (directory / name).open("xb") as output:
            output.write(data)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seg0", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="new output directory; existing directories are refused")
    parser.add_argument("--audit-module", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="pure-fixed-gated",
                        help="pure-fixed-gated is the intended fixed-width OFF/ON candidate; older profiles are comparisons")
    args = parser.parse_args(argv)
    try:
        audit = load_audit(args.audit_module)
        with args.seg0.open("rb") as input_file:
            source = input_file.read(audit.SEG0_SIZE + 1)
        candidate, pool, manifest = build_candidate(source, audit, args.profile)
        manifest["audit_module_sha256"] = digest(args.audit_module.read_bytes())
        manifest["builder_sha256"] = digest(Path(__file__).read_bytes())
        write_artifacts(args.output, candidate, pool, manifest)
    except (OSError, ValueError, ImportError) as exc:
        print("candidate failed: %s" % exc, file=sys.stderr)
        return 2
    print(json.dumps({"status": manifest["status"], "output": str(args.output.resolve()),
                      "page_length": len(candidate), "unresolved_count": len(manifest["unresolved"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
