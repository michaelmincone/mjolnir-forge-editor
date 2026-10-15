"""U-08 (SPEC 9.3, tier T2; owned by G3, re-run by G5): passthrough, forced re-encode, slot repack, plain round trip.

* ``to_bytes() == input`` for every fixture (also the ``_cmp`` wrapper, ``_fsm`` and the trailer verbatim);
* ``to_bytes(force=True) == input`` for every fixture of shape ``plain4`` / ``plain4+fsm``; for the ``cmp`` shapes
  it equals the builder's golden ``<name>_expanded`` file (DEC-2.6) and re-parses to the same slots, labels
  and quotas;
* invariant I1 (every slot re-packs to its own bits); label re-encode report; ``MapVariant.copy()`` is a deep copy;
* the patched mode (changed slots re-packed, the rest shifted) reproduces the W1 golden edits E1/E2/E2b/E3
  byte for byte, which also checks quota, L and hash recomputation.

Everything is built in memory; nothing is written to disk.
"""
import hashlib
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import helpers_g3 as g3  # noqa: E402

from mvarlib import errors, hashing, labels, plain  # noqa: E402
from mvarlib.model import MapVariant  # noqa: E402
from mvarlib.slot import Slot  # noqa: E402


def views(m):
    """Everything a re-parse must agree on."""
    return ([s.snapshot() for s in m.slots], [q.as_tuple() for q in m.quotas], m.labels.texts(), m.labels.entries,
            m.fixed.raw, m.hypothesis, m.header.title, m.header.description, m.header.map_id)


class TestPassthrough(unittest.TestCase):
    def test_every_positive_fixture_returns_the_input(self):
        for name in g3.positive_names():
            with self.subTest(name):
                m = g3.model(name)
                self.assertEqual(m.to_bytes(force=False), g3.data(name))
                self.assertEqual(m.render().issues, [])

    def test_passthrough_does_not_depend_on_flavour_or_options(self):
        data = g3.data("w1_minimal")
        m = g3.model("w1_minimal")
        self.assertEqual(m.to_bytes(flavour=hashing.HashFlavour(">", "plain_le32")), data)       # a clean unforced save never rewrites

    def test_trailer_and_fsm_and_cmp_wrapper_are_verbatim(self):
        for name in ("trailer", "fsm", "cmp", "cmp_fsm"):
            with self.subTest(name):
                self.assertEqual(g3.model(name).to_bytes(force=False), g3.data(name))
        self.assertEqual(len(g3.data("trailer")), 29481 + 512)


class TestForcedReencode(unittest.TestCase):
    def test_plain_shapes_equal_the_input(self):
        checked = 0
        for name in g3.positive_names():
            shape = g3.spec(name)["container"]["shape"]
            if shape.startswith("cmp"):
                continue
            with self.subTest(name):
                m = g3.model(name)
                rendered = m.render(force=True)
                self.assertEqual(rendered.data, g3.data(name))
                self.assertEqual([i.code for i in rendered.issues if i.code != "I_HASH_ZERO"], [])
                checked += 1
        self.assertGreaterEqual(checked, 36)

    def test_cmp_shapes_give_the_golden_expanded_file(self):
        for name in ("cmp", "cmp_fsm"):
            with self.subTest(name):
                m = g3.model(name)
                forced = m.to_bytes(force=True)
                self.assertEqual(forced, g3.data(name + "_expanded"))
                self.assertNotEqual(forced, g3.data(name))
                self.assertIn("W_CMP_EXPANDED", [i.code for i in m.render(force=True).issues])
                again = MapVariant.from_bytes(forced)
                self.assertEqual(views(again), views(m))
                self.assertEqual(again.shape, "plain4+fsm" if "fsm" in name else "plain4")
                self.assertEqual(again.to_bytes(force=False), forced)
                self.assertEqual(again.to_bytes(force=True), forced)
                self.assertEqual(m.to_bytes(force=False), g3.data(name))                  # the passthrough still gives the wrapper

    def test_expanded_goldens_are_fixed_points(self):
        for name in ("cmp_expanded", "cmp_fsm_expanded"):
            self.assertEqual(g3.model(name).to_bytes(force=True), g3.data(name))

    def test_forcing_a_hash_recipe_reproduces_the_other_flavour_fixture(self):
        m = g3.model("w1_minimal")
        out = m.to_bytes(force=True, flavour=hashing.HashFlavour(">", "plain_le32"))
        self.assertEqual(out, g3.data("plain_le32"))
        self.assertEqual(hashlib.sha256(out).hexdigest(), "9e11095033b8356e7f772a2f615ceb77ba7e49b18c047f3826ac1da7a62ddbc5")
        zero = m.to_bytes(force=True, flavour=hashing.HashFlavour(">", "zero"))
        self.assertEqual(zero, g3.data("zero_hash"))
        le = m.to_bytes(force=True, flavour=hashing.HashFlavour("<", "salted_be32"))
        self.assertEqual(le, g3.data("le_length"))

    def test_zero_hash_and_unknown_hash_reports(self):
        m = g3.model("zero_hash")
        self.assertIn("I_HASH_ZERO", [i.code for i in m.render(force=True).issues])
        data = bytearray(g3.data("w1_minimal"))
        data[0x2F0 + 12] ^= 0x55                                      # corrupt the stored SHA-1: no recipe matches any more
        broken = MapVariant.from_bytes(bytes(data))
        self.assertIsNone(broken.flavour)
        self.assertEqual(hashing.flavour_label(broken.flavour), "unknown")
        self.assertEqual(broken.to_bytes(force=False), bytes(data))                                       # passthrough keeps it
        rendered = broken.render(force=True)
        self.assertIn("W_HASH_UNKNOWN", [i.code for i in rendered.issues])
        self.assertEqual(rendered.data, g3.data("w1_minimal"))                                  # the salted recipe repairs it

    def test_forced_rebuild_keeps_the_class_of_the_stored_length(self):
        self.assertEqual(g3.model("length_capacity").length_class, "capacity")
        self.assertEqual(g3.model("length_capacity").to_bytes(force=True), g3.data("length_capacity"))

    def test_nonzero_tail_and_pad_bits_survive(self):
        data = bytearray(g3.data("w1_minimal"))
        stream = 0x2F0 + 36
        data[stream + 700] = 0x5A                                     # beyond L: not hashed, so the hash still matches
        m = MapVariant.from_bytes(bytes(data))
        self.assertEqual(m.soft.get("tail_nonzero"), 1)
        self.assertIn("W_TAIL_NONZERO", [w.code for w in m.warnings])
        self.assertEqual(m.to_bytes(force=False), bytes(data))
        self.assertEqual(m.to_bytes(force=True), bytes(data))
        data2 = bytearray(g3.data("w1_minimal"))
        data2[stream + 621] |= 0x01                                   # bit 4975, inside the pad after bit 4970 (hashed)
        digest = hashing.compute(hashing.HashFlavour(">", "salted_be32"), bytes(data2[stream:stream + 622]), 622)
        data2[0x2F0 + 12:0x2F0 + 32] = digest
        m2 = MapVariant.from_bytes(bytes(data2))
        self.assertEqual(m2.flavour, (">", "salted_be32"))
        self.assertEqual(m2.soft.get("pad_bits_nonzero"), 1)
        self.assertEqual(m2.to_bytes(force=True), bytes(data2))


    def test_the_last_bit_of_the_stream_is_kept(self):
        data = bytearray(g3.data("w1_minimal"))
        stream = 0x2F0 + 36
        data[stream + 0x6FFF] = 0x01                                  # bit 229,375, the very last bit of the capacity
        data[stream + 5000] = 0x80
        m = MapVariant.from_bytes(bytes(data))
        self.assertEqual(m.soft.get("tail_nonzero"), 1)
        self.assertEqual(m.to_bytes(force=True), bytes(data))
        edited = m.copy()
        edited.slots[1].pos[0] = 526473
        out = edited.to_bytes(force=False)
        self.assertEqual(out[stream + 0x6FFF], 0x01)
        self.assertEqual(out[stream + 5000], 0x80)

    def test_the_zero_length_class_is_reproduced(self):
        import copy
        build, _ = g3.build_modules()
        spec = copy.deepcopy(g3.spec("zero_hash"))
        spec.pop("expect", None)
        spec["container"]["length"] = {"endian": ">", "mode": "explicit", "value": 0}
        data = build.build(spec).data
        self.assertEqual(data[0x2F0 + 32:0x2F0 + 36], bytes(4))
        m = MapVariant.from_bytes(data)
        self.assertEqual((m.length_class, m.flavour), ("zero", (">", "zero")))
        self.assertEqual(m.to_bytes(force=False), data)
        self.assertEqual(m.to_bytes(force=True), data)
        edited = m.copy()
        edited.slots[1].pos[0] += 5
        out = edited.to_bytes(force=False)
        self.assertEqual(out[0x2F0 + 32:0x2F0 + 36], bytes(4))               # the class is kept, never recomputed
        self.assertEqual(out[0x2F0 + 12:0x2F0 + 32], bytes(20))
        self.assertEqual(MapVariant.from_bytes(out).length_class, "zero")


class TestSlotRepack(unittest.TestCase):
    def test_invariant_i1_for_every_slot_of_every_fixture(self):
        total = 0
        for name in g3.positive_names():
            m = g3.model(name)
            rule, axes = m.hypothesis.type19, m.hypothesis.axis_bits
            with self.subTest(name):
                for s in m.slots:
                    self.assertEqual(s.to_bits(rule, axes), s.raw, "slot %d" % s.index)
                    total += 1
        self.assertGreaterEqual(total, 40 * 651)

    def test_repack_works_under_the_wrong_rule_only_for_slots_without_type19(self):
        m = g3.model("type19_flag8")
        wrong = "plain8"
        axes = m.hypothesis.axis_bits
        differing = [s.index for s in m.slots if s.present and s.cached_type == 19 and s.to_bits("flag8", axes) != s.raw]
        self.assertEqual(differing, [])
        with self.assertRaises(errors.EncodeError):
            [s.to_bits(wrong, axes) for s in m.slots if s.present and s.cached_type == 19][0]      # extras shaped for flag8

    def test_pack_refuses_values_that_do_not_fit(self):
        m = g3.model("w1_minimal")
        s = m.slots[1].copy()
        s.pos[0] = 1 << 20
        with self.assertRaises(errors.EncodeError):
            s.to_bits("flag8", (20, 21, 19))
        s = m.slots[1].copy()
        s.spawn_seq = 128
        with self.assertRaises(errors.EncodeError):
            s.to_bits("flag8", (20, 21, 19))
        s = m.slots[1].copy()
        s.up_global = 0
        with self.assertRaises(errors.EncodeError):               # no up code
            s.to_bits("flag8", (20, 21, 19))
        s = m.slots[1].copy()
        s.shape = 2
        with self.assertRaises(errors.EncodeError):               # shape 2 needs three dimensions
            s.to_bits("flag8", (20, 21, 19))

    def test_slot_dirty_tracking(self):
        m = g3.model("w1_minimal").copy()
        s = m.slots[1]
        self.assertEqual(s.dirty, set())
        s.pos[0] += 1
        self.assertEqual(s.dirty, set(["pos"]))
        self.assertTrue(m.dirty)
        s.pos[0] -= 1
        self.assertEqual(s.dirty, set())
        self.assertFalse(m.dirty)                                  # setting a field back makes it clean again
        s.angle = 5
        s.team_raw = 3
        self.assertEqual(s.dirty, set(["angle", "team_raw"]))
        fresh = Slot(0, True)
        self.assertEqual(fresh.dirty, set(["*"]))
        gone = m.slots[5]
        gone.present = False
        self.assertEqual(gone.dirty, set(["present"]))


class TestLabelReencode(unittest.TestCase):
    def test_reencode_report_per_fixture(self):
        identical = {}
        for name in g3.positive_names():
            t = g3.model(name).labels
            kept = labels.encode_label_table(t.entries, t.buffer, t.compressed, t.comp_bytes, t.data_length)
            self.assertEqual(kept, t.raw, name)                    # with the stored compressed block it is always exact
            fresh = labels.encode_label_table(t.entries, t.buffer, t.compressed, None, t.data_length)
            identical[name] = fresh == t.raw
        self.assertTrue(identical["labels_uncompressed"])
        self.assertTrue(identical["w1_minimal"])
        self.assertTrue(identical["zero_labels"])
        self.assertTrue(identical["labels_compressed"])            # zlib level 9 reproduces the frozen stream on 1.2.12 and 1.3.1


class TestCopy(unittest.TestCase):
    def test_copy_is_deep_and_independent(self):
        m = g3.model("w1_minimal")
        c = m.copy()
        self.assertIsNot(c, m)
        self.assertEqual(c.to_bytes(force=False), g3.data("w1_minimal"))
        self.assertEqual(c.to_bytes(force=True), g3.data("w1_minimal"))
        c.slots[1].pos[0] = 5
        c.quotas[70].placed = 9
        c.labels.entries[0] = 1
        self.assertTrue(c.dirty)
        self.assertEqual(m.slots[1].pos[0], 524288)
        self.assertEqual(m.quotas[70].placed, 2)
        self.assertEqual(m.labels.entries[0], 0)
        self.assertFalse(m.dirty)
        self.assertEqual(m.to_bytes(force=False), g3.data("w1_minimal"))
        for a, b in zip(c.slots, m.slots):
            self.assertIsNot(a, b)
            self.assertIsNot(a.pos, b.pos)
        self.assertIsNot(c.blf, m.blf)

    def test_copy_of_cmp_and_fsm_models(self):
        for name in ("cmp", "fsm", "cmp_fsm", "trailer", "v32"):
            with self.subTest(name):
                c = g3.model(name).copy()
                self.assertEqual(c.to_bytes(force=False), g3.data(name))

    def test_fsm_policy_drop_counts_as_a_modification(self):
        c = g3.model("fsm").copy()
        self.assertFalse(c.dirty)
        c.drop_fsm()
        self.assertTrue(c.dirty)
        out = c.render()
        self.assertEqual(out.data, g3.data("w1_minimal"))          # dropping _fsm from the fsm fixture yields W1 (G1 integration check)
        self.assertEqual(MapVariant.from_bytes(out.data).shape, "plain4")
        self.assertEqual(g3.model("fsm").to_bytes(force=False), g3.data("fsm"))   # the original model is untouched


def new_block(index=0, angle=8192):
    """The slot of the W1 golden edit E2: a ``Block, 1x1`` with default fields."""
    s = Slot(index, True)
    s.flags2 = 1
    s.folder, s.item = 70, 0
    s.pos = [1, 2, 3]
    s.up_global, s.up_code = 1, None
    s.angle = angle
    s.placement = 0xCC
    s.team_raw = 9
    return s


class TestPatchedModeGoldenEdits(unittest.TestCase):
    """The patched mode (G5 completes and tests the rest) must already reproduce the independent W1 goldens."""

    def edit(self, fn):
        m = g3.model("w1_minimal").copy()
        fn(m)
        return m, m.to_bytes(force=False)

    def test_e1_move_slot_1(self):
        def fn(m):
            m.slots[1].pos[0] = 526473
        m, out = self.edit(fn)
        self.assertEqual(out, g3.data("w1_E1"))
        self.assertEqual(hashlib.sha256(out).hexdigest(), "32296dac74f00aea41f16859052f27a5230c29a556ddcc3b3edcefb19b64cf32")
        self.assertEqual(m.render().issues, [])

    def test_e2_add_a_block(self):
        def fn(m):
            m.slots[0] = new_block()
            m.quotas[70].placed = 3
        m, out = self.edit(fn)
        self.assertEqual(out, g3.data("w1_E2"))
        self.assertEqual(hashlib.sha256(out).hexdigest(), "9055a41eb6690c26d53b701a208c4531a7c239c474b7911147399a460b78a08d")
        again = MapVariant.from_bytes(out)
        self.assertEqual((again.end_bit, again.chunk.stored_length), (5110, 639))

    def test_e2b_unrotated_add(self):
        def fn(m):
            m.slots[0] = new_block(angle=12288)
            m.quotas[70].placed = 3
        m, out = self.edit(fn)
        self.assertEqual(out, g3.data("w1_E2b"))
        self.assertEqual(hashlib.sha256(out).hexdigest(), "851d42b8dc49182db799d0ee573dc30531be7992944e8406d6f6fc2adabb3fdd")

    def test_e3_delete_the_kill_boundary(self):
        def fn(m):
            m.slots[5].present = False
            m.quotas[61].placed = 0
        m, out = self.edit(fn)
        self.assertEqual(out, g3.data("w1_E3"))
        self.assertEqual(hashlib.sha256(out).hexdigest(), "6e3f948488c5a9ed4d0c0febdcb859738d8d28571860566ab4d0d2081ae4058f")
        again = MapVariant.from_bytes(out)
        self.assertEqual((again.end_bit, again.chunk.stored_length), (4778, 598))

    def test_a_quota_only_edit_is_patched_too(self):
        def fn(m):
            m.quotas[70].placed = 3
        m, out = self.edit(fn)
        self.assertNotEqual(out, g3.data("w1_minimal"))
        again = MapVariant.from_bytes(out)
        self.assertEqual(again.quotas[70].placed, 3)
        self.assertEqual(again.end_bit, 4970)

    def test_patched_cmp_template_expands(self):
        m = g3.model("cmp").copy()
        m.slots[1].pos[0] = 526473
        rendered = m.render()
        self.assertIn("W_CMP_EXPANDED", [i.code for i in rendered.issues])
        self.assertEqual(rendered.data, g3.data("w1_E1"))                       # expanded, lengths re-stamped, hash recomputed

    def test_patched_fsm_template_keeps_the_signature_block_and_warns(self):
        m = g3.model("fsm").copy()
        m.slots[1].pos[0] = 526473
        rendered = m.render()
        self.assertIn("W_FSM_STALE", [i.code for i in rendered.issues])
        self.assertEqual(rendered.data[:29481], g3.data("w1_E1"))
        self.assertEqual(rendered.data[29481:], g3.data("fsm")[29481:])

    def test_capacity_is_enforced(self):
        m = g3.model("near_full").copy()
        free = [s.index for s in m.slots if not s.present]
        self.assertTrue(free)
        m.slots[free[0]] = new_block(free[0])
        m.quotas[70].placed = (m.quotas[70].placed + 1) & 0xFF
        with self.assertRaises(errors.CapacityError) as cm:
            m.to_bytes(force=False)
        self.assertIn("229,376", str(cm.exception))

    def test_delete_then_add_in_the_same_edit_keeps_the_stream_consistent(self):
        m = g3.model("holes").copy()
        occupied = [s.index for s in m.slots if s.present]
        m.slots[occupied[0]].present = False
        free = [s.index for s in m.slots if not s.present][0]
        m.slots[free] = new_block(free)
        out = m.to_bytes(force=False)
        again = MapVariant.from_bytes(out)
        self.assertEqual(again.occupied, len(occupied))
        self.assertEqual(again.to_bytes(force=True), out)


class TestPlainRoundTrip(unittest.TestCase):
    def test_every_positive_fixture_round_trips_through_json(self):
        for name in g3.positive_names():
            with self.subTest(name):
                m = g3.model(name)
                d = json.loads(json.dumps(plain.to_plain(m)))
                m2 = plain.from_plain(d)
                expected = g3.data(name + "_expanded") if g3.spec(name)["container"]["shape"].startswith("cmp") else g3.data(name)
                self.assertEqual(m2.to_bytes(force=True), expected)
                self.assertEqual(m2.to_bytes(force=False), expected)
                self.assertEqual(views(m2), views(m))


if __name__ == "__main__":
    unittest.main()
