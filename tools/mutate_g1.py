#!/usr/bin/env python3
"""Mutation check of the G1 tests (the proof that U-01 to U-04, U-06 and the container tests bite).

    python3 -I tools/mutate_g1.py [--python PATH] [--list] [NAME_SUBSTRING ...]

Copies ``Addon/mvarlib``, the G1 tests and the reference W1 builder into a fresh temporary
directory (never inside the repository), then applies ONE source mutation at a time (flip an
endianness, break the masked write, shift a bit offset, drop a re-stamp, change a header width ...),
runs the G1 tests against the mutated copy with ``tools/run_tests.py --samples`` and reports whether
the tests KILLED the mutant (a test failed) or it SURVIVED. The real sources and the sample files are
only read. Exit status: 0 when every mutant that is not marked equivalent was killed, 1 otherwise,
2 when the unmutated baseline is not green.

A mutant marked EQUIVALENT cannot change any observable result (documented next to it); it is
expected to survive and does not fail the run.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FAST_BITIO = ["TestClobberHazard", "TestWidthsAndAlignment", "TestSignedFields", "TestStrings", "TestOverrun",
              "TestWriterRefusals", "TestBitString", "test_bitio.TestCopyAndPickle"]
CONTAINER = ["blf_real", "header_real", "labels_zlib", "test_hashing", "blf_synthetic"]
G1_TESTS = ("helpers_snapshot.py", "helpers_real.py", "helpers_container.py", "test_bitio.py", "test_blf_real.py",
            "test_header_real.py", "test_labels_zlib_real.py", "test_hashing.py", "test_blf_synthetic.py")
# Mutants that cannot change any observable result. Reason: the "zero" row of the candidate list matches a stored
# all-zero hash anyway, so classing it first only changes the (unobservable) length that would enter a digest.
EQUIVALENT = (
    "hashing: stored zero hash is not classed zero",
    # The next five were found by an independent verifier's mutation run; none can change a result:
    # a BitWriter's high-water update: _put sets pos = end one line earlier, so "pos == end" is always true
    "bitio: high-water mark only updated when pos == end",
    # the inflater's output cap only bounds memory; the length check after it raises the same error either way
    "blf: _cmp inflater not capped at the declared size",
    # chunks[3] being _eof (checked next) already implies eof_index == 3, because blocks 0 to 2 are _blf, chdr and a payload
    "blf: shape does not check the _eof index",
    # the length byte order handed to a recipe that ignores it: the recipe fixes the byte order inside the digest and the
    # stored length is written with the separate `endian` variable
    "blf: unknown-hash fallback flavour has a fixed length byte order",
    # four stored length bytes that are valid in both byte orders exist only when all four are zero, which has its own row
    "hashing: stored length readings try the other byte order first",
)

# (name, file relative to Addon/mvarlib, old text (must occur exactly once), new text, --only substrings)
MUTANTS = [
    # --- bitio -------------------------------------------------------------------------------
    ("bitio: masked put does not clear the target bits", "bitio.py",
     "    existing = (existing & ~mask) | (value << trail)\n    buf[b0:b1]",
     "    existing = existing | (value << trail)\n    buf[b0:b1]", FAST_BITIO),
    ("bitio: RVT clobber hazard (trailing bits wiped when start is byte aligned)", "bitio.py",
     "    existing = (existing & ~mask) | (value << trail)\n    buf[b0:b1] = existing.to_bytes(b1 - b0, \"big\")",
     "    existing = (existing & ~mask) | (value << trail)\n    if start % 8 == 0 and n % 8:\n        existing &= ~((1 << trail) - 1)\n    buf[b0:b1] = existing.to_bytes(b1 - b0, \"big\")", FAST_BITIO),
    ("bitio: clobber hazard only for n < 8 (the literal C++ case)", "bitio.py",
     "    existing = (existing & ~mask) | (value << trail)\n    buf[b0:b1] = existing.to_bytes(b1 - b0, \"big\")",
     "    existing = (existing & ~mask) | (value << trail)\n    if start % 8 == 0 and n < 8:\n        existing &= ~((1 << trail) - 1)\n    buf[b0:b1] = existing.to_bytes(b1 - b0, \"big\")", FAST_BITIO),
    ("bitio: patch_bits clears the neighbours (writes the whole byte pair)", "bitio.py",
     "    _masked_put(buf, bitpos, nbits, value)\n\n\nclass BitString",
     "    _masked_put(buf, bitpos, nbits, value)\n    if bitpos % 8 == 4:\n        buf[bitpos // 8] &= 0xF0\n\n\nclass BitString", FAST_BITIO),
    ("bitio: read_signed never negative", "bitio.py",
     "if n and (value >> (n - 1)) & 1:", "if n and (value >> n) & 1:", FAST_BITIO),
    ("bitio: write accepts oversize values", "bitio.py",
     "        if not isinstance(value, int) or value < 0 or value >> n:\n            raise EncodeError(\"The value %r does not fit in %d bits.\" % (value, n))\n        self._put(value, n)",
     "        if not isinstance(value, int) or value < 0:\n            raise EncodeError(\"The value %r does not fit in %d bits.\" % (value, n))\n        self._put(value & ((1 << n) - 1), n)", FAST_BITIO),
    ("bitio: read_cstring drops the NUL", "bitio.py",
     "                unit = self.read(8)\n                out.append(unit)\n                if unit == 0:\n                    break",
     "                unit = self.read(8)\n                if unit == 0:\n                    break\n                out.append(unit)", FAST_BITIO),
    ("bitio: overrun check off by one", "bitio.py",
     "        if self.pos + n > self.bit_length:\n            raise BitOverrun(\"Read of",
     "        if self.pos + n >= self.bit_length:\n            raise BitOverrun(\"Read of", FAST_BITIO),
    ("bitio: bit_length ignored", "bitio.py",
     "        self.bit_length = bit_length\n        self.pos = 0", "        self.bit_length = total\n        self.pos = 0", FAST_BITIO),
    ("bitio: BitString padding not canonical", "bitio.py",
     "        if spare:                                     # canonical form: padding bits are zero\n",
     "        if False:                                     # canonical form: padding bits are zero\n", FAST_BITIO),
    ("bitio: write_to_bitpos does not restore pos", "bitio.py",
     "        finally:\n            self.pos = saved", "        finally:\n            pass", FAST_BITIO),
    ("bitio: getvalue floors the partial byte", "bitio.py",
     "    def bytespan(self):\n        return (self._hi + 7) >> 3", "    def bytespan(self):\n        return self._hi >> 3", FAST_BITIO),
    ("bitio: u16string reads 8 bits", "bitio.py",
     "                unit = self.read(16)\n                out.append(unit)", "                unit = self.read(8)\n                out.append(unit)", FAST_BITIO),
    ("bitio: zero-width read consumes a bit", "bitio.py",
     "        if n == 0:\n            return 0\n        self._need(n)", "        if n == 0:\n            self.pos += 1\n            return 0\n        self._need(n)", FAST_BITIO),
    ("bitio: LSB-first reading (negative control of SPEC 3.1)", "bitio.py",
     "    return (chunk >> ((b1 << 3) - end)) & ((1 << n) - 1)",
     "    value = (chunk >> ((b1 << 3) - end)) & ((1 << n) - 1)\n    return int(bin(value)[2:].zfill(n)[::-1], 2)", FAST_BITIO),
    # --- hashing -----------------------------------------------------------------------------
    ("hashing: salt byte changed", "hashing.py", "0xED, 0xD4, 0x30,", "0xED, 0xD5, 0x30,", CONTAINER),
    ("hashing: salted_be32 uses LE32", "hashing.py",
     "        return SALT34 + struct.pack(\">I\", length) + data\n    if recipe == \"salted_le32\"",
     "        return SALT34 + struct.pack(\"<I\", length) + data\n    if recipe == \"salted_le32\"", CONTAINER),
    ("hashing: plain_le32 uses BE32", "hashing.py",
     "    if recipe == \"plain_le32\":\n        return struct.pack(\"<I\", length) + data",
     "    if recipe == \"plain_le32\":\n        return struct.pack(\">I\", length) + data", CONTAINER),
    ("hashing: zero length is not also tried as the capacity", "hashing.py",
     "        return [(spec.length_endian, 0), (spec.length_endian, spec.stream_capacity)]",
     "        return [(spec.length_endian, 0)]", CONTAINER),
    ("hashing: hashed region one byte too long", "hashing.py",
     "        data = chunk[spec.stream_off:spec.stream_off + value]\n        for recipe",
     "        data = chunk[spec.stream_off:spec.stream_off + value + 1]\n        for recipe", CONTAINER),
    ("hashing: candidate order puts data_only first", "hashing.py",
     "RECIPES = (\"plain_le32\", \"salted_be32\", \"salted_le32\", \"plain_be32\", \"data_only\")",
     "RECIPES = (\"data_only\", \"plain_be32\", \"salted_le32\", \"salted_be32\", \"plain_le32\")", CONTAINER),
    ("hashing: stored zero hash is not classed zero", "hashing.py",
     "        if stored == bytes(HASH_SIZE):\n            flavour = HashFlavour(readings[0][0], ZERO)\n        else:",
     "        if False:\n            flavour = HashFlavour(readings[0][0], ZERO)\n        else:", CONTAINER),
    ("hashing: compute accepts data shorter than L", "hashing.py",
     "    if len(data) < L:\n        raise HashError(", "    if False:\n        raise HashError(", CONTAINER),
    ("hashing: valid length range includes 0 for non-zero bytes (lower bound)", "hashing.py",
     "        if 1 <= value <= spec.stream_capacity:", "        if 1 <= value <= spec.stream_capacity + 1:", CONTAINER),
    ("hashing: matching length reported wrong (stored instead of matched)", "hashing.py",
     "                    hash_length = value\n                    break", "                    hash_length = readings[0][1]\n                    break", CONTAINER),
    # --- blf ---------------------------------------------------------------------------------
    ("blf: embedded file length not re-stamped", "blf.py",
     "        if restamp:                                                                   # step 3\n            bitio.patch_bits(",
     "        if False:                                                                   # step 3\n            bitio.patch_bits(", CONTAINER),
    ("blf: embedded file length written at bit 5", "blf.py",
     "spec.stream_off * 8 + spec.embedded_filelen_bit, 32, total)", "spec.stream_off * 8 + spec.embedded_filelen_bit + 1, 32, total)", CONTAINER),
    ("blf: embedded file length written with the clobbering whole-byte assignment", "blf.py",
     "            bitio.patch_bits(block, spec.stream_off * 8 + spec.embedded_filelen_bit, 32, total)",
     "            bitio.patch_bits(block, spec.stream_off * 8 + spec.embedded_filelen_bit, 32, total)\n            if spec.embedded_filelen_bit % 8:\n                block[spec.stream_off + 4] &= 0xF0", CONTAINER),
    ("blf: chdr file length not re-stamped", "blf.py",
     "                elif chunk.sig == \"chdr\" and restamp and", "                elif chunk.sig == \"chdr\" and False and", CONTAINER),
    ("blf: _eof value not re-stamped", "blf.py",
     "elif chunk.sig == \"_eof\" and index == self.eof_index and restamp and", "elif chunk.sig == \"_eof\" and index == self.eof_index and False and", CONTAINER),
    ("blf: _eof value off by one", "blf.py",
     "struct.pack_into(self.eof_endian + \"I\", block, 12, eof_pos)", "struct.pack_into(self.eof_endian + \"I\", block, 12, eof_pos + 1)", CONTAINER),
    ("blf: hash computed over the stale stream (before the F patch)", "blf.py",
     "        stream = bytes(block[spec.stream_off:spec.pad_off])\n        block[spec.hash_off",
     "        stream = bytes(chunk.raw[spec.stream_off:spec.pad_off])\n        block[spec.hash_off", CONTAINER),
    ("blf: stream_length override ignored", "blf.py",
     "    override = stream_length.get(chunk.sig)\n        if override is None:", "    override = None\n        if override is None:", CONTAINER),
    ("blf: unknown hash falls back to plain_le32", "blf.py",
     "used = hashing.HashFlavour(endian, spec.default_recipe or \"salted_be32\")      # DEC-2.3 case 3",
     "used = hashing.HashFlavour(endian, \"plain_le32\")      # DEC-2.3 case 3", CONTAINER),
    ("blf: length byte order taken from the layout, not from the file", "blf.py",
     "endian = flavour.length_endian if flavour is not None else analysis.length_endian",
     "endian = flavour.length_endian if flavour is not None else spec.length_endian", CONTAINER),
    ("blf: restamp only when forced (cmp expansion in patched mode not restamped)", "blf.py",
     "    restamp = force or total != old_total", "    restamp = force", CONTAINER),
    ("blf: modified ignores cmp expansion (no fsm/trailer warning after expansion)", "blf.py",
     "    modified = self.dirty or expanded", "    modified = self.dirty", CONTAINER),
    ("blf: pending stream ignored", "blf.py",
     "        if self._stream is None:\n            return self.raw\n        spec = self.spec", "        if True:\n            return self.raw\n        spec = self.spec", CONTAINER),
    ("blf: zero class requested on an ordinary template hashes 0 bytes", "blf.py",
     "                hashed = spec.stream_capacity       # switching", "                hashed = 0       # switching", CONTAINER),
    ("blf: trailing valid blocks treated as trailer", "blf.py",
     "    return all(_is_signature_byte(b) for b in sig)", "    return False", CONTAINER),
    ("blf: block sizes not re-stamped in forced mode is invisible, but a wrong size stamp is not", "blf.py",
     "                    struct.pack_into(\">I\", block, 4, len(block))                       # step 1: size from the rendered body",
     "                    struct.pack_into(\">I\", block, 4, len(block) + 1)                       # step 1: size from the rendered body", CONTAINER),
    ("blf: chdr file length stamped big-endian", "blf.py",
     "struct.pack_into(\"<I\", block, CHDR_FILE_LENGTH_OFFSET, total)", "struct.pack_into(\">I\", block, CHDR_FILE_LENGTH_OFFSET, total)", CONTAINER),
    ("blf: stored length written in the wrong byte order", "blf.py",
     "block[spec.length_off:spec.length_off + 4] = hashing.encode_length(value, endian)", "block[spec.length_off:spec.length_off + 4] = hashing.encode_length(value, '>' if endian == '<' else '<')", CONTAINER),
    ("blf: version/flags of an expanded block taken from the wrapper", "blf.py",
     "chunk = Chunk(inner_sig, inner_version, inner_flags, inner, pos, size, wrapper)", "chunk = Chunk(inner_sig, version, flags, inner, pos, size, wrapper)", CONTAINER),
    ("blf: cmp compression type check removed", "blf.py", "    if ctype != 0:\n        raise bad(", "    if False:\n        raise bad(", CONTAINER),
    ("blf: unexpected chunk version silently accepted", "blf.py", "        if chunk.version not in MVAR_EXPECTED_CHUNK_VERSIONS:", "        if False:", CONTAINER),
    ("blf: W_HASH_UNKNOWN not reported", "blf.py",
     "            issues.append(Issue(\"W_HASH_UNKNOWN\"", "            (lambda *a: None)(Issue(\"W_HASH_UNKNOWN\"", CONTAINER),
    ("blf: trailer dropped on rebuild", "blf.py", "        if self.trailer:\n            out.append(self.trailer)", "        if False:\n            out.append(self.trailer)", CONTAINER),
    ("blf: _cmp passthrough re-emits the expanded block", "blf.py",
     "                if force or chunk.dirty:\n                    expanded = True", "                if True:\n                    expanded = True", CONTAINER),
    ("blf: _cmp inner size not verified", "blf.py",
     "    if inner_size != len(inner):", "    if False:", CONTAINER),
    ("blf: mvar stream offset 40", "blf.py",
     "\"mvar\": PayloadSpec(\"mvar\", 0x7028, 12, 32, \">\", 36, 0x7000, 4, None)", "\"mvar\": PayloadSpec(\"mvar\", 0x7028, 12, 32, \">\", 40, 0x7000, 4, None)", CONTAINER),
    ("blf: mvar length at +36", "blf.py",
     "\"mvar\": PayloadSpec(\"mvar\", 0x7028, 12, 32, \">\", 36, 0x7000, 4, None)", "\"mvar\": PayloadSpec(\"mvar\", 0x7028, 12, 36, \">\", 36, 0x7000, 4, None)", CONTAINER),
    ("blf: mpvr embedded length at bit 71", "blf.py",
     "\"mpvr\": PayloadSpec(\"mpvr\", 0x5028, 12, 0x24, \"<\", 0x28, 0x5000, 72, \"salted_be32\")", "\"mpvr\": PayloadSpec(\"mpvr\", 0x5028, 12, 0x24, \"<\", 0x28, 0x5000, 71, \"salted_be32\")", CONTAINER),
    ("blf: mpvr wrongly given the mvar layout (the reference script's trap, reversed)", "blf.py",
     "\"mpvr\": PayloadSpec(\"mpvr\", 0x5028, 12, 0x24, \"<\", 0x28, 0x5000, 72, \"salted_be32\")", "\"mpvr\": PayloadSpec(\"mpvr\", 0x5028, 12, 0x20, \"<\", 0x24, 0x5000, 72, \"salted_be32\")", CONTAINER),
    ("blf: eof byte order detection swapped", "blf.py",
     "        if as_be == eof.offset:\n            blf.eof_endian, blf.eof_value_ok = \">\", True\n        elif as_le == eof.offset:\n            blf.eof_endian, blf.eof_value_ok = \"<\", True",
     "        if as_be == eof.offset:\n            blf.eof_endian, blf.eof_value_ok = \"<\", True\n        elif as_le == eof.offset:\n            blf.eof_endian, blf.eof_value_ok = \">\", True", CONTAINER),
    ("blf: drop_fsm does not make the file dirty", "blf.py", "            self._structure_dirty = True\n            self.shape = _shape_of", "            self.shape = _shape_of", CONTAINER),
    ("blf: block size below 12 accepted", "blf.py", "            if size < BLOCK_HEADER_SIZE:\n                raise BlfFormatError(\"The file is damaged: block '%s' at offset 0x%X has the invalid size", "            if False:\n                raise BlfFormatError(\"The file is damaged: block '%s' at offset 0x%X has the invalid size", CONTAINER),
    ("blf: 51 not refused as a chunk version", "blf.py", "MVAR_REFUSED_CHUNK_VERSIONS = (12, 13, 14, 50, 51)", "MVAR_REFUSED_CHUNK_VERSIONS = (12, 13, 14, 50)", CONTAINER),
    ("blf: shape ignores the fsm block", "blf.py", "    elif len(chunks) == 5 and sigs[4] == \"_fsm\":", "    elif len(chunks) == 5 and sigs[4] == \"_xxx\":", CONTAINER),
    ("blf: W_FSM_STALE only on dirty (never for expansion)", "blf.py", "        if modified and any(c.sig == \"_fsm\" for c in self.chunks):", "        if self.dirty and False and any(c.sig == \"_fsm\" for c in self.chunks):", CONTAINER),
    # --- ugc_header --------------------------------------------------------------------------
    ("header: hopper tested on the stored activity", "ugc_header.py",
     "        return self.activity == ACTIVITY_HOPPER", "        return self.activity_raw == ACTIVITY_HOPPER", CONTAINER),
    ("header: campaign difficulty 3 bits", "ugc_header.py",
     "header.campaign = CampaignTail(r.read(8), r.read(2), r.read(2), r.read(8), r.read(32))", "header.campaign = CampaignTail(r.read(8), r.read(3), r.read(2), r.read(8), r.read(32))", CONTAINER),
    ("header: author name limit 15", "ugc_header.py", "AUTHOR_NAME_MAX = 16", "AUTHOR_NAME_MAX = 15", CONTAINER),
    ("header: firefight tail 33 bits", "ugc_header.py",
     "header.firefight = FirefightTail(r.read(2), r.read(32))", "header.firefight = FirefightTail(r.read(2), r.read(31))", CONTAINER),
    ("header: engine icon for map variants instead of game variants", "ugc_header.py",
     "        return self.content_type == CONTENT_TYPE_GAME_VARIANT", "        return self.content_type == CONTENT_TYPE_MAP_VARIANT", CONTAINER),
    ("header: title limit 127", "ugc_header.py", "TEXT_UNITS_MAX = 128", "TEXT_UNITS_MAX = 127", CONTAINER),
    ("header: chdr map id at 0x40", "ugc_header.py", "\"map_id\": u(\"<I\", 0x3C)", "\"map_id\": u(\"<I\", 0x40)", CONTAINER),
    ("header: chdr build omits the pad bytes", "ugc_header.py",
     "    b[0x11:0x14] = _fixed(d[\"pad_11\"], 3, \"pad_11\")", "    pass", CONTAINER),
    ("header: stored contentType used undecoded", "ugc_header.py",
     "        return self.content_type_raw - 1\n\n    @property\n    def activity", "        return self.content_type_raw\n\n    @property\n    def activity", CONTAINER),
    ("header: author record reads 63-bit xuid", "ugc_header.py", "    xuid = r.read(64)\n    name", "    xuid = r.read(63)\n    name", CONTAINER),
    ("header: raw range kept one bit short", "ugc_header.py", "    header.raw = r.slice(start, r.pos)", "    header.raw = r.slice(start, r.pos - 1)", CONTAINER),
    # --- second round: the gaps an independent verifier found (every one is now killed or documented equivalent) --
    ("bitio: BitString cannot be copied or pickled (the defect as found)", "bitio.py",
     "    def __copy__(self):\n        return self\n\n    def __deepcopy__(self, memo):\n        return self\n\n    def __reduce__(self):\n        return (type(self), (self._data, self._nbits))\n\n",
     "", FAST_BITIO + ["TestHeaderCopyAndPickle", "test_blf_synthetic.TestCopyAndPickle"]),
    ("bitio: BitString pickle drops the bit count", "bitio.py",
     "        return (type(self), (self._data, self._nbits))", "        return (type(self), (self._data,))", FAST_BITIO),
    ("bitio: read_cstring keeps pos advanced after an overrun", "bitio.py",
     "        except BitOverrun:\n            self.pos = start\n            raise\n        return bytes(out)",
     "        except BitOverrun:\n            raise\n        return bytes(out)", FAST_BITIO),
    ("bitio: read_u16string keeps pos advanced after an overrun", "bitio.py",
     "        except BitOverrun:\n            self.pos = start\n            raise\n        return out",
     "        except BitOverrun:\n            raise\n        return out", FAST_BITIO),
    ("bitio: string writers do not range-check the units", "bitio.py",
     "        for unit in units:\n            if not isinstance(unit, int) or unit < 0 or unit >> width:\n                raise EncodeError(\"The value %r does not fit in a %d-bit unit of a %s.\" % (unit, width, what))\n",
     "", FAST_BITIO),
    ("bitio: write_u16string validates unit by unit while writing", "bitio.py",
     "        self._check_string_units(units, maxlen, \"UTF-16 string\", 16)\n        for unit in units:\n            self._put(unit, 16)",
     "        for unit in units:\n            self.write(unit, 16)\n        self._check_string_units(units, maxlen, \"UTF-16 string\", 16)", FAST_BITIO),
    ("bitio: getvalue adds a byte when the bits are a multiple of 8", "bitio.py",
     "        return (self._hi + 7) >> 3", "        return (self._hi + 8) >> 3", FAST_BITIO),
    ("bitio: high-water mark only updated when pos == end", "bitio.py",
     "        if end > self._hi:\n            self._hi = end", "        if end > self._hi and self.pos == end:\n            self._hi = end", FAST_BITIO),
    ("bitio: reader.slice refuses the exact end", "bitio.py",
     "        if end > self.bit_length:\n            raise BitOverrun(\"Bit range", "        if end >= self.bit_length:\n            raise BitOverrun(\"Bit range", FAST_BITIO),
    ("blf: a block that overruns the file by one byte is accepted", "blf.py",
     "            if pos + size > size_total:\n                raise BlfFormatError(\"The file is damaged: block '%s' at offset 0x%X claims",
     "            if pos + size > size_total + 1:\n                raise BlfFormatError(\"The file is damaged: block '%s' at offset 0x%X claims", CONTAINER),
    ("blf: block limit 257", "blf.py", "MAX_BLOCKS = 256 ", "MAX_BLOCKS = 257 ", CONTAINER),
    ("blf: block limit check off by one", "blf.py", "        if len(chunks) >= MAX_BLOCKS:", "        if len(chunks) > MAX_BLOCKS:", CONTAINER),
    ("blf: trailing blocks are recognised by size alone", "blf.py",
     "    return all(_is_signature_byte(b) for b in sig)", "    return True", CONTAINER),
    ("blf: trailing signature accepts Latin-1 letters", "blf.py",
     "    return 0x30 <= b <= 0x39 or 0x41 <= b <= 0x5A or 0x61 <= b <= 0x7A or b == 0x5F",
     "    return chr(b).isalnum() or b == 0x5F", CONTAINER),
    ("blf: trailing signature rejects the underscore", "blf.py",
     " or 0x61 <= b <= 0x7A or b == 0x5F", " or 0x61 <= b <= 0x7A", CONTAINER),
    ("blf: trailing signature rejects 9", "blf.py", "    return 0x30 <= b <= 0x39 or", "    return 0x30 <= b < 0x39 or", CONTAINER),
    ("blf: trailing signature rejects Z", "blf.py", "or 0x41 <= b <= 0x5A or", "or 0x41 <= b < 0x5A or", CONTAINER),
    ("blf: trailing signature rejects z", "blf.py", "or 0x61 <= b <= 0x7A or", "or 0x61 <= b < 0x7A or", CONTAINER),
    ("blf: trailing signature accepts @ and [", "blf.py", "    return 0x30 <= b <= 0x39 or 0x41 <= b <= 0x5A", "    return 0x30 <= b <= 0x39 or 0x40 <= b <= 0x5B", CONTAINER),
    ("blf: trailing block of size 12 refused", "blf.py",
     "    if size < BLOCK_HEADER_SIZE or pos + size > len(data):\n        return False\n    return all",
     "    if size <= BLOCK_HEADER_SIZE or pos + size > len(data):\n        return False\n    return all", CONTAINER),
    ("blf: trailing block that overruns the file by one byte accepted", "blf.py",
     "    if size < BLOCK_HEADER_SIZE or pos + size > len(data):\n        return False\n    return all",
     "    if size < BLOCK_HEADER_SIZE or pos + size > len(data) + 1:\n        return False\n    return all", CONTAINER),
    ("blf: shape does not check the _blf size", "blf.py", "    for index in (0, 1, 3):", "    for index in (1, 3):", CONTAINER),
    ("blf: shape does not check the chdr size", "blf.py", "    for index in (0, 1, 3):", "    for index in (0, 3):", CONTAINER),
    ("blf: shape does not check the _eof size", "blf.py", "    for index in (0, 1, 3):", "    for index in (0, 1):", CONTAINER),
    ("blf: shape does not check the _eof index", "blf.py", "    if len(chunks) < 4 or eof_index != 3:", "    if len(chunks) < 4:", CONTAINER),
    ("blf: every _eof block is re-stamped, not only the first", "blf.py",
     "elif chunk.sig == \"_eof\" and index == self.eof_index and restamp", "elif chunk.sig == \"_eof\" and restamp", CONTAINER),
    ("blf: the last _eof is taken as the end of the file", "blf.py",
     "        if chunk.sig == \"_eof\" and eof_index is None:\n            eof_index = len(chunks) - 1",
     "        if chunk.sig == \"_eof\":\n            eof_index = len(chunks) - 1", CONTAINER),
    ("blf: a little-endian _eof value is preferred when both orders match", "blf.py",
     "        if as_be == eof.offset:\n            blf.eof_endian, blf.eof_value_ok = \">\", True\n        elif as_le == eof.offset:\n            blf.eof_endian, blf.eof_value_ok = \"<\", True",
     "        if as_le == eof.offset:\n            blf.eof_endian, blf.eof_value_ok = \"<\", True\n        elif as_be == eof.offset:\n            blf.eof_endian, blf.eof_value_ok = \">\", True", CONTAINER),
    ("blf: set_stream refuses the capacity class length", "blf.py",
     "not 0 <= length <= self.spec.stream_capacity", "not 0 <= length < self.spec.stream_capacity", CONTAINER),
    ("blf: set_stream does not zero pad a short stream", "blf.py",
     "        self._stream = stream + bytes(self.spec.stream_capacity - len(stream))", "        self._stream = stream", CONTAINER),
    ("blf: set_stream refuses a stream of exactly the capacity", "blf.py",
     "        if len(stream) > self.spec.stream_capacity:", "        if len(stream) >= self.spec.stream_capacity:", CONTAINER),
    ("blf: _cmp inflater not capped at the declared size", "blf.py",
     "inflater.decompress(raw[17:], usize + 1)", "inflater.decompress(raw[17:])", CONTAINER),
    ("blf: unknown-hash fallback flavour has a fixed length byte order", "blf.py",
     "used = hashing.HashFlavour(endian, spec.default_recipe or \"salted_be32\")", "used = hashing.HashFlavour(\">\", spec.default_recipe or \"salted_be32\")", CONTAINER),
    ("hashing: stored length readings try the other byte order first", "hashing.py",
     "    order = [spec.length_endian, \"<\" if spec.length_endian == \">\" else \">\"]",
     "    order = [\"<\" if spec.length_endian == \">\" else \">\", spec.length_endian]", CONTAINER),
    ("header: chdr author records read from each other's offsets", "ugc_header.py",
     "_AUTHOR_OFFSETS = ((\"created_by\", 0x48), (\"modified_by\", 0x6C))", "_AUTHOR_OFFSETS = ((\"created_by\", 0x6C), (\"modified_by\", 0x48))", CONTAINER),
    ("header: chdr comparison skips the content type", "ugc_header.py",
     "    check(\"content type\", chdr[\"content_type\"], header.content_type)\n", "", CONTAINER),
    ("header: chdr comparison skips the file length", "ugc_header.py",
     "    check(\"file length\", chdr[\"file_length\"], header.file_length)\n", "", CONTAINER),
    ("header: chdr comparison skips the map id", "ugc_header.py",
     "    check(\"map id\", chdr[\"map_id\"], header.map_id)\n", "", CONTAINER),
    ("header: chdr comparison skips the description", "ugc_header.py",
     "    check(\"description\", chdr[\"description\"], header.description_text)\n", "", CONTAINER),
    ("header: chdr comparison skips the title", "ugc_header.py",
     "    check(\"title\", chdr[\"title\"], header.title_text)\n", "", CONTAINER),
    ("header: chdr comparison reads the modified author for the created one", "ugc_header.py",
     "        for who in (\"created_by\", \"modified_by\"):\n            record = getattr(header, who)",
     "        for who in (\"created_by\", \"modified_by\"):\n            record = getattr(header, \"modified_by\")", CONTAINER),
]

def prepare(sandbox):
    os.makedirs(os.path.join(sandbox, "Addon"))
    os.makedirs(os.path.join(sandbox, "tests", "unit"))
    os.makedirs(os.path.join(sandbox, "tools"))
    os.makedirs(os.path.join(sandbox, "docs", "mvar"))
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(os.path.join(REPO, "Addon", "mvarlib"), os.path.join(sandbox, "Addon", "mvarlib"), ignore=ignore)
    shutil.copytree(os.path.join(REPO, "docs", "mvar", "reference"), os.path.join(sandbox, "docs", "mvar", "reference"), ignore=ignore)
    for name in G1_TESTS:
        shutil.copy(os.path.join(REPO, "tests", "unit", name), os.path.join(sandbox, "tests", "unit", name))
    shutil.copy(os.path.join(REPO, "tools", "run_tests.py"), os.path.join(sandbox, "tools", "run_tests.py"))


def run(python, sandbox, only):
    cmd = [python, "-I", os.path.join(sandbox, "tools", "run_tests.py"), "--samples", "--only"] + list(only)
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, cwd=sandbox)
    return proc.returncode, proc.stdout


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--python", default=sys.executable, help="interpreter that runs the tests (default: this one)")
    ap.add_argument("--list", action="store_true", help="list the mutants and exit")
    ap.add_argument("names", nargs="*", help="run only mutants whose name contains one of these")
    args = ap.parse_args(argv)
    if args.list:
        for name, rel, _, _, _ in MUTANTS:
            print("%-14s %s%s" % (rel, name, "   [EQUIVALENT]" if name in EQUIVALENT else ""))
        print("%d mutants" % len(MUTANTS))
        return 0
    sandbox = tempfile.mkdtemp(prefix="mjolnir-g1-mutants-")
    if os.path.realpath(sandbox).startswith(os.path.realpath(REPO) + os.sep):
        print("refusing to work inside the repository", file=sys.stderr)
        return 2
    try:
        prepare(sandbox)
        for label, only in (("container tests", CONTAINER), ("bitio tests", FAST_BITIO)):
            code, out = run(args.python, sandbox, only)
            print("baseline (%s): exit %d" % (label, code))
            if code != 0:
                print(out[-3000:])
                return 2
        survivors = []
        killed = 0
        for name, rel, old, new, only in MUTANTS:
            if args.names and not any(n in name for n in args.names):
                continue
            target = os.path.join(sandbox, "Addon", "mvarlib", rel)
            with open(target, "r") as handle:
                original = handle.read()
            if original.count(old) != 1:
                print("BAD MUTANT (pattern found %d times): %s" % (original.count(old), name))
                survivors.append(name + " [bad pattern]")
                continue
            with open(target, "w") as handle:
                handle.write(original.replace(old, new))
            try:
                code, out = run(args.python, sandbox, only)
            finally:
                with open(target, "w") as handle:
                    handle.write(original)
            if code == 0:
                tag = "equivalent" if name in EQUIVALENT else "SURVIVED"
                print("%-10s %s" % (tag, name))
                if name not in EQUIVALENT:
                    survivors.append(name)
            else:
                killed += 1
                first = [line for line in out.splitlines() if line.startswith(("FAIL:", "ERROR:"))][:1]
                print("killed     %s   (%s)" % (name, first[0][:80] if first else "import or other failure"))
        print("")
        print("%d killed, %d survived (equivalent mutants are not counted)" % (killed, len(survivors)))
        for name in survivors:
            print("  SURVIVOR: " + name)
        return 1 if survivors else 0
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
