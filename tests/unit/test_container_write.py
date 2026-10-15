"""U-10, write parts (SPEC 9.3, tier T2; gate G5): container variants seen through ``export_map_variant``.

The expected bytes of every case are built by the INDEPENDENT fixture builder: the spec of the template fixture with the
slots and quota rows of the golden edit (W1 E1 moves slot 1, E3 deletes slot 5) put in, so the builder decides what the file
looks like (hash recipe, stored-length byte order, ``_eof`` byte order, ``_cmp`` or ``_fsm`` or trailer, version 32 and its
128 bits, the capacity length class) and the library has to produce exactly that.

* ``_cmp``: an unmodified save is the wrapper; a modified save expands it, re-stamps the three lengths and warns;
* ``_fsm``: kept by default (warning), ``fsm_policy = DROP`` removes it (also from a clean template: that counts as a change);
* version 32, little-endian stored length, little-endian ``_eof``, ``plain_le32``, the all-zero hash, the stored-length
  classes ``capacity`` and ``zero``, a trailer after ``_eof``;
* the hash flavour of the template is reproduced; an unknown hash falls back to salted with a warning; ``hash_policy`` forces
  a recipe (for an edit, and for a clean template, which is then re-hashed);
* the shape ``other`` is readable and passes through but refuses every modification.
"""
import copy
import os
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import helpers_g5 as h  # noqa: E402

from mvarlib import errors  # noqa: E402
from mvarlib.model import MapVariant  # noqa: E402


def builder():
    return h.build_modules()[0]


def plain_spec(template_name):
    """The template's spec with the ``_cmp`` wrapper taken off (the expanded plain form)."""
    spec = copy.deepcopy(builder().load_spec(template_name))
    if spec["container"]["shape"].startswith("cmp"):
        spec["container"]["shape"] = spec["container"]["shape"].replace("cmp4", "plain4")
        spec["container"]["cmp"] = None
        spec["container"]["eof"] = {"endian": ">", "value": None}
    return spec


def expected_after(template_name, golden="w1_E1", container=None, hash_recipe=None):
    """What the independent builder makes of ``template_name`` after the golden edit ``golden``: ``w1_E1`` moves slot 1 by one
    unit in x (cell 524288 -> 526473), ``w1_E3`` deletes slot 5 (quota row 61 -> 0), ``w1_E2`` adds the block of E2 in slot 0
    (quota row 70 -> 3). Only those slots and rows are touched, so a template with another label table or header stays itself.
    ``container`` and ``hash_recipe`` override parts of the container description."""
    build = builder()
    spec = plain_spec(template_name)
    gold = build.load_spec(golden)
    if golden == "w1_E1":
        for s in spec["slots"]:
            if s["index"] == 1:
                s["pos"] = [526473, s["pos"][1], s["pos"][2]]
    elif golden == "w1_E3":
        spec["slots"] = [s for s in spec["slots"] if s["index"] != 5]
        spec["quotas"]["rows"]["61"] = [0, 1, 0]
    elif golden == "w1_E2":
        spec["slots"].insert(0, copy.deepcopy([s for s in gold["slots"] if s["index"] == 0][0]))
        spec["quotas"]["rows"]["70"] = [0, 16, 3]
    else:
        raise ValueError(golden)
    if container:
        spec["container"].update(container)
    if hash_recipe:
        spec["container"]["hash"] = {"recipe": hash_recipe}
    return build.build(spec).data


def move_slot_1(data, dx=1.0):
    objs = h.objects_for(data)
    pos = h.by_slot(objs, 1).position
    h.change(objs, 1, position=(pos[0] + dx, pos[1], pos[2]))
    return objs


def delete_slot_5(data):
    return h.without(h.objects_for(data), 5)


def codes_of(result):
    return h.codes(result.warnings)


class TestEveryVariantReproducesItsOwnLayout(unittest.TestCase):
    PLAIN = ("w1_minimal", "plain_le32", "le_length", "eof_le", "zero_hash", "length_capacity", "labels_compressed",
             "labels_uncompressed", "zero_labels", "fsm", "trailer")

    def test_a_move_keeps_every_container_property_of_the_template(self):
        for name in self.PLAIN + ("cmp", "cmp_fsm"):
            with self.subTest(name):
                data = h.g3.data(name)
                result = h.export(data, move_slot_1(data))
                self.assertTrue(result.ok, [e.message for e in result.errors])
                self.assertEqual(result.data, expected_after(name), "the builder's file for this template with slot 1 moved")

    def test_a_delete_changes_the_length_and_keeps_every_container_property(self):
        for name in self.PLAIN + ("cmp", "cmp_fsm"):
            with self.subTest(name):
                data = h.g3.data(name)
                result = h.export(data, delete_slot_5(data))
                self.assertTrue(result.ok, [e.message for e in result.errors])
                self.assertEqual(result.data, expected_after(name, "w1_E3"))

    def test_an_add_keeps_every_container_property(self):
        for name in ("plain_le32", "le_length", "eof_le", "length_capacity", "fsm", "trailer", "cmp"):
            with self.subTest(name):
                data = h.g3.data(name)
                objs = h.objects_for(data)
                objs.append(h.new_object("Added", position=h.cell_centre(h.g3.model(name), (1, 2, 3))))
                result = h.export(data, objs, **h.GATE)
                self.assertTrue(result.ok, [e.message for e in result.errors])
                self.assertEqual(result.data, expected_after(name, "w1_E2"))

    def test_unchanged_objects_return_the_template_bytes_for_every_variant(self):
        for name in self.PLAIN + ("cmp", "cmp_fsm", "v32"):
            with self.subTest(name):
                data = h.g3.data(name)
                result = h.export(data, h.objects_for(data))
                self.assertEqual(result.data, data)
                self.assertEqual(result.stats["mode"], "passthrough")


class TestCmp(unittest.TestCase):
    def test_unmodified_save_is_the_wrapper(self):
        data = h.g3.data("cmp")
        self.assertEqual(h.export(data, h.objects_for(data)).data, data)

    def test_a_modified_save_expands_and_restamps_the_three_lengths(self):
        data = h.g3.data("cmp")
        result = h.export(data, move_slot_1(data))
        out = result.data
        self.assertEqual(out, h.g3.data("w1_E1"))
        self.assertEqual(len(out), 29481)
        self.assertEqual(struct.unpack("<I", out[0x30 + 0x14:0x30 + 0x18])[0], 29481, "chdr fileLength")
        self.assertEqual(struct.unpack(">I", out[0x7318 + 12:0x7318 + 16])[0], 0x7318, "_eof value")
        self.assertEqual(h.decode(out)["header"]["file_length"], 29481, "the embedded fileLength")
        warning = [w for w in result.warnings if w.code == "W_CMP_EXPANDED"]
        self.assertEqual(len(warning), 1)
        self.assertEqual(MapVariant.from_bytes(out).shape, "plain4")

    def test_cmp_with_fsm_expands_and_keeps_the_signature_block(self):
        data = h.g3.data("cmp_fsm")
        result = h.export(data, move_slot_1(data))
        self.assertEqual(result.data, expected_after("cmp_fsm"))
        self.assertEqual(MapVariant.from_bytes(result.data).shape, "plain4+fsm")
        self.assertTrue({"W_CMP_EXPANDED", "W_FSM_STALE"} <= set(codes_of(result)))

    def test_force_reencode_of_a_cmp_template_is_the_expanded_form(self):
        data = h.g3.data("cmp")
        result = h.export(data, h.objects_for(data), force_reencode=True)
        self.assertEqual(result.data, h.g3.data("cmp_expanded"))
        self.assertIn("W_CMP_EXPANDED", codes_of(result))
        self.assertEqual(result.stats["mode"], "forced")


class TestFsm(unittest.TestCase):
    def test_a_modified_save_keeps_the_signature_block_verbatim_and_warns(self):
        data = h.g3.data("fsm")
        result = h.export(data, move_slot_1(data))
        self.assertEqual(result.data[:29481], h.g3.data("w1_E1"))
        self.assertEqual(result.data[29481:], data[29481:], "_fsm is kept verbatim")
        self.assertEqual([w.message for w in result.warnings if w.code == "W_FSM_STALE"],
                         ["The file-share signature block (_fsm) was kept unchanged. If MCC refuses the file, export again with fsm_policy = DROP."])

    def test_drop_after_an_edit_removes_it(self):
        data = h.g3.data("fsm")
        result = h.export(data, move_slot_1(data), fsm_policy="DROP")
        self.assertEqual(result.data, h.g3.data("w1_E1"))
        self.assertNotIn("W_FSM_STALE", codes_of(result))
        self.assertEqual(MapVariant.from_bytes(result.data).shape, "plain4")

    def test_drop_on_a_clean_template_counts_as_a_modification(self):
        data = h.g3.data("fsm")
        result = h.export(data, h.objects_for(data), fsm_policy="DROP")
        self.assertTrue(result.ok)
        self.assertEqual(result.data, h.g3.data(h.build_modules()[0].load_spec("fsm")["name"].replace("fsm", "w1_minimal")))
        self.assertNotEqual(result.data, data, "the shape without _fsm, never the template bytes")
        self.assertEqual(result.stats["mode"], "patched")
        self.assertEqual(len(result.data), 29481)

    def test_drop_on_a_template_without_fsm_changes_nothing(self):
        data = h.g3.data("w1_minimal")
        result = h.export(data, h.objects_for(data), fsm_policy="DROP")
        self.assertEqual(result.data, data)
        self.assertEqual(result.stats["mode"], "passthrough")

    def test_drop_on_cmp_with_fsm_keeps_the_unmodified_wrapper(self):
        """Only the signature block goes: the compressed block itself is unchanged, so its wrapper bytes are kept (SPEC 2.8)."""
        data = h.g3.data("cmp_fsm")
        result = h.export(data, h.objects_for(data), fsm_policy="DROP")
        self.assertEqual(result.data, h.g3.data("cmp"))
        self.assertEqual(MapVariant.from_bytes(result.data).shape, "cmp4")
        self.assertNotIn("W_CMP_EXPANDED", codes_of(result))
        edited = h.export(data, move_slot_1(data), fsm_policy="DROP")
        self.assertEqual(edited.data, h.g3.data("w1_E1"), "an edit expands the wrapper")
        self.assertIn("W_CMP_EXPANDED", codes_of(edited))

    def test_keep_on_a_clean_template_is_the_template(self):
        data = h.g3.data("fsm")
        self.assertEqual(h.export(data, h.objects_for(data), fsm_policy="KEEP").data, data)


class TestVersion32(unittest.TestCase):
    def test_the_128_bits_survive_an_edit(self):
        data = h.g3.data("v32")
        model = h.g3.model("v32")
        self.assertEqual(model.version, 32)
        result = h.export(data, move_slot_1(data))
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual(result.data, expected_after("v32"))
        before, after = h.decode(data), h.decode(result.data)
        self.assertEqual(before["guid"], after["guid"])
        self.assertEqual(after["body"]["version"], 32)

    def test_a_delete_and_an_add_with_the_guid_block(self):
        data = h.g3.data("v32")
        result = h.export(data, delete_slot_5(data))
        self.assertEqual(result.data, expected_after("v32", "w1_E3"))

    def test_a_guid_that_contradicts_the_version_is_still_written_back_and_warns(self):
        data = h.g3.data("guid_v32_absent")
        objs = h.objects_for(data)
        stock_slot = next(r.slot for r in h.g3.model("guid_v32_absent").objects() if r.stock)
        pos = h.by_slot(objs, stock_slot).position
        h.change(objs, stock_slot, position=(pos[0] + 1.0, pos[1], pos[2]))
        result = h.export(data, objs, keep_unrecognised_imported=True)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertIn("W_GUID_VERSION_MISMATCH", codes_of(result))
        again = MapVariant.from_bytes(result.data)
        self.assertEqual((again.version, again.hypothesis.guid), (32, False))
        data = h.g3.data("guid_v31_present")
        result = h.export(data, h.objects_for(data), keep_unrecognised_imported=True, force_reencode=True)
        self.assertEqual(result.data, data)


class TestHashFlavourReproduction(unittest.TestCase):
    def check_hash(self, data, recipe, endian=">"):
        """The stored SHA-1 is the recipe's digest over the stream up to the stored length (hashlib, the walker's table)."""
        raw = data[h.LENGTH_AT:h.LENGTH_AT + 4]
        length = struct.unpack(endian + "I", raw)[0]
        _b, selfcheck = h.build_modules()
        self.assertEqual(h.stored_hash(data), selfcheck.digest(recipe, h.stream_bytes(data), length), recipe)
        return length

    def test_salted_be32_is_reproduced(self):
        data = h.g3.data("w1_minimal")
        out = h.export(data, move_slot_1(data)).data
        self.check_hash(out, "salted_be32")

    def test_plain_le32_is_reproduced_on_edit_add_and_delete(self):
        data = h.g3.data("plain_le32")
        for objs in (move_slot_1(data), delete_slot_5(data), h.objects_for(data) + [h.new_object("N", position=(1.0, 1.0, 1.0))]):
            out = h.export(data, objs, **h.GATE).data
            length = self.check_hash(out, "plain_le32")
            self.assertEqual(length, (h.decode(out)["end"] + 7) // 8)
            self.assertEqual(MapVariant.from_bytes(out).flavour, (">", "plain_le32"))

    def test_little_endian_length_is_reproduced(self):
        data = h.g3.data("le_length")
        out = h.export(data, delete_slot_5(data)).data
        self.assertEqual(out[h.LENGTH_AT:h.LENGTH_AT + 4], struct.pack("<I", 598))
        self.check_hash(out, "salted_be32", "<")
        self.assertEqual(MapVariant.from_bytes(out).flavour, ("<", "salted_be32"))

    def test_little_endian_eof_is_reproduced_after_an_expansion_free_edit(self):
        data = h.g3.data("eof_le")
        out = h.export(data, move_slot_1(data)).data
        self.assertEqual(out[0x7318 + 12:0x7318 + 16], struct.pack("<I", 0x7318))
        self.assertEqual(MapVariant.from_bytes(out).blf.eof_endian, "<")

    def test_the_all_zero_hash_is_reproduced_and_reported(self):
        data = h.g3.data("zero_hash")
        result = h.export(data, move_slot_1(data))
        self.assertEqual(h.stored_hash(result.data), bytes(20))
        self.assertEqual(result.data, expected_after("zero_hash"))
        self.assertEqual([w.message for w in result.warnings if w.code == "I_HASH_ZERO"],
                         ["The template carries no SHA-1 (20 zero bytes, which KSoft.Blam documents for MCC-written game variants); none was written."])
        self.assertEqual(MapVariant.from_bytes(result.data).flavour, (">", "zero"))

    def test_an_unknown_hash_falls_back_to_salted_with_the_template_length_order_and_a_warning(self):
        data = bytearray(h.g3.data("le_length"))
        data[h.HASH_AT] ^= 0x55
        data = bytes(data)
        self.assertIsNone(MapVariant.from_bytes(data).flavour)
        result = h.export(data, move_slot_1(data))
        self.assertEqual([w.message for w in result.warnings if w.code == "W_HASH_UNKNOWN"],
                         ["The template's SHA-1 matches no known recipe; the salted recipe was written. Whether MCC checks it is unknown."])
        self.assertEqual(result.data, expected_after("le_length"), "salted recipe, little-endian length like the template")
        self.assertEqual(MapVariant.from_bytes(result.data).flavour, ("<", "salted_be32"))

    def test_the_unknown_fallback_is_not_used_for_a_known_plain_le32_file(self):
        data = h.g3.data("plain_le32")
        result = h.export(data, move_slot_1(data))
        self.assertNotIn("W_HASH_UNKNOWN", codes_of(result))

    def test_an_unknown_hash_on_a_clean_template_passes_through_unchanged(self):
        data = bytearray(h.g3.data("w1_minimal"))
        data[h.HASH_AT] ^= 0x55
        result = h.export(bytes(data), h.objects_for(bytes(data)))
        self.assertEqual(result.data, bytes(data))
        self.assertNotIn("W_HASH_UNKNOWN", codes_of(result))

    def test_capacity_length_class_stays_at_0x7000_and_hashes_the_whole_stream(self):
        data = h.g3.data("length_capacity")
        out = h.export(data, move_slot_1(data)).data
        self.assertEqual(h.stored_length(out), 0x7000)
        self.check_hash(out, "salted_be32")
        self.assertEqual(MapVariant.from_bytes(out).length_class, "capacity")
        out = h.export(data, delete_slot_5(data)).data
        self.assertEqual(h.stored_length(out), 0x7000, "the length does not follow the end bit in this class")
        self.assertEqual(out, expected_after("length_capacity", "w1_E3"))

    def zero_length_template(self):
        _b, selfcheck = h.build_modules()
        data = bytearray(h.g3.data("w1_minimal"))
        data[h.LENGTH_AT:h.LENGTH_AT + 4] = bytes(4)
        data[h.HASH_AT:h.HASH_AT + 20] = selfcheck.digest("salted_be32", h.stream_bytes(bytes(data)), 0x7000)
        return bytes(data)

    def test_the_zero_length_class_stays_four_zero_bytes(self):
        data = self.zero_length_template()
        model = MapVariant.from_bytes(data)
        self.assertEqual((model.length_class, model.flavour), ("zero", (">", "salted_be32")))
        out = h.export(data, move_slot_1(data)).data
        self.assertEqual(out[h.LENGTH_AT:h.LENGTH_AT + 4], bytes(4))
        _b, selfcheck = h.build_modules()
        self.assertEqual(h.stored_hash(out), selfcheck.digest("salted_be32", h.stream_bytes(out), 0x7000))
        self.assertEqual(MapVariant.from_bytes(out).length_class, "zero")
        out = h.export(data, delete_slot_5(data)).data
        self.assertEqual(out[h.LENGTH_AT:h.LENGTH_AT + 4], bytes(4))


class TestHashPolicy(unittest.TestCase):
    def check(self, data, recipe, endian=">"):
        length = struct.unpack(endian + "I", data[h.LENGTH_AT:h.LENGTH_AT + 4])[0]
        _b, selfcheck = h.build_modules()
        self.assertEqual(h.stored_hash(data), selfcheck.digest(recipe, h.stream_bytes(data), length))

    def test_a_forced_recipe_replaces_the_templates_on_an_edit(self):
        salted = h.g3.data("w1_minimal")
        out = h.export(salted, move_slot_1(salted), hash_policy="PLAIN_LE32").data
        self.assertEqual(out, expected_after("w1_minimal", hash_recipe="plain_le32"))
        self.check(out, "plain_le32")
        plain = h.g3.data("plain_le32")
        out = h.export(plain, move_slot_1(plain), hash_policy="SALTED_BE32").data
        self.assertEqual(out, expected_after("plain_le32", hash_recipe="salted_be32"))
        self.check(out, "salted_be32")

    def test_the_length_byte_order_of_the_template_is_kept_when_a_recipe_is_forced(self):
        data = h.g3.data("le_length")
        out = h.export(data, move_slot_1(data), hash_policy="PLAIN_LE32").data
        self.assertEqual(out, expected_after("le_length", container={"length": {"endian": "<", "mode": "ceil_end", "value": None}, "hash": {"recipe": "plain_le32"}}))
        self.assertEqual(out[h.LENGTH_AT:h.LENGTH_AT + 4], struct.pack("<I", 622))
        self.check(out, "plain_le32", "<")

    def test_a_forced_recipe_overrides_the_unknown_fallback_without_the_warning(self):
        data = bytearray(h.g3.data("w1_minimal"))
        data[h.HASH_AT] ^= 0x55
        out = h.export(bytes(data), move_slot_1(bytes(data)), hash_policy="PLAIN_LE32")
        self.assertNotIn("W_HASH_UNKNOWN", codes_of(out))
        self.assertEqual(out.data, expected_after("w1_minimal", hash_recipe="plain_le32"))

    def test_a_forced_recipe_replaces_the_zero_hash(self):
        data = h.g3.data("zero_hash")
        result = h.export(data, move_slot_1(data), hash_policy="SALTED_BE32")
        self.assertEqual(result.data, expected_after("w1_minimal"))
        self.assertNotIn("I_HASH_ZERO", codes_of(result))

    def test_a_forced_recipe_rehashes_a_clean_template(self):
        """A recipe that differs from the template's counts as a modification: the file is rewritten with the new hash only."""
        data = h.g3.data("w1_minimal")
        result = h.export(data, h.objects_for(data), hash_policy="PLAIN_LE32")
        self.assertTrue(result.ok)
        self.assertEqual(result.data, h.g3.data("plain_le32"))
        self.assertEqual(result.stats["mode"], "forced")
        changed = [i for i in range(len(data)) if data[i] != result.data[i]]
        self.assertTrue(all(h.HASH_AT <= i < h.HASH_AT + 20 for i in changed), "only the SHA-1 bytes differ")

    def test_the_templates_own_recipe_on_a_clean_template_is_a_passthrough(self):
        data = h.g3.data("w1_minimal")
        for policy in ("REPRODUCE", "SALTED_BE32"):
            result = h.export(data, h.objects_for(data), hash_policy=policy)
            self.assertEqual(result.data, data, policy)
            self.assertEqual(result.stats["mode"], "passthrough")
        plain = h.g3.data("plain_le32")
        self.assertEqual(h.export(plain, h.objects_for(plain), hash_policy="PLAIN_LE32").data, plain)

    def test_a_forced_recipe_with_fsm_drop_on_a_clean_template(self):
        data = h.g3.data("fsm")
        result = h.export(data, h.objects_for(data), hash_policy="PLAIN_LE32", fsm_policy="DROP")
        self.assertEqual(result.data, h.g3.data("plain_le32"))

    def test_cmp_template_with_a_forced_recipe(self):
        data = h.g3.data("cmp")
        result = h.export(data, h.objects_for(data), hash_policy="PLAIN_LE32")
        self.assertEqual(result.data, h.g3.data("plain_le32"))
        self.assertIn("W_CMP_EXPANDED", codes_of(result))

    def test_every_policy_value_is_checked(self):
        for policy in ("REPRODUCE", "SALTED_BE32", "PLAIN_LE32"):
            self.assertTrue(h.export(h.g3.data("w1_minimal"), h.objects_for(h.g3.data("w1_minimal")), hash_policy=policy).ok)
        for policy in ("", "salted_be32", "MD5", None):
            self.assertEqual(h.codes(h.export(h.g3.data("w1_minimal"), [], hash_policy=policy).errors), ["E_OPTION_INVALID"])


class TestTemplatesThatAreNotCanonical(unittest.TestCase):
    """A template whose derived fields are inconsistent (a wrong `_eof` value or `chdr` length) is edited in patched mode, which keeps
    those fields verbatim; only a forced re-encode repairs them. The export must not mistake that for a writer bug."""

    def test_a_wrong_eof_value_survives_an_edit_untouched(self):
        data = bytearray(h.g3.data("w1_minimal"))
        data[0x7318 + 12:0x7318 + 16] = struct.pack(">I", 0x7319)
        data = bytes(data)
        self.assertFalse(MapVariant.from_bytes(data).blf.eof_value_ok)
        result = h.export(data, move_slot_1(data))
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual(result.data[0x7318 + 12:0x7318 + 16], struct.pack(">I", 0x7319), "kept verbatim")
        self.assertEqual(result.data[:0x7318], h.g3.data("w1_E1")[:0x7318])
        forced = h.export(data, move_slot_1(data), force_reencode=True)
        self.assertEqual(forced.data[0x7318 + 12:0x7318 + 16], struct.pack(">I", 0x7318), "a forced re-encode repairs it")

    def test_a_wrong_chdr_length_survives_an_edit_untouched(self):
        data = bytearray(h.g3.data("w1_minimal"))
        data[0x30 + 0x14:0x30 + 0x18] = struct.pack("<I", 12345)
        data = bytes(data)
        result = h.export(data, h.without(h.objects_for(data), 5))
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual(struct.unpack("<I", result.data[0x30 + 0x14:0x30 + 0x18])[0], 12345)


class TestTrailer(unittest.TestCase):
    def test_a_trailer_after_eof_is_kept_and_reported_on_a_modified_save(self):
        data = h.g3.data("trailer")
        result = h.export(data, move_slot_1(data))
        self.assertEqual(result.data[29481:], bytes(512))
        self.assertEqual(result.data[:29481], h.g3.data("w1_E1"))
        self.assertEqual([w.message for w in result.warnings if w.code == "W_TRAILER_KEPT"],
                         ["512 bytes after the end-of-file block were kept unchanged."])

    def test_a_clean_save_has_no_trailer_warning(self):
        data = h.g3.data("trailer")
        result = h.export(data, h.objects_for(data))
        self.assertEqual(result.data, data)
        self.assertNotIn("W_TRAILER_KEPT", codes_of(result))

    def test_a_non_zero_trailer_is_kept_byte_for_byte(self):
        data = h.g3.data("w1_minimal") + bytes(range(256)) * 2
        result = h.export(data, move_slot_1(data))
        self.assertEqual(result.data[29481:], bytes(range(256)) * 2)


class TestShapeOther(unittest.TestCase):
    @staticmethod
    def template():
        data = h.g3.data("w1_minimal")
        unknown = b"abcd" + (16).to_bytes(4, "big") + (1).to_bytes(2, "big") + (1).to_bytes(2, "big") + bytes(4)
        cut = h.MVAR + 0x7028
        return data[:cut] + unknown + data[cut:]

    def test_it_is_readable_and_passes_through(self):
        data = self.template()
        self.assertEqual(MapVariant.from_bytes(data).shape, "other")
        result = h.export(data, h.objects_for(data))
        self.assertTrue(result.ok)
        self.assertEqual(result.data, data)

    def test_every_kind_of_modification_is_refused(self):
        data = self.template()
        message = "This file's block layout (_blf, chdr, mvar, abcd, _eof) cannot be modified safely."
        tries = [dict(objects=move_slot_1(data)), dict(objects=delete_slot_5(data)),
                 dict(objects=h.objects_for(data), force_reencode=True),
                 dict(objects=h.objects_for(data), hash_policy="PLAIN_LE32"),
                 dict(objects=h.objects_for(data) + [h.new_object("N", position=(1.0, 1.0, 1.0))], **h.GATE)]
        for kwargs in tries:
            with self.subTest(sorted(kwargs)):
                objs = kwargs.pop("objects")
                result = h.export(data, objs, **kwargs)
                self.assertFalse(result.ok)
                self.assertIsNone(result.data)
                self.assertIn(message, [e.message for e in result.errors])


class TestChunkVersions(unittest.TestCase):
    def test_halo_3_and_halo_4_chunk_versions_are_refused_with_the_template_message(self):
        for name, version in (("chunk_version_13", 13), ("chunk_version_50", 50)):
            data = h.g3.data(name)
            result = h.export(data, [])
            self.assertEqual([e.code for e in result.errors], ["E_TEMPLATE_UNREADABLE"])
            self.assertIn("The map variant block has chunk version %d; Halo: Reach uses 31 or 32 (50 and 51 are Halo 4, "
                          "12 to 14 are Halo 3)." % version, result.errors[0].message)
            self.assertIsNone(result.data)

    def test_a_game_variant_is_not_a_map_variant(self):
        import helpers_real
        sample = helpers_real.distinct_samples(helpers_real.load_samples())[0]
        result = h.export(sample.data, [])
        self.assertEqual(result.errors[0].message, "The imported map variant could not be read again: This is a game variant "
                                                   "(block 'mpvr'), not a map variant. Use File > Import for map variants only.")


if __name__ == "__main__":
    unittest.main()
