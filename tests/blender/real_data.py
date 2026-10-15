"""Data and oracles of the real-provider Blender tests (SPEC 9.4, gate G6). Inside Blender only; no test lives here.

Everything the end-to-end tests need to know about a file WITHOUT asking the code under test:

* the files themselves: the one real Halo: Reach map variant (``0aaaf8c7-...mvar``, "Headstrong", Breakneck), read in place
  with ``rb`` only and never copied next to anything, and the synthetic fixtures of the independent builder
  (``tests/fixturebuilder``), built in memory;
* the independent reading: the builder's own walker (``tests/fixturebuilder/selfcheck.py``) decodes a file into slots,
  field bit spans, quota rows and the hash flavour, so "what changed" is judged against a second implementation of
  SPEC sections 2 to 4, never against ``mvarlib``;
* the bit-diff helpers of SPEC 5.9 (which stream bits and which bytes differ between two files) and the SHA-1 recipes.

This module does not import ``mvarlib`` or the add-on. Standard library only, Python 3.13 (Blender) and 3.9.
"""
import copy
import hashlib
import importlib
import importlib.util
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TESTS = os.path.join(REPO, "tests")
BUILDER = os.path.join(TESTS, "fixturebuilder")

ENV_REAL_MVAR = "MJOLNIR_REAL_MVAR"
REAL_MVAR_DEFAULT = os.path.expanduser("~/Local_Documents/Halo-MCC/forge/real-mvar-samples/0aaaf8c7-5ae6-43ba-bb4d-37c987f5e8b8.mvar")
REAL_SHA256 = "e514a53b61977a897ac9dbf7225085aa01b5b255f3c8079b5938ef87579bb254"
REAL_SIZE = 59392
REAL_PLAIN_SIZE = 29481          # the map variant proper; 29,911 zero bytes follow _eof
REAL_OBJECTS = 610
REAL_BOUNDS = 20000.0            # +-20000 on every axis, 23 bits per axis
REAL_BITS = 23
REAL_CELL = 40000.0 / (1 << 23)  # the position quantisation step of the real file

# plain4 layout (SPEC 2.2): the offsets used by the bit-diff contract
MVAR = 0x2F0
HASH_AT = MVAR + 12              # 20 bytes
LENGTH_AT = MVAR + 32            # 4 bytes
STREAM_AT = MVAR + 36
STREAM_END = STREAM_AT + 0x7000
STREAM_BITS = 0x7000 * 8

FORGE_WORLD = 3006
BONEYARD = 1080
BREAKNECK = 10050


# --- the real file ------------------------------------------------------------------------------
def real_mvar_path():
    return os.environ.get(ENV_REAL_MVAR) or REAL_MVAR_DEFAULT


def real_available():
    return os.path.isfile(real_mvar_path())


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def real_bytes():
    """The bytes of the real file (opened ``rb``); the SHA-256 is checked so a changed original fails loudly."""
    data = read_bytes(real_mvar_path())
    digest = hashlib.sha256(data).hexdigest()
    if digest != REAL_SHA256:
        raise AssertionError("the real map variant is not the expected file (sha256 %s)" % digest)
    return data


def file_fingerprint(path):
    """``(size, mtime_ns, sha256)`` of a file: the proof that an original was not touched."""
    stat = os.stat(path)
    return stat.st_size, stat.st_mtime_ns, hashlib.sha256(read_bytes(path)).hexdigest()


# --- the independent builder and walker ------------------------------------------------------------
_modules = {}


def builder_package():
    """The package ``fixturebuilder`` loaded straight from ``tests/fixturebuilder`` (``tests/`` is never on ``sys.path``)."""
    if "fixturebuilder" in sys.modules:
        return sys.modules["fixturebuilder"]
    spec = importlib.util.spec_from_file_location("fixturebuilder", os.path.join(BUILDER, "__init__.py"),
                                                  submodule_search_locations=[BUILDER])
    module = importlib.util.module_from_spec(spec)
    sys.modules["fixturebuilder"] = module
    spec.loader.exec_module(module)
    return module


def modules():
    """``(build, selfcheck, catalogue)`` of the independent builder."""
    if not _modules:
        builder_package()
        _modules["build"] = importlib.import_module("fixturebuilder.build")
        _modules["selfcheck"] = importlib.import_module("fixturebuilder.selfcheck")
        _modules["catalogue"] = importlib.import_module("fixturebuilder.catalogue")
    return _modules["build"], _modules["selfcheck"], _modules["catalogue"]


def spec(name):
    """A fresh copy of the committed spec ``name`` (``tests/golden/fixture_specs/<name>.json``)."""
    build, _selfcheck, _catalogue = modules()
    return copy.deepcopy(build.load_spec(name))


def build_spec(spec_dict):
    """Bytes of a fixture built from a spec dictionary."""
    build, _selfcheck, _catalogue = modules()
    return build.build(spec_dict).data


def fixture(name):
    """Bytes of the committed fixture ``name`` (built in memory by the independent builder)."""
    return build_spec(spec(name))


def w1_spec(name="w1_variant", description="W1 variant built by a Blender test"):
    """A derived copy of the reference fixture W1 (Appendix C) that tests may edit before ``build_spec``."""
    _build, _selfcheck, catalogue = modules()
    return catalogue.derive(catalogue.w1(), name, description)


def decode(data):
    """The independent walker's decode of ``data`` (slots, slot_ranges, slot_field_spans, quotas, sections, ...)."""
    _build, selfcheck, _catalogue = modules()
    result = selfcheck.read(data)
    if result.get("outcome") != "ok":
        raise AssertionError("the independent walker refuses the file: %r" % (result.get("outcome"),))
    return result["decoded"]


def read_result(data):
    """The whole result of the independent ``read`` (flavour, hypothesis, length ...), not only the decode."""
    _build, selfcheck, _catalogue = modules()
    return selfcheck.read(data)


def digest(recipe, data):
    """The SHA-1 ``recipe`` gives for the mvar block of ``data`` (stored length read from the file, either byte order)."""
    _build, selfcheck, _catalogue = modules()
    return selfcheck.digest(recipe, data[STREAM_AT:STREAM_END], stored_length(data))


def stored_length(data):
    raw = data[LENGTH_AT:LENGTH_AT + 4]
    be = struct.unpack(">I", raw)[0]
    if 1 <= be <= 0x7000:
        return be
    return struct.unpack("<I", raw)[0]


def stored_hash(data):
    return data[HASH_AT:HASH_AT + 20]


def sha1_plain_le32(data):
    """``SHA1(LE32(L) || stream[:L])`` with the L stored in ``data``: hashlib only (the real file's recipe)."""
    length = stored_length(data)
    return hashlib.sha1(struct.pack("<I", length) + data[STREAM_AT:STREAM_AT + length]).digest()


# --- the bit-diff contract (SPEC 5.9) ----------------------------------------------------------------
def stream_bits(data):
    return bin(int.from_bytes(data[STREAM_AT:STREAM_END], "big"))[2:].zfill(STREAM_BITS)


def stream_diff(a, b):
    """Stream bit positions (counted from stream bit 0) where two files differ."""
    x = int.from_bytes(a[STREAM_AT:STREAM_END], "big") ^ int.from_bytes(b[STREAM_AT:STREAM_END], "big")
    text = bin(x)[2:].zfill(STREAM_BITS)
    return [i for i, c in enumerate(text) if c == "1"]


def changed_bytes(a, b):
    """Byte offsets where two files of the same length differ."""
    assert len(a) == len(b), (len(a), len(b))
    return [i for i in range(len(a)) if a[i] != b[i]]


def bytes_outside_stream(offsets):
    return [i for i in offsets if not STREAM_AT <= i < STREAM_END]


def slot_span(decoded, slot, field):
    """``(start, end)`` stream bits of one field of a present slot, from the independent decode."""
    for name, lo, hi in decoded["slot_field_spans"][slot]:
        if name == field:
            return lo, hi
    raise KeyError(field)


def span_bytes(spans):
    """File offsets of every stream byte touched by the bit ranges ``spans``."""
    out = set()
    for lo, hi in spans:
        out.update(range(STREAM_AT + lo // 8, STREAM_AT + (hi - 1) // 8 + 1))
    return out


# --- positions ---------------------------------------------------------------------------------------
def cell_for(value, nbits=REAL_BITS, lo=-REAL_BOUNDS, hi=REAL_BOUNDS):
    """The cell a world coordinate falls into (the spec's floor rule, written out here)."""
    _build, selfcheck, _catalogue = modules()
    return selfcheck.pos_encode(value, nbits, lo, hi)


def cell_centre(cell, nbits=REAL_BITS, lo=-REAL_BOUNDS, hi=REAL_BOUNDS):
    _build, selfcheck, _catalogue = modules()
    return selfcheck.pos_decode(cell, nbits, lo, hi)


def f32(x):
    """``x`` rounded to float32 (what Blender stores for a location)."""
    return struct.unpack("<f", struct.pack("<f", x))[0]


def unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


# --- comparing two independent decodes -------------------------------------------------------------
def pos_bits_changed(dec_old, slot, new_cells):
    """Stream bit positions that differ when the position cells of ``slot`` become ``new_cells`` (values are written
    most significant bit first)."""
    out = []
    for axis, field in enumerate(("pos_x", "pos_y", "pos_z")):
        lo, hi = slot_span(dec_old, slot, field)
        width = hi - lo
        diff = dec_old["slots"][slot]["pos"][axis] ^ new_cells[axis]
        for k in range(width):
            if (diff >> (width - 1 - k)) & 1:
                out.append(lo + k)
    return sorted(out)


def slots_equal(dec_a, dec_b, ignore=(), ignore_fields=()):
    """Slot indices that differ between two decodes (the slots in ``ignore`` are skipped; ``ignore_fields`` names the
    fields that are not compared in them are not skipped for the others)."""
    bad = []
    for index in sorted(set(dec_a["slots"]) | set(dec_b["slots"])):
        if index in ignore:
            continue
        if dec_a["slots"].get(index) != dec_b["slots"].get(index):
            bad.append(index)
    return bad


def fields_differing(slot_a, slot_b):
    """Names of the fields in which two decoded slot dictionaries differ."""
    return sorted(k for k in set(slot_a) | set(slot_b) if slot_a.get(k) != slot_b.get(k))


def decode_summary(decoded):
    """The parts of a decode that no object edit touches: header, body, labels (``quotas`` is compared by the caller)."""
    return {"header": decoded["header"], "body": decoded["body"], "labels": decoded["labels"], "guid": decoded["guid"]}


# --- shared fixtures -------------------------------------------------------------------------------------
def cast_spec(name="cast"):
    """Nine objects on W1's map: a block, a rifle (class 1), a box kill boundary, a tilted block, the loadout camera (class 27),
    a SCALE-labelled block, a teleporter node (class 12), a cylinder and a sphere kill boundary. Slot numbers 1, 2, 5, 9, 11 and
    20 to 23 are the cast of the stub's canned data, so the panel and replace tests can use one body for both providers."""
    spec = w1_spec(name, "a cast of every kind of object the Forge panels draw")
    spec["slots"] = [
        {"index": 1, "folder": 70, "item": 0, "pos": [524288, 1048576, 262144]},
        {"index": 2, "folder": 0, "item": 0, "pos": [524300, 1048500, 262200], "cached_type": 1, "extra": [3]},
        {"index": 5, "folder": 61, "item": 0, "pos": [123456, 654321, 98765], "shape": 3, "dims": [2047, 1024, 0, 2046],
         "spawn_seq": -5, "label": 1, "cached_type": 26, "placement": 0x0C, "team_raw": 0},
        {"index": 9, "folder": 70, "item": 0, "pos": [400000, 500000, 250000], "up_global": 0, "up_code": 436468, "angle": 5000},
        {"index": 11, "folder": 56, "item": 0, "pos": [530000, 1000000, 260000], "cached_type": 27},
        {"index": 20, "folder": 70, "item": 0, "pos": [524400, 1048600, 262300], "label": 0, "spawn_seq": -30},
        {"index": 21, "folder": 51, "item": 2, "pos": [524500, 1048700, 262400], "cached_type": 12, "extra": [3, 5]},
        {"index": 22, "folder": 61, "item": 0, "pos": [524600, 1048800, 262500], "shape": 2, "dims": [100, 50, 20]},
        {"index": 23, "folder": 61, "item": 0, "pos": [524700, 1048900, 262600], "shape": 1, "dims": [70]},
    ]
    spec["quotas"]["rows"] = {"0": [0, 8, 1], "51": [0, 8, 1], "56": [0, 8, 1], "61": [0, 16, 4], "70": [0, 32, 4]}
    return spec
