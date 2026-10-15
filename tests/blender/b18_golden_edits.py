"""B-18 (SPEC 9.4, Appendix C.3, gate G6): THE END-TO-END ANCHOR. Blender edits of W1 equal the independent golden files.

W1 (the reference fixture of Appendix C: Forge World, three objects) is built by the independent fixture builder,
imported through File > Import with the REAL provider, edited in Blender and exported through File > Export. The bytes
that come out must equal the files the independent builder writes for the same edit (``w1_E1``, ``w1_E2``, ``w1_E2b``,
``w1_E3``) and the file SHA-256 numbers printed in SPEC Appendix C.3:

* E1  move ``1 - Block, 1x1`` by +1.0 in x                       -> ``w1_E1``  (x cell 524,288 -> 526,473)
* E2  add ``Block, 1x1`` at the centre of cells (1, 2, 3), the rotation gate on, rotated so that its forward (local +Y)
      points along world +X (``rotation_euler.z = -pi/2``)         -> ``w1_E2``  (angle 8192; quota row 70 placed 2 -> 3)
* E2b the same unrotated: forward (0, 1, 0) is a yaw of +pi/2    -> ``w1_E2b`` (angle 12288)
* E3  delete ``5 - Kill Boundary``                                -> ``w1_E3``  (quota row 61 placed 1 -> 0)

Each edit starts from a fresh import. Also: the unedited W1 comes back byte for byte (passthrough); E2 is repeated with
the stand-in palette library linked (the type then comes from the linked collection's ``.name``) and the edits survive
re-import. The expected bytes never come from ``mvarlib``.
"""
import hashlib
import math
import os
import sys

import bpy

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common  # noqa: E402
import real_data as rd  # noqa: E402
from bl_common import check, check_eq  # noqa: E402

ID = "b18"
TITLE = "end-to-end anchor: Blender edits of W1 equal the independent builder's E1/E2/E2b/E3 files"
NEEDS_STUB = False
REAL_ONLY = True

# SPEC Appendix C.3 (salted_be32 flavour): the file SHA-256 of the goldens
SHA256 = {
    "w1_minimal": "902d952fdce8b5830e53e96e0ad45926554e1a9e617f753f39bb58a5fd2344e4",
    "w1_E1": "32296dac74f00aea41f16859052f27a5230c29a556ddcc3b3edcefb19b64cf32",
    "w1_E2": "9055a41eb6690c26d53b701a208c4531a7c239c474b7911147399a460b78a08d",
    "w1_E2b": "851d42b8dc49182db799d0ee573dc30531be7992944e8406d6f6fc2adabb3fdd",
    "w1_E3": "6e3f948488c5a9ed4d0c0febdcb859738d8d28571860566ab4d0d2081ae4058f",
}
# W1 of Appendix C.1: bounds and the axis widths (20, 21, 19)
BOUNDS = (-240.0, 240.0, -345.0, 345.0, -70.0, 70.0)
AXIS_BITS = (20, 21, 19)


def cell_centre_position(cells):
    """World position of the centre of position cells ``cells`` on W1's axes (the independent codec of the builder)."""
    return tuple(rd.cell_centre(cells[k], AXIS_BITS[k], BOUNDS[2 * k], BOUNDS[2 * k + 1]) for k in range(3))


def import_w1(env, data):
    result, path = env.import_bytes(data, "w1_minimal.mvar")
    check_eq(result, {'FINISHED'}, "import of W1")
    objs = dict((o["mj_slot"], o) for o in env.forge_objects() if "mj_slot" in o)
    check_eq(sorted(objs), [1, 5, 650], "W1 has objects in slots 1, 5 and 650")
    check_eq(objs[1].name, "1 - Block, 1x1")
    check_eq(objs[5].name, "5 - Kill Boundary")
    return objs, path


def export_bytes(env, name):
    result, path = env.export_to(name)
    check_eq(result, {'FINISHED'}, "export %s: %r\n%s" % (name, result, env.report_text()[:2000]))
    with open(path, "rb") as fh:
        return fh.read()


def check_golden(name, produced, expected):
    check_eq(hashlib.sha256(expected).hexdigest(), SHA256[name], "%s: the independent builder's file is the one the spec prints" % name)
    check(produced == expected, "%s: the exported bytes differ from the independent golden file at byte(s) %s (lengths %d / %d)"
          % (name, rd.changed_bytes(produced, expected)[:8] if len(produced) == len(expected) else "-", len(produced), len(expected)))
    print("B-18 %s: exported bytes == independent %s (%d bytes, sha256 %s...)" % (name, name, len(produced), SHA256[name][:16]))


def add_block(env, rotation_z):
    """Add > Forge Object > Block, 1x1 at the centre of cells (1, 2, 3); the rotation gate on."""
    bpy.context.scene.forge.allowUnverifiedRotation = True
    check_eq(bpy.ops.forge.add_object(objectType="Block, 1x1"), {'FINISHED'})
    block = bpy.context.active_object
    check("mj_slot" not in block, "a new object claims no slot")
    block.location = cell_centre_position((1, 2, 3))
    block.rotation_euler = (0.0, 0.0, rotation_z)
    bpy.context.view_layer.update()
    return block


def run_real(env):
    w1 = rd.fixture("w1_minimal")
    check_eq(hashlib.sha256(w1).hexdigest(), SHA256["w1_minimal"], "W1 itself")
    expected = dict((name, rd.fixture(name)) for name in ("w1_E1", "w1_E2", "w1_E2b", "w1_E3"))

    # --- the unedited W1 comes back byte for byte -------------------------------------------------------------------------
    import_w1(env, w1)
    check(export_bytes(env, "b18_noop.mvar") == w1, "an unedited import -> export gives W1 back byte for byte (passthrough)")

    # --- E1: move slot 1 by +1.0 in x ------------------------------------------------------------------------------------------
    env.reset()
    objs, _path = import_w1(env, w1)
    objs[1].location.x += 1.0
    bpy.context.view_layer.update()
    produced = export_bytes(env, "b18_e1.mvar")
    check_golden("w1_E1", produced, expected["w1_E1"])

    # --- E2: add a Block, 1x1 at the centre of cells (1, 2, 3), forward along +X ---------------------------------------------
    for with_library in (False, True):
        env.reset()
        if with_library:
            env.use_library()                       # the linked collection's .name gives the type
        import_w1(env, w1)
        block = add_block(env, -math.pi / 2)
        check_eq(bool(block.instance_collection), with_library, "model-backed exactly when the library is linked")
        forward = block.matrix_world.col[1].xyz
        check(abs(forward.x - 1.0) < 1e-6 and abs(forward.y) < 1e-6, "forward (local +Y) points along world +X: %r" % (tuple(forward),))
        produced = export_bytes(env, "b18_e2_%s.mvar" % ("lib" if with_library else "nolib"))
        check_golden("w1_E2", produced, expected["w1_E2"])
        report = env.report_text()
        check("ADDED slot 0" in report or "ADDED slot - " in report or "ADDED" in report, report)
        check("W_ORIENTATION_UNVERIFIED" in report, "the unverified-rotation warning is in the report")

    # --- E2b: the same, unrotated: forward (0, 1, 0) is a yaw of +pi/2 (raw angle 12288) ----------------------------------------
    env.reset()
    import_w1(env, w1)
    add_block(env, 0.0)
    produced = export_bytes(env, "b18_e2b.mvar")
    check_golden("w1_E2b", produced, expected["w1_E2b"])

    # --- E3: delete slot 5 ----------------------------------------------------------------------------------------------------
    env.reset()
    objs, _path = import_w1(env, w1)
    env.mjolnir.remove_with_helpers(objs[5])
    produced = export_bytes(env, "b18_e3.mvar")
    check_golden("w1_E3", produced, expected["w1_E3"])
    check("REMOVED slot 5 " in env.report_text(), env.report_text())

    # --- the edits survive a re-import (a second scene) ---------------------------------------------------------------------
    with bl_common.fresh_scene("E3Reimport") as scene2:
        check_eq(env.import_file(os.path.join(env.tmp, "b18_e3.mvar")), {'FINISHED'})
        check_eq(sorted(o["mj_slot"] for o in scene2.objects if "mj_slot" in o), [1, 650], "E3 re-imported: slot 5 is gone")
    env.reset()
    import_w1(env, w1)
    objs = dict((o["mj_slot"], o) for o in env.forge_objects() if "mj_slot" in o)
    objs[1].location.x += 1.0
    block = add_block(env, -math.pi / 2)
    env.mjolnir.remove_with_helpers(objs[5])
    produced = export_bytes(env, "b18_all.mvar")
    with bl_common.fresh_scene("AllReimport") as scene2:
        check_eq(env.import_file(os.path.join(env.tmp, "b18_all.mvar")), {'FINISHED'})
        slots = dict((o["mj_slot"], o) for o in scene2.objects if "mj_slot" in o)
        check_eq(sorted(slots), [0, 1, 650], "E1 + E2 + E3 together: slots 0 (new), 1 and 650")
        moved = slots[1].matrix_world.translation
        check(abs(moved.x - 1.0002288818359375) < 1e-3, "slot 1 moved by +1.0: x = %r" % (moved.x,))
        new = slots[0].matrix_world.translation
        for got, want in zip(new, cell_centre_position((1, 2, 3))):
            check(abs(got - want) < 1e-4, "the added block is at the centre of cells (1, 2, 3): %r" % (tuple(new),))
        check_eq(slots[0].name.split(" - ", 1)[1].rsplit(".", 1)[0], "Block, 1x1")
    dec = rd.decode(produced)
    check_eq(sorted(dec["slots"]), [0, 1, 650], "independent decode of the combined edit")


if __name__ == "__main__":
    bl_common.main_module(sys.modules[__name__])
