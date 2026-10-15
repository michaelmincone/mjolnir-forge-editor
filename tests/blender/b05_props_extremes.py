"""B-05 (SPEC 9.4, 8.7 #4 #5 #6 #8 #13 #18): extreme values import and hand back unchanged.

Stub variant (``run``): the stub's ``CANNED_EXTREMES`` (shape 1, width 200, spawn sequence -128 and 127, team none,
placement byte 0xFF, label none, parent set) imports without an exception and every field comes back to the provider
unchanged ("zero diff" at the glue level).

Real variant (``run_real``, G6), with the REAL library and the independent builder:
* the builder's own ``extremes`` fixture (shape 3 with dims 0 and 0x7FF, spawn sequence -128 and 127, label 255 in a 256-entry
  table, folder 255, item 31, cached type 31, a zero-range axis, ...) imports every one of its 8 slots; exporting it is refused
  (``E_OBJ_NOT_STOCK`` x6 and ``E_OBJ_NO_TYPE``, nothing written) and with "Keep objects this tool does not recognise"
  it comes back BYTE FOR BYTE (a zero diff, 8 ``kept``, ``W_UNKNOWN_TYPE_KEPT``);
* an extremes fixture with STOCK types (sphere with width 200, spawn sequence -128 and 127, team none, placement 0xFF, colour 7,
  labels, parent links, a box with dimensions 200) imports and exports unchanged with a byte-level zero diff;
* every property edit lands in exactly one field of the independent decode (spawn sequence, spawn time, team, colour, label,
  physics, the box dimensions, the extras of a weapon ...) and nothing else changes;
* one bad object never aborts an import: failed slots are counted, kept unchanged by the real export (``NOT IMPORTED``,
  ``W_SLOT_NOT_IMPORTED``), and leave no half-built object.
Also (both): every property range and enum round-trips.
"""
import os
import sys

import bpy

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common  # noqa: E402
import real_data as rd  # noqa: E402
from bl_common import check, check_close, check_eq  # noqa: E402

ID = "b05"
TITLE = "extremes import, every range and enum round-trips, per-object failure isolation"
NEEDS_STUB = True


def check_ranges_and_enums(env, by_slot, o3):
    """Every property range clamps at its hard limit, every enum item exists with its stored number and exports its integer."""
    mj = env.mjolnir
    scene = bpy.context.scene
    # --- every property range (8.7 #5): clamped at the hard limits, the sliders keep the old soft feel
    fp = o3.forge
    for name, low, high in (("width", 0, 200), ("length", 0, 200), ("top", 0, 200), ("bottom", 0, 200),
                            ("spawnSequence", -128, 127), ("spawnTime", 0, 255), ("otherInfoA", 0, 255),
                            ("otherInfoB", 0, 255), ("cachedType", 0, 31)):
        setattr(fp, name, low - 50)
        check_eq(getattr(fp, name), low, "%s low clamp" % name)
        setattr(fp, name, high + 50)
        check_eq(getattr(fp, name), high, "%s high clamp" % name)
        setattr(fp, name, low)
        check_eq(getattr(fp, name), low, name)
    props = fp.bl_rna.properties
    check_close([props["width"].soft_max], [100.9], 1e-4, "soft limit keeps the old slider feel")
    check_eq((props["spawnSequence"].soft_min, props["spawnSequence"].soft_max), (-100, 100))
    check_eq((props["spawnSequence"].hard_min, props["spawnSequence"].hard_max), (-128, 127), "hard range")
    check_close([props["width"].hard_max], [200.0], 1e-6, "hard range of the dimensions")

    # --- the numbers a .blend stores for the enums are the ones forge.py v0.9.9.2 used (it numbered the items by
    # position), so a .blend saved by the old add-on reads back the same values; SPHERE and NEITHER are new and
    # take the next free numbers
    stored = {
        "physics": {"NORMAL": 0, "FIXED": 1, "PHASED": 2},
        "symmetry": {"BOTH": 0, "SYMMETRIC": 1, "ASYMMETRIC": 2, "NEITHER": 3},
        "shape": {"NONE": 0, "CYLINDER": 1, "BOX": 2, "SPHERE": 3},
    }
    for prop, table in stored.items():
        actual = dict((i.identifier, i.value) for i in o3.forge.bl_rna.properties[prop].enum_items)
        check_eq(actual, table, "stored enum numbers of %s" % prop)
    legacy = bpy.data.objects.new("legacy", None)             # raw values as a pre-1.0 .blend holds them
    scene.collection.objects.link(legacy)
    for prop, table in stored.items():
        for ident, number in table.items():
            legacy.forge[prop] = number
            check_eq(getattr(legacy.forge, prop), ident, "stored %s=%d reads as %s" % (prop, number, ident))
    bpy.data.objects.remove(legacy, do_unlink=True)

    # --- every enum item round-trips and exports the documented integer
    ints = {
        "physics": {"NORMAL": 0, "FIXED": 1, "PHASED": 3},
        "symmetry": {"BOTH": 3, "SYMMETRIC": 2, "ASYMMETRIC": 1, "NEITHER": 0},
        "shape": {"NONE": 0, "SPHERE": 1, "CYLINDER": 2, "BOX": 3},
    }
    fp = by_slot[1].forge
    obj = by_slot[1]
    for prop, table in ints.items():
        items = [i.identifier for i in fp.bl_rna.properties[prop].enum_items]
        check_eq(sorted(items), sorted(table), "%s items" % prop)
        for ident, number in table.items():
            setattr(fp, prop, ident)
            check_eq(getattr(fp, prop), ident, "%s=%s" % (prop, ident))
            eo, _problems = mj.to_export_object(env.provider.get_provider(), obj, obj.matrix_world)
            check_eq(getattr(eo, prop), number, "%s=%s exports %d" % (prop, ident, number))
    for index, name in enumerate(mj.TEAM_NAMES):
        fp.team = name
        fp.color = name
        eo, _problems = mj.to_export_object(env.provider.get_provider(), obj, obj.matrix_world)
        check_eq((eo.team, eo.color), (index, index), "team/color %s" % name)
        check_eq(fp.colorIndex, index, "colorIndex follows the colour")
    fp.color = "TEAM_COLOR"
    fp.team = "GREEN"
    check_eq(fp.colorIndex, 2, "team colour: colorIndex follows the team")
    eo, _problems = mj.to_export_object(env.provider.get_provider(), obj, obj.matrix_world)
    check_eq((eo.team, eo.color), (2, -1))
    # labels: NO_LABEL and every present entry
    for ident, index in (("NO_LABEL", -1), ("L0", 0), ("L1", 1), ("L2", 2)):
        fp.gtLabel = ident
        eo, _problems = mj.to_export_object(env.provider.get_provider(), obj, obj.matrix_world)
        check_eq(eo.label_index, index, "label %s" % ident)


def run(env):
    stub = env.stub
    mj = env.mjolnir

    result, _ = env.import_stub(load=stub.CANNED_EXTREMES)
    check_eq(result, {'FINISHED'})
    scene = bpy.context.scene
    by_slot = dict((o["mj_slot"], o) for o in env.forge_objects())
    check_eq(sorted(by_slot), [1, 2, 3])
    o1, o2, o3 = by_slot[1], by_slot[2], by_slot[3]

    # shape 1 is a sphere now (8.7 #6), not flattened to NONE; radius = width = 200 (hard limit is 200, 8.7 #5)
    check_eq(o1.forge.shape, "SPHERE")
    check_eq(o1.forge.width, 200.0)
    helper = [c for c in o1.children if c.get("mj_helper") == "shape"][0]
    check_eq(helper.empty_display_type, "SPHERE")
    check_eq(helper.empty_display_size, 200.0)
    check_eq(o1.forge.spawnSequence, -128)
    check_eq(o1.forge.spawnTime, 255)
    check_eq(o1.forge.team, "NEUTRAL", "team none shows as neutral")
    check_eq(o1.forge.color, "TEAM_COLOR")
    check_eq(o1.forge.gtLabel, "NO_LABEL")
    check_eq((o1.forge.physics, o1.forge.symmetry, o1.forge.placeAtStart, o1.forge.gameSpecific),
             ("PHASED", "BOTH", False, True), "placement byte 0xFF decoded with the file reading")
    check_eq(o2.forge.spawnSequence, 127)
    check_eq((o2.forge.team, o2.forge.color, o2.forge.gtLabel), ("RED", "PINK", "L0"))
    check_eq((o2.forge.physics, o2.forge.symmetry, o2.forge.placeAtStart, o2.forge.gameSpecific),
             ("NORMAL", "NEITHER", True, False), "placement byte 0x00")
    check_eq(o2["mj_parent_slot"], 1)
    check_eq(o3.forge.shape, "BOX")
    check_close((o3.forge.width, o3.forge.length, o3.forge.top, o3.forge.bottom), (200, 200, 200, 0), 1e-6)
    check_eq(o3.forge.gtLabel, "L2")

    # everything comes back to the provider unchanged
    collected = env.io_ops.collect_export_objects(scene)
    check_eq([e.code for e in collected.errors], [], "no glue-level problem")
    check_eq(len(collected.objects), 3)
    exported = dict((e.slot, e) for e in collected.objects)
    for rec in stub.CANNED_EXTREMES.objects:
        diffs = bl_common.record_vs_export(rec, exported[rec.slot])
        check_eq(diffs, [], "slot %d comes back unchanged" % rec.slot)
    result, path = env.export_to("b05.mvar")
    check_eq(result, {'FINISHED'}, "export of the extremes")
    template, objects, options = stub.LAST_EXPORT
    check_eq(options.imported_slots, [1, 2, 3])
    check_eq(options.allow_unverified_rotation, False)
    check_eq(options.fsm_policy, "KEEP")
    check_eq(options.hash_policy, "REPRODUCE")
    check_eq(options.force_reencode, False)
    check_eq(options.keep_unrecognised_imported, False)
    check(os.path.exists(path), "file written")

    check_ranges_and_enums(env, by_slot, o3)

    # --- one bad object never aborts the import (8.7 #4)
    env.reset()
    real_apply = mj.apply_record

    def flaky(obj, rec, scene):
        real_apply(obj, rec, scene)
        if rec.slot == 2:
            raise ValueError("synthetic failure for slot 2")

    with bl_common.patched(mj, "apply_record", flaky):
        with bl_common.capture_output() as out:
            result, _ = env.import_stub()
    check_eq(result, {'FINISHED'}, "the import survives a failing object")
    check("1 objects could not be imported" in out[0], "the failure is reported: " + out[0])
    objs = env.forge_objects()
    check_eq(sorted(o["mj_slot"] for o in objs), [1, 5, 9, 11], "the other objects are there")
    check(all("mj_slot" in o for o in objs), "no half-built object is left behind")
    check(not [o for o in bpy.data.objects if o.name.startswith("2 - ")], "slot 2 left nothing behind")
    st = env.state.get(bpy.context.scene)
    check_eq(st["imported_slots"], [1, 5, 9, 11])
    check_eq(st["failed_slots"], [2])
    result, _ = env.export_to("b05_partial.mvar")
    check_eq(result, {'FINISHED'})
    template, objects, options = stub.LAST_EXPORT
    check_eq(options.imported_slots, [1, 5, 9, 11], "a failed slot is not an imported slot (never treated as deleted)")
    check_eq(sorted(o.slot for o in objects), [1, 5, 9, 11])


# =====================================================================================================
# the real-provider variant (G6)
# =====================================================================================================
def stock_extremes_data():
    """Extreme field values on STOCK types (so a zero-diff export is allowed): a sphere with width 200, spawn sequence -128 and
    127, team none, colour 7, placement bytes 0xFF and 0x00, labels, parent links and a box with dimensions 200."""
    spec = rd.w1_spec("b05_extremes_stock", "extreme field values on stock types, for the Blender tests")
    spec["slots"] = [
        {"index": 1, "folder": 70, "item": 0, "pos": [524288, 1048576, 262144], "shape": 1, "dims": [2047], "spawn_seq": -128,
         "respawn": 255, "team_raw": 0, "placement": 0xFF},
        {"index": 2, "folder": 70, "item": 0, "pos": [524289, 1048577, 262145], "spawn_seq": 127, "team_raw": 1, "color": 7,
         "label": 0, "parent_raw": 2, "placement": 0x00},
        {"index": 3, "folder": 61, "item": 0, "pos": [600000, 700000, 200000], "shape": 3, "dims": [2047, 2047, 2047, 0],
         "cached_type": 26, "team_raw": 9, "label": 2, "parent_raw": 3, "placement": 0x0C},
    ]
    spec["quotas"]["rows"] = {"61": [0, 1, 1], "70": [0, 16, 2]}
    return rd.build_spec(spec)


def exported_file(env, name, **options):
    result, path = env.export_to(name, **options)
    check_eq(result, {'FINISHED'}, "%s: %r\n%s" % (name, result, env.report_text()[:2500]))
    return rd.read_bytes(path)


def run_real(env):
    _build, selfcheck, _catalogue = rd.modules()
    mj = env.mjolnir
    scene = bpy.context.scene

    # --- the builder's own extremes fixture: all 8 slots import, nothing fails ---------------------------------------------------
    data = rd.fixture("extremes")
    dec = rd.decode(data)
    result, _ = env.import_bytes(data, "b05_extremes.mvar")
    check_eq(result, {'FINISHED'})
    st = env.state.get(scene)
    check_eq((st["imported_slots"], st["failed_slots"]), ([0, 1, 2, 3, 4, 5, 6, 650], []), "every extreme slot imports")
    check_eq(list(st["hypothesis"]["axis_bits"]), [23, 15, 0], "axis bits 23, 15 and 0 (z has a zero range)")
    check_eq(len(st["labels"]), 256)
    by = dict((o["mj_slot"], o) for o in env.forge_objects())
    s1 = dec["slots"][1]                                       # folder 255 item 31, shape 3, label 255, colour 7, parent 651
    f1 = by[1].forge
    check_eq((f1.shape, f1.cachedType, f1.spawnSequence, f1.spawnTime, f1.gtLabel, f1.color, f1.team),
             ("BOX", 31, 127, 255, "L255", "PINK", "NEUTRAL"), "slot 1 of the extremes fixture")
    check_close((f1.width, f1.length, f1.top, f1.bottom), tuple(selfcheck.dim_decode(v) for v in s1["dims"]), 1e-4, "box dims 0 / 2047 / 0 / 2047")
    check_eq(by[1]["mj_parent_slot"], 650, "parent raw 651 is slot 650")
    check_eq((by[0].forge.spawnSequence, by[0].forge.team), (-128, "NEUTRAL"), "slot 0: spawn sequence -128, team none shown as neutral")
    check_eq((by[2].forge.shape, by[2].forge.width, by[2].forge.gtLabel), ("SPHERE", 200.0, "L0"), "slot 2: a sphere of radius 200")
    check_eq(by[3].forge.shape, "CYLINDER")
    check_eq(by[3].forge.gtLabel, "L128", "label 128")
    check_eq(by[4].forge.gtLabel, "L253")
    check_eq((by[5].forge.cachedType, by[5].forge.otherInfoA), (1, 255), "weapon with 255 spare clips")
    helper = [c for c in by[2].children if c.get("mj_helper") == "shape"][0]
    check_eq((helper.empty_display_type, helper.empty_display_size), ("SPHERE", 200.0))
    # refused as it is (unrecognised ids; one object has no type at all) ...
    result, path = env.export_to("b05_extremes_refused.mvar")
    check(isinstance(result, RuntimeError), "refused: %r" % (result,))
    report = env.report_text()
    check(report.count("ERROR E_OBJ_NOT_STOCK") == 6 and report.count("ERROR E_OBJ_NO_TYPE") == 1, report[:2500])
    check(not os.path.exists(path), "nothing written")
    # ... and kept byte for byte when asked
    scene.forge.keepUnrecognisedObjects = True
    kept = exported_file(env, "b05_extremes_kept.mvar")
    check(kept == data, "extremes fixture: a zero diff, the exported file is the template byte for byte")
    report = env.report_text()
    check(report.count("W_UNKNOWN_TYPE_KEPT") == 7 and "Objects: 8 before, 8 after" in report, report[:2500])
    check(report.count("  KEPT slot") == 8, "8 kept")

    # --- stock extremes: a byte-level zero diff without any option --------------------------------------------------------------
    env.reset()
    data = stock_extremes_data()
    dec = rd.decode(data)
    result, _ = env.import_bytes(data, "b05_stock.mvar")
    check_eq(result, {'FINISHED'})
    by = dict((o["mj_slot"], o) for o in env.forge_objects())
    check_eq(sorted(by), [1, 2, 3])
    o1, o2, o3 = by[1], by[2], by[3]
    check_eq(o1.forge.shape, "SPHERE")
    check_eq(o1.forge.width, 200.0)
    check_eq((o1.forge.spawnSequence, o1.forge.spawnTime, o1.forge.team, o1.forge.color, o1.forge.gtLabel),
             (-128, 255, "NEUTRAL", "TEAM_COLOR", "NO_LABEL"))
    check_eq((o1.forge.physics, o1.forge.symmetry, o1.forge.placeAtStart, o1.forge.gameSpecific), ("PHASED", "BOTH", False, True))
    check_eq((o2.forge.spawnSequence, o2.forge.team, o2.forge.color, o2.forge.gtLabel), (127, "RED", "PINK", "L0"))
    check_eq((o2.forge.physics, o2.forge.symmetry, o2.forge.placeAtStart, o2.forge.gameSpecific), ("NORMAL", "NEITHER", True, False))
    check_eq((o2["mj_parent_slot"], o3["mj_parent_slot"]), (1, 2))
    check_close((o3.forge.width, o3.forge.length, o3.forge.top, o3.forge.bottom), (200.0, 200.0, 200.0, 0.0), 1e-4)
    check_eq(exported_file(env, "b05_stock_noop.mvar"), data, "stock extremes: a zero diff without any option")
    check("Objects: 3 before, 3 after" in env.report_text() and env.report_text().count("  KEPT slot") == 3)

    # --- every property edit lands in exactly one field of the independent decode --------------------------------------------------
    expected = {
        # (object slot, property, new value): (decode field, expected decoded value)
        (1, "spawnSequence", -7): ("spawn_seq", -7),
        (1, "spawnTime", 33): ("respawn", 33),
        (2, "gtLabel", "L2"): ("label", 2),
        (2, "gtLabel", "NO_LABEL"): ("label", None),
        (2, "team", "BLUE"): ("team_raw", 2),
        (2, "color", "ORANGE"): ("color", 3),
        (2, "color", "TEAM_COLOR"): ("color", None),
        (1, "physics", "FIXED"): ("placement", (0xFF & 0x3F) | 0x40),
        (1, "physics", "NORMAL"): ("placement", 0xFF & 0x3F),
        (2, "physics", "FIXED"): ("placement", 0x40),
        (3, "spawnSequence", 99): ("spawn_seq", 99),
    }
    for (slot, prop, value), (field, want) in sorted(expected.items(), key=lambda kv: (kv[0][0], kv[0][1], str(kv[0][2]))):
        env.reset()
        env.import_bytes(data, "b05_edit.mvar")
        obj = dict((o["mj_slot"], o) for o in env.forge_objects())[slot]
        setattr(obj.forge, prop, value)
        out = exported_file(env, "b05_edit_out.mvar")
        after = rd.decode(out)
        check_eq(rd.slots_equal(dec, after, ignore=(slot,)), [], "%s=%r on slot %d: the other slots are unchanged" % (prop, value, slot))
        changed = rd.fields_differing(dec["slots"][slot], after["slots"][slot])
        check_eq(changed, [field], "%s=%r on slot %d changes exactly the field %s" % (prop, value, slot, field))
        check_eq(after["slots"][slot][field], want, "%s=%r on slot %d: the decoded %s" % (prop, value, slot, field))
    # the box dimensions of slot 3 and the sphere radius of slot 1 (11-bit codes through the dimension codec)
    for slot, prop, value, field_index in ((3, "length", 17.25, 1), (3, "bottom", 12.0, 3), (1, "width", 50.0, 0)):
        env.reset()
        env.import_bytes(data, "b05_dims.mvar")
        obj = dict((o["mj_slot"], o) for o in env.forge_objects())[slot]
        setattr(obj.forge, prop, value)
        after = rd.decode(exported_file(env, "b05_dims_out.mvar"))
        check_eq(rd.fields_differing(dec["slots"][slot], after["slots"][slot]), ["dims"], "%s=%r changes only the dimensions" % (prop, value))
        check_eq(after["slots"][slot]["dims"][field_index], selfcheck.dim_encode(value), "%s=%r: the 11-bit code" % (prop, value))
    # symmetry, place at start and game specific are refused (how they are stored is unverified, SPEC 3.9)
    for prop, value in (("symmetry", "SYMMETRIC"), ("placeAtStart", True), ("gameSpecific", False)):
        env.reset()
        env.import_bytes(data, "b05_flags.mvar")
        obj = dict((o["mj_slot"], o) for o in env.forge_objects())[1]
        setattr(obj.forge, prop, value)
        result, path = env.export_to("b05_flags_refused.mvar")
        check(isinstance(result, RuntimeError) and "ERROR E_FLAG_UNVERIFIED" in env.report_text(), "%s=%r is refused: %r" % (prop, value, result))
        check(not os.path.exists(path), "nothing written")

    # --- ranges and enums (shared with the stub variant) ---------------------------------------------------------------------------------
    env.reset()
    env.import_bytes(data, "b05_ranges.mvar")
    by = dict((o["mj_slot"], o) for o in env.forge_objects())
    check_ranges_and_enums(env, by, by[3])

    # --- one bad object never aborts the import (8.7 #4) -----------------------------------------------------------------------------------
    env.reset()
    real_apply = mj.apply_record

    def flaky(obj, rec, scene):
        real_apply(obj, rec, scene)
        if rec.slot == 2:
            raise ValueError("synthetic failure for slot 2")

    with bl_common.patched(mj, "apply_record", flaky):
        with bl_common.capture_output() as out:
            result, _ = env.import_bytes(data, "b05_flaky.mvar")
    check_eq(result, {'FINISHED'}, "the import survives a failing object")
    check("1 objects could not be imported" in out[0], "the failure is reported: " + out[0])
    objs = env.forge_objects()
    check_eq(sorted(o["mj_slot"] for o in objs), [1, 3], "the other objects are there")
    check(not [o for o in bpy.data.objects if o.name.startswith("2 - ")], "slot 2 left nothing behind")
    st = env.state.get(bpy.context.scene)
    check_eq((st["imported_slots"], st["failed_slots"]), ([1, 3], [2]))
    out_bytes = exported_file(env, "b05_flaky_out.mvar")
    check(out_bytes == data, "a failed slot is kept exactly as it was (never treated as deleted)")
    report = env.report_text()
    check("NOT IMPORTED slot 2 " in report and "W_SLOT_NOT_IMPORTED" in report, report[:2500])
    # moving the other objects still works around the failed slot
    dict((o["mj_slot"], o) for o in env.forge_objects())[1].location.x += 1.0
    moved = exported_file(env, "b05_flaky_moved.mvar")
    after = rd.decode(moved)
    check_eq(rd.slots_equal(dec, after, ignore=(1,)), [], "slot 2 and slot 3 are unchanged; only slot 1 moved")
    check_eq(rd.fields_differing(dec["slots"][1], after["slots"][1]), ["pos"])


if __name__ == "__main__":
    bl_common.main_module(sys.modules[__name__])
