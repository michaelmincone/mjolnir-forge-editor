"""G0 extra: the exception hierarchy of SPEC 6.2 (frozen in errors.py)."""
import ast
import copy
import os
import pickle
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "Addon"))

from mvarlib import api, errors  # noqa: E402

# class -> parent, exactly the tree of SPEC 6.2
TREE = {
    "MvarError": "Exception",
    "FormatError": "MvarError",
    "BlfFormatError": "FormatError",
    "UnsupportedVariantError": "FormatError",
    "DesyncError": "FormatError",
    "AmbiguousLayoutError": "FormatError",
    "OutOfBoundsPositionError": "FormatError",
    "DecodeError": "MvarError",
    "EncodeError": "MvarError",
    "CapacityError": "MvarError",
    "HashError": "MvarError",
    "ValidationError": "MvarError",
    "PathPolicyError": "MvarError",
    "InternalError": "MvarError",
}


class TestHierarchy(unittest.TestCase):
    def test_tree_matches_spec(self):
        for name, parent in TREE.items():
            cls = getattr(errors, name)
            self.assertEqual(cls.__bases__, (getattr(errors, parent) if parent != "Exception" else Exception,), name)

    def test_all_lists_exactly_the_classes(self):
        self.assertEqual(sorted(errors.__all__), sorted(TREE))

    def test_api_reexports_the_same_objects(self):
        for name in TREE:
            self.assertIs(getattr(api, name), getattr(errors, name), name)
            self.assertIn(name, api.__all__)

    def test_errors_imports_nothing_from_the_package(self):
        with open(os.path.join(REPO, "Addon", "mvarlib", "errors.py"), "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            self.assertNotIsInstance(node, (ast.Import, ast.ImportFrom), "errors.py must import nothing")

    def test_catching_the_base_catches_everything(self):
        for name in TREE:
            if name == "MvarError":
                continue
            with self.assertRaises(errors.MvarError):
                raise getattr(errors, name)("A complete sentence.")


class TestAttributes(unittest.TestCase):
    def test_defaults_and_roundtrip_through_message_only(self):
        for name in TREE:
            exc = getattr(errors, name)("Something went wrong.")
            self.assertEqual(str(exc), "Something went wrong.")
        self.assertEqual(errors.DesyncError("m").diagnostics, [])
        self.assertEqual(errors.AmbiguousLayoutError("m").candidates, [])
        self.assertIsNone(errors.OutOfBoundsPositionError("m").slot)
        self.assertEqual(errors.ValidationError("m").issues, [])

    def test_extra_attributes(self):
        d = errors.DesyncError("no layout fits", diagnostics=[{"hyp": "a", "slot": 3}])
        self.assertEqual(d.diagnostics[0]["slot"], 3)
        a = errors.AmbiguousLayoutError("two readings", candidates=[1, 2])
        self.assertEqual(a.candidates, [1, 2])
        o = errors.OutOfBoundsPositionError("slot 7 is outside", slot=7)
        self.assertEqual(o.slot, 7)

    def test_validation_error_collects_issues_and_builds_a_message(self):
        issues = [api.Issue("E_TOO_MANY", "error", "651 objects would be written."),
                  api.Issue("E_CAPACITY", "error", "Too many bits.")]
        v = errors.ValidationError(issues=issues)
        self.assertEqual(v.issues, issues)
        self.assertIn("651 objects would be written.", str(v))
        self.assertIn("2 problem", str(v))
        self.assertEqual(str(errors.ValidationError("explicit", issues)), "explicit")

    def test_pickle_and_copy_keep_attributes(self):
        cases = [errors.DesyncError("d", diagnostics=[1]), errors.AmbiguousLayoutError("a", candidates=[2]),
                 errors.OutOfBoundsPositionError("o", slot=9),
                 errors.ValidationError("v", [api.Issue("E_X", "error", "m")])]
        for exc in cases:
            for clone in (pickle.loads(pickle.dumps(exc)), copy.copy(exc), copy.deepcopy(exc)):
                self.assertIs(type(clone), type(exc))
                self.assertEqual(str(clone), str(exc))
                self.assertEqual(clone.__dict__, exc.__dict__)

    def test_stdlib_only_module_has_docstring(self):
        self.assertTrue(errors.__doc__ and "FROZEN" in errors.__doc__)


if __name__ == "__main__":
    unittest.main()
