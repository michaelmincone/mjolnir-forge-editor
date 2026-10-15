"""U-03 (SPEC 9.3, tier T1): the shared UGC header codec and the ``chdr`` byte form.

* Real files: decode the header at payload bit 68 (after the 4-bit engine type and the two u32
  versions of an ``mpvr``); header lengths 1,535 / 1,183 / 2,287 / 2,271 / 2,575 bits; re-encode from
  the decoded fields at bit 68 **and** at bit 0 (where an ``mvar`` starts it) and get identical bits;
  the same bits placed at any other alignment decode to the same fields; a longer or shorter title,
  description or author name shifts the rest of the stream consistently; ``chdr`` parse/build is
  byte-exact and agrees with the bit-form header.
* Synthetic headers (no samples needed): the W1 reference header (header end 1,255) and the five
  header variants of Appendix C.4 (hopper, campaign, firefight, long text, minimal text) reproduce the
  header ends, end bits, ``L`` and stored SHA-1 values of the spec, so the widths of the conditional
  tails and of the variable-length text are pinned.
* ``chdr`` fields on a synthetic block whose two author records differ (the real files carry the same
  author twice, which cannot tell the records apart), every field that ``compare_chdr_header`` checks
  reported on its own, and ``copy`` / ``deepcopy`` / ``pickle`` of a decoded ``UgcHeader`` (its ``raw``
  is a ``BitString``; SPEC 6.3 deep-copies the model).
"""
import copy
import dataclasses
import hashlib
import os
import pickle
import random
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for _path in (HERE, os.path.join(REPO, "Addon")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import helpers_container  # noqa: E402
import helpers_real  # noqa: E402
from mvarlib import bitio, blf, ugc_header  # noqa: E402
from mvarlib.errors import BlfFormatError, EncodeError  # noqa: E402

# facts about the 5 distinct real files, keyed by the first 16 hex digits of the SHA-256 (SPEC 3.2 and A.2 R8)
REAL_FACTS = {
    "e2fbf965263740b6": (1535, "No-Armor-Lock Slayer"),
    "c3332ebe3b18c948": (1183, "Cobb Script Tests 01"),
    "e11ad8489e0a1a3b": (2287, "MOTL TEST"),
    "9deda304bbb14454": (2271, "User-Defined Function Test"),
    "9edf84633ceddf8d": (2575, "Vehicle HP API Tests"),
}
SALT34 = bytes.fromhex("EDD43009666D5C4A5C3657FAB40E022F535AC6C9EE471F01F1A44756B7714F1C36EC")


def stream_of(sample):
    """``(BlfFile, payload chunk, BitReader over the hashed part of the stream)`` for a sample."""
    parsed = blf.parse(sample.data)
    chunk = parsed.find("mpvr")
    return parsed, chunk, bitio.BitReader(chunk.stream, chunk.stored_length * 8)


def decode_at_68(sample):
    parsed, chunk, reader = stream_of(sample)
    prefix = (reader.read(4), reader.read(32), reader.read(32))
    assert reader.pos == 68
    return parsed, chunk, reader, prefix, ugc_header.read_header(reader)


class TestRealHeaders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.samples = helpers_real.load_samples()

    def test_header_decodes_at_bit_68(self):
        lengths = set()
        for sample in self.samples:
            with self.subTest(file=sample.path):
                _, chunk, reader, prefix, header = decode_at_68(sample)
                self.assertEqual(prefix[0], 2, "engine type nibble")
                self.assertEqual(prefix[1], 0x6B, "encodingVersion")
                self.assertEqual(header.start_bit, 68)
                length = header.end_bit - header.start_bit
                self.assertEqual(header.bit_length(), length, "the formula of SPEC 3.2 must equal what was consumed")
                self.assertEqual(reader.pos, header.end_bit)
                lengths.add(length)
                self.assertEqual(header.content_type_raw, 7, "stored value of a game variant")
                self.assertEqual((header.content_type, header.activity, header.game_mode, header.engine),
                                 (6, 3, 3, 2))
                self.assertEqual(header.file_length, len(sample.data))
                self.assertEqual(header.map_id, 0xFFFFFFFF)
                self.assertEqual(header.unk08, 0x4A6994BF5D589B43)
                for record in (header.created_by, header.modified_by):
                    self.assertEqual((record.timestamp, record.xuid, record.name, record.is_online_id),
                                     (1284422400, 0, b"\xa6\x00", 1))
                self.assertIsNotNone(header.engine_icon, "an engine icon is stored for a game variant")
                self.assertEqual((header.hopper_id, header.campaign, header.firefight), (None, None, None))
                self.assertLess(header.end_bit, chunk.stored_length * 8)
                known = REAL_FACTS.get(sample.sha16)
                if known is not None:
                    self.assertEqual((length, header.title_text), known)
        if helpers_real.require_samples():
            self.assertEqual(lengths, set(f[0] for f in REAL_FACTS.values()))

    def test_reencode_from_fields_at_68_and_at_0_is_bit_identical(self):
        for sample in self.samples:
            with self.subTest(file=sample.path):
                _, chunk, reader, prefix, header = decode_at_68(sample)
                original = bitio.BitReader(chunk.stream)
                # at bit 68: the prefix, then the header re-encoded from its fields
                writer = bitio.BitWriter()
                writer.write(prefix[0], 4)
                writer.write(prefix[1], 32)
                writer.write(prefix[2], 32)
                ugc_header.write_header(writer, header)
                self.assertEqual(writer.pos, header.end_bit)
                self.assertEqual(writer.getbits(), original.slice(0, header.end_bit))
                # at bit 0 (as in an mvar): the header alone
                alone = bitio.BitWriter()
                ugc_header.write_header(alone, header)
                self.assertEqual(alone.getbits(), original.slice(68, header.end_bit))
                self.assertEqual(alone.getbits(), header.raw, "the kept raw range is the same bits")
                self.assertEqual(alone.bits_written, header.end_bit - 68)

    def test_header_decodes_identically_at_offset_zero_and_at_every_alignment(self):
        rng = random.Random(0x68)
        for sample in self.samples:
            with self.subTest(file=sample.path):
                _, chunk, _, _, header = decode_at_68(sample)
                for lead in range(0, 9):
                    writer = bitio.BitWriter()
                    writer.write(rng.getrandbits(lead) if lead else 0, lead)
                    writer.write_bitstring(header.raw)
                    writer.write(rng.getrandbits(40), 40)                       # unrelated bits after it
                    reader = bitio.BitReader(writer.getvalue())
                    reader.set_bitpos(lead)
                    moved = ugc_header.read_header(reader)
                    self.assertEqual(moved, header, "lead %d" % lead)
                    self.assertEqual(moved.raw, header.raw)
                    self.assertEqual((moved.start_bit, moved.end_bit - moved.start_bit),
                                     (lead, header.end_bit - header.start_bit))

    def test_raw_range_is_the_exact_stream_bits(self):
        for sample in self.samples:
            with self.subTest(file=sample.path):
                _, chunk, _, _, header = decode_at_68(sample)
                self.assertEqual(header.raw, bitio.BitReader(chunk.stream).slice(68, header.end_bit))
                self.assertEqual(header.raw.nbits, header.end_bit - 68)

    def test_edits_shift_the_remainder_consistently(self):
        """A longer or shorter title, description or author name moves the rest of the stream by exactly the width change."""
        for sample in helpers_real.distinct_samples(self.samples):
            with self.subTest(file=sample.path):
                _, chunk, _, prefix, header = decode_at_68(sample)
                stream = bitio.BitReader(chunk.stream, chunk.stored_length * 8)
                remainder = stream.slice(header.end_bit, chunk.stored_length * 8)
                variants = {
                    "longer title": dataclasses.replace(header, title=ugc_header.encode_u16("A much longer title than before!!")),
                    "shorter title": dataclasses.replace(header, title=[0x4D, 0]),
                    "empty title": dataclasses.replace(header, title=[0]),
                    "longer description": dataclasses.replace(header, description=ugc_header.encode_u16("d" * 127)),
                    "empty description": dataclasses.replace(header, description=[0]),
                    "longer author": dataclasses.replace(header, created_by=dataclasses.replace(
                        header.created_by, name=b"Longer Gamertag\x00")),
                    "16 char author, no NUL": dataclasses.replace(header, modified_by=dataclasses.replace(
                        header.modified_by, name=b"0123456789ABCDEF")),
                    "empty author": dataclasses.replace(header, created_by=dataclasses.replace(header.created_by, name=b"\x00")),
                }
                for name, changed in variants.items():
                    writer = bitio.BitWriter()
                    writer.write(prefix[0], 4)
                    writer.write(prefix[1], 32)
                    writer.write(prefix[2], 32)
                    ugc_header.write_header(writer, changed)
                    new_end = writer.pos
                    self.assertEqual(new_end - 68, changed.bit_length(), name)
                    writer.write_bitstring(remainder)
                    again = bitio.BitReader(writer.getvalue(), writer.bits_written)
                    again.read(68)
                    decoded = ugc_header.read_header(again)
                    self.assertEqual(decoded, changed, name)
                    self.assertEqual(decoded.end_bit, new_end, name)
                    delta = changed.bit_length() - header.bit_length()
                    self.assertEqual(decoded.end_bit, header.end_bit + delta, name)
                    self.assertEqual(again.slice(decoded.end_bit, writer.bits_written), remainder,
                                     "%s: the rest of the stream must be unchanged, only moved" % name)

    def test_decoded_headers_survive_copy_and_pickle(self):
        for sample in self.samples:
            with self.subTest(file=sample.path):
                header = decode_at_68(sample)[4]
                for clone in (copy.copy(header), copy.deepcopy(header), pickle.loads(pickle.dumps(header)),
                              pickle.loads(pickle.dumps(header, 0))):
                    self.assertEqual(clone, header)
                    self.assertEqual(clone.raw, header.raw)
                    self.assertEqual((clone.start_bit, clone.end_bit), (68, header.end_bit))
                    self.assertEqual((clone.title_text, clone.description_text), (header.title_text, header.description_text))

    def test_chdr_parse_and_build_are_byte_exact(self):
        for sample in self.samples:
            with self.subTest(file=sample.path):
                chdr = blf.parse(sample.data).find("chdr")
                parsed = ugc_header.parse_chdr(chdr.raw)
                self.assertEqual(ugc_header.build_chdr(parsed), chdr.raw)
                self.assertEqual((parsed["version"], parsed["flags"]), (10, 2))
                self.assertEqual(parsed["content_type"], 6)
                self.assertEqual(parsed["file_length"], len(sample.data))
                self.assertEqual(parsed["map_id"], 0xFFFFFFFF)

    def test_chdr_build_is_byte_exact_on_arbitrary_blocks(self):
        """Pads and unknown regions are kept, so any 0x2C0 block survives a parse and a build."""
        rng = random.Random(0xC4D2)
        for _ in range(50):
            body = bytes(rng.getrandbits(8) for _ in range(0x2C0 - 12))
            block = struct.pack(">4sIHH", b"chdr", 0x2C0, rng.getrandbits(16), rng.getrandbits(16)) + body
            self.assertEqual(ugc_header.build_chdr(ugc_header.parse_chdr(block)), block)

    def test_chdr_rejects_other_blocks(self):
        data = self.samples[0].data
        with self.assertRaises(BlfFormatError):
            ugc_header.parse_chdr(data[:0x2C0])                      # starts with _blf
        with self.assertRaises(BlfFormatError):
            ugc_header.parse_chdr(data[0x30:0x30 + 0x2BF])
        parsed = ugc_header.parse_chdr(data[0x30:0x30 + 0x2C0])
        parsed["pad_11"] = b"\x00"
        with self.assertRaises(EncodeError):
            ugc_header.build_chdr(parsed)

    def test_chdr_agrees_with_the_bit_form_header(self):
        for sample in self.samples:
            with self.subTest(file=sample.path):
                parsed, _, _, _, header = decode_at_68(sample)
                chdr = ugc_header.parse_chdr(parsed.find("chdr").raw)
                self.assertEqual(ugc_header.compare_chdr_header(chdr, header, extended=True), [])
                wrong = dict(chdr, title="something else", file_length=1)
                problems = ugc_header.compare_chdr_header(wrong, header)
                self.assertEqual(len(problems), 2)
                self.assertTrue(problems[0].startswith("file length differs"))
                self.assertTrue(problems[1].startswith("title differs"))


# ---------------------------------------------------------------------------------------------
# Synthetic headers: the widths of the conditional tails and of the variable-length text
# ---------------------------------------------------------------------------------------------
class TestSyntheticHeaders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        w1 = helpers_container.load_w1_builder()
        data, _, cls.w1_length, cls.w1_hash = w1.build_file("salted_be32")
        cls.w1_stream = data[0x314:0x314 + 0x7000]                     # file offset 0x2F0 + 36
        reader = bitio.BitReader(cls.w1_stream)
        cls.header = ugc_header.read_header(reader)
        cls.rest = reader.slice(cls.header.end_bit, 4970)               # the W1 body, labels, slots and quotas

    def variant_numbers(self, header):
        """Encode ``header``, append the W1 remainder, return (header end, end bit, L, stored SHA-1 of the salted recipe)."""
        writer = bitio.BitWriter()
        ugc_header.write_header(writer, header)
        end_of_header = writer.pos
        writer.write_bitstring(self.rest)
        end = writer.bits_written
        length = (end + 7) // 8
        stream = writer.getvalue(0x7000)
        digest = hashlib.sha1(SALT34 + struct.pack(">I", length) + stream[:length]).hexdigest()
        return end_of_header, end, length, digest

    def test_w1_header(self):
        h = self.header
        self.assertEqual((h.start_bit, h.end_bit), (0, 1255))
        self.assertEqual((h.content_type_raw, h.content_type, h.file_length), (6, 5, 0x7329))
        self.assertEqual((h.unk08, h.unk10, h.unk18, h.unk20), (0x0123456789ABCDEF, 0x0F1E2D3C4B5A6978, 0x1122334455667788, 0))
        self.assertEqual((h.activity_raw, h.game_mode, h.engine, h.map_id, h.engine_category), (1, 4, 1, 3006, 0))
        self.assertEqual((h.created_by.timestamp, h.modified_by.timestamp), (1700000000, 1700000001))
        self.assertEqual((h.created_by.name, h.modified_by.name), (b"A\x00", b"A\x00"))
        self.assertEqual((h.title_text, h.description_text), ("W1 minimal", "synthetic reference fixture"))
        self.assertEqual((h.title, h.description[-1]), (list(map(ord, "W1 minimal")) + [0], 0))
        self.assertIsNone(h.engine_icon, "a map variant stores no engine icon")
        self.assertEqual(h.bit_length(), 1255)
        writer = bitio.BitWriter()
        ugc_header.write_header(writer, h)
        self.assertEqual(writer.getbits(), bitio.BitReader(self.w1_stream).slice(0, 1255))

    def test_w1_numbers_are_those_of_appendix_c(self):
        self.assertEqual((self.w1_length, self.w1_hash.hex()), (622, "a6183d5f5872d38b6dda0d476ea7d8c8c40641ad"))
        self.assertEqual(self.variant_numbers(self.header), (1255, 4970, 622, self.w1_hash.hex()))

    def test_header_variants_of_appendix_c4(self):
        h = self.header
        variants = {
            "hdr_hopper": (dataclasses.replace(h, activity_raw=3, hopper_id=0x1234),
                           (1271, 4986, 624, "9c8723519aebc42e54a16d5c59fa26b2af1e3615")),
            "hdr_campaign": (dataclasses.replace(h, game_mode=1, campaign=ugc_header.CampaignTail(5, 2, 1, 7, 0x01020304)),
                             (1307, 5022, 628, "e7495f21fa80a3d6f763a7ded50a1535edfce855")),
            "hdr_firefight": (dataclasses.replace(h, game_mode=2, firefight=ugc_header.FirefightTail(3, 0xA0B0C0D0)),
                              (1289, 5004, 626, "2db181cdbab88900a4812b2a30d6e53083b84a24")),
            # the spec names no characters for the long-text fixture; these (found by matching the golden SHA-1) are the ones
            # that reproduce it: both author names ABCDEFGHIJKLMNOP, the title 128 x 'T', the description 128 x 'D'
            "hdr_long_text": (dataclasses.replace(
                h, created_by=dataclasses.replace(h.created_by, name=b"ABCDEFGHIJKLMNOP"),
                modified_by=dataclasses.replace(h.modified_by, name=b"ABCDEFGHIJKLMNOP"),
                title=[0x54] * 128, description=[0x44] * 128),
                (4951, 8666, 1084, "34925a9213e04d13caf9187778b3f76a4233f343")),
            "hdr_min_text": (dataclasses.replace(
                h, created_by=dataclasses.replace(h.created_by, name=b"\x00"),
                modified_by=dataclasses.replace(h.modified_by, name=b"\x00"), title=[0], description=[0]),
                (647, 4362, 546, "1a45c8a3b33c8e1c444409ce2e7371ebafa15b4c")),
        }
        for name, (header, golden) in variants.items():
            with self.subTest(fixture=name):
                self.assertEqual(self.variant_numbers(header), golden)
                self.assertEqual(header.bit_length(), golden[0])
                # and the variant reads back from the stream it produced
                writer = bitio.BitWriter()
                ugc_header.write_header(writer, header)
                writer.write_bitstring(self.rest)
                again = ugc_header.read_header(bitio.BitReader(writer.getvalue()))
                self.assertEqual(again, header)
                self.assertEqual(again.end_bit, golden[0])

    def test_conditional_fields_are_present_iff_their_condition_holds(self):
        h = self.header
        for name, header, extra in (
                ("hopper", dataclasses.replace(h, activity_raw=3), "hopper_id"),
                ("campaign", dataclasses.replace(h, game_mode=1), "campaign"),
                ("firefight", dataclasses.replace(h, game_mode=2), "firefight"),
                ("engine icon", dataclasses.replace(h, content_type_raw=7), "engine_icon")):
            with self.subTest(case=name):
                self.assertIsNone(getattr(header, extra))
                with self.assertRaises(EncodeError):
                    ugc_header.write_header(bitio.BitWriter(), header)    # the field the condition needs is missing
        with self.assertRaises(EncodeError):                              # and a field whose condition does not hold
            ugc_header.write_header(bitio.BitWriter(), dataclasses.replace(h, hopper_id=1))
        with self.assertRaises(EncodeError):
            ugc_header.write_header(bitio.BitWriter(), dataclasses.replace(h, engine_icon=1))
        with self.assertRaises(EncodeError):
            ugc_header.write_header(bitio.BitWriter(), dataclasses.replace(h, campaign=ugc_header.CampaignTail(0, 0, 0, 0, 0)))

    def test_hopper_is_tested_on_the_decoded_activity(self):
        """Stored 3 (decoded 2) has a hopper id; stored 2 (decoded 1) and stored 4 (decoded 3, every real file) do not."""
        h = self.header
        for stored, expected in ((0, False), (1, False), (2, False), (3, True), (4, False), (7, False)):
            self.assertEqual(dataclasses.replace(h, activity_raw=stored).has_hopper, expected, stored)

    def test_text_extremes_and_strict_strings(self):
        h = self.header
        for field, ok in (("title", [0x41] * 128), ("title", [0]), ("description", [0x41] * 127 + [0])):
            writer = bitio.BitWriter()
            ugc_header.write_header(writer, dataclasses.replace(h, **{field: ok}))
        for field, bad in (("title", []), ("title", [0x41]), ("title", [0x41] * 129), ("title", [0, 0x41, 0])):
            with self.assertRaises(EncodeError, msg=(field, bad)):
                ugc_header.write_header(bitio.BitWriter(), dataclasses.replace(h, **{field: bad}))
        with self.assertRaises(EncodeError):
            ugc_header.write_header(bitio.BitWriter(), dataclasses.replace(
                h, created_by=dataclasses.replace(h.created_by, name=b"x" * 17)))
        with self.assertRaises(EncodeError):
            ugc_header.write_header(bitio.BitWriter(), dataclasses.replace(h, file_length=1 << 32))
        self.assertEqual(ugc_header.decode_u16(ugc_header.encode_u16("héllo €")), "héllo €")
        self.assertEqual(len(ugc_header.encode_u16("x" * 500)), 128)

    def test_truncated_headers_raise_bit_overrun(self):
        writer = bitio.BitWriter()
        ugc_header.write_header(writer, self.header)
        data = writer.getvalue()
        for cut in (3, 100, 1254):
            with self.assertRaises(bitio.BitOverrun, msg=cut):
                ugc_header.read_header(bitio.BitReader(data, cut))


class TestChdrFields(unittest.TestCase):
    """``chdr`` offsets and ``compare_chdr_header`` on a block built here with ``struct`` (SPEC 2.4), not with ``build_chdr``."""

    CREATED = (1700000000, 0x1111222233334444, b"Creator", 1)
    MODIFIED = (1700000099, 0x5555666677778888, b"Modifier", 0)

    @classmethod
    def setUpClass(cls):
        w1 = helpers_container.load_w1_builder()
        data = w1.build_file("salted_be32")[0]
        reader = bitio.BitReader(data[0x314:0x314 + 0x7000])
        header = ugc_header.read_header(reader)
        cls.header = dataclasses.replace(
            header,
            created_by=ugc_header.AuthorRecord(cls.CREATED[0], cls.CREATED[1], cls.CREATED[2] + b"\x00", cls.CREATED[3]),
            modified_by=ugc_header.AuthorRecord(cls.MODIFIED[0], cls.MODIFIED[1], cls.MODIFIED[2] + b"\x00", cls.MODIFIED[3]))
        cls.block = cls.make_block(cls.header)

    @staticmethod
    def make_block(header):
        b = bytearray(0x2C0)
        struct.pack_into(">4sIHH", b, 0, b"chdr", 0x2C0, 10, 2)
        b[0x10] = header.content_type
        struct.pack_into("<I", b, 0x14, header.file_length)
        for off, value in ((0x18, header.unk08), (0x20, header.unk10), (0x28, header.unk18), (0x30, header.unk20)):
            struct.pack_into("<Q", b, off, value)
        b[0x38] = header.activity
        b[0x39] = header.game_mode
        b[0x3A] = header.engine
        struct.pack_into("<I", b, 0x3C, header.map_id)
        struct.pack_into("<I", b, 0x40, header.engine_category)
        for off, record in ((0x48, header.created_by), (0x6C, header.modified_by)):
            struct.pack_into("<QQ", b, off, record.timestamp, record.xuid)
            b[off + 16:off + 32] = record.name.ljust(16, b"\x00")
            b[off + 32] = record.is_online_id
        b[0x90:0x190] = header.title_text.encode("utf-16-le").ljust(0x100, b"\x00")
        b[0x190:0x290] = header.description_text.encode("utf-16-le").ljust(0x100, b"\x00")
        return bytes(b)

    def test_the_two_author_records_are_read_from_their_own_offsets(self):
        parsed = ugc_header.parse_chdr(self.block)
        for who, (timestamp, xuid, name, online) in (("created_by", self.CREATED), ("modified_by", self.MODIFIED)):
            with self.subTest(record=who):
                record = parsed[who]
                self.assertEqual((record["timestamp"], record["xuid"], record["is_online_id"]), (timestamp, xuid, online))
                self.assertEqual(record["name"], name.ljust(16, b"\x00"))
        self.assertEqual(ugc_header.build_chdr(parsed), self.block)
        swapped = ugc_header.parse_chdr(self.block)
        self.assertNotEqual(swapped["created_by"], swapped["modified_by"])

    def test_the_other_fields_are_read_from_their_offsets(self):
        parsed = ugc_header.parse_chdr(self.block)
        h = self.header
        self.assertEqual((parsed["content_type"], parsed["file_length"], parsed["map_id"], parsed["engine_category"]),
                         (5, 0x7329, 3006, 0))
        self.assertEqual((parsed["unk08"], parsed["unk10"], parsed["unk18"], parsed["unk20"]), (h.unk08, h.unk10, h.unk18, h.unk20))
        self.assertEqual((parsed["activity"], parsed["game_mode"], parsed["engine"]), (h.activity, 4, 1))
        self.assertEqual((parsed["title"], parsed["description"]), ("W1 minimal", "synthetic reference fixture"))

    def test_the_agreeing_block_has_no_differences(self):
        parsed = ugc_header.parse_chdr(self.block)
        self.assertEqual(ugc_header.compare_chdr_header(parsed, self.header), [])
        self.assertEqual(ugc_header.compare_chdr_header(parsed, self.header, extended=True), [])

    def test_each_checked_field_is_reported_on_its_own(self):
        parsed = ugc_header.parse_chdr(self.block)
        basic = (("content type", dict(parsed, content_type=6)),
                 ("file length", dict(parsed, file_length=1)),
                 ("map id", dict(parsed, map_id=3007)),
                 ("title", dict(parsed, title="other")),
                 ("description", dict(parsed, description="other")))
        for name, changed in basic:
            for extended in (False, True):
                with self.subTest(field=name, extended=extended):
                    problems = ugc_header.compare_chdr_header(changed, self.header, extended=extended)
                    self.assertEqual(len(problems), 1, problems)
                    self.assertTrue(problems[0].startswith(name + " differs: chdr has "), problems[0])
        # all five at once, in the documented order
        every = dict(parsed, content_type=6, file_length=1, map_id=3007, title="a", description="b")
        problems = ugc_header.compare_chdr_header(every, self.header)
        self.assertEqual([p.split(" differs")[0] for p in problems], ["content type", "file length", "map id", "title", "description"])

    def test_extended_fields_are_reported_only_when_asked_for(self):
        parsed = ugc_header.parse_chdr(self.block)
        extended = [("unk08", dict(parsed, unk08=1)), ("unk10", dict(parsed, unk10=1)), ("unk18", dict(parsed, unk18=1)),
                    ("unk20", dict(parsed, unk20=1)), ("activity", dict(parsed, activity=5)),
                    ("game mode", dict(parsed, game_mode=2)), ("engine", dict(parsed, engine=2)),
                    ("engine category", dict(parsed, engine_category=9))]
        for who in ("created_by", "modified_by"):
            for key, label in (("timestamp", "timestamp"), ("xuid", "xuid"), ("name", "name"), ("is_online_id", "online id flag")):
                value = b"Someone".ljust(16, b"\x00") if key == "name" else (parsed[who][key] ^ 1)
                extended.append(("%s %s" % (who, label), dict(parsed, **{who: dict(parsed[who], **{key: value})})))
        for name, changed in extended:
            with self.subTest(field=name):
                self.assertEqual(ugc_header.compare_chdr_header(changed, self.header), [])
                problems = ugc_header.compare_chdr_header(changed, self.header, extended=True)
                self.assertEqual(len(problems), 1, problems)
                self.assertTrue(problems[0].startswith(name + " differs: chdr has "), problems[0])

    def test_the_author_records_are_not_confused_with_each_other(self):
        parsed = ugc_header.parse_chdr(self.block)
        crossed = dict(parsed, created_by=parsed["modified_by"], modified_by=parsed["created_by"])
        problems = ugc_header.compare_chdr_header(crossed, self.header, extended=True)
        self.assertEqual(len(problems), 8, problems)             # timestamp, xuid, name, online id flag for each record
        self.assertEqual(sorted(p.split(" differs")[0] for p in problems),
                         sorted("%s %s" % (who, what) for who in ("created_by", "modified_by")
                                for what in ("timestamp", "xuid", "name", "online id flag")))


class TestHeaderCopyAndPickle(unittest.TestCase):
    """``UgcHeader.raw`` is a ``BitString``; a deep copy of the header (and so of the model) must work (SPEC 6.3)."""

    @classmethod
    def setUpClass(cls):
        data = helpers_container.load_w1_builder().build_file("salted_be32")[0]
        base = ugc_header.read_header(bitio.BitReader(data[0x314:0x314 + 0x7000]))
        variants = {
            "w1": base,
            "hopper": dataclasses.replace(base, activity_raw=3, hopper_id=0x1234),
            "campaign": dataclasses.replace(base, game_mode=1, campaign=ugc_header.CampaignTail(5, 2, 1, 7, 0x01020304)),
            "firefight": dataclasses.replace(base, game_mode=2, firefight=ugc_header.FirefightTail(3, 0xA0B0C0D0)),
            "game variant": dataclasses.replace(base, content_type_raw=7, engine_icon=9),
        }
        cls.headers = {}
        for name, header in variants.items():          # re-read, so that ``raw``, ``start_bit`` and ``end_bit`` are those of the bits
            writer = bitio.BitWriter()
            writer.write(0, 3)                          # a misaligned start
            ugc_header.write_header(writer, header)
            reader = bitio.BitReader(writer.getvalue())
            reader.set_bitpos(3)
            cls.headers[name] = ugc_header.read_header(reader)

    def clones(self, header):
        yield "copy", copy.copy(header)
        yield "deepcopy", copy.deepcopy(header)
        for protocol in range(0, pickle.HIGHEST_PROTOCOL + 1):
            yield "pickle%d" % protocol, pickle.loads(pickle.dumps(header, protocol))

    def test_every_variant_survives(self):
        for name, header in self.headers.items():
            self.assertEqual(header.start_bit, 3)
            for how, clone in self.clones(header):
                with self.subTest(header=name, how=how):
                    self.assertEqual(clone, header)
                    self.assertIsInstance(clone.raw, bitio.BitString)
                    self.assertEqual(clone.raw, header.raw)
                    self.assertEqual((clone.start_bit, clone.end_bit), (header.start_bit, header.end_bit))
                    self.assertEqual(clone.raw.nbits, clone.end_bit - clone.start_bit)
                    writer = bitio.BitWriter()
                    ugc_header.write_header(writer, clone)
                    self.assertEqual(writer.getbits(), clone.raw, "the copy still re-encodes to the bits it was read from")

    def test_a_deep_copy_is_independent_of_the_original(self):
        header = self.headers["w1"]
        clone = copy.deepcopy(header)
        clone.title[0] = 0x58
        clone.created_by.name = b"Zed\x00"
        self.assertEqual(header.title[0], ord("W"))
        self.assertEqual(header.created_by.name, b"A\x00")
        self.assertNotEqual(clone, header)


if __name__ == "__main__":
    unittest.main()
