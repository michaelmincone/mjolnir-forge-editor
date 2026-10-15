"""The fixture catalogue: every fixture spec of SPEC section 11 (G2), as Python data (SPEC 9.1, Appendix C).

``all_specs()`` returns the specs in a fixed order; ``python3 -I tests/fixturebuilder/build.py --write-specs`` writes
them to ``tests/golden/fixture_specs/*.json``, which are the committed, human-readable source of truth.  A unit test
(U-20) fails when the committed JSON and this module disagree.

Everything here is data plus small helpers that edit copies of the W1 reference spec.  No bytes are produced here.
"""
import copy

if __package__:
    from . import consts
else:
    from fixturebuilder import consts

W1_NAME = "w1_minimal"

# Strings of the compressed-label fixture.  Their buffer is 281 bytes (above RVT's 0x80 compression threshold).
LABELS_COMPRESSED_STRINGS = [
    "Forge World spawn point number %d" % i for i in range(1, 7)
] + ["Kill Boundary", "Safe Boundary", "Respawn Zone", "Weapon Cache", "Vehicle Pad", "Objective Marker"]

# Frozen zlib level-9 stream of that buffer (generated once with Python's zlib 1.2.12 and checked identical with 1.3.1).  It is
# kept as a literal so the fixture bytes never depend on the zlib version of the machine that builds them.
LABELS_COMPRESSED_COMP_HEX = (
    "78da85cb4d0ac2400c86e11c2557f0f7000add88280a16dca59d4f3b3a4d86d82adede850b77cef285e7adccafe0da3c057e647929678b3ab08e7d03e70955"
    "ffc1b4046625302f8145092c691353e2958d1ac4df74940b7e75c077399b826a4836e5b5b41de8842eb609bc9740bbe68676884ff056fc0ea70fe51a62df")


def _w1_slots():
    return [
        {"index": 1, "folder": 70, "item": 0, "pos": [524288, 1048576, 262144]},
        {"index": 5, "folder": 61, "item": 0, "pos": [123456, 654321, 98765], "shape": 3, "dims": [2047, 1024, 0, 2046],
         "spawn_seq": -5, "label": 1, "cached_type": 26, "placement": 0x0C, "team_raw": 0},
        {"index": 650, "folder": 70, "item": 0, "pos": [0, 0, 0], "up_global": 0, "up_code": 436468, "angle": 16383,
         "parent_raw": 2, "label": 2, "color": 7},
    ]


def base_spec(name, description):
    """The W1 reference fixture of Appendix C, as a spec, under another name."""
    return {
        "schema": consts.SCHEMA_SPEC,
        "name": name,
        "description": description,
        "role": "positive",
        "container": {
            "shape": "plain4",
            "blf": {"version": 1, "flags": 2},
            "mvar": {"version": 31, "flags": 1, "size": 0x7028, "extra_bytes": 0},
            "length": {"endian": ">", "mode": "ceil_end", "value": None},
            "hash": {"recipe": "salted_be32"},
            "eof": {"endian": ">", "value": None},
            "fsm": None,
            "cmp": None,
            "trailer_hex": "",
            "truncate_to": None,
        },
        "header": {
            "content_type": 5,
            "file_length": None,
            "ids": ["0x0123456789ABCDEF", "0x0F1E2D3C4B5A6978", "0x1122334455667788", "0x0"],
            "activity": 0,
            "game_mode": 4,
            "engine": 1,
            "map_id": consts.FORGE_WORLD_MAP_ID,
            "category": 0,
            "created_by": {"timestamp": 1700000000, "xuid": "0x0", "name_hex": "4100", "online": 0},
            "modified_by": {"timestamp": 1700000001, "xuid": "0x0", "name_hex": "4100", "online": 0},
            "title": {"text": "W1 minimal", "nul": True},
            "description": {"text": "synthetic reference fixture", "nul": True},
            "engine_icon": 0,
            "hopper_id": None,
            "campaign": None,
            "firefight": None,
            "chdr": {"build_major": 0, "build_minor": 0xFFFF},
        },
        "body": {
            "version": 31,
            "checksum": "0xFFFFFFFF",
            "palette_crc": "0xDEADBEEF",
            "quota_count": 80,
            "map_id_2": consts.FORGE_WORLD_MAP_ID,
            "built_in": 0,
            "built_from_xml": 0,
            "bounds": [-240.0, 240.0, -345.0, 345.0, -70.0, 70.0],
            "max_budget": 30000,
            "spent_budget": 123,
        },
        "layout": {"axis_variant": "ceil", "axis_bits": None, "type19": "flag8"},
        "labels": {"strings": ["SCALE", "Kill Boundary", "Spawn"], "compressed": False},
        "guid": {"present": False, "hex": None},
        "slots": _w1_slots(),
        "quotas": {"rows": {"61": [0, 1, 1], "70": [0, 16, 2]}},
        "tail": {"bits": ""},
    }


def w1():
    return base_spec(W1_NAME, "Reference fixture W1 of SPEC Appendix C: plain4, version 31, salted_be32 hash, big-endian "
                     "stored length, 3 present objects, 3 labels, 80 quota rows.")


# =====================================================================================================
# Helpers
# =====================================================================================================

def derive(base, name, description, role=None):
    """A deep copy of ``base`` under another name."""
    spec = copy.deepcopy(base)
    spec["name"] = name
    spec["description"] = description
    if role:
        spec["role"] = role
    return spec


def quota_rows_for(slots, rows=None, maximum=255):
    """Quota rows ``(0, maximum, placed)`` where ``placed`` is the number of listed slots of each folder; ``rows`` adds or
    overrides single rows.  Keys are strings (JSON)."""
    counts = {}
    for sl in slots:
        if sl.get("folder") is not None:
            counts[sl["folder"]] = counts.get(sl["folder"], 0) + 1
    out = {str(f): [0, maximum, n] for f, n in sorted(counts.items())}
    for key, row in (rows or {}).items():
        out[str(key)] = list(row)
    return out


def set_header_text(spec, long_text=False, minimal=False):
    h = spec["header"]
    if long_text:
        name = "ABCDEFGHIJKLMNOP"                       # 16 characters, no NUL
        h["created_by"]["name_hex"] = name.encode("ascii").hex()
        h["modified_by"]["name_hex"] = name.encode("ascii").hex()
        h["title"] = {"text": "T" * 128, "nul": False}
        h["description"] = {"text": "D" * 128, "nul": False}
    if minimal:
        h["created_by"]["name_hex"] = "00"
        h["modified_by"]["name_hex"] = "00"
        h["title"] = {"text": "", "nul": True}
        h["description"] = {"text": "", "nul": True}


def set_version(spec, version):
    spec["body"]["version"] = version
    spec["container"]["mvar"]["version"] = version


GUID_HEX = "A1B2C3D4E5F60718293A4B5C6D7E8F90"


# =====================================================================================================
# The fixtures
# =====================================================================================================

def w1_edit(name, description, edit):
    spec = derive(w1(), name, description)
    edit(spec)
    return spec


def _e1(spec):
    spec["slots"][0]["pos"][0] = 526473                      # slot 1 moved by +1.0 world unit in x


def _e2(spec, angle=8192):
    spec["slots"].append({"index": 0, "folder": 70, "item": 0, "pos": [1, 2, 3], "angle": angle})
    spec["quotas"]["rows"]["70"] = [0, 16, 3]


def _e3(spec):
    spec["slots"] = [s for s in spec["slots"] if s["index"] != 5]
    spec["quotas"]["rows"]["61"] = [0, 1, 0]


def holes():
    s = derive(w1(), "holes", "Present slots scattered over the whole range 0..650 with long absent runs, parent links, every extras "
               "width (cached types 1, 12, 13, 14) and all shapes; quota rows equal the slot counts.")
    slots = [
        {"index": 0, "folder": 70, "item": 0, "pos": [1048575, 0, 262144], "angle": 0},
        {"index": 2, "folder": 61, "item": 0, "pos": [10, 20, 30], "shape": 1, "dims": [512], "label": 1, "cached_type": 26,
         "placement": 0x0C, "team_raw": 0, "parent_raw": 1},
        {"index": 3, "folder": 0, "item": 0, "pos": [500000, 1000000, 250000], "cached_type": 1, "extra": [255], "team_raw": 1},
        {"index": 4, "folder": 12, "item": 4, "pos": [2, 4, 8], "cached_type": 12, "extra": [7, 31], "color": 3, "up_global": 0,
         "up_code": 0},
        {"index": 37, "folder": 12, "item": 4, "pos": [3, 5, 7], "cached_type": 14, "extra": [0, 0], "team_raw": 5, "up_global": 0,
         "up_code": 174762, "angle": 1},
        {"index": 38, "folder": 71, "item": 8, "pos": [999999, 2000000, 500000], "shape": 2, "dims": [100, 200, 300], "label": 0,
         "cached_type": 13, "extra": [1, 2], "parent_raw": 38},
        {"index": 255, "folder": 70, "item": 0, "pos": [262144, 524288, 131072]},
        {"index": 256, "folder": 70, "item": 0, "pos": [262145, 524289, 131073], "color": 0},
        {"index": 511, "folder": 79, "item": 31, "pos": [7, 7, 7], "shape": 3, "dims": [1, 2, 3, 4], "spawn_seq": -1, "respawn": 30},
        {"index": 512, "folder": 79, "item": 31, "pos": [8, 8, 8], "spawn_seq": 127, "label": 2},
        {"index": 640, "folder": 69, "item": 1, "pos": [100, 200, 300], "team_raw": 8},
        {"index": 649, "folder": 70, "item": 0, "pos": [1, 1, 1], "parent_raw": 651},
        {"index": 650, "folder": 70, "item": 0, "pos": [1048575, 2097151, 524287], "parent_raw": 1, "label": 2, "angle": 16383},
    ]
    s["slots"] = slots
    s["quotas"]["rows"] = quota_rows_for(slots)
    return s


def _labels_256(absent):
    """A 256-entry label table "L000" .. "L255" with the given entries absent (a compact generator form in the JSON)."""
    return {"strings_gen": {"format": "L%03d", "count": 256, "absent": sorted(absent)}, "compressed": False}


def extremes():
    s = derive(w1(), "extremes", "Field extremes: shape 3 with dims 0 and 0x7FF, spawn sequence -128 and 127, team raw 0 and 9, colour "
               "absent and 7, parent raw 0 and 651, label 255 in a 256-entry table, folder 255, item 31, cached type 31, angle 0 and 16383, "
               "positions 0 and 2^bits-1, flags2 0 and 3, placement 0x00 and 0xFF; axis bits 23, 15 and 0 (z has a zero range).")
    s["header"]["map_id"] = consts.FORGE_WORLD_MAP_ID
    s["body"]["quota_count"] = 256
    s["body"]["bounds"] = [-2500.0, 2500.0, 0.0, 10.0, 50.0, 50.0]
    s["labels"] = _labels_256({3, 100, 254})
    slots = [
        {"index": 0, "flags2": 0, "folder": 0, "item": 0, "pos": [0, 0, 0], "angle": 0, "spawn_seq": -128, "respawn": 0,
         "placement": 0x00, "team_raw": 0},
        {"index": 1, "flags2": 3, "folder": 255, "item": 31, "pos": [8388607, 32767, 0], "up_global": 0, "up_code": 1048571,
         "angle": 16383, "parent_raw": 651, "shape": 3, "dims": [0, 2047, 0, 2047], "spawn_seq": 127, "respawn": 255,
         "cached_type": 31, "label": 255, "placement": 0xFF, "team_raw": 9, "color": 7},
        {"index": 2, "flags2": 1, "pos": [4194304, 16384, 0], "up_global": 0, "up_code": 0, "parent_raw": 1, "shape": 1,
         "dims": [2047], "cached_type": 13, "extra": [31, 31], "label": 0, "team_raw": 1, "color": 0},
        {"index": 3, "folder": 1, "item": 1, "pos": [1, 1, 0], "shape": 2, "dims": [0, 1, 2046], "cached_type": 12, "extra": [0, 0],
         "label": 128, "color": 4},
        {"index": 4, "folder": 128, "item": 16, "pos": [8388606, 32766, 0], "shape": 3, "dims": [2046, 1, 1024, 2047],
         "cached_type": 14, "extra": [31, 0], "label": 254 - 1},
        {"index": 5, "folder": 254, "item": 30, "pos": [2, 3, 0], "cached_type": 1, "extra": [255], "team_raw": 8},
        {"index": 6, "folder": 2, "item": 2, "pos": [3, 4, 0], "cached_type": 1, "extra": [0]},
        {"index": 650, "folder": 255, "item": 0, "pos": [8388607, 0, 0], "up_global": 0, "up_code": 436468, "angle": 8192,
         "parent_raw": 0, "respawn": 1},
    ]
    s["slots"] = slots
    s["quotas"]["rows"] = quota_rows_for(slots, rows={})
    return s


def _axes_slots(widths):
    """Objects at the first, last and middle cell of each axis."""
    mx = [(1 << w) - 1 for w in widths]
    mid = [(1 << w) >> 1 for w in widths]
    return [
        {"index": 0, "folder": 70, "item": 0, "pos": [0, 0, 0]},
        {"index": 1, "folder": 70, "item": 0, "pos": list(mx), "angle": 16383},
        {"index": 2, "folder": 70, "item": 0, "pos": list(mid), "up_global": 0, "up_code": 12345},
        {"index": 650, "folder": 70, "item": 0, "pos": [mx[0], 0, mx[2]]},
    ]


def axes_family(name, ranges, widths):
    s = derive(w1(), name, "Position field widths %s: objects at cell 0, the last cell and the middle cell of every axis "
               "(extremes family, widths 15 to 23 across extremes and the three axes_* fixtures)." % (widths,))
    lo = [-r / 2.0 for r in ranges]
    s["body"]["bounds"] = [lo[0], lo[0] + ranges[0], lo[1], lo[1] + ranges[1], lo[2], lo[2] + ranges[2]]
    s["slots"] = _axes_slots(widths)
    s["labels"] = {"strings": [], "compressed": False}
    s["quotas"]["rows"] = quota_rows_for(s["slots"])
    return s


def zero_labels():
    s = derive(w1(), "zero_labels", "A label table with 0 entries (only the 9-bit count is stored); no object has a label.")
    s["labels"] = {"strings": [], "compressed": False}
    for sl in s["slots"]:
        sl.pop("label", None)
    return s


def labels_uncompressed():
    s = derive(w1(), "labels_uncompressed", "Uncompressed label table with an absent entry, a shared offset, a non-monotonic offset "
               "and an entry that points at a NUL byte (empty text, not absent).")
    buf = b"Alpha\x00Beta\x00\x00Gamma\x00"
    s["labels"] = {"offsets": [12, None, 0, 6, 11, 6], "buffer_hex": buf.hex(), "compressed": False}
    s["slots"][0]["label"] = 0
    s["slots"][1]["label"] = 4
    s["slots"][2]["label"] = 5
    return s


def labels_compressed():
    s = derive(w1(), "labels_compressed", "Compressed label table (flag 1, 13-bit size that includes the 4-byte prefix, zlib 78 DA stream "
               "frozen as a literal) with 12 entries.")
    s["labels"] = {"strings": LABELS_COMPRESSED_STRINGS, "compressed": True, "comp_hex": LABELS_COMPRESSED_COMP_HEX}
    s["slots"][0]["label"] = 11
    s["slots"][1]["label"] = 0
    s["slots"][2]["label"] = 6
    return s


def v32():
    s = derive(w1(), "v32", "Body and chunk version 32: 128 extra bits (the map GUID) follow the label table.")
    set_version(s, 32)
    s["guid"] = {"present": True, "hex": GUID_HEX}
    return s


def cmp_fixture(fsm):
    name = "cmp_fsm" if fsm else "cmp"
    s = derive(w1(), name, "W1 content in a _cmp wrapper (stored zlib stream) %s; the embedded fileLength, the chdr fileLength and the _eof "
               "value count the compressed file, so expanding it must re-stamp them." % ("followed by an _fsm block" if fsm else ""))
    s["container"]["shape"] = "cmp4+fsm" if fsm else "cmp4"
    s["container"]["cmp"] = {"version": consts.CMP["version"], "flags": consts.CMP["flags"]}
    if fsm:
        s["container"]["fsm"] = {"version": 1, "flags": 1, "size": consts.FSM["size"], "seed": "cmp_fsm"}
    return s


def cmp_expanded(fsm):
    name = "cmp_fsm_expanded" if fsm else "cmp_expanded"
    s = derive(w1(), name, "Golden expanded form of %s (DEC-2.6): the plain %s with the file lengths re-stamped to %d and the hash "
               "recomputed." % ("cmp_fsm" if fsm else "cmp", "plain4+fsm" if fsm else "plain4", consts.PLAIN_FILE_LENGTH))
    if fsm:
        s["container"]["shape"] = "plain4+fsm"
        s["container"]["fsm"] = {"version": 1, "flags": 1, "size": consts.FSM["size"], "seed": "cmp_fsm"}
    return s


def fsm_fixture():
    s = derive(w1(), "fsm", "W1 content followed by an _fsm block (not counted in the file length fields).")
    s["container"]["shape"] = "plain4+fsm"
    s["container"]["fsm"] = {"version": 1, "flags": 1, "size": consts.FSM["size"], "seed": "fsm"}
    return s


def plain_le32():
    s = derive(w1(), "plain_le32", "W1 with the plain_le32 hash recipe (stored length still big-endian).")
    s["container"]["hash"] = {"recipe": "plain_le32"}
    return s


def le_length():
    s = derive(w1(), "le_length", "W1 with the stored length little-endian (the mpvr convention) and the salted_be32 recipe.")
    s["container"]["length"] = {"endian": "<", "mode": "ceil_end", "value": None}
    return s


def length_capacity():
    s = derive(w1(), "length_capacity", "W1 with the stored length equal to the stream capacity 0x7000 (length class capacity, SPEC 2.12); "
               "the hash covers all 0x7000 stream bytes. Extra fixture, not in the G2 list.")
    s["container"]["length"] = {"endian": ">", "mode": "capacity", "value": None}
    return s


def eof_le():
    s = derive(w1(), "eof_le", "W1 with the _eof offset value little-endian.")
    s["container"]["eof"] = {"endian": "<", "value": None}
    return s


def zero_hash():
    s = derive(w1(), "zero_hash", "W1 with a stored hash of 20 zero bytes (recipe class zero).")
    s["container"]["hash"] = {"recipe": "zero"}
    return s


def trailer():
    s = derive(w1(), "trailer", "W1 followed by 512 zero bytes after _eof (padding; shape other, kept verbatim).")
    s["container"]["trailer_hex"] = "00" * 512
    return s


def unknown_map():
    s = derive(w1(), "unknown_map", "W1 with map id 0xFFFFFFFF in the header, the body copy and chdr.")
    s["header"]["map_id"] = consts.UNKNOWN_MAP_ID
    s["body"]["map_id_2"] = consts.UNKNOWN_MAP_ID
    return s


def _mix_gen(seed, start, stop, every, types, folders=None, labels=None):
    return {"kind": "bulk", "style": "mix", "start": start, "stop": stop, "every": every, "seed": seed,
            "folders": folders or [70, 71, 61, 12], "items": [0, 1, 2, 3], "types": types, "labels": labels or [0, 1, 2]}


def guid_fixture(name, version, present, description):
    s = derive(w1(), name, description)
    set_version(s, version)
    s["guid"] = {"present": present, "hex": GUID_HEX if present else None}
    s["slots_gen"] = _mix_gen(32, 0, 300, 3, [0, 1, 12, 13, 14, 26])
    s["quotas"]["rows"] = quota_rows_for(s["slots"] + _gen_preview(s))
    return s


def _gen_preview(spec):
    """The slots a spec's generator would add (to compute quota rows); built with the builder's own expansion."""
    from_build = _build_module()
    m = from_build.normalise(dict(spec, quotas={"rows": {}}))
    return [dict(folder=sl["folder"]) for i, sl in m["slots"].items() if i not in {x["index"] for x in spec["slots"]}]


def _build_module():
    if __package__:
        from . import build
    else:
        from fixturebuilder import build
    return build


def type19_fixture(rule):
    name = "type19_" + rule
    s = derive(w1(), name, "Cached-type-19 objects (location names) stored under the %s rule (SPEC 3.8); the other rule desynchronises "
               "the walk." % rule)
    s["body"]["quota_count"] = 160
    s["layout"]["type19"] = rule
    if rule == "flag8":
        extras = [[1, 0], [0, 5], [0, 200], [0, 0], [1, 0]]
    else:
        extras = [[0], [6], [201], [1], [0]]
    s["slots_gen"] = _mix_gen(19, 10, 90, 5, [0, 1, 12, 14], folders=[70, 71, 61, 12])
    s["slots"] += [{"index": 100 + k, "folder": 144, "item": 0, "pos": [1000 * (k + 1), 2000 * (k + 1), 3000 * (k + 1)],
                    "cached_type": 19, "extra": e, "team_raw": k} for k, e in enumerate(extras)]
    s["quotas"]["rows"] = quota_rows_for(s["slots"] + _gen_preview(s))
    s["design"] = {"must_reject": [{"type19": "plain8" if rule == "flag8" else "flag8", "guid": False}]}
    return s


def axis_threshold_fixture(name, bounds_x, variant, description):
    s = derive(w1(), name, description)
    s["body"]["bounds"] = [bounds_x[0], bounds_x[1], -345.0, 345.0, -70.0, 70.0]
    s["layout"]["axis_variant"] = variant
    s["slots_gen"] = _mix_gen(20, 8, 600, 23, [0, 1, 12, 14, 26])
    s["quotas"]["rows"] = quota_rows_for(s["slots"] + _gen_preview(s))
    return s


# x range of the first fixture: 2^20 x 0.000520833333125 (the JS threshold) as a difference of two float32 bounds
THRESHOLD_JS_BOUNDS = (2.870152638934087e-05, 546.1333618164062)
# x range of the second: f32(2^20 x 0.0005208333604969084), the threshold of the engine's own float32 step (G-AX-6)
THRESHOLD_F32_BOUNDS = (0.0, 546.1333618164062)


def bulk_fixture(name, description, stop, skip):
    s = derive(w1(), name, description)
    s["slots"] = []
    s["slots_gen"] = {"kind": "bulk", "style": "w1", "start": 0, "stop": stop, "skip": skip, "seed": 650,
                      "folders": [70, 71, 72, 73], "items": [0]}
    counts = {}
    k = 0
    for i in range(0, stop):
        if i in skip:
            continue
        counts[70 + k % 4] = counts.get(70 + k % 4, 0) + 1
        k += 1
    s["quotas"]["rows"] = {str(f): [0, 255, n] for f, n in sorted(counts.items())}
    return s


NEAR_FULL_SKIP = [5, 70, 130, 200, 260, 330, 400, 470, 540, 600, 650]


def near_full():
    s = derive(w1(), "near_full", "Almost full stream: 640 present slots of the largest kind (235 bits), 256 labels, 256 quota rows, "
               "long header text and a label buffer of about 8 kB (above RVT's 4096-byte maximum; the 13-bit size field allows it) "
               "leave about 100 free bits, so adding an object cannot fit but a small edit can.")
    set_header_text(s, long_text=True)
    s["body"]["quota_count"] = 256
    s["body"]["bounds"] = [-2500.0, 2500.0, -2500.0, 2500.0, -2500.0, 2500.0]
    s["labels"] = _labels_256(set())
    s["slots"] = []
    s["slots_gen"] = {"kind": "bulk", "style": "max", "start": 0, "stop": 651, "skip": NEAR_FULL_SKIP, "seed": 235,
                      "folders": list(range(256)), "items": list(range(32)), "labels": list(range(256)), "full_types": [12, 13, 14]}
    return s


def near_full_tuned():
    """near_full with the label buffer padded so that about 100 bits stay free (computed with the builder's own bookkeeping)."""
    b = _build_module()
    s = near_full()
    counts = {}
    base_bytes = 256 * 5
    s["labels"]["pad_to"] = base_bytes
    probe = b.build(s)
    spare_bits = probe.info["free_bits"]
    extra_bytes = (spare_bits - 100) // 8
    s["labels"]["pad_to"] = base_bytes + extra_bytes
    m = b.normalise(s)
    for sl in m["slots"].values():
        counts[sl["folder"]] = counts.get(sl["folder"], 0) + 1
    s["quotas"]["rows"] = {str(f): [0, 255, n] for f, n in sorted(counts.items())}
    return s


# ---- negative fixtures -----------------------------------------------------------------------------------

def negative(name, description, error, edit):
    s = derive(w1(), name, description, role="negative")
    edit(s)
    s["expect_error"] = error
    return s


def _bad_version(s):
    s["body"]["version"] = 30


def _bad_size(s):
    s["container"]["mvar"]["size"] = 0x7030
    s["container"]["mvar"]["extra_bytes"] = 8


def _oob(s):
    s["slots"][1]["in_bounds"] = 0


def _desync_length(s):
    s["container"]["length"] = {"endian": ">", "mode": "explicit", "value": 625}


def _truncated(s):
    s["container"]["truncate_to"] = 10000


def _bad_content_type(s):
    s["header"]["content_type"] = 6


def _chunk_version(v):
    def edit(s):
        s["container"]["mvar"]["version"] = v
    return edit


def _bounds_inverted(s):
    s["body"]["bounds"] = [240.0, -240.0, -345.0, 345.0, -70.0, 70.0]
    s["layout"]["axis_bits"] = [20, 21, 19]


def negatives():
    return [
        negative("bad_version", "Body version 30 (chunk version 31): neither 31 nor 32.", "UnsupportedVariantError", _bad_version),
        negative("bad_size", "mvar block of 0x7030 bytes (tiles correctly) instead of 0x7028.", "UnsupportedVariantError", _bad_size),
        negative("oob", "Slot 5 has in_bounds = 0 (an out-of-bounds position record).", "OutOfBoundsPositionError", _oob),
        negative("desync_length", "Stored length 625 although the walk ends at bit 4970 (L would be 622): the hash matches that length but "
                 "no hypothesis fits.", "DesyncError", _desync_length),
        negative("truncated", "The file is cut at byte 10000, inside the mvar block.", "BlfFormatError", _truncated),
        negative("bad_content_type", "Content type 6 (game variant) in the header of a map-variant block.", "UnsupportedVariantError",
                 _bad_content_type),
        negative("chunk_version_50", "mvar chunk version 50 (Halo 4).", "UnsupportedVariantError", _chunk_version(50)),
        negative("chunk_version_13", "mvar chunk version 13 (Halo 3).", "UnsupportedVariantError", _chunk_version(13)),
        negative("bounds_inverted", "x bounds min 240 > max -240.", "FormatError", _bounds_inverted),
    ]


# ---- the list ---------------------------------------------------------------------------------------------

def header_fixtures():
    def hopper(s):
        s["header"]["activity"] = 2
        s["header"]["hopper_id"] = 0x1234

    def campaign(s):
        s["header"]["game_mode"] = 1
        s["header"]["campaign"] = {"id": 5, "difficulty": 2, "metagame": 1, "rally": 7, "unk": 0x01020304}

    def firefight(s):
        s["header"]["game_mode"] = 2
        s["header"]["firefight"] = {"difficulty": 3, "unk": 0xA0B0C0D0}

    out = [
        w1_edit("hdr_hopper", "W1 with decoded activity 2 (stored 3) and hopper id 0x1234.", hopper),
        w1_edit("hdr_campaign", "W1 with game mode 1 and the campaign tail (id 5, difficulty 2, metagame 1, rally 7, unk 0x01020304).",
                campaign),
        w1_edit("hdr_firefight", "W1 with game mode 2 and the firefight tail (difficulty 3, unk 0xA0B0C0D0).", firefight),
    ]
    long_text = derive(w1(), "hdr_long_text", "W1 with both author names 16 characters without a NUL and title and description of 128 "
                       "units without a NUL (names ABCDEFGHIJKLMNOP, title T x 128, description D x 128).")
    set_header_text(long_text, long_text=True)
    min_text = derive(w1(), "hdr_min_text", "W1 with author names consisting of only the NUL and an empty title and description.")
    set_header_text(min_text, minimal=True)
    return out + [long_text, min_text]


def _raw_specs():
    out = [w1(),
           w1_edit("w1_E1", "W1 edit E1: slot 1 moved by +1.0 world unit in x (x cell 524288 -> 526473).", _e1),
           w1_edit("w1_E2", "W1 edit E2: a Block, 1x1 added in slot 0 at cells (1, 2, 3), yaw 0 (angle 8192), quota row 70 placed 3.", _e2),
           w1_edit("w1_E2b", "W1 edit E2b: as E2 but angle 12288 (an unrotated Blender add).", lambda s: _e2(s, 12288)),
           w1_edit("w1_E3", "W1 edit E3: slot 5 (the kill boundary) deleted, quota row 61 placed 0.", _e3),
           holes(), extremes(),
           axes_family("axes_16_17_18", [20.0, 50.0, 100.0], [16, 17, 18]),
           axes_family("axes_19_20_21", [200.0, 400.0, 800.0], [19, 20, 21]),
           axes_family("axes_22_23_22", [1600.0, 5000.0, 1600.0], [22, 23, 22]),
           zero_labels(), labels_uncompressed(), labels_compressed(), v32(),
           cmp_fixture(False), cmp_fixture(True), cmp_expanded(False), cmp_expanded(True), fsm_fixture(),
           plain_le32(), le_length(), eof_le(), length_capacity(),
           type19_fixture("flag8"), type19_fixture("plain8"),
           axis_threshold_fixture("axis_threshold", THRESHOLD_JS_BOUNDS, "ceil",
                                  "x range = 2^20 x 0.000520833333125 (the JS threshold): ceil and ceil_f32 give 20 bits, trunc9999 21. "
                                  "Written with 20 bits."),
           axis_threshold_fixture("axis_threshold_f32", THRESHOLD_F32_BOUNDS, "ceil_f32",
                                  "x range = f32(2^20 x 0.0005208333604969084) (the float32-step threshold): ceil and trunc9999 give 21 "
                                  "bits, ceil_f32 20. Written with 20 bits, the minority reading."),
           near_full_tuned(),
           bulk_fixture("full650", "650 occupied slots over folders 70 to 73, each quota (0, 255, n).", 651, [325]),
           bulk_fixture("over650", "651 occupied slots (every slot) over folders 70 to 73, each quota (0, 255, n).", 651, []),
           unknown_map(), zero_hash(),
           guid_fixture("guid_v32_absent", 32, False, "Version 32 without the 128 extra bits (the version-implied reading is wrong)."),
           guid_fixture("guid_v31_present", 31, True, "Version 31 with the 128 extra bits present (the version-implied reading is wrong)."),
           trailer()]
    out += header_fixtures()
    out += negatives()
    return out


DESIGN = {
    "axis_threshold": {"must_reject": [{"axis_bits": [21, 21, 19], "guid": False}]},
    "axis_threshold_f32": {"must_reject": [{"axis_bits": [21, 21, 19], "guid": False}]},
    "guid_v32_absent": {"must_reject": [{"guid": True}]},
    "guid_v31_present": {"must_reject": [{"guid": False}]},
}


def annotate(spec, selfcheck):
    """Adds the ``expect`` block (derived from the bytes by the independent walker) and checks the fixture's design."""
    build = _build_module()
    spec = copy.deepcopy(spec)
    for key in ("expect", "design"):
        spec.pop(key, None)
    built = build.build(dict(spec))
    exp = selfcheck.analyse(built.data)
    if spec["role"] == "negative":
        want = spec["expect_error"]
        if exp["outcome"] != "error" or exp["error"] != want:
            raise AssertionError("%s: the walker found %r, the catalogue says %s" % (spec["name"], exp, want))
        spec["expect"] = exp
        return spec
    res = selfcheck.read(built.data)
    diffs = selfcheck.compare(res, built.model, built.info)
    diffs += selfcheck.check_chdr(built.data, res)
    if diffs:
        raise AssertionError("%s: walker and builder disagree: %s" % (spec["name"], diffs[:5]))
    design = DESIGN.get(spec["name"]) or spec.get("design_preset")
    if spec["name"].startswith("type19_"):
        other = "plain8" if spec["name"].endswith("flag8") else "flag8"
        design = {"must_reject": [{"type19": other, "guid": False}]}
    if design:
        spec["design"] = design
        core = selfcheck.analyse(built.data, core_only=True)
        for want in design["must_reject"]:
            for label, table in (("all checks", exp["hypotheses"]), ("core checks only", core["hypotheses"])):
                for row in table:
                    if all(row.get(k) == v for k, v in want.items()) and row["accepted"]:
                        raise AssertionError("%s: hypothesis %r is accepted (%s) but the fixture is designed to reject it"
                                             % (spec["name"], row, label))
                if not any(all(row.get(k) == v for k, v in want.items()) for row in table):
                    raise AssertionError("%s: no hypothesis matches %r" % (spec["name"], want))
    spec["expect"] = exp
    return spec


def all_specs():
    """Every fixture spec, with its ``expect`` block, in a fixed order."""
    if __package__:
        from . import selfcheck
    else:
        from fixturebuilder import selfcheck
    return [annotate(s, selfcheck) for s in _raw_specs()]
