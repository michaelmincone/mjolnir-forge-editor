"""B-02 (SPEC 9.4): import through File > Import: objects, names, matrices, identity props, scene state.

Stub variant (``run``): the provider's ``CANNED`` Forge World map, five objects. Real variant (``run_real``, G6): W1, the
reference fixture of the independent builder, imported through the REAL library; every expectation is derived from the
independent decode (position cells, the angle and up codecs) or from the fixture's declared values, never from the
library. Also, in both: an unknown map id (0xFFFFFFFF) imports without an exception, with ``map_name`` '' and
``map_id_hex`` '0xFFFFFFFF'; a refused file creates nothing and leaves no state; and (real) importing the real
Breakneck file keeps the console bounded.
"""
import dataclasses
import glob
import hashlib
import math
import os
import sys

import bpy
from mathutils import Vector

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common  # noqa: E402
import real_data as rd  # noqa: E402
from bl_common import check, check_close, check_eq  # noqa: E402

ID = "b02"
TITLE = "import: objects, names, matrices, mj_* props, scene state"
NEEDS_STUB = True


def check_import_is_all_or_nothing(env, path):
    """An unexpected failure outside the per-object isolation leaves no state and no objects (nothing half-imported)."""
    def boom():
        raise RuntimeError("synthetic failure outside the per-object try")

    with bl_common.patched(env.palette, "collection_index", boom):
        with bl_common.capture_output(stderr=True) as out:
            try:
                bpy.ops.import_scene.mjolnir_mvar(filepath=path)
                raised = None
            except RuntimeError as exc:
                raised = str(exc)
    check(raised is not None and "Unexpected error while importing: RuntimeError: synthetic failure outside the per-object try. Nothing was imported." in raised, repr(raised))
    check_eq(len(env.forge_objects()), 0, "no object left")
    check_eq(env.state.get(bpy.context.scene), None, "no state that claims 'no slot imported'")
    check("mjolnir_template" not in bpy.context.scene, "no template left in the scene")


def run(env):
    stub = env.stub
    canned = stub.CANNED
    template = b"B02-template-bytes\x00\xff" * 3
    path = env.write_template("b02.mvar", template)

    with bl_common.capture_output() as out:
        result, _ = env.import_stub(path=path)
    check_eq(result, {'FINISHED'}, "import result")
    check("Imported 5 objects from b02.mvar (Forge World, 5 of 650 slots used)" in out[0], out[0])
    check("Palette library not found" in out[0], "arrow-empty warning missing: " + out[0])

    objs = env.forge_objects()
    check_eq(len(objs), 5, "object count")
    by_slot = dict((o["mj_slot"], o) for o in objs)
    check_eq(sorted(by_slot), [1, 2, 5, 9, 11])
    for rec in canned.objects:
        obj = by_slot[rec.slot]
        check_eq(obj.name, "%d - %s" % (rec.slot, rec.type_name), "name")
        fwd, up, pos = Vector(rec.forward), Vector(rec.up), Vector(rec.position)
        m = obj.matrix_world
        check_close(m.col[0].xyz, fwd.cross(up), 1e-5, "right")
        check_close(m.col[1].xyz, fwd, 1e-5, "forward")
        check_close(m.col[2].xyz, up, 1e-5, "up")
        check_close(m.col[3].xyz, pos, 1e-5, "position")
        check_eq(bytes(obj["mj_raw"]), rec.raw, "token")
        check_eq(obj["mj_raw_bits"], rec.raw_bits)
        check_eq(obj["mj_parent_slot"], rec.parent_slot)
        check_eq(obj["mj_name"], obj.name)
        check_eq(obj["mj_physics"], rec.physics)
        fp = obj.forge
        check_eq(fp.objectType, rec.type_id, "type id")
        check_eq(fp.cachedType, rec.cached_type)
        check_eq(fp.otherInfoA, rec.other_a)
        check_eq(fp.spawnSequence, rec.spawn_sequence)
        check_eq(fp.symmetry, "BOTH", "placement 0xCC / 0x0C decode")
        check_eq(fp.placeAtStart, True)
        check(obj.empty_display_type == 'ARROWS' and obj.instance_collection is None, "no library: arrow empty")
        check(all(obj.lock_scale), "scale is locked")

    # the label keeps its original case; the enum shows the text
    kill = by_slot[5]
    check_eq(kill.forge.gtLabel, "L1")
    items = [(i[0], i[1]) for i in env.mjolnir._label_items(kill.forge, bpy.context)]
    check_eq(items, [("NO_LABEL", "No Label"), ("L0", "SCALE"), ("L1", "Kill Boundary"), ("L2", "Spawn")], "label enum")
    check_eq(kill.forge.shape, "BOX")
    helper = [c for c in kill.children if c.get("mj_helper") == "shape"]
    check_eq(len(helper), 1, "shape helper child")
    check_close(tuple(helper[0].scale), (20.0, 15.0, 15.0), 1e-5, "box scale (width, length, top+bottom)")
    camera_parent = by_slot[11]
    cams = [c for c in camera_parent.children if c.get("mj_helper") == "camera"]
    check_eq(len(cams), 1, "loadout camera child")
    check_eq(cams[0].type, "CAMERA")

    # scene state
    scene = bpy.context.scene
    raw = scene["mjolnir_template"]
    check_eq(bytes(raw), template, "embedded template")
    st = env.state.get(scene)
    check_eq(st["template_sha256"], hashlib.sha256(template).hexdigest())
    check_eq(st["source_name"], "b02.mvar")
    check_eq(st["source_path"], path)
    check_eq(st["map_id_hex"], "0x00000BBE")
    check_eq(st["map_name"], "Forge World")
    check_eq(st["labels"], ["SCALE", "Kill Boundary", "Spawn"], "labels in original case")
    check_eq(st["label_present"], [1, 1, 1])
    check_close(st["bounds"], canned.info.bounds, 1e-9)
    check_eq(st["quota_count"], 80)
    check_eq(st["version"], 31)
    check_eq(st["occupied_at_import"], 5)
    check_eq(st["imported_slots"], [1, 2, 5, 9, 11])
    check_eq(st["failed_slots"], [])
    check_eq(st["hash_flavour"], "salted_be32/>")
    check_eq(st["hypothesis"]["type19"], "undetermined")
    check_eq(list(st["hypothesis"]["axis_bits"]), [20, 21, 19])
    check_eq(st["hypothesis"]["guid"], False)
    check_eq(st["addon_version"], env.mjolnir.VERSION)
    check("mvarlib_version" in st, "mvarlib_version key")
    check(all(abs(v) < 2 ** 31 for v in st["imported_slots"]), "32-bit ints only")
    check_eq(len(bpy.app.driver_namespace.keys() & {"gtIndexToLabel", "persist_vars"}), 0, "driver_namespace unused")

    # the stub saw the file name and the exact bytes
    check_eq(stub.LAST_LOAD[0], template)
    check_eq(stub.LAST_LOAD[1], "b02.mvar")

    # an unknown map id imports without an exception
    env.reset()
    unknown = dataclasses.replace(canned.info, map_id=0xFFFFFFFF, map_name=None, is_stock_map=False)
    load = dataclasses.replace(canned, info=unknown)
    with bl_common.capture_output() as out:
        result, _ = env.import_stub(load=load)
    check_eq(result, {'FINISHED'}, "unknown map import")
    st = env.state.get(bpy.context.scene)
    check_eq(st["map_id_hex"], "0xFFFFFFFF")
    check_eq(st["map_name"], "")
    check_eq(len(env.forge_objects()), 5)

    env.reset()
    check_import_is_all_or_nothing(env, path)

    # a library refusal creates nothing and reports the message
    env.reset()
    stub.NEXT_LOAD_ERROR = stub.UnsupportedVariantError(
        "This is a game variant (block 'mpvr'), not a map variant. Use File > Import for map variants only.")
    with bl_common.capture_output() as out:
        try:
            bpy.ops.import_scene.mjolnir_mvar(filepath=path)
            raised = None
        except RuntimeError as exc:
            raised = str(exc)
    check(raised and "game variant" in raised, "refusal text reaches the caller: %r" % raised)
    check_eq(len(env.forge_objects()), 0, "nothing created")
    check_eq(env.state.get(bpy.context.scene), None, "no state after a refusal")


# =====================================================================================================
# the real-provider variant (G6): W1 from the independent builder, the real library
# =====================================================================================================
W1_BITS = (20, 21, 19)
W1_BOUNDS = (-240.0, 240.0, -345.0, 345.0, -70.0, 70.0)


def w1_world_position(cells):
    return tuple(rd.cell_centre(cells[k], W1_BITS[k], W1_BOUNDS[2 * k], W1_BOUNDS[2 * k + 1]) for k in range(3))


def run_real(env):
    _build, selfcheck, _catalogue = rd.modules()
    w1 = rd.fixture("w1_minimal")
    dec = rd.decode(w1)
    path = os.path.join(env.tmp, "b02_w1.mvar")
    with open(path, "wb") as fh:
        fh.write(w1)
    with bl_common.capture_output() as out:
        result = bpy.ops.import_scene.mjolnir_mvar(filepath=path)
    check_eq(result, {'FINISHED'}, "import result")
    check("Imported 3 objects from b02_w1.mvar (Forge World, 3 of 650 slots used)" in out[0], out[0])
    check("Palette library not found" in out[0], "arrow-empty warning missing: " + out[0])
    objs = env.forge_objects()
    check_eq(len(objs), 3, "object count")
    by_slot = dict((o["mj_slot"], o) for o in objs)
    check_eq(sorted(by_slot), [1, 5, 650])
    check_eq(sorted(o.name for o in objs), ["1 - Block, 1x1", "5 - Kill Boundary", "650 - Block, 1x1"], "names are \"slot - type\"")

    # positions: the cell centres of the independent decode
    for slot, obj in by_slot.items():
        check_close(tuple(obj.matrix_world.translation), w1_world_position(dec["slots"][slot]["pos"]), 2e-4, "position of slot %d" % slot)
    # orientation: vertical slots are yaw decode(8192) about +Z (forward = (cos t, sin t, 0)); slot 650 has the up code 436468
    yaw = selfcheck.angle_decode(8192)
    for slot in (1, 5):
        m = by_slot[slot].matrix_world
        check_close(m.col[1].xyz, (math.cos(yaw), math.sin(yaw), 0.0), 1e-5, "forward of slot %d" % slot)
        check_close(m.col[2].xyz, (0.0, 0.0, 1.0), 1e-6, "up of slot %d" % slot)
        check_close(m.col[0].xyz, Vector(m.col[1].xyz).cross(Vector(m.col[2].xyz)), 1e-5, "right = forward x up")
    up650 = selfcheck.up_decode(436468)[0]
    m = by_slot[650].matrix_world
    check_close(m.col[2].xyz, up650, 1e-5, "up of slot 650 is the decoded up code")
    check(abs(Vector(m.col[1].xyz).dot(Vector(m.col[2].xyz))) < 1e-5 and abs(Vector(m.col[1].xyz).length - 1.0) < 1e-5, "orthonormal")

    # identity props
    p1, p5, p650 = by_slot[1], by_slot[5], by_slot[650]
    for slot, obj in by_slot.items():
        check_eq(obj["mj_name"], obj.name)
        check(len(bytes(obj["mj_raw"])) > 0 and obj["mj_raw_bits"] > 0, "slot %d token" % slot)
        check(all(obj.lock_scale), "scale is locked")
        check(obj.empty_display_type == 'ARROWS' and obj.instance_collection is None, "no library: arrow empty")
        check_eq(len(obj["mj_pose"]), 9)
        check_eq(len(obj["mj_base"]), 9)
    check_eq((p1["mj_raw_bits"], p5["mj_raw_bits"], p650["mj_raw_bits"]), (141, 193, 172), "slot record sizes of Appendix C.2")
    check_eq(p650["mj_parent_slot"], 1, "parent_raw 2 -> parent slot 1")
    check_eq((p1["mj_parent_slot"], p5["mj_parent_slot"]), (-1, -1))
    # properties from the declared values of the spec
    fp = p5.forge
    check_eq((fp.cachedType, fp.spawnSequence, fp.spawnTime, fp.gtLabel), (26, -5, 0, "L1"))
    check_eq(fp.shape, "BOX")
    check_close((fp.width, fp.length, fp.top, fp.bottom), tuple(selfcheck.dim_decode(v) for v in (2047, 1024, 0, 2046)), 1e-4,
                "box dimensions (11-bit codes 2047, 1024, 0, 2046)")
    check_eq((fp.physics, fp.symmetry, fp.placeAtStart, fp.gameSpecific), ("NORMAL", "BOTH", True, False), "placement byte 0x0C")
    check_eq((p1.forge.physics, p1.forge.team, p1.forge.color, p1.forge.gtLabel), ("PHASED", "NEUTRAL", "TEAM_COLOR", "NO_LABEL"),
             "slot 1: placement 0xCC, team raw 9, no colour, no label")
    check_eq((p650.forge.color, p650.forge.gtLabel), ("PINK", "L2"), "slot 650: colour 7, label 2")
    check_eq(p650.forge.shape, "NONE")
    items = [(i[0], i[1]) for i in env.mjolnir._label_items(p5.forge, bpy.context)]
    check_eq(items, [("NO_LABEL", "No Label"), ("L0", "SCALE"), ("L1", "Kill Boundary"), ("L2", "Spawn")], "label enum in original case")
    helpers = [c for c in p5.children if c.get("mj_helper") == "shape"]
    check_eq(len(helpers), 1, "box helper")

    # scene state
    scene = bpy.context.scene
    check_eq(bytes(scene["mjolnir_template"]), w1, "embedded template")
    st = env.state.get(scene)
    check_eq(st["template_sha256"], hashlib.sha256(w1).hexdigest())
    check_eq((st["source_name"], st["source_path"]), ("b02_w1.mvar", path))
    check_eq((st["map_id_hex"], st["map_name"]), ("0x00000BBE", "Forge World"))
    check_eq(st["labels"], ["SCALE", "Kill Boundary", "Spawn"], "labels in original case")
    check_eq(st["label_present"], [1, 1, 1])
    check_close(st["bounds"], W1_BOUNDS, 1e-9)
    check_eq((st["quota_count"], st["version"], st["occupied_at_import"]), (80, 31, 3))
    check_eq((st["imported_slots"], st["failed_slots"]), ([1, 5, 650], []))
    check_eq(st["hash_flavour"], "salted_be32/>")
    check_eq((st["hypothesis"]["type19"], list(st["hypothesis"]["axis_bits"]), st["hypothesis"]["guid"]), ("undetermined", [20, 21, 19], False))
    check_eq(st["addon_version"], env.mjolnir.VERSION)
    check("mvarlib_version" in st, "mvarlib_version key")
    check(all(abs(v) < 2 ** 31 for v in st["imported_slots"]), "32-bit ints only")
    check_eq(len(bpy.app.driver_namespace.keys() & {"gtIndexToLabel", "persist_vars"}), 0, "driver_namespace unused")

    # an unknown map id imports without an exception
    env.reset()
    result, _ = env.import_bytes(rd.fixture("unknown_map"), "b02_unknown.mvar")
    check_eq(result, {'FINISHED'}, "unknown map import")
    st = env.state.get(bpy.context.scene)
    check_eq((st["map_id_hex"], st["map_name"]), ("0xFFFFFFFF", ""))
    check_eq(len(env.forge_objects()), 3)

    env.reset()
    check_import_is_all_or_nothing(env, os.path.join(env.tmp, "b02_w1.mvar"))

    # files the library refuses create nothing and leave no state
    sample = list(w1)
    sample[0x2F0:0x2F4] = list(b"mpvr")                    # a game variant block instead of a map variant
    refusals = (("a block that claims to be a game variant", bytes(sample), "mpvr"),
                ("garbage", b"this is not a map variant at all", ""),
                ("a truncated file", w1[:20000], ""))
    for label, payload, expect in refusals:
        env.reset()
        path = os.path.join(env.tmp, "b02_refused.mvar")
        with open(path, "wb") as fh:
            fh.write(payload)
        try:
            bpy.ops.import_scene.mjolnir_mvar(filepath=path)
            raised = None
        except RuntimeError as exc:
            raised = str(exc)
        check(raised is not None and expect in raised, "%s is refused with a message: %r" % (label, raised))
        check_eq(len(env.forge_objects()), 0, "%s: nothing created" % label)
        check_eq(env.state.get(bpy.context.scene), None, "%s: no state after a refusal" % label)
        check("mjolnir_template" not in bpy.context.scene, "%s: no template left in the scene" % label)

    # a real Halo: Reach GAME variant (read in place, never written): refused with the message that names it
    samples = sorted(glob.glob(os.path.expanduser("~/Local_Documents/Halo-MCC/variant-tool/test-samples/*.bin")))
    if samples:
        env.reset()
        try:
            bpy.ops.import_scene.mjolnir_mvar(filepath=samples[0])
            raised = None
        except RuntimeError as exc:
            raised = str(exc)
        check(raised is not None and "game variant" in raised, "a real game variant is refused: %r" % (raised,))
        check_eq(len(env.forge_objects()), 0)

    # the real Breakneck file: 610 objects, a bounded console, nothing failed
    if rd.real_available():
        env.reset()
        env.use_library()
        with bl_common.capture_output() as out:
            result = env.import_file(rd.real_mvar_path())
        check_eq(result, {'FINISHED'})
        check_eq(len(env.forge_objects()), rd.REAL_OBJECTS, "610 Blender objects")
        lines = [l for l in out[0].splitlines() if l.strip()]
        check(len(lines) <= 12, "the console of a clean import is short (%d lines):\n%s" % (len(lines), out[0][:1500]))
        check_eq(env.state.get(bpy.context.scene)["failed_slots"], [])
        # an import in which EVERY object fails prints a handful of tracebacks and one summary, not 610 tracebacks
        env.reset()

        def always_fails(obj, rec, scene):
            raise ValueError("synthetic failure for slot %d" % rec.slot)

        with bl_common.patched(env.mjolnir, "apply_record", always_fails):
            with bl_common.capture_output(stderr=True) as out:
                result = env.import_file(rd.real_mvar_path())
        check_eq(result, {'FINISHED'}, "an import survives every object failing")
        text = out[0]
        lines = text.splitlines()
        check(len(lines) < 150, "bounded console output: %d lines for 610 failing objects" % len(lines))
        check_eq(text.count("Traceback (most recent call last)"), env.io_ops.MAX_IMPORT_TRACEBACKS, "only the first tracebacks are printed")
        check("610 object(s) could not be imported (1 kind(s) of failure)." in text, "summary line:\n" + text[-1500:])
        check("610 x ValueError: synthetic failure for slot #" in text, text[-1500:])
        check("traceback(s) were printed above, 607 left out." in text, text[-1500:])
        st = env.state.get(bpy.context.scene)
        check_eq((len(st["imported_slots"]), len(st["failed_slots"])), (0, rd.REAL_OBJECTS))
        check_eq(len(env.forge_objects()), 0, "no half-built object is left behind")


if __name__ == "__main__":
    bl_common.main_module(sys.modules[__name__])
