"""A tiny, independent builder of container-level synthetic map variants for the G1 tests.

It writes plain ``struct`` / ``int`` / ``hashlib`` / ``zlib`` code from SPEC sections 2.1 to 2.9 and
imports nothing from ``mvarlib``, so the container tests do not check the library against itself.
It knows nothing about the bit stream's *content*: the stream is random bytes whose first 36 bits are
a 4-bit content type nibble and the 32-bit embedded file length (bit 4, as in an ``mvar``). Nothing
here is game data and nothing is written to disk: files exist only as ``bytes``.

The G2 fixture builder (``tests/fixturebuilder``) is a different, full-format builder owned by another gate.
"""
import hashlib
import importlib.util
import os
import random
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
W1_REFERENCE = os.path.join(REPO, "docs", "mvar", "reference", "w1_build.py")

SALT34 = bytes.fromhex("EDD43009666D5C4A5C3657FAB40E022F535AC6C9EE471F01F1A44756B7714F1C36EC")
MVAR_SIZE = 0x7028
MVAR_CAPACITY = 0x7000
RECIPE_NAMES = ("plain_le32", "salted_be32", "salted_le32", "plain_be32", "data_only")


def hash_input(recipe, data, length):
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
    raise ValueError(recipe)


def digest(recipe, stream, length):
    """The 20-byte hash for ``recipe`` over ``stream[:length]`` (``zero`` is twenty 0x00 bytes)."""
    if recipe == "zero":
        return bytes(20)
    return hashlib.sha1(hash_input(recipe, stream[:length], length)).digest()


def block(sig, version, flags, body):
    return struct.pack(">4sIHH", sig, 12 + len(body), version, flags) + body


def random_stream(seed, used_bytes, capacity=MVAR_CAPACITY):
    """``capacity`` bytes: ``used_bytes`` pseudo-random bytes then zeros; the content nibble is 6."""
    rng = random.Random(seed)
    data = bytearray(capacity)
    for i in range(used_bytes):
        data[i] = rng.getrandbits(8)
    data[0] = (data[0] & 0x0F) | 0x60
    return bytes(data)


def put_embedded_length(stream, file_length):
    """Write ``file_length`` into bits 4..35 of ``stream`` (a plain integer model, no library code)."""
    head = int.from_bytes(stream[:5], "big")
    head = (head & ~(0xFFFFFFFF << 4)) | (file_length << 4)
    return head.to_bytes(5, "big") + stream[5:]


def get_embedded_length(stream):
    return (int.from_bytes(stream[:5], "big") >> 4) & 0xFFFFFFFF


def blf_block():
    return block(b"_blf", 1, 2, struct.pack(">H", 0xFFFE) + bytes(0x20) + struct.pack(">H", 0))


def chdr_block(file_length, title="synthetic"):
    body = bytearray(0x2C0 - 12)
    struct.pack_into("<HH", body, 0, 0, 0xFFFF)                 # build major / minor (block offset 0x0C)
    body[0x10 - 12] = 5                                          # contentType: map variant
    struct.pack_into("<I", body, 0x14 - 12, file_length)
    struct.pack_into("<I", body, 0x3C - 12, 3006)                # mapID
    text = (title.encode("utf-16-le") + b"\x00\x00").ljust(256, b"\x00")
    body[0x90 - 12:0x190 - 12] = text
    return block(b"chdr", 10, 2, bytes(body))


def eof_block(offset, endian=">", auth=0):
    return block(b"_eof", 1, 1, struct.pack(endian + "I", offset) + bytes([auth]))


def fsm_block():
    return block(b"_fsm", 1, 1, bytes(range(256)) + bytes(0x1C4 - 12 - 256))


def mvar_block(stream, length, recipe="salted_be32", length_endian=">", version=31, flags=1, pad=bytes(4),
               hash_bytes=None, length_bytes=None, hashed_length=None):
    """A 0x7028-byte ``mvar`` block: header, hash, stored length, stream, pad.

    ``length`` is the stored L; ``hashed_length`` (default: ``length``) is the L used inside the digest
    (differs only for the "four zero bytes" length, whose effective length is 0 or 0x7000).
    """
    assert len(stream) == MVAR_CAPACITY
    hashed = length if hashed_length is None else hashed_length
    hsh = digest(recipe, stream, hashed) if hash_bytes is None else hash_bytes
    stored_len = struct.pack(length_endian + "I", length) if length_bytes is None else length_bytes
    body = hsh + stored_len + stream + pad
    assert len(body) == MVAR_SIZE - 12
    return block(b"mvar", version, flags, body)


def cmp_block(inner_block, level=9, ctype=0, usize=None, version=1, flags=1, tamper=None):
    """A ``_cmp`` wrapper (SPEC 2.8): type byte, u32 BE uncompressed size, zlib stream."""
    packed = zlib.compress(inner_block, level)
    if tamper is not None:
        packed = tamper(packed)
    declared = len(inner_block) if usize is None else usize
    return block(b"_cmp", version, flags, bytes([ctype]) + struct.pack(">I", declared) + packed)


def make_file(stream, length, recipe="salted_be32", length_endian=">", chunk_version=31, wrap_cmp=False, fsm=False,
              trailer=b"", eof_endian=">", extra_before_eof=None, hash_bytes=None, length_bytes=None,
              hashed_length=None, cmp_level=9, pad=bytes(4), embedded=None):
    """Assemble a complete file and return ``(data, parts)``.

    The ``chdr`` file length and the ``_eof`` value are set to the real values of the assembled file.
    The embedded file length (bit 4 of the stream) is ``embedded`` if given, else the length of the
    expanded plain file (equal to the real length unless the payload is ``_cmp`` wrapped); the hash is
    computed after the embedded length was written, like a correct writer does. ``parts`` lists the
    blocks in file order.
    """
    stream = bytes(stream)
    blf = blf_block()
    extra = extra_before_eof or b""

    def payload(embedded):
        return mvar_block(put_embedded_length(stream, embedded), length, recipe, length_endian, chunk_version,
                          hash_bytes=hash_bytes, length_bytes=length_bytes, hashed_length=hashed_length, pad=pad)

    plain_total = len(blf) + 0x2C0 + MVAR_SIZE + len(extra) + 0x11
    if embedded is None:
        embedded = plain_total       # for a _cmp file the value inside the wrapper is the expanded length (a choice: SPEC 2.8 says U)
    inner = payload(embedded)
    middle = cmp_block(inner, cmp_level) if wrap_cmp else inner
    total = len(blf) + 0x2C0 + len(middle) + len(extra) + 0x11
    eof_offset = total - 0x11
    parts = [blf, chdr_block(total), middle]
    if extra:
        parts.append(extra)
    parts.append(eof_block(eof_offset, eof_endian))
    if fsm:
        parts.append(fsm_block())
    return b"".join(parts) + trailer, parts


def plain_file(seed=1, used=600, **kwargs):
    """A plain ``mvar`` file with a deterministic random stream of ``used`` bytes and ``L = used``."""
    stream = random_stream(seed, used)
    data, parts = make_file(stream, used, **kwargs)
    return data


def load_w1_builder():
    """The spec's reference W1 builder (``docs/mvar/reference/w1_build.py``, synthetic, not game data).

    Written from SPEC appendix C by the spec's author, it shares nothing with ``mvarlib``; the tests
    use it as an outside source of container bytes. Import has no side effects (it only writes files
    when run as a script with an output directory).
    """
    spec = importlib.util.spec_from_file_location("w1_build_reference", W1_REFERENCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
