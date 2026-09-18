"""Synthetic schema tests plus optional explicit pinned-seg0 transform tests."""

import argparse
from copy import deepcopy
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_menu_candidate as builder

SEG0 = None
AUDIT_MODULE = builder.DEFAULT_AUDIT


class FakeRecord:
    def __init__(self, offset, tag, body):
        self.offset, self.tag = offset, tag
        self.data = builder.words(tag, 8 + len(body)) + body


class SchemaTests(unittest.TestCase):
    def test_ids_are_deterministic_collision_checked_and_bounded(self):
        self.assertEqual(builder.allocate_ids([1, 16, 122, 345], [122, 16]), {122: 346, 16: 347})
        for ids, donors in (([1, 1], [1]), ([1], [2]), ([1], [1, 1]), ([65535], [65535]), ([0], [0])):
            with self.subTest(ids=ids, donors=donors), self.assertRaises(builder.CandidateError):
                builder.allocate_ids(ids, donors)

    def test_private_pool_preserves_old_offsets(self):
        original = b"\0\0\0\0stock\0\0\0"
        pool = builder.PrivatePool(original)
        offset = pool.intern("MV_fpLossless")
        self.assertGreaterEqual(offset, len(original))
        self.assertEqual(pool.resolve(4), "stock")
        self.assertEqual(pool.resolve(offset), "MV_fpLossless")
        self.assertEqual(pool.intern("MV_fpLossless"), offset)
        self.assertEqual(pool.data[:len(original)], original)
        for bad in (-1, len(pool.data), 0xFFFFFFFF):
            with self.subTest(bad=bad), self.assertRaises(builder.CandidateError):
                pool.resolve(bad)

    def test_event_owner_is_at_24_not_20_and_decoys_are_untouched(self):
        # tag 10006: component, property count, flags, instance name, owner, local ID, mask, body.
        pool = builder.PrivatePool(b"event\0\0\0")
        remap = builder.Remapper(pool, {16: 90}, {16})
        source = FakeRecord(123, 0x10006, builder.words(0, 1, 0, 0xFFFFFFFF, 16, 16, 1, 16))
        result = remap.transform(source)
        self.assertEqual(builder.u32(result, 20), 0xFFFFFFFF)
        self.assertEqual(builder.u32(result, 24), 90)
        self.assertEqual(builder.u32(result, 28), 16)  # Component-local ID, not object ID.
        self.assertEqual(builder.u32(result, 36), 16)  # Untyped body; not globally replaced.
        self.assertEqual(remap.unresolved[0]["code"], "UNTYPED_COMPONENT_PROPERTY_BODY")
        self.assertEqual(remap.unresolved[0]["body_offset"], 36)

    def test_unknown_typed_object_reference_fails(self):
        pool = builder.PrivatePool(b"event\0\0\0")
        remap = builder.Remapper(pool, {16: 90}, {16})
        source = FakeRecord(123, 0x10006, builder.words(0, 1, 0, 0xFFFFFFFF, 999, 1, 1, 0))
        with self.assertRaisesRegex(builder.CandidateError, "unresolved typed object"):
            remap.transform(source)

    def test_typed_properties_remap_only_object_type_and_preserve_string_flag(self):
        pool = builder.PrivatePool(b"test\0\0\0\0name\0\0\0\0")
        schema = {"test": [{"kind": 9, "name": "enum"}, {"kind": 14, "name": "object-id"},
                           {"kind": 1, "name": "float"}, {"kind": 11, "name": "string"}]}
        remap = builder.Remapper(pool, {16: 90}, {16}, schema)
        source = FakeRecord(123, 0x10009, builder.words(0, 4, 0xFFFFFFFF, 16, 1, 1, 15, 16, 16, 16, 8) + b"\x01")
        result = remap.transform(source)
        self.assertEqual(builder.u32(result, 20), 90)
        self.assertEqual(builder.u32(result, 36), 16)
        self.assertEqual(builder.u32(result, 40), 90)
        self.assertEqual(builder.u32(result, 44), 16)
        self.assertEqual(builder.u32(result, 48), 8)
        self.assertEqual(result[52], 1)
        self.assertEqual(remap.unresolved, [])
        self.assertTrue(remap.decoded_property_records[0]["body_fully_consumed"])

    def test_unknown_tag_fails_instead_of_guessing(self):
        remap = builder.Remapper(builder.PrivatePool(b"\0" * 4), {16: 90}, {16})
        with self.assertRaisesRegex(builder.CandidateError, "no donor schema"):
            remap.transform(FakeRecord(0, 0x123456, b""))

    def test_mask_bits_beyond_descriptor_count_fail(self):
        pool = builder.PrivatePool(b"test\0\0\0\0")
        schema = {"test": [{"kind": 9, "name": "enum"}]}
        remap = builder.Remapper(pool, {16: 90}, {16}, schema)
        record = FakeRecord(123, 0x10009, builder.words(0, 1, 0xFFFFFFFF, 16, 1, 1, 0x80000001, 7))
        with self.assertRaisesRegex(builder.CandidateError, "mask sets bits beyond"):
            remap.transform(record)

    def test_pure_profile_rejects_unlisted_foreign_property_reference(self):
        pool = builder.PrivatePool(b"test\0\0\0\0")
        schema = {"test": [{"kind": 14, "name": "object-id"}]}
        remap = builder.Remapper(pool, {16: 90}, {16, 37}, schema, builder.PROFILES["pure-select-gated"])
        record = FakeRecord(123, 0x10009, builder.words(0, 1, 0xFFFFFFFF, 16, 1, 1, 1, 37))
        with self.assertRaisesRegex(builder.CandidateError, "foreign-page typed object"):
            remap.transform(record)

    def test_existing_output_directory_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(builder.CandidateError, "refusing to overwrite"):
                builder.write_artifacts(Path(directory), b"page", b"pool", {})
            self.assertEqual(list(Path(directory).iterdir()), [])


class FirmwareCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if SEG0 is None:
            raise unittest.SkipTest("pass --seg0 for pinned-firmware builder tests")
        cls.audit = builder.load_audit(AUDIT_MODULE)
        cls.source = SEG0.read_bytes()
        cls.page, cls.pool, cls.manifest = builder.build_candidate(cls.source, cls.audit, "audio-gated")
        cls.records = cls.audit.records(cls.page, 0, len(cls.page))
        cls.by_offset = {record.offset: record for record in cls.records}
        cls.strings = builder.PrivatePool(cls.pool)

    def locations(self, source, provenance=None):
        return [entry for entry in self.manifest["record_locations"]
                if entry["source_record"] == "0x%08X" % source
                and (provenance is None or entry["provenance"] == provenance)]

    def clone_record(self, source):
        location = self.locations(source, "cloned_fourth_row_gated")[0]
        return self.by_offset[location["candidate_offset"]]

    def test_actual_full_page_and_private_pool_exist(self):
        self.assertEqual(len(self.page), 181976)
        self.assertEqual(len(self.records), 1579)
        self.assertEqual(self.manifest["outputs"][builder.NAMES[0]]["sha256"], builder.digest(self.page))
        self.assertEqual(self.manifest["outputs"][builder.NAMES[1]]["sha256"], builder.digest(self.pool))
        original = self.source[self.audit.POOL:self.audit.POOL_END]
        self.assertEqual(self.pool[:len(original)], original)

    def test_stock_records_preserved_except_three_exact_structural_edits(self):
        changed = []
        for entry in self.manifest["record_locations"]:
            if entry["provenance"] == "cloned_fourth_row_gated":
                continue
            source_offset = int(entry["source_record"], 16) - 0xC0000000
            original_length = builder.u32(self.source, source_offset + 4)
            original = self.source[source_offset:source_offset + original_length]
            output = self.by_offset[entry["candidate_offset"]].data
            if original != output:
                changed.append(source_offset)
        self.assertEqual(changed, [self.audit.PAGE_START, self.audit.MODE_CHANGE, self.audit.B2_OBJECT])
        original_audio = b"".join(self.by_offset[e["candidate_offset"]].data
                                   for e in self.manifest["record_locations"]
                                   if e["provenance"] == "stock_unchanged"
                                   and self.audit.DONOR_START <= int(e["source_record"], 16) - 0xC0000000 < self.audit.DONOR_END)
        self.assertEqual(builder.digest(original_audio), self.audit.DONOR_SHA256)

    def test_fourth_row_graph_modechange_and_geometry(self):
        objects = self.audit.parse_objects(self.records, self.strings.resolve)
        root = self.manifest["new_row"]["root_id"]
        self.assertEqual(len(objects), 216)
        self.assertEqual(objects[116]["child_count"], 7)
        self.assertEqual(objects[root]["parent_id"], 116)
        self.assertEqual(objects[root]["name"], "fpLossless_Row_GATED")
        mode = self.locations(0xC20318F7, "stock_modified")[0]
        # Audit's stock-specific parser permits exactly two states/zero transitions,
        # and accepts the new seven-reference length without firmware execution.
        refs = self.audit.parse_mode_change(self.by_offset[mode["candidate_offset"]])
        self.assertEqual(refs[-1], [root, 1])
        self.assertEqual(len(refs), 7)
        geometry = self.audit.parse_clip(self.clone_record(0xC204DB16), self.strings.resolve)
        properties = {p["name"]: p for p in geometry["properties"]}
        self.assertEqual(properties["is-visible"]["keys"], [{"time": 0, "value": 0}, {"time": 66, "value": 1}])
        self.assertEqual(properties["position"]["keys"][-1], {"time": 66, "value": 243.0})

    def test_all_recorded_typed_remaps_match_candidate_bytes(self):
        mapping = {int(old): new for old, new in self.manifest["new_row"]["object_id_map"].items()}
        original_ids = set(self.audit.parse_objects(self.audit.records(self.source, self.audit.PAGE_START, self.audit.PAGE_END),
                                                    lambda offset: self.audit.pool_string(self.source, offset)))
        self.assertTrue(set(mapping.values()).isdisjoint(original_ids))
        for field in self.manifest["typed_object_fields"]:
            cloned = self.clone_record(int(field["source_record"], 16))
            self.assertEqual(cloned.word(field["field_offset"]), field["new"])
            self.assertEqual(field["new"], mapping.get(field["old"], field["old"]))
        for field in self.manifest["typed_string_fields"]:
            cloned = self.clone_record(int(field["source_record"], 16))
            self.assertEqual(self.strings.resolve(cloned.word(field["field_offset"])), field["text"])

    def test_known_audio_side_effects_redirected_without_claiming_pure_toggle(self):
        for source, (offset, old, private) in builder.PRIVATE_FIELDS.items():
            clone = self.clone_record(source + 0xC0000000)
            self.assertEqual(self.strings.resolve(clone.word(offset)), private)
        codes = {item["code"] for item in self.manifest["unresolved"]}
        self.assertTrue({"PURE_TOGGLE_NOT_PROVEN", "NAVIGATION_NOT_PROVEN",
                         "PRIVATE_VARIABLE_UNREGISTERED", "NO_RUNTIME_RESOURCE_ADAPTER"} <= codes)
        self.assertNotIn("UNTYPED_COMPONENT_PROPERTY_BODY", codes)
        self.assertFalse(self.manifest["deployable"])
        self.assertTrue(self.manifest["structural_checks"]["complete_typed_payload_remap"])
        self.assertFalse(self.manifest["structural_checks"]["pure_select_widget_structure"])
        self.assertFalse(self.manifest["structural_checks"]["pure_toggle_runtime_verified"])

    def test_unaligned_menu_level1_and_focus_object_fields_are_typed_remaps(self):
        mapping = self.manifest["new_row"]["object_id_map"]
        menu_level1 = self.clone_record(0xC204DC51)
        self.assertEqual(self.strings.resolve(menu_level1.word(36)), "MENU_Level1")
        self.assertEqual(menu_level1.data[40], 0)  # type B includes a one-byte flag.
        self.assertEqual(menu_level1.word(41), 1)  # source-type enum: ObjectID.
        self.assertEqual(menu_level1.word(45), mapping["28971"])
        focus_object = self.clone_record(0xC204E2B6)
        self.assertEqual(focus_object.word(36), 4)  # FocusObject enum stays unchanged.
        self.assertEqual(focus_object.word(40), mapping["28977"])
        # GoPrevious and default GoNext have no object references in their masks.
        for source in (0xC204DD87, 0xC204DE0D):
            cloned = self.clone_record(source)
            old = source - 0xC0000000
            length = builder.u32(self.source, old + 4)
            self.assertEqual(cloned.data[32:], self.source[old + 32:old + length])

    def test_original_reservations_and_exact_added_budget(self):
        before = self.audit.parse_header(self.audit.records(self.source, self.audit.PAGE_START, self.audit.PAGE_END)[0],
                                        lambda offset: self.audit.pool_string(self.source, offset))
        after = self.audit.parse_header(self.records[0], self.strings.resolve)
        for key in ("groups", "clip_property_counts", "property_key_counts", "trailing_budget"):
            self.assertEqual(after[key][:len(before[key])], before[key])
        self.assertEqual((len(self.records[0].data), after["objects"], len(after["groups"]),
                          len(after["clip_property_counts"]), len(after["property_key_counts"])), (3352, 216, 60, 200, 403))
        delta = self.manifest["budget"]["donor_delta"]["component_counts"]
        for kind, count in before["component_counts"].items():
            self.assertEqual(after["component_counts"][kind], count + delta.get(kind, 0))

    def test_deterministic_candidate_and_manifest(self):
        page, pool, manifest = builder.build_candidate(self.source, self.audit, "audio-gated")
        self.assertEqual((page, pool, manifest), (self.page, self.pool, self.manifest))

    def test_wrong_source_hash_cannot_build(self):
        modified = bytearray(self.source)
        modified[0] ^= 1
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            builder.build_candidate(modified, self.audit)

    def test_artifacts_are_gated_resource_fragments_only(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "candidate"
            builder.write_artifacts(target, self.page, self.pool, self.manifest)
            self.assertEqual(sorted(path.name for path in target.iterdir()), sorted(builder.NAMES))
            self.assertEqual((target / builder.NAMES[0]).read_bytes(), self.page)
            self.assertEqual((target / builder.NAMES[1]).read_bytes(), self.pool)
            with self.assertRaisesRegex(builder.CandidateError, "refusing to overwrite"):
                builder.write_artifacts(target, self.page, self.pool, deepcopy(self.manifest))


class PureSelectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if SEG0 is None:
            raise unittest.SkipTest("pass --seg0 for pure-select candidate tests")
        cls.audit = builder.load_audit(AUDIT_MODULE)
        cls.source = SEG0.read_bytes()
        cls.page, cls.pool, cls.manifest = builder.build_candidate(cls.source, cls.audit, "pure-select-gated")
        cls.records = cls.audit.records(cls.page, 0, len(cls.page))
        cls.by_offset = {record.offset: record for record in cls.records}
        cls.strings = builder.PrivatePool(cls.pool)

    def clone(self, address):
        location = next(entry for entry in self.manifest["record_locations"]
                        if entry["source_record"] == "0x%08X" % address
                        and entry["provenance"] == "cloned_fourth_row_gated")
        return self.by_offset[location["candidate_offset"]]

    def test_explicit_old_profile_is_real_pure_select_with_expanded_page(self):
        self.assertEqual(self.manifest["profile"], "pure-select-gated")
        self.assertEqual((len(self.page), len(self.records)), (179826, 1540))
        objects = self.audit.parse_objects(self.records, self.strings.resolve)
        self.assertEqual(len(objects), 214)
        self.assertTrue(self.manifest["structural_checks"]["complete_typed_payload_remap"])
        self.assertTrue(self.manifest["structural_checks"]["pure_select_widget_structure"])
        self.assertFalse(self.manifest["deployable"])
        self.assertFalse(self.manifest["runtime_tested"])
        self.assertFalse(any(obj["name"] == "JumpEvent" for obj in
                             self.audit.parse_objects([self.clone(int(e["source_record"], 16)) for e in self.manifest["record_locations"]
                                                       if e["provenance"] == "cloned_fourth_row_gated"], self.strings.resolve).values()))

    def test_literal_title_off_on_and_animation_values(self):
        for address, text in ((0xC216DD72, "OFF"), (0xC2170209, "ON"),
                              (0xC2172640, "Lossless RAW"), (0xC21727CD, "OFF")):
            record = self.clone(address)
            self.assertEqual(self.strings.resolve(record.word(32)), text)
            self.assertEqual(record.data[36], 0)
        for address, expected in ((0xC2172735, {"Lossless RAW"}), (0xC21728BE, {"OFF", "ON"})):
            clip = self.audit.parse_clip(self.clone(address), self.strings.resolve)
            values = {self.strings.resolve(key["value"]) for prop in clip["properties"] if prop["name"] == "text" for key in prop["keys"]}
            self.assertEqual(values, expected)

    def test_binary_list_and_insertion_provenance_without_changing_animation_counter(self):
        value = self.clone(0xC216D3EB)
        self.assertEqual((len(value.data), value.word(28)), (48, 15))
        self.assertEqual(value.data[32:], builder.words(0, 0x3F800000, 0, 1))
        insertion = self.manifest["typed_insertions"]
        self.assertEqual(len(insertion), 1)
        self.assertEqual((insertion[0]["source_record"], insertion[0]["field_offset"], insertion[0]["length"]),
                         ("0xC216D3EB", 32, 12))
        self.assertEqual(bytes.fromhex(insertion[0]["hex"]), value.data[32:44])
        self.assertEqual(insertion[0]["values"], {"min-value": 0.0, "max-value": 1.0, "value": 0.0})
        # All other controlValue masks/values are source-exact, including root max=7.
        for entry in self.manifest["decoded_property_records"]:
            if entry["component"] != "controlValue" or entry["source_record"] == "0xC216D3EB":
                continue
            address = int(entry["source_record"], 16)
            record = self.clone(address)
            offset = address - 0xC0000000
            self.assertEqual(record.data[28:], self.source[offset + 28:offset + builder.u32(self.source, offset + 4)])

    def test_only_explicit_parent_and_four_verified_shared_refs_are_external(self):
        mapping = {int(old): new for old, new in self.manifest["new_row"]["object_id_map"].items()}
        external = []
        for field in self.manifest["typed_object_fields"]:
            record = self.clone(int(field["source_record"], 16))
            self.assertEqual(record.word(field["field_offset"]), field["new"])
            if field["scope"] == "explicit_reparent_to_mainb2":
                self.assertEqual((field["old"], field["new"]), (196, 116))
            elif field["scope"] == "verified_shared_ui_dependency":
                external.append((int(field["source_record"], 16) - 0xC0000000, field["old"]))
                self.assertEqual(field["new"], field["old"])
            else:
                self.assertEqual(field["new"], mapping.get(field["old"], field["old"]))
                self.assertTrue(field["old"] in mapping or field["old"] == 0)
        self.assertEqual(sorted(external), sorted((address, owner) for address, (owner, _) in builder.SHARED_CALLS.items()))
        self.assertEqual(len(self.manifest["shared_ui_dependency_evidence"]), 6)

    def test_shared_dependency_byte_tamper_fails(self):
        modified = bytearray(self.source)
        modified[0x2035EE6 + 28] ^= 1
        profile = builder.PROFILES["pure-select-gated"]
        donor = self.audit.records(modified, profile["page_start"], profile["page_end"])
        target = self.audit.records(modified, self.audit.PAGE_START, self.audit.PAGE_END)
        with self.assertRaisesRegex(builder.CandidateError, "dependency byte fingerprint"):
            builder.validate_shared_dependencies(modified, self.audit, donor, target, self.strings.resolve)

    def test_stock_audio_unchanged_and_only_three_original_structural_edits(self):
        changed, audio = [], []
        for entry in self.manifest["record_locations"]:
            if entry["provenance"] == "cloned_fourth_row_gated":
                continue
            offset = int(entry["source_record"], 16) - 0xC0000000
            record = self.by_offset[entry["candidate_offset"]]
            original = self.source[offset:offset + builder.u32(self.source, offset + 4)]
            if record.data != original:
                changed.append(offset)
            if self.audit.DONOR_START <= offset < self.audit.DONOR_END:
                audio.append(record.data)
        self.assertEqual(changed, [self.audit.PAGE_START, self.audit.MODE_CHANGE, self.audit.B2_OBJECT])
        self.assertEqual(builder.digest(b"".join(audio)), self.audit.DONOR_SHA256)

    def test_pure_geometry_budget_and_remaining_gates(self):
        self.assertEqual(self.clone(0xC216C8DC).word(36), 0x43730000)
        clip = self.audit.parse_clip(self.clone(0xC216C904), self.strings.resolve)
        self.assertEqual(clip["properties"][0]["keys"], [{"time": 0, "value": 0}, {"time": 66, "value": 1}])
        budget = self.manifest["budget"]
        self.assertEqual((budget["after_header_length"], budget["objects"], budget["group_entries"],
                          budget["clip_entries"], budget["property_entries"]), (3288, 214, 58, 197, 396))
        codes = {gate["code"] for gate in self.manifest["unresolved"]}
        self.assertNotIn("PURE_TOGGLE_NOT_PROVEN", codes)
        self.assertNotIn("UNTYPED_COMPONENT_PROPERTY_BODY", codes)
        self.assertTrue({"PRIVATE_ROW_STATE_UNRESOLVED", "PRIVATE_VARIABLE_UNREGISTERED", "NAVIGATION_NOT_PROVEN",
                         "NO_RUNTIME_RESOURCE_ADAPTER", "NATIVE_ALLOCATION_NOT_EXECUTED"} <= codes)


class FixedPopupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if SEG0 is None:
            raise unittest.SkipTest("pass --seg0 for fixed-popup candidate tests")
        cls.audit = builder.load_audit(AUDIT_MODULE)
        cls.source = SEG0.read_bytes()
        cls.page, cls.pool, cls.manifest = builder.build_candidate(cls.source, cls.audit)
        cls.records = cls.audit.records(cls.page, 0, len(cls.page))
        cls.by_offset = {record.offset: record for record in cls.records}
        cls.strings = builder.PrivatePool(cls.pool)

    def clone(self, address):
        location = next(entry for entry in self.manifest["record_locations"]
                        if entry["source_record"] == "0x%08X" % address
                        and entry["provenance"] == "cloned_fourth_row_gated")
        return self.by_offset[location["candidate_offset"]]

    def test_default_is_fixed_and_static_gate_only_is_closed(self):
        self.assertEqual(self.manifest["profile"], "pure-fixed-gated")
        self.assertEqual((len(self.page), len(self.records)), (179725, 1538))
        self.assertTrue(self.manifest["structural_checks"]["private_fixed_popup_without_stock_sync"])
        self.assertTrue(self.manifest["structural_checks"]["complete_typed_payload_remap"])
        codes = {gate["code"] for gate in self.manifest["unresolved"]}
        self.assertNotIn("PRIVATE_ROW_STATE_UNRESOLVED", codes)
        self.assertTrue({"PRIVATE_VARIABLE_UNREGISTERED", "NAVIGATION_NOT_PROVEN",
                         "PRIVATE_LABEL_RENDERING_NOT_PROVEN", "NO_RUNTIME_RESOURCE_ADAPTER",
                         "NATIVE_ALLOCATION_NOT_EXECUTED"} <= codes)
        self.assertFalse(self.manifest["deployable"])
        self.assertFalse(self.manifest["runtime_tested"])
        self.assertFalse(self.manifest["camera_accessed"])

    def test_focus_sync_explicitly_false_and_escape_preserved(self):
        action = self.clone(0xC216CA4D)
        self.assertEqual((len(action.data), action.word(4)), (44, 44))
        self.assertEqual(action.data[32:], builder.words(0x22, 0, 0))
        self.assertEqual(self.strings.resolve(action.word(8)), "controlAppState")
        self.assertEqual((action.word(24), action.word(28)), (1, 4))
        escape = self.clone(0xC216CE63)
        self.assertEqual(escape.data[24:], self.source[0x216CE63 + 24:0x216CE63 + len(escape.data)])

    def test_width_watcher_removed_and_component_budget_decremented(self):
        clone_addresses = {entry["source_record"] for entry in self.manifest["record_locations"]
                           if entry["provenance"] == "cloned_fourth_row_gated"}
        self.assertNotIn("0xC216CF50", clone_addresses)
        self.assertNotIn("0xC216CF7D", clone_addresses)
        self.assertEqual(self.clone(0xC216C948).word(8), 15)
        original = self.audit.records(self.source, 0x216C8B8, 0x2172BC6)
        old_counts = self.audit.component_counts(original, self.strings.resolve)
        delta = self.manifest["budget"]["donor_delta"]["component_counts"]
        for name, value in old_counts.items():
            self.assertEqual(delta[name], value - (name in {"appVariableChangeEvent", "controlAnimation"}))
        before = self.audit.parse_header(self.audit.records(self.source, self.audit.PAGE_START, self.audit.PAGE_END)[0],
                                        self.strings.resolve)
        after = self.audit.parse_header(self.records[0], self.strings.resolve)
        for name, value in before["component_counts"].items():
            self.assertEqual(after["component_counts"][name], value + delta.get(name, 0))
        self.assertEqual(self.manifest["fixed_popup"]["record_count_delta"], -2)
        self.assertEqual(self.manifest["fixed_popup"]["object_count_delta"], 0)
        self.assertEqual(self.manifest["fixed_popup"]["group_clip_key_budget_delta"], 0)

    def test_no_shared_width_refs_or_unresolved_private_strings(self):
        for field in self.manifest["typed_string_fields"]:
            self.assertNotEqual(field["text"], "submenu_width")
            self.assertNotIn("UNRESOLVED", field["text"])
            self.assertNotEqual(field["text"], "submenu_width_NoIcon")
        self.assertFalse(any("UNRESOLVED" in name for name in self.manifest["string_pool"]["added"]))
        group = self.clone(0xC216D1FF)
        self.assertEqual(self.strings.resolve(group.word(20)), "fpLossless_FixedWidth")
        self.assertEqual(self.strings.resolve(group.word(28)), "fpLossless_FixedWidth")

    def test_initial_geometry_is_already_fixed_without_variable_notification(self):
        for field in self.manifest["fixed_popup"]["base_fields"]:
            data = self.clone(int(field["address"], 16)).data
            self.assertEqual(struct.unpack_from(">f", data, field["offset"])[0], field["new"])
        self.assertEqual(self.manifest["fixed_popup"]["width"], 320)
        self.assertIn("host design", self.manifest["fixed_popup"]["choice"])

    def test_every_width_animation_key_is_constant(self):
        for evidence in self.manifest["fixed_popup"]["constant_clips"]:
            clip = self.audit.parse_clip(self.clone(int(evidence["address"], 16)), self.strings.resolve)
            prop = next(p for p in clip["properties"] if p["component_ref"] == evidence["component"]
                        and p["name"] == evidence["property"] and p["dimension"] == evidence["dimension"])
            self.assertEqual(len(prop["keys"]), evidence["key_count"])
            self.assertEqual({p["value"] for p in prop["keys"]}, {evidence["constant"]})

    def test_only_three_original_records_changed(self):
        changed = []
        for entry in self.manifest["record_locations"]:
            if entry["provenance"] == "cloned_fourth_row_gated":
                continue
            offset = int(entry["source_record"], 16) - 0xC0000000
            original = self.source[offset:offset + builder.u32(self.source, offset + 4)]
            if self.by_offset[entry["candidate_offset"]].data != original:
                changed.append(offset)
        self.assertEqual(changed, [self.audit.PAGE_START, self.audit.MODE_CHANGE, self.audit.B2_OBJECT])
        self.assertEqual(self.pool[:self.audit.POOL_END - self.audit.POOL],
                         self.source[self.audit.POOL:self.audit.POOL_END])

    def test_literal_choices_and_binary_control_preserved(self):
        for address, text in ((0xC216DD72, "OFF"), (0xC2170209, "ON"), (0xC2172640, "Lossless RAW")):
            record = self.clone(address)
            self.assertEqual(self.strings.resolve(record.word(32)), text)
            self.assertEqual(record.data[36], 0)
        value = self.clone(0xC216D3EB)
        self.assertEqual(value.data[28:], builder.words(15, 0, 0x3F800000, 0, 1))

    def test_fixed_candidate_is_deterministic(self):
        result = builder.build_candidate(self.source, self.audit, "pure-fixed-gated")
        self.assertEqual(result, (self.page, self.pool, self.manifest))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--seg0", type=Path)
    parser.add_argument("--audit-module", type=Path, default=builder.DEFAULT_AUDIT)
    args, rest = parser.parse_known_args()
    SEG0, AUDIT_MODULE = args.seg0, args.audit_module
    unittest.main(argv=[sys.argv[0]] + rest)
