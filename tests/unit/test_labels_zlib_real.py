"""U-04 (SPEC 9.3, 3.4, tier T1): zlib determinism of the compressed string tables in the real game variants.

Each real ``mpvr`` stream holds zlib-compressed string tables inside the bit stream, at any bit
alignment (RVT writes ``u32 BE uncompressed size`` then a zlib stream, ``78 DA``, level 9). The test
locates them by scanning every one of the 8 bit alignments for ``78 DA``, accepting a hit only when the
zlib stream inflates completely, the 4-byte big-endian size in front of it equals the inflated length
and a 11 to 13 bit size field further in front equals the compressed length plus 4. It then
recompresses the inflated bytes with Python's zlib at levels 7, 8 and 9 and compares with the original
bytes (expected identical on zlib 1.2.12 / Python 3.9.6 and zlib 1.3.1 / Python 3.13.13, SPEC 3.4).

The 5 distinct contents hold 9 streams: a 535-byte table that every file shares and 4 larger tables
(``test_user_funcs_and_recursion.bin`` has only the shared one). The test asserts at least 4 streams.
"""
import os
import sys
import unittest
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for _path in (HERE, os.path.join(REPO, "Addon")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import helpers_real  # noqa: E402
from mvarlib import bitio, blf  # noqa: E402

LEVELS = (7, 8, 9)

# (bit position in the stream, compressed length, uncompressed length) per distinct file, keyed by sha16
PINNED = {
    "e2fbf965263740b6": [(11582, 1784, 4784), (26052, 422, 535)],
    "c3332ebe3b18c948": [(10038, 311, 502), (12724, 422, 535)],
    "e11ad8489e0a1a3b": [(18054, 630, 1492), (23292, 422, 535)],
    "9deda304bbb14454": [(5845, 422, 535)],
    "9edf84633ceddf8d": [(9510, 207, 380), (11364, 422, 535)],
}


def find_zlib_streams(stream, nbits):
    """``[(bit_position, compressed_bytes, inflated_bytes)]`` for the zlib streams in ``stream[:nbits]``."""
    reader = bitio.BitReader(stream, nbits)
    found = {}
    for shift in range(8):
        whole = (nbits - shift) // 8
        if whole <= 0:
            continue
        aligned = reader.slice(shift, shift + whole * 8).data
        index = aligned.find(b"\x78\xda")
        while index >= 0:
            stream_bytes = aligned[index:]
            inflater = zlib.decompressobj()
            try:
                inflated = inflater.decompress(stream_bytes)
            except zlib.error:
                inflated = None
            if inflated is not None and inflater.eof and index >= 4:
                used = len(stream_bytes) - len(inflater.unused_data)
                prefix = int.from_bytes(aligned[index - 4:index], "big")
                bit = shift + 8 * index
                if prefix == len(inflated) and plausible_size_field(reader, bit - 32, used + 4):
                    found[bit] = (aligned[index:index + used], inflated)
            index = aligned.find(b"\x78\xda", index + 1)
    return [(bit, comp, inflated) for bit, (comp, inflated) in sorted(found.items())]


def plausible_size_field(reader, end_bit, expected):
    """A size field of 11 to 13 bits right before the u32 prefix holds the compressed size plus the 4-byte prefix."""
    for width in (11, 12, 13):
        if end_bit - width >= 0 and reader.slice(end_bit - width, end_bit).to_int() == expected:
            return True
    return False


class TestRealZlib(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.samples = helpers_real.distinct_samples(helpers_real.load_samples())
        cls.found = {}
        for sample in cls.samples:
            chunk = blf.parse(sample.data).find("mpvr")
            cls.found[sample.sha16] = find_zlib_streams(chunk.stream, chunk.stored_length * 8)

    def test_at_least_four_compressed_tables_are_found(self):
        total = sum(len(v) for v in self.found.values())
        self.assertGreaterEqual(total, 4)
        if helpers_real.require_samples():
            self.assertEqual(total, 9)
        with_streams = sum(1 for v in self.found.values() if v)
        self.assertGreaterEqual(with_streams, 4, "4 of the 5 distinct contents have a compressed table (SPEC 3.4)")
        sys.stdout.write("\nU-04: %d zlib streams in %d distinct files (zlib %s)\n" % (total, len(self.found), zlib.ZLIB_VERSION))

    def test_known_files_have_the_known_streams(self):
        for sample in self.samples:
            pinned = PINNED.get(sample.sha16)
            if pinned is None:
                continue
            with self.subTest(file=sample.name):
                got = [(bit, len(comp), len(inflated)) for bit, comp, inflated in self.found[sample.sha16]]
                self.assertEqual(got, pinned)

    def test_recompression_at_levels_7_to_9_reproduces_the_original_bytes(self):
        checked = 0
        for sample in self.samples:
            for bit, comp, inflated in self.found[sample.sha16]:
                for level in LEVELS:
                    with self.subTest(file=sample.name, bit=bit, level=level):
                        self.assertEqual(zlib.compress(inflated, level), comp,
                                         "zlib %s level %d does not reproduce the original compressor output"
                                         % (zlib.ZLIB_VERSION, level))
                        checked += 1
        self.assertGreaterEqual(checked, 4 * len(LEVELS))

    def test_the_streams_are_best_compression_zlib(self):
        """RVT compresses with Z_BEST_COMPRESSION: header 78 DA (SPEC 3.4); a faster level gives a different header or stream."""
        for sample in self.samples:
            for bit, comp, inflated in self.found[sample.sha16]:
                self.assertEqual(comp[:2], b"\x78\xda")
                self.assertEqual(zlib.compress(inflated, 1)[:2], b"\x78\x01")
                self.assertNotEqual(zlib.compress(inflated, 1), comp)

    def test_inflated_tables_are_nul_separated_utf8_text(self):
        """The inflated bytes are NUL-separated UTF-8 strings (several languages), the layout the label lookup assumes."""
        for sample in self.samples:
            for bit, comp, inflated in self.found[sample.sha16]:
                with self.subTest(file=sample.name, bit=bit):
                    text = inflated.decode("utf-8")
                    self.assertGreaterEqual(text.count("\x00"), 2)
                    self.assertTrue(text.endswith("\x00"))

    def test_scan_does_not_invent_streams(self):
        """Negative controls: a stream of zeros and a stream with 78 DA but no valid zlib data find nothing."""
        self.assertEqual(find_zlib_streams(bytes(512), 512 * 8), [])
        junk = bytes(8) + b"\x00\x00\x00\x10" + b"\x78\xda" + bytes(range(40)) + bytes(16)
        self.assertEqual(find_zlib_streams(junk, len(junk) * 8), [])
        good = zlib.compress(b"hello\x00world\x00" * 8, 9)
        body = len(b"hello\x00world\x00" * 8).to_bytes(4, "big") + good
        size_field = (len(good) + 4).to_bytes(2, "big")
        built = bytes(4) + size_field + body + bytes(8)
        self.assertEqual([(bit, len(c), len(i)) for bit, c, i in find_zlib_streams(built, len(built) * 8)],
                         [(8 * (6 + 4), len(good), 96)])
        shifted = bitio.BitWriter()
        shifted.write(0b101, 3)
        shifted.write_bytes(built)
        found = find_zlib_streams(shifted.getvalue(), shifted.bits_written)
        self.assertEqual([(bit, len(c)) for bit, c, _ in found], [(3 + 8 * 10, len(good))], "any bit alignment works")


if __name__ == "__main__":
    unittest.main()
