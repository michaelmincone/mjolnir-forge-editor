"""Bit and byte primitives of the independent fixture builder (SPEC 9.1, DEC-9.2).

Nothing here comes from the library under test.  The two techniques are deliberately different from
the ones the library uses:

* ``BitWriter`` accumulates ONE Python big integer (shift left, OR the value in).  The library's
  writer is a masked byte writer; a bug in one cannot hide in the other.
* ``BitSource`` (used by the self-check walker) turns the whole stream into a ``'0'/'1'`` string and
  slices it, which is a third technique.

Bit order everywhere: bit 0 is the most significant bit of byte 0; a field of n bits is the next
n bits and its first bit is the most significant bit of the value (SPEC 3.1).
Python 3.9 compatible (no ``X | Y`` at runtime, no ``match``).
"""
import json
import struct

__all__ = ["dumps_json", "BitWriter", "BitSource", "BitOverrun", "f32_bits", "bits_f32", "f32_round", "adler32",
           "zlib_stored", "zlib_stored_length", "block_header", "unpack_block_header"]


class BitOverrun(Exception):
    """A read past the end of the bits."""


class BitWriter(object):
    """MSB-first writer: one big integer plus a bit count."""

    def __init__(self):
        self._v = 0
        self._n = 0
        self._marks = []

    @property
    def nbits(self):
        return self._n

    def put(self, value, width):
        """Append ``value`` as an unsigned field of ``width`` bits (0 to 64+).  Never masks: a value
        that does not fit is a bug in the fixture description and raises ``ValueError``."""
        if width < 0:
            raise ValueError("negative width %r" % (width,))
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("field value must be an int, got %r" % (value,))
        if value < 0 or (value >> width) != 0:
            raise ValueError("value %d does not fit in %d bit(s)" % (value, width))
        self._v = (self._v << width) | value
        self._n += width

    def put_signed(self, value, width):
        """Two's complement field."""
        if width <= 0:
            raise ValueError("signed field needs a positive width")
        lo = -(1 << (width - 1))
        hi = (1 << (width - 1)) - 1
        if isinstance(value, bool) or not isinstance(value, int) or value < lo or value > hi:
            raise ValueError("signed value %r does not fit in %d bit(s)" % (value, width))
        self.put(value & ((1 << width) - 1), width)

    def put_bytes(self, data):
        """Append whole bytes (8 bits each) at the current, possibly unaligned, position."""
        data = bytes(data)
        if data:
            self._v = (self._v << (8 * len(data))) | int.from_bytes(data, "big")
            self._n += 8 * len(data)

    def put_bitstring(self, text):
        """Append a string of '0'/'1' characters (used for the raw tail and the GUID)."""
        if text:
            self._v = (self._v << len(text)) | int(text, 2)
            self._n += len(text)

    def mark(self, name):
        """Remember the current position under ``name``; returns it."""
        self._marks.append((name, self._n))
        return self._n

    @property
    def marks(self):
        return list(self._marks)

    def getbytes(self, total_bytes):
        """The bits, zero padded on the right to exactly ``total_bytes`` bytes (never truncated)."""
        if self._n > 8 * total_bytes:
            raise ValueError("%d bits do not fit in %d bytes (%d bits)" % (self._n, total_bytes, 8 * total_bytes))
        return (self._v << (8 * total_bytes - self._n)).to_bytes(total_bytes, "big")

    def to_bitstring(self):
        if self._n == 0:
            return ""
        return format(self._v, "b").zfill(self._n)


class BitSource(object):
    """MSB-first reader over a '0'/'1' string (the walker's own technique)."""

    def __init__(self, data, nbits=None):
        data = bytes(data)
        # a leading 0x01 byte keeps the leading zero bits of the data when the integer is printed
        self._s = bin(int.from_bytes(b"\x01" + data, "big"))[3:]
        self.capacity = 8 * len(data) if nbits is None else nbits
        self.pos = 0

    def u(self, n):
        if n == 0:
            return 0
        end = self.pos + n
        if end > self.capacity:
            raise BitOverrun("read of %d bit(s) at bit %d passes the end (%d bits)" % (n, self.pos, self.capacity))
        v = int(self._s[self.pos:end], 2)
        self.pos = end
        return v

    def s(self, n):
        v = self.u(n)
        return v - (1 << n) if v >> (n - 1) else v

    def bits(self, start, end):
        return self._s[start:end]


# ---- number helpers ---------------------------------------------------------------------------------

def f32_bits(x):
    """The 32 IEEE-754 bits of ``x`` rounded to float32, as an int."""
    return struct.unpack(">I", struct.pack(">f", x))[0]


def bits_f32(b):
    return struct.unpack(">f", struct.pack(">I", b))[0]


def f32_round(x):
    return bits_f32(f32_bits(x))


# ---- zlib without a compressor ------------------------------------------------------------------------
# The ``_cmp`` fixtures must have the same bytes on every zlib version, so they carry a *stored*
# (uncompressed) deflate stream written here.  Any inflater accepts it.

def adler32(data):
    a, b = 1, 0
    for ch in bytes(data):
        a = (a + ch) % 65521
        b = (b + a) % 65521
    return (b << 16) | a


def zlib_stored_length(n):
    """Length of ``zlib_stored`` output for ``n`` input bytes."""
    blocks = max(1, -(-n // 65535))
    return 2 + n + 5 * blocks + 4


def zlib_stored(data):
    data = bytes(data)
    out = bytearray(b"\x78\x01")
    pos = 0
    n = len(data)
    if n == 0:
        out += b"\x01\x00\x00\xff\xff"
    while pos < n:
        chunk = data[pos:pos + 65535]
        pos += len(chunk)
        out.append(1 if pos >= n else 0)
        out += struct.pack("<HH", len(chunk), len(chunk) ^ 0xFFFF)
        out += chunk
    out += struct.pack(">I", adler32(data))
    return bytes(out)


# ---- canonical JSON (the golden files) ---------------------------------------------------------------------

def _is_scalar(v):
    return v is None or isinstance(v, (bool, int, float, str))


def _dump(v, level, width):
    pad = " " * level
    if isinstance(v, dict):
        if not v:
            return "{}"
        rows = [" " * (level + 1) + json.dumps(k) + ": " + _dump(v[k], level + 1, width) for k in sorted(v)]
        return "{\n" + ",\n".join(rows) + "\n" + pad + "}"
    if isinstance(v, (list, tuple)):
        if not v:
            return "[]"
        if all(_is_scalar(x) for x in v):
            parts = [json.dumps(x) for x in v]
            one = "[" + ", ".join(parts) + "]"
            if len(one) + level <= width:
                return one
            lines, cur = [], ""
            for p in parts:
                if cur and len(cur) + len(p) + 2 + level + 1 > width:
                    lines.append(cur)
                    cur = p
                else:
                    cur = p if not cur else cur + ", " + p
            lines.append(cur)
            return "[\n" + ",\n".join(" " * (level + 1) + ln for ln in lines) + "\n" + pad + "]"
        return "[\n" + ",\n".join(" " * (level + 1) + _dump(x, level + 1, width) for x in v) + "\n" + pad + "]"
    return json.dumps(v)


def dumps_json(obj, width=110):
    """Deterministic JSON for the golden files: sorted keys, one-line scalar lists (wrapped past ``width`` columns), a final newline.
    ``json.loads`` of the result gives back ``obj``."""
    return _dump(obj, 0, width) + "\n"


# ---- block headers (SPEC 2.1) ------------------------------------------------------------------------

def block_header(sig, size, version, flags):
    """12 bytes, big-endian: signature, size (whole block), version, flags."""
    sig = sig.encode("ascii") if isinstance(sig, str) else bytes(sig)
    if len(sig) != 4:
        raise ValueError("block signature must be 4 bytes")
    return struct.pack(">4sIHH", sig, size, version, flags)


def unpack_block_header(data, offset=0):
    sig, size, version, flags = struct.unpack_from(">4sIHH", data, offset)
    return sig.decode("latin-1"), size, version, flags
