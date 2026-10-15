"""S1: ``tools/verify_star_output.py``, the independent check of a finished block-star file.

The star file is built here in memory by the library from the one real Breakneck sample (read in place, ``rb`` only, never
copied next to anything; without the file the module is skipped with a loud notice), exactly as the Blender glue hands the
blocks over. The checker must pass it, and it must catch each of the mistakes a bad writer could make (a changed original
slot, a wrong hash, a damaged trailer, a different quota row, a block that is not Fixed, another length). The temporary
files go to a private temp folder.
"""
import contextlib
import hashlib
import io
import os
import shutil
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
TOOLS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "tools")
sys.path.insert(0, TOOLS)

import helpers_g5 as h  # noqa: E402
import star_layout as sl  # noqa: E402
import verify_star_output as vso  # noqa: E402

from mvarlib.model import MapVariant  # noqa: E402

REAL_SHA256 = "e514a53b61977a897ac9dbf7225085aa01b5b255f3c8079b5938ef87579bb254"
CENTRE = (13.25, -15.75, 17.0)
BLOCK = sl.Footprint(1.0182, 1.0182, 1.0)


def require_real():
    if not h.g3.real_available():
        sys.stderr.write("\n" + "=" * 78 + "\nNOTICE: the real map variant %s is absent;\n"
                         "        test_verify_star_output is SKIPPED, not passed.\n" % h.g3.REAL_MVAR + "=" * 78 + "\n")
        raise unittest.SkipTest("NOTICE: the real map variant is absent (%s)" % h.g3.REAL_MVAR)


def refresh_hash(data):
    """Rewrite the SHA-1 of ``data`` the way the template's flavour does (plain_le32), so a tamper test isolates one fault."""
    out = bytearray(data)
    length = struct.unpack(">I", out[h.LENGTH_AT:h.LENGTH_AT + 4])[0]
    out[h.HASH_AT:h.HASH_AT + 20] = hashlib.sha1(struct.pack("<I", length) + bytes(out[h.STREAM_AT:h.STREAM_AT + length])).digest()
    return bytes(out)


def flip_stream_bit(data, bit):
    out = bytearray(data)
    out[h.STREAM_AT + bit // 8] ^= 0x80 >> (bit % 8)
    return bytes(out)


class StarCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_real()
        cls.template = h.g3.real_data()
        cls.sha_before = hashlib.sha256(cls.template).hexdigest()
        model = MapVariant.from_bytes(cls.template, None, "real")
        objects = h.objects_for(model)
        cells = sl.named_shape("pixel39")
        positions = sl.cell_positions(cells, BLOCK, CENTRE)
        blocks = [h.new_object("Star %03d" % i, "Block, 1x1", position=p, forward=(0.0, 1.0, 0.0), physics=1)
                  for i, p in enumerate(positions)]
        result = h.export(cls.template, objects + blocks, allow_unverified_rotation=True, raise_quota_max=True)
        assert result.ok, [e.message for e in result.errors]
        cls.star = result.data
        cls.dec = h.decode(cls.star)

    @classmethod
    def tearDownClass(cls):
        with open(h.g3.REAL_MVAR, "rb") as handle:
            after = hashlib.sha256(handle.read()).hexdigest()
        assert after == cls.sha_before == REAL_SHA256, "the real sample changed during the test"

    def run_check(self, output, **kwargs):
        kwargs.setdefault("shape", "pixel39")
        kwargs.setdefault("centre", CENTRE)
        checks, info = vso.check(self.template, output, "Block, 1x1", BLOCK, **kwargs)
        return checks, info

    def failed(self, output, **kwargs):
        checks, _info = self.run_check(output, **kwargs)
        return [c.name for c in checks if c.status == "FAIL"]


class TestAGoodStar(StarCase):
    def test_every_check_passes(self):
        checks, info = self.run_check(self.star)
        self.assertEqual([c.line() for c in checks if c.status == "FAIL"], [])
        self.assertGreaterEqual(len([c for c in checks if c.status == "PASS"]), 25)
        self.assertEqual(len(info["positions"]), 39)
        self.assertEqual(info["slots"], list(range(610, 649)))

    def test_the_lines_say_what_they_checked(self):
        text = "\n".join(c.line() for c in self.run_check(self.star)[0])
        for needle in ("file length unchanged", "trailer preserved: 29911 bytes", "plain_le32", "610 of 610 slots identical",
                       "bit-identical up to the first new slot", "39 x 'Block, 1x1'", "placement byte 0x4C", "row 63: [0, 0, 0] -> [0, 39, 39]",
                       "649 objects (template 610 + 39 new), limit 650", "UNVERIFIED in game"):
            self.assertIn(needle, text)

    def test_the_decoded_positions_are_the_star(self):
        _checks, info = self.run_check(self.star)
        expected = sl.cell_positions(sl.named_shape("pixel39"), BLOCK, CENTRE)
        match = sl.match_positions(expected, info["positions"], 0.0105)
        self.assertTrue(match.ok)
        self.assertLess(max(match.worst), 0.0048, "within one position step of the real file's axes")

    def test_the_preview_is_the_design(self):
        _checks, info = self.run_check(self.star)
        self.assertEqual(vso.ascii_preview(info["positions"], BLOCK), list(sl.NAMED_SHAPES["pixel39"]))
        self.assertEqual(vso.ascii_preview([], BLOCK), [])

    def test_without_a_design_the_position_check_is_left_out_not_failed(self):
        checks, _info = vso.check(self.template, self.star, "Block, 1x1", BLOCK)
        self.assertEqual([c for c in checks if c.status == "FAIL"], [])
        self.assertFalse([c for c in checks if "centred at" in c.name])

    def test_a_copy_of_the_template_has_no_new_slots_and_nothing_to_pass_as_a_star(self):
        checks, info = vso.check(self.template, self.template, "Block, 1x1", BLOCK)
        names = [c.name for c in checks if c.status == "FAIL"]
        self.assertTrue(any("new slots are 0" in n for n in names), names)
        self.assertEqual(info["positions"], [])


class TestEachMistakeIsCaught(StarCase):
    def test_a_changed_original_slot_even_with_a_correct_hash(self):
        first_slot_start = self.dec["slot_ranges"][5][0]
        bad = refresh_hash(flip_stream_bit(self.star, first_slot_start + 40))
        failed = self.failed(bad)
        self.assertTrue(any("bit-identical up to the first new slot" in n for n in failed), failed)

    def test_a_wrong_hash(self):
        bad = bytearray(self.star)
        bad[h.HASH_AT] ^= 0xFF
        failed = self.failed(bytes(bad))
        self.assertTrue(any("SHA-1 of the output" in n for n in failed), failed)

    def test_a_trailer_that_is_not_the_templates(self):
        bad = bytearray(self.star)
        bad[40000] = 1
        failed = self.failed(bytes(bad))
        self.assertTrue(any("trailer preserved" in n for n in failed), failed)

    def test_another_file_length(self):
        failed = self.failed(self.star + b"\x00")
        self.assertTrue(any("file length unchanged" in n for n in failed), failed)

    def test_a_block_that_is_not_fixed(self):
        slot = 620
        start, _end = self.dec["slot_ranges"][slot]
        span = [s for s in self.dec["slot_field_spans"][slot] if s[0] == "placement"][0]
        bad = refresh_hash(flip_stream_bit(self.star, span[1]))                        # the top bit of the placement byte: Fixed (01) becomes Phased (11)
        failed = self.failed(bad, shape=None, centre=None)
        self.assertTrue(any("Fixed" in n for n in failed), failed)

    def test_a_block_that_moved_off_the_star(self):
        slot = 630
        pos_x = [s for s in self.dec["slot_field_spans"][slot] if s[0] == "pos_x"][0]
        bad = refresh_hash(flip_stream_bit(self.star, pos_x[1] + 3))                   # a high bit of the x cell: some 2,500 units away
        failed = self.failed(bad)
        self.assertTrue(any("the decoded blocks are the star" in n for n in failed), failed)

    def test_a_quota_row_that_is_not_the_blocks(self):
        row = self.dec["sections"]["quotas"] + 10 * vso.QUOTA_BITS + 23                  # the last bit of row 10's placed byte
        bad = refresh_hash(flip_stream_bit(self.star, row))
        failed = self.failed(bad)
        self.assertTrue(any("only the block's quota row changed" in n for n in failed), failed)

    def test_a_quota_maximum_that_was_not_raised(self):
        # the block row left at (0, 0, 39): the maximum is below the count, and the check expects the raised maximum
        span = self.dec["sections"]["quotas"] + 63 * vso.QUOTA_BITS + 8                  # first bit of the maximum byte
        bad = bytearray(self.star)
        value = int.from_bytes(bad[h.STREAM_AT:h.STREAM_END], "big")
        shift = h.STREAM_BITS - span - 8
        value &= ~(0xFF << shift)
        bad[h.STREAM_AT:h.STREAM_END] = value.to_bytes(0x7000, "big")
        failed = self.failed(refresh_hash(bytes(bad)))
        self.assertTrue(any("only the block's quota row changed" in n for n in failed), failed)

    def test_a_different_flavour_of_the_hash(self):
        length = struct.unpack(">I", self.star[h.LENGTH_AT:h.LENGTH_AT + 4])[0]
        bad = bytearray(self.star)
        bad[h.HASH_AT:h.HASH_AT + 20] = hashlib.sha1(bytes(self.star[h.STREAM_AT:h.STREAM_AT + length])).digest()       # payload only
        failed = self.failed(bytes(bad))
        self.assertTrue(any("SHA-1 of the output" in n for n in failed), failed)

    def test_an_object_count_over_the_limit_is_judged_by_the_object_count(self):
        checks, _info = self.run_check(self.star)
        line = [c for c in checks if c.name.startswith("object count")][0]
        self.assertEqual(line.status, "PASS")
        self.assertIn("limit 650", line.detail)


class TestCommandLine(StarCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mjolnir-verify-star-")
        self.out = os.path.join(self.tmp, "star.mvar")
        with open(self.out, "wb") as fh:
            fh.write(self.star)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_main(self, argv):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = vso.main(argv)
        return code, out.getvalue()

    def test_exit_zero_and_a_result_line(self):
        code, text = self.run_main([h.g3.REAL_MVAR, self.out, "--shape", "pixel39", "--center", "13.25,-15.75,17.0", "--preview"])
        self.assertEqual(code, 0, text)
        self.assertIn("RESULT: OK", text)
        self.assertIn("....#....", text)
        self.assertIn("front view of the decoded blocks", text)

    def test_exit_one_when_a_check_fails(self):
        bad = os.path.join(self.tmp, "bad.mvar")
        with open(bad, "wb") as fh:
            fh.write(self.star[:-1] + b"\x01")
        code, text = self.run_main([h.g3.REAL_MVAR, bad])
        self.assertEqual(code, 1, text)
        self.assertIn("[FAIL] trailer preserved", text)
        self.assertIn("RESULT: FAILED", text)

    def test_json_prints_the_positions_and_nothing_else(self):
        import json
        code, text = self.run_main([h.g3.REAL_MVAR, self.out, "--json"])
        self.assertEqual(code, 0)
        data = json.loads(text)
        self.assertEqual(len(data["positions"]), 39)
        self.assertEqual(data["block"], "Block, 1x1")
        self.assertEqual(data["footprint"], [1.0182, 1.0182, 1.0])

    def test_usage_problems_exit_two(self):
        for argv in ([], [h.g3.REAL_MVAR], [h.g3.REAL_MVAR, os.path.join(self.tmp, "missing.mvar")],
                     [h.g3.REAL_MVAR, self.out, "--shape", "pixel39"], [h.g3.REAL_MVAR, self.out, "--center", "1,2,3"],
                     [h.g3.REAL_MVAR, self.out, "--footprint", "1,2"], [h.g3.REAL_MVAR, self.out, "--shape", "nope", "--center", "1,2,3"]):
            code, _text = self.run_main(argv)
            self.assertEqual(code, 2, argv)

    def test_nothing_is_written_and_the_inputs_are_untouched(self):
        before = sorted(os.listdir(self.tmp))
        self.run_main([h.g3.REAL_MVAR, self.out])
        self.assertEqual(sorted(os.listdir(self.tmp)), before)
        with open(self.out, "rb") as fh:
            self.assertEqual(fh.read(), self.star)


if __name__ == "__main__":
    unittest.main()
