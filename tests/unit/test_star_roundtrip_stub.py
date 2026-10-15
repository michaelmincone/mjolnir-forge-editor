"""S1 preparation: ``tests/stubs/stub_roundtrip.py``, the stub that remembers what it was asked to write.

It is test infrastructure for the block-star pipeline (export, then read back), not a codec, so what matters is that
it behaves like the contract it stands in for: the same names as ``mvarlib.api``, canned maps chosen by template
bytes, the plain stub's controls still working, the few validation rules it claims, and a deliberately wrong file for
each mistake the star verifier must catch. Pure Python, no Blender.
"""
import dataclasses
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "Addon"))
sys.path.insert(0, os.path.join(REPO, "tests", "stubs"))

import provider  # noqa: E402
import stub_mvarlib as base  # noqa: E402
import stub_roundtrip as rt  # noqa: E402


def export_object(name, position=(0.0, 0.0, 0.0), slot=None, **kwargs):
    fields = dict(name=name, slot=slot, token_raw=None, token_bits=None, type_name="Block, 1x1", position=position,
                  forward=(0.0, 1.0, 0.0), up=(0.0, 0.0, 1.0), physics=1, symmetry=3, place_at_start=True,
                  game_specific=False, team=8, color=-1)
    fields.update(kwargs)
    return rt.ExportObject(**fields)


def originals(template=b"t"):
    return [rt.ExportObject(name="%d - %s" % (r.slot, r.type_name), slot=r.slot, token_raw=r.raw, token_bits=r.raw_bits,
                            type_name=r.type_name, position=r.position, forward=r.forward, up=r.up)
            for r in rt.load_map_variant(template).objects]


def options(**kwargs):
    fields = dict(allow_unverified_rotation=True)
    fields.update(kwargs)
    return rt.ExportOptions(**fields)


class RoundtripCase(unittest.TestCase):
    def setUp(self):
        rt.reset()

    def tearDown(self):
        rt.reset()
        provider.set_provider(None)

    def write(self, new, template=b"t", **opts):
        return rt.export_map_variant(template, originals(template) + list(new), options(**opts))


class TestContract(RoundtripCase):
    def test_it_is_a_complete_provider(self):
        self.assertEqual(provider.missing_names(rt), [])
        provider.set_provider(rt)
        self.assertIs(provider.get_provider(), rt)
        self.assertTrue(rt.IS_STUB and rt.ROUNDTRIP)
        self.assertFalse(getattr(base, "ROUNDTRIP", False), "the plain stub stays unable to remember")

    def test_plain_bytes_load_as_the_canned_map(self):
        result = rt.load_map_variant(b"anything")
        self.assertEqual(result.info.map_name, "Forge World")
        self.assertEqual([r.slot for r in result.objects], [1, 2, 5, 9, 11])
        self.assertEqual(result.info.template_sha256, __import__("hashlib").sha256(b"anything").hexdigest())

    def test_template_flavours(self):
        self.assertEqual(rt.load_map_variant(rt.map_template(1080)).info.map_name, "Boneyard")
        self.assertEqual(rt.load_map_variant(rt.map_template(3006)).info.map_name, "Forge World")
        with self.assertRaises(KeyError):
            rt.map_template(1)
        no_blocks = rt.load_map_variant(rt.NO_BLOCKS_TEMPLATE)
        self.assertFalse([r for r in no_blocks.objects if r.type_name.startswith("Block")])
        self.assertEqual(no_blocks.info.occupied, len(no_blocks.objects))
        odd = rt.load_map_variant(rt.ODD_EXAMPLE_TEMPLATE)
        block = [r for r in odd.objects if r.slot == 1][0]
        self.assertEqual((block.symmetry, block.place_at_start, block.game_specific), (1, False, True))
        self.assertEqual([r for r in odd.objects if r.slot == 9][0].symmetry, 3, "only slot 1 is odd")

    def test_a_real_like_template_has_the_shape_of_the_one_real_file(self):
        result = rt.load_map_variant(rt.real_like_template())
        self.assertEqual((result.info.map_name, result.info.occupied, len(result.objects)), ("Breakneck", 610, 610))
        self.assertEqual(result.info.bounds, (-20000.0, 20000.0) * 3)
        self.assertEqual(result.info.quota_count, 82)
        self.assertEqual(result.info.hash_flavour, "plain_le32/>")
        self.assertEqual(len(set(r.slot for r in result.objects)), 610)
        self.assertFalse([r for r in result.objects if r.type_name.startswith("Block")], "no block in the template")
        self.assertEqual(rt.load_map_variant(rt.real_like_template()).objects, result.objects, "deterministic")
        self.assertEqual(len(rt.load_map_variant(rt.real_like_template(100)).objects), 100)
        for r in result.objects:
            self.assertTrue(-30 < r.position[0] < 30 and -30 < r.position[1] < 30 and 2.0 < r.position[2] < 22.0)

    def test_a_huge_bounds_range_uses_a_coarser_position_cell(self):
        template = rt.real_like_template(10)
        orig = originals(template)
        result = rt.export_map_variant(template, orig + [export_object("Star 000", (1.0, 2.0, 5.0))], options())
        self.assertTrue(result.ok, result.errors)
        record = [r for r in rt.load_map_variant(result.data).objects if r.slot == 10][0]
        cell = 40000.0 / 8388608.0
        for got, want in zip(record.position, (1.0, 2.0, 5.0)):
            self.assertLessEqual(abs(got - want), cell / 2.0 + 1e-9)
        self.assertGreater(max(abs(got - want) for got, want in zip(record.position, (1.0, 2.0, 5.0))), 0.0005,
                           "coarser than the default 0.0005 quantum")

    def test_the_plain_stub_controls_still_work(self):
        base.NEXT_LOAD = base.CANNED_BONEYARD
        self.assertEqual(rt.load_map_variant(b"x").info.map_name, "Boneyard")
        self.assertEqual(rt.load_map_variant(b"x").info.map_name, "Forge World", "NEXT_LOAD is consumed")
        base.NEXT_LOAD_ERROR = base.UnsupportedVariantError("nope")
        with self.assertRaises(base.UnsupportedVariantError):
            rt.load_map_variant(b"x")
        rt.load_map_variant(b"y", "n.mvar")
        self.assertEqual(base.LAST_LOAD[1], "n.mvar", "the plain stub's LAST_LOAD is kept up to date")
        base.preset_refusal(rt.Issue("E_QUOTA", "error", "full"))
        result = self.write([export_object("Star 000")])
        self.assertFalse(result.ok)
        self.assertEqual([e.code for e in result.errors], ["E_QUOTA"])
        self.assertIsNotNone(base.LAST_EXPORT, "the plain stub recorded the call")
        self.assertEqual(len(base.LAST_EXPORT[1]), 6)

    def test_reset_clears_everything(self):
        rt.CORRUPT = "drop"
        rt.QUOTA_MAX = {"x": 1}
        rt.QUANT = 1.0
        base.NEXT_LOAD = base.CANNED_BONEYARD
        self.write([export_object("Star 000")])
        rt.reset()
        self.assertEqual((rt.CORRUPT, rt.QUOTA_MAX, rt.QUANT), (None, {}, 0.0005))
        self.assertIsNone(base.NEXT_LOAD)
        self.assertIsNone(base.LAST_EXPORT)


class TestWriteAndRead(RoundtripCase):
    def test_new_objects_take_the_lowest_free_slots_in_name_order_and_read_back(self):
        new = [export_object("Star 002", (12.0, 0.0, 5.0)), export_object("Star 000", (10.0, 0.0, 5.0)),
               export_object("Star 001", (11.0, 0.0, 5.0))]
        result = self.write(new)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.stats["occupied_before"], 5)
        self.assertEqual(result.stats["occupied_after"], 8)
        self.assertEqual([d.kind for d in result.diff].count("added"), 3)
        back = rt.load_map_variant(result.data)
        self.assertEqual(back.info.occupied, 8)
        by_slot = dict((r.slot, r) for r in back.objects)
        self.assertEqual(sorted(by_slot), [0, 1, 2, 3, 4, 5, 9, 11], "slots 0, 3, 4 were free")
        self.assertAlmostEqual(by_slot[0].position[0], 10.0, delta=rt.QUANT)
        self.assertAlmostEqual(by_slot[3].position[0], 11.0, delta=rt.QUANT)
        self.assertAlmostEqual(by_slot[4].position[0], 12.0, delta=rt.QUANT)
        self.assertEqual([by_slot[s].physics for s in (0, 3, 4)], [1, 1, 1])
        self.assertEqual(by_slot[0].type_name, "Block, 1x1")
        self.assertEqual(by_slot[0].type_id, 0x4600)
        for slot in (1, 2, 5, 9, 11):                          # the originals are bit-identical records
            self.assertEqual(by_slot[slot], [r for r in base.CANNED.objects if r.slot == slot][0])

    def test_positions_are_quantised_like_a_cell_centre_codec(self):
        rt.QUANT = 0.25
        result = self.write([export_object("Star 000", (1.30, -2.10, 3.99))])
        record = [r for r in rt.load_map_variant(result.data).objects if r.slot == 0][0]
        for got, want in zip(record.position, (1.30, -2.10, 3.99)):
            self.assertLessEqual(abs(got - want), 0.125 + 1e-9)
        self.assertEqual(record.position[0], 1.375, "bounds minimum -240 + (floor(...) + 0.5) * 0.25")

    def test_an_output_can_be_exported_again(self):
        first = self.write([export_object("Star 000", (1.0, 0.0, 5.0))])
        second = rt.export_map_variant(first.data, [export_object("Star 001", (2.0, 0.0, 5.0))] + [
            rt.ExportObject(name="o%d" % r.slot, slot=r.slot, token_raw=r.raw, token_bits=r.raw_bits, type_name=r.type_name)
            for r in rt.load_map_variant(first.data).objects], options())
        self.assertTrue(second.ok, second.errors)
        back = rt.load_map_variant(second.data)
        self.assertEqual(back.info.occupied, 7)
        self.assertEqual(sorted(r.slot for r in back.objects), [0, 1, 2, 3, 5, 9, 11])

    def test_physics_follows_the_export_object(self):
        result = self.write([export_object("Star 000", physics=0), export_object("Star 001", physics=3)])
        by_slot = dict((r.slot, r) for r in rt.load_map_variant(result.data).objects)
        self.assertEqual((by_slot[0].physics, by_slot[3].physics), (0, 3))

    def test_the_module_data_is_never_mutated(self):
        before = (base.CANNED.info, tuple(base.CANNED.objects))
        self.write([export_object("Star 000")])
        self.assertEqual((base.CANNED.info, tuple(base.CANNED.objects)), before)


class TestRefusals(RoundtripCase):
    def codes(self, result):
        self.assertFalse(result.ok)
        self.assertIsNone(result.data)
        return [e.code for e in result.errors]

    def test_the_rotation_gate(self):
        result = self.write([export_object("Star 000")], allow_unverified_rotation=False)
        self.assertEqual(self.codes(result), ["E_ROTATION_GATED"])
        self.assertTrue(self.write([]).ok, "nothing new, nothing gated")

    def test_unknown_names_and_names_that_are_not_stock_on_this_map(self):
        self.assertEqual(self.codes(self.write([export_object("Star 000", type_name="Warthog Block")])), ["E_OBJ_NAME_UNKNOWN"])
        boneyard = rt.map_template(1080)
        result = rt.export_map_variant(boneyard, originals(boneyard) + [export_object("Star 000", type_name="Block, 2x2")], options())
        self.assertEqual(self.codes(result), ["E_OBJ_NAME_UNKNOWN"])

    def test_bounds_are_half_open(self):
        low, high = -240.0, 240.0
        self.assertTrue(self.write([export_object("Star 000", (low, 0.0, 0.0))]).ok)
        self.assertEqual(self.codes(self.write([export_object("Star 000", (high, 0.0, 0.0))])), ["E_OUT_OF_BOUNDS"])
        self.assertEqual(self.codes(self.write([export_object("Star 000", (0.0, -345.001, 0.0))])), ["E_OUT_OF_BOUNDS"])
        self.assertEqual(self.codes(self.write([export_object("Star 000", (0.0, 0.0, 70.0))])), ["E_OUT_OF_BOUNDS"])

    def test_flags_must_equal_the_examples(self):
        self.assertEqual(self.codes(self.write([export_object("Star 000", symmetry=1)])), ["E_FLAG_UNVERIFIED"])
        self.assertEqual(self.codes(self.write([export_object("Star 000", place_at_start=False)])), ["E_FLAG_UNVERIFIED"])
        self.assertEqual(self.codes(self.write([export_object("Star 000", game_specific=True)])), ["E_FLAG_UNVERIFIED"])
        odd = rt.ODD_EXAMPLE_TEMPLATE
        copy = export_object("Star 000", symmetry=1, place_at_start=False, game_specific=True)
        self.assertTrue(rt.export_map_variant(odd, originals(odd) + [copy], options()).ok, "the example's own flags pass")
        self.assertEqual(self.codes(rt.export_map_variant(odd, originals(odd) + [export_object("Star 000")], options())),
                         ["E_FLAG_UNVERIFIED"])

    def test_quota_counts_the_template_and_the_new_objects(self):
        rt.QUOTA_MAX = {"Block, 1x1": 4}                       # the template has 2
        self.assertTrue(self.write([export_object("Star 000"), export_object("Star 001")]).ok)
        result = self.write([export_object("Star %03d" % i) for i in range(3)])
        self.assertEqual(self.codes(result), ["E_QUOTA"])
        self.assertIn("would have 5 placed", result.errors[0].message)
        self.assertTrue(self.write([export_object("Star 000", type_name="Block, 1x1, Flat")]).ok, "another type is not limited")

    def test_the_object_limit_and_the_free_slots(self):
        many = [export_object("Star %03d" % i, (float(i % 400) - 200.0, 0.0, 0.0)) for i in range(647)]
        self.assertTrue(self.write(many[:645]).ok, "5 + 645 = 650")
        result = self.write(many[:646])
        self.assertEqual(self.codes(result), ["E_TOO_MANY"])
        self.assertIn("651 objects would be written; the limit is 650", result.errors[0].message)
        self.assertTrue(self.write(many[:646], max_objects=1000).ok, "651 records exist: 5 + 646 fill them all")
        result = self.write(many, max_objects=1000)
        self.assertEqual(self.codes(result), ["E_NO_FREE_SLOT"], "one more than the 651 records")

    def test_every_problem_is_reported_together(self):
        result = self.write([export_object("Star 000", (1000.0, 0.0, 0.0), symmetry=1)], allow_unverified_rotation=False)
        self.assertEqual(sorted(self.codes(result)), ["E_FLAG_UNVERIFIED", "E_OUT_OF_BOUNDS", "E_ROTATION_GATED"])


class TestDeliberatelyWrongFiles(RoundtripCase):
    def read(self, mode):
        rt.CORRUPT = mode
        new = [export_object("Star %03d" % i, (float(i), 0.0, 5.0)) for i in range(4)]
        result = self.write(new)
        self.assertTrue(result.ok)
        return rt.load_map_variant(result.data)

    def new_records(self, back):
        return [r for r in back.objects if r.slot not in (1, 2, 5, 9, 11)]

    def test_a_clean_write_for_comparison(self):
        back = self.read(None)
        self.assertEqual(len(self.new_records(back)), 4)

    def test_drop(self):
        self.assertEqual(len(self.new_records(self.read("drop"))), 3)

    def test_extra(self):
        back = self.read("extra")
        self.assertEqual(len(self.new_records(back)), 5)
        self.assertEqual(len(set(r.slot for r in back.objects)), len(back.objects))

    def test_shift(self):
        new = sorted(self.new_records(self.read("shift")), key=lambda r: r.slot)
        self.assertAlmostEqual(new[-1].position[0], 3.0 + 0.05, delta=0.001)
        self.assertAlmostEqual(new[0].position[0], 0.0, delta=0.001)

    def test_physics(self):
        self.assertEqual(set(r.physics for r in self.new_records(self.read("physics"))), set([3]))

    def test_type(self):
        types = sorted(set(r.type_name for r in self.new_records(self.read("type"))))
        self.assertEqual(len(types), 2)
        self.assertIn("Block, 1x1", types)

    def test_touch_original(self):
        back = self.read("touch_original")
        original = [r for r in base.CANNED.objects if r.slot == 1][0]
        changed = [r for r in back.objects if r.slot == 1][0]
        self.assertNotEqual(changed, original)
        self.assertEqual(back.info.occupied, 9, "a replaced record, not an added one")
        self.assertEqual(len(back.objects), 9)

    def test_flavour(self):
        back = self.read("flavour")
        self.assertEqual(back.info.hash_flavour, "plain_le32/>")
        self.assertEqual(self.read(None).info.hash_flavour, base.CANNED.info.hash_flavour)


if __name__ == "__main__":
    unittest.main()
