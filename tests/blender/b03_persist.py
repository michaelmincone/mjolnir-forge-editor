"""B-03 (SPEC 9.4, 8.3): the imported file lives in the .blend; export works in a fresh Blender process.

Import (stub provider), ``save_as_mainfile``, open the saved file in a SECOND Blender process (add-on
enabled at startup, stub provider) and export there: the embedded template bytes reach the provider
unchanged and the exported file equals them (the stub returns the template). No path dependency (the
source file is deleted before the child runs) and ``bpy.app.driver_namespace`` holds no key of this
add-on (a fresh Blender already holds about 74 unrelated entries). ``b03r_persist_real.py`` repeats it
with ``--provider real`` in G6.
"""
import hashlib
import json
import os
import subprocess
import sys

import bpy

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common  # noqa: E402
from bl_common import check, check_eq  # noqa: E402

ID = "b03"
TITLE = "import, save, reopen in a fresh process, export from the embedded template"
NEEDS_STUB = True
REAL_VARIANT = "b03r"                   # under --provider real this test IS b03r_persist_real.py (SPEC 11 G6)

TEMPLATE = bytes((i * 7 + 3 + (i >> 8)) % 256 for i in range(29481))       # the size of the spec's plain4 example, NULs included


def forbidden_keys():
    return [k for k in bpy.app.driver_namespace.keys()
            if str(k).startswith(("mjolnir", "gtIndexToLabel", "persist_vars"))]


def run(env):
    path = env.write_template("b03.mvar", TEMPLATE)
    result, _ = env.import_stub(path=path)
    check_eq(result, {'FINISHED'})
    check_eq(forbidden_keys(), [], "driver_namespace in the first process")
    blend = os.path.join(env.tmp, "b03.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend, check_existing=False)
    os.remove(path)                                   # no dependency on the source file
    out = os.path.join(env.tmp, "b03_child.json")
    cmd = [bpy.app.binary_path, "-b", "--factory-startup", "--python-exit-code", "1", "--addons", env.addon_name,
           blend, "--python", os.path.abspath(__file__), "--", "--child", out, env.tmp]
    proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True, env=dict(os.environ))
    check_eq(proc.returncode, 0, "child Blender exit status; output:\n" + proc.stdout[-3000:])
    with open(out, "r") as fh:
        report = json.load(fh)
    check_eq(report["template_equal"], True, "template bytes in the fresh process")
    check_eq(report["objects"], 5)
    check_eq(report["identity_survived"], [True] * 5, "mj_* identity props in the fresh process")
    check_eq(report["export_equal"], True, "exported file equals the template")
    check_eq(report["labels"], ["SCALE", "Kill Boundary", "Spawn"])
    check_eq(report["forbidden_keys"], [])
    check_eq(report["last_export_objects"], 5)
    check_eq(report["pose_exact"], [True] * 5, "the baseline survives save + open: an untouched export hands the records' poses back")
    # the parent's own file is untouched by the child
    bpy.ops.wm.open_mainfile(filepath=blend)          # reopening in-process keeps the state as well
    scene = bpy.context.scene
    check_eq(bytes(scene["mjolnir_template"]), TEMPLATE)
    check_eq(env.state.get(scene)["template_sha256"], hashlib.sha256(TEMPLATE).hexdigest())
    check(env.addon_name in sys.modules, "add-on still loaded after open_mainfile")


def child():
    """Runs inside the second Blender process (the .blend is already open)."""
    argv = sys.argv[sys.argv.index("--") + 1:]
    out, tmp = argv[1], argv[2]
    addon_name = os.environ.get(bl_common.ENV_ADDON, bl_common.DEFAULT_ADDON)
    state = __import__(addon_name + ".state", fromlist=["state"])
    provider = __import__(addon_name + ".provider", fromlist=["provider"])
    stub = bl_common._import_stub()
    provider.set_provider(stub)
    scene = bpy.context.scene
    report = {"forbidden_keys": forbidden_keys()}
    report["template_equal"] = bytes(scene["mjolnir_template"]) == TEMPLATE
    report["objects"] = sum(1 for o in scene.objects if o.get("isForgeObject"))
    report["labels"] = list(state.get(scene)["labels"])
    records = dict((r.slot, r) for r in stub.CANNED.objects)
    survived = []
    for obj in scene.objects:                         # the identity token and the other custom props survive save + open
        if obj.get("isForgeObject"):
            rec = records[obj["mj_slot"]]
            survived.append(bytes(obj["mj_raw"]) == rec.raw and obj["mj_raw_bits"] == rec.raw_bits
                            and obj["mj_parent_slot"] == rec.parent_slot and obj["mj_physics"] == rec.physics
                            and obj["mj_name"] == obj.name and obj.forge.objectType == rec.type_id
                            and tuple(obj["mj_pose"]) == tuple(rec.position) + tuple(rec.forward) + tuple(rec.up)
                            and len(obj["mj_base"]) == 9)
    report["identity_survived"] = survived
    target = os.path.join(tmp, "b03_child_out.mvar")
    result = bpy.ops.export_scene.mjolnir_mvar(filepath=target)
    check_eq(result, {'FINISHED'}, "export in the fresh process")
    with open(target, "rb") as fh:
        report["export_equal"] = fh.read() == TEMPLATE
    report["last_export_objects"] = len(stub.LAST_EXPORT[1])
    # nothing was touched in this process: every object hands the record's own pose back, exactly
    report["pose_exact"] = [(tuple(eo.position), tuple(eo.forward), tuple(eo.up)) ==
                            (tuple(records[eo.slot].position), tuple(records[eo.slot].forward), tuple(records[eo.slot].up))
                            for eo in stub.LAST_EXPORT[1]]
    with open(out, "w") as fh:
        json.dump(report, fh)


if __name__ == "__main__":
    if "--child" in sys.argv:
        child()
    else:
        bl_common.main_module(sys.modules[__name__])
