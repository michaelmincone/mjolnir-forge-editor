"""Object library and Add-menu data of the Blender glue (SPEC 8.6).

* **Lazy link.** The object library (``Halo Reach.blend``, Microsoft/343 models) is NEVER linked in
  ``register()`` and never in ``load_post``: it is linked inside operators (Import, Add > Forge Object,
  Setup Array, shape creation) by :func:`ensure_palette`, only the two collections the add-on needs
  (``Forge World Palette`` and ``Shape Models``), read in place and never copied.
* **Names, not full names.** A linked collection's ``.name`` is ``Block, 1x1`` while ``.name_full`` is
  ``Block, 1x1 [Halo Reach.blend]``; the glue only ever uses ``.name`` (:func:`find_collection`).
* **Complete browser.** The provider merges the original model-library tree with the complete native
  object catalog. Drawing never touches ``bpy.data`` and does not depend on a model being present.
  The per-map filter keeps stock names; verified Forge World templates can extend their quota table
  to the full native palette when a newly requested type requires it.
* **Relink.** A ``load_post`` handler repairs the path of a missing ``Halo Reach.blend`` link (for an
  extension the path contains a per-Blender-version profile directory that an upgrade strands).
* **Icons.** A hand-written name -> icon map (the stored numeric ``forge.icon`` indices of the library
  drift across Blender versions and resolve to wrong icons); every icon is validated against the
  running Blender's icon enum by ``tests/blender/b04_addmenu.py``.

Nothing here runs at import or in ``register()`` except class registration and the handler append.
"""
import os

import bpy
from bpy.app.handlers import persistent
from bpy.props import StringProperty
from bpy.types import AddonPreferences

from . import provider, state

WANTED = ("Forge World Palette", "Shape Models")
LIBRARY_BASENAME = "Halo Reach.blend"
ENV_LIBRARY = "MJOLNIR_LIBRARY"
DEFAULT_ICON = "OBJECT_DATA"
MENU_POOL_SIZE = 48                      # pre-declared submenu classes (see mjolnir.py); more groups are drawn inline

# group name -> icon identifier (all exist in the 5.2.1 icon enum; checked by B-04)
GROUP_ICONS = {
    "Structure": "MESH_CUBE",
    "Building Blocks": "CUBE",
    "Bridges And Platforms": "MESH_PLANE",
    "Buildings": "HOME",
    "Decorative": "MOD_WIREFRAME",
    "Doors, Windows, And Walls": "WINDOW",
    "Inclines": "MESH_CONE",
    "Natural": "WORLD",
    "Scenery": "OUTLINER_OB_GROUP_INSTANCE",
    "Barricades": "LOCKED",
    "Crates": "MESH_CUBE",
    "Palletes": "MESH_GRID",
    "Gadgets": "TOOL_SETTINGS",
    "Explosives": "MOD_EXPLODE",
    "Cannons, Men": "FORCE_FORCE",
    "Powerups": "SOLO_ON",
    "Teleporters": "ARROW_LEFTRIGHT",
    "Toys": "MESH_UVSPHERE",
    "Lights": "LIGHT",
    "Spawning": "EMPTY_AXIS",
    "Objectives": "BOOKMARKS",
    "Hidden": "HIDE_ON",
    "Invisible": "GHOST_ENABLED",
    "Weapons, Human": "OUTLINER_OB_ARMATURE",
    "Weapons, Covenant": "OUTLINER_OB_ARMATURE",
    "Armor Abilities": "FORCE_FORCE",
    "Vehicles": "AUTO",
    "More": "COLLECTION_NEW",
    "MCC Additions": "COLLECTION_NEW",
}

NO_FILTER_NOTE = "Import a map variant to filter by map"
UNKNOWN_MAP_NOTE = "Not a stock map: nothing is filtered, export will be refused"
QUOTA_NOTE = "Entries beyond this map variant's %d palette entries are not offered"


# --- library location and linking -----------------------------------------------------------
def _addon_preferences():
    try:
        return bpy.context.preferences.addons[__package__].preferences
    except Exception:
        return None


def library_path():
    """Where to find ``Halo Reach.blend``: preference, then ``$MJOLNIR_LIBRARY``, then ``<package>/Resources``.

    The package copy exists only in the development loop (``Addon/`` symlinked into the profile) and in
    a ``--with-library`` build; the default package carries no game asset. A preference or environment
    value naming a folder gets the file name appended. The result may not exist (callers test it).
    """
    candidates = []
    prefs = _addon_preferences()
    if prefs is not None:
        try:
            if prefs.library_path:
                candidates.append(bpy.path.abspath(prefs.library_path))
        except Exception:
            pass
    env = os.environ.get(ENV_LIBRARY)
    if env:
        candidates.append(os.path.expanduser(env))
    if candidates:
        path = candidates[0]
        return os.path.join(path, LIBRARY_BASENAME) if os.path.isdir(path) else path
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "Resources", LIBRARY_BASENAME)


def _is_palette_library(collection):
    lib = collection.library
    return lib is not None and os.path.basename(lib.filepath.replace("\\", "/")) == LIBRARY_BASENAME


def _library_key(collection):
    return (os.path.realpath(bpy.path.abspath(collection.library.filepath))
            if collection.library is not None else None)


def _library_score(collection, preferred):
    if collection.library is None:
        return 1
    if _library_key(collection) == preferred:
        return 3
    return 2 if _is_palette_library(collection) else 0


def find_collection(name):
    """The palette collection called ``name``: a linked one from ``Halo Reach.blend`` first, else a local one.

    Never ``bpy.data.collections[name]`` (a name can exist twice, linked and local).
    """
    best, score = None, 0
    preferred = os.path.realpath(library_path())
    for coll in bpy.data.collections:
        if coll.name != name:
            continue
        candidate = _library_score(coll, preferred)
        if candidate > score:
            best, score = coll, candidate
    return best


def collection_index():
    """``{name: collection}`` with the same preference as :func:`find_collection` (one pass, for batch imports)."""
    found, scores = {}, {}
    preferred = os.path.realpath(library_path())
    for coll in bpy.data.collections:
        score = _library_score(coll, preferred)
        if score > scores.get(coll.name, 0):
            found[coll.name], scores[coll.name] = coll, score
    return found


def ensure_palette():
    """Link the palette collections if they are not available yet; True when ``Forge World Palette`` is.

    Called only from operators. Linking needs the file named by :func:`library_path`; without it this
    returns False and the caller falls back to arrow empties (import reports a WARNING).
    """
    path = library_path()
    if path and os.path.isfile(path):
        preferred = os.path.realpath(path)
        missing = [n for n in WANTED if not any(col.name == n and _library_key(col) == preferred
                                               for col in bpy.data.collections)]
    else:
        missing = [n for n in WANTED if find_collection(n) is None]
    if not missing:
        return True
    if path and os.path.isfile(path):
        try:
            with bpy.data.libraries.load(path, link=True, relative=False) as (data_from, data_to):
                data_to.collections = [n for n in missing if n in data_from.collections]
        except Exception as exc:                        # unreadable library: report through the False result
            print("Mjolnir: could not link %s: %s" % (path, exc))
    return find_collection(WANTED[0]) is not None


def palette_missing_warning():
    return ("Palette library not found. Set Preferences > Add-ons > Halo: Mjolnir Forge Editor > Library path. "
            "Objects were imported as arrow empties.")


# --- relink on load -------------------------------------------------------------------------
@persistent
def _on_load(_unused=None):
    """Point a stranded ``Halo Reach.blend`` link at :func:`library_path` and reload it. Never links anything new."""
    try:
        for lib in bpy.data.libraries:
            if os.path.basename(lib.filepath.replace("\\", "/")) != LIBRARY_BASENAME:
                continue
            if os.path.isfile(bpy.path.abspath(lib.filepath, library=lib.library)):
                continue
            target = library_path()
            if target and os.path.isfile(target):
                lib.filepath = target
                lib.reload()
    except Exception as exc:
        print("Mjolnir: relink skipped: %s" % exc)


# --- add-on preferences ---------------------------------------------------------------------
class MjolnirPreferences(AddonPreferences):
    bl_idname = __package__

    library_path: StringProperty(
        name="Library path",
        description="Halo Reach.blend object library (or the folder that holds it). It is linked in place and "
                    "never copied; without it objects are imported as arrow empties",
        subtype='FILE_PATH')
    protected_folders: StringProperty(
        name="Extra protected folders",
        description="Folders (separated by ;) that export refuses to write into, besides the built-in sample "
                    "folders")

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "library_path")
        layout.operator('forge.refresh_previews', text='Refresh Object Previews')
        path = library_path()
        if os.path.isfile(path):
            layout.label(text="Library found: %s" % path, icon='CHECKMARK')
        else:
            layout.label(text="Library not found (%s)" % path, icon='ERROR')
        layout.prop(self, "protected_folders")


def extra_protected_folders():
    """Folders from the preference (``;``-separated), without the built-in defaults."""
    prefs = _addon_preferences()
    if prefs is None:
        return []
    try:
        text = prefs.protected_folders
    except Exception:
        return []
    return [os.path.expanduser(p.strip()) for p in text.split(";") if p.strip()]


# --- static tree, per-map filter, icons ------------------------------------------------------
_cache = {"provider": None, "tree": None, "groups": [], "leaves": [], "numbers": {}, "leaf_icons": {},
          "items": {}, "names": {}, "quota": {}}


def _icon_for(group_name, inherited):
    return GROUP_ICONS.get(group_name, inherited)


def _load_tree():
    P = provider.get_provider()
    if _cache["provider"] is P and _cache["tree"] is not None:
        return _cache
    tree = provider.browser_tree()
    groups = []                                  # [(node, icon)] in preorder, root excluded; index = menu number
    leaves = []                                  # [(name, icon)] in tree order (groups first, then leaves)

    def walk(node, icon):
        # a leaf wears the icon of the group that holds it; a group wears its own, else its parent's
        for child in node.get("groups", []):
            child_icon = _icon_for(child.get("name", ""), icon)
            groups.append((child, child_icon))
            walk(child, child_icon)
        for leaf in node.get("leaves", []):
            leaves.append((leaf["name"] if isinstance(leaf, dict) else leaf, icon))

    walk(tree, DEFAULT_ICON)
    _cache.update(provider=P, tree=tree, groups=groups, leaves=leaves,
                  numbers=dict((id(node), i) for i, (node, _icon) in enumerate(groups)),
                  leaf_icons=dict(leaves), items={}, names={}, quota={})
    return _cache


def tree():
    """The palette tree document (cached per provider)."""
    return _load_tree()["tree"]


def groups():
    """``[(node, icon)]`` of every group in preorder (the menu number is the index)."""
    return _load_tree()["groups"]


def group_number(node):
    return _load_tree()["numbers"].get(id(node))


def leaf_entries():
    """``[(display name, icon)]`` of every leaf of the tree."""
    return _load_tree()["leaves"]


def leaf_icon(name):
    """Icon of a leaf (the icon of the group that holds it)."""
    return _load_tree()["leaf_icons"].get(name, DEFAULT_ICON)


def stock_names(map_name):
    """Set of the display names valid on ``map_name`` (cached); empty for an unknown map."""
    cache = _load_tree()
    names = cache["names"].get(map_name)
    if names is None:
        names = frozenset(provider.get_provider().stock_object_names(map_name))
        cache["names"][map_name] = names
    return names


def names_within_quota(map_name, names, quota_count):
    """``(kept, hid_a_leaf)``: the members of ``names`` whose palette folder is below ``quota_count`` (cached), and
    whether that removed an entry of the Add menu tree.

    A stock object on ``map_name`` whose folder (``id >> 8``) is at or beyond the quota count of the loaded
    template cannot be exported to that file (``E_FOLDER_RANGE``: the file defines no quota row for it), so it is
    not offered. A name the tables cannot place (should not happen) stays visible. ``quota_count`` <= 0 means unknown.
    """
    if quota_count <= 0:
        return names, False
    cache = _load_tree()["quota"]
    key = (map_name, int(quota_count))
    found = cache.get(key)
    if found is None:
        keep = []
        for name in names:
            folder = provider.object_folder(map_name, name)
            if folder is None or folder < quota_count:
                keep.append(name)
        kept = frozenset(keep)
        hid = any(leaf in names and leaf not in kept for leaf, _icon in leaf_entries())
        found = cache[key] = (kept, hid)
    return found


def visible_names(scene):
    """``(names, note)``: the set of leaf names to show (``None`` = all) and an optional one-line note.

    No template in the scene -> everything with :data:`NO_FILTER_NOTE`; a template on a map that is not
    in the stock table -> everything with :data:`UNKNOWN_MAP_NOTE`; otherwise the stock names of the map,
    without the entries whose palette folder lies beyond the template's quota count (:data:`QUOTA_NOTE`
    says so when an entry of the menu was left out).
    """
    if not state.has_map(scene):
        return None, NO_FILTER_NOTE
    map_name = state.map_name(scene)
    names = stock_names(map_name) if map_name else frozenset()
    if not names:
        return None, UNKNOWN_MAP_NOTE
    quota_count = state.quota_count(scene)
    native_count = provider.available_palette_count(state.template_bytes(scene))
    if native_count is not None and native_count > quota_count:
        within, _hid = names_within_quota(map_name, names, native_count)
        return within, ("Export can extend this template's %d entries to the full %d-entry native palette"
                        % (quota_count, native_count))
    within, hid = names_within_quota(map_name, names, quota_count)
    return within, (QUOTA_NOTE % quota_count if hid else None)


def count_visible(node, names):
    """Number of leaves under ``node`` that pass the filter (``names=None`` shows all)."""
    total = 0
    for leaf in node.get("leaves", []):
        name = leaf["name"] if isinstance(leaf, dict) else leaf
        if names is None or name in names:
            total += 1
    for child in node.get("groups", []):
        total += count_visible(child, names)
    return total


def search_items(scene):
    """Enum items for the search popup: the visible leaves with their group icon (cached list, stable numbers)."""
    cache = _load_tree()
    names, _note = visible_names(scene)
    key = None if names is None else tuple(sorted(names))
    items = cache["items"].get(key)
    if items is None:
        items = []
        for number, (name, icon) in enumerate(cache["leaves"]):
            if names is None or name in names:
                items.append((name, name, "", icon, number))
        if not items:
            items = [("NONE", "No objects", "")]
        cache["items"][key] = items
    return items


# --- registration ---------------------------------------------------------------------------
_classes = (MjolnirPreferences,)
_registered = False


def register():
    global _registered
    if _registered:
        unregister()
    for cls in _classes:
        bpy.utils.register_class(cls)
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)
    _registered = True


def unregister():
    global _registered
    while _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    for cls in reversed(_classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    _registered = False
