"""Shared helpers of the G5 tests (export planning, the write path, the bit-diff contract).

* ``objects_for(data_or_model, **per_slot_changes)`` builds the ``ExportObject`` list the Blender glue would hand over for
  an imported file: one per occupied slot, claiming it with its identity token, every value copied from the decoded record
  (a team of ``none`` is handed over as 8, a physics of 2 as it is), so an untouched list is the "unchanged objects" of
  SPEC 6.4. ``change(objs, slot, **fields)`` edits one of them; ``new_object(...)`` makes an unclaimed one.
* ``export(data, objects, **options)`` calls the library's ``export_map_variant``.
* ``decode(data)`` is the INDEPENDENT reading (the fixture builder's own walker, ``tests/fixturebuilder/selfcheck.py``): the
  expected bit ranges of the bit-diff contract (SPEC 5.9) come from there, never from the code under test.
* ``stream_diff`` / ``container_diff`` give the differing stream bits and the differing bytes outside the stream, and
  ``independent_hash`` recomputes a SHA-1 with ``hashlib`` and the walker's recipe table.

Everything works on bytes in memory; nothing is written to disk. Python 3.9 to 3.13, standard library only.
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for _path in (HERE, os.path.join(REPO, "Addon")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import helpers_g3 as g3  # noqa: E402

from mvarlib import api  # noqa: E402
from mvarlib.model import MapVariant  # noqa: E402

MVAR = 0x2F0                          # file offset of the mvar block in a plain4 file
HASH_AT = MVAR + 12                   # 20 bytes
LENGTH_AT = MVAR + 32                 # 4 bytes
STREAM_AT = MVAR + 36                 # the bit stream, 0x7000 bytes
STREAM_END = STREAM_AT + 0x7000
PAD_AT = STREAM_END                   # 4 pad bytes
STREAM_BITS = 0x7000 * 8
GATE = dict(allow_unverified_rotation=True)


def build_modules():
    return g3.build_modules()


# ---------------------------------------------------------------------------------------------
# ExportObject lists
# ---------------------------------------------------------------------------------------------
def export_object(rec, name=None, **fields):
    """The ``ExportObject`` the glue hands over for an imported ``ObjectRecord`` (unchanged unless ``fields`` say so)."""
    values = dict(
        name=name or "%d - %s" % (rec.slot, rec.type_name), slot=rec.slot, token_raw=rec.raw, token_bits=rec.raw_bits,
        name_matches_import=True, type_name=rec.type_name if rec.stock else "", type_id_hint=rec.type_id,
        position=rec.position, forward=rec.forward, up=rec.up, shape=rec.shape, width=rec.width, length=rec.length,
        top=rec.top, bottom=rec.bottom, spawn_sequence=rec.spawn_sequence, spawn_time=rec.spawn_time,
        cached_type=rec.cached_type, label_index=rec.label_index, physics=rec.physics, symmetry=rec.symmetry,
        place_at_start=rec.place_at_start, game_specific=rec.game_specific, team=8 if rec.team == -1 else rec.team,
        color=rec.color, other_a=rec.other_a, other_b=rec.other_b)
    values.update(fields)
    return api.ExportObject(**values)


def model_of(source):
    return source if isinstance(source, MapVariant) else MapVariant.from_bytes(source)


def objects_for(source, **_unused):
    """One unchanged ``ExportObject`` per occupied slot of ``source`` (bytes or a model), in slot order."""
    return [export_object(rec) for rec in model_of(source).objects()]


def by_slot(objects, slot):
    found = [o for o in objects if o.slot == slot]
    assert len(found) == 1, "no unique object for slot %r" % (slot,)
    return found[0]


def change(objects, slot, **fields):
    """Edit the object that claims ``slot`` (in place); returns it."""
    obj = by_slot(objects, slot)
    for key, value in fields.items():
        setattr(obj, key, value)
    return obj


def without(objects, *slots):
    """The list without the objects that claim these slots (a deletion)."""
    return [o for o in objects if o.slot not in slots]


def new_object(name, type_name="Block, 1x1", position=(0.0, 0.0, 0.0), forward=(1.0, 0.0, 0.0), up=(0.0, 0.0, 1.0), **fields):
    """An unclaimed object (a new one). Default forward +X is yaw 0 (raw angle 8192), like golden edit E2."""
    return api.ExportObject(name=name, slot=None, token_raw=None, token_bits=None, type_name=type_name, position=position,
                            forward=forward, up=up, **fields)


def new_like_example(source, type_name="Block, 1x1", name="New", position=(0.0, 0.0, 0.0), **fields):
    """A new object whose symmetry, place-at-start, game-specific, physics, team and colour equal the learned example's
    (SPEC 5.6), so that none of them counts as a change from the baseline; ``fields`` then override."""
    from mvarlib import codecs, edit, tables
    model = model_of(source)
    type_id = tables.object_id_for_name(model.map_name, type_name)
    example = edit.learn_example(model, type_id >> 8, type_id & 0xFF)
    if example is not None:
        (placement, team_raw, color), _slot = example
        view = codecs.placement_view(placement)
        values = dict(physics=view.physics, symmetry=view.symmetry, place_at_start=view.place_at_start,
                      game_specific=view.game_specific, team=8 if team_raw == 0 else team_raw - 1,
                      color=codecs.color_view(color))
        values.update(fields)
        fields = values
    return new_object(name, type_name, position, **fields)


def cell_centre(model, cells):
    """World position of the centre of position cells ``(qx, qy, qz)``."""
    from mvarlib import codecs
    b = model.fixed.bounds
    axes = model.hypothesis.axis_bits
    return tuple(codecs.pos_decode(cells[k], axes[k], b[2 * k], b[2 * k + 1]) for k in range(3))


def export(data, objects, **options):
    """``api.export_map_variant`` with ``ExportOptions(**options)``."""
    return api.export_map_variant(data, objects, api.ExportOptions(**options))


def codes(issues):
    return [i.code for i in issues]


def only(issues, code):
    found = [i for i in issues if i.code == code]
    return found


# ---------------------------------------------------------------------------------------------
# the independent reading and the bit-diff contract (SPEC 5.9)
# ---------------------------------------------------------------------------------------------
def decode(data):
    """The independent walker's decode of ``data`` (the ``decoded`` dict: slots, slot_ranges, slot_field_spans, sections, end, ...)."""
    _build, selfcheck = build_modules()
    res = selfcheck.read(data)
    assert res["outcome"] == "ok", res
    return res["decoded"]


def independent_hash(recipe, data):
    """The SHA-1 that ``recipe`` gives for the mvar block of ``data``, with ``hashlib`` and the walker's table, over the
    stream bytes up to the stored length (read from the file, both byte orders tried by the caller if needed)."""
    _build, selfcheck = build_modules()
    block = data[MVAR:MVAR + 0x7028]
    stream = block[36:36 + 0x7000]
    raw = block[32:36]
    length = struct.unpack(">I", raw)[0]
    if not 1 <= length <= 0x7000:
        length = struct.unpack("<I", raw)[0]
    return selfcheck.digest(recipe, stream, length)


def stream_bytes(data):
    return data[STREAM_AT:STREAM_END]


def stream_diff(a, b):
    """Stream bit positions (counted from stream bit 0) where two files differ."""
    x = int.from_bytes(stream_bytes(a), "big") ^ int.from_bytes(stream_bytes(b), "big")
    text = bin(x)[2:].zfill(STREAM_BITS)
    return [i for i, c in enumerate(text) if c == "1"]


def container_diff(a, b):
    """Byte offsets, outside the stream, where two files of the same length differ."""
    assert len(a) == len(b), (len(a), len(b))
    return [i for i in range(len(a)) if a[i] != b[i] and not STREAM_AT <= i < STREAM_END]


def in_ranges(position, ranges):
    return any(lo <= position < hi for lo, hi in ranges)


def slot_span(decoded, slot, field):
    """The ``(start, end)`` stream bits of one field of a present slot in the independent decode."""
    for name, a, b in decoded["slot_field_spans"][slot]:
        if name == field:
            return a, b
    raise KeyError(field)


def stored_length(data):
    raw = data[LENGTH_AT:LENGTH_AT + 4]
    return struct.unpack(">I", raw)[0]


def stored_hash(data):
    return data[HASH_AT:HASH_AT + 20]
