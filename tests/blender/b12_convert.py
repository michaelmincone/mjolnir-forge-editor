"""B-12 (SPEC 9.4, 8.7 #12): Convert To Forge Object on a plain Blender object cannot export (E_OBJ_NO_TYPE).

The old add-on exported such an object as type 0 (an Assault Rifle). Now the glue reports ``E_OBJ_NO_TYPE`` and
nothing is written; converting back makes the export work again. The context-menu item reads the active object.

Also the other refusals the glue makes itself (the library is not asked, or its answer is not used): no
template, tampered template, mirrored transform, no target, target = the imported file (also through a symlink),
target in a protected folder. Each one writes the report and no file.

Real variant (``run_real``, G6): the same conversion with the REAL library on W1: the refusal names the object and writes no
file, converting back exports W1 byte for byte (the cube is not exported), and an object added from the Add menu without a
library names its type and is accepted (with the rotation gate, as every new object). The glue's other refusals run against the
real library in ``b16_refusals.py``.
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

ID = "b12"
TITLE = "Convert To Forge Object on a plain object -> E_OBJ_NO_TYPE"
NEEDS_STUB = True


def run(env):
    stub = env.stub
    env.import_stub()
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.active_object
    for obj in bpy.context.selected_objects:
        obj.select_set(obj is cube)

    # the context menu item
    ui = bl_common.draw_with_fake(env.mjolnir.convertForgeMenuItem, bl_common.FakeContext(selected_objects=[cube]))
    check_eq([e[2] for e in ui.operators()], ["Convert To Forge Object"])
    forge_ui = bl_common.draw_with_fake(env.mjolnir.convertForgeMenuItem,
                                        bl_common.FakeContext(selected_objects=[env.forge_objects()[0]]))
    check_eq([e[2] for e in forge_ui.operators()], ["Convert To Blender Object"])
    nothing = bl_common.draw_with_fake(env.mjolnir.convertForgeMenuItem, bl_common.FakeContext())
    check_eq(nothing.operators(), [], "no active object: nothing drawn, no exception")

    result = bpy.ops.object.convert_forge(isForgeObject=True)
    check_eq(result, {'FINISHED'})
    check(cube.get("isForgeObject"), "converted")
    result, path = env.export_to("b12.mvar")
    check(isinstance(result, RuntimeError), "refused: %r" % (result,))
    check("Object 'Cube' has no Forge object type. Add it with Add > Forge Object, or duplicate an imported object."
          in str(result) or "E_OBJ_NO_TYPE" in env.report_text(), str(result))
    check("ERROR E_OBJ_NO_TYPE '" in env.report_text() and "Object 'Cube' has no Forge object type." in env.report_text(),
          env.report_text())
    check(not os.path.exists(path), "nothing written")
    cube_export = [o for o in stub.LAST_EXPORT[1] if o.name == "Cube"][0]
    check_eq((cube_export.type_name, cube_export.type_id_hint, cube_export.slot), ("", -1, None),
             "the glue does not invent type 0")

    result = bpy.ops.object.convert_forge(isForgeObject=False)
    check_eq(result, {'FINISHED'})
    result, path = env.export_to("b12_back.mvar")
    check_eq(result, {'FINISHED'}, "a plain object again: the export works")
    check(os.path.exists(path))
    check_eq(len(stub.LAST_EXPORT[1]), 5, "the cube is not exported")

    # a model-less object added from the Add menu names its type, so it is not refused
    bpy.ops.forge.add_object(objectType="Block, 1x1")
    added = bpy.context.active_object
    result, path = env.export_to("b12_added.mvar")
    check_eq(result, {'FINISHED'}, "an Add > Forge Object object has a type even without the library")
    eo = [o for o in stub.LAST_EXPORT[1] if o.slot is None][0]
    check_eq((eo.type_name, eo.type_id_hint), ("Block, 1x1", -1))

    env.reset()
    run_glue_refusals(env)



def sha256_of(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def refused(env, name, code, text, **kwargs):
    """Export must be refused with ``code``: RuntimeError carrying ``text``, report line, no file."""
    result, path = env.export_to(name, **kwargs)
    check(isinstance(result, RuntimeError), "%s: expected a refusal, got %r" % (code, result))
    check(text in str(result), "%s: %r not in %r" % (code, text, str(result)))
    report = env.report_text()
    check("ERROR %s" % code in report, "%s: not in the report:\n%s" % (code, report))
    check("REFUSED, nothing was written" in report)
    return path


def run_glue_refusals(env):
    stub = env.stub
    scene = bpy.context.scene
    source = env.write_template("b12_source.mvar", b"SOURCE-FILE-BYTES")
    before = sha256_of(source)
    env.import_stub(path=source)
    by = dict((o["mj_slot"], o) for o in env.forge_objects())

    # mirrored transform
    by[1].scale = (-1.0, 1.0, 1.0)
    path = refused(env, "b12_mirrored.mvar", "E_MIRRORED", "Object '1 - Block, 1x1' has a mirrored (negative scale) "
                   "transform, which cannot be exported.")
    check(not os.path.exists(path))
    by[1].scale = (1.0, 1.0, 1.0)

    # the target is the imported file, also through a symlink; the original bytes stay what they were
    result = None
    try:
        result = bpy.ops.export_scene.mjolnir_mvar(filepath=source)
    except RuntimeError as exc:
        result = exc
    check(isinstance(result, RuntimeError) and "Refusing to overwrite the file this map was imported from (%s)" % source
          in str(result), repr(result))
    check("ERROR E_PATH_SAME_AS_SOURCE" in env.report_text() and "REFUSED, nothing was written" in env.report_text())
    alias = os.path.join(env.tmp, "alias.mvar")
    os.symlink(source, alias)
    try:
        bpy.ops.export_scene.mjolnir_mvar(filepath=alias)
        aliased = None
    except RuntimeError as exc:
        aliased = str(exc)
    check(aliased and "Refusing to overwrite the file this map was imported from" in aliased, aliased)
    check_eq(sha256_of(source), before, "the imported file is untouched")
    check(os.path.islink(alias))

    # protected folders: the built-in ones are known to the path policy; an extra one from the preferences is refused by the operator
    P = env.provider.get_provider()
    issue = env.io_ops.path_issue(P, os.path.expanduser("~/Local_Documents/Halo-MCC/variant-tool/test-samples/never-written.mvar"), source)
    check(issue is not None and issue.code == "E_PATH_PROTECTED", "built-in protected folder: %r" % (issue,))
    protected = os.path.join(env.tmp, "protected")
    os.makedirs(protected)

    class FakePrefs(object):
        library_path = ""
        protected_folders = protected + " ; /nonexistent-other-folder"

    with bl_common.patched(env.palette, "_addon_preferences", lambda: FakePrefs()):
        try:
            bpy.ops.export_scene.mjolnir_mvar(filepath=os.path.join(protected, "out.mvar"))
            blocked = None
        except RuntimeError as exc:
            blocked = str(exc)
        check(blocked and "Refusing to write into the protected folder %s." % protected in blocked, blocked)
        check(not os.path.exists(os.path.join(protected, "out.mvar")), "nothing written into a protected folder")

    # no target
    try:
        bpy.ops.export_scene.mjolnir_mvar(filepath="")
        none = None
    except RuntimeError as exc:
        none = str(exc)
    check(none and "No output file was chosen." in none, none)

    # a tampered template (checksum mismatch) and a scene without one
    good = bytes(scene["mjolnir_template"])
    scene["mjolnir_template"] = good[:-1] + bytes([(good[-1] + 1) % 256])
    refused(env, "b12_tampered.mvar", "E_TEMPLATE_CORRUPT", "The map variant stored in this scene is damaged (checksum "
            "mismatch). Import the original file again.")
    scene["mjolnir_template"] = good
    result, path = env.export_to("b12_restored.mvar")
    check_eq(result, {'FINISHED'}, "the restored template exports again")
    env.state.clear(scene)
    refused(env, "b12_none.mvar", "E_NO_TEMPLATE", "This scene has no imported map variant. Import a .mvar first: export "
            "patches the imported file.")
    check_eq(stub.LAST_EXPORT[0], good, "the provider was last called with the good template")


# =====================================================================================================
# the real-provider variant (G6)
# =====================================================================================================
def run_real(env):
    w1 = rd.fixture("w1_minimal")
    env.import_bytes(w1, "b12_w1.mvar")
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.active_object
    for obj in bpy.context.selected_objects:
        obj.select_set(obj is cube)

    ui = bl_common.draw_with_fake(env.mjolnir.convertForgeMenuItem, bl_common.FakeContext(selected_objects=[cube]))
    check_eq([e[2] for e in ui.operators()], ["Convert To Forge Object"])
    forge_ui = bl_common.draw_with_fake(env.mjolnir.convertForgeMenuItem, bl_common.FakeContext(selected_objects=[env.forge_objects()[0]]))
    check_eq([e[2] for e in forge_ui.operators()], ["Convert To Blender Object"])
    check_eq(bl_common.draw_with_fake(env.mjolnir.convertForgeMenuItem, bl_common.FakeContext()).operators(), [])

    check_eq(bpy.ops.object.convert_forge(isForgeObject=True), {'FINISHED'})
    check(cube.get("isForgeObject"), "converted")
    result, path = env.export_to("b12_cube.mvar")
    check(isinstance(result, RuntimeError), "refused: %r" % (result,))
    report = env.report_text()
    check("ERROR E_OBJ_NO_TYPE '" in report and "Object 'Cube' has no Forge object type. Add it with Add > Forge Object, or duplicate an imported object." in report, report[:1500])
    check("Result: REFUSED, nothing was written" in report)
    check(not os.path.exists(path), "nothing written")

    check_eq(bpy.ops.object.convert_forge(isForgeObject=False), {'FINISHED'})
    result, path = env.export_to("b12_back.mvar")
    check_eq(result, {'FINISHED'}, "a plain object again: the export works: %r" % (result,))
    check(rd.read_bytes(path) == w1, "the cube is not exported: W1 comes back byte for byte")

    # a model-less object added from the Add menu names its type, so it is not refused (new objects need the gate)
    check_eq(bpy.ops.forge.add_object(objectType="Block, 1x1"), {'FINISHED'})
    added = bpy.context.active_object
    added.location = (3.0, 4.0, 5.0)
    bpy.context.scene.forge.allowUnverifiedRotation = True
    result, path = env.export_to("b12_added.mvar")
    check_eq(result, {'FINISHED'}, "an Add > Forge Object object has a type even without the library: %r\n%s" % (result, env.report_text()[:1500]))
    after = rd.decode(rd.read_bytes(path))
    check_eq(sorted(after["slots"]), [0, 1, 5, 650])
    check_eq((after["slots"][0]["folder"], after["slots"][0]["item"]), (70, 0), "Block, 1x1")


if __name__ == "__main__":
    bl_common.main_module(sys.modules[__name__])
