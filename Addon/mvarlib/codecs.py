"""Pure field codecs of the map variant body (SPEC section 4, 3.9, 3.11; gate G3).

Everything here is a pure function of its arguments (no I/O, no state), written from the spec text.

* Axis bit counts from the bounds (4.1): three rounding variants (``ceil`` with the JS double
  constant, ``trunc9999`` in float32, ``ceil_f32`` with the engine's own float32 constant) and the
  distinct triples they produce (``axis_bit_hypotheses``), each one a hypothesis of the walk (3.10).
* Position codec (4.2): cell-centre decode, floor encode that refuses (never clamps) values outside
  ``[min, max)``, and the change tolerance ``POS_TOL``.
* Shape dimension codec (4.3, 11 bits, 0 to 200) and angle codec (4.4, 14 bits).
* Up axis, the 20-bit cube-face code (4.5): decode only. ``reconstruct_orientation`` (4.6) turns an
  up code plus a 14-bit angle into ``(forward, up)``; it is **UNVERIFIED and display only**.
* Team, colour and placement-byte views (3.9, 3.11). The placement view uses the file reading (HMS)
  of the disputed byte; nothing but the physics bits may be edited (DEC-3.9).

Pure Python 3.9 to 3.13, standard library only, relative imports only.
"""
import math
import struct
from collections import namedtuple
from typing import List, Tuple

from .errors import DecodeError, EncodeError

__all__ = [
    "f32", "MIN_UNIT_16", "STEP_FLOOR", "ENGINE_UNIT_16", "AXIS_BASE_BITS", "AXIS_MAX_BITS", "AXIS_MAX_CELLS",
    "AXIS_VARIANTS", "bits_from_cells", "axis_bits_ceil", "axis_bits_trunc", "axis_bits_ceil_f32",
    "axis_bit_hypotheses", "axis_ranges", "pos_cell", "pos_decode", "pos_encode", "pos_tolerance", "ulp32",
    "DIM_MAX", "DIM_BITS", "dim_decode", "dim_encode", "ANGLE_STEP", "angle_decode", "angle_encode",
    "UP_STRIDE", "UP_N", "UP_CODE_MAX_VALID", "up_parts", "up_decode", "reconstruct_orientation",
    "PlacementView", "placement_view", "placement_with_physics", "team_view", "team_raw", "color_view",
    "color_raw", "PHYSICS_NAMES", "SYMMETRY_NAMES", "TEAM_NEUTRAL",
]

# ---------------------------------------------------------------------------------------------
# float32 helper
# ---------------------------------------------------------------------------------------------


def f32(x):
    """Round a Python float to the nearest float32 (and back). Overflow gives +-inf, NaN stays NaN."""
    try:
        return struct.unpack(">f", struct.pack(">f", x))[0]
    except OverflowError:
        return math.inf if x > 0 else -math.inf


# ---------------------------------------------------------------------------------------------
# 4.1 Axis bit counts
# ---------------------------------------------------------------------------------------------
MIN_UNIT_16 = 0.00833333333            # JS constant; the engine's f32 constant is ENGINE_UNIT_16
STEP_FLOOR = 0.0001                    # f32 0x38D1B717
ENGINE_UNIT_16 = 0.008333333767950535  # f32 0x3C088889 exactly
AXIS_BASE_BITS = 21
AXIS_MAX_BITS = 26
AXIS_MAX_CELLS = 0x800000
TRUNC_FUDGE = 0.9999
AXIS_VARIANTS = ("ceil", "trunc9999", "ceil_f32")


def bits_from_cells(n):
    """``ceil(log2(n))``; 0 for ``n <= 1`` (the JS highest-bit-plus-remainder test, 4.1)."""
    return 0 if n <= 1 else (n - 1).bit_length()


def _cells_ceil(x):
    """``min(0x800000, ceil(x))`` that survives inf and NaN (a huge range is capped, a NaN gives no cells)."""
    if x != x:
        return 0
    if x >= float(AXIS_MAX_CELLS):
        return AXIS_MAX_CELLS
    return max(0, int(math.ceil(x)))


def axis_bits_ceil(rng, base=AXIS_BASE_BITS):
    """Variant ``ceil`` (JS), double precision."""
    step = MIN_UNIT_16 / (1 << (base - 16))
    if step < STEP_FLOOR:
        return AXIS_MAX_BITS
    step *= 2
    return min(AXIS_MAX_BITS, bits_from_cells(_cells_ceil(rng / step)))


def axis_bits_trunc(rng, base=AXIS_BASE_BITS):
    """Variant ``trunc9999`` (HMS): float32 arithmetic and ``+ 0.9999`` then truncate."""
    step = f32(f32(f32(MIN_UNIT_16) / f32(1 << (base - 16))) * 2.0)
    q = f32(f32(f32(rng) / step) + f32(TRUNC_FUDGE))
    if q != q:
        cells = 0
    else:
        cells = int(min(float(AXIS_MAX_CELLS), max(0.0, q)))
    return min(AXIS_MAX_BITS, bits_from_cells(cells))


def axis_bits_ceil_f32(rng, base=AXIS_BASE_BITS):
    """Variant ``ceil_f32``: the engine's own float32 constant, float32 arithmetic, then ceil."""
    step = f32(f32(f32(ENGINE_UNIT_16) / f32(1 << (base - 16))) * 2.0)
    return min(AXIS_MAX_BITS, bits_from_cells(_cells_ceil(f32(f32(rng) / step))))


_VARIANT_FUNCS = {"ceil": axis_bits_ceil, "trunc9999": axis_bits_trunc, "ceil_f32": axis_bits_ceil_f32}


def axis_ranges(bounds):
    """The two ways an axis range is computed: ``(double_ranges, f32_ranges)``, three values each.

    ``bounds`` is ``(xmin, xmax, ymin, ymax, zmin, zmax)`` as the float32 values decoded from the file.
    """
    pairs = [(bounds[0], bounds[1]), (bounds[2], bounds[3]), (bounds[4], bounds[5])]
    doubles = tuple(mx - mn for mn, mx in pairs)
    singles = tuple(f32(mx - mn) for mn, mx in pairs)
    return doubles, singles


def axis_bit_hypotheses(bounds) -> List[Tuple[int, int, int]]:
    """The distinct ``(bx, by, bz)`` triples of all rounding variants, primary (``ceil`` on the double range) first.

    Two range computations (the double difference of the float32-decoded bounds, and the float32
    of that difference) times the three variants of 4.1; duplicates removed, first-seen order. Almost
    every file yields exactly one triple; they differ only when a range sits within about 1e-7
    (relative) of an exact cell-count threshold.
    """
    doubles, singles = axis_ranges(bounds)
    out = []
    for ranges in (doubles, singles):
        for name in AXIS_VARIANTS:
            func = _VARIANT_FUNCS[name]
            triple = tuple(func(r) for r in ranges)
            if triple not in out:
                out.append(triple)
    # the primary triple (ceil on the double range) must be first: it is, by construction of the loop
    return out


# ---------------------------------------------------------------------------------------------
# 4.2 Position codec
# ---------------------------------------------------------------------------------------------


def pos_cell(bits, mn, mx):
    """Cell size in world units."""
    return (mx - mn) / float(1 << bits)


def pos_decode(q, bits, mn, mx):
    """Cell centre of cell ``q`` (4.2). Bits may be 0 (a zero-range axis decodes to ``mn``)."""
    return (q + 0.5) * pos_cell(bits, mn, mx) + mn


def pos_encode(v, bits, mn, mx):
    """Containing cell of ``v``; ``EncodeError`` (never a clamp) outside ``[mn, mx)``."""
    if not (v == v and mn <= v < mx):
        raise EncodeError("The position %r is outside the map bounds [%r, %r)." % (v, mn, mx))
    cell = pos_cell(bits, mn, mx)
    return min((1 << bits) - 1, int(math.floor((v - mn) / cell)))


def ulp32(m):
    """Spacing of float32 values just above ``abs(m)``: ``2 ** (floor(log2(m)) - 23)`` (0.0 for 0)."""
    m = abs(m)
    if m == 0.0 or m != m or m == math.inf:
        return 0.0
    _, exponent = math.frexp(m)          # m = f * 2**exponent with 0.5 <= f < 1, so floor(log2 m) = exponent - 1
    return math.ldexp(1.0, exponent - 1 - 23)


def pos_tolerance(bits, mn, mx):
    """``POS_TOL = max(1e-3, 0.5 * cell, 2 * ulp32(M))`` with ``M = max(abs(mn), abs(mx))`` (DEC-4.1)."""
    return max(1.0e-3, 0.5 * pos_cell(bits, mn, mx), 2.0 * ulp32(max(abs(mn), abs(mx))))


# ---------------------------------------------------------------------------------------------
# 4.3 Shape dimension codec
# ---------------------------------------------------------------------------------------------
DIM_BITS = 11
DIM_MAX = 200.0


def dim_decode(v):
    """Dimension for the 11-bit code ``v`` (0 -> 0.0, 0x7FF -> 200.0, else cell centre of ``200/2046`` steps)."""
    if not isinstance(v, int) or not 0 <= v <= 0x7FF:
        raise DecodeError("A shape dimension code must be 0 to 2047, got %r." % (v,))
    if v == 0:
        return 0.0
    if v == 0x7FF:
        return 200.0
    return (v - 1) * 0.0977517142892 + 0.0488758571446


def dim_encode(x):
    """Code for the dimension ``x``; ``EncodeError`` outside ``0 .. 200``."""
    if not (x == x and 0.0 <= x <= DIM_MAX):
        raise EncodeError("A shape dimension must be between 0 and 200, got %r." % (x,))
    if x == 0.0:
        return 0
    if x == DIM_MAX:
        return 0x7FF
    return max(1, min(2046, int(math.floor(x * 2046.0 / 200.0 + 1.0))))


# ---------------------------------------------------------------------------------------------
# 4.4 Angle codec
# ---------------------------------------------------------------------------------------------
ANGLE_STEP = 2 * math.pi / 16384


def angle_decode(raw):
    """Angle in radians for the 14-bit code (cell centre, -pi .. pi)."""
    if not isinstance(raw, int) or not 0 <= raw <= 0x3FFF:
        raise DecodeError("An angle code must be 0 to 16383, got %r." % (raw,))
    return (raw + 0.5) * ANGLE_STEP - math.pi


def angle_encode(theta):
    """14-bit code of an angle in ``[-pi, pi]``; ``EncodeError`` for NaN or infinity."""
    if not (theta == theta and abs(theta) != math.inf):
        raise EncodeError("An angle must be a finite number, got %r." % (theta,))
    return max(0, min(16383, int(math.floor((theta + math.pi) / ANGLE_STEP))))


# ---------------------------------------------------------------------------------------------
# 4.5 Up axis (decode only) and 4.6 orientation reconstruction (UNVERIFIED, display only)
# ---------------------------------------------------------------------------------------------
UP_STRIDE = 174762                      # floor(2**20 / 6)
UP_N = 417                              # isqrt(STRIDE) - 1
UP_CODE_MAX_VALID = 6 * UP_STRIDE - 1   # 1,048,571: faces 0..5; 1,048,572 .. 1,048,575 are invalid


def up_parts(code):
    """``(face, u, v)`` of an up code. ``face`` may be above 5 for the four invalid codes (no exception)."""
    if not isinstance(code, int) or not 0 <= code < (1 << 20):
        raise DecodeError("An up-axis code must be 0 to 1048575, got %r." % (code,))
    face = code // UP_STRIDE
    rem = code - face * UP_STRIDE
    return face, rem // UP_N, rem % UP_N


def _normalise(vec):
    length = math.sqrt(vec[0] * vec[0] + vec[1] * vec[1] + vec[2] * vec[2])
    if length == 0.0:
        raise DecodeError("A zero-length vector cannot be normalised.")
    return (vec[0] / length, vec[1] / length, vec[2] / length)


def up_decode(code):
    """Unit vector for a 20-bit cube-face code. ``DecodeError`` for the invalid codes (face above 5)."""
    face, u, v = up_parts(code)
    if face > 5:
        raise DecodeError("The up-axis code %d is invalid (cube face %d; codes above %d do not exist)."
                          % (code, face, UP_CODE_MAX_VALID))
    cu = (2 * u + 1) / 416.0 - 1.0
    cv = (2 * v + 1) / 416.0 - 1.0
    if face == 0:
        vec = (1.0, cu, cv)
    elif face == 1:
        vec = (cu, 1.0, cv)
    elif face == 2:
        vec = (cu, cv, 1.0)
    elif face == 3:
        vec = (-1.0, cu, cv)
    elif face == 4:
        vec = (cu, -1.0, cv)
    else:
        vec = (cu, cv, -1.0)
    return _normalise(vec)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def reconstruct_orientation(up_global, up_code, angle_raw):
    """``(forward, up)`` for a slot's stored orientation (4.6). UNVERIFIED, display only.

    Vertical (``up_global`` set): ``up = (0, 0, 1)``, ``forward = (cos t, sin t, 0)``. Tilted: ``up`` from
    the code, ``ref`` = Gram-Schmidt of +X against ``up`` (+Y when ``up`` is nearly along X),
    ``forward = ref cos t + (up x ref) sin t``. The counter-clockwise sense and the reference vector are
    guesses; an object whose orientation does not change keeps its raw bits, so a wrong guess cannot be
    exported.
    """
    t = angle_decode(angle_raw)
    ct, st = math.cos(t), math.sin(t)
    if up_global:
        return (ct, st, 0.0), (0.0, 0.0, 1.0)
    up = up_decode(up_code)
    axis = (1.0, 0.0, 0.0) if abs(up[0]) <= 0.99999 else (0.0, 1.0, 0.0)
    d = _dot(axis, up)
    ref = _normalise((axis[0] - d * up[0], axis[1] - d * up[1], axis[2] - d * up[2]))
    side = _cross(up, ref)
    forward = (ref[0] * ct + side[0] * st, ref[1] * ct + side[1] * st, ref[2] * ct + side[2] * st)
    return forward, up


def native_tilt_reference(up):
    """Pinned Reach FUN_1800dbff4: normalize Y-cross-up or up-cross-X.

    The branch is abs(up.y) > abs(up.x). Its two output axes are
    corroborated by disassembly of DLL SHA-256 738dd2d2...b0894.
    """
    return _normalise((0.0, up[2], -up[1]) if abs(up[1]) > abs(up[0])
                      else (up[2], 0.0, -up[0]))


def reconstruct_native_orientation(up_global, up_code, angle_raw):
    if up_global:
        return reconstruct_orientation(up_global, up_code, angle_raw)
    up = up_decode(up_code)
    reference = native_tilt_reference(up)
    side = _cross(up, reference)
    angle = angle_decode(angle_raw)
    return tuple(reference[i] * math.cos(angle) + side[i] * math.sin(angle) for i in range(3)), up


def up_encode_native(vector):
    """Native 20-bit face/tangent packing; ties prefer Z, then Y, then X."""
    up = tuple(f32(value) for value in _normalise(tuple(float(v) for v in vector)))
    absolute = tuple(abs(v) for v in up)
    axis = 0 if absolute[0] > absolute[1] and absolute[0] > absolute[2] else (1 if absolute[1] > absolute[2] else 2)
    face = axis if up[axis] > 0 else axis + 3
    step = f32(2.0 / 416.0)
    tangents = [f32(v / absolute[axis]) for i, v in enumerate(up) if i != axis]
    cells = [min(415, max(0, int(f32(f32(v + 1.0) / step)))) for v in tangents]
    return face * UP_STRIDE + cells[0] * UP_N + cells[1]


def orientation_encode_native(forward, up):
    u = _normalise(tuple(float(v) for v in up))
    if abs(u[0]) < 0.0001 and abs(u[1]) < 0.0001 and abs(u[2] - 1.0) < 0.0001:
        return 1, None, angle_encode(math.atan2(forward[1], forward[0]))
    code = up_encode_native(u)
    stored_up = up_decode(code)
    reference = native_tilt_reference(stored_up)
    side = _cross(stored_up, reference)
    return 0, code, angle_encode(math.atan2(_dot(forward, side), _dot(forward, reference)))


# ---------------------------------------------------------------------------------------------
# 3.9 / 3.11 Placement byte, team and colour views
# ---------------------------------------------------------------------------------------------
# File reading (HMS) of the disputed placement byte (3.9): bits 6-7 physics, bit 5 game specific, bit 4 NOT
# placed at start (inverted), bit 3 symmetric, bit 2 asymmetric. Bits 0 and 1 are not decoded.
PlacementView = namedtuple("PlacementView", ["physics", "symmetry", "place_at_start", "game_specific"])
PHYSICS_NAMES = {0: "normal", 1: "fixed", 2: "unused", 3: "phased"}
SYMMETRY_NAMES = {0: "neither", 1: "asymmetric only", 2: "symmetric only", 3: "both"}
TEAM_NEUTRAL = 8


def placement_view(byte):
    """Decoded view of a placement byte (file reading, 3.9): ``physics`` 0..3 (2 stays 2), ``symmetry`` 0..3
    (0 neither, 1 asymmetric only, 2 symmetric only, 3 both), ``place_at_start`` (bit 4 clear), ``game_specific``."""
    if not isinstance(byte, int) or not 0 <= byte <= 0xFF:
        raise DecodeError("A placement byte must be 0 to 255, got %r." % (byte,))
    return PlacementView((byte >> 6) & 3, (byte >> 2) & 3, not (byte & 0x10), bool(byte & 0x20))


def placement_with_physics(byte, physics):
    """``byte`` with the physics bits (6-7) replaced; every other bit is kept (the only editable part, DEC-3.9)."""
    if physics not in (0, 1, 2, 3):
        raise EncodeError("Physics must be 0 to 3, got %r." % (physics,))
    return (byte & 0x3F) | (physics << 6)


def team_view(raw):
    """Team for the stored value: ``raw - 1`` (-1 none, 0..8 teams, 8 = neutral)."""
    return raw - 1


def team_raw(view):
    """Stored team value for a team ``view`` in 0..8 (none cannot be written: it is stored as 0 only by copying)."""
    if not isinstance(view, int) or not 0 <= view <= 14:
        raise EncodeError("A team must be 0 to 8, got %r." % (view,))
    return view + 1


def color_view(color):
    """Colour for the stored optional value: ``None`` (absent bit) -> -1 (team colour), else 0..7."""
    return -1 if color is None else color


def color_raw(view):
    """Stored optional colour for a colour ``view``: -1 -> ``None``; 0..7 -> itself; 8 (neutral) is refused."""
    if view == -1:
        return None
    if not isinstance(view, int) or not 0 <= view <= 7:
        raise EncodeError("A colour must be -1 (team colour) or 0 to 7, got %r." % (view,))
    return view
