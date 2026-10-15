"""Stub provider: lets the Blender glue (G4) be built and tested before the codec exists (SPEC section 11).

Exposes exactly the names of ``Addon/mvarlib/api.py``: the dataclasses, options and error classes
are imported from ``api.py`` (never redefined), the five data/path helpers are the real G0
functions re-exported, and the two entry points are replaced by canned behaviour:

* ``load_map_variant(data, name="", options=None)`` ignores the bytes except for their SHA-256 and
  returns ``CANNED`` (a Forge World map with five objects), or the controls below.
* ``export_map_variant(template, objects, options)`` records its arguments in ``LAST_EXPORT`` and
  returns ``ok=True`` with ``data=template`` and a naive diff, unless ``NEXT_EXPORT`` is set.

Controls (module attributes, set by the tests; ``reset()`` clears them all)::

    LAST_EXPORT      (template, objects, options) of the last export_map_variant() call
    NEXT_EXPORT      an ExportResult returned (and cleared) by the next export call: inject refusals
    NEXT_LOAD_ERROR  an MvarError raised (and cleared) by the next load call
    NEXT_LOAD        a LoadResult returned (and cleared) by the next load call (CANNED_EXTREMES, ...)
    LAST_LOAD        (data, name, options) of the last load call (extra, for assertions)

Canned data (all synthetic, no game data; ids and names come from the real G0 stock tables):

    CANNED               Forge World (id 3006), bounds -240..240, -345..345, -70..70, quota_count 80,
                         version 31, labels SCALE / Kill Boundary / Spawn, five objects: slot 1
                         ``Block, 1x1`` (vertical, yaw 0), slot 2 ``Assault Rifle`` (no model; cached
                         type 1, other_a 3), slot 5 ``Kill Boundary`` (box shape, label 1, cached type
                         26), slot 9 ``Block, 1x1`` (tilted), slot 11 ``Initial Loadout Camera`` (so
                         the camera-child path runs). Every record carries a distinct raw/raw_bits token.
    CANNED_BY_MAP        {3006: <Forge World>, 1080: <Boneyard>} for the per-map Add-menu filter
    CANNED_EXTREMES      shape 1 (sphere) with width 200, spawn sequence -128 and 127, team none,
                         placement byte 0xFF, label none, parent set
    CANNED_PLACEMENT_ALL 256 objects, one per placement byte 0x00..0xFF (decoded with the file
                         reading of SPEC 3.9; physics keeps the raw 2-bit value, so 2 occurs)

``IS_STUB`` is True. Inside Blender the real library is ``<extension>.mvarlib`` while this stub
imports the repository copy as ``mvarlib``: two module identities, which is why the glue builds
api objects through the provider and never uses ``isinstance`` on them.
"""
import dataclasses
import hashlib
import importlib.util
import math
import os
import sys

_ADDON = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "Addon")
if importlib.util.find_spec("mvarlib") is None:       # tests insert Addon/ themselves; this only helps stand-alone use
    sys.path.append(_ADDON)                           # appended, never inserted first: it must not shadow anything

from mvarlib.api import *                                   # noqa: E402,F401,F403  (dataclasses, errors, 5 helpers)
from mvarlib.api import __all__ as _API_ALL                 # noqa: E402
from mvarlib import tables as _tables                       # noqa: E402

IS_STUB = True

LAST_EXPORT = None
NEXT_EXPORT = None
NEXT_LOAD_ERROR = None
NEXT_LOAD = None
LAST_LOAD = None

CAPACITY_BITS = 0x7000 * 8


# --- building blocks ---------------------------------------------------------------------------
def decode_placement(byte):
    """Decoded view of a placement byte with the FILE reading of SPEC 3.9 (physics kept raw)."""
    return {
        "physics": (byte >> 6) & 3,
        "symmetry": (byte >> 2) & 3,
        "place_at_start": not (byte & 0x10),
        "game_specific": bool(byte & 0x20),
    }


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _forward_for_yaw(yaw):
    return (math.cos(yaw), math.sin(yaw), 0.0)


def _tilted_pair():
    up = _unit((0.3, -0.2, 0.9))
    dot = up[0]                                              # X . up
    fwd = _unit((1.0 - dot * up[0], -dot * up[1], -dot * up[2]))
    return fwd, up


def make_record(slot, map_name, type_name, position=(0.0, 0.0, 0.0), forward=None, up=None, **overrides):
    """Build one ``ObjectRecord`` for ``type_name`` on ``map_name`` (ids from the real stock table)."""
    type_id = _tables.object_id_for_name(map_name, type_name)
    if type_id is None:
        raise KeyError("%r is not a stock object on %r" % (type_name, map_name))
    placement = overrides.pop("placement", 0x0C)
    view = decode_placement(placement)
    bits = overrides.pop("raw_bits", 128 + slot % 100)     # a slot is at most 235 bits (SPEC 3.6)
    fields = dict(
        slot=slot, folder=type_id >> 8, item=type_id & 0xFF, type_id=type_id, type_name=type_name, stock=True,
        position=tuple(float(c) for c in position),
        forward=tuple(forward) if forward is not None else (1.0, 0.0, 0.0),
        up=tuple(up) if up is not None else (0.0, 0.0, 1.0),
        orientation_kind="vertical", parent_slot=-1,
        shape=0, width=0.0, length=0.0, top=0.0, bottom=0.0,
        spawn_sequence=0, spawn_time=0, cached_type=0, label_index=-1,
        placement=placement, physics=view["physics"], symmetry=view["symmetry"],
        place_at_start=view["place_at_start"], game_specific=view["game_specific"],
        team=8, color=-1, other_a=0, other_b=0, flags2=1,
        raw=bytes([slot & 0xFF, (slot >> 8) & 0xFF, 0xA5] + [(slot * 31 + i * 7) & 0xFF for i in range((bits + 7) // 8 - 3)]),
        raw_bits=bits,
    )
    fields.update(overrides)
    return ObjectRecord(**fields)


def _info(map_id, map_name, bounds, quota_count, labels, occupied, title):
    return MapInfo(
        map_id=map_id, map_name=map_name, is_stock_map=True, bounds=bounds,
        quota_count=quota_count, version=31, title=title,
        description="Canned stub data for tests. Synthetic: not game data.",
        labels=list(labels), label_present=[True] * len(labels),
        occupied=occupied, shape="plain4", template_sha256="", hash_flavour="salted_be32/>",
        palette_crc=0xDEADBEEF, max_budget_raw=30000, spent_budget_raw=123,
        hypothesis={"type19": "undetermined", "axis_bits": [20, 21, 19], "guid": False, "length_class": "ceil_end"},
        warnings=[],
    )


def _result(info, objects):
    return LoadResult(info=info, objects=list(objects), warnings=[])


_FW_BOUNDS = (-240.0, 240.0, -345.0, 345.0, -70.0, 70.0)
_FW = "Forge World"
_TILT_FWD, _TILT_UP = _tilted_pair()

CANNED = _result(
    _info(3006, _FW, _FW_BOUNDS, 80, ["SCALE", "Kill Boundary", "Spawn"], 5, "Canned Forge World"),
    [
        make_record(1, _FW, "Block, 1x1", (10.0, 20.0, 5.0), placement=0xCC),
        make_record(2, _FW, "Assault Rifle", (-15.5, 3.25, 1.0), cached_type=1, other_a=3),
        make_record(5, _FW, "Kill Boundary", (0.0, 100.0, 12.0), shape=3, width=20.0, length=15.0, top=10.0,
                    bottom=5.0, label_index=1, cached_type=26, team=-1),
        make_record(9, _FW, "Block, 1x1", (-60.0, -80.0, 20.0), forward=_TILT_FWD, up=_TILT_UP,
                    orientation_kind="tilted", placement=0xCC),
        make_record(11, _FW, "Initial Loadout Camera", (5.0, -5.0, 3.0), cached_type=27),
    ],
)

_BY = "Boneyard"
CANNED_BONEYARD = _result(
    _info(1080, _BY, (-100.0, 100.0, -120.0, 120.0, -30.0, 30.0), 80, ["SCALE", "Spawn"], 3, "Canned Boneyard"),
    [
        make_record(1, _BY, "Assault Rifle", (1.0, 2.0, 3.0), cached_type=1, other_a=2),
        make_record(2, _BY, "Kill Boundary", (0.0, 0.0, 5.0), shape=3, width=10.0, length=10.0, top=5.0,
                    bottom=5.0, label_index=0, cached_type=26, team=-1),
        make_record(3, _BY, "Initial Loadout Camera", (4.0, 4.0, 2.0), cached_type=27),
    ],
)

CANNED_BY_MAP = {3006: CANNED, 1080: CANNED_BONEYARD}

CANNED_EXTREMES = _result(
    _info(3006, _FW, _FW_BOUNDS, 80, ["SCALE", "Kill Boundary", "Spawn"], 3, "Canned extremes"),
    [
        # shape 1 (radius only) with the maximum dimension, lowest signed spawn sequence, no team, every
        # placement bit set, no label
        make_record(1, _FW, "Block, 1x1", (0.0, 0.0, 0.0), shape=1, width=200.0, spawn_sequence=-128, spawn_time=255,
                    team=-1, color=-1, label_index=-1, placement=0xFF, cached_type=0),
        # highest signed spawn sequence, colour 7, a parent link to slot 1, a label
        make_record(2, _FW, "Block, 1x1", (1.0, 1.0, 1.0), spawn_sequence=127, team=0, color=7, label_index=0,
                    parent_slot=1, placement=0x00),
        # box with the maximum dimensions
        make_record(3, _FW, "Kill Boundary", (2.0, 2.0, 2.0), shape=3, width=200.0, length=200.0, top=200.0,
                    bottom=0.0, cached_type=26, team=8, color=-1, label_index=2, parent_slot=2),
    ],
)

CANNED_PLACEMENT_ALL = _result(
    _info(3006, _FW, _FW_BOUNDS, 80, ["SCALE", "Kill Boundary", "Spawn"], 256, "Canned placement bytes"),
    [make_record(b, _FW, "Block, 1x1", (-150.0 + (b % 16) * 20.0, -150.0 + (b // 16) * 20.0, 0.0), placement=b)
     for b in range(256)],
)


# --- controls and the two entry points ---------------------------------------------------------
def reset():
    """Clear every control attribute."""
    global LAST_EXPORT, NEXT_EXPORT, NEXT_LOAD_ERROR, NEXT_LOAD, LAST_LOAD
    LAST_EXPORT = None
    NEXT_EXPORT = None
    NEXT_LOAD_ERROR = None
    NEXT_LOAD = None
    LAST_LOAD = None


def preset_refusal(*issues):
    """Make the next ``export_map_variant`` call refuse with these ``Issue`` objects."""
    global NEXT_EXPORT
    NEXT_EXPORT = ExportResult(ok=False, data=None, diff=[], errors=list(issues), warnings=[], stats={})


def _fresh(result, data):
    """Copy a canned result so tests cannot mutate module data; fill an empty template hash."""
    info = result.info
    if not info.template_sha256:
        info = dataclasses.replace(info, template_sha256=hashlib.sha256(bytes(data)).hexdigest())
    info = dataclasses.replace(info, labels=list(info.labels), label_present=list(info.label_present),
                               hypothesis=dict(info.hypothesis), warnings=list(info.warnings))
    return dataclasses.replace(result, info=info, objects=list(result.objects), warnings=list(result.warnings))


def load_map_variant(data, name="", options=None):
    """Return ``NEXT_LOAD`` / ``CANNED`` (ignores the bytes except for their SHA-256), or raise ``NEXT_LOAD_ERROR``."""
    global NEXT_LOAD, NEXT_LOAD_ERROR, LAST_LOAD
    LAST_LOAD = (data, name, options)
    if NEXT_LOAD_ERROR is not None:
        error, NEXT_LOAD_ERROR = NEXT_LOAD_ERROR, None
        raise error
    result = CANNED
    if NEXT_LOAD is not None:
        result, NEXT_LOAD = NEXT_LOAD, None
    return _fresh(result, data)


def export_map_variant(template, objects, options):
    """Record the arguments; return ``NEXT_EXPORT`` if set, else ``ok=True`` with ``data=template`` and a naive diff."""
    global LAST_EXPORT, NEXT_EXPORT
    objects = list(objects)
    LAST_EXPORT = (template, objects, options)
    if NEXT_EXPORT is not None:
        result, NEXT_EXPORT = NEXT_EXPORT, None
        return result
    diff = [DiffEntry(kind="added" if o.slot is None else "kept", slot=o.slot, name=o.name, detail="stub")
            for o in objects]
    claimed = sum(1 for o in objects if o.slot is not None)
    stats = {
        "occupied_before": claimed, "occupied_after": len(objects), "end_bit": 0, "capacity_bits": CAPACITY_BITS,
        "L": 0, "hash_flavour": "stub", "quota_changes": {}, "mode": "passthrough",
    }
    return ExportResult(ok=True, data=bytes(template), diff=diff, errors=[], warnings=[], stats=stats)
