"""G1 extra (not in the SPEC 9.3 catalogue): ``BlfFile`` on synthetic container shapes (SPEC 2.1 to 2.11).

The tier-T2 container tests (U-10) belong to gate G3 and need the full fixture builder; these tests
pin the behaviour of the generic container code itself with ``helpers_container`` (a tiny, independent
``struct`` builder): the shapes ``plain4``, ``plain4+fsm``, ``cmp4``, ``cmp4+fsm`` and ``other``, a
trailer after ``_eof``, ``_eof`` byte orders, bad ``_cmp`` blocks, the chunk-version policy, and the
exact refusal sentences of SPEC 7.2. Nothing here needs the sample files.

The classes at the end pin the boundaries the first version of these tests left open (found by an
independent mutation run): the 256/257 block limit, a block that overruns the file by one byte, what
counts as a block after ``_eof``, the shape gate for wrong-sized ``_blf`` / ``chdr`` / ``_eof``,
``Chunk.set_stream`` (capacity class, zero padding), and copy/pickle of a parsed file.
"""
import copy
import os
import pickle
import struct
import sys
import unittest
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for _path in (HERE, os.path.join(REPO, "Addon")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import helpers_container as hc  # noqa: E402
from mvarlib import blf  # noqa: E402
from mvarlib.errors import BlfFormatError, CapacityError, InternalError, UnsupportedVariantError  # noqa: E402
from mvarlib.hashing import HashFlavour  # noqa: E402

MVAR_AT = 0x30 + 0x2C0
EOF_AT = MVAR_AT + 0x7028
PLAIN_SIZE = 29481


def codes(issues):
    return [i.code for i in issues]


class TestPlainShapes(unittest.TestCase):
    def setUp(self):
        self.stream = hc.random_stream(31, 800)
        self.plain, _ = hc.make_file(self.stream, 800)
        self.with_fsm, _ = hc.make_file(self.stream, 800, fsm=True)

    def test_plain4(self):
        parsed = blf.parse(self.plain)
        self.assertEqual(len(self.plain), PLAIN_SIZE)
        self.assertEqual((parsed.shape, parsed.trailer, parsed.warnings, parsed.dirty), ("plain4", b"", [], False))
        self.assertEqual(parsed.blocks(), [("_blf", 0, 0x30, 1, 2), ("chdr", 0x30, 0x2C0, 10, 2),
                                           ("mvar", MVAR_AT, 0x7028, 31, 1), ("_eof", EOF_AT, 0x11, 1, 1)])
        self.assertEqual(parsed.layout_text(), "_blf, chdr, mvar, _eof")
        self.assertEqual((parsed.eof_endian, parsed.eof_value_ok), (">", True))
        chunk = parsed.find("mvar")
        self.assertIs(chunk.spec, blf.PAYLOAD_SPECS["mvar"])
        self.assertEqual((chunk.stored_length, chunk.length_endian, chunk.length_raw), (800, ">", struct.pack(">I", 800)))
        self.assertEqual(chunk.stream, hc.put_embedded_length(self.stream, PLAIN_SIZE))
        self.assertEqual(len(chunk.stream), 0x7000)
        self.assertEqual(chunk.pad, bytes(4))
        self.assertEqual(chunk.hash_stored, self.plain[MVAR_AT + 12:MVAR_AT + 32])
        self.assertIsNone(parsed.find("mpvr"))
        self.assertIs(parsed.payload, chunk)
        self.assertEqual(parsed.to_bytes(), self.plain)
        self.assertEqual(parsed.to_bytes(force=True), self.plain)
        self.assertEqual(parsed.render(force=True).issues, [])

    def test_input_types(self):
        for convert in (bytes, bytearray, memoryview):
            parsed = blf.parse(convert(self.plain))
            self.assertEqual(parsed.to_bytes(), self.plain)
        for bad in ("text", None, 5, [1, 2]):
            with self.assertRaises(InternalError):
                blf.parse(bad)

    def test_plain4_with_fsm(self):
        parsed = blf.parse(self.with_fsm)
        self.assertEqual(parsed.shape, "plain4+fsm")
        self.assertEqual(parsed.layout_text(), "_blf, chdr, mvar, _eof, _fsm")
        self.assertEqual(parsed.find("_fsm").size, 0x1C4)
        self.assertEqual(parsed.to_bytes(), self.with_fsm)
        self.assertEqual(parsed.to_bytes(force=True), self.with_fsm)
        self.assertEqual(parsed.render(force=True).issues, [], "a forced rebuild of an unmodified file changes nothing")

    def test_a_modified_save_keeps_fsm_and_warns(self):
        parsed = blf.parse(self.with_fsm)
        new_stream = hc.put_embedded_length(hc.random_stream(32, 900), PLAIN_SIZE)
        parsed.find("mvar").set_stream(new_stream, 900)
        result = parsed.render()
        expected, _ = hc.make_file(hc.random_stream(32, 900), 900, fsm=True)
        self.assertEqual(result.data, expected)
        self.assertEqual(result.data[-0x1C4:], hc.fsm_block())
        self.assertEqual(codes(result.issues), ["W_FSM_STALE"])
        self.assertEqual(result.issues[0].severity, "warning")
        self.assertEqual(result.issues[0].message,
                         "The file-share signature block (_fsm) was kept unchanged. If MCC refuses the file, "
                         "export again with fsm_policy = DROP.")

    def test_dropping_fsm_is_a_modification_and_yields_the_shape_without_it(self):
        parsed = blf.parse(self.with_fsm)
        parsed.drop_fsm()
        self.assertTrue(parsed.dirty)
        self.assertEqual(parsed.shape, "plain4")
        result = parsed.render()
        self.assertEqual(result.data, self.plain, "the template bytes minus _fsm")
        self.assertEqual(result.issues, [])
        self.assertEqual(blf.parse(result.data).shape, "plain4")
        clean = blf.parse(self.plain)
        clean.drop_fsm()
        self.assertFalse(clean.dirty, "nothing to drop")
        self.assertIs(clean.to_bytes(), clean.original)

    def test_trailer_after_eof_is_kept_verbatim_and_reported_on_modification(self):
        for trailer in (bytes(200), b"padding that is not a block " * 5, bytes(range(256))):
            data, _ = hc.make_file(self.stream, 800, trailer=trailer)
            with self.subTest(trailer=len(trailer)):
                parsed = blf.parse(data)
                self.assertEqual((parsed.shape, parsed.trailer), ("plain4", trailer))
                self.assertEqual(parsed.to_bytes(), data)
                self.assertEqual(parsed.to_bytes(force=True), data)
                self.assertEqual(parsed.render(force=True).issues, [])
                parsed.find("mvar").set_stream(hc.put_embedded_length(hc.random_stream(33, 850), PLAIN_SIZE), 850)
                result = parsed.render()
                self.assertEqual(result.data[-len(trailer):], trailer)
                self.assertEqual(codes(result.issues), ["W_TRAILER_KEPT"])
                self.assertEqual(result.issues[0].message, "%d bytes after the end-of-file block were kept unchanged." % len(trailer))

    def test_fsm_followed_by_padding(self):
        data, _ = hc.make_file(self.stream, 800, fsm=True, trailer=bytes(64))
        parsed = blf.parse(data)
        self.assertEqual((parsed.shape, parsed.trailer), ("plain4+fsm", bytes(64)))
        self.assertEqual(parsed.to_bytes(force=True), data)

    def test_extra_blocks_make_the_shape_other(self):
        extra = hc.block(b"xRVT", 1, 1, b"editor data")
        after, _ = hc.make_file(self.stream, 800, trailer=extra)
        before, _ = hc.make_file(self.stream, 800, extra_before_eof=hc.block(b"athr", 1, 1, b"author"))
        for name, data in (("after _eof", after), ("before _eof", before)):
            with self.subTest(extra=name):
                parsed = blf.parse(data)
                self.assertEqual(parsed.shape, "other")
                self.assertEqual(parsed.to_bytes(), data, "passthrough works for every shape")
                self.assertIsNotNone(parsed.find("mvar"))
                with self.assertRaises(BlfFormatError) as ctx:
                    parsed.to_bytes(force=True)
                self.assertTrue(str(ctx.exception).startswith("This file's block layout ("))
                self.assertTrue(str(ctx.exception).endswith(") cannot be modified safely."))
                parsed.find("mvar").set_stream(self.stream, 800)
                with self.assertRaises(BlfFormatError):
                    parsed.to_bytes()

    def test_a_long_eof_block_is_passthrough_only(self):
        data, parts = hc.make_file(self.stream, 800)
        long_eof = hc.block(b"_eof", 1, 1, struct.pack(">I", EOF_AT) + bytes([3]) + bytes(256))
        data = b"".join(parts[:-1]) + long_eof
        parsed = blf.parse(data)
        self.assertEqual((parsed.shape, parsed.eof_value_ok), ("other", True))
        self.assertEqual(parsed.to_bytes(), data)
        with self.assertRaises(BlfFormatError):
            parsed.to_bytes(force=True)

    def test_pad_bytes_and_block_versions_are_copied_from_the_template(self):
        data, _ = hc.make_file(self.stream, 800, pad=b"\x01\x02\x03\x04", chunk_version=32)
        parsed = blf.parse(data)
        self.assertEqual(parsed.find("mvar").pad, b"\x01\x02\x03\x04")
        self.assertEqual(parsed.to_bytes(force=True), data)
        parsed.find("mvar").set_stream(hc.put_embedded_length(hc.random_stream(34, 700), PLAIN_SIZE), 700)
        out = parsed.to_bytes()
        self.assertEqual(out[EOF_AT - 4:EOF_AT], b"\x01\x02\x03\x04")
        self.assertEqual(struct.unpack_from(">4sIHH", out, MVAR_AT), (b"mvar", 0x7028, 32, 1))


class TestEofByteOrder(unittest.TestCase):
    def setUp(self):
        self.stream = hc.random_stream(41, 500)

    def test_little_endian_eof_value_is_detected_and_reproduced(self):
        data, _ = hc.make_file(self.stream, 500, eof_endian="<")
        parsed = blf.parse(data)
        self.assertEqual((parsed.eof_endian, parsed.eof_value_ok), ("<", True))
        self.assertEqual(parsed.to_bytes(force=True), data)

    def test_an_eof_value_that_matches_neither_order_is_rewritten_big_endian(self):
        data, _ = hc.make_file(self.stream, 500)
        broken = bytearray(data)
        broken[EOF_AT + 12:EOF_AT + 16] = b"\x01\x02\x03\x04"
        parsed = blf.parse(bytes(broken))
        self.assertEqual((parsed.eof_endian, parsed.eof_value_ok), (">", False))
        self.assertEqual(parsed.to_bytes(), bytes(broken))
        self.assertEqual(parsed.to_bytes(force=True), data)

    def test_the_authentication_byte_is_kept(self):
        data, _ = hc.make_file(self.stream, 500)
        changed = bytearray(data)
        changed[EOF_AT + 16] = 7
        self.assertEqual(blf.parse(bytes(changed)).to_bytes(force=True), bytes(changed))


class TestCmp(unittest.TestCase):
    def setUp(self):
        self.stream = hc.random_stream(51, 1000)
        self.plain, _ = hc.make_file(self.stream, 1000)
        self.cmp, _ = hc.make_file(self.stream, 1000, wrap_cmp=True)
        self.cmp_fsm, _ = hc.make_file(self.stream, 1000, wrap_cmp=True, fsm=True)
        self.plain_fsm, _ = hc.make_file(self.stream, 1000, fsm=True)

    def test_parse_expands_the_wrapper(self):
        parsed = blf.parse(self.cmp)
        self.assertEqual(parsed.shape, "cmp4")
        self.assertLess(len(self.cmp), 3000)
        chunk = parsed.find("mvar")
        self.assertEqual(chunk.size, len(self.cmp) - 0x30 - 0x2C0 - 0x11, "size and offset are the wrapper's")
        self.assertEqual(chunk.offset, MVAR_AT)
        self.assertEqual(len(chunk.raw), 0x7028)
        self.assertEqual((chunk.cmp.ctype, chunk.cmp.usize), (0, 0x7028))
        self.assertEqual((chunk.version, chunk.flags), (31, 1), "the expanded block keeps its own header, not the wrapper's")
        self.assertEqual(struct.unpack_from(">4sIHH", self.cmp, MVAR_AT), (b"_cmp", chunk.size, 1, 1))
        self.assertEqual(parsed.warnings, [])
        self.assertEqual(chunk.cmp.wrapper, self.cmp[MVAR_AT:MVAR_AT + chunk.size])
        self.assertEqual(chunk.flavour, HashFlavour(">", "salted_be32"))
        self.assertEqual(chunk.stored_length, 1000)
        self.assertEqual(parsed.eof_endian, ">")
        self.assertTrue(parsed.eof_value_ok, "the _eof value is the offset in the compressed file")

    def test_unmodified_save_emits_the_original_wrapper_bytes(self):
        for data in (self.cmp, self.cmp_fsm):
            parsed = blf.parse(data)
            self.assertEqual(parsed.to_bytes(), data)
            self.assertEqual(parsed.render().issues, [])

    def test_forced_rebuild_is_the_expanded_form(self):
        """DEC-2.6: ``force=True`` of a ``_cmp`` shape is the plain file, never the wrapper, never a new zlib stream."""
        for data, golden, shape in ((self.cmp, self.plain, "cmp4"), (self.cmp_fsm, self.plain_fsm, "cmp4+fsm")):
            parsed = blf.parse(data)
            self.assertEqual(parsed.shape, shape)
            result = parsed.render(force=True)
            self.assertEqual(result.data, golden)
            self.assertEqual(blf.parse(result.data).shape, shape.replace("cmp4", "plain4"))
            self.assertNotEqual(result.data, data)
            self.assertIn("W_CMP_EXPANDED", codes(result.issues))
        self.assertEqual(blf.parse(self.cmp).render(force=True).issues[0].message,
                         "The map variant was stored compressed; the exported file stores it uncompressed "
                         "(the game accepts both, per the available documentation).")
        self.assertEqual(codes(blf.parse(self.cmp_fsm).render(force=True).issues), ["W_CMP_EXPANDED", "W_FSM_STALE"])

    def test_modified_save_expands_and_restamps_all_three_lengths(self):
        parsed = blf.parse(self.cmp)
        new = hc.random_stream(52, 1100)
        parsed.find("mvar").set_stream(hc.put_embedded_length(new, 0xAAAAAAAA), 1100)      # wrong embedded value on purpose
        result = parsed.render()
        expected, _ = hc.make_file(new, 1100)
        self.assertEqual(result.data, expected)
        self.assertEqual(codes(result.issues), ["W_CMP_EXPANDED"])
        self.assertEqual(struct.unpack_from("<I", result.data, 0x30 + 0x14)[0], PLAIN_SIZE)
        self.assertEqual(struct.unpack_from(">I", result.data, EOF_AT + 12)[0], EOF_AT)
        self.assertEqual(hc.get_embedded_length(result.data[MVAR_AT + 36:MVAR_AT + 44]), PLAIN_SIZE)

    def test_an_embedded_length_that_counts_the_wrong_size_is_repaired_by_a_forced_rebuild(self):
        wrong, _ = hc.make_file(self.stream, 1000, wrap_cmp=True, embedded=len(self.cmp))
        self.assertNotEqual(wrong, self.cmp)
        parsed = blf.parse(wrong)
        self.assertEqual(parsed.find("mvar").flavour, HashFlavour(">", "salted_be32"))
        self.assertEqual(parsed.to_bytes(), wrong)
        self.assertEqual(parsed.to_bytes(force=True), self.plain)

    def test_a_clean_wrapper_survives_changes_to_other_blocks(self):
        parsed = blf.parse(self.cmp_fsm)
        parsed.drop_fsm()
        out = parsed.to_bytes()
        self.assertEqual(out, self.cmp, "the wrapper bytes are kept; only the _fsm block is gone")
        self.assertEqual(parsed.render().issues, [])

    def test_compression_level_does_not_matter_for_parsing(self):
        for level in (1, 6, 9):
            data, _ = hc.make_file(self.stream, 1000, wrap_cmp=True, cmp_level=level)
            parsed = blf.parse(data)
            self.assertEqual(parsed.to_bytes(), data)
            self.assertEqual(parsed.to_bytes(force=True), self.plain)

    def test_bad_cmp_blocks(self):
        inner = hc.mvar_block(hc.random_stream(53, 100), 100)
        base = hc.make_file(self.stream, 1000)[1]

        def file_with(cmp_block):
            return base[0] + base[1] + cmp_block + base[3]

        wrap = zlib.compress(inner, 9)
        cases = {
            "compression type 1": (hc.cmp_block(inner, ctype=1),
                                   "compression type 1 is not supported (only 0, zlib)"),
            "declared too small": (hc.cmp_block(inner, usize=0x7000), "it expands to more than the declared 28672 bytes"),
            "declared too big": (hc.cmp_block(inner, usize=0x7030), "it expands to 28712 bytes but 28720 were declared"),
            "declared implausible": (hc.cmp_block(inner, usize=5), "the declared size 5 is not plausible"),
            "declared huge": (hc.cmp_block(inner, usize=1 << 30), "the declared size 1073741824 is not plausible"),
            "truncated stream": (hc.cmp_block(inner, tamper=lambda z: z[:len(z) // 2]), "the zlib stream is incomplete"),
            "garbage stream": (hc.cmp_block(inner, tamper=lambda z: b"\x78\xda" + bytes(range(3, 60))), "the zlib stream is damaged"),
            "too short": (hc.block(b"_cmp", 1, 1, b"\x00\x00\x00"), "the block is too short (15 bytes)"),
        }
        for name, (cmp_block, reason) in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(BlfFormatError) as ctx:
                    blf.parse(file_with(cmp_block))
                self.assertTrue(str(ctx.exception).startswith("The compressed (_cmp) block could not be expanded: "), str(ctx.exception))
                self.assertIn(reason, str(ctx.exception))
        # a zlib stream with a flipped byte in the middle
        flipped = bytearray(wrap)
        flipped[len(flipped) // 2] ^= 0xFF
        with self.assertRaises(BlfFormatError):
            blf.parse(file_with(hc.cmp_block(inner, tamper=lambda z: bytes(flipped))))
        # an inner block whose own size field disagrees with the expanded size
        shrunk = bytearray(inner)
        struct.pack_into(">I", shrunk, 4, 0x7000)
        with self.assertRaises(BlfFormatError) as ctx:
            blf.parse(file_with(hc.cmp_block(bytes(shrunk))))
        self.assertIn("the inner block claims 28672 bytes but the expanded data is 28712 bytes", str(ctx.exception))
        # a compressed block whose inner mvar has the wrong size is refused as an unsupported variant
        small = hc.block(b"mvar", 31, 1, bytes(0x100))
        with self.assertRaises(UnsupportedVariantError):
            blf.parse(file_with(hc.cmp_block(small)))

    def test_a_cmp_that_wraps_something_else_is_an_unknown_block(self):
        other = hc.block(b"abcd", 1, 1, b"something else entirely" * 3)
        base = hc.make_file(self.stream, 1000)[1]
        data = base[0] + base[1] + hc.cmp_block(other) + base[3]
        parsed = blf.parse(data)
        self.assertEqual((parsed.shape, parsed.layout_text()), ("other", "_blf, chdr, _cmp, _eof"))
        self.assertIsNone(parsed.payload)
        self.assertEqual(parsed.to_bytes(), data)
        with self.assertRaises(BlfFormatError):
            parsed.to_bytes(force=True)


class TestRefusals(unittest.TestCase):
    """The sentences of SPEC 7.2 and the rules of 2.1."""

    def setUp(self):
        self.data = hc.plain_file()

    def refused(self, data, exception=BlfFormatError):
        with self.assertRaises(exception) as ctx:
            blf.parse(data)
        return str(ctx.exception)

    def test_too_short(self):
        self.assertEqual(self.refused(b""), "The file is too short to be a Halo BLF file (0 bytes).")
        self.assertEqual(self.refused(b"_blf"), "The file is too short to be a Halo BLF file (4 bytes).")

    def test_first_block_must_be_blf(self):
        data = b"mvar" + self.data[4:]
        self.assertEqual(self.refused(data), "This file is not a Halo BLF file (first block is 'mvar', expected '_blf').")
        data = b"\x00\x01\xffz" + self.data[4:]
        self.assertEqual(self.refused(data), "This file is not a Halo BLF file (first block is '???z', expected '_blf').")

    def test_blocks_must_tile(self):
        self.assertEqual(self.refused(self.data[:MVAR_AT + 100]),
                         "The file is damaged: block 'mvar' at offset 0x%X claims 28712 bytes but only 100 remain." % MVAR_AT)
        broken = bytearray(self.data)
        struct.pack_into(">I", broken, 0x30 + 4, 0x2C0 + 50)                 # chdr claims 50 more bytes
        self.assertTrue(self.refused(bytes(broken)).startswith("The file is damaged: block "))
        tiny = bytearray(self.data)
        struct.pack_into(">I", tiny, 0x30 + 4, 5)
        self.assertEqual(self.refused(bytes(tiny)), "The file is damaged: block 'chdr' at offset 0x30 has the invalid size 5.")

    def test_a_block_that_runs_exactly_one_byte_past_the_end(self):
        """The tiling check is exact: a block that claims one byte more than remains is refused, one that fits is not."""
        self.assertEqual(self.refused(self.data[:-1]),
                         "The file is damaged: block '_eof' at offset 0x%X claims 17 bytes but only 16 remain." % EOF_AT)
        self.assertEqual(self.refused(self.data[:EOF_AT - 1]),
                         "The file is damaged: block 'mvar' at offset 0x%X claims 28712 bytes but only 28711 remain." % MVAR_AT)
        self.assertEqual(blf.parse(self.data).shape, "plain4", "the exact fit is fine")
        # the same for the last block of a file that has no payload at all
        tiny = hc.blf_block() + hc.chdr_block(0) + hc.eof_block(0x30 + 0x2C0)
        self.assertEqual(blf.parse(tiny).chunks[-1].sig, "_eof")
        self.assertEqual(self.refused(tiny[:-1]),
                         "The file is damaged: block '_eof' at offset 0x%X claims 17 bytes but only 16 remain." % (0x30 + 0x2C0))

    def test_a_header_cut_in_half(self):
        self.assertEqual(self.refused(self.data[:0x30 + 7]),
                         "The file is damaged: 7 bytes at offset 0x30 are too short for a block header.")

    def test_eof_is_required(self):
        self.assertEqual(self.refused(self.data[:EOF_AT]), "The file has no end-of-file ('_eof') block.")

    def test_more_than_256_blocks(self):
        blocks = [hc.blf_block(), hc.chdr_block(0)] + [hc.block(b"abcd", 1, 1, b"") for _ in range(260)] + [hc.eof_block(0)]
        self.assertEqual(self.refused(b"".join(blocks)), "The file has more than 256 blocks.")
        ok = [hc.blf_block(), hc.chdr_block(0)] + [hc.block(b"abcd", 1, 1, b"") for _ in range(250)] + [hc.eof_block(0)]
        self.assertEqual(blf.parse(b"".join(ok)).shape, "other")

    def test_the_block_limit_is_exactly_256(self):
        """256 blocks (``_eof`` included) parse; the 257th is refused. 250 and 260 do not pin the boundary."""
        def file_of(count):
            middle = [hc.block(b"abcd", 1, 1, b"") for _ in range(count - 3)]
            return b"".join([hc.blf_block(), hc.chdr_block(0)] + middle + [hc.eof_block(0)])

        self.assertEqual(blf.MAX_BLOCKS, 256)
        for count in (255, 256):
            with self.subTest(blocks=count):
                parsed = blf.parse(file_of(count))
                self.assertEqual(len(parsed.chunks), count)
                self.assertEqual(parsed.eof_index, count - 1)
        for count in (257, 258):
            with self.subTest(blocks=count):
                self.assertEqual(self.refused(file_of(count)), "The file has more than 256 blocks.")

    def test_mvar_block_size(self):
        small = hc.block(b"mvar", 31, 1, bytes(0x6000 - 12))
        data = self.data[:MVAR_AT] + small + self.data[EOF_AT:]
        self.assertEqual(self.refused(data, UnsupportedVariantError),
                         "The map variant block has size 0x6000; only 0x7028 is supported.")
        game = hc.block(b"mpvr", 54, 1, bytes(0x100))
        data = self.data[:MVAR_AT] + game + self.data[EOF_AT:]
        self.assertEqual(self.refused(data, UnsupportedVariantError), "The 'mpvr' block has size 0x10C; only 0x5028 is supported.")

    def test_known_non_reach_chunk_versions_are_refused(self):
        for version in blf.MVAR_REFUSED_CHUNK_VERSIONS:
            data, _ = hc.make_file(hc.random_stream(61, 300), 300, chunk_version=version)
            self.assertEqual(self.refused(data, UnsupportedVariantError),
                             "The map variant block has chunk version %d; Halo: Reach uses 31 or 32 (50 and 51 are Halo 4, "
                             "12 to 14 are Halo 3)." % version)
        self.assertEqual(blf.MVAR_REFUSED_CHUNK_VERSIONS, (12, 13, 14, 50, 51))

    def test_other_chunk_versions_warn_and_31_32_do_not(self):
        for version in (31, 32):
            data, _ = hc.make_file(hc.random_stream(62, 300), 300, chunk_version=version)
            self.assertEqual(blf.parse(data).warnings, [])
        for version in (0, 1, 30, 33, 49, 52, 1000):
            data, _ = hc.make_file(hc.random_stream(62, 300), 300, chunk_version=version)
            warnings = blf.parse(data).warnings
            self.assertEqual(codes(warnings), ["W_CHUNK_VERSION_UNEXPECTED"], version)
            self.assertEqual((warnings[0].severity, warnings[0].message),
                             ("warning", "The map variant block has chunk version %d; Halo: Reach uses 31 or 32. "
                                         "It was read anyway because the layout fits." % version))

    def test_refusals_are_library_errors_with_complete_sentences(self):
        for bad in (b"", b"mvar" + self.data[4:], self.data[:EOF_AT]):
            message = self.refused(bad)
            self.assertTrue(message.endswith("."))
            self.assertNotIn("Traceback", message)


class TestScanAndApi(unittest.TestCase):
    def test_scan_blocks_never_raises(self):
        data = hc.plain_file()
        self.assertEqual([b[0] for b in blf.scan_blocks(data)], ["_blf", "chdr", "mvar", "_eof"])
        self.assertEqual(blf.scan_blocks(b""), [])
        self.assertEqual(blf.scan_blocks(b"junk"), [])
        cut = blf.scan_blocks(data[:MVAR_AT + 20])
        self.assertEqual([b[0] for b in cut], ["_blf", "chdr", "mvar"])
        self.assertEqual(cut[-1][2], 0x7028, "the claimed size is reported even when the block does not fit")
        zero_size = bytearray(data)
        struct.pack_into(">I", zero_size, 4, 0)
        self.assertEqual(len(blf.scan_blocks(bytes(zero_size))), 1)

    def test_payload_specs(self):
        mvar, mpvr = blf.PAYLOAD_SPECS["mvar"], blf.PAYLOAD_SPECS["mpvr"]
        self.assertEqual((mvar.chunk_size, mvar.hash_off, mvar.length_off, mvar.length_endian, mvar.stream_off,
                          mvar.stream_capacity, mvar.embedded_filelen_bit, mvar.default_recipe),
                         (0x7028, 12, 32, ">", 36, 0x7000, 4, None))
        self.assertEqual((mpvr.chunk_size, mpvr.hash_off, mpvr.length_off, mpvr.length_endian, mpvr.stream_off,
                          mpvr.stream_capacity, mpvr.embedded_filelen_bit, mpvr.default_recipe),
                         (0x5028, 12, 0x24, "<", 0x28, 0x5000, 72, "salted_be32"))
        self.assertEqual((mvar.pad_off, mpvr.pad_off), (0x7024, 0x5028))
        self.assertEqual(mvar.chunk_size - mvar.pad_off, 4, "the 4 zero bytes after the stream")
        self.assertEqual(mpvr.chunk_size - mpvr.pad_off, 0)
        with self.assertRaises(Exception):
            mvar.stream_off = 40                                          # frozen

    def test_render_argument_validation(self):
        parsed = blf.parse(hc.plain_file())
        with self.assertRaises(InternalError):
            parsed.render(flavour=("<", "salted_be32"))
        with self.assertRaises(InternalError):
            parsed.render(stream_length={"mvar": -1})
        with self.assertRaises(InternalError):
            parsed.render(stream_length={"chdr": 1})
        with self.assertRaises(InternalError):
            parsed.render(stream_length={"mvar": 0x7001})

    def test_stream_length_overrides_the_stored_length(self):
        data = hc.plain_file(used=600)
        parsed = blf.parse(data)
        out = parsed.to_bytes(force=True, stream_length={"mvar": 700})
        self.assertEqual(out[MVAR_AT + 32:MVAR_AT + 36], struct.pack(">I", 700))
        self.assertEqual(out[MVAR_AT + 12:MVAR_AT + 32], hc.digest("salted_be32", hc.put_embedded_length(hc.random_stream(1, 600), PLAIN_SIZE), 700))
        self.assertEqual(blf.parse(out).flavour, HashFlavour(">", "salted_be32"))
        # not forced and clean: the argument is ignored, the original comes back
        self.assertIs(parsed.to_bytes(stream_length={"mvar": 700}), parsed.original)

    def test_render_is_pure(self):
        data = hc.plain_file()
        parsed = blf.parse(data)
        parsed.find("mvar").set_stream(hc.put_embedded_length(hc.random_stream(9, 100), PLAIN_SIZE), 100)
        first = parsed.to_bytes()
        self.assertEqual(parsed.to_bytes(), first)
        self.assertEqual(parsed.original, data)
        self.assertTrue(parsed.dirty)


class TestAfterEof(unittest.TestCase):
    """What follows ``_eof``: further blocks while they look like blocks (D9), otherwise an opaque trailer."""

    def setUp(self):
        self.stream = hc.random_stream(81, 400)

    def tail(self, tail):
        data, _ = hc.make_file(self.stream, 400, trailer=tail)
        return blf.parse(data), data

    @staticmethod
    def raw_block(sig, size, total):
        """``total`` bytes: signature, a size field of ``size``, zero filler."""
        return sig + struct.pack(">I", size) + bytes(total - 8)

    def test_signatures_made_of_letters_digits_and_underscore_are_blocks(self):
        for sig in (b"abcd", b"ABCD", b"0123", b"_xyz", b"a_1Z", b"____", b"azAZ", b"09__", b"_fsm"):
            with self.subTest(sig=sig):
                parsed, data = self.tail(hc.block(sig, 1, 1, b""))
                self.assertEqual((parsed.layout_text(), parsed.trailer, parsed.shape),
                                 ("_blf, chdr, mvar, _eof, " + sig.decode(), b"", "other" if sig != b"_fsm" else "plain4+fsm"))
                self.assertEqual(parsed.to_bytes(), data)

    def test_any_other_signature_byte_makes_the_rest_an_opaque_trailer(self):
        """The shape stays ``plain4`` (D1) and a modified save keeps the bytes and warns."""
        bad = (b"ab d", b"ab-d", b"\x01\x02\x03\x04", b"ab\x00d", b"abc\x7f", b"ab.d", b"{abc", b"@abc", b"`abc", b"[abc",
               b"/abc", b":abc", b"abc\xff", b"\x5eabc")
        # Latin-1 letters are alphanumeric for Python's str.isalnum; they are not signature characters
        bad += (b"\xe9bcd", b"abc\xaa", b"a\xb5cd", b"\xc0\xc1\xc2\xc3")
        for sig in bad:
            with self.subTest(sig=sig):
                tail = hc.block(sig, 1, 1, b"payload")                  # a perfectly plausible size field
                parsed, data = self.tail(tail)
                self.assertEqual((parsed.shape, parsed.trailer, parsed.layout_text()), ("plain4", tail, "_blf, chdr, mvar, _eof"))
                self.assertEqual(parsed.to_bytes(), data)
                self.assertEqual(parsed.to_bytes(force=True), data)

    def test_a_trailer_that_starts_01_02_03_04_is_kept_not_parsed(self):
        tail = b"\x01\x02\x03\x04" + struct.pack(">I", 20) + bytes(12)
        parsed, data = self.tail(tail)
        self.assertEqual((parsed.shape, len(parsed.trailer), parsed.trailer), ("plain4", 20, tail))
        parsed.find("mvar").set_stream(hc.put_embedded_length(hc.random_stream(82, 450), PLAIN_SIZE), 450)
        result = parsed.render()
        self.assertEqual(result.data[-20:], tail)
        self.assertEqual(codes(result.issues), ["W_TRAILER_KEPT"])

    def test_the_size_field_decides_too(self):
        sig = b"abcd"
        as_block = "_blf, chdr, mvar, _eof, abcd"
        as_trailer = "_blf, chdr, mvar, _eof"
        cases = (
            # name, bytes after _eof, layout, the trailer that is left over
            ("size 11, below the 12 byte header", self.raw_block(sig, 11, 20), as_trailer, None),
            ("size 0", self.raw_block(sig, 0, 20), as_trailer, None),
            ("size 12, exactly the header", self.raw_block(sig, 12, 12), as_block, b""),
            ("size 13 then 7 bytes of padding", self.raw_block(sig, 13, 13) + bytes(7), as_block, bytes(7)),
            ("size 20 in 20 bytes, exact fit", self.raw_block(sig, 20, 20), as_block, b""),
            ("size 21 in 20 bytes, one too many", self.raw_block(sig, 21, 20), as_trailer, None),
            ("size 0xFFFFFFFF", self.raw_block(sig, 0xFFFFFFFF, 20), as_trailer, None),
            ("fewer than 12 bytes left", b"abcdefghijk", as_trailer, None),
        )
        for name, tail, layout, left in cases:
            with self.subTest(case=name):
                parsed, data = self.tail(tail)
                self.assertEqual((parsed.layout_text(), parsed.trailer), (layout, tail if left is None else left))
                self.assertEqual(parsed.to_bytes(), data)

    def test_blocks_then_padding(self):
        tail = hc.block(b"abcd", 1, 1, b"x") + bytes(30)
        parsed, data = self.tail(tail)
        self.assertEqual((parsed.layout_text(), parsed.trailer), ("_blf, chdr, mvar, _eof, abcd", bytes(30)))
        self.assertEqual(parsed.shape, "other")

    def test_a_second_eof_is_an_ordinary_trailing_block(self):
        data, _ = hc.make_file(self.stream, 400)
        second = hc.block(b"_eof", 1, 1, struct.pack(">I", 0x12345678) + b"\x00")
        parsed = blf.parse(data + second)
        self.assertEqual(parsed.layout_text(), "_blf, chdr, mvar, _eof, _eof")
        self.assertEqual(parsed.eof_index, 3, "the first _eof is the end of the file proper")
        self.assertEqual((parsed.eof_endian, parsed.eof_value_ok), (">", True), "the first _eof's value is the one checked")
        self.assertEqual(parsed.shape, "other")
        self.assertEqual(parsed.to_bytes(), data + second)
        with self.assertRaises(BlfFormatError):
            parsed.to_bytes(force=True)
        # white box: even with the shape gate bypassed, only the first _eof is ever re-stamped
        parsed.shape = "plain4"
        self.assertEqual(parsed.to_bytes(force=True), data + second)


class TestShapeGate(unittest.TestCase):
    """A ``_blf``, ``chdr`` or ``_eof`` of the wrong size makes the shape ``other``: readable, never rewritten."""

    def setUp(self):
        self.stream = hc.random_stream(91, 400)
        self.parts = hc.make_file(self.stream, 400)[1]

    def assemble(self, index, replacement):
        parts = list(self.parts)
        parts[index] = replacement
        return b"".join(parts)

    def test_wrong_sized_blocks(self):
        blf_block, chdr_block, _, eof_block = self.parts
        cases = (
            ("_blf 4 bytes too long", 0, hc.block(b"_blf", 1, 2, bytes(len(blf_block) - 12 + 4))),
            ("_blf 4 bytes too short", 0, hc.block(b"_blf", 1, 2, bytes(len(blf_block) - 12 - 4))),
            ("chdr 4 bytes too long", 1, hc.block(b"chdr", 10, 2, bytes(len(chdr_block) - 12 + 4))),
            ("chdr 4 bytes too short", 1, hc.block(b"chdr", 10, 2, bytes(len(chdr_block) - 12 - 4))),
            ("_eof 1 byte too long", 3, hc.block(b"_eof", 1, 1, eof_block[12:] + b"\x00")),
            ("_eof 1 byte too short", 3, hc.block(b"_eof", 1, 1, eof_block[12:-1])),
        )
        for name, index, replacement in cases:
            with self.subTest(case=name):
                data = self.assemble(index, replacement)
                parsed = blf.parse(data)
                self.assertEqual(parsed.shape, "other")
                self.assertEqual(parsed.layout_text(), "_blf, chdr, mvar, _eof")
                self.assertIsNotNone(parsed.find("mvar"), "still readable")
                self.assertEqual(parsed.to_bytes(), data, "passthrough")
                with self.assertRaises(BlfFormatError) as ctx:
                    parsed.to_bytes(force=True)
                self.assertTrue(str(ctx.exception).endswith(") cannot be modified safely."))
                parsed.find("mvar").set_stream(self.stream, 400)
                with self.assertRaises(BlfFormatError):
                    parsed.to_bytes()

    def test_the_standard_sizes_are_the_plain_shape(self):
        data = b"".join(self.parts)
        self.assertEqual([len(p) for p in self.parts], [blf.BLF_SIZE, blf.CHDR_SIZE, 0x7028, blf.EOF_SIZE])
        self.assertEqual(blf.parse(data).shape, "plain4")

    def test_a_payload_in_the_wrong_slot_is_other(self):
        blf_block, chdr_block, mvar_block, eof_block = self.parts
        for name, order in (("mvar before chdr", (blf_block, mvar_block, chdr_block, eof_block)),
                            ("chdr missing", (blf_block, mvar_block, eof_block)),
                            ("no payload", (blf_block, chdr_block, eof_block))):
            with self.subTest(case=name):
                data = b"".join(order)
                self.assertEqual(blf.parse(data).shape, "other")
                self.assertEqual(blf.parse(data).to_bytes(), data)


class TestEofValueOrder(unittest.TestCase):
    def test_a_value_that_reads_the_same_in_both_orders_is_taken_as_big_endian(self):
        """65792 = 00 01 01 00 is a byte palindrome: the order cannot be told from the bytes, the layout default wins."""
        offset = 0x00010100
        self.assertEqual(struct.pack(">I", offset), struct.pack("<I", offset))
        filler = hc.block(b"abcd", 1, 1, bytes(offset - 0x30 - 0x2C0 - 12))
        data = hc.blf_block() + hc.chdr_block(offset + 0x11) + filler + hc.eof_block(offset)
        self.assertEqual(len(data), offset + 0x11)
        parsed = blf.parse(data)
        self.assertEqual(parsed.chunks[parsed.eof_index].offset, offset)
        self.assertEqual((parsed.eof_endian, parsed.eof_value_ok), (">", True))

    def test_each_order_is_found_when_only_one_matches(self):
        for endian in (">", "<"):
            data, _ = hc.make_file(hc.random_stream(95, 100), 100, eof_endian=endian)
            parsed = blf.parse(data)
            self.assertEqual((parsed.eof_endian, parsed.eof_value_ok), (endian, True))


class TestSetStream(unittest.TestCase):
    def setUp(self):
        self.stream = hc.random_stream(71, 800)
        self.data, _ = hc.make_file(self.stream, 800)
        self.parsed = blf.parse(self.data)
        self.chunk = self.parsed.find("mvar")

    def test_the_capacity_class_length_is_accepted(self):
        """``L = 0x7000`` is what G5 passes for the capacity class; ``0x7001`` is a bug."""
        full = hc.random_stream(72, 0x7000)
        self.chunk.set_stream(hc.put_embedded_length(full, PLAIN_SIZE), 0x7000)
        out = self.parsed.to_bytes()
        expected, _ = hc.make_file(full, 0x7000)
        self.assertEqual(out, expected)
        self.assertEqual(struct.unpack_from(">I", out, MVAR_AT + 32)[0], 0x7000)
        self.assertEqual(out[MVAR_AT + 12:MVAR_AT + 32], hc.digest("salted_be32", hc.put_embedded_length(full, PLAIN_SIZE), 0x7000))
        reparsed = blf.parse(out)
        self.assertEqual((reparsed.find("mvar").stored_length, reparsed.flavour), (0x7000, HashFlavour(">", "salted_be32")))
        with self.assertRaises(InternalError):
            self.chunk.set_stream(full, 0x7001)

    def test_stream_length_argument_accepts_the_capacity_too(self):
        out = blf.parse(self.data).to_bytes(force=True, stream_length={"mvar": 0x7000})
        self.assertEqual(struct.unpack_from(">I", out, MVAR_AT + 32)[0], 0x7000)

    def test_a_short_stream_is_zero_padded_to_the_capacity(self):
        short = hc.put_embedded_length(hc.random_stream(73, 150)[:150], PLAIN_SIZE)
        self.assertEqual(len(short), 150)
        self.chunk.set_stream(short, 150)
        self.assertEqual(self.chunk.stream, short + bytes(0x7000 - 150))
        self.assertEqual(len(self.chunk.stream), 0x7000)
        out = self.parsed.to_bytes()
        expected, _ = hc.make_file(hc.random_stream(73, 150), 150)
        self.assertEqual(len(out), PLAIN_SIZE, "the block keeps its size")
        self.assertEqual(out, expected)
        self.assertEqual(blf.parse(out).find("mvar").stored_length, 150)

    def test_other_bytes_like_streams_and_an_omitted_length(self):
        for convert in (bytes, bytearray, memoryview):
            parsed = blf.parse(self.data)
            short = hc.put_embedded_length(hc.random_stream(74, 120)[:120], PLAIN_SIZE)
            parsed.find("mvar").set_stream(convert(short))                 # no length: the stored 800 is kept
            out = parsed.to_bytes()
            self.assertEqual(struct.unpack_from(">I", out, MVAR_AT + 32)[0], 800)
            self.assertEqual(out[MVAR_AT + 12:MVAR_AT + 32], hc.digest("salted_be32", short + bytes(0x7000 - 120), 800))
            self.assertEqual(len(out), PLAIN_SIZE)

    def test_a_refused_stream_changes_nothing(self):
        before = self.chunk.stream
        with self.assertRaises(CapacityError):
            self.chunk.set_stream(bytes(0x7001), 100)
        with self.assertRaises(InternalError):
            self.chunk.set_stream(bytes(10), -1)
        self.assertEqual((self.chunk.stream, self.parsed.dirty), (before, False))
        self.chunk.set_stream(bytes(0x7000))                                # exactly the capacity is fine
        self.assertTrue(self.parsed.dirty)


class TestCopyAndPickle(unittest.TestCase):
    """SPEC 6.3 ``MapVariant.copy()`` is a deep copy; the container objects must survive ``copy`` and ``pickle``."""

    def build(self):
        stream = hc.random_stream(101, 500)
        plain, _ = hc.make_file(stream, 500, chunk_version=33, fsm=True, trailer=bytes(30))   # 33 -> a parse warning
        wrapped, _ = hc.make_file(stream, 500, wrap_cmp=True)
        return {"plain": plain, "cmp": wrapped}

    def clones(self, parsed):
        yield "deepcopy", copy.deepcopy(parsed)
        yield "copy", copy.copy(parsed)
        for protocol in range(0, pickle.HIGHEST_PROTOCOL + 1):
            yield "pickle%d" % protocol, pickle.loads(pickle.dumps(parsed, protocol))

    def test_parsed_files_copy_and_pickle(self):
        for name, data in self.build().items():
            parsed = blf.parse(data)
            for how, clone in self.clones(parsed):
                with self.subTest(file=name, how=how):
                    self.assertEqual(clone.shape, parsed.shape)
                    self.assertEqual(clone.to_bytes(), data)
                    self.assertEqual(clone.to_bytes(force=True), parsed.to_bytes(force=True))
                    self.assertEqual(clone.warnings, parsed.warnings)
                    self.assertEqual(clone.find("mvar").flavour, parsed.find("mvar").flavour)
                    self.assertEqual(clone.find("mvar").analysis, parsed.find("mvar").analysis)
                    self.assertEqual(clone.layout_text(), parsed.layout_text())

    def test_a_modified_file_keeps_its_pending_changes_and_the_copy_is_independent(self):
        data = self.build()["plain"]
        parsed = blf.parse(data)
        new = hc.put_embedded_length(hc.random_stream(102, 600), PLAIN_SIZE + 30)
        parsed.find("mvar").set_stream(new, 600)
        expected = parsed.render()
        for how, clone in self.clones(parsed):
            with self.subTest(how=how):
                self.assertTrue(clone.dirty)
                result = clone.render()
                self.assertEqual(result.data, expected.data)
                self.assertEqual(result.issues, expected.issues)
        independent = copy.deepcopy(parsed)
        independent.find("mvar").set_stream(hc.random_stream(103, 700), 700)
        independent.drop_fsm()
        self.assertEqual(parsed.render().data, expected.data, "changing the copy must not change the original")
        self.assertNotEqual(independent.render().data, expected.data)
        self.assertEqual(parsed.layout_text(), "_blf, chdr, mvar, _eof, _fsm")

    def test_flavours_analyses_and_issues(self):
        parsed = blf.parse(self.build()["plain"])
        chunk = parsed.find("mvar")
        for value in (chunk.flavour, chunk.analysis, parsed.warnings, parsed.render(force=True).issues, blf.PAYLOAD_SPECS["mvar"]):
            for clone in (copy.deepcopy(value), pickle.loads(pickle.dumps(value))):
                self.assertEqual(clone, value)
        self.assertEqual(copy.deepcopy(chunk.flavour), (">", "salted_be32"))


if __name__ == "__main__":
    unittest.main()
