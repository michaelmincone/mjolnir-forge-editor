"""B-13 (SPEC 9.4, 8.7 #15 #16): panels draw with a recording fake UILayout in all states.

Every ``layout.prop(data, name)`` must resolve to a real property, every icon must exist in this Blender. The
object panels are drawn for each cached-type branch (weapon, teleporter), every shape and a SCALE-labelled
object, in a wide and a narrow region; the collection panel is disabled for linked data; the scene panel shows
the map-variant box and both checkboxes; the overlay callback returns at once in background mode and, with
``blf`` replaced by a recorder, draws "N / 650" with the right colour otherwise.

The checks are the same for both providers (``run_with``): the stub variant imports the provider's canned records, the real
variant (``run_real``, G6) imports a fixture of the independent builder with the same cast (a weapon, a teleporter node, a
SCALE-labelled block, a box, a cylinder and a sphere shape, a tilted block, the loadout camera) through the real library.
"""
import dataclasses
import os
import sys

import bpy

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common  # noqa: E402
import real_data as rd  # noqa: E402
from bl_common import FakeContext, check, check_eq, draw_with_fake  # noqa: E402

ID = "b13"
TITLE = "panels draw with a recording layout; linked collection panel disabled; overlay guarded in -b"
NEEDS_STUB = True


class FakeBlf(object):
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args):
            self.calls.append((name,) + args)
        return record


def run(env):
    stub = env.stub
    loaded = dataclasses.replace(stub.CANNED, objects=list(stub.CANNED.objects) + [
        dataclasses.replace(stub.CANNED.objects[0], slot=20, label_index=0, spawn_sequence=-30),            # SCALE
        stub.make_record(21, "Forge World", "Two-Way Node", (0, 0, 0), cached_type=12, other_a=3, other_b=5),
        stub.make_record(22, "Forge World", "Kill Boundary", (0, 1, 0), shape=2, width=5.0, top=3.0, bottom=1.0),
        stub.make_record(23, "Forge World", "Kill Boundary", (0, 2, 0), shape=1, width=7.0),
    ])
    run_with(env, lambda: env.import_stub(load=loaded), lambda: env.import_stub())


def cast_fixture():
    """Nine objects with the slot numbers of the stub's cast (1, 2, 5, 9, 11, 20 to 23) on W1's map."""
    return rd.build_spec(rd.cast_spec("b13_cast"))


def run_real(env):
    data = cast_fixture()
    rd.decode(data)                                   # the independent walker accepts it

    def import_full():
        return env.import_bytes(data, "b13_cast.mvar")

    def import_plain():
        return env.import_bytes(rd.fixture("w1_minimal"), "b13_w1.mvar")

    run_with(env, import_full, import_plain)


def run_with(env, import_full, import_plain):
    mj = env.mjolnir
    scene = bpy.context.scene

    # --- object panels, every branch --------------------------------------------------------------------------
    import_full()
    by = dict((o["mj_slot"], o) for o in env.forge_objects())
    drawn = 0
    for slot, obj in sorted(by.items()):
        for width in (500, 190, 150):                               # wide, narrow, very narrow regions
            with bl_common.patched(mj, "region_width", lambda region, w=width: w):
                for panel in (mj.ForgeObjectPanel, mj.ForgeObjectPanel_Sidebar):
                    ctx = FakeContext(scene, [obj])
                    check(panel.poll(ctx), "panel poll for a forge object")
                    ui = draw_with_fake(panel.draw, ctx)
                    props = ui.props()
                    check("physics" in props and "team" in props and "gtLabel" in props, "common props drawn")
                    drawn += 1
                    if slot == 2:
                        check("otherInfoA" in props, "weapon branch: spare clips")
                    if slot == 21:
                        check(props.count("otherInfoA") == 1 and "otherInfoB" in props, "teleporter branch")
                    if slot == 20:
                        check("scaleConvention" in props, "scaled object shows the convention")
                    if slot == 22:
                        check("top" in props and "bottom" in props and "length" not in props, "cylinder")
                    if slot == 23:
                        check("width" in props and "top" not in props and "length" not in props, "sphere: radius only")
                    if slot == 5:
                        check("length" in props and "top" in props, "box")
    check(drawn >= 8 * 3 * 2)
    check_eq(mj.ForgeObjectPanel.poll(FakeContext(scene, [])), False, "nothing selected")
    cube = bpy.data.objects.new("plain", None)
    scene.collection.objects.link(cube)
    check_eq(mj.ForgeObjectPanel.poll(FakeContext(scene, [cube])), False, "not a forge object")

    # --- collection panel ------------------------------------------------------------------------------------------
    local = bpy.data.collections.new("Mine")
    ui = draw_with_fake(mj.ForgeCollectionPanel.draw, FakeContext(scene, collection=local))
    check_eq(ui.props(), ["icon"])
    check("enabled" not in ui.sets or ui.sets["enabled"], "a local collection is editable")
    env.use_library()
    check(env.palette.ensure_palette())
    linked = env.palette.find_collection("Forge World Palette")
    check(linked is not None and linked.library is not None, "linked collection")
    ui = draw_with_fake(mj.ForgeCollectionPanel.draw, FakeContext(scene, collection=linked))
    check_eq(ui.sets.get("enabled"), False, "linked data: the panel is disabled (8.7 #15)")
    check("Linked collection: read-only" in ui.texts())
    ui = draw_with_fake(mj.ForgeCollectionPanel.draw, FakeContext(scene, collection=None))
    check_eq(ui.texts(), ["No active collection"])

    # --- scene panel -------------------------------------------------------------------------------------------------
    ui = draw_with_fake(mj.ForgeScenePanel.draw, FakeContext(scene))
    check_eq(sorted(ui.props()), ["allowUnverifiedRotation", "keepUnrecognisedObjects", "scaleConvention"])
    check(any("Map: Forge World (0x00000BBE)" == t for t in ui.texts()), ui.texts())
    occupied = env.state.get(scene)["occupied_at_import"]
    check("Slots at import: %d / 650" % occupied in ui.texts(), ui.texts())
    env.state.set_import_results(scene, env.state.get(scene)["imported_slots"], [4, 7])
    ui = draw_with_fake(mj.ForgeScenePanel.draw, FakeContext(scene))
    check("Not imported (left unchanged on export): slots 4, 7" in ui.texts(), ui.texts())
    check(not any("not stock objects" in t for t in ui.texts()), "no non-stock note while none of the failed slots is non-stock")
    env.state.set_import_results(scene, env.state.get(scene)["imported_slots"], [4, 7], {7: "Unknown (0x4F1F)"})
    ui = draw_with_fake(mj.ForgeScenePanel.draw, FakeContext(scene))
    check("Not stock objects: slots 7. Export is refused unless \"Keep objects this tool does not recognise\" is ticked" in ui.texts(), ui.texts())
    env.state.clear(scene)
    ui = draw_with_fake(mj.ForgeScenePanel.draw, FakeContext(scene))
    check("No map variant imported (File > Import)" in ui.texts())

    # --- operator dialogs and the import/export menu entries ---------------------------------------------------------------
    import_plain()
    ui = draw_with_fake(env.io_ops.EXPORT_OT_mjolnir_mvar.draw, FakeContext(scene), force_reencode=False,
                        fsm_policy="KEEP", hash_policy="REPRODUCE", raise_quota_max=False)
    check_eq(sorted(ui.props()), ["allowUnverifiedRotation", "force_reencode", "fsm_policy", "hash_policy",
                                  "keepUnrecognisedObjects", "raise_quota_max"])
    # polish item 6 (G6): the unverified quota option is never remembered between runs, so it can never come back pre-ticked
    export_props = dict((p.identifier, p) for p in bpy.ops.export_scene.mjolnir_mvar.get_rna_type().properties)
    check_eq(export_props["raise_quota_max"].is_skip_save, True, "raise_quota_max carries SKIP_SAVE")
    check_eq(export_props["raise_quota_max"].default, False, "and is off by default")
    check_eq(export_props["raise_quota_max"].name, "Raise quota maximum (unverified)")
    for kind in ("CONST", "OBJECT", "CURVE"):
        ui = draw_with_fake(mj.SetupArray.draw, FakeContext(scene), type=kind, count=3, offset=(1, 0, 0),
                            rotation=(0, 0, 0), size=5.0)
        props = ui.props()
        check("type" in props and "offset" in props, props)
        check(("count" in props) == (kind != "CURVE") and ("rotation" in props) == (kind == "OBJECT")
              and ("size" in props) == (kind == "CURVE"), "%s: %s" % (kind, props))
    ui = draw_with_fake(mj.ErrorMessage.draw, FakeContext(scene), message="boom\nsecond line", url="https://example.invalid")
    check("boom" in ui.texts() and ui.operators()[0][1] == "wm.url_open")
    ui = draw_with_fake(mj.ErrorMessage.draw, FakeContext(scene), message="plain", url="")
    check_eq(ui.operators(), [])
    for fn, idname in ((env.io_ops.menu_func_import, "import_scene.mjolnir_mvar"),
                       (env.io_ops.menu_func_export, "export_scene.mjolnir_mvar")):
        ui = draw_with_fake(fn)
        check_eq(ui.operators(), [("operator", idname, "Halo Reach Map Variant (.mvar)", "ANTIALIASED")])
    ui = draw_with_fake(mj.setupArrayMenuItem)
    check_eq([e[1] for e in ui.operators()], ["object.setup_array"])

    # --- the overlay (8.7 #16) -----------------------------------------------------------------------------------------------
    blf = FakeBlf()
    with bl_common.patched(mj, "blf", blf):
        mj.draw_forgeObjectOverlay()                                  # -b: returns at once
    check_eq(blf.calls, [], "no blf call in background mode")
    check(bpy.app.background)
    with bl_common.patched(mj, "blf", blf), bl_common.patched(mj, "_is_background", lambda: False):
        mj._overlay["dirty"] = True
        mj.draw_forgeObjectOverlay()
        n_forge = len(env.forge_objects())
        check_eq(blf.calls[-1], ("draw", 0, "%d / 650" % n_forge), "the count of the Forge objects")
        check_eq([c for c in blf.calls if c[0] == "color"][-1], ("color", 0, 1, 1, 1, 1), "white up to 500")
        for count, color in ((501, (1, 0.5, 0, 1)), (651, (1, 0, 0, 1))):
            blf.calls.clear()
            with bl_common.patched(mj, "count_forge_objects", lambda *a, **k: count):
                mj._overlay["dirty"] = True
                mj.draw_forgeObjectOverlay()
            check_eq([c for c in blf.calls if c[0] == "color"][-1], ("color", 0) + color, "colour at %d" % count)
            check_eq(blf.calls[-1], ("draw", 0, "%d / 650" % count))
        # the count is cached: no recount until the depsgraph handler marks it dirty
        blf.calls.clear()
        with bl_common.patched(mj, "count_forge_objects", lambda *a, **k: 1 / 0):
            mj.draw_forgeObjectOverlay()                              # cached, so the failing counter is not called
            check_eq(blf.calls[-1], ("draw", 0, "651 / 650"), "cached count")
            mj._on_depsgraph_update(scene)
            check_eq(mj._overlay["dirty"], True)
            blf.calls.clear()
            mj.draw_forgeObjectOverlay()                              # a failure inside the callback never raises
        check_eq(blf.calls, [])


if __name__ == "__main__":
    bl_common.main_module(sys.modules[__name__])
