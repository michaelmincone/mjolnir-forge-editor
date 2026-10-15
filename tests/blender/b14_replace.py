"""B-14 (SPEC 9.4, 8.4, 8.7 #17): ``replace_existing`` removes imported objects and their helpers, keeps the user's.

A second import into a scene that holds a map variant deletes every object with an ``mj_slot`` together with its
shape and loadout-camera helper children (they carry no flag), replaces the stored state and keeps user-made Forge
objects and plain Blender objects. Without ``replace_existing`` the import is refused and nothing changes.
"""
import hashlib
import os
import sys

import bpy

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common  # noqa: E402
import real_data as rd  # noqa: E402
from bl_common import check, check_eq  # noqa: E402

ID = "b14"
TITLE = "replace_existing removes imported objects and helpers, keeps user-made objects"
NEEDS_STUB = True


def helpers():
    return sorted(o.name for o in bpy.data.objects if o.get("mj_helper"))


def run(env):
    stub = env.stub
    scene = bpy.context.scene
    env.import_stub()
    check_eq(len(env.forge_objects()), 5)
    check_eq(len(helpers()), 2, "one shape helper and one camera")
    check_eq(len(bpy.data.cameras), 1)

    # user-made things
    bpy.ops.forge.add_object(objectType="Block, 1x1")
    mine = bpy.context.active_object
    plain = bpy.data.objects.new("plain empty", None)
    scene.collection.objects.link(plain)
    old_state = env.state.get(scene)

    # replace with another map variant, from a file with different bytes (the stored template must follow)
    second = env.write_template("second.mvar", b"SECOND-TEMPLATE-BYTES")
    result, _ = env.import_stub(load=stub.CANNED_BONEYARD, path=second)
    check_eq(result, {'FINISHED'})
    names = sorted(o.name for o in bpy.data.objects)
    check("Block, 1x1" in names, "the user's forge object is kept")
    check("plain empty" in names, "the plain object is kept")
    check(mine.name in bpy.data.objects and "mj_slot" not in mine)
    imported = sorted(o["mj_slot"] for o in env.forge_objects() if "mj_slot" in o)
    check_eq(imported, [1, 2, 3], "only the new objects carry slots")
    check(not any(n.startswith(("5 - ", "9 - ", "11 - ")) for n in names), "old imported objects are gone: %s" % names)
    check_eq(len(helpers()), 2, "the old helpers are gone, the new map brought its own (shape + camera)")
    check_eq(len(bpy.data.cameras), 1, "the old camera data was removed")
    new_state = env.state.get(scene)
    check_eq(new_state["map_name"], "Boneyard")
    check(new_state["template_sha256"] != old_state["template_sha256"], "the stored template is replaced, not kept")
    check_eq(new_state["template_sha256"], hashlib.sha256(b"SECOND-TEMPLATE-BYTES").hexdigest())
    check_eq(env.state.template_bytes(scene), b"SECOND-TEMPLATE-BYTES", "the embedded bytes are the second file")
    check_eq(new_state["source_name"], "second.mvar")
    ok, why = env.state.verify_template(scene)
    check(ok, "the replaced template verifies: %s" % why)
    check_eq(new_state["imported_slots"], [1, 2, 3])
    check_eq(len(env.forge_objects()), 4, "3 imported + the user's object")

    # no replacing: refused, nothing changes
    before = sorted(o.name for o in bpy.data.objects)
    stub.NEXT_LOAD = stub.CANNED
    try:
        bpy.ops.import_scene.mjolnir_mvar(filepath=env.write_template(), replace_existing=False)
        raised = None
    except RuntimeError as exc:
        raised = str(exc)
    check(raised and "This scene already contains a map variant; tick Replace Existing or use a new scene." in raised, raised)
    check_eq(sorted(o.name for o in bpy.data.objects), before, "nothing changed")
    check_eq(env.state.get(scene)["map_name"], "Boneyard")

    # a library refusal on a second import leaves the first import alone
    stub.NEXT_LOAD_ERROR = stub.UnsupportedVariantError("nope")
    try:
        bpy.ops.import_scene.mjolnir_mvar(filepath=env.write_template())
    except RuntimeError:
        pass
    check_eq(sorted(o.name for o in bpy.data.objects), before, "a refused file replaces nothing")
    check_eq(env.state.get(scene)["map_name"], "Boneyard")

    # a missing file and an oversized file are refused with their messages
    try:
        bpy.ops.import_scene.mjolnir_mvar(filepath=os.path.join(env.tmp, "missing.mvar"))
        missing = None
    except RuntimeError as exc:
        missing = str(exc)
    check(missing and "Cannot read" in missing, missing)
    big = os.path.join(env.tmp, "big.mvar")
    with open(big, "wb") as fh:
        fh.write(b"\0" * ((1 << 20) + 1))
    try:
        bpy.ops.import_scene.mjolnir_mvar(filepath=big)
        too_big = None
    except RuntimeError as exc:
        too_big = str(exc)
    check(too_big and "This does not look like a map variant (file too large)." in too_big, too_big)
    check_eq(sorted(o.name for o in bpy.data.objects), before)


# =====================================================================================================
# the real-provider variant (G6)
# =====================================================================================================
def run_real(env):
    scene = bpy.context.scene
    first = rd.build_spec(rd.cast_spec("b14_first"))
    result, _ = env.import_bytes(first, "b14_first.mvar")
    check_eq(result, {'FINISHED'})
    check_eq(len(env.forge_objects()), 9)
    check_eq(len(helpers()), 4, "three shape helpers and one camera")
    check_eq(len(bpy.data.cameras), 1)

    # user-made things
    check_eq(bpy.ops.forge.add_object(objectType="Block, 1x1"), {'FINISHED'})
    mine = bpy.context.active_object
    plain = bpy.data.objects.new("plain empty", None)
    scene.collection.objects.link(plain)
    old_state = env.state.get(scene)

    # replace with another map's file, with different bytes (the stored template must follow)
    spec = rd.w1_spec("b14_second", "W1 on Boneyard")
    spec["header"]["map_id"] = rd.BONEYARD
    spec["body"]["map_id_2"] = rd.BONEYARD
    second = rd.build_spec(spec)
    check(second != first)
    result, second_path = env.import_bytes(second, "b14_second.mvar")
    check_eq(result, {'FINISHED'})
    names = sorted(o.name for o in bpy.data.objects)
    check("Block, 1x1" in names and "plain empty" in names, "the user's objects are kept: %s" % names)
    check(mine.name in bpy.data.objects and "mj_slot" not in mine)
    imported = sorted(o["mj_slot"] for o in env.forge_objects() if "mj_slot" in o)
    check_eq(imported, [1, 5, 650], "only the new objects carry slots")
    check(not any(n.startswith(("9 - ", "11 - ", "20 - ", "21 - ", "22 - ", "23 - ")) for n in names), "old imported objects are gone: %s" % names)
    check_eq(len(helpers()), 1, "the old helpers are gone; the new file brought its own shape helper (no camera)")
    check_eq(len(bpy.data.cameras), 0, "the old camera data was removed")
    new_state = env.state.get(scene)
    check_eq(new_state["map_name"], "Boneyard")
    check(new_state["template_sha256"] != old_state["template_sha256"], "the stored template is replaced, not kept")
    check_eq(new_state["template_sha256"], hashlib.sha256(second).hexdigest())
    check_eq(env.state.template_bytes(scene), second, "the embedded bytes are the second file")
    check_eq(new_state["source_name"], "b14_second.mvar")
    ok, why = env.state.verify_template(scene)
    check(ok, "the replaced template verifies: %s" % why)
    check_eq(new_state["imported_slots"], [1, 5, 650])
    check_eq(len(env.forge_objects()), 4, "3 imported + the user's object")
    # the replaced scene exports the NEW file; the user's own object would be a new one, so it goes first
    bpy.data.objects.remove(mine, do_unlink=True)
    result, path = env.export_to("b14_out.mvar")
    check_eq(result, {'FINISHED'}, "%r\n%s" % (result, env.report_text()[:1500]))
    check(rd.read_bytes(path) == second, "the replaced scene exports the second file, byte for byte")

    # no replacing: refused, nothing changes
    before = sorted(o.name for o in bpy.data.objects)
    try:
        bpy.ops.import_scene.mjolnir_mvar(filepath=second_path, replace_existing=False)
        raised = None
    except RuntimeError as exc:
        raised = str(exc)
    check(raised and "This scene already contains a map variant; tick Replace Existing or use a new scene." in raised, raised)
    check_eq(sorted(o.name for o in bpy.data.objects), before, "nothing changed")
    check_eq(env.state.get(scene)["map_name"], "Boneyard")

    # a file the library refuses leaves the first import alone
    garbage = os.path.join(env.tmp, "garbage.mvar")
    with open(garbage, "wb") as fh:
        fh.write(b"this is not a map variant")
    try:
        bpy.ops.import_scene.mjolnir_mvar(filepath=garbage)
    except RuntimeError:
        pass
    check_eq(sorted(o.name for o in bpy.data.objects), before, "a refused file replaces nothing")
    check_eq(env.state.get(scene)["map_name"], "Boneyard")
    check_eq(env.state.template_bytes(scene), second)

    # a missing file and an oversized file are refused with their messages
    try:
        bpy.ops.import_scene.mjolnir_mvar(filepath=os.path.join(env.tmp, "missing.mvar"))
        missing = None
    except RuntimeError as exc:
        missing = str(exc)
    check(missing and "Cannot read" in missing, missing)
    big = os.path.join(env.tmp, "big.mvar")
    with open(big, "wb") as fh:
        fh.write(b"\0" * ((1 << 20) + 1))
    try:
        bpy.ops.import_scene.mjolnir_mvar(filepath=big)
        too_big = None
    except RuntimeError as exc:
        too_big = str(exc)
    check(too_big and "This does not look like a map variant (file too large)." in too_big, too_big)
    check_eq(sorted(o.name for o in bpy.data.objects), before)


if __name__ == "__main__":
    bl_common.main_module(sys.modules[__name__])
