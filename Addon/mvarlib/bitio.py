"""MSB-first bit I/O for Halo: Reach BLF payloads (SPEC 3.1, 6.3; promoted in gate G1).

Conventions (all ``V`` on the real Reach game-variant files, SPEC 3.1):

* Bit 0 of a stream is the most significant bit of byte 0.
* A field of ``n`` bits is the next ``n`` bits and its first bit is the most significant bit of
  the value, so every multi-bit field is big-endian even when it is not byte aligned.
* Reading past the end is an error here (:class:`BitOverrun`); the C++ original returns zero bits
  and counts an overflow, which would hide a desynchronised walk.
* Strings stop after the first NUL (the NUL is part of the returned value) or at the maximum length.
* Widths 0 to 64 are used by the format and any larger width works for blobs; a 0-bit read returns 0
  and consumes nothing.

Writing is a *masked overwrite*: ``write`` clears exactly the target bits and ORs the value in, so a
write never disturbs a neighbouring bit, at any alignment and at any ``pos``. This is the property
the C++ ``write_to_bitpos`` lacks: with a byte-aligned start and fewer than 8 bits left it assigns
the whole final byte, which clobbers the low bits that follow. The ``mvar`` stream holds its embedded
file length at bit 4, so that hazard is real here (``tests/unit/test_bitio.py`` demonstrates it on a
port of the C++ code and proves this module cannot do it).

Pure Python 3.9 to 3.13, standard library only (this module also imports the package's own
``errors``). Relative imports only.
"""
from typing import List, Optional, Union

from .errors import CapacityError, DecodeError, EncodeError, InternalError

BytesLike = Union[bytes, bytearray, memoryview]

__all__ = ["BitOverrun", "BitReader", "BitWriter", "BitString", "get_bits", "patch_bits"]


class BitOverrun(DecodeError):
    """A read or slice went past the end of the available bits.

    Inside a walk this means the layout hypothesis is wrong (a desynchronisation); the walk code
    converts it into a ``DesyncError`` diagnostic. ``pos`` is where the failed read started,
    ``requested`` how many bits it wanted and ``bit_length`` how many bits exist. (For a string
    read, the failed read is the unit that did not fit; the reader itself is back at the start
    of the string.)
    """

    def __init__(self, message="", pos=None, requested=None, bit_length=None):
        super().__init__(message)
        self.pos = pos
        self.requested = requested
        self.bit_length = bit_length


def _check_width(n):
    """Widths are plain non-negative ints; anything else is a bug in the caller."""
    if not isinstance(n, int) or n < 0:
        raise InternalError("A bit width must be a non-negative integer, got %r." % (n,))


def _as_bytes(data):
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise InternalError("Bit data must be bytes-like, got %s." % type(data).__name__)
    return bytes(data)


def _extract(data, start, n):
    """Unsigned value of ``n`` bits at bit ``start`` of ``data`` (the caller has range-checked)."""
    if n == 0:
        return 0
    end = start + n
    b0 = start >> 3
    b1 = (end + 7) >> 3
    chunk = int.from_bytes(data[b0:b1], "big")
    return (chunk >> ((b1 << 3) - end)) & ((1 << n) - 1)


def _masked_put(buf, start, n, value):
    """Overwrite exactly bits ``[start, start + n)`` of the bytearray ``buf`` with ``value``.

    Every other bit of the buffer is left as it was. The caller guarantees ``0 <= value < 2**n``
    and that the buffer is long enough.
    """
    if n == 0:
        return
    end = start + n
    b0 = start >> 3
    b1 = (end + 7) >> 3
    trail = (b1 << 3) - end
    existing = int.from_bytes(buf[b0:b1], "big")
    mask = ((1 << n) - 1) << trail
    existing = (existing & ~mask) | (value << trail)
    buf[b0:b1] = existing.to_bytes(b1 - b0, "big")


def get_bits(data, bitpos, nbits):
    """Unsigned value of ``nbits`` bits at absolute bit position ``bitpos`` of a bytes-like ``data``."""
    _check_width(nbits)
    if not isinstance(bitpos, int) or bitpos < 0:
        raise InternalError("A bit position must be a non-negative integer, got %r." % (bitpos,))
    data = _as_bytes(data)
    if bitpos + nbits > len(data) * 8:
        raise BitOverrun("Cannot read %d bits at bit %d: only %d bits exist." % (nbits, bitpos, len(data) * 8),
                         bitpos, nbits, len(data) * 8)
    return _extract(data, bitpos, nbits)


def patch_bits(buf, bitpos, nbits, value):
    """Masked overwrite of ``nbits`` bits at ``bitpos`` inside the bytearray ``buf``; nothing else changes.

    Raises ``EncodeError`` when ``value`` does not fit in ``nbits`` bits or the range lies outside
    the buffer. This is how the container patches the embedded file length (bit 4 of an ``mvar``
    stream, bit 72 of an ``mpvr`` stream) without touching the neighbouring bits.
    """
    _check_width(nbits)
    if not isinstance(buf, bytearray):
        raise InternalError("patch_bits needs a bytearray.")
    if not isinstance(bitpos, int) or bitpos < 0:
        raise InternalError("A bit position must be a non-negative integer, got %r." % (bitpos,))
    if not isinstance(value, int) or value < 0 or value >> nbits:
        raise EncodeError("The value %r does not fit in %d bits." % (value, nbits))
    if bitpos + nbits > len(buf) * 8:
        raise EncodeError("Cannot write %d bits at bit %d: the buffer holds only %d bits."
                          % (nbits, bitpos, len(buf) * 8))
    _masked_put(buf, bitpos, nbits, value)


class BitString(object):
    """An immutable bit range, MSB-first. ``data`` is zero padded in the last byte; ``nbits`` is exact.

    Two bit strings are equal when they hold the same bits (the padding is always zero, so the
    comparison is on ``nbits`` and ``data``). Used to keep the raw bit range of the header, the
    label table, a slot, and so on (SPEC 5.1).
    """

    __slots__ = ("_data", "_nbits")

    def __init__(self, data: BytesLike = b"", nbits: Optional[int] = None) -> None:
        data = _as_bytes(data)
        if nbits is None:
            nbits = len(data) * 8
        _check_width(nbits)
        need = (nbits + 7) >> 3
        if len(data) < need:
            raise InternalError("A BitString of %d bits needs %d bytes, got %d." % (nbits, need, len(data)))
        data = data[:need]
        spare = nbits & 7
        if spare:                                     # canonical form: padding bits are zero
            data = data[:-1] + bytes([data[-1] & ((0xFF << (8 - spare)) & 0xFF)])
        object.__setattr__(self, "_data", data)
        object.__setattr__(self, "_nbits", nbits)

    def __setattr__(self, name, value):
        raise AttributeError("BitString is immutable")

    def __delattr__(self, name):
        raise AttributeError("BitString is immutable")

    # Copy and pickle support. The ``__setattr__`` above refuses every assignment, so the default
    # slot-restoring machinery of ``copy`` and ``pickle`` (which assigns each slot) cannot work.
    # An immutable value is its own copy; pickling rebuilds it through the constructor, which
    # validates and canonicalises again. ``UgcHeader.raw`` and the other raw ranges of SPEC 5.1 hold
    # a BitString, so ``copy.deepcopy`` of the model (SPEC 6.3 ``MapVariant.copy``) depends on this.
    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        return (type(self), (self._data, self._nbits))

    @property
    def data(self):
        return self._data

    @property
    def nbits(self):
        return self._nbits

    @classmethod
    def from_int(cls, value, nbits):
        """The ``nbits`` bits of the non-negative integer ``value`` (which must fit)."""
        _check_width(nbits)
        if not isinstance(value, int) or value < 0 or value >> nbits:
            raise EncodeError("The value %r does not fit in %d bits." % (value, nbits))
        nbytes = (nbits + 7) >> 3
        return cls((value << ((nbytes << 3) - nbits)).to_bytes(nbytes, "big"), nbits)

    def get(self, start: int, n: int) -> int:
        """Unsigned value of ``n`` bits at ``start`` (``BitOverrun`` outside the string)."""
        _check_width(n)
        if not isinstance(start, int) or start < 0 or start + n > self._nbits:
            raise BitOverrun("Cannot read %d bits at bit %r of a %d-bit string." % (n, start, self._nbits),
                             start, n, self._nbits)
        return _extract(self._data, start, n)

    def slice(self, start: int, end: int) -> "BitString":
        """The bits ``[start, end)`` as a new BitString."""
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end < start:
            raise InternalError("Invalid bit range [%r, %r)." % (start, end))
        return BitString.from_int(self.get(start, end - start), end - start)

    def to_int(self):
        """All bits as one unsigned integer (MSB-first)."""
        return self.get(0, self._nbits)

    def __add__(self, other):
        if not isinstance(other, BitString):
            return NotImplemented
        return BitString.from_int((self.to_int() << other._nbits) | other.to_int(), self._nbits + other._nbits)

    def __len__(self):
        return self._nbits

    def __eq__(self, other):
        if not isinstance(other, BitString):
            return NotImplemented
        return self._nbits == other._nbits and self._data == other._data

    def __hash__(self):
        return hash((self._nbits, self._data))

    def __repr__(self):
        shown = self._data[:8].hex()
        return "BitString(%d bits, %s%s)" % (self._nbits, shown, "..." if len(self._data) > 8 else "")


class BitReader(object):
    """Reads MSB-first from a bytes-like object. ``pos`` is the bit position.

    ``bit_length`` limits the readable bits (default: all bits of ``data``); a read that would pass
    it raises :class:`BitOverrun` and leaves ``pos`` unchanged. That holds for every method,
    including the string readers, which consume several units: they restore ``pos`` to where the
    string started before raising (the exception's own ``pos`` then names the unit that did not fit).
    """

    def __init__(self, data: BytesLike, bit_length: Optional[int] = None) -> None:
        self.data = _as_bytes(data)
        total = len(self.data) * 8
        if bit_length is None:
            bit_length = total
        if not isinstance(bit_length, int) or bit_length < 0 or bit_length > total:
            raise InternalError("bit_length %r is outside 0..%d." % (bit_length, total))
        self.bit_length = bit_length
        self.pos = 0

    # --- position ------------------------------------------------------------------------
    def set_bitpos(self, p: int) -> None:
        if not isinstance(p, int) or p < 0:
            raise InternalError("A bit position must be a non-negative integer, got %r." % (p,))
        if p > self.bit_length:
            raise BitOverrun("Cannot move to bit %d: the stream has %d bits." % (p, self.bit_length),
                             p, 0, self.bit_length)
        self.pos = p

    def remaining(self) -> int:
        """Bits left before ``bit_length``."""
        return self.bit_length - self.pos

    def skip(self, n):
        _check_width(n)
        self._need(n)
        self.pos += n

    def is_byte_aligned(self):
        return self.pos % 8 == 0

    def _need(self, n):
        if self.pos + n > self.bit_length:
            raise BitOverrun("Read of %d bits at bit %d runs past the end of the %d-bit stream."
                             % (n, self.pos, self.bit_length), self.pos, n, self.bit_length)

    # --- numbers -------------------------------------------------------------------------
    def read(self, n: int) -> int:
        """Unsigned value of the next ``n`` bits (any ``n >= 0``), MSB-first."""
        _check_width(n)
        if n == 0:
            return 0
        self._need(n)
        value = _extract(self.data, self.pos, n)
        self.pos += n
        return value

    def read_signed(self, n: int) -> int:
        """Two's complement value of the next ``n`` bits."""
        value = self.read(n)
        if n and (value >> (n - 1)) & 1:
            value -= 1 << n
        return value

    def read_bool(self):
        return self.read(1) == 1

    def read_bytes(self, count):
        """``count`` bytes, 8 bits at a time, at any bit alignment."""
        _check_width(count)
        if count == 0:
            return b""
        return self.read(count * 8).to_bytes(count, "big")

    def read_bitstring(self, n):
        """The next ``n`` bits as a BitString."""
        return BitString.from_int(self.read(n), n)

    def slice(self, start, end):
        """The absolute bit range ``[start, end)`` as a BitString; the position does not move."""
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end < start:
            raise InternalError("Invalid bit range [%r, %r)." % (start, end))
        if end > self.bit_length:
            raise BitOverrun("Bit range [%d, %d) is past the end of the %d-bit stream." % (start, end, self.bit_length),
                             start, end - start, self.bit_length)
        return BitString.from_int(_extract(self.data, start, end - start), end - start)

    # --- strings -------------------------------------------------------------------------
    def read_cstring(self, maxlen: int) -> bytes:
        """8-bit units, stopping after (and including) the first NUL or after ``maxlen`` units.

        Atomic: if a unit does not fit, ``BitOverrun`` is raised and ``pos`` is back where it was.
        """
        _check_width(maxlen)
        start = self.pos
        out = bytearray()
        try:
            for _ in range(maxlen):
                unit = self.read(8)
                out.append(unit)
                if unit == 0:
                    break
        except BitOverrun:
            self.pos = start
            raise
        return bytes(out)

    def read_u16string(self, maxlen: int) -> List[int]:
        """16-bit units (UTF-16BE), stopping after (and including) the first NUL or after ``maxlen`` units.

        Atomic: if a unit does not fit, ``BitOverrun`` is raised and ``pos`` is back where it was.
        """
        _check_width(maxlen)
        start = self.pos
        out = []
        try:
            for _ in range(maxlen):
                unit = self.read(16)
                out.append(unit)
                if unit == 0:
                    break
        except BitOverrun:
            self.pos = start
            raise
        return out

    def __repr__(self):
        return "BitReader(pos=%d, bit_length=%d)" % (self.pos, self.bit_length)


class BitWriter(object):
    """Writes MSB-first into a growable zero-filled buffer. ``pos`` is the bit position.

    Writes overwrite exactly the target bits (see the module docstring); ``pos`` may be moved back
    and forth, so a field can be patched after the fact. ``getvalue`` returns the bytes up to the
    highest bit ever written, with the unused bits of the last byte zero.
    """

    def __init__(self):
        self._buf = bytearray()
        self._hi = 0                  # highest bit position ever written to (exclusive)
        self.pos = 0

    @property
    def bits_written(self):
        """High-water mark: one past the highest bit written so far."""
        return self._hi

    def bytespan(self):
        return (self._hi + 7) >> 3

    # --- numbers -------------------------------------------------------------------------
    def _put(self, value, n):
        if not isinstance(self.pos, int) or self.pos < 0:
            raise InternalError("The bit position must be a non-negative integer, got %r." % (self.pos,))
        end = self.pos + n
        need = (end + 7) >> 3
        if len(self._buf) < need:
            self._buf.extend(bytes(need - len(self._buf)))
        _masked_put(self._buf, self.pos, n, value)
        self.pos = end
        if end > self._hi:
            self._hi = end

    def write(self, value: int, n: int) -> None:
        """Write ``value`` in ``n`` bits. ``EncodeError`` unless ``0 <= value < 2**n``.

        A masked write would hide an encoder bug (a value that silently loses its high bits), so
        this method refuses instead; ``write_masked`` is the explicit opt-out.
        """
        _check_width(n)
        if not isinstance(value, int) or value < 0 or value >> n:
            raise EncodeError("The value %r does not fit in %d bits." % (value, n))
        self._put(value, n)

    def write_signed(self, value: int, n: int) -> None:
        """Two's complement; ``EncodeError`` outside ``-2**(n-1) .. 2**(n-1) - 1``."""
        _check_width(n)
        low = -(1 << (n - 1)) if n else 0
        high = (1 << (n - 1)) - 1 if n else 0
        if not isinstance(value, int) or value < low or value > high:
            raise EncodeError("The value %r does not fit in %d signed bits." % (value, n))
        self._put(value & ((1 << n) - 1), n)

    def write_masked(self, value: int, n: int) -> None:
        """Write the low ``n`` bits of ``value`` (negative ints become two's complement).

        Used by the tests that port the C++ code; library encoders use :meth:`write`.
        """
        _check_width(n)
        if not isinstance(value, int):
            raise EncodeError("The value %r is not an integer." % (value,))
        self._put(value & ((1 << n) - 1), n)

    def write_bool(self, flag):
        self._put(1 if flag else 0, 1)

    def write_bytes(self, data):
        """Bytes, 8 bits at a time, at any bit alignment."""
        data = _as_bytes(data)
        if data:
            self._put(int.from_bytes(data, "big"), len(data) * 8)

    def write_bitstring(self, bs: "BitString") -> None:
        if not isinstance(bs, BitString):
            raise InternalError("write_bitstring needs a BitString, got %s." % type(bs).__name__)
        self._put(bs.to_int(), bs.nbits)

    def write_to_bitpos(self, bitpos, n, value):
        """Overwrite ``n`` bits at the absolute position ``bitpos``; ``pos`` is not moved.

        Masked: the bits before ``bitpos`` and after ``bitpos + n`` are unchanged.
        """
        _check_width(n)
        if not isinstance(bitpos, int) or bitpos < 0:
            raise InternalError("A bit position must be a non-negative integer, got %r." % (bitpos,))
        if not isinstance(value, int) or value < 0 or value >> n:
            raise EncodeError("The value %r does not fit in %d bits." % (value, n))
        saved = self.pos
        self.pos = bitpos
        try:
            self._put(value, n)
        finally:
            self.pos = saved

    # --- strings -------------------------------------------------------------------------
    @staticmethod
    def _check_string_units(units, maxlen, what, width):
        """A string must be readable back as itself: it ends at its first NUL, or fills ``maxlen``.

        Every unit is checked (an integer of ``width`` bits) before anything is written, so a refused
        string leaves the writer exactly as it was.
        """
        _check_width(maxlen)
        count = len(units)
        if count == 0 or count > maxlen:
            raise EncodeError("A %s of %d units cannot be stored (1 to %d units are needed)." % (what, count, maxlen))
        for unit in units:
            if not isinstance(unit, int) or unit < 0 or unit >> width:
                raise EncodeError("The value %r does not fit in a %d-bit unit of a %s." % (unit, width, what))
        for index in range(count - 1):
            if units[index] == 0:
                raise EncodeError("A %s has a NUL before its last unit; the units after it could not be read back." % what)
        if count < maxlen and units[-1] != 0:
            raise EncodeError("A %s shorter than %d units must end with a NUL unit." % (what, maxlen))

    def write_cstring(self, data, maxlen):
        """8-bit units: ends at its first NUL, or is exactly ``maxlen`` units long. All-or-nothing."""
        units = list(_as_bytes(data))
        self._check_string_units(units, maxlen, "byte string", 8)
        for unit in units:
            self._put(unit, 8)

    def write_u16string(self, units, maxlen):
        """16-bit units (UTF-16BE): ends at its first NUL, or is exactly ``maxlen`` units long. All-or-nothing."""
        units = list(units)
        self._check_string_units(units, maxlen, "UTF-16 string", 16)
        for unit in units:
            self._put(unit, 16)

    # --- result --------------------------------------------------------------------------
    def getvalue(self, total_bytes: Optional[int] = None) -> bytes:
        """The bytes written so far, zero padded to ``total_bytes`` (``CapacityError`` if longer)."""
        out = bytes(self._buf[:self.bytespan()])
        if total_bytes is not None:
            if len(out) > total_bytes:
                raise CapacityError("The written bit stream is %d bytes long; it does not fit into %d bytes."
                                    % (len(out), total_bytes))
            out = out + bytes(total_bytes - len(out))
        return out

    def getbits(self):
        """Everything written so far as a BitString (exact bit length)."""
        return BitString(self.getvalue(), self._hi)

    def __repr__(self):
        return "BitWriter(pos=%d, bits_written=%d)" % (self.pos, self._hi)
