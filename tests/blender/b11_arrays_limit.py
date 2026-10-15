"""B-11 (SPEC 9.4, 8.5, 8.7 #10): arrays of model-backed and model-less objects, 650 objects, refusals shown.

Array copies are read from the evaluated depsgraph (also for arrow empties without a model, which used to
vanish): N instances give N objects, the first carries the source's slot and token, the others are new
(``slot is None``, ``from_array``). 650 imported objects round-trip through the glue in reasonable time. The
count limit itself is the library's (``E_TOO_MANY``, G5/G6 with fixtures ``full650`` and ``over650``); here
the stub is told to refuse and the glue must show the code and write nothing.

Real variant (``run_real``, G6): the REAL library and fixtures of the independent builder. Arrays of a model-backed object (a
Block with the stand-in library) and of a model-less one (an Assault Rifle) turn N instances into N objects: the first keeps the
slot byte for byte, the others become new objects with the right class and extras (checked in the independent decode, positions
one array step apart); the object-offset, curve and vertex arrays export; ``full650`` (650 occupied slots, roomy quotas)
imports, exports unchanged byte for byte and is refused with ``E_TOO_MANY`` as soon as one object is added; ``over650`` (651) is
refused even unchanged; a hidden vertex array is refused with ``E_ARRAY_NOT_EVALUATED``.
"""
import dataclasses
import math
import os
import sys
import time

import bpy

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common  # noqa: E402
import real_data as rd  # noqa: E402
from bl_common import check, check_close, check_eq  # noqa: E402

ID = "b11"
TITLE = "arrays (model-backed and model-less), 650 objects, E_TOO_MANY passthrough"
NEEDS_STUB = True


def make_array(source, count):
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    source.select_set(True)
    bpy.context.view_layer.objects.active = source
    check_eq(bpy.ops.object.setup_array(type='CONST', count=count), {'FINISHED'})


def run(env):
    stub = env.stub
    scene = bpy.context.scene
    env.use_library()
    env.import_stub()
    by = dict((o["mj_slot"], o) for o in env.forge_objects())
    check(by[1].instance_collection is not None, "slot 1 has a model (stand-in library)")
    check(by[2].instance_collection is None, "slot 2 (Assault Rifle) has none")

    make_array(by[1], 3)                                      # model-backed
    make_array(by[2], 4)                                      # model-less
    result, path = env.export_to("b11_arrays.mvar")
    check_eq(result, {'FINISHED'})
    objs = list(stub.LAST_EXPORT[1])
    block = [o for o in objs if o.name.startswith("1 - ")]
    rifle = [o for o in objs if o.name.startswith("2 - ")]
    check_eq(len(block), 3, "N instances -> N objects (model-backed)")
    check_eq(len(rifle), 4, "N instances -> N objects (model-less)")
    check_eq(len(objs), 5 - 2 + 3 + 4, "5 objects, two of them arrayed")
    for group, slot, count in ((block, 1, 3), (rifle, 2, 4)):
        claimed = [o for o in group if o.slot is not None]
        check_eq([o.slot for o in claimed], [slot], "only the first instance claims the slot")
        check(claimed[0].token_raw is not None and claimed[0].name_matches_import)
        others = [o for o in group if o.slot is None]
        check_eq(len(others), count - 1)
        check(all(o.from_array and o.token_raw is None and not o.name_matches_import for o in others), "new, from_array")
        check_eq(len(set(o.name for o in group)), count, "unique names")
    # positions advance by the array offset (1, 0, 0) in the source's own frame; the imported objects face +X, so their
    # local X is world -Y
    check_close(sorted(o.position[1] for o in block), [18.0, 19.0, 20.0], 1e-4, "instance positions (model-backed)")
    check_close(sorted(o.position[1] for o in rifle), [0.25, 1.25, 2.25, 3.25], 1e-4, "instance positions (model-less)")
    check_close(sorted(set(round(o.position[0], 4) for o in block)), [10.0], 1e-4)
    for o in block + rifle:
        check_close(o.forward, (1.0, 0.0, 0.0), 1e-5, "instances keep the source orientation")
    check_eq(set(o.type_id_hint for o in rifle), {0}, "the rifle keeps its type id")
    check_eq(set(o.cached_type for o in rifle), {1})
    check_eq(set(o.type_name for o in block), {"Block, 1x1"})
    # the overlay counts the same objects
    depsgraph = bpy.context.evaluated_depsgraph_get()
    check_eq(env.mjolnir.count_forge_objects(scene, depsgraph), len(objs), "overlay count == exported objects")

    # --- the other two array types (object offset, curve) -------------------------------------------------------
    env.reset()
    env.import_stub()
    by = dict((o["mj_slot"], o) for o in env.forge_objects())
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    by[2].select_set(True)
    bpy.context.view_layer.objects.active = by[2]
    check_eq(bpy.ops.object.setup_array(type='OBJECT', count=3, offset=(0, 2, 0), rotation=(0, 0, 45)), {'FINISHED'})
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    by[1].select_set(True)
    bpy.context.view_layer.objects.active = by[1]
    check_eq(bpy.ops.object.setup_array(type='CURVE', size=6.0), {'FINISHED'})
    result, path = env.export_to("b11_array_types.mvar")
    check_eq(result, {'FINISHED'}, "object and curve arrays export")
    objs = list(stub.LAST_EXPORT[1])
    check_eq(len([o for o in objs if o.name.startswith("2 - ")]), 3, "object-offset array: 3 instances")
    check(len([o for o in objs if o.name.startswith("1 - ")]) >= 2, "curve array: several instances")
    check_eq(len([o for o in objs if o.slot is not None]), 5, "each source still claims its slot exactly once")
    check(len(set(o.position for o in objs if o.name.startswith("2 - "))) == 3, "the offset object spreads the copies")

    # --- instancing vertices (VERTS) makes an array source too, just like FACES ---------------------------------------
    env.reset()
    env.import_stub()
    by = dict((o["mj_slot"], o) for o in env.forge_objects())
    source = by[2]
    corners = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 3.0, 0.0), (2.0, 3.0, 0.0)]
    mesh = bpy.data.meshes.new("vertex holder")
    mesh.from_pydata(corners, [], [])
    holder = bpy.data.objects.new("vertex holder", mesh)
    scene.collection.objects.link(holder)
    holder.instance_type = 'VERTS'
    holder.show_instancer_for_viewport = holder.show_instancer_for_render = False
    source.parent = holder
    check_eq(holder.instance_type, 'VERTS')
    check(env.mjolnir.is_array_source(source), "a child of a VERTS instancer is an array source")
    check(not env.mjolnir.is_array_source(by[1]), "an object without such a parent is not")
    result, path = env.export_to("b11_verts.mvar")
    check_eq(result, {'FINISHED'}, "a VERTS array exports")
    objs = list(stub.LAST_EXPORT[1])
    rifle = [o for o in objs if o.name.startswith("2 - ")]
    check_eq(len(rifle), 4, "one instance per vertex")
    check_eq(len(objs), 5 - 1 + 4, "the other four objects are exported once each")
    check_eq([o.slot for o in rifle if o.slot is not None], [2], "only one instance claims the slot")
    check_eq(len([o for o in rifle if o.from_array and o.slot is None and o.token_raw is None]), 3, "the rest are new")
    origin = stub.CANNED.objects[1].position                     # slot 2: the source's own position
    expected = sorted((origin[0] + dx, origin[1] + dy, origin[2]) for dx, dy, _dz in corners)
    for got, want in zip(sorted(o.position for o in rifle), expected):
        check_close(got, want, 1e-4, "an instance sits on its vertex")
    check_eq(env.mjolnir.count_forge_objects(scene, bpy.context.evaluated_depsgraph_get()), len(objs),
             "the overlay counts the vertex instances too")
    holder.hide_set(True)                                       # not evaluated: refused, like a hidden FACES parent
    result, path = env.export_to("b11_verts_hidden.mvar")
    check(isinstance(result, RuntimeError), "refused: %r" % (result,))
    check("ERROR E_ARRAY_NOT_EVALUATED '2 - Assault Rifle'" in env.report_text(), env.report_text())
    check(not os.path.exists(path), "nothing written")
    holder.hide_set(False)
    result, path = env.export_to("b11_verts_back.mvar")
    check_eq(result, {'FINISHED'}, "visible again: exported again")

    # --- 650 objects ----------------------------------------------------------------------------------------------
    env.reset()
    records = [stub.make_record(i, "Forge World", "Block, 1x1", (-200.0 + (i % 40) * 10.0, -300.0 + (i // 40) * 10.0, 0.0),
                                placement=0xCC) for i in range(650)]
    info = dataclasses.replace(stub.CANNED.info, occupied=650)
    load = dataclasses.replace(stub.CANNED, info=info, objects=records)
    t0 = time.time()
    result, _ = env.import_stub(load=load)
    elapsed = time.time() - t0
    check_eq(result, {'FINISHED'})
    check_eq(len(env.forge_objects()), 650)
    check(elapsed < 20, "650 objects imported in %.1fs" % elapsed)
    st = env.state.get(scene)
    check_eq(len(st["imported_slots"]), 650)
    t0 = time.time()
    result, path = env.export_to("b11_650.mvar")
    check_eq(result, {'FINISHED'})
    check(time.time() - t0 < 20, "650 objects exported in %.1fs" % (time.time() - t0))
    objs = stub.LAST_EXPORT[1]
    check_eq(len(objs), 650)
    check_eq(sorted(o.slot for o in objs), list(range(650)))
    check_eq(stub.LAST_EXPORT[2].imported_slots, list(range(650)))
    for rec, eo in list(zip(records, sorted(objs, key=lambda o: o.slot)))[::97]:
        check_eq(bl_common.record_vs_export(rec, eo), [], "slot %d" % rec.slot)

    # one more object than the limit: the library refuses (stub: preset), the glue shows it and writes nothing
    extra = env.forge_objects()[0].copy()
    scene.collection.objects.link(extra)
    for key in ("mj_slot", "mj_raw", "mj_raw_bits", "mj_parent_slot", "mj_name", "mj_physics"):
        del extra[key]
    extra.name = "one too many"
    message = "650 objects would be written; the limit is 650. Remove 1 object(s). (A file that already holds more than 650 objects cannot be exported.)"
    stub.preset_refusal(stub.Issue("E_TOO_MANY", "error", message))
    result, path = env.export_to("b11_651.mvar")
    check(isinstance(result, RuntimeError) and "Export refused: 1 problem(s)" in str(result), repr(result))
    check(message in str(result), "the message reaches the user")
    check(not os.path.exists(path), "nothing written")
    check("ERROR E_TOO_MANY: " + message in env.report_text())
    check_eq(len(stub.LAST_EXPORT[1]), 651, "the glue handed all 651 objects over and left the decision to the library")


# =====================================================================================================
# the real-provider variant (G6)
# =====================================================================================================
W1_BITS = (20, 21, 19)
W1_LO = (-240.0, -345.0, -70.0)
W1_HI = (240.0, 345.0, 70.0)


def arrays_fixture():
    """W1's map with a block (slot 1) and an Assault Rifle with 3 spare clips (slot 2: class 1, extras [3])."""
    spec = rd.w1_spec("b11_arrays", "a block and a rifle for the array tests")
    spec["slots"] = [
        {"index": 1, "folder": 70, "item": 0, "pos": [524288, 1048576, 262144]},
        {"index": 2, "folder": 0, "item": 0, "pos": [524300, 1048500, 262200], "cached_type": 1, "extra": [3]},
    ]
    spec["quotas"]["rows"] = {"70": [0, 16, 1], "0": [0, 8, 1]}
    return rd.build_spec(spec)


def positions(decoded, slots):
    return [tuple(rd.cell_centre(decoded["slots"][i]["pos"][k], W1_BITS[k], W1_LO[k], W1_HI[k]) for k in range(3)) for i in slots]


def exported(env, name, **options):
    result, path = env.export_to(name, **options)
    check_eq(result, {'FINISHED'}, "%s: %r\n%s" % (name, result, env.report_text()[:2500]))
    return rd.decode(rd.read_bytes(path))


def run_real(env):
    _build, selfcheck, _catalogue = rd.modules()
    scene = bpy.context.scene
    env.use_library()
    data = arrays_fixture()
    dec = rd.decode(data)
    env.import_bytes(data, "b11_arrays.mvar")
    by = dict((o["mj_slot"], o) for o in env.forge_objects())
    check(by[1].instance_collection is not None, "slot 1 has a model (stand-in library)")
    check(by[2].instance_collection is None, "slot 2 (Assault Rifle) has none")
    scene.forge.allowUnverifiedRotation = True

    make_array(by[1], 3)                                      # model-backed
    make_array(by[2], 4)                                      # model-less
    collected = env.io_ops.collect_export_objects(scene)
    check_eq([i.code for i in collected.errors], [])
    objs = collected.objects
    block = [o for o in objs if o.name.startswith("1 - ")]
    rifle = [o for o in objs if o.name.startswith("2 - ")]
    check_eq((len(block), len(rifle), len(objs)), (3, 4, 7), "N instances -> N objects, model-backed and model-less")
    check(len(set(o.name for o in block + rifle)) == 7, "unique names")
    after = exported(env, "b11_arrays_out.mvar")
    new_blocks = sorted(i for i, s in after["slots"].items() if (s["folder"], s["item"]) == (70, 0) and i != 1)
    new_rifles = sorted(i for i, s in after["slots"].items() if (s["folder"], s["item"]) == (0, 0) and i != 2)
    check_eq((len(new_blocks), len(new_rifles)), (2, 3), "2 + 3 new objects")
    check_eq(after["slots"][1], dec["slots"][1], "the first instance keeps slot 1 byte for byte")
    check_eq(after["slots"][2], dec["slots"][2], "the first rifle keeps slot 2 byte for byte")
    for i in new_rifles:
        check_eq((after["slots"][i]["cached_type"], after["slots"][i]["extra"]), (1, [3]), "a new rifle: class 1 with 3 spare clips")
    check_eq(after["quotas"][70], [0, 16, 3])
    check_eq(after["quotas"][0], [0, 8, 4])
    # the array step is the source's local X (world -Y here): one unit per instance
    t = selfcheck.angle_decode(8192)
    for source_slot, news, count in ((1, new_blocks, 3), (2, new_rifles, 4)):
        base = positions(dec, [source_slot])[0]
        want = sorted(((base[0] + k * math.sin(t), base[1] - k * math.cos(t), base[2]) for k in range(1, count)), key=lambda p: p[1])
        got = sorted(positions(after, news), key=lambda p: p[1])
        for g, w in zip(got, want):
            check_close(g, w, 2e-3, "instance of slot %d one array step apart" % source_slot)
    # the overlay counts the same objects
    check_eq(env.mjolnir.count_forge_objects(scene, bpy.context.evaluated_depsgraph_get()), len(objs), "overlay count == exported objects")

    # --- the other two array types (object offset, curve) export too ----------------------------------------------------------------------
    env.reset()
    env.use_library()
    env.import_bytes(data, "b11_arrays2.mvar")
    scene = bpy.context.scene
    scene.forge.allowUnverifiedRotation = True
    by = dict((o["mj_slot"], o) for o in env.forge_objects())
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    by[2].select_set(True)
    bpy.context.view_layer.objects.active = by[2]
    check_eq(bpy.ops.object.setup_array(type='OBJECT', count=3, offset=(0, 2, 0), rotation=(0, 0, 45)), {'FINISHED'})
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    by[1].select_set(True)
    bpy.context.view_layer.objects.active = by[1]
    check_eq(bpy.ops.object.setup_array(type='CURVE', size=6.0), {'FINISHED'})
    objs = env.io_ops.collect_export_objects(scene).objects
    check_eq(len([o for o in objs if o.name.startswith("2 - ")]), 3, "object-offset array: 3 instances")
    check(len([o for o in objs if o.name.startswith("1 - ")]) >= 2, "curve array: several instances")
    check_eq(len([o for o in objs if o.slot is not None]), 2, "each source still claims its slot exactly once")
    after = exported(env, "b11_array_types.mvar")
    check_eq(len(after["slots"]), len(objs), "every instance is in the file")

    # --- instancing vertices (VERTS) -------------------------------------------------------------------------------------------------------------
    env.reset()
    env.import_bytes(data, "b11_verts.mvar")
    scene = bpy.context.scene
    scene.forge.allowUnverifiedRotation = True
    by = dict((o["mj_slot"], o) for o in env.forge_objects())
    source = by[2]
    corners = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 3.0, 0.0), (2.0, 3.0, 0.0)]
    mesh = bpy.data.meshes.new("vertex holder")
    mesh.from_pydata(corners, [], [])
    holder = bpy.data.objects.new("vertex holder", mesh)
    scene.collection.objects.link(holder)
    holder.instance_type = 'VERTS'
    holder.show_instancer_for_viewport = holder.show_instancer_for_render = False
    source.parent = holder
    check(env.mjolnir.is_array_source(source) and not env.mjolnir.is_array_source(by[1]))
    after = exported(env, "b11_verts_out.mvar")
    new_rifles = sorted(i for i, s in after["slots"].items() if (s["folder"], s["item"]) == (0, 0) and i != 2)
    check_eq(len(new_rifles), 3, "one instance per vertex: the first keeps slot 2, three are new")
    origin = positions(dec, [2])[0]
    want = sorted((origin[0] + dx, origin[1] + dy, origin[2]) for dx, dy, _dz in corners)
    got = sorted(positions(after, [2] + new_rifles))
    for g, w in zip(got, want):
        check_close(g, w, 2e-3, "an instance sits on its vertex")
    holder.hide_set(True)
    result, path = env.export_to("b11_verts_hidden.mvar")
    check(isinstance(result, RuntimeError) and "ERROR E_ARRAY_NOT_EVALUATED '2 - Assault Rifle'" in env.report_text(), repr(result))
    check(not os.path.exists(path), "nothing written")
    holder.hide_set(False)
    exported(env, "b11_verts_back.mvar")

    # --- 650 objects: exports unchanged; one more is refused ---------------------------------------------------------------------------------------
    env.reset()
    full = rd.fixture("full650")
    t0 = time.time()
    result, _ = env.import_bytes(full, "b11_full650.mvar")
    elapsed = time.time() - t0
    check_eq(result, {'FINISHED'})
    check_eq(len(env.forge_objects()), 650)
    check(elapsed < 20, "650 objects imported in %.1fs" % elapsed)
    st = env.state.get(bpy.context.scene)
    check_eq((len(st["imported_slots"]), st["failed_slots"]), (650, []))
    t0 = time.time()
    result, path = env.export_to("b11_650.mvar")
    check_eq(result, {'FINISHED'}, "full650 exports: %r\n%s" % (result, env.report_text()[:1500]))
    check(time.time() - t0 < 20, "650 objects exported in %.1fs" % (time.time() - t0))
    check(rd.read_bytes(path) == full, "full650: unchanged export, byte for byte")
    bpy.context.scene.forge.allowUnverifiedRotation = True
    extra = env.forge_objects()[0].copy()
    bpy.context.scene.collection.objects.link(extra)
    result, path = env.export_to("b11_651.mvar")
    check(isinstance(result, RuntimeError) and "Export refused" in str(result), repr(result))
    check("ERROR E_TOO_MANY: 651 objects would be written; the limit is 650. Remove 1 object(s)." in env.report_text(), env.report_text()[:1500])
    check(not os.path.exists(path), "nothing written")
    env.reset()
    env.import_bytes(rd.fixture("over650"), "b11_over650.mvar")
    check_eq(len(env.forge_objects()), 651)
    result, path = env.export_to("b11_over650_out.mvar")
    check(isinstance(result, RuntimeError) and "E_TOO_MANY" in env.report_text(), "over650 is refused even unchanged: %r" % (result,))
    check(not os.path.exists(path), "nothing written")


if __name__ == "__main__":
    bl_common.main_module(sys.modules[__name__])
