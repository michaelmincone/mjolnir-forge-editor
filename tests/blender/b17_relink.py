"""B-17 (SPEC 9.4, 8.6): a moved object library is relinked on load; export still works.

Link the (stand-in) library through an import, save the .blend (the library path is stored relative), move the
library file, point ``$MJOLNIR_LIBRARY`` at the new place and reopen the .blend: the ``load_post`` handler
repairs ``filepath`` and reloads, the models are back (``is_missing`` is false, the instanced collections hold
objects again) and the export works. When no library can be found the handler leaves the link alone, raises
nothing, and the export still works (it needs only the collection name). The handler never links anything new.

Real variant (``run_real``, G6): the same with W1 and the REAL library: after the relink, and with the library gone, the
export gives W1 back byte for byte (the type comes from the bare ``.name`` of the instanced collection); every spelling of the
duplicate suffix (``Block, 1x1``, ``.001``, ``.002``) exports the same file; a moved ``.blend`` whose library is found again
exports an edit (a moved block) correctly.
"""
import os
import shutil
import sys

import bpy

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common  # noqa: E402
import real_data as rd  # noqa: E402
from bl_common import check, check_eq  # noqa: E402

ID = "b17"
TITLE = "moved library relinked on load_post; export still works"
NEEDS_STUB = True


def block_object():
    return [o for o in bpy.context.scene.objects if o.get("mj_slot") == 1][0]


def check_library_lookup(env):
    # where the library is looked for: preference, then $MJOLNIR_LIBRARY, then <package>/Resources
    pal = env.palette

    class Prefs(object):
        def __init__(self, path):
            self.library_path = path
            self.protected_folders = ""

    folder = os.path.join(env.tmp, "pref-folder")
    os.makedirs(folder)
    os.environ[bl_common.ENV_LIBRARY] = os.path.join(env.tmp, "from-env", "Halo Reach.blend")
    with bl_common.patched(pal, "_addon_preferences", lambda: Prefs(os.path.join(env.tmp, "from-pref", "x.blend"))):
        check_eq(pal.library_path(), os.path.join(env.tmp, "from-pref", "x.blend"), "the preference wins")
    with bl_common.patched(pal, "_addon_preferences", lambda: Prefs(folder)):
        check_eq(pal.library_path(), os.path.join(folder, "Halo Reach.blend"), "a folder gets the file name appended")
    with bl_common.patched(pal, "_addon_preferences", lambda: Prefs("")):
        check_eq(pal.library_path(), os.path.join(env.tmp, "from-env", "Halo Reach.blend"), "empty preference: the environment")
    with bl_common.patched(pal, "_addon_preferences", lambda: None):
        check_eq(pal.library_path(), os.path.join(env.tmp, "from-env", "Halo Reach.blend"), "no preferences available")
    del os.environ[bl_common.ENV_LIBRARY]
    package_default = pal.library_path()
    check(package_default.endswith(os.path.join("Resources", "Halo Reach.blend")), package_default)
    check_eq(os.path.dirname(os.path.dirname(package_default)), os.path.dirname(os.path.abspath(pal.__file__)),
             "<package>/Resources/Halo Reach.blend")
    check(not os.path.isfile(package_default) or not env.addon_name.startswith("bl_ext."),
          "the default package carries no library (only the dev loop / --with-library does)")


def check_handler(env):
    # the handler is persistent and registered once
    handlers = [f for f in bpy.app.handlers.load_post if getattr(f, "__module__", "").startswith(env.addon_name)]
    check_eq([f.__name__ for f in handlers], ["_on_load"])
    check(hasattr(handlers[0], "_bpy_persistent"), "persistent")


def run(env):
    stub = env.stub
    lib_a = os.path.join(env.tmp, "libA")
    lib_b = os.path.join(env.tmp, "libB")
    os.makedirs(lib_a)
    os.makedirs(lib_b)
    path_a = os.path.join(lib_a, "Halo Reach.blend")
    shutil.copy(env.standin_library(), path_a)           # a copy: the stand-in itself stays where it is
    env.use_library(path_a)
    env.import_stub()
    obj = block_object()
    check(obj.instance_collection is not None and obj.instance_collection.library is not None, "linked model")
    check_eq(len(bpy.data.libraries), 1)
    blend_dir = os.path.join(env.tmp, "scenes")
    os.makedirs(blend_dir)
    blend = os.path.join(blend_dir, "relink.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend, check_existing=False)

    # the library moves
    path_b = os.path.join(lib_b, "Halo Reach.blend")
    shutil.move(path_a, path_b)
    env.use_library(path_b)
    bpy.ops.wm.open_mainfile(filepath=blend)
    lib = bpy.data.libraries[0]
    check(not lib.is_missing, "the handler repaired the library path: %s" % lib.filepath)
    check_eq(os.path.realpath(bpy.path.abspath(lib.filepath)), os.path.realpath(path_b))
    obj = block_object()
    check(len(obj.instance_collection.objects) > 0, "the instanced collection holds its objects again")
    result, path = env.export_to("b17.mvar")
    check_eq(result, {'FINISHED'}, "export after the relink")
    eo = [o for o in stub.LAST_EXPORT[1] if o.slot == 1][0]
    check_eq(eo.type_name, "Block, 1x1", "the type is the bare .name, not .name_full")
    check_eq(len(bpy.data.libraries), 1, "the handler links nothing new")

    # no library anywhere: nothing is repaired, nothing raises, export still resolves the name
    os.remove(path_b)
    env.use_library(os.path.join(env.tmp, "nowhere", "Halo Reach.blend"))
    bpy.ops.wm.open_mainfile(filepath=blend)
    lib = bpy.data.libraries[0]
    check(lib.is_missing, "still missing: no replacement exists")
    obj = block_object()
    result, path = env.export_to("b17_missing.mvar")
    check_eq(result, {'FINISHED'}, "export with a missing library")
    check_eq([o for o in stub.LAST_EXPORT[1] if o.slot == 1][0].type_name, "Block, 1x1")

    check_library_lookup(env)

    # --- the duplicate suffix: a second collection called "Block, 1x1" is "Block, 1x1.001" in Blender, and the type
    # that reaches the provider is always the bare name (SPEC 8.5: ``.name`` with a trailing ``.NNN`` removed)
    env.reset()
    env.import_stub()
    obj = block_object()
    mj = env.mjolnir
    variants = [bpy.data.collections.new("Block, 1x1") for _ in range(3)]
    check_eq([c.name for c in variants], ["Block, 1x1", "Block, 1x1.001", "Block, 1x1.002"], "Blender's own suffixes")
    for coll in variants:
        obj.instance_collection = coll
        obj.instance_type = 'COLLECTION'
        check_eq(mj.forge_type_name(obj), "Block, 1x1", "type of %r" % coll.name)
        result, path = env.export_to("b17_suffix.mvar")
        check_eq(result, {'FINISHED'}, "export with the instance collection %r" % coll.name)
        eo = [o for o in stub.LAST_EXPORT[1] if o.slot == 1][0]
        check_eq(eo.type_name, "Block, 1x1", "type_name handed to the provider for %r" % coll.name)
    strip = mj.strip_duplicate_suffix
    for name, expected in (("Block, 1x1.001", "Block, 1x1"), ("Block, 1x1.1234", "Block, 1x1"),
                           ("Block, 1x1", "Block, 1x1"), ("Block, 1x1.01", "Block, 1x1.01"),
                           ("Block, 1x1.5", "Block, 1x1.5"), ("Sniper.001.002", "Sniper.001"),
                           ("Block.001, 1x1", "Block.001, 1x1"), (".001", "")):
        check_eq(strip(name), expected, "strip_duplicate_suffix(%r)" % name)
    obj.instance_collection = None
    obj.instance_type = 'NONE'
    check_eq(mj.forge_type_name(obj), "", "no collection and no chosen type: no name")
    obj["mj_type_name"] = "Assault Rifle"
    check_eq(mj.forge_type_name(obj), "Assault Rifle", "a model-less object names its type itself")

    check_handler(env)


# =====================================================================================================
# the real-provider variant (G6)
# =====================================================================================================
def run_real(env):
    w1 = rd.fixture("w1_minimal")
    lib_a = os.path.join(env.tmp, "libA")
    lib_b = os.path.join(env.tmp, "libB")
    os.makedirs(lib_a)
    os.makedirs(lib_b)
    path_a = os.path.join(lib_a, "Halo Reach.blend")
    shutil.copy(env.standin_library(), path_a)          # a copy of the STAND-IN, always: even with --real-library the game library is never copied
    env.use_library(path_a)
    result, _ = env.import_bytes(w1, "b17_w1.mvar")
    check_eq(result, {'FINISHED'})
    obj = block_object()
    check(obj.instance_collection is not None and obj.instance_collection.library is not None, "linked model")
    check_eq(len(bpy.data.libraries), 1)
    blend_dir = os.path.join(env.tmp, "scenes")
    os.makedirs(blend_dir)
    blend = os.path.join(blend_dir, "relink.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend, check_existing=False)
    result, path = env.export_to("b17_before.mvar")
    check_eq(result, {'FINISHED'})
    check(rd.read_bytes(path) == w1, "export with the library in place: passthrough")

    # the library moves
    path_b = os.path.join(lib_b, "Halo Reach.blend")
    shutil.move(path_a, path_b)
    env.use_library(path_b)
    bpy.ops.wm.open_mainfile(filepath=blend)
    lib = bpy.data.libraries[0]
    check(not lib.is_missing, "the handler repaired the library path: %s" % lib.filepath)
    check_eq(os.path.realpath(bpy.path.abspath(lib.filepath)), os.path.realpath(path_b))
    obj = block_object()
    check(len(obj.instance_collection.objects) > 0, "the instanced collection holds its objects again")
    result, path = env.export_to("b17_relinked.mvar")
    check_eq(result, {'FINISHED'}, "export after the relink: %r" % (result,))
    check(rd.read_bytes(path) == w1, "export after the relink: passthrough, byte for byte")
    check_eq(len(bpy.data.libraries), 1, "the handler links nothing new")
    obj.location.x += 1.0                                # an edit through the repaired link lands in the file
    result, path = env.export_to("b17_relinked_edit.mvar")
    check_eq(result, {'FINISHED'})
    check(rd.read_bytes(path) == rd.fixture("w1_E1"), "the edit made after the relink is the golden E1")

    # no library anywhere: nothing is repaired, nothing raises, the export still resolves the type (the id is in the template)
    os.remove(path_b)
    env.use_library(os.path.join(env.tmp, "nowhere", "Halo Reach.blend"))
    bpy.ops.wm.open_mainfile(filepath=blend)
    lib = bpy.data.libraries[0]
    check(lib.is_missing, "still missing: no replacement exists")
    result, path = env.export_to("b17_missing.mvar")
    check_eq(result, {'FINISHED'}, "export with a missing library")
    check(rd.read_bytes(path) == w1, "export with a missing library: passthrough")

    check_library_lookup(env)

    # --- the duplicate suffix: every spelling of the collection name exports the same file --------------------------------------------------
    env.reset()
    env.import_bytes(w1, "b17_suffix.mvar")
    obj = block_object()
    mj = env.mjolnir
    variants = [bpy.data.collections.new("Block, 1x1") for _ in range(3)]
    check_eq([c.name for c in variants], ["Block, 1x1", "Block, 1x1.001", "Block, 1x1.002"], "Blender's own suffixes")
    for coll in variants:
        obj.instance_collection = coll
        obj.instance_type = 'COLLECTION'
        check_eq(mj.forge_type_name(obj), "Block, 1x1", "type of %r" % coll.name)
        result, path = env.export_to("b17_suffix_out.mvar")
        check_eq(result, {'FINISHED'}, "export with the instance collection %r" % coll.name)
        check(rd.read_bytes(path) == w1, "the type 'Block, 1x1' is recognised for %r: passthrough" % coll.name)
        eo = [o for o in env.io_ops.collect_export_objects(bpy.context.scene).objects if o.slot == 1][0]
        check_eq(eo.type_name, "Block, 1x1", "type_name handed to the provider for %r" % coll.name)
    # a collection of ANOTHER type on a block changes its type: a retarget to a class the file knows is a real edit
    other = bpy.data.collections.new("Block, 1x2")
    obj.instance_collection = other
    check_eq(mj.forge_type_name(obj), "Block, 1x2")
    result, path = env.export_to("b17_retarget.mvar")
    check_eq(result, {'FINISHED'}, "a retarget to a type of the same class is written: %r" % (result,))
    check("RETARGETED slot 1 \"1 - Block, 1x1\" Block, 1x1 -> Block, 1x2" in env.report_text(), env.report_text()[:1500])
    after = rd.decode(rd.read_bytes(path))
    check_eq((after["slots"][1]["folder"], after["slots"][1]["item"]), (0x4605 >> 8, 0x4605 & 255), "slot 1 is a Block, 1x2 now (0x4605)")
    strip = mj.strip_duplicate_suffix
    for name, expected in (("Block, 1x1.001", "Block, 1x1"), ("Block, 1x1.1234", "Block, 1x1"),
                           ("Block, 1x1", "Block, 1x1"), ("Block, 1x1.01", "Block, 1x1.01"),
                           ("Block, 1x1.5", "Block, 1x1.5"), ("Sniper.001.002", "Sniper.001"),
                           ("Block.001, 1x1", "Block.001, 1x1"), (".001", "")):
        check_eq(strip(name), expected, "strip_duplicate_suffix(%r)" % name)
    obj.instance_collection = None
    obj.instance_type = 'NONE'
    check_eq(mj.forge_type_name(obj), "", "no collection and no chosen type: no name")
    obj["mj_type_name"] = "Assault Rifle"
    check_eq(mj.forge_type_name(obj), "Assault Rifle", "a model-less object names its type itself")
    check_handler(env)


if __name__ == "__main__":
    bl_common.main_module(sys.modules[__name__])
