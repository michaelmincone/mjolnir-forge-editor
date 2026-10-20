"""G4 extra: the packaging and palette-tree tools (pure Python, no Blender, no game asset).

``tools/build_package.py`` (SPEC 8.10): refuses an output folder inside the repository, refuses a placeholder
manifest, never stages the DLL / parse_palette.py / bytecode / the object library (unless the owner-only flags),
and inspects the finished zip. ``tools/gen_palette_tree.py`` (SPEC 8.6): turns a raw collection tree into the
committed document deterministically and refuses leaf names that are not Forge World objects. Nothing here runs
Blender or writes inside the repository.
"""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "Addon"))


def load_tool(name):
    spec = importlib.util.spec_from_file_location("g4_tool_" + name, os.path.join(REPO, "tools", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bp = load_tool("build_package")
gp = load_tool("gen_palette_tree")
TREE = os.path.join(REPO, "Addon", "mvarlib", "data", "palette_tree.json")


def to_raw(node):
    """The committed node format -> the raw format Blender reports (empty lists present)."""
    return {"name": node.get("name", "Forge World Palette"), "groups": [to_raw(g) for g in node.get("groups", [])],
            "leaves": list(node.get("leaves", []))}


def quiet(fn, *args):
    """Call a tool's ``main`` without letting its messages into the test output."""
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        return fn(*args)


class TestBuildPackage(unittest.TestCase):
    def test_output_inside_the_repository_is_refused_and_nothing_is_created(self):
        inside = os.path.join(REPO, "dist-g4-test-never-created")
        self.assertTrue(bp.is_inside_tree(inside))
        self.assertTrue(bp.is_inside_tree(REPO))
        self.assertTrue(bp.is_inside_tree(os.path.join(REPO, "Addon", "x")))
        with self.assertRaises(bp.BuildError) as cm:
            bp.build(inside, blender="/bin/echo", allow_placeholders=True)
        self.assertIn("inside the repository", str(cm.exception))
        self.assertFalse(os.path.exists(inside), "the refusal must not create the folder")
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(bp.is_inside_tree(os.path.join(tmp, "dist")))

    def test_main_needs_the_acknowledgement_for_the_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(quiet(bp.main, ["--out", os.path.join(tmp, "dist"), "--with-library"]), 2)
            self.assertFalse(os.path.exists(os.path.join(tmp, "dist")))

    def test_placeholders_are_found_outside_comments_only(self):
        self.assertEqual(bp.placeholders_in('maintainer = "OWNER NAME <owner@example.com>"\n'), ["example.com", "OWNER"])
        self.assertEqual(bp.placeholders_in('maintainer = "A B <a@b.org>"   # fill in: OWNER, example.com\n'), [])
        self.assertEqual(bp.placeholders_in('license = ["SPDX:GPL-3.0-or-later"]  # PLACEHOLDER OWNER\n'), [])

    def test_a_placeholder_manifest_is_refused_before_blender_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            addon = os.path.join(tmp, "Addon")
            os.makedirs(addon)
            with open(os.path.join(addon, "blender_manifest.toml"), "w") as fh:
                fh.write('maintainer = "OWNER NAME <owner@example.com>"\n')
            old = bp.ADDON_DIR
            bp.ADDON_DIR = addon
            try:
                with self.assertRaises(bp.BuildError) as cm:
                    bp.build(os.path.join(tmp, "dist"), blender="/bin/echo")      # /bin/echo: any executable; never run
            finally:
                bp.ADDON_DIR = old
            self.assertIn("placeholder", str(cm.exception))
            self.assertFalse(os.path.exists(os.path.join(tmp, "dist")), "refused before the output folder is created")

    def test_missing_blender_is_a_build_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(bp.BuildError):
                bp.build(os.path.join(tmp, "dist"), blender=os.path.join(tmp, "no-such-blender"), allow_placeholders=True)

    def test_the_ignore_rules_drop_the_dll_the_dev_tool_bytecode_and_the_library(self):
        ignore = bp._ignore_factory(with_library=False)
        resources = os.path.join(bp.ADDON_DIR, "Resources")
        self.assertEqual(sorted(ignore(resources, ["ForgeBridge.dll", "Halo Reach.blend", "keep.txt"])),
                         ["ForgeBridge.dll", "Halo Reach.blend"])
        self.assertEqual(sorted(ignore(bp.ADDON_DIR, ["__init__.py", "parse_palette.py", "__pycache__", "x.pyc",
                                                      "mjolnir.py"])), ["__pycache__", "parse_palette.py", "x.pyc"])
        with_library = bp._ignore_factory(with_library=True)
        self.assertEqual(sorted(with_library(resources, ["ForgeBridge.dll", "Halo Reach.blend"])), ["ForgeBridge.dll"])

    def test_stage_copies_the_addon_without_game_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "stage")
            bp.stage(dest)
            names = []
            for base, _dirs, files in os.walk(dest):
                names.extend(os.path.relpath(os.path.join(base, f), dest).replace(os.sep, "/") for f in files)
            self.assertIn("blender_manifest.toml", names)
            self.assertIn("__init__.py", names)
            self.assertIn("mvarlib/data/palette_tree.json", names)
            self.assertFalse([n for n in names if n.endswith((".dll", ".blend", ".pyc", ".mvar", ".bin"))], names)
            self.assertNotIn("parse_palette.py", names)

    def test_external_preview_library_is_staged_without_modifying_either_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, 'external.blend')
            payload = b'Synthetic preview-library stand-in; not a game asset'
            with open(source, 'wb') as stream:
                stream.write(payload)
            dest = os.path.join(tmp, 'stage')
            bp.stage(dest, with_library=True, library_path=source)
            with open(os.path.join(dest, bp.LIBRARY_REL), 'rb') as stream:
                self.assertEqual(stream.read(), payload)
            with open(source, 'rb') as stream:
                self.assertEqual(stream.read(), payload)
            with open(os.path.join(dest, bp.LIBRARY_REL), 'wb') as stream:
                stream.write(b'Changed staged stand-in')
            with open(source, 'rb') as stream:
                self.assertEqual(stream.read(), payload, 'The staged library must not alias mutable source bytes')

    def test_zip_inspection_finds_every_forbidden_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            clean = os.path.join(tmp, "clean.zip")
            with zipfile.ZipFile(clean, "w") as zf:
                for name in ("blender_manifest.toml", "__init__.py", "mvarlib/api.py", "mvarlib/data/maps.json"):
                    zf.writestr(name, "x")
            self.assertEqual(bp.inspect_zip(clean, False), [])
            for planted in ("Resources/ForgeBridge.dll", "Resources/Halo Reach.blend", "__pycache__/x.cpython-313.pyc",
                            "parse_palette.py", "maps/forge.mvar", "samples/a.bin"):
                bad = os.path.join(tmp, "bad.zip")
                with zipfile.ZipFile(bad, "w") as zf:
                    for name in ("blender_manifest.toml", "__init__.py", planted):
                        zf.writestr(name, "x")
                self.assertTrue(bp.inspect_zip(bad, False), "not found: " + planted)
            library = os.path.join(tmp, "lib.zip")
            with zipfile.ZipFile(library, "w") as zf:
                for name in ("blender_manifest.toml", "__init__.py", "Resources/Halo Reach.blend"):
                    zf.writestr(name, "x")
            self.assertTrue(bp.inspect_zip(library, False))
            self.assertEqual(bp.inspect_zip(library, True), [], "allowed with the owner-only flag")
            missing = os.path.join(tmp, "nomanifest.zip")
            with zipfile.ZipFile(missing, "w") as zf:
                zf.writestr("__init__.py", "x")
            self.assertTrue(bp.inspect_zip(missing, False))

    def test_the_manifest_matches_the_spec(self):
        text = bp.manifest_text(bp.ADDON_DIR)
        for needle in ('schema_version = "1.0.0"', 'id = "mjolnir_forge"', 'type = "add-on"',
                       'blender_version_min = "5.2.0"', 'files = "Read and write map variant files chosen by the user"',
                       '"Resources/ForgeBridge.dll"', '"parse_palette.py"', '"__pycache__/"'):
            self.assertIn(needle, text)
        self.assertNotIn("network", text, "no network permission: the update checker is gone")


class TestGenPaletteTree(unittest.TestCase):
    def setUp(self):
        with open(TREE, "r", encoding="utf-8") as fh:
            self.committed = json.load(fh)
        self.names = gp.forge_world_names()

    def test_the_committed_tree_is_the_rendered_document(self):
        with open(TREE, "rb") as fh:
            self.assertEqual(fh.read(), gp.render(self.committed).encode("ascii"))

    def test_finalize_reproduces_the_committed_document_from_the_raw_format(self):
        raw = {"name": "Forge World Palette", "groups": [to_raw(g) for g in self.committed["groups"]], "leaves": []}
        self.assertEqual(gp.finalize(raw, self.names), self.committed)
        self.assertEqual(gp.count_leaves(self.committed), 194)

    def test_unknown_leaf_names_and_root_objects_are_refused(self):
        raw = {"name": "root", "groups": [{"name": "G", "groups": [], "leaves": ["Block, 1x1", "Not A Forge Object"]}],
               "leaves": []}
        with self.assertRaises(gp.GenError) as cm:
            gp.finalize(raw, self.names)
        self.assertIn("Not A Forge Object", str(cm.exception))
        with self.assertRaises(gp.GenError):
            gp.finalize({"name": "root", "groups": [], "leaves": ["Block, 1x1"]}, self.names)

    def test_empty_keys_are_omitted_and_the_text_is_ascii_lf(self):
        doc = gp.finalize({"name": "r", "groups": [{"name": "A", "groups": [], "leaves": ["Block, 1x1"]},
                                                    {"name": "B", "groups": [{"name": "C", "groups": [], "leaves": []}],
                                                     "leaves": []}], "leaves": []}, self.names)
        self.assertEqual(doc["groups"][0], {"name": "A", "leaves": ["Block, 1x1"]})
        self.assertEqual(doc["groups"][1], {"name": "B", "groups": [{"name": "C"}]})
        text = gp.render(doc)
        text.encode("ascii")
        self.assertTrue(text.endswith("\n"))
        self.assertNotIn("\r", text)
        self.assertEqual(text, gp.render(doc))

    def test_cli_from_raw_check_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_path = os.path.join(tmp, "raw.json")
            out = os.path.join(tmp, "tree.json")
            with open(raw_path, "w") as fh:
                json.dump({"name": "Forge World Palette", "groups": [to_raw(g) for g in self.committed["groups"]],
                           "leaves": []}, fh)
            self.assertEqual(quiet(gp.main, ["--from-raw", raw_path, "--out", out]), 0)
            with open(out, "rb") as fh, open(TREE, "rb") as ref:
                self.assertEqual(fh.read(), ref.read())
            self.assertEqual(quiet(gp.main, ["--from-raw", raw_path, "--out", out, "--check"]), 0)
            with open(out, "a") as fh:
                fh.write(" ")
            self.assertEqual(quiet(gp.main, ["--from-raw", raw_path, "--out", out, "--check"]), 1)
            self.assertEqual(quiet(gp.main, ["--library", os.path.join(tmp, "missing.blend"), "--out", out]), 2)
            self.assertEqual(quiet(gp.main, ["--library", os.path.join(tmp, "missing.blend"), "--out", out,
                                             "--blender", os.path.join(tmp, "no-blender")]), 2)

    def test_sha256_helper_and_defaults_point_at_the_repository(self):
        self.assertTrue(gp.DEFAULT_LIBRARY.endswith(os.path.join("Addon", "Resources", "Halo Reach.blend")))
        self.assertEqual(gp.DEFAULT_OUT, TREE)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "f")
            with open(path, "wb") as fh:
                fh.write(b"abc")
            self.assertEqual(gp.sha256_of(path), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


class TestRunBlenderTestsScript(unittest.TestCase):
    """Exit status of ``tools/run_blender_tests.sh``, driven by a fake Blender (no Blender is started).

    A run that skipped tests is never a pass (status 3, "SKIPPED"); a failure always wins (status 1).
    """
    SCRIPT = os.path.join(REPO, "tools", "run_blender_tests.sh")

    def setUp(self):
        probe = subprocess.run(["/usr/bin/python3", "-I", "-c", "import sys; print(sys.version_info[:2] == (3, 9))"],
                               stdout=subprocess.PIPE, universal_newlines=True)
        if probe.stdout.strip() != "True":
            self.skipTest("the script insists on /usr/bin/python3 being 3.9")

    def run_script(self, canned, fake_status, *args, **extra):
        """Run the script with a fake Blender that prints ``canned``; ``touch_original=True`` makes the fake append a byte to the
        file named by ``$MJOLNIR_REAL_MVAR`` (a temporary stand-in for the real map variant), as a Blender run that wrote an original would."""
        with tempfile.TemporaryDirectory() as tmp:
            fake = os.path.join(tmp, "fake-blender")
            original = os.path.join(tmp, "original.mvar")
            with open(original, "wb") as fh:
                fh.write(b"ORIGINAL")
            with open(os.path.join(tmp, "canned.txt"), "w") as fh:
                fh.write(canned)
            with open(fake, "w") as fh:
                fh.write('#!/bin/bash\ncat "%s"\n%sexit %d\n' % (
                    os.path.join(tmp, "canned.txt"), 'printf X >> "%s"\n' % original if extra.get("touch_original") else "", fake_status))
            os.chmod(fake, 0o755)
            env = dict(os.environ, BLENDER=fake, TMPDIR=tmp, MJOLNIR_REAL_MVAR=original)
            proc = subprocess.run(["/bin/bash", self.SCRIPT, "--dev"] + list(args), env=env, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
            return proc.returncode, proc.stdout

    PASSED = "PASS b01 x\nrun_all: 16 passed, 0 failed, 0 skipped\nrun_all: RESULT: PASSED\n"

    def test_all_passed_is_exit_0(self):
        status, out = self.run_script(self.PASSED, 0)
        self.assertEqual(status, 0, out)
        self.assertIn("ALL BLENDER RUNS PASSED", out)

    def test_a_run_without_a_result_line_is_never_a_pass(self):
        """Polish item 3 of gate G6: exit status 0 and no FAIL line is not enough; the run must say how it ended."""
        for canned in ("", "PASS b01 x\nrun_all: 16 passed, 0 failed, 0 skipped\n", "run_all: RESULT: PASSED\n",
                       "PASS b01 x\nrun_all: no test matches ['zzz']\n"):
            status, out = self.run_script(canned, 0)
            self.assertEqual(status, 1, "%r\n%s" % (canned, out))
            self.assertNotIn("ALL BLENDER RUNS PASSED", out)
            self.assertIn("NO RESULT LINE", out)

    def test_skipped_tests_are_never_exit_0(self):
        canned = ("PASS b01 x\nSKIP b02 y\nrun_all: 1 passed, 0 failed, 1 skipped\n  SKIPPED b02: needs the stub\n"
                  "run_all: RESULT: SKIPPED\n")
        status, out = self.run_script(canned, 3)
        self.assertEqual(status, 3, out)
        self.assertIn("SKIPPED", out)
        self.assertNotIn("ALL BLENDER RUNS PASSED", out)
        # a SKIP line is enough, whatever status the driver returned
        status, out = self.run_script("PASS b01 x\nSKIP b02 y\nrun_all: RESULT: SKIPPED\n", 0)
        self.assertEqual(status, 3, out)
        self.assertNotIn("ALL BLENDER RUNS PASSED", out)

    def test_a_run_that_changed_an_original_fails_even_when_every_test_passed(self):
        status, out = self.run_script(self.PASSED, 0)
        self.assertEqual(status, 0, out)
        self.assertIn("originals untouched", out)
        status, out = self.run_script(self.PASSED, 0, touch_original=True)
        self.assertEqual(status, 1, out)
        self.assertIn("ORIGINALS CHANGED", out)
        self.assertNotIn("ALL BLENDER RUNS PASSED", out)

    def test_both_providers_are_run_and_a_failure_in_one_fails_all(self):
        status, out = self.run_script(self.PASSED, 0, "--provider", "all")
        self.assertEqual(status, 0, out)
        self.assertIn("=== provider: stub ===", out)
        self.assertIn("=== provider: real ===", out)
        self.assertEqual(out.count("ALL BLENDER RUNS PASSED"), 1)
        status, out = self.run_script(self.PASSED, 0, "--provider", "nope")
        self.assertEqual(status, 2, out)

    def test_a_failure_wins_over_a_skip(self):
        status, out = self.run_script("FAIL b05 z\nSKIP b02 y\n", 3)
        self.assertEqual(status, 1, out)
        status, out = self.run_script("FAIL b05 z\n", 0)
        self.assertEqual(status, 1, out)
        status, out = self.run_script("PASS b01 x\n", 1)
        self.assertEqual(status, 1, out)
        self.assertIn("FAILED", out)
        self.assertNotIn("ALL BLENDER RUNS PASSED", out)


if __name__ == "__main__":
    unittest.main()
