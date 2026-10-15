"""S1: where the block star goes (``tools/star_placement.py``) and the numbers behind the choice.

The geometry is tested on small synthetic worlds where the right answer can be worked out by hand (no game data). The one
real-file test reads the Breakneck sample in place (read-only, skipped loudly when it is absent) and pins the clearances
of the chosen place, which are quoted in ``docs/mvar/notes/S1.md`` and in the report that goes with the star.
"""
import ast
import contextlib
import io
import math
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for _path in (os.path.join(REPO, "tools"),):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import star_layout as sl  # noqa: E402
import star_placement as sp  # noqa: E402

TOOL = os.path.join(REPO, "tools", "star_placement.py")
REAL_SAMPLE = os.path.expanduser("~/Local_Documents/Halo-MCC/forge/real-mvar-samples/0aaaf8c7-5ae6-43ba-bb4d-37c987f5e8b8.mvar")
BLOCK = sl.Footprint(1.0182, 1.0182, 1.0)
PIXEL39 = sl.named_shape("pixel39")


def record(slot, name, position, shape=0, width=0.0, length=0.0, top=0.0, bottom=0.0):
    return types.SimpleNamespace(slot=slot, type_name=name, position=position, shape=shape, width=width, length=length,
                                 top=top, bottom=bottom)


def square_hull():
    return sp.convex_hull([(0, 0), (10, 0), (10, 10), (0, 10), (5, 5), (3, 3)])


class TestGeometry(unittest.TestCase):
    def test_convex_hull_drops_the_inner_points_and_is_counter_clockwise(self):
        hull = square_hull()
        self.assertEqual(sorted(hull), [(0.0, 0.0), (0.0, 10.0), (10.0, 0.0), (10.0, 10.0)])
        area2 = sum(hull[i][0] * hull[(i + 1) % 4][1] - hull[(i + 1) % 4][0] * hull[i][1] for i in range(4))
        self.assertGreater(area2, 0, "counter-clockwise")
        self.assertEqual(sp.convex_hull([(1, 1)]), [(1.0, 1.0)])
        self.assertEqual(sp.convex_hull([(1, 1), (2, 2), (1, 1)]), [(1.0, 1.0), (2.0, 2.0)])
        self.assertEqual(sp.convex_hull([]), [])
        self.assertEqual(sorted(sp.convex_hull([(0, 0), (1, 1), (2, 2), (3, 3)])), [(0.0, 0.0), (3.0, 3.0)], "collinear")

    def test_hull_margin_is_signed_distance_to_the_border(self):
        hull = square_hull()
        self.assertAlmostEqual(sp.hull_margin(hull, 5, 5), 5.0)
        self.assertAlmostEqual(sp.hull_margin(hull, 1, 4), 1.0)
        self.assertAlmostEqual(sp.hull_margin(hull, 0, 5), 0.0)
        self.assertAlmostEqual(sp.hull_margin(hull, -2, 5), -2.0)
        self.assertAlmostEqual(sp.hull_margin(hull, 13, 14), -5.0, msg="outside past a corner: distance to the corner")
        self.assertEqual(sp.hull_margin([], 0, 0), float("-inf"))

    def test_rect_and_box_distance(self):
        self.assertEqual(sp.rect_distance(1, 1, (0, 2, 0, 2)), 0.0)
        self.assertEqual(sp.rect_distance(5, 1, (0, 2, 0, 2)), 3.0)
        self.assertAlmostEqual(sp.rect_distance(5, 6, (0, 2, 0, 2)), 5.0)
        box = (0, 1, 0, 1, 0, 1)
        self.assertEqual(sp.box_distance((0.5, 0.5, 0.5), box), 0.0)
        self.assertEqual(sp.box_distance((3, 0.5, 0.5), box), 2.0)
        self.assertAlmostEqual(sp.box_distance((2, 2, 2), box), math.sqrt(3))

    def test_volume_distance_uses_the_circle_and_the_vertical_extent(self):
        volume = sp.Volume(1, "Kill Boundary", 0.0, 0.0, 10.0, 20.0, 2.0)
        near = (5, 6, 0, 1, 12, 13)                                  # 5 away in x, inside the vertical extent
        self.assertAlmostEqual(sp.volume_distance(volume, near), 3.0)
        above = (0, 1, 0, 1, 25, 26)                                 # right above the circle: 5 over the top
        self.assertAlmostEqual(sp.volume_distance(volume, above), 5.0)
        corner = (5, 6, 0, 1, 25, 26)                                # 3 beyond the circle and 5 over the top
        self.assertAlmostEqual(sp.volume_distance(volume, corner), math.hypot(3.0, 5.0))
        touching = (1, 2, 0, 1, 12, 13)
        self.assertEqual(sp.volume_distance(volume, touching), 0.0)

    def test_volumes_from_records(self):
        box = sp.volume_from_record(7, "Soft Kill Boundary", (10.0, 20.0, 30.0), 3, 6.0, 8.0, 4.0, 2.0)
        self.assertEqual((box.x, box.y, box.z0, box.z1), (10.0, 20.0, 28.0, 34.0))
        self.assertAlmostEqual(box.radius, 5.0, msg="the circle through the corners of 6 x 8, yaw unknown")
        cyl = sp.volume_from_record(8, "Kill Boundary", (1.0, 2.0, 3.0), 2, 4.0, 0.0, 1.0, 1.5)
        self.assertEqual((cyl.radius, cyl.z0, cyl.z1), (4.0, 1.5, 4.0))
        sphere = sp.volume_from_record(9, "Kill Boundary", (0.0, 0.0, 10.0), 1, 3.0, 0.0, 0.0, 0.0)
        self.assertEqual((sphere.radius, sphere.z0, sphere.z1), (3.0, 7.0, 13.0))
        point = sp.volume_from_record(10, "Kill Boundary", (0.0, 0.0, 10.0), 0, 0.0, 0.0, 0.0, 0.0)
        self.assertEqual((point.radius, point.z0, point.z1), (0.0, 10.0, 10.0))

    def test_only_boundaries_are_volumes_but_every_record_is_an_item(self):
        records = [record(0, "Respawn Point", (1.0, 2.0, 3.0)), record(1, "Kill Boundary", (4.0, 5.0, 6.0), 3, 2.0, 2.0, 1.0, 1.0),
                   record(2, "Soft Kill Boundary", (7.0, 8.0, 9.0), 2, 1.0, 0.0, 1.0, 1.0), record(3, "Block, 1x1", (0.0, 0.0, 0.0))]
        items, volumes = sp.split_records(records)
        self.assertEqual([i.slot for i in items], [0, 1, 2, 3])
        self.assertEqual([v.slot for v in volumes], [1, 2])
        self.assertTrue(sp.is_boundary("Safe Boundary") and sp.is_boundary("soft kill boundary"))
        self.assertFalse(sp.is_boundary("Respawn Zone"))
        self.assertIn("Respawn Point (slot 0)", items[0].label())
        self.assertIn("bounding radius", volumes[0].label())


class TestBoxesAndMeasure(unittest.TestCase):
    def test_star_boxes_touch_and_never_overlap_and_are_centred(self):
        boxes = sp.star_boxes(PIXEL39, BLOCK, (13.25, -15.75, 17.0))
        self.assertEqual(len(boxes), 39)
        self.assertEqual(sp.overlap_count(boxes), 0)
        lo, hi = sp.union_bounds(boxes)
        self.assertAlmostEqual((lo[0] + hi[0]) / 2.0, 13.25, places=9)
        self.assertAlmostEqual((lo[1] + hi[1]) / 2.0, -15.75, places=9)
        self.assertAlmostEqual((lo[2] + hi[2]) / 2.0, 17.0, places=9)
        self.assertAlmostEqual(hi[0] - lo[0], 9 * 1.0182, places=9)
        self.assertAlmostEqual(hi[2] - lo[2], 9.0, places=9)

    def test_overlap_count_counts_real_overlap_only(self):
        a = (0, 1, 0, 1, 0, 1)
        self.assertEqual(sp.overlap_count([a, (1, 2, 0, 1, 0, 1)]), 0, "touching along a face")
        self.assertEqual(sp.overlap_count([a, (1, 2, 1, 2, 1, 2)]), 0, "touching at a corner")
        self.assertEqual(sp.overlap_count([a, (0.9, 2, 0, 1, 0, 1)]), 1)
        self.assertEqual(sp.overlap_count([a, a, a]), 3)

    def test_boxes_at_decoded_positions_equal_boxes_from_the_layout(self):
        positions = sl.cell_positions(PIXEL39, BLOCK, (1.0, 2.0, 3.0))
        self.assertEqual(sp.boxes_at_positions(positions, BLOCK), sp.star_boxes(PIXEL39, BLOCK, (1.0, 2.0, 3.0)))

    def test_measure_names_the_nearest_object_in_each_sense(self):
        boxes = [(0, 1, 0, 1, 10, 11)]
        items = [sp.Item(1, "Far below", 0.5, 0.5, 0.0), sp.Item(2, "Beside", 3.0, 0.5, 10.5), sp.Item(3, "Diagonal", 2.0, 2.0, 12.0)]
        m = sp.measure_boxes(boxes, items)
        self.assertEqual(m.xy_item.slot, 1)
        self.assertEqual(m.xy, 0.0, "directly below: no horizontal distance at all")
        self.assertEqual(m.d3_item.slot, 3)
        self.assertAlmostEqual(m.d3, math.sqrt(3))
        self.assertEqual(m.inside, [])
        self.assertEqual(m.volume, float("inf"))
        self.assertEqual(m.hull, float("inf"))
        self.assertEqual(m.blocks, 1)

    def test_measure_reports_objects_inside_the_bounding_box_and_volumes_and_hull(self):
        boxes = [(0, 1, 0, 1, 0, 1), (1, 2, 0, 1, 0, 1)]
        items = [sp.Item(1, "Inside", 1.5, 0.5, 0.5), sp.Item(2, "Outside", 5.0, 5.0, 5.0)]
        volume = sp.Volume(9, "Kill Boundary", 10.0, 0.0, 0.0, 5.0, 1.0)
        hull = sp.convex_hull([(-5, -5), (5, -5), (5, 5), (-5, 5)])
        m = sp.measure_boxes(boxes, items, [volume], hull)
        self.assertEqual([i.slot for i in m.inside], [1])
        self.assertEqual(m.d3, 0.0)
        self.assertAlmostEqual(m.volume, 7.0)
        self.assertAlmostEqual(m.hull, 3.0, msg="the star's bounding rectangle, 2 + 3 inside from the +x edge: the least is 3")
        lines = m.summary_lines()
        self.assertEqual(len(lines), 5)
        self.assertIn("Inside", "\n".join(lines))

    def test_measure_of_nothing_is_empty_not_an_error(self):
        m = sp.measure_boxes([], [sp.Item(1, "x", 0, 0, 0)])
        self.assertEqual(m.blocks, 0)
        self.assertEqual(m.d3, float("inf"))


COARSE = dict(coarse=1.0, fine=0.25)                          # a coarser search keeps these synthetic worlds fast


class TestSearch(unittest.TestCase):
    def world(self):
        """A 50 x 50 floor of objects every 5 units at z 0, except a hole of 20 x 20 around (10, -10); one tower at z 30."""
        items = []
        slot = 0
        for ix in range(-5, 6):
            for iy in range(-5, 6):
                x, y = ix * 5.0, iy * 5.0
                if abs(x - 10.0) < 9.9 and abs(y + 10.0) < 9.9:
                    continue
                items.append(sp.Item(slot, "Floor", x, y, 0.0))
                slot += 1
        items.append(sp.Item(slot, "Tower", -20.0, 20.0, 30.0))
        return items

    def test_the_bottom_is_the_highest_multiple_that_keeps_the_top_inside_the_range(self):
        items = [sp.Item(0, "a", 0, 0, 2.0), sp.Item(1, "b", 0, 0, 21.698)]
        self.assertEqual(sp.choose_bottom(items, 9.0), 12.5)
        self.assertLessEqual(sp.choose_bottom(items, 9.0) + 9.0, 21.698)
        self.assertEqual(sp.choose_bottom(items, 9.0, step=1.0), 12.0)
        self.assertEqual(sp.choose_bottom(items, 9.0, top_limit=30.0, step=0.5), 21.0)
        self.assertEqual(sp.choose_bottom(items, 1.698, step=0.25), 20.0)
        self.assertEqual(sp.choose_bottom([sp.Item(0, "a", 0, 0, 10.0)], 4.0), 6.0, "exact multiples are not lost to rounding")
        with self.assertRaises(sl.LayoutError):
            sp.choose_bottom([], 9.0)

    def test_the_star_goes_where_the_footprint_is_furthest_from_every_object(self):
        items = self.world()
        ranked = sp.search(items, [], PIXEL39, BLOCK, margin=3.0, **COARSE)
        best = ranked[0]
        self.assertAlmostEqual(best.centre[0], 10.0, delta=0.5)
        self.assertTrue(-17.0 <= best.centre[1] <= -3.0, best.centre)
        self.assertGreater(best.measure.xy, 5.3, "the hole is 20 wide, the footprint 9.2 x 1.0: 5.4 each side")
        self.assertEqual(best.measure.inside, [])
        # the height: the top is not above the highest object (the tower, 30), so the bottom is 21
        self.assertAlmostEqual(best.centre[2] - 4.5, 21.0, places=9)
        self.assertGreaterEqual(best.measure.d3, 3.0)
        self.assertGreaterEqual(best.measure.hull, 3.0)

    def test_the_answer_is_deterministic_and_ranked_best_first(self):
        items = self.world()
        a = sp.search(items, [], PIXEL39, BLOCK, **COARSE)
        b = sp.search(items, [], PIXEL39, BLOCK, **COARSE)
        self.assertEqual([c.centre for c in a], [c.centre for c in b])
        keys = [c.key for c in a]
        self.assertEqual(keys, sorted(keys, reverse=True))
        self.assertTrue(len(a) >= 2)

    def test_a_boundary_volume_pushes_the_star_away(self):
        items = self.world()
        centre_of_hole = sp.search(items, [], PIXEL39, BLOCK, **COARSE)[0].centre
        volume = sp.Volume(900, "Kill Boundary", centre_of_hole[0], centre_of_hole[1], 0.0, 200.0, 2.0)
        moved = sp.search(items, [volume], PIXEL39, BLOCK, **COARSE)[0]
        self.assertGreaterEqual(moved.measure.volume, 3.0)
        self.assertGreater(math.hypot(moved.centre[0] - centre_of_hole[0], moved.centre[1] - centre_of_hole[1]), 3.0)

    def test_the_hull_margin_keeps_the_star_off_the_edge_of_the_area(self):
        items = [sp.Item(i, "p", x, y, 0.0) for i, (x, y) in enumerate([(0, 0), (30, 0), (0, 30), (30, 30), (15, 15)])]
        ranked = sp.search(items, [], PIXEL39, BLOCK, margin=3.0, **COARSE)
        hull = sp.convex_hull([(i.x, i.y) for i in items])
        for cand in ranked:
            self.assertGreaterEqual(cand.measure.hull, 3.0)
            self.assertGreaterEqual(sp.hull_margin(hull, cand.centre[0] - 4.58, cand.centre[1]), 3.0 - 1e-6)

    def test_nothing_qualifies_in_a_tiny_world(self):
        items = [sp.Item(0, "a", 0, 0, 0), sp.Item(1, "b", 5, 0, 0), sp.Item(2, "c", 0, 5, 0), sp.Item(3, "d", 5, 5, 0)]
        with self.assertRaises(sl.LayoutError) as caught:
            sp.search(items, [], PIXEL39, BLOCK, margin=3.0, **COARSE)
        self.assertIn("margin", str(caught.exception))
        with self.assertRaises(sl.LayoutError):
            sp.search([], [], PIXEL39, BLOCK)

    def test_largest_empty_circle(self):
        items = [sp.Item(0, "a", x, y, 0.0) for x, y in ((0, 0), (20, 0), (0, 20), (20, 20))]
        radius, x, y = sp.largest_empty_circle(items, margin=0.0, step=0.5)
        self.assertAlmostEqual(radius, math.hypot(10, 10), delta=0.8)
        self.assertAlmostEqual(x, 10.0, delta=0.6)
        self.assertAlmostEqual(y, 10.0, delta=0.6)


class TestCommandLine(unittest.TestCase):
    def quiet(self, argv):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sp.main(argv)
        return code, out.getvalue() + err.getvalue()

    def test_usage_errors_exit_2(self):
        for argv in ([], ["search"], ["measure", "only-one.mvar"], ["frobnicate"], ["search", "x.mvar", "--shape", "nope"]):
            code, _text = self.quiet(argv)
            self.assertEqual(code, 2, argv)

    def test_a_bad_footprint_or_a_missing_file_is_a_clear_message_not_a_traceback(self):
        code, text = self.quiet(["search", "x.mvar", "--footprint", "1,2"])
        self.assertEqual(code, 2)
        self.assertIn("three comma-separated numbers", text)
        code, text = self.quiet(["search", os.path.join(os.path.dirname(TOOL), "no-such-file.mvar")])
        self.assertEqual(code, 2)
        self.assertIn("star_placement:", text)
        self.assertNotIn("Traceback", text)

    def test_parse_footprint(self):
        fp = sp.parse_footprint("1.0182, 1.0182, 1")
        self.assertEqual((fp.width, fp.depth, fp.height), (1.0182, 1.0182, 1.0))
        with self.assertRaises(ValueError):
            sp.parse_footprint("1,2")
        with self.assertRaises(ValueError):
            sp.parse_footprint("a,b,c")
        with self.assertRaises(sl.LayoutError):
            sp.parse_footprint("1,2,-3")


class TestModuleShape(unittest.TestCase):
    def test_standard_library_and_the_layout_only_and_no_file_writes(self):
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
        self.assertLessEqual(imported, set(["argparse", "math", "os", "sys", "star_layout", "mvarlib"]))
        self.assertNotIn("bpy", imported)
        self.assertFalse(calls & set(["exec", "eval", "__import__"]))
        opens = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "open"]
        self.assertTrue(opens)
        for call in opens:                                            # the tool only reads: every open() says "rb"
            self.assertEqual(len(call.args), 2)
            self.assertEqual(getattr(call.args[1], "value", None), "rb")
        self.assertTrue(sp.sys.dont_write_bytecode, "no bytecode is written beside the tools")


class TestRealSample(unittest.TestCase):
    """The place chosen for the star on the real file and its clearances (read-only)."""

    CENTRE = (13.25, -15.75, 17.0)

    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(REAL_SAMPLE):
            sys.stderr.write("\n" + "=" * 78 + "\nNOTICE: the real map variant %s is absent;\n"
                             "        the real-file star placement test is SKIPPED, not passed.\n" % REAL_SAMPLE + "=" * 78 + "\n")
            raise unittest.SkipTest("NOTICE: the real map variant is absent (%s)" % REAL_SAMPLE)
        cls.loaded = sp.load_records(REAL_SAMPLE)
        cls.items, cls.volumes = sp.split_records(cls.loaded.objects)
        cls.hull = sp.convex_hull([(i.x, i.y) for i in cls.items])

    def test_the_file_is_the_one_the_numbers_are_about(self):
        self.assertEqual(len(self.items), 610)
        self.assertEqual(len(self.volumes), 17, "15 soft kill boundaries and kill boundaries, as decoded in G3")
        self.assertAlmostEqual(max(i.z for i in self.items), 21.698, places=3)
        self.assertEqual(sp.choose_bottom(self.items, 9.0), 12.5)

    def test_the_chosen_place_clearances(self):
        boxes = sp.star_boxes(PIXEL39, BLOCK, self.CENTRE)
        m = sp.measure_boxes(boxes, self.items, self.volumes, self.hull)
        self.assertEqual(sp.overlap_count(boxes), 0)
        self.assertEqual(m.inside, [], "no object lies inside the star's bounding box")
        self.assertAlmostEqual(m.xy, 2.593, places=2)
        self.assertEqual(m.xy_item.slot, 425)
        self.assertAlmostEqual(m.d3, 7.738, places=2)
        self.assertAlmostEqual(m.volume, 3.870, places=2)
        self.assertEqual(m.volume_item.slot, 592)
        self.assertAlmostEqual(m.hull, 9.316, places=2)
        lo, hi = m.lo, m.hi
        self.assertAlmostEqual(lo[2], 12.5, places=6)
        self.assertAlmostEqual(hi[2], 21.5, places=6)
        self.assertLessEqual(hi[2], max(i.z for i in self.items), "the star stays inside the vertical range of the objects")
        self.assertGreaterEqual(lo[2], min(i.z for i in self.items))

    def test_no_object_of_the_template_comes_closer_than_seven_units_in_three_dimensions(self):
        boxes = sp.star_boxes(PIXEL39, BLOCK, self.CENTRE)
        near = [i for i in self.items if min(sp.box_distance((i.x, i.y, i.z), b) for b in boxes) < 7.0]
        self.assertEqual(near, [])


if __name__ == "__main__":
    unittest.main()
