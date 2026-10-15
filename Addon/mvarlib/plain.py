"""Plain-dict / JSON form of a map variant: ``to_plain`` / ``from_plain`` (SPEC 6.6; gate G3).

Purpose: load a map variant into plain data and write it back; golden data; diffing; debugging. The form is
JSON-safe (64-bit values and byte strings are hex strings). ``from_plain(to_plain(m)).to_bytes(force=True)``
equals the original for every file of shape ``plain4`` / ``plain4+fsm``; for a ``cmp`` shape it is the
expanded form (DEC-2.6), because ``from_plain`` always builds the plain block layout.

Only present slots are listed (absent slots are implicit). The raw ranges are the truth: ``header.raw_hex`` /
``header.raw_bits`` is the exact header bit range (DEC-3.1), ``labels.comp_hex`` the compressed label block as
stored (4-byte size prefix + zlib stream), ``tail_hex`` the unused part of the stream after the quota table
(empty when it is all zero; ``tail_bits`` is its exact length). The ``views`` block holds derived floats for
humans and is ignored by ``from_plain``.

A hand-written minimal dict is enough for ``from_plain``: every missing part gets a default (version 31,
salted_be32 hash with a big-endian length, a ``chdr`` built from the header fields, axis bits from the
bounds, ``flag8``, 651 absent slots, zero quota rows); see ``MINIMAL_HEADER`` below for the header keys.

Pure Python 3.9 to 3.13, standard library only, relative imports only.
"""
import struct
from typing import Dict

from . import blf as blf_mod
from . import codecs, hashing
from .bitio import BitString, BitWriter
from .errors import EncodeError
from .labels import encode_label_table
from .slot import SLOT_COUNT, SHAPE_DIM_COUNT, Slot
from .ugc_header import AuthorRecord, CampaignTail, FirefightTail, UgcHeader, build_chdr, encode_u16, write_header
from .walk import STREAM_BITS, STREAM_BYTES

__all__ = ["SCHEMA", "to_plain", "from_plain", "MINIMAL_HEADER"]

SCHEMA = "mvarlib.plain/1"
MVAR_BLOCK_SIZE = 0x7028
MINIMAL_HEADER = {"content_type_raw": 6, "file_length": 0, "ids": ["0x0", "0x0", "0x0", "0x0"], "activity_raw": 1,
                  "game_mode": 4, "engine": 1, "map_id": 3006, "category": 0,
                  "created_by": {"timestamp": 0, "xuid": "0x0", "name_hex": "00", "online": 0},
                  "modified_by": {"timestamp": 0, "xuid": "0x0", "name_hex": "00", "online": 0},
                  "title": "", "description": ""}


def _hex64(value):
    return "0x%016X" % value


def _hex32(value):
    return "0x%08X" % value


def _int(value):
    """An int or a ``"0x..."`` string."""
    if isinstance(value, str):
        return int(value, 0)
    return int(value)


# ---------------------------------------------------------------------------------------------
# to_plain
# ---------------------------------------------------------------------------------------------
def _author_plain(a):
    return {"timestamp": a.timestamp, "xuid": _hex64(a.xuid), "name_hex": a.name.hex(), "online": a.is_online_id}


def to_plain(model) -> Dict[str, object]:
    """The plain form of a parsed ``MapVariant`` (see the module docstring)."""
    blf = model.blf
    chunks = []
    for chunk in blf.chunks:
        entry = {"sig": chunk.sig, "version": chunk.version, "flags": chunk.flags}
        if chunk.is_payload:
            entry["pad_hex"] = chunk.pad.hex()
        else:
            entry["body_hex"] = chunk.raw[12:].hex()
        chunks.append(entry)
    cmp_info = None
    for chunk in blf.chunks:
        if chunk.cmp is not None:
            cmp_info = {"ctype": chunk.cmp.ctype, "usize": chunk.cmp.usize}
    flavour = model.flavour
    h = model.header
    f = model.fixed
    labels = model.labels
    rule, axes = model.hypothesis.type19, model.hypothesis.axis_bits
    tail = model.tail
    tail_zero = tail.to_int() == 0
    out = {
        "schema": SCHEMA,
        "container": {
            "shape": blf.shape, "chunks": chunks, "cmp": cmp_info,
            "trailer_hex": blf.trailer.hex() if blf.trailer else None,
            "eof_endian": blf.eof_endian,
            "hash": None if flavour is None else {"length_endian": flavour.length_endian, "recipe": flavour.recipe},
            "length_class": model.length_class,
        },
        "header": {
            "content_type_raw": h.content_type_raw, "file_length": h.file_length,
            "ids": [_hex64(h.unk08), _hex64(h.unk10), _hex64(h.unk18), _hex64(h.unk20)],
            "activity_raw": h.activity_raw, "game_mode": h.game_mode, "engine": h.engine, "map_id": h.map_id,
            "category": h.engine_category, "created_by": _author_plain(h.created_by), "modified_by": _author_plain(h.modified_by),
            "title": h.title_text, "description": h.description_text,
            "title_units": list(h.title), "description_units": list(h.description),
            "hopper_id": h.hopper_id,
            "campaign_hex": None if h.campaign is None else "%02X%X%X%02X%08X" % (
                h.campaign.id, h.campaign.difficulty, h.campaign.metagame_scoring, h.campaign.rally_point, h.campaign.unk),
            "firefight_hex": None if h.firefight is None else "%X%08X" % (h.firefight.difficulty, h.firefight.unk),
            "raw_hex": h.raw.data.hex(), "raw_bits": h.raw.nbits,
        },
        "body": {
            "version": f.version, "checksum": _hex32(f.checksum), "palette_crc": _hex32(f.palette_crc),
            "quota_count": f.quota_count, "map_id_2": f.map_id_2, "built_in": f.built_in, "built_from_xml": f.built_from_xml,
            "bounds_hex": ["%08x" % v for v in f.bounds_raw], "max_budget": f.max_budget, "spent_budget": f.spent_budget,
            "guid_hex": None if model.guid is None else model.guid.data.hex(),
        },
        "labels": {
            "entries": list(labels.entries), "data_length": labels.data_length, "compressed": labels.compressed,
            "buffer_hex": labels.buffer.hex(), "comp_hex": labels.comp_bytes.hex() if labels.comp_bytes is not None else None,
        },
        "layout": {"type19": rule, "axis_bits": list(axes), "guid": model.hypothesis.guid},
        "slots": [_slot_plain(s) for s in model.slots if s.present],
        "quotas": [list(q.as_tuple()) for q in model.quotas],
        "tail_hex": "" if tail_zero else tail.data.hex(),
        "tail_bits": tail.nbits,
        "views": {"note": "derived values for humans; ignored by from_plain",
                  "map_name": model.map_name, "bounds": list(f.bounds),
                  "objects": [{"slot": o.slot, "type_id": o.type_id, "type_name": o.type_name, "position": list(o.position)}
                              for o in model.objects()]},
    }
    return out


def _slot_plain(s):
    return {"index": s.index, "flags2": s.flags2, "folder": s.folder, "item": s.item, "in_bounds": s.in_bounds,
            "pos": list(s.pos), "up_global": s.up_global, "up_code": s.up_code, "angle": s.angle,
            "parent_raw": s.parent_raw, "shape": s.shape, "dims": list(s.dims), "spawn_seq": s.spawn_seq,
            "respawn": s.respawn, "cached_type": s.cached_type, "label": s.label, "placement": s.placement,
            "team_raw": s.team_raw, "color": s.color, "extra": list(s.extra)}


# ---------------------------------------------------------------------------------------------
# from_plain
# ---------------------------------------------------------------------------------------------
def _author_from(d):
    name = bytes.fromhex(d.get("name_hex", "00"))
    return AuthorRecord(int(d.get("timestamp", 0)), _int(d.get("xuid", 0)), name, int(d.get("online", 0)))


def _units(d, units_key, text_key):
    if d.get(units_key) is not None:
        return [int(u) for u in d[units_key]]
    return encode_u16(d.get(text_key, ""))


def _header_from_fields(d):
    """A ``UgcHeader`` from the header dict's fields (used when there is no raw range)."""
    ids = [_int(x) for x in d.get("ids", ["0x0"] * 4)]
    campaign = firefight = None
    if d.get("campaign_hex"):
        c = d["campaign_hex"]
        campaign = CampaignTail(int(c[0:2], 16), int(c[2], 16), int(c[3], 16), int(c[4:6], 16), int(c[6:14], 16))
    if d.get("firefight_hex"):
        c = d["firefight_hex"]
        firefight = FirefightTail(int(c[0], 16), int(c[1:9], 16))
    hopper = d.get("hopper_id")
    header = UgcHeader(
        content_type_raw=int(d.get("content_type_raw", 6)), file_length=int(d.get("file_length", 0)),
        unk08=ids[0], unk10=ids[1], unk18=ids[2], unk20=ids[3], activity_raw=int(d.get("activity_raw", 1)),
        game_mode=int(d.get("game_mode", 4)), engine=int(d.get("engine", 1)), map_id=int(d.get("map_id", 3006)),
        engine_category=int(d.get("category", 0)), created_by=_author_from(d.get("created_by", {})),
        modified_by=_author_from(d.get("modified_by", {})), title=_units(d, "title_units", "title"),
        description=_units(d, "description_units", "description"), hopper_id=hopper, campaign=campaign, firefight=firefight)
    return header


def _slot_from(d):
    s = Slot(int(d["index"]), True)
    s.flags2 = int(d.get("flags2", 1))
    s.folder = d.get("folder")
    s.item = d.get("item")
    s.in_bounds = int(d.get("in_bounds", 1))
    s.pos = [int(x) for x in d.get("pos", [0, 0, 0])]
    s.up_global = int(d.get("up_global", 1))
    s.up_code = d.get("up_code")
    s.angle = int(d.get("angle", 0))
    s.parent_raw = int(d.get("parent_raw", 0))
    s.shape = int(d.get("shape", 0))
    s.dims = [int(x) for x in d.get("dims", [0] * SHAPE_DIM_COUNT.get(s.shape, 0))]
    s.spawn_seq = int(d.get("spawn_seq", 0))
    s.respawn = int(d.get("respawn", 0))
    s.cached_type = int(d.get("cached_type", 0))
    s.label = d.get("label")
    s.placement = int(d.get("placement", 0x0C))
    s.team_raw = int(d.get("team_raw", 9))
    s.color = d.get("color")
    s.extra = [int(x) for x in d.get("extra", [])]
    return s


def _block(sig, version, flags, body):
    return struct.pack(">4sIHH", sig.encode("latin-1"), 12 + len(body), version, flags) + body


def from_plain(d: Dict[str, object]):
    """Build a ``MapVariant`` from the plain form (see the module docstring); ``EncodeError`` for inconsistent data."""
    from .model import MapVariant
    if d.get("schema", SCHEMA) != SCHEMA:
        raise EncodeError("Unknown plain schema %r; expected %r." % (d.get("schema"), SCHEMA))
    body = d.get("body", {})
    version = int(body.get("version", 31))
    bounds_hex = body.get("bounds_hex")
    if bounds_hex is None:
        bounds = body.get("bounds", [-1.0, 1.0, -1.0, 1.0, -1.0, 1.0])
        bounds_raw = [struct.unpack(">I", struct.pack(">f", float(x)))[0] for x in bounds]
    else:
        bounds_raw = [int(x, 16) for x in bounds_hex]
    if len(bounds_raw) != 6:
        raise EncodeError("The bounds need six values, got %d." % len(bounds_raw))
    bounds = [struct.unpack(">f", struct.pack(">I", v))[0] for v in bounds_raw]
    layout = d.get("layout", {})
    rule = layout.get("type19", "flag8")
    axes = tuple(layout["axis_bits"]) if layout.get("axis_bits") else codecs.axis_bit_hypotheses(bounds)[0]
    guid_hex = body.get("guid_hex")
    guid = bytes.fromhex(guid_hex) if guid_hex else None
    if guid is None and layout.get("guid"):
        guid = bytes(16)
    if guid is not None and len(guid) != 16:
        raise EncodeError("The GUID block must be 16 bytes, got %d." % len(guid))
    quotas = d.get("quotas")
    quota_count = int(body.get("quota_count", len(quotas) if quotas is not None else 0))
    if quotas is None:
        quotas = [[0, 0, 0]] * quota_count
    if len(quotas) != quota_count:
        raise EncodeError("quota_count is %d but %d quota rows are given." % (quota_count, len(quotas)))

    # --- the bit stream -----------------------------------------------------------------------
    w = BitWriter()
    hd = d.get("header", MINIMAL_HEADER)
    if hd.get("raw_hex") is not None and hd.get("raw_bits") is not None:
        w.write_bitstring(BitString(bytes.fromhex(hd["raw_hex"]), int(hd["raw_bits"])))
    else:
        write_header(w, _header_from_fields(hd))
    w.write(version, 8)
    w.write(_int(body.get("checksum", 0xFFFFFFFF)), 32)
    w.write(_int(body.get("palette_crc", 0)), 32)
    w.write(quota_count, 9)
    w.write(int(body.get("map_id_2", hd.get("map_id", 3006))), 32)
    w.write(int(body.get("built_in", 0)), 1)
    w.write(int(body.get("built_from_xml", 0)), 1)
    for v in bounds_raw:
        w.write(v, 32)
    w.write(int(body.get("max_budget", 0)), 32)
    w.write(int(body.get("spent_budget", 0)), 32)
    lab = d.get("labels", {"entries": []})
    comp_hex = lab.get("comp_hex")
    w.write_bitstring(encode_label_table(
        list(lab.get("entries", [])), bytes.fromhex(lab.get("buffer_hex", "")), bool(lab.get("compressed", False)) if lab.get("entries") else None,
        bytes.fromhex(comp_hex) if comp_hex else None, lab.get("data_length")))
    if guid is not None:
        w.write_bytes(guid)
    by_index = {}
    for sd in d.get("slots", []):
        by_index[int(sd["index"])] = _slot_from(sd)
    for index in by_index:
        if not 0 <= index < SLOT_COUNT:
            raise EncodeError("Slot index %d is outside 0..%d." % (index, SLOT_COUNT - 1))
    for index in range(SLOT_COUNT):
        by_index.get(index, Slot(index, False)).pack(w, rule, axes)
    for row in quotas:
        w.write(int(row[0]), 8)
        w.write(int(row[1]), 8)
        w.write(int(row[2]), 8)
    end = w.pos
    if end > STREAM_BITS:
        raise EncodeError("The plain data needs %d bits; the stream holds at most %d." % (end, STREAM_BITS))
    tail_bits = int(d.get("tail_bits", STREAM_BITS - end))
    tail_hex = d.get("tail_hex", "")
    if tail_hex:
        tail = BitString(bytes.fromhex(tail_hex), tail_bits)
        if end + tail.nbits > STREAM_BITS:
            raise EncodeError("The tail does not fit behind the data (%d + %d bits)." % (end, tail.nbits))
        w.write_bitstring(tail)
    stream = w.getvalue(STREAM_BYTES)

    # --- the container ------------------------------------------------------------------------
    cont = d.get("container", {})
    chunk_specs = cont.get("chunks")
    if chunk_specs is None:
        chunk_specs = [{"sig": "_blf", "version": 1, "flags": 2}, {"sig": "chdr", "version": 10, "flags": 2},
                       {"sig": "mvar", "version": version, "flags": 1}, {"sig": "_eof", "version": 1, "flags": 1}]
    eof_endian = cont.get("eof_endian", ">")
    blocks = []
    offset = 0
    for spec in chunk_specs:
        sig = spec["sig"]
        if sig == "_blf":
            data = _block(sig, spec.get("version", 1), spec.get("flags", 2),
                          bytes.fromhex(spec["body_hex"]) if spec.get("body_hex") is not None else b"\xff\xfe" + bytes(0x30 - 12 - 2))
        elif sig == "chdr":
            if spec.get("body_hex") is not None:
                data = _block(sig, spec.get("version", 10), spec.get("flags", 2), bytes.fromhex(spec["body_hex"]))
            else:
                data = _default_chdr(hd, spec)
        elif sig == "mvar":
            pad = bytes.fromhex(spec["pad_hex"]) if spec.get("pad_hex") is not None else bytes(4)
            data = _block(sig, spec.get("version", version), spec.get("flags", 1), bytes(MVAR_BLOCK_SIZE - 12 - len(pad)) + pad)
        elif sig == "_eof":
            body_hex = spec.get("body_hex")
            tail_byte = bytes.fromhex(body_hex)[4:] if body_hex else b"\x00"
            data = _block(sig, spec.get("version", 1), spec.get("flags", 1), struct.pack(eof_endian + "I", offset) + tail_byte)
        else:
            data = _block(sig, spec.get("version", 1), spec.get("flags", 1), bytes.fromhex(spec.get("body_hex", "")))
        blocks.append(data)
        offset += len(data)
    trailer = bytes.fromhex(cont["trailer_hex"]) if cont.get("trailer_hex") else b""
    placeholder = blf_mod.parse(b"".join(blocks) + trailer)
    chunk = placeholder.find("mvar")
    if chunk is None:
        raise EncodeError("The container has no 'mvar' block.")
    hash_info = cont.get("hash") or {"length_endian": ">", "recipe": "salted_be32"}
    flavour = hashing.HashFlavour(hash_info.get("length_endian", ">"), hash_info.get("recipe", "salted_be32"))
    length_class = cont.get("length_class", "ceil_end")
    if length_class == "capacity":
        length = STREAM_BYTES
    elif length_class == "zero":
        length = 0
    else:
        length = (end + 7) // 8
    chunk.set_stream(stream, length)
    data = placeholder.render(force=True, stream_length={"mvar": length}, flavour=flavour).data
    return MapVariant.from_bytes(data)


def _default_chdr(header, spec):
    """A ``chdr`` block built from the bit-form header fields (hand-written minimal dicts have no chdr)."""
    units_t = _units(header, "title_units", "title")
    units_d = _units(header, "description_units", "description")

    def utf16(units):
        raw = b"".join(struct.pack("<H", u) for u in units[:128])
        return raw + bytes(256 - len(raw))

    def author(a):
        name = bytes.fromhex(a.get("name_hex", "00"))[:16]
        return {"timestamp": int(a.get("timestamp", 0)), "xuid": _int(a.get("xuid", 0)), "name": name + bytes(16 - len(name)),
                "is_online_id": int(a.get("online", 0)), "pad": bytes(3)}

    ids = [_int(x) for x in header.get("ids", ["0x0"] * 4)]
    parsed = {
        "version": spec.get("version", 10), "flags": spec.get("flags", 2), "build_major": 0, "build_minor": 0xFFFF,
        "content_type": int(header.get("content_type_raw", 6)) - 1, "pad_11": bytes(3),
        "file_length": int(header.get("file_length", 0)), "unk08": ids[0], "unk10": ids[1], "unk18": ids[2], "unk20": ids[3],
        "activity": int(header.get("activity_raw", 1)) - 1, "game_mode": int(header.get("game_mode", 4)),
        "engine": int(header.get("engine", 1)), "pad_3b": bytes(1), "map_id": int(header.get("map_id", 3006)),
        "engine_category": int(header.get("category", 0)), "pad_44": bytes(4),
        "created_by": author(header.get("created_by", {})), "modified_by": author(header.get("modified_by", {})),
        "title_raw": utf16(units_t), "description_raw": utf16(units_d), "engine_icon": 0, "unk294": bytes(0x1C),
        "campaign_id": 0, "campaign_difficulty": 0, "campaign_metagame": 0, "campaign_rally": 0, "campaign_unk": 0,
        "unk2b8": bytes(8),
    }
    return build_chdr(parsed)
