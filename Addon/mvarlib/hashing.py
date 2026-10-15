"""SHA-1 recipes and hash-flavour detection for the payload block (SPEC 2.7, 6.3; promoted in gate G1).

Two independent facts differ per file, and both are detected, never assumed:

1. the byte order of the 4-byte stored stream length ``L`` (``'>'`` or ``'<'``);
2. the hash recipe: how the 20-byte SHA-1 of the payload block is computed over ``stream[0:L]``.

A :class:`HashFlavour` is the pair ``(length_endian, recipe)``. The recipes are

==============  ======================================  =====================================
name            digest input                            status
==============  ======================================  =====================================
``plain_le32``  ``LE32(L) || data``                     ``W:HMS`` (said to be MCC's own)
``salted_be32`` ``SALT34 || BE32(L) || data``           ``V`` on the real ``mpvr`` files
``salted_le32`` ``SALT34 || LE32(L) || data``           diagnostic only
``plain_be32``  ``BE32(L) || data``                     diagnostic only
``data_only``   ``data``                                diagnostic only
``zero``        no digest: the 20 hash bytes are 0x00   ``I`` for ``mvar`` (KSoft.Blam, game variants)
==============  ======================================  =====================================

``SALT34`` is a published algorithm constant (RVT ``formats/sha1.h``), not game data.

The functions take the whole payload block (``chunk``) and a ``PayloadSpec`` (from ``blf.py``; any
object with ``hash_off``, ``length_off``, ``length_endian``, ``stream_off`` and ``stream_capacity``
works, so this module does not import ``blf``).

Stored length rules (SPEC 2.7): read the 4 bytes both ways; the valid reading is the one in
``1 .. stream_capacity``; both can be valid only when the bytes are all zero. For zero bytes the
effective length is tried as ``0`` and as ``stream_capacity`` (``W:BLF``). A stored hash of 20
zero bytes is classed ``zero`` before any digest is tried.

Pure Python 3.9 to 3.13, standard library only.
"""
import hashlib
import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .errors import HashError

__all__ = ["SALT34", "HASH_SIZE", "RECIPES", "DIAGNOSTIC_RECIPES", "ZERO", "ALL_RECIPES", "HashFlavour",
           "HashAnalysis", "recipe_input", "digest", "compute", "length_readings", "analyse", "candidates",
           "detect_flavour", "fallback_flavour", "flavour_label", "encode_length"]

SALT34 = bytes([
    0xED, 0xD4, 0x30, 0x09, 0x66, 0x6D, 0x5C, 0x4A, 0x5C, 0x36, 0x57, 0xFA,
    0xB4, 0x0E, 0x02, 0x2F, 0x53, 0x5A, 0xC6, 0xC9, 0xEE, 0x47, 0x1F, 0x01,
    0xF1, 0xA4, 0x47, 0x56, 0xB7, 0x71, 0x4F, 0x1C, 0x36, 0xEC,
])
HASH_SIZE = 20
ZERO = "zero"
# Candidate order of SPEC 2.7: when two recipes would give the same digest (only possible for L == 0,
# where LE32 and BE32 are both four zero bytes) the first one in this order is reported.
RECIPES = ("plain_le32", "salted_be32", "salted_le32", "plain_be32", "data_only")
DIAGNOSTIC_RECIPES = ("salted_le32", "plain_be32", "data_only")
ALL_RECIPES = RECIPES + (ZERO,)


@dataclass(frozen=True, eq=False)
class HashFlavour:
    """``(length_endian, recipe)``: byte order of the stored length and the hash recipe.

    A frozen dataclass that also behaves like the pair it is named after: it compares equal to (and
    hashes like) the plain tuple ``('<', 'salted_be32')``, unpacks, and indexes. The spec writes the
    detection result both ways (SPEC 6.3 as a class, 9.1 as a pair), so both forms work.
    """
    length_endian: str            # '>' | '<'
    recipe: str                   # one of RECIPES, or 'zero'

    def __post_init__(self):
        if self.length_endian not in (">", "<"):
            raise HashError("A length byte order must be '>' or '<', got %r." % (self.length_endian,))
        if self.recipe not in ALL_RECIPES:
            raise HashError("Unknown hash recipe %r; expected one of %s." % (self.recipe, ", ".join(ALL_RECIPES)))

    def as_tuple(self):
        return (self.length_endian, self.recipe)

    def __eq__(self, other):
        if isinstance(other, HashFlavour):
            return self.as_tuple() == other.as_tuple()
        if isinstance(other, tuple):
            return self.as_tuple() == other
        return NotImplemented

    def __hash__(self):
        return hash(self.as_tuple())

    def __iter__(self):
        return iter(self.as_tuple())

    def __len__(self):
        return 2

    def __getitem__(self, index):
        return self.as_tuple()[index]


def flavour_label(flavour):
    """``'salted_be32/>'`` style text (``MapInfo.hash_flavour``); ``'unknown'`` for ``None``."""
    if flavour is None:
        return "unknown"
    return "%s/%s" % (flavour.recipe, flavour.length_endian)


def fallback_flavour(length_endian):
    """DEC-2.3 case 3: salted recipe with the template's valid length byte order."""
    return HashFlavour(length_endian if length_endian in (">", "<") else ">", "salted_be32")


def encode_length(value, endian):
    """The 4 stored length bytes for ``value`` in the byte order ``endian``."""
    if endian not in (">", "<") or not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFF:
        raise HashError("Cannot encode the stream length %r with byte order %r." % (value, endian))
    return struct.pack(endian + "I", value)


def recipe_input(recipe, data, length):
    """The exact bytes that are fed to SHA-1 for ``recipe`` (``zero`` has none)."""
    data = bytes(data)
    if recipe == "plain_le32":
        return struct.pack("<I", length) + data
    if recipe == "salted_be32":
        return SALT34 + struct.pack(">I", length) + data
    if recipe == "salted_le32":
        return SALT34 + struct.pack("<I", length) + data
    if recipe == "plain_be32":
        return struct.pack(">I", length) + data
    if recipe == "data_only":
        return data
    raise HashError("Recipe %r has no digest input." % (recipe,))


def digest(recipe, data, length):
    """The 20 bytes the recipe produces for ``data`` (already cut to ``length`` bytes)."""
    if recipe == ZERO:
        return bytes(HASH_SIZE)
    return hashlib.sha1(recipe_input(recipe, data, length)).digest()


def compute(flavour: HashFlavour, data: bytes, L: int) -> bytes:
    """Hash for ``flavour`` over ``data[:L]`` (``HashError`` if ``data`` is shorter than ``L``).

    ``L`` is the length that enters the digest; the stored length byte order does not matter here
    (it only matters when the length field itself is written).
    """
    if not isinstance(flavour, HashFlavour):
        raise HashError("compute() needs a HashFlavour, got %s." % type(flavour).__name__)
    if not isinstance(L, int) or L < 0:
        raise HashError("The hashed length must be a non-negative integer, got %r." % (L,))
    data = bytes(data)
    if len(data) < L:
        raise HashError("Cannot hash %d bytes: only %d are available." % (L, len(data)))
    return digest(flavour.recipe, data[:L], L)


def length_readings(chunk, spec):
    """Valid readings of the stored length as ``[(endian, L), ...]``, the layout's own order first.

    One reading for a normal field. For four zero bytes the effective length is ambiguous, so the
    readings are ``(spec.length_endian, 0)`` and ``(spec.length_endian, stream_capacity)``. Empty
    when neither byte order gives a length in ``1 .. stream_capacity``.
    """
    raw = bytes(chunk[spec.length_off:spec.length_off + 4])
    if len(raw) < 4:
        raise HashError("The block is too short to hold the stored length.")
    if raw == bytes(4):
        return [(spec.length_endian, 0), (spec.length_endian, spec.stream_capacity)]
    order = [spec.length_endian, "<" if spec.length_endian == ">" else ">"]
    out = []
    for endian in order:
        value = struct.unpack(endian + "I", raw)[0]
        if 1 <= value <= spec.stream_capacity:
            out.append((endian, value))
    return out


@dataclass(frozen=True)
class HashAnalysis:
    """Everything detected about the stored length and hash of one payload block."""
    stored_hash: bytes
    length_raw: bytes
    readings: Tuple[Tuple[str, int], ...]                 # valid length readings (see length_readings)
    candidates: Tuple[Tuple[str, str, int, bool], ...]    # (length_endian, recipe, L, matches)
    flavour: Optional[HashFlavour]                        # None: no candidate matched ("unknown")
    length_endian: Optional[str]                          # valid byte order of the stored length; None if invalid
    stored_length: int                                    # the stored value (0 for four zero bytes)
    hash_length: int                                      # L that enters the digest (matching candidate; else the stored/effective one)
    zero_length: bool                                     # the stored length bytes are 00 00 00 00


def analyse(chunk, spec):
    """Detect the stored-length byte order and the hash recipe of a payload block (SPEC 2.7)."""
    chunk = bytes(chunk)
    need = spec.stream_off + spec.stream_capacity
    if len(chunk) < need:
        raise HashError("The block has %d bytes; the layout needs at least %d." % (len(chunk), need))
    stored = chunk[spec.hash_off:spec.hash_off + HASH_SIZE]
    raw = chunk[spec.length_off:spec.length_off + 4]
    readings = length_readings(chunk, spec)
    zero_length = raw == bytes(4)
    cands = []
    for endian, value in readings:
        data = chunk[spec.stream_off:spec.stream_off + value]
        for recipe in RECIPES:
            cands.append((endian, recipe, value, digest(recipe, data, value) == stored))
    if readings:
        cands.append((readings[0][0], ZERO, readings[0][1], stored == bytes(HASH_SIZE)))
    flavour = None
    # Length that enters the digest when nothing matches: the stored value, or the capacity for four zero bytes.
    hash_length = spec.stream_capacity if zero_length else (readings[0][1] if readings else 0)
    if readings:
        if stored == bytes(HASH_SIZE):
            flavour = HashFlavour(readings[0][0], ZERO)
        else:
            for endian, recipe, value, matches in cands:
                if matches:
                    flavour = HashFlavour(endian, recipe)
                    hash_length = value
                    break
    return HashAnalysis(
        stored_hash=bytes(stored), length_raw=bytes(raw), readings=tuple(readings), candidates=tuple(cands),
        flavour=flavour, length_endian=readings[0][0] if readings else None,
        stored_length=0 if zero_length else (readings[0][1] if readings else 0),
        hash_length=hash_length, zero_length=zero_length)


def candidates(chunk: bytes, spec) -> List[Tuple[str, str, int, bool]]:
    """``[(length_endian, recipe, L, matches), ...]`` for every valid length reading and every recipe."""
    return list(analyse(chunk, spec).candidates)


def detect_flavour(chunk: bytes, spec) -> Optional[HashFlavour]:
    """The ``HashFlavour`` whose digest equals the stored hash, or ``None`` (unknown / invalid length)."""
    return analyse(chunk, spec).flavour
