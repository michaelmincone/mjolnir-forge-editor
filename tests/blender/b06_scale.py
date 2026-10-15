"""B-06 (SPEC 9.4, 8.7 #2 #3): the SCALE label scales the imported object even with a selection present.

The old ``UpdateSpawnSeq`` rescaled ``context.selected_objects`` instead of the object being set, so an import
with anything selected ignored the scale (and reset the scale of unrelated selected objects). Now every
update acts on ``self.id_data`` and import sets ``obj.scale`` directly. The default convention is 47X.

Both variants: the conversion table, the default, the scale of a SCALE-labelled object with a selection present, the
convention change, Scale Forge Objects. The real variant (``run_real``, G6) imports fixtures of the independent builder with
the real library: a SCALE object that is not touched exports as a byte-level zero diff, and Scale Forge Objects lands in
exactly the label and spawn sequence fields of the independent decode. The enum numbers a .blend stores for
``scaleConvention`` are pinned (1X 0, 33X 1, 71X 2, 47X 3, 330X 4: forge.py v0.9.9.2, the shipped add-on).
"""
import dataclasses
import os
import sys

import bpy

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common  # noqa: E402
import real_data as rd  # noqa: E402
from bl_common import check, check_close, check_eq  # noqa: E402

ID = "b06"
TITLE = "SCALE label scales the object with a selection present; default convention 47X"
NEEDS_STUB = True

# values computed by forge.py's own spawnSeqToScale on Blender 5.2.1 (addon-architecture.md section 3.6)
TABLE = {
    "33X": {-30: 15.0, 0: 1.0, 50: 6.0, 100: 11.0, -100: 33.0},
    "71X": {-30: 19.0, -100: 71.0},
    "47X": {-30: 35.6, 50: 6.0, 100: 11.0, -100: 11.2},
    "330X": {-30: 240.88, -10: 0.5, 50: 4.17, 100: 21.65},
}


def check_table_and_default(env):
    mj = env.mjolnir
    scene = bpy.context.scene
    # the conversion table
    for convention, values in TABLE.items():
        for seq, expected in values.items():
            check_close([mj.spawnSeqToScale(seq, convention)], [expected], 0.006, "%s %d" % (convention, seq))
    check_eq(mj.spawnSeqToScale(-10, "47X"), 0.01)
    check_eq(mj.spawnSeqToScale(-20, "330X"), 0.01)
    check_eq(mj.spawnSeqToScale(77, "1X"), 1)

    # 8.7 #3: the documented default is 47X (the old script defaulted to index 2 = 71X)
    check_eq(scene.forge.scaleConvention, "47X")
    check_eq(scene.forge.bl_rna.properties["scaleConvention"].default, "47X")
    # the numbers a .blend stores (forge.py v0.9.9.2 numbered the items by position; 1X is the first)
    items = dict((i.identifier, i.value) for i in scene.forge.bl_rna.properties["scaleConvention"].enum_items)
    check_eq(items, {"1X": 0, "33X": 1, "71X": 2, "47X": 3, "330X": 4}, "stored numbers of the scale conventions")
    legacy = bpy.data.scenes.new("legacy")                 # raw values as a .blend saved by the shipped add-on holds them
    try:
        for ident, number in items.items():
            legacy.forge["scaleConvention"] = number
            check_eq(legacy.forge.scaleConvention, ident, "stored %d reads as %s" % (number, ident))
        legacy.forge.property_unset("scaleConvention")
        check_eq(legacy.forge.scaleConvention, "47X", "an untouched scene reads the documented default")
    finally:
        bpy.data.scenes.remove(legacy)


def run(env):
    mj = env.mjolnir
    stub = env.stub
    scene = bpy.context.scene

    check_table_and_default(env)

    # an object selected before the import keeps its scale; the SCALE object gets its scale
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.active_object
    cube.select_set(True)
    check(len(bpy.context.selected_objects) == 1)
    scaled = dataclasses.replace(stub.CANNED.objects[0], label_index=0, spawn_sequence=-30)
    plain = stub.CANNED.objects[3]
    load = dataclasses.replace(stub.CANNED, objects=[scaled, plain])
    result, _ = env.import_stub(load=load)
    check_eq(result, {'FINISHED'})
    by_slot = dict((o["mj_slot"], o) for o in env.forge_objects())
    check_close(tuple(by_slot[1].scale), (35.6,) * 3, 1e-4, "SCALE object scale (47X, seq -30)")
    check_close(tuple(by_slot[9].scale), (1, 1, 1), 1e-6, "no label: scale 1")
    check_close(tuple(cube.scale), (1, 1, 1), 1e-6, "the selected cube is untouched")
    check_eq(by_slot[1].forge.gtLabel, "L0")
    check(env.state.label_text(scene, "L0") == "SCALE")

    # exports ignore scale: forward/up are normalised, position is the translation
    collected = env.io_ops.collect_export_objects(scene)
    eo = [e for e in collected.objects if e.slot == 1][0]
    check_close(eo.forward, scaled.forward, 1e-5)
    check_close(eo.up, scaled.up, 1e-5)
    check_close(eo.position, scaled.position, 1e-4)

    # changing the sequence of one object while others are selected affects only that object
    cube.scale = (2, 2, 2)
    cube.select_set(True)
    by_slot[9].select_set(True)
    by_slot[1].forge.spawnSequence = 50
    check_close(tuple(by_slot[1].scale), (6.0,) * 3, 1e-4, "50 -> 6 on the object itself")
    check_close(tuple(cube.scale), (2, 2, 2), 1e-6, "selected unrelated object keeps its scale")
    check_close(tuple(by_slot[9].scale), (1, 1, 1), 1e-6)

    # changing the convention rescales Forge objects only. Sequence 50 gives 6.0 under 33X, 47X and 71X alike (so it
    # cannot tell a rescale from no rescale); at -30 the conventions differ: 47X 35.6, 71X 19, 33X 15, 330X 240.88
    by_slot[1].forge.spawnSequence = -30
    check_close(tuple(by_slot[1].scale), (35.6,) * 3, 1e-4, "47X at -30")
    previous = 35.6
    for convention, expected in (("71X", 19.0), ("33X", 15.0), ("330X", 240.88), ("47X", 35.6)):
        scene.forge.scaleConvention = convention
        check_close(tuple(by_slot[1].scale), (expected,) * 3, 0.006, "%s at -30 after the change" % convention)
        check_close(tuple(by_slot[1].scale), (mj.spawnSeqToScale(-30, convention),) * 3, 1e-4,
                    "%s: the object follows spawnSeqToScale" % convention)
        check(abs(by_slot[1].scale[0] - previous) > 1.0, "%s: the scale really changed (was %g)" % (convention, previous))
        previous = by_slot[1].scale[0]
        check_close(tuple(cube.scale), (2, 2, 2), 1e-6, "the convention change leaves other objects alone")
        check_close(tuple(by_slot[9].scale), (1, 1, 1), 1e-6, "an object without the SCALE label stays at 1")

    # Scale Forge Objects: label + sequence + scale on the selected Forge objects
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    by_slot[9].select_set(True)
    bpy.context.view_layer.objects.active = by_slot[9]
    check(bpy.ops.forge.scale_objects.poll(), "poll: selection and a SCALE label")
    result = bpy.ops.forge.scale_objects(seq=-30)
    check_eq(result, {'FINISHED'})
    check_eq(by_slot[9].forge.gtLabel, "L0")
    check_eq(by_slot[9].forge.spawnSequence, -30)
    check_close(tuple(by_slot[9].scale), (35.6,) * 3, 1e-4)

    # no SCALE label in the map: the operator is not available
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    env.reset()
    info = dataclasses.replace(stub.CANNED.info, labels=["Kill Boundary", "Spawn"], label_present=[True, True])
    env.import_stub(load=dataclasses.replace(stub.CANNED, info=info))
    obj = env.forge_objects()[0]
    obj.select_set(True)
    check(not bpy.ops.forge.scale_objects.poll(), "no SCALE label, no operator")


# =====================================================================================================
# the real-provider variant (G6)
# =====================================================================================================
def scale_fixture(scale_label=True):
    """W1 with the SCALE label (index 0) and spawn sequence -30 on slot 1; slot 650 has no label."""
    spec = rd.w1_spec("b06_scale", "W1 with a SCALE object")
    if scale_label:
        spec["slots"][0]["label"] = 0
        spec["slots"][0]["spawn_seq"] = -30
        spec["slots"][2]["label"] = None
    else:
        spec["labels"] = {"strings": ["Kill Boundary", "Spawn"], "compressed": False}
        spec["slots"][1]["label"] = 0
        spec["slots"][2]["label"] = 1
    return rd.build_spec(spec)


def run_real(env):
    mj = env.mjolnir
    scene = bpy.context.scene
    check_table_and_default(env)

    # an object selected before the import keeps its scale; the SCALE object gets its scale
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.active_object
    cube.select_set(True)
    check(len(bpy.context.selected_objects) == 1)
    data = scale_fixture()
    dec = rd.decode(data)
    result, _ = env.import_bytes(data, "b06_scale.mvar")
    check_eq(result, {'FINISHED'})
    by_slot = dict((o["mj_slot"], o) for o in env.forge_objects())
    check_close(tuple(by_slot[1].scale), (35.6,) * 3, 1e-4, "SCALE object scale (47X, seq -30)")
    check_close(tuple(by_slot[650].scale), (1, 1, 1), 1e-6, "no label: scale 1")
    check_close(tuple(by_slot[5].scale), (1, 1, 1), 1e-6, "another label: scale 1")
    check_close(tuple(cube.scale), (1, 1, 1), 1e-6, "the selected cube is untouched")
    check_eq(by_slot[1].forge.gtLabel, "L0")
    check_eq(env.state.label_text(scene, "L0"), "SCALE")
    # scale is not exported: an untouched SCALE object is a byte-level zero diff
    result, path = env.export_to("b06_noop.mvar")
    check_eq(result, {'FINISHED'}, "%r\n%s" % (result, env.report_text()[:1500]))
    check(rd.read_bytes(path) == data, "scaled objects export their position and orientation only: passthrough, byte for byte")

    # changing the sequence of one object while others are selected affects only that object
    cube.scale = (2, 2, 2)
    cube.select_set(True)
    by_slot[650].select_set(True)
    by_slot[1].forge.spawnSequence = 50
    check_close(tuple(by_slot[1].scale), (6.0,) * 3, 1e-4, "50 -> 6 on the object itself")
    check_close(tuple(cube.scale), (2, 2, 2), 1e-6, "selected unrelated object keeps its scale")
    check_close(tuple(by_slot[650].scale), (1, 1, 1), 1e-6)
    result, path = env.export_to("b06_seq.mvar")
    check_eq(result, {'FINISHED'})
    after = rd.decode(rd.read_bytes(path))
    check_eq(rd.fields_differing(dec["slots"][1], after["slots"][1]), ["spawn_seq"], "the new sequence is the only change")
    check_eq(after["slots"][1]["spawn_seq"], 50)
    check_eq(rd.slots_equal(dec, after, ignore=(1,)), [])
    by_slot[1].forge.spawnSequence = -30

    # the convention change rescales Forge objects only; at -30 the conventions differ
    previous = 35.6
    for convention, expected in (("71X", 19.0), ("33X", 15.0), ("330X", 240.88), ("47X", 35.6), ("1X", 1.0)):
        scene.forge.scaleConvention = convention
        check_close(tuple(by_slot[1].scale), (expected,) * 3, 0.006, "%s at -30" % convention)
        check_close(tuple(by_slot[1].scale), (mj.spawnSeqToScale(-30, convention),) * 3, 1e-4)
        check_close(tuple(cube.scale), (2, 2, 2), 1e-6, "the convention change leaves other objects alone")
        check_close(tuple(by_slot[650].scale), (1, 1, 1), 1e-6)
    scene.forge.scaleConvention = "47X"

    # Scale Forge Objects: label + sequence + scale on the selected Forge objects, landing in the file
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    by_slot[650].select_set(True)
    bpy.context.view_layer.objects.active = by_slot[650]
    check(bpy.ops.forge.scale_objects.poll(), "poll: selection and a SCALE label")
    check_eq(bpy.ops.forge.scale_objects(seq=-30), {'FINISHED'})
    check_eq((by_slot[650].forge.gtLabel, by_slot[650].forge.spawnSequence), ("L0", -30))
    check_close(tuple(by_slot[650].scale), (35.6,) * 3, 1e-4)
    result, path = env.export_to("b06_scaleops.mvar")
    check_eq(result, {'FINISHED'}, "%r\n%s" % (result, env.report_text()[:1500]))
    after = rd.decode(rd.read_bytes(path))
    check_eq(rd.fields_differing(dec["slots"][650], after["slots"][650]), ["label", "spawn_seq"], "label and spawn sequence only")
    check_eq((after["slots"][650]["label"], after["slots"][650]["spawn_seq"]), (0, -30))

    # no SCALE label in the map: the operator is not available
    env.reset()
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    result, _ = env.import_bytes(scale_fixture(scale_label=False), "b06_noscale.mvar")
    check_eq(result, {'FINISHED'})
    check_eq(env.state.get(bpy.context.scene)["labels"], ["Kill Boundary", "Spawn"])
    env.forge_objects()[0].select_set(True)
    check(not bpy.ops.forge.scale_objects.poll(), "no SCALE label, no operator")


if __name__ == "__main__":
    bl_common.main_module(sys.modules[__name__])
