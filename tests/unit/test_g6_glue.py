"""Gate G6 extras that need no Blender: the oracle helpers of the headless suite and the small glue pieces added in G6.

* ``tests/blender/real_data.py`` is the oracle the end-to-end Blender tests judge a file with (independent walker, bit-diff,
  SHA-1 recipes). It is checked here against the independent builder's own golden files, so a wrong oracle cannot make the
  Blender tests agree with a wrong library: the position bits of golden edit E1 (W1 slot 1 moved by +1.0) are exactly the
  bits that differ between the builder's ``w1_minimal`` and ``w1_E1`` files, the quantiser reproduces cell 526,473, the
  plain_le32 recipe matches the fixture that carries it.
* ``provider.object_folder`` (the folder of a stock object on a map, used by the Add menu to leave out palette entries beyond
  the template's quota count) answers from the add-on's own tables whichever provider is active.
* static checks on ``io_ops.py``: the unverified quota option is ``SKIP_SAVE`` (never remembered, never pre-ticked), the write
  step has a catch-all after ``PathPolicyError`` and ``OSError`` (a ``ValueError`` from the writer is a FAILED report),
  and the new glue codes exist.
Standard library only, Python 3.9 and 3.13.
"""
import ast
import importlib.util
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ADDON = os.path.join(REPO, "Addon")
BLENDER_TESTS = os.path.join(REPO, "tests", "blender")


def load_real_data():
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True                  # keep tests/blender and tests/fixturebuilder free of __pycache__
    try:
        spec = importlib.util.spec_from_file_location("g6_real_data", os.path.join(BLENDER_TESTS, "real_data.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.modules()                             # loads the independent builder while bytecode is still off
    finally:
        sys.dont_write_bytecode = saved
    return module


rd = load_real_data()


class TestOracleAgainstTheBuildersGoldens(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w1 = rd.fixture("w1_minimal")
        cls.e1 = rd.fixture("w1_E1")
        cls.dec = rd.decode(cls.w1)

    def test_w1_is_the_file_of_appendix_c(self):
        import hashlib
        self.assertEqual(hashlib.sha256(self.w1).hexdigest(), "902d952fdce8b5830e53e96e0ad45926554e1a9e617f753f39bb58a5fd2344e4")
        self.assertEqual(len(self.w1), rd.REAL_PLAIN_SIZE)

    def test_the_position_bits_of_golden_edit_e1_are_the_bits_that_differ(self):
        # W1 slot 1 moves from x cell 524,288 to 526,473 (Appendix C.3)
        expected = rd.pos_bits_changed(self.dec, 1, [526473, 1048576, 262144])
        self.assertTrue(expected)
        self.assertEqual(rd.stream_diff(self.w1, self.e1), expected)
        lo, hi = rd.slot_span(self.dec, 1, "pos_x")
        self.assertEqual(hi - lo, 20)
        self.assertTrue(all(lo <= bit < hi for bit in expected))
        changed = rd.changed_bytes(self.w1, self.e1)
        outside = rd.bytes_outside_stream(changed)
        self.assertTrue(set(outside) <= set(range(rd.HASH_AT, rd.HASH_AT + 20)), "outside the stream only the SHA-1 changes")
        self.assertEqual(rd.stored_length(self.w1), rd.stored_length(self.e1))

    def test_the_quantiser_reproduces_the_cell_of_e1(self):
        self.assertEqual(rd.cell_for(1.0002288818359375, 20, -240.0, 240.0), 526473)
        self.assertEqual(rd.cell_for(0.0002288818359375, 20, -240.0, 240.0), 524288)
        self.assertAlmostEqual(rd.cell_centre(524288, 20, -240.0, 240.0), 0.0002288818359375, places=12)

    def test_the_bit_diff_is_empty_for_an_equal_file_and_slots_equal_sees_one_changed_slot(self):
        self.assertEqual(rd.stream_diff(self.w1, self.w1), [])
        self.assertEqual(rd.pos_bits_changed(self.dec, 1, list(self.dec["slots"][1]["pos"])), [])
        after = rd.decode(self.e1)
        self.assertEqual(rd.slots_equal(self.dec, after), [1])
        self.assertEqual(rd.slots_equal(self.dec, after, ignore=(1,)), [])
        self.assertEqual(rd.fields_differing(self.dec["slots"][1], after["slots"][1]), ["pos"])

    def test_the_plain_le32_recipe_matches_the_fixture_that_carries_it(self):
        plain = rd.fixture("plain_le32")
        self.assertEqual(rd.stored_hash(plain), rd.sha1_plain_le32(plain))
        self.assertNotEqual(rd.stored_hash(self.w1), rd.sha1_plain_le32(self.w1), "W1 is salted_be32")
        self.assertEqual(rd.read_result(plain)["flavour"], {"length_endian": ">", "recipe": "plain_le32"})
        self.assertEqual(rd.read_result(self.w1)["flavour"], {"length_endian": ">", "recipe": "salted_be32"})
        self.assertEqual(rd.digest("salted_be32", self.w1), rd.stored_hash(self.w1))

    def test_a_derived_spec_builds_and_is_independent_of_the_committed_one(self):
        spec = rd.w1_spec("g6_probe")
        spec["slots"][0]["pos"][0] += 1
        changed = rd.build_spec(spec)
        self.assertNotEqual(changed, self.w1)
        self.assertEqual(rd.fixture("w1_minimal"), self.w1, "the committed fixture is untouched by editing a derived copy")

    def test_the_shared_cast_fixture_is_accepted_by_the_walker(self):
        data = rd.build_spec(rd.cast_spec("g6_cast"))
        decoded = rd.decode(data)
        self.assertEqual(sorted(decoded["slots"]), [1, 2, 5, 9, 11, 20, 21, 22, 23])
        self.assertEqual(decoded["slots"][21]["cached_type"], 12)
        self.assertEqual(decoded["slots"][9]["up_global"], 0)

    def test_the_f32_helper_rounds_like_blender_stores_a_location(self):
        self.assertEqual(rd.f32(1.0), 1.0)
        self.assertNotEqual(rd.f32(0.1), 0.1)
        self.assertAlmostEqual(rd.f32(0.1), 0.1, places=7)

    @unittest.skipUnless(rd.real_available(), "NOTICE: the real map variant is absent; the real-file oracle checks are skipped")
    def test_the_real_file_is_read_in_place_and_decodes_to_610_slots(self):
        before = rd.file_fingerprint(rd.real_mvar_path())
        data = rd.real_bytes()
        decoded = rd.decode(data)
        self.assertEqual(len(decoded["slots"]), rd.REAL_OBJECTS)
        self.assertEqual(rd.stored_hash(data), rd.sha1_plain_le32(data))
        self.assertEqual(rd.stored_length(data), 13311)
        self.assertEqual(rd.file_fingerprint(rd.real_mvar_path()), before, "reading changes nothing")
        self.assertAlmostEqual(rd.REAL_CELL, 40000.0 / (1 << 23))


class TestProviderObjectFolder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if ADDON not in sys.path:
            sys.path.insert(0, ADDON)
        spec = importlib.util.spec_from_file_location("g6_provider", os.path.join(ADDON, "provider.py"))
        cls.provider = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.provider)

    def tearDown(self):
        self.provider.set_provider(None)

    def test_folders_are_per_map(self):
        p = self.provider
        self.assertEqual(p.object_folder("Forge World", "Block, 1x1"), 70)
        self.assertEqual(p.object_folder("Breakneck", "Block, 1x1"), 63)
        self.assertEqual(p.object_folder("Forge World", "Sprint"), 30)
        self.assertEqual(p.object_folder("Breakneck", "Door"), 116)
        self.assertEqual(p.object_folder("Forge World", "Door (MCC)"), 136)

    def test_unknown_names_and_maps_have_no_folder(self):
        p = self.provider
        self.assertIsNone(p.object_folder("Forge World", "Nonsense Thing"))
        self.assertIsNone(p.object_folder("No Such Map", "Block, 1x1"))
        self.assertIsNone(p.object_folder("", ""))
        self.assertIsNone(p.object_folder("Forge World", None))

    def test_it_is_not_part_of_the_frozen_interface(self):
        self.assertNotIn("object_folder", self.provider.REQUIRED_NAMES)
        self.assertNotIn("object_id_for_name", self.provider.REQUIRED_NAMES)

    def test_a_provider_may_answer_itself(self):
        from mvarlib import api
        names = dict((n, getattr(api, n)) for n in self.provider.REQUIRED_NAMES)
        names["object_id_for_name"] = lambda map_name, name: 0x2A07
        custom = types.SimpleNamespace(**names)
        self.provider.set_provider(custom)
        self.assertEqual(self.provider.object_folder("Anything", "Whatever"), 0x2A)

    def test_the_default_answer_does_not_need_the_stub_to_know_the_tables(self):
        from mvarlib import api
        names = dict((n, getattr(api, n)) for n in self.provider.REQUIRED_NAMES)
        self.provider.set_provider(types.SimpleNamespace(**names))        # carries the names of the api, no object_id_for_name
        self.assertEqual(self.provider.object_folder("Forge World", "Block, 1x1"), 70)


class TestIoOpsStatic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ADDON, "io_ops.py"), "r", encoding="utf-8") as fh:
            cls.source = fh.read()
        cls.tree = ast.parse(cls.source)

    def annotated(self, name):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
                return node
        self.fail("no annotated attribute %s" % name)

    def test_the_unverified_quota_option_is_never_remembered(self):
        call = self.annotated("raise_quota_max").annotation
        options = [kw.value for kw in call.keywords if kw.arg == "options"]
        self.assertEqual(len(options), 1, "raise_quota_max needs options={'SKIP_SAVE'}")
        self.assertEqual(ast.literal_eval(options[0]), {"SKIP_SAVE"})
        default = [ast.literal_eval(kw.value) for kw in call.keywords if kw.arg == "default"]
        self.assertEqual(default, [False])

    def test_the_other_export_options_are_still_remembered_normally(self):
        for name in ("force_reencode", "fsm_policy", "hash_policy"):
            call = self.annotated(name).annotation
            self.assertEqual([kw for kw in call.keywords if kw.arg == "options"], [], name)

    def test_the_write_step_catches_everything_after_the_two_known_errors(self):
        execute = None
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef) and node.name == "EXPORT_OT_mjolnir_mvar":
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "execute":
                        execute = item
        self.assertIsNotNone(execute)
        handlers = []
        for node in ast.walk(execute):
            if isinstance(node, ast.Try) and any(isinstance(n, ast.Attribute) and n.attr == "write_atomic"
                                                 for stmt in node.body for n in ast.walk(stmt)):
                handlers = [ast.dump(h.type) if h.type is not None else "bare" for h in node.handlers]
        self.assertEqual(len(handlers), 3, handlers)
        self.assertIn("PathPolicyError", handlers[0])
        self.assertIn("OSError", handlers[1])
        self.assertIn("'Exception'", handlers[2], "a ValueError from the writer must be a FAILED report, not a traceback")

    def test_the_glue_codes_added_in_g6_exist(self):
        for code in ("E_FAILED_SLOT_NOT_STOCK", "W_FAILED_SLOT_KEPT", "E_WRITE_FAILED", "E_INTERNAL"):
            self.assertIn('"%s"' % code, self.source)

    def test_the_import_console_is_bounded_by_constants(self):
        values = {}
        for node in self.tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant):
                values[node.targets[0].id] = node.value.value
        self.assertEqual(values["MAX_IMPORT_TRACEBACKS"], 3)
        self.assertEqual(values["MAX_IMPORT_KINDS"], 5)
        self.assertEqual(values["MAX_CONSOLE_WARNINGS"], 20)
        self.assertLessEqual(values["MAX_LISTED_WARNINGS"], 5)


if __name__ == "__main__":
    unittest.main()
