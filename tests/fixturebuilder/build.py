"""The independent, table-driven fixture builder (SPEC 9.1 T2, DEC-9.2, section 11 G2).

Turns a fixture *spec* (the JSON files in ``tests/golden/fixture_specs``) into the bytes of a synthetic Halo:
Reach map variant.  It is written from SPEC sections 2 to 4 and Appendix C only: it imports nothing from the
library under test, carries its own big-integer bit writer (``bits.py``) and its own literal tables
(``consts.py``), and is checked by a separately written walker (``selfcheck.py``).

Public API (all pure; nothing here writes into the repository except the golden JSON written by
``--write-specs``)::

    spec = load_spec("w1_minimal")           # the committed JSON spec
    built = build(spec)                      # Built: .data (bytes), .info (bookkeeping), .model (declared values)
    model = normalise(spec)                  # the declared values with every default filled in
    build_all(out_dir)                       # writes <name>.mvar for every committed spec (out_dir must be outside the repo)

Command line (Python 3.9 or 3.13, run with ``-I``)::

    python3 -I tests/fixturebuilder/build.py --out DIR [--only NAME ...]   # write the fixtures into DIR
    python3 -I tests/fixturebuilder/build.py --write-specs                 # regenerate the golden JSON from the catalogue
    python3 -I tests/fixturebuilder/build.py --check                       # committed JSON == catalogue, SHA-256s, determinism
    python3 -I tests/fixturebuilder/build.py --list

Spec format ``mjolnir.fixture_spec/1`` is documented in ``docs/mvar/notes/G2.md``.
"""
import copy
import hashlib
import json
import math
import os
import struct
import sys

if __package__:
    from . import bits, consts
else:                                                  # script mode: make the package importable under its real name
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from fixturebuilder import bits, consts

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(HERE)
REPO = os.path.dirname(TESTS_DIR)
GOLDEN_DIR = os.path.join(TESTS_DIR, "golden")
SPECS_DIR = os.path.join(GOLDEN_DIR, "fixture_specs")
SHA_FILE = os.path.join(GOLDEN_DIR, "fixture_sha256.json")
SHA_SCHEMA = "mjolnir.fixture_sha256/1"


class FixtureError(Exception):
    """The fixture description cannot be encoded (a bug in a spec, not in the code under test)."""


# =====================================================================================================
# Small helpers
# =====================================================================================================

def to_int(value):
    """Accepts an int, ``"0x..."`` or decimal text."""
    if isinstance(value, bool):
        raise FixtureError("expected an integer, got a boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise FixtureError("expected an integer, got %r" % (value,))


def hexs(value, width_bits=None):
    if width_bits is None:
        return "0x%X" % value
    return "0x%0*X" % (width_bits // 4, value)


def _endian_name(code):
    if code == ">":
        return "big"
    if code == "<":
        return "little"
    raise FixtureError("byte order must be '>' or '<', got %r" % (code,))


class Lcg(object):
    """A tiny deterministic generator for bulk fixtures (31-bit linear congruential)."""

    def __init__(self, seed):
        self.x = (int(seed) * 2654435761 + 12345) & 0x7FFFFFFF

    def next(self, mod):
        self.x = (self.x * 1103515245 + 12345) & 0x7FFFFFFF
        return (self.x >> 8) % mod


# =====================================================================================================
# Axis bit counts (SPEC 4.1): written here from the formulas, used to size the position fields
# =====================================================================================================

def _bits_from_cells(n):
    return 0 if n <= 1 else (n - 1).bit_length()


def axis_bits_one(rng, variant):
    """Bits for one axis range under one rounding variant (SPEC 4.1)."""
    f = bits.f32_round
    if variant == "ceil":                                  # JS: double precision, ceil
        step = consts.MIN_UNIT_16 / (1 << (consts.AXIS_BASE_BITS - 16))
        if step < consts.STEP_FLOOR:
            return consts.AXIS_MAX_BITS
        step *= 2
        n = min(consts.AXIS_MAX_CELLS, math.ceil(rng / step))
        return min(consts.AXIS_MAX_BITS, _bits_from_cells(n))
    if variant == "trunc9999":                             # HMS: float32 arithmetic, +0.9999, truncate
        step = f(f(f(consts.MIN_UNIT_16) / f(float(1 << (consts.AXIS_BASE_BITS - 16)))) * 2.0)
        q = f(f(f(rng) / step) + f(consts.TRUNC_FUDGE))
        return min(consts.AXIS_MAX_BITS, _bits_from_cells(int(min(float(consts.AXIS_MAX_CELLS), q))))
    if variant == "ceil_f32":                              # the engine's own float32 constant, float32 arithmetic, ceil
        step = f(f(f(consts.ENGINE_UNIT_16) / f(float(1 << (consts.AXIS_BASE_BITS - 16)))) * 2.0)
        n = min(consts.AXIS_MAX_CELLS, math.ceil(f(f(rng) / step)))
        return min(consts.AXIS_MAX_BITS, _bits_from_cells(n))
    raise FixtureError("unknown axis variant %r" % (variant,))


def axis_ranges(bounds, method="double"):
    """The three axis ranges from the six bounds (already float32 values).  ``double``: difference of the two
    float32-decoded bounds in double precision; ``f32``: that difference rounded to float32."""
    out = []
    for k in range(3):
        lo, hi = bits.f32_round(bounds[2 * k]), bits.f32_round(bounds[2 * k + 1])
        r = hi - lo
        out.append(bits.f32_round(r) if method == "f32" else r)
    return out


def axis_bits(bounds, variant="ceil", method="double"):
    return [axis_bits_one(r, variant) for r in axis_ranges(bounds, method)]


def axis_hypotheses(bounds):
    """Every (method, variant) -> triple, and the distinct triples in first-seen order (SPEC 4.1)."""
    table = {}
    distinct = []
    for method in ("double", "f32"):
        for variant in consts.AXIS_VARIANTS:
            t = tuple(axis_bits(bounds, variant, method))
            table[(method, variant)] = t
            if t not in distinct:
                distinct.append(t)
    return table, distinct


# =====================================================================================================
# Hashes (SPEC 2.7)
# =====================================================================================================

def hash_digest(recipe, data, length):
    """The 20 stored bytes for ``data[:length]`` under ``recipe``."""
    if recipe not in consts.HASH_RECIPES:
        raise FixtureError("unknown hash recipe %r" % (recipe,))
    if recipe == "zero":
        return bytes(consts.MVAR_HASH_LENGTH)
    salted, order = consts.HASH_RECIPES[recipe]
    h = hashlib.sha1()
    if salted:
        h.update(consts.SALT34)
    if order is not None:
        h.update(length.to_bytes(4, _endian_name(order)))
    h.update(bytes(data[:length]))
    return h.digest()


# =====================================================================================================
# Normalising a spec into the full declared model
# =====================================================================================================

SLOT_DEFAULTS = {
    "flags2": 1, "folder": None, "item": None, "in_bounds": 1, "pos": (0, 0, 0), "up_global": 1, "up_code": None,
    "angle": 8192, "parent_raw": 0, "shape": 0, "dims": (), "spawn_seq": 0, "respawn": 0, "cached_type": 0,
    "label": None, "placement": 0xCC, "team_raw": 9, "color": None, "extra": (),
}
SLOT_KEYS = set(SLOT_DEFAULTS) | {"index"}


def _author(rec, what):
    name = bytes.fromhex(rec["name_hex"])
    if not 1 <= len(name) <= consts.AUTHOR_NAME_MAX:
        raise FixtureError("%s name must be 1 to 16 bytes" % what)
    if b"\x00" in name[:-1]:
        raise FixtureError("%s name has a NUL before its last byte" % what)
    if len(name) < consts.AUTHOR_NAME_MAX and name[-1] != 0:
        raise FixtureError("%s name shorter than 16 bytes must end with its NUL" % what)
    return {"timestamp": to_int(rec["timestamp"]), "xuid": to_int(rec["xuid"]), "name": name, "online": to_int(rec["online"])}


def _text_units(rec, what):
    text = rec["text"]
    units = [ord(c) for c in text]
    if any(u == 0 or u > 0xFFFF for u in units):
        raise FixtureError("%s text has a NUL or a character outside the BMP" % what)
    if rec["nul"]:
        units.append(0)
    elif len(units) != consts.TEXT_UNITS_MAX:
        raise FixtureError("%s without a NUL must have exactly %d units" % (what, consts.TEXT_UNITS_MAX))
    if len(units) > consts.TEXT_UNITS_MAX:
        raise FixtureError("%s is longer than %d units" % (what, consts.TEXT_UNITS_MAX))
    return units


def _norm_header(h):
    out = {
        "content_type": to_int(h["content_type"]),
        "file_length": None if h.get("file_length") is None else to_int(h["file_length"]),
        "ids": [to_int(x) for x in h["ids"]],
        "activity": to_int(h["activity"]),
        "game_mode": to_int(h["game_mode"]),
        "engine": to_int(h["engine"]),
        "map_id": to_int(h["map_id"]),
        "category": to_int(h["category"]),
        "created_by": _author(h["created_by"], "created_by"),
        "modified_by": _author(h["modified_by"], "modified_by"),
        "title_units": _text_units(h["title"], "title"),
        "description_units": _text_units(h["description"], "description"),
        "title": h["title"],
        "description": h["description"],
        "engine_icon": to_int(h.get("engine_icon", 0)),
        "hopper_id": None if h.get("hopper_id") is None else to_int(h["hopper_id"]),
        "campaign": None if h.get("campaign") is None else {k: to_int(v) for k, v in h["campaign"].items()},
        "firefight": None if h.get("firefight") is None else {k: to_int(v) for k, v in h["firefight"].items()},
        "chdr": dict(h.get("chdr", {})),
    }
    if len(out["ids"]) != 4:
        raise FixtureError("header.ids needs 4 entries")
    if (out["activity"] == consts.HOPPER_ACTIVITY) != (out["hopper_id"] is not None):
        raise FixtureError("hopper_id is present exactly when the decoded activity is %d" % consts.HOPPER_ACTIVITY)
    if (out["game_mode"] == consts.GAME_MODE_CAMPAIGN) != (out["campaign"] is not None):
        raise FixtureError("campaign tail is present exactly when game_mode is 1")
    if (out["game_mode"] == consts.GAME_MODE_FIREFIGHT) != (out["firefight"] is not None):
        raise FixtureError("firefight tail is present exactly when game_mode is 2")
    return out


def _norm_labels(lab):
    strings = lab.get("strings")
    gen = lab.get("strings_gen")
    if gen is not None:
        absent = set(gen.get("absent", []))
        strings = [None if i in absent else gen["format"] % i for i in range(gen["count"])]
    if strings is not None:
        buf = bytearray()
        offsets = []
        for s in strings:
            if s is None:
                offsets.append(None)
            else:
                offsets.append(len(buf))
                buf += s.encode("latin-1") + b"\x00"
        buffer = bytes(buf)
    else:
        offsets = [None if o is None else to_int(o) for o in lab["offsets"]]
        buffer = bytes.fromhex(lab["buffer_hex"])
    pad_to = lab.get("pad_to")
    if pad_to is not None:
        if pad_to < len(buffer):
            raise FixtureError("labels.pad_to is smaller than the buffer")
        buffer = buffer + bytes(pad_to - len(buffer))
    if len(offsets) > consts.LABEL_MAX_COUNT + 255:       # 9-bit field; >256 is legal to encode (negative tests)
        raise FixtureError("too many label entries")
    texts = []
    for o in offsets:
        if o is None:
            texts.append(None)
        else:
            end = buffer.find(b"\x00", o)
            texts.append(buffer[o:end if end >= 0 else len(buffer)].decode("latin-1"))
    compressed = bool(lab.get("compressed", False))
    comp = None
    if compressed:
        comp = bytes.fromhex(lab["comp_hex"])
        if comp[:1] != b"\x78":
            raise FixtureError("labels.comp_hex is not a zlib stream")
    return {"count": len(offsets), "offsets": offsets, "buffer": buffer, "texts": texts, "compressed": compressed,
            "comp": comp, "data_length": len(buffer)}


def _norm_slot(raw, index_hint=None):
    unknown = set(raw) - SLOT_KEYS
    if unknown:
        raise FixtureError("unknown slot keys %s" % sorted(unknown))
    s = {}
    for key, default in SLOT_DEFAULTS.items():
        v = raw.get(key, default)
        if key in ("pos", "dims", "extra"):
            v = [to_int(x) for x in v]
        elif v is not None:
            v = to_int(v)
        s[key] = v
    s["index"] = to_int(raw["index"]) if "index" in raw else index_hint
    if s["index"] is None or not 0 <= s["index"] < consts.SLOT_COUNT:
        raise FixtureError("slot index out of range: %r" % (s["index"],))
    if len(s["pos"]) != 3:
        raise FixtureError("slot %d: pos needs 3 values" % s["index"])
    return s


def expand_bulk(gen, axis_widths, quota_count, rule):
    """The deterministic slot generator named by ``slots_gen`` (see docs/mvar/notes/G2.md)."""
    r = Lcg(gen.get("seed", 1))
    style = gen.get("style", "w1")
    folders = gen.get("folders", [70])
    items = gen.get("items", [0])
    types = gen.get("types", [0])
    labels = gen.get("labels", [])
    skip = set(gen.get("skip", []))
    start, stop = gen.get("start", 0), gen.get("stop", consts.SLOT_COUNT)
    every = gen.get("every", 1)
    out = []
    k = 0
    for i in range(start, stop):
        if i in skip or (i - start) % every:
            continue
        s = {"index": i}
        s["folder"] = folders[k % len(folders)]
        s["item"] = items[(k // len(folders)) % len(items)]
        s["pos"] = [r.next(1 << b) if b else 0 for b in axis_widths]
        s["angle"] = r.next(1 << consts.ANGLE_BITS)
        if style == "w1":
            pass                                            # defaults: vertical, 141-bit block records with W1 axes
        elif style in ("mix", "max"):
            full = style == "max"
            s["flags2"] = r.next(4)
            if not full and r.next(16) == 0:
                s["folder"] = None
            if not full and r.next(16) == 0:
                s["item"] = None
            if full or r.next(2):
                s["up_global"] = 0
                s["up_code"] = r.next(consts.UP_CODE_MAX_VALID + 1)
            s["parent_raw"] = r.next(consts.PARENT_RAW_MAX + 1) if (not full and r.next(4) == 0) else 0
            s["shape"] = 3 if full else r.next(4)
            s["dims"] = [r.next(1 << consts.DIM_BITS) for _ in range(consts.SHAPE_DIM_COUNT[s["shape"]])]
            s["spawn_seq"] = r.next(256) - 128
            s["respawn"] = r.next(256)
            ctype = types[r.next(len(types))] if not full else gen.get("full_types", [12, 13, 14])[r.next(3)]
            s["cached_type"] = ctype
            if ctype == consts.TYPE19:
                s["extra"] = _gen_type19(r, rule)
            elif ctype in consts.EXTRA_WIDTHS:
                s["extra"] = [r.next(1 << w) for w in consts.EXTRA_WIDTHS[ctype]]
            if labels and (full or r.next(2)):
                s["label"] = labels[r.next(len(labels))]
            s["placement"] = r.next(256)
            s["team_raw"] = r.next(10)
            if full or r.next(2):
                s["color"] = r.next(8)
        else:
            raise FixtureError("unknown slots_gen style %r" % (style,))
        out.append(s)
        k += 1
    return out


def _gen_type19(r, rule):
    if rule == "plain8":
        return [r.next(256)]
    flag = r.next(2)
    return [1, 0] if flag else [0, r.next(256)]


def normalise(spec):
    """The declared model: defaults filled in, hex strings turned into ints, bulk generators expanded."""
    if spec.get("schema") != consts.SCHEMA_SPEC:
        raise FixtureError("unexpected spec schema %r" % (spec.get("schema"),))
    c = spec["container"]
    cont = {
        "shape": c["shape"],
        "blf_version": c.get("blf", {}).get("version", consts.BLF["version"]),
        "blf_flags": c.get("blf", {}).get("flags", consts.BLF["flags"]),
        "mvar_version": c.get("mvar", {}).get("version", consts.MVAR["version"]),
        "mvar_flags": c.get("mvar", {}).get("flags", consts.MVAR["flags"]),
        "mvar_size": c.get("mvar", {}).get("size", consts.MVAR["size"]),
        "mvar_extra_bytes": c.get("mvar", {}).get("extra_bytes", 0),
        "length_endian": c.get("length", {}).get("endian", ">"),
        "length_mode": c.get("length", {}).get("mode", "ceil_end"),
        "length_value": c.get("length", {}).get("value"),
        "hash_recipe": c.get("hash", {}).get("recipe", "salted_be32"),
        "eof_endian": c.get("eof", {}).get("endian", ">"),
        "eof_value": c.get("eof", {}).get("value"),
        "fsm": c.get("fsm"),
        "cmp": c.get("cmp"),
        "trailer": bytes.fromhex(c.get("trailer_hex", "")),
        "truncate_to": c.get("truncate_to"),
    }
    if cont["shape"] not in ("plain4", "plain4+fsm", "cmp4", "cmp4+fsm"):
        raise FixtureError("unknown container shape %r" % (cont["shape"],))
    if cont["shape"].endswith("+fsm") != (cont["fsm"] is not None):
        raise FixtureError("container.fsm must be present exactly for the +fsm shapes")
    if cont["shape"].startswith("cmp") != (cont["cmp"] is not None):
        raise FixtureError("container.cmp must be present exactly for the cmp shapes")
    if cont["length_mode"] not in ("ceil_end", "capacity", "explicit"):
        raise FixtureError("unknown length mode %r" % (cont["length_mode"],))

    header = _norm_header(spec["header"])
    b = spec["body"]
    bounds = [float(x) for x in b["bounds"]]
    if len(bounds) != 6:
        raise FixtureError("body.bounds needs 6 values")
    body = {
        "version": to_int(b["version"]), "checksum": to_int(b["checksum"]), "palette_crc": to_int(b["palette_crc"]),
        "quota_count": to_int(b["quota_count"]),
        "map_id_2": header["map_id"] if b.get("map_id_2") is None else to_int(b["map_id_2"]),
        "built_in": to_int(b["built_in"]), "built_from_xml": to_int(b["built_from_xml"]),
        "bounds": bounds, "max_budget": to_int(b["max_budget"]), "spent_budget": to_int(b["spent_budget"]),
    }
    lay = spec.get("layout", {})
    explicit_bits = lay.get("axis_bits")
    variant = lay.get("axis_variant", "ceil")
    layout = {
        "axis_variant": variant,
        "axis_bits": [to_int(x) for x in explicit_bits] if explicit_bits else axis_bits(bounds, variant),
        "type19": lay.get("type19", "flag8"),
        "axis_bits_explicit": bool(explicit_bits),
    }
    if layout["type19"] not in consts.TYPE19_RULES:
        raise FixtureError("layout.type19 must be one of %s" % (consts.TYPE19_RULES,))

    labels = _norm_labels(spec["labels"])
    guid = spec.get("guid") or {"present": False, "hex": None}
    guid_value = None
    if guid["present"]:
        guid_value = bytes.fromhex(guid["hex"])
        if len(guid_value) != consts.GUID_BITS // 8:
            raise FixtureError("guid.hex must be 16 bytes")

    slots = {}
    gen = spec.get("slots_gen")
    if gen:
        for s in expand_bulk(gen, layout["axis_bits"], body["quota_count"], layout["type19"]):
            ns = _norm_slot(s)
            slots[ns["index"]] = ns
    for raw in spec.get("slots", []):
        ns = _norm_slot(raw)
        slots[ns["index"]] = ns

    qrows = spec.get("quotas", {}).get("rows", {})
    quotas = [[0, 0, 0] for _ in range(body["quota_count"])]
    for key, row in qrows.items():
        idx = to_int(key)
        if idx >= body["quota_count"]:
            raise FixtureError("quota row %d is beyond quota_count %d" % (idx, body["quota_count"]))
        quotas[idx] = [to_int(x) for x in row]

    tail = spec.get("tail", {})
    return {
        "name": spec["name"], "role": spec.get("role", "positive"), "container": cont, "header": header,
        "body": body, "layout": layout, "labels": labels, "guid": guid_value, "slots": slots, "quotas": quotas,
        "tail": tail.get("bits", ""),
    }


declared = normalise


# =====================================================================================================
# Writing the stream (SPEC 3.2 to 3.7), table-driven
# =====================================================================================================

def _put_author(w, a):
    for name, width in consts.AUTHOR_FIELDS:
        w.put(a[name], width)
    for ch in a["name"]:
        w.put(ch, 8)
    w.put(a["online"], 1)


def _write_header(w, h):
    values = {"content_type": h["content_type"], "file_length": h["file_length_resolved"], "id0": h["ids"][0],
              "id1": h["ids"][1], "id2": h["ids"][2], "id3": h["ids"][3], "activity": h["activity"],
              "game_mode": h["game_mode"], "engine": h["engine"], "map_id": h["map_id"], "category": h["category"]}
    for name, width, adjust in consts.UGC_HEADER_FIXED:
        w.put(values[name] + adjust, width)
    _put_author(w, h["created_by"])
    _put_author(w, h["modified_by"])
    for u in h["title_units"]:
        w.put(u, 16)
    for u in h["description_units"]:
        w.put(u, 16)
    if h["content_type"] == consts.CONTENT_TYPE_GAME_VARIANT:
        w.put(h["engine_icon"], consts.ENGINE_ICON_BITS)
    if h["activity"] == consts.HOPPER_ACTIVITY:
        w.put(h["hopper_id"], consts.HOPPER_BITS)
    if h["game_mode"] == consts.GAME_MODE_CAMPAIGN:
        for name, width in consts.CAMPAIGN_TAIL:
            w.put(h["campaign"][name], width)
    if h["game_mode"] == consts.GAME_MODE_FIREFIGHT:
        for name, width in consts.FIREFIGHT_TAIL:
            w.put(h["firefight"][name], width)


def _write_body(w, b):
    for name, width in consts.BODY_FIELDS:
        w.put(b[name], width)
    for x in b["bounds"]:
        w.put(bits.f32_bits(x), consts.BOUNDS_BITS)
    for name, width in consts.BODY_TAIL_FIELDS:
        w.put(b[name], width)


def _write_labels(w, lab):
    w.put(lab["count"], consts.LABEL_COUNT_BITS)
    for off in lab["offsets"]:
        if off is None:
            w.put(0, consts.LABEL_PRESENT_BITS)
        else:
            w.put(1, consts.LABEL_PRESENT_BITS)
            w.put(off, consts.LABEL_OFFSET_BITS)
    if lab["count"] == 0:
        return
    w.put(lab["data_length"], consts.LABEL_DATA_LENGTH_BITS)
    w.put(1 if lab["compressed"] else 0, consts.LABEL_COMPRESSED_BITS)
    if lab["compressed"]:
        payload = struct.pack(">I", lab["data_length"]) + lab["comp"]
        w.put(len(payload), consts.LABEL_COMP_SIZE_BITS)
        w.put_bytes(payload)
    else:
        w.put_bytes(lab["buffer"])


SPAN_NAMES = {"parent_raw": "parent", "team_raw": "team", "extra": "extras"}


def _write_slot(w, s, axes, rule):
    """Writes one present slot; returns the list of (field, start, end) spans."""
    spans = []

    def span(name, start):
        spans.append((name, start, w.nbits))

    for name, kind, width in consts.SLOT_FIELDS:
        start = w.nbits
        if name == "present":
            w.put(1, 1)
            span("present", start)
        elif kind == "u":
            w.put(s[name], width)
            span(SPAN_NAMES.get(name, name), start)
        elif kind == "s":
            w.put_signed(s[name], width)
            span(SPAN_NAMES.get(name, name), start)
        elif kind == "opt":
            v = s[name]
            w.put(1 if v is None else 0, 1)
            span(name + "_absent", start)
            if v is not None:
                start = w.nbits
                w.put(v, width)
                span(name, start)
        elif kind == "axes":
            for k, axis in enumerate("xyz"):
                start = w.nbits
                w.put(s["pos"][k], axes[k])
                span("pos_" + axis, start)
        elif kind == "up":
            w.put(s["up_global"], 1)
            span("up_global", start)
            if s["up_global"] == 0:
                start = w.nbits
                w.put(s["up_code"], width)
                span("up_code", start)
            elif s["up_code"] is not None:
                raise FixtureError("slot %d: up_global is set but an up_code is given" % s["index"])
        elif kind == "dims":
            count = consts.SHAPE_DIM_COUNT[s["shape"]]
            if len(s["dims"]) != count:
                raise FixtureError("slot %d: shape %d needs %d dims" % (s["index"], s["shape"], count))
            for d in s["dims"]:
                w.put(d, width)
            span("dims", start)
        elif kind == "extras":
            ct, ex = s["cached_type"], s["extra"]
            if ct == consts.TYPE19:
                if rule == "plain8":
                    if len(ex) != 1:
                        raise FixtureError("slot %d: plain8 type 19 needs extra [stored]" % s["index"])
                    w.put(ex[0], 8)
                else:
                    if len(ex) != 2 or ex[0] not in (0, 1) or (ex[0] == 1 and ex[1] != 0):
                        raise FixtureError("slot %d: flag8 type 19 needs extra [flag, index] (index 0 when flag is 1)" % s["index"])
                    w.put(ex[0], 1)
                    if ex[0] == 0:
                        w.put(ex[1], 8)
            elif ct in consts.EXTRA_WIDTHS:
                widths = consts.EXTRA_WIDTHS[ct]
                if len(ex) != len(widths):
                    raise FixtureError("slot %d: cached type %d needs %d extra value(s)" % (s["index"], ct, len(widths)))
                for v, wd in zip(ex, widths):
                    w.put(v, wd)
            elif ex:
                raise FixtureError("slot %d: cached type %d takes no extras" % (s["index"], ct))
            span("extras", start)
    return spans


def build_stream(m, file_length):
    """Returns (writer, info) for the bit stream of model ``m``."""
    w = bits.BitWriter()
    info = {"sections": {}, "slot_ranges": {}, "slot_field_spans": {}}
    sec = info["sections"]
    h = dict(m["header"])
    h["file_length_resolved"] = file_length if h["file_length"] is None else h["file_length"]
    sec["header"] = w.nbits
    _write_header(w, h)
    sec["body_fixed"] = w.nbits
    _write_body(w, m["body"])
    sec["labels"] = w.nbits
    _write_labels(w, m["labels"])
    if m["guid"] is not None:
        sec["guid"] = w.nbits
        w.put(int.from_bytes(m["guid"], "big"), consts.GUID_BITS)
    else:
        sec["guid"] = None
    sec["slots"] = w.nbits
    axes = m["layout"]["axis_bits"]
    rule = m["layout"]["type19"]
    for i in range(consts.SLOT_COUNT):
        start = w.nbits
        s = m["slots"].get(i)
        if s is None:
            w.put(0, 1)
        else:
            info["slot_field_spans"][i] = _write_slot(w, s, axes, rule)
            info["slot_ranges"][i] = (start, w.nbits)
    sec["quotas"] = w.nbits
    if len(m["quotas"]) != m["body"]["quota_count"]:
        raise FixtureError("quota rows do not match quota_count")
    for row in m["quotas"]:
        for (name, width), v in zip(consts.QUOTA_ROW, row):
            w.put(v, width)
    sec["end"] = w.nbits
    w.put_bitstring(m["tail"])
    info["header_end"] = sec["body_fixed"]
    return w, info


# =====================================================================================================
# Containers (SPEC 2)
# =====================================================================================================

def build_chdr(m, file_length):
    h = m["header"]
    buf = bytearray(consts.CHDR["size"])
    buf[0:12] = bits.block_header(consts.CHDR["sig"], consts.CHDR["size"], consts.CHDR["version"], consts.CHDR["flags"])
    ch = h["chdr"]
    vals = {
        "build_major": ch.get("build_major", 0), "build_minor": ch.get("build_minor", 0xFFFF),
        "content_type": h["content_type"], "file_length": file_length,
        "id0": h["ids"][0], "id1": h["ids"][1], "id2": h["ids"][2], "id3": h["ids"][3],
        "activity": h["activity"], "game_mode": h["game_mode"], "engine": h["engine"], "map_id": h["map_id"],
        "engine_category": h["category"], "engine_icon": h["engine_icon"],
        "campaign_id": 0, "campaign_difficulty": 0, "campaign_metagame": 0, "campaign_rally": 0, "campaign_unk": 0,
    }
    if h["campaign"] is not None:
        c = h["campaign"]
        vals.update({"campaign_id": c["id"], "campaign_difficulty": c["difficulty"], "campaign_metagame": c["metagame"],
                     "campaign_rally": c["rally"], "campaign_unk": c["unk"]})
    for name, off, fmt in consts.CHDR_SCALARS:
        struct.pack_into(fmt, buf, off, vals[name])
    for which, off in consts.CHDR_AUTHOR_OFFSETS.items():
        a = h[which]
        struct.pack_into("<QQ", buf, off, a["timestamp"], a["xuid"])
        buf[off + 16:off + 32] = a["name"].ljust(16, b"\x00")
        buf[off + 32] = a["online"]
    for units, off in ((h["title_units"], consts.CHDR_TITLE_OFFSET), (h["description_units"], consts.CHDR_DESCRIPTION_OFFSET)):
        for k, u in enumerate(units):
            struct.pack_into("<H", buf, off + 2 * k, u)
    return bytes(buf)


def _fsm_block(spec_fsm):
    size = spec_fsm.get("size", consts.FSM["size"])
    seed = spec_fsm.get("seed", "fsm")
    body = bytearray()
    counter = 0
    while len(body) < size - consts.BLOCK_HEADER_SIZE:
        body += hashlib.sha256(("fsm-body|%s|%d" % (seed, counter)).encode("ascii")).digest()
        counter += 1
    body = bytes(body[:size - consts.BLOCK_HEADER_SIZE])
    return bits.block_header(consts.FSM["sig"], size, spec_fsm.get("version", consts.FSM["version"]),
                             spec_fsm.get("flags", consts.FSM["flags"])) + body


class Built(object):
    """The result of building one fixture."""

    def __init__(self, name, data, info, model):
        self.name = name
        self.data = data
        self.info = info
        self.model = model

    @property
    def sha256(self):
        return hashlib.sha256(self.data).hexdigest()


def build(spec):
    """Build one fixture from a spec dict (or its name).  Pure and deterministic."""
    if isinstance(spec, str):
        spec = load_spec(spec)
    m = normalise(spec)
    cont = m["container"]
    is_cmp = cont["shape"].startswith("cmp")

    mvar_size = cont["mvar_size"]
    mvar_total = consts.MVAR["size"] + cont["mvar_extra_bytes"]
    if is_cmp:
        wrapper_size = consts.CMP_PREFIX + bits.zlib_stored_length(mvar_total)
        middle = wrapper_size
    else:
        middle = mvar_total
    eof_offset = consts.BLF["size"] + consts.CHDR["size"] + middle
    file_length = eof_offset + consts.EOF["size"]            # "total file length through _eof" (the _fsm is not counted)

    w, sinfo = build_stream(m, file_length)
    end = sinfo["sections"]["end"]
    if w.nbits > consts.STREAM_CAPACITY_BITS:
        raise FixtureError("stream needs %d bits, capacity %d" % (w.nbits, consts.STREAM_CAPACITY_BITS))
    stream = w.getbytes(consts.MVAR_STREAM_CAPACITY)

    mode = cont["length_mode"]
    if mode == "ceil_end":
        length = (end + 7) // 8
    elif mode == "capacity":
        length = consts.MVAR_STREAM_CAPACITY
    else:
        length = to_int(cont["length_value"])
    stored_hash = hash_digest(cont["hash_recipe"], stream, length)

    mvar = (bits.block_header(consts.MVAR["sig"], mvar_size, cont["mvar_version"], cont["mvar_flags"]) + stored_hash
            + length.to_bytes(4, _endian_name(cont["length_endian"])) + stream + bytes(consts.MVAR_TRAILING_PAD)
            + bytes(cont["mvar_extra_bytes"]))
    if len(mvar) != mvar_total:
        raise FixtureError("internal: mvar block is %d bytes, expected %d" % (len(mvar), mvar_total))

    blf = (bits.block_header(consts.BLF["sig"], consts.BLF["size"], cont["blf_version"], cont["blf_flags"]) + consts.BLF_BOM
           + bytes(0x20) + bytes(2))
    chdr = build_chdr(m, file_length)
    if is_cmp:
        c = cont["cmp"]
        middle_bytes = (bits.block_header(consts.CMP["sig"], wrapper_size, c.get("version", consts.CMP["version"]),
                                          c.get("flags", consts.CMP["flags"]))
                        + bytes([consts.CMP_TYPE_ZLIB]) + struct.pack(">I", len(mvar)) + bits.zlib_stored(mvar))
    else:
        middle_bytes = mvar
    if len(middle_bytes) != middle:
        raise FixtureError("internal: middle block is %d bytes, expected %d" % (len(middle_bytes), middle))
    eof_value = eof_offset if cont["eof_value"] is None else to_int(cont["eof_value"])
    eof = (bits.block_header(consts.EOF["sig"], consts.EOF["size"], consts.EOF["version"], consts.EOF["flags"])
           + eof_value.to_bytes(4, _endian_name(cont["eof_endian"])) + b"\x00")
    data = blf + chdr + middle_bytes + eof
    if cont["fsm"] is not None:
        data += _fsm_block(cont["fsm"])
    data += cont["trailer"]
    if cont["truncate_to"] is not None:
        data = data[:cont["truncate_to"]]

    info = dict(sinfo)
    info.update({
        "name": m["name"], "size": len(data), "shape": cont["shape"], "file_length": file_length,
        "end_bit": end, "L": length, "stored_hash": stored_hash.hex(), "axis_bits": list(m["layout"]["axis_bits"]),
        "stream_bits_written": w.nbits, "free_bits": consts.STREAM_CAPACITY_BITS - end, "eof_offset": eof_offset,
        "present_count": len(m["slots"]),
        "type19_status": "determined" if any(s["cached_type"] == consts.TYPE19 for s in m["slots"].values()) else "undetermined",
        "mvar_block_offset": consts.BLF["size"] + consts.CHDR["size"] if not is_cmp else None,
    })
    return Built(m["name"], data, info, m)


# =====================================================================================================
# Spec files
# =====================================================================================================

def spec_names(specs_dir=None):
    d = specs_dir or SPECS_DIR
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json"))


def load_spec(name, specs_dir=None):
    path = os.path.join(specs_dir or SPECS_DIR, name + ".json")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def dumps_json(obj):
    """Canonical JSON for the golden files (stable across Python versions)."""
    return bits.dumps_json(obj)


def inside_repo(path):
    real = os.path.realpath(path)
    root = os.path.realpath(REPO)
    return real == root or real.startswith(root + os.sep)


def build_all(out_dir, names=None, specs_dir=None):
    """Write ``<name>.mvar`` for every (or the named) spec into ``out_dir``; returns {name: path}."""
    if inside_repo(out_dir):
        raise FixtureError("refusing to write fixtures inside the repository: %s" % out_dir)
    os.makedirs(out_dir, exist_ok=True)
    out = {}
    for name in (names or spec_names(specs_dir)):
        built = build(load_spec(name, specs_dir))
        path = os.path.join(out_dir, name + ".mvar")
        with open(path, "wb") as fh:
            fh.write(built.data)
        out[name] = path
    return out


def sha256_table(specs):
    """{name: {"sha256": ..., "size": ...}} for a dict/list of spec dicts (sorted by name)."""
    table = {}
    for spec in specs:
        b = build(spec)
        table[b.name] = {"sha256": b.sha256, "size": len(b.data)}
    return {"schema": SHA_SCHEMA, "files": table}


# =====================================================================================================
# Command line
# =====================================================================================================

def _catalogue():
    if __package__:
        from . import catalogue
    else:
        from fixturebuilder import catalogue
    return catalogue


def write_specs(catalogue_specs):
    os.makedirs(SPECS_DIR, exist_ok=True)
    existing = set(f for f in os.listdir(SPECS_DIR) if f.endswith(".json"))
    wanted = set()
    for spec in catalogue_specs:
        fname = spec["name"] + ".json"
        wanted.add(fname)
        with open(os.path.join(SPECS_DIR, fname), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(dumps_json(spec))
    for stale in sorted(existing - wanted):
        os.remove(os.path.join(SPECS_DIR, stale))
    with open(SHA_FILE, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(dumps_json(sha256_table(catalogue_specs)))
    return sorted(wanted)


def check():
    """Returns a list of problems (empty = ok): committed JSON == catalogue, SHA-256 file, determinism."""
    catalogue = _catalogue()
    problems = []
    cat = catalogue.all_specs()
    on_disk = spec_names()
    if sorted(s["name"] for s in cat) != on_disk:
        problems.append("spec files on disk %s differ from the catalogue %s" % (on_disk, sorted(s["name"] for s in cat)))
    for spec in cat:
        path = os.path.join(SPECS_DIR, spec["name"] + ".json")
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as fh:
            if fh.read() != dumps_json(spec):
                problems.append("%s.json differs from the catalogue" % spec["name"])
    with open(SHA_FILE, "r", encoding="utf-8") as fh:
        recorded = json.load(fh)
    for spec in cat:
        first, second = build(spec), build(copy.deepcopy(spec))
        if first.data != second.data:
            problems.append("%s: two builds differ" % spec["name"])
        rec = recorded["files"].get(spec["name"])
        if rec is None or rec["sha256"] != first.sha256 or rec["size"] != len(first.data):
            problems.append("%s: fixture_sha256.json is out of date" % spec["name"])
    return problems


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Independent fixture builder (SPEC 9.1, G2).")
    ap.add_argument("--out", metavar="DIR", help="write <name>.mvar for the committed specs into DIR (outside the repo)")
    ap.add_argument("--only", nargs="+", metavar="NAME")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--write-specs", action="store_true", help="regenerate tests/golden/fixture_specs and fixture_sha256.json")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    if args.list:
        for n in spec_names():
            print(n)
        return 0
    if args.write_specs:
        names = write_specs(_catalogue().all_specs())
        print("wrote %d spec files and %s" % (len(names), os.path.relpath(SHA_FILE, REPO)))
        return 0
    if args.check:
        problems = check()
        for p in problems:
            print("FAIL " + p)
        print("check: %s" % ("ok" if not problems else "%d problem(s)" % len(problems)))
        return 1 if problems else 0
    if args.out:
        try:
            paths = build_all(args.out, args.only)
        except FixtureError as exc:
            print("build: %s" % exc, file=sys.stderr)
            return 2
        for name in sorted(paths):
            print("%s  %s" % (name, paths[name]))
        return 0
    ap.print_usage()
    return 2


if __name__ == "__main__":
    sys.exit(main())
