"""B-07 (SPEC 9.4, 8.7 #1, 8.6, gate G6): export with a LINKED palette works; the type resolves per map.

The old export read ``instance_collection.name_full``, which carries the library suffix once the palette is linked
(``Block, 1x1 [Halo Reach.blend]``), so every export raised ``KeyError``. Now the type is the collection's ``.name``
(trailing ``.NNN`` removed) and the ids come from the library's per-map table.

* stub: the linked ``Block, 1x1`` reaches the provider as ``type_name == 'Block, 1x1'`` although ``name_full`` differs;
* real: the stand-in (or, with ``--real-library``, the real) library is linked and
    - W1 (Forge World) + a linked ``Block, 1x1`` exports and is folder 70, item 0 in the independent decode;
    - the real Breakneck file + a linked ``Block, 1x1`` (rotation gate and the quota option on) exports and is folder 63
      (the same display name has another id on another map: the table is per map, never a global name -> id dictionary);
    - ``Sprint`` (one id, 0x1E00, two internal names: ``sprint_spartan`` on Forge World, ``arm_sprint`` on Breakneck) resolves on
      both maps to folder 30, item 0: two fixtures that differ only in the map id each take a new ``Sprint``.
"""
import os
import sys

import bpy

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common  # noqa: E402
import real_data as rd  # noqa: E402
from bl_common import check, check_eq  # noqa: E402

ID = "b07"
TITLE = "export with a linked palette (name_full has the library suffix); ids resolve per map (Sprint, Block)"
NEEDS_STUB = True
SPRINT_ID = 0x1E00


# --- stub variant ---------------------------------------------------------------------------------------
def run(env):
    env.use_library()
    env.import_stub()
    block = [o for o in env.forge_objects() if o.get("mj_slot") == 1][0]
    coll = block.instance_collection
    check(coll is not None and coll.library is not None, "the palette is linked")
    check_eq(coll.name, "Block, 1x1")
    check(coll.name_full != coll.name and coll.name_full.startswith("Block, 1x1 ["), "name_full carries the library suffix: %r" % coll.name_full)
    result, _path = env.export_to("b07.mvar")
    check_eq(result, {'FINISHED'}, "export with a linked palette: %r" % (result,))
    objs = dict((o.slot, o) for o in env.stub.LAST_EXPORT[1])
    check_eq(objs[1].type_name, "Block, 1x1", "the bare .name reaches the provider")
    check_eq(objs[9].type_name, "Block, 1x1")
    check_eq(objs[2].type_name, "", "a model-less imported object hands its id (type_id_hint), not a name")
    check_eq(objs[2].type_id_hint, 0)


# --- real variant ---------------------------------------------------------------------------------------------
def add_linked_block(env, position, gate=True):
    bpy.context.scene.forge.allowUnverifiedRotation = gate
    check_eq(bpy.ops.forge.add_object(objectType="Block, 1x1"), {'FINISHED'})
    block = bpy.context.active_object
    check(block.instance_collection is not None and block.instance_collection.library is not None, "the new block is the linked model")
    check(block.instance_collection.name_full != block.instance_collection.name)
    block.location = position
    bpy.context.view_layer.update()
    return block


def sprint_fixture(map_id, name):
    """W1 with a ``Sprint`` (folder 30, item 0, quota row 30) in slot 2, on the map ``map_id``."""
    spec = rd.w1_spec(name, "W1 plus a Sprint on map id %d" % map_id)
    spec["header"]["map_id"] = map_id
    spec["body"]["map_id_2"] = map_id
    spec["slots"].append({"index": 2, "folder": 30, "item": 0, "pos": [600000, 700000, 200000]})
    spec["quotas"]["rows"]["30"] = [0, 4, 1]
    return rd.build_spec(spec)


def run_real(env):
    env.use_library()
    # --- W1 on Forge World: a linked Block, 1x1 is folder 70 -----------------------------------------------------------------
    result, _path = env.import_bytes(rd.fixture("w1_minimal"), "b07_w1.mvar")
    check_eq(result, {'FINISHED'})
    add_linked_block(env, (3.0, 4.0, 5.0))
    result, path = env.export_to("b07_w1_out.mvar")
    check_eq(result, {'FINISHED'}, "W1 + linked block: %r\n%s" % (result, env.report_text()[:1500]))
    dec = rd.decode(rd.read_bytes(path))
    added = dec["slots"][0]
    check_eq((added["folder"], added["item"]), (70, 0), "Forge World: Block, 1x1 is folder 70")
    check_eq(dec["quotas"][70], [0, 16, 3])

    # --- Sprint resolves on every map ----------------------------------------------------------------------------------------------
    for map_id, map_name, internal in ((rd.FORGE_WORLD, "Forge World", "sprint_spartan"), (rd.BREAKNECK, "Breakneck", "arm_sprint")):
        env.reset()
        env.use_library()
        result, _path = env.import_bytes(sprint_fixture(map_id, "sprint_%d" % map_id), "b07_sprint_%d.mvar" % map_id)
        check_eq(result, {'FINISHED'})
        st = env.state.get(bpy.context.scene)
        check_eq(st["map_name"], map_name)
        sprint = [o for o in env.forge_objects() if o["mj_slot"] == 2][0]
        check_eq(sprint.name, "2 - Sprint")
        check_eq(env.state.get(bpy.context.scene)["failed_slots"], [])
        result, path = env.export_to("b07_sprint_noop_%d.mvar" % map_id)
        check_eq(result, {'FINISHED'})
        bpy.context.scene.forge.allowUnverifiedRotation = True
        twin = env.mjolnir.create_forge_object(bpy.context, "Sprint")        # what a script or an older .blend makes: no model
        check_eq(twin["mj_type_name"], "Sprint")
        twin.location = (1.0, 2.0, 3.0)
        bpy.context.view_layer.update()
        result, path = env.export_to("b07_sprint_%d_out.mvar" % map_id)
        check_eq(result, {'FINISHED'}, "%s: a new Sprint: %r\n%s" % (map_name, result, env.report_text()[:1800]))
        dec = rd.decode(rd.read_bytes(path))
        new_slots = [i for i in dec["slots"] if i not in (1, 2, 5, 650)]
        check_eq(len(new_slots), 1, "%s: one new object" % map_name)
        new = dec["slots"][new_slots[0]]
        check_eq(((new["folder"] << 8) + new["item"]), SPRINT_ID, "%s: Sprint is id 0x1E00 (%s)" % (map_name, internal))
        check_eq(dec["quotas"][30], [0, 4, 2])
        print("B-07 %s: a new Sprint is id 0x%04X (internal name %s), quota row 30 (0, 4, 2)" % (map_name, SPRINT_ID, internal))

    # --- Breakneck: Block, 1x1 is folder 63 there, not 70 -----------------------------------------------------------------------------
    if not rd.real_available():
        print("NOTICE: the real map variant is absent (%s); the Breakneck half of B-07 is SKIPPED." % rd.real_mvar_path())
        raise bl_common.Skip("the real map variant is absent: %s" % rd.real_mvar_path())
    env.reset()
    env.use_library()
    check_eq(env.import_file(rd.real_mvar_path()), {'FINISHED'})
    add_linked_block(env, (2.0, 3.0, 4.0))
    result, path = env.export_to("b07_breakneck.mvar")
    check(isinstance(result, RuntimeError) and "E_QUOTA" in env.report_text(), "the finished map has no room for a block without the option: %r" % (result,))
    result, path = env.export_to("b07_breakneck.mvar", raise_quota_max=True)
    check_eq(result, {'FINISHED'}, "Breakneck + linked block: %r\n%s" % (result, env.report_text()[:1800]))
    dec = rd.decode(rd.read_bytes(path))
    added = dec["slots"][610]
    check_eq((added["folder"], added["item"]), (63, 0), "Breakneck: Block, 1x1 is folder 63 (Forge World: 70)")
    check_eq(dec["quotas"][63], [0, 1, 1])
    print("B-07 Breakneck: a new Block, 1x1 is folder 63 (Forge World: 70); the linked model's name_full carries the library suffix, .name does not")


if __name__ == "__main__":
    bl_common.main_module(sys.modules[__name__])
