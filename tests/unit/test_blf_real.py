"""U-02 (SPEC 9.3, 9.8 row 1, tier T1): the generic ``BlfFile`` code path on the 8 real game-variant files.

For every one of the 8 paths (5 distinct contents) the test checks, in this order: chunk walk and
tiling; ``to_bytes() == input``; ``to_bytes(force=True) == input``; flavour detection returns
``('<', 'salted_be32')`` and ``plain_le32`` does **not** match; the recomputed hash equals the stored
one; a 1-bit flip in the stream breaks every candidate and restoring it matches again; the ``_eof``
value and byte order. Only a file that passes every clause prints ``PASS <file> <sha256[:16]>``.

Further tests prove that the forced rebuild really recomputes (a file with a wrong ``chdr`` length, a
wrong ``_eof`` value, a wrong embedded length or a wrong hash comes out as the original) and that it
keeps what is not derivable (stored length, the unused bytes, unhashed stream bits).
"""
import hashlib
import os
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for _path in (HERE, os.path.join(REPO, "Addon")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import helpers_real  # noqa: E402
from mvarlib import bitio, blf, hashing  # noqa: E402
from mvarlib.errors import BlfFormatError  # noqa: E402

# Independent copy of the 34-byte salt (SPEC 2.7) so the stored hashes of the real files check the library's constant.
SALT34 = bytes.fromhex("EDD43009666D5C4A5C3657FAB40E022F535AC6C9EE471F01F1A44756B7714F1C36EC")
MPVR_AT = 0x2F0
EOF_AT = 0x5318
CHDR_AT = 0x30


def independent_blocks(data):
    """Plain ``struct`` block walk (no library code): ``[(sig, offset, size, version, flags)]``."""
    out = []
    pos = 0
    while pos + 12 <= len(data):
        sig, size, version, flags = struct.unpack_from(">4sIHH", data, pos)
        out.append((sig.decode("latin-1"), pos, size, version, flags))
        pos += size
    return out


def flip_bit(data, bit):
    out = bytearray(data)
    out[bit // 8] ^= 0x80 >> (bit % 8)
    return bytes(out)


class TestRealBlf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.samples = helpers_real.load_samples()
        cls.log = helpers_real.PassLog("U-02")

    @classmethod
    def tearDownClass(cls):
        cls.log.flush()

    # ------------------------------------------------------------------------------------------
    def check_file(self, sample):
        data = sample.data
        # 1. chunk walk and tiling ------------------------------------------------------------
        walk = independent_blocks(data)
        self.assertEqual([b[0] for b in walk], ["_blf", "chdr", "mpvr", "_eof"])
        self.assertEqual(sum(b[2] for b in walk), len(data), "the blocks must tile the file exactly")
        parsed = blf.parse(data)
        self.assertEqual(parsed.blocks(), walk)
        self.assertEqual([b[2] for b in walk], [0x30, 0x2C0, 0x5028, 0x11])
        self.assertEqual(len(data), 21289)
        self.assertEqual((parsed.shape, parsed.trailer, parsed.warnings, parsed.dirty), ("plain4", b"", [], False))
        self.assertEqual((walk[0][3:], walk[1][3:], walk[3][3:]), ((1, 2), (10, 2), (1, 1)))
        chunk = parsed.find("mpvr")
        self.assertIsNotNone(chunk)
        self.assertIs(chunk.spec, blf.PAYLOAD_SPECS["mpvr"])
        self.assertIsNone(parsed.find("mvar"))
        # 2. passthrough ----------------------------------------------------------------------
        self.assertEqual(parsed.to_bytes(), data)
        # 3. forced rebuild -------------------------------------------------------------------
        rebuilt = parsed.render(force=True)
        self.assertEqual(rebuilt.data, data, "forced rebuild must equal the input byte for byte")
        self.assertEqual(rebuilt.issues, [], "a clean forced rebuild raises no warning")
        self.assertEqual(parsed.to_bytes(force=True), data)
        # 4. flavour detection ----------------------------------------------------------------
        self.assertEqual((chunk.flavour.length_endian, chunk.flavour.recipe), ("<", "salted_be32"))
        self.assertEqual(chunk.flavour, ("<", "salted_be32"), "SPEC 9.1 writes the result as this pair")
        self.assertEqual(hashing.detect_flavour(chunk.raw, chunk.spec), ("<", "salted_be32"))
        self.assertEqual(parsed.flavour, chunk.flavour)
        stored_length = struct.unpack_from("<I", data, MPVR_AT + 0x24)[0]
        self.assertEqual(chunk.stored_length, stored_length)
        self.assertEqual(chunk.length_endian, "<")
        candidates = hashing.candidates(chunk.raw, chunk.spec)
        self.assertEqual([(e, r, n) for e, r, n, m in candidates if m], [("<", "salted_be32", stored_length)])
        self.assertTrue(candidates and all(n == stored_length for _, _, n, _ in candidates))
        for endian, recipe, _, matches in candidates:
            if recipe == "plain_le32":
                self.assertFalse(matches, "plain_le32 must not match the verified mpvr recipe")
        # 5. recompute equals stored ----------------------------------------------------------
        stream = data[MPVR_AT + 0x28:MPVR_AT + 0x28 + stored_length]
        independent = hashlib.sha1(SALT34 + struct.pack(">I", stored_length) + stream).digest()
        self.assertEqual(data[MPVR_AT + 12:MPVR_AT + 32], independent)
        self.assertEqual(chunk.hash_stored, independent)
        self.assertEqual(hashing.compute(chunk.flavour, chunk.stream, stored_length), independent)
        # 6. a 1-bit flip breaks every candidate; restoring it matches again ------------------
        first_bit = (MPVR_AT + 0x28) * 8 + 5
        last_bit = (MPVR_AT + 0x28 + stored_length) * 8 - 1
        for bit in (first_bit, (first_bit + last_bit) // 2, last_bit):
            broken = blf.parse(flip_bit(data, bit))
            self.assertIsNone(broken.find("mpvr").flavour, "bit %d" % bit)
            self.assertFalse(any(m for _, _, _, m in hashing.candidates(broken.find("mpvr").raw, blf.PAYLOAD_SPECS["mpvr"])))
            restored = blf.parse(flip_bit(flip_bit(data, bit), bit))
            self.assertEqual(restored.find("mpvr").flavour, chunk.flavour)
        # 7. the _eof value and its byte order ------------------------------------------------
        self.assertEqual(data[EOF_AT:EOF_AT + 4], b"_eof")
        self.assertEqual(struct.unpack_from(">I", data, EOF_AT + 12)[0], EOF_AT)
        self.assertEqual((parsed.eof_endian, parsed.eof_value_ok), (">", True))
        # the other two derived fields of SPEC 2.11 (kept consistent in the real files)
        self.assertEqual(struct.unpack_from("<I", data, CHDR_AT + 0x14)[0], len(data))
        self.assertEqual(bitio.get_bits(chunk.stream, 72, 32), len(data))

    def test_every_real_file_passes_every_clause(self):
        for sample in self.samples:
            with self.subTest(file=sample.path):
                self.check_file(sample)
                self.log.add(sample)

    def test_there_are_eight_paths_and_five_distinct_contents(self):
        if helpers_real.require_samples():
            self.assertEqual(len(self.samples), helpers_real.EXPECTED_PATHS)
            self.assertEqual(len(helpers_real.distinct_samples(self.samples)), helpers_real.EXPECTED_DISTINCT)
        self.assertGreaterEqual(len(self.samples), 1)

    # ------------------------------------------------------------------------------------------
    def corruptions(self, data):
        """Variants of a file whose *derived* fields are wrong: ``[(name, bytes, expected_issue_codes)]``."""
        def patch(buf, offset, raw):
            buf = bytearray(buf)
            buf[offset:offset + len(raw)] = raw
            return bytes(buf)

        chdr_length = patch(data, CHDR_AT + 0x14, struct.pack("<I", 0x1234))
        eof_value = patch(data, EOF_AT + 12, struct.pack(">I", 0x01020304))
        embedded = bytearray(data)
        bitio.patch_bits(embedded, (MPVR_AT + 0x28) * 8 + 72, 32, 99)
        embedded = bytes(embedded)
        bad_hash = flip_bit(data, (MPVR_AT + 12) * 8 + 3)
        everything = patch(patch(patch(embedded, CHDR_AT + 0x14, struct.pack("<I", 7)), EOF_AT + 12, struct.pack(">I", 9)),
                           MPVR_AT + 12, bytes(range(20)))
        return [
            ("chdr file length", chdr_length, []),
            ("_eof value", eof_value, []),
            ("embedded file length", embedded, ["W_HASH_UNKNOWN"]),     # the stored hash no longer matches the stream
            ("stored hash", bad_hash, ["W_HASH_UNKNOWN"]),
            ("all four", everything, ["W_HASH_UNKNOWN"]),
        ]

    def test_forced_rebuild_recomputes_every_derived_field(self):
        for sample in self.samples:
            for name, mutated, codes in self.corruptions(sample.data):
                with self.subTest(file=sample.path, corruption=name):
                    self.assertNotEqual(mutated, sample.data)
                    parsed = blf.parse(mutated)
                    self.assertEqual(parsed.to_bytes(), mutated, "passthrough must not repair anything")
                    result = parsed.render(force=True)
                    self.assertEqual(result.data, sample.data, "forced rebuild must restore the original")
                    self.assertEqual([i.code for i in result.issues], codes)

    def test_unknown_hash_falls_back_to_salted_with_the_length_byte_order_of_the_file(self):
        sample = self.samples[0]
        mutated = flip_bit(sample.data, (MPVR_AT + 12) * 8)
        parsed = blf.parse(mutated)
        self.assertIsNone(parsed.flavour)
        self.assertEqual(parsed.find("mpvr").length_endian, "<")
        issue = parsed.render(force=True).issues[0]
        self.assertEqual((issue.code, issue.severity), ("W_HASH_UNKNOWN", "warning"))
        self.assertEqual(issue.message, "The template's SHA-1 matches no known recipe; the salted recipe was written. "
                                        "Whether MCC checks it is unknown.")

    def test_forced_rebuild_keeps_what_is_not_derivable(self):
        for sample in self.samples:
            data = bytearray(sample.data)
            length = struct.unpack_from("<I", data, MPVR_AT + 0x24)[0]
            data[MPVR_AT + 32:MPVR_AT + 36] = b"\xde\xad\xbe\xef"                 # the 4 unused bytes before the length
            tail_bit = (MPVR_AT + 0x28 + length) * 8 + 3                          # a stream bit after L: not hashed
            data[tail_bit // 8] |= 0x80 >> (tail_bit % 8)
            data = bytes(data)
            with self.subTest(file=sample.path):
                parsed = blf.parse(data)
                self.assertEqual(parsed.flavour.recipe, "salted_be32", "bits after L are outside the hashed region")
                self.assertEqual(parsed.to_bytes(force=True), data)
                self.assertEqual(parsed.find("mpvr").stored_length, length)

    def test_stream_length_override_changes_only_length_and_hash(self):
        sample = self.samples[0]
        parsed = blf.parse(sample.data)
        length = parsed.find("mpvr").stored_length
        out = parsed.to_bytes(force=True, stream_length={"mpvr": length + 1})
        self.assertEqual(struct.unpack_from("<I", out, MPVR_AT + 0x24)[0], length + 1)
        expected = hashlib.sha1(SALT34 + struct.pack(">I", length + 1) + out[MPVR_AT + 0x28:MPVR_AT + 0x28 + length + 1]).digest()
        self.assertEqual(out[MPVR_AT + 12:MPVR_AT + 32], expected)
        diff = [i for i in range(len(out)) if out[i] != sample.data[i]]
        self.assertTrue(all(MPVR_AT + 12 <= i < MPVR_AT + 32 or MPVR_AT + 0x24 <= i < MPVR_AT + 0x28 for i in diff),
                        "only the hash and the stored length may differ")

    def test_big_endian_stored_length_is_a_second_dimension(self):
        """A game variant written with a big-endian length (Firefight style) is detected as ('>', 'salted_be32')."""
        for sample in helpers_real.distinct_samples(self.samples):
            data = bytearray(sample.data)
            length = struct.unpack_from("<I", data, MPVR_AT + 0x24)[0]
            struct.pack_into(">I", data, MPVR_AT + 0x24, length)
            data = bytes(data)
            with self.subTest(file=sample.path):
                parsed = blf.parse(data)
                self.assertEqual((parsed.flavour.length_endian, parsed.flavour.recipe), (">", "salted_be32"))
                self.assertEqual(parsed.to_bytes(force=True), data)
                forced_le = parsed.to_bytes(force=True, flavour=hashing.HashFlavour("<", "salted_be32"))
                self.assertEqual(forced_le, sample.data, "forcing the little-endian flavour reproduces the real file")

    def test_a_trailer_after_the_eof_block_is_kept(self):
        sample = self.samples[0]
        data = sample.data + bytes(100)
        parsed = blf.parse(data)
        self.assertEqual((parsed.shape, len(parsed.trailer)), ("plain4", 100))
        self.assertEqual(parsed.to_bytes(), data)
        self.assertEqual(parsed.to_bytes(force=True), data)

    def test_damaged_real_files_are_refused_with_the_documented_sentences(self):
        data = self.samples[0].data
        with self.assertRaises(BlfFormatError) as ctx:
            blf.parse(data[:0x500])
        self.assertEqual(str(ctx.exception), "The file is damaged: block 'mpvr' at offset 0x2F0 claims 20520 bytes "
                                             "but only 528 remain.")
        with self.assertRaises(BlfFormatError) as ctx:
            blf.parse(data[:EOF_AT])
        self.assertEqual(str(ctx.exception), "The file has no end-of-file ('_eof') block.")
        with self.assertRaises(BlfFormatError) as ctx:
            blf.parse(b"xblf" + data[4:])
        self.assertEqual(str(ctx.exception), "This file is not a Halo BLF file (first block is 'xblf', expected '_blf').")


if __name__ == "__main__":
    unittest.main()
