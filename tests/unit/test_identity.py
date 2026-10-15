"""U-12 (SPEC 9.3, tier T2; gate G5): slot identity, duplicates, not-imported slots, deletions, new-object order.

SPEC 5.5: an object claims a slot with an identity token (the slot's original bit range). A claim is valid when the slot is
present in the template and the token equals the template slot's bits; an invalid claimant is a NEW object (warning
``W_TOKEN_MISMATCH``). Several valid claimants of one slot: the one whose name matches the import wins, else the one closest
to the baseline pose, else the smallest name; the others are new (``W_DUPLICATE_SLOT``). A present slot that is in
``imported_slots`` (all of them when ``None``) and has no valid claimant is deleted; one that is NOT in ``imported_slots`` is
kept untouched (``W_SLOT_NOT_IMPORTED``). New objects are sorted by name and take the lowest absent slots.
"""
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import helpers_g5 as h  # noqa: E402

from mvarlib import api  # noqa: E402
from mvarlib.model import MapVariant  # noqa: E402

W1 = "w1_minimal"


def w1():
    return h.g3.data(W1)


def block_at(cells, name="B"):
    return h.new_object(name, position=h.cell_centre(h.g3.model(W1), cells))


def ok(testcase, result):
    testcase.assertTrue(result.ok, [e.message for e in result.errors])
    return result.data


def slots_of(data):
    return sorted(h.decode(data)["slots"])


class TestTokens(unittest.TestCase):
    def test_a_matching_token_keeps_the_slot_and_nothing_changes(self):
        result = h.export(w1(), h.objects_for(w1()))
        self.assertEqual(ok(self, result), w1())
        self.assertEqual([e.kind for e in result.diff], ["kept"] * 3)
        self.assertEqual([e.slot for e in result.diff], [1, 5, 650])
        self.assertEqual(h.codes(result.warnings), ["I_BUDGET", "I_PALETTE", "I_UNVERIFIED"])

    def test_a_token_from_another_slot_is_a_mismatch_and_the_object_becomes_new(self):
        objs = h.objects_for(w1())
        other = h.by_slot(objs, 5)
        obj = h.by_slot(objs, 1)
        obj.token_raw, obj.token_bits = other.token_raw, other.token_bits         # claims slot 1 with slot 5's bits
        result = h.export(w1(), objs, **h.GATE)
        data = ok(self, result)
        mismatch = [w for w in result.warnings if w.code == "W_TOKEN_MISMATCH"]
        self.assertEqual([(w.slot, w.object_name, w.message) for w in mismatch],
                         [(1, "1 - Block, 1x1", "Object '1 - Block, 1x1' claims slot 1 but does not match the imported file "
                                                "(copied from another file?); it was treated as a new object.")])
        kinds = sorted((e.kind, e.slot) for e in result.diff if e.kind != "kept")
        self.assertEqual(kinds, [("added", 0), ("removed", 1)], "slot 1 lost its claimant and a new object took slot 0")
        self.assertEqual(slots_of(data), [0, 5, 650])

    def test_a_token_with_the_wrong_bit_count_or_a_missing_token_is_a_mismatch(self):
        for fields in ({"token_bits": 140}, {"token_raw": None}, {"token_bits": None}, {"token_raw": b"\x00" * 18}):
            with self.subTest(fields):
                objs = h.objects_for(w1())
                h.change(objs, 1, **fields)
                result = h.export(w1(), objs, **h.GATE)
                self.assertIn("W_TOKEN_MISMATCH", h.codes(result.warnings))

    def test_a_claim_on_an_absent_or_impossible_slot_is_a_mismatch(self):
        for slot in (0, 2, 649, 651, -1, 100000):
            with self.subTest(slot):
                objs = h.objects_for(w1())
                objs.append(h.export_object(w1_model().objects()[0], name="Copied", slot=slot))
                result = h.export(w1(), objs, **h.GATE)
                self.assertTrue(result.ok, [e.message for e in result.errors])
                mismatch = [w for w in result.warnings if w.code == "W_TOKEN_MISMATCH"]
                self.assertEqual(len(mismatch), 1)
                self.assertEqual(mismatch[0].message, "Object 'Copied' claims slot %d but does not match the imported file "
                                                      "(copied from another file?); it was treated as a new object." % slot)

    def test_the_one_bit_token_of_an_absent_slot_is_no_valid_claim(self):
        """An absent slot's 'bit range' is the single bit 0: an object holding exactly that token still claims nothing."""
        objs = h.objects_for(w1())
        copy = h.export_object(w1_model().objects()[0], name="Claims an absent slot", slot=0, token_raw=b"\x00", token_bits=1)
        objs.append(copy)
        result = h.export(w1(), objs, **h.GATE)
        ok(self, result)
        self.assertEqual([w.slot for w in result.warnings if w.code == "W_TOKEN_MISMATCH"], [0])
        self.assertEqual([(e.kind, e.slot, e.name) for e in result.diff if e.kind == "added"], [("added", 0, "Claims an absent slot")])

    def test_an_object_that_claims_nothing_is_new_without_a_warning(self):
        result = h.export(w1(), h.objects_for(w1()) + [block_at((3, 3, 3))], **h.GATE)
        ok(self, result)
        self.assertNotIn("W_TOKEN_MISMATCH", h.codes(result.warnings))

    def test_a_token_from_a_different_file_does_not_match(self):
        """Objects imported from W1 handed to an export of the same map with another layout (E2's file): the tokens of slots whose
        bits differ no longer match."""
        other = h.g3.data("w1_E1")                                     # slot 1 moved: its bits differ
        result = h.export(other, h.objects_for(w1()), **h.GATE)
        self.assertEqual([w.slot for w in result.warnings if w.code == "W_TOKEN_MISMATCH"], [1])


def w1_model():
    return h.g3.model(W1)


class TestDuplicates(unittest.TestCase):
    def duplicate(self, **changes_for_copy):
        """W1 objects plus a Blender duplicate of slot 1 that inherited its slot and token."""
        objs = h.objects_for(w1())
        original = h.by_slot(objs, 1)
        copy = h.export_object(w1_model().objects()[0], name="1 - Block, 1x1.001", name_matches_import=False)
        for key, value in changes_for_copy.items():
            setattr(copy, key, value)
        self.assertEqual(copy.slot, original.slot)
        objs.append(copy)
        return objs

    def test_the_object_whose_name_matches_the_import_is_kept(self):
        objs = self.duplicate()
        result = h.export(w1(), objs, **h.GATE)
        data = ok(self, result)
        warning = [w for w in result.warnings if w.code == "W_DUPLICATE_SLOT"]
        self.assertEqual([(w.slot, w.object_name, w.message) for w in warning],
                         [(1, "1 - Block, 1x1.001", "Objects '1 - Block, 1x1' and '1 - Block, 1x1.001' both claim slot 1; "
                                                    "kept '1 - Block, 1x1' and treated '1 - Block, 1x1.001' as new.")])
        self.assertEqual(slots_of(data), [0, 1, 5, 650], "the duplicate became a new object in the lowest free slot")
        added = [e for e in result.diff if e.kind == "added"]
        self.assertEqual([(e.slot, e.name) for e in added], [(0, "1 - Block, 1x1.001")])

    def test_a_name_match_beats_a_closer_pose_and_a_smaller_name(self):
        objs = h.objects_for(w1())
        pos = h.by_slot(objs, 1).position
        h.change(objs, 1, position=(pos[0] + 10.0, pos[1], pos[2]))          # the imported name, but moved away
        copy = h.export_object(w1_model().objects()[0], name="0 copy at the baseline pose")
        copy.name_matches_import = False
        objs.append(copy)
        result = h.export(w1(), objs, **h.GATE)
        ok(self, result)
        self.assertEqual([w.message for w in result.warnings if w.code == "W_DUPLICATE_SLOT"],
                         ["Objects '1 - Block, 1x1' and '0 copy at the baseline pose' both claim slot 1; kept '1 - Block, 1x1' "
                          "and treated '0 copy at the baseline pose' as new."])
        self.assertEqual(h.decode(result.data)["slots"][1]["pos"][0], 524288 + 21845, "the kept object carries the move")

    def test_among_several_name_matches_a_non_matching_object_never_wins(self):
        objs = [o for o in h.objects_for(w1()) if o.slot != 1]
        rec = w1_model().objects()[0]
        far, farther, exact = (h.export_object(rec, name=n) for n in ("far", "farther", "exact"))
        far.position = (rec.position[0] + 5.0, rec.position[1], rec.position[2])
        farther.position = (rec.position[0] + 9.0, rec.position[1], rec.position[2])
        exact.name_matches_import = False                                    # at the baseline pose, but its name does not match
        objs += [far, farther, exact]
        result = h.export(w1(), objs, **h.GATE)
        ok(self, result)
        losers = sorted(w.object_name for w in result.warnings if w.code == "W_DUPLICATE_SLOT")
        self.assertEqual(losers, ["exact", "farther"])
        self.assertIn("kept 'far'", [w.message for w in result.warnings if w.object_name == "exact"][0])

    def test_the_diff_says_which_one_was_kept(self):
        result = h.export(w1(), self.duplicate(), **h.GATE)
        kept = [e for e in result.diff if e.kind == "kept" and e.slot == 1]
        self.assertEqual([e.name for e in kept], ["1 - Block, 1x1"])

    def test_without_a_name_match_the_closest_to_the_baseline_wins(self):
        objs = h.objects_for(w1())
        for o in objs:
            o.name_matches_import = False
        copy = h.export_object(w1_model().objects()[0], name="A copy")
        copy.name_matches_import = False
        pos = copy.position
        copy.position = (pos[0] + 10.0, pos[1], pos[2])                  # the copy was moved away
        objs.append(copy)
        result = h.export(w1(), objs, **h.GATE)
        ok(self, result)
        self.assertEqual([w.message for w in result.warnings if w.code == "W_DUPLICATE_SLOT"],
                         ["Objects '1 - Block, 1x1' and 'A copy' both claim slot 1; kept '1 - Block, 1x1' and treated 'A copy' as new."])
        # now the ORIGINAL moved away and the copy stayed
        objs = h.objects_for(w1())
        for o in objs:
            o.name_matches_import = False
        h.change(objs, 1, position=(pos[0] + 10.0, pos[1], pos[2]))
        copy = h.export_object(w1_model().objects()[0], name="A copy")
        copy.name_matches_import = False
        objs.append(copy)
        result = h.export(w1(), objs, **h.GATE)
        ok(self, result)
        self.assertEqual([w.message for w in result.warnings if w.code == "W_DUPLICATE_SLOT"],
                         ["Objects 'A copy' and '1 - Block, 1x1' both claim slot 1; kept 'A copy' and treated '1 - Block, 1x1' as new."])

    def test_orientation_decides_when_the_positions_are_equal(self):
        objs = h.objects_for(w1())
        for o in objs:
            o.name_matches_import = False
        turned = h.export_object(w1_model().objects()[0], name="0 turned", forward=(0.0, 1.0, 0.0))
        turned.name_matches_import = False
        objs.append(turned)
        result = h.export(w1(), objs, **h.GATE)
        ok(self, result)
        self.assertEqual([w.message for w in result.warnings if w.code == "W_DUPLICATE_SLOT"],
                         ["Objects '1 - Block, 1x1' and '0 turned' both claim slot 1; kept '1 - Block, 1x1' and treated '0 turned' as new."])

    def test_a_complete_tie_goes_to_the_smallest_name(self):
        objs = [o for o in h.objects_for(w1()) if o.slot != 1]
        rec = w1_model().objects()[0]
        for name in ("Zeta", "Alpha", "Mid"):
            obj = h.export_object(rec, name=name)
            obj.name_matches_import = False
            objs.append(obj)
        result = h.export(w1(), objs, **h.GATE)
        ok(self, result)
        messages = [w.message for w in result.warnings if w.code == "W_DUPLICATE_SLOT"]
        self.assertEqual(messages, ["Objects 'Alpha' and 'Mid' both claim slot 1; kept 'Alpha' and treated 'Mid' as new.",
                                    "Objects 'Alpha' and 'Zeta' both claim slot 1; kept 'Alpha' and treated 'Zeta' as new."])

    def test_several_name_matches_fall_back_to_the_pose_rule(self):
        objs = [o for o in h.objects_for(w1()) if o.slot != 1]
        rec = w1_model().objects()[0]
        near = h.export_object(rec, name="Zed near")
        far = h.export_object(rec, name="Aaa far")
        far.position = (rec.position[0] + 5.0, rec.position[1], rec.position[2])
        objs += [far, near]                                                # both say name_matches_import = True
        result = h.export(w1(), objs, **h.GATE)
        ok(self, result)
        self.assertEqual([w.message for w in result.warnings if w.code == "W_DUPLICATE_SLOT"],
                         ["Objects 'Zed near' and 'Aaa far' both claim slot 1; kept 'Zed near' and treated 'Aaa far' as new."])

    def test_an_invalid_duplicate_is_not_a_candidate(self):
        objs = self.duplicate(token_bits=1)
        result = h.export(w1(), objs, **h.GATE)
        ok(self, result)
        self.assertIn("W_TOKEN_MISMATCH", h.codes(result.warnings))
        self.assertNotIn("W_DUPLICATE_SLOT", h.codes(result.warnings))


class TestImportedSlots(unittest.TestCase):
    def test_a_slot_that_was_not_imported_is_kept_untouched(self):
        objs = h.without(h.objects_for(w1()), 5)                          # its Blender object does not exist: the import of slot 5 failed
        result = h.export(w1(), objs, imported_slots=[1, 650])
        data = ok(self, result)
        self.assertEqual(data, w1(), "nothing changed")
        self.assertEqual([(w.slot, w.message) for w in result.warnings if w.code == "W_SLOT_NOT_IMPORTED"],
                         [(5, "Slot 5 could not be imported earlier; it was left unchanged in the exported file.")])
        self.assertIn(("not_imported", 5), [(e.kind, e.slot) for e in result.diff])

    def test_a_slot_that_was_imported_and_has_no_object_is_deleted(self):
        objs = h.without(h.objects_for(w1()), 5)
        result = h.export(w1(), objs, imported_slots=[1, 5, 650])
        self.assertEqual(ok(self, result), h.g3.data("w1_E3"))
        self.assertNotIn("W_SLOT_NOT_IMPORTED", h.codes(result.warnings))

    def test_none_means_all_present_slots_were_imported(self):
        objs = h.without(h.objects_for(w1()), 1, 5, 650)
        result = h.export(w1(), objs, imported_slots=None)
        data = ok(self, result)
        self.assertEqual(slots_of(data), [])
        self.assertEqual(sorted((e.kind, e.slot) for e in result.diff), [("removed", 1), ("removed", 5), ("removed", 650)])

    def test_an_empty_list_means_nothing_was_imported(self):
        result = h.export(w1(), [], imported_slots=[])
        self.assertEqual(ok(self, result), w1())
        self.assertEqual(sorted(w.slot for w in result.warnings if w.code == "W_SLOT_NOT_IMPORTED"), [1, 5, 650])

    def test_slots_that_are_not_in_the_template_are_ignored_in_imported_slots(self):
        result = h.export(w1(), h.objects_for(w1()), imported_slots=[1, 2, 3, 5, 650, 700, -4])
        self.assertEqual(ok(self, result), w1())

    def test_a_valid_claimant_of_a_not_imported_slot_is_honoured(self):
        objs = h.objects_for(w1())
        pos = h.by_slot(objs, 5).position
        h.change(objs, 5, position=(pos[0] + 1.0, pos[1], pos[2]))
        result = h.export(w1(), objs, imported_slots=[1, 650])
        ok(self, result)
        self.assertEqual(h.decode(result.data)["slots"][5]["pos"][0], h.decode(w1())["slots"][5]["pos"][0] + 2185)    # 1.0 / cell, cell centre: as in G-POS-3
        self.assertNotIn("W_SLOT_NOT_IMPORTED", h.codes(result.warnings))

    def test_a_deleted_slot_in_a_file_with_a_not_imported_neighbour(self):
        objs = h.without(h.objects_for(w1()), 1, 5)                      # slot 1 was imported and removed; slot 5 never imported
        result = h.export(w1(), objs, imported_slots=[1, 650])
        data = ok(self, result)
        self.assertEqual(slots_of(data), [5, 650])
        self.assertEqual([w.slot for w in result.warnings if w.code == "W_SLOT_NOT_IMPORTED"], [5])


class TestNewObjectOrder(unittest.TestCase):
    def build(self, order, template=W1, count=4):
        names = ["N%02d" % i for i in range(count)]
        objs = h.objects_for(h.g3.data(template))
        pool = [block_at((i + 1, i + 2, i + 3), name) for i, name in enumerate(names)]
        for index in order:
            objs.append(pool[index])
        return objs

    def test_new_objects_are_sorted_by_name_and_take_the_lowest_free_slots(self):
        result = h.export(w1(), self.build([2, 0, 3, 1]), **h.GATE)
        data = ok(self, result)
        dec = h.decode(data)
        self.assertEqual(sorted(dec["slots"]), [0, 1, 2, 3, 4, 5, 650])
        for i, slot in enumerate((0, 2, 3, 4)):
            self.assertEqual(dec["slots"][slot]["pos"], [i + 1, i + 2, i + 3], "N%02d is in slot %d" % (i, slot))
        self.assertEqual([(e.slot, e.name) for e in result.diff if e.kind == "added"],
                         [(0, "N00"), (2, "N01"), (3, "N02"), (4, "N03")], "slot 1 is taken, so the second goes to slot 2")

    def test_the_output_does_not_depend_on_the_order_of_the_list(self):
        reference = h.export(w1(), self.build([0, 1, 2, 3]), **h.GATE).data
        rng = random.Random(5)
        for _ in range(6):
            order = [0, 1, 2, 3]
            rng.shuffle(order)
            self.assertEqual(h.export(w1(), self.build(order), **h.GATE).data, reference)
        shuffled = self.build([0, 1, 2, 3])
        rng.shuffle(shuffled)                                                # claimants shuffled among the new ones too
        self.assertEqual(h.export(w1(), shuffled, **h.GATE).data, reference)

    def test_the_same_request_twice_gives_the_same_bytes(self):
        a = h.export(w1(), self.build([0, 1, 2, 3]), **h.GATE).data
        b = h.export(w1(), self.build([0, 1, 2, 3]), **h.GATE).data
        self.assertEqual(a, b)

    def test_slots_vacated_by_a_deletion_are_free_for_new_objects(self):
        objs = h.without(h.objects_for(w1()), 1)
        objs.append(block_at((9, 9, 9), "A"))
        objs.append(block_at((8, 8, 8), "B"))
        result = h.export(w1(), objs, **h.GATE)
        data = ok(self, result)
        self.assertEqual(slots_of(data), [0, 1, 5, 650], "A took slot 0, B took the vacated slot 1")
        self.assertEqual(h.decode(data)["slots"][0]["pos"], [9, 9, 9])
        self.assertEqual(h.decode(data)["slots"][1]["pos"], [8, 8, 8])

    def test_names_sort_as_text(self):
        objs = h.objects_for(w1())
        objs.append(block_at((1, 1, 1), "b"))
        objs.append(block_at((2, 2, 2), "B"))
        objs.append(block_at((3, 3, 3), "a10"))
        objs.append(block_at((4, 4, 4), "a2"))
        result = h.export(w1(), objs, **h.GATE)
        order = [(e.slot, e.name) for e in result.diff if e.kind == "added"]
        self.assertEqual(order, [(0, "B"), (2, "a10"), (3, "a2"), (4, "b")])

    def test_a_new_object_that_failed_a_check_takes_no_slot(self):
        objs = h.objects_for(w1())
        objs.append(block_at((1, 1, 1), "A bad"))
        h.change(objs, 1, position=(float("nan"), 0.0, 0.0))
        objs.append(h.new_object("B bad", position=(9999.0, 0.0, 0.0)))
        objs.append(block_at((2, 2, 2), "C good"))
        result = h.export(w1(), objs, **h.GATE)
        self.assertFalse(result.ok)
        self.assertIsNone(result.data)


if __name__ == "__main__":
    unittest.main()
