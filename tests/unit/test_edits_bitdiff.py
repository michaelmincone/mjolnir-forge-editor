"""U-11 (SPEC 9.3, tier T2; gate G5): the edits of the export, byte for byte and bit for bit.

* the W1 golden edits E1, E2, E2b and E3 (Appendix C.3) made through ``api.export_map_variant`` equal the independent
  builder's files byte for byte, with the numbers of the spec (end bit, L, SHA-256);
* the bit-diff contract of SPEC 5.9 for every kind of edit: a same-length edit changes only the bits of the edited field of
  the edited slot (plus the 20 hash bytes); a length-changing edit leaves the bits before the slot alone and shifts everything
  after it, except the quota rows it changes; nothing outside the stream moves (``_blf``, ``chdr``, the ``mvar`` header, the
  pad, ``_eof``). The expected bit ranges come from the INDEPENDENT walker of the fixture builder, never from the library;
* quota deltas, parent clearing, hash and L recomputation (checked with ``hashlib``), the capacity refusal and its exact
  boundary, and the type-19 extras under both rules.

Everything is built in memory.
"""
import hashlib
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import helpers_g5 as h  # noqa: E402

from mvarlib import api, codecs  # noqa: E402
from mvarlib.model import MapVariant  # noqa: E402

W1 = "w1_minimal"


def w1():
    return h.g3.data(W1)


def w1_model():
    return h.g3.model(W1)


def run(objects, name=W1, **options):
    result = h.export(h.g3.data(name), objects, **options)
    return result


def ok_data(testcase, objects, name=W1, **options):
    result = run(objects, name, **options)
    testcase.assertTrue(result.ok, [e.message for e in result.errors])
    return result.data, result


def real_changes(testcase, result, *kinds):
    """The diff entries other than ``kept``, as ``[(kind, slot)]``."""
    return [(e.kind, e.slot) for e in result.diff if e.kind != "kept"]


def slot_start(decoded, index):
    """First stream bit of slot ``index`` in an independent decode (an absent slot is one bit)."""
    pos = decoded["sections"]["slots"]
    for i in range(index):
        rng = decoded["slot_ranges"].get(i)
        pos += (rng[1] - rng[0]) if rng else 1
    return pos


def slot_len(decoded, index):
    rng = decoded["slot_ranges"].get(index)
    return (rng[1] - rng[0]) if rng else 1


class ContractCase(unittest.TestCase):
    """Helpers that check SPEC 5.9 on a pair of files."""

    def assert_container_untouched(self, a, b, allow_length=False):
        """Nothing outside the bit stream, the 20 hash bytes and (if allowed) the 4 length bytes differs."""
        self.assertEqual(len(a), len(b))
        outside = [i for i in h.container_diff(a, b) if not (h.HASH_AT <= i < h.HASH_AT + 20)]
        if allow_length:
            outside = [i for i in outside if not (h.LENGTH_AT <= i < h.LENGTH_AT + 4)]
        self.assertEqual(outside, [], "bytes outside the stream, the hash and the length changed")

    def assert_same_length_edit(self, a, b, slot, fields, quota_rows=()):
        """Only bits inside the named fields of ``slot`` (and of the listed quota rows) changed; L is unchanged; the hash is new."""
        da = h.decode(a)
        allowed = [h.slot_span(da, slot, f) for f in fields]
        first_row = da["sections"]["quotas"]
        allowed += [(first_row + 24 * r, first_row + 24 * r + 24) for r in quota_rows]
        diff = h.stream_diff(a, b)
        self.assertTrue(diff, "the edit changed no bit")
        stray = [p for p in diff if not h.in_ranges(p, allowed)]
        self.assertEqual(stray, [], "bits outside %s changed (allowed %s)" % (fields, allowed))
        self.assertEqual(h.stored_length(a), h.stored_length(b), "a same-length edit keeps L")
        self.assertNotEqual(h.stored_hash(a), h.stored_hash(b))
        self.assert_container_untouched(a, b, allow_length=False)
        self.assertEqual(h.decode(b)["end"], da["end"])

    def assert_shifted_edit(self, a, b, slot, delta, quota_rows=()):
        """A length-changing edit of ``slot``: the prefix is identical, the rest shifted by ``delta``, quota rows as listed."""
        da, db = h.decode(a), h.decode(b)
        start = slot_start(da, slot)
        self.assertEqual(slot_start(db, slot), start, "slots before the edited one keep their position")
        ea, eb = start + slot_len(da, slot), start + slot_len(db, slot)
        self.assertEqual(eb - ea, delta)
        self.assertEqual(db["end"] - da["end"], delta)
        xa = int.from_bytes(h.stream_bytes(a), "big")
        xb = int.from_bytes(h.stream_bytes(b), "big")

        def bits(x, lo, hi):
            return (x >> (h.STREAM_BITS - hi)) & ((1 << (hi - lo)) - 1)

        self.assertEqual(bits(xa, 0, start), bits(xb, 0, start), "the bits before the edited slot changed")
        qa, qb = da["sections"]["quotas"], db["sections"]["quotas"]
        self.assertEqual(bits(xa, ea, qa), bits(xb, eb, qb), "the slots after the edit are not the old ones shifted")
        self.assertEqual(qb - qa, delta)
        rows_a, rows_b = da["quotas"], db["quotas"]
        changed = [i for i in range(len(rows_a)) if rows_a[i] != rows_b[i]]
        self.assertEqual(changed, sorted(quota_rows), "quota rows that changed")
        self.assertEqual(bits(xa, da["end"], h.STREAM_BITS), 0)
        self.assertEqual(bits(xb, db["end"], h.STREAM_BITS), 0, "the tail stays zero")
        self.assertEqual(h.stored_length(b), (db["end"] + 7) // 8, "L = ceil(end / 8)")
        self.assert_container_untouched(a, b, allow_length=True)

    def assert_hash_is_right(self, data, recipe="salted_be32"):
        self.assertEqual(h.stored_hash(data), h.independent_hash(recipe, data), "stored SHA-1 vs hashlib")


# =====================================================================================================
class TestGoldenEdits(ContractCase):
    def test_e1_move_slot_1_by_one_unit_in_x(self):
        objs = h.objects_for(w1())
        rec = w1_model().record_for(w1_model().slots[1])
        h.change(objs, 1, position=(rec.position[0] + 1.0, rec.position[1], rec.position[2]))
        data, result = ok_data(self, objs)
        self.assertEqual(data, h.g3.data("w1_E1"))
        self.assertEqual(hashlib.sha256(data).hexdigest(), "32296dac74f00aea41f16859052f27a5230c29a556ddcc3b3edcefb19b64cf32")
        self.assertEqual(h.stored_hash(data).hex(), "770d7849af8a19d13deb739ea8fd97d77da956d7")
        self.assertEqual((result.stats["mode"], result.stats["end_bit"], result.stats["L"]), ("patched", 4970, 622))
        self.assertEqual(real_changes(self, result), [("moved", 1)])
        self.assertEqual([e for e in result.diff if e.kind == "moved"][0].detail, "moved by (+1.000, +0.000, +0.000)")
        self.assertEqual(result.stats["quota_changes"], [])
        self.assertEqual([w.code for w in result.warnings if w.severity != "info"], [])
        self.assert_same_length_edit(w1(), data, 1, ["pos_x"])          # only the 20 x bits, nothing else

    def test_e2_add_a_block_into_the_lowest_free_slot(self):
        objs = h.objects_for(w1())
        objs.append(h.new_object("Added", position=h.cell_centre(w1_model(), (1, 2, 3))))
        data, result = ok_data(self, objs, **h.GATE)
        self.assertEqual(data, h.g3.data("w1_E2"))
        self.assertEqual(hashlib.sha256(data).hexdigest(), "9055a41eb6690c26d53b701a208c4531a7c239c474b7911147399a460b78a08d")
        self.assertEqual(h.stored_hash(data).hex(), "2749d9b60e6da739d296d18aeec31a0490e9a36a")
        self.assertEqual((result.stats["end_bit"], result.stats["L"]), (5110, 639))
        self.assertEqual(real_changes(self, result), [("added", 0)])
        quota = result.stats["quota_changes"]
        self.assertEqual([(q["folder"], q["placed_before"], q["placed_after"], q["maximum_before"], q["maximum_after"]) for q in quota],
                         [(70, 2, 3, 16, 16)])
        self.assertEqual(h.codes(result.warnings), ["W_ORIENTATION_UNVERIFIED", "I_BUDGET", "I_PALETTE", "I_UNVERIFIED"])
        self.assertEqual(result.warnings[0].message, "1 object(s) had their rotation written with an unverified convention.")
        self.assert_shifted_edit(w1(), data, 0, 140, quota_rows=[70])

    def test_e2b_the_unrotated_add_has_yaw_pi_over_2(self):
        objs = h.objects_for(w1())
        objs.append(h.new_object("Added", position=h.cell_centre(w1_model(), (1, 2, 3)), forward=(0.0, 1.0, 0.0)))
        data, _ = ok_data(self, objs, **h.GATE)
        self.assertEqual(data, h.g3.data("w1_E2b"))
        self.assertEqual(hashlib.sha256(data).hexdigest(), "851d42b8dc49182db799d0ee573dc30531be7992944e8406d6f6fc2adabb3fdd")
        self.assertEqual(h.stored_hash(data).hex(), "0ebb78f125fd9f1dc8ec2cea072433f3b6082c77")

    def test_e3_delete_the_kill_boundary(self):
        objs = h.without(h.objects_for(w1()), 5)
        data, result = ok_data(self, objs)
        self.assertEqual(data, h.g3.data("w1_E3"))
        self.assertEqual(hashlib.sha256(data).hexdigest(), "6e3f948488c5a9ed4d0c0febdcb859738d8d28571860566ab4d0d2081ae4058f")
        self.assertEqual(h.stored_hash(data).hex(), "89a171193839cb0b9ec718db061295c9cb176819")
        self.assertEqual((result.stats["end_bit"], result.stats["L"]), (4778, 598))
        self.assertEqual(real_changes(self, result), [("removed", 5)])
        removed = [e for e in result.diff if e.kind == "removed"][0]
        self.assertEqual((removed.slot, removed.name), (5, "5 - Kill Boundary"))
        self.assertEqual([(q["folder"], q["placed_before"], q["placed_after"]) for q in result.stats["quota_changes"]], [(61, 1, 0)])
        self.assert_shifted_edit(w1(), data, 5, -192, quota_rows=[61])

    def test_a_forced_re_encode_of_an_edited_model_equals_the_patched_golden(self):
        """Forced mode for an edited model (SPEC 5.2): every slot is re-packed from its raw ints; for these edits the bytes are the goldens."""
        rec = w1_model().record_for(w1_model().slots[1])
        moved = h.objects_for(w1())
        h.change(moved, 1, position=(rec.position[0] + 1.0, rec.position[1], rec.position[2]))
        added = h.objects_for(w1()) + [h.new_object("Added", position=h.cell_centre(w1_model(), (1, 2, 3)))]
        for label, objs, golden in (("E1", moved, "w1_E1"), ("E2", added, "w1_E2"), ("E3", h.without(h.objects_for(w1()), 5), "w1_E3")):
            with self.subTest(label):
                result = run(objs, force_reencode=True, **h.GATE)
                self.assertTrue(result.ok, [e.message for e in result.errors])
                self.assertEqual(result.data, h.g3.data(golden))
                self.assertEqual(result.stats["mode"], "forced")

    def test_the_goldens_survive_a_reparse_and_a_second_export(self):
        for name, golden in (("E1", "w1_E1"), ("E2", "w1_E2"), ("E3", "w1_E3")):
            with self.subTest(name):
                data = h.g3.data(golden)
                again = h.export(data, h.objects_for(data), **h.GATE)
                self.assertTrue(again.ok)
                self.assertEqual(again.data, data, "unchanged objects of an edited file give the file back")

    def test_all_three_edits_at_once_decode_to_all_three_changes(self):
        objs = h.without(h.objects_for(w1()), 5)
        rec = w1_model().record_for(w1_model().slots[1])
        h.change(objs, 1, position=(rec.position[0] + 1.0, rec.position[1], rec.position[2]))
        objs.append(h.new_object("Added", position=h.cell_centre(w1_model(), (1, 2, 3))))
        data, result = ok_data(self, objs, **h.GATE)
        self.assertEqual(sorted(real_changes(self, result)), [("added", 0), ("moved", 1), ("removed", 5)])
        dec = h.decode(data)
        self.assertEqual(sorted(dec["slots"]), [0, 1, 650])
        self.assertEqual(dec["slots"][1]["pos"][0], 526473)
        self.assertEqual(dec["slots"][0]["pos"], [1, 2, 3])
        self.assertEqual(dec["end"], 4970 + 140 - 192)
        self.assert_hash_is_right(data)


# =====================================================================================================
class TestSameLengthEdits(ContractCase):
    """Translate, yaw, spawn fields, team, physics: only the bits of that field of that slot change."""

    def move(self, axis, delta, slot=1):
        objs = h.objects_for(w1())
        pos = list(by_pos(objs, slot))
        pos[axis] += delta
        h.change(objs, slot, position=tuple(pos))
        return ok_data(self, objs)

    def test_each_axis_alone_changes_only_its_own_bits(self):
        for axis, field in enumerate(("pos_x", "pos_y", "pos_z")):
            with self.subTest(field):
                data, result = self.move(axis, 2.5)
                self.assert_same_length_edit(w1(), data, 1, [field])
                self.assertEqual(real_changes(self, result), [("moved", 1)])

    def test_moving_a_negative_direction_and_a_far_object(self):
        data, _ = self.move(0, -3.0, slot=1)
        self.assert_same_length_edit(w1(), data, 1, ["pos_x"])
        data, _ = self.move(1, 100.0, slot=5)
        self.assert_same_length_edit(w1(), data, 5, ["pos_y"])
        data, _ = self.move(0, 3.0, slot=650)                           # slot 650 sits in the lowest cell of every axis
        self.assert_same_length_edit(w1(), data, 650, ["pos_x"])
        self.assertEqual(h.decode(data)["slots"][650]["pos"][0], 6554)    # floor((3.0 + cell / 2) / cell) with cell 480 / 2^20

    def test_all_three_axes_at_once(self):
        objs = h.objects_for(w1())
        pos = by_pos(objs, 5)
        h.change(objs, 5, position=(pos[0] + 1.0, pos[1] - 2.0, pos[2] + 3.0))
        data, _ = ok_data(self, objs)
        self.assert_same_length_edit(w1(), data, 5, ["pos_x", "pos_y", "pos_z"])
        dec = h.decode(data)
        self.assertNotEqual(dec["slots"][5]["pos"], h.decode(w1())["slots"][5]["pos"])

    def test_the_moved_cell_is_the_containing_cell_and_other_axes_keep_their_raw_cells(self):
        data, _ = self.move(0, 1.0)
        before, after = h.decode(w1())["slots"][1], h.decode(data)["slots"][1]
        self.assertEqual(after["pos"][0], 526473)                    # G-POS-3
        self.assertEqual(after["pos"][1:], before["pos"][1:])
        self.assertEqual({k: v for k, v in after.items() if k != "pos"}, {k: v for k, v in before.items() if k != "pos"})

    def test_yaw_of_a_vertical_object_changes_only_the_angle(self):
        objs = h.objects_for(w1())
        h.change(objs, 1, forward=(0.0, 1.0, 0.0))                      # yaw pi/2 -> raw 12288
        data, result = ok_data(self, objs, **h.GATE)
        self.assert_same_length_edit(w1(), data, 1, ["angle"])
        self.assertEqual(h.decode(data)["slots"][1]["angle"], 12288)
        self.assertEqual(real_changes(self, result), [("edited", 1)])
        self.assertEqual([w.message for w in result.warnings if w.code == "W_ORIENTATION_UNVERIFIED"],
                         ["1 object(s) had their rotation written with an unverified convention."])

    def test_yaw_all_four_quarter_turns(self):
        for forward, raw in (((1.0, 0.0, 0.0), 8192), ((0.0, 1.0, 0.0), 12288), ((-1.0, 0.0, 0.0), 16383),
                             ((0.0, -1.0, 0.0), 4096)):
            with self.subTest(forward):
                objs = h.objects_for(w1())
                h.change(objs, 5, forward=forward)                      # slot 5 is vertical with raw 8192
                data, _ = ok_data(self, objs, **h.GATE)
                self.assertEqual(h.decode(data)["slots"][5]["angle"], raw)

    def test_spawn_fields_change_only_their_own_bits(self):
        objs = h.objects_for(w1())
        h.change(objs, 5, spawn_sequence=-128)
        data, _ = ok_data(self, objs)
        self.assert_same_length_edit(w1(), data, 5, ["spawn_seq"])
        self.assertEqual(h.decode(data)["slots"][5]["spawn_seq"], -128)
        objs = h.objects_for(w1())
        h.change(objs, 5, spawn_time=255)
        data, _ = ok_data(self, objs)
        self.assert_same_length_edit(w1(), data, 5, ["respawn"])
        objs = h.objects_for(w1())
        h.change(objs, 5, spawn_sequence=127, spawn_time=1)
        data, _ = ok_data(self, objs)
        self.assert_same_length_edit(w1(), data, 5, ["spawn_seq", "respawn"])

    def test_team_changes_only_the_team_bits(self):
        objs = h.objects_for(w1())
        h.change(objs, 650, team=2)                                       # raw 9 -> 3
        data, _ = ok_data(self, objs)
        self.assert_same_length_edit(w1(), data, 650, ["team"])
        self.assertEqual(h.decode(data)["slots"][650]["team_raw"], 3)
        objs = h.objects_for(w1())
        h.change(objs, 1, team=0)
        data, _ = ok_data(self, objs)
        self.assertEqual(h.decode(data)["slots"][1]["team_raw"], 1)

    def test_physics_changes_only_the_two_physics_bits(self):
        objs = h.objects_for(w1())
        h.change(objs, 1, physics=1)                                      # 0xCC (phased) -> 0x4C (fixed)
        data, _ = ok_data(self, objs)
        self.assert_same_length_edit(w1(), data, 1, ["placement"])
        self.assertEqual(h.decode(data)["slots"][1]["placement"], 0x4C)
        start, end = h.slot_span(h.decode(w1()), 1, "placement")
        self.assertEqual(h.stream_diff(w1(), data), [start])              # 0xCC ^ 0x4C = 0x80: the first bit of the byte only
        for physics, byte in ((0, 0x0C), (3, 0xCC), (1, 0x4C)):
            objs = h.objects_for(w1())
            h.change(objs, 1, physics=physics)
            data, _ = ok_data(self, objs)
            self.assertEqual(h.decode(data)["slots"][1]["placement"], byte)
            self.assertEqual(h.decode(data)["slots"][1]["placement"] & 0x3F, 0x0C, "bits 0-5 are never touched")

    def test_the_physics_value_2_counts_as_normal(self):
        """4.9: a file that stores the unused physics value 2 is unchanged when the UI hands back 0, written 0 only on a real change."""
        data = bytearray(w1())
        dec = h.decode(bytes(data))
        # build a variant of W1 with placement 0x8C (physics 2) through the fixture spec
        build, _ = h.build_modules()
        spec = build.load_spec(W1)
        spec = __import__("copy").deepcopy(spec)
        spec["slots"][0]["placement"] = 0x8C
        template = build.build(spec).data
        model = MapVariant.from_bytes(template)
        self.assertEqual(model.objects()[0].physics, 2)
        objs = h.objects_for(model)
        result = h.export(template, objs)                                  # physics handed back as 2: unchanged
        self.assertEqual(result.data, template)
        h.change(objs, 1, physics=0)                                       # the UI shows 2 as NORMAL: handing back 0 is no change
        self.assertEqual(h.export(template, objs).data, template)
        h.change(objs, 1, physics=3)
        changed = h.export(template, objs)
        self.assertEqual(h.decode(changed.data)["slots"][1]["placement"], 0xCC)

    def test_unchanged_values_inside_the_tolerance_are_not_written(self):
        """G-POS-5 and 4.9: a drift inside 1e-3 world units keeps the raw cells; an angle drift below 1e-4 rad keeps the angle."""
        objs = h.objects_for(w1())
        pos = by_pos(objs, 1)
        h.change(objs, 1, position=(pos[0] + 0.0004, pos[1] - 0.0004, pos[2] + 0.0009))
        self.assertEqual(h.export(w1(), objs).data, w1())
        rec = w1_model().record_for(w1_model().slots[1])
        t = math.atan2(rec.forward[1], rec.forward[0]) + 0.00009
        h.change(objs, 1, forward=(math.cos(t), math.sin(t), 0.0))
        self.assertEqual(h.export(w1(), objs).data, w1(), "no rotation written, so the gate is not needed either")
        h.change(objs, 1, position=(pos[0] + 0.0011, pos[1], pos[2]))
        self.assertNotEqual(h.export(w1(), objs).data, w1(), "0.0011 is outside the tolerance")

    def test_neutral_team_over_a_none_baseline_and_team_colour_are_unchanged(self):
        """4.9: W1 slot 5 stores team raw 0 (none). The glue hands back 8 (neutral): no change. Colour -1 is the team colour."""
        model = w1_model()
        self.assertEqual(model.objects()[1].team, -1)
        self.assertEqual(h.export(w1(), h.objects_for(model)).data, w1())

    def test_force_reencode_of_an_unchanged_model_equals_the_template(self):
        result = h.export(w1(), h.objects_for(w1()), force_reencode=True)
        self.assertTrue(result.ok)
        self.assertEqual(result.data, w1())
        self.assertEqual(result.stats["mode"], "forced")
        plain = h.export(w1(), h.objects_for(w1()))
        self.assertEqual(plain.stats["mode"], "passthrough")


def by_pos(objs, slot):
    return h.by_slot(objs, slot).position


# =====================================================================================================
class TestLengthChangingEdits(ContractCase):
    def test_tilt_to_vertical_drops_the_20_bit_up_code(self):
        objs = h.objects_for(w1())
        change = h.change(objs, 650, forward=(1.0, 0.0, 0.0), up=(0.0, 0.0, 1.0))        # slot 650 is tilted (up code 436468)
        data, result = ok_data(self, objs, **h.GATE)
        self.assert_shifted_edit(w1(), data, 650, -20)
        dec = h.decode(data)["slots"][650]
        self.assertEqual((dec["up_global"], dec["up_code"], dec["angle"]), (1, None, 8192))
        self.assertEqual(real_changes(self, result), [("edited", 650)])
        self.assertEqual(change.slot, 650)

    def test_colour_adds_and_removes_three_bits(self):
        objs = h.objects_for(w1())
        h.change(objs, 1, color=3)                                         # none -> 3: +3
        data, _ = ok_data(self, objs)
        self.assert_shifted_edit(w1(), data, 1, 3)
        self.assertEqual(h.decode(data)["slots"][1]["color"], 3)
        objs = h.objects_for(w1())
        h.change(objs, 650, color=-1)                                      # 7 -> team colour: -3
        data, _ = ok_data(self, objs)
        self.assert_shifted_edit(w1(), data, 650, -3)
        self.assertIsNone(h.decode(data)["slots"][650]["color"])
        objs = h.objects_for(w1())
        h.change(objs, 650, color=0)                                       # 7 -> 0: same length
        data, _ = ok_data(self, objs)
        self.assert_same_length_edit(w1(), data, 650, ["color"])

    def test_label_adds_and_removes_eight_bits(self):
        objs = h.objects_for(w1())
        h.change(objs, 1, label_index=2)                                   # none -> 2: +8
        data, _ = ok_data(self, objs)
        self.assert_shifted_edit(w1(), data, 1, 8)
        self.assertEqual(h.decode(data)["slots"][1]["label"], 2)
        objs = h.objects_for(w1())
        h.change(objs, 650, label_index=-1)                                # 2 -> none: -8
        data, _ = ok_data(self, objs)
        self.assert_shifted_edit(w1(), data, 650, -8)
        objs = h.objects_for(w1())
        h.change(objs, 5, label_index=0)                                   # 1 -> 0: same length
        data, _ = ok_data(self, objs)
        self.assert_same_length_edit(w1(), data, 5, ["label"])

    def test_shape_changes_add_and_remove_eleven_bits_per_dimension(self):
        objs = h.objects_for(w1())
        h.change(objs, 1, shape=1, width=10.0)                             # none -> radius only: +11
        data, _ = ok_data(self, objs)
        self.assert_shifted_edit(w1(), data, 1, 11)
        self.assertEqual(h.decode(data)["slots"][1]["dims"], [103])        # G-SH: 10.0 -> 103
        objs = h.objects_for(w1())
        h.change(objs, 5, shape=2)                                         # box (4 dims) -> cylinder (3): -11
        data, _ = ok_data(self, objs)
        self.assert_shifted_edit(w1(), data, 5, -11)
        self.assertEqual(len(h.decode(data)["slots"][5]["dims"]), 3)
        objs = h.objects_for(w1())
        h.change(objs, 5, shape=0)                                         # box -> none: -44
        data, _ = ok_data(self, objs)
        self.assert_shifted_edit(w1(), data, 5, -44)
        objs = h.objects_for(w1())
        h.change(objs, 650, shape=3, width=1.0, length=2.0, top=3.0, bottom=4.0)       # none -> box: +44
        data, _ = ok_data(self, objs)
        self.assert_shifted_edit(w1(), data, 650, 44)
        self.assertEqual(h.decode(data)["slots"][650]["dims"], [codecs.dim_encode(v) for v in (1.0, 2.0, 3.0, 4.0)])

    def test_a_dimension_change_inside_a_box_keeps_the_length(self):
        rec = w1_model().record_for(w1_model().slots[5])
        objs = h.objects_for(w1())
        h.change(objs, 5, top=rec.top + 5.0)
        data, _ = ok_data(self, objs)
        self.assert_same_length_edit(w1(), data, 5, ["dims"])
        before, after = h.decode(w1())["slots"][5]["dims"], h.decode(data)["slots"][5]["dims"]
        self.assertEqual(sum(1 for a, b in zip(before, after) if a != b), 1, "one of the four codes changed")
        self.assertEqual(before[0], after[0])

    def test_dimension_codes_are_kept_when_dim_encode_gives_the_same_code(self):
        """4.3: the glue compares codes, not floats; handing back float32(decoded) never rewrites a dimension."""
        import struct
        objs = h.objects_for(w1())
        for name in ("width", "length", "top", "bottom"):
            value = getattr(h.by_slot(objs, 5), name)
            setattr(h.by_slot(objs, 5), name, struct.unpack(">f", struct.pack(">f", value))[0])
        self.assertEqual(h.export(w1(), objs).data, w1())

    def test_delete_then_add_in_one_export_reuses_the_vacated_slot(self):
        objs = h.without(h.objects_for(w1()), 1)
        objs.append(h.new_object("Added", position=h.cell_centre(w1_model(), (7, 8, 9))))
        data, result = ok_data(self, objs, **h.GATE)
        dec = h.decode(data)
        self.assertEqual(sorted(dec["slots"]), [0, 5, 650], "the new object took the lowest absent slot, 0")
        self.assertEqual(dec["slots"][0]["pos"], [7, 8, 9])
        self.assertEqual(sorted(real_changes(self, result)), [("added", 0), ("removed", 1)])
        self.assertEqual([(q["folder"], q["placed_before"], q["placed_after"]) for q in result.stats["quota_changes"]], [],
                         "one deleted and one added in the same folder: the net change is zero")
        self.assert_hash_is_right(data)


# =====================================================================================================
class TestQuotaAndParents(ContractCase):
    def test_quota_rows_follow_adds_and_deletes_by_delta(self):
        objs = h.objects_for(w1())
        for i in range(3):
            objs.append(h.new_object("A%d" % i, position=h.cell_centre(w1_model(), (i, i, i))))
        data, result = ok_data(self, objs, **h.GATE)
        rows = h.decode(data)["quotas"]
        self.assertEqual((rows[70], rows[61]), ([0, 16, 5], [0, 1, 1]))
        self.assertEqual(result.warnings[0].code, "W_ORIENTATION_UNVERIFIED")
        self.assertEqual(result.warnings[0].message, "3 object(s) had their rotation written with an unverified convention.")

    def test_a_retarget_moves_the_count_between_two_rows(self):
        """Slot 1 changes from Block, 1x1 (folder 70) to Block, 1x1, Flat (folder 70, item 1): the same row, no delta."""
        objs = h.objects_for(w1())
        h.change(objs, 1, type_name="Block, 1x1, Flat")
        data, result = ok_data(self, objs)
        self.assertEqual(result.stats["quota_changes"], [])
        self.assertEqual(real_changes(self, result), [("retargeted", 1)])
        dec = h.decode(data)["slots"][1]
        self.assertEqual((dec["folder"], dec["item"]), (70, 1))
        self.assert_same_length_edit(w1(), data, 1, ["item"])

    def test_a_retarget_to_another_folder_changes_two_rows(self):
        """full650: Block, 1x1 (folder 70, class 0) -> Bridge, Small (folder 71, class 0 learned): row 70 loses one, row 71 gains one."""
        data = h.g3.data("full650")
        model = h.g3.model("full650")
        slot = next(r.slot for r in model.objects() if r.type_name == "Block, 1x1")
        objs = h.objects_for(model)
        h.change(objs, slot, type_name="Bridge, Small")
        result = h.export(data, objs)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual([(q["folder"], q["placed_before"], q["placed_after"]) for q in result.stats["quota_changes"]],
                         [(70, 163, 162), (71, 163, 164)])
        rows = h.decode(result.data)["quotas"]
        self.assertEqual((rows[70], rows[71]), ([0, 255, 162], [0, 255, 164]))
        self.assertEqual(real_changes(self, result), [("retargeted", slot)])
        self.assertNotIn("W_CACHED_TYPE_ASSUMED", h.codes(result.warnings), "the class is learned, not assumed")
        self.assert_same_length_edit(data, result.data, slot, ["folder"], quota_rows=[70, 71])
        self.assertEqual(h.decode(result.data)["slots"][slot]["folder"], 71)

    def test_a_retarget_into_a_full_row_is_refused_by_quota(self):
        """W1 row 71 is (0, 0, 0): moving an object into it exceeds its maximum."""
        objs = h.objects_for(w1())
        h.change(objs, 650, type_name="Bridge, Small")
        result = run(objs)
        self.assertFalse(result.ok)
        self.assertEqual([e.message for e in result.errors],
                         ["Palette entry 71 (Bridge, Small) would have 1 placed; the maximum on this map variant is 0."])

    def test_deleting_the_parent_clears_the_childs_link(self):
        objs = h.without(h.objects_for(w1()), 1)                           # slot 650 has parent slot 1 (parent_raw 2)
        data, result = ok_data(self, objs)
        self.assertEqual(h.decode(w1())["slots"][650]["parent_raw"], 2)
        self.assertEqual(h.decode(data)["slots"][650]["parent_raw"], 0)
        warning = [w for w in result.warnings if w.code == "W_PARENT_CLEARED"]
        self.assertEqual([(w.slot, w.message) for w in warning],
                         [(650, 'Slot 650 lost its "spawn relative to" parent because slot 1 was deleted.')])
        before = h.decode(w1())["slots"][650]
        after = h.decode(data)["slots"][650]
        self.assertEqual({k: v for k, v in before.items() if k != "parent_raw"}, {k: v for k, v in after.items() if k != "parent_raw"})

    def test_deleting_the_child_leaves_the_parent_alone(self):
        data, result = ok_data(self, h.without(h.objects_for(w1()), 650))
        self.assertNotIn("W_PARENT_CLEARED", h.codes(result.warnings))
        self.assertEqual(h.decode(data)["slots"][1], h.decode(w1())["slots"][1])


# =====================================================================================================
class TestHashAndLength(ContractCase):
    def test_hash_and_L_are_recomputed_for_every_edit_with_hashlib(self):
        edits = []
        objs = h.objects_for(w1())
        pos = by_pos(objs, 1)
        h.change(objs, 1, position=(pos[0] + 9.0, pos[1], pos[2]))
        edits.append(objs)
        edits.append(h.without(h.objects_for(w1()), 5))
        objs = h.objects_for(w1())
        objs.append(h.new_object("N", position=(1.0, 1.0, 1.0)))
        edits.append(objs)
        for objects in edits:
            data, result = ok_data(self, objects, **h.GATE)
            dec = h.decode(data)
            self.assertEqual(h.stored_length(data), (dec["end"] + 7) // 8)
            self.assert_hash_is_right(data)
            self.assertEqual(result.stats["L"], h.stored_length(data))
            self.assertEqual(result.stats["end_bit"], dec["end"])

    def test_the_embedded_file_length_and_chdr_are_untouched_for_a_plain_file(self):
        data, _ = ok_data(self, h.without(h.objects_for(w1()), 5))
        self.assertEqual(len(data), 29481)
        self.assertEqual(data[:h.MVAR], w1()[:h.MVAR], "_blf and chdr")
        self.assertEqual(data[h.PAD_AT:], w1()[h.PAD_AT:], "pad, _eof")


# =====================================================================================================
class TestCapacity(ContractCase):
    # A new Block, 1x1 on near_full: 81 bits + the three position axes (23 each, 150 in all) + the 5 + 5 extras of the learned
    # class 14 + the 3 bits of the learned example's colour = 163 bits; it replaces the one bit of the absent slot: +162.
    BLOCK_NET = 81 + 69 + 10 + 3 - 1

    def near_full(self, extra_free):
        """The ``near_full`` fixture with ``extra_free`` more free bits: label buffer bytes (8 bits each) and absent label
        entries (12 bits each) are removed. ``near_full`` itself has 100 free bits."""
        import copy
        build, _ = h.build_modules()
        spec = copy.deepcopy(build.load_spec("near_full"))
        entries = 0
        while (extra_free - 12 * entries) % 8:
            entries += 1
        assert entries <= 8 and extra_free >= 12 * entries
        spec["labels"]["pad_to"] -= (extra_free - 12 * entries) // 8
        used = set(s["label"] for s in h.decode(build.build(spec).data)["slots"].values() if s["label"] is not None) \
            if False else self.used_labels()
        spare = [i for i in range(255, -1, -1) if i not in used][:entries]
        spec["labels"]["strings_gen"]["absent"] = spare
        data = build.build(spec).data
        free = h.STREAM_BITS - h.decode(data)["end"]
        self.assertEqual(free, 100 + extra_free)
        return data

    def used_labels(self):
        return set(s["label"] for s in h.decode(h.g3.data("near_full"))["slots"].values() if s["label"] is not None)

    def attempt(self, data, **block):
        objs = h.objects_for(data)
        objs.append(h.new_like_example(data, "Block, 1x1", "Candidate", **block))
        return h.export(data, objs, **h.GATE, keep_unrecognised_imported=True, raise_quota_max=True)

    def test_a_near_full_file_refuses_an_add_with_the_exact_message_and_no_data(self):
        data = h.g3.data("near_full")
        model = MapVariant.from_bytes(data)
        self.assertEqual(model.end_bit, 229276)
        result = self.attempt(data)
        errors = [e for e in result.errors if e.code == "E_CAPACITY"]
        self.assertEqual(len(errors), 1)
        needed = 229276 + self.BLOCK_NET
        self.assertEqual(errors[0].message, "The edited map variant needs %d bits; it can hold at most 229,376." % needed)
        self.assertEqual(needed, 229438)
        self.assertFalse(result.ok)
        self.assertIsNone(result.data)
        self.assertEqual(result.stats["occupied_after"], 641)

    def test_the_capacity_error_comes_with_the_other_errors(self):
        data = h.g3.data("near_full")
        objs = h.objects_for(data)
        objs.append(h.new_like_example(data, "Block, 1x1", "Too big"))
        objs.append(h.new_like_example(data, "Block, 1x1", "Outside", position=(9999.0, 0.0, 0.0)))
        result = h.export(data, objs, **h.GATE, keep_unrecognised_imported=True, raise_quota_max=True)
        self.assertEqual(sorted(set(h.codes(result.errors))), ["E_CAPACITY", "E_OUT_OF_BOUNDS"])

    def test_a_small_edit_still_fits_in_a_full_stream(self):
        data = h.g3.data("near_full")
        objs = h.objects_for(data)
        pos = h.by_slot(objs, 1).position
        h.change(objs, 1, position=(pos[0] + 5.0, pos[1], pos[2]))
        result = h.export(data, objs, keep_unrecognised_imported=True)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual(result.stats["end_bit"], 229276)

    def test_an_edit_that_ends_exactly_at_the_capacity_is_written(self):
        # team colour instead of the example's colour (-3) and a cylinder (+33): the block costs 162 - 3 + 33 = 192 = 100 + 92 free bits
        data = self.near_full(92)
        result = self.attempt(data, color=-1, shape=2, width=2.0, top=1.0, bottom=1.0)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual(result.stats["end_bit"], h.STREAM_BITS)
        self.assertEqual(h.decode(result.data)["end"], h.STREAM_BITS)
        self.assertEqual(result.stats["L"], 0x7000)
        self.assert_hash_is_right(result.data)

    def test_one_bit_over_the_capacity_is_refused(self):
        data = self.near_full(72)                                        # 172 free bits; a block with a radius costs 162 + 11 = 173
        result = self.attempt(data, shape=1, width=2.0)
        self.assertEqual([e.message for e in result.errors], ["The edited map variant needs 229377 bits; it can hold at most 229,376."])
        self.assertIsNone(result.data)
        self.assertFalse(result.ok)
        fits = self.attempt(data, shape=0)                               # without the radius it fits with 10 bits to spare
        self.assertTrue(fits.ok, [e.message for e in fits.errors])
        self.assertEqual(fits.stats["end_bit"], h.STREAM_BITS - 10)


# =====================================================================================================
class TestType19Extras(ContractCase):
    """Class 19 (location names) is written under the rule the template determined; both rules are tested."""

    def setUp(self):
        self.options = dict(keep_unrecognised_imported=True, raise_quota_max=True)

    def location(self, name, slot):
        data = h.g3.data(name)
        model = h.g3.model(name)
        return data, model, h.objects_for(model)

    def test_changing_the_index_of_a_location_name_keeps_the_length_under_flag8(self):
        data, model, objs = self.location("type19_flag8", 101)
        self.assertEqual(model.type19_status, "flag8")
        h.change(objs, 101, other_a=77)                                   # was 5
        result = h.export(data, objs, **self.options)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual(h.decode(result.data)["slots"][101]["extra"], [0, 77])
        self.assert_same_length_edit(data, result.data, 101, ["extras"])

    def test_none_to_an_index_adds_the_eight_bits_under_flag8(self):
        data, model, objs = self.location("type19_flag8", 100)
        self.assertEqual(h.by_slot(objs, 100).other_a, -1)
        h.change(objs, 100, other_a=9)
        result = h.export(data, objs, **self.options)
        self.assertTrue(result.ok)
        self.assertEqual(h.decode(result.data)["slots"][100]["extra"], [0, 9])
        self.assert_shifted_edit(data, result.data, 100, 8)
        again = h.g3.model("type19_flag8")
        back = h.objects_for(MapVariant.from_bytes(result.data))
        h.change(back, 100, other_a=-1)
        r2 = h.export(result.data, back, **self.options)
        self.assertEqual(r2.data, data, "none again: the original bytes")

    def test_plain8_stores_the_index_plus_one(self):
        data, model, objs = self.location("type19_plain8", 101)
        self.assertEqual(model.type19_status, "plain8")
        h.change(objs, 101, other_a=77)
        result = h.export(data, objs, **self.options)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual(h.decode(result.data)["slots"][101]["extra"], [78])
        self.assert_same_length_edit(data, result.data, 101, ["extras"])
        objs = h.objects_for(MapVariant.from_bytes(data))
        h.change(objs, 100, other_a=-1)
        self.assertEqual(h.export(data, objs, **self.options).data, data, "-1 over a none baseline is unchanged")

    def test_range_of_the_index(self):
        data, model, objs = self.location("type19_flag8", 101)
        h.change(objs, 101, other_a=256)
        result = h.export(data, objs, **self.options)
        self.assertEqual([e.message for e in result.errors], ["Object '101 - Location Name': other_a must be 0 to 255."])
        data, model, objs = self.location("type19_plain8", 101)
        h.change(objs, 101, other_a=255)
        self.assertEqual([e.message for e in h.export(data, objs, **self.options).errors],
                         ["Object '101 - Location Name': other_a must be 0 to 254."])


if __name__ == "__main__":
    unittest.main()
