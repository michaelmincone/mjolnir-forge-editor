"""Pure geometry of the Forge block star (S1 preparation, NOTES.md D10 / D10a).

A five-pointed, pixel-art star made of axis-aligned cells, upright in a vertical plane (apex up), built from the
TRUE star polygon sampled at the centre of every cell of an N x N grid. Nothing here knows Blender, the map
variant format or the library: it turns a grid size and a block footprint into 3D positions and checks them
against the map bounds. ``tools/build_star_mvar.py`` (the Blender script) is the only caller that matters;
``tests/unit/test_star_layout.py`` pins every property below. ``NAMED_SHAPES`` holds fixed designs (S1: a 39-block
star whose feet touch along faces) for when the sampled stars do not fit the free slots of a real file.

Conventions
-----------
* A cell is ``(ix, iz)``: ``ix`` counts columns left to right (world +X), ``iz`` counts rows bottom to top
  (world +Z, up). The grid centre is ``((N - 1) / 2, (N - 1) / 2)``; the star's circumscribed circle has its
  centre there and a radius of ``N / 2`` cells. Rows without a cell (the bottom of the grid) simply do not
  appear in the result.
* ``star_cells`` returns the cells in reading order (top row first, left to right): the order is a pure
  function of ``(n, mode)``, so two calls always agree and a map variant built twice is identical.
* The star lies in the XZ plane (one layer deep along Y). A block footprint is the bounding box of the
  library mesh: ``width`` along X, ``depth`` along Y, ``height`` along Z, plus the offset of the box centre
  from the object origin. Neighbouring blocks are exactly one footprint apart, so they touch and never
  overlap.
* Symmetry about the vertical axis is exact, not approximate: the polygon is built mirror-symmetric and every
  cell is sampled at ``abs(x)``.

Python 3.9 to 3.13, standard library only, no ``bpy``, no I/O.
"""
import math

DEFAULT_GRID = 17                       # 80 filled cells (see star_cells); the task asked for roughly 60 to 120
AUTO_GRIDS = (17, 15, 13, 11, 9)        # what "auto" tries, largest first: odd sizes keep the apex on a single column
MIN_GRID = 5
MAX_GRID = 64
MODES = ("filled", "outline")
INNER_RATIO = (3.0 - math.sqrt(5.0)) / 2.0         # inner / outer radius of the regular pentagram {5/2}
DEFAULT_MARGIN = 1.0                    # world units kept free between the star's mesh and every bound
MIN_POSITION_TOL = 1.0e-3               # SPEC 4.2 DEC-4.1: the flat part of the change tolerance
MAX_CELL_BELOW_23_BITS = 0.00052084     # SPEC 4.1: a position cell is never larger than this unless an axis range exceeds ~4369


class LayoutError(ValueError):
    """The requested star cannot be laid out (bad grid, bad footprint, does not fit the map)."""


class Footprint(object):
    """Bounding box of one block mesh: ``width`` (X), ``depth`` (Y), ``height`` (Z) and the box centre.

    ``offset`` is the centre of the mesh box relative to the object's origin (the point the map variant
    stores as the position). A mesh whose origin is at its centre has offset ``(0, 0, 0)``; a mesh that
    stands on its origin has ``(0, 0, height / 2)``.
    """

    def __init__(self, width, depth, height, offset=(0.0, 0.0, 0.0)):
        for label, value in (("width", width), ("depth", depth), ("height", height)):
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise LayoutError("The block footprint %s must be a positive number (got %r)." % (label, value))
        offset = tuple(float(c) for c in offset)
        if len(offset) != 3 or not all(math.isfinite(c) for c in offset):
            raise LayoutError("The block footprint offset must be three finite numbers (got %r)." % (offset,))
        self.width = float(width)
        self.depth = float(depth)
        self.height = float(height)
        self.offset = offset

    def __repr__(self):
        return "Footprint(%.6g x %.6g x %.6g, offset=%r)" % (self.width, self.depth, self.height, self.offset)

    def __eq__(self, other):
        return (isinstance(other, Footprint) and (self.width, self.depth, self.height, self.offset) ==
                (other.width, other.depth, other.height, other.offset))

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash((self.width, self.depth, self.height, self.offset))


# --- the polygon and the cells -----------------------------------------------------------------------
def star_polygon(radius=1.0, inner_ratio=INNER_RATIO):
    """The ten vertices of the regular five-pointed star, apex up, clockwise from the apex, mirror-symmetric.

    Vertices alternate between the outer radius (the five tips) and ``inner_ratio * radius`` (the five
    notches). The left half is the exact mirror image of the right half and the two on-axis vertices have
    ``x == 0.0``, so the polygon is symmetric about the vertical axis to the last bit.
    """
    if not (isinstance(radius, (int, float)) and math.isfinite(radius) and radius > 0):
        raise LayoutError("The star radius must be a positive number (got %r)." % (radius,))
    if not (0.0 < inner_ratio < 1.0):
        raise LayoutError("The inner ratio must be between 0 and 1 (got %r)." % (inner_ratio,))
    right = []                                           # vertices k = 1 .. 4 (right side, top to bottom)
    for k in range(1, 5):
        angle = math.radians(90.0 - 36.0 * k)
        rad = radius if k % 2 == 0 else radius * inner_ratio
        right.append((rad * math.cos(angle), rad * math.sin(angle)))
    polygon = [(0.0, float(radius))]                     # k = 0, the apex
    polygon.extend(right)
    polygon.append((0.0, -radius * inner_ratio))         # k = 5, the notch between the two lower tips
    polygon.extend((-x, y) for x, y in reversed(right))
    return polygon


def point_in_polygon(x, y, polygon):
    """Even-odd ray casting; ``True`` when ``(x, y)`` is inside ``polygon`` (a list of ``(x, y)``)."""
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _check_grid(n):
    if isinstance(n, bool) or not isinstance(n, int):
        raise LayoutError("The grid size must be a whole number (got %r)." % (n,))
    if n < MIN_GRID or n > MAX_GRID:
        raise LayoutError("The grid size must be between %d and %d (got %d)." % (MIN_GRID, MAX_GRID, n))


def star_cells(n=DEFAULT_GRID, mode="filled"):
    """The cells ``[(ix, iz), ...]`` of a star on an ``n`` x ``n`` grid, in reading order.

    ``mode='filled'``: every cell whose centre lies inside the star polygon (circumradius ``n / 2`` cells,
    centred on the grid). ``mode='outline'``: the filled cells that have at least one unfilled 4-neighbour.
    Raises :class:`LayoutError` for a bad ``n`` or ``mode``.
    """
    _check_grid(n)
    if mode not in MODES:
        raise LayoutError("The star mode must be one of %s (got %r)." % (", ".join(MODES), mode))
    polygon = star_polygon(n / 2.0)
    middle = (n - 1) / 2.0
    filled = set()
    for iz in range(n):
        for ix in range(n):
            if point_in_polygon(abs(ix - middle), iz - middle, polygon):       # abs(): exact mirror symmetry
                filled.add((ix, iz))
    if mode == "outline":
        filled = set(c for c in filled if any((c[0] + dx, c[1] + dz) not in filled
                                              for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1))))
    return sorted(filled, key=lambda c: (-c[1], c[0]))


# --- named designs -----------------------------------------------------------------------------------
# The sampled stars above cannot always be used as they are. The real Breakneck file has 40 free object slots, and of
# the grids that fit them only grid 11 (34 blocks) comes close, whose two feet touch the legs at a corner only (SPEC
# of the star build, S1prep). A named design is a fixed, reviewed raster: rows from the top, ``#`` = one block. Every
# design is pinned by ``tests/unit/test_star_layout.py`` (mirror symmetric, one piece under 4-connectivity, five tips).
#
# pixel39: 39 blocks, 9 x 9, apex up. Derived once with an area-coverage raster (a cell is a block when at least half
# of it lies inside the true five-pointed star; star circumradius 6.0 rows, centre 5.7 rows above the bottom of a
# 13-row grid, 9 columns of 1.0182 x 1.0 for the measured "Block, 1x1", 6 x 6 sub-samples per cell), keeping the
# raster that is mirror symmetric, 4-connected and has at most 40 cells with the best overlap with the true star
# (0.83). The test re-derives it from that rule, so the literal below is not a free-hand drawing.
NAMED_SHAPES = {
    "pixel39": (
        "....#....",
        "....#....",
        "...###...",
        "#########",
        ".#######.",
        "..#####..",
        "..#####..",
        "..##.##..",
        ".##...##.",
    ),
}


def shape_names():
    """The names of the designs, sorted."""
    return sorted(NAMED_SHAPES)


def named_shape(name):
    """The cells ``[(ix, iz), ...]`` of a named design, in the same reading order as :func:`star_cells`.

    Raises :class:`LayoutError` for an unknown name or a malformed design (rows of different length, other characters).
    """
    if name not in NAMED_SHAPES:
        raise LayoutError("There is no star design called %r (known: %s)." % (name, ", ".join(shape_names())))
    rows = NAMED_SHAPES[name]
    if not rows or any(len(row) != len(rows[0]) for row in rows) or any(set(row) - set("#.") for row in rows):
        raise LayoutError("The star design %r is malformed." % (name,))
    height = len(rows)
    cells = [(ix, height - 1 - r) for r, row in enumerate(rows) for ix, ch in enumerate(row) if ch == "#"]
    return sorted(cells, key=lambda c: (-c[1], c[0]))


def render_cells(cells, on="#", off="."):
    """The cells as text rows, top row first, trimmed to their span (so a person can see the shape that will be built)."""
    x0, x1, z0, z1 = _spans(cells)
    taken = set(cells)
    return ["".join(on if (ix, iz) in taken else off for ix in range(x0, x1 + 1)) for iz in range(z1, z0 - 1, -1)]


def fit_grid(room, mode="filled", sizes=AUTO_GRIDS):
    """The largest grid size in ``sizes`` whose star has at most ``room`` cells, or ``None`` when even the smallest does not fit."""
    for n in sorted(sizes, reverse=True):
        if len(star_cells(n, mode)) <= room:
            return n
    return None


def tip_cells(cells, n):
    """The five tip cells, apex first then clockwise: the cell furthest in each outer vertex direction.

    Ties go to the cell with the larger radius, then to reading order, so the answer is deterministic.
    """
    _check_grid(n)
    middle = (n - 1) / 2.0
    tips = []
    for k in range(5):
        angle = math.radians(90.0 - 72.0 * k)
        dx, dz = math.cos(angle), math.sin(angle)
        best = None
        for cell in cells:
            px, pz = cell[0] - middle, cell[1] - middle
            key = (round(px * dx + pz * dz, 9), round(math.hypot(px, pz), 9), -cell[1], -cell[0])
            if best is None or key > best[0]:
                best = (key, cell)
        if best is None:
            raise LayoutError("A star without cells has no tips.")
        tips.append(best[1])
    return tips


# --- 3D positions ------------------------------------------------------------------------------------
def _spans(cells):
    if not cells:
        raise LayoutError("There are no cells to place.")
    xs = [c[0] for c in cells]
    zs = [c[1] for c in cells]
    return min(xs), max(xs), min(zs), max(zs)


def extent(cells, footprint):
    """``(width, depth, height)`` of the star's mesh box: the cells' span times the footprint, one layer deep."""
    x0, x1, z0, z1 = _spans(cells)
    return ((x1 - x0 + 1) * footprint.width, footprint.depth, (z1 - z0 + 1) * footprint.height)


def cell_positions(cells, footprint, centre):
    """Object positions ``[(x, y, z), ...]`` (same order as ``cells``) for a star whose mesh box is centred on ``centre``.

    Adjacent cells are exactly one footprint apart. The footprint's ``offset`` (mesh box centre relative to
    the object origin) is subtracted so that the MESHES, not the origins, form the centred star.
    """
    x0, x1, z0, z1 = _spans(cells)
    x_mid = (x0 + x1) / 2.0
    z_mid = (z0 + z1) / 2.0
    ox, oy, oz = footprint.offset
    cx, cy, cz = (float(c) for c in centre)
    return [(cx + (ix - x_mid) * footprint.width - ox, cy - oy, cz + (iz - z_mid) * footprint.height - oz)
            for ix, iz in cells]


def mesh_boxes(positions, footprint):
    """The mesh box ``((x0, y0, z0), (x1, y1, z1))`` of every block at ``positions``."""
    ox, oy, oz = footprint.offset
    hw, hd, hh = footprint.width / 2.0, footprint.depth / 2.0, footprint.height / 2.0
    return [((x + ox - hw, y + oy - hd, z + oz - hh), (x + ox + hw, y + oy + hd, z + oz + hh)) for x, y, z in positions]


# --- bounds ------------------------------------------------------------------------------------------
def _check_bounds_tuple(bounds):
    if len(bounds) != 6 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in bounds):
        raise LayoutError("The map bounds must be six finite numbers (xmin, xmax, ymin, ymax, zmin, zmax).")


def check_bounds(positions, footprint, bounds, margin=DEFAULT_MARGIN):
    """Problems (a list of complete sentences, empty when everything fits) with ``positions`` inside ``bounds``.

    Two rules, both required: every object position lies in ``[min, max)`` of each axis (the rule of the
    library, SPEC 4.2 / E_OUT_OF_BOUNDS: positions are never clamped), and the whole mesh box of the star stays
    ``margin`` world units away from every bound. Axes are reported once, with the extreme offender.
    """
    _check_bounds_tuple(bounds)
    if not positions:
        return ["There are no blocks to check."]
    problems = []
    boxes = mesh_boxes(positions, footprint)
    for axis, name in enumerate("xyz"):
        lo, hi = bounds[2 * axis], bounds[2 * axis + 1]
        pos_lo = min(p[axis] for p in positions)
        pos_hi = max(p[axis] for p in positions)
        mesh_lo = min(b[0][axis] for b in boxes)
        mesh_hi = max(b[1][axis] for b in boxes)
        if pos_lo < lo or pos_hi >= hi:
            problems.append("The star's block positions span %s %.3f to %.3f, outside the map bounds (%s %.1f to %.1f). "
                            "Move the star inside; positions are never clamped." % (name, pos_lo, pos_hi, name, lo, hi))
        elif mesh_lo < lo + margin or mesh_hi > hi - margin:
            problems.append("The star's blocks reach %s %.3f to %.3f, closer than the margin of %.2f to the map bounds "
                            "(%s %.1f to %.1f)." % (name, mesh_lo, mesh_hi, margin, name, lo, hi))
    return problems


def choose_centre(bounds, size, margin=DEFAULT_MARGIN, ground_z=None, requested=(None, None, None)):
    """The centre ``(x, y, z)`` of the star's mesh box.

    ``requested`` holds the user's choice per axis (``None`` = automatic). Automatic X and Y are the middle of
    the bounds. Automatic Z puts the star's bottom edge at ``ground_z`` when given (a typical height of the
    objects already on the map), else the middle of the vertical bounds; it is then moved the shortest way into
    ``[zmin + margin, zmax - margin]``. A requested axis is used as given (``check_bounds`` judges it). Raises
    :class:`LayoutError` when an automatic axis cannot fit the star at all.
    """
    _check_bounds_tuple(bounds)
    if len(requested) != 3:
        raise LayoutError("The requested centre must have three components.")
    centre = []
    for axis in range(3):
        lo, hi = bounds[2 * axis], bounds[2 * axis + 1]
        half = size[axis] / 2.0
        if requested[axis] is not None:
            value = float(requested[axis])
            if not math.isfinite(value):
                raise LayoutError("The requested centre must be finite (got %r)." % (requested[axis],))
            centre.append(value)
            continue
        low_limit, high_limit = lo + margin + half, hi - margin - half
        if low_limit > high_limit:
            raise LayoutError("The star is %.2f wide on the %s axis but the map only allows %.2f there (bounds %.1f "
                              "to %.1f, margin %.2f). Use a smaller grid." % (size[axis], "xyz"[axis],
                                                                              hi - lo - 2 * margin, lo, hi, margin))
        if axis == 2 and ground_z is not None:
            value = float(ground_z) + half
        else:
            value = (lo + hi) / 2.0
        centre.append(min(max(value, low_limit), high_limit))
    return tuple(centre)


# --- quantisation tolerance and matching --------------------------------------------------------------
def position_tolerance(bounds):
    """Per-axis tolerance ``(tx, ty, tz)`` for "this written position was read back".

    One encode / decode is exact to half a cell; a cell is at most 0.00052084 world units unless an axis range
    exceeds about 4369 (then ``range / 2**23``), SPEC 4.1 / 4.2. The tolerance is twice that, never below the
    library's own flat 1.0e-3 (4.2 DEC-4.1), plus two float32 spacings at the largest coordinate (Blender and the
    stub keep float32). A zero-range axis gets the flat minimum.
    """
    _check_bounds_tuple(bounds)
    out = []
    for axis in range(3):
        lo, hi = bounds[2 * axis], bounds[2 * axis + 1]
        cell = max(MAX_CELL_BELOW_23_BITS, (hi - lo) / 8388608.0)
        biggest = max(abs(lo), abs(hi), 1.0)
        ulp32 = 2.0 ** (math.floor(math.log2(biggest)) - 23)
        out.append(max(MIN_POSITION_TOL, 2.0 * cell) + 2.0 * ulp32)
    return tuple(out)


class Matching(object):
    """Result of :func:`match_positions`."""

    def __init__(self, pairs, missing, extra, worst):
        self.pairs = pairs               # [(expected index, actual index)]
        self.missing = missing           # expected indices with no partner within the tolerance
        self.extra = extra               # actual indices nobody expected
        self.worst = worst               # largest per-axis error among the pairs, (ex, ey, ez)

    @property
    def ok(self):
        return not self.missing and not self.extra


def match_positions(expected, actual, tol):
    """One-to-one matching of ``expected`` to ``actual`` positions within a per-axis tolerance (nearest first).

    Order does not matter (the library decides which free slot each new block gets). ``tol`` is a 3-tuple or a
    single number.
    """
    if isinstance(tol, (int, float)):
        tol = (tol, tol, tol)
    candidates = []
    for i, e in enumerate(expected):
        for j, a in enumerate(actual):
            d = (abs(e[0] - a[0]), abs(e[1] - a[1]), abs(e[2] - a[2]))
            if d[0] <= tol[0] and d[1] <= tol[1] and d[2] <= tol[2]:
                candidates.append((d[0] * d[0] + d[1] * d[1] + d[2] * d[2], i, j, d))
    candidates.sort()
    used_e, used_a, pairs = set(), set(), []
    worst = [0.0, 0.0, 0.0]
    for _dist, i, j, d in candidates:
        if i in used_e or j in used_a:
            continue
        used_e.add(i)
        used_a.add(j)
        pairs.append((i, j))
        worst = [max(w, v) for w, v in zip(worst, d)]
    missing = [i for i in range(len(expected)) if i not in used_e]
    extra = [j for j in range(len(actual)) if j not in used_a]
    return Matching(sorted(pairs), missing, extra, tuple(worst))
