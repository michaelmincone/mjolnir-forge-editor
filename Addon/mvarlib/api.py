"""Frozen public interface of ``mvarlib`` (SPEC section 6.4, DEC-6.4): the contract between G3/G5 and G4.

INTERFACE FREEZE v2 (v1 plus DECISION D11: ``ExportOptions.raise_quota_max``, appended last with a default,
so every existing call stays valid). This file is COMPLETE and is not changed without both teams agreeing.
The SHA-256 of ``api.py`` and ``errors.py`` is recorded in ``tests/golden/interface_sha256.json``
and in ``NOTES.md``; test U-22 (``tests/unit/test_interface_frozen.py``) fails when either differs.

* The dataclasses, the options and the error classes (re-exported from ``errors.py``) are final.
* ``load_map_variant`` and ``export_map_variant`` are lazy delegations to ``entry.py``: G3 and G5
  edit ``entry.py`` only. Until then ``entry`` raises ``NotImplementedError("G3")`` / ``("G5")``.
* The five helpers (``map_name_for_id``, ``stock_object_names``, ``palette_tree``,
  ``check_output_path``, ``write_atomic``) delegate to ``tables.py`` and ``io.py``, which are
  complete at G0, so the Blender glue (G4) can use them before the codec exists.

Pure Python 3.9 to 3.13, standard library only, no ``bpy``, relative imports only (it runs as
``mvarlib`` from the tools and as ``<extension>.mvarlib`` inside Blender). The glue reaches this
module only through ``Addon/provider.py`` and never uses ``isinstance`` on its types.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple
from .errors import (MvarError, FormatError, BlfFormatError, UnsupportedVariantError, DesyncError,
                     AmbiguousLayoutError, OutOfBoundsPositionError, DecodeError, EncodeError, CapacityError,
                     HashError, ValidationError, PathPolicyError, InternalError)    # re-exported: the glue catches P.MvarError

Vec3 = Tuple[float, float, float]
Bounds = Tuple[float, float, float, float, float, float]       # xmin, xmax, ymin, ymax, zmin, zmax

@dataclass(frozen=True)
class Issue:
    code: str                          # 'E_...' (refusal), 'W_...' (warning), 'I_...' (info); table in section 7
    severity: str                      # 'error' | 'warning' | 'info'
    message: str                       # complete sentence, user-facing
    slot: Optional[int] = None
    object_name: Optional[str] = None

@dataclass(frozen=True)
class MapInfo:
    map_id: int ; map_name: Optional[str] ; is_stock_map: bool ; bounds: Bounds
    quota_count: int ; version: int ; title: str ; description: str
    labels: List[str]                  # index -> text; '' where the entry is absent (see label_present)
    label_present: List[bool]
    occupied: int ; shape: str         # container shape id, e.g. 'plain4'
    template_sha256: str ; hash_flavour: str            # e.g. 'salted_be32/>' or 'unknown'
    palette_crc: int ; max_budget_raw: int ; spent_budget_raw: int
    hypothesis: Dict[str, object]      # {'type19': 'flag8'|'plain8'|'undetermined', 'axis_bits': [..], 'guid': bool, 'length_class': 'ceil_end'}
    warnings: List[Issue] = field(default_factory=list)

@dataclass(frozen=True)
class ObjectRecord:                    # one occupied slot, "ForgeObject-like" (3.11)
    slot: int
    folder: int ; item: int            # -1 where the file has the absent bit
    type_id: int                       # (folder << 8) | item, or -1
    type_name: str                     # display name on this map, or "Unknown (0x%04X)"
    stock: bool                        # (map, type_id) is in the stock table
    position: Vec3 ; forward: Vec3 ; up: Vec3
    orientation_kind: str              # 'vertical' | 'tilted'
    parent_slot: int                   # -1 none
    shape: int ; width: float ; length: float ; top: float ; bottom: float
    spawn_sequence: int ; spawn_time: int ; cached_type: int ; label_index: int   # -1 none
    placement: int ; physics: int ; symmetry: int ; place_at_start: bool ; game_specific: bool   # 3.9, file reading
    team: int                          # -1 none, 0..8
    color: int                         # -1 none (team colour), 0..7
    other_a: int ; other_b: int ; flags2: int
    raw: bytes ; raw_bits: int         # identity token

@dataclass(frozen=True)
class LoadResult:
    info: MapInfo ; objects: List[ObjectRecord] ; warnings: List[Issue]

@dataclass
class ExportObject:                    # one Blender object (or one array instance) handed to export
    name: str
    slot: Optional[int]                # None = no slot claimed (new object)
    token_raw: Optional[bytes] ; token_bits: Optional[int]
    name_matches_import: bool = False
    type_name: str = ""                # display name of the instanced palette collection (suffix .NNN stripped), or the imported type name
    type_id_hint: int = -1             # the imported type id (forge.objectType), -1 if none
    position: Vec3 = (0.0, 0.0, 0.0) ; forward: Vec3 = (0.0, 1.0, 0.0) ; up: Vec3 = (0.0, 0.0, 1.0)
    shape: int = 0 ; width: float = 0.0 ; length: float = 0.0 ; top: float = 0.0 ; bottom: float = 0.0
    spawn_sequence: int = 0 ; spawn_time: int = 0 ; cached_type: int = 0 ; label_index: int = -1
    physics: int = 3 ; symmetry: int = 3 ; place_at_start: bool = True ; game_specific: bool = False
    team: int = 8 ; color: int = -1 ; other_a: int = 0 ; other_b: int = 0
    hidden: bool = False ; from_array: bool = False          # informational, used in the diff

@dataclass
class ExportOptions:
    allow_unverified_rotation: bool = False
    force_reencode: bool = False
    fsm_policy: str = "KEEP"           # 'KEEP' | 'DROP'
    hash_policy: str = "REPRODUCE"     # 'REPRODUCE' (template's flavour, DEC-2.3) | 'SALTED_BE32' | 'PLAIN_LE32' (force a recipe)
    keep_unrecognised_imported: bool = False             # DEC-7.4: keep imported objects whose id is not in the map's stock table (warning instead of E_OBJ_NOT_STOCK)
    imported_slots: Optional[Sequence[int]] = None      # slots that were successfully imported; None = all present slots
    max_objects: int = 650
    raise_quota_max: bool = False      # D11: opt-in; when a quota row new placed would exceed its maximum, raise maximum to the new placed (never lowers anything, never touches minimum); warning W_QUOTA_MAX_RAISED

@dataclass(frozen=True)
class DiffEntry:
    kind: str                          # 'kept' | 'moved' | 'edited' | 'retargeted' | 'added' | 'removed' | 'not_imported'
    slot: Optional[int] ; name: str ; detail: str

@dataclass(frozen=True)
class ExportResult:
    ok: bool
    data: Optional[bytes]              # None when ok is False; nothing may be written
    diff: List[DiffEntry]
    errors: List[Issue] ; warnings: List[Issue]
    stats: Dict[str, object]           # occupied_before/after, end_bit, capacity_bits, L, hash_flavour, quota_changes, mode ('passthrough'|'patched'|'forced')

@dataclass(frozen=True)
class ReadOptions:
    strict: bool = True                # False only for verify_mvar --lenient; export refuses non-strict parses
    hypothesis_filter: Optional[Dict[str, object]] = None   # diagnostics/tests only

def load_map_variant(data: bytes, name: str = "", options: Optional[ReadOptions] = None) -> LoadResult:
    from . import entry                       # lazy; entry.load_map_variant raises NotImplementedError("G3") until G3; the stub returns canned data
    return entry.load_map_variant(data, name, options)

def export_map_variant(template: bytes, objects: Sequence[ExportObject], options: ExportOptions) -> ExportResult:
    from . import entry                       # lazy; entry.export_map_variant raises NotImplementedError("G5") until G5; the stub records its arguments
    return entry.export_map_variant(template, objects, options)

# Data and path helpers: implemented in G0 (they need only the JSON tables and `os`, no format knowledge), so G4 can use them
def map_name_for_id(map_id: int) -> Optional[str]:
    from . import tables
    return tables.map_name_for_id(map_id)                            # data/maps.json
def stock_object_names(map_name: str) -> List[str]:
    from . import tables
    return tables.stock_object_names(map_name)                       # data/stock_objects.json: display names valid on that map
def palette_tree() -> Dict[str, object]:
    from . import tables
    return tables.palette_tree()                                     # data/palette_tree.json
def check_output_path(target: str, source_paths: Sequence[str] = (), protected: Optional[Sequence[str]] = None) -> Optional[Issue]:
    from . import io as mio
    return mio.check_output_path(target, source_paths, protected)    # E_PATH_SAME_AS_SOURCE / E_PATH_PROTECTED (2.13), else None
def write_atomic(target: str, data: bytes, source_paths: Sequence[str] = (), protected: Optional[Sequence[str]] = None) -> None:
    from . import io as mio
    mio.write_atomic(target, data, source_paths, protected)          # raises PathPolicyError (2.13)

__all__ = ["Vec3", "Bounds", "Issue", "MapInfo", "ObjectRecord", "LoadResult", "ExportObject", "ExportOptions",
           "DiffEntry", "ExportResult", "ReadOptions", "load_map_variant", "export_map_variant",
           "map_name_for_id", "stock_object_names", "palette_tree", "check_output_path", "write_atomic",
           "MvarError", "FormatError", "BlfFormatError", "UnsupportedVariantError", "DesyncError",
           "AmbiguousLayoutError", "OutOfBoundsPositionError", "DecodeError", "EncodeError", "CapacityError",
           "HashError", "ValidationError", "PathPolicyError", "InternalError"]
