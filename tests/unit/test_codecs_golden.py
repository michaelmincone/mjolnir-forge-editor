"""U-05 (SPEC 9.3): the pure codecs against every golden vector of SPEC 4.10, plus property tests.

The vectors come from ``tests/golden/codec_vectors.json`` (G2: computed by the independent fixture builder's
own codec functions and cross-checked against the numbers printed in the spec text); the library's
``codecs.py`` was written separately from the spec text, so agreement here is a real two-implementation check.
Pure Python 3.9 to 3.13, standard library only.
"""
import json
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "Addon"))

from mvarlib import codecs, tables  # noqa: E402
from mvarlib.errors import DecodeError, EncodeError  # noqa: E402

with open(os.path.join(REPO, "tests", "golden", "codec_vectors.json"), "r", encoding="utf-8") as _fh:
    VEC = json.load(_fh)


class TestAxisBits(unittest.TestCase):
    def test_every_golden_row_in_all_three_variants(self):
        self.assertGreaterEqual(len(VEC["axis_bits"]), 20)
        for row in VEC["axis_bits"]:
            ranges = row["ranges"]
            with self.subTest(row["id"]):
                self.assertEqual([codecs.axis_bits_ceil(r) for r in ranges], row["ceil"])
                self.assertEqual([codecs.axis_bits_trunc(r) for r in ranges], row["trunc9999"])
                self.assertEqual([codecs.axis_bits_ceil_f32(r) for r in ranges], row["ceil_f32"])

    def test_printed_values_of_the_spec(self):
        self.assertEqual([codecs.axis_bits_ceil(r) for r in (1024.0, 1024.0, 1024.0)], [21, 21, 21])      # G-AX-1
        self.assertEqual([codecs.axis_bits_ceil(r) for r in (480.0, 690.0, 140.0)], [20, 21, 19])         # G-AX-2
        self.assertEqual([codecs.axis_bits_ceil(r) for r in (34.0, 34.2, 0.0)], [16, 17, 0])              # G-AX-4
        self.assertEqual(codecs.axis_bits_ceil(4369.07), 23)                                                # G-AX-5
        self.assertEqual(codecs.axis_bits_ceil(1.0e9), 23)
        self.assertEqual(codecs.axis_bits_ceil(float("inf")), 23)                                           # capped, never raises
        self.assertEqual(codecs.axis_bits_trunc(float("inf")), 23)
        self.assertEqual(codecs.axis_bits_ceil_f32(float("inf")), 23)

    def test_js_thresholds_ceil_gives_k_and_trunc_gives_k_plus_one(self):          # G-AX-3
        step = 0.00833333333 / 32 * 2
        for k in range(15, 23):
            rng = (2 ** k) * step
            with self.subTest(k=k):
                self.assertEqual(codecs.axis_bits_ceil(rng), k)
                self.assertEqual(codecs.axis_bits_trunc(rng), k + 1)
                self.assertEqual(codecs.axis_bits_ceil_f32(rng), k)

    def test_f32_step_thresholds(self):                                           # G-AX-6
        for k in range(15, 23):
            rng = codecs.f32((2 ** k) * 0.0005208333604969084)
            with self.subTest(k=k):
                self.assertEqual(codecs.axis_bits_ceil(rng), k + 1)
                self.assertEqual(codecs.axis_bits_trunc(rng), k + 1)
                self.assertEqual(codecs.axis_bits_ceil_f32(rng), k)

    def test_zero_range_reads_zero_bits(self):
        self.assertEqual((codecs.axis_bits_ceil(0.0), codecs.axis_bits_trunc(0.0), codecs.axis_bits_ceil_f32(0.0)), (0, 0, 0))
        self.assertEqual(codecs.bits_from_cells(0), 0)
        self.assertEqual(codecs.bits_from_cells(1), 0)
        self.assertEqual(codecs.bits_from_cells(2), 1)
        self.assertEqual(codecs.bits_from_cells(3), 2)
        self.assertEqual(codecs.bits_from_cells(0x800000), 23)
        self.assertEqual(codecs.bits_from_cells(0x800001), 24)

    def test_bits_from_cells_equals_ceil_log2(self):
        for n in list(range(2, 5000)) + [2 ** 20, 2 ** 20 + 1, 2 ** 23 - 1, 2 ** 23]:
            self.assertEqual(codecs.bits_from_cells(n), int(math.ceil(math.log(n, 2) - 1e-12)) if n & (n - 1) else n.bit_length() - 1)

    def test_hypotheses_one_triple_for_ordinary_bounds(self):
        self.assertEqual(codecs.axis_bit_hypotheses((-240.0, 240.0, -345.0, 345.0, -70.0, 70.0)), [(20, 21, 19)])
        self.assertEqual(codecs.axis_bit_hypotheses((0.0, 1024.0, 0.0, 1024.0, 0.0, 1024.0)), [(21, 21, 21)])

    def test_hypotheses_two_or_more_triples_at_a_threshold(self):
        lo = codecs.f32(2.870152638934087e-05)
        hi = codecs.f32(546.1333618164062)
        triples = codecs.axis_bit_hypotheses((lo, hi, 0.0, 480.0, 0.0, 140.0))
        self.assertGreaterEqual(len(triples), 2)
        self.assertEqual(len(set(triples)), len(triples))
        xs = sorted(set(t[0] for t in triples))
        self.assertEqual(xs, [20, 21])
        self.assertEqual(triples[0][0], 20)                                       # ceil on the double range is the primary

    def test_f32_threshold_has_a_minority_triple(self):
        rng = codecs.f32((2 ** 20) * 0.0005208333604969084)
        triples = codecs.axis_bit_hypotheses((0.0, rng, 0.0, 1.0, 0.0, 1.0))
        self.assertEqual(sorted(set(t[0] for t in triples)), [20, 21])

    def test_zero_range_axis_in_hypotheses(self):
        self.assertEqual(codecs.axis_bit_hypotheses((0.0, 34.0, 5.0, 5.0, 0.0, 34.2)), [(16, 0, 17)])


class TestPosition(unittest.TestCase):
    def test_every_golden_row(self):
        self.assertGreaterEqual(len(VEC["pos"]), 9)
        for row in VEC["pos"]:
            with self.subTest(row["id"]):
                fn = row["fn"]
                if fn == "pos_decode":
                    got = codecs.pos_decode(row["q"], row["bits"], row["min"], row["max"])
                    self.assertAlmostEqual(got, row["expect"], delta=max(row["tol"], 1e-15))
                elif fn == "pos_cell":
                    got = codecs.pos_cell(row["bits"], row["min"], row["max"])
                    self.assertAlmostEqual(got, row["expect"], delta=max(row["tol"], 1e-18))
                elif fn == "pos_encode":
                    if row["expect"] == "refused":
                        with self.assertRaises(EncodeError):
                            codecs.pos_encode(row["value"], row["bits"], row["min"], row["max"])
                    else:
                        self.assertEqual(codecs.pos_encode(row["value"], row["bits"], row["min"], row["max"]), row["expect"])
                elif fn == "pos_unchanged":
                    mn, mx, bits, q = row["min"], row["max"], row["bits"], row["q"]
                    value = codecs.pos_decode(q, bits, mn, mx) + row["blender_offset"]
                    self.assertLessEqual(abs(value - codecs.pos_decode(q, bits, mn, mx)), codecs.pos_tolerance(bits, mn, mx))
                    self.assertEqual(codecs.pos_encode(value, bits, mn, mx), row["plain_encode"])      # a plain encode would move the cell
                    self.assertEqual(codecs.pos_tolerance(bits, mn, mx), row["tolerance"])
                else:
                    self.fail("unknown vector function %r" % fn)

    def test_encode_refuses_instead_of_clamping(self):
        for bad in (-240.0001, 240.0, 240.5, float("nan"), float("inf"), -float("inf")):
            with self.subTest(v=bad):
                with self.assertRaises(EncodeError):
                    codecs.pos_encode(bad, 20, -240.0, 240.0)
        self.assertEqual(codecs.pos_encode(-240.0, 20, -240.0, 240.0), 0)
        self.assertEqual(codecs.pos_encode(239.99999, 20, -240.0, 240.0), (1 << 20) - 1)

    def test_zero_range_axis(self):
        self.assertEqual(codecs.pos_decode(0, 0, 5.0, 5.0), 5.0)
        self.assertEqual(codecs.pos_cell(0, 5.0, 5.0), 0.0)
        with self.assertRaises(EncodeError):                    # the interval [5, 5) is empty
            codecs.pos_encode(5.0, 0, 5.0, 5.0)

    def test_round_trip_when_float32_spacing_is_below_half_a_cell(self):
        mn, mx, bits = -240.0, 240.0, 20
        for q in (0, 1, 2, 12345, 524288, 524289, (1 << 20) - 2, (1 << 20) - 1):
            v = codecs.pos_decode(q, bits, mn, mx)
            self.assertEqual(codecs.pos_encode(v, bits, mn, mx), q)
            self.assertEqual(codecs.pos_encode(codecs.f32(v), bits, mn, mx), q)      # float32 spacing (3e-5) < half a cell (2.3e-4)

    def test_round_trip_is_not_the_identity_when_float32_is_too_coarse(self):
        mn, mx, bits = 3000.0, 7000.0, 23                        # the example of SPEC 4.2 (range 4000): why raw cells are kept
        self.assertEqual(codecs.axis_bit_hypotheses((mn, mx, mn, mx, mn, mx)), [(23, 23, 23)])
        bad = 0
        for q in range(0, 1 << 23, 4099):
            v = codecs.f32(codecs.pos_decode(q, bits, mn, mx))
            if codecs.pos_encode(v, bits, mn, mx) != q:
                bad += 1
        self.assertGreater(bad, 0)

    def test_tolerance_is_a_flat_milli_unit_for_plausible_boxes(self):
        self.assertEqual(codecs.pos_tolerance(20, -240.0, 240.0), 1.0e-3)
        self.assertEqual(codecs.pos_tolerance(21, -345.0, 345.0), 1.0e-3)
        self.assertEqual(codecs.pos_tolerance(19, -70.0, 70.0), 1.0e-3)
        self.assertEqual(codecs.pos_tolerance(10, -240.0, 240.0), 0.5 * 480.0 / 1024)         # big cells win
        self.assertGreater(codecs.pos_tolerance(23, 1.0e7, 1.1e7), 1.0e-3)                      # ulp32 term at huge coordinates

    def test_ulp32(self):
        self.assertEqual(codecs.ulp32(1.0), 2.0 ** -23)
        self.assertEqual(codecs.ulp32(0.5), 2.0 ** -24)
        self.assertEqual(codecs.ulp32(240.0), 2.0 ** (7 - 23))
        self.assertEqual(codecs.ulp32(-240.0), 2.0 ** (7 - 23))
        self.assertEqual(codecs.ulp32(0.0), 0.0)


class TestShapeDimension(unittest.TestCase):
    def test_decode_vectors(self):
        for row in VEC["shape_decode"]:
            with self.subTest(row["id"]):
                self.assertAlmostEqual(codecs.dim_decode(row["code"]), row["expect"], delta=max(row["tol"], 1e-12))

    def test_encode_vectors(self):
        for row in VEC["shape_encode"]:
            with self.subTest(row["id"]):
                self.assertEqual(codecs.dim_encode(row["value"]), row["expect"])

    def test_refused_vectors(self):
        for row in VEC["shape_refused"]:
            with self.subTest(row["id"]):
                with self.assertRaises(EncodeError):
                    codecs.dim_encode(row["value"])
        for bad in (float("nan"), float("inf"), -1.0e-9):
            with self.assertRaises(EncodeError):
                codecs.dim_encode(bad)

    def test_every_code_survives_float32_and_encode(self):
        self.assertTrue(VEC["shape_round_trip_all_2048"])
        for code in range(2048):
            self.assertEqual(codecs.dim_encode(codecs.f32(codecs.dim_decode(code))), code, code)

    def test_decode_is_monotonic_and_rejects_bad_codes(self):
        values = [codecs.dim_decode(c) for c in range(2048)]
        self.assertEqual(values, sorted(values))
        for bad in (-1, 2048, 1.5, None):
            with self.assertRaises(DecodeError):
                codecs.dim_decode(bad)


class TestAngle(unittest.TestCase):
    def test_decode_vectors(self):
        for row in VEC["angle_decode"]:
            with self.subTest(row["id"]):
                self.assertAlmostEqual(codecs.angle_decode(row["raw"]), row["expect"], delta=1e-12)
                self.assertAlmostEqual(codecs.angle_decode(row["raw"]), row["printed_js_form"], delta=row["tol"])       # the JS form agrees to 1e-6

    def test_encode_vectors(self):
        for row in VEC["angle_encode"]:
            with self.subTest(row["id"]):
                self.assertEqual(codecs.angle_encode(row["theta"]), row["expect"])

    def test_round_trip_all_codes(self):
        for raw in range(16384):
            self.assertEqual(codecs.angle_encode(codecs.angle_decode(raw)), raw)

    def test_non_finite_and_bad_codes(self):
        for bad in (float("nan"), float("inf"), -float("inf")):
            with self.assertRaises(EncodeError):
                codecs.angle_encode(bad)
        for bad in (-1, 16384):
            with self.assertRaises(DecodeError):
                codecs.angle_decode(bad)
        self.assertEqual(codecs.angle_encode(10.0), 16383)             # outside [-pi, pi] is clamped by the spec formula
        self.assertEqual(codecs.angle_encode(-10.0), 0)


class TestUpAxis(unittest.TestCase):
    def test_golden_vectors(self):
        for row in VEC["up_decode"]:
            with self.subTest(row["id"]):
                face, u, v = codecs.up_parts(row["code"])
                self.assertEqual((face, u, v), (row["face"], row["u"], row["v"]))
                vec = codecs.up_decode(row["code"])
                for got, want in zip(vec, row["expect"]):
                    self.assertAlmostEqual(got, want, delta=row["tol"])
                self.assertAlmostEqual(sum(c * c for c in vec), 1.0, places=12)
                self.assertEqual(u > 416, row["dead_zone"])

    def test_invalid_codes(self):
        for row in VEC["up_decode_error"]:
            with self.assertRaises(DecodeError):
                codecs.up_decode(row["code"])
        for code in (1048572, 1048573, 1048574, 1048575):
            self.assertGreater(codecs.up_parts(code)[0], 5)
            with self.assertRaises(DecodeError):
                codecs.up_decode(code)
        self.assertEqual(codecs.UP_CODE_MAX_VALID, 1048571)
        for bad in (-1, 1 << 20, "x"):
            with self.assertRaises(DecodeError):
                codecs.up_parts(bad)

    def test_constants_follow_the_closed_form(self):
        self.assertEqual(codecs.UP_STRIDE, (1 << 20) // 6)
        self.assertEqual(codecs.UP_N, math.isqrt(codecs.UP_STRIDE) - 1)

    def test_every_valid_face_start_decodes_to_a_unit_vector_on_its_axis(self):
        for face in range(6):
            vec = codecs.up_decode(face * codecs.UP_STRIDE + 208 * 417 + 208)          # the centre cell of the face
            axis = face % 3
            sign = 1 if face < 3 else -1
            self.assertGreater(sign * vec[axis], 0.99999)

    def test_no_code_decodes_to_exactly_plus_z(self):
        best = max(codecs.up_decode(2 * codecs.UP_STRIDE + 208 * 417 + 208)[2], 0)
        self.assertLess(best, 1.0)


class TestOrientation(unittest.TestCase):
    def test_vertical(self):
        fwd, up = codecs.reconstruct_orientation(1, None, 8192)
        self.assertEqual(up, (0.0, 0.0, 1.0))
        t = codecs.angle_decode(8192)
        self.assertAlmostEqual(fwd[0], math.cos(t), places=15)
        self.assertAlmostEqual(fwd[1], math.sin(t), places=15)
        self.assertEqual(fwd[2], 0.0)
        self.assertAlmostEqual(fwd[0], 1.0, places=6)                    # W1 slot 1: forward (1.0, 0.000192, 0)
        self.assertAlmostEqual(fwd[1], 0.000192, places=6)

    def test_tilted_is_orthonormal(self):
        for code in (0, 416, 173888, 174762, 436468, 436050, 1047698, 1048571, 3 * codecs.UP_STRIDE + 5000):
            for raw in (0, 4096, 8192, 12288, 16383):
                fwd, up = codecs.reconstruct_orientation(0, code, raw)
                self.assertAlmostEqual(sum(c * c for c in fwd), 1.0, places=12)
                self.assertAlmostEqual(sum(c * c for c in up), 1.0, places=12)
                self.assertAlmostEqual(sum(a * b for a, b in zip(fwd, up)), 0.0, places=12)

    def test_up_along_x_uses_the_y_reference(self):
        # face 0 centre cell: up is almost exactly +X, the +X reference would degenerate
        code = 0 * codecs.UP_STRIDE + 208 * 417 + 208
        fwd, up = codecs.reconstruct_orientation(0, code, 8192)
        self.assertGreater(up[0], 0.9999)
        self.assertAlmostEqual(sum(a * b for a, b in zip(fwd, up)), 0.0, places=12)

    def test_nearly_vertical_tilted_matches_the_vertical_case(self):
        vert, _ = codecs.reconstruct_orientation(1, None, 5000)
        tilt, up = codecs.reconstruct_orientation(0, 436468, 5000)       # up is 0.0024 off +Z
        for a, b in zip(vert, tilt):
            self.assertAlmostEqual(a, b, delta=5.0e-3)

    def test_invalid_up_code_raises(self):
        with self.assertRaises(DecodeError):
            codecs.reconstruct_orientation(0, 1048575, 0)


class TestViews(unittest.TestCase):
    def test_placement_view_file_reading(self):
        pv = codecs.placement_view(0xCC)                        # phased, both symmetries, placed at start, not game specific
        self.assertEqual(tuple(pv), (3, 3, True, False))
        self.assertEqual(tuple(codecs.placement_view(0x0C)), (0, 3, True, False))
        self.assertEqual(tuple(codecs.placement_view(0x04)), (0, 1, True, False))           # bit 2 = asymmetric only
        self.assertEqual(tuple(codecs.placement_view(0x08)), (0, 2, True, False))           # bit 3 = symmetric only
        self.assertEqual(tuple(codecs.placement_view(0x10)), (0, 0, False, False))          # bit 4 set = NOT placed at start
        self.assertEqual(tuple(codecs.placement_view(0x20)), (0, 0, True, True))
        self.assertEqual(codecs.placement_view(0x80).physics, 2)                             # the unused value stays 2
        self.assertEqual(codecs.placement_view(0x40).physics, 1)
        self.assertEqual(tuple(codecs.placement_view(0x00)), (0, 0, True, False))
        self.assertEqual(tuple(codecs.placement_view(0xFF)), (3, 3, False, True))
        self.assertEqual(codecs.placement_view(0x03), codecs.PlacementView(0, 0, True, False))   # bits 0, 1 are not decoded
        with self.assertRaises(DecodeError):
            codecs.placement_view(256)

    def test_placement_with_physics_keeps_every_other_bit(self):
        for byte in range(256):
            for physics in (0, 1, 3):
                out = codecs.placement_with_physics(byte, physics)
                self.assertEqual(out & 0x3F, byte & 0x3F)
                self.assertEqual(codecs.placement_view(out).physics, physics)
        with self.assertRaises(EncodeError):
            codecs.placement_with_physics(0, 4)

    def test_team_and_color(self):
        self.assertEqual(codecs.team_view(0), -1)
        self.assertEqual(codecs.team_view(1), 0)
        self.assertEqual(codecs.team_view(9), 8)
        self.assertEqual(codecs.team_raw(8), 9)
        self.assertEqual(codecs.team_raw(0), 1)
        with self.assertRaises(EncodeError):
            codecs.team_raw(-1)
        self.assertEqual(codecs.color_view(None), -1)
        self.assertEqual(codecs.color_view(7), 7)
        self.assertIsNone(codecs.color_raw(-1))
        self.assertEqual(codecs.color_raw(0), 0)
        with self.assertRaises(EncodeError):
            codecs.color_raw(8)                                   # neutral cannot be stored


class TestIdRows(unittest.TestCase):
    """G-ID-1..3: the object ids of SPEC 4.10 against the real G0 stock tables."""

    def test_ids_resolve_in_the_stock_tables(self):
        self.assertGreaterEqual(len(VEC["ids"]), 7)
        for row in VEC["ids"]:
            with self.subTest(row["id"]):
                self.assertEqual(row["object_id"], (row["folder"] << 8) | row["item"])
                self.assertEqual(tables.object_id_for_name(row["map"], row["display"]), row["object_id"])
                self.assertEqual(tables.object_name_for_id(row["map"], row["object_id"]), row["display"])
                if row.get("internal"):
                    self.assertEqual(tables.internal_name_for_id(row["map"], row["object_id"]), row["internal"])


class TestSizes(unittest.TestCase):
    def test_g_sz(self):
        sz = VEC["sizes"]
        self.assertEqual(sz["plain_file_length"], 0x30 + 0x2C0 + 0x7028 + 0x11)
        self.assertEqual(sz["eof_block_offset"], 0x7318)
        self.assertEqual(sz["stream_file_offset"], 0x2F0 + 36)
        self.assertEqual(sz["capacity_bits"], 0x7000 * 8)


if __name__ == "__main__":
    unittest.main()
