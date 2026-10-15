"""B-01 (SPEC 9.4, 8.2): the add-on is enabled at STARTUP and register()/unregister() are clean.

Run with the add-on enabled by ``--addons`` so that ``register()`` executes while ``bpy.data`` is
restricted (any ``bpy.data`` or ``context.scene`` access there makes the enable fail and the classes
missing, which this test notices). Checks: classes registered; no ``bpy.ops`` call, thread, network call or
file read during ``register()``; three unregister/register cycles leave exactly one File > Import and one
Export entry (and the other hooks exactly once), a final unregister leaves none and no residue (classes,
pointer properties, handlers, draw handler); ``ErrorMessage`` is never invoked; the overlay handler is absent
in background mode. The add-on is left registered.
"""
import ast
import builtins
import inspect
import os
import sys
import threading
import traceback

import addon_utils
import bpy

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common  # noqa: E402
from bl_common import check, check_eq  # noqa: E402

ID = "b01"
TITLE = "enabled at startup; register/unregister x3 leaves one Import/Export entry, then none"
NEEDS_STUB = False

OPERATOR_TYPES = ["IMPORT_SCENE_OT_mjolnir_mvar", "EXPORT_SCENE_OT_mjolnir_mvar", "FORGE_OT_add_object",
                  "FORGE_OT_error", "FORGE_OT_scale_objects", "OBJECT_OT_convert_forge", "OBJECT_OT_setup_array"]
OTHER_TYPES = ["SCENE_PT_forge_object", "SCENE_PT_forge_object_sidebar", "SCENE_PT_forge_collection",
               "SCENE_PT_forge_scene", "VIEW3D_MT_add_forge_object", "MJOLNIR_FH_mvar"]


def entries(menu_type, module_prefix):
    """Draw functions of this add-on appended to ``menu_type``."""
    funcs = menu_type._dyn_ui_initialize()
    return [f for f in funcs if getattr(f, "__module__", "").startswith(module_prefix)]


def registered_state(env):
    return {
        "operators": [n for n in OPERATOR_TYPES if getattr(bpy.types, n, None) is not None],
        "others": [n for n in OTHER_TYPES if getattr(bpy.types, n, None) is not None],
        "object_forge": hasattr(bpy.types.Object, "forge"),
        "collection_forge": hasattr(bpy.types.Collection, "forge"),
        "scene_forge": hasattr(bpy.types.Scene, "forge"),
        "pool": [n for n in env.mjolnir.MENU_POOL_IDNAMES if getattr(bpy.types, n, None) is not None],
        "prefs": getattr(bpy.types, "MjolnirPreferences", None) is not None,
    }


def handlers_of_addon(env):
    prefix = env.addon_name
    found = []
    for name in ("load_post", "depsgraph_update_post", "load_pre", "save_pre", "undo_post", "redo_post"):
        for fn in getattr(bpy.app.handlers, name):
            if getattr(fn, "__module__", "").startswith(prefix):
                found.append((name, fn.__name__))
    return found


def run(env):
    """Run the checks; if one fails the add-on is registered cleanly again before the exception goes on.

    The checks unregister and register on purpose. A failure in between would leave the add-on unregistered (or
    half registered) and every later test would fail with an unrelated ``AttributeError`` on ``scene.forge``
    instead of the real problem being reported once, here.
    """
    finished = False
    try:
        _checks(env)
        finished = True
    finally:
        if not finished:
            print("b01: a check failed; unregistering and registering the add-on again so that later tests run")
            try:
                env.addon.unregister()
            except Exception:
                traceback.print_exc()
            env.addon.register()


def _checks(env):
    prefix = env.addon_name
    # 1. enabled at startup: everything is registered before this test touches anything
    check(addon_utils.check(prefix)[1], "add-on is not loaded/enabled: %s" % prefix)
    state = registered_state(env)
    check_eq(len(state["operators"]), len(OPERATOR_TYPES), "operators registered at startup")
    check_eq(len(state["others"]), len(OTHER_TYPES), "panels/menus/file handler registered at startup")
    check(state["object_forge"] and state["collection_forge"] and state["scene_forge"], "pointer properties")
    check_eq(len(state["pool"]), env.palette.MENU_POOL_SIZE, "pooled Add submenus")
    check_eq(len(entries(bpy.types.TOPBAR_MT_file_import, prefix)), 1, "File > Import entry at startup")
    check_eq(len(entries(bpy.types.TOPBAR_MT_file_export, prefix)), 1, "File > Export entry at startup")
    check_eq(len(entries(bpy.types.VIEW3D_MT_add, prefix)), 1, "Add menu hook")
    check_eq(len(entries(bpy.types.VIEW3D_MT_object_context_menu, prefix)), 2, "object context menu hooks")

    # 2. background mode: no overlay handler (blf.draw crashes -b)
    check(bpy.app.background, "this test is meant for background mode")
    check(env.mjolnir._overlay["handle"] is None, "overlay draw handler must be absent in -b")
    check_eq(handlers_of_addon(env), [("load_post", "_on_load")], "handlers after startup (only the relink handler)")

    # 3. register() itself: no operator call, no thread, no network, no file read, no bpy.data / scene access
    addon = env.addon
    calls = {"ops": [], "threads": [], "open": [], "net": []}
    original_getattr = bpy.ops.__getattr__                 # module-level __getattr__ of bpy/ops.py: every bpy.ops.X goes through it

    def spy_getattr(name):
        calls["ops"].append(name)
        return original_getattr(name)

    original_start = threading.Thread.start
    original_open = builtins.open

    def spy_start(self, *a, **kw):
        calls["threads"].append(self.name)
        return original_start(self, *a, **kw)

    def spy_open(file, *a, **kw):
        calls["open"].append(str(file))
        return original_open(file, *a, **kw)

    import urllib.request
    import webbrowser
    original_urlopen = urllib.request.urlopen
    original_browser = webbrowser.open

    def spy_net(*a, **kw):
        calls["net"].append(a)
        raise RuntimeError("network use during register()")

    bpy.ops.__getattr__ = spy_getattr
    threading.Thread.start = spy_start
    builtins.open = spy_open
    urllib.request.urlopen = spy_net
    webbrowser.open = spy_net
    threads_before = threading.active_count()
    try:
        addon.unregister()
        addon.register()
    finally:
        bpy.ops.__getattr__ = original_getattr
        threading.Thread.start = original_start
        builtins.open = original_open
        urllib.request.urlopen = original_urlopen
        webbrowser.open = original_browser
    check_eq(calls["ops"], [], "bpy.ops used during register()/unregister()")
    check_eq(calls["threads"], [], "thread started during register()")
    check_eq(calls["net"], [], "network during register()")
    check_eq(calls["open"], [], "file opened during register(): %s" % calls["open"])
    check_eq(threading.active_count(), threads_before, "thread count changed")

    # static scan of the register functions: no bpy.data, no scene access, no operator call
    for module in (env.mjolnir, env.palette, env.io_ops, addon):
        for fn in (module.register, module.unregister):
            tree = ast.parse(inspect.getsource(fn))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    dotted = []
                    cur = node
                    while isinstance(cur, ast.Attribute):
                        dotted.append(cur.attr)
                        cur = cur.value
                    if isinstance(cur, ast.Name):
                        path = ".".join([cur.id] + list(reversed(dotted)))
                        check(not path.startswith(("bpy.data", "bpy.ops", "bpy.context.scene", "context.scene")),
                              "%s.%s uses %s" % (module.__name__, fn.__name__, path))

    # 4. three enable/disable cycles through the add-on manager (what Preferences > Add-ons does), then direct ones
    for cycle in range(3):
        addon_utils.disable(prefix, default_set=False)
        check_eq(len(entries(bpy.types.TOPBAR_MT_file_import, prefix)), 0, "Import entries while disabled (cycle %d)" % cycle)
        check_eq(len(entries(bpy.types.TOPBAR_MT_file_export, prefix)), 0, "Export entries while disabled (cycle %d)" % cycle)
        check(getattr(bpy.types, "IMPORT_SCENE_OT_mjolnir_mvar", None) is None, "operator gone while disabled")
        check(addon_utils.enable(prefix, default_set=False, persistent=False) is not None, "enable returned None")
        check_eq(len(entries(bpy.types.TOPBAR_MT_file_import, prefix)), 1, "Import entries after enable (cycle %d)" % cycle)
        check_eq(len(entries(bpy.types.TOPBAR_MT_file_export, prefix)), 1, "Export entries after enable (cycle %d)" % cycle)
        check_eq(len(entries(bpy.types.VIEW3D_MT_add, prefix)), 1, "Add hook after enable (cycle %d)" % cycle)
        check_eq(len(entries(bpy.types.VIEW3D_MT_object_context_menu, prefix)), 2, "context hooks after enable")
        check_eq(handlers_of_addon(env), [("load_post", "_on_load")], "handlers after enable (cycle %d)" % cycle)
    check_eq(len(registered_state(env)["operators"]), len(OPERATOR_TYPES), "operators after the manager cycles")
    for cycle in range(3):
        addon.unregister()
        addon.register()
        check_eq(len(entries(bpy.types.TOPBAR_MT_file_import, prefix)), 1, "Import entries after cycle %d" % cycle)
        check_eq(len(entries(bpy.types.TOPBAR_MT_file_export, prefix)), 1, "Export entries after cycle %d" % cycle)
        check_eq(len(entries(bpy.types.VIEW3D_MT_add, prefix)), 1, "Add hooks after cycle %d" % cycle)
        check_eq(len(entries(bpy.types.VIEW3D_MT_object_context_menu, prefix)), 2, "context hooks after cycle %d" % cycle)
        check_eq(handlers_of_addon(env), [("load_post", "_on_load")], "handlers after cycle %d" % cycle)
    # registering twice in a row must not duplicate anything either
    addon.register()
    check_eq(len(entries(bpy.types.TOPBAR_MT_file_import, prefix)), 1, "double register: Import")
    check_eq(len(entries(bpy.types.TOPBAR_MT_file_export, prefix)), 1, "double register: Export")

    # 4b. the non-background branch of register(): draw handler and depsgraph handler are added and removed cleanly
    class AppProxy(object):
        background = False

        def __getattr__(self, name):
            return getattr(bpy.app, name)

    class BpyProxy(object):
        app = AppProxy()

        def __getattr__(self, name):
            return getattr(bpy, name)

    addon.unregister()
    with bl_common.patched(env.mjolnir, "bpy", BpyProxy()):
        env.mjolnir.register()
        check(env.mjolnir._overlay["handle"] is not None, "overlay draw handler added outside background mode")
        check(env.mjolnir._on_depsgraph_update in bpy.app.handlers.depsgraph_update_post, "depsgraph handler added")
        env.mjolnir.unregister()
    check(env.mjolnir._overlay["handle"] is None, "overlay draw handler removed")
    check(env.mjolnir._on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post, "depsgraph handler removed")
    env.mjolnir.unregister()                 # a second unregister must not raise (the old code raised KeyError)
    addon.register()

    # 5. a final unregister leaves nothing
    addon.unregister()
    gone = registered_state(env)
    check_eq(gone["operators"], [], "operators after unregister")
    check_eq(gone["others"], [], "panels/menus after unregister")
    check_eq(gone["pool"], [], "pooled menus after unregister")
    check(not (gone["object_forge"] or gone["collection_forge"] or gone["scene_forge"]), "pointer props after unregister")
    check_eq(len(entries(bpy.types.TOPBAR_MT_file_import, prefix)), 0, "Import entries after unregister")
    check_eq(len(entries(bpy.types.TOPBAR_MT_file_export, prefix)), 0, "Export entries after unregister")
    check_eq(len(entries(bpy.types.VIEW3D_MT_add, prefix)), 0)
    check_eq(len(entries(bpy.types.VIEW3D_MT_object_context_menu, prefix)), 0)
    check_eq(handlers_of_addon(env), [], "handlers after unregister")
    check(env.mjolnir._overlay["handle"] is None, "draw handler after unregister")
    addon.unregister()                       # unregistering twice is harmless
    addon.register()                         # leave the add-on registered for the other tests
    check_eq(len(registered_state(env)["operators"]), len(OPERATOR_TYPES), "re-registered")
    check_eq(len(entries(bpy.types.TOPBAR_MT_file_import, prefix)), 1)


if __name__ == "__main__":
    bl_common.main_module(sys.modules[__name__])
