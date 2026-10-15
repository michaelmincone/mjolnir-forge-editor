#!/usr/bin/env python3
"""Where the block star goes on a real map variant, and how much room it has (S1; NOTES.md D10 / D10a).

    python3 -I tools/star_placement.py search  TEMPLATE.mvar [--shape pixel39] [--footprint W,D,H] [--margin 3.0]
    python3 -I tools/star_placement.py measure TEMPLATE.mvar OUTPUT.mvar [--footprint W,D,H]

``search`` reads the template (read-only, with the library's own reader) and prints the place where a star of the given
design has the most room, and the numbers behind the choice. ``measure`` reads the template and the star file that was
built from it, takes the blocks that are new in the output (their DECODED positions, not the positions Blender
had), and prints how far they are from the template's objects and from its kill boundaries.

What "room" means here. The file holds only object records, not the terrain, so room is measured against the objects:

* ``xy``: the horizontal distance from the star's footprint (the XY projection of its blocks) to the nearest object
  of the template, whatever its height. This is the "largest empty circle" criterion: the star is put where the
  footprint is furthest from every object, inside the area the objects cover.
* ``3d``: the distance from the star's blocks (as boxes) to the nearest object position in three dimensions.
* ``volume``: the distance to the nearest kill / safe boundary volume. A box volume is judged by its horizontal bounding
  circle (its yaw is not known here, so the circle is the safe overestimate) and by its vertical extent
  ``[z - bottom, z + top]``; a cylinder by its radius. Boundary volumes are not objects one collides with, but a
  block inside one may be removed by the game.
* ``hull``: how far inside the convex hull of the template's objects the footprint lies (the hull is the stand-in
  for "the playable region"; the bounds of a map variant are far larger than the map).

The choice (``search``): among the places where the footprint is at least ``--margin`` inside the hull and at least
``--margin`` from every boundary volume and from every object in 3D, the one with the largest ``xy`` clearance wins
(ties: the larger hull margin). The height is not searched: the star is raised until its top is as high as the highest
object of the template (``star_layout`` / the task: stay inside the vertical range of the existing objects, so that
the game's kill and safe volumes are not left), rounded down to a multiple of ``--z-step``.

Pure Python 3.9 to 3.13, standard library only. The functions that take numbers import nothing of the library; only
the two commands read files (the Blender add-on is not needed).
"""
import argparse
import math
import os
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import star_layout as sl  # noqa: E402

DEFAULT_FOOTPRINT = (1.0182, 1.0182, 1.0)       # the measured mesh box of "Block, 1x1" (width x, depth y, height z)
DEFAULT_MARGIN = 3.0
DEFAULT_Z_STEP = 0.25
MAX_BYTES = 8 << 20


class Item(object):
    """A point object of the template (a spawn point, a weapon, a wall piece ...)."""

    def __init__(self, slot, name, x, y, z):
        self.slot, self.name, self.x, self.y, self.z = slot, name, float(x), float(y), float(z)

    def label(self):
        return "%s (slot %s) at (%.2f, %.2f, %.2f)" % (self.name, self.slot, self.x, self.y, self.z)


class Volume(object):
    """A boundary volume, simplified to a vertical cylinder ``radius`` around ``(x, y)`` between ``z0`` and ``z1``."""

    def __init__(self, slot, name, x, y, z0, z1, radius):
        self.slot, self.name, self.x, self.y = slot, name, float(x), float(y)
        self.z0, self.z1, self.radius = float(z0), float(z1), float(radius)

    def label(self):
        return "%s (slot %s) at (%.2f, %.2f), z %.2f to %.2f, bounding radius %.2f" % (
            self.name, self.slot, self.x, self.y, self.z0, self.z1, self.radius)


def is_boundary(name):
    """True for the kill and safe boundary objects (``Kill Boundary``, ``Soft Kill Boundary``, ``Safe Boundary`` ...)."""
    return "boundary" in str(name).lower()


def volume_from_record(slot, name, position, shape, width, length, top, bottom):
    """The simplified volume of a boundary record. Shapes: 1 sphere (radius = width), 2 cylinder, 3 box, 0 none.

    A box is overestimated by the circle through its corners: ``hypot(width / 2, length / 2)`` (its yaw is unknown), and
    its vertical extent is ``[z - bottom, z + top]``. A shape of kind none (0) is a point of no extent.
    """
    x, y, z = position
    if shape == 3:
        return Volume(slot, name, x, y, z - bottom, z + top, math.hypot(width / 2.0, length / 2.0))
    if shape == 2:
        return Volume(slot, name, x, y, z - bottom, z + top, width)
    if shape == 1:
        return Volume(slot, name, x, y, z - width, z + width, width)
    return Volume(slot, name, x, y, z, z, 0.0)


def split_records(records):
    """``(items, volumes)`` of a list of object records (anything with ``slot``, ``type_name``, ``position``, ``shape``,
    ``width``, ``length``, ``top``, ``bottom``, as ``mvarlib.api.ObjectRecord`` has). Boundary objects are in both lists:
    their centre is an object position too (they are objects of the map), and their volume matters for the star."""
    items, volumes = [], []
    for r in records:
        x, y, z = r.position
        items.append(Item(r.slot, r.type_name, x, y, z))
        if is_boundary(r.type_name):
            volumes.append(volume_from_record(r.slot, r.type_name, r.position, r.shape, r.width, r.length, r.top, r.bottom))
    return items, volumes


# --- geometry ----------------------------------------------------------------------------------------
def convex_hull(points):
    """Counter-clockwise convex hull ``[(x, y), ...]`` (Andrew's monotone chain; fewer than three points: the points)."""
    pts = sorted(set((float(x), float(y)) for x, y in points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _segment_distance(px, py, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def hull_margin(hull, px, py):
    """Signed distance from ``(px, py)`` to the border of a convex counter-clockwise ``hull``: positive inside, negative outside."""
    if len(hull) < 3:
        return -min(math.hypot(px - x, py - y) for x, y in hull) if hull else float("-inf")
    edge = min(_segment_distance(px, py, hull[i], hull[(i + 1) % len(hull)]) for i in range(len(hull)))
    inside = all((hull[(i + 1) % len(hull)][0] - hull[i][0]) * (py - hull[i][1])
                 - (hull[(i + 1) % len(hull)][1] - hull[i][1]) * (px - hull[i][0]) >= 0 for i in range(len(hull)))
    return edge if inside else -edge


def rect_distance(px, py, rect):
    """Distance from a point to an axis-aligned rectangle ``(x0, x1, y0, y1)`` in the plane (0 inside)."""
    dx = max(rect[0] - px, 0.0, px - rect[1])
    dy = max(rect[2] - py, 0.0, py - rect[3])
    return math.hypot(dx, dy)


def box_distance(point, box):
    """Distance from a point to an axis-aligned box ``(x0, x1, y0, y1, z0, z1)`` (0 inside)."""
    dx = max(box[0] - point[0], 0.0, point[0] - box[1])
    dy = max(box[2] - point[1], 0.0, point[1] - box[3])
    dz = max(box[4] - point[2], 0.0, point[2] - box[5])
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def volume_distance(volume, box):
    """Distance between a block box and a boundary volume (vertical cylinder); 0 when they touch or overlap."""
    ring = max(math.hypot(max(box[0] - volume.x, 0.0, volume.x - box[1]), max(box[2] - volume.y, 0.0, volume.y - box[3]))
               - volume.radius, 0.0)
    rise = max(volume.z0 - box[5], 0.0, box[4] - volume.z1)
    return math.hypot(ring, rise)


def star_boxes(cells, footprint, centre):
    """The mesh box ``(x0, x1, y0, y1, z0, z1)`` of every block of a star whose mesh box is centred on ``centre``."""
    positions = sl.cell_positions(cells, footprint, centre)
    return [(lo[0], hi[0], lo[1], hi[1], lo[2], hi[2]) for lo, hi in sl.mesh_boxes(positions, footprint)]


def boxes_at_positions(positions, footprint):
    """The same boxes for given object positions (the DECODED positions of a built star)."""
    return [(lo[0], hi[0], lo[1], hi[1], lo[2], hi[2]) for lo, hi in sl.mesh_boxes(positions, footprint)]


def union_bounds(boxes):
    """``((x0, y0, z0), (x1, y1, z1))`` around all boxes."""
    return (tuple(min(b[2 * a] for b in boxes) for a in range(3)), tuple(max(b[2 * a + 1] for b in boxes) for a in range(3)))


class Measure(object):
    """Room around a star (see the module docstring). Distances are ``float('inf')`` when there is nothing to measure against."""

    def __init__(self):
        self.xy = float("inf")
        self.xy_item = None
        self.d3 = float("inf")
        self.d3_item = None
        self.volume = float("inf")
        self.volume_item = None
        self.hull = float("inf")
        self.inside = []                 # items whose position lies inside the star's bounding box
        self.lo = self.hi = None
        self.blocks = 0

    def summary_lines(self):
        def one(label, distance, item):
            return "%-7s %.3f  (%s)" % (label, distance, item.label() if item is not None else "nothing to measure against")
        return [one("xy", self.xy, self.xy_item), one("3d", self.d3, self.d3_item),
                one("volume", self.volume, self.volume_item),
                "hull    %.3f  (inside the convex hull of the template's objects; negative = outside)" % self.hull,
                "inside  %d object position(s) lie inside the star's bounding box" % len(self.inside)]


def measure_boxes(boxes, items, volumes=(), hull=None):
    """:class:`Measure` of a set of block boxes against the template's items and volumes."""
    m = Measure()
    m.blocks = len(boxes)
    if not boxes:
        return m
    m.lo, m.hi = union_bounds(boxes)
    for item in items:
        d3 = min(box_distance((item.x, item.y, item.z), b) for b in boxes)
        if d3 < m.d3:
            m.d3, m.d3_item = d3, item
        dxy = min(rect_distance(item.x, item.y, (b[0], b[1], b[2], b[3])) for b in boxes)
        if dxy < m.xy:
            m.xy, m.xy_item = dxy, item
        if all(m.lo[a] <= (item.x, item.y, item.z)[a] <= m.hi[a] for a in range(3)):
            m.inside.append(item)
    for volume in volumes:
        dv = min(volume_distance(volume, b) for b in boxes)
        if dv < m.volume:
            m.volume, m.volume_item = dv, volume
    if hull:
        corners = [(x, y) for x in (m.lo[0], m.hi[0]) for y in (m.lo[1], m.hi[1])]
        m.hull = min(hull_margin(hull, x, y) for x, y in corners)
    return m


def overlap_count(boxes, tolerance=1.0e-6):
    """How many pairs of blocks overlap by more than ``tolerance`` in all three axes (touching along a face is not an overlap)."""
    count = 0
    for i in range(len(boxes)):
        a = boxes[i]
        for j in range(i + 1, len(boxes)):
            b = boxes[j]
            if all(min(a[2 * k + 1], b[2 * k + 1]) - max(a[2 * k], b[2 * k]) > tolerance for k in range(3)):
                count += 1
    return count


# --- the search ----------------------------------------------------------------------------------------
def choose_bottom(items, height, step=DEFAULT_Z_STEP, top_limit=None):
    """Bottom height of the star: as high as possible with its top not above ``top_limit`` (default: the highest item).

    ``floor((top_limit - height) / step) * step``, so the top of the star is never above the limit.
    """
    if not items:
        raise sl.LayoutError("There are no objects to place the star among.")
    limit = max(i.z for i in items) if top_limit is None else float(top_limit)
    return math.floor((limit - height) / step + 1.0e-9) * step


class Candidate(object):
    def __init__(self, centre, measure):
        self.centre, self.measure = centre, measure

    @property
    def key(self):
        return (round(self.measure.xy, 6), round(self.measure.hull, 6))


def search(items, volumes, cells, footprint, margin=DEFAULT_MARGIN, z_step=DEFAULT_Z_STEP, coarse=0.5, fine=0.125, keep=6):
    """The best places for the star, best first (:class:`Candidate`; the first one is the answer).

    Coarse pass on a grid of ``coarse`` over the bounding box of the items, keeping the places that satisfy the margins
    (hull, 3-D distance to objects, boundary volumes) by the footprint's bounding rectangle; then each of the best
    ``keep`` coarse places is refined on a grid of ``fine`` (+- ``coarse``) with the exact block boxes. Raises
    :class:`star_layout.LayoutError` when nothing qualifies.
    """
    if not items:
        raise sl.LayoutError("There are no objects to place the star among.")
    size = sl.extent(cells, footprint)
    height = size[2]
    bottom = choose_bottom(items, height, z_step)
    centre_z = bottom + height / 2.0
    hull = convex_hull([(i.x, i.y) for i in items])
    xs = [i.x for i in items]
    ys = [i.y for i in items]

    def evaluate(cx, cy, exact):
        half_w, half_d = size[0] / 2.0, size[1] / 2.0
        corners = [(cx + sx * half_w, cy + sy * half_d) for sx in (-1, 1) for sy in (-1, 1)]
        if min(hull_margin(hull, x, y) for x, y in corners) < margin:
            return None
        if exact:
            boxes = star_boxes(cells, footprint, (cx, cy, centre_z))
        else:
            boxes = [(cx - half_w, cx + half_w, cy - half_d, cy + half_d, bottom, bottom + height)]
        m = measure_boxes(boxes, items, volumes, hull)
        if m.d3 < margin or m.volume < margin:
            return None
        return Candidate((cx, cy, centre_z), m)

    def frange(lo, hi, step):
        n = int(math.floor((hi - lo) / step + 1.0e-9))
        return [lo + k * step for k in range(n + 1)]

    coarse_hits = []
    for cx in frange(min(xs), max(xs), coarse):
        for cy in frange(min(ys), max(ys), coarse):
            cand = evaluate(cx, cy, False)
            if cand is not None:
                coarse_hits.append(cand)
    if not coarse_hits:
        raise sl.LayoutError("No place keeps the star %.1f units inside the area of the objects and away from the boundary "
                             "volumes and objects. Try a smaller --margin." % margin)
    coarse_hits.sort(key=lambda c: (-c.key[0], -c.key[1], c.centre[0], c.centre[1]))
    picked = []
    for cand in coarse_hits:
        if all(math.hypot(cand.centre[0] - p.centre[0], cand.centre[1] - p.centre[1]) > 2.0 * coarse for p in picked):
            picked.append(cand)
        if len(picked) >= keep:
            break
    refined = []
    for cand in picked:
        best = None
        for dx in frange(-coarse, coarse, fine):
            for dy in frange(-coarse, coarse, fine):
                exact = evaluate(cand.centre[0] + dx, cand.centre[1] + dy, True)
                if exact is not None and (best is None or (-exact.key[0], -exact.key[1]) < (-best.key[0], -best.key[1])):
                    best = exact
        if best is not None:
            refined.append(best)
    if not refined:
        raise sl.LayoutError("No refined place satisfies the margins.")
    refined.sort(key=lambda c: (-c.key[0], -c.key[1], c.centre[0], c.centre[1]))
    return refined


def largest_empty_circle(items, margin=0.0, step=0.5):
    """``(radius, x, y)`` of the largest circle without an object position, centre inside the hull at least ``margin`` from its border."""
    hull = convex_hull([(i.x, i.y) for i in items])
    best = (-1.0, 0.0, 0.0)
    xs = [i.x for i in items]
    ys = [i.y for i in items]
    x = min(xs)
    while x <= max(xs):
        y = min(ys)
        while y <= max(ys):
            if hull_margin(hull, x, y) >= margin:
                r = min(math.hypot(x - i.x, y - i.y) for i in items)
                if r > best[0]:
                    best = (r, x, y)
            y += step
        x += step
    return best


# --- the commands ------------------------------------------------------------------------------------------
def parse_footprint(text):
    parts = [p.strip() for p in str(text).split(",")]
    if len(parts) != 3:
        raise ValueError("--footprint needs three comma-separated numbers (width, depth, height)")
    values = [float(p) for p in parts]
    return sl.Footprint(values[0], values[1], values[2])


def load_records(path):
    """The :class:`mvarlib.api.LoadResult` of a map variant file, which is only opened for reading."""
    sys.path.insert(0, os.path.join(REPO, "Addon"))
    from mvarlib import entry                                               # noqa: E402
    if os.path.getsize(path) > MAX_BYTES:
        raise ValueError("%s is larger than %d bytes; this does not look like a map variant" % (path, MAX_BYTES))
    with open(path, "rb") as fh:
        data = fh.read()
    return entry.load_map_variant(data, os.path.basename(path))


def run_search(args, out):
    footprint = parse_footprint(args.footprint)
    cells = sl.named_shape(args.shape)
    loaded = load_records(args.template)
    items, volumes = split_records(loaded.objects)
    ranked = search(items, volumes, cells, footprint, margin=args.margin, z_step=args.z_step)
    size = sl.extent(cells, footprint)
    out("template : %s (%d objects, %d boundary volumes)" % (args.template, len(items), len(volumes)))
    out("star     : design %s, %d blocks, mesh box %.3f x %.3f x %.3f" % (args.shape, len(cells), size[0], size[1], size[2]))
    zmax = max(i.z for i in items)
    out("height   : highest object z %.3f; star bottom %.3f, top %.3f (not above the highest object)" % (
        zmax, ranked[0].centre[2] - size[2] / 2.0, ranked[0].centre[2] + size[2] / 2.0))
    r, ex, ey = largest_empty_circle(items, args.margin)
    out("empty circle (objects only, centre %.1f inside the hull): radius %.2f at (%.2f, %.2f)" % (args.margin, r, ex, ey))
    for rank, cand in enumerate(ranked, 1):
        m = cand.measure
        out("#%d centre (%.3f, %.3f, %.3f): xy %.3f, 3d %.3f, volume %.3f, hull %.3f" % (
            rank, cand.centre[0], cand.centre[1], cand.centre[2], m.xy, m.d3, m.volume, m.hull))
    out("chosen   : --center %.3f,%.3f,%.3f" % ranked[0].centre)
    for line in ranked[0].measure.summary_lines():
        out("           " + line)
    return 0


def run_measure(args, out):
    footprint = parse_footprint(args.footprint)
    before = load_records(args.template)
    after = load_records(args.output)
    old = set(r.slot for r in before.objects)
    new = [r for r in after.objects if r.slot not in old]
    items, volumes = split_records(before.objects)
    hull = convex_hull([(i.x, i.y) for i in items])
    positions = [r.position for r in new]
    boxes = boxes_at_positions(positions, footprint)
    m = measure_boxes(boxes, items, volumes, hull)
    out("template : %s (%d objects)" % (args.template, len(items)))
    out("output   : %s (%d new objects: %s)" % (args.output, len(new), ", ".join(sorted(set(r.type_name for r in new))) or "none"))
    if boxes:
        out("star box : x %.3f to %.3f, y %.3f to %.3f, z %.3f to %.3f" % (
            m.lo[0], m.hi[0], m.lo[1], m.hi[1], m.lo[2], m.hi[2]))
        bounds = before.info.bounds
        bits = (before.info.hypothesis or {}).get("axis_bits") or [23, 23, 23]
        step = max((bounds[2 * a + 1] - bounds[2 * a]) / float(1 << bits[a]) for a in range(3))      # the file's position step
        out("overlaps : %d pair(s) of star blocks overlap by more than two position steps (%.5f; one step is %.5f)" % (
            overlap_count(boxes, 2.0 * step), 2.0 * step, step))
    for line in m.summary_lines():
        out(line)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="star_placement", description="Where the block star goes, and how much room it has (S1).")
    sub = ap.add_subparsers(dest="command")
    for name in ("search", "measure"):
        p = sub.add_parser(name)
        p.add_argument("template", metavar="TEMPLATE.mvar")
        if name == "measure":
            p.add_argument("output", metavar="OUTPUT.mvar")
        else:
            p.add_argument("--shape", choices=sl.shape_names(), default="pixel39")
            p.add_argument("--margin", type=float, default=DEFAULT_MARGIN)
            p.add_argument("--z-step", type=float, default=DEFAULT_Z_STEP, dest="z_step")
        p.add_argument("--footprint", default=",".join("%g" % v for v in DEFAULT_FOOTPRINT),
                       help="mesh box of one block: width,depth,height (default the measured 'Block, 1x1')")
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code not in (0, None) else 0
    if not args.command:
        ap.print_usage()
        return 2
    try:
        return run_search(args, print) if args.command == "search" else run_measure(args, print)
    except (ValueError, OSError, sl.LayoutError) as exc:
        print("star_placement: %s" % exc)
        return 2
    except Exception as exc:                                                 # a map variant the library refuses
        print("star_placement: %s: %s" % (type(exc).__name__, exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
