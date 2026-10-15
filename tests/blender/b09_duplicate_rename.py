"""B-09 (SPEC 9.4, 8.7 #9): duplicate, rename, unlink/relink and collection moves.

A duplicate (Shift+D) inherits ``mj_slot``/``mj_raw``; the glue hands both objects to the library with their
names (the library keeps the claimant whose name still matches ``mj_name``). ``forge.object`` is gone: shape
helpers are found through the parent link (``id_data``), so renaming the object or its helper, or duplicating
a shaped object, never confuses them. Unlinking and relinking an object, or moving it to another collection,
leaves the objects handed to the provider unchanged (the order is by slot and name, not by depsgraph order).

Real variant (``run_real``, G6): W1 through the REAL library. A duplicate and a Python copy of ``1 - Block, 1x1`` both claim
slot 1 (``W_DUPLICATE_SLOT``): the original keeps the slot byte for byte and the copies become two new blocks in the lowest free
slots (the rotation gate is needed to add objects); renaming the original changes nothing in the file; unlinking and relinking
an object, or moving it to another collection, gives the same exported bytes; the shape helpers survive rename and duplicate.
"""
import os
import sys

import bpy

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common  # noqa: E402
import real_data as rd  # noqa: E402
from bl_common import check, check_eq  # noqa: E402

ID = "b09"
TITLE = "duplicate / rename / relink / collection move"
NEEDS_STUB = True


def handed_over(env, name="b09.mvar"):
    result, path = env.export_to(name)
    check_eq(result, {'FINISHED'}, "export")
    return list(env.stub.LAST_EXPORT[1])


def check_shape_helpers(env, kill):
    """Shape helpers are found through the parent link: rename and duplicate never confuse them (8.7 #9)."""
    # --- shape helpers survive rename and duplicate (forge.object is gone) -------------------------------------------
    scene = bpy.context.scene
    helpers = [c for c in kill.children if c.get("mj_helper") == "shape"]
    check_eq(len(helpers), 1)

    # a copy made while the name hint is still valid: ``forge.shapeObject`` is copied with the object and names the
    # ORIGINAL's helper, an object that exists but is not a child of the copy. Only the parent check of
    # find_shape_helper keeps the copy from adopting (and then rescaling or deleting) someone else's helper.
    hint_copy = kill.copy()
    scene.collection.objects.link(hint_copy)
    check_eq(hint_copy.forge.shapeObject, helpers[0].name, "the copy carries the original's helper name as its hint")
    check(bpy.data.objects.get(hint_copy.forge.shapeObject) is helpers[0], "the hint resolves to the original's helper")
    check(helpers[0].parent == kill and helpers[0].parent != hint_copy)
    check(env.mjolnir.find_shape_helper(hint_copy) is None, "the hint names a helper of another object: rejected")
    check(env.mjolnir.find_shape_helper(kill) == helpers[0])
    scale_before = tuple(round(v, 6) for v in helpers[0].scale)
    hint_copy.forge.width = 33.0                          # rebuilds the shape of the copy only
    own_hint = [c for c in hint_copy.children if c.get("mj_helper") == "shape"]
    check_eq(len(own_hint), 1, "the copy built its own helper")
    check(own_hint[0] != helpers[0], "...not the original's")
    check_eq(tuple(round(v, 6) for v in helpers[0].scale), scale_before, "the original's helper was not touched")
    check(helpers[0].parent == kill, "the original's helper still belongs to the original")
    hint_copy.forge.shape = "NONE"                        # removes the copy's helper, never the original's
    check(helpers[0].name in bpy.data.objects and helpers[0].parent == kill, "the original's helper survives")
    env.mjolnir.remove_with_helpers(hint_copy)
    check(helpers[0].name in bpy.data.objects and helpers[0].parent == kill, "...also after the copy is deleted")

    kill.name = "kill zone"
    helpers[0].name = "something else entirely"
    kill.forge.width = 30.0
    helpers = [c for c in kill.children if c.get("mj_helper") == "shape"]
    check_eq(len(helpers), 1, "still exactly one helper after renaming both")
    check_eq(helpers[0].name, "something else entirely")
    depth = round(kill.forge.top + kill.forge.bottom, 4)
    length = round(kill.forge.length, 4)
    check_eq(tuple(round(v, 4) for v in helpers[0].scale), (30.0, length, depth), "the renamed helper was updated")
    dup_kill = kill.copy()
    scene.collection.objects.link(dup_kill)
    dup_kill.forge.width = 40.0
    own = [c for c in dup_kill.children if c.get("mj_helper") == "shape"]
    check_eq(len(own), 1, "the duplicate builds its own helper")
    check(own[0] != helpers[0], "not the original's helper")
    check_eq(tuple(round(v, 4) for v in helpers[0].scale), (30.0, length, depth), "the original's helper is untouched")
    check_eq(tuple(round(v, 4) for v in own[0].scale), (40.0, length, depth))
    dup_kill.forge.shape = "NONE"
    check_eq([c for c in dup_kill.children if c.get("mj_helper") == "shape"], [], "NONE removes the duplicate's own helper")
    check_eq(len([c for c in kill.children if c.get("mj_helper") == "shape"]), 1, "...and not the original's")
    bpy.data.objects.remove(dup_kill, do_unlink=True)
    kill.name = kill["mj_name"]


def run(env):
    scene = bpy.context.scene
    env.import_stub()
    by = dict((o["mj_slot"], o) for o in env.forge_objects())
    original = by[1]
    baseline = handed_over(env)
    check_eq(sorted(o.slot for o in baseline), [1, 2, 5, 9, 11])
    check(all(o.name_matches_import for o in baseline), "nothing was renamed yet")

    # --- duplicate through the operator (Shift+D) and by copy ---------------------------------------------------
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    original.select_set(True)
    bpy.context.view_layer.objects.active = original
    result = bpy.ops.object.duplicate()
    check_eq(result, {'FINISHED'})
    dups = [o for o in env.forge_objects() if o is not original and o.get("mj_slot") == 1]
    check_eq(len(dups), 1, "operator duplicate")
    dup = dups[0]
    check(dup.name.startswith("1 - Block, 1x1.0"), "duplicate name %s" % dup.name)
    check_eq(dup["mj_slot"], 1)
    check_eq(bytes(dup["mj_raw"]), bytes(original["mj_raw"]))
    check_eq(dup["mj_name"], original.name, "mj_name still names the imported object")
    dup.location = (50, 60, 70)
    copy = original.copy()                               # a Python-side copy behaves the same
    scene.collection.objects.link(copy)
    objs = handed_over(env)
    claimants = [o for o in objs if o.slot == 1]
    check_eq(len(claimants), 3, "original, duplicate and copy all claim slot 1")
    check_eq(sorted(o.name_matches_import for o in claimants), [False, False, True], "only the original keeps its name")
    check_eq([o.name for o in claimants if o.name_matches_import], [original.name])
    check_eq(len(objs), 7)
    bpy.data.objects.remove(copy, do_unlink=True)
    bpy.data.objects.remove(dup, do_unlink=True)

    # --- rename -----------------------------------------------------------------------------------------------
    original.name = "my renamed block"
    objs = handed_over(env)
    eo = [o for o in objs if o.slot == 1][0]
    check_eq((eo.name, eo.name_matches_import), ("my renamed block", False))
    check_eq(original["mj_name"], "1 - Block, 1x1", "mj_name keeps the name at import")
    original.name = "1 - Block, 1x1"
    check([o for o in handed_over(env) if o.slot == 1][0].name_matches_import)

    check_shape_helpers(env, by[5])

    # --- unlink / relink / move to another collection leave the handed-over objects unchanged ----------------------------
    before = handed_over(env, "b09_before.mvar")
    other = bpy.data.collections.new("Elsewhere")
    scene.collection.children.link(other)
    obj = by[9]
    for coll in list(obj.users_collection):
        coll.objects.unlink(obj)
    scene.collection.objects.link(obj)                    # unlink and relink: moves to the end of the depsgraph order
    after_relink = handed_over(env, "b09_relink.mvar")
    check_eq(after_relink, before, "unlink + relink")
    scene.collection.objects.unlink(obj)
    other.objects.link(obj)
    after_move = handed_over(env, "b09_move.mvar")
    check_eq(after_move, before, "moved to another collection")
    check_eq([o.slot for o in after_move], [1, 2, 5, 9, 11], "the order is by slot")


# =====================================================================================================
# the real-provider variant (G6)
# =====================================================================================================
def real_bytes(env, name, **options):
    result, path = env.export_to(name, **options)
    check_eq(result, {'FINISHED'}, "%s: %r\n%s" % (name, result, env.report_text()[:2500]))
    return rd.read_bytes(path)


def run_real(env):
    w1 = rd.fixture("w1_minimal")
    dec = rd.decode(w1)
    scene = bpy.context.scene
    result, _ = env.import_bytes(w1, "b09_w1.mvar")
    check_eq(result, {'FINISHED'})
    by = dict((o["mj_slot"], o) for o in env.forge_objects())
    original = by[1]
    check(real_bytes(env, "b09_base.mvar") == w1, "baseline: passthrough")

    # --- duplicate through the operator (Shift+D) and by Python copy: two more claimants of slot 1 -------------------------------
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    original.select_set(True)
    bpy.context.view_layer.objects.active = original
    check_eq(bpy.ops.object.duplicate(), {'FINISHED'})
    dups = [o for o in env.forge_objects() if o is not original and o.get("mj_slot") == 1]
    check_eq(len(dups), 1, "operator duplicate")
    dup = dups[0]
    check(dup.name.startswith("1 - Block, 1x1.0"), "duplicate name %s" % dup.name)
    check_eq((dup["mj_slot"], bytes(dup["mj_raw"])), (1, bytes(original["mj_raw"])), "the duplicate inherits the slot and the token")
    check_eq(dup["mj_name"], original.name, "mj_name still names the imported object")
    dup.location = (50, 60, 40)
    copy = original.copy()                               # a Python-side copy behaves the same
    scene.collection.objects.link(copy)
    copy.location = (-50, -60, -40)
    bpy.context.view_layer.update()
    # adding objects needs the gate
    result, path = env.export_to("b09_dup_nogate.mvar")
    check(isinstance(result, RuntimeError) and "E_ROTATION_GATED" in env.report_text(), "copies are new objects: the gate is needed: %r" % (result,))
    check(not os.path.exists(path))
    scene.forge.allowUnverifiedRotation = True
    out = real_bytes(env, "b09_dup.mvar")
    report = env.report_text()
    check(report.count("W_DUPLICATE_SLOT") == 2 and "kept '1 - Block, 1x1'" in report, report[:2500])
    after = rd.decode(out)
    check_eq(sorted(after["slots"]), [0, 1, 2, 5, 650], "the copies became new blocks in the lowest free slots 0 and 2")
    check_eq(after["slots"][1], dec["slots"][1], "the original keeps slot 1 exactly")
    check_eq(rd.slots_equal(dec, after, ignore=(0, 2)), [], "the other slots are unchanged")
    cells = lambda p: [rd.cell_for(c, (20, 21, 19)[k], (-240.0, -345.0, -70.0)[k], (240.0, 345.0, 70.0)[k]) for k, c in enumerate(p)]
    names = sorted([dup, copy], key=lambda o: o.name)                    # new objects get the lowest free slots in name order
    check_eq(list(after["slots"][0]["pos"]), cells(tuple(names[0].matrix_world.translation)), "slot 0 is " + names[0].name)
    check_eq(list(after["slots"][2]["pos"]), cells(tuple(names[1].matrix_world.translation)), "slot 2 is " + names[1].name)
    check_eq(after["quotas"][70], [0, 16, 4])
    bpy.data.objects.remove(copy, do_unlink=True)
    bpy.data.objects.remove(dup, do_unlink=True)
    check(real_bytes(env, "b09_dup_gone.mvar") == w1, "the copies are gone: passthrough again")

    # --- rename: the file does not care ---------------------------------------------------------------------------------------------
    original.name = "my renamed block"
    check(real_bytes(env, "b09_renamed.mvar") == w1, "a renamed object is still the claimant of its slot: passthrough")
    original.name = "1 - Block, 1x1"
    # a renamed original and a moved duplicate: the original, which is where the file put it, keeps the slot
    original.name = "my renamed block"
    twin = original.copy()
    scene.collection.objects.link(twin)
    twin.location = (70.0, 80.0, 50.0)
    bpy.context.view_layer.update()
    after = rd.decode(real_bytes(env, "b09_renamed_twin.mvar"))
    check_eq(after["slots"][1], dec["slots"][1], "the unmoved object keeps the slot although it was renamed")
    check_eq(sorted(after["slots"]), [0, 1, 5, 650], "the twin is new")
    bpy.data.objects.remove(twin, do_unlink=True)
    original.name = "1 - Block, 1x1"
    scene.forge.allowUnverifiedRotation = False

    # --- shape helpers survive rename and duplicate (forge.object is gone) -------------------------------------------------------------
    check_shape_helpers(env, by[5])

    # --- unlink / relink / move to another collection give the same file ----------------------------------------------------------------
    before = real_bytes(env, "b09_before.mvar")
    before_dec = rd.decode(before)
    other = bpy.data.collections.new("Elsewhere")
    scene.collection.children.link(other)
    obj = by[650]
    for coll in list(obj.users_collection):
        coll.objects.unlink(obj)
    scene.collection.objects.link(obj)
    check(real_bytes(env, "b09_relink.mvar") == before, "unlink + relink: the same bytes")
    scene.collection.objects.unlink(obj)
    other.objects.link(obj)
    check(real_bytes(env, "b09_move.mvar") == before, "moved to another collection: the same bytes")
    # a moved object in another collection is still found and moved
    obj.location.x += 1.0
    moved = rd.decode(real_bytes(env, "b09_move2.mvar"))
    check_eq(rd.fields_differing(before_dec["slots"][650], moved["slots"][650]), ["pos"])
    check_eq(rd.slots_equal(before_dec, moved, ignore=(650,)), [], "nothing else moved")


if __name__ == "__main__":
    bl_common.main_module(sys.modules[__name__])
