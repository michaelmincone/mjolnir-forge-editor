"""The builder's own walker and the golden codec vectors (SPEC 9.1, test U-20).

A second reading of SPEC sections 2 to 4, written separately from ``build.py``: it decodes a fixture's bytes with a
different bit reader (``'0'/'1'`` string slicing), procedural field code instead of the builder's tables, and its own
copies of the codec formulas.  If the builder had a typo, the walker disagrees and U-20 fails before the fixture can mask
a bug in the code under test.

* ``read(data)``      full read of a file the way SPEC 2.7, 3.10 describes: container, flavour, every hypothesis,
                      selection; returns an outcome dict (``ok`` with the decode, or an ``error`` named like the
                      library exception the spec gives for that situation).
* ``compare(...)``    decode versus the declared model of a spec.
* ``analyse(data)``   the ``expect`` block stored in the fixture spec files.
* ``compute_codec_vectors()``  the contents of ``tests/golden/codec_vectors.json`` (computed here, cross-checked
                      against the numbers printed in the spec).

Python 3.9 compatible.  Nothing here imports the library under test.
"""
import hashlib
import json
import math
import os
import struct
import sys
import zlib

if __package__:
    from . import bits, consts
else:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from fixturebuilder import bits, consts

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN_DIR = os.path.join(os.path.dirname(HERE), "golden")

TYPE19_ORDER = ("flag8", "plain8")


class ReadError(Exception):
    """The file is refused; ``kind`` is the exception the spec names (SPEC 7.2)."""

    def __init__(self, kind, message, slot=None):
        Exception.__init__(self, "%s: %s" % (kind, message))
        self.kind = kind
        self.message = message
        self.slot = slot


class WalkReject(Exception):
    """One hypothesis does not fit (SPEC 3.10)."""

    def __init__(self, kind, message, slot=None, bit=None):
        Exception.__init__(self, message)
        self.kind = kind
        self.message = message
        self.slot = slot
        self.bit = bit


# =====================================================================================================
# Container
# =====================================================================================================

def parse_blocks(data):
    """Tile the file into blocks (SPEC 2.1).  Returns (blocks, trailer_bytes).  Raises ReadError('BlfFormatError')."""
    blocks = []
    pos = 0
    seen_eof = False
    while pos < len(data):
        if len(data) - pos < 12:
            break
        sig, size, version, flags = bits.unpack_block_header(data, pos)
        valid = size >= 12 and pos + size <= len(data) and all(32 <= ord(c) < 127 for c in sig)
        if not valid:
            if seen_eof:
                break
            if not blocks:
                raise ReadError("BlfFormatError", "This file is not a Halo BLF file (first block is %r, expected '_blf')." % sig)
            raise ReadError("BlfFormatError", "The file is damaged: block '%s' at offset 0x%X claims %d bytes but only %d remain."
                            % (sig, pos, size, len(data) - pos))
        if not blocks and sig != "_blf":
            raise ReadError("BlfFormatError", "This file is not a Halo BLF file (first block is '%s', expected '_blf')." % sig)
        blocks.append({"sig": sig, "offset": pos, "size": size, "version": version, "flags": flags})
        if len(blocks) > 256:
            raise ReadError("BlfFormatError", "more than 256 blocks")
        pos += size
        if sig == "_eof":
            seen_eof = True
    if not blocks:
        raise ReadError("BlfFormatError", "This file is not a Halo BLF file (it is empty).")
    if not seen_eof:
        raise ReadError("BlfFormatError", "The file is damaged: no '_eof' block.")
    return blocks, data[pos:]


def container(data):
    """Parse the container and locate the map variant block.  Returns a dict."""
    blocks, trailer = parse_blocks(data)
    sigs = [b["sig"] for b in blocks]
    eof_index = sigs.index("_eof")
    head, after = sigs[:eof_index + 1], sigs[eof_index + 1:]
    out = {"blocks": blocks, "trailer": trailer, "sigs": sigs, "cmp": None}
    mvar_block = None
    for b in blocks:
        if b["sig"] == "mvar":
            mvar_block = (b, data[b["offset"]:b["offset"] + b["size"]])
        elif b["sig"] == "_cmp":
            body = data[b["offset"] + 12:b["offset"] + b["size"]]
            ctype, usize = body[0], struct.unpack(">I", body[1:5])[0]
            if ctype != consts.CMP_TYPE_ZLIB:
                raise ReadError("BlfFormatError", "The compressed (_cmp) block could not be expanded: compression type %d." % ctype)
            try:
                inner = zlib.decompress(body[5:])
            except zlib.error as exc:
                raise ReadError("BlfFormatError", "The compressed (_cmp) block could not be expanded: %s." % exc)
            if len(inner) != usize:
                raise ReadError("BlfFormatError", "The compressed (_cmp) block could not be expanded: size mismatch.")
            isig, isize, iver, iflags = bits.unpack_block_header(inner, 0)
            if isig == "mvar":
                mvar_block = ({"sig": "mvar", "offset": None, "size": isize, "version": iver, "flags": iflags}, inner)
                out["cmp"] = {"usize": usize, "wrapper_size": b["size"], "type": ctype}
    if mvar_block is None:
        if "mpvr" in sigs:
            raise ReadError("UnsupportedVariantError", "This is a game variant (block 'mpvr'), not a map variant.")
        raise ReadError("UnsupportedVariantError", "No map variant block ('mvar') was found; blocks present: %s." % ", ".join(sigs))
    plain = ["_blf", "chdr", "mvar", "_eof"]
    cmpd = ["_blf", "chdr", "_cmp", "_eof"]
    if head == plain and after == [] and not trailer:
        shape = "plain4"
    elif head == plain and after == ["_fsm"] and not trailer:
        shape = "plain4+fsm"
    elif head == cmpd and after == [] and not trailer and out["cmp"]:
        shape = "cmp4"
    elif head == cmpd and after == ["_fsm"] and not trailer and out["cmp"]:
        shape = "cmp4+fsm"
    else:
        shape = "other"
    out["shape"] = shape
    out["mvar_header"], out["mvar_bytes"] = mvar_block
    eof = [b for b in blocks if b["sig"] == "_eof"][0]
    raw = data[eof["offset"] + 12:eof["offset"] + 16]
    be, le = struct.unpack(">I", raw)[0], struct.unpack("<I", raw)[0]
    out["eof"] = {"offset": eof["offset"], "be": be, "le": le,
                  "endian": ">" if be == eof["offset"] else ("<" if le == eof["offset"] else None)}
    out["file_length_through_eof"] = eof["offset"] + eof["size"]
    return out


def check_mvar_block(c):
    """Size and chunk-version policy (SPEC 2.2).  Returns warnings."""
    hdr = c["mvar_header"]
    if hdr["size"] != consts.MVAR["size"]:
        raise ReadError("UnsupportedVariantError", "The map variant block has size 0x%X; only 0x%X is supported."
                        % (hdr["size"], consts.MVAR["size"]))
    warnings = []
    if hdr["version"] in (12, 13, 14, 50, 51):
        raise ReadError("UnsupportedVariantError", "The map variant block has chunk version %d; Halo: Reach uses 31 or 32." % hdr["version"])
    if hdr["version"] not in (31, 32):
        warnings.append("W_CHUNK_VERSION_UNEXPECTED")
    return warnings


def stored_length(raw4):
    """The stored stream length in both byte orders (SPEC 2.7).  Returns [(endian, value)] of the valid readings:
    a reading is valid when its value is in 1..0x7000; four zero bytes are the special "zero" case."""
    be, le = struct.unpack(">I", raw4)[0], struct.unpack("<I", raw4)[0]
    if be == 0 and le == 0:
        return [(">", 0)]
    good = []
    if 1 <= be <= consts.MVAR_STREAM_CAPACITY:
        good.append((">", be))
    if 1 <= le <= consts.MVAR_STREAM_CAPACITY:
        good.append(("<", le))                      # both can only be valid when all four bytes are zero, handled above
    if not good:
        raise ReadError("BlfFormatError", "The stored stream length bytes %s are not a valid length (maximum 0x7000)." % raw4.hex())
    return good


RECIPES = ("salted_be32", "plain_le32", "salted_le32", "plain_be32", "data_only")


def digest(recipe, stream, length):
    """Written separately from the builder's table: the five recipes spelled out."""
    body = bytes(stream[:length])
    be, le = struct.pack(">I", length), struct.pack("<I", length)
    if recipe == "salted_be32":
        return hashlib.sha1(consts.SALT34 + be + body).digest()
    if recipe == "plain_le32":
        return hashlib.sha1(le + body).digest()
    if recipe == "salted_le32":
        return hashlib.sha1(consts.SALT34 + le + body).digest()
    if recipe == "plain_be32":
        return hashlib.sha1(be + body).digest()
    if recipe == "data_only":
        return hashlib.sha1(body).digest()
    raise ValueError(recipe)


def detect_flavour(block):
    """Returns (length_endian, recipe, L, class_hint) or None for each reading; first match in preference order."""
    stored = block[consts.MVAR_HASH_OFFSET:consts.MVAR_HASH_OFFSET + 20]
    raw4 = block[consts.MVAR_LENGTH_OFFSET:consts.MVAR_LENGTH_OFFSET + 4]
    stream = block[consts.MVAR_STREAM_OFFSET:consts.MVAR_STREAM_OFFSET + consts.MVAR_STREAM_CAPACITY]
    readings = stored_length(raw4)
    zero_len = readings == [(">", 0)]
    results = []
    for endian, L in readings:
        eff = [consts.MVAR_STREAM_CAPACITY] if zero_len else [L]
        for length in (([0] + eff) if zero_len else eff):
            if stored == bytes(20):
                results.append((endian, "zero", length))
                continue
            for recipe in RECIPES:
                if digest(recipe, stream, length) == stored:
                    results.append((endian, recipe, length))
    return {"readings": readings, "zero_length_bytes": zero_len, "matches": results, "stored_hash": stored,
            "stream": stream}


# =====================================================================================================
# Stream walk
# =====================================================================================================

def _author(r):
    ts, xuid = r.u(64), r.u(64)
    name = bytearray()
    while len(name) < 16:
        ch = r.u(8)
        name.append(ch)
        if ch == 0:
            break
    return {"timestamp": ts, "xuid": xuid, "name": bytes(name), "online": r.u(1)}


def _units(r):
    out = []
    while len(out) < 128:
        u = r.u(16)
        out.append(u)
        if u == 0:
            break
    return out


def read_header(r):
    h = {}
    h["content_type_stored"] = r.u(4)
    h["content_type"] = h["content_type_stored"] - 1
    h["file_length"] = r.u(32)
    h["ids"] = [r.u(64) for _ in range(4)]
    h["activity_stored"] = r.u(3)
    h["activity"] = h["activity_stored"] - 1
    h["game_mode"] = r.u(3)
    h["engine"] = r.u(3)
    h["map_id"] = r.u(32)
    h["category"] = r.u(8)
    h["created_by"] = _author(r)
    h["modified_by"] = _author(r)
    h["title_units"] = _units(r)
    h["description_units"] = _units(r)
    h["engine_icon"] = r.u(8) if h["content_type"] == 6 else 0
    h["hopper_id"] = r.u(16) if h["activity"] == 2 else None
    h["campaign"] = None
    h["firefight"] = None
    if h["game_mode"] == 1:
        h["campaign"] = {"id": r.u(8), "difficulty": r.u(2), "metagame": r.u(2), "rally": r.u(8), "unk": r.u(32)}
    if h["game_mode"] == 2:
        h["firefight"] = {"difficulty": r.u(2), "unk": r.u(32)}
    return h


def read_body(r):
    b = {}
    b["version"] = r.u(8)
    b["checksum"] = r.u(32)
    b["palette_crc"] = r.u(32)
    b["quota_count"] = r.u(9)
    b["map_id_2"] = r.u(32)
    b["built_in"] = r.u(1)
    b["built_from_xml"] = r.u(1)
    b["bounds"] = [bits.bits_f32(r.u(32)) for _ in range(6)]
    b["max_budget"] = r.u(32)
    b["spent_budget"] = r.u(32)
    return b


def read_labels(r):
    count = r.u(9)
    if count > 256:
        raise WalkReject("labels", "label count %d is above 256" % count, bit=r.pos)
    offsets = []
    for _ in range(count):
        offsets.append(r.u(12) if r.u(1) else None)
    lab = {"count": count, "offsets": offsets, "buffer": b"", "compressed": False, "comp": None, "data_length": 0}
    if count == 0:
        return lab
    lab["data_length"] = r.u(13)
    lab["compressed"] = bool(r.u(1))
    if lab["compressed"]:
        size = r.u(13)
        payload = bytes(r.u(8) for _ in range(size))
        lab["comp"] = payload[4:]
        try:
            lab["buffer"] = zlib.decompress(payload[4:])
        except zlib.error:
            raise WalkReject("labels", "compressed label buffer does not inflate", bit=r.pos)
        if struct.unpack(">I", payload[:4])[0] != len(lab["buffer"]):
            lab["size_prefix_mismatch"] = True
    else:
        lab["buffer"] = bytes(r.u(8) for _ in range(lab["data_length"]))
    return lab


def read_slot(r, idx, axes, rule, quota_count, label_count, label_offsets, spans, core_only=False):
    """Reads the rest of a present slot (the presence bit is already consumed).  Raises WalkReject on a hard-check failure."""
    s = {"index": idx}

    def mark(name, start):
        spans.append((name, start, r.pos))

    t = r.pos
    s["flags2"] = r.u(2)
    mark("flags2", t)
    t = r.pos
    fa = r.u(1)
    mark("folder_absent", t)
    s["folder"] = None
    if not fa:
        t = r.pos
        s["folder"] = r.u(8)
        mark("folder", t)
    t = r.pos
    ia = r.u(1)
    mark("item_absent", t)
    s["item"] = None
    if not ia:
        t = r.pos
        s["item"] = r.u(5)
        mark("item", t)
    t = r.pos
    s["in_bounds"] = r.u(1)
    mark("in_bounds", t)
    pos = []
    for k, axis in enumerate("xyz"):
        t = r.pos
        pos.append(r.u(axes[k]))
        mark("pos_" + axis, t)
    s["pos"] = pos
    t = r.pos
    s["up_global"] = r.u(1)
    mark("up_global", t)
    s["up_code"] = None
    if not s["up_global"]:
        t = r.pos
        s["up_code"] = r.u(20)
        mark("up_code", t)
    t = r.pos
    s["angle"] = r.u(14)
    mark("angle", t)
    t = r.pos
    s["parent_raw"] = r.u(10)
    mark("parent", t)
    t = r.pos
    s["shape"] = r.u(2)
    mark("shape", t)
    t = r.pos
    n = {0: 0, 1: 1, 2: 3, 3: 4}[s["shape"]]
    s["dims"] = [r.u(11) for _ in range(n)]
    mark("dims", t)
    t = r.pos
    s["spawn_seq"] = r.s(8)
    mark("spawn_seq", t)
    t = r.pos
    s["respawn"] = r.u(8)
    mark("respawn", t)
    t = r.pos
    s["cached_type"] = r.u(5)
    mark("cached_type", t)
    t = r.pos
    la = r.u(1)
    mark("label_absent", t)
    s["label"] = None
    if not la:
        t = r.pos
        s["label"] = r.u(8)
        mark("label", t)
    t = r.pos
    s["placement"] = r.u(8)
    mark("placement", t)
    t = r.pos
    s["team_raw"] = r.u(4)
    mark("team", t)
    t = r.pos
    ca = r.u(1)
    mark("color_absent", t)
    s["color"] = None
    if not ca:
        t = r.pos
        s["color"] = r.u(3)
        mark("color", t)
    t = r.pos
    ct = s["cached_type"]
    if ct == 1:
        s["extra"] = [r.u(8)]
    elif ct in (12, 13, 14):
        s["extra"] = [r.u(5), r.u(5)]
    elif ct == 19:
        if rule == "plain8":
            s["extra"] = [r.u(8)]
        else:
            flag = r.u(1)
            s["extra"] = [1, 0] if flag else [0, r.u(8)]
    else:
        s["extra"] = []
    mark("extras", t)
    # hard checks of SPEC 3.10 rule 1 and 3
    if s["in_bounds"] == 0:
        raise WalkReject("oob", "out of bounds at slot %d" % idx, slot=idx, bit=r.pos)
    if s["up_code"] is not None and s["up_code"] // 174762 > 5:
        raise WalkReject("upface", "up code %d has face %d at slot %d" % (s["up_code"], s["up_code"] // 174762, idx), slot=idx, bit=r.pos)
    if s["parent_raw"] > 651:
        raise WalkReject("parent", "parent %d above 651 at slot %d" % (s["parent_raw"], idx), slot=idx, bit=r.pos)
    if core_only:
        return s                                    # checks 3(b, label presence) and 3(c) carry evidence tag I (SPEC 3.10): skipped
    if s["folder"] is not None and s["folder"] >= quota_count:
        raise WalkReject("folder", "folder %d >= quota_count %d at slot %d" % (s["folder"], quota_count, idx), slot=idx, bit=r.pos)
    if s["label"] is not None:
        if s["label"] >= label_count or label_offsets[s["label"]] is None:
            raise WalkReject("label", "label %r not a present entry (count %d) at slot %d" % (s["label"], label_count, idx),
                             slot=idx, bit=r.pos)
    return s


def my_axis_bits(rng, variant):
    """Axis bits for one range (SPEC 4.1), the walker's own copy of the three variants."""
    def f(x):
        return struct.unpack(">f", struct.pack(">f", x))[0]

    def bc(n):
        return 0 if n <= 1 else (n - 1).bit_length()
    if variant == "ceil":
        step = 0.00833333333 / 32
        step *= 2
        return min(26, bc(min(0x800000, math.ceil(rng / step))))
    if variant == "trunc9999":
        step = f(f(f(0.00833333333) / 32.0) * 2.0)
        q = f(f(f(rng) / step) + f(0.9999))
        return min(26, bc(int(min(8388608.0, q))))
    step = f(f(f(0.008333333767950535) / 32.0) * 2.0)
    return min(26, bc(min(0x800000, math.ceil(f(f(rng) / step)))))


def axis_triples(bounds):
    """Distinct axis-bit triples from 2 range computations x 3 rounding variants, in first-seen order."""
    b = [bits.f32_round(x) for x in bounds]
    ranges_double = [b[1] - b[0], b[3] - b[2], b[5] - b[4]]
    ranges_f32 = [bits.f32_round(x) for x in ranges_double]
    out = []
    for rngs in (ranges_double, ranges_f32):
        for variant in ("ceil", "trunc9999", "ceil_f32"):
            t = tuple(my_axis_bits(x, variant) for x in rngs)
            if t not in out:
                out.append(t)
    return out


def walk(stream, L, length_class, hyp, core_only=False):
    """Decode ``stream`` under hypothesis ``hyp`` = (type19_rule, axis_bits, guid_present).  Raises WalkReject.
    ``core_only`` leaves out the two hard checks the spec itself marks as unsourced (3.10 rule 3: label entry presence and
    folder < quota_count)."""
    rule, axes, guid = hyp
    r = bits.BitSource(stream, consts.STREAM_CAPACITY_BITS)
    sections = {}
    spans = {}
    out = {}
    try:
        sections["header"] = r.pos
        out["header"] = read_header(r)
        sections["body_fixed"] = r.pos
        out["body"] = read_body(r)
        body = out["body"]
        if body["quota_count"] > 256:
            raise WalkReject("quota_count", "quota_count %d above 256" % body["quota_count"], bit=r.pos)
        bnd = body["bounds"]
        if not all(math.isfinite(x) for x in bnd) or bnd[0] > bnd[1] or bnd[2] > bnd[3] or bnd[4] > bnd[5]:
            raise WalkReject("bounds", "bounds not valid", bit=r.pos)
        sections["labels"] = r.pos
        out["labels"] = read_labels(r)
        sections["guid"] = None
        out["guid"] = None
        if guid:
            sections["guid"] = r.pos
            out["guid"] = r.u(128).to_bytes(16, "big")
        sections["slots"] = r.pos
        slots, ranges = {}, {}
        lab = out["labels"]
        for i in range(651):
            start = r.pos
            if not r.u(1):
                continue
            sp = [("present", start, r.pos)]
            slots[i] = read_slot(r, i, axes, rule, body["quota_count"], lab["count"], lab["offsets"], sp, core_only)
            ranges[i] = (start, r.pos)
            spans[i] = sp
        out["slots"], out["slot_ranges"], out["slot_field_spans"] = slots, ranges, spans
        sections["quotas"] = r.pos
        out["quotas"] = [[r.u(8), r.u(8), r.u(8)] for _ in range(body["quota_count"])]
        sections["end"] = r.pos
    except bits.BitOverrun as exc:
        raise WalkReject("overrun", str(exc), bit=r.pos)
    end = r.pos
    if length_class == "ceil_end" and (end + 7) // 8 != L:
        raise WalkReject("length", "ceil(end/8) = %d but L = %d" % ((end + 7) // 8, L), bit=end)
    out["sections"] = sections
    out["end"] = end
    rest = r.bits(end, consts.STREAM_CAPACITY_BITS)
    out["tail_nonzero"] = "1" in rest
    return out


def decode_signature(dec):
    """What "decodes identically" means (SPEC 3.10): the slot tuples and the end bit."""
    return (dec["end"], tuple((i, tuple(sorted((k, tuple(v) if isinstance(v, list) else v) for k, v in s.items())))
                              for i, s in sorted(dec["slots"].items())))


# =====================================================================================================
# Reading a whole file
# =====================================================================================================

def read(data, core_only=False):
    """Read ``data`` like a conforming reader.  Returns {"outcome": "ok", ...} or {"outcome": "error", "error": kind, ...}.
    ``core_only`` disables the two unsourced hard checks (see ``walk``)."""
    try:
        return _read(data, core_only)
    except ReadError as exc:
        return {"outcome": "error", "error": exc.kind, "message": exc.message, "slot": exc.slot}


def _read(data, core_only=False):
    c = container(data)
    warnings = check_mvar_block(c)
    block = c["mvar_bytes"]
    fl = detect_flavour(block)
    stream = fl["stream"]
    readings = fl["readings"]
    # the header needs no hypothesis: read it once for the content type, the version and the bounds
    r = bits.BitSource(stream, consts.STREAM_CAPACITY_BITS)
    try:
        header = read_header(r)
        if header["content_type"] != 5:
            raise ReadError("UnsupportedVariantError", "The content type is %d; a map variant is 5." % header["content_type"])
        body = read_body(r)
    except bits.BitOverrun:
        raise ReadError("DesyncError", "header runs past the end of the stream")
    if body["version"] not in (31, 32):
        raise ReadError("UnsupportedVariantError", "The map variant body version is %d; supported versions are 31 and 32." % body["version"])
    bnd = body["bounds"]
    for k, ax in enumerate("xyz"):
        lo, hi = bnd[2 * k], bnd[2 * k + 1]
        if not (math.isfinite(lo) and math.isfinite(hi)) or lo > hi:
            raise ReadError("FormatError", "The map bounds are not valid (axis %s: min %g, max %g)." % (ax, lo, hi))
    if c["mvar_header"]["version"] != body["version"]:
        warnings.append("W_VERSION_MISMATCH")
    if any(bnd[2 * k] == bnd[2 * k + 1] for k in range(3)):
        warnings.append("W_ZERO_RANGE_AXIS")

    implied = body["version"] >= 32
    triples = axis_triples(bnd)
    classes = []
    stored = block[consts.MVAR_LENGTH_OFFSET:consts.MVAR_LENGTH_OFFSET + 4]
    for endian, L in readings:
        if fl["zero_length_bytes"]:
            classes.append((endian, consts.MVAR_STREAM_CAPACITY, "zero"))
        elif L == consts.MVAR_STREAM_CAPACITY:
            classes.append((endian, L, "capacity"))
        else:
            classes.append((endian, L, "ceil_end"))
    table = []
    accepted = []
    for guid in (implied, not implied):
        for rule in TYPE19_ORDER:
            for triple in triples:
                hyp = (rule, triple, guid)
                best = None
                reason = None
                for endian, L, klass in classes:
                    try:
                        dec = walk(stream, L, klass, hyp, core_only)
                        # a "capacity"/"zero" class passes rule 2 by itself; "ceil_end" was checked inside walk()
                        best = (dec, endian, L, klass)
                        break
                    except WalkReject as exc:
                        reason = exc
                entry = {"type19": rule, "axis_bits": list(triple), "guid": guid, "accepted": best is not None,
                         "reason": None if best else reason.kind, "reason_detail": None if best else reason.message,
                         "slot": None if best else reason.slot}
                table.append(entry)
                if best:
                    accepted.append((hyp, best))
    result = {"outcome": None, "table": table, "shape": c["shape"], "warnings": warnings, "container": c, "flavours": fl["matches"],
              "header": header, "body": body}
    group = [a for a in accepted if a[0][2] == implied]
    mismatch = False
    if not group:
        group = [a for a in accepted if a[0][2] != implied]
        mismatch = bool(group)
    if not group:
        # nothing accepted: OutOfBounds when every hypothesis of the version-implied group fails at the same slot
        implied_rows = [e for e in table if e["guid"] == implied]
        oob_slots = set(e["slot"] for e in implied_rows if e["reason"] == "oob")
        if implied_rows and all(e["reason"] == "oob" for e in implied_rows) and len(oob_slots) == 1:
            slot = oob_slots.pop()
            result.update({"outcome": "error", "error": "OutOfBoundsPositionError", "slot": slot,
                           "message": "Slot %d has a position outside the map bounds (in-bounds flag is 0)." % slot})
            all_rows = table
            result["oob_all_hypotheses_same_slot"] = (all(e["reason"] == "oob" for e in all_rows)
                                                      and len(set(e["slot"] for e in all_rows)) == 1)
        else:
            result.update({"outcome": "error", "error": "DesyncError",
                           "message": "none of the %d known layouts fits." % len(table)})
        return result
    sigs = {}
    for hyp, best in group:
        sigs.setdefault(decode_signature(best[0]), []).append((hyp, best))
    if len(sigs) > 1:
        result.update({"outcome": "error", "error": "AmbiguousLayoutError",
                       "message": "%d different readings fit." % len(sigs)})
        return result
    hyp, best = group[0]
    dec, endian, L, klass = best
    rules = sorted(set(h[0][0] for h in group))
    if mismatch:
        warnings.append("W_GUID_VERSION_MISMATCH")
    flavour = None
    for e, rec, length in fl["matches"]:
        if e == endian and length == L:
            flavour = {"length_endian": e, "recipe": rec}
            break
    if flavour is None and fl["matches"]:
        flavour = {"length_endian": fl["matches"][0][0], "recipe": fl["matches"][0][1]}
    result.update({
        "outcome": "ok", "decoded": dec, "hypothesis": {"type19": hyp[0], "axis_bits": list(hyp[1]), "guid": hyp[2]},
        "type19_status": "undetermined" if len(rules) > 1 else rules[0], "guid_contradicts_version": mismatch,
        "length": L, "length_class": klass, "length_endian": endian, "flavour": flavour,
        "accepted": [{"type19": h[0], "axis_bits": list(h[1]), "guid": h[2]} for h, _ in accepted],
        "stored_hash": fl["stored_hash"].hex(), "eof_endian": c["eof"]["endian"],
    })
    return result


# =====================================================================================================
# Comparison with the declared model
# =====================================================================================================

def compare(res, model, info=None):
    """Differences between a read result and the builder's declared model (empty list = agreement)."""
    diffs = []
    if res["outcome"] != "ok":
        return ["read failed: %s %s" % (res.get("error"), res.get("message"))]
    dec = res["decoded"]
    h, mh = dec["header"], model["header"]
    for key in ("ids", "activity", "game_mode", "engine", "map_id", "category", "title_units", "description_units",
                "hopper_id", "campaign", "firefight", "created_by", "modified_by"):
        if h[key] != mh[key]:
            diffs.append("header.%s: walker %r, declared %r" % (key, h[key], mh[key]))
    if h["content_type"] != mh["content_type"]:
        diffs.append("header.content_type: walker %r, declared %r" % (h["content_type"], mh["content_type"]))
    if mh["file_length"] is not None and h["file_length"] != mh["file_length"]:
        diffs.append("header.file_length: walker %r, declared %r" % (h["file_length"], mh["file_length"]))
    if info is not None and h["file_length"] != info["file_length"]:
        diffs.append("header.file_length: walker %r, builder %r" % (h["file_length"], info["file_length"]))
    for key, want in model["body"].items():
        if key == "bounds":
            if [bits.f32_round(x) for x in want] != dec["body"]["bounds"]:
                diffs.append("body.bounds: walker %r, declared %r" % (dec["body"]["bounds"], want))
        elif dec["body"][key] != want:
            diffs.append("body.%s: walker %r, declared %r" % (key, dec["body"][key], want))
    lab, ml = dec["labels"], model["labels"]
    for key in ("count", "offsets", "compressed", "data_length"):
        if lab[key] != ml[key]:
            diffs.append("labels.%s: walker %r, declared %r" % (key, lab[key], ml[key]))
    if lab["buffer"] != ml["buffer"]:
        diffs.append("labels.buffer differs")
    if dec["guid"] != model["guid"]:
        diffs.append("guid: walker %r, declared %r" % (dec["guid"], model["guid"]))
    if sorted(dec["slots"]) != sorted(model["slots"]):
        diffs.append("present slots: walker %s, declared %s" % (sorted(dec["slots"])[:8], sorted(model["slots"])[:8]))
    else:
        for i in sorted(dec["slots"]):
            a, b = dec["slots"][i], model["slots"][i]
            for key in b:
                if a[key] != b[key]:
                    diffs.append("slot %d %s: walker %r, declared %r" % (i, key, a[key], b[key]))
    if dec["quotas"] != model["quotas"]:
        diffs.append("quota rows differ")
    if dec["tail_nonzero"] != any(c == "1" for c in model["tail"]):
        diffs.append("tail: walker nonzero=%r" % dec["tail_nonzero"])
    if res["hypothesis"]["axis_bits"] != model["layout"]["axis_bits"]:
        diffs.append("axis bits: walker %r, declared %r" % (res["hypothesis"]["axis_bits"], model["layout"]["axis_bits"]))
    if info is not None:
        want = info["sections"]
        got = dec["sections"]
        for key in ("header", "body_fixed", "labels", "guid", "slots", "quotas", "end"):
            if got[key] != want[key]:
                diffs.append("section %s: walker %r, builder %r" % (key, got[key], want[key]))
        if {i: tuple(v) for i, v in dec["slot_ranges"].items()} != {i: tuple(v) for i, v in info["slot_ranges"].items()}:
            diffs.append("slot bit ranges differ")
        if dec["slot_field_spans"] != {i: [tuple(x) for x in v] for i, v in info["slot_field_spans"].items()}:
            diffs.append("per-field bit spans differ")
        if res["length"] != info["L"]:
            diffs.append("L: walker %r, builder %r" % (res["length"], info["L"]))
        if res["stored_hash"] != info["stored_hash"]:
            diffs.append("stored hash differs")
    return diffs


def check_chdr(data, res):
    """The chdr block against the bit-form header (SPEC 2.4, 3.2 consistency checks).  Returns differences."""
    c = res["container"]
    chdr = [b for b in c["blocks"] if b["sig"] == "chdr"][0]
    raw = data[chdr["offset"]:chdr["offset"] + chdr["size"]]
    h = res["header"]
    diffs = []
    if len(raw) != 0x2C0:
        return ["chdr is %d bytes" % len(raw)]
    content = struct.unpack_from("<b", raw, 0x10)[0]
    flen = struct.unpack_from("<I", raw, 0x14)[0]
    mapid = struct.unpack_from("<I", raw, 0x3C)[0]
    if content != h["content_type"]:
        diffs.append("chdr content type %d, stream %d" % (content, h["content_type"]))
    if flen != h["file_length"]:
        diffs.append("chdr file length %d, stream %d" % (flen, h["file_length"]))
    if mapid != h["map_id"]:
        diffs.append("chdr map id 0x%X, stream 0x%X" % (mapid, h["map_id"]))
    for off, key in ((0x90, "title_units"), (0x190, "description_units")):
        units = list(struct.unpack_from("<128H", raw, off))
        want = h[key] + [0] * (128 - len(h[key]))
        if units != want:
            diffs.append("chdr %s differs from the stream header" % key)
    if struct.unpack_from("<b", raw, 0x38)[0] != h["activity"] or raw[0x39] != h["game_mode"]:
        diffs.append("chdr activity/game mode differ")
    return diffs


def set_bits(stream, start, width, value):
    """Overwrite ``width`` bits of ``stream`` at bit ``start`` (MSB-first) with ``value``; returns new bytes."""
    total = 8 * len(stream)
    shift = total - start - width
    v = int.from_bytes(stream, "big")
    v = (v & ~(((1 << width) - 1) << shift)) | (value << shift)
    return v.to_bytes(len(stream), "big")


def expand_cmp(data):
    """The DEC-2.6 expanded form of a cmp4 / cmp4+fsm file, derived here without the builder: the inflated mvar block in place of
    the wrapper, the embedded fileLength (stream bit 4), the chdr fileLength and the _eof offset re-stamped to the expanded
    length, the hash recomputed with the detected flavour; the _fsm block (and any trailer) verbatim."""
    c = container(data)
    if not c["cmp"]:
        raise ValueError("not a _cmp file")
    inner = c["mvar_bytes"]
    flav = detect_flavour(inner)
    if not flav["matches"]:
        raise ValueError("no hash recipe matches")
    endian, recipe, length = flav["matches"][0]
    new_len = 0x30 + 0x2C0 + len(inner) + 0x11
    chdr = bytearray(data[0x30:0x30 + 0x2C0])
    struct.pack_into("<I", chdr, 0x14, new_len)
    stream = set_bits(flav["stream"], 4, 32, new_len)
    stored = bytes(20) if recipe == "zero" else digest(recipe, stream, length)
    mvar = inner[:12] + stored + inner[32:36] + stream + inner[36 + consts.MVAR_STREAM_CAPACITY:]
    eof_block = [b for b in c["blocks"] if b["sig"] == "_eof"][0]
    eof_hdr = data[eof_block["offset"]:eof_block["offset"] + 12]
    eof_offset = 0x30 + 0x2C0 + len(mvar)
    eof_body = eof_offset.to_bytes(4, "big" if c["eof"]["endian"] in (">", None) else "little") + b"\x00"
    return data[:0x30] + bytes(chdr) + mvar + eof_hdr + eof_body + data[eof_block["offset"] + eof_block["size"]:]


# =====================================================================================================
# The "expect" block of a spec (derived from bytes only)
# =====================================================================================================

def analyse(data, core_only=False):
    """The facts a reader must find in ``data``; this is what is stored under ``expect`` in the spec files."""
    res = read(data, core_only)
    if res["outcome"] != "ok":
        out = {"outcome": "error", "error": res["error"]}
        if res.get("slot") is not None:
            out["slot"] = res["slot"]
        out["message_hint"] = res["message"]
        if res["error"] == "OutOfBoundsPositionError":
            out["oob_all_hypotheses_same_slot"] = res["oob_all_hypotheses_same_slot"]
        if "table" in res:
            out["hypotheses"] = _table_for_json(res["table"])
        return out
    dec = res["decoded"]
    exp = {
        "outcome": "ok",
        "shape": res["shape"],
        "file_length": dec["header"]["file_length"],
        "size": len(data),
        "flavour": res["flavour"],
        "length": res["length"],
        "length_class": res["length_class"],
        "eof_endian": res["eof_endian"],
        "header_end": dec["sections"]["body_fixed"],
        "end_bit": dec["end"],
        "sections": dec["sections"],
        "slot_ranges": {str(i): list(v) for i, v in sorted(dec["slot_ranges"].items())},
        "present_slots": sorted(dec["slots"]),
        "label_texts": _label_texts(dec["labels"]),
        "hypothesis": res["hypothesis"],
        "type19_status": res["type19_status"],
        "guid_contradicts_version": res["guid_contradicts_version"],
        "accepted_hypotheses": res["accepted"],
        "hypotheses": _table_for_json(res["table"]),
        "read_warnings": sorted(set(res["warnings"])),
        "stored_hash": res["stored_hash"],
        "free_bits": consts.STREAM_CAPACITY_BITS - dec["end"],
    }
    return exp


def _label_texts(lab):
    out = []
    for o in lab["offsets"]:
        if o is None:
            out.append(None)
        else:
            end = lab["buffer"].find(b"\x00", o)
            out.append(lab["buffer"][o:end if end >= 0 else len(lab["buffer"])].decode("latin-1"))
    return out


def _table_for_json(table):
    out = []
    for e in table:
        row = {"type19": e["type19"], "axis_bits": e["axis_bits"], "guid": e["guid"], "accepted": e["accepted"]}
        if not e["accepted"]:
            row["reject"] = e["reason"]
            if e["slot"] is not None:
                row["slot"] = e["slot"]
        out.append(row)
    return out


# =====================================================================================================
# Codec functions (SPEC 4.2 to 4.5): the walker's own copies, used for the golden vectors
# =====================================================================================================

def f32(x):
    return bits.f32_round(x)


def pos_cell(nbits, mn, mx):
    return (mx - mn) / float(1 << nbits)


def pos_decode(q, nbits, mn, mx):
    return (q + 0.5) * pos_cell(nbits, mn, mx) + mn


def pos_encode(v, nbits, mn, mx):
    if not (mn <= v < mx):
        raise ValueError("position %r outside [%r, %r)" % (v, mn, mx))
    return min((1 << nbits) - 1, int(math.floor((v - mn) / pos_cell(nbits, mn, mx))))


def pos_tolerance(nbits, mn, mx):
    m = max(abs(mn), abs(mx))
    ulp = 2.0 ** (math.floor(math.log2(m)) - 23) if m > 0 else 0.0
    return max(1.0e-3, 0.5 * pos_cell(nbits, mn, mx), 2 * ulp)


def dim_decode(v):
    if v == 0:
        return 0.0
    if v == 0x7FF:
        return 200.0
    return (v - 1) * 0.0977517142892 + 0.0488758571446


def dim_encode(x):
    if x < 0.0 or x > 200.0:
        raise ValueError("dimension %r outside 0..200" % (x,))
    if x == 0.0:
        return 0
    if x == 200.0:
        return 0x7FF
    return max(1, min(2046, int(math.floor(x * 2046.0 / 200.0 + 1.0))))


ANGLE_STEP = 2 * math.pi / 16384


def angle_decode(raw):
    return (raw + 0.5) * ANGLE_STEP - math.pi


def angle_encode(theta):
    return max(0, min(16383, int(math.floor((theta + math.pi) / ANGLE_STEP))))


def up_decode(code):
    face = code // 174762
    if face > 5:
        raise ValueError("up code %d: face %d" % (code, face))
    rem = code - face * 174762
    u, v = rem // 417, rem % 417
    cu, cv = (2 * u + 1) / 416.0 - 1.0, (2 * v + 1) / 416.0 - 1.0
    vec = {0: (1, cu, cv), 1: (cu, 1, cv), 2: (cu, cv, 1), 3: (-1, cu, cv), 4: (cu, -1, cv), 5: (cu, cv, -1)}[face]
    n = math.sqrt(sum(x * x for x in vec))
    return tuple(x / n for x in vec), face, u, v


# =====================================================================================================
# Golden codec vectors (SPEC 4.10)
# =====================================================================================================

def _close(a, b, tol):
    return abs(a - b) <= tol


def compute_codec_vectors():
    """Every vector of SPEC 4.10, computed here and cross-checked against the number printed in the spec.
    Raises AssertionError naming the vector when the computed value and the printed one disagree."""
    problems = []

    def check(vid, computed, printed, tol):
        if printed is not None and not _close(computed, printed, tol):
            problems.append("%s: computed %r, spec prints %r" % (vid, computed, printed))

    out = {"schema": "mjolnir.codec_vectors/1",
           "source": "docs/mvar/SPEC-mvar.md section 4 (values computed by tests/fixturebuilder/selfcheck.py and cross-checked "
                     "against the numbers printed there; 'printed' is the spec's own literal, null where it prints none)"}

    # --- G-AX ---------------------------------------------------------------------------------------
    step_js = 0.00833333333 / 32 * 2
    step_f32 = 0.0005208333604969084
    ax = []

    def ax_entry(vid, ranges, printed):
        row = {"id": vid, "ranges": list(ranges)}
        for variant in ("ceil", "trunc9999", "ceil_f32"):
            row[variant] = [my_axis_bits(r, variant) for r in ranges]
        row["printed"] = printed
        for variant, want in (printed or {}).items():
            if row[variant] != want:
                problems.append("%s %s: computed %r, spec prints %r" % (vid, variant, row[variant], want))
        ax.append(row)
    ax_entry("G-AX-1", [1024.0, 1024.0, 1024.0], {"ceil": [21, 21, 21]})
    ax_entry("G-AX-2", [480.0, 690.0, 140.0], {"ceil": [20, 21, 19]})
    for k in range(15, 23):
        r = (2.0 ** k) * step_js
        ax_entry("G-AX-3/k=%d" % k, [r, r, r], {"ceil": [k] * 3, "trunc9999": [k + 1] * 3, "ceil_f32": [k] * 3})
    ax_entry("G-AX-3/k=23", [(2.0 ** 23) * step_js] * 3, {"ceil": [23] * 3, "trunc9999": [23] * 3, "ceil_f32": [23] * 3})
    ax_entry("G-AX-4", [34.0, 34.2, 0.0], {"ceil": [16, 17, 0]})
    ax_entry("G-AX-5/4369.07", [4369.07] * 3, {"ceil": [23] * 3})
    ax_entry("G-AX-5/100000", [100000.0] * 3, {"ceil": [23] * 3})
    for k in range(15, 23):
        r = f32((2.0 ** k) * step_f32)
        ax_entry("G-AX-6/k=%d" % k, [r, r, r], {"ceil": [k + 1] * 3, "trunc9999": [k + 1] * 3, "ceil_f32": [k] * 3})
    ax_entry("G-AX-6/k=23", [f32((2.0 ** 23) * step_f32)] * 3, {"ceil": [23] * 3, "trunc9999": [23] * 3, "ceil_f32": [23] * 3})
    out["axis_bits"] = ax

    # --- G-POS --------------------------------------------------------------------------------------
    pos = []

    def pos_entry(vid, fn, **kw):
        kw["id"] = vid
        kw["fn"] = fn
        pos.append(kw)
    for q, printed in ((0, 0.000244140625), (1, 0.000732421875), (2097151, 1023.999755859375)):
        v = pos_decode(q, 21, 0.0, 1024.0)
        check("G-POS-1/q=%d" % q, v, printed, 1e-12)
        pos_entry("G-POS-1/q=%d" % q, "pos_decode", q=q, bits=21, min=0.0, max=1024.0, expect=v, printed=printed, tol=1e-12)
    v = pos_decode(524288, 20, -240.0, 240.0)
    check("G-POS-2", v, 0.0002288818359375, 1e-12)
    pos_entry("G-POS-2", "pos_decode", q=524288, bits=20, min=-240.0, max=240.0, expect=v, printed=0.0002288818359375, tol=1e-12)
    pos_entry("G-POS-2/cell", "pos_cell", bits=20, min=-240.0, max=240.0, expect=pos_cell(20, -240.0, 240.0),
              printed=0.000457763671875, tol=1e-15)
    value = 1.0002288818359375
    q = pos_encode(value, 20, -240.0, 240.0)
    if q != 526473:
        problems.append("G-POS-3: encode gave %d, spec prints 526473" % q)
    pos_entry("G-POS-3", "pos_encode", value=value, bits=20, min=-240.0, max=240.0, expect=q, printed=526473, tol=0)
    d = pos_decode(526473, 20, -240.0, 240.0)
    check("G-POS-3/decode", d, 1.0004425048828125, 1e-12)
    pos_entry("G-POS-3/decode", "pos_decode", q=526473, bits=20, min=-240.0, max=240.0, expect=d, printed=1.0004425048828125, tol=1e-12)
    try:
        pos_encode(240.0, 20, -240.0, 240.0)
        problems.append("G-POS-4: encode of the maximum was not refused")
    except ValueError:
        pass
    pos_entry("G-POS-4", "pos_encode", value=240.0, bits=20, min=-240.0, max=240.0, expect="refused", printed="refused", tol=0)
    blender = pos_decode(524288, 20, -240.0, 240.0) + 0.0004
    tol = pos_tolerance(20, -240.0, 240.0)
    unchanged = abs(blender - pos_decode(524288, 20, -240.0, 240.0)) <= tol
    if not unchanged or pos_encode(blender, 20, -240.0, 240.0) != 524289:
        problems.append("G-POS-5: expected 'unchanged' with a plain encode of 524289")
    pos_entry("G-POS-5", "pos_unchanged", q=524288, bits=20, min=-240.0, max=240.0, blender_offset=0.0004, expect=True,
              plain_encode=pos_encode(blender, 20, -240.0, 240.0), tolerance=tol, printed="unchanged", tol=0)
    out["pos"] = pos

    # --- G-SH ---------------------------------------------------------------------------------------
    sh_dec = []
    for v, printed in ((0, 0.0), (1, 0.0488758571446), (2, 0.1466275714338), (1024, 100.04887957499619),
                       (2046, 199.9511315785586), (0x7FF, 200.0)):
        got = dim_decode(v)
        check("G-SH/decode %d" % v, got, printed, 1e-12)
        sh_dec.append({"id": "G-SH/decode/%d" % v, "code": v, "expect": got, "printed": printed, "tol": 1e-12})
    sh_enc = []
    for x, printed in ((0.0, 0), (0.04, 1), (10.0, 103), (100.0, 1024), (199.97, 2046), (200.0, 0x7FF)):
        got = dim_encode(x)
        if got != printed:
            problems.append("G-SH/encode %r: computed %d, spec prints %d" % (x, got, printed))
        sh_enc.append({"id": "G-SH/encode/%r" % x, "value": x, "expect": got, "printed": printed})
    sh_ref = []
    for x in (200.01, -0.01):
        try:
            dim_encode(x)
            problems.append("G-SH: %r was not refused" % x)
        except ValueError:
            pass
        sh_ref.append({"id": "G-SH/refused/%r" % x, "value": x, "expect": "refused"})
    round_trip_ok = all(dim_encode(f32(dim_decode(v))) == v for v in range(2048))
    if not round_trip_ok:
        problems.append("G-SH: dim_encode(f32(dim_decode(v))) != v for some code")
    out["shape_decode"] = sh_dec
    out["shape_encode"] = sh_enc
    out["shape_refused"] = sh_ref
    out["shape_round_trip_all_2048"] = round_trip_ok

    # --- G-ANG --------------------------------------------------------------------------------------
    ang_dec = []
    for raw, exact, js in ((0, -3.1414009059913073, -3.1414009523999997), (8192, 0.00019174759848583633, 0.00019172599999998916),
                           (16383, 3.1414009059913077, 3.1414009091999997)):
        got = angle_decode(raw)
        check("G-ANG/decode %d" % raw, got, exact, 1e-12)
        ang_dec.append({"id": "G-ANG/decode/%d" % raw, "raw": raw, "expect": got, "printed": exact, "printed_js_form": js, "tol": 1e-6})
        if not _close(got, js, 1e-6):
            problems.append("G-ANG/decode %d: JS form %r differs from %r by more than 1e-6" % (raw, js, got))
    ang_enc = []
    for label, theta, printed in (("0.0", 0.0, 8192), ("pi/2", math.pi / 2, 12288), ("-pi/2", -math.pi / 2, 4096),
                                  ("pi", math.pi, 16383), ("-pi", -math.pi, 0)):
        got = angle_encode(theta)
        if got != printed:
            problems.append("G-ANG/encode %s: computed %d, spec prints %d" % (label, got, printed))
        ang_enc.append({"id": "G-ANG/encode/" + label, "theta": theta, "theta_text": label, "expect": got, "printed": printed})
    out["angle_decode"] = ang_dec
    out["angle_encode"] = ang_enc

    # --- G-UP ---------------------------------------------------------------------------------------
    up = []
    for code, face, u, v, printed in (
            (0, 0, 0, 0, (0.5782766, -0.5768865, -0.5768865)),
            (416, 0, 0, 416, (0.5773492, -0.5759613, 0.5787370)),
            (173888, 0, 416, 416, (0.5764261, 0.5778118, 0.5778118)),
            (174762, 1, 0, 0, (-0.5768865, 0.5782766, -0.5768865)),
            (436468, 2, 208, 208, (0.0024038, 0.0024038, 0.9999942)),
            (436050, 2, 207, 207, (-0.0024038, -0.0024038, 0.9999942)),
            (1047698, 5, 416, 416, (0.5778118, 0.5778118, -0.5764261)),
            (1048571, 5, 419, 38, (0.6190499, -0.4961180, -0.6088056))):
        vec, f2, u2, v2 = up_decode(code)
        if (f2, u2, v2) != (face, u, v):
            problems.append("G-UP code %d: computed face/u/v %r, spec prints %r" % (code, (f2, u2, v2), (face, u, v)))
        for a, b in zip(vec, printed):
            if not _close(a, b, 1e-6):
                problems.append("G-UP code %d: computed %r, spec prints %r" % (code, vec, printed))
                break
        up.append({"id": "G-UP/%d" % code, "code": code, "face": face, "u": u, "v": v, "expect": list(vec),
                   "printed": list(printed), "tol": 1e-6, "dead_zone": u > 416})
    out["up_decode"] = up
    try:
        up_decode(1048572)
        problems.append("G-UP: code 1048572 was not refused")
    except ValueError:
        pass
    out["up_decode_error"] = [{"id": "G-UP/1048572", "code": 1048572, "expect": "DecodeError"}]

    # --- G-ID (data from the spec; names come from the stock object table, which this builder does not read) ----------
    out["ids"] = [
        {"id": "G-ID-1", "map": "Tempest", "object_id": 0x4708, "folder": 0x47, "item": 8, "internal": "wall_coliseum",
         "display": "Wall, Coliseum"},
        {"id": "G-ID-2/forge_world", "map": "Forge World", "object_id": 0x4600, "display": "Block, 1x1"},
        {"id": "G-ID-2/tempest", "map": "Tempest", "object_id": 0x4300, "display": "Block, 1x1"},
        {"id": "G-ID-2/battle_canyon", "map": "Battle Canyon", "object_id": 0x3900, "display": "Block, 1x1"},
        {"id": "G-ID-3/kill_boundary", "map": "Forge World", "object_id": 0x3D00, "display": "Kill Boundary"},
        {"id": "G-ID-3/safe_boundary", "map": "Forge World", "object_id": 0x3C00, "display": "Safe Boundary"},
        {"id": "G-ID-3/location_name", "map": "Forge World", "object_id": 0x9000, "display": "Location Name"},
    ]
    for row in out["ids"]:
        row["folder"] = row["object_id"] >> 8
        row["item"] = row["object_id"] & 0x1F if row["object_id"] & 0xE0 == 0 else None
        if row["item"] is None:
            problems.append("%s: object id 0x%04X has an item above 31" % (row["id"], row["object_id"]))
        row["object_id_hex"] = "0x%04X" % row["object_id"]

    # --- G-SZ ---------------------------------------------------------------------------------------
    sz = {
        "plain_file_length": consts.PLAIN_FILE_LENGTH, "plain_file_length_hex": "0x%X" % consts.PLAIN_FILE_LENGTH,
        "eof_block_offset": consts.EOF_OFFSET, "mvar_chunk_size": consts.MVAR["size"],
        "stream_file_offset": consts.BLF["size"] + consts.CHDR["size"] + consts.MVAR_STREAM_OFFSET,
        "capacity_bits": consts.STREAM_CAPACITY_BITS, "blf_size": consts.BLF["size"], "chdr_size": consts.CHDR["size"],
        "eof_size": consts.EOF["size"], "printed": {"plain_file_length": 29481, "eof_block_offset": 0x7318, "mvar_chunk_size": 0x7028,
                                                    "stream_file_offset": 0x314, "capacity_bits": 229376},
    }
    for key, want in sz["printed"].items():
        if sz[key] != want:
            problems.append("G-SZ %s: computed %r, spec prints %r" % (key, sz[key], want))
    out["sizes"] = sz

    # --- G-HASH -------------------------------------------------------------------------------------
    data = consts.HASH_TEST_VECTOR_DATA
    printed_hashes = {
        "salted_be32": "6f0d524ee1491d003958ab5065fa74db67f4cc7e", "plain_le32": "908ea657bfe5b911f8752827b0c8e5ad9fef06b3",
        "salted_le32": "134da971af17127d0854f27a1a4dd49b2aa9a671",
        "plain_be32": "6df6c8eef85b2a16452be2f9adf695fa478b61c2", "data_only": "494179714a6cd627239dfededf2de9ef994caf03",
    }
    hashes = {}
    for recipe in RECIPES:
        got = digest(recipe, data, consts.HASH_TEST_VECTOR_L).hex()
        hashes[recipe] = got
        if got != printed_hashes[recipe]:
            problems.append("G-HASH %s: computed %s, spec prints %s" % (recipe, got, printed_hashes[recipe]))
    out["hashes"] = {"data_hex": data.hex(), "L": consts.HASH_TEST_VECTOR_L, "salt34_hex": consts.SALT34.hex(),
                     "digests": hashes, "printed": printed_hashes}

    # --- G-REAL (transcribed from the spec; this module never opens a real file) ---------------------------
    out["real_game_variants"] = {
        "note": "facts about the five distinct real game-variant files as printed in SPEC 4.10; transcribed, not recomputed here",
        "file_size": 21289, "eof_value": 21272, "payload_header_start_bit": 68,
        "header_bits": [1535, 1183, 2287, 2271, 2575], "L": [4648, 3779, 7288, 2006, 3467],
        "stored_sha1_prefix": ["eda354ab", "dde9b021", "85e9acf0", "1af297bf", "d7d035eb"],
        "recipe": "salted_be32", "length_endian": "<",
    }
    out["w1"] = {"see": "tests/golden/w1_reference.json"}
    if problems:
        raise AssertionError("codec vectors disagree with the spec:\n  " + "\n  ".join(problems))
    return out


# =====================================================================================================
# W1 reference numbers, read from the spec text (Appendix C.2 to C.4)
# =====================================================================================================

def _num(text):
    return int(text.replace(",", ""))


def parse_spec_appendix_c(md):
    """Pulls every golden number of Appendix C out of the spec's markdown, so ``w1_reference.json`` is not retyped by hand."""
    import re
    start, end = md.index("## Appendix C."), md.index("## Appendix D.")
    c = md[start:end]
    c2 = c[c.index("### C.2"):c.index("### C.3")]
    c3 = c[c.index("### C.3"):c.index("### C.4")]
    c4 = c[c.index("### C.4"):]

    def row(table, label):
        for line in table.splitlines():
            if line.startswith("| " + label + " |"):
                return [cell.strip() for cell in line.strip().strip("|").split("|")]
        raise ValueError("row %r not found" % label)
    out = {"schema": "mjolnir.w1_reference/1",
           "source": "docs/mvar/SPEC-mvar.md Appendix C.1 to C.4, parsed from the spec text by tests/fixturebuilder/selfcheck.py",
           "fixture": "w1_minimal"}
    out["file_length"] = _num(re.match(r"([\d,]+) bytes", row(c2, "file length")[1]).group(1))
    out["axis_bits"] = [int(x) for x in re.search(r"Axis bits \((\d+), (\d+), (\d+)\)", c).groups()]
    starts = re.findall(r"([a-z ]+?) ([\d,]+)(?:;|$)", row(c2, "section start bits")[1])
    names = {"header": "header", "body fixed": "body_fixed", "labels": "labels", "slots": "slots", "quota table": "quotas", "end": "end"}
    out["section_starts"] = {names[k.strip()]: _num(v) for k, v in starts}
    ranges = row(c2, "slot bit ranges")[1]
    out["slot_ranges"] = {m.group(1): [_num(m.group(2)), _num(m.group(3))]
                          for m in re.finditer(r"slot (\d+) \[([\d,]+), ([\d,]+)\)", ranges)}
    out["slot_bits"] = {m.group(1): _num(m.group(2)) for m in re.finditer(r"slot (\d+) \[[\d, ]+\) = ([\d,]+) bits", ranges)}
    q = re.search(r"quota table \[([\d,]+), ([\d,]+)\) = (\d+) x 24", ranges)
    out["quota_table"] = [_num(q.group(1)), _num(q.group(2))]
    out["quota_rows"] = int(q.group(3))
    out["L"] = _num(re.search(r"\*\*(\d+)\*\*", row(c2, "L")[1]).group(1))
    hexv = lambda cell: re.search(r"`([0-9a-f]+)`", cell).group(1)
    out["flavours"] = {
        "salted_be32": {"stored_sha1": hexv(row(c2, "stored SHA-1 (salted_be32)")[1]), "file_sha256": hexv(row(c2, "file SHA-256 (salted_be32)")[1]),
                        "fixture": "w1_minimal"},
        "plain_le32": {"stored_sha1": hexv(row(c2, "stored SHA-1 (plain_le32, stored length still BE)")[1]),
                       "file_sha256": hexv(row(c2, "file SHA-256 (plain_le32)")[1]), "fixture": "plain_le32"},
    }
    edits = {}
    for name in ("E1", "E2", "E3"):
        cells = row(c3, name)
        edits[name] = {"end_bit": _num(re.match(r"([\d,]+)", cells[2]).group(1)), "L": _num(cells[3]), "stored_sha1": hexv(cells[4]),
                       "file_sha256": hexv(cells[5]), "fixture": "w1_" + name}
    m = re.search(r"E2b\*\*: same end bit ([\d,]+) and L (\d+), stored SHA-1 `([0-9a-f]+)`, file SHA-256 `([0-9a-f]+)`", c3)
    edits["E2b"] = {"end_bit": _num(m.group(1)), "L": int(m.group(2)), "stored_sha1": m.group(3), "file_sha256": m.group(4),
                    "fixture": "w1_E2b"}
    out["edits"] = edits
    heads = {}
    for line in c4.splitlines():
        m = re.match(r"\| `(hdr_\w+)` \|.*\| ([\d,]+) \| ([\d,]+) \| ([\d,]+) \| `([0-9a-f]+)` \|$", line)
        if m:
            heads[m.group(1)] = {"header_end": _num(m.group(2)), "end_bit": _num(m.group(3)), "L": _num(m.group(4)),
                                 "stored_sha1": m.group(5), "fixture": m.group(1)}
    out["headers"] = heads
    return out


def dumps(obj):
    return bits.dumps_json(obj)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["--write-golden"]:
        path = os.path.join(GOLDEN_DIR, "codec_vectors.json")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(dumps(compute_codec_vectors()))
        print("wrote " + path)
        return 0
    if argv == ["--check-golden"]:
        with open(os.path.join(GOLDEN_DIR, "codec_vectors.json"), "r", encoding="utf-8") as fh:
            same = fh.read() == dumps(compute_codec_vectors())
        print("codec_vectors.json: %s" % ("ok" if same else "DIFFERS"))
        return 0 if same else 1
    if len(argv) == 2 and argv[0] == "--write-w1-reference":
        with open(argv[1], "r", encoding="utf-8") as fh:
            ref = parse_spec_appendix_c(fh.read())
        with open(os.path.join(GOLDEN_DIR, "w1_reference.json"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(dumps(ref))
        print("wrote w1_reference.json")
        return 0
    print("usage: selfcheck.py --write-golden | --check-golden | --write-w1-reference SPEC.md")
    return 2


if __name__ == "__main__":
    sys.exit(main())
