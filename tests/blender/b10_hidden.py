"""B-10 (SPEC 9.4, 8.5, 8.7 #10): hidden objects are exported, unevaluated arrays are refused.

Eye-hidden (``hide_set``), ``hide_viewport`` and excluded-collection plain objects are NOT skipped: they reach
the provider with ``hidden=True`` and their real transform (rebuilt from the local transforms where the
depsgraph does not evaluate them), and ``W_HIDDEN_EXPORTED`` appears. An array source whose parent is
eye-hidden, ``hide_viewport`` or in an excluded collection yields no evaluated instance: the export is
refused with ``E_ARRAY_NOT_EVALUATED`` and writes no file (its slot would otherwise look deleted).

Real variant (``run_real``, G6): W1 through the REAL library. The hidden objects' positions land in the file (checked against the
independent decode, cell by cell), ``W_HIDDEN_EXPORTED`` is in the report; a visible array exports its instances as new blocks
(the first instance keeps the slot byte for byte); the three unevaluated-array cases are refused and write nothing.
"""
import os
import sys

import bpy

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common  # noqa: E402
import real_data as rd  # noqa: E402
from bl_common import check, check_close, check_eq  # noqa: E402

ID = "b10"
TITLE = "hidden objects exported (W_HIDDEN_EXPORTED); unevaluated arrays refused (E_ARRAY_NOT_EVALUATED)"
NEEDS_STUB = True


def make_array(env, source, count=3):
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    source.select_set(True)
    bpy.context.view_layer.objects.active = source
    check_eq(bpy.ops.object.setup_array(type='CONST', count=count), {'FINISHED'})
    return source.parent


def run(env):
    stub = env.stub
    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    env.import_stub()
    by = dict((o["mj_slot"], o) for o in env.forge_objects())

    # --- hidden plain objects are exported -----------------------------------------------------------------------
    by[1].hide_set(True)
    by[2].hide_viewport = True
    by[2].location = (-1.5, 2.5, 3.5)                    # changed while not evaluated: matrix_world is stale
    excluded = bpy.data.collections.new("Excluded")
    scene.collection.children.link(excluded)
    scene.collection.objects.unlink(by[9])
    excluded.objects.link(by[9])
    view_layer.layer_collection.children["Excluded"].exclude = True
    by[9].location = (7.0, 8.0, 9.0)
    with bl_common.capture_output() as out:
        result, path = env.export_to("b10_hidden.mvar")
    check_eq(result, {'FINISHED'}, "export with hidden objects")
    check(os.path.exists(path), "file written")
    check("3 hidden object(s) were exported" in out[0], "W_HIDDEN_EXPORTED on the console: " + out[0])
    check("WARNING W_HIDDEN_EXPORTED: 3 hidden object(s) were exported." in env.report_text(), env.report_text())
    objs = dict((o.slot, o) for o in stub.LAST_EXPORT[1])
    check_eq(sorted(objs), [1, 2, 5, 9, 11], "all five objects reached the provider")
    check_eq(sorted(s for s, o in objs.items() if o.hidden), [1, 2, 9], "hidden flags")
    check_close(objs[2].position, (-1.5, 2.5, 3.5), 1e-4, "hide_viewport object: real position, not the stale matrix")
    check_close(objs[9].position, (7.0, 8.0, 9.0), 1e-4, "excluded-collection object: real position")
    check_close(objs[1].position, stub.CANNED.objects[0].position, 1e-4, "eye-hidden object")

    # --- unevaluated array sources are refused -----------------------------------------------------------------------
    env.reset()
    env.import_stub()
    by = dict((o["mj_slot"], o) for o in env.forge_objects())
    plane = make_array(env, by[2])                       # a model-less object (the old export lost it and all copies)
    check_eq(plane.instance_type, "FACES")
    result, path = env.export_to("b10_array_ok.mvar")
    check_eq(result, {'FINISHED'}, "a visible array exports")
    check_eq(len([o for o in stub.LAST_EXPORT[1] if o.name.startswith("2 - ")]), 3, "3 instances of the model-less source")

    def refused(label):
        result, path = env.export_to("b10_array_%s.mvar" % label)
        check(isinstance(result, RuntimeError), "%s: refused: %r" % (label, result))
        check("Array '2 - Assault Rifle' is hidden, excluded or empty, so its instances cannot be read." in str(result)
              or "E_ARRAY_NOT_EVALUATED" in env.report_text(), "%s: message" % label)
        check("ERROR E_ARRAY_NOT_EVALUATED '2 - Assault Rifle': Array '2 - Assault Rifle' is hidden, excluded or empty"
              in env.report_text(), env.report_text())
        check(not os.path.exists(path), "%s: no file written" % label)

    plane.hide_set(True)
    refused("eye_hidden")
    plane.hide_set(False)
    plane.hide_viewport = True
    refused("hide_viewport")
    plane.hide_viewport = False
    parking = bpy.data.collections.new("Parking")
    scene.collection.children.link(parking)
    for coll in list(plane.users_collection):
        coll.objects.unlink(plane)
    parking.objects.link(plane)
    view_layer.layer_collection.children["Parking"].exclude = True
    refused("excluded_collection")
    view_layer.layer_collection.children["Parking"].exclude = False
    result, path = env.export_to("b10_array_back.mvar")
    check_eq(result, {'FINISHED'}, "visible again: exported again")


# =====================================================================================================
# the real-provider variant (G6)
# =====================================================================================================
W1_BITS = (20, 21, 19)
W1_LO = (-240.0, -345.0, -70.0)
W1_HI = (240.0, 345.0, 70.0)


def w1_cells(position):
    return [rd.cell_for(position[k], W1_BITS[k], W1_LO[k], W1_HI[k]) for k in range(3)]


def run_real(env):
    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    w1 = rd.fixture("w1_minimal")
    dec = rd.decode(w1)
    result, _ = env.import_bytes(w1, "b10_w1.mvar")
    check_eq(result, {'FINISHED'})
    by = dict((o["mj_slot"], o) for o in env.forge_objects())

    # --- hidden plain objects are exported, at their real position ------------------------------------------------------------------
    by[1].hide_set(True)
    by[5].hide_viewport = True
    by[5].location = (-1.5, 2.5, 3.5)                    # changed while not evaluated: matrix_world is stale
    excluded = bpy.data.collections.new("Excluded")
    scene.collection.children.link(excluded)
    scene.collection.objects.unlink(by[650])
    excluded.objects.link(by[650])
    view_layer.layer_collection.children["Excluded"].exclude = True
    by[650].location = (7.0, 8.0, 9.0)
    by[1].location.x += 2.0                              # eye-hidden and moved
    with bl_common.capture_output() as out:
        result, path = env.export_to("b10_hidden.mvar")
    check_eq(result, {'FINISHED'}, "export with hidden objects: %r\n%s" % (result, env.report_text()[:1500]))
    check("3 hidden object(s) were exported" in out[0], "W_HIDDEN_EXPORTED on the console: " + out[0])
    check("WARNING W_HIDDEN_EXPORTED: 3 hidden object(s) were exported." in env.report_text(), env.report_text())
    after = rd.decode(rd.read_bytes(path))
    check_eq(sorted(after["slots"]), [1, 5, 650], "all three objects are in the file")
    check_eq(list(after["slots"][5]["pos"]), w1_cells((-1.5, 2.5, 3.5)), "hide_viewport object: the real position, not the stale matrix")
    check_eq(list(after["slots"][650]["pos"]), w1_cells((7.0, 8.0, 9.0)), "excluded-collection object: the real position")
    expected_x = rd.cell_for(rd.cell_centre(dec["slots"][1]["pos"][0], 20, -240.0, 240.0) + 2.0, 20, -240.0, 240.0)
    check_eq(after["slots"][1]["pos"][0], expected_x, "eye-hidden object: moved by +2.0 in x")
    for slot in (1, 5, 650):
        check_eq(rd.fields_differing(dec["slots"][slot], after["slots"][slot]), ["pos"], "slot %d: only the position changed" % slot)

    # --- a visible array exports its instances ------------------------------------------------------------------------------------------
    env.reset()
    env.import_bytes(w1, "b10_array.mvar")
    scene.forge.allowUnverifiedRotation = True
    by = dict((o["mj_slot"], o) for o in env.forge_objects())
    plane = make_array(env, by[1])
    check_eq(plane.instance_type, "FACES")
    result, path = env.export_to("b10_array_ok.mvar")
    check_eq(result, {'FINISHED'}, "a visible array exports: %r\n%s" % (result, env.report_text()[:2000]))
    after = rd.decode(rd.read_bytes(path))
    blocks = [i for i, s in after["slots"].items() if (s["folder"], s["item"]) == (70, 0)]
    check_eq(len(blocks), 1 + 3 + 0, "slot 650 is a block too: 3 instances of slot 1 plus slot 650")
    check_eq(after["slots"][1], dec["slots"][1], "the first instance keeps slot 1 byte for byte")
    new = sorted(i for i in blocks if i not in (1, 650))
    check_eq(new, [0, 2], "the other two instances are new blocks in the lowest free slots")
    pts = [tuple(rd.cell_centre(after["slots"][i]["pos"][k], W1_BITS[k], W1_LO[k], W1_HI[k]) for k in range(3)) for i in blocks if i != 650]
    dist = lambda a, b: ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5
    check_close(sorted([dist(pts[0], pts[1]), dist(pts[0], pts[2]), dist(pts[1], pts[2])]), [1.0, 1.0, 2.0], 2e-3,
                "the three instances stand on a line, one unit apart")

    def refused(label):
        result, path = env.export_to("b10_array_%s.mvar" % label)
        check(isinstance(result, RuntimeError), "%s: refused: %r" % (label, result))
        check("ERROR E_ARRAY_NOT_EVALUATED '1 - Block, 1x1': Array '1 - Block, 1x1' is hidden, excluded or empty" in env.report_text(), env.report_text())
        check("Result: REFUSED, nothing was written" in env.report_text())
        check(not os.path.exists(path), "%s: no file written" % label)

    plane.hide_set(True)
    refused("eye_hidden")
    plane.hide_set(False)
    plane.hide_viewport = True
    refused("hide_viewport")
    plane.hide_viewport = False
    parking = bpy.data.collections.new("Parking")
    scene.collection.children.link(parking)
    for coll in list(plane.users_collection):
        coll.objects.unlink(plane)
    parking.objects.link(plane)
    view_layer.layer_collection.children["Parking"].exclude = True
    refused("excluded_collection")
    view_layer.layer_collection.children["Parking"].exclude = False
    result, path = env.export_to("b10_array_back.mvar")
    check_eq(result, {'FINISHED'}, "visible again: exported again")


if __name__ == "__main__":
    bl_common.main_module(sys.modules[__name__])
