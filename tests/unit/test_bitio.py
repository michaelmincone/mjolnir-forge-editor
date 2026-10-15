"""U-01 (SPEC 9.3, tier T1): MSB-first bit I/O.

* A 608-check port of ``docs/mvar/reference/bitio_prototype.py``: random width schedules over the real
  ``mpvr`` payloads (whole payload, payload minus 1 to 7 bits, and the hashable region from the
  misaligned bit 4), each cross-checked against line-by-line Python ports of the C++ reader and
  writer (the oracles ``RvtPortReader`` / ``RvtPortWriter`` below), plus 8 unit checks.
* Masked writes never disturb neighbouring bits. The C++ ``write_to_bitpos`` does (with a byte-aligned
  start and fewer than 8 bits left it assigns the whole byte); ``TestClobberHazard`` shows the hazard
  on the port and proves the library cannot do it, exhaustively over offsets and widths.
* Signed fields, strings that stop after the NUL, overrun raises, widths 0 to 64 (a 0-bit read
  consumes nothing), ``write`` raises ``EncodeError`` on a value that does not fit.
* A failed read moves nothing (the string readers included) and a refused write changes nothing (the
  string writers included); ``BitString`` can be copied, deep-copied and pickled (SPEC 5.1 keeps raw
  bit ranges in the model, SPEC 6.3 deep-copies the model).

The real-payload part needs the sample files (it is skipped with a notice without ``--samples``);
everything else is pure and always runs.
"""
import copy
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

import helpers_real  # noqa: E402
from mvarlib import bitio  # noqa: E402
from mvarlib.bitio import BitOverrun, BitReader, BitString, BitWriter  # noqa: E402
from mvarlib.errors import CapacityError, DecodeError, EncodeError, InternalError, MvarError  # noqa: E402


# ---------------------------------------------------------------------------------------------
# Oracles: line-by-line ports of ReachVariantTool's byte-oriented algorithms (bitreader.h:17-95,
# bitwriter.cpp:77-106). They are kept here, not in the library: the library must not contain them.
# ---------------------------------------------------------------------------------------------
class RvtPortReader(object):
    """Port of cobb::bitreader::_consume_byte / read_bits."""

    def __init__(self, data):
        self.buffer = data
        self.length = len(data)
        self.offset = 0

    def _consume_byte(self, bitcount):
        bytepos = self.offset // 8
        if bytepos >= self.length:
            return 0, bitcount
        shift = self.offset % 8
        byte = self.buffer[bytepos] & (0xFF >> shift)
        bits_read = 8 - shift
        if bitcount < bits_read:
            byte >>= (bits_read - bitcount)
            self.offset += bitcount
            consumed = bitcount
        else:
            self.offset += bits_read
            consumed = bits_read
        return byte, consumed

    def read_bits(self, bitcount):
        bits, consumed = self._consume_byte(bitcount)
        result = bits
        remaining = bitcount - consumed
        while remaining:
            bits, consumed = self._consume_byte(remaining)
            result = (result << consumed) | bits
            remaining -= consumed
        return result


class RvtPortWriter(object):
    """Port of cobb::bitwriter::_write. Buffer pre-sized and zeroed; ``bitpos`` is the write cursor.

    With ``shift == 0`` and ``bits < 8`` the C++ code *assigns* the whole byte, which wipes the low
    bits that follow the field: the clobber hazard this library avoids.
    """

    def __init__(self, nbytes):
        self.buf = bytearray(nbytes)
        self.bitpos = 0

    def write(self, value, bits):
        if bits == 0:
            return
        self._write(value, bits, [bits])

    def _write(self, value, bits, remaining_box):
        value &= (1 << bits) - 1
        bytepos = self.bitpos // 8
        shift = self.bitpos % 8
        if shift == 0:
            if bits < 8:
                self.buf[bytepos] = (value << (8 - bits)) & 0xFF
                self.bitpos += bits
                return
            self.buf[bytepos] = (value >> (bits - 8)) & 0xFF
            self.bitpos += 8
            remaining_box[0] -= 8
        else:
            extra = 8 - shift
            if bits <= extra:
                self.buf[bytepos] |= (value << (extra - bits)) & 0xFF
                self.bitpos += bits
                return
            self.buf[bytepos] &= ~(0xFF >> shift) & 0xFF
            self.buf[bytepos] |= (value >> (bits - extra)) & 0xFF
            self.bitpos += extra
            remaining_box[0] -= extra
        if remaining_box[0] > 0:
            self._write(value, remaining_box[0], remaining_box)


def reference_overwrite(buf, start, nbits, value):
    """Big-integer model of "overwrite exactly these bits": the definition the library must match."""
    total = len(buf) * 8
    model = int.from_bytes(bytes(buf), "big")
    shift = total - start - nbits
    mask = ((1 << nbits) - 1) << shift
    model = (model & ~mask) | (value << shift)
    return model.to_bytes(len(buf), "big")


# ---------------------------------------------------------------------------------------------
# Real payloads
# ---------------------------------------------------------------------------------------------
def mpvr_payloads(samples):
    """``[(name, payload_bytes, hashable_len, seed_int)]`` for each distinct real file."""
    out = []
    for sample in helpers_real.distinct_samples(samples):
        data = sample.data
        pos = 0
        while pos + 12 <= len(data):
            sig, size, _, _ = struct.unpack_from(">4sIHH", data, pos)
            if sig == b"mpvr":
                hashable_len = struct.unpack_from("<I", data, pos + 0x24)[0]
                out.append((sample.name, data[pos + 0x28:pos + size], hashable_len, int(sample.sha256[:8], 16)))
                break
            pos += size
    return out


def random_schedule(rng, total_bits):
    """Random field widths (1..64, biased toward small like real fields) that sum to ``total_bits``."""
    widths = []
    left = total_bits
    while left > 0:
        r = rng.random()
        if r < 0.45:
            w = rng.randint(1, 8)
        elif r < 0.75:
            w = rng.randint(9, 16)
        elif r < 0.92:
            w = rng.randint(17, 32)
        else:
            w = rng.randint(33, 64)
        w = min(w, left)
        widths.append(w)
        left -= w
    return widths


def roundtrip(source, total_bits, start_bit, rng):
    """Read ``total_bits`` bits in random widths from ``start_bit``, write them back; cross-check both oracles."""
    widths = random_schedule(rng, total_bits)
    reader = BitReader(source)
    reader.set_bitpos(start_bit)
    values = [reader.read(w) for w in widths]
    assert reader.pos == start_bit + total_bits
    oracle = RvtPortReader(source)
    oracle.offset = start_bit
    assert [oracle.read_bits(w) for w in widths] == values, "RVT-port reader disagrees with BitReader"
    writer = BitWriter()
    for value, n in zip(values, widths):
        writer.write(value, n)
    assert writer.pos == total_bits
    port = RvtPortWriter((total_bits + 7) // 8 + 1)
    for value, n in zip(values, widths):
        port.write(value, n)
    assert bytes(port.buf[:(total_bits + 7) // 8]) == writer.getvalue(), "RVT-port writer disagrees with BitWriter"
    return writer.getvalue(), widths


class TestRealPayloadRoundTrips(unittest.TestCase):
    """The 608-check port of the prototype's self test (600 round trips + 8 unit checks)."""

    SEEDS = 40
    checks = 0
    sections = set()

    @classmethod
    def setUpClass(cls):
        cls.payloads = mpvr_payloads(helpers_real.load_samples())
        cls.checks = 0
        cls.sections = set()

    def test_random_width_schedules_over_real_payloads(self):
        self.assertGreaterEqual(len(self.payloads), 1)
        if helpers_real.require_samples():
            self.assertEqual(len(self.payloads), helpers_real.EXPECTED_DISTINCT)
        count = 0
        for name, payload, hashable_len, seed_base in self.payloads:
            full_bits = len(payload) * 8
            for seed in range(self.SEEDS):
                rng = random.Random(0xC0BB ^ (seed * 7919) ^ seed_base)
                # (a) the whole payload, a byte-multiple total
                out, _ = roundtrip(payload, full_bits, 0, rng)
                self.assertEqual(out, payload, "%s seed %d: whole-payload round trip" % (name, seed))
                count += 1
                # (b) the payload minus 1..7 bits: the last byte is partial and padded with zero bits
                trim = rng.randint(1, 7)
                out, _ = roundtrip(payload, full_bits - trim, 0, rng)
                mask = (0xFF << trim) & 0xFF
                self.assertEqual(len(out), len(payload))
                self.assertEqual(out[:-1], payload[:-1])
                self.assertEqual(out[-1] & mask, payload[-1] & mask)
                self.assertEqual(out[-1] & ~mask & 0xFF, 0, "%s seed %d: padding bits must be zero" % (name, seed))
                count += 1
                # (c) the hashable region from the misaligned bit 4 with a non-multiple-of-8 total
                total = hashable_len * 8 - 4 - rng.randint(0, 7)
                out, _ = roundtrip(payload, total, 4, rng)
                big = int.from_bytes(payload, "big")
                piece = (big >> (full_bits - 4 - total)) & ((1 << total) - 1)
                expected = (piece << ((8 - total % 8) % 8)).to_bytes((total + 7) // 8, "big")
                self.assertEqual(out, expected, "%s seed %d: misaligned region" % (name, seed))
                count += 1
        self.assertEqual(count, len(self.payloads) * self.SEEDS * 3)
        type(self).checks += count
        type(self).sections.add("schedules")

    def test_eight_unit_checks(self):
        """The prototype's final eight checks (signed, offset, write_to_bitpos, u16string, overflow)."""
        w = BitWriter()
        w.write_signed(-1, 3)
        w.write(0, 3)                                    # "offset" field: real value -1 stored as 0
        w.write(6, 3)                                    # real value 5 stored as 6
        w.write_u16string([0x4E, 0x6F, 0], 4)
        r = BitReader(w.getvalue())
        self.assertEqual(r.read_signed(3), -1)                              # 1
        self.assertEqual(r.read(3) - 1, -1)                                 # 2
        self.assertEqual(r.read(3) - 1, 5)                                  # 3
        self.assertEqual(r.read_u16string(4), [0x4E, 0x6F, 0])              # 4
        w2 = BitWriter()
        w2.write(0, 40)
        w2.write_to_bitpos(5, 32, 0xDEADBEEF)
        rb = BitReader(w2.getvalue())
        rb.set_bitpos(5)
        self.assertEqual(rb.read(32), 0xDEADBEEF)                           # 5
        self.assertEqual(w2.pos, 40)                                        # 6: the cursor did not move
        rr = BitReader(b"\xff")
        with self.assertRaises(BitOverrun):                                 # 7: reading past the end raises ...
            rr.read(12)
        self.assertEqual(rr.pos, 0)                                         # 8: ... and consumes nothing
        type(self).checks += 8
        type(self).sections.add("units")

    def test_zz_total_is_608(self):
        if type(self).sections == set(["schedules", "units"]) and self.SEEDS == 40 \
                and len(self.payloads) == helpers_real.EXPECTED_DISTINCT:
            self.assertEqual(type(self).checks, 608, "expected 600 round trips + 8 unit checks")
        sys.stdout.write("\nU-01: %d real-payload bit I/O checks passed (%d distinct files)\n"
                         % (type(self).checks, len(self.payloads)))


# ---------------------------------------------------------------------------------------------
# Masked writes
# ---------------------------------------------------------------------------------------------
class TestClobberHazard(unittest.TestCase):
    """The RVT ``write_to_bitpos`` hazard (container-and-bit-conventions.md section 11) cannot occur here."""

    def test_the_port_of_the_cpp_code_does_clobber(self):
        """Overwriting 32 bits at bit 4 over 0xFF bytes: the C++ algorithm wipes the low nibble after the field."""
        port = RvtPortWriter(8)
        port.buf[:] = b"\xff" * 8
        port.bitpos = 4
        port.write(0x5329, 32)
        self.assertEqual(bytes(port.buf).hex(), "f000053290ffffff")          # note the 90: should be 9f
        correct = reference_overwrite(b"\xff" * 8, 4, 32, 0x5329)
        self.assertEqual(correct.hex(), "f00005329fffffff")
        self.assertNotEqual(bytes(port.buf), correct, "the hazard demo is only meaningful if the port is wrong")
        aligned = RvtPortWriter(8)                                           # at a byte boundary the port is fine
        aligned.buf[:] = b"\xff" * 8
        aligned.bitpos = 8
        aligned.write(0x5329, 32)
        self.assertEqual(bytes(aligned.buf), reference_overwrite(b"\xff" * 8, 8, 32, 0x5329))

    def test_library_write_to_bitpos_does_not_clobber(self):
        writer = BitWriter()
        writer.write(0xFFFFFFFFFFFFFFFF, 64)
        writer.write_to_bitpos(4, 32, 0x5329)
        self.assertEqual(writer.getvalue().hex(), "f00005329fffffff")
        self.assertEqual(writer.pos, 64)

    def test_patch_bits_does_not_clobber(self):
        buf = bytearray(b"\xff" * 8)
        bitio.patch_bits(buf, 4, 32, 0x5329)
        self.assertEqual(bytes(buf).hex(), "f00005329fffffff")
        buf = bytearray(b"\x00" * 8)
        bitio.patch_bits(buf, 4, 32, 0xFFFFFFFF)
        self.assertEqual(bytes(buf).hex(), "0ffffffff0000000")

    def test_exhaustive_offsets_and_widths(self):
        """Every (offset, width) pair over several backgrounds equals the big-integer definition."""
        backgrounds = [b"\xff" * 16, b"\x00" * 16, b"\xaa" * 16, b"\x55" * 16, bytes(range(16)), bytes(range(240, 256))]
        rng = random.Random(0x5EED)
        checked = 0
        for background in backgrounds:
            for start in range(0, 24):
                for nbits in range(0, 49):
                    value = rng.getrandbits(nbits) if nbits else 0
                    expected = reference_overwrite(background, start, nbits, value)
                    writer = BitWriter()
                    writer.write_bytes(background)
                    writer.write_to_bitpos(start, nbits, value)
                    self.assertEqual(writer.getvalue(), expected, (background[:2].hex(), start, nbits))
                    self.assertEqual(writer.pos, 128)
                    buf = bytearray(background)
                    bitio.patch_bits(buf, start, nbits, value)
                    self.assertEqual(bytes(buf), expected)
                    # the same field written in sequence with a cursor placed there
                    cursor = BitWriter()
                    cursor.write_bytes(background)
                    cursor.pos = start
                    cursor.write(value, nbits)
                    self.assertEqual(cursor.getvalue(), expected)
                    self.assertEqual(cursor.pos, start + nbits)
                    checked += 1
        self.assertEqual(checked, len(backgrounds) * 24 * 49)

    def test_random_overwrites_never_touch_outside_bits(self):
        rng = random.Random(0xC10B)
        for _ in range(500):
            size = rng.randint(1, 40)
            background = bytes(rng.getrandbits(8) for _ in range(size))
            nbits = rng.randint(0, min(64, size * 8))
            start = rng.randint(0, size * 8 - nbits)
            value = rng.getrandbits(nbits) if nbits else 0
            buf = bytearray(background)
            bitio.patch_bits(buf, start, nbits, value)
            before = int.from_bytes(background, "big")
            after = int.from_bytes(bytes(buf), "big")
            diff = before ^ after
            window = ((1 << nbits) - 1) << (size * 8 - start - nbits)
            self.assertEqual(diff & ~window, 0, "a bit outside the field changed")
            self.assertEqual(bitio.get_bits(bytes(buf), start, nbits), value)

    def test_mvar_embedded_file_length_position(self):
        """The case that matters: the embedded fileLength of an mvar sits at bit 4, next to the content type nibble."""
        stream = bytearray(b"\x6f\xff\xff\xff\xff\xf0")            # nibble 6, then 32 one-bits, then ones
        bitio.patch_bits(stream, 4, 32, 0x7329)
        self.assertEqual(stream[0] >> 4, 6, "the content type nibble must survive")
        self.assertEqual(bitio.get_bits(bytes(stream), 4, 32), 0x7329)
        self.assertEqual(stream[5], 0xF0, "the bits after the field must survive")

    def test_patch_bits_errors(self):
        buf = bytearray(4)
        with self.assertRaises(EncodeError):
            bitio.patch_bits(buf, 0, 4, 16)
        with self.assertRaises(EncodeError):
            bitio.patch_bits(buf, 28, 8, 1)
        with self.assertRaises(EncodeError):
            bitio.patch_bits(buf, 0, 4, -1)
        with self.assertRaises(InternalError):
            bitio.patch_bits(bytes(4), 0, 4, 1)                # needs a bytearray
        self.assertEqual(bytes(buf), bytes(4), "a refused patch must change nothing")


# ---------------------------------------------------------------------------------------------
# Reader and writer behaviour
# ---------------------------------------------------------------------------------------------
class TestWidthsAndAlignment(unittest.TestCase):
    def test_all_widths_0_to_64_at_all_alignments(self):
        rng = random.Random(64)
        for width in range(0, 65):
            for lead in range(0, 8):
                value = rng.getrandbits(width) if width else 0
                writer = BitWriter()
                writer.write(0b1010101 >> (7 - lead) if lead else 0, lead)
                writer.write(value, width)
                writer.write(0b101, 3)
                reader = BitReader(writer.getvalue())
                reader.read(lead)
                self.assertEqual(reader.read(width), value, (width, lead))
                self.assertEqual(reader.read(3), 0b101)
                self.assertEqual(reader.pos, lead + width + 3)

    def test_zero_width_read_consumes_nothing(self):
        reader = BitReader(b"\xa5\x5a")
        reader.set_bitpos(5)
        self.assertEqual(reader.read(0), 0)
        self.assertEqual(reader.pos, 5)
        reader.set_bitpos(16)
        self.assertEqual(reader.read(0), 0, "a 0-bit read at the very end is not an overrun")
        writer = BitWriter()
        writer.write(0, 0)
        self.assertEqual((writer.pos, writer.getvalue()), (0, b""))
        with self.assertRaises(EncodeError):
            writer.write(1, 0)                                  # nothing but 0 fits in 0 bits

    def test_msb_first_big_endian_fields(self):
        reader = BitReader(bytes([0b10110010, 0b01111111, 0xFF]))
        self.assertEqual(reader.read(1), 1)
        self.assertEqual(reader.read(3), 0b011)
        self.assertEqual(reader.read(8), 0b00100111)
        self.assertEqual(BitReader(bytes.fromhex("12345678")).read(32), 0x12345678)
        shifted = BitReader(bytes.fromhex("0123456780"))          # the same u32 starting at bit 4
        self.assertEqual(shifted.read(4), 0)
        self.assertEqual(shifted.read(32), 0x12345678)

    def test_large_widths_for_blobs(self):
        rng = random.Random(7)
        blob = bytes(rng.getrandbits(8) for _ in range(4096))
        for lead in (0, 3, 7):
            writer = BitWriter()
            if lead:
                writer.write(1, lead)
            writer.write_bytes(blob)
            reader = BitReader(writer.getvalue())
            reader.read(lead)
            self.assertEqual(reader.read_bytes(len(blob)), blob)
            self.assertEqual(reader.pos, lead + 8 * len(blob))
        self.assertEqual(BitReader(blob).read(8 * len(blob)), int.from_bytes(blob, "big"))

    def test_bool_and_bytes_helpers(self):
        writer = BitWriter()
        writer.write_bool(True)
        writer.write_bool(False)
        writer.write_bytes(b"\xAB\xCD")
        reader = BitReader(writer.getvalue())
        self.assertIs(reader.read_bool(), True)
        self.assertIs(reader.read_bool(), False)
        self.assertEqual(reader.read_bytes(2), b"\xAB\xCD")
        self.assertEqual(reader.read_bytes(0), b"")

    def test_sequential_write_equals_big_integer_concatenation(self):
        rng = random.Random(99)
        for _ in range(200):
            widths = [rng.randint(0, 40) for _ in range(rng.randint(1, 30))]
            values = [rng.getrandbits(w) if w else 0 for w in widths]
            writer = BitWriter()
            acc = 0
            total = 0
            for value, w in zip(values, widths):
                writer.write(value, w)
                acc = (acc << w) | value
                total += w
            expected = (acc << ((8 - total % 8) % 8)).to_bytes((total + 7) // 8, "big")
            self.assertEqual(writer.getvalue(), expected)
            self.assertEqual(writer.bits_written, total)
            self.assertEqual(writer.getbits(), BitString(expected, total))


class TestSignedFields(unittest.TestCase):
    def test_signed_round_trip_all_small_widths(self):
        for n in range(1, 9):
            for value in range(-(1 << (n - 1)), 1 << (n - 1)):
                writer = BitWriter()
                writer.write_signed(value, n)
                reader = BitReader(writer.getvalue(), n)
                self.assertEqual(reader.read_signed(n), value, (n, value))

    def test_signed_edges_up_to_64(self):
        for n in (9, 16, 31, 32, 33, 63, 64):
            for value in (-(1 << (n - 1)), -(1 << (n - 1)) + 1, -1, 0, 1, (1 << (n - 1)) - 1):
                writer = BitWriter()
                writer.write(0, 3)
                writer.write_signed(value, n)
                reader = BitReader(writer.getvalue())
                reader.read(3)
                self.assertEqual(reader.read_signed(n), value, (n, value))

    def test_signed_out_of_range_raises(self):
        for n, value in ((1, 1), (1, -2), (3, 4), (3, -5), (8, 128), (8, -129), (64, 1 << 63), (64, -(1 << 63) - 1)):
            with self.assertRaises(EncodeError, msg=(n, value)):
                BitWriter().write_signed(value, n)
        with self.assertRaises(EncodeError):
            BitWriter().write_signed(1, 0)
        BitWriter().write_signed(0, 0)

    def test_zero_width_signed_read_is_zero(self):
        self.assertEqual(BitReader(b"\xff").read_signed(0), 0)

    def test_signed_read_of_the_four_bit_pattern(self):
        reader = BitReader(bytes([0b11110111]))
        self.assertEqual(reader.read_signed(4), -1)
        self.assertEqual(reader.read_signed(4), 7)


class TestStrings(unittest.TestCase):
    def test_cstring_stops_after_the_nul_and_keeps_it(self):
        reader = BitReader(b"AB\x00CD")
        self.assertEqual(reader.read_cstring(16), b"AB\x00")
        self.assertEqual(reader.pos, 24, "the bytes after the NUL are not consumed")
        self.assertEqual(reader.read_cstring(2), b"CD", "stops at the maximum length too")

    def test_cstring_stops_at_maxlen_without_a_nul(self):
        reader = BitReader(b"ABCDEFGH")
        self.assertEqual(reader.read_cstring(3), b"ABC")
        self.assertEqual(reader.pos, 24)
        self.assertEqual(BitReader(b"\x00xyz").read_cstring(16), b"\x00")
        self.assertEqual(BitReader(b"abc").read_cstring(0), b"")

    def test_u16string_stops_after_the_nul(self):
        writer = BitWriter()
        for unit in (0x57, 0x31, 0, 0x99, 0x99):
            writer.write(unit, 16)
        reader = BitReader(writer.getvalue())
        self.assertEqual(reader.read_u16string(128), [0x57, 0x31, 0])
        self.assertEqual(reader.pos, 48)
        reader = BitReader(writer.getvalue())
        self.assertEqual(reader.read_u16string(2), [0x57, 0x31], "stops at the maximum length too")

    def test_strings_at_misaligned_positions(self):
        for lead in range(8):
            writer = BitWriter()
            writer.write(0, lead)
            writer.write_cstring(b"Hi\x00", 16)
            writer.write_u16string([0x48, 0x69, 0], 128)
            reader = BitReader(writer.getvalue())
            reader.read(lead)
            self.assertEqual(reader.read_cstring(16), b"Hi\x00")
            self.assertEqual(reader.read_u16string(128), [0x48, 0x69, 0])

    def test_writer_strings_must_read_back_as_themselves(self):
        writer = BitWriter()
        writer.write_u16string([0] , 128)                             # the empty string is a single NUL
        writer.write_u16string([1] * 128, 128)                        # exactly maxlen units, no NUL
        writer.write_cstring(b"x" * 16, 16)
        for bad_units in ([], [1, 2], [0, 0], [1, 0, 2, 0], [1] * 129):
            with self.assertRaises(EncodeError, msg=bad_units):
                BitWriter().write_u16string(bad_units, 128)
        for bad_bytes in (b"", b"ab", b"a\x00b\x00", b"x" * 17):
            with self.assertRaises(EncodeError, msg=bad_bytes):
                BitWriter().write_cstring(bad_bytes, 16)
        with self.assertRaises(EncodeError):
            BitWriter().write_u16string([0x10000, 0], 128)


class TestOverrun(unittest.TestCase):
    def test_overrun_raises_and_consumes_nothing(self):
        reader = BitReader(b"\xff\x00")
        reader.read(13)
        with self.assertRaises(BitOverrun) as ctx:
            reader.read(4)
        self.assertEqual(reader.pos, 13)
        self.assertEqual((ctx.exception.pos, ctx.exception.requested, ctx.exception.bit_length), (13, 4, 16))
        self.assertEqual(reader.read(3), 0, "the remaining bits can still be read")
        self.assertEqual(reader.remaining(), 0)

    def test_bit_overrun_is_a_library_error(self):
        self.assertTrue(issubclass(BitOverrun, DecodeError))
        self.assertTrue(issubclass(BitOverrun, MvarError))

    def test_bit_length_limits_the_readable_bits(self):
        reader = BitReader(b"\xff\xff\xff", bit_length=20)
        self.assertEqual(reader.read(20), 0xFFFFF)
        with self.assertRaises(BitOverrun):
            reader.read(1)
        with self.assertRaises(BitOverrun):
            BitReader(b"\xff\xff", bit_length=9).read(10)

    def test_every_reader_entry_point_raises(self):
        with self.assertRaises(BitOverrun):
            BitReader(b"").read(1)
        with self.assertRaises(BitOverrun):
            BitReader(b"\x01").read_signed(9)
        with self.assertRaises(BitOverrun):
            BitReader(b"AB").read_cstring(3)                  # no NUL within the data
        with self.assertRaises(BitOverrun):
            BitReader(b"\x00\x01\x00").read_u16string(3)       # third unit incomplete
        with self.assertRaises(BitOverrun):
            BitReader(b"AB").read_bytes(3)
        with self.assertRaises(BitOverrun):
            BitReader(b"AB").skip(17)
        with self.assertRaises(BitOverrun):
            BitReader(b"AB").set_bitpos(17)
        with self.assertRaises(BitOverrun):
            BitReader(b"AB").slice(8, 17)
        BitReader(b"AB").set_bitpos(16)                        # the end itself is a valid position

    def test_a_failed_read_leaves_pos_unchanged_for_every_entry_point(self):
        """The documented guarantee: single-value reads and the multi-unit string readers alike."""
        data = b"ABC"                                              # 24 bits
        cases = (
            ("read", lambda r: r.read(25)),
            ("read_signed", lambda r: r.read_signed(25)),
            ("read_bytes", lambda r: r.read_bytes(4)),
            ("read_bitstring", lambda r: r.read_bitstring(25)),
            ("skip", lambda r: r.skip(25)),
            ("slice", lambda r: r.slice(4, 25)),
            ("set_bitpos", lambda r: r.set_bitpos(25)),
            ("read_cstring", lambda r: r.read_cstring(4)),         # no NUL, the 4th unit does not fit
            ("read_u16string", lambda r: r.read_u16string(3)),     # the 2nd unit is cut
        )
        for name, call in cases:
            for start in (0, 5, 8):
                with self.subTest(method=name, start=start):
                    reader = BitReader(data)
                    reader.set_bitpos(start)
                    with self.assertRaises(BitOverrun):
                        call(reader)
                    self.assertEqual(reader.pos, start)
                    self.assertEqual(reader.read(1), (data[start // 8] >> (7 - start % 8)) & 1,
                                     "and the reader still works from there")

    def test_string_readers_restore_pos_after_consuming_units(self):
        reader = BitReader(b"ABC")
        with self.assertRaises(BitOverrun) as ctx:
            reader.read_cstring(16)                                 # A, B, C read, the 4th unit is missing
        self.assertEqual(reader.pos, 0)
        self.assertEqual((ctx.exception.pos, ctx.exception.requested, ctx.exception.bit_length), (24, 8, 24),
                         "the exception names the unit that did not fit")
        reader = BitReader(b"ABCD")
        reader.set_bitpos(3)
        with self.assertRaises(BitOverrun) as ctx:
            reader.read_u16string(3)                                # one unit fits, the second is cut
        self.assertEqual(reader.pos, 3)
        self.assertEqual((ctx.exception.pos, ctx.exception.requested), (19, 16))
        # a string that does fit is unaffected, also right at the end of the stream
        reader = BitReader(b"AB\x00")
        self.assertEqual(reader.read_cstring(16), b"AB\x00")
        self.assertEqual(reader.remaining(), 0)
        reader = BitReader(b"\x00\x41\x00\x00")
        self.assertEqual(reader.read_u16string(128), [0x41, 0])

    def test_bad_arguments_are_library_bugs(self):
        for bad in (-1, 1.5, "3", None):
            with self.assertRaises(InternalError, msg=bad):
                BitReader(b"abc").read(bad)
        with self.assertRaises(InternalError):
            BitReader(b"abc", bit_length=25)
        with self.assertRaises(InternalError):
            BitReader("abc")
        with self.assertRaises(InternalError):
            BitReader(b"abc").set_bitpos(-1)


class TestWriterRefusals(unittest.TestCase):
    def test_write_raises_encode_error_when_the_value_does_not_fit(self):
        for value, n in ((2, 1), (256, 8), (1 << 32, 32), (-1, 8), (1, 0), (1 << 64, 64)):
            with self.assertRaises(EncodeError, msg=(value, n)):
                BitWriter().write(value, n)
        for value in (1.0, "1", None, b"\x01"):
            with self.assertRaises(EncodeError, msg=value):
                BitWriter().write(value, 8)
        writer = BitWriter()
        with self.assertRaises(EncodeError):
            writer.write(300, 8)
        self.assertEqual((writer.pos, writer.getvalue()), (0, b""), "a refused write must change nothing")

    def test_encode_error_is_an_mvar_error(self):
        self.assertTrue(issubclass(EncodeError, MvarError))

    def test_edge_values_fit(self):
        for n in (1, 7, 8, 9, 31, 32, 33, 63, 64):
            writer = BitWriter()
            writer.write((1 << n) - 1, n)
            writer.write(0, n)
            reader = BitReader(writer.getvalue())
            self.assertEqual(reader.read(n), (1 << n) - 1)
            self.assertEqual(reader.read(n), 0)

    def test_write_masked_masks_and_is_the_only_way_to_lose_bits(self):
        writer = BitWriter()
        writer.write_masked(0x1FF, 8)
        writer.write_masked(-1, 4)
        writer.write_masked(-2, 4)
        self.assertEqual(writer.getvalue().hex(), "fffe")
        with self.assertRaises(EncodeError):
            BitWriter().write_masked(1.5, 4)

    def test_negative_or_non_integer_widths_are_library_bugs(self):
        for bad in (-1, 1.5, None):
            with self.assertRaises(InternalError):
                BitWriter().write(0, bad)

    def test_getvalue_pads_but_never_truncates(self):
        writer = BitWriter()
        writer.write(0x1FF, 9)
        self.assertEqual(writer.getvalue(), b"\xff\x80")
        self.assertEqual(writer.getvalue(5), b"\xff\x80\x00\x00\x00")
        with self.assertRaises(CapacityError):
            writer.getvalue(1)
        self.assertEqual(BitWriter().getvalue(3), b"\x00\x00\x00")

    def test_getvalue_length_is_exact_when_the_bits_are_a_multiple_of_8(self):
        for bits in (0, 1, 7, 8, 9, 15, 16, 17, 24, 64, 65):
            writer = BitWriter()
            writer.write_masked(-1, bits)                             # all ones: a padding bug would show as extra bytes
            expected = (bits + 7) // 8
            with self.subTest(bits=bits):
                self.assertEqual(len(writer.getvalue()), expected)
                self.assertEqual(writer.bytespan(), expected)
                self.assertEqual(writer.bits_written, bits)
                self.assertEqual(writer.getbits().nbits, bits)
                self.assertEqual(len(writer.getbits().data), expected)
        self.assertEqual(BitWriter().getvalue(), b"")
        self.assertEqual(BitWriter().getbits(), BitString())

    def test_a_refused_string_changes_nothing(self):
        """The writer is left exactly as it was: no unit of a refused string is written (all-or-nothing)."""
        def state(writer):
            return (writer.pos, writer.bits_written, writer.getvalue())

        for lead in (0, 5):
            writer = BitWriter()
            writer.write(0x2A, lead + 8)
            before = state(writer)
            bad_u16 = ([0x41, 0x10000, 0], [0x41, -1, 0], [0x41, 1.5, 0], [0x41, "x", 0], [0x41, None, 0],
                       [0x41, 0x42, 0x43, 0, 0x44], [0x41] * 129, [], [0x41, 0x42])
            for units in bad_u16:
                with self.subTest(lead=lead, units=units):
                    with self.assertRaises(EncodeError):
                        writer.write_u16string(units, 128)
                    self.assertEqual(state(writer), before)
            for data in (b"ab\x00cd", b"x" * 17, b"", b"ab"):
                with self.subTest(lead=lead, data=data):
                    with self.assertRaises(EncodeError):
                        writer.write_cstring(data, 16)
                    self.assertEqual(state(writer), before)
            with self.assertRaises(EncodeError):
                writer.write_u16string([0x41, 0x42, 0x10000], 3)        # exactly maxlen units, the last one is bad
            self.assertEqual(state(writer), before)
        # the unit range is the unit width: 0xFFFF fits, 0x10000 does not
        writer = BitWriter()
        writer.write_u16string([0xFFFF, 0xFFFF, 0], 128)
        self.assertEqual(writer.getvalue(), b"\xff\xff\xff\xff\x00\x00")
        # a nonsense maximum is a library bug, not an encode error
        with self.assertRaises(InternalError):
            BitWriter().write_u16string([0], -1)
        with self.assertRaises(InternalError):
            BitWriter().write_cstring(b"\x00", 1.5)

    def test_overwriting_earlier_bits_keeps_the_high_water_mark(self):
        writer = BitWriter()
        writer.write(0xABCDEF, 24)
        writer.pos = 4
        writer.write(0, 4)
        self.assertEqual(writer.getvalue().hex(), "abcdef"[:1] + "0" + "cdef")
        self.assertEqual(writer.bits_written, 24)
        writer.pos = 100
        writer.write(1, 1)
        self.assertEqual(writer.bits_written, 101)
        self.assertEqual(len(writer.getvalue()), 13)
        self.assertEqual(bitio.get_bits(writer.getvalue(), 24, 76), 0, "the gap is zero filled")

    def test_write_to_bitpos_validates_and_restores_the_cursor(self):
        writer = BitWriter()
        writer.write(0, 16)
        with self.assertRaises(EncodeError):
            writer.write_to_bitpos(2, 3, 8)
        with self.assertRaises(InternalError):
            writer.write_to_bitpos(-1, 3, 1)
        self.assertEqual(writer.pos, 16)
        writer.write_to_bitpos(40, 8, 0xAA)                      # beyond the end extends with zeros
        self.assertEqual(writer.pos, 16)
        self.assertEqual(writer.getvalue().hex(), "0000" + "000000" + "aa")


class TestBitString(unittest.TestCase):
    def test_canonical_padding_and_equality(self):
        a = BitString(b"\xff\xff", 12)
        b = BitString(b"\xff\xf0", 12)
        self.assertEqual(a, b)
        self.assertEqual(a.data, b"\xff\xf0")
        self.assertEqual(hash(a), hash(b))
        self.assertNotEqual(a, BitString(b"\xff\xf0", 13))
        self.assertNotEqual(a, BitString(b"\xff\xe0", 12))
        self.assertEqual(len(a), 12)
        self.assertEqual(a.nbits, 12)
        self.assertNotEqual(a, b"\xff\xf0")

    def test_immutable(self):
        bs = BitString(b"\x01", 8)
        with self.assertRaises(AttributeError):
            bs.nbits = 4
        with self.assertRaises(AttributeError):
            bs.data = b""
        with self.assertRaises(AttributeError):
            del bs.nbits
        with self.assertRaises(AttributeError):
            bs.extra = 1

    def test_get_slice_concat_from_int(self):
        bs = BitString.from_int(0b1011001110001, 13)
        self.assertEqual(bs.get(0, 13), 0b1011001110001)
        self.assertEqual(bs.get(3, 4), 0b1001)
        self.assertEqual(bs.slice(3, 7), BitString.from_int(0b1001, 4))
        self.assertEqual(bs.slice(0, 0), BitString())
        self.assertEqual(bs.slice(0, 13), bs)
        self.assertEqual(bs.slice(0, 5) + bs.slice(5, 13), bs)
        self.assertEqual(bs.to_int(), 0b1011001110001)
        with self.assertRaises(BitOverrun):
            bs.get(10, 4)
        with self.assertRaises(BitOverrun):
            bs.get(-1, 2)
        with self.assertRaises(InternalError):
            bs.slice(5, 3)
        with self.assertRaises(EncodeError):
            BitString.from_int(8, 3)
        with self.assertRaises(InternalError):
            BitString(b"\x00", 9)

    def test_reader_slice_reaches_the_exact_end_and_not_one_bit_further(self):
        reader = BitReader(b"AB")
        self.assertEqual(reader.slice(8, 16), BitString(b"B"))
        self.assertEqual(reader.slice(0, 16), BitString(b"AB"))
        self.assertEqual(reader.slice(16, 16), BitString())
        self.assertEqual(reader.slice(3, 3), BitString())
        self.assertEqual(reader.pos, 0, "slice() does not move the reader")
        with self.assertRaises(BitOverrun):
            reader.slice(8, 17)
        with self.assertRaises(BitOverrun):
            reader.slice(17, 17)
        limited = BitReader(b"\xff\xff\xff", bit_length=20)
        self.assertEqual(limited.slice(4, 20), BitString.from_int(0xFFFF, 16))
        with self.assertRaises(BitOverrun):
            limited.slice(4, 21)
        # the same for the library's own get_bits, which also reads up to the last bit
        self.assertEqual(bitio.get_bits(b"AB", 8, 8), 0x42)
        self.assertEqual(bitio.get_bits(b"AB", 16, 0), 0)
        with self.assertRaises(BitOverrun):
            bitio.get_bits(b"AB", 9, 8)
        # BitString.get / slice reach their own last bit too
        bs = BitString.from_int(0b10110, 5)
        self.assertEqual(bs.get(0, 5), 0b10110)
        self.assertEqual(bs.get(5, 0), 0)
        self.assertEqual(bs.slice(5, 5), BitString())
        with self.assertRaises(BitOverrun):
            bs.get(1, 5)

    def test_reader_writer_round_trip_of_bitstrings(self):
        rng = random.Random(5)
        for _ in range(100):
            n = rng.randint(0, 200)
            bs = BitString.from_int(rng.getrandbits(n) if n else 0, n)
            lead = rng.randint(0, 7)
            writer = BitWriter()
            writer.write(0, lead)
            writer.write_bitstring(bs)
            writer.write(1, 1)
            reader = BitReader(writer.getvalue())
            reader.read(lead)
            self.assertEqual(reader.read_bitstring(n), bs)
            self.assertEqual(reader.read(1), 1)
            self.assertEqual(reader.slice(lead, lead + n), bs)
            self.assertEqual(reader.pos, lead + n + 1, "slice() must not move the reader")
        with self.assertRaises(InternalError):
            BitWriter().write_bitstring(b"\x00")


class TestCopyAndPickle(unittest.TestCase):
    """``BitString`` forbids attribute assignment, which used to break ``copy`` and ``pickle`` (they assign the slots)."""

    SAMPLES = (BitString(), BitString.from_int(5, 3), BitString.from_int(1, 1), BitString(b"\xff\xff", 12),
               BitString.from_int(0b1011001110001, 13), BitString(bytes(range(40)), 311),
               BitString.from_int((1 << 200) - 12345, 200))

    def test_copy_and_deepcopy(self):
        for bs in self.SAMPLES:
            with self.subTest(bits=bs.nbits):
                for clone in (copy.copy(bs), copy.deepcopy(bs)):
                    self.assertEqual(clone, bs)
                    self.assertEqual((clone.nbits, clone.data, hash(clone)), (bs.nbits, bs.data, hash(bs)))
                    self.assertIsInstance(clone, BitString)

    def test_pickle_every_protocol(self):
        for bs in self.SAMPLES:
            for protocol in range(0, pickle.HIGHEST_PROTOCOL + 1):
                with self.subTest(bits=bs.nbits, protocol=protocol):
                    clone = pickle.loads(pickle.dumps(bs, protocol))
                    self.assertEqual(clone, bs)
                    self.assertEqual((clone.nbits, clone.data), (bs.nbits, bs.data))
                    self.assertIsInstance(clone, BitString)

    def test_copies_stay_immutable_and_usable(self):
        for clone in (copy.deepcopy(self.SAMPLES[4]), pickle.loads(pickle.dumps(self.SAMPLES[4]))):
            with self.assertRaises(AttributeError):
                clone.nbits = 1
            self.assertEqual(clone.get(3, 4), 0b1001)
            self.assertEqual(clone.slice(0, 5) + clone.slice(5, 13), clone)
            writer = BitWriter()
            writer.write_bitstring(clone)
            self.assertEqual(writer.getbits(), clone)

    def test_containers_of_bit_strings_deep_copy(self):
        model = {"raw": self.SAMPLES[5], "ranges": [self.SAMPLES[1], self.SAMPLES[6]], "nested": {"a": self.SAMPLES[4]}}
        for clone in (copy.deepcopy(model), pickle.loads(pickle.dumps(model))):
            self.assertEqual(clone, model)
            self.assertIsNot(clone["ranges"], model["ranges"])

    def test_unpickling_goes_through_the_validating_constructor(self):
        # a payload that claims more bits than its data holds is refused like the constructor refuses it
        with self.assertRaises(InternalError):
            BitString(b"\x00", 9)
        self.assertEqual(BitString.__reduce__(BitString(b"\xff\xf0", 12))[1], (b"\xff\xf0", 12))


if __name__ == "__main__":
    unittest.main()
