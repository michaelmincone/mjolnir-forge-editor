"""U-15 (SPEC 9.3): the committed stock tables equal what Addon/objects.py says.

``data/stock_objects.json`` must equal the tables parsed with ``ast`` (never executed) from
``Addon/objects.py``; there are 20 maps with the ids of ReachVariantTool ``page_map_perms.cpp``;
the committed JSON must be byte-identical to what ``tools/gen_stock_tables.py`` generates;
palette tree names (none in G0: the tree is empty) must resolve in the Forge World table.

The ``ast`` parsing below is written independently of the generator on purpose, so a slip in one
cannot hide in the other.
"""
import ast
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(REPO, "Addon", "mvarlib", "data")
sys.path.insert(0, os.path.join(REPO, "Addon"))

from mvarlib import tables  # noqa: E402

EXPECTED_MAP_IDS = {
    "Sword Base": 1000, "Countdown": 1020, "Boardwalk": 1035, "Zealot": 1040, "Powerhouse": 1055,
    "Boneyard": 1080, "Reflection": 1150, "Spire": 1200, "Condemned": 1500, "Highlands": 1510,
    "Anchor 9": 2001, "Breakpoint": 2002, "Tempest": 2004, "Forge World": 3006, "Penance": 10010,
    "Battle Canyon": 10020, "Ridgeline": 10030, "Breakneck": 10050, "High Noon": 10060, "Solitary": 10070,
}
EXPECTED_COUNTS = {                       # SPEC 7.1 "Objects per map"
    "Forge World": 348, "Boardwalk": 121, "Boneyard": 96, "Countdown": 121, "Powerhouse": 123, "Reflection": 117,
    "Spire": 100, "Sword Base": 116, "Zealot": 109, "Anchor 9": 102, "Breakpoint": 119, "Tempest": 347,
    "Condemned": 125, "Highlands": 116, "Battle Canyon": 161, "Penance": 112, "Ridgeline": 232, "Solitary": 197,
    "High Noon": 209, "Breakneck": 218,
}


def parse_objects_py():
    """{map: {id: internal}} and {internal: display} read from Addon/objects.py without running it."""
    with open(os.path.join(REPO, "Addon", "objects.py"), "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    assigns = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            assigns[node.targets[0].id] = node.value
    per_map = {}
    for key, value in zip(assigns["map_object_types"].keys, assigns["map_object_types"].values):
        per_map[ast.literal_eval(key)] = ast.literal_eval(value.args[0])
    names = ast.literal_eval(assigns["type_to_name"].args[0])
    return per_map, names


def load_generator():
    spec = importlib.util.spec_from_file_location("gen_stock_tables_under_test", os.path.join(REPO, "tools", "gen_stock_tables.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestStockTablesMatchObjectsPy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.per_map, cls.names = parse_objects_py()
        with open(os.path.join(DATA, "stock_objects.json"), "r", encoding="utf-8") as fh:
            cls.stock = json.load(fh)

    def test_twenty_maps_and_counts(self):
        self.assertEqual(len(self.per_map), 20)
        self.assertEqual(list(self.stock["maps"]), list(self.per_map))
        self.assertEqual(dict((k, len(v)) for k, v in self.stock["maps"].items()), EXPECTED_COUNTS)

    def test_every_entry_equals_objects_py(self):
        for map_name, table in self.per_map.items():
            expect = [[i, table[i], self.names.get(table[i], table[i])] for i in sorted(table)]
            self.assertEqual(self.stock["maps"][map_name], expect, map_name)

    def test_map_ids_and_names(self):
        with open(os.path.join(DATA, "maps.json"), "r", encoding="utf-8") as fh:
            maps = json.load(fh)
        self.assertEqual(dict((m["name"], m["id"]) for m in maps["maps"]), EXPECTED_MAP_IDS)
        self.assertEqual(sorted(EXPECTED_MAP_IDS), sorted(self.per_map))     # the map names of objects.py
        self.assertEqual([m["id"] for m in maps["maps"]], sorted(EXPECTED_MAP_IDS.values()))
        for m in maps["maps"]:
            self.assertTrue(m["source"])
        not_stock = [n["id"] for n in maps["not_stock_ids"]]
        self.assertEqual(not_stock, [1, 1001, 1056])
        for map_id in not_stock:
            self.assertIsNone(tables.map_name_for_id(map_id))
        for name, map_id in EXPECTED_MAP_IDS.items():
            self.assertEqual(tables.map_name_for_id(map_id), name)

    def test_disputed_ids_are_the_eight(self):
        self.assertEqual(self.stock["disputed"], {"Breakneck": [0x2203, 0x2204],
                                                  "Tempest": [0x2800, 0x2801, 0x2802, 0x6100, 0x6101, 0x6102]})

    def test_golden_ids_g_id_1_to_3(self):
        # G-ID-1: Tempest 0x4708 = folder 71, item 8, wall_coliseum, "Wall, Coliseum"
        row = dict((r[0], r) for r in self.stock["maps"]["Tempest"])[0x4708]
        self.assertEqual((0x4708 >> 8, 0x4708 & 0xFF, row[1], row[2]), (71, 8, "wall_coliseum", "Wall, Coliseum"))
        # G-ID-2: "Block, 1x1" per map
        self.assertEqual(tables.object_id_for_name("Forge World", "Block, 1x1"), 0x4600)
        self.assertEqual(tables.object_id_for_name("Tempest", "Block, 1x1"), 0x4300)
        self.assertEqual(tables.object_id_for_name("Battle Canyon", "Block, 1x1"), 0x3900)
        # G-ID-3: Forge World boundaries and location name
        self.assertEqual(tables.object_name_for_id("Forge World", 0x3D00), "Kill Boundary")
        self.assertEqual(tables.object_name_for_id("Forge World", 0x3C00), "Safe Boundary")
        self.assertEqual(tables.object_name_for_id("Forge World", 0x9000), "Location Name")

    def test_display_names_unique_per_map(self):
        for map_name, rows in self.stock["maps"].items():
            names = [r[2] for r in rows]
            self.assertEqual(len(names), len(set(names)), map_name)
            ids = [r[0] for r in rows]
            self.assertEqual(len(ids), len(set(ids)), map_name)


class TestCommittedFilesAreGeneratorOutput(unittest.TestCase):
    def test_byte_identical_to_a_fresh_generation(self):
        generated = load_generator().build_outputs()
        self.assertEqual(sorted(generated), ["maps.json", "stock_objects.json"])
        for name, data in generated.items():
            with open(os.path.join(DATA, name), "rb") as fh:
                self.assertEqual(fh.read(), data, "%s differs: run python3 -I tools/gen_stock_tables.py" % name)

    def test_generation_is_deterministic(self):
        gen = load_generator()
        self.assertEqual(gen.build_outputs(), gen.build_outputs())

    def test_data_files_are_ascii_lf_json(self):
        for name in ("maps.json", "stock_objects.json", "cached_type_hints.json", "palette_tree.json"):
            with open(os.path.join(DATA, name), "rb") as fh:
                raw = fh.read()
            raw.decode("ascii")
            self.assertNotIn(b"\r", raw, name)
            self.assertTrue(raw.endswith(b"\n"), name)
            json.loads(raw.decode("ascii"))


MINI_OBJECTS = """\
from TwoWayDict import TwoWayDict

map_object_types = {
    "Alpha" : TwoWayDict({0: 'rifle', 256: 'block'}),
    "Beta"  : TwoWayDict({0: 'rifle', 513: 'wall'}),
}
type_to_name = TwoWayDict({
    'rifle' : "Rifle",
    'block' : "Block",
    'wall'  : "Wall",
})
print("this must never run")
"""


class TestGeneratorBehaviour(unittest.TestCase):
    def setUp(self):
        self.gen = load_generator()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as fh:
            fh.write(text)
        return path

    def test_objects_py_is_parsed_not_executed_and_order_is_kept(self):
        path = self.write("objects.py", MINI_OBJECTS)
        maps, names = self.gen.parse_objects_py(path)
        self.assertEqual(list(maps), ["Alpha", "Beta"])
        self.assertEqual(maps["Beta"], [(0, "rifle"), (513, "wall")])
        self.assertEqual(names["wall"], "Wall")

    def test_duplicate_keys_in_the_literal_are_refused(self):
        path = self.write("objects.py", MINI_OBJECTS.replace("{0: 'rifle', 256: 'block'}", "{0: 'rifle', 0: 'block'}"))
        with self.assertRaises(self.gen.GenError):
            self.gen.parse_objects_py(path)

    def test_missing_assignments_and_non_literals_are_refused(self):
        with self.assertRaises(self.gen.GenError):
            self.gen.parse_objects_py(self.write("a.py", "x = 1\n"))
        with self.assertRaises(self.gen.GenError):
            self.gen.parse_objects_py(self.write("b.py", MINI_OBJECTS.replace("TwoWayDict({0: 'rifle', 256: 'block'})", "dict()")))

    def test_build_tables_validates_items_and_names(self):
        saved = (self.gen.STOCK_MAPS, self.gen.DISPUTED)
        try:
            self.gen.STOCK_MAPS = [(1, "Alpha"), (2, "Beta")]
            self.gen.DISPUTED = {}
            maps, objects = self.gen.build_tables(self.write("objects.py", MINI_OBJECTS))
            self.assertEqual([m["name"] for m in maps], ["Alpha", "Beta"])
            self.assertEqual(objects["Beta"], [(0, "rifle", "Rifle"), (513, "wall", "Wall")])
            with self.assertRaises(self.gen.GenError):          # item 32 does not fit 5 bits
                self.gen.build_tables(self.write("o2.py", MINI_OBJECTS.replace("513: 'wall'", "544: 'wall'")))
            with self.assertRaises(self.gen.GenError):          # two ids with one display name on a map
                self.gen.build_tables(self.write("o3.py", MINI_OBJECTS.replace("'block' : \"Block\"", "'block' : \"Rifle\"")))
            with self.assertRaises(self.gen.GenError):          # map names must equal the RVT list
                self.gen.STOCK_MAPS = [(1, "Alpha"), (2, "Gamma")]
                self.gen.build_tables(self.write("o4.py", MINI_OBJECTS))
        finally:
            self.gen.STOCK_MAPS, self.gen.DISPUTED = saved

    def test_cli_writes_checks_and_exits(self):
        script = os.path.join(REPO, "tools", "gen_stock_tables.py")
        out = os.path.join(self.tmp, "out")
        os.makedirs(out)
        run = lambda *a: subprocess.run([sys.executable, "-I", script] + list(a), stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, universal_newlines=True)
        self.assertEqual(run("--out-dir", out, "--check").returncode, 1)            # nothing there yet
        done = run("--out-dir", out)
        self.assertEqual(done.returncode, 0, done.stdout)
        for name in ("maps.json", "stock_objects.json"):
            with open(os.path.join(out, name), "rb") as a, open(os.path.join(DATA, name), "rb") as b:
                self.assertEqual(a.read(), b.read(), name)
        self.assertEqual(run("--out-dir", out, "--check").returncode, 0)
        with open(os.path.join(out, "maps.json"), "ab") as fh:
            fh.write(b" ")
        self.assertEqual(run("--out-dir", out, "--check").returncode, 1)
        broken = self.write("objects.py", "x = 1\n")
        bad = run("--objects-py", broken, "--out-dir", out, "--check")
        self.assertEqual(bad.returncode, 2, bad.stdout)

    def test_cross_check_with_the_session_research_tables_when_present(self):
        research = os.environ.get("MJOLNIR_RESEARCH_TABLES")
        if not research or not os.path.isdir(research):
            self.skipTest("set MJOLNIR_RESEARCH_TABLES to the research/tables folder to re-run the cross-check "
                          "(done once in G0: see NOTES.md D7-2)")
        self.assertEqual(self.gen.cross_check_research(research), [])


class TestPaletteTreeResolvesInForgeWorld(unittest.TestCase):
    def test_every_leaf_name_is_a_forge_world_object(self):
        forge_world = set(tables.stock_object_names("Forge World"))
        tree = tables.palette_tree()
        self.assertIsInstance(tree.get("groups"), list)

        def leaves(node):
            for leaf in node.get("leaves", []):
                yield leaf["name"] if isinstance(leaf, dict) else leaf
            for child in node.get("groups", []):
                for name in leaves(child):
                    yield name

        for name in leaves(tree):
            self.assertIn(name, forge_world, "palette leaf %r is not a Forge World object" % name)


if __name__ == "__main__":
    unittest.main()
