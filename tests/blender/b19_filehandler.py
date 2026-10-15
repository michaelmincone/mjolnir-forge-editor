"""B-19 (SPEC 9.4, 8.12): the FileHandler registers and unregisters; the import operator takes ``directory`` + ``files``.

Actual drag and drop needs a GUI (9.6). Here: the handler class is registered with the operators named, its
``poll_drop`` accepts the 3D viewport only, a register/unregister cycle works, and
``import_scene.mjolnir_mvar(directory=..., files=[{"name": ...}])`` imports the first file (more than one is a
warning) while a preset ``filepath`` still works.

Real variant (``run_real``, G6): the same with two real fixtures (W1 and its golden edit E1); the embedded template of the scene
shows which file was imported.
"""
import os
import sys

import bpy

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common  # noqa: E402
import real_data as rd  # noqa: E402
from bl_common import FakeContext, check, check_eq  # noqa: E402

ID = "b19"
TITLE = "FileHandler registers/unregisters; import accepts directory + files"
NEEDS_STUB = True


class Area(object):
    def __init__(self, kind):
        self.type = kind


def check_handler_registration(env):
    io = env.io_ops
    handler = getattr(bpy.types, "MJOLNIR_FH_mvar", None)
    check(handler is not None, "FileHandler registered")
    check_eq(handler.bl_import_operator, "import_scene.mjolnir_mvar")
    check_eq(handler.bl_export_operator, "export_scene.mjolnir_mvar")
    check_eq(handler.bl_file_extensions, ".mvar")
    check_eq(handler.bl_label, "Halo Reach Map Variant")
    check(io.MJOLNIR_FH_mvar.poll_drop(FakeContext(area=Area("VIEW_3D"))), "drop accepted in the 3D viewport")
    check(not io.MJOLNIR_FH_mvar.poll_drop(FakeContext(area=Area("PROPERTIES"))), "not in other editors")
    check(not io.MJOLNIR_FH_mvar.poll_drop(FakeContext(area=None)), "not without an area")

    for _ in range(2):                                    # unregister / register cycles
        env.addon.unregister()
        check(getattr(bpy.types, "MJOLNIR_FH_mvar", None) is None, "unregistered")
        env.addon.register()
        check(getattr(bpy.types, "MJOLNIR_FH_mvar", None) is not None, "registered again")


def run(env):
    check_handler_registration(env)

    # directory + files (what a drop on the viewport delivers)
    first = env.write_template("dropped.mvar", b"DROP-1")
    env.write_template("second.mvar", b"DROP-2")
    result = bpy.ops.import_scene.mjolnir_mvar(directory=env.tmp + os.sep, files=[{"name": "dropped.mvar"}])
    check_eq(result, {'FINISHED'})
    check_eq(env.state.get(bpy.context.scene)["source_name"], "dropped.mvar")
    check_eq(env.stub.LAST_LOAD[0], b"DROP-1")
    with bl_common.capture_output() as out:
        result = bpy.ops.import_scene.mjolnir_mvar(directory=env.tmp, files=[{"name": "second.mvar"}, {"name": "dropped.mvar"}])
    check_eq(result, {'FINISHED'})
    check("Only the first of 2 files is imported." in out[0], out[0])
    check_eq(env.state.get(bpy.context.scene)["source_name"], "second.mvar")
    check_eq(env.stub.LAST_LOAD[0], b"DROP-2")
    result = bpy.ops.import_scene.mjolnir_mvar(filepath=first)
    check_eq(result, {'FINISHED'})
    check_eq(env.stub.LAST_LOAD[0], b"DROP-1", "filepath still works")
    check_eq(len(env.forge_objects()), 5, "each import replaced the previous one")


# =====================================================================================================
# the real-provider variant (G6)
# =====================================================================================================
def run_real(env):
    check_handler_registration(env)
    one, two = rd.fixture("w1_minimal"), rd.fixture("w1_E1")
    first = os.path.join(env.tmp, "dropped.mvar")
    second = os.path.join(env.tmp, "second.mvar")
    for path, data in ((first, one), (second, two)):
        with open(path, "wb") as fh:
            fh.write(data)
    scene = bpy.context.scene
    result = bpy.ops.import_scene.mjolnir_mvar(directory=env.tmp + os.sep, files=[{"name": "dropped.mvar"}])
    check_eq(result, {'FINISHED'})
    check_eq(env.state.get(scene)["source_name"], "dropped.mvar")
    check_eq(env.state.template_bytes(scene), one)
    with bl_common.capture_output() as out:
        result = bpy.ops.import_scene.mjolnir_mvar(directory=env.tmp, files=[{"name": "second.mvar"}, {"name": "dropped.mvar"}])
    check_eq(result, {'FINISHED'})
    check("Only the first of 2 files is imported." in out[0], out[0])
    check_eq(env.state.get(scene)["source_name"], "second.mvar")
    check_eq(env.state.template_bytes(scene), two)
    result = bpy.ops.import_scene.mjolnir_mvar(filepath=first)
    check_eq(result, {'FINISHED'})
    check_eq(env.state.template_bytes(scene), one, "filepath still works")
    check_eq(len(env.forge_objects()), 3, "each import replaced the previous one")


if __name__ == "__main__":
    bl_common.main_module(sys.modules[__name__])
