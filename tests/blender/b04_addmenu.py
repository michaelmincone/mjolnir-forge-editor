"""B-04 (SPEC 9.4, 8.6): the Add menu draws from the static tree, filtered per map AND by the template's quota count.

* Drawn with a recording layout before any import and with ``bpy.data.collections`` empty: no ``KeyError``;
  the drawing code does not touch ``bpy.data`` at all (``palette.bpy`` is replaced by an object that
  explodes on use during the draw).
* The tree reaches every one of the 194 palette leaves through the 23 group submenus; every icon exists in
  the running Blender and every group has an entry in the icon table.
* Per-map filter: Forge World shows all 194 leaves (when the file defines enough palette entries), Boneyard only its own
  stock objects (the sets differ).
* Quota-count filter (G6, G5 defect 12): a stock object whose palette folder (``id >> 8``) lies at or beyond the quota count
  of the loaded template cannot be exported to that file (``E_FOLDER_RANGE``), so it is not offered, and the menu says so.
  W1 defines 80 entries: 41 Forge World leaves with a folder of 80 or more disappear; the real Breakneck file defines 82
  entries: ``Door``, ``Wall (MCC)``, ``Dumpster``, ``Heavy Barrier`` ... disappear.
* The search popup items equal the visible leaves; ``forge.add_object`` links the palette lazily, creates the
  object with the model, and a second call links nothing new.
* ``tools/gen_palette_tree.py`` run on the stand-in library reproduces the committed ``palette_tree.json``.
Stub variant (``run``): canned maps; real variant (``run_real``): fixtures of the independent builder and the real file.
"""
import os
import subprocess
import sys

import bpy

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common  # noqa: E402
import real_data as rd  # noqa: E402
from bl_common import check, check_eq  # noqa: E402

ID = "b04"
TITLE = "Add menu from the static tree: no KeyError, per-map filter, lazy palette link"
NEEDS_STUB = True

REPO = bl_common.REPO


class Exploding(object):
    def __getattr__(self, name):
        raise AssertionError("the Add menu touched bpy.%s while drawing" % name)


def all_menu_entries(env, context=None):
    """Draw the root menu and every pooled submenu; returns ``(root_ui, {menu number: ui})``."""
    root = bl_common.draw_with_fake(env.mjolnir.AddForgeObjectMenu.draw, context)
    subs = {}
    for number, (node, _icon) in enumerate(env.palette.groups()):
        fake = bl_common.FakeSelf()
        env.mjolnir.MENU_POOL[number].draw(fake, context or bl_common.FakeContext())
        subs[number] = fake.layout
    return root, subs


def leaf_names(subs):
    names = []
    for ui in subs.values():
        names.extend(entry[2] for entry in ui.operators())
    return names


def generator_reproduces_the_tree(env):
    """``tools/gen_palette_tree.py`` run on the stand-in library reproduces the committed ``palette_tree.json``."""
    py39 = "/usr/bin/python3"
    if os.path.exists(py39):
        out = os.path.join(env.tmp, "regenerated_tree.json")
        proc = subprocess.run([py39, "-I", os.path.join(REPO, "tools", "gen_palette_tree.py"), "--library",
                               env.standin_library(), "--out", out, "--blender", bpy.app.binary_path],
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              universal_newlines=True)
        check_eq(proc.returncode, 0, "gen_palette_tree on the stand-in:\n" + proc.stdout)
        with open(out, "rb") as fh, open(os.path.join(REPO, "Addon", "mvarlib", "data", "palette_tree.json"), "rb") as ref:
            check_eq(fh.read(), ref.read(), "regenerated tree equals the committed tree")


def quota_filter(env, scene, all_leaves, expected_count, quota_count, label):
    """Re-label the loaded template's quota count and check the Add menu: entries beyond it are not offered, with a note."""
    P = env.provider.get_provider()
    map_name = env.state.map_name(scene)
    st_quota = env.state.quota_count(scene)
    scene["mjolnir"]["quota_count"] = quota_count             # what a file with fewer palette entries would have stored
    env.palette._cache.update(provider=None, tree=None)       # forget cached filters
    try:
        root, subs = all_menu_entries(env, bl_common.FakeContext(scene))
        shown = set(leaf_names(subs))
        hidden = all_leaves - shown
        check_eq(len(shown), expected_count, "%s: leaves offered with %d palette entries" % (label, quota_count))
        for name in shown:
            folder = env.provider.object_folder(map_name, name)
            check(folder is None or folder < quota_count, "%s: %r (folder %r) is offered with %d entries" % (label, name, folder, quota_count))
        for name in hidden:
            check(env.provider.object_folder(map_name, name) >= quota_count, "%s: %r is hidden although its folder is below %d" % (label, name, quota_count))
        check_eq(root.texts(), [env.palette.QUOTA_NOTE % quota_count], "%s: the menu says entries were left out" % label)
        items = env.mjolnir.genObjectTypesEnum(None, bpy.context)
        check_eq(set(i[0] for i in items), shown, "%s: the search popup offers the same entries" % label)
        bl_common.check_raises(TypeError, bpy.ops.forge.add_object, objectType=sorted(hidden)[0])
        return shown
    finally:
        scene["mjolnir"]["quota_count"] = st_quota
        env.palette._cache.update(provider=None, tree=None)


def run(env):
    scene = bpy.context.scene
    check_eq(len(bpy.data.collections), 0, "no collections at the start")

    # --- before any import, drawing touches no bpy.data --------------------------------------------
    with bl_common.patched(env.palette, "bpy", Exploding()):
        root, subs = all_menu_entries(env)
    check_eq(root.texts(), [env.palette.NO_FILTER_NOTE], "note about filtering")
    tops = [m[2] for m in root.menus()]
    check_eq(tops, ["Structure", "Scenery", "Gadgets", "Spawning", "Objectives", "Hidden"], "top-level groups")
    check_eq(len(env.palette.groups()), 23, "group submenus in the tree")
    names = leaf_names(subs)
    check_eq(len(names), 194, "leaves reachable through the submenus")
    check_eq(len(set(names)), 194, "leaf names are unique")
    # the leaf buttons of the root menu: none (all leaves sit in groups)
    check_eq(root.operators(), [], "root has only groups")
    check_eq(set(names) - set(env.provider.get_provider().stock_object_names("Forge World")), set(),
             "every leaf is a Forge World object")

    # the hook in the Add menu: the search operator first, then the submenu
    hook = bl_common.draw_with_fake(env.mjolnir.addForgeObjectMenuItem)
    check_eq([e[1] for e in hook.operators()], ["forge.add_object"])
    check_eq([m[1] for m in hook.menus()], ["VIEW3D_MT_add_forge_object"])

    # icons: every one exists in this Blender, every group has its own entry
    icons = bl_common.icon_names()
    check(set(env.palette.GROUP_ICONS.values()) <= icons, "unknown icons: %s" % (set(env.palette.GROUP_ICONS.values()) - icons))
    for node, icon in env.palette.groups():
        check(node["name"] in env.palette.GROUP_ICONS, "no icon entry for group %r" % node["name"])
        check(icon in icons)
    for entry in root.menus():
        check(entry[3] in icons)

    # --- per-map filter ---------------------------------------------------------------------------------
    import dataclasses
    roomy = dataclasses.replace(env.stub.CANNED.info, quota_count=145)          # Forge World's highest palette entry is 144
    result, _ = env.import_stub(load=dataclasses.replace(env.stub.CANNED, info=roomy))   # Forge World
    check_eq(result, {'FINISHED'})
    root_fw, subs_fw = all_menu_entries(env, bl_common.FakeContext(scene))
    fw = set(leaf_names(subs_fw))
    check_eq(len(fw), 194, "Forge World shows every leaf")
    check_eq(root_fw.texts(), [], "no filter note once a template exists")
    quota_filter(env, scene, fw, 194 - 41, 80, "stub Forge World")

    env.stub.NEXT_LOAD = env.stub.CANNED_BONEYARD
    result, _ = env.import_stub()                                    # replaces; Boneyard
    check_eq(result, {'FINISHED'})
    check_eq(env.state.get(scene)["map_name"], "Boneyard")
    root_by, subs_by = all_menu_entries(env, bl_common.FakeContext(scene))
    by = set(leaf_names(subs_by))
    stock = set(env.provider.get_provider().stock_object_names("Boneyard"))
    check_eq(by, fw & stock, "Boneyard shows exactly its stock leaves")
    check(0 < len(by) < len(fw), "the Forge World and Boneyard sets differ (%d vs %d)" % (len(fw), len(by)))
    check("Block, 1x1" in fw and "Block, 1x1" not in by, "Block, 1x1 is not a Boneyard object")
    for number, ui in subs_by.items():              # a group without a visible leaf has no menu entry anywhere
        for entry in ui.menus():
            sub_number = env.mjolnir.MENU_POOL_IDNAMES.index(entry[1])
            check(len([e for e in subs_by[sub_number].operators()] + subs_by[sub_number].menus()) > 0, "empty submenu shown")
    # the search popup lists the same leaves
    items = env.mjolnir.genObjectTypesEnum(None, bpy.context)
    check_eq(set(i[0] for i in items), by, "search popup items")
    check(items is env.mjolnir.genObjectTypesEnum(None, bpy.context), "items list is cached (string lifetime)")

    # an unknown map shows everything with a note
    unknown = dataclasses.replace(env.stub.CANNED.info, map_id=0xFFFFFFFF, map_name=None, is_stock_map=False)
    env.stub.NEXT_LOAD = dataclasses.replace(env.stub.CANNED, info=unknown)
    env.import_stub()
    root_unknown, subs_unknown = all_menu_entries(env, bl_common.FakeContext(scene))
    check_eq(root_unknown.texts(), [env.palette.UNKNOWN_MAP_NOTE])
    check_eq(len(leaf_names(subs_unknown)), 194)

    # --- lazy link through the operator -------------------------------------------------------------------
    env.reset()
    env.import_stub()                                                 # Forge World again, no library available
    check_eq(len(bpy.data.libraries), 0)
    result = bpy.ops.forge.add_object(objectType="Block, 1x1")
    check_eq(result, {'FINISHED'})
    obj = bpy.context.active_object
    check_eq(obj.name, "Block, 1x1")
    check(obj.get("isForgeObject"), "flagged as a forge object")
    check(obj.instance_collection is None and obj.empty_display_type == 'ARROWS', "no library: arrow empty")
    check_eq(obj.get("mj_type_name"), "Block, 1x1", "the chosen type is remembered without a model")
    check("mj_slot" not in obj, "a new object claims no slot")
    check_eq(obj.forge.objectType, -1)
    check(obj.select_get(), "selected")

    env.use_library()                                                 # the stand-in
    check_eq(len(bpy.data.libraries), 0, "not linked before use")
    result = bpy.ops.forge.add_object(objectType="Block, 1x1")
    obj2 = bpy.context.active_object
    check_eq(len(bpy.data.libraries), 1, "linked on first use")
    check(obj2.instance_collection is not None and obj2.instance_collection.library is not None, "linked model")
    check_eq(obj2.instance_collection.name, "Block, 1x1")
    check(obj2.instance_collection.name_full != "Block, 1x1", ".name_full carries the library suffix")
    check("mj_type_name" not in obj2)
    n_colls = len(bpy.data.collections)
    bpy.ops.forge.add_object(objectType="Block, 1x1")
    check_eq(len(bpy.data.libraries), 1, "second call links nothing")
    check_eq(len(bpy.data.collections), n_colls, "second call creates no collection")
    wanted = set(c.name for c in bpy.data.collections)
    check({"Forge World Palette", "Shape Models"} <= wanted, "palette roots linked")
    check("Forge World" not in wanted and len(bpy.data.scenes) == 1, "no scene and no backdrop linked")
    # a name that is not on this map is refused by the enum
    env.stub.NEXT_LOAD = env.stub.CANNED_BONEYARD
    env.import_stub()
    bl_common.check_raises(TypeError, bpy.ops.forge.add_object, objectType="Block, 1x1")

    generator_reproduces_the_tree(env)


# =====================================================================================================
# the real-provider variant (G6)
# =====================================================================================================
def tree_leaves(env):
    return set(name for name, _icon in env.palette.leaf_entries())


def map_fixture(map_id, quota_count, name):
    """W1 on another map and with another number of palette entries (the quota table has one row per entry)."""
    spec = rd.w1_spec(name, "W1 on map %d with %d palette entries" % (map_id, quota_count))
    spec["header"]["map_id"] = map_id
    spec["body"]["map_id_2"] = map_id
    spec["body"]["quota_count"] = quota_count
    return rd.build_spec(spec)


def offered(env, scene):
    root, subs = all_menu_entries(env, bl_common.FakeContext(scene))
    return root, set(leaf_names(subs))


def run_real(env):
    scene = bpy.context.scene
    P = env.provider.get_provider()
    check_eq(len(bpy.data.collections), 0, "no collections at the start")

    # --- before any import, drawing touches no bpy.data -----------------------------------------------------------
    with bl_common.patched(env.palette, "bpy", Exploding()):
        root, subs = all_menu_entries(env)
    check_eq(root.texts(), [env.palette.NO_FILTER_NOTE], "note about filtering")
    check_eq([m[2] for m in root.menus()], ["Structure", "Scenery", "Gadgets", "Spawning", "Objectives", "Hidden"], "top-level groups")
    names = leaf_names(subs)
    check_eq((len(names), len(set(names))), (194, 194), "leaves reachable through the submenus")
    check_eq(set(names) - set(P.stock_object_names("Forge World")), set(), "every leaf is a Forge World object")
    leaves = tree_leaves(env)
    icons = bl_common.icon_names()
    check(set(env.palette.GROUP_ICONS.values()) <= icons)

    # --- Forge World, 145 palette entries: every leaf --------------------------------------------------------------------
    result, _ = env.import_bytes(map_fixture(rd.FORGE_WORLD, 145, "b04_fw145"), "b04_fw145.mvar")
    check_eq(result, {'FINISHED'})
    root_fw, fw = offered(env, scene)
    check_eq(len(fw), 194, "Forge World with 145 entries shows every leaf")
    check_eq(root_fw.texts(), [], "no note: nothing was left out")

    # --- W1 as it is: 80 palette entries, so 41 Forge World leaves with a folder of 80 or more are not offered ----------------------------
    env.reset()
    result, _ = env.import_bytes(rd.fixture("w1_minimal"), "b04_w1.mvar")
    check_eq(result, {'FINISHED'})
    root_80, fw80 = offered(env, scene)
    check_eq(len(fw80), 194 - 41, "W1 (80 palette entries): the 41 leaves of entries 80 and beyond are not offered")
    check_eq(root_80.texts(), [env.palette.QUOTA_NOTE % 80], "the note says why")
    for gone in ("Block, 2x2x2, Invisible", "Dumpster", "Bridge", "Door (MCC)", "Vending Machine", "Ammo Cabinet"):
        check(gone in leaves and gone not in fw80, "%r is hidden with 80 entries" % gone)
    for kept in ("Block, 1x1", "Kill Boundary" if "Kill Boundary" in leaves else "Block, 1x2", "Initial Spawn", "Wall"):
        check(kept in fw80, "%r is offered with 80 entries" % kept)
    for name in fw80:
        check(P.stock_object_names("Forge World").count(name) == 1 and env.provider.object_folder("Forge World", name) < 80, name)
    items = env.mjolnir.genObjectTypesEnum(None, bpy.context)
    check_eq(set(i[0] for i in items), fw80, "search popup items")
    check(items is env.mjolnir.genObjectTypesEnum(None, bpy.context), "items list is cached (string lifetime)")
    bl_common.check_raises(TypeError, bpy.ops.forge.add_object, objectType="Bridge")

    # --- Boneyard: its own stock objects only ---------------------------------------------------------------------------------------
    env.reset()
    result, _ = env.import_bytes(map_fixture(rd.BONEYARD, 80, "b04_boneyard"), "b04_boneyard.mvar")
    check_eq(result, {'FINISHED'})
    check_eq(env.state.get(scene)["map_name"], "Boneyard")
    root_by, subs_by = all_menu_entries(env, bl_common.FakeContext(scene))
    by = set(leaf_names(subs_by))
    stock = set(P.stock_object_names("Boneyard"))
    check_eq(by, fw & stock, "Boneyard shows exactly its stock leaves")
    check(0 < len(by) < len(fw), "the Forge World and Boneyard sets differ (%d vs %d)" % (len(fw), len(by)))
    check("Block, 1x1" in fw and "Block, 1x1" not in by, "Block, 1x1 is not a Boneyard object")
    check_eq(root_by.texts(), [], "every Boneyard entry is below its 80 palette entries: no note")
    for ui in subs_by.values():                     # a group without a visible leaf has no menu entry anywhere
        for entry in ui.menus():
            sub = subs_by[env.mjolnir.MENU_POOL_IDNAMES.index(entry[1])]
            check(len(sub.operators()) + len(sub.menus()) > 0, "empty submenu shown")

    # --- an unknown map shows everything with a note -----------------------------------------------------------------------------------------
    env.reset()
    result, _ = env.import_bytes(rd.fixture("unknown_map"), "b04_unknown.mvar")
    check_eq(result, {'FINISHED'})
    root_unknown, unknown = offered(env, scene)
    check_eq(root_unknown.texts(), [env.palette.UNKNOWN_MAP_NOTE])
    check_eq(len(unknown), 194)

    # --- the real file: Breakneck defines 82 palette entries -----------------------------------------------------------------------------------
    if rd.real_available():
        env.reset()
        env.use_library()
        check_eq(env.import_file(rd.real_mvar_path()), {'FINISHED'})
        root_bk, bk = offered(env, scene)
        stock = set(P.stock_object_names("Breakneck"))
        expected = set(n for n in leaves & stock if env.provider.object_folder("Breakneck", n) < 82)
        check_eq(bk, expected, "Breakneck: stock leaves with a palette entry below 82")
        beyond = (leaves & stock) - expected
        check_eq(sorted(beyond), ["Ammo Cabinet", "Door", "Dumpster", "Dumpster, Tall", "Heavy Barrier", "Wall (MCC)"],
                 "the leaves of entries 82 and beyond that the file cannot hold")
        check_eq(root_bk.texts(), [env.palette.QUOTA_NOTE % 82])
        check_eq(len(bk), 106)
        for name in beyond:
            bl_common.check_raises(TypeError, bpy.ops.forge.add_object, objectType=name)
        # an offered entry can be added, and the lazy link works on the real file as well
        before = len(bpy.data.libraries)
        check_eq(bpy.ops.forge.add_object(objectType="Cover, Large") if "Cover, Large" in bk else {'FINISHED'}, {'FINISHED'})
        check(len(bpy.data.libraries) >= before)

    # --- lazy link through the operator (W1) ---------------------------------------------------------------------------------------------------
    env.reset()
    result, _ = env.import_bytes(rd.fixture("w1_minimal"), "b04_lazy.mvar")
    check_eq(len(bpy.data.libraries), 0)
    check_eq(bpy.ops.forge.add_object(objectType="Block, 1x1"), {'FINISHED'})
    obj = bpy.context.active_object
    check_eq(obj.name, "Block, 1x1")
    check(obj.get("isForgeObject") and obj.instance_collection is None and obj.empty_display_type == 'ARROWS', "no library: arrow empty")
    check_eq(obj.get("mj_type_name"), "Block, 1x1", "the chosen type is remembered without a model")
    check("mj_slot" not in obj, "a new object claims no slot")
    check_eq(obj.forge.objectType, -1)
    env.use_library()
    check_eq(len(bpy.data.libraries), 0, "not linked before use")
    check_eq(bpy.ops.forge.add_object(objectType="Block, 1x1"), {'FINISHED'})
    obj2 = bpy.context.active_object
    check_eq(len(bpy.data.libraries), 1, "linked on first use")
    check(obj2.instance_collection is not None and obj2.instance_collection.library is not None, "linked model")
    check_eq(obj2.instance_collection.name, "Block, 1x1")
    n_colls = len(bpy.data.collections)
    bpy.ops.forge.add_object(objectType="Block, 1x1")
    check_eq((len(bpy.data.libraries), len(bpy.data.collections)), (1, n_colls), "a second call links nothing new")
    check("Forge World" not in set(c.name for c in bpy.data.collections) and len(bpy.data.scenes) == 1, "no scene and no backdrop linked")

    generator_reproduces_the_tree(env)



if __name__ == "__main__":
    bl_common.main_module(sys.modules[__name__])
