"""G0 extra: Addon/provider.py and tests/stubs/stub_mvarlib.py (the cross-gate contract of SPEC section 11)."""
import dataclasses
import hashlib
import math
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "Addon"))
sys.path.insert(0, os.path.join(REPO, "tests", "stubs"))

import provider  # noqa: E402
import stub_mvarlib as stub  # noqa: E402
from mvarlib import api, tables  # noqa: E402


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


class TestProvider(unittest.TestCase):
    def tearDown(self):
        provider.set_provider(None)
        stub.reset()

    def test_required_names_are_exactly_the_api(self):
        self.assertEqual(tuple(api.__all__), provider.REQUIRED_NAMES)

    def test_default_is_the_api_module(self):
        provider.set_provider(None)
        self.assertIs(provider.get_provider(), api)
        self.assertEqual(provider.missing_names(api), [])

    def test_set_and_restore(self):
        previous = provider.set_provider(stub)
        self.assertIs(previous, api)
        self.assertIs(provider.get_provider(), stub)
        self.assertIs(provider.set_provider(None), stub)
        self.assertIs(provider.get_provider(), api)

    def test_incomplete_provider_is_rejected_and_not_installed(self):
        partial = types.SimpleNamespace(load_map_variant=lambda *a, **k: None)
        with self.assertRaises(TypeError) as cm:
            provider.set_provider(partial)
        self.assertIn("export_map_variant", str(cm.exception))
        self.assertIs(provider.get_provider(), api)

    def test_glue_pattern_builds_objects_through_the_provider(self):
        provider.set_provider(stub)
        P = provider.get_provider()
        obj = P.ExportObject(name="1 - Block, 1x1", slot=1, token_raw=b"\x01", token_bits=9)
        result = P.export_map_variant(b"TEMPLATE", [obj], P.ExportOptions())
        self.assertTrue(result.ok)
        self.assertEqual(stub.LAST_EXPORT[0], b"TEMPLATE")
        with self.assertRaises(P.MvarError):
            stub.NEXT_LOAD_ERROR = P.FormatError("This file is not a Halo BLF file.")
            P.load_map_variant(b"x")

    def test_provider_module_does_not_import_bpy(self):
        import ast
        with open(os.path.join(REPO, "Addon", "provider.py"), "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in tree.body:                         # module level only: nothing may run on import
            self.assertNotIsInstance(node, (ast.Import,), "provider.py imports at module level")
            if isinstance(node, ast.ImportFrom):
                self.fail("provider.py imports at module level: %s" % node.module)


class TestStubSurface(unittest.TestCase):
    def tearDown(self):
        stub.reset()

    def test_exposes_every_api_name_and_does_not_redefine_the_types(self):
        for name in api.__all__:
            self.assertTrue(hasattr(stub, name), name)
        for name in api.__all__:
            if name not in ("load_map_variant", "export_map_variant"):
                self.assertIs(getattr(stub, name), getattr(api, name), name)
        self.assertIsNot(stub.load_map_variant, api.load_map_variant)
        self.assertIsNot(stub.export_map_variant, api.export_map_variant)
        self.assertTrue(stub.IS_STUB)
        self.assertEqual(provider.missing_names(stub), [])

    def test_helpers_are_the_real_g0_functions(self):
        self.assertEqual(stub.map_name_for_id(3006), "Forge World")
        self.assertEqual(stub.stock_object_names("Boneyard"), tables.stock_object_names("Boneyard"))
        self.assertEqual(stub.palette_tree(), tables.palette_tree())     # G4 replaced the empty G0 tree by the generated one


class TestCannedData(unittest.TestCase):
    def tearDown(self):
        stub.reset()

    def test_canned_forge_world_as_specified(self):
        info = stub.CANNED.info
        self.assertEqual((info.map_id, info.map_name, info.is_stock_map, info.quota_count, info.version),
                         (3006, "Forge World", True, 80, 31))
        self.assertEqual(info.bounds, (-240.0, 240.0, -345.0, 345.0, -70.0, 70.0))
        self.assertEqual(info.labels, ["SCALE", "Kill Boundary", "Spawn"])
        self.assertEqual(info.hypothesis, {"type19": "undetermined", "axis_bits": [20, 21, 19], "guid": False,
                                           "length_class": "ceil_end"})
        objs = stub.CANNED.objects
        self.assertEqual([o.slot for o in objs], [1, 2, 5, 9, 11])
        self.assertEqual(info.occupied, 5)
        by_slot = dict((o.slot, o) for o in objs)
        self.assertEqual(by_slot[1].type_name, "Block, 1x1")
        self.assertEqual(by_slot[1].orientation_kind, "vertical")
        self.assertEqual(by_slot[1].forward, (1.0, 0.0, 0.0))        # yaw 0
        a = by_slot[2]
        self.assertEqual((a.type_name, a.folder, a.item, a.cached_type, a.other_a), ("Assault Rifle", 0, 0, 1, 3))
        k = by_slot[5]
        self.assertEqual((k.type_name, k.shape, k.label_index, k.cached_type), ("Kill Boundary", 3, 1, 26))
        self.assertEqual(by_slot[9].orientation_kind, "tilted")
        self.assertEqual(by_slot[9].type_name, "Block, 1x1")
        self.assertEqual(by_slot[11].type_name, "Initial Loadout Camera")

    def test_records_are_consistent_with_the_real_tables(self):
        for result in [stub.CANNED, stub.CANNED_BONEYARD, stub.CANNED_EXTREMES, stub.CANNED_PLACEMENT_ALL]:
            map_name = result.info.map_name
            xmin, xmax, ymin, ymax, zmin, zmax = result.info.bounds
            self.assertEqual(result.info.occupied, len(result.objects))
            for o in result.objects:
                self.assertEqual(o.type_id, (o.folder << 8) | o.item)
                self.assertEqual(tables.object_name_for_id(map_name, o.type_id), o.type_name)
                self.assertTrue(o.stock)
                self.assertLess(o.folder, result.info.quota_count)
                self.assertTrue(xmin <= o.position[0] < xmax and ymin <= o.position[1] < ymax
                                and zmin <= o.position[2] < zmax, (o.slot, o.position))
                self.assertAlmostEqual(math.sqrt(dot(o.forward, o.forward)), 1.0, places=9)
                self.assertAlmostEqual(math.sqrt(dot(o.up, o.up)), 1.0, places=9)
                self.assertAlmostEqual(dot(o.forward, o.up), 0.0, places=9)
                self.assertEqual(o.up == (0.0, 0.0, 1.0), o.orientation_kind == "vertical")
                self.assertLessEqual(o.raw_bits, 235)
                self.assertEqual(len(o.raw), (o.raw_bits + 7) // 8)

    def test_every_record_has_a_distinct_token(self):
        for result in [stub.CANNED, stub.CANNED_BONEYARD, stub.CANNED_EXTREMES, stub.CANNED_PLACEMENT_ALL]:
            tokens = [(o.raw, o.raw_bits) for o in result.objects]
            self.assertEqual(len(tokens), len(set(tokens)))
            self.assertEqual(len(set(o.raw for o in result.objects)), len(result.objects))
        self.assertEqual(len(set(o.raw_bits for o in stub.CANNED.objects)), 5)

    def test_by_map_and_the_per_map_filter(self):
        self.assertEqual(sorted(stub.CANNED_BY_MAP), [1080, 3006])
        self.assertIs(stub.CANNED_BY_MAP[3006], stub.CANNED)
        boneyard = stub.CANNED_BY_MAP[1080]
        self.assertEqual(boneyard.info.map_name, "Boneyard")
        self.assertNotIn("Block, 1x1", tables.stock_object_names("Boneyard"))
        self.assertIn("Block, 1x1", tables.stock_object_names("Forge World"))
        for o in boneyard.objects:
            self.assertIn(o.type_name, tables.stock_object_names("Boneyard"))

    def test_extremes(self):
        objs = stub.CANNED_EXTREMES.objects
        self.assertTrue(any(o.shape == 1 and o.width == 200.0 for o in objs))
        self.assertTrue(any(o.spawn_sequence == -128 for o in objs))
        self.assertTrue(any(o.spawn_sequence == 127 for o in objs))
        self.assertTrue(any(o.team == -1 for o in objs))
        self.assertTrue(any(o.placement == 0xFF for o in objs))
        self.assertTrue(any(o.label_index == -1 for o in objs))
        self.assertTrue(any(o.parent_slot >= 0 for o in objs))
        slots = set(o.slot for o in objs)
        for o in objs:
            if o.parent_slot >= 0:
                self.assertIn(o.parent_slot, slots)

    def test_placement_all_has_one_object_per_byte(self):
        objs = stub.CANNED_PLACEMENT_ALL.objects
        self.assertEqual(len(objs), 256)
        self.assertEqual(sorted(o.placement for o in objs), list(range(256)))
        for o in objs:
            self.assertEqual(o.physics, (o.placement >> 6) & 3)
            self.assertEqual(o.symmetry, (o.placement >> 2) & 3)
            self.assertEqual(o.place_at_start, not (o.placement & 0x10))
            self.assertEqual(o.game_specific, bool(o.placement & 0x20))
        self.assertIn(2, set(o.physics for o in objs))             # the glue must cope with the unused value


class TestLoad(unittest.TestCase):
    def tearDown(self):
        stub.reset()

    def test_load_fills_the_hash_and_returns_a_copy(self):
        data = b"any bytes at all"
        r1 = stub.load_map_variant(data, "canned.mvar")
        self.assertEqual(r1.info.template_sha256, hashlib.sha256(data).hexdigest())
        self.assertEqual(stub.LAST_LOAD, (data, "canned.mvar", None))
        r1.objects.clear()
        r1.info.labels.append("mutated")
        r2 = stub.load_map_variant(b"other")
        self.assertEqual(len(r2.objects), 5)
        self.assertEqual(r2.info.labels, ["SCALE", "Kill Boundary", "Spawn"])
        self.assertEqual(stub.CANNED.info.template_sha256, "")
        self.assertNotEqual(r1.info.template_sha256, r2.info.template_sha256)

    def test_next_load_is_returned_once(self):
        stub.NEXT_LOAD = stub.CANNED_EXTREMES
        self.assertEqual(stub.load_map_variant(b"a").info.title, "Canned extremes")
        self.assertIsNone(stub.NEXT_LOAD)
        self.assertEqual(stub.load_map_variant(b"a").info.title, "Canned Forge World")
        stub.NEXT_LOAD = stub.CANNED_BY_MAP[1080]
        self.assertEqual(stub.load_map_variant(b"a").info.map_name, "Boneyard")

    def test_next_load_error_is_raised_once(self):
        stub.NEXT_LOAD_ERROR = api.DesyncError("none of the layouts fits")
        with self.assertRaises(api.MvarError):
            stub.load_map_variant(b"a")
        self.assertIsNone(stub.NEXT_LOAD_ERROR)
        self.assertEqual(stub.load_map_variant(b"a").info.map_id, 3006)


class TestExport(unittest.TestCase):
    def tearDown(self):
        stub.reset()

    def _objects(self):
        return [api.ExportObject(name="a", slot=1, token_raw=b"x", token_bits=8),
                api.ExportObject(name="b", slot=None, token_raw=None, token_bits=None)]

    def test_default_records_and_returns_the_template(self):
        opts = api.ExportOptions(allow_unverified_rotation=True)
        objs = self._objects()
        result = stub.export_map_variant(b"TEMPLATE", objs, opts)
        self.assertTrue(result.ok)
        self.assertEqual(result.data, b"TEMPLATE")
        self.assertEqual([(d.kind, d.slot, d.name) for d in result.diff], [("kept", 1, "a"), ("added", None, "b")])
        self.assertEqual(result.errors, [])
        self.assertEqual(result.stats["mode"], "passthrough")
        self.assertEqual(result.stats["capacity_bits"], 229376)
        template, recorded, options = stub.LAST_EXPORT
        self.assertEqual(template, b"TEMPLATE")
        self.assertEqual([o.name for o in recorded], ["a", "b"])
        self.assertIs(options, opts)

    def test_the_stub_accepts_and_records_the_quota_option_of_freeze_v2(self):
        """Decision D11: ExportOptions.raise_quota_max reaches the stub unchanged (it imports the dataclass from api.py)."""
        opts = api.ExportOptions(raise_quota_max=True, allow_unverified_rotation=True)
        stub.export_map_variant(b"TEMPLATE", self._objects(), opts)
        self.assertTrue(stub.LAST_EXPORT[2].raise_quota_max)
        self.assertIs(stub.ExportOptions, api.ExportOptions)
        stub.export_map_variant(b"TEMPLATE", self._objects(), api.ExportOptions())
        self.assertFalse(stub.LAST_EXPORT[2].raise_quota_max)

    def test_preset_refusal_is_returned_once_and_data_is_none(self):
        issue = api.Issue("E_TOO_MANY", "error", "651 objects would be written; the limit is 650.")
        stub.preset_refusal(issue)
        result = stub.export_map_variant(b"T", self._objects(), api.ExportOptions())
        self.assertFalse(result.ok)
        self.assertIsNone(result.data)
        self.assertEqual(result.errors, [issue])
        self.assertTrue(stub.export_map_variant(b"T", [], api.ExportOptions()).ok)

    def test_next_export_accepts_any_export_result(self):
        custom = api.ExportResult(ok=True, data=b"CUSTOM", diff=[], errors=[],
                                  warnings=[api.Issue("W_HIDDEN_EXPORTED", "warning", "1 hidden object(s) were exported.")],
                                  stats={})
        stub.NEXT_EXPORT = custom
        self.assertIs(stub.export_map_variant(b"T", [], api.ExportOptions()), custom)
        self.assertIsNone(stub.NEXT_EXPORT)

    def test_reset_clears_every_control(self):
        stub.export_map_variant(b"T", [], api.ExportOptions())
        stub.load_map_variant(b"T")
        stub.NEXT_EXPORT = stub.NEXT_LOAD = stub.NEXT_LOAD_ERROR = object()
        stub.reset()
        for name in ("LAST_EXPORT", "NEXT_EXPORT", "NEXT_LOAD_ERROR", "NEXT_LOAD", "LAST_LOAD"):
            self.assertIsNone(getattr(stub, name), name)

    def test_stub_does_not_mutate_the_canned_dataclasses(self):
        frozen_before = dataclasses.asdict(stub.CANNED.objects[0])
        stub.load_map_variant(b"x")
        self.assertEqual(dataclasses.asdict(stub.CANNED.objects[0]), frozen_before)


if __name__ == "__main__":
    unittest.main()
