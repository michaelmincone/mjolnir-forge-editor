"""Forge label table: decode, encode, text lookup (SPEC 3.4; gate G3).

The table sits right after the fixed body fields and holds a single language (X12)::

    9 bits   count N (0..511 in the field; more than 256 is an error)
    N x      presence bit (1 = present), then a 12-bit byte offset if present
    if N > 0:
      13 bits  dataLength   uncompressed byte count of the string buffer
       1 bit   isCompressed
      compressed:   13 bits compSize (includes a 4-byte prefix), then compSize bytes:
                    u32 BE uncompressed size + a zlib stream
      uncompressed: dataLength raw bytes (8 bits at a time, any bit alignment)

A label's text is ``buffer[offset : first NUL at or after offset]``; an entry whose presence bit is 0 has
*no text* (that is not the empty string). The label index stored in an object slot is the entry index.
The library never edits the table (DEC-3.2): it is re-emitted from its raw bit range; ``encode_label_table``
exists for ``from_plain``, tests and the "label re-encode identical" report line.

Pure Python 3.9 to 3.13, standard library only, relative imports only.
"""
import struct
import zlib
from typing import List, Optional

from .bitio import BitReader, BitString, BitWriter
from .errors import DecodeError, EncodeError

__all__ = ["LabelTable", "LabelError", "read_label_table", "encode_label_table", "label_text", "decode_text",
           "COUNT_BITS", "OFFSET_BITS", "DATA_LENGTH_BITS", "COMP_SIZE_BITS", "MAX_COUNT", "COMPRESS_MIN_BYTES"]

COUNT_BITS = 9
OFFSET_BITS = 12
DATA_LENGTH_BITS = 13
COMP_SIZE_BITS = 13
MAX_COUNT = 256
COMPRESS_MIN_BYTES = 0x80          # RVT compresses a buffer from this size on (informative, 3.4)
_MAX_INFLATED = 1 << 20            # hard cap while inflating (the 13-bit size field cannot describe more)


class LabelError(DecodeError):
    """The label table cannot be read (count above 256, bad compressed block, ...). ``bit`` is where it went wrong."""

    def __init__(self, message="", bit=None):
        super().__init__(message)
        self.bit = bit


def decode_text(raw):
    """Text of label bytes: UTF-8 with a Latin-1 fallback (the encoding is ``U``, 3.4)."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


class LabelTable(object):
    """A decoded label table plus its raw bit range (SPEC 5.1)."""

    def __init__(self, count, entries, data_length, compressed, buffer, comp_bytes, raw, start_bit=0, end_bit=0):
        self.count = count                       # N as stored
        self.entries = entries                   # List[Optional[int]]: byte offset, or None for an absent entry
        self.data_length = data_length           # the stored 13-bit value (0 when N == 0)
        self.compressed = compressed
        self.buffer = buffer                     # the (inflated) string buffer
        self.comp_bytes = comp_bytes             # compressed: the compSize bytes as stored (u32 BE size + zlib stream)
        self.raw = raw                           # BitString of the whole table
        self.start_bit = start_bit
        self.end_bit = end_bit

    # --- queries ---------------------------------------------------------------------------
    def present(self, index):
        """True when ``index`` is a valid entry whose presence bit is set."""
        return 0 <= index < self.count and self.entries[index] is not None

    @property
    def present_flags(self):
        return [e is not None for e in self.entries]

    def text_bytes(self, index):
        """Bytes of label ``index`` (up to its NUL), or ``None`` for an absent entry or an offset past the buffer."""
        if not 0 <= index < self.count:
            return None
        offset = self.entries[index]
        if offset is None or offset >= len(self.buffer):
            return None
        end = self.buffer.find(b"\x00", offset)
        if end < 0:
            end = len(self.buffer)
        return self.buffer[offset:end]

    def text(self, index):
        """Decoded text of label ``index``; ``''`` for an absent entry or an unusable offset."""
        raw = self.text_bytes(index)
        return decode_text(raw) if raw is not None else ""

    def texts(self):
        return [self.text(i) for i in range(self.count)]

    def undecodable(self):
        """Indices of present entries whose offset lies past the buffer or whose bytes are not valid UTF-8."""
        out = []
        for i in range(self.count):
            if self.entries[i] is None:
                continue
            raw = self.text_bytes(i)
            if raw is None:
                out.append(i)
                continue
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError:
                out.append(i)
        return out

    @property
    def inflated_length_matches(self):
        """For a compressed table: the inflated length equals dataLength (a mismatch is only a warning)."""
        return (not self.compressed) or len(self.buffer) == self.data_length

    def bit_length(self):
        return self.raw.nbits

    def __repr__(self):
        return "LabelTable(count=%d, buffer=%d bytes, %s)" % (self.count, len(self.buffer),
                                                              "compressed" if self.compressed else "plain")


def _inflate(blob, bit):
    """Inflate ``compSize`` bytes (u32 BE uncompressed size + zlib stream) with a hard output cap."""
    if len(blob) < 4:
        raise LabelError("The compressed label block is only %d bytes long; it needs a 4-byte size prefix." % len(blob), bit)
    inflater = zlib.decompressobj()
    try:
        out = inflater.decompress(blob[4:], _MAX_INFLATED + 1)
    except zlib.error as exc:
        raise LabelError("The compressed label block could not be inflated (%s)." % exc, bit)
    if len(out) > _MAX_INFLATED:
        raise LabelError("The compressed label block expands to more than %d bytes." % _MAX_INFLATED, bit)
    if not inflater.eof:
        raise LabelError("The compressed label block is not a complete zlib stream.", bit)
    return out


def read_label_table(r: BitReader) -> LabelTable:
    """Decode the label table at the reader's position; the reader ends just after it.

    ``LabelError`` for a count above 256 and for a compressed block that cannot be inflated;
    ``BitOverrun`` (also a ``DecodeError``) when the stream ends inside the table.
    """
    start = r.pos
    count = r.read(COUNT_BITS)
    if count > MAX_COUNT:
        raise LabelError("The label table claims %d entries; at most %d are allowed." % (count, MAX_COUNT), start)
    entries = []
    for _ in range(count):
        entries.append(r.read(OFFSET_BITS) if r.read(1) else None)
    data_length = 0
    compressed = False
    buffer = b""
    comp_bytes = None
    if count > 0:
        data_length = r.read(DATA_LENGTH_BITS)
        compressed = bool(r.read(1))
        if compressed:
            size_bit = r.pos
            comp_size = r.read(COMP_SIZE_BITS)
            comp_bytes = r.read_bytes(comp_size)
            buffer = _inflate(comp_bytes, size_bit)
        else:
            buffer = r.read_bytes(data_length)
    end = r.pos
    return LabelTable(count, entries, data_length, compressed, buffer, comp_bytes, r.slice(start, end), start, end)


def encode_label_table(entries: List[Optional[int]], buffer: bytes, compressed: Optional[bool] = None,
                       comp_bytes: Optional[bytes] = None, data_length: Optional[int] = None) -> BitString:
    """Bit string of a label table built from fields.

    * ``entries``: offset or ``None`` per label (at most 256, offsets below 4096).
    * ``compressed``: ``None`` follows RVT's rule (compress when the buffer has at least 0x80 bytes);
      ``True``/``False`` force it.
    * ``comp_bytes``: the exact ``compSize`` bytes to write when compressing (so a decoded table is
      reproduced regardless of the local zlib); otherwise ``u32 BE len(buffer)`` + ``zlib`` level 9.
    * ``data_length``: the dataLength field; default ``len(buffer)``.
    """
    count = len(entries)
    if count > MAX_COUNT:
        raise EncodeError("A label table holds at most %d entries, got %d." % (MAX_COUNT, count))
    w = BitWriter()
    w.write(count, COUNT_BITS)
    for offset in entries:
        if offset is None:
            w.write(0, 1)
        else:
            w.write(1, 1)
            w.write(offset, OFFSET_BITS)
    if count == 0:
        return w.getbits()
    buffer = bytes(buffer)
    if data_length is None:
        data_length = len(buffer)
    if compressed is None:
        compressed = len(buffer) >= COMPRESS_MIN_BYTES
    w.write(data_length, DATA_LENGTH_BITS)
    w.write(1 if compressed else 0, 1)
    if compressed:
        if comp_bytes is None:
            comp_bytes = struct.pack(">I", len(buffer)) + zlib.compress(buffer, 9)
        comp_bytes = bytes(comp_bytes)
        w.write(len(comp_bytes), COMP_SIZE_BITS)
        w.write_bytes(comp_bytes)
    else:
        if len(buffer) != data_length:
            raise EncodeError("An uncompressed label buffer must have exactly dataLength (%d) bytes, got %d."
                              % (data_length, len(buffer)))
        w.write_bytes(buffer)
    return w.getbits()


def label_text(table, index):
    """Text of label ``index`` of ``table`` (``''`` for an absent entry); see :meth:`LabelTable.text`."""
    return table.text(index)
