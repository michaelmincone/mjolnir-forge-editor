"""S1 preparation: the pure parts of ``tools/build_star_mvar.py`` (no Blender, no library, nothing written outside temp).

Covers the command line, the output path policy (never inside the repository, a sample folder or beside the
template), the block ranking, the 650-object pre-flight, the independent container / hash checks (against synthetic
files built by ``helpers_container`` and, read-only and skipped loudly when absent, the one real Breakneck file),
the record verifier (each way a written file can be wrong is caught) and the parser of the add-on's export report.
The Blender part is ``tests/blender/s1_star_stub.py``.
"""
import ast
import contextlib
import dataclasses
import hashlib
import importlib.util
import io
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for _path in (HERE, os.path.join(REPO, "Addon"), os.path.join(REPO, "tests", "stubs"), os.path.join(REPO, "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import helpers_container as hc  # noqa: E402
import star_layout as sl  # noqa: E402
import stub_mvarlib as stub  # noqa: E402

TOOL = os.path.join(REPO, "tools", "build_star_mvar.py")
REAL_SAMPLE = os.path.expanduser("~/Local_Documents/Halo-MCC/forge/real-mvar-samples/0aaaf8c7-5ae6-43ba-bb4d-37c987f5e8b8.mvar")


def load_tool():
    spec = importlib.util.spec_from_file_location("build_star_mvar_under_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bs = load_tool()


def quiet_error(argv):
    """Run ``parse_args`` expecting ``SystemExit``; returns ``(code, stderr text)``."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        try:
            bs.parse_args(argv)
        except SystemExit as exc:
            return exc.code, err.getvalue()
    raise AssertionError("parse_args did not exit for %r" % (argv,))


class TestCommandLine(unittest.TestCase):
    def test_defaults(self):
        opts = bs.parse_args(["--template", "a.mvar", "--out", "b.mvar"])
        self.assertEqual((opts.template, opts.out, opts.block, opts.cells, opts.mode, opts.provider),
                         ("a.mvar", "b.mvar", "auto", None, "filled", "real"))
        self.assertEqual(opts.center, (None, None, None))
        self.assertEqual((opts.real_library, opts.keep_unrecognised, opts.overwrite, opts.allow_stub_output, opts.dry_run),
                         (False,) * 5)
        self.assertTrue(opts.unverified_rotation, "adding objects needs the gate: ticked by default")
        self.assertFalse(opts.raise_quota_max, "decision D11: the quota option is off unless asked for")
        self.assertEqual(opts.color, "KEEP")
        self.assertEqual(opts.margin, sl.DEFAULT_MARGIN)

    def test_every_option(self):
        opts = bs.parse_args(["--template", "t", "--out", "o", "--block", "Block, 1x1", "--cells", "21", "--outline",
                              "--provider", "stub", "--real-library", "--center", "1,auto,-3.5", "--margin", "2",
                              "--color", "YELLOW", "--keep-unrecognised", "--raise-quota-max", "--no-rotation-gate", "--overwrite",
                              "--allow-stub-output", "--dry-run", "--addon-module", "mjolnir_forge"])
        self.assertEqual((opts.block, opts.cells, opts.mode, opts.provider), ("Block, 1x1", 21, "outline", "stub"))
        self.assertEqual(opts.center, (1.0, None, -3.5))
        self.assertEqual((opts.margin, opts.color, opts.addon_module), (2.0, "YELLOW", "mjolnir_forge"))
        self.assertTrue(opts.real_library and opts.keep_unrecognised and opts.overwrite and opts.allow_stub_output and opts.dry_run)
        self.assertTrue(opts.raise_quota_max)
        self.assertFalse(opts.unverified_rotation)
        self.assertEqual(bs.parse_args(["--template", "t", "--out", "o", "--grid", "19"]).cells, 19, "--grid is an alias")
        self.assertIsNone(bs.parse_args(["--template", "t", "--out", "o", "--cells", "auto"]).cells)
        self.assertIsNone(bs.parse_args(["--template", "t", "--out", "o", "--cells", "AUTO"]).cells)

    def test_bad_command_lines_exit_with_status_2_and_a_message(self):
        for argv, needle in ((["--out", "o"], "--template"), (["--template", "t"], "--out"),
                             (["--template", "t", "--out", "o", "--cells", "2"], "--cells"),
                             (["--template", "t", "--out", "o", "--cells", "65"], "--cells"),
                             (["--template", "t", "--out", "o", "--cells", "x"], "invalid int value or 'auto'"),
                             (["--template", "t", "--out", "o", "--center", "1,2"], "three"),
                             (["--template", "t", "--out", "o", "--center", "a,b,c"], "not a number"),
                             (["--template", "t", "--out", "o", "--center", "nan,0,0"], "not finite"),
                             (["--template", "t", "--out", "o", "--margin", "-1"], "--margin"),
                             (["--template", "t", "--out", "o", "--provider", "magic"], "invalid choice"),
                             (["--template", "t", "--out", "o", "--color", "MAUVE"], "invalid choice")):
            code, text = quiet_error(argv)
            self.assertEqual(code, 2, argv)
            self.assertIn(needle, text, argv)

    def test_the_fixed_design_option(self):
        """S1: ``--shape pixel39`` is the 39-block star whose feet touch along faces; it replaces the grid, never mixes with it."""
        opts = bs.parse_args(["--template", "t", "--out", "o", "--shape", "pixel39"])
        self.assertEqual((opts.shape, opts.cells, opts.mode), ("pixel39", None, "filled"))
        self.assertIsNone(bs.parse_args(["--template", "t", "--out", "o"]).shape, "off by default: the sampled grid is the default")
        self.assertIsNone(bs.Options().shape)
        self.assertEqual(bs.Options(shape="pixel39").shape, "pixel39")
        for argv, needle in ((["--shape", "pixel39", "--cells", "11"], "cannot be combined"),
                             (["--shape", "pixel39", "--outline"], "cannot be combined"),
                             (["--shape", "pixel39", "--cells", "auto", "--outline"], "cannot be combined"),
                             (["--shape", "pixel40"], "invalid choice")):
            code, text = quiet_error(["--template", "t", "--out", "o"] + argv)
            self.assertEqual(code, 2, argv)
            self.assertIn(needle, text, argv)
        # --cells auto is the same as not giving it, so it may stand next to --shape
        self.assertEqual(bs.parse_args(["--template", "t", "--out", "o", "--shape", "pixel39", "--cells", "auto"]).shape, "pixel39")

    def test_the_fixed_design_is_not_replaced_by_the_auto_grid(self):
        """The auto grid (11, 34 blocks) is only chosen when neither a grid size nor a design was asked for."""
        wants = bs._wants_auto_grid
        run = types.SimpleNamespace(options=bs.Options())
        self.assertTrue(wants(run))
        run.options = bs.Options(cells=11)
        self.assertFalse(wants(run))
        run.options = bs.Options(shape="pixel39")
        self.assertFalse(wants(run))

    def test_parse_center(self):
        self.assertEqual(bs.parse_center("0,0,10"), (0.0, 0.0, 10.0))
        self.assertEqual(bs.parse_center("auto, AUTO ,1e1"), (None, None, 10.0))
        for bad in ("1", "1,2,3,4", "x,y,z", "inf,0,0"):
            with self.assertRaises(ValueError):
                bs.parse_center(bad)

    def test_arguments_after_the_double_dash(self):
        self.assertEqual(bs.script_arguments(["blender", "-b", "--python", "x.py", "--", "--template", "t"]), ["--template", "t"])
        self.assertEqual(bs.script_arguments(["blender", "-b"]), [])
        self.assertEqual(bs.script_arguments(["blender", "--"]), [])

    def test_options_reject_unknown_keywords(self):
        self.assertEqual(bs.Options(cells=21).cells, 21)
        with self.assertRaises(TypeError):
            bs.Options(celles=21)


class TestPathPolicy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mjolnir-star-test-")
        self.tpl_dir = os.path.join(self.tmp, "tpl")
        self.out_dir = os.path.join(self.tmp, "out")
        os.makedirs(self.tpl_dir)
        os.makedirs(self.out_dir)
        self.template = os.path.join(self.tpl_dir, "t.mvar")
        with open(self.template, "wb") as fh:
            fh.write(b"x")

    def tearDown(self):
        for root, dirs, files in os.walk(self.tmp, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                path = os.path.join(root, name)
                os.rmdir(path) if not os.path.islink(path) else os.remove(path)
        os.rmdir(self.tmp)

    def problems(self, out, **kwargs):
        return bs.path_problems(out, self.template, **kwargs)

    def test_a_fresh_file_in_another_folder_is_fine(self):
        self.assertEqual(self.problems(os.path.join(self.out_dir, "star.mvar")), [])

    def test_inside_the_repository_is_refused(self):
        for rel in ("star.mvar", os.path.join("docs", "star.mvar"), os.path.join("Addon", "x", "star.mvar")):
            found = self.problems(os.path.join(REPO, rel))
            self.assertTrue(any("inside the repository" in p for p in found), rel)

    def test_sample_folders_are_refused_whether_they_exist_or_not(self):
        for folder in bs.SAMPLE_FOLDERS:
            path = os.path.join(os.path.expanduser(folder), "deep", "star.mvar")
            self.assertTrue(any("protected sample folder" in p for p in self.problems(path)), folder)
        self.assertIn("~/Local_Documents/Halo-MCC/forge/real-mvar-samples", bs.SAMPLE_FOLDERS)
        self.assertIn("~/Local_Documents/Halo-MCC/variant-tool/test-samples", bs.SAMPLE_FOLDERS)

    def test_extra_protected_folders_from_the_environment(self):
        extra = os.path.join(self.tmp, "mine")
        folders = bs.protected_folders({"MJOLNIR_SAMPLES": extra + os.pathsep + "/x/y", "MJOLNIR_PROTECTED": "/p/q"})
        self.assertIn(extra, folders)
        self.assertIn("/x/y", folders)
        self.assertIn("/p/q", folders)
        self.assertTrue(any("protected sample folder" in p for p in self.problems(os.path.join(extra, "s.mvar"), protected=folders)))

    def test_beside_or_equal_to_the_template_is_refused(self):
        self.assertTrue(any("beside the template" in p for p in self.problems(os.path.join(self.tpl_dir, "new.mvar"))))
        self.assertTrue(any("overwrite the template" in p for p in self.problems(self.template, overwrite=True)))

    def test_a_link_to_the_template_is_the_template(self):
        link = os.path.join(self.out_dir, "link.mvar")
        os.symlink(self.template, link)
        self.assertTrue(any("overwrite the template" in p for p in self.problems(link, overwrite=True)))
        hard = os.path.join(self.out_dir, "hard.mvar")
        os.link(self.template, hard)
        self.assertTrue(any("overwrite the template" in p for p in self.problems(hard, overwrite=True)))

    def test_an_existing_output_needs_overwrite(self):
        out = os.path.join(self.out_dir, "star.mvar")
        with open(out, "wb") as fh:
            fh.write(b"y")
        self.assertTrue(any("already exists" in p for p in self.problems(out)))
        self.assertEqual(self.problems(out, overwrite=True), [])

    def test_extension_folder_and_empty(self):
        self.assertTrue(any("must end in .mvar" in p for p in self.problems(os.path.join(self.out_dir, "star.bin"))))
        folder = os.path.join(self.out_dir, "looks_like_a_file.mvar")
        os.mkdir(folder)
        self.assertTrue(any("is a folder" in p for p in self.problems(folder, overwrite=True)))
        os.rmdir(folder)
        self.assertEqual(self.problems(""), ["No output file was given (--out)."])

    def test_several_problems_are_all_reported(self):
        found = self.problems(os.path.join(REPO, "star.txt"))
        self.assertGreaterEqual(len(found), 2)

    def test_nothing_is_created_by_the_check(self):
        out = os.path.join(self.out_dir, "never", "star.mvar")
        self.problems(out)
        self.assertFalse(os.path.exists(os.path.dirname(out)))

    # --- a case-insensitive volume (the macOS default): the same folder under another spelling -------------------
    def need_other_spelling(self, path):
        """The same folder under a different case, or skip loudly when this volume is case-sensitive."""
        other = path.swapcase()
        if other == path or not os.path.isdir(other):
            self.skipTest("NOTICE: %s is not reachable as %s (a case-sensitive volume): the case-insensitive path checks "
                          "did not run" % (path, other))
        return other

    def test_a_mis_cased_path_into_the_repository_is_refused(self):
        for spelling in (REPO.lower(), REPO.upper(), self.need_other_spelling(REPO)):
            if not os.path.isdir(spelling):
                self.skipTest("NOTICE: %s does not exist on this volume (case-sensitive): not run" % spelling)
            found = self.problems(os.path.join(spelling, "star.mvar"))
            self.assertTrue(any("inside the repository" in p for p in found), spelling)
            found = self.problems(os.path.join(spelling, "docs", "nested", "star.mvar"))
            self.assertTrue(any("inside the repository" in p for p in found), spelling + " (deeper)")

    def test_a_mis_cased_path_into_a_sample_folder_is_refused(self):
        folder = os.path.join(self.tmp, "Samples_Mixed_Case")
        os.mkdir(folder)
        other = self.need_other_spelling(folder)
        found = self.problems(os.path.join(other, "star.mvar"), protected=[folder])
        self.assertTrue(any("protected sample folder" in p for p in found), found)
        found = self.problems(os.path.join(other, "a", "b", "star.mvar"), protected=[folder])
        self.assertTrue(any("protected sample folder" in p for p in found), found)
        os.rmdir(folder)
        # the real default folders, when they exist on this machine (the case the verifier found)
        for default in bs.SAMPLE_FOLDERS:
            real = os.path.expanduser(default)
            if not os.path.isdir(real) or not os.path.isdir(real.upper()):
                continue
            for spelling in (real.lower(), real.upper()):
                self.assertTrue(any("protected sample folder" in p for p in self.problems(os.path.join(spelling, "x.mvar"))),
                                spelling)

    def test_a_mis_cased_folder_beside_the_template_is_refused(self):
        other = self.need_other_spelling(self.tpl_dir)
        found = self.problems(os.path.join(other, "new.mvar"))
        self.assertTrue(any("beside the template" in p for p in found), found)

    def test_a_similar_looking_folder_is_not_mistaken_for_the_repository(self):
        sibling = os.path.join(os.path.dirname(REPO), "not-" + os.path.basename(REPO), "star.mvar")
        self.assertFalse(any("inside the repository" in p for p in self.problems(sibling)))
        self.assertEqual(self.problems(os.path.join(self.out_dir, "star.mvar")), [])
        self.assertTrue(bs._inside(REPO, REPO), "the folder itself counts as inside")
        self.assertFalse(bs._inside(os.path.dirname(REPO), REPO))


class TestBlockChoice(unittest.TestCase):
    def setUp(self):
        from mvarlib import api
        self.api = api
        self.tree = api.palette_tree()
        self.stock = api.stock_object_names("Breakneck")

    def test_the_building_blocks_group_is_found_in_the_committed_tree(self):
        leaves = bs.leaves_of_group(self.tree, "Building Blocks")
        self.assertIn("Block, 1x1", leaves)
        self.assertEqual(len(leaves), 26)
        self.assertEqual(bs.leaves_of_group(self.tree, "No Such Group"), [])
        self.assertEqual(bs.leaves_of_group({"groups": []}, "Building Blocks"), [])

    def test_candidates_are_stock_blocks_of_the_map_in_stock_order_and_never_invisible(self):
        names = bs.candidate_names(self.stock, bs.leaves_of_group(self.tree, "Building Blocks"))
        self.assertEqual(names[0], "Block, 1x1")
        self.assertEqual(len(names), 12)
        self.assertTrue(all(n in self.stock and "Invisible" not in n for n in names))
        self.assertNotIn("Block, 2x3", names, "not a stock object on Breakneck")
        self.assertEqual(names, [n for n in self.stock if n in set(names)], "map order")
        with_invisible = bs.candidate_names(self.stock, bs.leaves_of_group(self.tree, "Building Blocks"), allow_invisible=True)
        self.assertEqual(with_invisible, names, "the Invisible blocks are in another palette group")
        fallback = bs.candidate_names(self.stock, [], allow_invisible=True)
        self.assertIn("Block, 1x1, Invisible", fallback)
        self.assertEqual(bs.candidate_names(self.api.stock_object_names("Boneyard"), bs.leaves_of_group(self.tree, "Building Blocks")), [])

    def test_object_names_of_the_importer(self):
        self.assertEqual(bs.type_name_from_object_name("12 - Block, 1x1"), "Block, 1x1")
        self.assertEqual(bs.type_name_from_object_name("0 - Block, 1x1.001"), "Block, 1x1")
        self.assertEqual(bs.type_name_from_object_name("650 - Wall (MCC)"), "Wall (MCC)")
        for name in ("Star 000", "Block, 1x1", "", None, "x - y"):
            self.assertEqual(bs.type_name_from_object_name(name), "")

    def test_aspect_and_plan_symmetry(self):
        self.assertAlmostEqual(bs.aspect_penalty(sl.Footprint(1.0182, 1.0182, 1.0)), 0.018, places=3)
        self.assertGreater(bs.aspect_penalty(sl.Footprint(2.0, 2.0, 1.0)), 0.6)
        self.assertTrue(bs.yaw_symmetric(sl.Footprint(1.0182, 1.0182, 1.0)))
        self.assertFalse(bs.yaw_symmetric(sl.Footprint(1.0182, 2.0183, 1.0)))
        self.assertAlmostEqual(bs.plan_penalty(sl.Footprint(1.0182, 4.0155, 1.0182)), 1.372, places=3)
        self.assertTrue(bs.good_for_a_star(sl.Footprint(1.0182, 1.0182, 1.0)))
        self.assertTrue(bs.good_for_a_star(sl.Footprint(3.0, 3.0, 3.0)))
        self.assertFalse(bs.good_for_a_star(sl.Footprint(1.0182, 4.0155, 1.0182)), "square face but four deep")
        self.assertFalse(bs.good_for_a_star(sl.Footprint(2.0, 2.0, 1.0)), "a slab: twice as wide as tall")

    def test_ranking_tiers(self):
        cube = sl.Footprint(1.0182, 1.0182, 1.0)
        slab = sl.Footprint(2.0, 2.0, 1.0)
        long = sl.Footprint(1.0182, 4.0155, 1.0182)
        entries = [("slab absent", 0, slab), ("cube absent", 0, cube), ("long present", 1, long), ("cube present", 2, cube),
                   ("no model", 5, None)]
        order = [n for n, _p, _f in bs.rank_candidates(entries)]
        self.assertEqual(order, ["cube present", "long present", "cube absent", "slab absent"],
                         "in the template and cube-like, in the template, cube-like, the rest")

    def test_a_long_block_is_never_preferred_to_the_one_by_one(self):
        """Regression: the first dry run on the real map chose 'Block, 1x4' (square face, four deep) over 'Block, 1x1'.

        The footprints are the measured mesh boxes of the object library (numbers only, no game data).
        """
        measured = [("Block, 1x4", 1.0182, 4.0155, 1.0182), ("Block, 1x1", 1.0182, 1.0182, 1.0), ("Block, 1x2", 1.0182, 2.0183, 1.0),
                    ("Block, 2x2, Tall", 2.0, 2.0, 3.0), ("Block, 2x2", 2.0, 2.0, 0.9999), ("Block, 1x1, Short", 1.0176, 1.0176, 0.5),
                    ("Block, 1x1, Tall", 1.0182, 1.0182, 2.5), ("Block, 2x2, Short", 2.0, 2.0, 0.4999)]
        entries = [(n, 0, sl.Footprint(w, d, h)) for n, w, d, h in measured]
        self.assertEqual(bs.rank_candidates(entries)[0][0], "Block, 1x1")
        self.assertEqual(bs.rank_candidates(list(reversed(entries)))[0][0], "Block, 1x1", "input order does not matter")
        self.assertEqual([n for n, _p, _f in bs.rank_candidates(entries)][:2], ["Block, 1x1", "Block, 2x2, Tall"])

    def test_among_cubes_the_smaller_block_wins_then_more_examples_then_the_name(self):
        small = sl.Footprint(1.0, 1.0, 1.0)
        big = sl.Footprint(3.0, 3.0, 3.0)
        self.assertEqual([n for n, _p, _f in bs.rank_candidates([("big", 9, big), ("small", 1, small)])], ["small", "big"])
        self.assertEqual([n for n, _p, _f in bs.rank_candidates([("few", 1, small), ("many", 4, small)])], ["many", "few"])
        self.assertEqual([n for n, _p, _f in bs.rank_candidates([("b", 1, small), ("a", 1, small)])], ["a", "b"], "name breaks ties")
        self.assertEqual(bs.rank_candidates([("x", 1, None)]), [])

    def test_resolve_block_name(self):
        self.assertEqual(bs.resolve_block_name("Block, 1x1", self.stock), "Block, 1x1")
        self.assertEqual(bs.resolve_block_name("block, 1X1", self.stock), "Block, 1x1")
        self.assertIsNone(bs.resolve_block_name("Warthog", self.stock))
        self.assertIsNone(bs.resolve_block_name("", self.stock))

    def test_preflight(self):
        stock = ["Block, 1x1"]
        self.assertEqual(bs.preflight_problems("Breakneck", stock, "Block, 1x1", 300, 80), [])
        self.assertEqual(bs.preflight_problems("Breakneck", stock, None, 570, 80), [], "exactly 650 passes")
        found = bs.preflight_problems("Breakneck", stock, None, 571, 80)
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].startswith("E_TOO_MANY") and "651" in found[0] and "650" in found[0] and "at most 79" in found[0], found)
        self.assertTrue(bs.preflight_problems("Breakneck", stock, "Warthog", 0, 1)[0].startswith("E_OBJ_NAME_UNKNOWN"))
        self.assertTrue(bs.preflight_problems("", stock, None, 0, 1)[0].startswith("E_MAP_UNKNOWN"))
        self.assertEqual(len(bs.preflight_problems("", stock, "Warthog", 700, 1)), 2, "unknown map + too many")
        self.assertEqual(bs.preflight_problems("Breakneck", stock, None, 700, 1)[0][:10], "E_TOO_MANY")


class TestContainerChecks(unittest.TestCase):
    def file(self, seed=1, used=600, **kwargs):
        return hc.plain_file(seed, used, **kwargs)

    def test_split_blocks_of_a_plain_file(self):
        data = self.file()
        blocks, end = bs.split_blocks(data)
        self.assertEqual([b[0] for b in blocks], [b"_blf", b"chdr", b"mvar", b"_eof"])
        self.assertEqual([b[1] for b in blocks], [0, 0x30, 0x2F0, 0x7318])
        self.assertEqual([b[2] for b in blocks], [0x30, 0x2C0, 0x7028, 0x11])
        self.assertEqual((blocks[2][3], blocks[2][4]), (31, 1))
        self.assertEqual(end, 0x7329)

    def test_split_blocks_stops_at_garbage_and_keeps_the_trailer_out(self):
        data = self.file(trailer=b"\x00" * 100)
        blocks, end = bs.split_blocks(data)
        self.assertEqual(len(blocks), 4)
        self.assertEqual(len(data) - end, 100)
        self.assertEqual(bs.split_blocks(b"\x00" * 5), ([], 0))
        self.assertEqual(bs.split_blocks(struct.pack(">4sIHH", b"_blf", 5, 1, 1))[0], [], "size below 12 is not a block")
        self.assertEqual(bs.split_blocks(struct.pack(">4sIHH", b"_blf", 5000, 1, 1))[0], [], "runs past the end")

    def test_hash_flavour_detects_every_recipe_and_byte_order(self):
        for recipe in hc.RECIPE_NAMES:
            for endian in (">", "<"):
                data = self.file(recipe=recipe, length_endian=endian, used=700)
                flavour = bs.hash_flavour(data)
                self.assertEqual(flavour, (endian, recipe, 700), (recipe, endian))

    def test_hash_flavour_zero_unknown_and_missing(self):
        zero = self.file(hash_bytes=bytes(20))
        self.assertEqual(bs.hash_flavour(zero)[1], "zero")
        unknown = self.file(hash_bytes=bytes(range(1, 21)))
        self.assertEqual(bs.hash_flavour(unknown)[1], "unknown")
        self.assertIsNone(bs.hash_flavour(b"nothing"))
        wrong_size = bytearray(self.file())
        struct.pack_into(">I", wrong_size, 0x2F0 + 4, 0x7000)
        self.assertIsNone(bs.hash_flavour(bytes(wrong_size)))

    def test_outside_payload_identical_passes_when_only_the_stream_hash_and_length_differ(self):
        a = self.file(seed=1, used=600)
        b = self.file(seed=2, used=900)
        status, detail = bs.outside_payload_identical(a, b)
        self.assertEqual((status, detail[:8]), ("PASS", "4 blocks"), detail)
        self.assertEqual(bs.outside_payload_identical(a, a)[0], "PASS")
        c = self.file(seed=3, used=100, trailer=b"\x00" * 8)
        d = self.file(seed=4, used=100, trailer=b"\x00" * 8)
        self.assertEqual(bs.outside_payload_identical(c, d)[0], "PASS")
        self.assertIn("8 trailer", bs.outside_payload_identical(c, d)[1])

    def test_outside_payload_identical_catches_each_kind_of_change(self):
        a = self.file()
        for offset, what in ((0x10, "_blf"), (0x30 + 0x40, "chdr"), (0x2F0 + 4, "mvar block header"),
                             (0x2F0 + 0x7024, "pad bytes"), (0x7318 + 12, "_eof")):
            b = bytearray(a)
            b[offset] ^= 0xFF
            status, detail = bs.outside_payload_identical(a, bytes(b))
            self.assertEqual(status, "FAIL", what)
        status, detail = bs.outside_payload_identical(a, a + b"\x01")
        self.assertEqual(status, "FAIL")
        self.assertIn("after _eof", detail)
        status, detail = bs.outside_payload_identical(a, a[:0x2F0] + a[0x2F0:0x7318])
        self.assertEqual(status, "FAIL")
        self.assertIn("block list changed", detail)
        b = bytearray(a)
        b[0x2F0 + 40] ^= 0xFF                                  # inside the stream: allowed to differ
        self.assertEqual(bs.outside_payload_identical(a, bytes(b))[0], "PASS")

    def test_compressed_payloads_are_skipped_not_failed(self):
        wrapped = self.file(wrap_cmp=True)
        status, detail = bs.outside_payload_identical(wrapped, wrapped)
        self.assertEqual(status, "SKIP", detail)


class TestFileChecks(unittest.TestCase):
    """``_file_checks``: the library-free checks on the written bytes (hash recipe, outside bytes, inputs untouched)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mjolnir-star-filechecks-")
        self.template_path = os.path.join(self.tmp, "t.mvar")
        self.library_path = os.path.join(self.tmp, "lib.blend")

    def tearDown(self):
        for name in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, name))
        os.rmdir(self.tmp)

    def run_object(self, template_bytes, can_store=True, with_library=False):
        with open(self.template_path, "wb") as fh:
            fh.write(template_bytes)
        run = type("Run", (), {})()
        run.template_bytes = template_bytes
        run.template = self.template_path
        run.template_before = bs.fingerprint(self.template_path)
        run.can_store = can_store
        run.library_before = None
        run.library_path = None
        if with_library:
            with open(self.library_path, "wb") as fh:
                fh.write(b"library")
            run.library_path = self.library_path                # what the add-on resolved; no environment variable involved
            run.library_before = bs.fingerprint(self.library_path)
        return run

    def statuses(self, checks):
        return dict((c.name, c.status) for c in checks)

    def test_a_clean_output_with_the_same_recipe_passes(self):
        template = hc.plain_file(1, 600, recipe="plain_le32", length_endian=">")
        output = hc.plain_file(2, 900, recipe="plain_le32", length_endian=">")
        found = self.statuses(bs._file_checks(self.run_object(template), output))
        self.assertEqual(found["bytes outside the bit stream identical"], "PASS")
        self.assertEqual(found["hash recipe reproduced"], "PASS")
        self.assertEqual(found["output differs from the template"], "PASS")
        self.assertEqual(found["template untouched"], "PASS")
        self.assertNotIn("object library untouched", found)

    def test_a_different_recipe_or_byte_order_is_a_failure(self):
        template = hc.plain_file(1, 600, recipe="plain_le32", length_endian=">")
        for recipe, endian in (("salted_be32", ">"), ("plain_le32", "<"), ("data_only", ">")):
            output = hc.plain_file(2, 900, recipe=recipe, length_endian=endian)
            checks = bs._file_checks(self.run_object(template), output)
            self.assertEqual(self.statuses(checks)["hash recipe reproduced"], "FAIL", (recipe, endian))
            self.assertIn("plain_le32", [c for c in checks if c.name == "hash recipe reproduced"][0].detail)

    def test_zero_hash_templates_must_get_a_zero_hash_and_unknown_ones_are_only_noted(self):
        zero = hc.plain_file(1, 600, hash_bytes=bytes(20))
        self.assertEqual(self.statuses(bs._file_checks(self.run_object(zero), hc.plain_file(2, 700, hash_bytes=bytes(20))))
                         ["hash recipe reproduced"], "PASS")
        self.assertEqual(self.statuses(bs._file_checks(self.run_object(zero), hc.plain_file(2, 700, recipe="salted_be32")))
                         ["hash recipe reproduced"], "FAIL")
        unknown = hc.plain_file(1, 600, hash_bytes=bytes(range(1, 21)))
        self.assertEqual(self.statuses(bs._file_checks(self.run_object(unknown), hc.plain_file(2, 700)))["hash recipe reproduced"], "INFO")

    def test_a_payload_the_checks_cannot_read_is_skipped_not_passed(self):
        wrapped = hc.plain_file(1, 600, wrap_cmp=True)
        found = self.statuses(bs._file_checks(self.run_object(wrapped), wrapped + b"x"))
        self.assertEqual(found["bytes outside the bit stream identical"], "SKIP")
        self.assertEqual(found["hash recipe reproduced"], "SKIP")

    def test_a_changed_template_file_is_a_failure(self):
        template = hc.plain_file(1, 600)
        run = self.run_object(template)
        with open(self.template_path, "ab") as fh:
            fh.write(b"tamper")
        self.assertEqual(self.statuses(bs._file_checks(run, template))["template untouched"], "FAIL")

    def test_a_changed_library_file_is_a_failure(self):
        template = hc.plain_file(1, 600)
        run = self.run_object(template, with_library=True)
        saved = os.environ.pop("MJOLNIR_LIBRARY", None)          # the check follows run.library_path, not the environment
        try:
            self.assertEqual(self.statuses(bs._file_checks(run, template))["object library untouched"], "PASS")
            with open(self.library_path, "ab") as fh:
                fh.write(b"tamper")
            self.assertEqual(self.statuses(bs._file_checks(run, template))["object library untouched"], "FAIL")
            os.remove(self.library_path)
            self.assertEqual(self.statuses(bs._file_checks(run, template))["object library untouched"], "FAIL",
                             "a library that vanished has changed (no traceback)")
        finally:
            if saved is not None:
                os.environ["MJOLNIR_LIBRARY"] = saved

    def test_a_stub_that_returns_the_template_is_not_a_failure_but_a_real_writer_must_change_the_file(self):
        template = hc.plain_file(1, 600)
        self.assertEqual(self.statuses(bs._file_checks(self.run_object(template, can_store=False), template))
                         ["output differs from the template"], "SKIP")
        self.assertEqual(self.statuses(bs._file_checks(self.run_object(template, can_store=True), template))
                         ["output differs from the template"], "FAIL")


class TestRealFile(unittest.TestCase):
    """The one real Breakneck map variant, opened read-only and only here. Skipped loudly when it is absent."""

    def test_container_and_hash_of_the_real_file(self):
        if not os.path.isfile(REAL_SAMPLE):
            self.skipTest("NOTICE: the real map variant %s is absent; the real-file checks of the star tool did not run" % REAL_SAMPLE)
        with open(REAL_SAMPLE, "rb") as fh:
            data = fh.read()
        blocks, end = bs.split_blocks(data)
        self.assertEqual([(b[0], b[1], b[2]) for b in blocks],
                         [(b"_blf", 0, 0x30), (b"chdr", 0x30, 0x2C0), (b"mvar", 0x2F0, 0x7028), (b"_eof", 0x7318, 0x11)])
        self.assertEqual(end, 29481)
        self.assertEqual(len(data) - end, 29911)
        self.assertEqual(data[end:], bytes(29911), "the zero padding after _eof")
        self.assertEqual(bs.hash_flavour(data), (">", "plain_le32", 13311), "NOTES.md D9, re-derived without the library")
        self.assertEqual(bs.outside_payload_identical(data, data)[0], "PASS")
        self.assertEqual(hashlib.sha256(data).hexdigest(), "e514a53b61977a897ac9dbf7225085aa01b5b255f3c8079b5938ef87579bb254")


def make_before_after(extra=0):
    """``(before, after, positions)``: the canned Forge World and a copy with ``extra`` new Fixed blocks."""
    before = stub.CANNED
    positions = [(float(i), 0.0, 10.0) for i in range(extra)]
    new = [stub.make_record(20 + i, "Forge World", "Block, 1x1", p, placement=0x4C) for i, p in enumerate(positions)]
    info = dataclasses.replace(before.info, occupied=before.info.occupied + extra)
    after = dataclasses.replace(before, info=info, objects=list(before.objects) + new)
    return before, after, positions


class TestVerifyRecords(unittest.TestCase):
    TOL = (0.001, 0.001, 0.001)

    def run_checks(self, after_transform=None, extra=4, block="Block, 1x1", positions=None, can_store=True):
        before, after, expected = make_before_after(extra)
        if after_transform is not None:
            after = after_transform(after)
        return bs.verify_records(before, after, expected if positions is None else positions, block, self.TOL, can_store)

    def failed(self, checks):
        return sorted(c.name for c in checks if c.failed)

    def test_a_correct_output_passes_everything(self):
        checks = self.run_checks()
        self.assertEqual(self.failed(checks), [])
        names = [c.name for c in checks]
        for name in ("original objects unchanged", "map header and body fields unchanged", "star block count",
                     "star block type", "star block positions", "star blocks Fixed", "star blocks vertical", "occupied count"):
            self.assertEqual(dict((c.name, c.status) for c in checks)[name], "PASS", name)
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(c.line().startswith("[PASS] ") for c in checks))

    def test_a_missing_block_is_caught(self):
        checks = self.run_checks(lambda a: dataclasses.replace(a, objects=a.objects[:-1], info=dataclasses.replace(
            a.info, occupied=a.info.occupied - 1)))
        self.assertEqual(self.failed(checks), ["occupied count", "star block count", "star block positions"])

    def test_an_extra_block_is_caught(self):
        extra = stub.make_record(99, "Forge World", "Block, 1x1", (50.0, 0.0, 10.0), placement=0x4C)
        checks = self.run_checks(lambda a: dataclasses.replace(a, objects=list(a.objects) + [extra]))
        self.assertIn("star block count", self.failed(checks))
        self.assertIn("star block positions", self.failed(checks))

    def test_a_position_error_beyond_the_tolerance_is_caught_and_within_it_is_not(self):
        def move(offset):
            def transform(after):
                objs = list(after.objects)
                objs[-1] = dataclasses.replace(objs[-1], position=(objs[-1].position[0] + offset, 0.0, 10.0))
                return dataclasses.replace(after, objects=objs)
            return transform
        self.assertEqual(self.failed(self.run_checks(move(0.0009))), [])
        self.assertEqual(self.failed(self.run_checks(move(0.002))), ["star block positions"])

    def test_the_wrong_type_physics_or_a_tilt_is_caught(self):
        def alter(**fields):
            def transform(after):
                objs = list(after.objects)
                objs[-1] = dataclasses.replace(objs[-1], **fields)
                return dataclasses.replace(after, objects=objs)
            return transform
        self.assertEqual(self.failed(self.run_checks(alter(type_name="Block, 2x2"))), ["star block type"])
        self.assertEqual(self.failed(self.run_checks(alter(physics=3))), ["star blocks Fixed"])
        self.assertEqual(self.failed(self.run_checks(alter(physics=0))), ["star blocks Fixed"])
        self.assertEqual(self.failed(self.run_checks(alter(up=(0.0, 0.5, 0.866)))), ["star blocks vertical"])

    def test_a_changed_original_or_a_removed_original_is_caught(self):
        def change(after):
            objs = list(after.objects)
            objs[0] = dataclasses.replace(objs[0], position=(objs[0].position[0] + 0.5,) + objs[0].position[1:])
            return dataclasses.replace(after, objects=objs)

        def drop(after):
            return dataclasses.replace(after, objects=after.objects[1:], info=dataclasses.replace(after.info, occupied=after.info.occupied - 1))
        checks = self.run_checks(change)
        self.assertEqual(self.failed(checks), ["original objects unchanged"])
        detail = [c for c in checks if c.failed][0].detail
        self.assertIn("1 changed (1)", detail)
        self.assertIn("original objects unchanged", self.failed(self.run_checks(drop)))
        token = lambda a: dataclasses.replace(a, objects=[dataclasses.replace(a.objects[0], raw=b"\x00" + a.objects[0].raw[1:])] + list(a.objects[1:]))
        self.assertEqual(self.failed(self.run_checks(token)), ["original objects unchanged"], "the identity token counts")

    def test_header_and_budget_words_must_not_move(self):
        for field, value in (("palette_crc", 1), ("spent_budget_raw", 999), ("max_budget_raw", 1), ("title", "x"),
                             ("bounds", (0.0, 1.0, 0.0, 1.0, 0.0, 1.0)), ("hash_flavour", "plain_le32/>"), ("labels", ["a"])):
            checks = self.run_checks(lambda a, f=field, v=value: dataclasses.replace(a, info=dataclasses.replace(a.info, **{f: v})))
            self.assertEqual(self.failed(checks), ["map header and body fields unchanged"], field)

    def test_two_objects_in_one_slot_is_caught(self):
        def dup(after):
            return dataclasses.replace(after, objects=list(after.objects) + [after.objects[-1]])
        self.assertIn("slots are unique", self.failed(self.run_checks(dup)))

    def test_the_650_limit_is_checked(self):
        before, after, expected = make_before_after(3)
        info = dataclasses.replace(after.info, occupied=651)
        checks = bs.verify_records(before, dataclasses.replace(after, info=info), expected, "Block, 1x1", self.TOL)
        self.assertIn("650-object limit", self.failed(checks))

    def test_a_stub_that_cannot_remember_skips_the_star_checks_but_still_compares_the_originals(self):
        before, after, _expected = make_before_after(0)
        checks = bs.verify_records(before, after, [(0.0, 0.0, 0.0)] * 4, "Block, 1x1", self.TOL, can_store=False)
        status = dict((c.name, c.status) for c in checks)
        self.assertEqual(status["original objects unchanged"], "PASS")
        self.assertEqual(status["star block count"], "SKIP")
        self.assertEqual(self.failed(checks), [])
        changed = dataclasses.replace(after, objects=after.objects[1:])
        self.assertTrue([c for c in bs.verify_records(before, changed, [], "Block, 1x1", self.TOL, can_store=False) if c.failed])

    def test_order_of_the_new_objects_does_not_matter(self):
        before, after, expected = make_before_after(6)
        shuffled = dataclasses.replace(after, objects=list(reversed(after.objects)))
        self.assertEqual(self.failed(bs.verify_records(before, shuffled, expected[::-1], "Block, 1x1", self.TOL)), [])


class TestDiffReport(unittest.TestCase):
    def test_added_objects_are_listed_by_type_and_slot(self):
        before, after, _positions = make_before_after(12)
        lines = bs.diff_lines(before, after)
        self.assertEqual(lines[0], "diff     : 12 object(s) added, 0 removed, 0 changed, 5 unchanged (of 5 in the template)")
        self.assertIn("added 12 x 'Block, 1x1' in slot(s) 20, 21, 22, 23, 24, 25, 26, 27 ... ", lines[1] + " ")
        self.assertEqual(len(lines), 2)

    def test_removed_and_changed_objects_are_reported_too(self):
        before, after, _positions = make_before_after(2)
        objs = list(after.objects)
        objs[0] = dataclasses.replace(objs[0], position=(9.0, 9.0, 9.0))
        gone = objs.pop(1)
        lines = bs.diff_lines(before, dataclasses.replace(after, objects=objs))
        self.assertEqual(lines[0], "diff     : 2 object(s) added, 1 removed, 1 changed, 3 unchanged (of 5 in the template)")
        self.assertTrue(any("removed 1 x '%s' in slot(s) %d" % (gone.type_name, gone.slot) in line for line in lines), lines)
        self.assertTrue(any("changed 1 x 'Block, 1x1' in slot(s) 1" in line for line in lines), lines)

    def test_an_unchanged_file_has_a_one_line_diff(self):
        before, _after, _positions = make_before_after(0)
        self.assertEqual(bs.diff_lines(before, before), ["diff     : 0 object(s) added, 0 removed, 0 changed, 5 unchanged (of 5 in the template)"])


class TestReportParser(unittest.TestCase):
    REPORT = "\n".join([
        "Mjolnir export report", "Target: /x/star.mvar", "Result: REFUSED, nothing was written", "",
        "Problems (2 error(s), 1 warning(s))",
        "  ERROR E_QUOTA: Palette entry 63 (Block, 1x1) would have 85 placed; the maximum on this map variant is 80.",
        "  ERROR E_ROTATION_GATED 'Star 000': Object 'Star 000' has a new or changed rotation.",
        "  WARNING W_CACHED_TYPE_ASSUMED: The object class of the new 'Block, 1x1' was assumed.",
        "", "Changes",
        "  KEPT slot 1 \"1 - Block, 1x1\" stub", "  KEPT slot 2 \"2 - Assault Rifle\" stub",
        "  ADDED slot - \"Star 000\" stub", "  NOT IMPORTED slot 7 \"x\" y", "", "Stats", "  Objects: 2 before, 3 after (limit 650)"])

    def test_issues_and_change_counts(self):
        issues, changes = bs.parse_report(self.REPORT)
        self.assertEqual([(s, c) for s, c, _l in issues],
                         [("ERROR", "E_QUOTA"), ("ERROR", "E_ROTATION_GATED"), ("WARNING", "W_CACHED_TYPE_ASSUMED")])
        self.assertEqual(changes, {"KEPT": 2, "ADDED": 1, "NOT IMPORTED": 1})
        self.assertEqual(bs.parse_report(""), ([], {}))

    def test_type_specific_codes_are_the_block_dependent_ones(self):
        for code in ("E_QUOTA", "E_FLAG_UNVERIFIED", "E_CACHED_TYPE_UNKNOWN", "E_OBJ_NOT_STOCK", "E_OBJ_NAME_UNKNOWN"):
            self.assertIn(code, bs.TYPE_SPECIFIC_CODES)
        for code in ("E_ROTATION_GATED", "E_OUT_OF_BOUNDS", "E_TOO_MANY", "E_CAPACITY", "E_INTERNAL", "E_MAP_UNKNOWN",
                     "E_PATH_PROTECTED", "E_TEMPLATE_UNREADABLE"):
            self.assertNotIn(code, bs.TYPE_SPECIFIC_CODES)
        for code in bs.HINTS:
            self.assertTrue(code.startswith("E_"))


class TestModuleShape(unittest.TestCase):
    def test_importing_the_tool_needs_no_blender_and_runs_nothing(self):
        with open(TOOL, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        top = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                top.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                top.add((node.module or "").split(".")[0])
        self.assertNotIn("bpy", top)
        self.assertNotIn("mathutils", top)
        self.assertEqual(top, set(["argparse", "hashlib", "importlib", "math", "os", "re", "struct", "sys", "tempfile", "time",
                                   "star_layout"]))
        guard = [n for n in tree.body if isinstance(n, ast.If) and "__main__" in ast.dump(n.test)]
        self.assertEqual(len(guard), 1, "main() is guarded")

    def test_the_caveats_name_the_unverified_things(self):
        text = " ".join(bs.CAVEATS)
        for needle in ("UNVERIFIED IN GAME", "Xbox", "Waypoint", "Budget", "Orientation"):
            self.assertIn(needle, text)

    def test_the_tool_never_writes_to_these_places_by_construction(self):
        with open(TOOL, "r", encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn("save_as_mainfile", source)
        self.assertNotIn("shutil.rmtree", source)
        self.assertEqual(source.count('open(run.template'), 1, "the template is only ever opened once, for reading")
        for line in source.splitlines():
            if "open(" in line and "template" in line:
                self.assertIn('"rb"', line)


class FakeMods(object):
    """Stands in for the add-on's modules: ``palette.library_path()`` answers what the test says the add-on resolved."""

    def __init__(self, resolved):
        self.bpy = object()
        self.name = "fake_addon"
        self.palette = types.SimpleNamespace(library_path=lambda: resolved)
        self.provider = types.SimpleNamespace(set_provider=lambda module: None)


class TestFixedDesignInTheRequestStage(unittest.TestCase):
    """S1: ``stage_request`` turns ``--shape`` into the cells of the design (no Blender, nothing written)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mjolnir-star-shape-")
        os.makedirs(os.path.join(self.tmp, "in"))
        os.makedirs(os.path.join(self.tmp, "out"))
        self.template = os.path.join(self.tmp, "in", "t.mvar")
        with open(self.template, "wb") as fh:
            fh.write(b"not a map variant, only read for its fingerprint")
        self.out = os.path.join(self.tmp, "out", "o.mvar")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def request(self, **options):
        opts = bs.Options(template=self.template, out=self.out, provider=stub, **options)
        log = bs.Log(echo=False)
        run = bs.Run(opts, log, bs.BuildResult())
        bs.stage_request(run)
        return run, "\n".join(log.lines)

    def test_the_design_becomes_the_cells_and_the_log_says_so(self):
        run, text = self.request(shape="pixel39")
        self.assertEqual(run.cells, sl.named_shape("pixel39"))
        self.assertEqual(run.grid, 9)
        self.assertIn("design pixel39", text)
        self.assertIn("star     : 39 blocks (fixed design 'pixel39', 9 columns)", text)

    def test_without_a_design_the_old_behaviour_is_unchanged(self):
        run, text = self.request(cells=11)
        self.assertEqual((len(run.cells), run.grid), (34, 11))
        self.assertIn("star     : 34 blocks (filled, grid 11)", text)
        run, text = self.request()
        self.assertEqual((run.cells, run.grid), ([], None), "auto: chosen after the template is read")

    def test_a_design_and_a_grid_never_mix_even_through_the_api(self):
        for mixed in ({"shape": "pixel39", "cells": 11}, {"shape": "pixel39", "mode": "outline"}):
            with self.assertRaises(bs.StarBuildError) as caught:
                self.request(**mixed)
            self.assertEqual(caught.exception.kind, "refused")
            self.assertIn("cannot be combined", str(caught.exception))

    def test_an_unknown_design_is_refused(self):
        with self.assertRaises(bs.StarBuildError) as caught:
            self.request(shape="pixel40")
        self.assertEqual(caught.exception.kind, "refused")
        self.assertIn("pixel39", str(caught.exception), "the known designs are named")

    def test_the_650_pre_flight_still_judges_the_design(self):
        cells = sl.named_shape("pixel39")
        self.assertEqual(bs.preflight_problems("Breakneck", ["Block, 1x1"], "Block, 1x1", 610, len(cells)), [])
        self.assertEqual(bs.preflight_problems("Breakneck", ["Block, 1x1"], "Block, 1x1", 611, len(cells)), [])
        problems = bs.preflight_problems("Breakneck", ["Block, 1x1"], "Block, 1x1", 612, len(cells))
        self.assertEqual(len(problems), 1)
        self.assertIn("E_TOO_MANY", problems[0])


class TestLibraryResolution(unittest.TestCase):
    """Which object library is linked: what the add-on RESOLVES (preference, then $MJOLNIR_LIBRARY, then ``Resources``).

    The real ``Halo Reach.blend`` is never touched here: ``bs.REPO`` is pointed at a scratch folder holding a tiny fake of it.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mjolnir-star-libres-")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(self.repo, "Addon", "Resources"))
        self.real = os.path.join(self.repo, "Addon", "Resources", "Halo Reach.blend")
        self.standin_dir = os.path.join(self.tmp, "standin")
        os.makedirs(self.standin_dir)
        self.standin = os.path.join(self.standin_dir, "Halo Reach.blend")
        for path, payload in ((self.real, b"FAKE-REAL-LIBRARY"), (self.standin, b"STAND-IN")):
            with open(path, "wb") as fh:
                fh.write(payload)
        self.saved = (bs.REPO, bs.load_modules, os.environ.get("MJOLNIR_LIBRARY"))
        bs.REPO = self.repo
        os.environ.pop("MJOLNIR_LIBRARY", None)

    def tearDown(self):
        bs.REPO, bs.load_modules, env = self.saved
        if env is None:
            os.environ.pop("MJOLNIR_LIBRARY", None)
        else:
            os.environ["MJOLNIR_LIBRARY"] = env
        for root, dirs, files in os.walk(self.tmp, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                path = os.path.join(root, name)
                os.rmdir(path) if not os.path.islink(path) else os.remove(path)
        os.rmdir(self.tmp)

    def stage(self, resolved, **options):
        bs.load_modules = lambda preferred=None: FakeMods(resolved)
        opts = bs.Options(template=os.path.join(self.tmp, "t.mvar"), out=os.path.join(self.tmp, "o.mvar"), provider=stub,
                          **options)
        log = bs.Log(echo=False)
        run = bs.Run(opts, log, bs.BuildResult())
        bs.stage_environment(run)
        return run, log

    # --- the pure decisions ----------------------------------------------------------------------------------------
    def test_the_real_library_of_a_checkout_is_in_addon_resources(self):
        self.assertEqual(bs.repo_library_path(), self.real)
        self.assertEqual(bs.repo_library_path("/x"), os.path.join("/x", "Addon", "Resources", "Halo Reach.blend"))

    def test_same_file_sees_through_links_and_spelling(self):
        link = os.path.join(self.tmp, "link.blend")
        os.symlink(self.real, link)
        hard = os.path.join(self.tmp, "hard.blend")
        os.link(self.real, hard)
        self.assertTrue(bs.same_file(self.real, self.real))
        self.assertTrue(bs.same_file(link, self.real))
        self.assertTrue(bs.same_file(hard, self.real))
        self.assertFalse(bs.same_file(self.standin, self.real))
        self.assertFalse(bs.same_file(os.path.join(self.tmp, "missing.blend"), self.real))
        self.assertTrue(bs.same_file(os.path.join(self.tmp, "missing.blend"), os.path.join(self.tmp, "missing.blend")))
        self.assertFalse(bs.same_file("", self.real))
        self.assertFalse(bs.same_file(None, self.real))
        other = self.real.swapcase()
        if os.path.isfile(other):
            self.assertTrue(bs.same_file(other, self.real), "the same file under another spelling (case-insensitive volume)")

    def test_the_decision_table(self):
        real = self.real
        # without --real-library the real library is refused, however the add-on got there
        text = bs.library_problem(real, False, real)
        self.assertIn("--real-library", text)
        self.assertIn("$MJOLNIR_LIBRARY", text)
        self.assertIn("stand-in", text)
        self.assertIn("Resources", text, "the fallback is named")
        link = os.path.join(self.tmp, "link.blend")
        os.symlink(real, link)
        self.assertIsNotNone(bs.library_problem(link, False, real), "a link to the real library is the real library")
        self.assertIsNone(bs.library_problem(self.standin, False, real))
        # with --real-library the add-on must really resolve to it
        self.assertIsNone(bs.library_problem(real, True, real))
        text = bs.library_problem(self.standin, True, real)
        self.assertIn("preference", text)
        self.assertIn("overrides", text)
        self.assertIn(self.standin, text, "names the file the add-on resolved")

    def test_the_source_named_in_the_log(self):
        real = self.real
        self.assertEqual(bs.library_source(self.standin, {"MJOLNIR_LIBRARY": self.standin}, real), "$MJOLNIR_LIBRARY")
        self.assertEqual(bs.library_source(self.standin, {"MJOLNIR_LIBRARY": self.standin_dir}, real), "$MJOLNIR_LIBRARY",
                         "an environment value that names a folder gets the file name appended")
        self.assertEqual(bs.library_source(real, {}, real), "the add-on's Resources folder")
        self.assertEqual(bs.library_source(self.standin, {}, real), "the add-on preference 'Library path'")
        self.assertEqual(bs.library_source(self.standin, {"MJOLNIR_LIBRARY": real}, real), "the add-on preference 'Library path'",
                         "the environment names another file than the one resolved: the preference won")
        self.assertEqual(bs.library_source(real, {"MJOLNIR_LIBRARY": real}, real), "$MJOLNIR_LIBRARY")

    # --- stage_environment ------------------------------------------------------------------------------------------
    def test_the_fallback_to_the_real_library_is_refused_before_it_is_read(self):
        with self.assertRaises(bs.StarBuildError) as caught:
            self.stage(self.real)                                  # no --real-library, no $MJOLNIR_LIBRARY: the Resources fallback
        self.assertEqual(caught.exception.kind, "refused")
        self.assertIn("pass --real-library", str(caught.exception))
        self.assertIsNone(os.environ.get("MJOLNIR_LIBRARY"), "nothing was exported to the environment")

    def test_the_preference_overriding_real_library_is_refused(self):
        with self.assertRaises(bs.StarBuildError) as caught:
            self.stage(self.standin, real_library=True)             # the add-on preference points at a stand-in
        self.assertEqual(caught.exception.kind, "refused")
        self.assertIn("overrides", str(caught.exception))

    def test_a_stand_in_is_logged_by_its_real_path_and_fingerprinted(self):
        os.environ["MJOLNIR_LIBRARY"] = self.standin
        run, log = self.stage(self.standin)
        self.assertEqual(run.library_path, self.standin)
        self.assertEqual(run.library_before, bs.fingerprint(self.standin))
        text = "\n".join(log.lines)
        self.assertIn("library  : %s ($MJOLNIR_LIBRARY; linked read-only; sha256 " % self.standin, text)
        self.assertNotIn("(the add-on preference)", text)
        template = hc.plain_file(1, 600)
        run.template_bytes, run.template, run.can_store = template, os.path.join(self.tmp, "t.mvar"), True
        with open(run.template, "wb") as fh:
            fh.write(template)
        run.template_before = bs.fingerprint(run.template)
        found = dict((c.name, c.status) for c in bs._file_checks(run, hc.plain_file(2, 900)))
        self.assertEqual(found["object library untouched"], "PASS", "checked although --real-library was not given")
        with open(self.standin, "ab") as fh:
            fh.write(b"tamper")
        found = dict((c.name, c.status) for c in bs._file_checks(run, hc.plain_file(2, 900)))
        self.assertEqual(found["object library untouched"], "FAIL")

    def test_a_library_chosen_by_the_preference_is_fingerprinted_too(self):
        run, log = self.stage(self.standin)                        # no environment variable: the preference named it
        self.assertEqual(run.library_before, bs.fingerprint(self.standin))
        self.assertIn("(the add-on preference 'Library path'; linked read-only", "\n".join(log.lines))

    def test_the_real_library_on_request_is_exported_logged_and_fingerprinted(self):
        run, log = self.stage(self.real, real_library=True)
        self.assertEqual(os.environ["MJOLNIR_LIBRARY"], self.real)
        self.assertEqual(run.library_path, self.real)
        self.assertEqual(run.library_before, bs.fingerprint(self.real))
        self.assertIn("library  : %s (--real-library; linked read-only" % self.real, "\n".join(log.lines))

    def test_a_missing_library_is_reported_not_fingerprinted(self):
        missing = os.path.join(self.tmp, "nowhere", "Halo Reach.blend")
        run, log = self.stage(missing)
        self.assertIsNone(run.library_before)
        self.assertEqual(run.library_path, missing)
        self.assertIn("NOT FOUND", "\n".join(log.lines))

    def test_real_library_needs_the_file_of_the_checkout(self):
        os.remove(self.real)
        with self.assertRaises(bs.StarBuildError) as caught:
            self.stage(self.real, real_library=True)
        self.assertIn("was not found", str(caught.exception))
        self.assertEqual(caught.exception.kind, "failed")


class TestNoBytecodeAndWrappers(unittest.TestCase):
    """The documented command must leave nothing in the repository: no ``__pycache__``; paths relative to the caller."""

    def source_lines(self, path):
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().splitlines()

    def test_the_script_turns_bytecode_off_before_importing_its_sibling(self):
        with open(TOOL, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        off = sibling = None
        for index, node in enumerate(tree.body):
            if (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Attribute)
                    and node.targets[0].attr == "dont_write_bytecode" and getattr(node.targets[0].value, "id", "") == "sys"
                    and getattr(node.value, "value", None) is True):
                off = index
            if isinstance(node, ast.Import) and any(a.name == "star_layout" for a in node.names):
                sibling = index
        self.assertIsNotNone(off, "sys.dont_write_bytecode = True")
        self.assertIsNotNone(sibling)
        self.assertLess(off, sibling, "before 'import star_layout'")

    def test_running_the_script_turns_bytecode_off_and_leaves_no_pycache(self):
        scratch = tempfile.mkdtemp(prefix="mjolnir-star-bytecode-")
        try:
            for name in ("build_star_mvar.py", "star_layout.py"):
                with open(os.path.join(REPO, "tools", name), "rb") as fh:
                    data = fh.read()
                with open(os.path.join(scratch, name), "wb") as fh:
                    fh.write(data)
            script = os.path.join(scratch, "build_star_mvar.py")
            env = dict((k, v) for k, v in os.environ.items() if not k.startswith("PYTHON"))
            # run the script's code the way Blender does (as a script: its own file is never cached), without calling main()
            code = ("import sys; assert not sys.dont_write_bytecode; "
                    "exec(compile(open(%r).read(), %r, 'exec'), {'__name__': 'probe', '__file__': %r}); "
                    "print('FLAG', sys.dont_write_bytecode, 'PREFIX', sys.pycache_prefix)" % (script, script, script))

            def flag_after_import():
                # No PYTHON* variable and no -I / -E (Apple's 3.9 turns bytecode off for those by itself, which would make
                # the control below pass for the wrong reason): only the module's own line can keep the bytecode away.
                # The folder holds nothing but the two copies made above.
                done = subprocess.run([sys.executable, "-c", code], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, env=env, timeout=60, cwd=scratch, universal_newlines=True)
                self.assertEqual(done.returncode, 0, done.stdout[-500:])
                return done.stdout.split()

            found = flag_after_import()
            self.assertEqual(found[:2], ["FLAG", "True"], "the script switches bytecode off")
            # Apple's 3.9 keeps all bytecode in ~/Library/Caches (sys.pycache_prefix), so it can never write beside the
            # source; the file check below is therefore only made on an interpreter that would (Blender's 3.13).
            beside_the_source = found[3] == "None"
            if beside_the_source:
                self.assertEqual(sorted(os.listdir(scratch)), ["build_star_mvar.py", "star_layout.py"], "no __pycache__ appeared")
            # control: without the line, the same run leaves bytecode behind (so the checks above CAN fail)
            with open(script, "r", encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("sys.dont_write_bytecode = True", text)
            with open(script, "w", encoding="utf-8") as fh:
                fh.write(text.replace("sys.dont_write_bytecode = True", "pass", 1))
            found = flag_after_import()
            self.assertEqual(found[:2], ["FLAG", "False"], "control: the detector sees the flag when the line is absent")
            if beside_the_source:
                self.assertIn("__pycache__", os.listdir(scratch), "control: the detector sees bytecode when it is written")
        finally:
            for root, dirs, files in os.walk(scratch, topdown=False):
                for name in files:
                    os.remove(os.path.join(root, name))
                for name in dirs:
                    os.rmdir(os.path.join(root, name))
            os.rmdir(scratch)

    def test_both_wrappers_export_the_no_bytecode_variable_before_starting_blender(self):
        for name in ("run_star_build.sh", "run_star_tests.sh"):
            lines = self.source_lines(os.path.join(REPO, "tools", name))
            export = [i for i, line in enumerate(lines) if line.strip().startswith("export PYTHONDONTWRITEBYTECODE=1")]
            launch = [i for i, line in enumerate(lines) if line.lstrip().startswith('"$BL"')]
            self.assertTrue(export, name + ": exports PYTHONDONTWRITEBYTECODE=1")
            self.assertTrue(launch, name + ": starts Blender")
            self.assertLess(export[0], launch[0], name + ": the variable is exported before Blender starts")
            # Blender's embedded Python ignores PYTHON* variables unless it is started with --python-use-system-env (measured
            # on 5.2.1: sys.flags.ignore_environment is 1), so the export alone keeps no bytecode out of the repository
            runs = [lines[i] for i in launch if "--factory-startup" in lines[i]]
            self.assertTrue(runs, name + ": starts a headless Blender run")
            for line in runs:
                self.assertIn("--python-use-system-env", line, name + ": " + line.strip())
            unset = "\n".join(line for line in lines if line.startswith("unset "))
            for variable in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE"):
                self.assertIn(variable, unset, name + ": --python-use-system-env would honour " + variable)
        tests = "\n".join(self.source_lines(os.path.join(REPO, "tools", "run_star_tests.sh")))
        for interpreter_call in re.findall(r'"\$(?:py|PY39)" [^\n|]*tools/\w+\.py', tests):
            self.assertIn(" -B ", interpreter_call, "python is started with -B: " + interpreter_call)

    def test_the_build_wrapper_keeps_the_callers_directory(self):
        lines = self.source_lines(os.path.join(REPO, "tools", "run_star_build.sh"))
        code = [line for line in lines if not line.lstrip().startswith("#")]
        self.assertFalse([line for line in code if re.match(r"\s*cd\s", line)],
                         "a bare 'cd' would make relative --template / --out paths mean something else than the caller meant")
        joined = re.sub(r"\\\n\s*", " ", "\n".join(code))             # a command continued with a trailing backslash
        launch = [line for line in joined.splitlines() if line.lstrip().startswith('"$BL"')]
        self.assertEqual(len(launch), 1)
        self.assertIn('--python "$REPO/tools/build_star_mvar.py"', launch[0], "the script is given by absolute path")
        header = " ".join(line for line in lines if line.startswith("#"))
        self.assertIn("Relative --template / --out paths are resolved against the directory you run this from", header)

    def test_the_wrapper_help_is_the_whole_header_and_nothing_else(self):
        lines = self.source_lines(os.path.join(REPO, "tools", "run_star_build.sh"))
        shown = re.search(r"sed -n 2,(\d+)p", "\n".join(lines))
        last_header = max(i + 1 for i, line in enumerate(lines) if line.startswith("#"))
        self.assertEqual(int(shown.group(1)), last_header, "--help prints lines 2..%d" % last_header)
        tests_lines = self.source_lines(os.path.join(REPO, "tools", "run_star_tests.sh"))
        shown = re.search(r"sed -n 2,(\d+)p", "\n".join(tests_lines))
        last_header = max(i + 1 for i, line in enumerate(tests_lines) if line.startswith("#"))
        self.assertEqual(int(shown.group(1)), last_header)


if __name__ == "__main__":
    unittest.main()
