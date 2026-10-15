"""B-23 (extra, SPEC 4.8 / 4.9 glue half, 8.5): an untouched object is never reported as moved or rotated.

The library keeps an object's original raw bits only when the position handed to it is within ``POS_TOL`` (1e-3) and
forward and up are within ``ANG_TOL`` (1e-4 rad) of the pose it decoded. Blender cannot always give that pose back:
``matrix_world`` is recomposed from location / rotation / scale on the next depsgraph update, which re-orthonormalises
the rotation, so a forward / up pair that is not perpendicular drifts by milliradians. The glue therefore compares
Blender with Blender (the pose read right after import against the pose read at export, through the same code) and
hands back the record's own numbers for every part that did not change.

Records here: a perpendicular control, a pair 0.2 degrees off perpendicular, a tilted pair that is not perpendicular,
and a forward parallel to up (degenerate). Checked: the premise (the raw Blender pose WOULD look changed to the
library), the import (orthonormal rotation, unit scale), the no-op export (the record's numbers, exactly), position
and orientation judged separately, tolerances, hidden objects, duplicates, objects without a baseline, save and
reopen. The byte-level proof with the real codec is the G6 run (``run_real``).

Added in G6: a change in ``up`` ALONE counts as a turn (a rotation about the forward axis leaves forward where it was; a
glue that looked only at forward would hand the old ``up`` back and drop the user's edit silently), and float32 noise on an
axis-aligned rotation is removed (``snap_axis``: ``cos`` of the float32 ``-pi/2`` is ``-4.4e-8``, which the flooring angle
quantiser would write one cell low).

Real variant (``run_real``): the real Breakneck file (207 tilted objects): moving a tilted object keeps its orientation bits;
turning a vertical object changes only its angle; a tilted object that is turned, and a vertical object whose ``up`` alone changed,
are refused (``E_TILT_UNSUPPORTED``) instead of passing as unchanged; noise below the tolerances is ignored; a move below the
quantisation step is not written; all of it survives save and reopen.
"""
import dataclasses
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common  # noqa: E402
import real_data as rd  # noqa: E402
from bl_common import check, check_close, check_eq  # noqa: E402

ID = "b23"
TITLE = "untouched objects keep the record's pose: non-orthonormal forward/up, moved and rotated judged separately"
NEEDS_STUB = True

LIB_POS_TOL = 1e-3            # SPEC 4.9 (POS_TOL = max(1e-3, ...))
LIB_ANG_TOL = 1e-4            # SPEC 4.9 (ANG_TOL)
FW = "Forge World"


def unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


class Pose(object):
    """A bare ``position / forward / up`` holder shaped like the fields the library compares."""
    def __init__(self, position, forward, up):
        self.position, self.forward, self.up = position, forward, up


def library_sees_change(rec, eo):
    """What the library's change detection (SPEC 4.9) would conclude from ``eo`` against ``rec``: (moved, turned)."""
    moved = any(abs(a - b) > LIB_POS_TOL for a, b in zip(rec.position, eo.position))
    turned = (Vector(rec.forward).angle(Vector(eo.forward), 0.0) > LIB_ANG_TOL
              or Vector(rec.up).angle(Vector(eo.up), 0.0) > LIB_ANG_TOL)
    return moved, turned


def canned_load(env):
    stub = env.stub
    ang = math.radians(89.8)
    records = [
        stub.make_record(1, FW, "Block, 1x1", (10.0, 20.0, 5.0)),                                     # control
        stub.make_record(2, FW, "Block, 1x1", (-15.5, 3.25, 1.0), forward=(1.0, 0.0, 0.0),
                         up=(math.cos(ang), 0.0, math.sin(ang)), orientation_kind="tilted"),         # 0.2 deg off
        stub.make_record(3, FW, "Block, 1x1", (-60.0, -80.0, 20.0), forward=unit((1.0, 0.15, 0.1)),
                         up=unit((0.3, -0.2, 0.9)), orientation_kind="tilted"),                       # tilted, skewed
        stub.make_record(4, FW, "Block, 1x1", (7.0, 8.0, 9.0), forward=(0.0, 0.0, 1.0), up=(0.0, 0.0, 1.0)),
    ]
    info = dataclasses.replace(stub.CANNED.info, occupied=len(records))
    return dataclasses.replace(stub.CANNED, info=info, objects=records)


def fresh(env, load):
    env.reset()
    result, _ = env.import_stub(load=load)
    check_eq(result, {'FINISHED'})
    return dict((o["mj_slot"], o) for o in env.forge_objects())


def handed_over(env, name="b23.mvar"):
    result, path = env.export_to(name)
    check_eq(result, {'FINISHED'}, "export")
    return dict((o.slot, o) for o in env.stub.LAST_EXPORT[1])


def assert_record_pose(rec, eo, what):
    check_eq(tuple(eo.position), tuple(rec.position), "%s: position is the record's, exactly" % what)
    check_eq(tuple(eo.forward), tuple(rec.forward), "%s: forward is the record's, exactly" % what)
    check_eq(tuple(eo.up), tuple(rec.up), "%s: up is the record's, exactly" % what)
    check_eq(library_sees_change(rec, eo), (False, False), "%s: the library sees no change" % what)


def turn_about_forward(obj, angle):
    """Rotate ``obj`` about its own forward axis through its own origin: forward and position stay, up tilts."""
    m = obj.matrix_world.copy()
    axis = m.col[1].xyz.normalized()
    rotation = Matrix.Rotation(angle, 3, axis) @ m.to_3x3()
    obj.matrix_world = Matrix.Translation(m.translation) @ rotation.to_4x4()
    bpy.context.view_layer.update()


def blender_pose(env, obj):
    """The pose Blender holds for ``obj`` now (the export's own reading), as an ``ExportObject``-like triple."""
    bpy.context.view_layer.update()
    return env.mjolnir.pose_from_matrix(obj.matrix_world)


def run(env):
    mj = env.mjolnir
    load = canned_load(env)
    records = dict((r.slot, r) for r in load.objects)

    # --- the premise: without the baseline the library WOULD see a change ------------------------------------------------
    by = fresh(env, load)
    for slot in (1, 2, 3, 4):
        pos, fwd, up = blender_pose(env, by[slot])
        moved, turned = library_sees_change(records[slot], Pose(pos, fwd, up))
        check_eq(moved, False, "slot %d: the position survives the depsgraph" % slot)
        if slot == 1:
            check_eq(turned, False, "the perpendicular control survives unchanged")
        else:
            check_eq(turned, True, "slot %d: Blender's own reading of the skewed pair is more than 1e-4 rad off, so the "
                                   "raw pose would be reported as rotated" % slot)

    # --- the import: orthonormal rotation, unit scale, a baseline on every imported object ---------------------------
    for slot, obj in by.items():
        m3 = obj.matrix_world.to_3x3()
        check(m3.determinant() > 0, "slot %d: a proper rotation" % slot)
        check_close(tuple(obj.scale), (1.0, 1.0, 1.0), 1e-5, "slot %d: the skewed pair no longer leaks into the scale" % slot)
        product = m3 @ m3.transposed()
        for i in range(3):
            for j in range(3):
                check(abs(product[i][j] - (1.0 if i == j else 0.0)) < 1e-5, "slot %d: orthonormal rotation" % slot)
        check_eq(len(obj["mj_pose"]), 9, "slot %d: the record's pose is kept" % slot)
        check_eq(len(obj["mj_base"]), 9, "slot %d: the Blender-side baseline is kept" % slot)
        check_eq(tuple(obj["mj_pose"]), tuple(records[slot].position) + tuple(records[slot].forward) + tuple(records[slot].up))
        check_close(tuple(obj["mj_base"]), sum(blender_pose(env, obj), ()), 1e-9, "baseline == the export's reading")
    # up is the stored axis: it stays exactly where the record put it (to float32), forward is the one that gives way
    for slot in (2, 3, 4):
        check_close(by[slot].matrix_world.col[2].xyz, records[slot].up, 1e-5, "slot %d: up kept" % slot)
    check_close(by[4].matrix_world.col[1].xyz.length, 1.0, 1e-5, "degenerate forward: still a unit vector")

    # --- the no-op export hands the record's own numbers back --------------------------------------------------------------
    objs = handed_over(env, "b23_noop.mvar")
    check_eq(sorted(objs), [1, 2, 3, 4])
    for slot, rec in records.items():
        assert_record_pose(rec, objs[slot], "no-op slot %d" % slot)
        check_eq(bl_common.record_vs_export(rec, objs[slot], 1e-12, 1e-12, 1e-12), [], "slot %d: every field" % slot)

    # --- position and orientation are judged separately ---------------------------------------------------------------
    by[2].location.x += 1.0                                                 # moved, not turned
    by[3].rotation_euler.z += math.radians(90.0)                           # turned, not moved
    by[1].location.y += 2.0
    by[1].rotation_euler.z += math.radians(30.0)                           # both
    objs = handed_over(env, "b23_edits.mvar")
    eo = objs[2]
    check_close(eo.position, (records[2].position[0] + 1.0, records[2].position[1], records[2].position[2]), 1e-4, "moved")
    check_eq((tuple(eo.forward), tuple(eo.up)), (records[2].forward, records[2].up), "a move keeps the record's orientation")
    check_eq(library_sees_change(records[2], eo), (True, False))
    eo = objs[3]
    check_eq(tuple(eo.position), tuple(records[3].position), "a turn keeps the record's position")
    bpy.context.view_layer.update()
    turned_fwd = by[3].matrix_world.col[1].xyz.normalized()
    check_close(eo.forward, turned_fwd, 1e-6, "a turn hands over Blender's orientation")
    check_close(eo.up, by[3].matrix_world.col[2].xyz.normalized(), 1e-6)
    check(Vector(records[3].forward).angle(Vector(eo.forward)) > 1.0, "...which is far from the record's")
    check_eq(library_sees_change(records[3], eo), (False, True))
    eo = objs[1]
    check_close(eo.position, (10.0, 22.0, 5.0), 1e-4)
    check_eq(library_sees_change(records[1], eo), (True, True))
    assert_record_pose(records[4], objs[4], "the untouched neighbour")

    # --- tolerances: Blender-side noise is ignored, a real edit is not --------------------------------------------------------
    by = fresh(env, load)
    by[1].location.x += 1e-5
    by[2].rotation_euler.z += 1e-5
    by[3].location.z += 2e-3
    by[4].rotation_euler.x += 1e-3
    objs = handed_over(env, "b23_tol.mvar")
    assert_record_pose(records[1], objs[1], "1e-5 move")
    assert_record_pose(records[2], objs[2], "1e-5 rad turn")
    check_close(objs[3].position, (records[3].position[0], records[3].position[1], records[3].position[2] + 2e-3), 1e-4,
                "a 2e-3 move is real")
    check(Vector(objs[4].forward).angle(Vector(records[4].forward)) > 5e-4, "a 1e-3 rad turn is real")

    # --- hidden objects: the pose is read another way (rebuilt from the local transforms), still not "changed" ---------------
    by = fresh(env, load)
    by[2].hide_viewport = True
    by[3].hide_set(True)
    objs = handed_over(env, "b23_hidden.mvar")
    for slot in (1, 2, 3, 4):
        assert_record_pose(records[slot], objs[slot], "hidden/visible slot %d" % slot)
    check_eq(sorted(s for s, o in objs.items() if o.hidden), [2, 3])
    excluded = bpy.data.collections.new("Excluded")
    bpy.context.scene.collection.children.link(excluded)
    bpy.context.scene.collection.objects.unlink(by[3])
    excluded.objects.link(by[3])
    bpy.context.view_layer.layer_collection.children["Excluded"].exclude = True
    objs = handed_over(env, "b23_excluded.mvar")
    assert_record_pose(records[3], objs[3], "slot 3 in an excluded collection")

    # --- duplicates share the baseline: unmoved = record, moved = its own position ----------------------------------------------
    by = fresh(env, load)
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    by[2].select_set(True)
    bpy.context.view_layer.objects.active = by[2]
    check_eq(bpy.ops.object.duplicate(), {'FINISHED'})
    dup = [o for o in env.forge_objects() if o is not by[2] and o.get("mj_slot") == 2][0]
    claimants = [o for o in handed_over_list(env, "b23_dup.mvar") if o.slot == 2]
    check_eq(len(claimants), 2, "the original and the duplicate both claim slot 2")
    for eo in claimants:
        assert_record_pose(records[2], eo, "unmoved duplicate and original")
    dup.location = (50.0, 60.0, 70.0)
    claimants = [o for o in handed_over_list(env, "b23_dup_moved.mvar") if o.slot == 2]
    moved = [o for o in claimants if o.position[0] > 40]
    check_eq(len(moved), 1, "the moved duplicate")
    check_close(moved[0].position, (50.0, 60.0, 70.0), 1e-4)
    check_eq((tuple(moved[0].forward), tuple(moved[0].up)), (records[2].forward, records[2].up), "...still not turned")
    still = [o for o in claimants if o.position[0] <= 40]
    assert_record_pose(records[2], still[0], "the original beside the moved duplicate")

    # --- objects without a baseline (made by hand, or by an older import) hand over Blender's pose --------------------------------
    by = fresh(env, load)
    del by[2]["mj_base"]
    objs = handed_over(env, "b23_nobase.mvar")
    check_close(objs[2].forward, blender_pose(env, by[2])[1], 1e-9, "no baseline: the current pose")
    assert_record_pose(records[3], objs[3], "an object that has its baseline")
    bpy.ops.forge.add_object(objectType="Block, 1x1")
    added = bpy.context.active_object
    check("mj_pose" not in added and "mj_base" not in added, "a hand-made object has no record to hand back")
    added.location = (3.0, 4.0, 5.0)
    new = [o for o in handed_over_list(env, "b23_added.mvar") if o.slot is None][0]
    check_close(new.position, (3.0, 4.0, 5.0), 1e-5)
    check_close(new.forward, (0.0, 1.0, 0.0), 1e-6, "a new object faces local +Y")
    by[2]["mj_base"] = [0.0] * 8                                           # malformed: ignored, not an error
    objs = handed_over(env, "b23_badbase.mvar")
    check_close(objs[2].forward, blender_pose(env, by[2])[1], 1e-9, "a malformed baseline is ignored")

    # --- a change in ``up`` ALONE is a turn (polish item 2 of G6) ---------------------------------------------------------------------
    by = fresh(env, load)
    rec = records[1]
    obj = by[1]
    turn_about_forward(obj, 0.01)                                          # forward stays, up tilts
    pos, fwd, up = blender_pose(env, obj)
    check(Vector(fwd).angle(Vector(obj["mj_base"][3:6])) < 5e-5, "premise: forward did not change (%g rad)" % Vector(fwd).angle(Vector(obj["mj_base"][3:6])))
    check(Vector(up).angle(Vector(obj["mj_base"][6:9])) > 5e-3, "premise: up did change")
    eo = handed_over(env, "b23_up_alone.mvar")[1]
    check_close(eo.up, up, 1e-6, "up alone changed: Blender's up is handed over, not the record's")
    check(Vector(rec.up).angle(Vector(eo.up)) > 5e-3, "...which is 0.01 rad from the record's")
    check_eq(library_sees_change(rec, eo), (False, True), "the library sees the turn")
    exact = by[2]
    check_eq(env.mjolnir.exported_pose(exact, env.mjolnir.pose_from_matrix(exact.matrix_world)),
             (tuple(records[2].position), tuple(records[2].forward), tuple(records[2].up)), "an untouched object still hands the record back")
    base = tuple(by[3]["mj_base"][0:3]), tuple(by[3]["mj_base"][3:6]), tuple(by[3]["mj_base"][6:9])
    tilted_up = tuple(Vector(base[2]).lerp(Vector((0.0, 0.0, 1.0)), 0.02).normalized())
    pose = env.mjolnir.exported_pose(by[3], (base[0], base[1], tilted_up))
    check_eq(pose[2], tilted_up, "exported_pose: up alone differs -> the current up")
    check_eq(pose[1], base[1], "exported_pose: orientation is one quantity, so the current forward is handed over with the current up")

    # --- float32 noise on an axis-aligned rotation (polish: -pi/2 must be the cell that starts at yaw 0) --------------------------------
    mj = env.mjolnir
    check_eq(mj.snap_axis((1.0, -4.371138828673793e-08, 0.0)), (1.0, 0.0, 0.0), "cos of the float32 -pi/2")
    check_eq(mj.snap_axis((0.0, 1.0, 6.0e-8)), (0.0, 1.0, 0.0))
    check_eq(mj.snap_axis((-4.0e-8, -1.0, 4.0e-8)), (0.0, -1.0, 0.0))
    a = mj.snap_axis((0.6, 0.8, 5.0e-7))
    check_close(a, (0.6, 0.8, 0.0), 1e-12, "noise below 1e-6 goes, the rest is renormalised")
    keep = mj.snap_axis((1.0, 1.0e-5, 0.0))                                # 1e-5 rad is an angle, not noise
    check(keep[1] > 9e-6 and abs(sum(c * c for c in keep) - 1.0) < 1e-12, "a real 1e-5 rad stays: %r" % (keep,))
    check_eq(mj.snap_axis((0.0, 0.0, 0.0)), (0.0, 0.0, 0.0), "a zero vector is returned as it is")
    quarter = Matrix.Rotation(-math.pi / 2, 4, 'Z')                        # float32 storage, as an Euler assignment makes it
    holder = bpy.data.objects.new("quarter", None)
    bpy.context.scene.collection.objects.link(holder)
    holder.rotation_euler = (0.0, 0.0, -math.pi / 2)
    bpy.context.view_layer.update()
    check_eq(mj.pose_from_matrix(holder.matrix_world)[1], (1.0, 0.0, 0.0), "rotation_euler.z = -pi/2 gives forward exactly +X")
    holder.rotation_euler = (0.0, 0.0, 0.0)
    bpy.context.view_layer.update()
    check_eq(mj.pose_from_matrix(holder.matrix_world)[1], (0.0, 1.0, 0.0))
    bpy.data.objects.remove(holder, do_unlink=True)

    # --- the numbers survive save and reopen --------------------------------------------------------------------------------------
    by = fresh(env, load)
    blend = os.path.join(env.tmp, "b23.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend, check_existing=False)
    bpy.ops.wm.open_mainfile(filepath=blend)
    objs = handed_over(env, "b23_reopened.mvar")
    for slot, rec in records.items():
        assert_record_pose(rec, objs[slot], "after save and reopen, slot %d" % slot)


def handed_over_list(env, name):
    result, path = env.export_to(name)
    check_eq(result, {'FINISHED'}, "export")
    return list(env.stub.LAST_EXPORT[1])


# =====================================================================================================
# the real-provider variant (G6)
# =====================================================================================================
def run_real(env):
    if not rd.real_available():
        print("NOTICE: the real map variant is absent (%s); the real half of B-23 is SKIPPED." % rd.real_mvar_path())
        raise bl_common.Skip("the real map variant is absent: %s" % rd.real_mvar_path())
    mj = env.mjolnir
    path = rd.real_mvar_path()
    original = rd.real_bytes()
    dec = rd.decode(original)
    fingerprint = rd.file_fingerprint(path)
    env.use_library()

    def fresh_real():
        env.reset()
        env.use_library()
        check_eq(env.import_file(path), {'FINISHED'})
        return dict((o["mj_slot"], o) for o in env.forge_objects())

    def kind(obj):
        return "vertical" if tuple(round(float(c), 6) for c in obj["mj_pose"][6:9]) == (0.0, 0.0, 1.0) else "tilted"

    def pick(by, name, wanted):
        return [o for _s, o in sorted(by.items()) if o.name.split(" - ", 1)[1] == name and kind(o) == wanted][0]

    def export_ok(name, **options):
        result, out = env.export_to(name, **options)
        check_eq(result, {'FINISHED'}, "%s: %r\n%s" % (name, result, env.report_text()[:2000]))
        return rd.read_bytes(out)

    by = fresh_real()
    tilted = [o for o in by.values() if kind(o) == "tilted"]
    check_eq(len(tilted), 207, "207 tilted objects in the real file")
    # every tilted object hands its record back: no-op, byte for byte
    check(export_ok("b23r_noop.mvar") == original, "all 207 tilted objects and 403 vertical ones come back unchanged")

    # moving a tilted object keeps its orientation bits; turning a vertical one changes only its angle -- both at once
    coil = pick(by, "Fusion Coil", "tilted")
    cover = pick(by, "Cover, Large", "vertical")
    coil.location.y += 0.75
    cover.rotation_euler.z += math.radians(30.0)
    bpy.context.scene.forge.allowUnverifiedRotation = True
    out = rd.decode(export_ok("b23r_both.mvar"))
    a, b = coil["mj_slot"], cover["mj_slot"]
    check_eq(rd.fields_differing(dec["slots"][a], out["slots"][a]), ["pos"], "the moved tilted object: position only")
    check_eq(rd.fields_differing(dec["slots"][b], out["slots"][b]), ["angle"], "the turned vertical object: angle only")
    check_eq(rd.slots_equal(dec, out, ignore=(a, b)), [], "all other slots unchanged")
    check(out["slots"][b]["angle"] != dec["slots"][b]["angle"])

    # a tilted object that is turned is refused, not passed as unchanged
    by = fresh_real()
    coil = pick(by, "Fusion Coil", "tilted")
    bpy.context.scene.forge.allowUnverifiedRotation = True
    coil.rotation_euler.z += math.radians(20.0)
    result, out_path = env.export_to("b23r_tilted_turn.mvar")
    check(isinstance(result, RuntimeError) and "ERROR E_TILT_UNSUPPORTED" in env.report_text(), "turning a tilted object: %r" % (result,))
    check(not os.path.exists(out_path), "nothing written")

    # a vertical object whose UP alone changed (a turn about its forward axis) is refused: it is a real edit, not noise
    by = fresh_real()
    cover = pick(by, "Cover, Large", "vertical")
    bpy.context.scene.forge.allowUnverifiedRotation = True
    turn_about_forward(cover, 0.01)
    base = Vector(cover["mj_base"][3:6])
    check(mj.pose_from_matrix(cover.matrix_world)[1] and Vector(mj.pose_from_matrix(cover.matrix_world)[1]).angle(base) < 5e-5, "forward did not change")
    result, out_path = env.export_to("b23r_up_alone.mvar")
    check(isinstance(result, RuntimeError) and "ERROR E_TILT_UNSUPPORTED" in env.report_text(),
          "a change in up alone is seen by the library (not dropped silently): %r" % (result,))
    check(not os.path.exists(out_path))

    # noise below the tolerances is ignored; a move below the quantisation step is not written; a real move is
    by = fresh_real()
    cover = pick(by, "Cover, Large", "vertical")
    coil = pick(by, "Fusion Coil", "tilted")
    cover.location.x += 1e-5
    cover.rotation_euler.z += 1e-5
    coil.location.z += 1e-5
    check(export_ok("b23r_noise.mvar") == original, "1e-5 of move or turn is noise: passthrough")
    cover.location.x += 2e-3
    check(export_ok("b23r_substep.mvar") == original, "a move of 0.002 is below the quantisation step 0.0048: not written")
    cover.location.x += 0.05
    out = rd.decode(export_ok("b23r_step.mvar"))
    check_eq(rd.fields_differing(dec["slots"][cover["mj_slot"]], out["slots"][cover["mj_slot"]]), ["pos"], "0.05 is a move")

    # save and reopen between import and export, with the moved tilted object
    by = fresh_real()
    coil = pick(by, "Fusion Coil", "tilted")
    coil.location.y += 0.75
    here = export_ok("b23r_before_save.mvar")
    blend = os.path.join(env.tmp, "b23r.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend, check_existing=False)
    bpy.ops.wm.open_mainfile(filepath=blend)
    check(export_ok("b23r_after_open.mvar") == here, "after save and reopen the same file")
    check_eq(rd.file_fingerprint(path), fingerprint, "the original is untouched")


if __name__ == "__main__":
    bl_common.main_module(sys.modules[__name__])
