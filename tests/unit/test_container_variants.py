"""U-10, read parts (SPEC 9.3, tier T2; the write parts belong to G5).

Container variants of a map variant seen through ``MapVariant``: ``_cmp`` and ``_fsm`` wrappers, version 32 with its
128 extra bits, the hash flavours (plain_le32, all-zero), little-endian stored length and ``_eof``, the unknown-block
shape that is readable but refuses modification, a trailer after ``_eof``, chunk versions. Unmodified saves are the
input; forced saves are the input (plain shapes) or the golden expanded file (``_cmp`` shapes, DEC-2.6).
"""
import os
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import helpers_g3 as g3  # noqa: E402

from mvarlib import api, errors, hashing  # noqa: E402
from mvarlib.model import MapVariant  # noqa: E402


class TestCmpWrapper(unittest.TestCase):
    def test_cmp_is_read_and_passes_through(self):
        for name, shape in (("cmp", "cmp4"), ("cmp_fsm", "cmp4+fsm")):
            with self.subTest(name):
                m = g3.model(name)
                self.assertEqual(m.shape, shape)
                self.assertIsNotNone(m.chunk.cmp)
                self.assertEqual(m.chunk.cmp.ctype, 0)
                self.assertEqual(m.chunk.cmp.usize, 0x7028)
                self.assertEqual(m.to_bytes(force=False), g3.data(name))
                self.assertEqual(m.to_bytes(force=True), g3.data(name + "_expanded"))
                self.assertEqual(m.occupied, 3)
                self.assertEqual(api.load_map_variant(g3.data(name)).info.shape, shape)

    def test_cmp_and_plain_decode_to_the_same_body(self):
        plain = g3.model("w1_minimal")
        for name in ("cmp", "cmp_fsm", "cmp_expanded", "cmp_fsm_expanded"):
            m = g3.model(name)
            with self.subTest(name):
                self.assertEqual([s.snapshot() for s in m.slots], [s.snapshot() for s in plain.slots])
                self.assertEqual(m.labels.texts(), plain.labels.texts())
                self.assertEqual(m.end_bit, plain.end_bit)

    def test_the_embedded_file_length_of_a_cmp_file_counts_the_cmp_file(self):
        m = g3.model("cmp")
        self.assertEqual(m.header.file_length, 29509)
        self.assertNotIn("W_FILE_LENGTH_MISMATCH", [w.code for w in m.warnings])          # judged against the real length
        self.assertEqual(g3.model("cmp_expanded").header.file_length, 29481)

    def test_modified_cmp_expands_and_restamps(self):
        m = g3.model("cmp").copy()
        m.slots[1].pos[0] = 526473
        rendered = m.render()
        self.assertEqual(rendered.data, g3.data("w1_E1"))
        self.assertEqual([i.code for i in rendered.issues], ["W_CMP_EXPANDED"])
        again = MapVariant.from_bytes(rendered.data)
        self.assertEqual(again.shape, "plain4")
        self.assertEqual(again.header.file_length, 29481)


class TestFsm(unittest.TestCase):
    def test_fsm_is_read_kept_or_dropped(self):
        m = g3.model("fsm")
        self.assertEqual(m.shape, "plain4+fsm")
        self.assertEqual(m.to_bytes(force=False), g3.data("fsm"))
        self.assertEqual(m.to_bytes(force=True), g3.data("fsm"))
        self.assertEqual(m.header.file_length, 29481)                  # the _fsm block is outside the length fields
        self.assertNotIn("W_FILE_LENGTH_MISMATCH", [w.code for w in m.warnings])
        dropped = m.copy()
        dropped.drop_fsm()
        self.assertEqual(dropped.to_bytes(force=False), g3.data("w1_minimal"))
        self.assertEqual(dropped.shape, "plain4")

    def test_dropping_fsm_from_a_template_without_one_changes_nothing(self):
        m = g3.model("w1_minimal").copy()
        m.drop_fsm()
        self.assertFalse(m.dirty)
        self.assertEqual(m.to_bytes(force=False), g3.data("w1_minimal"))


class TestVersion32(unittest.TestCase):
    def test_v32_has_a_128_bit_block(self):
        m = g3.model("v32")
        self.assertEqual((m.fixed.version, m.chunk.version), (32, 32))
        self.assertTrue(m.hypothesis.guid)
        self.assertEqual(m.guid.nbits, 128)
        base = g3.model("w1_minimal")
        self.assertEqual(m.end_bit, base.end_bit + 128)
        self.assertEqual(m.chunk.stored_length, 638)
        self.assertEqual(m.to_bytes(force=False), g3.data("v32"))
        self.assertEqual(m.to_bytes(force=True), g3.data("v32"))
        self.assertEqual([s.snapshot() for s in m.slots], [s.snapshot() for s in base.slots])
        self.assertFalse(m.guid_contradicts_version)
        self.assertEqual(api.load_map_variant(g3.data("v32")).info.version, 32)

    def test_the_guid_block_is_a_span(self):
        spans = dict((n, (a, b)) for n, a, b in g3.model("v32").spans())
        self.assertEqual(spans["guid"][1] - spans["guid"][0], 128)
        self.assertEqual(spans["slot_0"][0], spans["guid"][1])


class TestHashFlavours(unittest.TestCase):
    def test_flavours_of_the_fixtures(self):
        expected = {"w1_minimal": (">", "salted_be32"), "plain_le32": (">", "plain_le32"), "le_length": ("<", "salted_be32"),
                    "zero_hash": (">", "zero"), "eof_le": (">", "salted_be32"), "length_capacity": (">", "salted_be32")}
        for name, flavour in expected.items():
            with self.subTest(name):
                m = g3.model(name)
                self.assertEqual(m.flavour, flavour)
                self.assertEqual(api.load_map_variant(g3.data(name)).info.hash_flavour, hashing.flavour_label(hashing.HashFlavour(*flavour)))
                self.assertEqual(m.to_bytes(force=True), g3.data(name))

    def test_little_endian_stored_length(self):
        m = g3.model("le_length")
        self.assertEqual(m.chunk.length_endian, "<")
        self.assertEqual(m.chunk.stored_length, 622)
        self.assertEqual(g3.data("le_length")[0x2F0 + 32:0x2F0 + 36], struct.pack("<I", 622))

    def test_little_endian_eof(self):
        m = g3.model("eof_le")
        self.assertEqual(m.blf.eof_endian, "<")
        self.assertTrue(m.blf.eof_value_ok)
        self.assertEqual(m.to_bytes(force=True), g3.data("eof_le"))

    def test_all_zero_hash(self):
        m = g3.model("zero_hash")
        self.assertEqual(m.chunk.hash_stored, bytes(20))
        self.assertEqual(m.to_bytes(force=False), g3.data("zero_hash"))
        self.assertEqual(m.to_bytes(force=True), g3.data("zero_hash"))
        self.assertEqual(api.load_map_variant(g3.data("zero_hash")).info.hash_flavour, "zero/>")

    def test_stored_length_classes(self):
        self.assertEqual(g3.model("length_capacity").length_class, "capacity")
        self.assertEqual(g3.model("length_capacity").chunk.stored_length, 0x7000)
        self.assertEqual(g3.model("w1_minimal").length_class, "ceil_end")


class TestShapeOtherAndTrailer(unittest.TestCase):
    @staticmethod
    def with_unknown_block():
        """W1 with an unknown block between chdr and mvar (still tiles): readable, shape `other`."""
        data = g3.data("w1_minimal")
        extra = struct.pack(">4sIHH", b"xyzw", 12 + 4, 1, 1) + b"\x01\x02\x03\x04"
        out = data[:0x2F0] + extra + data[0x2F0:]
        # the _eof value is the offset of the _eof block: move it by len(extra) (the chdr length is left as it was)
        eof_at = 0x7318 + len(extra)
        return out[:eof_at + 12] + struct.pack(">I", eof_at) + out[eof_at + 16:]

    def test_unknown_block_is_readable_but_refuses_modification(self):
        data = self.with_unknown_block()
        m = MapVariant.from_bytes(data)
        self.assertEqual(m.shape, "other")
        self.assertEqual(m.occupied, 3)
        self.assertEqual(m.to_bytes(force=False), data)                                    # passthrough works
        edited = m.copy()
        edited.slots[1].pos[0] = 5
        with self.assertRaises(errors.BlfFormatError) as cm:
            edited.to_bytes(force=False)
        self.assertIn("block layout", str(cm.exception))
        self.assertIn("cannot be modified safely", str(cm.exception))
        with self.assertRaises(errors.BlfFormatError):
            m.to_bytes(force=True)

    def test_trailer_is_kept_and_reported_on_modification(self):
        m = g3.model("trailer")
        self.assertEqual(m.shape, "plain4")                                     # see G1 note S1 and the U-07 comment
        self.assertEqual(len(m.blf.trailer), 512)
        edited = m.copy()
        edited.slots[1].pos[0] = 526473
        rendered = edited.render()
        self.assertIn("W_TRAILER_KEPT", [i.code for i in rendered.issues])
        self.assertEqual(rendered.data[:29481], g3.data("w1_E1"))
        self.assertEqual(rendered.data[29481:], bytes(512))
        self.assertEqual(m.render().issues, [])                                 # not for an unmodified save

    def test_long_eof_is_an_unknown_shape(self):
        data = g3.data("w1_minimal")
        longer = data[:-17] + struct.pack(">4sIHH", b"_eof", 0x105, 1, 1) + struct.pack(">I", 0x7318) + bytes(1 + 256)
        m = MapVariant.from_bytes(longer)
        self.assertEqual(m.shape, "other")
        self.assertEqual(m.to_bytes(force=False), longer)


class TestChunkVersionPolicy(unittest.TestCase):
    def test_refused_and_unexpected(self):
        for name in ("chunk_version_13", "chunk_version_50"):
            with self.assertRaises(errors.UnsupportedVariantError):
                api.load_map_variant(g3.data(name))
        warn = bytearray(g3.data("w1_minimal"))
        warn[0x2F0 + 8:0x2F0 + 10] = struct.pack(">H", 40)
        res = api.load_map_variant(bytes(warn))
        self.assertIn("W_CHUNK_VERSION_UNEXPECTED", [w.code for w in res.warnings])


class TestSpansAndBlocks(unittest.TestCase):
    def test_spans_tile_the_stream(self):
        for name in ("w1_minimal", "v32", "extremes", "labels_compressed", "hdr_campaign"):
            m = g3.model(name)
            with self.subTest(name):
                spans = m.spans()
                pos = 0
                for span_name, a, b in spans:
                    self.assertEqual(a, pos, span_name)           # every part starts where the previous one ended
                    pos = b
                self.assertEqual(pos, 0x7000 * 8)
                self.assertEqual(sum(1 for x in spans if x[0].startswith("body.")), 15)      # 7 scalars, 6 bounds, 2 budget words
                fine = m.spans(fields=True)
                self.assertGreater(len(fine), len(spans))
                for slot in m.present_slots():
                    sub = [x for x in fine if x[0].startswith("slot_%d." % slot.index)]
                    whole = [x for x in fine if x[0] == "slot_%d" % slot.index][0]
                    self.assertEqual(sub[0][1], whole[1])
                    self.assertEqual(sub[-1][2], whole[2])
                    for a, b in zip(sub, sub[1:]):
                        self.assertEqual(a[2], b[1])
                self.assertEqual(m.locate_bit(0), "header")
                self.assertTrue(m.locate_bit(m.end_bit - 1).startswith("quota_"))
                self.assertEqual(m.locate_bit(m.end_bit), "tail")


if __name__ == "__main__":
    unittest.main()
