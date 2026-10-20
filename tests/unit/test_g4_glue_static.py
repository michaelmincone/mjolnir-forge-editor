"""G4 extra: static properties of the Blender glue that need no Blender (SPEC 8.1, 8.2, 8.6, 8.13).

The glue files are parsed with ``ast`` (never imported: they import ``bpy``). Checked: the library is reached
only through ``provider`` (no import of ``mvarlib``, no ``isinstance`` on api types); everything SPEC 8.13 removes
is gone (ctypes, DLL, update checker, ``driver_namespace``, ``sys.path`` edit, network, threads); the
``register``/``unregister`` functions contain no ``bpy.data``, ``bpy.ops`` or scene access (8.2); the stable ids
the UI must keep are present; the icon table covers every group of the committed palette tree.
"""
import ast
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ADDON = os.path.join(REPO, "Addon")
GLUE = ("__init__.py", "mjolnir.py", "palette.py", "io_ops.py", "state.py")
API_TYPES = {"Issue", "MapInfo", "ObjectRecord", "LoadResult", "ExportObject", "ExportOptions", "DiffEntry",
             "ExportResult", "ReadOptions", "MvarError"}


def parse(name):
    with open(os.path.join(ADDON, name), "r", encoding="utf-8") as fh:
        return ast.parse(fh.read(), filename=name)


def imported_modules(tree):
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.append(("." * node.level) + (node.module or ""))
            found.extend(("." * node.level) + (node.module or "") + "." + alias.name for alias in node.names)
    return found


def dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


class TestGlueStatic(unittest.TestCase):
    def test_every_glue_file_parses(self):
        for name in GLUE:
            parse(name)

    def test_the_library_is_reached_only_through_the_provider(self):
        for name in GLUE:
            for module in imported_modules(parse(name)):
                self.assertNotIn("mvarlib", module.replace(".provider", ""), "%s imports %s" % (name, module))
                self.assertNotIn("errors", module.split(".")[-1:], "%s imports errors" % name)
        for name in GLUE:
            for node in ast.walk(parse(name)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "isinstance":
                    mentioned = set()
                    for arg in node.args[1:]:
                        mentioned.update(n.id for n in ast.walk(arg) if isinstance(n, ast.Name))
                        mentioned.update(n.attr for n in ast.walk(arg) if isinstance(n, ast.Attribute))
                    self.assertFalse(mentioned & API_TYPES, "%s:%d isinstance on an api type" % (name, node.lineno))

    def test_what_section_8_13_removes_is_gone(self):
        banned_modules = ("ctypes", "urllib", "webbrowser", "threading", "socket", "subprocess", "http")
        banned_names = {"cdll", "WinDLL", "LoadLibrary", "driver_namespace", "persist_vars", "gtIndexToLabel",
                        "githubURL", "check_update", "tryGetLatestRelease", "dllPath", "ForgeBridge"}
        for name in GLUE:
            tree = parse(name)
            for module in imported_modules(tree):
                self.assertNotIn(module.split(".")[0], banned_modules, "%s imports %s" % (name, module))
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    self.assertNotIn(node.id, banned_names, "%s:%d uses %s" % (name, node.lineno, node.id))
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, banned_names, "%s:%d uses %s" % (name, node.lineno, node.attr))
                    path = dotted(node)
                    self.assertFalse(path and path.startswith("sys.path"), "%s:%d edits sys.path" % (name, node.lineno))
                    self.assertFalse(path and path.endswith("instance_collection.name_full"),
                                     "%s:%d resolves a type with name_full" % (name, node.lineno))
                    self.assertNotEqual(path, "bpy.ops.forge.error", "ErrorMessage invoked by the glue")

    def test_register_functions_touch_no_data_operators_or_scene(self):
        for name in GLUE:
            for node in ast.walk(parse(name)):
                if isinstance(node, ast.FunctionDef) and node.name in ("register", "unregister"):
                    for inner in ast.walk(node):
                        if isinstance(inner, ast.Attribute):
                            path = dotted(inner) or ""
                            self.assertFalse(path.startswith(("bpy.data", "bpy.ops", "bpy.context.scene",
                                                              "context.scene")),
                                             "%s %s() uses %s" % (name, node.name, path))
                        if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):
                            self.assertNotIn(inner.func.id, ("open", "ensure_palette", "Thread"),
                                             "%s %s() calls %s" % (name, node.name, inner.func.id))

    def test_the_ids_the_user_interface_keeps(self):
        values = set()
        for name in GLUE:
            for node in ast.walk(parse(name)):
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ("bl_idname",)
                                                        for t in node.targets):
                    if isinstance(node.value, ast.Constant):
                        values.add(node.value.value)
        expected = {"import_scene.mjolnir_mvar", "export_scene.mjolnir_mvar", "forge.add_object", "forge.error",
                    "forge.scale_objects", "object.convert_forge", "object.setup_array", "SCENE_PT_forge_object",
                    "SCENE_PT_forge_object_sidebar", "SCENE_PT_forge_collection", "SCENE_PT_forge_scene",
                    "VIEW3D_MT_add_forge_object", "MJOLNIR_FH_mvar"}
        self.assertEqual(expected - values, set())
        self.assertNotIn("forge.import", values)
        self.assertNotIn("forge.export", values)

    def test_the_property_names_the_shaders_read_are_kept(self):
        with open(os.path.join(ADDON, "mjolnir.py"), encoding="utf-8") as fh:
            source = fh.read()
        for needle in ("bpy.types.Object.forge", "bpy.types.Collection.forge", "bpy.types.Scene.forge",
                       "colorIndex: IntProperty"):
            self.assertIn(needle, source)

    def test_every_palette_group_has_an_icon(self):
        icons = None
        for node in ast.walk(parse("palette.py")):
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "GROUP_ICONS"
                                                    for t in node.targets):
                icons = ast.literal_eval(node.value)
        self.assertIsNotNone(icons)
        with open(os.path.join(ADDON, "mvarlib", "data", "palette_tree.json"), "r", encoding="utf-8") as fh:
            tree = json.load(fh)
        sys.path.insert(0, ADDON)
        from mvarlib.catalog import browser_tree
        tree = browser_tree(tree)
        names = []

        def walk(node):
            for group in node.get("groups", []):
                names.append(group["name"])
                walk(group)

        walk(tree)
        self.assertEqual(len(names), 32)
        self.assertEqual(sorted(set(names) - set(icons)), [], "groups without an icon")
        self.assertEqual(sorted(set(icons) - set(names)), [], "icons for groups that do not exist")
        for icon in icons.values():
            self.assertRegex(icon, r"^[A-Z0-9_]+$")

    def test_the_scene_state_is_touched_only_inside_state_py(self):
        """SPEC 8.1: ``state.py`` is the only code that touches ``scene['mjolnir*']`` (no key, no ``state.KEY``)."""
        for name in GLUE:
            if name == "state.py":
                continue
            for node in ast.walk(parse(name)):
                if isinstance(node, ast.Subscript):
                    key = node.slice
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        self.assertFalse(key.value.startswith("mjolnir"), "%s:%d subscripts %r" % (name, node.lineno, key.value))
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args:
                    first = node.args[0]
                    if node.func.attr in ("get", "pop", "setdefault", "__getitem__", "__setitem__", "__contains__") \
                            and isinstance(first, ast.Constant) and isinstance(first.value, str):
                        self.assertFalse(first.value.startswith("mjolnir"), "%s:%d reads %r" % (name, node.lineno, first.value))
                if isinstance(node, ast.Attribute) and node.attr in ("KEY", "TEMPLATE_KEY") \
                        and isinstance(node.value, ast.Name) and node.value.id == "state":
                    self.fail("%s:%d reaches into state.%s instead of a state function" % (name, node.lineno, node.attr))

    def _enum_numbers(self, prop):
        """``{identifier: number}`` of the literal ``items`` of an ``EnumProperty`` annotated as ``prop``."""
        for node in ast.walk(parse("mjolnir.py")):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == prop \
                    and isinstance(node.annotation, ast.Call):          # Blender style: the EnumProperty is the annotation
                for kw in node.annotation.keywords:
                    if kw.arg == "items" and isinstance(kw.value, (ast.List, ast.Tuple)):
                        return dict((ast.literal_eval(e)[0], ast.literal_eval(e)[4]) for e in kw.value.elts)
        self.fail("no literal items for %s" % prop)

    def test_the_enum_numbers_a_blend_stores_are_the_old_add_ons(self):
        """forge.py v0.9.9.2 numbered the items by position; a .blend saved by it must read the same values."""
        self.assertEqual(self._enum_numbers("shape"), {"NONE": 0, "CYLINDER": 1, "BOX": 2, "SPHERE": 3})
        self.assertEqual(self._enum_numbers("physics"), {"NORMAL": 0, "FIXED": 1, "PHASED": 2})
        self.assertEqual(self._enum_numbers("symmetry"), {"BOTH": 0, "SYMMETRIC": 1, "ASYMMETRIC": 2, "NEITHER": 3})

    def test_the_scale_convention_numbers_are_the_shipped_add_ons(self):
        """Polish item 5 of gate G6: forge.py v0.9.9.2 stores 1X 0, 33X 1, 71X 2, 47X 3, 330X 4 for ``scaleConvention``.

        The older ``Addon/mjolnir.py`` of the repository numbered 33X 0, 71X 1, 47X 2, 330X 3 (no 1X). The explicit numbers
        keep a .blend saved by the shipped add-on reading the same convention; they are literal in the source so that a
        reordering of the items cannot shift them. The default is the identifier ``47X`` (8.7 #3), i.e. stored number 3.
        """
        self.assertEqual(self._enum_numbers("scaleConvention"), {"1X": 0, "33X": 1, "71X": 2, "47X": 3, "330X": 4})
        for node in ast.walk(parse("mjolnir.py")):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "scaleConvention":
                defaults = [ast.literal_eval(kw.value) for kw in node.annotation.keywords if kw.arg == "default"]
                self.assertEqual(defaults, ["47X"])
                return
        self.fail("scaleConvention not found")

    def test_property_groups_declare_slots(self):
        """``register_class`` warns under ``--debug-python`` about a PropertyGroup without ``__slots__``."""
        groups = [node for node in ast.walk(parse("mjolnir.py")) if isinstance(node, ast.ClassDef)
                  and any(dotted(base) == "bpy.types.PropertyGroup" for base in node.bases)]
        self.assertEqual(sorted(g.name for g in groups), ["ForgeCollectionProps", "ForgeObjectProps", "ForgeSceneProps"])
        for group in groups:
            slots = [n for n in group.body if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == "__slots__" for t in n.targets)]
            self.assertEqual(len(slots), 1, "%s has no __slots__" % group.name)

    def test_no_game_asset_or_dll_is_added_by_g4(self):
        for base, _dirs, files in os.walk(os.path.join(REPO, "tests", "blender")):
            for name in files:
                self.assertFalse(name.endswith((".blend", ".mvar", ".bin", ".dll", ".png")), name)


if __name__ == "__main__":
    unittest.main()
