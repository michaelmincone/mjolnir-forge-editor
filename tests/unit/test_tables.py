"""G0 extra: tables.py behaviour (maps, stock objects, hints, palette tree) on the committed data."""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(REPO, "Addon", "mvarlib", "data")
sys.path.insert(0, os.path.join(REPO, "Addon"))

from mvarlib import tables  # noqa: E402


class TestMaps(unittest.TestCase):
    def test_twenty_stock_maps_by_id_and_name(self):
        maps = tables.maps()
        self.assertEqual(len(maps), 20)
        self.assertEqual([m["id"] for m in maps], sorted(m["id"] for m in maps))
        for m in maps:
            self.assertEqual(tables.map_name_for_id(m["id"]), m["name"])
            self.assertEqual(tables.map_id_for_name(m["name"]), m["id"])
            self.assertTrue(m["source"])
        self.assertEqual(tables.stock_map_names()[0], "Sword Base")
        self.assertEqual(tables.stock_map_names()[-1], "Solitary")

    def test_non_stock_and_odd_ids_give_none(self):
        for bad in (0, 1, 1001, 1056, 5005, 7000, 0xFFFFFFFF, -1, None, "3006", 3006.5, (3006,), [3006]):
            self.assertIsNone(tables.map_name_for_id(bad), repr(bad))
        for bad in ("", "Creep's Forge World", None, 3006, ["Forge World"]):
            self.assertIsNone(tables.map_id_for_name(bad), repr(bad))

    def test_returned_structures_are_copies(self):
        maps = tables.maps()
        maps[0]["name"] = "changed"
        maps.append({})
        self.assertEqual(tables.maps()[0]["name"], "Sword Base")
        self.assertEqual(len(tables.maps()), 20)


class TestStockObjects(unittest.TestCase):
    def test_names_in_id_order_and_unique_per_map(self):
        for name in tables.stock_map_names():
            rows = tables.stock_objects(name)
            self.assertTrue(rows, name)
            ids = [r[0] for r in rows]
            self.assertEqual(ids, sorted(ids), name)
            names = tables.stock_object_names(name)
            self.assertEqual(len(names), len(set(names)), name)
            self.assertEqual(names, [r[2] for r in rows])

    def test_lookups_both_ways(self):
        self.assertEqual(tables.object_name_for_id("Forge World", 0x4600), "Block, 1x1")
        self.assertEqual(tables.object_id_for_name("Forge World", "Block, 1x1"), 0x4600)
        self.assertEqual(tables.internal_name_for_id("Forge World", 0x4600), "block_1x1")
        self.assertTrue(tables.is_stock_object("Forge World", 0x4600))
        self.assertTrue(tables.is_stock_object("Forge World", 0x4601))               # "Block, 1x1, Flat"
        self.assertFalse(tables.is_stock_object("Forge World", 0xFFFF))
        # the same id means another object on another map; Boneyard has no "Block, 1x1" at all
        self.assertEqual(tables.object_name_for_id("Boneyard", 0x4600), "Block, 2x2x2, Invisible")
        self.assertIsNone(tables.object_id_for_name("Boneyard", "Block, 1x1"))
        # The global duplicate display name "Sprint": the same id on every map, but two internal types
        # (sprint_spartan on some maps, arm_sprint on others); lookups resolve per map.
        internal = {}
        for map_name in tables.stock_map_names():
            type_id = tables.object_id_for_name(map_name, "Sprint")
            self.assertEqual(type_id, 0x1E00, map_name)
            internal[map_name] = tables.internal_name_for_id(map_name, type_id)
        self.assertEqual(set(internal.values()), {"sprint_spartan", "arm_sprint"})
        self.assertEqual(internal["Forge World"], "sprint_spartan")
        self.assertEqual(internal["Countdown"], "arm_sprint")

    def test_unknown_inputs_never_raise(self):
        self.assertEqual(tables.stock_object_names("Nowhere"), [])
        self.assertEqual(tables.stock_object_names(None), [])
        self.assertEqual(tables.stock_object_names(["Forge World"]), [])
        self.assertIsNone(tables.object_name_for_id("Nowhere", 0))
        self.assertIsNone(tables.object_id_for_name("Forge World", "No Such Object"))
        self.assertIsNone(tables.object_id_for_name("Forge World", ["x"]))
        self.assertFalse(tables.is_stock_object("Forge World", None))
        self.assertFalse(tables.is_stock_object("Forge World", [1]))
        self.assertEqual(tables.disputed_ids("Forge World"), [])
        self.assertEqual(tables.disputed_ids("Nowhere"), [])

    def test_item_fits_five_bits_and_folder_eight(self):
        for name in tables.stock_map_names():
            for type_id, _, _ in tables.stock_objects(name):
                self.assertLessEqual(type_id & 0xFF, 31)
                self.assertLessEqual(type_id >> 8, 255)

    def test_disputed_ids(self):
        self.assertEqual(tables.disputed_ids("Tempest"), [0x2800, 0x2801, 0x2802, 0x6100, 0x6101, 0x6102])
        self.assertEqual(tables.disputed_ids("Breakneck"), [0x2203, 0x2204])
        for name in ("Tempest", "Breakneck"):
            for i in tables.disputed_ids(name):
                self.assertTrue(tables.is_stock_object(name, i))

    def test_stock_objects_returns_a_copy(self):
        rows = tables.stock_objects("Forge World")
        rows.clear()
        self.assertEqual(len(tables.stock_objects("Forge World")), 348)


class TestHintsAndTree(unittest.TestCase):
    def test_cached_type_hints(self):
        hints = tables.cached_type_hints()
        self.assertEqual(hints["assumed_zero_groups"], ["Structure", "Scenery"])
        self.assertEqual(tables.assumed_zero_groups(), ["Structure", "Scenery"])
        for key, cls in hints["known_classes"].items():
            self.assertTrue(0 <= int(key) <= 31)
            self.assertIn("name", cls)
        self.assertEqual(hints["known_classes"]["1"]["extra_bits"], [8])
        self.assertEqual(hints["known_classes"]["13"]["extra_bits"], [5, 5])
        self.assertIsNone(hints["known_classes"]["19"]["extra_bits"])      # disputed (X5)
        hints["assumed_zero_groups"].append("Weapons")
        self.assertEqual(tables.assumed_zero_groups(), ["Structure", "Scenery"])

    def test_palette_tree_is_the_generated_tree_and_a_copy(self):
        """G0 shipped the empty tree ``{"groups": []}``; G4 replaced it with the tree generated from the object
        library by ``tools/gen_palette_tree.py`` (names only). The top level keeps the ``groups`` convention."""
        tree = tables.palette_tree()
        with open(os.path.join(DATA, "palette_tree.json"), "r", encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), tree)
        self.assertIsInstance(tree["groups"], list)
        self.assertTrue(tree["groups"], "the generated tree has groups")

        def leaves(node):
            found = list(node.get("leaves", []))
            for child in node.get("groups", []):
                found.extend(leaves(child))
            return found

        names = leaves(tree)
        self.assertEqual(len(names), 194, "the 194 palette leaves of the object library")
        self.assertEqual(len(set(names)), 194)
        tree["groups"].append({"name": "x"})
        tree["groups"][0]["name"] = "changed"
        again = tables.palette_tree()
        self.assertNotEqual(again["groups"][0]["name"], "changed", "palette_tree() returns a copy")
        self.assertEqual(len(again["groups"]), len(tree["groups"]) - 1)

    def test_data_files_load_lazily_and_reset(self):
        tables.reset_cache()
        self.assertEqual(tables._cache, {})
        tables.map_name_for_id(3006)
        self.assertIn("maps", tables._cache)
        tables.reset_cache()
        self.assertEqual(tables._cache, {})


if __name__ == "__main__":
    unittest.main()
