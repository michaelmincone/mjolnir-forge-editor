"""G0 extra: the frozen interface api.py (SPEC 6.4) is complete, importable and shaped as specified.

The SHA-256 freeze itself is U-22 (test_interface_frozen.py); this module checks the content:
the names, the dataclass fields and defaults, the lazy delegation to entry.py, the helpers
that delegate to tables.py and io.py, and the package rules of 6.1 (no bpy, relative imports
only, standard library only).
"""
import ast
import dataclasses
import inspect
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
PKG = os.path.join(REPO, "Addon", "mvarlib")
sys.path.insert(0, os.path.join(REPO, "Addon"))

import mvarlib  # noqa: E402
from mvarlib import api, entry, io as mio, tables  # noqa: E402

ALL_NAMES = [
    "Vec3", "Bounds", "Issue", "MapInfo", "ObjectRecord", "LoadResult", "ExportObject", "ExportOptions",
    "DiffEntry", "ExportResult", "ReadOptions", "load_map_variant", "export_map_variant",
    "map_name_for_id", "stock_object_names", "palette_tree", "check_output_path", "write_atomic",
    "MvarError", "FormatError", "BlfFormatError", "UnsupportedVariantError", "DesyncError",
    "AmbiguousLayoutError", "OutOfBoundsPositionError", "DecodeError", "EncodeError", "CapacityError",
    "HashError", "ValidationError", "PathPolicyError", "InternalError",
]

FIELDS = {
    "Issue": ["code", "severity", "message", "slot", "object_name"],
    "MapInfo": ["map_id", "map_name", "is_stock_map", "bounds", "quota_count", "version", "title", "description",
                "labels", "label_present", "occupied", "shape", "template_sha256", "hash_flavour", "palette_crc",
                "max_budget_raw", "spent_budget_raw", "hypothesis", "warnings"],
    "ObjectRecord": ["slot", "folder", "item", "type_id", "type_name", "stock", "position", "forward", "up",
                     "orientation_kind", "parent_slot", "shape", "width", "length", "top", "bottom",
                     "spawn_sequence", "spawn_time", "cached_type", "label_index", "placement", "physics",
                     "symmetry", "place_at_start", "game_specific", "team", "color", "other_a", "other_b",
                     "flags2", "raw", "raw_bits"],
    "LoadResult": ["info", "objects", "warnings"],
    "ExportObject": ["name", "slot", "token_raw", "token_bits", "name_matches_import", "type_name", "type_id_hint",
                     "position", "forward", "up", "shape", "width", "length", "top", "bottom", "spawn_sequence",
                     "spawn_time", "cached_type", "label_index", "physics", "symmetry", "place_at_start",
                     "game_specific", "team", "color", "other_a", "other_b", "hidden", "from_array"],
    "ExportOptions": ["allow_unverified_rotation", "force_reencode", "fsm_policy", "hash_policy",
                      "keep_unrecognised_imported", "imported_slots", "max_objects", "raise_quota_max"],
    "DiffEntry": ["kind", "slot", "name", "detail"],
    "ExportResult": ["ok", "data", "diff", "errors", "warnings", "stats"],
    "ReadOptions": ["strict", "hypothesis_filter"],
}
FROZEN = {"Issue", "MapInfo", "ObjectRecord", "LoadResult", "DiffEntry", "ExportResult", "ReadOptions"}
MUTABLE = {"ExportObject", "ExportOptions"}

STDLIB_FALLBACK = set("""
__future__ abc argparse array ast base64 binascii bisect builtins bz2 calendar codecs collections contextlib copy
csv ctypes dataclasses datetime decimal difflib enum errno fnmatch fractions functools gc glob gzip hashlib heapq
hmac io itertools json keyword locale logging lzma math numbers operator os pathlib pickle platform pprint random
re shutil signal stat statistics string struct subprocess sys tempfile textwrap threading time traceback types
typing unicodedata unittest uuid warnings weakref zlib
""".split())


def _package_files():
    for name in sorted(os.listdir(PKG)):
        if name.endswith(".py"):
            yield os.path.join(PKG, name)


class TestNames(unittest.TestCase):
    def test_all_is_exactly_the_spec_list(self):
        self.assertEqual(list(api.__all__), ALL_NAMES)

    def test_every_name_resolves(self):
        for name in ALL_NAMES:
            self.assertTrue(hasattr(api, name), name)

    def test_package_reexports_the_api(self):
        for name in ALL_NAMES:
            self.assertIs(getattr(mvarlib, name), getattr(api, name), name)
        self.assertEqual(mvarlib.__version__, "1.0.0")
        self.assertIs(mvarlib.errors, sys.modules["mvarlib.errors"])


class TestDataclasses(unittest.TestCase):
    def test_fields_match_the_spec_in_order(self):
        for cls_name, names in FIELDS.items():
            cls = getattr(api, cls_name)
            self.assertTrue(dataclasses.is_dataclass(cls), cls_name)
            self.assertEqual([f.name for f in dataclasses.fields(cls)], names, cls_name)

    def test_frozen_and_mutable(self):
        issue = api.Issue("W_X", "warning", "A sentence.")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            issue.code = "E_Y"
        for name in FROZEN:
            self.assertTrue(getattr(api, name).__dataclass_params__.frozen, name)
        for name in MUTABLE:
            self.assertFalse(getattr(api, name).__dataclass_params__.frozen, name)

    def test_defaults(self):
        eo = api.ExportOptions()
        self.assertEqual((eo.allow_unverified_rotation, eo.force_reencode, eo.fsm_policy, eo.hash_policy,
                          eo.keep_unrecognised_imported, eo.imported_slots, eo.max_objects, eo.raise_quota_max),
                         (False, False, "KEEP", "REPRODUCE", False, None, 650, False))
        ro = api.ReadOptions()
        self.assertEqual((ro.strict, ro.hypothesis_filter), (True, None))
        ob = api.ExportObject(name="n", slot=None, token_raw=None, token_bits=None)
        self.assertEqual((ob.name_matches_import, ob.type_name, ob.type_id_hint, ob.position, ob.forward, ob.up),
                         (False, "", -1, (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))
        self.assertEqual((ob.shape, ob.spawn_sequence, ob.spawn_time, ob.cached_type, ob.label_index, ob.physics,
                          ob.symmetry, ob.place_at_start, ob.game_specific, ob.team, ob.color, ob.other_a,
                          ob.other_b, ob.hidden, ob.from_array),
                         (0, 0, 0, 0, -1, 3, 3, True, False, 8, -1, 0, 0, False, False))
        issue = api.Issue("I_X", "info", "m")
        self.assertEqual((issue.slot, issue.object_name), (None, None))
        self.assertEqual(api.MapInfo.__dataclass_fields__["warnings"].default_factory(), [])

    def test_freeze_v2_field_is_appended_last_with_a_default(self):
        """D11: every call written against freeze v1 (positional or keyword) stays valid."""
        fields = dataclasses.fields(api.ExportOptions)
        self.assertEqual(fields[-1].name, "raise_quota_max")
        self.assertIs(fields[-1].default, False)
        old_style = api.ExportOptions(True, False, "DROP", "SALTED_BE32", True, [1, 2], 600)    # the seven v1 fields, positional
        self.assertEqual((old_style.max_objects, old_style.raise_quota_max), (600, False))
        self.assertTrue(api.ExportOptions(raise_quota_max=True).raise_quota_max)

    def test_instances_can_be_built_end_to_end(self):
        info = api.MapInfo(map_id=3006, map_name="Forge World", is_stock_map=True, bounds=(0.0,) * 6, quota_count=80,
                           version=31, title="t", description="d", labels=["a"], label_present=[True], occupied=0,
                           shape="plain4", template_sha256="0" * 64, hash_flavour="unknown", palette_crc=0,
                           max_budget_raw=0, spent_budget_raw=0, hypothesis={"guid": False})
        self.assertEqual(info.warnings, [])
        rec = api.ObjectRecord(**dict((n, 0) for n in FIELDS["ObjectRecord"]))
        self.assertEqual(api.LoadResult(info, [rec], []).objects[0].slot, 0)
        result = api.ExportResult(ok=False, data=None, diff=[api.DiffEntry("kept", 1, "n", "")], errors=[issue_e()],
                                  warnings=[], stats={})
        self.assertIsNone(result.data)


def issue_e():
    return api.Issue("E_TOO_MANY", "error", "Too many.")


class TestApiIsTheSpecBlock(unittest.TestCase):
    def test_api_py_equals_the_block_of_spec_6_4_apart_from_the_docstring(self):
        with open(os.path.join(REPO, "docs", "mvar", "SPEC-mvar.md"), "r", encoding="utf-8") as fh:
            lines = fh.read().split("\n")
        heading = next(i for i, line in enumerate(lines) if line.startswith("### 6.4 The frozen interface"))
        start = next(i for i in range(heading, len(lines)) if lines[i].strip() == "```python") + 1
        end = next(i for i in range(start, len(lines)) if lines[i].strip() == "```")
        block = "\n".join(lines[start:end]) + "\n"
        with open(os.path.join(PKG, "api.py"), "r", encoding="utf-8") as fh:
            source = fh.read()
        tree = ast.parse(source)
        self.assertIsInstance(tree.body[0], ast.Expr)                       # the module docstring
        self.assertIsInstance(tree.body[0].value, ast.Constant)
        docstring_end_line = tree.body[0].end_lineno if hasattr(tree.body[0], "end_lineno") else None
        if docstring_end_line is None:                                      # Python 3.7 and older would lack it; 3.8+ has it
            self.skipTest("ast end_lineno unavailable")
        body = "\n".join(source.split("\n")[docstring_end_line:])
        self.assertEqual(body, block, "api.py differs from the 6.4 block of docs/mvar/SPEC-mvar.md")


class TestLazyDelegation(unittest.TestCase):
    def test_api_does_not_import_entry_at_module_level(self):
        with open(os.path.join(PKG, "api.py"), "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                imported = [a.name for a in node.names]
                self.assertNotIn("entry", imported)
                self.assertNotIn("tables", imported)
                self.assertNotIn("io", imported)
                self.assertTrue(node.module in ("dataclasses", "typing", "errors"), node.module)

    def test_entry_signatures_mirror_api(self):
        self.assertEqual(list(inspect.signature(entry.load_map_variant).parameters), ["data", "name", "options"])
        self.assertEqual(list(inspect.signature(entry.export_map_variant).parameters),
                         ["template", "objects", "options"])
        self.assertEqual(list(inspect.signature(api.load_map_variant).parameters), ["data", "name", "options"])
        self.assertEqual(list(inspect.signature(api.export_map_variant).parameters),
                         ["template", "objects", "options"])

    def _entry_source(self):
        with open(os.path.join(PKG, "entry.py"), "r", encoding="utf-8") as fh:
            return fh.read()

    def test_load_placeholder_raises_until_g3_replaces_it(self):
        if 'raise NotImplementedError("G3")' not in self._entry_source():
            self.skipTest("entry.load_map_variant has been implemented (G3)")
        with self.assertRaises(NotImplementedError) as cm:
            api.load_map_variant(b"")
        self.assertEqual(str(cm.exception), "G3")

    def test_export_placeholder_raises_until_g5_replaces_it(self):
        if 'raise NotImplementedError("G5")' not in self._entry_source():
            self.skipTest("entry.export_map_variant has been implemented (G5)")
        with self.assertRaises(NotImplementedError) as cm:
            api.export_map_variant(b"", [], api.ExportOptions())
        self.assertEqual(str(cm.exception), "G5")


class TestHelpers(unittest.TestCase):
    def test_data_helpers_delegate_to_tables(self):
        self.assertEqual(api.map_name_for_id(3006), "Forge World")
        self.assertIsNone(api.map_name_for_id(0xFFFFFFFF))
        self.assertEqual(api.stock_object_names("Forge World"), tables.stock_object_names("Forge World"))
        self.assertEqual(api.palette_tree(), tables.palette_tree())      # G4 replaced the empty G0 tree by the generated one

    def test_path_helpers_delegate_to_io(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "in.mvar")
            with open(src, "wb") as fh:
                fh.write(b"x")
            issue = api.check_output_path(src, [src], protected=[])
            self.assertEqual(issue.code, "E_PATH_SAME_AS_SOURCE")
            out = os.path.join(tmp, "out.mvar")
            self.assertIsNone(api.check_output_path(out, [src], protected=[]))
            api.write_atomic(out, b"payload", [src], [])
            with open(out, "rb") as fh:
                self.assertEqual(fh.read(), b"payload")
            with self.assertRaises(api.PathPolicyError):
                api.write_atomic(src, b"zzz", [src], [])
            with open(src, "rb") as fh:
                self.assertEqual(fh.read(), b"x")


class TestPackageRules(unittest.TestCase):
    def test_no_bpy_relative_imports_only_stdlib_only(self):
        allowed = getattr(sys, "stdlib_module_names", None) or STDLIB_FALLBACK
        for path in _package_files():
            with open(path, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level == 0:
                        roots = [(node.module or "").split(".")[0]]
                    else:
                        roots = []               # relative import: fine
                else:
                    continue
                for root in roots:
                    self.assertNotIn(root, ("bpy", "bmesh", "mathutils", "mvarlib", "Addon"), "%s imports %s" % (path, root))
                    self.assertIn(root, allowed, "%s imports non-stdlib %s" % (path, root))

    def test_files_of_g0_exist(self):
        for name in ("__init__", "api", "errors", "entry", "tables", "io"):
            self.assertTrue(os.path.isfile(os.path.join(PKG, name + ".py")), name)
        for name in ("maps.json", "stock_objects.json", "cached_type_hints.json", "palette_tree.json"):
            self.assertTrue(os.path.isfile(os.path.join(PKG, "data", name)), name)


if __name__ == "__main__":
    unittest.main()
