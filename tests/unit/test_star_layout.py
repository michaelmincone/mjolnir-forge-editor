"""S1 preparation: the pure star geometry of ``tools/star_layout.py`` (NOTES.md D10 / D10a).

Pins every property the star must have before any Blender or library code is involved: the cells are the true
five-pointed star sampled at cell centres (symmetric to the last bit, five tips, connected, no duplicates, 60 to
120 cells by default, deterministic), the positions put neighbouring blocks exactly one footprint apart (touching,
never overlapping), the bounds check judges the mesh box with a margin and the library's ``[min, max)`` rule, and
the read-back tolerance is the one derived from SPEC 4.1 / 4.2. Pure Python, standard library only, nothing is
written anywhere.
"""
import ast
import importlib.util
import itertools
import math
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TOOL = os.path.join(REPO, "tools", "star_layout.py")


def load_module():
    spec = importlib.util.spec_from_file_location("star_layout_under_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sl = load_module()

SQUARE = sl.Footprint(1.0, 1.0, 1.0)
REAL_LIKE = sl.Footprint(1.0182, 1.0182, 1.0)                    # the shape of the measured "Block, 1x1" mesh box
STANDS_ON_ORIGIN = sl.Footprint(1.0, 1.0, 1.0, (0.0, 0.0, 0.5))   # the synthetic stand-in cube
ODD_SIZED = sl.Footprint(2.0, 0.5, 0.25, (0.1, -0.2, 0.3))
SWEEP = list(range(sl.MIN_GRID, 40))


def neighbours4(cell):
    return [(cell[0] + dx, cell[1] + dz) for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1))]


def neighbours8(cell):
    return [(cell[0] + dx, cell[1] + dz) for dx in (-1, 0, 1) for dz in (-1, 0, 1) if (dx, dz) != (0, 0)]


def components(cells, neighbours):
    todo = set(cells)
    count = 0
    while todo:
        count += 1
        stack = [todo.pop()]
        while stack:
            for other in neighbours(stack.pop()):
                if other in todo:
                    todo.remove(other)
                    stack.append(other)
    return count


class TestPolygon(unittest.TestCase):
    def test_ten_vertices_alternating_outer_and_inner_radius(self):
        poly = sl.star_polygon(10.0)
        self.assertEqual(len(poly), 10)
        radii = [math.hypot(x, y) for x, y in poly]
        for k, radius in enumerate(radii):
            self.assertAlmostEqual(radius, 10.0 if k % 2 == 0 else 10.0 * sl.INNER_RATIO, places=9, msg="vertex %d" % k)

    def test_apex_is_straight_up_and_the_polygon_is_mirror_symmetric_to_the_last_bit(self):
        poly = sl.star_polygon(8.5)
        self.assertEqual(poly[0], (0.0, 8.5))
        self.assertEqual(poly[5][0], 0.0)
        mirrored = sorted((-x, y) for x, y in poly)
        self.assertEqual(sorted(poly), mirrored)

    def test_inner_ratio_is_the_golden_one_of_the_regular_pentagram(self):
        self.assertAlmostEqual(sl.INNER_RATIO, 0.3819660112501051, places=15)
        # the notch lies on the line joining the two tips next to it: tip(k) - tip(k+2) chord crosses at INNER_RATIO
        poly = sl.star_polygon(1.0)
        a, b = poly[2], poly[8]                                   # the two upper tips (right, left)
        self.assertAlmostEqual(a[1], b[1], places=12)
        self.assertGreater(a[0], 0)

    def test_the_area_matches_the_closed_form(self):
        radius = 7.0
        poly = sl.star_polygon(radius)
        shoelace = 0.5 * abs(sum(poly[i][0] * poly[(i + 1) % 10][1] - poly[(i + 1) % 10][0] * poly[i][1]
                                 for i in range(10)))
        self.assertAlmostEqual(shoelace, 5.0 * radius * radius * sl.INNER_RATIO * math.sin(math.radians(36.0)), places=9)

    def test_point_in_polygon_basics(self):
        poly = sl.star_polygon(10.0)
        self.assertTrue(sl.point_in_polygon(0.0, 0.0, poly))
        self.assertTrue(sl.point_in_polygon(0.0, 9.0, poly))                      # inside the apex
        self.assertFalse(sl.point_in_polygon(0.0, 10.5, poly))                    # above the apex
        self.assertFalse(sl.point_in_polygon(0.0, -9.0, poly))                    # below the notch between the legs
        self.assertFalse(sl.point_in_polygon(6.0, 6.0, poly))                     # in the notch between apex and right tip
        self.assertTrue(sl.point_in_polygon(8.0, 3.0, poly))                      # inside the right tip

    def test_bad_arguments_are_refused(self):
        for radius in (0, -1.0, float("nan"), float("inf"), "x", None):
            with self.assertRaises(sl.LayoutError):
                sl.star_polygon(radius)
        for ratio in (0.0, 1.0, 1.5, -0.1):
            with self.assertRaises(sl.LayoutError):
                sl.star_polygon(1.0, ratio)


class TestCells(unittest.TestCase):
    def test_the_default_star_has_between_60_and_120_cells(self):
        cells = sl.star_cells()
        self.assertEqual(sl.DEFAULT_GRID, 17)
        self.assertGreaterEqual(len(cells), 60)
        self.assertLessEqual(len(cells), 120)
        self.assertEqual(len(cells), 80)                           # pinned: a change of the sampling rule is a decision

    def test_count_follows_the_area_of_the_star_for_every_grid_size(self):
        # area of the star = 5 R r sin 36 degrees with R = n / 2 cells; each cell has area 1
        for n in SWEEP:
            area = 5.0 * (n / 2.0) ** 2 * sl.INNER_RATIO * math.sin(math.radians(36.0))
            count = len(sl.star_cells(n))
            self.assertLess(abs(count - area), 0.18 * area + 4, "n=%d count=%d area=%.1f" % (n, count, area))

    def test_larger_grids_give_more_cells(self):
        counts = [len(sl.star_cells(n)) for n in range(7, 40, 2)]
        self.assertEqual(counts, sorted(counts))
        self.assertEqual(len(set(counts)), len(counts))

    def test_no_duplicate_cells_and_all_inside_the_grid(self):
        for n in SWEEP:
            for mode in sl.MODES:
                cells = sl.star_cells(n, mode)
                self.assertEqual(len(cells), len(set(cells)), "n=%d %s" % (n, mode))
                for ix, iz in cells:
                    self.assertTrue(0 <= ix < n and 0 <= iz < n, (n, mode, ix, iz))
                    self.assertIsInstance(ix, int)
                    self.assertIsInstance(iz, int)

    def test_deterministic_and_in_reading_order(self):
        first = sl.star_cells(17)
        self.assertEqual(first, sl.star_cells(17))
        self.assertEqual(first, sorted(first, key=lambda c: (-c[1], c[0])))
        self.assertEqual(first[0], (8, 16))                        # the apex is the first cell
        self.assertEqual(sl.star_cells(17, "outline"), sl.star_cells(17, "outline"))

    def test_symmetric_about_the_vertical_axis_for_every_grid_size_exactly(self):
        for n in SWEEP:
            for mode in sl.MODES:
                cells = set(sl.star_cells(n, mode))
                mirrored = set((n - 1 - ix, iz) for ix, iz in cells)
                self.assertEqual(cells, mirrored, "n=%d %s" % (n, mode))

    def test_upright_apex_up_the_star_is_wider_in_the_upper_half(self):
        for n in (15, 17, 19, 21):
            cells = sl.star_cells(n)
            top = max(c[1] for c in cells)
            self.assertEqual(top, n - 1)                           # the apex touches the top row
            apex_row = [c for c in cells if c[1] == top]
            self.assertEqual(apex_row, [((n - 1) // 2, top)], "a single apex cell on the axis for odd n=%d" % n)
            widest_row = max(set(c[1] for c in cells), key=lambda z: len([c for c in cells if c[1] == z]))
            self.assertGreater(widest_row, (n - 1) / 2.0, "the arms are above the middle (n=%d)" % n)
            self.assertLess(min(c[1] for c in cells), (n - 1) / 2.0 - 3, "legs reach below the middle (n=%d)" % n)

    def test_exactly_five_tips(self):
        for n in (15, 17, 19):
            cells = sl.star_cells(n)
            tips = sl.tip_cells(cells, n)
            self.assertEqual(len(tips), 5)
            self.assertEqual(len(set(tips)), 5, "five distinct tip cells (n=%d)" % n)
            self.assertTrue(set(tips) <= set(cells))
            middle = (n - 1) / 2.0
            reach = [math.hypot(c[0] - middle, c[1] - middle) for c in tips]
            self.assertGreater(min(reach), 0.75 * (n / 2.0), "every tip is far from the centre (n=%d)" % n)
            self.assertEqual(tips[0], ((n - 1) // 2, n - 1), "the first tip is the apex")
            by_mirror = set((n - 1 - ix, iz) for ix, iz in tips)
            self.assertEqual(by_mirror, set(tips))

    def test_the_tips_are_the_only_dead_ends_of_the_default_star(self):
        cells = set(sl.star_cells(17))
        dead_ends = sorted(c for c in cells if sum(1 for o in neighbours4(c) if o in cells) == 1)
        self.assertEqual(dead_ends, sorted(sl.tip_cells(sorted(cells), 17)))

    def test_the_notches_between_the_tips_are_empty(self):
        n = 17
        cells = set(sl.star_cells(n))
        middle = (n - 1) / 2.0
        radius = n / 2.0
        for k in range(5):
            angle = math.radians(54.0 - 72.0 * k)                  # the five notch directions
            x = middle + 0.62 * radius * math.cos(angle)
            z = middle + 0.62 * radius * math.sin(angle)
            self.assertNotIn((int(round(x)), int(round(z))), cells, "notch %d" % k)

    def test_connectivity(self):
        for n in range(11, 32):
            cells = sl.star_cells(n)
            self.assertEqual(components(cells, neighbours8), 1, "8-connected (n=%d)" % n)
        for n in (15, 16, 17, 18, 19):
            self.assertEqual(components(sl.star_cells(n), neighbours4), 1, "4-connected (n=%d)" % n)

    def test_the_grids_auto_can_choose_are_pinned_to_one_piece_under_8_connectivity(self):
        """The shapes that can actually be built (D10a: 17, 15, 13, 11, 9; filled and outline) are one piece when a corner
        counts as touching. Face-to-face (4-connected) holds for the filled star on every auto grid EXCEPT 11, whose two
        feet touch the legs at a corner only; that is the grid the real Breakneck file gets (34 blocks), so it is pinned
        here and documented in docs/mvar/STAR_BUILD.md rather than left to chance."""
        for mode in sl.MODES:
            for n in sl.AUTO_GRIDS:
                self.assertEqual(components(sl.star_cells(n, mode), neighbours8), 1, "8-connected: %s grid %d" % (mode, n))
        for n in sl.AUTO_GRIDS:
            cells = set(sl.star_cells(n))
            lonely = sorted(c for c in cells if not any(o in cells for o in neighbours4(c)))
            if n != 11:
                self.assertEqual(components(cells, neighbours4), 1, "filled grid %d is 4-connected" % n)
                self.assertEqual(lonely, [], "grid %d" % n)
                continue
            self.assertEqual(components(cells, neighbours4), 3, "grid 11: the body and two feet")
            self.assertEqual(len(lonely), 2, "grid 11: exactly the two feet have no face neighbour")
            self.assertEqual(set((10 - ix, iz) for ix, iz in lonely), set(lonely), "the feet are mirror images")
            for foot in lonely:
                self.assertEqual(sum(1 for o in neighbours8(foot) if o in cells), 1, "each foot touches the leg at one corner")
            self.assertEqual(len(cells), 34)

    def test_outline_is_a_connected_ring_inside_the_filled_star(self):
        for n in (15, 17, 19, 23):
            filled = set(sl.star_cells(n))
            outline = set(sl.star_cells(n, "outline"))
            self.assertTrue(outline < filled)
            self.assertEqual(components(outline, neighbours8), 1)
            for cell in outline:
                self.assertTrue(any(o not in filled for o in neighbours4(cell)), "outline cell with no outside neighbour")
                self.assertGreaterEqual(sum(1 for o in neighbours8(cell) if o in outline), 1, "ring cell %r" % (cell,))
            # a one-cell-wide tip is a spike, not a ring: the only cells with a single neighbour are tips
            ends = set(c for c in outline if sum(1 for o in neighbours8(c) if o in outline) == 1)
            self.assertTrue(ends <= set(sl.tip_cells(sorted(outline), n)), "dead ends other than tips at n=%d: %r" % (n, ends))
            for cell in filled - outline:
                self.assertTrue(all(o in filled for o in neighbours4(cell)), "interior cell touches the outside")

    def test_bad_grid_sizes_and_modes_are_refused(self):
        for n in (0, 1, 4, 65, -3, 17.0, "17", None, True):
            with self.assertRaises(sl.LayoutError, msg=repr(n)):
                sl.star_cells(n)
        with self.assertRaises(sl.LayoutError):
            sl.star_cells(17, "hollow")
        with self.assertRaises(sl.LayoutError):
            sl.tip_cells([], 17)


class TestAutoGrid(unittest.TestCase):
    def test_the_largest_odd_grid_that_fits(self):
        counts = dict((n, len(sl.star_cells(n))) for n in sl.AUTO_GRIDS)
        self.assertEqual(counts, {17: 80, 15: 66, 13: 53, 11: 34, 9: 24})
        self.assertEqual(sl.fit_grid(1000), 17)
        self.assertEqual(sl.fit_grid(80), 17)
        self.assertEqual(sl.fit_grid(79), 15)
        self.assertEqual(sl.fit_grid(66), 15)
        self.assertEqual(sl.fit_grid(40), 11, "the room of the real Breakneck file: 650 - 610")
        self.assertEqual(sl.fit_grid(34), 11)
        self.assertEqual(sl.fit_grid(33), 9)
        self.assertEqual(sl.fit_grid(24), 9)
        self.assertIsNone(sl.fit_grid(23))
        self.assertIsNone(sl.fit_grid(0))

    def test_outline_fits_more_in_the_same_room(self):
        self.assertEqual(sl.fit_grid(40, "outline"), 15, "an outline of grid 15 has exactly 40 cells")
        self.assertEqual(len(sl.star_cells(15, "outline")), 40)
        self.assertEqual(sl.fit_grid(39, "outline"), 13)
        self.assertEqual(sl.fit_grid(19, "outline"), None)
        self.assertEqual(sl.fit_grid(20, "outline"), 9)

    def test_the_result_never_exceeds_the_room_and_is_the_largest_such(self):
        for room in range(0, 120):
            for mode in sl.MODES:
                n = sl.fit_grid(room, mode)
                if n is None:
                    self.assertGreater(len(sl.star_cells(min(sl.AUTO_GRIDS), mode)), room)
                    continue
                self.assertLessEqual(len(sl.star_cells(n, mode)), room)
                for bigger in (g for g in sl.AUTO_GRIDS if g > n):
                    self.assertGreater(len(sl.star_cells(bigger, mode)), room)

    def test_custom_sizes_and_bad_modes(self):
        self.assertEqual(sl.fit_grid(52, "filled", sizes=(13, 12, 11)), 12)
        with self.assertRaises(sl.LayoutError):
            sl.fit_grid(60, "hollow")

    def test_auto_sizes_are_odd_and_sorted_by_use(self):
        self.assertTrue(all(n % 2 == 1 for n in sl.AUTO_GRIDS))
        self.assertEqual(sl.AUTO_GRIDS[0], sl.DEFAULT_GRID)


class TestRender(unittest.TestCase):
    def test_the_default_star_as_text(self):
        rows = sl.render_cells(sl.star_cells())
        self.assertEqual(len(rows), 15)
        self.assertEqual(set(len(r) for r in rows), set([15]))
        self.assertEqual(rows[0], "." * 7 + "#" + "." * 7, "a single apex block on the axis")
        self.assertEqual(sum(r.count("#") for r in rows), 80)
        self.assertTrue(all(r == r[::-1] for r in rows), "mirror symmetric")
        self.assertEqual(rows[:3], [rows[0]] * 3, "the apex is three blocks tall")
        self.assertEqual(rows[3], "." * 6 + "###" + "." * 6)
        self.assertEqual(rows[6], "#" * 15, "the arms are one full row wide")

    def test_the_text_is_the_cells_and_nothing_else(self):
        for n in (9, 11, 13, 17):
            for mode in sl.MODES:
                cells = sl.star_cells(n, mode)
                rows = sl.render_cells(cells, on="X", off=" ")
                x0 = min(c[0] for c in cells)
                z1 = max(c[1] for c in cells)
                rebuilt = set((x0 + col, z1 - row) for row, text in enumerate(rows) for col, ch in enumerate(text) if ch == "X")
                self.assertEqual(rebuilt, set(cells), (n, mode))

    def test_no_cells_is_refused(self):
        with self.assertRaises(sl.LayoutError):
            sl.render_cells([])


class TestFootprint(unittest.TestCase):
    def test_valid_footprint(self):
        fp = sl.Footprint(1, 2, 3, (0, 0, 1.5))
        self.assertEqual((fp.width, fp.depth, fp.height, fp.offset), (1.0, 2.0, 3.0, (0.0, 0.0, 1.5)))
        self.assertEqual(fp, sl.Footprint(1.0, 2.0, 3.0, (0.0, 0.0, 1.5)))
        self.assertNotEqual(fp, sl.Footprint(1.0, 2.0, 3.0))
        self.assertEqual(hash(fp), hash(sl.Footprint(1.0, 2.0, 3.0, (0.0, 0.0, 1.5))))
        self.assertIn("1 x 2 x 3", repr(fp))

    def test_invalid_footprints_are_refused(self):
        for args in ((0, 1, 1), (1, -1, 1), (1, 1, float("nan")), (float("inf"), 1, 1), ("1", 1, 1), (True, 1, 1)):
            with self.assertRaises(sl.LayoutError, msg=repr(args)):
                sl.Footprint(*args)
        for offset in ((0, 0), (0, 0, float("nan")), (0, 0, 0, 0)):
            with self.assertRaises(sl.LayoutError, msg=repr(offset)):
                sl.Footprint(1, 1, 1, offset)


class TestPositions(unittest.TestCase):
    def positions(self, fp, centre=(10.0, -20.0, 30.0), n=17):
        cells = sl.star_cells(n)
        return cells, sl.cell_positions(cells, fp, centre)

    def test_one_position_per_cell_in_the_same_order(self):
        cells, pos = self.positions(REAL_LIKE)
        self.assertEqual(len(pos), len(cells))
        self.assertEqual(len(set(pos)), len(pos), "no two blocks at the same place")

    def test_spacing_equals_the_block_size(self):
        for fp in (SQUARE, REAL_LIKE, STANDS_ON_ORIGIN, ODD_SIZED):
            cells, pos = self.positions(fp)
            where = dict(zip(cells, pos))
            horizontal = vertical = 0
            for (ix, iz), p in where.items():
                right = where.get((ix + 1, iz))
                if right is not None:
                    horizontal += 1
                    self.assertAlmostEqual(right[0] - p[0], fp.width, places=9)
                    self.assertAlmostEqual(right[1], p[1], places=12)
                    self.assertAlmostEqual(right[2], p[2], places=12)
                above = where.get((ix, iz + 1))
                if above is not None:
                    vertical += 1
                    self.assertAlmostEqual(above[2] - p[2], fp.height, places=9)
                    self.assertAlmostEqual(above[0], p[0], places=12)
            self.assertGreater(horizontal, 40)
            self.assertGreater(vertical, 40)

    def test_neighbouring_blocks_touch_and_never_overlap(self):
        for fp in (SQUARE, REAL_LIKE, ODD_SIZED):
            cells, pos = self.positions(fp)
            boxes = sl.mesh_boxes(pos, fp)
            eps = 1e-9
            touching = 0
            for (i, a), (j, b) in itertools.combinations(enumerate(boxes), 2):
                overlap = [min(a[1][k], b[1][k]) - max(a[0][k], b[0][k]) for k in range(3)]
                self.assertFalse(all(o > eps for o in overlap), "blocks %d and %d overlap (%r)" % (i, j, overlap))
                if abs(overlap[0] - 0.0) < eps and overlap[1] > eps and overlap[2] > eps:
                    touching += 1
                if abs(overlap[2] - 0.0) < eps and overlap[0] > eps and overlap[1] > eps:
                    touching += 1
            self.assertGreater(touching, 100, "face-touching pairs exist (%r)" % fp)

    def test_all_blocks_share_one_plane_and_the_star_is_vertical(self):
        cells, pos = self.positions(STANDS_ON_ORIGIN, centre=(1.0, 2.0, 3.0))
        self.assertEqual(set(round(p[1], 12) for p in pos), set([round(2.0 - 0.0, 12)]))
        self.assertGreater(max(p[2] for p in pos) - min(p[2] for p in pos), 10)

    def test_the_mesh_box_of_the_star_is_centred_on_the_requested_centre(self):
        for fp in (SQUARE, REAL_LIKE, STANDS_ON_ORIGIN, ODD_SIZED):
            centre = (10.0, -20.0, 30.0)
            cells, pos = self.positions(fp, centre)
            boxes = sl.mesh_boxes(pos, fp)
            for axis in range(3):
                lo = min(b[0][axis] for b in boxes)
                hi = max(b[1][axis] for b in boxes)
                self.assertAlmostEqual((lo + hi) / 2.0, centre[axis], places=9, msg="axis %d %r" % (axis, fp))
            size = sl.extent(cells, fp)
            for axis in range(3):
                lo = min(b[0][axis] for b in boxes)
                hi = max(b[1][axis] for b in boxes)
                self.assertAlmostEqual(hi - lo, size[axis], places=9)

    def test_the_offset_moves_the_origin_not_the_mesh(self):
        cells = sl.star_cells(17)
        plain = sl.cell_positions(cells, sl.Footprint(1, 1, 1), (0, 0, 0))
        lifted = sl.cell_positions(cells, sl.Footprint(1, 1, 1, (0, 0, 0.5)), (0, 0, 0))
        for a, b in zip(plain, lifted):
            self.assertAlmostEqual(a[0], b[0], places=12)
            self.assertAlmostEqual(a[1], b[1], places=12)
            self.assertAlmostEqual(a[2] - 0.5, b[2], places=12)

    def test_symmetric_about_the_vertical_axis_through_the_centre(self):
        for fp in (SQUARE, REAL_LIKE, ODD_SIZED):
            centre = (10.0, -20.0, 30.0)
            cells, pos = self.positions(fp, centre)
            mesh_x = sorted(round(p[0] + fp.offset[0] - centre[0], 9) for p in pos)
            self.assertEqual(mesh_x, sorted(round(-x, 9) for x in mesh_x))
            where = dict(zip(cells, pos))
            for (ix, iz), p in where.items():
                mirror = where[(16 - ix, iz)]
                self.assertAlmostEqual((p[0] + mirror[0]) / 2.0, centre[0] - fp.offset[0], places=9)
                self.assertAlmostEqual(p[2], mirror[2], places=12)

    def test_deterministic(self):
        self.assertEqual(self.positions(REAL_LIKE), self.positions(REAL_LIKE))

    def test_extent_of_the_default_star(self):
        cells = sl.star_cells()
        width, depth, height = sl.extent(cells, REAL_LIKE)
        self.assertAlmostEqual(width, 15 * 1.0182, places=9)
        self.assertAlmostEqual(height, 15 * 1.0, places=9)
        self.assertAlmostEqual(depth, 1.0182, places=9)

    def test_no_cells_is_refused(self):
        with self.assertRaises(sl.LayoutError):
            sl.cell_positions([], SQUARE, (0, 0, 0))
        with self.assertRaises(sl.LayoutError):
            sl.extent([], SQUARE)


BOUNDS = (-240.0, 240.0, -345.0, 345.0, -70.0, 70.0)


class TestBounds(unittest.TestCase):
    def placed(self, centre, fp=REAL_LIKE, n=17):
        cells = sl.star_cells(n)
        return sl.cell_positions(cells, fp, centre)

    def test_a_star_in_the_middle_fits(self):
        self.assertEqual(sl.check_bounds(self.placed((0, 0, 0)), REAL_LIKE, BOUNDS), [])

    def test_every_position_is_inside_the_bounds_with_the_margin(self):
        centre = sl.choose_centre(BOUNDS, sl.extent(sl.star_cells(), REAL_LIKE))
        pos = self.placed(centre)
        for p in pos:
            for axis in range(3):
                self.assertGreaterEqual(p[axis], BOUNDS[2 * axis] + sl.DEFAULT_MARGIN)
                self.assertLess(p[axis], BOUNDS[2 * axis + 1] - sl.DEFAULT_MARGIN)

    def test_a_centre_outside_the_bounds_is_reported_per_axis(self):
        problems = sl.check_bounds(self.placed((1000.0, 0.0, 0.0)), REAL_LIKE, BOUNDS)
        self.assertEqual(len(problems), 1)
        self.assertIn("outside the map bounds", problems[0])
        self.assertIn("x ", problems[0])
        both = sl.check_bounds(self.placed((1000.0, -1000.0, 500.0)), REAL_LIKE, BOUNDS)
        self.assertEqual(len(both), 3)

    def test_the_margin_is_enforced_on_the_mesh_box_not_just_the_origin(self):
        # origin of the top blocks inside, but the mesh box (and the margin) is not
        fp = REAL_LIKE
        top = 70.0 - 7.5 - 0.2                                     # star half height 7.5: its top reaches 69.8
        problems = sl.check_bounds(self.placed((0, 0, top)), fp, BOUNDS, margin=1.0)
        self.assertEqual(len(problems), 1)
        self.assertIn("margin", problems[0])
        self.assertEqual(sl.check_bounds(self.placed((0, 0, top)), fp, BOUNDS, margin=0.0), [])

    def test_the_upper_bound_is_exclusive_like_the_library_rule(self):
        pos = [(240.0, 0.0, 0.0)]
        problems = sl.check_bounds(pos, sl.Footprint(0.1, 0.1, 0.1), BOUNDS, margin=0.0)
        self.assertEqual(len(problems), 1)
        self.assertIn("block positions span", problems[0], "the POSITION is outside [min, max): not just the mesh box")
        self.assertIn("outside the map bounds", problems[0])
        self.assertEqual(sl.check_bounds([(239.999, 0.0, 0.0)], sl.Footprint(0.001, 0.001, 0.001), BOUNDS, margin=0.0), [])

    def test_a_zero_range_axis_never_fits(self):
        flat = (-10.0, 10.0, -10.0, 10.0, 5.0, 5.0)
        self.assertTrue(sl.check_bounds([(0.0, 0.0, 5.0)], sl.Footprint(1, 1, 1), flat, margin=0.0))

    def test_bad_bounds_and_empty_positions(self):
        with self.assertRaises(sl.LayoutError):
            sl.check_bounds([(0, 0, 0)], SQUARE, (0, 1, 2))
        with self.assertRaises(sl.LayoutError):
            sl.check_bounds([(0, 0, 0)], SQUARE, (0, 1, 0, 1, 0, float("nan")))
        self.assertTrue(sl.check_bounds([], SQUARE, BOUNDS))


class TestChooseCentre(unittest.TestCase):
    SIZE = (15.27, 1.02, 15.0)

    def test_automatic_x_and_y_are_the_middle_of_the_bounds(self):
        x, y, z = sl.choose_centre((10.0, 50.0, -30.0, 90.0, -5.0, 45.0), self.SIZE)
        self.assertEqual((x, y), (30.0, 30.0))
        self.assertEqual(z, 20.0)                                  # the middle of the vertical bounds

    def test_ground_height_puts_the_bottom_edge_on_the_ground(self):
        centre = sl.choose_centre(BOUNDS, self.SIZE, ground_z=5.0)
        self.assertAlmostEqual(centre[2] - self.SIZE[2] / 2.0, 5.0, places=9)

    def test_the_height_is_moved_into_the_bounds_when_the_ground_is_too_high_or_too_low(self):
        high = sl.choose_centre(BOUNDS, self.SIZE, margin=1.0, ground_z=68.0)
        self.assertAlmostEqual(high[2] + self.SIZE[2] / 2.0, 69.0, places=9)
        low = sl.choose_centre(BOUNDS, self.SIZE, margin=1.0, ground_z=-200.0)
        self.assertAlmostEqual(low[2] - self.SIZE[2] / 2.0, -69.0, places=9)

    def test_requested_axes_are_used_as_given_even_outside_the_bounds(self):
        self.assertEqual(sl.choose_centre(BOUNDS, self.SIZE, requested=(1000.0, None, None))[0], 1000.0)
        self.assertEqual(sl.choose_centre(BOUNDS, self.SIZE, requested=(None, None, 7.0))[2], 7.0)
        with self.assertRaises(sl.LayoutError):
            sl.choose_centre(BOUNDS, self.SIZE, requested=(float("nan"), None, None))

    def test_a_star_that_cannot_fit_an_automatic_axis_is_refused_with_a_clear_message(self):
        with self.assertRaises(sl.LayoutError) as cm:
            sl.choose_centre((0.0, 10.0, -345.0, 345.0, -70.0, 70.0), self.SIZE)
        self.assertIn("smaller grid", str(cm.exception))
        with self.assertRaises(sl.LayoutError):
            sl.choose_centre((-240.0, 240.0, -345.0, 345.0, 0.0, 10.0), self.SIZE)

    def test_a_zero_range_automatic_axis_is_refused(self):
        with self.assertRaises(sl.LayoutError):
            sl.choose_centre((0.0, 100.0, 0.0, 100.0, 5.0, 5.0), self.SIZE)

    def test_the_chosen_centre_always_passes_check_bounds(self):
        for ground in (None, -100.0, 0.0, 12.0, 80.0):
            for fp in (REAL_LIKE, STANDS_ON_ORIGIN, ODD_SIZED):
                cells = sl.star_cells()
                centre = sl.choose_centre(BOUNDS, sl.extent(cells, fp), ground_z=ground)
                self.assertEqual(sl.check_bounds(sl.cell_positions(cells, fp, centre), fp, BOUNDS), [], (ground, fp))


class TestToleranceAndMatching(unittest.TestCase):
    def test_tolerance_is_about_a_millimetre_for_plausible_maps(self):
        tol = sl.position_tolerance(BOUNDS)
        for t in tol:
            self.assertGreaterEqual(t, 1.0e-3)
            self.assertLess(t, 1.3e-3)

    def test_tolerance_grows_with_a_huge_axis_range(self):
        tol = sl.position_tolerance((0.0, 100000.0, 0.0, 10.0, 0.0, 10.0))
        self.assertGreater(tol[0], 0.02)                           # range / 2**23 * 2
        self.assertLess(tol[1], 1.3e-3)

    def test_a_cell_never_exceeds_the_tolerance(self):
        # SPEC 4.1: bits = ceil(log2(ceil(range / 0.000520833)))  ->  cell = range / 2**bits <= 0.000521
        for rng in (1.0, 17.0, 480.0, 690.0, 1024.0, 3000.0):
            cells = math.ceil(rng / 0.00052083333)
            bits = 0 if cells <= 1 else (cells - 1).bit_length()
            cell = rng / float(1 << bits)
            self.assertLessEqual(cell / 2.0, sl.position_tolerance((0.0, rng, 0.0, rng, 0.0, rng))[0])

    def test_matching_ignores_order_and_reports_the_worst_error(self):
        expected = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
        actual = [(2.0004, 0.0, 0.0), (0.0, 0.0, 0.0), (1.0, 0.0003, 0.0)]
        match = sl.match_positions(expected, actual, (0.001, 0.001, 0.001))
        self.assertTrue(match.ok)
        self.assertEqual(match.pairs, [(0, 1), (1, 2), (2, 0)])
        self.assertAlmostEqual(match.worst[0], 0.0004, places=9)
        self.assertAlmostEqual(match.worst[1], 0.0003, places=9)

    def test_matching_reports_missing_and_extra(self):
        expected = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
        actual = [(0.0, 0.0, 0.0), (1.05, 0.0, 0.0), (9.0, 9.0, 9.0)]
        match = sl.match_positions(expected, actual, 0.01)
        self.assertFalse(match.ok)
        self.assertEqual(match.missing, [1])
        self.assertEqual(match.extra, [1, 2])
        self.assertEqual(match.pairs, [(0, 0)])

    def test_matching_is_one_to_one(self):
        match = sl.match_positions([(0.0, 0.0, 0.0), (0.0005, 0.0, 0.0)], [(0.0002, 0.0, 0.0)], 0.001)
        self.assertEqual(len(match.pairs), 1)
        self.assertEqual(len(match.missing), 1)

    def test_a_full_star_matches_itself_shuffled(self):
        cells = sl.star_cells(17)
        pos = sl.cell_positions(cells, REAL_LIKE, (0.0, 0.0, 12.0))
        shuffled = pos[::-1]
        match = sl.match_positions(pos, shuffled, sl.position_tolerance(BOUNDS))
        self.assertTrue(match.ok)
        self.assertEqual(len(match.pairs), len(pos))


PIXEL39_ROWS = (
    "....#....",
    "....#....",
    "...###...",
    "#########",
    ".#######.",
    "..#####..",
    "..#####..",
    "..##.##..",
    ".##...##.",
)


def coverage_raster(ncols, nrows, radius, centre_row, threshold=0.5, aspect=1.0, samples=6):
    """The rule the fixed design ``pixel39`` was derived with (S1): a cell is a block when at least ``threshold`` of its
    area lies inside the true star (circumradius ``radius`` rows, centre ``centre_row`` rows above the grid's first
    row, columns ``aspect`` times as wide as the rows are tall), area measured with ``samples`` x ``samples`` points."""
    polygon = sl.star_polygon(radius)
    middle = (ncols - 1) / 2.0
    cells = []
    for iz in range(nrows):
        for ix in range(ncols):
            hits = 0
            for a in range(samples):
                for b in range(samples):
                    x = ((ix - middle) + (a + 0.5) / samples - 0.5) * aspect
                    z = (iz - centre_row) + (b + 0.5) / samples - 0.5
                    if sl.point_in_polygon(abs(x), z, polygon):
                        hits += 1
            if hits / float(samples * samples) >= threshold:
                cells.append((ix, iz))
    lowest = min(c[1] for c in cells)
    return sorted(((x, z - lowest) for x, z in cells), key=lambda c: (-c[1], c[0]))


class TestNamedShapes(unittest.TestCase):
    """S1: ``pixel39``, the design for the 40 free slots of the real Breakneck file (the sampled grid 11 has detached feet)."""

    def setUp(self):
        self.cells = sl.named_shape("pixel39")

    def test_the_names(self):
        self.assertEqual(sl.shape_names(), ["pixel39"])
        self.assertEqual(sorted(sl.NAMED_SHAPES), sl.shape_names())

    def test_the_rows_are_the_design(self):
        self.assertEqual(sl.NAMED_SHAPES["pixel39"], PIXEL39_ROWS)
        self.assertEqual(sl.render_cells(self.cells), list(PIXEL39_ROWS))

    def test_thirty_nine_blocks_fit_the_forty_free_slots(self):
        self.assertEqual(len(self.cells), 39)
        self.assertEqual(len(set(self.cells)), 39)
        self.assertLessEqual(len(self.cells), 650 - 610)

    def test_cells_are_in_reading_order_like_the_sampled_stars(self):
        self.assertEqual(self.cells, sorted(self.cells, key=lambda c: (-c[1], c[0])))
        self.assertEqual(self.cells[0], (4, 8))                      # the apex
        self.assertEqual(self.cells[-1], (7, 0))

    def test_apex_up_nine_by_nine(self):
        self.assertEqual((min(c[0] for c in self.cells), max(c[0] for c in self.cells)), (0, 8))
        self.assertEqual((min(c[1] for c in self.cells), max(c[1] for c in self.cells)), (0, 8))
        self.assertEqual([c for c in self.cells if c[1] == 8], [(4, 8)])

    def test_exactly_mirror_symmetric_about_the_middle_column(self):
        taken = set(self.cells)
        self.assertTrue(all((8 - x, z) in taken for x, z in taken))

    def test_one_piece_under_face_connectivity_and_no_cell_is_alone(self):
        self.assertEqual(components(self.cells, neighbours4), 1)
        taken = set(self.cells)
        for cell in self.cells:
            self.assertTrue(any(n in taken for n in neighbours4(cell)), cell)

    def test_the_five_tips(self):
        taken = set(self.cells)
        for tip in ((4, 8), (0, 5), (8, 5), (1, 0), (7, 0)):         # apex, the two arms, the two feet
            self.assertIn(tip, taken)
        self.assertEqual(sl.tip_cells(self.cells, 9)[0], (4, 8))

    def test_the_feet_touch_the_legs_along_a_face(self):
        taken = set(self.cells)
        for foot, leg in (((1, 0), (2, 0)), ((7, 0), (6, 0)), ((2, 0), (2, 1)), ((6, 0), (6, 1))):
            self.assertIn(foot, taken)
            self.assertIn(leg, taken)
            self.assertEqual(abs(foot[0] - leg[0]) + abs(foot[1] - leg[1]), 1)

    def test_it_is_not_a_free_hand_drawing_it_is_the_area_coverage_rule(self):
        derived = coverage_raster(9, 13, 6.0, 5.7, 0.5, aspect=1.0182)
        self.assertEqual(derived, self.cells)

    def test_the_sampled_grid_it_replaces_is_not_face_connected(self):
        """The reason for the design: the best sampled grid for 40 slots (11, 34 blocks) has two feet that touch a leg at a corner."""
        eleven = sl.star_cells(11)
        self.assertEqual(len(eleven), 34)
        self.assertEqual(components(eleven, neighbours4), 3)
        self.assertEqual(components(eleven, neighbours8), 1)

    def test_positions_touch_without_overlap_on_the_measured_block(self):
        pos = sl.cell_positions(self.cells, REAL_LIKE, (13.25, -15.75, 17.0))
        by_cell = dict(zip(self.cells, pos))
        for (ix, iz), p in by_cell.items():
            if (ix + 1, iz) in by_cell:
                self.assertAlmostEqual(by_cell[(ix + 1, iz)][0] - p[0], REAL_LIKE.width, places=9)
            if (ix, iz + 1) in by_cell:
                self.assertAlmostEqual(by_cell[(ix, iz + 1)][2] - p[2], REAL_LIKE.height, places=9)
        self.assertEqual(sl.extent(self.cells, REAL_LIKE), (9 * 1.0182, 1.0182, 9.0))

    def test_unknown_and_malformed_designs_are_refused(self):
        with self.assertRaises(sl.LayoutError):
            sl.named_shape("pixel40")
        saved = dict(sl.NAMED_SHAPES)
        try:
            sl.NAMED_SHAPES["ragged"] = ("##", "#")
            with self.assertRaises(sl.LayoutError):
                sl.named_shape("ragged")
            sl.NAMED_SHAPES["alien"] = ("#x", "..")
            with self.assertRaises(sl.LayoutError):
                sl.named_shape("alien")
            sl.NAMED_SHAPES["empty"] = ()
            with self.assertRaises(sl.LayoutError):
                sl.named_shape("empty")
        finally:
            sl.NAMED_SHAPES.clear()
            sl.NAMED_SHAPES.update(saved)

    def test_deterministic(self):
        self.assertEqual(sl.named_shape("pixel39"), sl.named_shape("pixel39"))


class TestModuleIsPure(unittest.TestCase):
    def test_no_blender_no_file_access_no_output(self):
        with open(TOOL, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imported = set()
        calls = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                calls.add(node.func.id)
        self.assertEqual(imported, set(["math"]))
        self.assertFalse(calls & set(["open", "print", "exec", "eval", "__import__"]))


if __name__ == "__main__":
    unittest.main()
