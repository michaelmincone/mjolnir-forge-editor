"""B-16 (SPEC 9.4, 9.8 rows 3 to 6, gate G6): every refusal goes through File > Export, says why, and writes NOTHING.

The REAL provider, fixtures of the independent builder and the real Breakneck file. Each case triggers one refusal with
the operator ``export_scene.mjolnir_mvar`` and checks: a ``RuntimeError`` reaches the caller (the ERROR report), the
text ``Mjolnir Export Report`` says ``Result: REFUSED, nothing was written`` and carries ``ERROR <code>`` (with the
library's own wording), the target file does not exist, and no temporary file is left behind in its folder.

Cases: no template (``E_NO_TEMPLATE``); tampered template (``E_TEMPLATE_CORRUPT``); unknown map id 0xFFFFFFFF
(``E_MAP_UNKNOWN``, also for an unchanged export); non-stock object, new (``E_OBJ_NAME_UNKNOWN``) and imported-unrecognised
(``E_OBJ_NOT_STOCK``, kept with ``W_UNKNOWN_TYPE_KEPT`` only when asked), and a failed-import slot that is not stock
(``E_FAILED_SLOT_NOT_STOCK``); a folder beyond the quota count (``E_FOLDER_RANGE``); more than 650 objects (``full650``
exports, ``full650`` plus one and ``over650`` give ``E_TOO_MANY``; the real file plus 40 objects fits and plus 41 does not);
an unevaluated array parent (``E_ARRAY_NOT_EVALUATED``); out of bounds (``E_OUT_OF_BOUNDS``); quota (``E_QUOTA``); an
unknown object class (``E_CACHED_TYPE_UNKNOWN``); a label outside the table (``E_LABEL_RANGE``); the rotation gate
(``E_ROTATION_GATED``); a tilt (``E_TILT_UNSUPPORTED``); a mirrored object (``E_MIRRORED``); overwriting the file the map
came from, also through a symlink and a hard link (``E_PATH_SAME_AS_SOURCE``); a protected folder (``E_PATH_PROTECTED``).
``E_NO_FREE_SLOT`` cannot be reached through the operator (650 objects is the limit and a file has 651 slots), see G6.md.
"""
import math
import os
import sys

import bpy

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common  # noqa: E402
import real_data as rd  # noqa: E402
from bl_common import check, check_eq  # noqa: E402

ID = "b16"
TITLE = "every refusal writes no file: template, map, stock, 650, bounds, quota, class, label, rotation, tilt, mirror, paths"
NEEDS_STUB = False
REAL_ONLY = True

REFUSED = "Result: REFUSED, nothing was written"
SEEN = []                                      # codes triggered, printed at the end


def leftovers(path):
    folder = os.path.dirname(path)
    stem = os.path.basename(path)
    return [n for n in os.listdir(folder) if n == stem or n.startswith(stem + ".tmp")]


def assert_nothing_written(path, what):
    check_eq(leftovers(path), [], what + ": no file and no temporary file was left behind")


def refuse(env, label, code, contains=(), also=(), absent=(), **options):
    """Run File > Export on the current scene; it must be refused with ``code`` and write nothing."""
    result, path = env.export_to("b16_%s.mvar" % label, **options)
    check(isinstance(result, RuntimeError), "%s: expected a refusal, got %r" % (label, result))
    report = env.report_text()
    check("ERROR %s" % code in report, "%s: ERROR %s is not in the report:\n%s" % (label, code, report[:3000]))
    check(REFUSED in report, "%s: the report does not say REFUSED:\n%s" % (label, report[:600]))
    for needle in contains:
        check(needle in report, "%s: %r is not in the report:\n%s" % (label, needle, report[:3000]))
    for other in also:
        check("ERROR %s" % other in report, "%s: ERROR %s is missing" % (label, other))
    for other in absent:
        check("ERROR %s" % other not in report, "%s: ERROR %s must not appear" % (label, other))
    check(code in str(result) or "Export refused" in str(result) or "Export failed" in str(result), "%s: the error text reaches the user: %s" % (label, result))
    assert_nothing_written(path, label)
    SEEN.append(code)
    return report


def import_data(env, data, name="fixture.mvar", **kwargs):
    result, path = env.import_bytes(data, name, **kwargs)
    check_eq(result, {'FINISHED'}, "import of %s" % name)
    return path


def forge_by_slot():
    return dict((o["mj_slot"], o) for o in bpy.context.scene.objects if o.get("isForgeObject") and "mj_slot" in o)


def new_model_less(name, type_name, location=(0.0, 0.0, 0.0), via_menu=True):
    """What Add > Forge Object makes without a library: an arrow empty that remembers the chosen type.

    ``via_menu=False`` builds the same object without the operator (a type the Add menu does not offer for this file,
    such as a palette entry beyond the file's quota count, can only come from a script or an older ``.blend``)."""
    if via_menu:
        check_eq(bpy.ops.forge.add_object(objectType=type_name), {'FINISHED'})
        obj = bpy.context.active_object
    else:
        obj = env_mjolnir_create(type_name)
    obj.name = name
    obj.location = location
    bpy.context.view_layer.update()
    return obj


def env_mjolnir_create(type_name):
    from importlib import import_module
    mj = import_module(os.environ.get(bl_common.ENV_ADDON, bl_common.DEFAULT_ADDON) + ".mjolnir")
    return mj.create_forge_object(bpy.context, type_name)


def make_array(source, count=3):
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    source.select_set(True)
    bpy.context.view_layer.objects.active = source
    check_eq(bpy.ops.object.setup_array(type='CONST', count=count), {'FINISHED'})
    return source.parent


def copy_of(obj, offset=(1.0, 0.0, 0.0)):
    """A Shift+D style copy (it inherits ``mj_slot``): a second claimant of the same slot, which becomes a new object."""
    twin = obj.copy()
    bpy.context.scene.collection.objects.link(twin)
    twin.location = (obj.location[0] + offset[0], obj.location[1] + offset[1], obj.location[2] + offset[2])
    return twin


# =====================================================================================================
def template_and_map_cases(env, w1):
    env.reset()
    refuse(env, "no_template", "E_NO_TEMPLATE", ["This scene has no imported map variant. Import a .mvar first"])

    env.reset()
    import_data(env, w1, "tamper.mvar")
    scene = bpy.context.scene
    good = bytes(scene["mjolnir_template"])
    # (Blender 5.2.1 stores an EMPTY value when bytes are assigned over an existing bytes property: delete the key first)
    del scene["mjolnir_template"]
    scene["mjolnir_template"] = good[:-1] + bytes([(good[-1] + 1) % 256])
    refuse(env, "tampered", "E_TEMPLATE_CORRUPT", ["(checksum mismatch)"])
    del scene["mjolnir_template"]
    scene["mjolnir_template"] = good
    result, _path = env.export_to("b16_tampered_restored.mvar")
    check_eq(result, {'FINISHED'}, "the restored template exports again")

    # an unknown map id imports (permissively) and is refused at export, also when nothing was edited
    env.reset()
    import_data(env, rd.fixture("unknown_map"), "unknown_map.mvar")
    st = env.state.get(bpy.context.scene)
    check_eq((st["map_id_hex"], st["map_name"]), ("0xFFFFFFFF", ""))
    refuse(env, "unknown_map", "E_MAP_UNKNOWN", ["Map id 4294967295 (0xFFFFFFFF) is not one of the 20 stock Halo: Reach maps"])


def stock_cases(env, w1):
    # a new object of a name nobody knows, and a real Reach name that is not stock on this map
    env.reset()
    import_data(env, w1, "stock_new.mvar")
    bpy.context.scene.forge.allowUnverifiedRotation = True
    nonsense = new_model_less("nonsense", "Block, 1x1", (1.0, 1.0, 1.0))
    nonsense["mj_type_name"] = "Nonsense Thing"
    refuse(env, "name_unknown", "E_OBJ_NAME_UNKNOWN", ["Object 'nonsense' uses 'Nonsense Thing', which is not a stock object on Forge World."])
    nonsense["mj_type_name"] = "Health Cabinet"          # a Breakneck object, not a Forge World one
    refuse(env, "name_other_map", "E_OBJ_NAME_UNKNOWN", ["Object 'nonsense' uses 'Health Cabinet', which is not a stock object on Forge World."])

    # imported objects the stock table does not know (fixture holes): refused by default, kept when asked
    env.reset()
    import_data(env, rd.fixture("holes"), "holes.mvar")
    st = env.state.get(bpy.context.scene)
    check_eq(st["failed_slots"], [], "the unrecognised objects import (as arrow empties)")
    report = refuse(env, "imported_unrecognised", "E_OBJ_NOT_STOCK", ["is not a stock object on Forge World."])
    bpy.context.scene.forge.keepUnrecognisedObjects = True
    result, path = env.export_to("b16_holes_kept.mvar")
    check_eq(result, {'FINISHED'}, "kept when asked: %r\n%s" % (result, env.report_text()[:1500]))
    report = env.report_text()
    check("W_UNKNOWN_TYPE_KEPT" in report and "it was kept exactly as imported" in report, report[:2500])
    check(rd.read_bytes(path) == rd.fixture("holes"), "all kept: the exported file is the template, byte for byte")

    # a slot that FAILED to import and is not stock: the library keeps it without a stock check, so the glue refuses it
    env.reset()
    mj = env.mjolnir
    real_apply = mj.apply_record
    holes = rd.fixture("holes")
    bad_slot = 511                                       # folder 79 item 31: not a Forge World object

    def flaky(obj, rec, scene):
        real_apply(obj, rec, scene)
        if rec.slot in (bad_slot, 2):
            raise ValueError("synthetic import failure for slot %d" % rec.slot)

    with bl_common.patched(mj, "apply_record", flaky):
        with bl_common.capture_output() as out:
            import_data(env, holes, "holes_failed.mvar")
    st = env.state.get(bpy.context.scene)
    check_eq(sorted(st["failed_slots"]), [2, bad_slot])
    check_eq(sorted(env.state.failed_nonstock(bpy.context.scene)), [bad_slot], "only the unrecognised failed slot is flagged non-stock")
    check("could not be imported" in out[0] and "not stock objects of this map" in out[0], out[0][-1500:])
    bpy.context.scene.forge.keepUnrecognisedObjects = False
    report = refuse(env, "failed_slot_not_stock", "E_FAILED_SLOT_NOT_STOCK",
                    ["Slot 511 ('Unknown (0x4F1F)') could not be imported and is not a stock object on Forge World"])
    bpy.context.scene.forge.keepUnrecognisedObjects = True
    result, path = env.export_to("b16_failed_kept.mvar")
    check_eq(result, {'FINISHED'}, "failed slot kept when asked: %r\n%s" % (result, env.report_text()[:2000]))
    report = env.report_text()
    check("W_FAILED_SLOT_KEPT" in report and "NOT IMPORTED slot 511" in report and "NOT IMPORTED slot 2 " in report, report[:3000])
    check("W_SLOT_NOT_IMPORTED" in report, "the library's own warning for a slot it was told was not imported")
    check(rd.read_bytes(path) == holes, "the failed slots are kept exactly as they were")

    # a stock name whose palette entry the file does not define (Breakneck has 82 entries, 'Door' is entry 116)
    if rd.real_available():
        env.reset()
        env.use_library()
        import_data_path = rd.real_mvar_path()
        check_eq(env.import_file(import_data_path), {'FINISHED'})
        bpy.context.scene.forge.allowUnverifiedRotation = True
        door = new_model_less("far door", "Door", (1.0, 1.0, 5.0), via_menu=False)
        check_eq(env.mjolnir.forge_type_name(door), "Door")
        refuse(env, "folder_range", "E_FOLDER_RANGE", ["Object 'far door' needs palette entry 116, but this map variant defines only 82 entries."])


def limit_cases(env):
    # 650 occupied slots: exports; one more, or 651 in the file, does not
    env.reset()
    full = rd.fixture("full650")
    import_data(env, full, "full650.mvar")
    check_eq(len(env.forge_objects()), 650)
    result, path = env.export_to("b16_full650.mvar")
    check_eq(result, {'FINISHED'}, "full650 exports: %r\n%s" % (result, env.report_text()[:1500]))
    check(rd.read_bytes(path) == full, "full650: unchanged export is the template")
    bpy.context.scene.forge.allowUnverifiedRotation = True
    extra = copy_of(sorted(env.forge_objects(), key=lambda o: o["mj_slot"])[0])
    report = refuse(env, "full650_plus_one", "E_TOO_MANY", ["651 objects would be written; the limit is 650. Remove 1 object(s)."],
                    absent=("E_NO_FREE_SLOT",))
    check("E_NO_FREE_SLOT" not in report, "the 650 limit comes first; E_NO_FREE_SLOT is unreachable")
    bpy.data.objects.remove(extra, do_unlink=True)

    env.reset()
    import_data(env, rd.fixture("over650"), "over650.mvar")
    check_eq(len(env.forge_objects()), 651)
    refuse(env, "over650_unchanged", "E_TOO_MANY", ["651 objects would be written; the limit is 650."])
    # deleting one makes it exportable
    env.mjolnir.remove_with_helpers(sorted(env.forge_objects(), key=lambda o: o["mj_slot"])[-1])
    result, path = env.export_to("b16_over650_fixed.mvar")
    check_eq(result, {'FINISHED'}, "651 minus one exports: %r\n%s" % (result, env.report_text()[:1500]))

    if not rd.real_available():
        return
    # the real file: more refusals on a map with 20000-unit bounds and 82 palette entries
    env.reset()
    env.use_library()
    check_eq(env.import_file(rd.real_mvar_path()), {'FINISHED'})
    scene = bpy.context.scene
    by = dict((o["mj_slot"], o) for o in env.forge_objects())
    far = [o for o in by.values() if o.name.endswith("Cover, Large")][0]
    home = tuple(far.location)
    far.location.x = 25000.0
    refuse(env, "real_out_of_bounds", "E_OUT_OF_BOUNDS", ["outside the map bounds (x -20000.0 to 20000.0, y -20000.0 to 20000.0, z -20000.0 to 20000.0)"])
    far.location = home
    scene.forge.allowUnverifiedRotation = True
    stranger = new_model_less("stranger", "Block, 1x1", (1.0, 1.0, 5.0), via_menu=False)
    stranger["mj_type_name"] = "Spire Cannon, Base"           # a stock object of Spire, not of Breakneck
    stranger.instance_collection = None
    refuse(env, "real_name_unknown", "E_OBJ_NAME_UNKNOWN", ["Object 'stranger' uses 'Spire Cannon, Base', which is not a stock object on Breakneck."])
    bpy.data.objects.remove(stranger, do_unlink=True)

    # the real file: 610 + 40 = 650 fits, 41 more does not (and the quota row is raised or refused on top)
    env.reset()
    env.use_library()
    check_eq(env.import_file(rd.real_mvar_path()), {'FINISHED'})
    scene = bpy.context.scene
    scene.forge.allowUnverifiedRotation = True
    source = [o for o in env.forge_objects() if o.name.endswith("Cover, Large")][0]
    twins = [copy_of(source, (0.5 * (i + 1), 0.0, 0.0)) for i in range(41)]
    report = refuse(env, "real_plus_41", "E_TOO_MANY", ["651 objects would be written; the limit is 650. Remove 1 object(s)."],
                    also=("E_QUOTA",))
    report = refuse(env, "real_plus_41_raised", "E_TOO_MANY", ["651 objects would be written"], raise_quota_max=True, absent=("E_QUOTA",))
    bpy.data.objects.remove(twins.pop(), do_unlink=True)             # 40 extra: 650 objects
    refuse(env, "real_plus_40_quota", "E_QUOTA", ["would have 47 placed; the maximum on this map variant is 7."], absent=("E_TOO_MANY",))
    result, path = env.export_to("b16_real_plus_40.mvar", raise_quota_max=True)
    check_eq(result, {'FINISHED'}, "610 + 40 = 650 objects fit: %r\n%s" % (result, env.report_text()[:1500]))
    dec = rd.decode(rd.read_bytes(path))
    check_eq(len(dec["slots"]), 650, "650 occupied slots in the file")
    check_eq(sorted(dec["slots"]), list(range(650)), "the 40 new objects took slots 610 to 649 (free slots are filled from the lowest)")


def scene_cases(env, w1):
    # unevaluated array parent
    env.reset()
    import_data(env, w1, "array.mvar")
    obj = forge_by_slot()[5]
    plane = make_array(obj)
    plane.hide_set(True)
    refuse(env, "array_hidden", "E_ARRAY_NOT_EVALUATED", ["Array '5 - Kill Boundary' is hidden, excluded or empty, so its instances cannot be read."])

    # out of bounds, quota, class, label, gate, tilt, mirror
    env.reset()
    import_data(env, w1, "scene_cases.mvar")
    by = forge_by_slot()
    scene = bpy.context.scene
    by[1].location.x = 1000.0                           # W1's bounds are +-240
    refuse(env, "out_of_bounds", "E_OUT_OF_BOUNDS", ["outside the map bounds (x -240.0 to 240.0, y -345.0 to 345.0, z -70.0 to 70.0)",
                                                      "positions are never clamped"])
    by[1].location.x = 0.0

    # rotation gate: a turned object needs it, a tilt is never written
    by[1].rotation_euler.z = math.radians(30.0)
    refuse(env, "rotation_gate", "E_ROTATION_GATED", ["has a new or changed rotation. Writing rotation is unverified"])
    scene.forge.allowUnverifiedRotation = True
    result, path = env.export_to("b16_rotation_ok.mvar")
    check_eq(result, {'FINISHED'}, "with the gate a pure yaw is written: %r\n%s" % (result, env.report_text()[:1500]))
    check("W_ORIENTATION_UNVERIFIED" in env.report_text())
    by[1].rotation_euler.z = 0.0
    by[1].rotation_euler.x = math.radians(20.0)
    refuse(env, "tilt", "E_TILT_UNSUPPORTED", ["is tilted. Writing a tilted orientation is not supported"])
    by[1].rotation_euler.x = 0.0
    scene.forge.allowUnverifiedRotation = False

    # mirrored
    by[1].scale = (-1.0, 1.0, 1.0)
    refuse(env, "mirrored", "E_MIRRORED", ["Object '1 - Block, 1x1' has a mirrored (negative scale) transform, which cannot be exported."])
    by[1].scale = (1.0, 1.0, 1.0)

    # quota: row 61 (Kill Boundary) holds at most 1
    scene.forge.allowUnverifiedRotation = True
    twin = copy_of(by[5], (5.0, 0.0, 0.0))
    refuse(env, "quota", "E_QUOTA", ["Palette entry 61 (Kill Boundary) would have 2 placed; the maximum on this map variant is 1."])
    result, path = env.export_to("b16_quota_raised.mvar", raise_quota_max=True)
    check_eq(result, {'FINISHED'}, "the opt-in option raises the maximum: %r\n%s" % (result, env.report_text()[:1500]))
    check("W_QUOTA_MAX_RAISED" in env.report_text())
    dec = rd.decode(rd.read_bytes(path))
    check_eq(dec["quotas"][61], [0, 2, 2])
    bpy.data.objects.remove(twin, do_unlink=True)

    # an object class the file cannot teach: a weapon in a file that has none
    weapon = new_model_less("rifle", "Assault Rifle", (1.0, 1.0, 1.0), via_menu=False)   # weapons are not in the Add menu
    refuse(env, "class_unknown", "E_CACHED_TYPE_UNKNOWN",
           ["Cannot add a new 'Assault Rifle': its game object class is not known from this map variant."])
    bpy.data.objects.remove(weapon, do_unlink=True)

    # a label that is not in the file's table (reachable only when the stored label list and the file disagree)
    st_labels = bpy.context.scene["mjolnir"]["labels"]
    bpy.context.scene["mjolnir"]["labels"] = list(st_labels) + ["Bogus 3", "Bogus 4", "Bogus 5"]
    bpy.context.scene["mjolnir"]["label_present"] = [1] * 6
    by[1].forge.gtLabel = "L5"
    refuse(env, "label_range", "E_LABEL_RANGE", ["label 5 is not in this map variant's label table (3 labels)."])
    by[1].forge.gtLabel = "NO_LABEL"
    bpy.context.scene["mjolnir"]["labels"] = list(st_labels)
    bpy.context.scene["mjolnir"]["label_present"] = [1] * 3
    result, _path = env.export_to("b16_label_ok.mvar")
    check_eq(result, {'FINISHED'}, "everything restored: the export works again: %r" % (result,))


def path_cases(env, w1):
    env.reset()
    folder = os.path.join(env.tmp, "paths")
    os.makedirs(folder)
    source = os.path.join(folder, "source.mvar")
    with open(source, "wb") as fh:
        fh.write(w1)                                   # a throw-away copy; the real file is never a target
    check_eq(env.import_file(source), {'FINISHED'})
    by = forge_by_slot()
    by[1].location.x += 1.0                           # an edit, so overwriting would change the file
    bpy.context.view_layer.update()
    before = rd.read_bytes(source)

    def refused_target(label, target, code, contains):
        try:
            bpy.ops.export_scene.mjolnir_mvar(filepath=target)
            raised = None
        except RuntimeError as exc:
            raised = str(exc)
        check(raised is not None, "%s: the export was not refused" % label)
        report = env.report_text()
        check("ERROR %s" % code in report and REFUSED in report, "%s:\n%s" % (label, report[:1200]))
        for needle in contains:
            check(needle in report, "%s: %r" % (label, needle))
        check_eq(rd.read_bytes(source), before, label + ": the imported file is untouched")
        check_eq(sorted(n for n in os.listdir(folder)), sorted(listing), label + ": nothing was added to the folder")
        SEEN.append(code)

    alias = os.path.join(folder, "alias.mvar")
    os.symlink(source, alias)
    hard = os.path.join(folder, "hard.mvar")
    os.link(source, hard)
    listing = sorted(os.listdir(folder))
    refused_target("same path", source, "E_PATH_SAME_AS_SOURCE", ["Refusing to overwrite the file this map was imported from (%s)." % source])
    refused_target("symlink to the source", alias, "E_PATH_SAME_AS_SOURCE", ["Refusing to overwrite the file this map was imported from"])
    refused_target("hard link to the source", hard, "E_PATH_SAME_AS_SOURCE", ["Refusing to overwrite the file this map was imported from"])
    check(os.path.islink(alias) and os.path.samefile(hard, source))

    # a protected folder from the preferences, and the built-in sample folders (checked without writing there)
    protected = os.path.join(env.tmp, "protected")
    os.makedirs(protected)

    class FakePrefs(object):
        library_path = ""
        protected_folders = protected

    with bl_common.patched(env.palette, "_addon_preferences", lambda: FakePrefs()):
        try:
            bpy.ops.export_scene.mjolnir_mvar(filepath=os.path.join(protected, "out.mvar"))
            blocked = None
        except RuntimeError as exc:
            blocked = str(exc)
    check(blocked is not None, "protected folder: refused")
    check("ERROR E_PATH_PROTECTED" in env.report_text() and "Refusing to write into the protected folder %s." % protected in env.report_text())
    check_eq(os.listdir(protected), [], "nothing written into the protected folder")
    SEEN.append("E_PATH_PROTECTED")
    P = env.provider.get_provider()
    for built_in in ("~/Local_Documents/Halo-MCC/variant-tool/test-samples/x.mvar", "~/Local_Documents/Halo-MCC/forge/real-mvar-samples/x.mvar",
                     "~/Local_Documents/Halo-MCC/variant-tool/ReachVariantTool-core-library/macos/Fixtures/x.mvar"):
        issue = env.io_ops.path_issue(P, os.path.expanduser(built_in), source)
        check(issue is not None and issue.code == "E_PATH_PROTECTED", "%s: %r" % (built_in, issue))
    # and a different path is fine
    result, path = env.export_to("b16_paths_ok.mvar")
    check_eq(result, {'FINISHED'}, "a normal target works: %r" % (result,))
    # the file dialog proposes <source folder>/<stem>_mjolnir.mvar, or the fallback folder when the source folder is protected (2.13)
    proposed = env.io_ops.propose_output_path(P, source)
    check_eq(proposed, os.path.join(folder, "source_mjolnir.mvar"), "next to a source in an ordinary folder")
    fallback = env.io_ops.propose_output_path(P, os.path.expanduser("~/Local_Documents/Halo-MCC/forge/real-mvar-samples/0aaaf8c7.mvar"))
    check_eq(fallback, os.path.join(os.path.expanduser(env.io_ops.FALLBACK_EXPORT_DIR), "0aaaf8c7_mjolnir.mvar"),
             "a protected source folder gets the fallback folder")
    check(env.io_ops.path_issue(P, proposed, source) is None and env.io_ops.path_issue(P, fallback, source) is None, "both proposals are allowed targets")


def run_real(env):
    w1 = rd.fixture("w1_minimal")
    fingerprint = rd.file_fingerprint(rd.real_mvar_path()) if rd.real_available() else None
    template_and_map_cases(env, w1)
    stock_cases(env, w1)
    limit_cases(env)
    scene_cases(env, w1)
    path_cases(env, w1)
    if fingerprint is not None:
        check_eq(rd.file_fingerprint(rd.real_mvar_path()), fingerprint, "the real map variant is untouched")
    print("B-16 refusals, each through File > Export, each writing nothing: %s" % ", ".join(sorted(set(SEEN))))
    if not rd.real_available():
        raise bl_common.Skip("the real map variant is absent: the Breakneck cases (E_FOLDER_RANGE, +40/+41 objects) did not run")


if __name__ == "__main__":
    bl_common.main_module(sys.modules[__name__])
