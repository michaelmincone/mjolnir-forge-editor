"""U-11 / U-13 companion (gate G5): the rules inside the export that the golden edits do not reach.

Quota rule boundaries and the opt-in ``raise_quota_max`` (decision D11), what a new object learns from the template (class,
placement byte, team, colour), the new-object field rules, retargets, parent clearing, the tolerances of 4.8 / 4.9, the
tail-bit capacity rule, the diff text, and fault injection into the writer that proves the re-parse verification (SPEC 5.10
step 12) really stops a wrong file. Everything is built in memory with the independent fixture builder.
"""
import copy
import math
import os
import random
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import helpers_g5 as h  # noqa: E402

from mvarlib import api, codecs, edit, errors, tables  # noqa: E402
from mvarlib.model import MapVariant  # noqa: E402

W1 = "w1_minimal"


def variant(edit_fn, name=W1):
    build, _ = h.build_modules()
    spec = copy.deepcopy(build.load_spec(name))
    edit_fn(spec)
    return build.build(spec).data


def w1():
    return h.g3.data(W1)


def with_rows(rows, name=W1):
    def fn(spec):
        for key, value in rows.items():
            spec["quotas"]["rows"][str(key)] = list(value)
    return variant(fn, name)


def block(source, name="N", **fields):
    fields.setdefault("position", (1.0, 1.0, 1.0))
    return h.new_like_example(source, "Block, 1x1", name, **fields)


def export_new(data, *new, **options):
    return h.export(data, h.objects_for(data) + list(new), **options)


GATE = h.GATE


class TestQuotaBoundaries(unittest.TestCase):
    def test_a_row_above_its_maximum_may_shrink_but_never_grow(self):
        data = with_rows({70: (0, 1, 3)})                                  # placed 3 above the maximum 1 (slots 1 and 650 + one not in the file)
        model = MapVariant.from_bytes(data)
        self.assertEqual(model.quotas[70].as_tuple(), (0, 1, 3))
        self.assertTrue(h.export(data, h.objects_for(data)).ok, "a pre-existing violation is not an error")
        shrink = h.export(data, h.without(h.objects_for(data), 1))
        self.assertTrue(shrink.ok, [e.message for e in shrink.errors])
        self.assertEqual(h.decode(shrink.data)["quotas"][70], [0, 1, 2], "3 -> 2 is still above 1 but not worse")
        grow = export_new(data, block(data), **GATE)
        self.assertEqual([e.message for e in grow.errors],
                         ["Palette entry 70 (Block, 1x1) would have 4 placed; the maximum on this map variant is 1."])

    def test_a_row_below_its_minimum_may_grow_but_never_shrink(self):
        data = with_rows({70: (5, 16, 2)})
        self.assertTrue(h.export(data, h.objects_for(data)).ok)
        grow = export_new(data, block(data), **GATE)
        self.assertTrue(grow.ok, [e.message for e in grow.errors])
        self.assertEqual(h.decode(grow.data)["quotas"][70], [5, 16, 3], "2 -> 3 is still below 5 but not worse")
        shrink = h.export(data, h.without(h.objects_for(data), 1))
        self.assertEqual([e.message for e in shrink.errors],
                         ["Palette entry 70 (Block, 1x1) would drop to 1 placed; the minimum on this map variant is 5."])

    def test_the_maximum_and_the_minimum_are_inclusive(self):
        data = with_rows({70: (2, 3, 2)})
        self.assertTrue(export_new(data, block(data), **GATE).ok, "placed == maximum is allowed")
        two = export_new(data, block(data, "A"), block(data, "B", position=(2.0, 2.0, 2.0)), **GATE)
        self.assertEqual(h.codes(two.errors), ["E_QUOTA"])
        down = h.export(data, h.without(h.objects_for(data), 650))
        self.assertEqual(h.codes(down.errors), ["E_QUOTA_MIN"], "2 -> 1 is below the minimum 2")
        data = with_rows({70: (1, 3, 2)})
        self.assertTrue(h.export(data, h.without(h.objects_for(data), 650)).ok, "placed == minimum is allowed")

    def test_255_is_the_ceiling_of_a_row(self):
        data = with_rows({70: (0, 255, 254)})
        self.assertTrue(export_new(data, block(data), **GATE).ok)
        over = export_new(data, block(data, "A"), block(data, "B", position=(2.0, 2.0, 2.0)), **GATE)
        self.assertEqual([e.message for e in over.errors], ["Palette entry 70 (Block, 1x1) cannot hold more than 255 objects."])
        data = with_rows({70: (0, 255, 255)})
        self.assertEqual(h.codes(export_new(data, block(data), **GATE, raise_quota_max=True).errors), ["E_QUOTA_RANGE"],
                         "the option never goes past 255")

    def test_deleting_an_object_whose_row_is_zero_is_an_error_not_a_wraparound(self):
        data = with_rows({70: (0, 16, 0)})                                   # the row says 0 although two blocks exist
        result = h.export(data, h.without(h.objects_for(data), 1))
        self.assertEqual([e.message for e in result.errors],
                         ["Palette entry 70 (Block, 1x1) would drop to -1 placed; the minimum on this map variant is 0."])


class TestRaiseQuotaMax(unittest.TestCase):
    def kill(self, data, name="Second"):
        return h.new_like_example(data, "Kill Boundary", name, position=(1.0, 1.0, 1.0))

    def test_off_by_default_the_export_is_refused(self):
        result = export_new(w1(), self.kill(w1()), **GATE)
        self.assertEqual(h.codes(result.errors), ["E_QUOTA"])
        self.assertIsNone(result.data)
        self.assertFalse(api.ExportOptions().raise_quota_max)

    def test_on_the_maximum_is_raised_to_the_new_placed_and_nothing_else_changes(self):
        result = export_new(w1(), self.kill(w1()), **GATE, raise_quota_max=True)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        rows = h.decode(result.data)["quotas"]
        before = h.decode(w1())["quotas"]
        self.assertEqual((before[61], rows[61]), ([0, 1, 1], [0, 2, 2]))
        self.assertEqual([i for i in range(80) if rows[i] != before[i]], [61])
        raised = [w for w in result.warnings if w.code == "W_QUOTA_MAX_RAISED"]
        self.assertEqual([w.message for w in raised],
                         ["Quota maximum raised: unverified. Palette entry 61 (Kill Boundary) now has 2 placed; its maximum was raised "
                          "from 1 to 2. Whether the game honours the file's maximum or rebuilds it from the scenario is unknown."])
        self.assertEqual(raised[0].severity, "warning")
        self.assertEqual(result.stats["quota_changes"],
                         [{"folder": 61, "name": "Kill Boundary", "minimum": 0, "placed_before": 1, "placed_after": 2,
                           "maximum_before": 1, "maximum_after": 2}])

    def test_every_raised_row_gets_its_own_warning_in_folder_order(self):
        data = with_rows({70: (0, 2, 2)})
        result = export_new(data, block(data, "A"), self.kill(data, "B"), **GATE, raise_quota_max=True)
        self.assertTrue(result.ok)
        raised = [w.message for w in result.warnings if w.code == "W_QUOTA_MAX_RAISED"]
        self.assertEqual(len(raised), 2)
        self.assertIn("Palette entry 61 (Kill Boundary) now has 2 placed; its maximum was raised from 1 to 2", raised[0])
        self.assertIn("Palette entry 70 (Block, 1x1) now has 3 placed; its maximum was raised from 2 to 3", raised[1])
        self.assertEqual([q["folder"] for q in result.stats["quota_changes"]], [61, 70])

    def test_a_row_with_room_is_left_alone_and_there_is_no_warning(self):
        on = export_new(w1(), block(w1()), **GATE, raise_quota_max=True)
        off = export_new(w1(), block(w1()), **GATE)
        self.assertEqual(on.data, off.data)
        self.assertNotIn("W_QUOTA_MAX_RAISED", h.codes(on.warnings))
        self.assertEqual(h.decode(on.data)["quotas"][70], [0, 16, 3], "16 is not lowered to 3")

    def test_a_deletion_never_raises_or_lowers_anything(self):
        result = h.export(w1(), h.without(h.objects_for(w1()), 5), raise_quota_max=True)
        self.assertEqual(result.data, h.g3.data("w1_E3"))
        self.assertEqual(h.decode(result.data)["quotas"][61], [0, 1, 0])
        self.assertNotIn("W_QUOTA_MAX_RAISED", h.codes(result.warnings))

    def test_a_row_that_already_exceeded_its_maximum_is_raised_to_the_new_count(self):
        data = with_rows({70: (0, 1, 3)})
        result = export_new(data, block(data), **GATE, raise_quota_max=True)
        self.assertEqual(h.decode(result.data)["quotas"][70], [0, 4, 4])

    def test_the_minimum_rule_still_applies(self):
        data = with_rows({70: (5, 16, 2)})
        result = h.export(data, h.without(h.objects_for(data), 1), raise_quota_max=True)
        self.assertEqual(h.codes(result.errors), ["E_QUOTA_MIN"])

    def test_a_retarget_into_a_full_row_raises_it_too(self):
        objs = h.objects_for(w1())
        h.change(objs, 650, type_name="Bridge, Small")
        refused = h.export(w1(), objs)
        self.assertEqual(h.codes(refused.errors), ["E_QUOTA"])
        raised = h.export(w1(), objs, raise_quota_max=True)
        self.assertTrue(raised.ok)
        rows = h.decode(raised.data)["quotas"]
        self.assertEqual((rows[70], rows[71]), ([0, 16, 1], [0, 1, 1]))

    def test_the_stub_and_the_real_provider_take_the_same_option(self):
        self.assertEqual(api.ExportOptions(raise_quota_max=True).raise_quota_max, True)


class TestLearning(unittest.TestCase):
    def model(self, data):
        return MapVariant.from_bytes(data)

    def test_the_class_is_the_unique_one_of_the_same_type_else_of_the_same_folder(self):
        m = h.g3.model(W1)
        self.assertEqual(edit.learn_class(m, 70, 0), 0)
        self.assertEqual(edit.learn_class(m, 70, 1), 0, "no (70, 1) in the file: the folder decides")
        self.assertEqual(edit.learn_class(m, 61, 0), 26)
        self.assertEqual(edit.learn_class(m, 61, 9), 26)
        self.assertIsNone(edit.learn_class(m, 0, 0), "folder 0 has no object")

    def test_an_ambiguous_folder_has_no_class_but_an_exact_type_still_does(self):
        def fn(spec):
            spec["slots"][2]["cached_type"] = 5                           # slot 650: a second class in folder 70
            spec["slots"].append({"index": 3, "folder": 70, "item": 1, "pos": [1, 1, 1], "cached_type": 5})
        m = self.model(variant(fn))
        self.assertEqual(edit.learn_class(m, 70, 0), None, "classes 0 and 5 on the exact type and in the folder")
        self.assertEqual(edit.learn_class(m, 70, 1), 5, "exactly one class for (70, 1)")
        self.assertIsNone(edit.learn_class(m, 70, 2), "folder 70 is ambiguous")

    def test_an_ambiguous_class_is_not_learned_by_the_export(self):
        def fn(spec):
            spec["slots"].insert(0, {"index": 0, "folder": 0, "item": 0, "pos": [1, 1, 1], "cached_type": 1, "extra": [3]})
            spec["slots"].insert(1, {"index": 2, "folder": 0, "item": 0, "pos": [2, 2, 2], "cached_type": 2})
            spec["quotas"]["rows"]["0"] = [0, 9, 2]
        data = variant(fn)
        rifle = h.new_object("N", type_name="Assault Rifle", position=(1.0, 1.0, 1.0))
        result = export_new(data, rifle, **GATE, keep_unrecognised_imported=True)
        self.assertEqual(h.codes(result.errors), ["E_CACHED_TYPE_UNKNOWN"])

    def test_the_example_is_the_most_common_one_and_the_lowest_slot_breaks_a_tie(self):
        m = h.g3.model(W1)
        self.assertEqual(edit.learn_example(m, 70, 0), ((0xCC, 9, None), 1), "two different examples, one each: the lowest slot")
        self.assertEqual(edit.learn_example(m, 70, 5), ((0xCC, 9, None), 1), "the folder decides when the type has none")
        self.assertIsNone(edit.learn_example(m, 5, 0))

        def fn(spec):
            spec["slots"].insert(0, {"index": 2, "folder": 70, "item": 0, "pos": [1, 1, 1], "placement": 0x0C})
            spec["slots"].insert(1, {"index": 3, "folder": 70, "item": 0, "pos": [2, 2, 2], "placement": 0x0C})
            spec["quotas"]["rows"]["70"] = [0, 16, 4]
        data = variant(fn)
        m = self.model(data)
        self.assertEqual(edit.learn_example(m, 70, 0), ((0x0C, 9, None), 2), "two of the four say 0x0C: the majority wins")
        result = export_new(data, h.new_object("N", position=(1.0, 1.0, 1.0), physics=0), **GATE)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual(h.decode(result.data)["slots"][0]["placement"], 0x0C, "physics 0 equals the example: its byte is kept")
        result = export_new(data, h.new_object("N", position=(1.0, 1.0, 1.0), physics=3), **GATE)
        self.assertEqual(h.decode(result.data)["slots"][0]["placement"], 0xCC)

    def test_team_and_colour_come_from_the_example_unless_the_property_differs(self):
        def fn(spec):
            spec["slots"][0].update({"team_raw": 3, "color": 4})
            spec["slots"][2].update({"team_raw": 3, "color": 4})
        data = variant(fn)
        same = h.new_like_example(data, "Block, 1x1", "N", position=(1.0, 1.0, 1.0))
        self.assertEqual((same.team, same.color), (2, 4))
        slot = h.decode(export_new(data, same, **GATE).data)["slots"][0]
        self.assertEqual((slot["team_raw"], slot["color"]), (3, 4))
        other = h.new_like_example(data, "Block, 1x1", "N", position=(1.0, 1.0, 1.0), team=5, color=-1)
        slot = h.decode(export_new(data, other, **GATE).data)["slots"][0]
        self.assertEqual((slot["team_raw"], slot["color"]), (6, None))

    def test_without_an_example_the_defaults_are_0x0C_neutral_and_team_colour(self):
        result = export_new(w1(), h.new_object("N", type_name="Bridge, Small", position=(1.0, 1.0, 1.0), physics=0), **GATE,
                            raise_quota_max=True)
        slot = h.decode(result.data)["slots"][0]
        self.assertEqual((slot["placement"], slot["team_raw"], slot["color"], slot["flags2"], slot["cached_type"]), (0x0C, 9, None, 1, 0))
        self.assertEqual(h.codes([w for w in result.warnings if w.code == "W_CACHED_TYPE_ASSUMED"]), ["W_CACHED_TYPE_ASSUMED"])
        defaults = export_new(w1(), h.new_object("N", type_name="Bridge, Small", position=(1.0, 1.0, 1.0)), **GATE, raise_quota_max=True)
        self.assertEqual(h.decode(defaults.data)["slots"][0]["placement"], 0xCC, "the property default (phased) replaces the physics bits")
        for physics, byte in ((0, 0x0C), (1, 0x4C), (3, 0xCC)):
            r = export_new(w1(), h.new_object("N", type_name="Bridge, Small", position=(1.0, 1.0, 1.0), physics=physics), **GATE, raise_quota_max=True)
            self.assertEqual(h.decode(r.data)["slots"][0]["placement"], byte)

    def test_the_assumed_group_rule_needs_every_palette_path_to_be_an_assumed_group(self):
        ex = edit._Export(b"", [], api.ExportOptions())
        trees = {"groups": [{"name": "Structure", "groups": [{"name": "Blocks", "leaves": ["Both", "OnlyStructure"]}]},
                            {"name": "Scenery", "leaves": ["Both", {"name": "Prop"}]},
                            {"name": "Hidden", "leaves": ["Both", "Secret"]}]}
        with mock.patch.object(tables, "palette_tree", return_value=trees):
            self.assertTrue(ex._assumed_group("OnlyStructure"))
            self.assertTrue(ex._assumed_group("Prop"), "a leaf given as a dict with a name")
            self.assertFalse(ex._assumed_group("Secret"))
            self.assertFalse(ex._assumed_group("Both"), "one of its three paths (Hidden) is not an assumed group")
            self.assertFalse(ex._assumed_group("Unlisted"))

    def test_every_assumed_group_of_the_real_tree_is_assumed(self):
        ex = edit._Export(b"", [], api.ExportOptions())
        self.assertTrue(ex._assumed_group("Block, 1x1"))
        self.assertTrue(ex._assumed_group("Wall"))
        self.assertFalse(ex._assumed_group("Assault Rifle"))
        self.assertFalse(ex._assumed_group("Block, 1x1, Invisible"), "the Hidden group is not assumed")


class TestNewObjectFields(unittest.TestCase):
    def decode_new(self, **fields):
        result = export_new(w1(), block(w1(), **fields), **GATE)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        return h.decode(result.data)["slots"][0], result

    def test_plain_fields_are_written(self):
        slot, _ = self.decode_new(spawn_sequence=-3, spawn_time=9, label_index=1, team=2, color=5)
        self.assertEqual((slot["spawn_seq"], slot["respawn"], slot["label"], slot["team_raw"], slot["color"]), (-3, 9, 1, 3, 5))
        self.assertEqual((slot["folder"], slot["item"], slot["flags2"], slot["in_bounds"], slot["parent_raw"]), (70, 0, 1, 1, 0))

    def test_shape_and_dimensions_are_written(self):
        slot, _ = self.decode_new(shape=3, width=1.0, length=2.0, top=3.0, bottom=4.0)
        self.assertEqual((slot["shape"], slot["dims"]), (3, [codecs.dim_encode(v) for v in (1.0, 2.0, 3.0, 4.0)]))
        slot, _ = self.decode_new(shape=2, width=5.0, length=99.0, top=6.0, bottom=7.0)
        self.assertEqual((slot["shape"], slot["dims"]), (2, [codecs.dim_encode(v) for v in (5.0, 6.0, 7.0)]))

    def test_the_position_is_the_containing_cell_on_every_axis(self):
        slot, _ = self.decode_new(position=(10.0, -20.5, 3.25))
        b = (-240.0, 240.0, -345.0, 345.0, -70.0, 70.0)
        axes = (20, 21, 19)
        for k, v in enumerate((10.0, -20.5, 3.25)):
            cell = (b[2 * k + 1] - b[2 * k]) / float(1 << axes[k])
            self.assertEqual(slot["pos"][k], int(math.floor((v - b[2 * k]) / cell)))

    def test_yaw_of_a_new_object(self):
        for forward, raw in (((1.0, 0.0, 0.0), 8192), ((0.0, 1.0, 0.0), 12288), ((0.0, -1.0, 0.0), 4096), ((-1.0, 0.0, 0.0), 16383),
                             ((2.0, 0.0, 0.0), 8192), ((0.7, 0.7, 0.0), 10240)):
            with self.subTest(forward):
                slot, _ = self.decode_new(forward=forward)
                self.assertEqual((slot["up_global"], slot["up_code"], slot["angle"]), (1, None, raw))

    def test_flags_that_differ_from_the_baseline_are_refused_for_a_new_object(self):
        for fields, word in ((dict(symmetry=2), "symmetry"), (dict(symmetry=0), "symmetry"), (dict(place_at_start=False), "place at start"),
                             (dict(game_specific=True), "game specific")):
            with self.subTest(fields):
                result = export_new(w1(), block(w1(), **fields), **GATE)
                self.assertEqual([e.message for e in result.errors],
                                 ["Object 'N': %s cannot be changed yet; how it is stored is unverified." % word])
                self.assertEqual(h.codes(export_new(w1(), h.new_object("N", type_name="Bridge, Small", position=(1.0, 1.0, 1.0), **fields),
                                                    **GATE, raise_quota_max=True).errors), ["E_FLAG_UNVERIFIED"], "also without an example")

    def test_a_flag_equal_to_the_learned_example_is_not_a_change(self):
        def fn(spec):
            spec["slots"][0]["placement"] = 0x04 | 0x20 | 0x00               # asymmetric-only (reading HMS) and game specific, placed at start
            spec["slots"][2]["placement"] = 0x04 | 0x20
        data = variant(fn)
        like = h.new_like_example(data, "Block, 1x1", "N", position=(1.0, 1.0, 1.0))
        self.assertEqual((like.symmetry, like.game_specific, like.place_at_start), (1, True, True))
        result = export_new(data, like, **GATE)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual(h.decode(result.data)["slots"][0]["placement"], 0x24)
        default = export_new(data, h.new_object("M", position=(1.0, 1.0, 1.0)), **GATE)
        self.assertEqual([e.message for e in default.errors],
                         ["Object 'M': symmetry cannot be changed yet; how it is stored is unverified.",
                          "Object 'M': game specific cannot be changed yet; how it is stored is unverified."],
                         "the property defaults (both symmetries, not game specific) are not the example's")

    def test_a_type_given_only_by_its_id_is_a_stock_object_too(self):
        obj = h.new_object("N", type_name="", type_id_hint=0x4600, position=(1.0, 1.0, 1.0))
        result = export_new(w1(), obj, **GATE)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual((h.decode(result.data)["slots"][0]["folder"], h.decode(result.data)["slots"][0]["item"]), (70, 0))

    def test_a_type_id_of_zero_is_a_type(self):
        """Id 0x0000 is the Assault Rifle: a hint of 0 is not 'no type' (its class is unknown in W1, which is the error reported)."""
        obj = h.new_object("N", type_name="", type_id_hint=0, position=(1.0, 1.0, 1.0))
        result = export_new(w1(), obj, **GATE, raise_quota_max=True)
        self.assertEqual(h.codes(result.errors), ["E_CACHED_TYPE_UNKNOWN"])
        self.assertEqual(result.errors[0].message.split("'")[1], "Assault Rifle")

    def test_a_folder_equal_to_the_quota_count_does_not_exist(self):
        self.assertEqual(h.g3.model(W1).fixed.quota_count, 80)
        self.assertIn("Block, 2x2x2, Invisible", tables.stock_object_names("Forge World"))          # id 0x5000: folder 80
        result = export_new(w1(), h.new_object("N", type_name="Block, 2x2x2, Invisible", position=(1.0, 1.0, 1.0)), **GATE)
        self.assertEqual([e.message for e in result.errors], ["Object 'N' needs palette entry 80, but this map variant defines only 80 entries."])
        objs = h.objects_for(w1())
        h.change(objs, 1, type_name="Block, 2x2x2, Invisible")
        self.assertEqual([e.message for e in h.export(w1(), objs).errors],
                         ["Object '1 - Block, 1x1' needs palette entry 80, but this map variant defines only 80 entries."])

    def test_an_unknown_class_is_reported_once_per_type(self):
        rifles = [h.new_object("Rifle %d" % i, type_name="Assault Rifle", position=(float(i), 1.0, 1.0)) for i in range(3)]
        result = export_new(w1(), *rifles, **GATE, raise_quota_max=True)
        self.assertEqual(h.codes(result.errors), ["E_CACHED_TYPE_UNKNOWN"], "one error for the type, not three")
        mixed = rifles[:2] + [h.new_object("Dmr", type_name="DMR", position=(1.0, 2.0, 3.0))]
        result = export_new(w1(), *mixed, **GATE, raise_quota_max=True)
        self.assertEqual(sorted(e.message.split("'")[1] for e in result.errors), ["Assault Rifle", "DMR"])

    def test_the_default_team_is_neutral_not_none(self):
        slot = h.decode(export_new(w1(), h.new_object("N", type_name="Bridge, Small", position=(1.0, 1.0, 1.0)), **GATE, raise_quota_max=True).data)["slots"][0]
        self.assertEqual(slot["team_raw"], 9)

    def test_the_extras_of_a_weapon_use_other_a(self):
        data = h.g3.data("holes")
        rifle = h.new_like_example(data, "Assault Rifle", "N", position=(1.0, 1.0, 1.0), other_a=7)
        result = export_new(data, rifle, **GATE, keep_unrecognised_imported=True, raise_quota_max=True)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        new = [s for i, s in h.decode(result.data)["slots"].items() if i not in h.decode(data)["slots"]]
        self.assertEqual([(s["folder"], s["cached_type"], s["extra"]) for s in new], [(0, 1, [7])])

    def test_the_type_name_is_resolved_on_this_map_only(self):
        elsewhere = sorted(set(tables.stock_object_names("Tempest")) - set(tables.stock_object_names("Forge World")))
        self.assertTrue(elsewhere)
        name = elsewhere[0]
        result = export_new(w1(), h.new_object("N", type_name=name, position=(1.0, 1.0, 1.0)), **GATE)
        self.assertEqual([e.message for e in result.errors], ["Object 'N' uses '%s', which is not a stock object on Forge World." % name])


class TestRetargetRules(unittest.TestCase):
    def test_a_type_given_only_by_id_retargets_an_existing_object(self):
        objs = h.objects_for(w1())
        h.change(objs, 1, type_name="", type_id_hint=0x4601)               # Block, 1x1, Flat
        result = h.export(w1(), objs)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        slot = h.decode(result.data)["slots"][1]
        self.assertEqual((slot["folder"], slot["item"]), (70, 1))
        self.assertEqual([(e.kind, e.detail) for e in result.diff if e.kind != "kept"], [("retargeted", "Block, 1x1 -> Block, 1x1, Flat")])

    def test_a_retarget_by_id_to_a_non_stock_id_is_refused(self):
        objs = h.objects_for(w1())
        h.change(objs, 1, type_name="", type_id_hint=0x0101)
        self.assertEqual([e.message for e in h.export(w1(), objs).errors],
                         ["Object '1 - Block, 1x1' (id 0x0101) is not a stock object on Forge World."])

    def test_an_existing_object_with_a_name_the_map_does_not_know_is_refused(self):
        objs = h.objects_for(w1())
        h.change(objs, 1, type_name="Wibble")
        self.assertEqual([e.message for e in h.export(w1(), objs).errors],
                         ["Object '1 - Block, 1x1' uses 'Wibble', which is not a stock object on Forge World."])

    def test_an_existing_object_with_no_type_information_is_refused(self):
        objs = h.objects_for(w1())
        h.change(objs, 1, type_name="", type_id_hint=-1)
        self.assertEqual(h.codes(h.export(w1(), objs).errors), ["E_OBJ_NO_TYPE"])

    def test_an_imported_object_whose_type_name_is_the_unknown_placeholder_is_kept(self):
        """Tier 1 (SPEC 7.4): a name equal to the template's own "Unknown (0x....)" string keeps the bits."""
        data = h.g3.data("holes")
        model = h.g3.model("holes")
        slot = next(r for r in model.objects() if not r.stock and r.type_id >= 0)
        self.assertTrue(slot.type_name.startswith("Unknown (0x"))
        objs = h.objects_for(model)
        h.change(objs, slot.slot, type_name=slot.type_name)
        result = h.export(data, objs, keep_unrecognised_imported=True)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual(result.data, data)
        self.assertEqual(h.codes(h.export(data, objs).errors).count("E_OBJ_NOT_STOCK"), sum(1 for r in model.objects() if not r.stock and r.type_id >= 0))

    def test_a_retarget_to_a_type_with_no_known_class_is_refused(self):
        objs = h.objects_for(w1())
        h.change(objs, 1, type_name="Assault Rifle")                      # folder 0 has no object in W1 and weapons are not an assumed group
        result = h.export(w1(), objs)
        self.assertEqual([e.message for e in result.errors],
                         ["Object '1 - Block, 1x1' cannot change from 'Block, 1x1' to 'Assault Rifle': they are different object classes."])

    def test_a_retarget_to_a_folder_the_file_does_not_define_is_refused(self):
        objs = h.objects_for(w1())
        h.change(objs, 1, type_name="Location Name")
        self.assertEqual([e.message for e in h.export(w1(), objs).errors],
                         ["Object '1 - Block, 1x1' needs palette entry 144, but this map variant defines only 80 entries."])

    def test_a_retarget_with_an_assumed_class_warns(self):
        objs = h.objects_for(w1())
        h.change(objs, 650, type_name="Bridge, Small")
        result = h.export(w1(), objs, raise_quota_max=True)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual([w.slot for w in result.warnings if w.code == "W_CACHED_TYPE_ASSUMED"], [650])

    def test_a_retarget_to_a_disputed_id_warns(self):
        def fn(spec):
            spec["header"]["map_id"] = 2004
            spec["body"]["map_id_2"] = 2004
            spec["slots"][0].update({"folder": 40, "item": 0})
            spec["slots"][1].update({"folder": 58, "item": 0})
            spec["slots"][2].update({"folder": 67, "item": 0})
            spec["quotas"]["rows"] = {"58": [0, 1, 1], "40": [0, 5, 1], "67": [0, 16, 1]}
        data = variant(fn)
        objs = h.objects_for(data)
        self.assertEqual(h.by_slot(objs, 1).type_name, "Cannon, Man")
        h.change(objs, 1, type_name="Cannon, Man, Heavy")
        result = h.export(data, objs)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual([w.message for w in result.warnings if w.code == "W_DISPUTED_ID"],
                         ["The id of 'Cannon, Man, Heavy' differs between the two source tables on Tempest; check it in the game."])
        objs = h.objects_for(data)
        self.assertEqual(h.export(data, objs).data, data)
        h.change(objs, 1, type_name="Wall, Coliseum")
        self.assertNotIn("W_DISPUTED_ID", h.codes(h.export(data, objs, raise_quota_max=True).warnings))


class TestParentClearing(unittest.TestCase):
    def test_a_child_of_slot_0_loses_the_link_when_slot_0_goes(self):
        def fn(spec):
            spec["slots"].insert(0, {"index": 0, "folder": 70, "item": 0, "pos": [1, 1, 1]})
            spec["slots"][3]["parent_raw"] = 1                              # slot 650 now has slot 0 as its parent
            spec["quotas"]["rows"]["70"] = [0, 16, 3]
        data = variant(fn)
        self.assertEqual(h.g3.model("w1_minimal").slots[650].parent_raw, 2)
        self.assertEqual(MapVariant.from_bytes(data).slots[650].parent_raw, 1)
        result = h.export(data, h.without(h.objects_for(data), 0))
        self.assertEqual(h.decode(result.data)["slots"][650]["parent_raw"], 0)
        self.assertEqual([(w.slot, w.message) for w in result.warnings if w.code == "W_PARENT_CLEARED"],
                         [(650, 'Slot 650 lost its "spawn relative to" parent because slot 0 was deleted.')])

    def test_a_child_of_slot_650_loses_the_link_at_the_other_end_of_the_range(self):
        data = h.g3.data("holes")
        self.assertEqual(h.g3.model("holes").slots[649].parent_raw, 651)
        objs = h.without(h.objects_for(data), 650)
        result = h.export(data, objs, keep_unrecognised_imported=True)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual(h.decode(result.data)["slots"][649]["parent_raw"], 0)
        self.assertEqual([w.slot for w in result.warnings if w.code == "W_PARENT_CLEARED"], [649])

    def test_other_links_are_untouched(self):
        data = h.g3.data("holes")
        result = h.export(data, h.without(h.objects_for(data), 650), keep_unrecognised_imported=True)
        before, after = h.decode(data)["slots"], h.decode(result.data)["slots"]
        self.assertEqual(after[38]["parent_raw"], before[38]["parent_raw"])
        for i in before:
            if i not in (649, 650):
                self.assertEqual(after[i], before[i], "slot %d" % i)

    def test_a_deleted_child_of_a_deleted_parent_gets_no_warning(self):
        result = h.export(w1(), h.without(h.objects_for(w1()), 1, 650))
        self.assertNotIn("W_PARENT_CLEARED", h.codes(result.warnings))


class TestTolerances(unittest.TestCase):
    def turned(self, angle):
        rec = h.g3.model(W1).objects()[0]
        t = math.atan2(rec.forward[1], rec.forward[0]) + angle
        return (math.cos(t), math.sin(t), 0.0)

    def test_an_angle_change_below_1e_4_rad_is_not_a_change_and_above_it_is(self):
        objs = h.objects_for(w1())
        h.change(objs, 1, forward=self.turned(9.0e-5))
        self.assertEqual(h.export(w1(), objs).data, w1())
        h.change(objs, 1, forward=self.turned(-9.0e-5))
        self.assertEqual(h.export(w1(), objs).data, w1())
        h.change(objs, 1, forward=self.turned(1.2e-4))
        self.assertEqual(h.codes(h.export(w1(), objs).errors), ["E_ROTATION_GATED"])
        h.change(objs, 1, forward=self.turned(-1.2e-4))
        self.assertEqual(h.codes(h.export(w1(), objs).errors), ["E_ROTATION_GATED"])

    def test_an_up_vector_tilted_by_less_than_1e_4_is_still_unchanged(self):
        objs = h.objects_for(w1())
        h.change(objs, 1, up=(math.sin(9e-5), 0.0, math.cos(9e-5)))
        self.assertEqual(h.export(w1(), objs).data, w1())
        h.change(objs, 1, up=(math.sin(1.5e-4), 0.0, math.cos(1.5e-4)))
        self.assertEqual(h.codes(h.export(w1(), objs, **GATE).errors), ["E_TILT_UNSUPPORTED"], "a real tilt, gate or not")

    def test_a_new_object_must_be_vertical_within_1e_4(self):
        ok = export_new(w1(), block(w1(), up=(math.sin(9e-5), 0.0, math.cos(9e-5))), **GATE)
        self.assertTrue(ok.ok, [e.message for e in ok.errors])
        refused = export_new(w1(), block(w1(), up=(math.sin(1.5e-4), 0.0, math.cos(1.5e-4))), **GATE)
        self.assertEqual(h.codes(refused.errors), ["E_TILT_UNSUPPORTED"])
        upside_down = export_new(w1(), block(w1(), up=(0.0, 0.0, -1.0)), **GATE)
        self.assertEqual(h.codes(upside_down.errors), ["E_TILT_UNSUPPORTED"])
        sideways = export_new(w1(), block(w1(), forward=(0.0, 0.0, 1.0), up=(0.0, 0.0, 1.0)), **GATE)
        self.assertEqual(h.codes(sideways.errors), ["E_TILT_UNSUPPORTED"], "a vertical forward has no yaw")

    def test_vectors_are_normalised_so_scale_does_not_matter(self):
        slot = h.decode(export_new(w1(), block(w1(), forward=(0.0, 5.0, 0.0), up=(0.0, 0.0, 0.25)), **GATE).data)["slots"][0]
        self.assertEqual(slot["angle"], 12288)
        objs = h.objects_for(w1())
        rec = h.g3.model(W1).objects()[0]
        h.change(objs, 1, forward=tuple(3.0 * x for x in rec.forward), up=(0.0, 0.0, 7.0))
        self.assertEqual(h.export(w1(), objs).data, w1())

    def test_the_shortest_usable_vector_is_a_millionth(self):
        ok = export_new(w1(), block(w1(), forward=(2e-6, 0.0, 0.0)), **GATE)
        self.assertTrue(ok.ok, [e.message for e in ok.errors])
        self.assertEqual(h.decode(ok.data)["slots"][0]["angle"], 8192)
        for fields in (dict(forward=(5e-7, 0.0, 0.0)), dict(up=(0.0, 0.0, 5e-7))):
            self.assertEqual(h.codes(export_new(w1(), block(w1(), **fields), **GATE).errors), ["E_TRANSFORM_INVALID"])
        self.assertTrue(export_new(w1(), block(w1(), up=(0.0, 0.0, 2e-6)), **GATE).ok)

    def test_position_tolerance_follows_the_cell_size_on_wide_axes(self):
        """The real file's 23-bit axes have a 0.0048 cell: the tolerance is half a cell (0.0024) there, not 1e-3."""
        build, _ = h.build_modules()
        data = h.g3.data("axes_22_23_22")
        model = h.g3.model("axes_22_23_22")
        b = model.fixed.bounds
        cell = (b[3] - b[2]) / float(1 << 23)
        tol = max(1e-3, 0.5 * cell)
        objs = h.objects_for(model)
        pos = h.by_slot(objs, objs[0].slot).position
        h.change(objs, objs[0].slot, position=(pos[0], pos[1] + 0.9 * tol, pos[2]))
        self.assertEqual(h.export(data, objs).data, data)
        h.change(objs, objs[0].slot, position=(pos[0], pos[1] + 1.2 * tol, pos[2]))
        self.assertNotEqual(h.export(data, objs).data, data)


class TestTailBits(unittest.TestCase):
    def with_tail_bit(self, byte_offset, value=0x80):
        data = bytearray(w1())
        data[h.STREAM_AT + byte_offset] = value
        # the hash covers only stream[:L]: a bit far beyond L leaves it valid
        return bytes(data)

    def test_a_non_zero_tail_bit_survives_a_shift_that_keeps_it_inside_the_capacity(self):
        data = self.with_tail_bit(0x6000)
        self.assertEqual(MapVariant.from_bytes(data).soft.get("tail_nonzero"), 1)
        result = export_new(data, block(data), **GATE)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual(MapVariant.from_bytes(result.data).soft.get("tail_nonzero"), 1)
        stream_before, stream_after = h.stream_bytes(data), h.stream_bytes(result.data)
        shifted = 140                                                      # the add grows the stream by 140 bits (E2)
        before_bit = 0x6000 * 8
        after_pos = before_bit + shifted
        self.assertEqual((stream_after[after_pos // 8] >> (7 - after_pos % 8)) & 1, 1, "the tail bit moved with the quota rows")
        self.assertEqual((stream_before[before_bit // 8] >> (7 - before_bit % 8)) & 1, 1)

    def test_a_non_zero_bit_that_a_growth_would_push_out_of_the_capacity_refuses_the_export(self):
        data = self.with_tail_bit(0x6FFF, 0x01)                             # the very last bit of the stream
        result = export_new(data, block(data), **GATE)
        self.assertFalse(result.ok)
        self.assertIsNone(result.data)
        message = result.errors[0].message
        self.assertEqual(h.codes(result.errors), ["E_CAPACITY"])
        self.assertEqual(message, "The edited map variant needs %d bits; it can hold at most 229,376." % (5110 + (h.STREAM_BITS - 4970)))

    def test_a_zero_tail_can_always_lose_bits(self):
        data = w1()
        self.assertTrue(export_new(data, block(data), **GATE).ok)

    def test_a_non_zero_last_bit_is_fine_when_the_stream_does_not_grow(self):
        data = self.with_tail_bit(0x6FFF, 0x01)
        objs = h.objects_for(data)
        pos = h.by_slot(objs, 1).position
        h.change(objs, 1, position=(pos[0] + 1.0, pos[1], pos[2]))
        result = h.export(data, objs)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual(h.stream_bytes(result.data)[0x6FFF], 0x01)


class TestDiffText(unittest.TestCase):
    def test_every_kind_and_its_text(self):
        objs = h.objects_for(w1())
        h.change(objs, 1, position=(h.by_slot(objs, 1).position[0] + 1.0, h.by_slot(objs, 1).position[1], h.by_slot(objs, 1).position[2]))
        h.change(objs, 650, team=2)
        objs = h.without(objs, 5)
        objs.append(h.new_like_example(w1(), "Block, 1x1", "Added", position=h.cell_centre(h.g3.model(W1), (1, 2, 3))))
        result = h.export(w1(), objs, **GATE)
        self.assertTrue(result.ok)
        entries = [(e.kind, e.slot, e.name, e.detail) for e in result.diff]
        kinds = [e[0] for e in entries]
        self.assertEqual(kinds, ["moved", "edited", "removed", "added"], "kept entries first by slot, then removed, added, not imported")
        self.assertEqual(entries[0][3], "moved by (+1.000, +0.000, +0.000)")
        self.assertEqual(entries[1][3], "changed: team_raw")
        self.assertTrue(entries[2][3].startswith("deleted Kill Boundary at ("))
        self.assertTrue(entries[3][3].startswith("new Block, 1x1 at ("))

    def test_hidden_and_array_markers(self):
        objs = h.objects_for(w1())
        h.change(objs, 1, hidden=True)
        h.change(objs, 5, from_array=True, position=(h.by_slot(objs, 5).position[0] + 1.0,) + tuple(h.by_slot(objs, 5).position[1:]))
        result = h.export(w1(), objs)
        details = dict((e.slot, e.detail) for e in result.diff)
        self.assertEqual(details[1], "unchanged (hidden)")
        self.assertEqual(details[5], "moved by (+1.000, +0.000, +0.000) (array instance)")
        self.assertEqual(details[650], "unchanged")

    def test_the_diff_is_best_effort_on_a_refusal(self):
        objs = h.objects_for(w1())
        h.change(objs, 1, position=(9999.0, 0.0, 0.0))
        result = h.export(w1(), objs)
        self.assertFalse(result.ok)
        self.assertEqual(sorted((e.kind, e.slot) for e in result.diff), [("kept", 1), ("kept", 5), ("kept", 650)])
        self.assertIn("refused", [e.detail for e in result.diff if e.slot == 1][0])


class TestStatsAndResult(unittest.TestCase):
    def test_the_stats_of_a_patched_export(self):
        objs = h.objects_for(w1())
        h.change(objs, 1, position=(h.by_slot(objs, 1).position[0] + 3.0,) + tuple(h.by_slot(objs, 1).position[1:]))
        result = h.export(w1(), objs)
        self.assertEqual(sorted(result.stats), ["L", "capacity_bits", "end_bit", "hash_flavour", "mode", "occupied_after",
                                                "occupied_before", "quota_changes"])
        self.assertEqual((result.stats["mode"], result.stats["occupied_before"], result.stats["occupied_after"], result.stats["capacity_bits"],
                          result.stats["end_bit"], result.stats["L"], result.stats["hash_flavour"], result.stats["quota_changes"]),
                         ("patched", 3, 3, 229376, 4970, 622, "salted_be32/>", []))

    def test_a_result_is_a_complete_api_object(self):
        result = h.export(w1(), h.objects_for(w1()))
        self.assertIsInstance(result, api.ExportResult)
        self.assertTrue(result.ok)
        self.assertEqual(result.errors, [])
        for issue in result.warnings:
            self.assertIsInstance(issue, api.Issue)
        for entry in result.diff:
            self.assertIsInstance(entry, api.DiffEntry)
        self.assertIs(type(result.data), bytes)

    def test_the_export_is_stateless_and_does_not_modify_its_arguments(self):
        data = w1()
        objs = h.objects_for(data)
        pos = h.by_slot(objs, 1).position
        h.change(objs, 1, position=(pos[0] + 1.0, pos[1], pos[2]))
        snapshot = [(o.name, o.slot, o.position, o.forward, o.up, o.type_name) for o in objs]
        options = api.ExportOptions(allow_unverified_rotation=True)
        a = api.export_map_variant(data, objs, options)
        b = api.export_map_variant(data, objs, options)
        self.assertEqual(a.data, b.data)
        self.assertEqual(snapshot, [(o.name, o.slot, o.position, o.forward, o.up, o.type_name) for o in objs])
        self.assertEqual(data, w1())
        self.assertEqual((options.allow_unverified_rotation, options.raise_quota_max, options.max_objects), (True, False, 650))

    def test_the_template_can_be_a_bytearray_or_memoryview(self):
        self.assertEqual(h.export(bytearray(w1()), h.objects_for(w1())).data, w1())
        self.assertEqual(h.export(memoryview(w1()), h.objects_for(w1())).data, w1())

    def test_an_empty_object_list_deletes_every_imported_slot(self):
        result = h.export(w1(), [])
        self.assertTrue(result.ok)
        self.assertEqual(sorted(h.decode(result.data)["slots"]), [])


class TestVerificationBites(unittest.TestCase):
    """Fault injection: a writer that produces a wrong file is stopped by the re-parse of step 12 (an InternalError)."""

    def objs(self):
        objs = h.objects_for(w1())
        pos = h.by_slot(objs, 1).position
        h.change(objs, 1, position=(pos[0] + 1.0, pos[1], pos[2]))
        return objs

    def corrupt_render(self, transform):
        original = MapVariant.render

        def render(model, force=False, flavour=None):
            rendered = original(model, force, flavour)
            return type(rendered)(transform(rendered.data), rendered.issues)
        return mock.patch.object(MapVariant, "render", render)

    def flip_stream_bit(self, bit):
        def fn(data):
            out = bytearray(data)
            out[h.STREAM_AT + bit // 8] ^= 0x80 >> (bit % 8)
            return bytes(out)
        return fn

    def test_a_flipped_slot_bit_is_caught(self):
        dec = h.decode(w1())
        lo, hi = h.slot_span(dec, 5, "spawn_seq")
        with self.corrupt_render(self.flip_stream_bit(lo + 3)):
            with self.assertRaises(errors.InternalError) as cm:
                h.export(w1(), self.objs())
        self.assertIn("slot 5 does not decode to the planned values", str(cm.exception))

    def test_a_flipped_quota_bit_is_caught(self):
        dec = h.decode(w1())
        bit = dec["sections"]["quotas"] + 24 * 70 + 20
        with self.corrupt_render(self.flip_stream_bit(bit)):
            with self.assertRaises(errors.InternalError) as cm:
                h.export(w1(), self.objs())
        self.assertIn("quota rows differ from the plan", str(cm.exception))

    def test_a_flipped_label_or_body_bit_is_caught(self):
        dec = h.decode(w1())
        for bit, word in ((dec["sections"]["labels"] + 40, "never edited"), (dec["sections"]["body_fixed"] + 100, "never edited")):
            with self.subTest(bit):
                with self.corrupt_render(self.flip_stream_bit(bit)):
                    with self.assertRaises(errors.InternalError) as cm:
                        h.export(w1(), self.objs())
                self.assertIn(word, str(cm.exception))

    def test_a_flipped_header_bit_other_than_the_file_length_is_caught(self):
        with self.corrupt_render(self.flip_stream_bit(100)):
            with self.assertRaises(errors.InternalError):
                h.export(w1(), self.objs())

    def test_a_file_that_cannot_be_read_back_is_caught(self):
        def wreck(data):
            out = bytearray(data)
            out[h.LENGTH_AT:h.LENGTH_AT + 4] = b"\xff\xff\xff\xff"
            return bytes(out)
        with self.corrupt_render(wreck):
            with self.assertRaises(errors.InternalError) as cm:
                h.export(w1(), self.objs())
        self.assertIn("could not be read back", str(cm.exception))

    def test_a_forced_re_encode_that_differs_is_caught(self):
        original = MapVariant.to_bytes

        def to_bytes(model, force=False, flavour=None):
            data = original(model, force, flavour)
            if force and model.blf.original != w1():                       # the re-parsed OUTPUT, not the template
                out = bytearray(data)
                out[0x7318 + 12] ^= 0x01                                  # the forced rebuild would repair an _eof value: pretend it did not
                return bytes(out)
            return data
        with mock.patch.object(MapVariant, "to_bytes", to_bytes):
            with self.assertRaises(errors.InternalError) as cm:
                h.export(w1(), self.objs())
        self.assertIn("forced re-encode", str(cm.exception))

    def test_a_planning_bug_in_the_position_is_caught_by_the_request_check(self):
        real = codecs.pos_encode
        with mock.patch.object(codecs, "pos_encode", lambda v, bits, mn, mx: real(v, bits, mn, mx) + 4000):
            with self.assertRaises(errors.InternalError) as cm:
                h.export(w1(), self.objs())
        self.assertIn("position axis 0", str(cm.exception))

    def test_a_planning_bug_in_the_team_is_caught_by_the_request_check(self):
        real = codecs.team_raw
        objs = h.objects_for(w1())
        h.change(objs, 650, team=2)
        with mock.patch.object(codecs, "team_raw", lambda view: real(view) + 1):
            with self.assertRaises(errors.InternalError) as cm:
                h.export(w1(), objs)
        self.assertIn("team is", str(cm.exception))

    def test_a_planning_bug_in_the_yaw_is_caught_by_the_request_check(self):
        real = codecs.angle_encode
        objs = h.objects_for(w1())
        h.change(objs, 1, forward=(0.0, 1.0, 0.0))
        with mock.patch.object(codecs, "angle_encode", lambda theta: real(theta) + 1000):
            with self.assertRaises(errors.InternalError) as cm:
                h.export(w1(), objs, **GATE)
        self.assertIn("rotation does not match the requested yaw", str(cm.exception))

    def test_the_honest_writer_passes_every_check(self):
        self.assertTrue(h.export(w1(), self.objs()).ok)


class TestHelpers(unittest.TestCase):
    """The small pure helpers of ``edit`` and ``validate``."""

    def test_the_header_comparison_ignores_only_the_embedded_file_length(self):
        from mvarlib.bitio import BitString
        base = BitString.from_int(0x6A5B4C3D2E1F00112233, 80)
        self.assertTrue(edit._same_except_file_length(base, base))
        for bit in (0, 3):                                              # inside the 4 bits before the file length
            self.assertFalse(edit._same_except_file_length(base, BitString.from_int(base.to_int() ^ (1 << (79 - bit)), 80)))
        for bit in (4, 20, 35):                                         # the 32-bit file length: any change is allowed
            self.assertTrue(edit._same_except_file_length(base, BitString.from_int(base.to_int() ^ (1 << (79 - bit)), 80)))
        for bit in (36, 79):
            self.assertFalse(edit._same_except_file_length(base, BitString.from_int(base.to_int() ^ (1 << (79 - bit)), 80)))
        self.assertFalse(edit._same_except_file_length(base, BitString.from_int(0, 79)))
        self.assertFalse(edit._same_except_file_length(BitString.from_int(0, 20), BitString.from_int(0, 20)), "too short to hold a file length")

    def test_to_int_accepts_integers_and_integral_floats_only(self):
        from mvarlib import validate
        self.assertEqual([validate.to_int(v) for v in (3, 3.0, -2.0, True, False)], [3, 3, -2, 1, 0])
        self.assertEqual([validate.to_int(v) for v in (3.5, float("nan"), float("inf"), None, "3", [3])], [None] * 6)

    def test_float_values_of_integer_fields(self):
        ok = export_new(w1(), block(w1(), spawn_time=3.0, spawn_sequence=-4.0, team=2.0), **GATE)
        self.assertTrue(ok.ok, [e.message for e in ok.errors])
        slot = h.decode(ok.data)["slots"][0]
        self.assertEqual((slot["respawn"], slot["spawn_seq"], slot["team_raw"]), (3, -4, 3))
        bad = export_new(w1(), block(w1(), spawn_time=3.5), **GATE)
        self.assertEqual(h.codes(bad.errors), ["E_SPAWN_RANGE"])

    def test_the_angle_between_two_vectors_is_accurate_for_tiny_angles(self):
        from mvarlib import validate
        self.assertAlmostEqual(validate.angle_between((1, 0, 0), (math.cos(1e-6), math.sin(1e-6), 0)), 1e-6, places=12)
        self.assertAlmostEqual(validate.angle_between((0, 0, 1), (0, 0, -1)), math.pi, places=12)
        self.assertAlmostEqual(validate.angle_between((5, 0, 0), (0, 0.5, 0)), math.pi / 2, places=12)

    def test_yaw_of_a_forward_vector(self):
        from mvarlib import validate
        self.assertEqual(validate.yaw_of((1, 0, 0)), 0.0)
        self.assertAlmostEqual(validate.yaw_of((0, 1, 0)), math.pi / 2)
        self.assertAlmostEqual(validate.yaw_of((-1, 0, 1e-9)), math.pi)
        self.assertIsNone(validate.yaw_of((0, 0, 1)))
        self.assertIsNone(validate.yaw_of((1e-9, 0, 5)))

    def test_the_quota_decision_table(self):
        from mvarlib import validate
        cases = [((2, 3, 0, 5, False), (None, 5)), ((2, 6, 0, 5, False), ("E_QUOTA", 5)), ((2, 6, 0, 5, True), (None, 6)),
                 ((6, 6, 0, 5, False), (None, 5)), ((7, 6, 0, 5, False), (None, 5)), ((6, 5, 0, 5, False), (None, 5)),
                 ((3, 2, 3, 9, False), ("E_QUOTA_MIN", 9)), ((2, 3, 3, 9, False), (None, 9)), ((2, 2, 3, 9, False), (None, 9)),
                 ((255, 256, 0, 255, True), ("E_QUOTA_RANGE", 255)), ((254, 255, 0, 255, False), (None, 255)),
                 ((0, 5, 0, 0, True), (None, 5)), ((5, 5, 0, 20, True), (None, 20))]
        for args, expected in cases:
            self.assertEqual(validate.quota_decision(*args), expected, args)

    def test_the_palette_name_of_a_folder(self):
        from mvarlib import validate
        rows = [(0x4600, "block_1x1", "Block, 1x1"), (0x4601, "block_1x1_flat", "Block, 1x1, Flat"), (0x3D00, "kill", "Kill Boundary")]
        self.assertEqual(validate.palette_name_for_folder(rows, 0x46), "Block, 1x1", "the first stock object of the folder")
        self.assertEqual(validate.palette_name_for_folder(rows, 0x3D), "Kill Boundary")
        self.assertEqual(validate.palette_name_for_folder(rows, 0x00), "Unknown")
        self.assertEqual(validate.palette_name_for_folder(rows, 0x01), "Unknown", "an item byte is not a folder")
        self.assertEqual(validate.palette_name_for_folder([], 3), "Unknown")

    def test_make_fills_the_pattern_and_the_location(self):
        from mvarlib import validate
        issue = validate.make("W_SLOT_NOT_IMPORTED", 7, slot=7, object_name="x")
        self.assertEqual((issue.code, issue.severity, issue.slot, issue.object_name), ("W_SLOT_NOT_IMPORTED", "warning", 7, "x"))
        self.assertEqual(issue.message, "Slot 7 could not be imported earlier; it was left unchanged in the exported file.")
        self.assertEqual(validate.pattern("E_TEAM_RANGE"), "Object '%s': team must be 0 to 8.")
        with self.assertRaises(TypeError):
            validate.make("E_TEAM_RANGE")                                # a missing argument is a bug, not a silent empty text

    def test_other_limits_by_class(self):
        from mvarlib import validate
        self.assertEqual(validate.other_limits(1, "flag8"), (0, 255, 0))
        for cls in (12, 13, 14):
            self.assertEqual(validate.other_limits(cls, "flag8"), (0, 31, 31))
        self.assertEqual(validate.other_limits(19, "flag8"), (-1, 255, 0))
        self.assertEqual(validate.other_limits(19, "plain8"), (-1, 254, 0))
        for cls in (0, 2, 7, 11, 15, 18, 20, 26, 31):
            self.assertEqual(validate.other_limits(cls, "flag8"), (0, 0, 0))


class TestRandomEdits(unittest.TestCase):
    """A seeded mini fuzz: random valid-looking edits of every plain fixture either come back as a clean refusal (no bytes, only
    library issues) or as a file the INDEPENDENT walker reads, whose stored hash is right and whose untouched slots decode as before."""

    OPS = ("move", "delete", "add", "yaw", "color", "label", "spawn", "team", "shape", "physics")

    def one(self, rng, names):
        name = rng.choice(names)
        data = h.g3.data(name)
        model = h.g3.model(name)
        objs = h.objects_for(model)
        b = model.fixed.bounds
        touched = set()
        for _ in range(rng.randrange(1, 4)):
            kind = rng.choice(self.OPS)
            if kind == "add":
                t = rng.choice(["Block, 1x1", "Block, 1x1, Flat", "Kill Boundary", "Bridge, Small", "Assault Rifle", "Wall", "Door"])
                pos = tuple(rng.uniform(b[2 * k], b[2 * k + 1]) for k in range(3))
                angle = rng.random() * 6.0
                objs.append(h.new_object("New%03d" % rng.randrange(1000), type_name=t, position=pos,
                                         forward=(math.cos(angle), math.sin(angle), 0.0), physics=rng.choice([0, 1, 3]),
                                         team=rng.randrange(9), color=rng.choice([-1, 0, 3, 7]), label_index=rng.choice([-1, 0]),
                                         shape=rng.choice([0, 1, 2, 3]), width=rng.uniform(0, 200), length=rng.uniform(0, 200),
                                         top=rng.uniform(0, 200), bottom=rng.uniform(0, 200),
                                         spawn_sequence=rng.randrange(-128, 128), spawn_time=rng.randrange(256)))
                continue
            claimed = [o for o in objs if o.slot is not None]
            if not claimed:
                continue
            o = rng.choice(claimed)
            touched.add(o.slot)
            if kind == "move":
                pos = list(o.position)
                pos[rng.randrange(3)] += rng.uniform(-3, 3)
                o.position = tuple(pos)
            elif kind == "delete":
                objs.remove(o)
            elif kind == "yaw":
                angle = rng.random() * 6.2 - 3.1
                o.forward = (math.cos(angle), math.sin(angle), 0.0)
            elif kind == "color":
                o.color = rng.choice([-1, 0, 5])
            elif kind == "label":
                o.label_index = rng.choice([-1, 0])
            elif kind == "spawn":
                o.spawn_sequence, o.spawn_time = rng.randrange(-128, 128), rng.randrange(256)
            elif kind == "team":
                o.team = rng.randrange(9)
            elif kind == "shape":
                o.shape = rng.choice([0, 1, 2, 3])
                o.width, o.length, o.top, o.bottom = (rng.uniform(0, 200) for _ in range(4))
            else:
                o.physics = rng.choice([0, 1, 3])
        options = dict(allow_unverified_rotation=rng.random() < 0.8, keep_unrecognised_imported=True, raise_quota_max=rng.random() < 0.7,
                       force_reencode=rng.random() < 0.1, fsm_policy=rng.choice(["KEEP", "DROP"]),
                       hash_policy=rng.choice(["REPRODUCE", "REPRODUCE", "SALTED_BE32", "PLAIN_LE32"]))
        return name, data, objs, options, touched

    def test_random_edits_are_refused_cleanly_or_written_consistently(self):
        rng = random.Random(20261010)
        names = [n for n in h.g3.positive_names() if h.g3.spec(n)["container"]["shape"] != "other"]
        _b, selfcheck = h.build_modules()
        written = refused = 0
        for _ in range(80):
            name, data, objs, options, touched = self.one(rng, names)
            result = h.export(data, objs, **options)
            label = "%s %r" % (name, options)
            if not result.ok:
                refused += 1
                self.assertIsNone(result.data, label)
                self.assertTrue(result.errors, label)
                for issue in result.errors:
                    self.assertIn(issue.code, validate_codes(), label)
                continue
            written += 1
            walked = selfcheck.read(result.data)
            self.assertEqual(walked["outcome"], "ok", (label, walked.get("error"), walked.get("message")))
            again = MapVariant.from_bytes(result.data)
            self.assertEqual(again.occupied, result.stats["occupied_after"], label)
            before, after = h.decode(data), walked["decoded"]
            if result.data != data and again.blf.shape in ("plain4", "plain4+fsm", "cmp4", "cmp4+fsm"):
                model = h.g3.model(name)
                if model.length_class == "ceil_end" and result.stats["mode"] != "passthrough":
                    self.assertEqual(again.chunk.stored_length, (after["end"] + 7) // 8, label)
                if again.flavour is not None and again.flavour.recipe != "zero":
                    length = again.chunk.stored_length or 0x7000
                    self.assertEqual(h.stored_hash(result.data), selfcheck.digest(again.flavour.recipe, h.stream_bytes(result.data), length), label)
            for slot, fields in before["slots"].items():
                if slot not in touched and slot in after["slots"] and result.stats["occupied_after"] >= 0:
                    deleted_parent = fields["parent_raw"] and (fields["parent_raw"] - 1) not in after["slots"]
                    if not deleted_parent:
                        self.assertEqual(after["slots"][slot], fields, "%s untouched slot %d" % (label, slot))
        self.assertGreater(written, 20)
        self.assertGreater(refused, 3)


def validate_codes():
    from mvarlib import validate
    return set(validate.MESSAGES)


class TestAssortedRules(unittest.TestCase):
    def test_hash_and_fsm_policies_are_validated_first(self):
        result = h.export(w1(), h.objects_for(w1()), fsm_policy="REMOVE", hash_policy="MD5")
        self.assertEqual([e.message for e in result.errors],
                         ["The export option fsm_policy has the unknown value 'REMOVE'.", "The export option hash_policy has the unknown value 'MD5'."])

    def test_deleting_an_object_with_an_unknown_type_needs_no_option(self):
        data = h.g3.data("holes")
        model = h.g3.model("holes")
        bad = [r.slot for r in model.objects() if not r.stock]
        result = h.export(data, h.without(h.objects_for(model), *bad))
        self.assertTrue(result.ok)
        self.assertEqual(sorted(h.decode(result.data)["slots"]), sorted(r.slot for r in model.objects() if r.stock))

    def test_an_unknown_type_object_can_still_be_moved_when_kept(self):
        data = h.g3.data("holes")
        model = h.g3.model("holes")
        slot = next(r.slot for r in model.objects() if not r.stock and r.type_id >= 0)
        objs = h.objects_for(model)
        pos = h.by_slot(objs, slot).position
        h.change(objs, slot, position=(pos[0] + 1.0, pos[1], pos[2]))
        result = h.export(data, objs, keep_unrecognised_imported=True)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual([(e.kind, e.slot) for e in result.diff if e.kind != "kept"], [("moved", slot)])

    def test_the_class_of_an_unknown_type_object_cannot_change(self):
        data = h.g3.data("holes")
        model = h.g3.model("holes")
        slot = next(r.slot for r in model.objects() if not r.stock and r.type_id >= 0)
        objs = h.objects_for(model)
        h.change(objs, slot, cached_type=5)
        self.assertEqual(h.codes(h.export(data, objs, keep_unrecognised_imported=True).errors), ["E_CACHED_TYPE_CHANGED"])

    def test_shape_changes_on_an_existing_object_are_range_checked(self):
        objs = h.objects_for(w1())
        h.change(objs, 5, top=300.0)
        self.assertEqual([e.message for e in h.export(w1(), objs).errors], ["Object '5 - Kill Boundary': top must be between 0 and 200 (got 300.000)."])

    def test_a_label_and_a_spawn_change_on_an_existing_object(self):
        objs = h.objects_for(w1())
        h.change(objs, 1, label_index=1, spawn_sequence=9, spawn_time=45)
        result = h.export(w1(), objs)
        slot = h.decode(result.data)["slots"][1]
        self.assertEqual((slot["label"], slot["spawn_seq"], slot["respawn"]), (1, 9, 45))
        self.assertEqual([e.detail for e in result.diff if e.kind == "edited"], ["changed: label, respawn, spawn_seq"])

    def test_a_team_over_a_none_baseline_is_a_change_unless_it_is_neutral(self):
        """W1 slot 5 stores team raw 0 (none): neutral (8) is unchanged; any real team is written (raw = team + 1)."""
        for team, raw in ((8, 0), (0, 1), (2, 3), (7, 8)):
            objs = h.objects_for(w1())
            h.change(objs, 5, team=team)
            slot = h.decode(h.export(w1(), objs).data)["slots"][5]
            self.assertEqual(slot["team_raw"], raw, team)

    def test_the_type_19_guard_refuses_while_the_rule_is_undetermined(self):
        """An unknown planned rule is refused; native evidence can resolve the plan without changing the template."""
        import types
        ex = edit._Export(b"", [], api.ExportOptions())
        obj = h.new_object("N")
        ex.m = types.SimpleNamespace(type19_status="undetermined")
        ex.p = types.SimpleNamespace(type19_status="undetermined")
        self.assertFalse(ex._type19_ok(obj))
        self.assertEqual([e.code for e in ex.errors_object], ["E_TYPE19_UNDETERMINED"])
        ex.p = types.SimpleNamespace(type19_status="plain8")
        self.assertTrue(ex._type19_ok(obj))
        self.assertEqual(len(ex.errors_object), 1)

    def test_a_dropped_fsm_counts_as_a_modification_of_an_unsupported_shape(self):
        data = h.g3.data("fsm")
        unknown = b"abcd" + (16).to_bytes(4, "big") + (1).to_bytes(2, "big") + (1).to_bytes(2, "big") + bytes(4)
        cut = h.MVAR + 0x7028
        other = data[:cut] + unknown + data[cut:]
        self.assertEqual(MapVariant.from_bytes(other).shape, "other")
        self.assertTrue(h.export(other, h.objects_for(other)).ok)
        dropped = h.export(other, h.objects_for(other), fsm_policy="DROP")
        self.assertEqual([e.message for e in dropped.errors], ["This file's block layout (_blf, chdr, mvar, abcd, _eof, _fsm) cannot be modified safely."])
        self.assertIsNone(dropped.data)

    def test_the_diff_lists_existing_slots_then_removed_then_added_then_not_imported(self):
        objs = h.objects_for(w1())
        pos = h.by_slot(objs, 1).position
        h.change(objs, 1, position=(pos[0] + 1.0, pos[1], pos[2]))
        objs = h.without(objs, 5, 650)
        objs.append(block(w1(), "New"))
        result = h.export(w1(), objs, imported_slots=[1, 650], **GATE)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual([(e.kind, e.slot) for e in result.diff], [("moved", 1), ("removed", 650), ("added", 0), ("not_imported", 5)])

    def test_a_no_op_export_reports_the_template_numbers(self):
        result = h.export(w1(), h.objects_for(w1()))
        self.assertEqual(result.stats, {"mode": "passthrough", "occupied_before": 3, "occupied_after": 3, "capacity_bits": 229376,
                                        "end_bit": 4970, "L": 622, "hash_flavour": "salted_be32/>", "quota_changes": []})
        zero = h.g3.data("zero_hash")
        self.assertEqual(h.export(zero, h.objects_for(zero)).stats["hash_flavour"], "zero/>")

    def test_an_object_with_invalid_values_is_listed_as_not_exported(self):
        objs = h.objects_for(w1())
        h.change(objs, 1, position=(float("nan"), 0.0, 0.0))
        result = h.export(w1(), objs)
        entry = [e for e in result.diff if e.slot == 1]
        self.assertEqual([(e.kind, e.detail) for e in entry], [("kept", "not exported: the object has invalid values (see the errors)")])

    def test_colour_and_team_changes_on_an_existing_object(self):
        objs = h.objects_for(w1())
        h.change(objs, 1, color=6, team=0)
        slot = h.decode(h.export(w1(), objs).data)["slots"][1]
        self.assertEqual((slot["color"], slot["team_raw"]), (6, 1))


if __name__ == "__main__":
    unittest.main()
