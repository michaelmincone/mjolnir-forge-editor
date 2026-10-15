"""Generic BLF block file: parse and rebuild (SPEC 2.1 to 2.12, 6.3; promoted in gate G1).

``BlfFile`` knows nothing about slots or labels. It parses any block list that tiles the file
(``_blf``, ``chdr``, a payload block, ``_eof``, optionally ``_fsm`` and unknown blocks) and keeps the
exact bytes of every block, so an unmodified save returns the input unchanged. For blocks whose
signature has a registered :class:`PayloadSpec` it also knows where the hash, the stored length and
the bit stream live and can *finalise* the block (``to_bytes(force=True)``).

The promoted reference ``docs/mvar/reference/blf_container.py`` hard-wired the ``mpvr`` layout
(stream at +0x28, little-endian length at +0x24), which is wrong for ``mvar``. The registry
:data:`PAYLOAD_SPECS` replaces that: ``mvar`` (stream at +36, length at +32) and ``mpvr`` (stream at
+0x28, length at +0x24) are separate payload specs, and the same code path serves both (tier T1
exercises it on the real ``mpvr`` game variants).

Output modes (SPEC 5.2):

* **passthrough**: nothing dirty and ``force`` false: the original bytes, verbatim (also for a
  ``_cmp`` wrapper, ``_fsm``, unknown blocks and a trailer).
* **patched**: a payload chunk was given a new stream (``Chunk.set_stream``): that block is
  rendered with the new stream, the stored length and the hash; every other block stays verbatim.
  The embedded file length, the ``chdr`` file length and the ``_eof`` value are re-stamped only when
  the total file length changed (a ``_cmp`` block that was expanded).
* **forced**: ``to_bytes(force=True)``: everything derivable is recomputed in the order of SPEC
  2.11: block sizes, total length ``F``, the embedded file length, the stored length ``L``, the
  hash, the ``_eof`` value, the ``chdr`` file length; ``_cmp`` shapes come out expanded (DEC-2.6).

Decisions taken here (details in ``docs/mvar/notes/G1.md``):

* The shape id describes the *block list* only (``plain4``, ``plain4+fsm``, ``cmp4``, ``cmp4+fsm``,
  ``other``), for any registered payload, so the real ``mpvr`` game variants are ``plain4``. A
  non-block remainder after ``_eof`` is kept in :attr:`BlfFile.trailer` and does not change the
  shape; a modified save keeps it verbatim and reports ``W_TRAILER_KEPT`` (SPEC 2.1, 7.3, U-10).
* A hash that matches no candidate is rewritten as ``salted_be32`` with the template's length byte
  order and reported as ``W_HASH_UNKNOWN`` (DEC-2.3, case 3).
* ``flavour=`` (an explicit ``HashFlavour``) only chooses the recipe when a hash is written; it does
  not turn a clean unforced save into a rewrite.

Pure Python 3.9 to 3.13, standard library only, relative imports only.
"""
import struct
import zlib
from dataclasses import dataclass
from typing import List, Mapping, Optional

from . import bitio
from . import hashing
from .api import Issue
from .errors import BlfFormatError, CapacityError, InternalError, UnsupportedVariantError
from .hashing import HashFlavour

__all__ = ["PayloadSpec", "PAYLOAD_SPECS", "CmpWrapper", "Chunk", "BlfFile", "Rendered", "parse", "scan_blocks",
           "BLOCK_HEADER_SIZE", "BLF_SIZE", "CHDR_SIZE", "EOF_SIZE", "MAX_BLOCKS", "MVAR_REFUSED_CHUNK_VERSIONS",
           "MVAR_EXPECTED_CHUNK_VERSIONS"]

BLOCK_HEADER_SIZE = 12
BLF_SIZE = 0x30
CHDR_SIZE = 0x2C0
EOF_SIZE = 0x11
MAX_BLOCKS = 256                                  # SPEC 2.1: more than 256 blocks is rejected
MAX_INFLATED = 1 << 24                            # a _cmp block may not declare more than 16 MiB
CHDR_FILE_LENGTH_OFFSET = 0x14                    # u32 little-endian (SPEC 2.4)
MVAR_REFUSED_CHUNK_VERSIONS = (12, 13, 14, 50, 51)    # Halo 3 and Halo 4 (SPEC 2.2, X26)
MVAR_EXPECTED_CHUNK_VERSIONS = (31, 32)

_SHAPE_SIZES = {"_blf": BLF_SIZE, "chdr": CHDR_SIZE, "_eof": EOF_SIZE}


@dataclass(frozen=True)
class PayloadSpec:
    """Where the hash, the stored stream length and the bit stream live inside a payload block."""
    sig: str
    chunk_size: int                    # whole block, header included
    hash_off: int                      # 20 bytes
    length_off: int                    # 4 bytes
    length_endian: str                 # '>' | '<': the layout's default byte order of the stored length
    stream_off: int
    stream_capacity: int               # bytes
    embedded_filelen_bit: int          # bit offset of the 32-bit file length inside the stream
    default_recipe: Optional[str]      # None: detect; if nothing matches, salted_be32 plus a warning

    @property
    def pad_off(self):
        """Offset of the bytes after the stream (4 zero bytes in an ``mvar`` block, none in ``mpvr``)."""
        return self.stream_off + self.stream_capacity


PAYLOAD_SPECS = {
    "mpvr": PayloadSpec("mpvr", 0x5028, 12, 0x24, "<", 0x28, 0x5000, 72, "salted_be32"),
    "mvar": PayloadSpec("mvar", 0x7028, 12, 32, ">", 36, 0x7000, 4, None),
}


@dataclass(frozen=True)
class CmpWrapper:
    """A ``_cmp`` wrapper: compression type (0 = zlib), declared uncompressed size, and the wrapper bytes."""
    ctype: int
    usize: int
    wrapper: bytes                     # the whole _cmp block as found in the file


@dataclass(frozen=True)
class Rendered:
    """Result of :meth:`BlfFile.render`: the bytes and the issues the writer raised."""
    data: bytes
    issues: List[Issue]


def _printable(sig_bytes):
    return "".join(chr(b) if 32 <= b < 127 else "?" for b in sig_bytes)


def _hex_bytes(raw):
    return " ".join("%02X" % b for b in raw)


class Chunk(object):
    """One block of the file (SPEC 5.1; "chunk" in the sketches, "block" in the prose).

    ``raw`` is the exact original bytes of the block; for a block that came out of a ``_cmp``
    wrapper it is the inflated block and ``cmp`` describes the wrapper. ``offset`` and ``size`` are
    the position and length in the original file (the wrapper's, for such a block).
    """

    def __init__(self, sig, version, flags, raw, offset, size, cmp=None):
        self.sig = sig
        self.version = version
        self.flags = flags
        self.raw = raw
        self.offset = offset
        self.size = size
        self.cmp = cmp
        self.dirty = False
        self.spec = None                               # PayloadSpec for registered payload blocks
        self.analysis = None                           # hashing.HashAnalysis at parse time
        self._stream = None                            # pending replacement of the stream (set_stream)
        self._length = None                            # pending stored length (set_stream)

    # --- payload view ----------------------------------------------------------------------
    @property
    def is_payload(self):
        return self.spec is not None

    @property
    def flavour(self):
        """Detected :class:`HashFlavour` of the stored hash, or ``None`` (unknown)."""
        return self.analysis.flavour if self.analysis is not None else None

    @property
    def length_endian(self):
        """Byte order of the stored stream length (the layout's default for four zero bytes)."""
        return self.analysis.length_endian if self.analysis is not None else None

    @property
    def stored_length(self):
        """The stored stream length ``L`` as an integer (0 for four zero bytes, see ``zero_length``)."""
        return self.analysis.stored_length if self.analysis is not None else 0

    @property
    def zero_length(self):
        return bool(self.analysis is not None and self.analysis.zero_length)

    @property
    def length_raw(self):
        """The 4 stored length bytes as found."""
        return self.analysis.length_raw if self.analysis is not None else b""

    @property
    def hash_stored(self):
        """The 20 stored hash bytes as found."""
        return self.analysis.stored_hash if self.analysis is not None else b""

    @property
    def stream(self):
        """The bit stream bytes (``stream_capacity`` long): the pending replacement if one was set."""
        if self.spec is None:
            raise InternalError("Block '%s' is not a payload block and has no bit stream." % self.sig)
        if self._stream is not None:
            return self._stream
        return self.raw[self.spec.stream_off:self.spec.pad_off]

    @property
    def pad(self):
        """The bytes after the stream (``mvar``: 4 bytes copied from the template)."""
        if self.spec is None:
            raise InternalError("Block '%s' is not a payload block." % self.sig)
        return self.raw[self.spec.pad_off:]

    def set_stream(self, stream, length=None):
        """Replace the bit stream (zero padded to the capacity) and mark the block dirty.

        ``length`` is the new stored length ``L`` (0 keeps the "four zero bytes" class); ``None``
        keeps the stored one. ``CapacityError`` if ``stream`` does not fit.
        """
        if self.spec is None:
            raise InternalError("Block '%s' is not a payload block and has no bit stream." % self.sig)
        stream = bytes(stream)
        if len(stream) > self.spec.stream_capacity:
            raise CapacityError("The bit stream needs %d bytes; the '%s' block can hold at most %d."
                                % (len(stream), self.sig, self.spec.stream_capacity))
        self._check_length(length)
        self._stream = stream + bytes(self.spec.stream_capacity - len(stream))
        self._length = length
        self.dirty = True

    def _check_length(self, length):
        if length is None:
            return
        if not isinstance(length, int) or not 0 <= length <= self.spec.stream_capacity:
            raise InternalError("The stream length %r is outside 0..0x%X." % (length, self.spec.stream_capacity))

    def _current(self):
        """``raw`` with the pending stream applied (stored length and hash are not touched)."""
        if self._stream is None:
            return self.raw
        spec = self.spec
        return self.raw[:spec.stream_off] + self._stream + self.raw[spec.pad_off:]

    def __repr__(self):
        return "Chunk(%r, offset=0x%X, size=0x%X%s%s)" % (self.sig, self.offset, self.size,
                                                          ", cmp" if self.cmp else "", ", dirty" if self.dirty else "")


class BlfFile(object):
    """A parsed block file (SPEC 5.1). Build one with :func:`parse`."""

    def __init__(self, original, chunks, trailer, eof_index):
        self.original = original
        self.chunks = chunks                           # logical chunks, in file order (through _eof and after it)
        self.trailer = trailer                         # opaque bytes after the last valid block
        self.eof_index = eof_index
        self.warnings = []                             # parse-time issues (W_CHUNK_VERSION_UNEXPECTED)
        self.eof_endian = ">"
        self.eof_value_ok = False                      # the _eof value equals the block's own offset in one byte order
        self._structure_dirty = False
        self.shape = "other"

    # --- queries ---------------------------------------------------------------------------
    def find(self, sig: str) -> Optional[Chunk]:
        """The first block with this signature (a ``_cmp``-wrapped payload is found by its inner signature)."""
        for chunk in self.chunks:
            if chunk.sig == sig:
                return chunk
        return None

    @property
    def payload(self):
        """The first registered payload block, or ``None``."""
        for chunk in self.chunks:
            if chunk.spec is not None:
                return chunk
        return None

    @property
    def flavour(self):
        """Detected hash flavour of the first payload block (``None`` = unknown or no payload)."""
        chunk = self.payload
        return chunk.flavour if chunk is not None else None

    @property
    def dirty(self):
        return self._structure_dirty or any(c.dirty for c in self.chunks)

    def blocks(self):
        """``[(sig, offset, size, version, flags), ...]`` of the logical blocks (original positions)."""
        return [(c.sig, c.offset, c.size, c.version, c.flags) for c in self.chunks]

    def layout_text(self):
        return ", ".join(c.sig for c in self.chunks)

    # --- modification ----------------------------------------------------------------------
    def drop_fsm(self):
        """Remove the trailing ``_fsm`` block(s) (``fsm_policy = DROP``). Counts as a modification."""
        kept = [c for i, c in enumerate(self.chunks) if not (i > self.eof_index and c.sig == "_fsm")]
        if len(kept) != len(self.chunks):
            self.chunks = kept
            self._structure_dirty = True
            self.shape = _shape_of(self.chunks, self.eof_index)

    # --- output ----------------------------------------------------------------------------
    def to_bytes(self, force: bool = False, stream_length: Optional[Mapping[str, int]] = None,
                 flavour: Optional[HashFlavour] = None) -> bytes:
        """The file bytes; see :meth:`render` for the arguments and the issues."""
        return self.render(force=force, stream_length=stream_length, flavour=flavour).data

    def render(self, force: bool = False, stream_length: Optional[Mapping[str, int]] = None,
               flavour: Optional[HashFlavour] = None) -> "Rendered":
        """Serialise the file and return :class:`Rendered` (bytes plus the issues the writer raised).

        * Clean and ``force`` false: the original bytes (passthrough); ``stream_length`` and
          ``flavour`` are ignored because no hash is written.
        * ``force`` true, or something dirty: see the module docstring.
        * ``stream_length``: ``{sig: L}`` overrides the stored length of that payload block (this is
          how the walk's ``ceil(end / 8)`` arrives); 0 keeps the "four zero bytes" class.
        * ``flavour``: a :class:`HashFlavour` that replaces the detected recipe and length byte order
          when the hash is written (``ExportOptions.hash_policy``, probe files).
        """
        if flavour is not None and not isinstance(flavour, HashFlavour):
            raise InternalError("flavour must be a HashFlavour or None.")
        if stream_length is not None:
            for sig, value in stream_length.items():
                chunk = self.find(sig)
                if chunk is None or chunk.spec is None:
                    raise InternalError("stream_length names '%s', which is not a payload block of this file." % sig)
                chunk._check_length(value)
        if not force and not self.dirty:
            return Rendered(self.original, [])
        if self.shape == "other":
            raise BlfFormatError("This file's block layout (%s) cannot be modified safely." % self.layout_text())
        return self._rebuild(bool(force), stream_length or {}, flavour)

    def _rebuild(self, force, stream_length, flavour):
        issues = []
        # --- decide, per block, which bytes are emitted --------------------------------------
        units = []                                    # [chunk, bytes to emit] in file order
        expanded = False
        for chunk in self.chunks:
            if chunk.cmp is not None:
                if force or chunk.dirty:
                    expanded = True
                    units.append([chunk, chunk._current()])
                else:
                    units.append([chunk, chunk.cmp.wrapper])
            else:
                units.append([chunk, chunk._current()])
        # --- 1/2: sizes and the total length F (through _eof) --------------------------------
        offset = 0
        eof_pos = 0
        total = 0
        for index, (chunk, body) in enumerate(units):
            if index == self.eof_index:
                eof_pos = offset
            offset += len(body)
            if index == self.eof_index:
                total = offset
        old_total = self.chunks[self.eof_index].offset + self.chunks[self.eof_index].size
        restamp = force or total != old_total
        modified = self.dirty or expanded
        if expanded:
            issues.append(Issue("W_CMP_EXPANDED", "warning",
                                "The map variant was stored compressed; the exported file stores it uncompressed "
                                "(the game accepts both, per the available documentation)."))
        # --- render each block ---------------------------------------------------------------
        out = []
        for index, (chunk, body) in enumerate(units):
            emit = body
            wrapper = chunk.cmp is not None and body is chunk.cmp.wrapper
            if not wrapper:
                block = bytearray(body)
                if force:
                    struct.pack_into(">I", block, 4, len(block))                       # step 1: size from the rendered body
                if chunk.spec is not None and (force or chunk.dirty):
                    self._render_payload(chunk, block, restamp, total, stream_length, flavour, issues)
                elif chunk.sig == "chdr" and restamp and len(block) >= CHDR_FILE_LENGTH_OFFSET + 4:
                    struct.pack_into("<I", block, CHDR_FILE_LENGTH_OFFSET, total)      # step 7
                elif chunk.sig == "_eof" and index == self.eof_index and restamp and len(block) >= 16:
                    struct.pack_into(self.eof_endian + "I", block, 12, eof_pos)        # step 6
                emit = bytes(block)
            out.append(emit)
        # --- the opaque trailer is kept verbatim ---------------------------------------------
        if self.trailer:
            out.append(self.trailer)
            if modified:
                issues.append(Issue("W_TRAILER_KEPT", "warning",
                                    "%d bytes after the end-of-file block were kept unchanged." % len(self.trailer)))
        if modified and any(c.sig == "_fsm" for c in self.chunks):
            issues.append(Issue("W_FSM_STALE", "warning",
                                "The file-share signature block (_fsm) was kept unchanged. If MCC refuses the file, "
                                "export again with fsm_policy = DROP."))
        return Rendered(b"".join(out), issues)

    def _render_payload(self, chunk, block, restamp, total, stream_length, flavour, issues):
        """Steps 3 to 5 of SPEC 2.11 for one payload block (``block`` is a bytearray of its bytes)."""
        spec = chunk.spec
        analysis = chunk.analysis
        if restamp:                                                                   # step 3
            bitio.patch_bits(block, spec.stream_off * 8 + spec.embedded_filelen_bit, 32, total)
        endian = flavour.length_endian if flavour is not None else analysis.length_endian
        override = stream_length.get(chunk.sig)
        if override is None:
            override = chunk._length
        if override is None:                                                          # step 4: keep the stored L
            value = analysis.stored_length
            hashed = analysis.hash_length
        else:
            value = override
            hashed = override
        if value == 0:                                                                # the "four zero bytes" class
            block[spec.length_off:spec.length_off + 4] = bytes(4)
            if override is not None and not analysis.zero_length:
                hashed = spec.stream_capacity       # switching to the zero class: the effective length is the capacity
            else:
                hashed = analysis.hash_length       # the template's own zero class: whichever length it hashed
        else:
            block[spec.length_off:spec.length_off + 4] = hashing.encode_length(value, endian)
        # step 5: the hash, by the detected (or forced) flavour, over the stream as it now is
        if flavour is not None:
            used = flavour
        elif analysis.flavour is not None:
            used = analysis.flavour
            if used.recipe == hashing.ZERO:
                issues.append(Issue("I_HASH_ZERO", "info",
                                    "The template carries no SHA-1 (20 zero bytes, which KSoft.Blam documents for "
                                    "MCC-written game variants); none was written."))
        else:
            used = hashing.HashFlavour(endian, spec.default_recipe or "salted_be32")      # DEC-2.3 case 3
            issues.append(Issue("W_HASH_UNKNOWN", "warning",
                                "The template's SHA-1 matches no known recipe; the salted recipe was written. "
                                "Whether MCC checks it is unknown."))
        stream = bytes(block[spec.stream_off:spec.pad_off])
        block[spec.hash_off:spec.hash_off + hashing.HASH_SIZE] = hashing.compute(used, stream, hashed)


# ---------------------------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------------------------
def _is_signature_byte(b):
    """A block signature is four ASCII letters, digits or underscores (``chr(b).isalnum()`` would also pass Latin-1 letters)."""
    return 0x30 <= b <= 0x39 or 0x41 <= b <= 0x5A or 0x61 <= b <= 0x7A or b == 0x5F


def _plausible_trailing_block(data, pos):
    """Bytes after ``_eof`` are further blocks only while they look like valid blocks."""
    if pos + BLOCK_HEADER_SIZE > len(data):
        return False
    sig = data[pos:pos + 4]
    size = struct.unpack_from(">I", data, pos + 4)[0]
    if size < BLOCK_HEADER_SIZE or pos + size > len(data):
        return False
    return all(_is_signature_byte(b) for b in sig)


def scan_blocks(data):
    """Tolerant block listing for diagnostics: ``[(sig, offset, size, version, flags), ...]``.

    Never raises on damage: it stops at the first block that cannot be read (a block that does not
    fit is still listed with its claimed size, then the scan ends).
    """
    data = bytes(data)
    out = []
    pos = 0
    while pos + BLOCK_HEADER_SIZE <= len(data) and len(out) < MAX_BLOCKS:
        sig, size, version, flags = struct.unpack_from(">4sIHH", data, pos)
        out.append((sig.decode("latin-1"), pos, size, version, flags))
        if size < BLOCK_HEADER_SIZE or pos + size > len(data):
            break
        pos += size
    return out


def _expand_cmp(raw):
    """Inflate a ``_cmp`` wrapper (SPEC 2.8). Returns ``(CmpWrapper, inner_block_bytes)``."""
    def bad(reason):
        return BlfFormatError("The compressed (_cmp) block could not be expanded: %s." % reason)

    if len(raw) < 18:
        raise bad("the block is too short (%d bytes)" % len(raw))
    ctype = raw[12]
    usize = struct.unpack_from(">I", raw, 13)[0]
    if ctype != 0:
        raise bad("compression type %d is not supported (only 0, zlib)" % ctype)
    if usize < BLOCK_HEADER_SIZE or usize > MAX_INFLATED:
        raise bad("the declared size %d is not plausible" % usize)
    inflater = zlib.decompressobj()
    try:
        inner = inflater.decompress(raw[17:], usize + 1)
    except zlib.error as exc:
        raise bad("the zlib stream is damaged (%s)" % exc)
    if len(inner) > usize:
        raise bad("it expands to more than the declared %d bytes" % usize)
    if not inflater.eof:
        raise bad("the zlib stream is incomplete")
    if len(inner) != usize:
        raise bad("it expands to %d bytes but %d were declared" % (len(inner), usize))
    inner_size = struct.unpack_from(">I", inner, 4)[0]
    if inner_size != len(inner):
        raise bad("the inner block claims %d bytes but the expanded data is %d bytes" % (inner_size, len(inner)))
    return CmpWrapper(ctype, usize, bytes(raw)), bytes(inner)


def _attach_payload(chunk, warnings):
    """Registered payload block: check its size, apply the chunk-version policy, detect length and hash."""
    spec = PAYLOAD_SPECS.get(chunk.sig)
    if spec is None:
        return
    if len(chunk.raw) != spec.chunk_size:
        if chunk.sig == "mvar":
            raise UnsupportedVariantError("The map variant block has size 0x%X; only 0x%X is supported."
                                          % (len(chunk.raw), spec.chunk_size))
        raise UnsupportedVariantError("The '%s' block has size 0x%X; only 0x%X is supported."
                                      % (chunk.sig, len(chunk.raw), spec.chunk_size))
    if chunk.sig == "mvar":
        if chunk.version in MVAR_REFUSED_CHUNK_VERSIONS:
            raise UnsupportedVariantError(
                "The map variant block has chunk version %d; Halo: Reach uses 31 or 32 (50 and 51 are Halo 4, "
                "12 to 14 are Halo 3)." % chunk.version)
        if chunk.version not in MVAR_EXPECTED_CHUNK_VERSIONS:
            warnings.append(Issue("W_CHUNK_VERSION_UNEXPECTED", "warning",
                                  "The map variant block has chunk version %d; Halo: Reach uses 31 or 32. "
                                  "It was read anyway because the layout fits." % chunk.version))
    analysis = hashing.analyse(chunk.raw, spec)
    if analysis.length_endian is None:
        raise BlfFormatError("The stored stream length bytes %s are not a valid length (maximum 0x%X)."
                             % (_hex_bytes(chunk.raw[spec.length_off:spec.length_off + 4]), spec.stream_capacity))
    chunk.spec = spec
    chunk.analysis = analysis


def _shape_of(chunks, eof_index):
    """Shape id of SPEC 2.10 from the logical block list (the trailer does not matter)."""
    sigs = [c.sig for c in chunks]
    if len(chunks) < 4 or eof_index != 3:
        return "other"
    payload = chunks[2]
    if sigs[:2] != ["_blf", "chdr"] or sigs[3] != "_eof" or payload.spec is None:
        return "other"
    for index in (0, 1, 3):
        if chunks[index].size != _SHAPE_SIZES[sigs[index]]:
            return "other"
    if len(chunks) == 4:
        tail = ""
    elif len(chunks) == 5 and sigs[4] == "_fsm":
        tail = "+fsm"
    else:
        return "other"
    return ("cmp4" if payload.cmp is not None else "plain4") + tail


def parse(data: bytes) -> BlfFile:
    """Parse a BLF file into a :class:`BlfFile`.

    Raises ``BlfFormatError`` for: a first block that is not ``_blf``; a block that runs past the end
    of the file before ``_eof``; no ``_eof``; more than 256 blocks; a bad ``_cmp``; a stored stream
    length that is invalid in both byte orders. Raises ``UnsupportedVariantError`` for a registered
    payload block of the wrong size and for the known non-Reach ``mvar`` chunk versions.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise InternalError("parse() needs bytes, got %s." % type(data).__name__)
    data = bytes(data)
    size_total = len(data)
    if size_total < BLOCK_HEADER_SIZE:
        raise BlfFormatError("The file is too short to be a Halo BLF file (%d bytes)." % size_total)
    chunks = []
    warnings = []
    pos = 0
    eof_index = None
    while pos < size_total:
        if eof_index is not None and not _plausible_trailing_block(data, pos):
            break
        if pos + BLOCK_HEADER_SIZE > size_total:
            raise BlfFormatError("The file is damaged: %d bytes at offset 0x%X are too short for a block header."
                                 % (size_total - pos, pos))
        sig_bytes, size, version, flags = struct.unpack_from(">4sIHH", data, pos)
        sig = sig_bytes.decode("latin-1")
        if not chunks and sig != "_blf":
            raise BlfFormatError("This file is not a Halo BLF file (first block is '%s', expected '_blf')."
                                 % _printable(sig_bytes))
        if eof_index is None:
            if size < BLOCK_HEADER_SIZE:
                raise BlfFormatError("The file is damaged: block '%s' at offset 0x%X has the invalid size %d."
                                     % (_printable(sig_bytes), pos, size))
            if pos + size > size_total:
                raise BlfFormatError("The file is damaged: block '%s' at offset 0x%X claims %d bytes but only %d remain."
                                     % (_printable(sig_bytes), pos, size, size_total - pos))
        if len(chunks) >= MAX_BLOCKS:
            raise BlfFormatError("The file has more than %d blocks." % MAX_BLOCKS)
        raw = data[pos:pos + size]
        chunk = Chunk(sig, version, flags, raw, pos, size)
        if sig == "_cmp":
            wrapper, inner = _expand_cmp(raw)
            inner_sig, _, inner_version, inner_flags = struct.unpack_from(">4sIHH", inner, 0)
            inner_sig = inner_sig.decode("latin-1")
            if inner_sig in PAYLOAD_SPECS:
                chunk = Chunk(inner_sig, inner_version, inner_flags, inner, pos, size, wrapper)
            # a _cmp that wraps anything else is kept as an unknown (opaque) block
        _attach_payload(chunk, warnings)
        chunks.append(chunk)
        if chunk.sig == "_eof" and eof_index is None:
            eof_index = len(chunks) - 1
        pos += size
    if eof_index is None:
        raise BlfFormatError("The file has no end-of-file ('_eof') block.")
    trailer = data[pos:]
    blf = BlfFile(data, chunks, trailer, eof_index)
    blf.warnings = warnings
    eof = chunks[eof_index]
    if len(eof.raw) >= 16:
        as_be = struct.unpack_from(">I", eof.raw, 12)[0]
        as_le = struct.unpack_from("<I", eof.raw, 12)[0]
        if as_be == eof.offset:
            blf.eof_endian, blf.eof_value_ok = ">", True
        elif as_le == eof.offset:
            blf.eof_endian, blf.eof_value_ok = "<", True
    blf.shape = _shape_of(chunks, eof_index)
    return blf
