"""G4 extra: ``Addon/state.py``, the only code that touches ``scene['mjolnir*']`` (SPEC 8.3), without Blender.

``state.py`` imports nothing from ``bpy`` or from the package, so it is loaded as a plain module and driven with a
dict standing in for the scene's custom properties. Checked: the keys and value types of 8.3 (no u32 stored as an
int, no mixed lists), the template checksum rules (E_NO_TEMPLATE / E_TEMPLATE_CORRUPT), and the label helpers that
turn raw file indices into enum identifiers (original case kept; ``SCALE`` found case-insensitively).
"""
import hashlib
import importlib.util
import os
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))


def load_state():
    spec = importlib.util.spec_from_file_location("g4_state", os.path.join(REPO, "Addon", "state.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


state = load_state()


def make_result(labels=("SCALE", "Kill Boundary", "Spawn"), present=None, map_id=3006, map_name="Forge World"):
    info = types.SimpleNamespace(
        map_id=map_id, map_name=map_name, bounds=(-240.0, 240.0, -345.0, 345.0, -70.0, 70.0), quota_count=80,
        version=31, occupied=5, labels=list(labels), label_present=list(present if present is not None else [True] * len(labels)),
        hash_flavour="salted_be32/>",
        hypothesis={"type19": "undetermined", "axis_bits": [20, 21, 19], "guid": False, "length_class": "ceil_end",
                    "big": 2 ** 40, "nothing": None, "mixed": ["a", 1], "nested": {"x": 1}},
    )
    return types.SimpleNamespace(info=info, objects=[])


class TestSetFromLoad(unittest.TestCase):
    def setUp(self):
        self.scene = {}
        self.data = bytes(range(256)) * 3 + b"\x00tail"
        state.set_from_load(self.scene, self.data, make_result(), "/maps/hr_forgeWorld_theCage.mvar", "1.0.0", "1.0.0")

    def test_template_is_a_top_level_bytes_value_with_its_checksum(self):
        self.assertEqual(self.scene[state.TEMPLATE_KEY], self.data)
        self.assertIsInstance(self.scene[state.TEMPLATE_KEY], bytes)
        st = state.get(self.scene)
        self.assertEqual(st["template_sha256"], hashlib.sha256(self.data).hexdigest())
        self.assertEqual(state.verify_template(self.scene), (True, ""))
        self.assertEqual(state.template_bytes(self.scene), self.data)

    def test_keys_and_types_of_the_spec(self):
        st = state.get(self.scene)
        self.assertEqual(sorted(st), sorted([
            "template_sha256", "source_name", "source_path", "map_id_hex", "map_name", "labels", "label_present", "bounds",
            "quota_count", "version", "occupied_at_import", "imported_slots", "failed_slots", "failed_nonstock",
            "hash_flavour", "hypothesis", "addon_version", "mvarlib_version"]))
        self.assertEqual(st["source_name"], "hr_forgeWorld_theCage.mvar")
        self.assertEqual(st["source_path"], "/maps/hr_forgeWorld_theCage.mvar")
        self.assertEqual(st["map_id_hex"], "0x00000BBE")
        self.assertEqual(st["map_name"], "Forge World")
        self.assertEqual(st["labels"], ["SCALE", "Kill Boundary", "Spawn"], "original case")
        self.assertEqual(st["label_present"], [1, 1, 1])
        self.assertEqual(st["bounds"], [-240.0, 240.0, -345.0, 345.0, -70.0, 70.0])
        self.assertEqual((st["quota_count"], st["version"], st["occupied_at_import"]), (80, 31, 5))
        self.assertEqual(st["imported_slots"], [])
        self.assertEqual(st["failed_slots"], [])
        self.assertEqual(st["failed_nonstock"], {})
        self.assertEqual((st["addon_version"], st["mvarlib_version"]), ("1.0.0", "1.0.0"))

    def test_nothing_u32_is_stored_as_an_int_and_no_list_is_mixed(self):
        st = state.get(self.scene)
        hyp = st["hypothesis"]
        self.assertEqual(hyp["big"], "0x%X" % (2 ** 40), "a value beyond 32 bits becomes a hex string")
        self.assertEqual(hyp["nothing"], "")
        self.assertEqual(hyp["mixed"], ["a", "1"], "str and int are never mixed in one list")
        self.assertEqual(hyp["nested"], {"x": 1})
        self.assertEqual(hyp["axis_bits"], [20, 21, 19])
        self.assertIs(hyp["guid"], False)

        def walk(value):
            if isinstance(value, dict):
                for v in value.values():
                    walk(v)
            elif isinstance(value, list):
                self.assertTrue(len(set(type(v) for v in value)) <= 1 or all(isinstance(v, (int, float)) for v in value))
                for v in value:
                    walk(v)
            elif isinstance(value, int) and not isinstance(value, bool):
                self.assertTrue(-2 ** 31 <= value < 2 ** 31, value)

        walk(st)

    def test_a_u32_map_id_is_a_hex_string(self):
        scene = {}
        state.set_from_load(scene, b"x", make_result(map_id=0xFFFFFFFF, map_name=None), "x.mvar")
        st = state.get(scene)
        self.assertEqual(st["map_id_hex"], "0xFFFFFFFF")
        self.assertEqual(st["map_name"], "")
        self.assertEqual(state.map_name(scene), "")

    def test_import_results_and_clear(self):
        state.set_import_results(self.scene, [1, 2, 5], [9])
        st = state.get(self.scene)
        self.assertEqual((st["imported_slots"], st["failed_slots"]), ([1, 2, 5], [9]))
        state.clear(self.scene)
        self.assertIsNone(state.get(self.scene))
        self.assertIsNone(state.template_bytes(self.scene))
        self.assertEqual(state.verify_template(self.scene), (False, "E_NO_TEMPLATE"))
        state.clear(self.scene)                          # clearing twice is harmless

    def test_checksum_mismatch_and_missing_template(self):
        self.scene[state.TEMPLATE_KEY] = self.data[:-1] + b"?"
        self.assertEqual(state.verify_template(self.scene), (False, "E_TEMPLATE_CORRUPT"))
        del self.scene[state.TEMPLATE_KEY]
        self.assertEqual(state.verify_template(self.scene), (False, "E_NO_TEMPLATE"))
        self.assertEqual(state.verify_template({}), (False, "E_NO_TEMPLATE"))

    def test_has_map_is_the_cheap_presence_test(self):
        self.assertTrue(state.has_map(self.scene))
        self.assertFalse(state.has_map({}))
        self.assertFalse(state.has_map(None))
        state.clear(self.scene)
        self.assertFalse(state.has_map(self.scene))

    def test_a_property_group_with_to_dict_is_converted(self):
        class Group(dict):
            def to_dict(self):
                return dict(self)

        scene = {state.KEY: Group(map_name="Boneyard")}
        self.assertEqual(state.get(scene), {"map_name": "Boneyard"})
        self.assertEqual(state.map_name(scene), "Boneyard")
        self.assertIsNone(state.get(None))


class TestLabels(unittest.TestCase):
    def setUp(self):
        self.scene = {}
        state.set_from_load(self.scene, b"x", make_result(labels=("Scale", "Spawn", "", "Kill Boundary"),
                                                           present=[True, True, False, True]), "x.mvar")

    def test_entries_skip_absent_labels_and_keep_the_file_index(self):
        self.assertEqual(state.label_entries(self.scene), [(0, "Scale"), (1, "Spawn"), (3, "Kill Boundary")])
        self.assertEqual(state.label_entries({}), [])
        self.assertEqual(state.label_entries(None), [])

    def test_identifiers_follow_the_raw_index_not_the_text(self):
        self.assertEqual(state.label_enum_id(-1), "NO_LABEL")
        self.assertEqual(state.label_enum_id(None), "NO_LABEL")
        self.assertEqual(state.label_enum_id(0), "L0")
        self.assertEqual(state.label_enum_id(3), "L3")
        for ident, index in (("NO_LABEL", -1), ("", -1), ("L0", 0), ("L3", 3), ("L255", 255), ("Lx", -1), ("X1", -1)):
            self.assertEqual(state.label_index_from_enum(ident), index, ident)

    def test_text_and_scale_detection_are_case_insensitive(self):
        self.assertEqual(state.label_text(self.scene, "L0"), "Scale")
        self.assertEqual(state.label_text(self.scene, "L3"), "Kill Boundary")
        self.assertEqual(state.label_text(self.scene, "L2"), "", "an absent entry has no text")
        self.assertEqual(state.label_text(self.scene, "NO_LABEL"), "")
        self.assertEqual(state.label_text(self.scene, "L99"), "")
        self.assertEqual(state.enum_id_for_text(self.scene, "SCALE"), "L0")
        self.assertEqual(state.enum_id_for_text(self.scene, "scale"), "L0")
        self.assertIsNone(state.enum_id_for_text(self.scene, "Missing"))

    def test_duplicate_texts_stay_distinct_by_index(self):
        scene = {}
        state.set_from_load(scene, b"x", make_result(labels=("Same", "Same")), "x.mvar")
        self.assertEqual([i for i, _t in state.label_entries(scene)], [0, 1])
        self.assertEqual(state.enum_id_for_text(scene, "same"), "L0")


class TestClean(unittest.TestCase):
    def test_values(self):
        c = state._clean
        self.assertEqual(c(5), 5)
        self.assertIs(c(True), True)
        self.assertEqual(c(2 ** 31), "0x80000000")
        self.assertEqual(c(-2 ** 31), -2 ** 31)
        self.assertEqual(c(1.5), 1.5)
        self.assertEqual(c(None), "")
        self.assertEqual(c(b"\x01\xff"), "01ff")
        self.assertEqual(c((1, 2.5, True)), [1, 2.5, True])
        self.assertEqual(c(["a", 1, None]), ["a", "1", ""])
        self.assertEqual(c({1: [1, 2], "k": "v"}), {"1": [1, 2], "k": "v"})
        self.assertEqual(c([[1], [2]]), ["[1]", "[2]"], "Blender has no nested arrays")
        self.assertEqual(c(object.__name__), "object")


class TestG6Additions(unittest.TestCase):
    """Gate G6: the quota count accessor, the failed non-stock slots, and the Blender 5.2.1 bytes-reassignment bug."""

    def setUp(self):
        self.scene = {}
        state.set_from_load(self.scene, b"TEMPLATE", make_result(), "/maps/x.mvar")

    def test_quota_count_is_read_without_a_copy_and_is_zero_without_a_map(self):
        self.assertEqual(state.quota_count(self.scene), 80)
        self.assertEqual(state.quota_count({}), 0)
        self.assertEqual(state.quota_count(None), 0)
        self.scene[state.KEY]["quota_count"] = "garbage"
        self.assertEqual(state.quota_count(self.scene), 0, "a damaged value means unknown, never an exception")

    def test_failed_nonstock_round_trip(self):
        state.set_import_results(self.scene, [1, 2, 3], [4, 5], {4: "Unknown (0x4F1F)"})
        st = state.get(self.scene)
        self.assertEqual((st["imported_slots"], st["failed_slots"]), ([1, 2, 3], [4, 5]))
        self.assertEqual(st["failed_nonstock"], {"4": "Unknown (0x4F1F)"}, "ID property dictionaries have string keys")
        self.assertEqual(state.failed_nonstock(self.scene), {4: "Unknown (0x4F1F)"})
        state.set_import_results(self.scene, [1], [], None)
        self.assertEqual(state.failed_nonstock(self.scene), {})
        self.assertEqual(state.failed_nonstock({}), {}, "no state: nothing")
        old = {state.KEY: {"imported_slots": [1]}}                      # a scene saved before G6 has no such key
        self.assertEqual(state.failed_nonstock(old), {})

    def test_failed_nonstock_ignores_a_damaged_key(self):
        self.scene[state.KEY]["failed_nonstock"] = {"4": "x", "oops": "y"}
        self.assertEqual(state.failed_nonstock(self.scene), {4: "x"})

    def test_a_template_key_that_already_exists_is_deleted_before_it_is_assigned(self):
        """Blender 5.2.1 stores an EMPTY value when bytes are assigned over a key that already holds bytes (probed), so
        ``set_from_load`` deletes both keys first; a scene that still holds a template can never swallow the next file."""
        calls = []

        class Scene(dict):
            def __delitem__(self, key):
                calls.append(("del", key))
                dict.__delitem__(self, key)

            def __setitem__(self, key, value):
                calls.append(("set", key))
                dict.__setitem__(self, key, value)

        scene = Scene()
        state.set_from_load(scene, b"FIRST", make_result(), "/a.mvar")
        del calls[:]
        state.set_from_load(scene, b"SECOND-FILE", make_result(), "/b.mvar")
        self.assertEqual(calls, [("del", state.TEMPLATE_KEY), ("del", state.KEY), ("set", state.TEMPLATE_KEY), ("set", state.KEY)])
        self.assertEqual(state.template_bytes(scene), b"SECOND-FILE")


if __name__ == "__main__":
    unittest.main()
