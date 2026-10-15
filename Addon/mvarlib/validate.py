"""Validation rules and issue codes of the export (SPEC section 7; gate G5).

This module is the single source of the user-facing texts of SPEC 7.3 and 5.8: ``MESSAGES`` maps every issue
code to ``(severity, message pattern)`` and :func:`make` builds the ``api.Issue``. The patterns are the spec's
patterns verbatim (a test compares this table with the table of ``docs/mvar/SPEC-mvar.md``, so a drifting word
fails). It also holds the pure per-object field checks of 5.10 step 3, the orientation helpers of 4.7 and 4.8,
and the quota rule of 7.5. Nothing here touches a model or a file: ``edit.py`` plans with these functions.

Codes marked ``GLUE_CODES`` are produced by the Blender glue (``Addon/mjolnir.py``, ``Addon/io_ops.py``) or by
``io.py``; their texts live here so that one test can pin every pattern of 7.3 in one place.

Codes added by gate G5 beyond the spec's table (each is explained in ``docs/mvar/notes/G5.md``):
``E_COLOR_RANGE`` and ``E_PHYSICS_RANGE`` (a colour or a physics value that no enum can produce),
``E_OPTION_INVALID`` (an unknown ``fsm_policy`` / ``hash_policy`` string) and ``W_QUOTA_MAX_RAISED``
(decision D11, interface freeze v2; the text is also in SPEC 7.3).

Pure Python 3.9 to 3.13, standard library only, relative imports only.
"""
import math
from typing import List, Optional, Tuple

from .api import Issue

__all__ = ["MESSAGES", "LIBRARY_CODES", "GLUE_CODES", "SHAPE_KIND_PATTERN", "make", "pattern", "ANG_TOL",
           "MIN_VECTOR_LENGTH", "DIM_NAMES", "to_int", "finite_vec", "valid_transform", "normalise", "angle_between",
           "yaw_of", "orientation_unchanged", "check_fields", "check_other", "other_limits", "quota_decision",
           "physics_norm", "palette_name_for_folder"]

ANG_TOL = 1.0e-4                    # SPEC 4.8 / 4.9: forward and up unchanged within this angle (radians)
MIN_VECTOR_LENGTH = 1.0e-6          # SPEC 4.8 (6): shorter forward / up vectors are invalid

# ---------------------------------------------------------------------------------------------
# The texts (SPEC 7.3, 5.8). Severity, pattern. A pattern is applied with ``pattern % args``.
# ---------------------------------------------------------------------------------------------
MESSAGES = {
    "E_NO_TEMPLATE": ("error", "This scene has no imported map variant. Import a .mvar first: export patches the imported file."),
    "E_TEMPLATE_CORRUPT": ("error", "The map variant stored in this scene is damaged (checksum mismatch). Import the original file again."),
    "E_TEMPLATE_UNREADABLE": ("error", "The imported map variant could not be read again: %s"),
    "E_MAP_UNKNOWN": ("error", "Map id %d (0x%X) is not one of the 20 stock Halo: Reach maps this tool supports. Export is limited to stock maps."),
    "E_CONTAINER_SHAPE": ("error", "This file's block layout (%s) cannot be modified safely."),
    "E_TOO_MANY": ("error", "%d objects would be written; the limit is %d. Remove %d object(s). (A file that already holds more than %d objects cannot be exported.)"),
    "E_NO_FREE_SLOT": ("error", "No free object slot is left for '%s'."),
    "E_OBJ_NO_TYPE": ("error", "Object '%s' has no Forge object type. Add it with Add > Forge Object, or duplicate an imported object."),
    "E_OBJ_NAME_UNKNOWN": ("error", "Object '%s' uses '%s', which is not a stock object on %s."),
    "E_OBJ_NOT_STOCK": ("error", "Object '%s' (id 0x%04X) is not a stock object on %s."),
    "E_FOLDER_RANGE": ("error", "Object '%s' needs palette entry %d, but this map variant defines only %d entries."),
    "E_OUT_OF_BOUNDS": ("error", "Object '%s' is at (%.3f, %.3f, %.3f), outside the map bounds (x %.1f to %.1f, y %.1f to %.1f, z %.1f to %.1f). Move it inside; positions are never clamped."),
    "E_QUOTA": ("error", "Palette entry %d (%s) would have %d placed; the maximum on this map variant is %d."),
    "E_QUOTA_MIN": ("error", "Palette entry %d (%s) would drop to %d placed; the minimum on this map variant is %d."),
    "E_QUOTA_RANGE": ("error", "Palette entry %d (%s) cannot hold more than 255 objects."),
    "E_CACHED_TYPE_UNKNOWN": ("error", "Cannot add a new '%s': its game object class is not known from this map variant. Place one in the game and import again, or duplicate an object of the same kind."),
    "E_CACHED_TYPE_CHANGED": ("error", "Object '%s': the object class cannot be changed."),
    "E_RETARGET_CLASS": ("error", "Object '%s' cannot change from '%s' to '%s': they are different object classes."),
    "E_TYPE19_UNDETERMINED": ("error", "Location-name objects cannot be created or edited yet: this map variant contains none, so how they are stored is undetermined."),
    "E_ROTATION_GATED": ("error", "Object '%s' has a new or changed rotation. Writing rotation is unverified: tick Forge Scene > \"Allow unverified rotation export\" to write it."),
    "E_TILT_UNSUPPORTED": ("error", "Object '%s' is tilted. Writing a tilted orientation is not supported; rotate it around Z only, or leave its rotation unchanged."),
    "E_MIRRORED": ("error", "Object '%s' has a mirrored (negative scale) transform, which cannot be exported."),
    "E_TRANSFORM_INVALID": ("error", "Object '%s' has an invalid (non-finite or zero-length) position, forward or up vector and cannot be exported."),
    "E_ARRAY_NOT_EVALUATED": ("error", "Array '%s' is hidden, excluded or empty, so its instances cannot be read. Unhide it, include its collection or apply the array, then export again."),
    "E_FLAG_UNVERIFIED": ("error", "Object '%s': %s cannot be changed yet; how it is stored is unverified."),
    "E_COLOR_NEUTRAL": ("error", "Object '%s': the colour \"Neutral\" cannot be stored in a map variant (use colours 0 to 7 or \"Team\")."),
    "E_TEAM_RANGE": ("error", "Object '%s': team must be 0 to 8."),
    "E_SHAPE_RANGE": ("error", "Object '%s': %s must be between 0 and 200 (got %.3f)."),
    "E_SPAWN_RANGE": ("error", "Object '%s': spawn sequence must be -128 to 127 and spawn time 0 to 255."),
    "E_LABEL_RANGE": ("error", "Object '%s': label %d is not in this map variant's label table (%d labels)."),
    "E_OTHER_RANGE": ("error", "Object '%s': %s must be 0 to %d."),
    "E_CAPACITY": ("error", "The edited map variant needs %d bits; it can hold at most 229,376."),
    "E_PATH_SAME_AS_SOURCE": ("error", "Refusing to overwrite the file this map was imported from (%s). Choose a different name."),
    "E_PATH_PROTECTED": ("error", "Refusing to write into the protected folder %s."),
    # added by gate G5 (see the module docstring)
    "E_COLOR_RANGE": ("error", "Object '%s': the colour must be -1 (team colour) or 0 to 7 (got %d)."),
    "E_PHYSICS_RANGE": ("error", "Object '%s': physics must be 0 (normal), 1 (fixed) or 3 (phased) (got %d)."),
    "E_OPTION_INVALID": ("error", "The export option %s has the unknown value %r."),
    # warnings
    "W_HASH_UNKNOWN": ("warning", "The template's SHA-1 matches no known recipe; the salted recipe was written. Whether MCC checks it is unknown."),
    "W_GUID_VERSION_MISMATCH": ("warning", "This map variant says it has version %d but the 128-bit block that versions 32 and above carry is %s; it was read that way because only that reading fits."),
    "W_VERSION_MISMATCH": ("warning", "The map variant block has chunk version %d but its body says version %d."),
    "W_CHUNK_VERSION_UNEXPECTED": ("warning", "The map variant block has chunk version %d; Halo: Reach uses 31 or 32. It was read anyway because the layout fits."),
    "W_ZERO_RANGE_AXIS": ("warning", "The map bounds have no extent on the %s axis; positions on that axis cannot be changed."),
    "W_TRAILER_KEPT": ("warning", "%d bytes after the end-of-file block were kept unchanged."),
    "W_CMP_EXPANDED": ("warning", "The map variant was stored compressed; the exported file stores it uncompressed (the game accepts both, per the available documentation)."),
    "W_FSM_STALE": ("warning", "The file-share signature block (_fsm) was kept unchanged. If MCC refuses the file, export again with fsm_policy = DROP."),
    "W_TOKEN_MISMATCH": ("warning", "Object '%s' claims slot %d but does not match the imported file (copied from another file?); it was treated as a new object."),
    "W_DUPLICATE_SLOT": ("warning", "Objects '%s' and '%s' both claim slot %d; kept '%s' and treated '%s' as new."),
    "W_SLOT_NOT_IMPORTED": ("warning", "Slot %d could not be imported earlier; it was left unchanged in the exported file."),
    "W_PARENT_CLEARED": ("warning", "Slot %d lost its \"spawn relative to\" parent because slot %d was deleted."),
    "W_HIDDEN_EXPORTED": ("warning", "%d hidden object(s) were exported. Hidden objects are not skipped; delete them to remove them from the map."),
    "W_ORIENTATION_UNVERIFIED": ("warning", "%d object(s) had their rotation written with an unverified convention."),
    "W_CACHED_TYPE_ASSUMED": ("warning", "The object class of the new '%s' was assumed from its palette group, not learned from the map."),
    "W_DISPUTED_ID": ("warning", "The id of '%s' differs between the two source tables on %s; check it in the game."),
    "W_UNKNOWN_TYPE_KEPT": ("warning", "Object '%s' has an id (0x%04X) this tool does not know on %s; it was kept exactly as imported."),
    "W_QUOTA_MAX_RAISED": ("warning", "Quota maximum raised: unverified. Palette entry %d (%s) now has %d placed; its maximum was raised from %d to %d. Whether the game honours the file's maximum or rebuilds it from the scenario is unknown."),
    # info (the notes of 5.8 and the zero-hash note of 2.7)
    "I_BUDGET": ("info", "Budget was not recalculated: item prices are not stored in the map variant, so the spent-budget value was copied unchanged. Open the map in Forge and check the budget meter before playing."),
    "I_PALETTE": ("info", "Edits were written against the palette recorded in the file (CRC 0x%08X). If MCC rebuilds the variant from the scenario, changes may be lost (unverified)."),
    "I_UNVERIFIED": ("info", "This tool has never been checked against a real MCC load. Follow the test ladder in the documentation (NOTES.md) before relying on the output."),
    "I_HASH_ZERO": ("info", "The template carries no SHA-1 (20 zero bytes, which KSoft.Blam documents for MCC-written game variants); none was written."),
}

# E_SHAPE_RANGE has two conditions in SPEC 7.3 but one pattern (for a dimension). A shape kind outside 0..3 uses this sentence.
SHAPE_KIND_PATTERN = "Object '%s': the shape must be 0 (none), 1 (radius only), 2 (cylinder) or 3 (box) (got %d)."

# Produced by the Blender glue (Addon/mjolnir.py, Addon/io_ops.py) or by io.py, not by export_map_variant.
GLUE_CODES = frozenset(["E_NO_TEMPLATE", "E_TEMPLATE_CORRUPT", "E_MIRRORED", "E_ARRAY_NOT_EVALUATED", "E_PATH_SAME_AS_SOURCE",
                        "E_PATH_PROTECTED", "W_HIDDEN_EXPORTED"])
# Produced by the library (read-time W_ codes that appear in an export, the render warnings and the notes included).
LIBRARY_CODES = frozenset(c for c in MESSAGES if c not in GLUE_CODES)


def pattern(code):
    """The message pattern of ``code``."""
    return MESSAGES[code][1]


def make(code, *args, **kwargs):
    """The ``api.Issue`` for ``code`` with its pattern filled from ``args``; ``slot=`` and ``object_name=`` are optional."""
    severity, text = MESSAGES[code]
    message = text % args
    return Issue(code, severity, message, kwargs.get("slot"), kwargs.get("object_name"))


# ---------------------------------------------------------------------------------------------
# small value helpers
# ---------------------------------------------------------------------------------------------
def to_int(value):
    """``value`` as an int when it is one (a float with an integral value counts), else ``None``. Booleans are ints."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value == int(value):
        return int(value)
    return None


def finite_vec(v):
    """True for a sequence of three finite numbers."""
    try:
        return len(v) == 3 and all(isinstance(x, (int, float)) and math.isfinite(x) for x in v)
    except TypeError:
        return False


def _length(v):
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def valid_transform(obj):
    """5.10 step 3 / DEC-4.8 (6): finite position, finite forward and up of length at least ``MIN_VECTOR_LENGTH``."""
    if not (finite_vec(obj.position) and finite_vec(obj.forward) and finite_vec(obj.up)):
        return False
    return _length(obj.forward) >= MIN_VECTOR_LENGTH and _length(obj.up) >= MIN_VECTOR_LENGTH


def normalise(v):
    n = _length(v)
    return (v[0] / n, v[1] / n, v[2] / n)


def angle_between(a, b):
    """Angle in radians between two (not necessarily unit) vectors; accurate for tiny angles."""
    a = normalise(a)
    b = normalise(b)
    cross = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    return math.atan2(_length(cross), dot)


def yaw_of(forward):
    """``atan2(forward.y, forward.x)`` (SPEC 4.7), or ``None`` when forward has no horizontal part (a vertical forward)."""
    if math.hypot(forward[0], forward[1]) < MIN_VECTOR_LENGTH * _length(forward):
        return None
    return math.atan2(forward[1], forward[0])


def orientation_unchanged(obj, base_forward, base_up):
    """DEC-4.8 (1) / 4.9: both the forward and the up vector are within ``ANG_TOL`` of the baseline."""
    return angle_between(obj.forward, base_forward) <= ANG_TOL and angle_between(obj.up, base_up) <= ANG_TOL


def physics_norm(value):
    """The raw physics value 2 (unused) counts as normal for comparison and writing (SPEC 4.9)."""
    return 0 if value == 2 else value


# ---------------------------------------------------------------------------------------------
# 5.10 step 3: field validation of one ExportObject
# ---------------------------------------------------------------------------------------------
DIM_NAMES = {1: ("radius",), 2: ("radius", "top", "bottom"), 3: ("width", "length", "top", "bottom")}


def check_fields(obj, label_count, label_present) -> List[Issue]:
    """Range and enum checks of one object (5.10 step 3); the transform is checked by the caller first.

    Returns the issues: ``E_SHAPE_RANGE`` (shape kind, then the dimensions the shape uses), ``E_SPAWN_RANGE``,
    ``E_TEAM_RANGE``, ``E_COLOR_NEUTRAL`` / ``E_COLOR_RANGE``, ``E_LABEL_RANGE``, ``E_PHYSICS_RANGE``. The
    ranges that depend on the object class (``E_OTHER_RANGE``) are checked once the class is known.
    """
    out = []
    name = obj.name
    shape = to_int(obj.shape)
    if shape is None or shape not in DIM_NAMES and shape != 0:
        out.append(Issue("E_SHAPE_RANGE", "error", SHAPE_KIND_PATTERN % (name, shape if shape is not None else -1),
                         None, name))
    elif shape:
        values = {1: (obj.width,), 2: (obj.width, obj.top, obj.bottom), 3: (obj.width, obj.length, obj.top, obj.bottom)}[shape]
        for dim_name, value in zip(DIM_NAMES[shape], values):
            ok = isinstance(value, (int, float)) and math.isfinite(value) and 0.0 <= value <= 200.0
            if not ok:
                shown = float(value) if isinstance(value, (int, float)) else float("nan")
                out.append(make("E_SHAPE_RANGE", name, dim_name, shown, object_name=name))
    seq = to_int(obj.spawn_sequence)
    spawn = to_int(obj.spawn_time)
    if seq is None or spawn is None or not (-128 <= seq <= 127) or not (0 <= spawn <= 255):
        out.append(make("E_SPAWN_RANGE", name, object_name=name))
    team = to_int(obj.team)
    if team is None or not 0 <= team <= 8:
        out.append(make("E_TEAM_RANGE", name, object_name=name))
    color = to_int(obj.color)
    if color == 8:
        out.append(make("E_COLOR_NEUTRAL", name, object_name=name))
    elif color is None or not -1 <= color <= 7:
        out.append(make("E_COLOR_RANGE", name, color if color is not None else -2, object_name=name))
    label = to_int(obj.label_index)
    if label is None or label < -1 or (label >= 0 and (label >= label_count or not label_present[label])):
        out.append(make("E_LABEL_RANGE", name, label if label is not None else -2, label_count, object_name=name))
    physics = to_int(obj.physics)
    if physics is None or physics not in (0, 1, 2, 3):
        out.append(make("E_PHYSICS_RANGE", name, physics if physics is not None else -1, object_name=name))
    return out


def other_limits(cached_type, type19_rule):
    """``(low, high_a, high_b)`` for ``other_a`` / ``other_b`` of an object of this class (SPEC 3.8, 3.11).

    Class 1 has an 8-bit ``other_a``; classes 12 to 14 two 5-bit values; class 19 one index (``-1`` = none, up
    to 254 under ``plain8``, 255 under ``flag8``); every other class has no extras (both must be 0).
    """
    if cached_type == 1:
        return 0, 255, 0
    if 12 <= cached_type <= 14:
        return 0, 31, 31
    if cached_type == 19:
        return -1, (254 if type19_rule == "plain8" else 255), 0
    return 0, 0, 0


def check_other(obj, cached_type, type19_rule, only_if_changed=None) -> List[Issue]:
    """``E_OTHER_RANGE`` for ``other_a`` / ``other_b`` against the class's field widths.

    ``only_if_changed`` is ``(baseline_a, baseline_b)`` for an existing object: a value equal to its baseline is
    never an error (it is what the file holds).
    """
    low, high_a, high_b = other_limits(cached_type, type19_rule)
    out = []
    values = (("other_a", obj.other_a, low, high_a), ("other_b", obj.other_b, 0, high_b))
    for index, (label, value, lo, hi) in enumerate(values):
        v = to_int(value)
        if only_if_changed is not None and v == only_if_changed[index]:
            continue
        if v is None or not lo <= v <= hi:
            out.append(make("E_OTHER_RANGE", obj.name, label, hi, object_name=obj.name))
    return out


# ---------------------------------------------------------------------------------------------
# 7.5 quota rule
# ---------------------------------------------------------------------------------------------
def quota_decision(old: int, new: int, minimum: int, maximum: int, raise_max: bool) -> Tuple[Optional[str], int]:
    """Decide one quota row: ``(problem, new_maximum)``.

    ``problem`` is ``None`` (accepted), ``'E_QUOTA_RANGE'`` (above 255), ``'E_QUOTA'`` (above the maximum
    and above ``old``), ``'E_QUOTA_MIN'`` (below the minimum and below ``old``). With ``raise_max`` the
    ``E_QUOTA`` case is accepted and ``new_maximum`` is ``new`` (a maximum is never lowered and the minimum is
    never touched); otherwise ``new_maximum`` is ``maximum``. A row that already violates its own range is not
    an error until an edit makes it worse (7.5).
    """
    if new > 255:
        return "E_QUOTA_RANGE", maximum
    if new > maximum and new > old:
        if raise_max:
            return None, new
        return "E_QUOTA", maximum
    if new < minimum and new < old:
        return "E_QUOTA_MIN", maximum
    return None, maximum


def palette_name_for_folder(stock_rows, folder):
    """Display name for palette entry ``folder``: the first stock object of that folder, else ``'Unknown'``.

    ``stock_rows`` is ``tables.stock_objects(map_name)`` (``(type_id, internal, display)`` ascending by id).
    """
    for type_id, _internal, display in stock_rows:
        if (type_id >> 8) == folder:
            return display
    return "Unknown"
