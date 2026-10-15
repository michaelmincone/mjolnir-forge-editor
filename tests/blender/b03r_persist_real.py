"""B-03 with ``--provider real`` (SPEC 9.4, 8.3, gate G6): the imported file lives in the .blend; a FRESH Blender process exports.

    import -> (edit) -> save_as_mainfile -> open the .blend in a SECOND Blender process (add-on enabled at startup, real
    provider) -> File > Export there

* Breakneck (the real file, 59,392 bytes in a scene custom property, 610 objects): a no-op export from the fresh process
  reproduces the original bytes exactly; with one object moved before saving, the fresh process writes exactly the file
  that the first process writes (and the independent walker finds only that object's position bits changed).
* W1 (the independent fixture): the source file is DELETED before the second process starts, so nothing depends on a
  path; the fresh process still exports the golden edit (E1: ``+1.0`` in x) byte for byte.
* In both processes ``bpy.app.driver_namespace`` holds no key of this add-on. The identity props, the baselines
  (``mj_pose`` / ``mj_base``) and the labels survive the save; reopening inside the first process works too.
"""
import json
import os
import subprocess
import sys

import bpy
from mathutils import Vector

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common  # noqa: E402
import real_data as rd  # noqa: E402
from bl_common import check, check_eq  # noqa: E402

ID = "b03r"
TITLE = "import, save, reopen in a fresh process, export from the embedded template (real provider)"
NEEDS_STUB = False
REAL_ONLY = True

W1_MOVE_X = 1.0
REAL_MOVE = (1.0, -0.5, 0.25)


def forbidden_keys():
    return [k for k in bpy.app.driver_namespace.keys()
            if str(k).startswith(("mjolnir", "gtIndexToLabel", "persist_vars"))]


def imported(scene):
    return sorted((o for o in scene.objects if o.get("isForgeObject") and "mj_slot" in o), key=lambda o: o["mj_slot"])


def run_child(env, blend, out_json, *args):
    cmd = [bpy.app.binary_path, "-b", "--factory-startup", "--python-exit-code", "1", "--addons", env.addon_name,
           blend, "--python", os.path.abspath(__file__), "--", "--child", out_json] + list(args)
    proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True, env=dict(os.environ))
    check_eq(proc.returncode, 0, "child Blender exit status; output:\n" + proc.stdout[-4000:])
    with open(out_json, "r") as fh:
        return json.load(fh)


def run_real(env):
    env.use_library()                               # the stand-in is linked; the child finds it through $MJOLNIR_LIBRARY
    # ---------------------------------------------------------------- W1: no dependency on a path -----------------------------
    w1 = rd.fixture("w1_minimal")
    result, source = env.import_bytes(w1, "b03r_w1.mvar")
    check_eq(result, {'FINISHED'})
    check_eq(forbidden_keys(), [], "driver_namespace in the first process")
    scene = bpy.context.scene
    block = [o for o in imported(scene) if o["mj_slot"] == 1][0]
    block.location.x += W1_MOVE_X
    bpy.context.view_layer.update()
    blend = os.path.join(env.tmp, "b03r_w1.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend, check_existing=False)
    os.remove(source)                               # the source file is gone: the template must come out of the .blend
    check(not os.path.exists(source))
    report = run_child(env, blend, os.path.join(env.tmp, "b03r_w1.json"), "w1", env.tmp)
    check_eq(report["forbidden_keys"], [], "driver_namespace in the fresh process")
    check_eq(report["template_equal"], True, "the template bytes arrive unchanged")
    check_eq(report["objects"], 3)
    check_eq(report["identity_survived"], [True] * 3, "mj_* props, baselines and labels survive save + open")
    check_eq(report["labels"], ["SCALE", "Kill Boundary", "Spawn"])
    with open(report["output"], "rb") as fh:
        child_out = fh.read()
    golden = rd.fixture("w1_E1")
    check(child_out == golden, "the fresh process exported W1 + E1 byte for byte (golden w1_E1), no source file on disk")
    print("B-03r W1: the source file was deleted; the fresh process exported the golden E1 (%d bytes)" % len(child_out))
    # reopening inside this process works as well
    bpy.ops.wm.open_mainfile(filepath=blend)
    scene = bpy.context.scene
    ok, why = env.state.verify_template(scene)
    check(ok, "template verifies after open_mainfile: %s" % why)
    result, path = env.export_to("b03r_w1_inproc.mvar")
    check_eq(result, {'FINISHED'}, "export after reopening in the same process")
    with open(path, "rb") as fh:
        check(fh.read() == golden, "the reopened scene exports the golden E1 too")

    # ---------------------------------------------------------------- Breakneck: a big template, moved object -------------------
    if not rd.real_available():
        print("NOTICE: the real map variant is absent (%s); the Breakneck half of B-03r is SKIPPED." % rd.real_mvar_path())
        raise bl_common.Skip("the real map variant is absent: %s" % rd.real_mvar_path())
    env.reset()
    env.use_library()
    original = rd.real_bytes()
    fingerprint = rd.file_fingerprint(rd.real_mvar_path())
    check_eq(env.import_file(rd.real_mvar_path()), {'FINISHED'})
    scene = bpy.context.scene
    check_eq(len(imported(scene)), rd.REAL_OBJECTS)
    blend_noop = os.path.join(env.tmp, "b03r_real_noop.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_noop, check_existing=False)
    report = run_child(env, blend_noop, os.path.join(env.tmp, "b03r_real_noop.json"), "real-noop", env.tmp)
    check_eq(report["template_equal"], True, "the 59,392-byte template survives save + open")
    check_eq(report["objects"], rd.REAL_OBJECTS)
    check_eq(report["identity_survived"], [True] * rd.REAL_OBJECTS)
    with open(report["output"], "rb") as fh:
        child_noop = fh.read()
    check(child_noop == original, "a no-op export from the fresh process reproduces the original 59,392 bytes (passthrough)")
    print("B-03r Breakneck: no-op export from the fresh process == the original (%d bytes)" % len(child_noop))

    # one object moved before saving: the fresh process writes what this process writes
    env.reset()
    env.use_library()
    check_eq(env.import_file(rd.real_mvar_path()), {'FINISHED'})
    scene = bpy.context.scene
    objs = imported(scene)
    prop = [o for o in objs if o.name.endswith("Cover, Large")][0]
    slot = prop["mj_slot"]
    prop.location = Vector(prop.location) + Vector(REAL_MOVE)
    bpy.context.view_layer.update()
    result, here_path = env.export_to("b03r_real_here.mvar")
    check_eq(result, {'FINISHED'}, "export in the first process: %r" % (result,))
    here = rd.read_bytes(here_path)
    blend_moved = os.path.join(env.tmp, "b03r_real_moved.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_moved, check_existing=False)
    report = run_child(env, blend_moved, os.path.join(env.tmp, "b03r_real_moved.json"), "real-moved", env.tmp)
    with open(report["output"], "rb") as fh:
        there = fh.read()
    check(there == here, "the fresh process writes exactly the file the first process writes (moved slot %d)" % slot)
    check(there != original and len(there) == rd.REAL_SIZE)
    dec_old, dec_new = rd.decode(original), rd.decode(there)
    check_eq(rd.slots_equal(dec_old, dec_new, ignore=(slot,)), [], "only slot %d changed" % slot)
    check_eq(rd.fields_differing(dec_old["slots"][slot], dec_new["slots"][slot]), ["pos"], "only its position")
    check_eq(rd.read_bytes(rd.real_mvar_path()), original, "the original is untouched")
    check_eq(rd.file_fingerprint(rd.real_mvar_path()), fingerprint)
    print("B-03r Breakneck: slot %d moved before saving; the fresh process wrote the identical file (%d bytes, position bits only)"
          % (slot, len(there)))


def child():
    """Runs inside the second Blender process (the .blend is already open, the add-on enabled at startup)."""
    argv = sys.argv[sys.argv.index("--") + 1:]
    out_json, kind, tmp = argv[1], argv[2], argv[3]
    addon_name = os.environ.get(bl_common.ENV_ADDON, bl_common.DEFAULT_ADDON)
    state = __import__(addon_name + ".state", fromlist=["state"])
    provider = __import__(addon_name + ".provider", fromlist=["provider"])
    check(provider.get_provider().__name__.endswith("mvarlib.api"), "the real provider is active: %r" % provider.get_provider())
    scene = bpy.context.scene
    report = {"forbidden_keys": forbidden_keys()}
    template = state.template_bytes(scene)
    if kind == "w1":
        report["template_equal"] = template == rd.fixture("w1_minimal")
        report["labels"] = list(state.get(scene)["labels"])
    else:
        report["template_equal"] = template == rd.real_bytes()
    objs = imported(scene)
    report["objects"] = len(objs)
    report["identity_survived"] = [
        bool(len(bytes(o["mj_raw"])) > 0 and int(o["mj_raw_bits"]) > 0 and len(o["mj_pose"]) == 9 and len(o["mj_base"]) == 9
             and o["mj_name"] == o.name) for o in objs]
    target = os.path.join(tmp, "b03r_child_%s.mvar" % kind)
    result = bpy.ops.export_scene.mjolnir_mvar(filepath=target)
    check_eq(result, {'FINISHED'}, "export in the fresh process")
    report["output"] = target
    with open(out_json, "w") as fh:
        json.dump(report, fh)


if __name__ == "__main__":
    if "--child" in sys.argv:
        child()
    else:
        bl_common.main_module(sys.modules[__name__])
