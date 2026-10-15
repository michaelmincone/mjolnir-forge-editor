"""U-06 (SPEC 9.3, 2.7, 6.3): hash recipes, flavour detection and write-back.

* the five test vectors of SPEC 2.7 (``data = 00..09``, ``L = 10``) and the ``zero`` recipe;
* detection on the reference fixture W1 in both flavours (salted and plain) against the golden numbers
  of Appendix C.2, built by the spec's own reference script;
* both stored-length byte orders, for every recipe (the two are independent dimensions, SPEC 2.7);
  the claim that the two readings are never both valid unless the four bytes are zero, checked for
  every length up to the capacity;
* ``L = 0`` handling: four zero bytes are tried as the lengths 0 and 0x7000 and kept as zeros;
* the ``zero`` flavour: detection, write-back as zeros, forcing a recipe (``hash_policy``);
* a hash that matches nothing: salted fallback with the file's length byte order and ``W_HASH_UNKNOWN``.

Most of it is pure (no sample files); it uses a tiny independent builder (``helpers_container``).
"""
import dataclasses
import hashlib
import os
import random
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for _path in (HERE, os.path.join(REPO, "Addon")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import helpers_container as hc  # noqa: E402
from mvarlib import blf, hashing  # noqa: E402
from mvarlib.errors import BlfFormatError, CapacityError, HashError, InternalError  # noqa: E402
from mvarlib.hashing import HashFlavour  # noqa: E402

MVAR = blf.PAYLOAD_SPECS["mvar"]
MPVR = blf.PAYLOAD_SPECS["mpvr"]
MVAR_AT = 0x30 + 0x2C0                       # file offset of the mvar block in a plain file


def flip(data, bit):
    out = bytearray(data)
    out[bit // 8] ^= 0x80 >> (bit % 8)
    return bytes(out)


class TestVectors(unittest.TestCase):
    DATA = bytes(range(10))
    VECTORS = {
        "salted_be32": "6f0d524ee1491d003958ab5065fa74db67f4cc7e",
        "plain_le32": "908ea657bfe5b911f8752827b0c8e5ad9fef06b3",
        "salted_le32": "134da971af17127d0854f27a1a4dd49b2aa9a671",
        "plain_be32": "6df6c8eef85b2a16452be2f9adf695fa478b61c2",
        "data_only": "494179714a6cd627239dfededf2de9ef994caf03",
    }

    def test_the_five_vectors_of_section_2_7(self):
        for recipe, expected in self.VECTORS.items():
            for endian in (">", "<"):                   # the stored-length byte order does not change the digest
                self.assertEqual(hashing.compute(HashFlavour(endian, recipe), self.DATA, 10).hex(), expected, recipe)
            self.assertEqual(hashing.digest(recipe, self.DATA, 10).hex(), expected)

    def test_recipe_inputs(self):
        salt = hashing.SALT34
        self.assertEqual(len(salt), 34)
        self.assertEqual(salt.hex().upper(), "EDD43009666D5C4A5C3657FAB40E022F535AC6C9EE471F01F1A44756B7714F1C36EC")
        data = b"abc"
        self.assertEqual(hashing.recipe_input("plain_le32", data, 3), b"\x03\x00\x00\x00abc")
        self.assertEqual(hashing.recipe_input("plain_be32", data, 3), b"\x00\x00\x00\x03abc")
        self.assertEqual(hashing.recipe_input("salted_be32", data, 3), salt + b"\x00\x00\x00\x03abc")
        self.assertEqual(hashing.recipe_input("salted_le32", data, 3), salt + b"\x03\x00\x00\x00abc")
        self.assertEqual(hashing.recipe_input("data_only", data, 3), b"abc")
        with self.assertRaises(HashError):
            hashing.recipe_input("zero", data, 3)

    def test_zero_recipe_is_twenty_zero_bytes(self):
        self.assertEqual(hashing.compute(HashFlavour(">", "zero"), self.DATA, 10), bytes(20))
        self.assertEqual(hashing.compute(HashFlavour("<", "zero"), b"", 0), bytes(20))

    def test_compute_hashes_only_the_first_L_bytes(self):
        salted = HashFlavour(">", "salted_be32")
        self.assertEqual(hashing.compute(salted, self.DATA + b"junk", 10).hex(), self.VECTORS["salted_be32"])
        self.assertNotEqual(hashing.compute(salted, self.DATA, 9), hashing.compute(salted, self.DATA, 10))
        with self.assertRaises(HashError):
            hashing.compute(salted, self.DATA, 11)
        for bad in (-1, 1.5, None):
            with self.assertRaises(HashError):
                hashing.compute(salted, self.DATA, bad)
        with self.assertRaises(HashError):
            hashing.compute(("<", "plain_le32"), self.DATA, 10)

    def test_flavour_also_behaves_like_the_pair_of_the_spec(self):
        """SPEC 9.1 writes the detection result as ('<', 'salted_be32'); the class equals and hashes like that pair."""
        flavour = HashFlavour("<", "salted_be32")
        self.assertEqual(flavour, ("<", "salted_be32"))
        self.assertEqual(("<", "salted_be32"), flavour)
        self.assertNotEqual(flavour, (">", "salted_be32"))
        self.assertNotEqual(flavour, ("<", "plain_le32"))
        self.assertNotEqual(flavour, ["<", "salted_be32"])
        self.assertNotEqual(flavour, "<salted_be32")
        self.assertEqual(hash(flavour), hash(("<", "salted_be32")))
        self.assertEqual({("<", "salted_be32"): 1}[flavour], 1)
        endian, recipe = flavour
        self.assertEqual((endian, recipe, len(flavour), flavour[0], flavour[1]), ("<", "salted_be32", 2, "<", "salted_be32"))
        self.assertEqual(dataclasses.replace(flavour, recipe="zero"), ("<", "zero"))
        self.assertEqual(repr(flavour), "HashFlavour(length_endian='<', recipe='salted_be32')")

    def test_flavour_value_object(self):
        flavour = HashFlavour(">", "salted_be32")
        self.assertEqual(flavour, HashFlavour(">", "salted_be32"))
        self.assertNotEqual(flavour, HashFlavour("<", "salted_be32"))
        self.assertEqual(len(set([flavour, HashFlavour(">", "salted_be32")])), 1)
        with self.assertRaises(Exception):
            flavour.recipe = "plain_le32"                                # frozen
        for endian, recipe in (("big", "salted_be32"), (">", "sha256"), ("", "zero")):
            with self.assertRaises(HashError, msg=(endian, recipe)):
                HashFlavour(endian, recipe)
        self.assertEqual(hashing.flavour_label(flavour), "salted_be32/>")
        self.assertEqual(hashing.flavour_label(HashFlavour("<", "zero")), "zero/<")
        self.assertEqual(hashing.flavour_label(None), "unknown")
        self.assertEqual(hashing.fallback_flavour("<"), HashFlavour("<", "salted_be32"))
        self.assertEqual(hashing.fallback_flavour(None), HashFlavour(">", "salted_be32"))
        self.assertEqual(hashing.encode_length(0x0102, ">"), b"\x00\x00\x01\x02")
        self.assertEqual(hashing.encode_length(0x0102, "<"), b"\x02\x01\x00\x00")
        with self.assertRaises(HashError):
            hashing.encode_length(-1, ">")


class TestStoredLengthReadings(unittest.TestCase):
    @staticmethod
    def chunk(raw4, spec=MVAR):
        body = bytearray(spec.chunk_size)
        body[spec.length_off:spec.length_off + 4] = raw4
        return bytes(body)

    def test_exactly_one_reading_is_valid_for_every_length(self):
        """SPEC 2.7: the two readings cannot both be valid unless the four bytes are zero (checked for 1..0x7000)."""
        for value in range(1, MVAR.stream_capacity + 1):
            for endian in (">", "<"):
                readings = hashing.length_readings(self.chunk(struct.pack(endian + "I", value)), MVAR)
                self.assertEqual(readings, [(endian, value)], (value, endian))

    def test_zero_bytes_are_tried_as_0_and_as_the_capacity(self):
        self.assertEqual(hashing.length_readings(self.chunk(bytes(4)), MVAR), [(">", 0), (">", 0x7000)])
        self.assertEqual(hashing.length_readings(self.chunk(bytes(4), MPVR), MPVR), [("<", 0), ("<", 0x5000)])

    def test_bytes_that_are_too_big_in_both_orders_have_no_reading(self):
        for raw in (b"\x00\x00\x70\x01", b"\x01\x70\x00\x00", b"\x00\x00\x80\x00", b"\x00\x80\x00\x00",
                    b"\x12\x34\x56\x78", b"\xff\xff\xff\xff", b"\x01\x00\x00\x01", b"\x00\x01\x00\x01"):
            self.assertEqual(hashing.length_readings(self.chunk(raw), MVAR), [], raw.hex())

    def test_bytes_that_are_too_big_in_one_order_are_read_in_the_other(self):
        """A big-endian 65536 (00 01 00 00) is a little-endian 256: only the valid reading counts."""
        self.assertEqual(hashing.length_readings(self.chunk(b"\x00\x01\x00\x00"), MVAR), [("<", 256)])
        self.assertEqual(hashing.length_readings(self.chunk(b"\x00\x00\x01\x00"), MVAR), [(">", 256)])

    def test_the_layouts_own_byte_order_is_listed_first_when_it_is_valid(self):
        self.assertEqual(hashing.length_readings(self.chunk(struct.pack("<I", 4648), MPVR), MPVR), [("<", 4648)])
        self.assertEqual(hashing.length_readings(self.chunk(struct.pack(">I", 4648), MPVR), MPVR), [(">", 4648)])

    def test_short_block_is_a_hash_error(self):
        with self.assertRaises(HashError):
            hashing.length_readings(b"\x00" * 20, MVAR)
        with self.assertRaises(HashError):
            hashing.analyse(b"\x00" * 100, MVAR)


class TestDetectionOnSyntheticFiles(unittest.TestCase):
    def build(self, seed=3, used=900, recipe="salted_be32", length_endian=">", **kwargs):
        stream = hc.random_stream(seed, used)
        data, _ = hc.make_file(stream, used, recipe, length_endian, **kwargs)
        return data

    def analysis(self, data):
        chunk = data[MVAR_AT:MVAR_AT + 0x7028]
        return hashing.analyse(chunk, MVAR)

    def test_every_recipe_in_both_length_byte_orders(self):
        for recipe in hc.RECIPE_NAMES:
            for endian in (">", "<"):
                data = self.build(recipe=recipe, length_endian=endian)
                with self.subTest(recipe=recipe, endian=endian):
                    chunk = data[MVAR_AT:MVAR_AT + 0x7028]
                    self.assertEqual(hashing.detect_flavour(chunk, MVAR), HashFlavour(endian, recipe))
                    matches = [(e, r, n) for e, r, n, m in hashing.candidates(chunk, MVAR) if m]
                    self.assertEqual(matches, [(endian, recipe, 900)], "exactly one candidate matches")
                    result = self.analysis(data)
                    self.assertEqual((result.length_endian, result.stored_length, result.hash_length, result.zero_length),
                                     (endian, 900, 900, False))
                    parsed = blf.parse(data)
                    self.assertEqual(parsed.flavour, HashFlavour(endian, recipe))
                    self.assertEqual(parsed.to_bytes(force=True), data, "forced rebuild reproduces every flavour")
                    self.assertEqual(parsed.render(force=True).issues, [])

    def test_candidate_rows(self):
        data = self.build(recipe="plain_le32")
        rows = hashing.candidates(data[MVAR_AT:MVAR_AT + 0x7028], MVAR)
        self.assertEqual([(e, r, n) for e, r, n, _ in rows],
                         [(">", name, 900) for name in hashing.RECIPES] + [(">", "zero", 900)])
        self.assertEqual([m for _, _, _, m in rows], [True, False, False, False, False, False])

    def test_flipping_a_bit_inside_L_breaks_every_candidate_and_outside_L_does_not(self):
        rng = random.Random(0xB17)
        for _ in range(40):
            recipe = rng.choice(hc.RECIPE_NAMES)
            endian = rng.choice((">", "<"))
            used = rng.randint(1, 3000)
            data = self.build(seed=rng.randint(0, 99), used=used, recipe=recipe, length_endian=endian)
            stream_bit = (MVAR_AT + 36) * 8
            inside = flip(data, stream_bit + rng.randrange(used * 8))
            outside = flip(data, stream_bit + used * 8 + rng.randrange(0x7000 * 8 - used * 8))
            for name, mutated, detected in (("inside", inside, False), ("outside", outside, True)):
                chunk = mutated[MVAR_AT:MVAR_AT + 0x7028]
                self.assertEqual(hashing.detect_flavour(chunk, MVAR) is not None, detected, (name, recipe, endian, used))
                if not detected:
                    self.assertFalse(any(m for _, _, _, m in hashing.candidates(chunk, MVAR)))

    def test_changing_the_stored_length_breaks_the_hash(self):
        data = bytearray(self.build(used=900))
        struct.pack_into(">I", data, MVAR_AT + 32, 901)
        self.assertIsNone(hashing.detect_flavour(bytes(data[MVAR_AT:MVAR_AT + 0x7028]), MVAR))

    def test_unknown_hash(self):
        data = self.build(hash_bytes=bytes(range(1, 21)))
        result = self.analysis(data)
        self.assertIsNone(result.flavour)
        self.assertEqual((result.length_endian, result.stored_length, result.hash_length), (">", 900, 900))
        self.assertFalse(any(m for _, _, _, m in result.candidates))
        self.assertEqual(blf.parse(data).flavour, None)

    def test_candidate_order_decides_when_two_recipes_give_the_same_digest(self):
        """Only L == 0 makes LE32 and BE32 identical: the first recipe in the order of SPEC 2.7 is reported."""
        self.assertEqual(hashing.digest("plain_le32", b"", 0), hashing.digest("plain_be32", b"", 0))
        self.assertEqual(hashing.digest("salted_be32", b"", 0), hashing.digest("salted_le32", b"", 0))
        stream = hc.random_stream(5, 300)
        for recipe, reported in (("plain_be32", "plain_le32"), ("salted_le32", "salted_be32"),
                                 ("plain_le32", "plain_le32"), ("salted_be32", "salted_be32")):
            data, _ = hc.make_file(stream, 0, recipe, ">", hashed_length=0)
            with self.subTest(recipe=recipe):
                self.assertEqual(self.analysis(data).flavour, HashFlavour(">", reported))


class TestLengthZeroHandling(unittest.TestCase):
    """Four zero bytes: the effective length is 0 or 0x7000 (SPEC 2.7, 2.12 class ``zero``) and is written back as zeros."""

    def file_with(self, hashed_length, recipe="salted_be32", **kwargs):
        stream = hc.random_stream(11, 1234)
        data, _ = hc.make_file(stream, 0, recipe, ">", hashed_length=hashed_length, **kwargs)
        return data, stream

    def test_hash_over_the_capacity(self):
        data, _ = self.file_with(0x7000)
        parsed = blf.parse(data)
        chunk = parsed.find("mvar")
        self.assertTrue(chunk.zero_length)
        self.assertEqual((chunk.stored_length, chunk.length_raw, chunk.length_endian), (0, bytes(4), ">"))
        self.assertEqual(chunk.analysis.hash_length, 0x7000)
        self.assertEqual(chunk.flavour, HashFlavour(">", "salted_be32"))
        self.assertEqual(parsed.to_bytes(force=True), data)
        self.assertEqual(data[MVAR_AT + 32:MVAR_AT + 36], bytes(4))

    def test_hash_over_nothing(self):
        data, _ = self.file_with(0)
        chunk = blf.parse(data).find("mvar")
        self.assertEqual((chunk.zero_length, chunk.analysis.hash_length), (True, 0))
        self.assertEqual(chunk.flavour, HashFlavour(">", "salted_be32"))
        self.assertEqual(blf.parse(data).to_bytes(force=True), data)

    def test_the_two_effective_lengths_are_both_listed(self):
        data, _ = self.file_with(0x7000, recipe="plain_le32")
        rows = hashing.candidates(data[MVAR_AT:MVAR_AT + 0x7028], MVAR)
        self.assertEqual(sorted(set(n for _, _, n, _ in rows)), [0, 0x7000])
        self.assertEqual([(r, n) for _, r, n, m in rows if m], [("plain_le32", 0x7000)])

    def test_zero_length_and_zero_hash(self):
        data, _ = self.file_with(0x7000, hash_bytes=bytes(20))
        chunk = blf.parse(data).find("mvar")
        self.assertEqual(chunk.flavour, HashFlavour(">", "zero"))
        self.assertTrue(chunk.zero_length)
        self.assertEqual(blf.parse(data).to_bytes(force=True), data)

    def test_the_zero_class_survives_a_new_stream(self):
        """Patched mode with ``stream_length`` 0 keeps the four zero bytes and hashes the whole capacity."""
        data, _ = self.file_with(0x7000)
        parsed = blf.parse(data)
        new_stream = hc.random_stream(77, 2000)
        parsed.find("mvar").set_stream(new_stream, 0)
        out = parsed.to_bytes()
        self.assertEqual(out[MVAR_AT + 32:MVAR_AT + 36], bytes(4))
        self.assertEqual(out[MVAR_AT + 12:MVAR_AT + 32], hc.digest("salted_be32", new_stream, 0x7000),
                         "patched mode does not restamp the embedded length when the file length is unchanged")
        self.assertEqual(blf.parse(out).flavour, HashFlavour(">", "salted_be32"))
        # an explicit non-zero L leaves the class
        parsed = blf.parse(data)
        parsed.find("mvar").set_stream(new_stream, 2000)
        out = parsed.to_bytes()
        self.assertEqual(out[MVAR_AT + 32:MVAR_AT + 36], struct.pack(">I", 2000))
        self.assertEqual(out[MVAR_AT + 12:MVAR_AT + 32], hc.digest("salted_be32", new_stream, 2000))

    def test_asking_for_the_zero_class_on_an_ordinary_template_hashes_the_capacity(self):
        """``stream_length={'mvar': 0}`` on a file with L = 600: four zero bytes, hash over the whole 0x7000 stream."""
        stream = hc.random_stream(13, 600)
        data, _ = hc.make_file(stream, 600)
        parsed = blf.parse(data)
        out = parsed.to_bytes(force=True, stream_length={"mvar": 0})
        self.assertEqual(out[MVAR_AT + 32:MVAR_AT + 36], bytes(4))
        self.assertEqual(out[MVAR_AT + 12:MVAR_AT + 32], hc.digest("salted_be32", hc.put_embedded_length(stream, len(data)), 0x7000))
        again = blf.parse(out)
        self.assertEqual((again.flavour, again.find("mvar").zero_length), (HashFlavour(">", "salted_be32"), True))
        self.assertEqual(again.to_bytes(force=True), out)

    def test_invalid_length_bytes_refuse_to_parse(self):
        for raw in (struct.pack(">I", 0x7001), b"\x00\x00\x80\x00", b"\x12\x34\x56\x78", b"\xff\xff\xff\xff"):
            data = bytearray(hc.plain_file())
            data[MVAR_AT + 32:MVAR_AT + 36] = raw
            with self.assertRaises(BlfFormatError) as ctx:
                blf.parse(bytes(data))
            self.assertEqual(str(ctx.exception), "The stored stream length bytes %s are not a valid length (maximum 0x7000)."
                             % " ".join("%02X" % b for b in raw))


class TestZeroFlavourAndForcing(unittest.TestCase):
    def setUp(self):
        self.stream = hc.random_stream(21, 700)
        self.salted, _ = hc.make_file(self.stream, 700)
        self.zero, _ = hc.make_file(self.stream, 700, hash_bytes=bytes(20))

    def test_zero_flavour_is_detected_and_reproduced_as_zeros(self):
        parsed = blf.parse(self.zero)
        self.assertEqual(parsed.flavour, HashFlavour(">", "zero"))
        rows = hashing.candidates(self.zero[MVAR_AT:MVAR_AT + 0x7028], MVAR)
        self.assertEqual(rows[-1], (">", "zero", 700, True))
        self.assertFalse(any(m for _, r, _, m in rows if r != "zero"))
        result = parsed.render(force=True)
        self.assertEqual(result.data, self.zero)
        self.assertEqual([(i.code, i.severity) for i in result.issues], [("I_HASH_ZERO", "info")])
        self.assertEqual(result.issues[0].message,
                         "The template carries no SHA-1 (20 zero bytes, which KSoft.Blam documents for MCC-written "
                         "game variants); none was written.")

    def test_zero_flavour_survives_a_new_stream(self):
        parsed = blf.parse(self.zero)
        parsed.find("mvar").set_stream(hc.random_stream(22, 800), 800)
        out = parsed.to_bytes()
        self.assertEqual(out[MVAR_AT + 12:MVAR_AT + 32], bytes(20))
        self.assertEqual(out[MVAR_AT + 32:MVAR_AT + 36], struct.pack(">I", 800))

    def test_a_passthrough_save_has_no_hash_issue(self):
        parsed = blf.parse(self.zero)
        self.assertEqual(parsed.render().issues, [])
        self.assertEqual(parsed.render().data, self.zero)

    def test_forcing_a_recipe_regardless_of_the_template(self):
        """``hash_policy``: SALTED_BE32 / PLAIN_LE32 replace the template's recipe; no issue is raised for it."""
        for template in (self.salted, self.zero):
            parsed = blf.parse(template)
            for recipe in hc.RECIPE_NAMES + ("zero",):
                with self.subTest(recipe=recipe, template=template is self.zero):
                    result = parsed.render(force=True, flavour=HashFlavour(">", recipe))
                    self.assertEqual(result.issues, [])
                    expected, _ = hc.make_file(self.stream, 700, recipe)
                    self.assertEqual(result.data, expected)
                    self.assertEqual(blf.parse(result.data).flavour, HashFlavour(">", recipe))

    def test_forcing_a_length_byte_order(self):
        parsed = blf.parse(self.salted)
        out = parsed.to_bytes(force=True, flavour=HashFlavour("<", "salted_be32"))
        expected, _ = hc.make_file(self.stream, 700, "salted_be32", "<")
        self.assertEqual(out, expected)
        chunk = blf.parse(out).find("mvar")
        self.assertEqual((chunk.length_endian, chunk.stored_length), ("<", 700))

    def test_a_forced_flavour_does_not_turn_a_clean_save_into_a_rewrite(self):
        parsed = blf.parse(self.salted)
        self.assertIs(parsed.to_bytes(flavour=HashFlavour(">", "plain_le32")), parsed.original)

    def test_unknown_hash_is_rewritten_as_salted_with_a_warning(self):
        for endian in (">", "<"):
            stream = hc.random_stream(23, 650)
            data, _ = hc.make_file(stream, 650, "salted_be32", endian, hash_bytes=bytes(range(1, 21)))
            parsed = blf.parse(data)
            self.assertIsNone(parsed.flavour)
            result = parsed.render(force=True)
            expected, _ = hc.make_file(stream, 650, "salted_be32", endian)
            self.assertEqual(result.data, expected, "salted recipe with the file's own length byte order")
            self.assertEqual([i.code for i in result.issues], ["W_HASH_UNKNOWN"])
            self.assertEqual(blf.parse(result.data).flavour, HashFlavour(endian, "salted_be32"))

    def test_unknown_hash_with_zero_length_uses_the_layouts_byte_order(self):
        stream = hc.random_stream(24, 650)
        data, _ = hc.make_file(stream, 0, "salted_be32", ">", hash_bytes=bytes(range(1, 21)))
        result = blf.parse(data).render(force=True)
        self.assertEqual([i.code for i in result.issues], ["W_HASH_UNKNOWN"])
        self.assertEqual(result.data[MVAR_AT + 32:MVAR_AT + 36], bytes(4), "the zero length class is kept")
        self.assertEqual(result.data[MVAR_AT + 12:MVAR_AT + 32], hc.digest("salted_be32", hc.put_embedded_length(stream, len(data)), 0x7000))


class TestReferenceFixtureW1(unittest.TestCase):
    """The spec's reference W1 (Appendix C), built by ``docs/mvar/reference/w1_build.py``, through the container."""

    GOLDEN = {
        "salted_be32": ("a6183d5f5872d38b6dda0d476ea7d8c8c40641ad",
                        "902d952fdce8b5830e53e96e0ad45926554e1a9e617f753f39bb58a5fd2344e4"),
        "plain_le32": ("cb6d51c253b9d53b82b4faf653c3adc8e1a7afda",
                       "9e11095033b8356e7f772a2f615ceb77ba7e49b18c047f3826ac1da7a62ddbc5"),
    }

    @classmethod
    def setUpClass(cls):
        builder = hc.load_w1_builder()
        cls.files = {}
        for name in cls.GOLDEN:
            data, _, length, stored = builder.build_file(name)
            cls.files[name] = (data, length, stored)

    def test_the_reference_script_gives_the_golden_numbers(self):
        for name, (stored_hex, sha256) in self.GOLDEN.items():
            data, length, stored = self.files[name]
            self.assertEqual((len(data), length, stored.hex(), hashlib.sha256(data).hexdigest()),
                             (29481, 622, stored_hex, sha256))

    def test_detection_on_w1(self):
        for name in self.GOLDEN:
            data, length, _ = self.files[name]
            with self.subTest(flavour=name):
                parsed = blf.parse(data)
                self.assertEqual((parsed.shape, parsed.eof_endian, parsed.eof_value_ok), ("plain4", ">", True))
                chunk = parsed.find("mvar")
                self.assertEqual(chunk.flavour, HashFlavour(">", name))
                self.assertEqual((chunk.version, chunk.flags, chunk.stored_length, chunk.length_endian), (31, 1, 622, ">"))
                rows = hashing.candidates(chunk.raw, chunk.spec)
                self.assertEqual([(e, r, n) for e, r, n, m in rows if m], [(">", name, 622)])
                self.assertEqual(parsed.warnings, [])

    def test_plain_le32_keeps_the_big_endian_stored_length(self):
        """SPEC C.2: "plain_le32, stored length still BE": the hash input is LE32(L) while the field is big-endian."""
        data = self.files["plain_le32"][0]
        self.assertEqual(data[MVAR_AT + 32:MVAR_AT + 36], struct.pack(">I", 622))
        self.assertEqual(blf.parse(data).find("mvar").flavour, HashFlavour(">", "plain_le32"))

    def test_forced_rebuild_is_the_identity_on_w1(self):
        for name in self.GOLDEN:
            data = self.files[name][0]
            parsed = blf.parse(data)
            self.assertEqual(parsed.to_bytes(), data)
            self.assertEqual(parsed.to_bytes(force=True), data)
            self.assertEqual(parsed.to_bytes(force=True, stream_length={"mvar": 622}), data)

    def test_forcing_the_other_recipe_gives_the_other_golden_file(self):
        salted, plain = self.files["salted_be32"][0], self.files["plain_le32"][0]
        self.assertEqual(blf.parse(salted).to_bytes(force=True, flavour=HashFlavour(">", "plain_le32")), plain)
        self.assertEqual(blf.parse(plain).to_bytes(force=True, flavour=HashFlavour(">", "salted_be32")), salted)

    def test_embedded_length_at_bit_4_is_repaired_without_touching_its_neighbours(self):
        """Corrupt the 32-bit file length at bit 4 of the mvar stream; a forced rebuild restores it and the nibble beside it."""
        data = bytearray(self.files["salted_be32"][0])
        stream_at = MVAR_AT + 36
        self.assertEqual(data[stream_at] >> 4, 6)
        low = data[stream_at] & 0x0F
        self.assertEqual(hc.get_embedded_length(bytes(data[stream_at:stream_at + 8])), 0x7329)
        broken = bytearray(data)
        broken[stream_at:stream_at + 5] = hc.put_embedded_length(bytes(data[stream_at:stream_at + 5]), 0x0BADF00D)[:5]
        self.assertNotEqual(bytes(broken), bytes(data))
        self.assertEqual(broken[stream_at] >> 4, 6)
        self.assertEqual(hc.get_embedded_length(bytes(broken[stream_at:stream_at + 8])), 0x0BADF00D)
        repaired = blf.parse(bytes(broken)).render(force=True)
        self.assertEqual(repaired.data, bytes(data))
        self.assertEqual(repaired.data[stream_at] & 0x0F, low)
        self.assertEqual([i.code for i in repaired.issues], ["W_HASH_UNKNOWN"])

    def test_patched_mode_changes_only_stream_length_and_hash(self):
        data = self.files["salted_be32"][0]
        parsed = blf.parse(data)
        chunk = parsed.find("mvar")
        new_stream = bytearray(chunk.stream)
        new_stream[100] ^= 0x10
        chunk.set_stream(bytes(new_stream), 622)
        self.assertTrue(parsed.dirty)
        out = parsed.to_bytes()
        self.assertEqual(len(out), len(data))
        changed = [i for i in range(len(data)) if data[i] != out[i]]
        self.assertTrue(all(MVAR_AT + 12 <= i < MVAR_AT + 32 or i == MVAR_AT + 36 + 100 for i in changed), changed)
        self.assertEqual(out[MVAR_AT + 12:MVAR_AT + 32], hc.digest("salted_be32", bytes(new_stream), 622))
        self.assertEqual(blf.parse(out).flavour, HashFlavour(">", "salted_be32"))
        # the model is still dirty after serialising; the original object is untouched
        self.assertEqual(parsed.original, data)

    def test_set_stream_validation(self):
        parsed = blf.parse(self.files["salted_be32"][0])
        chunk = parsed.find("mvar")
        with self.assertRaises(CapacityError):
            chunk.set_stream(bytes(0x7001))
        with self.assertRaises(InternalError):
            chunk.set_stream(bytes(10), 0x7001)
        with self.assertRaises(InternalError):
            parsed.find("chdr").set_stream(bytes(10))
        with self.assertRaises(InternalError):
            parsed.to_bytes(force=True, stream_length={"mpvr": 10})
        self.assertFalse(parsed.dirty, "a refused change must not mark the file dirty")


if __name__ == "__main__":
    unittest.main()
