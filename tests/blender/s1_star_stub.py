"""S1 (NOTES.md D10 / D10a): the block-star build script against the stub providers and the SYNTHETIC stand-in library.

``tools/build_star_mvar.py`` is driven in-process (and once as a child Blender, the way the owner will run it):

* end to end against the plain stub (``tests/stubs/stub_mvarlib.py``): the stub's ``LAST_EXPORT`` holds the five
  original objects (slots and tokens untouched) and the star's blocks (count, positions, physics Fixed, stock type
  name and id, no slot claimed, flags copied from the template's own block), through the add-on's own operators;
* against the remembering double (``tests/stubs/stub_roundtrip.py``): the whole verification (count, positions within
  the quantisation tolerance, originals bit-identical, header fields) passes, and every deliberately wrong file it can
  produce (a block dropped / shifted / not Fixed / of another type / an extra block / a changed original / a changed
  hash recipe) is caught, renamed ``*.REJECTED`` and exits non-zero;
* refusals write no file: more blocks than the 650-object limit allows (and the exact boundary), a non-stock block name,
  a centre outside the bounds, an output path inside the repository / a sample folder / beside the template, the
  library's own refusals (quota with the next block type tried, flag mismatch, rotation gate), a missing real library;
* the mesh box of a library collection is measured with its rotation, scale, parent and instance offset, and the blocks are
  spaced by it end to end (a stand-in whose ``Block, 1x1`` is 1.0182 x 1.0182 x 1.0 like the real one, not a unit cube);
* the library that is linked is the one the add-on RESOLVES (preference, then ``$MJOLNIR_LIBRARY``, then ``Resources``): the
  log names it and the library-untouched check covers it; the real library is refused without ``--real-library`` and
  ``--real-library`` is refused when the preference overrides it;
* the wrapper ``tools/run_star_build.sh`` run from a scratch copy of the checkout: relative paths mean the caller's
  directory, the repository copy gets no ``__pycache__``.

Never touches the real ``Halo Reach.blend`` (stand-in only) or any real map variant.

    blender -b --factory-startup --python-exit-code 1 --addons <add-on module> \\
        --python tests/blender/s1_star_stub.py -- --provider stub
"""
import math
import os
import shutil
import subprocess
import sys
import types

import bpy

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bl_common  # noqa: E402
from bl_common import check, check_close, check_eq  # noqa: E402

REPO = bl_common.REPO
sys.path.insert(0, os.path.join(REPO, "tools"))
import build_star_mvar as star  # noqa: E402
import star_layout as sl  # noqa: E402

ID = "s1"
TITLE = "block star: end to end against the stubs, verification, refusals, measured footprint"
NEEDS_STUB = True

STAND_IN = sl.Footprint(1.0, 1.0, 1.0, (0.0, 0.0, 0.5))      # the stand-in library's cube: 1 x 1 x 1, origin at the bottom centre
ODD_BLOCK = sl.Footprint(1.0182, 1.0182, 1.0, (0.0, 0.0, 0.5))   # the odd library's "Block, 1x1": the size of the real one
FOREST_BOUNDS = (-240.0, 240.0, -345.0, 345.0, -70.0, 70.0)  # the canned Forge World


class Fixture(object):
    """Paths and options for one scenario (template and output in different folders, both in the test's temp dir)."""

    def __init__(self, env, counter=[0]):
        counter[0] += 1
        self.env = env
        self.dir_tpl = os.path.join(env.tmp, "tpl%d" % counter[0])
        self.dir_out = os.path.join(env.tmp, "out%d" % counter[0])
        os.makedirs(self.dir_tpl)
        os.makedirs(self.dir_out)
        self.template = os.path.join(self.dir_tpl, "template.mvar")
        self.out = os.path.join(self.dir_out, "star.mvar")

    def write_template(self, payload=b"STUB-TEMPLATE-BYTES\x00\x01\x02"):
        with open(self.template, "wb") as fh:
            fh.write(payload)
        return self.template

    def options(self, **kwargs):
        base = dict(template=self.template, out=self.out, provider=self.env.stub, allow_stub_output=True,
                    addon_module=self.env.addon_name)
        base.update(kwargs)
        return star.Options(**base)


def fresh(env):
    """A clean scene with the stand-in library, both stubs reset; returns ``(fixture, roundtrip module)``."""
    env.reset()
    env.use_library()
    rt = roundtrip_module()
    rt.reset()
    return Fixture(env), rt


def roundtrip_module():
    import importlib
    return importlib.import_module("stub_roundtrip")


def run_build(opts):
    return star.build(opts, star.Log(echo=False))


def star_exports(stub):
    template, objects, options = stub.LAST_EXPORT
    new = [o for o in objects if o.slot is None]
    old = [o for o in objects if o.slot is not None]
    return template, old, new, options


def expect_refused(res, needle, exit_code=star.EXIT_REFUSED, status="refused"):
    check_eq(res.status, status, "status of: " + res.message)
    check_eq(res.exit_code, exit_code, "exit code")
    check(needle in res.message, "expected %r in the message, got: %s" % (needle, res.message))
    check(res.out_path is None, "no output path may be reported")


def no_file(path):
    check(not os.path.exists(path), "a refused run must not write %s" % path)
    check(not os.path.exists(path + ".report.txt"), "a refused run must not write a report beside the output")
    check(not os.path.exists(path + ".REJECTED"))


def run(env):
    scenario_end_to_end_plain_stub(env)
    scenario_dry_run_keeps_nothing(env)
    scenario_repeated_runs_in_one_scene(env)
    scenario_roundtrip_verification(env)
    scenario_outline_colour_and_name(env)
    scenario_wrong_files_are_caught(env)
    scenario_refusals_before_anything_is_added(env)
    scenario_path_policy(env)
    scenario_library_refusals(env)
    scenario_template_flavours(env)
    scenario_few_free_slots_like_the_real_file(env)
    scenario_environment_problems(env)
    scenario_footprint_measurement(env)
    scenario_spacing_is_the_measured_mesh_box(env)
    scenario_library_resolution(env)
    scenario_child_blender(env)
    scenario_wrapper_in_a_scratch_checkout(env)


# --- 1. the main requirement: the plain stub's LAST_EXPORT --------------------------------------------------
def scenario_end_to_end_plain_stub(env):
    fx, rt = fresh(env)
    fx.write_template()
    template_stat = os.stat(fx.template)
    res = run_build(fx.options())
    check(res.ok, "plain stub run: %s" % res.message)
    check_eq(res.exit_code, 0)
    check_eq(res.block_name, "Block, 1x1", "the block type the template already contains")
    check_eq(res.grid, sl.DEFAULT_GRID, "auto takes the default grid when there is room")
    check_eq(res.footprint, STAND_IN, "footprint measured from the stand-in library mesh")

    stub = env.stub
    sent_template, old, new, options = star_exports(stub)
    check_eq(sent_template, open(fx.template, "rb").read(), "the template bytes handed to the exporter")
    check_eq(sorted(o.slot for o in old), [1, 2, 5, 9, 11], "the five originals keep their slots")
    for o in old:
        check(o.token_raw is not None and o.token_bits is not None, "originals keep their identity tokens")
    for rec in stub.CANNED.objects:                                    # originals are handed back exactly as imported
        eo = next(o for o in old if o.slot == rec.slot)
        diffs = bl_common.record_vs_export(rec, eo)
        check_eq(diffs, [], "original slot %d unchanged" % rec.slot)

    cells = sl.star_cells(sl.DEFAULT_GRID)
    check_eq(len(new), len(cells), "one new object per star cell")
    check(60 <= len(new) <= 120, "default star has 60..120 blocks (%d)" % len(new))
    new.sort(key=lambda o: o.name)
    check_eq([o.name for o in new], ["Star %03d" % i for i in range(len(new))], "deterministic names")
    id_block = stub.CANNED.objects[0].type_id                           # slot 1 is a Block, 1x1
    stock = stub.stock_object_names("Forge World")
    for i, o in enumerate(new):
        check(o.slot is None and o.token_raw is None and o.token_bits is None, "%s claims no slot" % o.name)
        check_eq(o.type_name, "Block, 1x1", "type name")
        check(o.type_name in stock, "stock object of the map")
        check_eq(o.physics, 1, "%s physics Fixed" % o.name)
        check_eq((o.symmetry, o.place_at_start, o.game_specific, o.team, o.color), (3, True, False, 8, -1),
                 "flags equal the example's, nothing extra is written")
        check_eq((o.spawn_sequence, o.spawn_time, o.label_index, o.shape), (0, 0, -1, 0))
        check_close(o.forward, (0.0, 1.0, 0.0), 1e-6, "forward")
        check_close(o.up, (0.0, 0.0, 1.0), 1e-6, "up (vertical, pure yaw)")
        check_close(o.position, res.positions[i], 1e-4, "position of %s" % o.name)
        check_eq(o.hidden, False)
    check_eq(stub._tables.object_id_for_name("Forge World", "Block, 1x1"), id_block, "type id = the example's id")
    check_eq(id_block, 0x4600)
    check(len(old) + len(new) <= 650, "inside the 650-object limit")
    check_eq(options.allow_unverified_rotation, True, "the rotation gate is ticked (DEC-5.6)")
    check_eq(options.imported_slots, [1, 2, 5, 9, 11])
    check_eq(options.max_objects, 650)
    check_eq(options.keep_unrecognised_imported, False)
    check_eq(options.raise_quota_max, False, "decision D11: the quota option is off unless --raise-quota-max is given")

    # the layout: centred in the bounds, standing on the typical height, the mesh boxes inside with the margin
    check_close(res.centre[:2], (0.0, 0.0), 1e-9, "x, y: the middle of the bounds")
    check_close(res.centre[2] - sl.extent(cells, STAND_IN)[2] / 2.0, 5.0, 1e-9, "bottom on the median object height (z = 5)")
    check_eq(sl.check_bounds(res.positions, STAND_IN, FOREST_BOUNDS, sl.DEFAULT_MARGIN), [], "inside the bounds")
    check_eq(sl.check_bounds([tuple(o.position) for o in new], STAND_IN, FOREST_BOUNDS), [], "as Blender gave them")
    # the shape really is the star: rebuild the cells from the positions
    xs = sorted(set(round(o.position[0], 3) for o in new))
    zs = sorted(set(round(o.position[2], 3) for o in new))
    check_eq(len(xs), 15, "15 columns")
    check_eq(len(zs), 15, "15 rows")
    got = set((xs.index(round(o.position[0], 3)), zs.index(round(o.position[2], 3))) for o in new)
    want = set((ix - min(c[0] for c in cells), iz - min(c[1] for c in cells)) for ix, iz in cells)
    check_eq(got, want, "the blocks form the star")
    # spacing: neighbours are exactly one block apart
    check_close(xs[1] - xs[0], 1.0, 2e-3)
    check_close(zs[1] - zs[0], 1.0, 2e-3)

    # outputs and safety
    check_eq(res.out_path, fx.out)
    check(os.path.isfile(fx.out), "the stub's bytes were kept because --allow-stub-output was given")
    check(os.path.isfile(fx.out + ".report.txt"), "report beside the output")
    check("RESULT: OK" in open(fx.out + ".report.txt").read())
    check(any(line.startswith("DELIVERABLE: " + fx.out) and "UNVERIFIED IN GAME" in line for line in res.report_lines))
    after = os.stat(fx.template)
    check_eq((after.st_size, after.st_mtime_ns), (template_stat.st_size, template_stat.st_mtime_ns), "template untouched")
    statuses = dict((c.name, c.status) for c in res.checks)
    check_eq(statuses["original objects unchanged"], "PASS")
    check_eq(statuses["star block count"], "SKIP", "the plain stub cannot remember what it wrote")
    check_eq(statuses["template untouched"], "PASS")
    check_eq(statuses["object library untouched"], "PASS", "the library the add-on resolved ($MJOLNIR_LIBRARY here) is fingerprinted")
    check_eq(statuses["re-import with the add-on"], "PASS")
    check(not [c for c in res.checks if c.failed], "no failed check: %s" % [c for c in res.checks if c.failed])
    library_line = [line for line in res.report_lines if line.startswith("library  : ")]
    check_eq(len(library_line), 1)
    check(library_line[0].startswith("library  : %s ($MJOLNIR_LIBRARY; linked read-only; sha256 " % os.environ["MJOLNIR_LIBRARY"]),
          "the log names the library that is really linked: " + library_line[0])
    # the star blocks live in their own collection until the re-import replaced the scene's objects
    art = sl.render_cells(cells)
    for i, row in enumerate(art):
        check(any(line == "            " + row for line in res.report_lines), "row %d of the star is drawn in the report" % i)
    check(any(line.startswith("shape    : 80 blocks") for line in res.report_lines))
    check(any("STUB PROVIDER" in line for line in res.report_lines), "the stub banner is printed")
    check(any("UNVERIFIED IN GAME" in line for line in res.report_lines), "the caveats are printed")


def scenario_repeated_runs_in_one_scene(env):
    """Several builds in one Blender session (the tests do it; a user may): the template's objects are never deleted."""
    fx, rt = fresh(env)
    fx.write_template(rt.map_template(3006))
    layer_before = bpy.context.view_layer.active_layer_collection.name
    for round_ in range(3):
        res = run_build(fx.options(provider=rt, overwrite=True))
        check(res.ok, "round %d: %s" % (round_, res.message))
        check_eq(bpy.context.view_layer.active_layer_collection.name, layer_before, "the active collection is restored")
        check_eq(len(env.forge_objects()), 85, "round %d: the scene holds the objects of the last output file" % round_)
        check(not [o for o in bpy.data.objects if o.get(star.STAR_MARK)], "no marked star block is left behind")
    # a user's own object in the Forge Star collection is not a star block and is not deleted
    mine = bpy.data.objects.new("my own empty", None)
    bpy.data.collections.get(star.COLLECTION_NAME).objects.link(mine)
    res = run_build(fx.options(provider=rt, overwrite=True))
    check(res.ok, res.message)
    check("my own empty" in bpy.data.objects, "an object without the star mark survives")


def scenario_dry_run_keeps_nothing(env):
    fx, rt = fresh(env)
    fx.write_template()
    res = run_build(fx.options(allow_stub_output=False))
    check(res.ok, res.message)
    check(res.out_path is None, "nothing kept")
    no_file(fx.out)
    check(res.scratch is not None and not os.path.exists(res.scratch), "the scratch folder is gone")
    check_eq(os.listdir(fx.dir_out), [], "the output folder stays empty")
    check(any("stub dry run" in line for line in res.report_lines))
    # --dry-run does the same for any provider, even when the stub's output would be allowed
    fx, rt = fresh(env)
    fx.write_template(rt.map_template(3006))
    res = run_build(fx.options(provider=rt, dry_run=True))
    check(res.ok, res.message)
    check(res.out_path is None and not os.listdir(fx.dir_out), "nothing kept")
    check(not os.path.exists(res.scratch), "scratch removed")
    check(any("--dry-run" in line for line in res.report_lines))
    check_eq(dict((c.name, c.status) for c in res.checks)["star block positions"], "PASS", "it was verified all the same")


# --- 2. the remembering double: full verification ---------------------------------------------------------------
def scenario_roundtrip_verification(env):
    fx, rt = fresh(env)
    fx.write_template(rt.map_template(3006))
    res = run_build(fx.options(provider=rt))
    check(res.ok, res.message)
    statuses = dict((c.name, c.status) for c in res.checks)
    for name in ("original objects unchanged", "map header and body fields unchanged", "star block count",
                 "star block type", "star block positions", "star blocks Fixed", "star blocks vertical",
                 "occupied count", "output differs from the template", "template untouched", "re-import with the add-on"):
        check_eq(statuses[name], "PASS", name)
    check_eq(res.out_path, fx.out)
    data = open(fx.out, "rb").read()
    back = rt.load_map_variant(data)                                   # independent of the script's own reading
    check_eq(len(back.objects), 5 + len(res.positions))
    new = [r for r in back.objects if r.slot not in (1, 2, 5, 9, 11)]
    check_eq(sorted(r.slot for r in new)[:3], [0, 3, 4], "the lowest free slots are used")
    match = sl.match_positions(res.positions, [r.position for r in new], sl.position_tolerance(FOREST_BOUNDS))
    check(match.ok, "every block is where the layout put it")
    check(all(r.physics == 1 for r in new), "Fixed")
    report = open(fx.out + ".report.txt").read()
    check("RESULT: OK" in report and "[PASS] star block positions" in report)
    check("diff     : 80 object(s) added, 0 removed, 0 changed, 5 unchanged (of 5 in the template)" in report, "the diff report")
    check("added 80 x 'Block, 1x1' in slot(s) 0, 3, 4, 6, 7, 8, 10, 12 ..." in report, "the new blocks took the lowest free slots")
    check_eq(env.stub.LAST_EXPORT[2].imported_slots, [1, 2, 5, 9, 11])
    # the scene ends as the re-imported file: the star's own blocks are gone, the file's 85 objects are there
    check(not [o for o in bpy.data.objects if o.name.startswith(star.BLOCK_PREFIX)], "no leftover star block in the scene")
    check_eq(len(env.forge_objects()), 85, "the scene holds exactly the objects of the output file")


def scenario_outline_colour_and_name(env):
    fx, rt = fresh(env)
    fx.write_template(rt.map_template(3006))
    res = run_build(fx.options(provider=rt, mode="outline", color="YELLOW", block="block, 1x1"))
    check(res.ok, res.message)
    check_eq(len(res.positions), len(sl.star_cells(17, "outline")), "outline block count")
    check_eq(res.block_name, "Block, 1x1", "the name is matched case-insensitively and canonicalised")
    new = star_exports(env.stub)[2]
    check(all(o.color == 5 for o in new), "colour YELLOW = 5 on every block")


def scenario_wrong_files_are_caught(env):
    expectations = [
        ("drop", ["star block count", "star block positions"]),
        ("shift", ["star block positions"]),
        ("touch_original", ["original objects unchanged"]),
        ("physics", ["star blocks Fixed"]),
        ("type", ["star block type"]),
        ("extra", ["star block count", "star block positions"]),
        ("flavour", ["map header and body fields unchanged"]),
    ]
    for mode, names in expectations:
        fx, rt = fresh(env)
        fx.write_template(rt.map_template(3006))
        rt.CORRUPT = mode
        res = run_build(fx.options(provider=rt))
        check_eq(res.status, "failed", "corrupt=%s must fail: %s" % (mode, res.message))
        check_eq(res.exit_code, star.EXIT_FAILED)
        failed = [c.name for c in res.checks if c.failed]
        for name in names:
            check(name in failed, "corrupt=%s should fail %r, failed: %s" % (mode, name, failed))
        check(not os.path.exists(fx.out), "corrupt=%s: the bad file must not keep the output name" % mode)
        check(os.path.isfile(fx.out + ".REJECTED"), "corrupt=%s: renamed *.REJECTED" % mode)
        check_eq(res.rejected_path, fx.out + ".REJECTED")
        check(any("DO NOT USE IT" in line for line in res.report_lines))
        check("failed" in res.message)
    # a clean run after the corrupt ones is unaffected (the double resets)
    fx, rt = fresh(env)
    fx.write_template(rt.map_template(3006))
    check(run_build(fx.options(provider=rt)).ok)


# --- 3. refusals: nothing added, nothing exported, nothing written ----------------------------------------------
def scenario_refusals_before_anything_is_added(env):
    stub = env.stub
    # too many: the exact boundary of the 650-object limit (5 objects in the canned map)
    limit_n = min(n for n in range(sl.MIN_GRID, sl.MAX_GRID + 1) if 5 + len(sl.star_cells(n)) > 650)
    fx, rt = fresh(env)
    fx.write_template()
    res = run_build(fx.options(cells=limit_n))
    expect_refused(res, "E_TOO_MANY")
    check("650" in res.message and ("%d" % (5 + len(sl.star_cells(limit_n)))) in res.message, res.message)
    check("smaller --cells" in res.message)
    no_file(fx.out)
    check(stub.LAST_EXPORT is None, "the exporter was never reached")
    star_collection = bpy.data.collections.get(star.COLLECTION_NAME)
    check(star_collection is None or len(star_collection.objects) == 0, "no star block was added")
    check_eq(len(env.forge_objects()), 5, "the scene still holds only the template's objects")
    fx, rt = fresh(env)
    fx.write_template()
    res = run_build(fx.options(cells=limit_n - 1))
    check(res.ok, "one grid size smaller passes the limit: %s" % res.message)
    check(5 + len(res.positions) <= 650)
    check_eq(len(star_exports(stub)[2]), len(res.positions))
    check_eq(len(res.positions), len(sl.star_cells(limit_n - 1)))

    # a name that is no stock object anywhere, and a real name that is not stock on THIS map
    fx, rt = fresh(env)
    fx.write_template()
    res = run_build(fx.options(block="Warthog Block"))
    expect_refused(res, "E_OBJ_NAME_UNKNOWN")
    check("Stock blocks on Forge World" in res.message and "Block, 1x1" in res.message, res.message)
    no_file(fx.out)
    check(stub.LAST_EXPORT is None)
    fx, rt = fresh(env)
    fx.write_template(rt.map_template(1080))
    res = run_build(fx.options(provider=rt, block="Block, 2x2"))
    expect_refused(res, "'Block, 2x2' is not a stock object on Boneyard")
    no_file(fx.out)
    res = run_build(fx.options(provider=rt))
    expect_refused(res, "no visible stock building block")
    check(stub.LAST_EXPORT is None)

    # a centre outside the bounds, on each axis, and a margin that leaves no room
    for centre, axis in (((1000.0, None, None), "x "), ((None, -5000.0, None), "y "), ((None, None, 500.0), "z ")):
        fx, rt = fresh(env)
        fx.write_template()
        res = run_build(fx.options(center=centre))
        expect_refused(res, "E_OUT_OF_BOUNDS")
        check("outside the map bounds" in res.message and axis in res.message, res.message)
        no_file(fx.out)
        check(stub.LAST_EXPORT is None)
    fx, rt = fresh(env)
    fx.write_template()
    res = run_build(fx.options(margin=200.0))
    expect_refused(res, "smaller grid")
    no_file(fx.out)
    # near the edge but still inside passes, one block further does not
    fx, rt = fresh(env)
    fx.write_template()
    res = run_build(fx.options(center=(None, None, 70.0 - 7.5 - 1.0)))
    check(res.ok, "the star's top exactly at the margin passes: %s" % res.message)
    fx, rt = fresh(env)
    fx.write_template()
    res = run_build(fx.options(center=(None, None, 70.0 - 7.5 - 0.5)))
    expect_refused(res, "margin")

    # a bad grid size and a mode
    fx, rt = fresh(env)
    fx.write_template()
    expect_refused(run_build(fx.options(cells=3)), "grid size")
    expect_refused(run_build(fx.options(mode="hollow")), "star mode")
    no_file(fx.out)
    # a template that does not exist
    fx, rt = fresh(env)
    res = run_build(fx.options())
    expect_refused(res, "does not exist")
    no_file(fx.out)


def scenario_path_policy(env):
    stub = env.stub
    fx, rt = fresh(env)
    fx.write_template()
    home = os.path.expanduser("~")
    bad = [
        (os.path.join(REPO, "star.mvar"), "inside the repository"),
        (os.path.join(REPO, "docs", "star.mvar"), "inside the repository"),
        (os.path.join(home, "Local_Documents", "Halo-MCC", "variant-tool", "test-samples", "star.mvar"), "protected sample folder"),
        (os.path.join(home, "Local_Documents", "Halo-MCC", "forge", "real-mvar-samples", "star.mvar"), "protected sample folder"),
        (os.path.join(home, "Local_Documents", "Halo-MCC", "variant-tool", "ReachVariantTool-core-library", "macos", "Fixtures", "star.mvar"), "protected sample folder"),
        (os.path.join(fx.dir_tpl, "star.mvar"), "beside the template"),
        (fx.template, "overwrite the template"),
        (os.path.join(fx.dir_out, "star.txt"), "must end in .mvar"),
    ]
    for path, needle in bad:
        existed = os.path.exists(path)
        res = run_build(fx.options(out=path))
        expect_refused(res, needle)
        check_eq(os.path.exists(path), existed, "a refused path must not be created: %s" % path)
        check(not os.path.exists(path + ".report.txt"))
    check(stub.LAST_EXPORT is None, "refused before Blender touched anything")
    # the same folders under another spelling: refused on a case-insensitive volume (the macOS default), skipped elsewhere
    cased = [(REPO.swapcase(), "inside the repository"), (fx.dir_tpl.swapcase(), "beside the template")]
    for folder, needle in cased:
        if folder != (REPO if "repository" in needle else fx.dir_tpl) and os.path.isdir(folder):
            path = os.path.join(folder, "star_mixedcase.mvar")
            res = run_build(fx.options(out=path))
            expect_refused(res, needle)
            check(not os.path.exists(path), "a refused path must not be created: %s" % path)
    # an existing output is only replaced with --overwrite
    with open(fx.out, "wb") as fh:
        fh.write(b"PRECIOUS")
    res = run_build(fx.options())
    expect_refused(res, "already exists")
    check_eq(open(fx.out, "rb").read(), b"PRECIOUS", "the existing file is untouched")
    res = run_build(fx.options(overwrite=True))
    check(res.ok, res.message)
    check(open(fx.out, "rb").read() != b"PRECIOUS")
    # a scratch file for a dry run is never made inside the repository, whatever $TMPDIR says
    import tempfile
    inside = os.path.join(REPO, "docs")
    listing = sorted(os.listdir(inside))
    saved = tempfile.tempdir
    tempfile.tempdir = inside
    try:
        res = run_build(fx.options(overwrite=True, allow_stub_output=False))
    finally:
        tempfile.tempdir = saved
    expect_refused(res, "is inside the repository", exit_code=star.EXIT_FAILED, status="failed")
    check_eq(sorted(os.listdir(inside)), listing, "no scratch folder was created in the repository")
    # a symlink to the template does not get around the rule
    link = os.path.join(fx.dir_out, "link.mvar")
    os.symlink(fx.template, link)
    expect_refused(run_build(fx.options(out=link, overwrite=True)), "template")
    check_eq(open(fx.template, "rb").read(), b"STUB-TEMPLATE-BYTES\x00\x01\x02", "template bytes unchanged")


def scenario_library_refusals(env):
    stub = env.stub
    # a refusal that does not depend on the block type: one attempt, a clear message, no file
    fx, rt = fresh(env)
    fx.write_template()
    stub.preset_refusal(stub.Issue("E_OUT_OF_BOUNDS", "error", "Object 'Star 000' is at (1.0, 2.0, 3.0), outside the map "
                                   "bounds. Move it inside; positions are never clamped.", None, "Star 000"))
    res = run_build(fx.options())
    expect_refused(res, "E_OUT_OF_BOUNDS", exit_code=star.EXIT_FAILED, status="failed")
    check_eq(res.attempts, [("Block, 1x1", "refused: E_OUT_OF_BOUNDS")], "no retry for a refusal that is not about the block")
    no_file(fx.out)
    check(any("hint: Choose a --center" in line for line in res.report_lines), "the hint is printed")

    # E_QUOTA: the next block type is tried in auto mode (the remembering double enforces QUOTA_MAX)
    fx, rt = fresh(env)
    fx.write_template(rt.map_template(3006))
    rt.QUOTA_MAX = {"Block, 1x1": 10}
    res = run_build(fx.options(provider=rt))
    check(res.ok, res.message)
    check_eq(res.attempts[0], ("Block, 1x1", "refused: E_QUOTA"))
    check(res.block_name != "Block, 1x1" and len(res.attempts) == 2, "the second block type passed: %s" % (res.attempts,))
    check(any("trying the next block type" in line for line in res.report_lines))
    check(any("NOT in template" in line for line in res.report_lines))
    # ... but not when the block was asked for by name
    fx, rt = fresh(env)
    fx.write_template(rt.map_template(3006))
    rt.QUOTA_MAX = {"Block, 1x1": 10}
    res = run_build(fx.options(provider=rt, block="Block, 1x1"))
    expect_refused(res, "E_QUOTA", exit_code=star.EXIT_FAILED, status="failed")
    check_eq(len(res.attempts), 1)
    no_file(fx.out)

    # the rotation gate is ticked by default and refuses when left off
    fx, rt = fresh(env)
    fx.write_template(rt.map_template(3006))
    res = run_build(fx.options(provider=rt, unverified_rotation=False))
    expect_refused(res, "E_ROTATION_GATED", exit_code=star.EXIT_FAILED, status="failed")
    check(any("Do not pass --no-rotation-gate" in line for line in res.report_lines))
    no_file(fx.out)

    # flags: the new block copies the template's example, otherwise the library refuses it
    fx, rt = fresh(env)
    fx.write_template(rt.ODD_EXAMPLE_TEMPLATE)
    res = run_build(fx.options(provider=rt, block="Block, 1x1"))
    check(res.ok, "flags copied from the example are accepted: %s" % res.message)
    new = star_exports(env.stub)[2]
    check_eq((new[0].symmetry, new[0].place_at_start, new[0].game_specific), (1, False, True), "the example's odd flags")
    fx, rt = fresh(env)
    fx.write_template(rt.ODD_EXAMPLE_TEMPLATE)
    original = star.example_flags
    star.example_flags = lambda examples: ({}, 1, 1)
    try:
        res = run_build(fx.options(provider=rt, block="Block, 1x1"))
    finally:
        star.example_flags = original
    expect_refused(res, "E_FLAG_UNVERIFIED", exit_code=star.EXIT_FAILED, status="failed")
    no_file(fx.out)

    # quota is untouched by a clean run, and --keep-unrecognised reaches the exporter
    fx, rt = fresh(env)
    fx.write_template()
    res = run_build(fx.options(keep_unrecognised=True))
    check(res.ok, res.message)
    check_eq(star_exports(env.stub)[3].keep_unrecognised_imported, True)

    # --raise-quota-max (decision D11) reaches the exporter as ExportOptions.raise_quota_max, and only when asked for
    fx, rt = fresh(env)
    fx.write_template()
    res = run_build(fx.options(raise_quota_max=True))
    check(res.ok, res.message)
    check_eq(star_exports(env.stub)[3].raise_quota_max, True)
    check_eq(star_exports(env.stub)[3].keep_unrecognised_imported, False, "the other options are not disturbed")


def scenario_template_flavours(env):
    # a template without any block: a stock block with the loud warning
    fx, rt = fresh(env)
    fx.write_template(rt.NO_BLOCKS_TEMPLATE)
    res = run_build(fx.options(provider=rt))
    check(res.ok, res.message)
    check(any("contains no building block" in line and "UNVERIFIED" in line for line in res.report_lines), "loud warning")
    check(any("no block type of the template" in w for w in res.warnings))
    check(any("NOT in template" in line for line in res.report_lines))
    check(res.block_name.startswith("Block"))
    # a block asked for by name that the template does not hold gets the same loud warning
    fx, rt = fresh(env)
    fx.write_template(rt.map_template(3006))
    res = run_build(fx.options(provider=rt, block="Block, 1x1, Flat"))
    check(res.ok, res.message)
    check(any("contains no 'Block, 1x1, Flat'" in line and "UNVERIFIED" in line for line in res.report_lines), "loud warning")
    check(any("not in the template" in w for w in res.warnings), res.warnings)
    # an existing object inside the star's box is reported
    fx, rt = fresh(env)
    fx.write_template(rt.map_template(3006))
    res = run_build(fx.options(provider=rt, center=(10.0, 20.0, 5.0)))
    check(res.ok, res.message)
    check(any("existing object(s) lie inside the star's box" in w for w in res.warnings), res.warnings)


def scenario_few_free_slots_like_the_real_file(env):
    """610 of 650 objects used, no block in the template, bounds +-20000: the shape of the one real Breakneck file."""
    stub = env.stub
    fx, rt = fresh(env)
    fx.write_template(rt.real_like_template())
    res = run_build(fx.options(provider=rt))
    check(res.ok, res.message)
    check_eq(res.grid, 11, "auto: the largest grid whose star fits the 40 free slots")
    check_eq(len(res.positions), 34)
    check(any("grid auto -> 11: 34 blocks" in line and "40 free slots" in line for line in res.report_lines))
    check(any("contains no building block" in line and "UNVERIFIED" in line for line in res.report_lines), "loud warning")
    check_eq(res.block_name, "Block, 1x1", "the first stock block with a good aspect")
    check(any("span x" in line for line in res.report_lines), "the extent of the template's objects is printed")
    check_close(res.centre[:2], (0.0, 0.0), 1e-9, "the middle of +-20000")
    heights = sorted(r.position[2] for r in rt.load_map_variant(rt.real_like_template()).objects)
    median = (heights[304] + heights[305]) / 2.0
    check_close(res.centre[2] - sl.extent(res.cells, STAND_IN)[2] / 2.0, median, 1e-4, "bottom on the median object height")
    detail = dict((c.name, c.detail) for c in res.checks)["star block positions"]
    check("allowed 0.0134" in detail, "the tolerance follows the 23-bit cell (2 cells + float32 spacing at 20000): " + detail)
    statuses = dict((c.name, c.status) for c in res.checks)
    check_eq(statuses["star block positions"], "PASS")
    check_eq(statuses["occupied count"], "PASS")
    check_eq(statuses["hash recipe reproduced"], "SKIP")

    # an explicit grid is never shrunk: 610 + 80 > 650 is refused with the room named, the exact fit passes
    fx, rt = fresh(env)
    fx.write_template(rt.real_like_template())
    res = run_build(fx.options(provider=rt, cells=17))
    expect_refused(res, "E_TOO_MANY")
    check("at most 40" in res.message and "690" in res.message, res.message)
    no_file(fx.out)
    check(stub.LAST_EXPORT is None)
    fx, rt = fresh(env)
    fx.write_template(rt.real_like_template())
    res = run_build(fx.options(provider=rt, cells=15, mode="outline"))
    check(res.ok, "610 + 40 = 650 is allowed: %s" % res.message)
    check_eq(len(res.positions), 40)
    check_eq(dict((c.name, c.detail) for c in res.checks)["occupied count"][:3], "650")
    fx, rt = fresh(env)
    fx.write_template(rt.real_like_template())
    res = run_build(fx.options(provider=rt, mode="outline"))
    check(res.ok, res.message)
    check_eq(res.grid, 15, "an outline of grid 15 has 40 blocks")
    # nothing fits
    fx, rt = fresh(env)
    fx.write_template(rt.real_like_template(640))
    res = run_build(fx.options(provider=rt))
    expect_refused(res, "only 10 more fit")
    check("smallest star (grid 9) needs 24 blocks (20 as an outline)" in res.message, res.message)
    no_file(fx.out)
    # a place away from every existing object is allowed but reported
    fx, rt = fresh(env)
    fx.write_template(rt.real_like_template())
    res = run_build(fx.options(provider=rt, center=(500.0, 500.0, 10.0)))
    check(res.ok, res.message)
    check(any("outside the area covered by the template's own objects" in w for w in res.warnings), res.warnings)
    check(any("Choose a place with --center" in line for line in res.report_lines))


def scenario_environment_problems(env):
    # the real library is not usable yet: a clear failure, not a traceback
    fx, rt = fresh(env)
    fx.write_template()
    unreadable = types.ModuleType("fake_real_provider")
    for name in env.provider.REQUIRED_NAMES:
        setattr(unreadable, name, getattr(env.stub, name))

    def not_yet(data, name="", options=None):
        raise NotImplementedError("G3")

    unreadable.load_map_variant = not_yet
    res = run_build(fx.options(provider=unreadable))
    expect_refused(res, "cannot read map variants yet", exit_code=star.EXIT_FAILED, status="failed")
    no_file(fx.out)
    unwritable = types.ModuleType("fake_real_provider2")
    for name in env.provider.REQUIRED_NAMES:
        setattr(unwritable, name, getattr(env.stub, name))

    def writer_missing(template, objects, options):
        raise NotImplementedError("G5")

    unwritable.export_map_variant = writer_missing
    res = run_build(fx.options(provider=unwritable))
    expect_refused(res, "real writer is not available yet", exit_code=star.EXIT_FAILED, status="failed")
    no_file(fx.out)
    # a template the library refuses
    fx, rt = fresh(env)
    fx.write_template()
    env.stub.NEXT_LOAD_ERROR = env.stub.UnsupportedVariantError("This is a game variant (block 'mpvr'), not a map variant.")
    res = run_build(fx.options())
    expect_refused(res, "game variant")
    no_file(fx.out)
    # no object library: the block cannot be measured
    fx, rt = fresh(env)
    fx.write_template()
    env.no_library()
    res = run_build(fx.options())
    expect_refused(res, "object library was not found", exit_code=star.EXIT_FAILED, status="failed")
    no_file(fx.out)
    # --real-library names a file that must exist (the real one is never opened by this test)
    env.use_library()


def scenario_footprint_measurement(env):
    env.reset()
    scene = bpy.context.scene

    def cube(name, size=(1.0, 1.0, 1.0)):
        mesh = bpy.data.meshes.new(name)
        verts = [(x, y, z) for x in (-0.5, 0.5) for y in (-0.5, 0.5) for z in (-0.5, 0.5)]
        faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        return bpy.data.objects.new(name, mesh)

    coll = bpy.data.collections.new("measure me")
    scene.collection.children.link(coll)
    plain = cube("plain")
    coll.objects.link(plain)
    fp = star.measure_collection(coll)
    check_eq(fp, sl.Footprint(1.0, 1.0, 1.0, (0.0, 0.0, 0.0)), "a unit cube at the origin")
    plain.location = (3.0, 4.0, 5.0)
    plain.rotation_euler = (0.0, 0.0, math.radians(90.0))
    plain.scale = (1.0, 2.0, 1.0)
    coll.instance_offset = (1.0, 0.0, 0.0)
    fp = star.measure_collection(coll)
    check_close((fp.width, fp.depth, fp.height), (2.0, 1.0, 1.0), 1e-5, "scale (1,2,1) then a quarter turn about Z: 2 x 1 x 1")
    check_close(fp.offset, (2.0, 4.0, 5.0), 1e-5, "centre relative to the instance offset")
    helper = bpy.data.objects.new("holder", None)
    coll.objects.link(helper)
    helper.location = (0.0, 0.0, 10.0)
    plain.parent = helper
    fp = star.measure_collection(coll)
    check_close(fp.offset, (2.0, 4.0, 15.0), 1e-5, "a parent's transform counts")
    empty = bpy.data.collections.new("no mesh")
    scene.collection.children.link(empty)
    empty.objects.link(bpy.data.objects.new("only an empty", None))
    check(star.measure_collection(empty) is None, "no mesh, no footprint")


def odd_library(env, cache={}):
    """The stand-in library whose ``Block, 1x1`` measures like the real one (built once per process in a child Blender)."""
    if "path" not in cache:
        out_dir = os.path.join(env.tmp, "odd_standin")
        subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", "--python-exit-code", "1", "--python",
                        os.path.join(HERE, "s1_make_odd_library.py"), "--", out_dir],
                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
        cache["path"] = os.path.join(out_dir, "Halo Reach.blend")
    return cache["path"]


def scenario_spacing_is_the_measured_mesh_box(env):
    """A tool that hard-coded a spacing of 1.0 (or used the width for the height) would pass with a unit-cube stand-in."""
    fx, rt = fresh(env)
    env.use_library(odd_library(env))
    fx.write_template()
    res = run_build(fx.options())
    check(res.ok, res.message)
    check_eq(res.block_name, "Block, 1x1")
    check_close((res.footprint.width, res.footprint.depth, res.footprint.height), (1.0182, 1.0182, 1.0), 1e-5,
                "the footprint is the measured mesh box of the odd library")
    check_close(res.footprint.offset, (0.0, 0.0, 0.5), 1e-5, "the origin is at the bottom centre")
    _template, _old, new, _options = star_exports(env.stub)
    cells = sl.star_cells(sl.DEFAULT_GRID)
    check_eq(len(new), len(cells))
    xs = sorted(set(round(o.position[0], 3) for o in new))
    zs = sorted(set(round(o.position[2], 3) for o in new))
    check_eq((len(xs), len(zs)), (15, 15), "15 columns and 15 rows")
    for a, b in zip(xs, xs[1:]):
        check_close(b - a, 1.0182, 2e-3, "columns are one block width apart (1.0182, not 1.0)")
    for a, b in zip(zs, zs[1:]):
        check_close(b - a, 1.0, 2e-3, "rows are one block height apart (1.0, not the width)")
    check_close(xs[-1] - xs[0], 14 * 1.0182, 5e-3, "the star is as wide as 14 block widths between the outer centres")
    check_close(zs[-1] - zs[0], 14 * 1.0, 5e-3, "and as tall as 14 block heights")
    # the blocks as Blender gave them still agree with the layout of the measured box, within the bounds and margin
    check_eq(sl.check_bounds([tuple(o.position) for o in new], ODD_BLOCK, FOREST_BOUNDS, sl.DEFAULT_MARGIN), [])
    check_close(res.centre[2] - sl.extent(res.cells, res.footprint)[2] / 2.0, 5.0, 1e-9, "bottom on the median object height")
    statuses = dict((c.name, c.status) for c in res.checks)
    check_eq(statuses["object library untouched"], "PASS")


def scenario_library_resolution(env):
    """The library that is linked is the one the add-on resolves; the log names it; the real one only on request."""
    # ``--addons`` in a background Blender does not put the add-on into ``preferences.addons``, so the preference is stood in
    # for by replacing ``palette._addon_preferences`` (the one function ``library_path()`` reads it through): the REAL
    # ``library_path()`` precedence code (preference, then environment, then Resources) is what decides below.
    prefs = types.SimpleNamespace(library_path="")
    saved_hook = env.palette._addon_preferences
    env.palette._addon_preferences = lambda: prefs
    saved_pref = prefs.library_path
    saved_env = os.environ.get("MJOLNIR_LIBRARY")
    real = star.repo_library_path()
    try:
        # 1. the preference is checked BEFORE $MJOLNIR_LIBRARY: --real-library cannot silently lose to it. The checkout's
        #    real library is stood in for by a placeholder file of a fake checkout (the run is refused before anything is linked)
        fx, rt = fresh(env)
        fx.write_template()
        fake_repo = os.path.join(env.tmp, "fake_checkout")
        fake_real = os.path.join(fake_repo, "Addon", "Resources", "Halo Reach.blend")
        os.makedirs(os.path.dirname(fake_real))
        with open(fake_real, "wb") as fh:
            fh.write(b"placeholder: only the path matters, the run is refused before it is read")
        prefs.library_path = odd_library(env)
        saved_repo, star.REPO = star.REPO, fake_repo
        try:
            res = run_build(fx.options(real_library=True))
        finally:
            star.REPO = saved_repo
        expect_refused(res, "overrides")
        check(odd_library(env) in res.message and fake_real in res.message, "names both files: " + res.message)
        check(not bpy.data.libraries, "nothing was linked")
        no_file(fx.out)
        check(env.stub.LAST_EXPORT is None)

        # 2. a preference without --real-library is honoured and the log names it (not "$MJOLNIR_LIBRARY")
        fx, rt = fresh(env)
        fx.write_template()
        prefs.library_path = odd_library(env)                      # $MJOLNIR_LIBRARY (the plain stand-in) loses to it
        res = run_build(fx.options())
        check(res.ok, res.message)
        check_close((res.footprint.width, res.footprint.height), (1.0182, 1.0), 1e-5, "the preference's library was measured")
        line = [l for l in res.report_lines if l.startswith("library  : ")][0]
        check(line.startswith("library  : %s (the add-on preference 'Library path'; linked read-only" % odd_library(env)), line)
        check_eq(dict((c.name, c.status) for c in res.checks)["object library untouched"], "PASS")
        prefs.library_path = ""

        # 3. the real library is never used without --real-library, whichever way the add-on would get to it
        attempts = [("$MJOLNIR_LIBRARY names it", real)]
        palette_dir = os.path.realpath(os.path.dirname(env.palette.__file__))
        if palette_dir == os.path.realpath(os.path.join(REPO, "Addon")):
            attempts.append(("nothing set: the add-on falls back to its Resources folder", None))
        for label, value in attempts:
            fx, rt = fresh(env)
            fx.write_template()
            if value is None:
                os.environ.pop("MJOLNIR_LIBRARY", None)
            else:
                os.environ["MJOLNIR_LIBRARY"] = value
            res = run_build(fx.options())
            expect_refused(res, "pass --real-library")
            check("stand-in" in res.message and real in res.message, label + ": " + res.message)
            check(not bpy.data.libraries, label + ": the real library was not linked")
            no_file(fx.out)
            check(env.stub.LAST_EXPORT is None, label)
    finally:
        env.palette._addon_preferences = saved_hook
        if saved_env is None:
            os.environ.pop("MJOLNIR_LIBRARY", None)
        else:
            os.environ["MJOLNIR_LIBRARY"] = saved_env
        env.reset()


# --- 4. the way the owner runs it: a child Blender ---------------------------------------------------------------
def scenario_child_blender(env):
    fx, rt = fresh(env)
    fx.write_template(rt.map_template(3006))
    tool = os.path.join(REPO, "tools", "build_star_mvar.py")

    def child(*args):
        cmd = [bpy.app.binary_path, "-b", "--factory-startup", "--python-use-system-env", "--python-exit-code", "1",
               "--addons", env.addon_name, "--python", tool, "--"] + list(args)
        return subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              universal_newlines=True, timeout=300)

    done = child("--template", fx.template, "--out", fx.out, "--provider", "stub-roundtrip", "--allow-stub-output")
    check_eq(done.returncode, 0, "child exit status\n" + done.stdout[-3000:])
    check("RESULT: OK" in done.stdout, done.stdout[-3000:])
    check("[PASS] star block positions" in done.stdout)
    check("UNVERIFIED IN GAME" in done.stdout)
    check(os.path.isfile(fx.out) and os.path.isfile(fx.out + ".report.txt"))

    out2 = os.path.join(fx.dir_out, "too_big.mvar")
    done = child("--template", fx.template, "--out", out2, "--provider", "stub-roundtrip", "--cells", "60")
    check_eq(done.returncode, star.EXIT_REFUSED, "a refused request exits with 2\n" + done.stdout[-2000:])
    check("E_TOO_MANY" in done.stdout and "REFUSED" in done.stdout, done.stdout[-2000:])
    check(not os.path.exists(out2))

    done = child("--template", fx.template, "--out", os.path.join(REPO, "star.mvar"), "--provider", "stub")
    check_eq(done.returncode, star.EXIT_REFUSED)
    check(not os.path.exists(os.path.join(REPO, "star.mvar")), "nothing written into the repository")

    done = child("--template", fx.template, "--out", os.path.join(fx.dir_out, "bad.mvar"), "--cells", "2")
    check_eq(done.returncode, 2, "a bad command line exits with 2\n" + done.stdout[-1000:])
    done = child("--help")
    check_eq(done.returncode, 0)
    check("--template" in done.stdout and "--block" in done.stdout and "--provider" in done.stdout)


def scenario_wrapper_in_a_scratch_checkout(env):
    """``tools/run_star_build.sh`` as the owner runs it, from a scratch copy of the checkout (no game library in it)."""
    fx, rt = fresh(env)
    fx.write_template(rt.map_template(3006))
    root = os.path.join(env.tmp, "checkout")
    skip = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(os.path.join(REPO, "Addon"), os.path.join(root, "Addon"), ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "Resources"))
    shutil.copytree(os.path.join(REPO, "tools"), os.path.join(root, "tools"), ignore=skip)
    shutil.copytree(os.path.join(REPO, "tests", "stubs"), os.path.join(root, "tests", "stubs"), ignore=skip)
    wrapper = os.path.join(root, "tools", "run_star_build.sh")

    def child_env(**extra):
        environment = dict(os.environ)
        for name in ("PYTHONDONTWRITEBYTECODE", "BLENDER_USER_RESOURCES", "MJOLNIR_ADDON_MODULE"):
            environment.pop(name, None)                       # the wrapper itself must provide what it needs
        environment.update(BLENDER=bpy.app.binary_path, TMPDIR=env.tmp, MJOLNIR_ADDON_MODULE="mjolnir_forge")
        environment.update(extra)
        for name, value in list(environment.items()):
            if value is None:
                del environment[name]
        return environment

    def run_wrapper(args, cwd, environment):
        return subprocess.run(["/bin/bash", wrapper] + list(args), cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=300)

    def pycache_dirs():
        return [d for d, _dirs, _files in os.walk(root) if os.path.basename(d) == "__pycache__"]

    check(not pycache_dirs(), "the scratch checkout starts without bytecode")
    # 1. relative paths mean the caller's directory (not the checkout), and nothing is left in the checkout
    rel_template = os.path.relpath(fx.template, env.tmp)
    rel_out = os.path.relpath(fx.out, env.tmp)
    done = run_wrapper(["--template", rel_template, "--out", rel_out, "--provider", "stub-roundtrip", "--allow-stub-output"],
                       env.tmp, child_env())
    check_eq(done.returncode, 0, "wrapper exit status\n" + done.stdout[-3000:])
    check("RESULT: OK" in done.stdout, done.stdout[-3000:])
    check(os.path.isfile(fx.out) and os.path.isfile(fx.out + ".report.txt"), "the relative --out landed where the caller meant")
    check(not os.path.exists(os.path.join(root, rel_out)), "...and not under the checkout")
    check(not pycache_dirs(), "the run wrote no bytecode into the checkout: %s" % pycache_dirs())
    check("library  : %s ($MJOLNIR_LIBRARY; linked read-only" % os.environ["MJOLNIR_LIBRARY"] in done.stdout, "the log names the library")
    # 2. the same relative --out from INSIDE the checkout is the checkout: refused, nothing written (exit 2)
    done = run_wrapper(["--template", fx.template, "--out", "star_in_checkout.mvar", "--provider", "stub-roundtrip",
                        "--allow-stub-output"], root, child_env())
    check_eq(done.returncode, star.EXIT_REFUSED, "inside the repository: refused\n" + done.stdout[-2000:])
    check("Refusing to write inside the repository" in done.stdout, done.stdout[-2000:])
    check(not os.path.exists(os.path.join(root, "star_in_checkout.mvar")))
    # 3. no flag and no library named: the add-on would fall back to the checkout's own Resources library; refused (exit 2)
    out2 = os.path.join(fx.dir_out, "fallback.mvar")
    done = run_wrapper(["--template", fx.template, "--out", out2, "--provider", "stub-roundtrip", "--allow-stub-output"],
                       env.tmp, child_env(MJOLNIR_LIBRARY=None))
    check_eq(done.returncode, star.EXIT_REFUSED, "no library named: refused\n" + done.stdout[-2000:])
    check("pass --real-library" in done.stdout, done.stdout[-2000:])
    check(not os.path.exists(out2))
    check(not pycache_dirs(), "refused runs leave no bytecode either: %s" % pycache_dirs())


if __name__ == "__main__":
    bl_common.main(run, ID)
