"""A stub provider that REMEMBERS what it was asked to write (S1 preparation; a test double, not a codec).

``stub_mvarlib.py`` returns canned data for every file and its export hands back the template unchanged, so a
pipeline that exports and then re-imports (``tools/build_star_mvar.py``) can never see its own blocks again. This
module wraps it: ``export_map_variant`` appends the added objects to the template as a small JSON payload (after
the marker ``MAGIC``) and ``load_map_variant`` turns such a payload back into ``ObjectRecord`` objects next to the
canned ones. It is NOT the map variant format and it carries no game data. Everything else (the data classes, the
error classes, the five G0 helpers, ``LAST_EXPORT``, ``NEXT_EXPORT``, ``NEXT_LOAD``, ``reset()``) is the plain
stub's, so a test reads ``stub_mvarlib.LAST_EXPORT`` as usual.

What it checks on export (a small, honest subset of SPEC 7.3, so the glue and the star script meet refusals that
look like the real library's): ``E_ROTATION_GATED`` (new objects need ``allow_unverified_rotation``),
``E_OBJ_NAME_UNKNOWN``, ``E_OUT_OF_BOUNDS`` (the ``[min, max)`` rule), ``E_FLAG_UNVERIFIED`` (symmetry, place at
start, game specific must equal the learned example's, SPEC 5.6), ``E_QUOTA`` (``QUOTA_MAX``), ``E_TOO_MANY``,
``E_NO_FREE_SLOT``. Positions are quantised to ``QUANT`` like the real cell-centre codec (error <= QUANT / 2).

Controls (module attributes, cleared by ``reset()``)::

    CORRUPT    None, or one of 'drop', 'shift', 'touch_original', 'physics', 'type', 'extra', 'flavour': makes the
               NEXT export write a deliberately wrong file, so a verifier can be shown to catch each mistake
    QUOTA_MAX  {type name: maximum placed}, counted over the template plus the new objects of that type
    QUANT      position quantum (default 0.0005)

Template flavours (the stub ignores the bytes except for their prefix): ``map_template(map_id)`` returns bytes
that load as that canned map (``CANNED_BY_MAP``); ``ODD_EXAMPLE_TEMPLATE`` loads as Forge World whose only
``Block, 1x1`` has symmetry ASYMMETRIC, place-at-start off and game-specific on, so a new block must copy those
flags or be refused with ``E_FLAG_UNVERIFIED``; ``NO_BLOCKS_TEMPLATE`` loads as Forge World without any block;
``real_like_template(count)`` loads as a synthetic Breakneck shaped like the one real file seen so far (610 objects of
a few spawn / flag / grenade types and no block, bounds +-20000 on every axis, so a position cell is 40000 / 2**23 =
0.0048): synthetic numbers only, no game data.
"""
import dataclasses
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.append(_HERE)

import stub_mvarlib as _base                                    # noqa: E402  (this module's parent; sets up the mvarlib path)
from mvarlib.api import *                                       # noqa: E402,F401,F403
from mvarlib import tables as _tables                           # noqa: E402

IS_STUB = True
ROUNDTRIP = True
MAGIC = b"\n--STUB-ROUNDTRIP-PAYLOAD--\n"
MAP_PREFIX = b"STUB-MAP:"
ODD_EXAMPLE_TEMPLATE = b"STUB-ODD-EXAMPLE:forge-world"
NO_BLOCKS_TEMPLATE = b"STUB-NO-BLOCKS:forge-world"
REAL_LIKE_PREFIX = b"STUB-REAL-LIKE:"
MAX_SLOT = 650                                                  # slots 0..650 exist (651 records)

CORRUPT = None
QUOTA_MAX = {}
QUANT = 0.0005

_PLACEMENT_FIXED = 0x4C                                         # physics 1, symmetry both, place at start, not game specific


def reset():
    """The plain stub's controls plus this module's."""
    global CORRUPT, QUOTA_MAX, QUANT
    _base.reset()
    CORRUPT = None
    QUOTA_MAX = {}
    QUANT = 0.0005


def map_template(map_id):
    """Template bytes that load as the canned map ``map_id`` (3006 Forge World, 1080 Boneyard)."""
    if map_id not in _base.CANNED_BY_MAP:
        raise KeyError("no canned map %r" % (map_id,))
    return MAP_PREFIX + str(map_id).encode("ascii") + b":" + b"template"


def _odd_example_result():
    canned = _base.CANNED
    objects = []
    for rec in canned.objects:
        if rec.type_name == "Block, 1x1" and rec.slot == 1:
            # symmetry ASYMMETRIC (1), place at start OFF, game specific ON, physics normal
            placement = (0 << 6) | (1 << 2) | 0x10 | 0x20
            view = _base.decode_placement(placement)
            rec = dataclasses.replace(rec, placement=placement, physics=view["physics"], symmetry=view["symmetry"],
                                      place_at_start=view["place_at_start"], game_specific=view["game_specific"])
        objects.append(rec)
    return dataclasses.replace(canned, objects=objects)


def real_like_template(count=610):
    """Template bytes that load as a synthetic Breakneck with ``count`` objects, none of them a block."""
    return REAL_LIKE_PREFIX + str(int(count)).encode("ascii")


def _real_like_result(count):
    types = [("Respawn Point", 15, 0.40), ("Initial Spawn", 15, 0.18), ("Flag Stand", 16, 0.08), ("Hill Marker", 16, 0.04),
             ("Frag Grenade", 7, 0.27), ("Health Station", 2, 0.02)]
    seed = 12345
    objects = []
    for slot in range(count):
        seed = (seed * 1103515245 + 12345) % (1 << 31)
        pick = (seed >> 8) / float(1 << 23)
        name, cached = types[-1][0], types[-1][1]
        total = 0.0
        for type_name, cached_type, share in types:
            total += share
            if pick < total:
                name, cached = type_name, cached_type
                break
        seed = (seed * 1103515245 + 12345) % (1 << 31)
        x = -29.0 + 58.0 * ((seed >> 8) / float(1 << 23))
        seed = (seed * 1103515245 + 12345) % (1 << 31)
        y = -29.0 + 58.0 * ((seed >> 8) / float(1 << 23))
        seed = (seed * 1103515245 + 12345) % (1 << 31)
        z = 2.1 + 19.6 * ((seed >> 8) / float(1 << 23)) ** 2
        objects.append(_base.make_record(slot, "Breakneck", name, (x, y, z), cached_type=cached))
    info = _base._info(10050, "Breakneck", (-20000.0, 20000.0, -20000.0, 20000.0, -20000.0, 20000.0), 82,
                       ["SCALE", "Spawn"], count, "Synthetic Breakneck")
    info = dataclasses.replace(info, hash_flavour="plain_le32/>")
    return _base.LoadResult(info=info, objects=objects, warnings=[])


def _no_blocks_result():
    canned = _base.CANNED
    kept = [r for r in canned.objects if not r.type_name.startswith("Block")]
    return dataclasses.replace(canned, objects=kept, info=dataclasses.replace(canned.info, occupied=len(kept)))


def _canned_for(template, consume):
    """The canned ``LoadResult`` for template bytes; ``consume`` honours (and clears) ``NEXT_LOAD`` like the plain stub."""
    if consume and _base.NEXT_LOAD is not None:
        result, _base.NEXT_LOAD = _base.NEXT_LOAD, None
        return result
    if template.startswith(MAP_PREFIX):
        map_id = int(template[len(MAP_PREFIX):].split(b":", 1)[0])
        return _base.CANNED_BY_MAP[map_id]
    if template.startswith(ODD_EXAMPLE_TEMPLATE):
        return _odd_example_result()
    if template.startswith(NO_BLOCKS_TEMPLATE):
        return _no_blocks_result()
    if template.startswith(REAL_LIKE_PREFIX):
        return _real_like_result(int(template[len(REAL_LIKE_PREFIX):].split(b":", 1)[0]))
    return _base.CANNED


def _split(data):
    data = bytes(data)
    cut = data.rfind(MAGIC)
    if cut < 0:
        return data, None
    return data[:cut], json.loads(data[cut + len(MAGIC):].decode("ascii"))


def _quantise(value, low, quant):
    return low + (math.floor((value - low) / quant) + 0.5) * quant


def _cell(info, axis):
    """Position cell size on an axis: at least ``QUANT``, and ``range / 2**23`` for a huge range (the 23-bit cap)."""
    return max(QUANT, (info.bounds[2 * axis + 1] - info.bounds[2 * axis]) / 8388608.0)


def _record(slot, map_name, entry):
    return _base.make_record(slot, map_name, entry["type_name"], tuple(entry["position"]),
                             forward=tuple(entry["forward"]), up=tuple(entry["up"]),
                             placement=entry["placement"], cached_type=entry["cached_type"])


def load_map_variant(data, name="", options=None):
    """The canned map the template prefix names, plus the objects of a round-trip payload."""
    _base.LAST_LOAD = (data, name, options)
    if _base.NEXT_LOAD_ERROR is not None:
        error, _base.NEXT_LOAD_ERROR = _base.NEXT_LOAD_ERROR, None
        raise error
    template, payload = _split(data)
    canned = _canned_for(template, consume=True)
    result = _base._fresh(canned, data)
    if payload is None:
        return result
    info = result.info
    records = dict((r.slot, r) for r in result.objects)
    for entry in payload["objects"]:                                 # an entry on a taken slot replaces that record
        records[entry["slot"]] = _record(entry["slot"], info.map_name, entry)
    flavour = payload.get("flavour") or info.hash_flavour
    info = dataclasses.replace(info, occupied=len(records), hash_flavour=flavour)
    return dataclasses.replace(result, info=info, objects=[records[s] for s in sorted(records)])


def _issue(code, message, name=None):
    return Issue(code=code, severity="error", message=message, slot=None, object_name=name)


def export_map_variant(template, objects, options):
    """Record the call (plain stub), validate a few rules, return the template with the new objects appended."""
    objects = list(objects)
    refusal = _base.export_map_variant(template, objects, options)        # records LAST_EXPORT, honours NEXT_EXPORT
    if not refusal.ok:
        return refusal
    base_template, previous = _split(template)
    canned = _canned_for(base_template, consume=False)
    info = canned.info
    existing = list(canned.objects)
    if previous is not None:
        existing += [_record(e["slot"], info.map_name, e) for e in previous["objects"]]
    taken = set(r.slot for r in existing)
    new = sorted((o for o in objects if o.slot is None), key=lambda o: o.name)
    errors = []
    stock = set(_tables.stock_object_names(info.map_name))
    if new and not options.allow_unverified_rotation:
        errors.append(_issue("E_ROTATION_GATED", "Object '%s' has a new or changed rotation. Writing rotation is "
                             "unverified: tick Forge Scene > \"Allow unverified rotation export\" to write it." % new[0].name,
                             new[0].name))
    for obj in new:
        if obj.type_name not in stock:
            errors.append(_issue("E_OBJ_NAME_UNKNOWN", "Object '%s' uses '%s', which is not a stock object on %s." % (
                obj.name, obj.type_name, info.map_name), obj.name))
            continue
        for axis in range(3):
            low, high = info.bounds[2 * axis], info.bounds[2 * axis + 1]
            if not low <= obj.position[axis] < high:
                errors.append(_issue("E_OUT_OF_BOUNDS", "Object '%s' is at (%.3f, %.3f, %.3f), outside the map bounds "
                                     "(x %.1f to %.1f, y %.1f to %.1f, z %.1f to %.1f). Move it inside; positions are "
                                     "never clamped." % ((obj.name,) + tuple(obj.position) + tuple(info.bounds)), obj.name))
                break
        example = next((r for r in existing if r.type_name == obj.type_name), None)
        base_flags = ((example.symmetry, example.place_at_start, example.game_specific) if example is not None
                      else (3, True, False))
        flags = (obj.symmetry, obj.place_at_start, obj.game_specific)
        if flags != base_flags:
            errors.append(_issue("E_FLAG_UNVERIFIED", "Object '%s': symmetry, place at start or game specific cannot be "
                                 "changed yet; how it is stored is unverified." % obj.name, obj.name))
    for type_name, limit in sorted(QUOTA_MAX.items()):
        placed = sum(1 for r in existing if r.type_name == type_name) + sum(1 for o in new if o.type_name == type_name)
        if placed > limit and any(o.type_name == type_name for o in new):
            errors.append(_issue("E_QUOTA", "Palette entry 0 (%s) would have %d placed; the maximum on this map variant "
                                 "is %d." % (type_name, placed, limit)))
    total = len(existing) + len(new)
    if total > options.max_objects:
        errors.append(_issue("E_TOO_MANY", "%d objects would be written; the limit is %d. Remove %d object(s). (A file "
                             "that already holds more than %d objects cannot be exported.)" % (
                                 total, options.max_objects, total - options.max_objects, options.max_objects)))
    free = [s for s in range(MAX_SLOT + 1) if s not in taken]
    if len(new) > len(free):
        errors.append(_issue("E_NO_FREE_SLOT", "No free object slot is left for '%s'." % new[len(free)].name))
    if errors:
        return ExportResult(ok=False, data=None, diff=[], errors=errors, warnings=[], stats={})

    entries = list(previous["objects"]) if previous is not None else []
    for obj, slot in zip(new, free):
        example = next((r for r in existing if r.type_name == obj.type_name), None)
        entries.append({
            "slot": slot, "type_name": obj.type_name, "name": obj.name,
            "position": [_quantise(obj.position[a], info.bounds[2 * a], _cell(info, a)) for a in range(3)],
            "forward": list(obj.forward), "up": list(obj.up),
            "placement": (_PLACEMENT_FIXED & 0x3F) | (int(obj.physics) << 6),
            "cached_type": example.cached_type if example is not None else 0,
        })
    flavour = None
    if CORRUPT == "drop" and entries:
        entries.pop()
    elif CORRUPT == "shift" and entries:
        entries[-1]["position"][0] += 0.05
    elif CORRUPT == "physics":
        for entry in entries:
            entry["placement"] = (entry["placement"] & 0x3F) | (3 << 6)
    elif CORRUPT == "type" and entries:
        other = next(n for n in sorted(stock) if n.startswith("Block") and n != entries[-1]["type_name"])
        entries[-1]["type_name"] = other
    elif CORRUPT == "extra":
        entries.append(dict(entries[-1], slot=next(s for s in free if s not in [e["slot"] for e in entries]),
                            position=[entries[-1]["position"][0] + 20.0] + entries[-1]["position"][1:]))
    elif CORRUPT == "flavour":
        flavour = "plain_le32/>"
    payload = {"objects": entries, "flavour": flavour}
    out = bytes(base_template) + MAGIC + json.dumps(payload, sort_keys=True).encode("ascii")
    if CORRUPT == "touch_original":
        payload["objects"].append({"slot": min(taken), "type_name": existing[0].type_name, "name": "tamper",
                                   "position": [0.0, 0.0, 0.0], "forward": [1.0, 0.0, 0.0], "up": [0.0, 0.0, 1.0],
                                   "placement": 0x0C, "cached_type": 0})
        out = bytes(base_template) + MAGIC + json.dumps(payload, sort_keys=True).encode("ascii")
    diff = [DiffEntry(kind="added" if o.slot is None else "kept", slot=o.slot, name=o.name, detail="stub round trip")
            for o in objects]
    stats = {"occupied_before": len(existing), "occupied_after": len(existing) + len(new),
             "end_bit": 0, "capacity_bits": _base.CAPACITY_BITS, "L": 0, "hash_flavour": info.hash_flavour,
             "quota_changes": {}, "mode": "patched"}
    return ExportResult(ok=True, data=out, diff=diff, errors=[], warnings=[], stats=stats)
