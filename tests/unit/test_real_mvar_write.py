"""T3-real, write side (SPEC 9.1; gate G5): the one real Halo: Reach map variant, ``0aaaf8c7-...mvar`` ("Headstrong", Breakneck).

Everything happens on bytes in memory: the original is opened ``rb`` only (through ``helpers_g3.real_data``), nothing is
written next to it and no temporary copy of it is made. Without the file the whole module is SKIPPED with a loud notice.

* a no-op export returns all 59,392 bytes of the input (the 29,911-byte zero trailer included), and so does a forced
  re-encode of the whole model;
* moving one object by +1.0 world unit in x changes ONLY that slot's 23 ``pos_x`` bits and the 20 SHA-1 bytes (plain_le32,
  recomputed here with ``hashlib``); L, the trailer and the total length are untouched; the expected bit range comes from
  the independent walker of the fixture builder; the re-parsed slot moved by 1.0 within the quantisation step ``40000 / 2^23``
  and the other 609 slots are bit-identical;
* five Blocks with ``raise_quota_max`` land in slots 610 to 614 (the block row is raised per decision D11, the stream grows by
  the sum of the new records, L and the hash follow); without the option the export is refused ``E_QUOTA`` with no data;
* deleting an object lowers its quota row and shrinks the stream; 40 additions fit the 650 limit and 41 are ``E_TOO_MANY``;
* the exact refusals for a non-stock name, a folder at or above the quota count, a position outside the bounds, a rotation
  without the gate and a placement-flag change; ``hash_policy`` forcing and flavour reproduction.
"""
import hashlib
import math
import os
import random
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import helpers_g5 as h  # noqa: E402

from mvarlib import api, tables  # noqa: E402
from mvarlib.model import MapVariant  # noqa: E402

REAL_SHA256 = "e514a53b61977a897ac9dbf7225085aa01b5b255f3c8079b5938ef87579bb254"
CELL = 40000.0 / (1 << 23)                       # bounds +-20000, 23 bits per axis
MIN = -20000.0
SPAN = 0x7000


def require_real():
    if not h.g3.real_available():
        sys.stderr.write("\n" + "=" * 78 + "\nNOTICE: the real map variant %s is absent;\n"
                         "        T3-real write tests (test_real_mvar_write) are SKIPPED, not passed.\n" % h.g3.REAL_MVAR + "=" * 78 + "\n")
        raise unittest.SkipTest("NOTICE: the real map variant is absent (%s); the T3-real write tests are skipped" % h.g3.REAL_MVAR)


def sha1_plain_le32(data):
    """SHA1(LE32(L) || stream[0:L]) with the L stored in ``data`` (big-endian): hashlib only, no library code."""
    length = struct.unpack(">I", data[h.LENGTH_AT:h.LENGTH_AT + 4])[0]
    return hashlib.sha1(struct.pack("<I", length) + data[h.STREAM_AT:h.STREAM_AT + length]).digest()


def sha1_salted_be32(data, endian=">"):
    length = struct.unpack(endian + "I", data[h.LENGTH_AT:h.LENGTH_AT + 4])[0]
    _b, selfcheck = h.build_modules()
    return selfcheck.digest("salted_be32", h.stream_bytes(data), length)


def cell_for(value):
    """The containing cell of a world coordinate on the real file's axes (floor), written out independently."""
    return int(math.floor((value - MIN) / CELL))


class RealWriteCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_real()
        cls.data = h.g3.real_data()
        cls.sha_before = hashlib.sha256(cls.data).hexdigest()
        cls.model = MapVariant.from_bytes(cls.data, None, "real")
        cls.dec = h.decode(cls.data)                          # the independent walker's reading of the original

    @classmethod
    def tearDownClass(cls):
        with open(h.g3.REAL_MVAR, "rb") as handle:
            after = hashlib.sha256(handle.read()).hexdigest()
        assert after == cls.sha_before == REAL_SHA256, "the real sample changed during the test"

    def objects(self):
        return h.objects_for(self.model)

    def export(self, objects, **options):
        return h.export(self.data, objects, **options)

    def changed_bytes(self, out):
        return [i for i in range(len(self.data)) if self.data[i] != out[i]]

    def slots_of_folder(self, folder):
        return sorted(i for i, s in self.dec["slots"].items() if s["folder"] == folder)


class TestNoOpAndForced(RealWriteCase):
    def test_a_no_op_export_returns_all_59392_bytes(self):
        result = self.export(self.objects())
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual(len(result.data), 59392)
        self.assertEqual(result.data, self.data)
        self.assertEqual(result.stats["mode"], "passthrough")
        self.assertEqual((result.stats["occupied_before"], result.stats["occupied_after"]), (610, 610))
        self.assertEqual([e.kind for e in result.diff], ["kept"] * 610)
        self.assertEqual(h.codes(result.warnings), ["I_BUDGET", "I_PALETTE", "I_UNVERIFIED"])
        self.assertEqual(result.warnings[1].message, "Edits were written against the palette recorded in the file (CRC 0xE1DE4A26). "
                                                     "If MCC rebuilds the variant from the scenario, changes may be lost (unverified).")

    def test_a_forced_re_encode_of_the_whole_model_equals_the_input(self):
        self.assertEqual(self.model.to_bytes(force=True), self.data)
        result = self.export(self.objects(), force_reencode=True)
        self.assertTrue(result.ok)
        self.assertEqual(result.data, self.data)
        self.assertEqual(result.stats["mode"], "forced")
        self.assertEqual(len(result.data), 59392)

    def test_the_trailer_is_part_of_the_bytes_and_not_a_warning_without_a_change(self):
        result = self.export(self.objects(), force_reencode=True)
        self.assertEqual(result.data[29481:], bytes(29911))
        self.assertNotIn("W_TRAILER_KEPT", h.codes(result.warnings), "nothing was modified, only re-encoded to the same bytes")

    def test_the_originals_flavour_is_plain_le32_with_a_big_endian_length(self):
        self.assertEqual(self.model.flavour, (">", "plain_le32"))
        self.assertEqual(h.stored_hash(self.data), sha1_plain_le32(self.data))
        self.assertEqual(h.stored_length(self.data), 13311)


class TestMoveOneObject(RealWriteCase):
    def move(self, slot, axis=0, delta=1.0):
        objs = self.objects()
        pos = list(h.by_slot(objs, slot).position)
        pos[axis] += delta
        h.change(objs, slot, position=tuple(pos))
        result = self.export(objs)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        return result

    def check_contract(self, result, slot, axis, expected_fields=None):
        out = result.data
        field = ("pos_x", "pos_y", "pos_z")[axis]
        lo, hi = h.slot_span(self.dec, slot, field)
        self.assertEqual(hi - lo, 23)
        # expected differing region: those 23 bits of the stream, the 20 SHA-1 bytes, nothing else (L is unchanged)
        allowed_bytes = set(range(h.STREAM_AT + lo // 8, h.STREAM_AT + (hi - 1) // 8 + 1)) | set(range(h.HASH_AT, h.HASH_AT + 20))
        changed = self.changed_bytes(out)
        self.assertTrue(changed)
        self.assertEqual([i for i in changed if i not in allowed_bytes], [], "bytes changed outside pos bits and the SHA-1")
        stream_diff = h.stream_diff(self.data, out)
        self.assertTrue(stream_diff)
        self.assertTrue(all(lo <= b < hi for b in stream_diff), "stream bits outside the %s bits changed" % field)
        self.assertEqual(h.stored_length(out), h.stored_length(self.data), "a same-length edit keeps L")
        self.assertEqual(out[h.LENGTH_AT:h.LENGTH_AT + 4], self.data[h.LENGTH_AT:h.LENGTH_AT + 4])
        self.assertEqual(len(out), 59392)
        self.assertEqual(out[29481:], bytes(29911), "the trailer is preserved")
        self.assertEqual(h.stored_hash(out), sha1_plain_le32(out), "SHA-1 recomputed with hashlib (plain_le32)")
        self.assertNotEqual(h.stored_hash(out), h.stored_hash(self.data))

    def test_move_one_object_by_plus_one_in_x(self):
        slot = 305
        result = self.move(slot)
        self.check_contract(result, slot, 0)
        again = MapVariant.from_bytes(result.data)
        before, after = self.model.record_for(self.model.slots[slot]), again.record_for(again.slots[slot])
        self.assertLessEqual(abs((after.position[0] - before.position[0]) - 1.0), CELL, "moved by 1.0 within the quantisation step")
        self.assertEqual(after.position[1:], before.position[1:])
        self.assertEqual(again.slots[slot].pos[0], cell_for(before.position[0] + 1.0))
        same = [i for i in range(651) if again.slots[i].raw == self.model.slots[i].raw]
        self.assertEqual(len(same), 650, "all but the moved slot are bit-identical (651 slots in all)")
        self.assertEqual([i for i in range(651) if i not in same], [slot])
        self.assertEqual(again.to_bytes(force=True), result.data)
        self.assertEqual([(e.kind, e.slot) for e in result.diff if e.kind != "kept"], [("moved", slot)])
        self.assertEqual(result.stats["mode"], "patched")
        self.assertIn("W_TRAILER_KEPT", h.codes(result.warnings))
        self.assertEqual([w.message for w in result.warnings if w.code == "W_TRAILER_KEPT"],
                         ["29911 bytes after the end-of-file block were kept unchanged."])

    def test_the_other_609_non_moved_present_slots_decode_identically(self):
        slot = 12
        result = self.move(slot)
        dec = h.decode(result.data)
        for i, s in self.dec["slots"].items():
            if i != slot:
                self.assertEqual(dec["slots"][i], s, "slot %d" % i)
        self.assertEqual(len(dec["slots"]), 610)
        self.assertEqual(dec["quotas"], self.dec["quotas"])

    def test_first_middle_and_last_object_each_axis(self):
        for slot in (0, 305, 609):
            for axis in (0, 1, 2):
                with self.subTest("slot %d axis %d" % (slot, axis)):
                    result = self.move(slot, axis, 1.0)
                    self.check_contract(result, slot, axis)

    def test_negative_and_fractional_moves_and_random_slots(self):
        rng = random.Random(20261010)
        for _ in range(12):
            slot = rng.randrange(610)
            axis = rng.randrange(3)
            delta = rng.choice([-7.5, -1.0, -0.01, 0.05, 0.3, 2.0, 123.456])
            with self.subTest("slot %d axis %d delta %r" % (slot, axis, delta)):
                result = self.move(slot, axis, delta)
                self.check_contract(result, slot, axis)
                again = MapVariant.from_bytes(result.data)
                old = self.model.record_for(self.model.slots[slot]).position[axis]
                new = again.record_for(again.slots[slot]).position[axis]
                self.assertLessEqual(abs((new - old) - delta), CELL)

    def test_a_move_below_the_tolerance_writes_nothing(self):
        objs = self.objects()
        pos = h.by_slot(objs, 7).position
        h.change(objs, 7, position=(pos[0] + 0.002, pos[1], pos[2]))              # POS_TOL here is 2^-8 = 0.0039 (two float32 steps at 20000)
        self.assertTrue(self.export(objs).data == self.data)

    def test_the_tolerance_on_these_axes_is_two_float32_steps_and_inclusive(self):
        """POS_TOL = max(1e-3, cell / 2, 2 ulp32(20000)) = max(0.001, 0.00238, 0.00390625) = 2^-8 here; every value below is exact in binary."""
        tol = 2.0 ** -8
        self.assertEqual(tol, 0.00390625)
        self.assertEqual(CELL / 2.0, 0.002384185791015625)
        objs = self.objects()
        pos = h.by_slot(objs, 7).position
        h.change(objs, 7, position=(pos[0] + tol, pos[1], pos[2]))
        self.assertTrue(self.export(objs).data == self.data, "exactly the tolerance is unchanged")
        h.change(objs, 7, position=(pos[0] - tol, pos[1], pos[2]))
        self.assertTrue(self.export(objs).data == self.data)
        h.change(objs, 7, position=(pos[0] + tol + 2.0 ** -20, pos[1], pos[2]))
        self.assertTrue(self.export(objs).data != self.data, "a hair more is a move")

    def test_a_move_just_above_the_tolerance_is_written(self):
        objs = self.objects()
        pos = h.by_slot(objs, 7).position
        h.change(objs, 7, position=(pos[0] + 0.01, pos[1], pos[2]))
        self.assertTrue(self.export(objs).data != self.data)

    def test_the_move_is_independent_of_the_other_objects_being_handed_back_unchanged(self):
        a = self.move(100).data
        b = self.move(100).data
        self.assertEqual(a, b)


class TestAddFiveBlocks(RealWriteCase):
    def blocks(self, count, **fields):
        return [h.new_object("Star %03d" % i, "Block, 1x1", (float(i) * 2.0, 0.0, 30.0), forward=(1.0, 0.0, 0.0), physics=1, **fields)
                for i in range(count)]

    def test_five_blocks_with_the_quota_option(self):
        result = self.export(self.objects() + self.blocks(5), allow_unverified_rotation=True, raise_quota_max=True)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        out = result.data
        dec = h.decode(out)
        self.assertEqual(sorted(i for i in dec["slots"] if i >= 610), [610, 611, 612, 613, 614])
        self.assertEqual(len(dec["slots"]), 615)
        sizes = []
        for n, slot in enumerate(range(610, 615)):
            s = dec["slots"][slot]
            self.assertEqual((s["folder"], s["item"], s["flags2"], s["in_bounds"]), (63, 0, 1, 1))
            self.assertEqual(s["pos"], [cell_for(n * 2.0), cell_for(0.0), cell_for(30.0)])
            self.assertEqual((s["up_global"], s["up_code"], s["angle"], s["parent_raw"]), (1, None, 8192, 0))
            self.assertEqual((s["shape"], s["dims"], s["spawn_seq"], s["respawn"], s["cached_type"], s["label"]), (0, [], 0, 0, 0, None))
            self.assertEqual((s["placement"], s["team_raw"], s["color"], s["extra"]), (0x4C, 9, None, []))
            lo, hi = dec["slot_ranges"][slot]
            sizes.append(hi - lo)
        self.assertEqual(sizes, [150] * 5, "81 bits + three 23-bit axes")
        # the quota row of the block folder: placed 5, maximum raised from 0 to 5 (D11), minimum untouched; no other row changed
        self.assertEqual(self.dec["quotas"][63], [0, 0, 0])
        self.assertEqual(dec["quotas"][63], [0, 5, 5])
        self.assertEqual([i for i in range(82) if dec["quotas"][i] != self.dec["quotas"][i]], [63])
        # the stream grows by the sum of the new records, minus the one absent bit each one replaced
        self.assertEqual(dec["end"] - self.dec["end"], sum(sizes) - 5)
        self.assertEqual(dec["end"], 106487 + 745)
        self.assertEqual(h.stored_length(out), (dec["end"] + 7) // 8)
        self.assertEqual(h.stored_length(out), 13404)
        self.assertEqual(h.stored_hash(out), sha1_plain_le32(out))
        # the original's slots 0..609 and the bits before slot 610 did not move
        start = self.dec["slot_ranges"][609][1]
        a = int.from_bytes(h.stream_bytes(self.data), "big") >> (h.STREAM_BITS - start)
        b = int.from_bytes(h.stream_bytes(out), "big") >> (h.STREAM_BITS - start)
        self.assertEqual(a, b)
        self.assertEqual(len(out), 59392)
        self.assertEqual(out[29481:], bytes(29911))
        self.assertEqual(self.changed_bytes(out)[0], h.HASH_AT, "everything before the SHA-1 is untouched: _blf, chdr and the mvar header")
        # what the library says about it
        again = MapVariant.from_bytes(out)
        self.assertEqual(again.occupied, 615)
        self.assertEqual(again.flavour, (">", "plain_le32"))
        self.assertEqual(again.to_bytes(force=True), out)
        for slot in range(610, 615):
            rec = again.record_for(again.slots[slot])
            self.assertEqual((rec.type_id, rec.type_name, rec.stock, rec.cached_type, rec.placement, rec.physics), (0x3F00, "Block, 1x1", True, 0, 0x4C, 1))
            self.assertEqual(rec.orientation_kind, "vertical")
            self.assertLessEqual(abs(rec.position[0] - (slot - 610) * 2.0), CELL)
        self.assertEqual(result.stats["quota_changes"],
                         [{"folder": 63, "name": "Block, 1x1", "minimum": 0, "placed_before": 0, "placed_after": 5,
                           "maximum_before": 0, "maximum_after": 5}])
        codes = h.codes(result.warnings)
        for code in ("W_QUOTA_MAX_RAISED", "W_CACHED_TYPE_ASSUMED", "W_ORIENTATION_UNVERIFIED", "W_TRAILER_KEPT"):
            self.assertIn(code, codes)
        self.assertEqual([w.message for w in result.warnings if w.code == "W_QUOTA_MAX_RAISED"],
                         ["Quota maximum raised: unverified. Palette entry 63 (Block, 1x1) now has 5 placed; its maximum was raised "
                          "from 0 to 5. Whether the game honours the file's maximum or rebuilds it from the scenario is unknown."])
        self.assertEqual([w.message for w in result.warnings if w.code == "W_CACHED_TYPE_ASSUMED"],
                         ["The object class of the new 'Block, 1x1' was assumed from its palette group, not learned from the map."])
        self.assertEqual([(e.kind, e.slot) for e in result.diff if e.kind != "kept"], [("added", n) for n in range(610, 615)])

    def test_the_same_five_blocks_without_the_option_are_refused_with_no_data(self):
        result = self.export(self.objects() + self.blocks(5), allow_unverified_rotation=True)
        self.assertFalse(result.ok)
        self.assertIsNone(result.data)
        self.assertEqual([e.message for e in result.errors],
                         ["Palette entry 63 (Block, 1x1) would have 5 placed; the maximum on this map variant is 0."])
        self.assertEqual(result.errors[0].code, "E_QUOTA")
        self.assertEqual(result.stats["quota_changes"], [])

    def test_a_single_block_is_refused_without_the_option_and_exact_with_it(self):
        refused = self.export(self.objects() + self.blocks(1), allow_unverified_rotation=True)
        self.assertEqual([e.message for e in refused.errors],
                         ["Palette entry 63 (Block, 1x1) would have 1 placed; the maximum on this map variant is 0."])
        result = self.export(self.objects() + self.blocks(1), allow_unverified_rotation=True, raise_quota_max=True)
        self.assertTrue(result.ok)
        dec = h.decode(result.data)
        self.assertEqual(dec["quotas"][63], [0, 1, 1])
        self.assertEqual(dec["end"] - self.dec["end"], 149)

    def test_the_option_never_lowers_a_maximum_and_leaves_rows_with_room_alone(self):
        """Rocket Launcher (row 4) is (0, 3, 2): one more is inside the maximum; nothing is raised."""
        rl = h.new_like_example(self.model, "Rocket Launcher", "Extra rocket launcher", position=(0.0, 0.0, 10.0))
        result = self.export(self.objects() + [rl], allow_unverified_rotation=True, raise_quota_max=True)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual(h.decode(result.data)["quotas"][4], [0, 3, 3])
        self.assertNotIn("W_QUOTA_MAX_RAISED", h.codes(result.warnings))
        two = [h.new_like_example(self.model, "Rocket Launcher", "RL %d" % i, position=(float(i), 0.0, 10.0)) for i in range(2)]
        refused = self.export(self.objects() + two, allow_unverified_rotation=True)
        self.assertEqual([e.message for e in refused.errors],
                         ["Palette entry 4 (Rocket Launcher) would have 4 placed; the maximum on this map variant is 3."])
        raised = self.export(self.objects() + two, allow_unverified_rotation=True, raise_quota_max=True)
        self.assertEqual(h.decode(raised.data)["quotas"][4], [0, 4, 4])
        self.assertEqual(self.dec["quotas"][4], [0, 3, 2])

    def test_a_learned_class_and_placement_come_from_the_templates_own_objects(self):
        """Street Cone (folder 53) exists 4 times as class 0 / 0x0C / team 9: a new one copies it, physics included."""
        cone = h.new_like_example(self.model, "Street Cone", "New cone", position=(1.0, 2.0, 3.0))
        self.assertEqual((cone.physics, cone.team, cone.symmetry), (0, 8, 3))
        result = self.export(self.objects() + [cone], allow_unverified_rotation=True, raise_quota_max=True)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        s = h.decode(result.data)["slots"][610]
        self.assertEqual((s["folder"], s["item"], s["cached_type"], s["placement"], s["team_raw"], s["color"]), (53, 0, 0, 0x0C, 9, None))
        self.assertNotIn("W_CACHED_TYPE_ASSUMED", h.codes(result.warnings), "learned, not assumed")
        self.assertEqual(h.decode(result.data)["quotas"][53], [0, 5, 5], "(0, 4, 4) -> maximum raised to the new placed")

    def test_a_new_block_in_a_folder_with_a_fixed_physics_example(self):
        """A physics change over the learned example only rewrites bits 6-7: Fixed on a crate-like example keeps its other bits."""
        crate = h.new_like_example(self.model, "Crate, Heavy, Small", "Crate", position=(0.0, 0.0, 10.0))
        self.assertEqual(crate.physics, 1)                                       # the example is 0x4C
        result = self.export(self.objects() + [crate], allow_unverified_rotation=True, raise_quota_max=True)
        self.assertEqual(h.decode(result.data)["slots"][610]["placement"], 0x4C)
        crate.physics = 3
        result = self.export(self.objects() + [crate], allow_unverified_rotation=True, raise_quota_max=True)
        self.assertEqual(h.decode(result.data)["slots"][610]["placement"], 0xCC)

    def test_the_rotation_gate_is_required_for_new_objects(self):
        result = self.export(self.objects() + self.blocks(1), raise_quota_max=True)
        self.assertEqual(h.codes(result.errors), ["E_ROTATION_GATED"])

    def test_40_additions_fit_and_41_are_too_many(self):
        ok = self.export(self.objects() + self.blocks(40), allow_unverified_rotation=True, raise_quota_max=True)
        self.assertTrue(ok.ok, [e.message for e in ok.errors])
        self.assertEqual(ok.stats["occupied_after"], 650)
        dec = h.decode(ok.data)
        self.assertEqual(sorted(i for i in dec["slots"] if i >= 610), list(range(610, 650)))
        self.assertEqual(dec["quotas"][63], [0, 40, 40])
        self.assertEqual(dec["end"] - self.dec["end"], 40 * 149)
        self.assertEqual(h.stored_hash(ok.data), sha1_plain_le32(ok.data))
        too_many = self.export(self.objects() + self.blocks(41), allow_unverified_rotation=True, raise_quota_max=True)
        self.assertFalse(too_many.ok)
        self.assertIsNone(too_many.data)
        self.assertEqual(h.codes(too_many.errors), ["E_TOO_MANY"])
        self.assertEqual(too_many.errors[0].message,
                         "651 objects would be written; the limit is 650. Remove 1 object(s). (A file that already holds more than 650 objects cannot be exported.)")
        self.assertEqual(too_many.stats["occupied_after"], 651)

    def test_the_forty_first_slot_exists_so_only_the_limit_stops_it(self):
        self.assertEqual(sum(1 for s in self.model.slots if not s.present), 41)
        raised = self.export(self.objects() + self.blocks(41), allow_unverified_rotation=True, raise_quota_max=True, max_objects=651)
        self.assertTrue(raised.ok, "the 651st slot can be written when the limit is lifted; it is a policy, not a format limit")
        beyond = self.export(self.objects() + self.blocks(42), allow_unverified_rotation=True, raise_quota_max=True, max_objects=1000)
        self.assertEqual(h.codes(beyond.errors), ["E_NO_FREE_SLOT"])
        self.assertEqual(beyond.errors[0].message, "No free object slot is left for 'Star 041'.")


class TestDeleteOneObject(RealWriteCase):
    def delete(self, slot):
        objs = h.without(self.objects(), slot)
        result = self.export(objs)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        return result

    def check_shift(self, out, slot, folder):
        dec = h.decode(out)
        lo, hi = self.dec["slot_ranges"][slot]
        self.assertEqual(dec["end"] - self.dec["end"], -((hi - lo) - 1))
        self.assertEqual(sorted(dec["slots"]), sorted(i for i in self.dec["slots"] if i != slot))
        for i, s in dec["slots"].items():
            self.assertEqual(s, self.dec["slots"][i], "slot %d" % i)
        before = self.dec["quotas"]
        self.assertEqual([i for i in range(82) if dec["quotas"][i] != before[i]], [folder])
        self.assertEqual(dec["quotas"][folder][2], before[folder][2] - 1)
        self.assertEqual(dec["quotas"][folder][:2], before[folder][:2], "minimum and maximum are never rewritten by a delete")
        self.assertEqual(h.stored_length(out), (dec["end"] + 7) // 8)
        self.assertEqual(h.stored_hash(out), sha1_plain_le32(out))
        self.assertEqual(len(out), 59392)
        self.assertEqual(out[29481:], bytes(29911))

    def test_delete_a_street_cone(self):
        slot = self.slots_of_folder(53)[0]
        result = self.delete(slot)
        self.check_shift(result.data, slot, 53)
        self.assertEqual(h.decode(result.data)["quotas"][53], [0, 4, 3])
        self.assertEqual([(e.kind, e.slot, e.name) for e in result.diff if e.kind != "kept"], [("removed", slot, "%d - Street Cone" % slot)])
        self.assertEqual(result.stats["occupied_after"], 609)

    def test_delete_the_only_object_of_a_row(self):
        slot = self.slots_of_folder(31)[0]                                       # the Fusion Coil: row 31 is (0, 1, 1)
        result = self.delete(slot)
        self.check_shift(result.data, slot, 31)
        self.assertEqual(h.decode(result.data)["quotas"][31], [0, 1, 0])

    def test_delete_the_first_and_the_last_object(self):
        for slot in (0, 609):
            with self.subTest(slot):
                result = self.delete(slot)
                self.check_shift(result.data, slot, self.dec["slots"][slot]["folder"])

    def test_delete_several_and_a_whole_folder(self):
        slots = self.slots_of_folder(8)                                          # 20 frag grenades
        objs = h.without(self.objects(), *slots)
        result = self.export(objs)
        self.assertTrue(result.ok)
        dec = h.decode(result.data)
        self.assertEqual(dec["quotas"][8], [0, 20, 0])
        self.assertEqual(len(dec["slots"]), 590)
        self.assertEqual(h.stored_hash(result.data), sha1_plain_le32(result.data))

    def test_a_delete_below_the_minimum_is_refused(self):
        """Real rows all have minimum 0; with a minimum of 1 on the Fusion Coil row the delete would be refused (SPEC 7.5)."""
        _b, selfcheck = h.build_modules()
        start = self.dec["sections"]["quotas"] + 24 * 31                          # the minimum byte of row 31 (not byte aligned)
        stream = selfcheck.set_bits(h.stream_bytes(self.data), start, 8, 1)
        data = self.data[:h.STREAM_AT] + stream + self.data[h.STREAM_END:]        # the SHA-1 is stale now: forced by hash_policy below
        self.assertEqual(MapVariant.from_bytes(data).quotas[31].as_tuple(), (1, 1, 1))
        objs = h.objects_for(data)
        result = h.export(data, h.without(objs, self.slots_of_folder(31)[0]), hash_policy="PLAIN_LE32")
        self.assertEqual([e.message for e in result.errors],
                         ["Palette entry 31 (Fusion Coil) would drop to 0 placed; the minimum on this map variant is 1."])
        self.assertEqual(result.errors[0].code, "E_QUOTA_MIN")
        # deleting nothing, or deleting from a row that stays at or above its minimum, is fine
        self.assertTrue(h.export(data, objs, hash_policy="PLAIN_LE32").ok)


class TestRefusals(RealWriteCase):
    def new(self, **fields):
        base = dict(name="N", type_name="Block, 1x1", position=(0.0, 0.0, 30.0))
        base.update(fields)
        return h.new_object(**base)

    def refused(self, extra, expected_codes, expected_messages, **options):
        options.setdefault("allow_unverified_rotation", True)
        options.setdefault("raise_quota_max", True)
        result = self.export(self.objects() + extra, **options)
        self.assertFalse(result.ok)
        self.assertIsNone(result.data, "a refusal writes no byte")
        self.assertEqual(h.codes(result.errors), expected_codes)
        self.assertEqual([e.message for e in result.errors], expected_messages)
        return result

    def test_non_stock_object_name(self):
        self.refused([self.new(type_name="Block, 3x3, Flat")], ["E_OBJ_NAME_UNKNOWN"],
                     ["Object 'N' uses 'Block, 3x3, Flat', which is not a stock object on Breakneck."])
        self.assertNotIn("Block, 3x3, Flat", tables.stock_object_names("Breakneck"))
        self.assertIn("Block, 3x3, Flat", tables.stock_object_names("Forge World"))

    def test_non_stock_object_id(self):
        self.refused([self.new(type_name="", type_id_hint=0x0101)], ["E_OBJ_NOT_STOCK"],
                     ["Object 'N' (id 0x0101) is not a stock object on Breakneck."])

    def test_folder_at_or_above_the_quota_count(self):
        self.assertIn("Falcon, Nose Gun", tables.stock_object_names("Breakneck"))
        self.assertEqual(self.model.fixed.quota_count, 82)
        self.refused([self.new(type_name="Falcon, Nose Gun")], ["E_FOLDER_RANGE"],
                     ["Object 'N' needs palette entry 82, but this map variant defines only 82 entries."])

    def test_position_outside_the_bounds(self):
        message = ("Object 'N' is at (30000.000, 0.000, 30.000), outside the map bounds (x -20000.0 to 20000.0, y -20000.0 to 20000.0, "
                   "z -20000.0 to 20000.0). Move it inside; positions are never clamped.")
        self.refused([self.new(position=(30000.0, 0.0, 30.0))], ["E_OUT_OF_BOUNDS"], [message])
        self.refused([self.new(position=(20000.0, 0.0, 30.0))], ["E_OUT_OF_BOUNDS"],
                     [message.replace("30000.000", "20000.000")])
        ok = self.export(self.objects() + [self.new(position=(19999.9, -20000.0, 30.0))], allow_unverified_rotation=True, raise_quota_max=True)
        self.assertTrue(ok.ok, "the bound is [min, max): -20000.0 itself is inside")

    def test_moving_an_existing_object_outside_the_bounds(self):
        objs = self.objects()
        pos = h.by_slot(objs, 4).position
        h.change(objs, 4, position=(pos[0], pos[1] + 25000.0, pos[2]))
        result = self.export(objs)
        self.assertEqual(h.codes(result.errors), ["E_OUT_OF_BOUNDS"])
        self.assertTrue(result.errors[0].message.startswith("Object '4 - "))
        self.assertIsNone(result.data)

    def test_rotation_change_without_the_gate(self):
        objs = self.objects()
        vertical = next(r for r in self.model.objects() if r.orientation_kind == "vertical")
        h.change(objs, vertical.slot, forward=(0.0, 1.0, 0.0) if abs(vertical.forward[1]) < 0.5 else (1.0, 0.0, 0.0))
        result = self.export(objs)
        self.assertEqual(h.codes(result.errors), ["E_ROTATION_GATED"])
        self.assertEqual(result.errors[0].message,
                         "Object '%d - %s' has a new or changed rotation. Writing rotation is unverified: tick Forge Scene > "
                         "\"Allow unverified rotation export\" to write it." % (vertical.slot, vertical.type_name))
        self.assertIsNone(result.data)
        allowed = self.export(objs, allow_unverified_rotation=True)
        self.assertTrue(allowed.ok)
        self.assertEqual(h.decode(allowed.data)["slots"][vertical.slot]["up_global"], 1)

    def test_rotating_a_tilted_object_is_refused_even_with_the_gate(self):
        tilted = next(r for r in self.model.objects() if r.orientation_kind == "tilted")
        objs = self.objects()
        h.change(objs, tilted.slot, forward=(tilted.forward[1], -tilted.forward[0], tilted.forward[2]))
        result = self.export(objs, allow_unverified_rotation=True)
        self.assertEqual(h.codes(result.errors), ["E_TILT_UNSUPPORTED"])
        self.assertEqual(result.errors[0].message,
                         "Object '%d - %s' is tilted. Writing a tilted orientation is not supported; rotate it around Z only, or leave "
                         "its rotation unchanged." % (tilted.slot, tilted.type_name))

    def test_placement_flag_changes(self):
        objs = self.objects()
        record = self.model.objects()[3]
        h.change(objs, record.slot, symmetry=0 if record.symmetry else 3, place_at_start=not record.place_at_start,
                 game_specific=not record.game_specific)
        result = self.export(objs)
        self.assertEqual(h.codes(result.errors), ["E_FLAG_UNVERIFIED"] * 3)
        name = "%d - %s" % (record.slot, record.type_name)
        self.assertEqual([e.message for e in result.errors],
                         ["Object '%s': symmetry cannot be changed yet; how it is stored is unverified." % name,
                          "Object '%s': place at start cannot be changed yet; how it is stored is unverified." % name,
                          "Object '%s': game specific cannot be changed yet; how it is stored is unverified." % name])
        self.assertIsNone(result.data)

    def test_physics_is_the_one_placement_bit_that_may_change(self):
        record = next(r for r in self.model.objects() if r.physics == 0 and r.placement == 0x0C)
        objs = self.objects()
        h.change(objs, record.slot, physics=1)
        result = self.export(objs)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual(h.decode(result.data)["slots"][record.slot]["placement"], 0x4C)
        self.assertEqual(h.stream_diff(self.data, result.data), [h.slot_span(self.dec, record.slot, "placement")[0] + 1])

    def test_the_object_class_of_an_existing_object_cannot_change(self):
        objs = self.objects()
        h.change(objs, 0, cached_type=14)
        result = self.export(objs)
        self.assertEqual(h.codes(result.errors), ["E_CACHED_TYPE_CHANGED"])

    def test_every_refusal_reports_all_problems_together(self):
        extra = [self.new(name="A", type_name="Wibble"), self.new(name="B", position=(30000.0, 0.0, 0.0)),
                 self.new(name="C", type_name="Falcon, Nose Gun")]
        result = self.export(self.objects() + extra, allow_unverified_rotation=True, raise_quota_max=True)
        self.assertEqual(sorted(h.codes(result.errors)), ["E_FOLDER_RANGE", "E_OBJ_NAME_UNKNOWN", "E_OUT_OF_BOUNDS"])
        self.assertIsNone(result.data)


class TestHashFlavourOnTheRealFile(RealWriteCase):
    def move(self):
        objs = self.objects()
        pos = h.by_slot(objs, 50).position
        h.change(objs, 50, position=(pos[0] + 1.0, pos[1], pos[2]))
        return objs

    def test_reproduce_keeps_plain_le32_and_never_uses_the_salted_fallback(self):
        result = self.export(self.move())
        self.assertNotIn("W_HASH_UNKNOWN", h.codes(result.warnings))
        self.assertEqual(h.stored_hash(result.data), sha1_plain_le32(result.data))
        self.assertEqual(result.stats["hash_flavour"], "plain_le32/>")
        self.assertEqual(MapVariant.from_bytes(result.data).flavour, (">", "plain_le32"))

    def test_forcing_the_salted_recipe_changes_only_the_sha1(self):
        reproduced = self.export(self.move()).data
        salted = self.export(self.move(), hash_policy="SALTED_BE32").data
        self.assertEqual(h.stored_hash(salted), sha1_salted_be32(salted))
        self.assertEqual([i for i in range(len(salted)) if salted[i] != reproduced[i] and not h.HASH_AT <= i < h.HASH_AT + 20], [])
        self.assertNotEqual(h.stored_hash(salted), h.stored_hash(reproduced))
        self.assertEqual(MapVariant.from_bytes(salted).flavour, (">", "salted_be32"))

    def test_forcing_plain_le32_on_the_real_file_is_the_same_as_reproducing(self):
        self.assertEqual(self.export(self.move(), hash_policy="PLAIN_LE32").data, self.export(self.move()).data)

    def test_a_clean_export_with_a_forced_other_recipe_changes_only_the_sha1(self):
        result = self.export(self.objects(), hash_policy="SALTED_BE32")
        self.assertTrue(result.ok)
        self.assertEqual([i for i in range(len(self.data)) if result.data[i] != self.data[i] and not h.HASH_AT <= i < h.HASH_AT + 20], [])
        self.assertEqual(h.stored_hash(result.data), sha1_salted_be32(result.data))
        self.assertEqual(result.data[29481:], bytes(29911))

    def test_the_realistic_recipe_is_the_only_one_that_matches_the_original(self):
        stream = h.stream_bytes(self.data)
        length = 13311
        self.assertEqual(hashlib.sha1(struct.pack("<I", length) + stream[:length]).hexdigest(), "b41f6cb0fabe27fc9b22a607c0a9c9ca51c344e3")
        self.assertEqual(h.stored_hash(self.data).hex(), "b41f6cb0fabe27fc9b22a607c0a9c9ca51c344e3")


class TestOriginalsStayUntouched(RealWriteCase):
    def test_nothing_in_this_module_wrote_a_file_and_the_input_bytes_are_unchanged(self):
        self.assertEqual(hashlib.sha256(self.data).hexdigest(), REAL_SHA256)
        with open(h.g3.REAL_MVAR, "rb") as handle:
            self.assertEqual(hashlib.sha256(handle.read()).hexdigest(), REAL_SHA256)
        self.assertFalse(os.path.exists(h.g3.REAL_MVAR + ".new"))


if __name__ == "__main__":
    unittest.main()
