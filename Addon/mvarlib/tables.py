"""Static data tables of ``mvarlib`` (SPEC 6.1, 7.1). Delivered complete in G0; needs no format knowledge.

Reads the JSON files in ``data/`` lazily on first use (never at import, so ``register()`` stays
free of I/O, SPEC 8.2) and caches the parsed tables for the life of the process. Every function
returns fresh lists/dicts, so callers may modify what they get.

``data/maps.json``           the 20 stock maps: id, name, source           (``tools/gen_stock_tables.py``)
``data/stock_objects.json``  per map ``[type_id, internal_type, display_name]``, plus ``disputed`` ids
                             (``tools/gen_stock_tables.py``, from ``Addon/objects.py``)
``data/cached_type_hints.json``  ``assumed_zero_groups`` and ``known_classes`` (SPEC 7.4); hints only
``data/palette_tree.json``   palette group tree, names only (G0 commits the empty tree
                             ``{"groups": []}``; ``tools/gen_palette_tree.py`` in G4 generates the content)

Object ids: ``type_id = (folder << 8) | item`` with an 8-bit folder and a 5-bit item (SPEC 0.3).
Display names are unique per map but not globally (the "Sprint" collision), so every lookup
by name takes the map name. Unknown maps and unknown ids give ``None`` / ``[]``, never an exception.

Palette tree convention (the part of the tree format fixed in G0 so the sync test U-15 can walk
it): a node is a dict with a ``name`` and optional ``groups`` (child nodes) and ``leaves`` (the
object display names of that group, each a string or a dict with a ``name``). The top level is
``{"groups": [node, ...]}``. G4 may add further keys (icons, ...) but keeps these.
"""
import copy
import json
import os

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

_cache = {}


def _load_json(filename, schema=None):
    path = os.path.join(_DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if schema is not None and data.get("schema") != schema:
        raise ValueError("%s: expected schema %r, found %r" % (path, schema, data.get("schema")))
    return data


def reset_cache():
    """Forget the parsed tables (tests; also useful after regenerating the data files)."""
    _cache.clear()


def _maps():
    if "maps" not in _cache:
        raw = _load_json("maps.json", "mvarlib.maps/1")
        entries = [dict(m) for m in raw["maps"]]
        _cache["maps"] = {
            "list": entries,
            "by_id": dict((m["id"], m["name"]) for m in entries),
            "by_name": dict((m["name"], m["id"]) for m in entries),
        }
    return _cache["maps"]


def _objects():
    if "objects" not in _cache:
        raw = _load_json("stock_objects.json", "mvarlib.stock_objects/1")
        per_map = {}
        for map_name, rows in raw["maps"].items():
            tuples = [(int(r[0]), r[1], r[2]) for r in rows]
            per_map[map_name] = {
                "rows": tuples,
                "by_id": dict((t[0], t) for t in tuples),
                "by_name": dict((t[2], t) for t in tuples),
            }
        _cache["objects"] = {"per_map": per_map,
                             "disputed": dict((k, [int(i) for i in v]) for k, v in raw.get("disputed", {}).items())}
    return _cache["objects"]


# --- maps ------------------------------------------------------------------------------------
def maps():
    """The stock maps as a list of ``{"id", "name", "source"}`` dicts, ascending by id."""
    return [dict(m) for m in _maps()["list"]]


def map_name_for_id(map_id):
    """Name of the stock map with this header ``mapID``, or ``None`` (also for non-stock ids)."""
    try:
        return _maps()["by_id"].get(map_id)
    except TypeError:
        return None


def map_id_for_name(map_name):
    """``mapID`` of the stock map with this name, or ``None``."""
    try:
        return _maps()["by_name"].get(map_name)
    except TypeError:
        return None


def stock_map_names():
    """The 20 stock map names, ascending by map id."""
    return [m["name"] for m in _maps()["list"]]


# --- stock objects ---------------------------------------------------------------------------
def _map_objects(map_name):
    try:
        return _objects()["per_map"].get(map_name)
    except TypeError:
        return None


def stock_objects(map_name):
    """``[(type_id, internal_type, display_name)]`` of a map, ascending by id; ``[]`` for unknown maps."""
    entry = _map_objects(map_name)
    return list(entry["rows"]) if entry else []


def stock_object_names(map_name):
    """Display names valid on that map, ascending by object id; ``[]`` for an unknown map."""
    return [row[2] for row in stock_objects(map_name)]


def object_name_for_id(map_name, type_id):
    """Display name of ``type_id`` on that map, or ``None``."""
    entry = _map_objects(map_name)
    row = entry["by_id"].get(type_id) if entry else None
    return row[2] if row else None


def internal_name_for_id(map_name, type_id):
    """Internal type name (``block_1x1``) of ``type_id`` on that map, or ``None``."""
    entry = _map_objects(map_name)
    row = entry["by_id"].get(type_id) if entry else None
    return row[1] if row else None


def object_id_for_name(map_name, display_name):
    """Object id of a display name on that map (names are unique per map), or ``None``."""
    entry = _map_objects(map_name)
    try:
        row = entry["by_name"].get(display_name) if entry else None
    except TypeError:
        row = None
    return row[0] if row else None


def is_stock_object(map_name, type_id):
    """True when ``type_id`` is in the stock table of that map."""
    entry = _map_objects(map_name)
    try:
        return bool(entry) and type_id in entry["by_id"]
    except TypeError:
        return False


def disputed_ids(map_name):
    """Ids on this map that the two upstream id tables disagree on (SPEC 7.1, X18); ``[]`` if none."""
    return list(_objects()["disputed"].get(map_name, []))


# --- palette tree and cached type hints ------------------------------------------------------
def palette_tree():
    """The palette group tree (names only). The G0 tree is empty: ``{"groups": []}``."""
    if "palette_tree" not in _cache:
        _cache["palette_tree"] = _load_json("palette_tree.json")
    return copy.deepcopy(_cache["palette_tree"])


def cached_type_hints():
    """``{"assumed_zero_groups": [...], "known_classes": {...}, ...}`` (SPEC 7.4)."""
    if "hints" not in _cache:
        _cache["hints"] = _load_json("cached_type_hints.json", "mvarlib.cached_type_hints/1")
    return copy.deepcopy(_cache["hints"])


def assumed_zero_groups():
    """Palette groups whose objects may be assumed to be cached type 0 (with a warning)."""
    return list(cached_type_hints()["assumed_zero_groups"])
