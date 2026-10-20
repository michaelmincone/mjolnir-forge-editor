"""Export planning and application: ``export_map_variant`` as one ordered algorithm (SPEC 5.3 to 5.10, 7.4, 7.5; gate G5).

The entry point :func:`export_map_variant` (behind ``api.export_map_variant`` through ``entry.py``) is stateless:
it parses the template strictly, plans every change from the objects the glue hands over, collects EVERY problem
(a refusal lists them all and returns ``data = None``), and only when nothing is wrong applies the plan to a copy of
the model, serialises it and re-parses its own output before returning bytes. The steps follow 5.10:

1. parse the template (``E_TEMPLATE_UNREADABLE``); 2. global checks (stock map, options); 3. field validation of
every object (``validate.check_fields``); 4. identity matching (5.5): a claimant is valid when its slot is present
and its token equals the slot's original bit range, duplicates keep the best one, the rest become new objects;
5. deletions (imported slots without a claimant) and ``not_imported`` slots; 6. per claimed slot: every field is
compared with the baseline view with its own tolerance (4.9) and only what moved is re-encoded (raw integers are the
truth; an untouched field keeps its bits); 7. new objects, sorted by name, into the lowest free slots (5.6);
8. quota deltas (5.4, 7.5), the object limit, the container shape and the capacity pre-check; 9. stop when anything
was collected; 10. apply; 11. serialise with the template's hash flavour (``hash_policy`` can force a recipe,
``fsm_policy`` the ``_fsm`` block); 12. verify by re-parsing (invariant I2, an ``InternalError`` on a violation);
13. report (diff, warnings, notes, stats).

Decisions taken here (details in ``docs/mvar/notes/G5.md``): the learned example for a new object's placement byte,
team and colour is the most common one among the template's objects of the same ``(folder, item)`` and otherwise of
the same folder (lowest slot on a tie); free slots are the absent slots of the state after the deletions;
``hash_policy`` that differs from the template's recipe counts as a modification (a clean template is then
re-hashed); a valid claimant of a slot that is not in ``imported_slots`` is honoured; all type checks are skipped
for a map that is not stock (``E_MAP_UNKNOWN`` already refuses the export).

Pure Python 3.9 to 3.13, standard library only, relative imports only.
"""
import math
from typing import Sequence

from . import catalog, codecs, hashing, tables
from . import validate as V
from .api import DiffEntry, ExportResult, ReadOptions
from .errors import EncodeError, InternalError, MvarError
from .model import MapVariant, type_name_for
from .bitio import BitWriter
from .slot import SLOT_COUNT, Slot
from .walk import Hypothesis, Quota, QUOTA_ROW_BITS, STREAM_BITS

__all__ = ["export_map_variant", "learn_class", "learn_example", "planned_end_bits"]

HASH_POLICIES = ("REPRODUCE", "SALTED_BE32", "PLAIN_LE32")
FSM_POLICIES = ("KEEP", "DROP")
DEFAULT_PLACEMENT = 0x0C            # SPEC 3.9 / 5.6: both symmetries, placed at start, normal physics
NEUTRAL_TEAM_RAW = 9                # SPEC 5.6: team raw 9 = neutral
NEW_FLAGS2 = 1                      # SPEC 5.6
UP_Z = (0.0, 0.0, 1.0)
POS_FIELDS = frozenset(["pos"])
TYPE_FIELDS = frozenset(["folder", "item"])
KEEP = "keep"
RETARGET = "retarget"
REFUSED = "refused"
FILE_LENGTH_BIT = 4                 # the embedded fileLength of the mvar stream (SPEC 2.11 step 3)
FILE_LENGTH_BITS = 32


# ---------------------------------------------------------------------------------------------
# helpers that read the template model
# ---------------------------------------------------------------------------------------------
def learn_class(model, folder, item):
    """Learned ``cached_type`` for ``(folder, item)`` (SPEC 7.4): the unique class among the template's objects of the
    same ``(folder, item)``; else the unique class among those of the same folder; else ``None``."""
    present = model.present_slots()
    same = set(s.cached_type for s in present if s.folder == folder and s.item == item)
    if len(same) == 1:
        return next(iter(same))
    same = set(s.cached_type for s in present if s.folder == folder)
    if len(same) == 1:
        return next(iter(same))
    return None


def learn_example(model, folder, item):
    """``((placement, team_raw, color), slot index)`` of the learned example for a new ``(folder, item)``, or ``None``.

    Candidates are the template's objects of the same ``(folder, item)``, else of the same folder. Among them the
    most common ``(placement, team_raw, color)`` triple wins; the lowest slot index breaks a tie. SPEC 5.6 says
    "learned example for the same (folder, item)"; the same-folder fallback follows the task text of gate G5 and the
    rule of the cached type (7.4).
    """
    present = model.present_slots()
    pool = [s for s in present if s.folder == folder and s.item == item]
    if not pool:
        pool = [s for s in present if s.folder == folder]
    if not pool:
        return None
    counts = {}
    first = {}
    for s in pool:
        key = (s.placement, s.team_raw, s.color)
        counts[key] = counts.get(key, 0) + 1
        first.setdefault(key, s.index)
    best = sorted(counts, key=lambda key: (-counts[key], first[key]))[0]
    return best, first[best]


def planned_end_bits(model):
    """Bits through the last quota row of the current (possibly edited) model, computed without packing."""
    rule, axes = model.hypothesis.type19, model.hypothesis.axis_bits
    total = model.header.raw.nbits + model.fixed.raw.nbits + model.labels.raw.nbits
    if model.guid is not None:
        total += model.guid.nbits
    for s in model.slots:
        total += s.bit_length(rule, axes)
    return total + QUOTA_ROW_BITS * len(model.quotas)


def _palette_groups():
    """``{leaf display name: [group path, ...]}`` from the palette tree (names only)."""
    out = {}

    def walk(node, path):
        for group in node.get("groups", []):
            walk(group, path + [group.get("name", "")])
        for leaf in node.get("leaves", []):
            name = leaf if isinstance(leaf, str) else leaf.get("name", "")
            out.setdefault(name, []).append(list(path))

    walk(tables.palette_tree(), [])
    return out


def _dim_values(obj, shape):
    """The dimension values a shape uses, in stored order (SPEC 4.3)."""
    if shape == 1:
        return [obj.width]
    if shape == 2:
        return [obj.width, obj.top, obj.bottom]
    if shape == 3:
        return [obj.width, obj.length, obj.top, obj.bottom]
    return []


def _fmt_vec(v):
    return "(%.3f, %.3f, %.3f)" % (v[0], v[1], v[2])


def _same_except_file_length(a, b):
    """Two header bit ranges are equal apart from the embedded 32-bit file length (re-stamped after a ``_cmp`` expansion)."""
    if a.nbits != b.nbits or a.nbits < FILE_LENGTH_BIT + FILE_LENGTH_BITS:
        return False
    mask = ((1 << FILE_LENGTH_BITS) - 1) << (a.nbits - FILE_LENGTH_BIT - FILE_LENGTH_BITS)
    return (a.to_int() & ~mask) == (b.to_int() & ~mask)


# ---------------------------------------------------------------------------------------------
# the export
# ---------------------------------------------------------------------------------------------
class _Export(object):
    """One call of ``export_map_variant``; the steps are methods in the order of SPEC 5.10."""

    def __init__(self, template, objects, options):
        self.template = template
        self.objects = list(objects)
        self.options = options
        self.errors_global = []
        self.errors_object = []
        self.errors_quota = []
        self.errors_capacity = []
        self.warnings = []
        self.diff = []
        self.stats = {}
        self.m = None                 # the template model (never modified)
        self.p = None                 # the planned model (a deep copy, edited)
        self.map_name = None
        self.stock_rows = []
        self.quota_delta = {}         # folder -> net change of ``placed``
        self.rotation_written = 0
        self.processed = []           # (obj, slot index, expected type id or None, expected class or None, rotation written)
        self._assumed_warned = set()
        self._unknown_class_reported = set()
        self._groups = None
        self.bad = set()              # ids of objects that failed the field checks

    # --- small utilities ---------------------------------------------------------------------
    def err(self, bucket, code, *args, **kwargs):
        bucket.append(V.make(code, *args, **kwargs))

    def _type_name(self, folder, item):
        return type_name_for(self.map_name, folder, item)[1]

    def _palette_name(self, folder):
        return V.palette_name_for_folder(self.stock_rows, folder)

    def _disputed(self):
        return tables.disputed_ids(self.map_name) if self.map_name else []

    def _assumed_group(self, type_name):
        """True when every palette group path of the display name contains an assumed-zero group (SPEC 7.4)."""
        if self._groups is None:
            self._groups = _palette_groups()
        paths = self._groups.get(type_name)
        if not paths:
            return False
        assumed = set(tables.assumed_zero_groups())
        return all(any(g in assumed for g in path) for path in paths)

    # --- driver ------------------------------------------------------------------------------
    def run(self):
        early = self._parse_template()
        if early is not None:
            return early
        self._check_options()
        self._global_checks()
        self._validate_fields()
        keepers, new_objects, deleted, not_imported = self._identity()
        retargets = [obj for index, obj in keepers.items()
                     if (obj.type_name and obj.type_name != self.m.record_for(self.m.slots[index]).type_name)
                     or (not obj.type_name and V.to_int(obj.type_id_hint) not in (-1, self.m.record_for(self.m.slots[index]).type_id))]
        self._prepare_native_palette(list(new_objects) + retargets)
        for index in sorted(keepers):
            self._plan_existing(index, keepers[index])
        self._plan_deleted(deleted)
        self._plan_new(new_objects, deleted)
        self._plan_not_imported(not_imported)
        self._plan_quotas()
        self._update_native_budget()
        self._check_shape()
        self._check_limit(new_objects, deleted)
        self._check_capacity()
        if self.rotation_written:
            self.warnings.append(V.make("W_ORIENTATION_UNVERIFIED", self.rotation_written))
        errors = self.errors_global + self.errors_object + self.errors_quota + self.errors_capacity
        self.stats["occupied_before"] = self.m.occupied
        self.stats["occupied_after"] = self.p.occupied
        self.stats["capacity_bits"] = STREAM_BITS
        self.stats["quota_changes"] = self._quota_changes()
        if errors:
            self._append_notes()
            return ExportResult(False, None, self._diff_sorted(), errors, self.warnings, self.stats)
        return self._finish()

    def _prepare_native_palette(self, requested):
        """Extend verified legacy palettes only when an added/retargeted type needs it.

        Original files and imported slot bytes remain untouched. The full palette
        CRC and class-19 codec come from the same shipped cache/DLL revision.
        """
        native = catalog.native_palette(self.m)
        if native is None:
            return
        definitions = []
        for obj in requested:
            key = obj.type_name if obj.type_name else V.to_int(obj.type_id_hint)
            row = catalog.definition(self.map_name, key)
            if row is not None and id(obj) not in self.bad:
                definitions.append(row)
        p = self.p
        if any(row['id'] >> 8 >= self.m.fixed.quota_count for row in definitions):
            old_count = p.fixed.quota_count
            p.quotas.extend(Quota(0, native['maxima'][folder], 0)
                            for folder in range(old_count, native['count']))
            p.fixed.quota_count = native['count']
            p.fixed.palette_crc = native['crc']
            p.fixed.max_budget = native['budget']
            self._refresh_fixed()
            self.stats['native_palette_extension'] = dict(before=old_count, after=native['count'], crc=native['crc'])
            self.warnings.append(V.make('W_NATIVE_PALETTE_EXTENDED', old_count, native['count']))
        if self.m.type19_status == 'undetermined' and any(row['cached_type'] == 19 for row in definitions):
            p.hypothesis = Hypothesis(native['type19'], p.hypothesis.axis_bits, p.hypothesis.guid)
            p.type19_status = native['type19']
            self.stats['native_location_codec'] = native['type19']

    def _refresh_fixed(self):
        fixed = self.p.fixed
        w = BitWriter()
        for field, bits in fixed.FIELDS:
            w.write(getattr(fixed, field), bits)
        for value in fixed.bounds_raw:
            w.write(value, 32)
        w.write(fixed.max_budget, 32)
        w.write(fixed.spent_budget, 32)
        fixed.raw = w.getbits()

    def _update_native_budget(self):
        if not catalog.compatible(self.m) or not self._content_dirty():
            return
        spent = 0
        for slot in self.p.present_slots():
            if slot.folder is None or slot.item is None:
                return
            definition = catalog.definition(self.map_name, (slot.folder << 8) | slot.item)
            if definition is None:
                return
            spent += definition['price']
        self.p.fixed.spent_budget = spent
        self._refresh_fixed()
        self.stats['native_budget'] = dict(spent=spent, maximum=self.p.fixed.max_budget)
        if spent > self.p.fixed.max_budget:
            self.warnings.append(V.make('W_NATIVE_BUDGET_EXCEEDED', spent, self.p.fixed.max_budget))

    # --- step 1 ------------------------------------------------------------------------------
    def _parse_template(self):
        try:
            raw = self.template if isinstance(self.template, bytes) else bytes(self.template)
            self.m = MapVariant.from_bytes(raw)
        except (MvarError, TypeError, ValueError) as exc:
            self.errors_global.append(V.make("E_TEMPLATE_UNREADABLE", str(exc)))
            return ExportResult(False, None, [], self.errors_global, [], {})
        self.template = raw
        self.p = self.m.copy()
        self.map_name = self.m.map_name
        self.stock_rows = tables.stock_objects(self.map_name) if self.map_name else []
        return None

    # --- step 2 ------------------------------------------------------------------------------
    def _check_options(self):
        o = self.options
        if o.fsm_policy not in FSM_POLICIES:
            self.err(self.errors_global, "E_OPTION_INVALID", "fsm_policy", o.fsm_policy)
        if o.hash_policy not in HASH_POLICIES:
            self.err(self.errors_global, "E_OPTION_INVALID", "hash_policy", o.hash_policy)

    def _global_checks(self):
        m = self.m
        if self.map_name is None:
            self.err(self.errors_global, "E_MAP_UNKNOWN", m.header.map_id, m.header.map_id)
        for issue in m.warnings:                       # the template's read-time warnings that SPEC 7.3 lists for an export
            if issue.code in ("W_GUID_VERSION_MISMATCH", "W_VERSION_MISMATCH", "W_CHUNK_VERSION_UNEXPECTED",
                              "W_ZERO_RANGE_AXIS"):
                self.warnings.append(issue)

    # --- step 3 ------------------------------------------------------------------------------
    def _validate_fields(self):
        labels = self.m.labels
        present = labels.present_flags
        for obj in self.objects:
            if not V.valid_transform(obj):
                self.err(self.errors_object, "E_TRANSFORM_INVALID", obj.name, object_name=obj.name)
                self.bad.add(id(obj))
                continue
            problems = V.check_fields(obj, labels.count, present)
            if problems:
                self.errors_object.extend(problems)
                self.bad.add(id(obj))

    # --- steps 4 and 5 -----------------------------------------------------------------------
    @staticmethod
    def _token_matches(obj, slot):
        if obj.token_raw is None or obj.token_bits is None or slot.raw is None:
            return False
        return bytes(obj.token_raw) == slot.raw.data and obj.token_bits == slot.raw.nbits

    def _pose_distance(self, obj, slot):
        """(position distance, orientation distance) of an object from its slot's baseline; infinity when unusable."""
        if id(obj) in self.bad:
            return (math.inf, math.inf)
        rec = self.m.record_for(slot)
        pos = math.sqrt(sum((obj.position[k] - rec.position[k]) ** 2 for k in range(3)))
        rot = V.angle_between(obj.forward, rec.forward) + V.angle_between(obj.up, rec.up)
        return (round(pos, 9), round(rot, 9))

    def _identity(self):
        """Valid claimants per slot, the objects that are new, the deleted slots and the slots that were not imported."""
        m = self.m
        claims = {}
        new_objects = []
        for obj in self.objects:
            if obj.slot is None:
                new_objects.append(obj)
                continue
            index = V.to_int(obj.slot)
            valid = (index is not None and 0 <= index < SLOT_COUNT and m.slots[index].present
                     and self._token_matches(obj, m.slots[index]))
            if valid:
                claims.setdefault(index, []).append(obj)
            else:
                self.warnings.append(V.make("W_TOKEN_MISMATCH", obj.name, index if index is not None else -1,
                                            slot=index, object_name=obj.name))
                new_objects.append(obj)
        keepers = {}
        for index in sorted(claims):
            claimants = claims[index]
            if len(claimants) == 1:
                keepers[index] = claimants[0]
                continue
            matching = [o for o in claimants if o.name_matches_import]
            if len(matching) == 1:
                keeper = matching[0]
            else:
                pool = matching if len(matching) > 1 else claimants
                keeper = min(pool, key=lambda o: self._pose_distance(o, m.slots[index]) + (o.name,))
            keepers[index] = keeper
            for obj in sorted(claimants, key=lambda o: o.name):
                if obj is not keeper:
                    self.warnings.append(V.make("W_DUPLICATE_SLOT", keeper.name, obj.name, index, keeper.name, obj.name,
                                                slot=index, object_name=obj.name))
                    new_objects.append(obj)
        imported = None
        if self.options.imported_slots is not None:
            imported = set(i for i in (V.to_int(x) for x in self.options.imported_slots) if i is not None)
        deleted = []
        not_imported = []
        for s in m.slots:
            if s.present and s.index not in keepers:
                if imported is None or s.index in imported:
                    deleted.append(s.index)
                else:
                    not_imported.append(s.index)
        return keepers, new_objects, deleted, not_imported

    def _plan_deleted(self, deleted):
        m, p = self.m, self.p
        gone = set(deleted)
        for index in deleted:
            slot = m.slots[index]
            p.slots[index].present = False
            if slot.folder is not None:
                self.quota_delta[slot.folder] = self.quota_delta.get(slot.folder, 0) - 1
            rec = m.record_for(slot)
            self.diff.append(DiffEntry("removed", index, "%d - %s" % (index, rec.type_name),
                                       "deleted %s at %s" % (rec.type_name, _fmt_vec(rec.position))))
        if gone:
            for s in p.slots:
                if s.present and s.parent_raw >= 1 and (s.parent_raw - 1) in gone:
                    parent = s.parent_raw - 1
                    s.parent_raw = 0
                    self.warnings.append(V.make("W_PARENT_CLEARED", s.index, parent, slot=s.index))

    def _plan_not_imported(self, not_imported):
        for index in not_imported:
            rec = self.m.record_for(self.m.slots[index])
            self.warnings.append(V.make("W_SLOT_NOT_IMPORTED", index, slot=index))
            self.diff.append(DiffEntry("not_imported", index, "%d - %s" % (index, rec.type_name),
                                       "left unchanged (the slot was not imported)"))

    # --- shared pieces of steps 6 and 7 --------------------------------------------------------
    def _cell_changes(self, obj, base_position=None):
        """Per-axis position change: ``({axis: new cell}, outside)``.

        For an existing object (``base_position`` given) only the axes that moved beyond the tolerance are returned;
        for a new object all three. ``outside`` is true when an axis to be written lies outside ``[min, max)`` (every
        value is outside on a zero-range axis); such an axis gets no cell.
        """
        b = self.m.fixed.bounds
        axes = self.m.hypothesis.axis_bits
        cells = {}
        outside = False
        for k in range(3):
            mn, mx = b[2 * k], b[2 * k + 1]
            v = float(obj.position[k])
            if base_position is not None and abs(v - base_position[k]) <= codecs.pos_tolerance(axes[k], mn, mx):
                continue
            if not (mn <= v < mx):
                outside = True
                continue
            cells[k] = codecs.pos_encode(v, axes[k], mn, mx)
        return cells, outside

    def _bounds_error(self, obj):
        b = self.m.fixed.bounds
        pos = obj.position
        self.err(self.errors_object, "E_OUT_OF_BOUNDS", obj.name, pos[0], pos[1], pos[2], b[0], b[1], b[2], b[3], b[4], b[5],
                 object_name=obj.name)

    def _yaw_angle(self, obj):
        """Stored orientation triple, with native tilt support for corroborated palettes."""
        if catalog.compatible(self.m):
            if not self.options.allow_unverified_rotation:
                self.err(self.errors_object, "E_ROTATION_GATED", obj.name, object_name=obj.name)
                return None
            return codecs.orientation_encode_native(obj.forward, obj.up)
        if V.angle_between(obj.up, UP_Z) > V.ANG_TOL or V.yaw_of(obj.forward) is None:
            self.err(self.errors_object, "E_TILT_UNSUPPORTED", obj.name, object_name=obj.name)
            return None
        if not self.options.allow_unverified_rotation:
            self.err(self.errors_object, "E_ROTATION_GATED", obj.name, object_name=obj.name)
            return None
        return 1, None, codecs.angle_encode(V.yaw_of(obj.forward))

    @staticmethod
    def _dims_codes(obj, shape):
        return [codecs.dim_encode(float(v)) for v in _dim_values(obj, shape)]

    def _extra_for(self, cached_type, a, b):
        """The stored ``extra`` list for ``other_a`` / ``other_b`` of a class (SPEC 3.8, 3.11)."""
        if cached_type == 1:
            return [a]
        if 12 <= cached_type <= 14:
            return [a, b]
        if cached_type == 19:
            if self.p.hypothesis.type19 == "plain8":
                return [a + 1]
            return [1, 0] if a == -1 else [0, a]
        return []

    def _type19_ok(self, obj):
        if self.p.type19_status == "undetermined":
            self.err(self.errors_object, "E_TYPE19_UNDETERMINED", object_name=obj.name)
            return False
        return True

    def _flag_problems(self, obj, symmetry, place_at_start, game_specific):
        """``E_FLAG_UNVERIFIED`` for each of symmetry, place at start, game specific that differs from its baseline."""
        if V.to_int(obj.symmetry) != symmetry:
            self.err(self.errors_object, "E_FLAG_UNVERIFIED", obj.name, "symmetry", object_name=obj.name)
        if bool(obj.place_at_start) != bool(place_at_start):
            self.err(self.errors_object, "E_FLAG_UNVERIFIED", obj.name, "place at start", object_name=obj.name)
        if bool(obj.game_specific) != bool(game_specific):
            self.err(self.errors_object, "E_FLAG_UNVERIFIED", obj.name, "game specific", object_name=obj.name)

    @staticmethod
    def _team_changed(new_team, base_team):
        """SPEC 4.9: unchanged iff equal, or the baseline is ``none`` (-1) and the object says neutral (8)."""
        return not (new_team == base_team or (base_team == -1 and new_team == codecs.TEAM_NEUTRAL))

    # --- classes and types (7.4) -------------------------------------------------------------
    def _class_for(self, folder, item, type_name, requested_class=None):
        """``(class or None, assumed)`` of a type: learned from the template, else assumed from the palette group."""
        native = catalog.native_class(self.m, folder, item)
        if native is not None and V.to_int(requested_class) == native:
            self.stats.setdefault('native_object_definitions', []).append(type_name)
            return native, False
        learned = learn_class(self.m, folder, item)
        if learned is not None:
            return learned, False
        if native is not None:
            self.stats.setdefault('native_object_definitions', []).append(type_name)
            return native, False
        if self._assumed_group(type_name):
            return 0, True
        return None, False

    def _warn_assumed(self, type_name, slot=None, object_name=None):
        if type_name not in self._assumed_warned:
            self._assumed_warned.add(type_name)
            self.warnings.append(V.make("W_CACHED_TYPE_ASSUMED", type_name, slot=slot, object_name=object_name))

    def _existing_type(self, obj, rec):
        """Type rule of an existing object (7.4): ``(KEEP, None)``, ``(RETARGET, type id)`` or ``(REFUSED, None)``."""
        name = obj.name
        text = obj.type_name or ""
        hint = V.to_int(obj.type_id_hint)
        hint = -1 if hint is None else hint
        known = self.map_name is not None
        if text:
            if text == rec.type_name:
                return KEEP, None
            resolved = tables.object_id_for_name(self.map_name, text) if known else None
            if resolved is None:
                if known:
                    self.err(self.errors_object, "E_OBJ_NAME_UNKNOWN", name, text, self.map_name, object_name=name)
                return REFUSED, None
            return (KEEP, None) if resolved == rec.type_id else (RETARGET, resolved)
        if hint == rec.type_id:
            return KEEP, None
        if hint == -1:
            self.err(self.errors_object, "E_OBJ_NO_TYPE", name, object_name=name)
            return REFUSED, None
        if known and not tables.is_stock_object(self.map_name, hint):
            self.err(self.errors_object, "E_OBJ_NOT_STOCK", name, hint & 0xFFFF, self.map_name, object_name=name)
            return REFUSED, None
        return RETARGET, hint

    def _kept_type_is_stock(self, index, obj, rec):
        """Tier 1 does not exempt an imported object from the stock rule (DEC-7.4)."""
        if rec.stock or self.map_name is None:
            return True
        if self.options.keep_unrecognised_imported:
            self.warnings.append(V.make("W_UNKNOWN_TYPE_KEPT", obj.name, rec.type_id & 0xFFFF, self.map_name,
                                        slot=index, object_name=obj.name))
            return True
        if rec.type_id == -1:
            self.err(self.errors_object, "E_OBJ_NO_TYPE", obj.name, object_name=obj.name)
        else:
            self.err(self.errors_object, "E_OBJ_NOT_STOCK", obj.name, rec.type_id, self.map_name, object_name=obj.name)
        return False

    # --- step 6 ------------------------------------------------------------------------------
    def _plan_existing(self, index, obj):
        m = self.m
        slot = m.slots[index]
        rec = m.record_for(slot)
        name = obj.name
        if id(obj) in self.bad:
            self.diff.append(DiffEntry("kept", index, name, "not exported: the object has invalid values (see the errors)"))
            return
        before = len(self.errors_object)
        changes = {}                                    # Slot attribute -> new value (applied only when nothing is wrong)
        retarget = None                                 # (old folder, new folder)
        new_id = None

        # --- type: tier 1 keeps the bits, tier 2 retargets (7.4) ---
        kind, resolved = self._existing_type(obj, rec)
        if kind == KEEP:
            self._kept_type_is_stock(index, obj, rec)
        elif kind == RETARGET:
            folder, item = resolved >> 8, resolved & 0xFF
            if folder >= self.p.fixed.quota_count:
                self.err(self.errors_object, "E_FOLDER_RANGE", name, folder, self.p.fixed.quota_count, object_name=name)
            else:
                new_name = self._type_name(folder, item)
                learned, assumed = self._class_for(folder, item, new_name)
                if learned is None or learned != slot.cached_type:
                    self.err(self.errors_object, "E_RETARGET_CLASS", name, rec.type_name, new_name, object_name=name)
                else:
                    if assumed:
                        self._warn_assumed(new_name, index, name)
                    if resolved in self._disputed():
                        self.warnings.append(V.make("W_DISPUTED_ID", new_name, self.map_name, slot=index, object_name=name))
                    changes["folder"], changes["item"] = folder, item
                    retarget = (slot.folder, folder)
                    new_id = resolved

        # Legacy class-zero records may explicitly enable their verified stock
        # properties. Unchanged imports and arbitrary class changes stay guarded.
        effective_class = slot.cached_type
        requested_class = V.to_int(obj.cached_type)
        if requested_class != slot.cached_type:
            native = catalog.native_class(m, slot.folder, slot.item) if kind == KEEP else None
            if slot.cached_type == 0 and native is not None and requested_class == native:
                effective_class = native
                changes['cached_type'] = native
                self.stats.setdefault('native_property_upgrades', []).append(name)
            else:
                self.err(self.errors_object, "E_CACHED_TYPE_CHANGED", name, object_name=name)

        # --- position (4.2) ---
        cells, outside = self._cell_changes(obj, rec.position)
        if outside:
            self._bounds_error(obj)
        pos = list(slot.pos)
        for k, cell in cells.items():
            pos[k] = cell
        if pos != list(slot.pos):
            changes["pos"] = pos

        # --- orientation (4.8) ---
        wrote_rotation = False
        if not V.orientation_unchanged(obj, rec.forward, rec.up):
            angle = self._yaw_angle(obj)
            if angle is not None:
                changes["up_global"], changes["up_code"], changes["angle"] = angle
                wrote_rotation = True

        # --- shape and dimensions (4.3) ---
        shape = V.to_int(obj.shape)
        codes = self._dims_codes(obj, shape)
        if shape != slot.shape or codes != slot.dims:
            changes["shape"], changes["dims"] = shape, codes

        # --- plain integer fields (4.9) ---
        seq = V.to_int(obj.spawn_sequence)
        if seq != slot.spawn_seq:
            changes["spawn_seq"] = seq
        spawn = V.to_int(obj.spawn_time)
        if spawn != slot.respawn:
            changes["respawn"] = spawn
        label = V.to_int(obj.label_index)
        if (None if label == -1 else label) != slot.label:
            changes["label"] = None if label == -1 else label
        team = V.to_int(obj.team)
        if self._team_changed(team, rec.team):
            changes["team_raw"] = codecs.team_raw(team)
        color = V.to_int(obj.color)
        if color != rec.color:
            changes["color"] = codecs.color_raw(color)

        # --- placement byte: the physics bits only (DEC-3.9) ---
        physics = V.physics_norm(V.to_int(obj.physics))
        if physics != V.physics_norm(rec.physics):
            changes["placement"] = codecs.placement_with_physics(slot.placement, physics)
        self._flag_problems(obj, rec.symmetry, rec.place_at_start, rec.game_specific)

        # --- other_a / other_b (3.8) ---
        a, b = V.to_int(obj.other_a), V.to_int(obj.other_b)
        if (a, b) != (rec.other_a, rec.other_b) or effective_class != slot.cached_type:
            problems = V.check_other(obj, effective_class, self.p.hypothesis.type19,
                                     (rec.other_a, rec.other_b) if effective_class == slot.cached_type else None)
            if problems:
                self.errors_object.extend(problems)
            elif effective_class != 19 or self._type19_ok(obj):
                changes["extra"] = self._extra_for(effective_class, a, b)

        # a retarget moves one object between two quota rows whatever else is wrong with the object
        if retarget is not None and retarget[0] != retarget[1]:
            if retarget[0] is not None:
                self.quota_delta[retarget[0]] = self.quota_delta.get(retarget[0], 0) - 1
            self.quota_delta[retarget[1]] = self.quota_delta.get(retarget[1], 0) + 1
        mine = len(self.errors_object) - before
        if mine:
            self.diff.append(DiffEntry("kept", index, name, "refused: %d problem(s), see the errors" % mine))
            return
        target = self.p.slots[index]
        for attr, value in changes.items():
            setattr(target, attr, value)
        if wrote_rotation:
            self.rotation_written += 1
        self.processed.append((obj, index, new_id, effective_class, wrote_rotation))
        self._diff_existing(index, name, target, obj, rec)

    def _diff_existing(self, index, name, target, obj, rec):
        changed = target.dirty
        if not changed:
            detail = "unchanged"
            kind = "kept"
        elif changed & TYPE_FIELDS:
            kind = "retargeted"
            detail = "%s -> %s" % (rec.type_name, self._type_name(target.folder, target.item))
        elif changed <= POS_FIELDS:
            kind = "moved"
            b = self.m.fixed.bounds
            axes = self.m.hypothesis.axis_bits
            new_pos = tuple(codecs.pos_decode(target.pos[k], axes[k], b[2 * k], b[2 * k + 1]) for k in range(3))
            detail = "moved by (%+.3f, %+.3f, %+.3f)" % tuple(new_pos[k] - rec.position[k] for k in range(3))
        else:
            kind = "edited"
            detail = "changed: " + ", ".join(sorted(changed))
        if obj.hidden:
            detail += " (hidden)"
        if obj.from_array:
            detail += " (array instance)"
        self.diff.append(DiffEntry(kind, index, name, detail))

    # --- step 7 ------------------------------------------------------------------------------
    def _plan_new(self, new_objects, deleted):
        m, p = self.m, self.p
        gone = set(deleted)
        occupied = set(s.index for s in m.slots if s.present and s.index not in gone)
        free = [i for i in range(SLOT_COUNT) if i not in occupied]
        for obj in sorted(new_objects, key=lambda o: o.name):
            if id(obj) in self.bad:
                continue
            slot, type_id, folder = self._build_new(obj)
            if folder is not None:
                self.quota_delta[folder] = self.quota_delta.get(folder, 0) + 1
            if slot is None:
                continue
            if not free:
                self.err(self.errors_object, "E_NO_FREE_SLOT", obj.name, object_name=obj.name)
                continue
            index = free.pop(0)
            slot.index = index
            p.slots[index] = slot
            b = m.fixed.bounds
            axes = m.hypothesis.axis_bits
            where = tuple(codecs.pos_decode(slot.pos[k], axes[k], b[2 * k], b[2 * k + 1]) for k in range(3))
            detail = "new %s at %s" % (self._type_name(slot.folder, slot.item), _fmt_vec(where))
            if obj.from_array:
                detail += " (array instance)"
            if obj.hidden:
                detail += " (hidden)"
            self.diff.append(DiffEntry("added", index, obj.name, detail))
            self.processed.append((obj, index, type_id, slot.cached_type, True))

    def _build_new(self, obj):
        """``(Slot or None, type id, folder)`` for a new object; problems are recorded, ``Slot.index`` is set by the caller."""
        m = self.m
        name = obj.name
        before = len(self.errors_object)
        known = self.map_name is not None
        # --- type, tier 2 ---
        text = obj.type_name or ""
        hint = V.to_int(obj.type_id_hint)
        hint = -1 if hint is None else hint
        type_id = None
        if text:
            type_id = tables.object_id_for_name(self.map_name, text) if known else None
            if type_id is None and known:
                self.err(self.errors_object, "E_OBJ_NAME_UNKNOWN", name, text, self.map_name, object_name=name)
        elif hint >= 0:
            if known and tables.is_stock_object(self.map_name, hint):
                type_id = hint
            elif known:
                self.err(self.errors_object, "E_OBJ_NOT_STOCK", name, hint & 0xFFFF, self.map_name, object_name=name)
        else:
            self.err(self.errors_object, "E_OBJ_NO_TYPE", name, object_name=name)
        folder = item = cached = None
        type_name = ""
        if type_id is not None:
            folder, item = type_id >> 8, type_id & 0xFF
            if folder >= self.p.fixed.quota_count:
                self.err(self.errors_object, "E_FOLDER_RANGE", name, folder, self.p.fixed.quota_count, object_name=name)
                folder = None
        if folder is not None:
            type_name = self._type_name(folder, item)
            cached, assumed = self._class_for(folder, item, type_name, obj.cached_type)
            if cached is None:
                if V.to_int(obj.cached_type) == 19 and m.type19_status == "undetermined":
                    self.err(self.errors_object, "E_TYPE19_UNDETERMINED", object_name=name)
                elif type_name not in self._unknown_class_reported:
                    self._unknown_class_reported.add(type_name)
                    self.err(self.errors_object, "E_CACHED_TYPE_UNKNOWN", type_name, object_name=name)
            elif assumed:
                self._warn_assumed(type_name, None, name)
            if type_id in self._disputed():
                self.warnings.append(V.make("W_DISPUTED_ID", type_name, self.map_name, object_name=name))
        # --- position: every axis is encoded, none is clamped ---
        cells, outside = self._cell_changes(obj, None)
        if outside:
            self._bounds_error(obj)
        # --- orientation: every new object writes one (DEC-5.6) ---
        angle = self._yaw_angle(obj)
        # --- the learned example is the baseline of team, colour, physics and the flags ---
        example = learn_example(m, folder, item) if folder is not None else None
        if example is not None:
            (base_placement, base_team_raw, base_color), _example_slot = example
        else:
            base_placement, base_team_raw, base_color = DEFAULT_PLACEMENT, NEUTRAL_TEAM_RAW, None
        base_view = codecs.placement_view(base_placement)
        self._flag_problems(obj, base_view.symmetry, base_view.place_at_start, base_view.game_specific)
        # --- extras ---
        extra = []
        if cached is not None:
            problems = V.check_other(obj, cached, self.p.hypothesis.type19, None)
            if problems:
                self.errors_object.extend(problems)
            elif cached != 19 or self._type19_ok(obj):
                extra = self._extra_for(cached, V.to_int(obj.other_a), V.to_int(obj.other_b))
        if len(self.errors_object) > before or folder is None or cached is None or angle is None or len(cells) != 3:
            return None, type_id, folder
        s = Slot(-1, True)
        s.flags2 = NEW_FLAGS2
        s.folder, s.item = folder, item
        s.in_bounds = 1
        s.pos = [cells[0], cells[1], cells[2]]
        s.up_global, s.up_code, s.angle = angle
        s.parent_raw = 0
        shape = V.to_int(obj.shape)
        s.shape = shape
        s.dims = self._dims_codes(obj, shape)
        s.spawn_seq = V.to_int(obj.spawn_sequence)
        s.respawn = V.to_int(obj.spawn_time)
        s.cached_type = cached
        label = V.to_int(obj.label_index)
        s.label = None if label == -1 else label
        physics = V.physics_norm(V.to_int(obj.physics))
        s.placement = base_placement
        if physics != V.physics_norm(base_view.physics):
            s.placement = codecs.placement_with_physics(base_placement, physics)
        team = V.to_int(obj.team)
        s.team_raw = codecs.team_raw(team) if self._team_changed(team, codecs.team_view(base_team_raw)) else base_team_raw
        color = V.to_int(obj.color)
        s.color = codecs.color_raw(color) if color != codecs.color_view(base_color) else base_color
        s.extra = extra
        self.rotation_written += 1
        return s, type_id, folder

    # --- step 8: quota, shape, limit, capacity ---------------------------------------------------
    def _plan_quotas(self):
        m, p = self.m, self.p
        raise_max = bool(self.options.raise_quota_max)
        for folder in sorted(self.quota_delta):
            delta = self.quota_delta[folder]
            if delta == 0 or folder >= len(p.quotas):
                continue
            row = m.quotas[folder] if folder < len(m.quotas) else p.quotas[folder]
            new = row.placed + delta
            name = self._palette_name(folder)
            problem, new_max = V.quota_decision(row.placed, new, row.minimum, row.maximum, raise_max)
            if problem == "E_QUOTA_RANGE":
                self.err(self.errors_quota, "E_QUOTA_RANGE", folder, name)
            elif problem == "E_QUOTA":
                self.err(self.errors_quota, "E_QUOTA", folder, name, new, row.maximum)
            elif problem == "E_QUOTA_MIN":
                self.err(self.errors_quota, "E_QUOTA_MIN", folder, name, new, row.minimum)
            else:
                p.quotas[folder].placed = new
                if new_max != row.maximum:
                    p.quotas[folder].maximum = new_max
                    self.warnings.append(V.make("W_QUOTA_MAX_RAISED", folder, name, new, row.maximum, new_max))

    def _quota_changes(self):
        out = []
        for folder, after in enumerate(self.p.quotas):
            before = self.m.quotas[folder] if folder < len(self.m.quotas) else Quota(0, 0, 0)
            if before.as_tuple() != after.as_tuple():
                out.append({"folder": folder, "name": self._palette_name(folder), "minimum": before.minimum,
                            "placed_before": before.placed, "placed_after": after.placed,
                            "maximum_before": before.maximum, "maximum_after": after.maximum})
        return out

    def _content_dirty(self):
        p = self.p
        if any(s.is_dirty for s in p.slots):
            return True
        return [q.as_tuple() for q in p.quotas] != p._quota_baseline

    def _flavour_override(self):
        """The ``HashFlavour`` that ``hash_policy`` forces, or ``None`` for REPRODUCE."""
        policy = self.options.hash_policy
        if policy == "REPRODUCE":
            return None
        endian = self.m.chunk.length_endian or ">"
        return hashing.HashFlavour(endian, "salted_be32" if policy == "SALTED_BE32" else "plain_le32")

    def _rewrite_hash(self):
        flavour = self._flavour_override()
        return flavour is not None and flavour != self.m.flavour

    def _will_change(self):
        o = self.options
        fsm_drop = o.fsm_policy == "DROP" and any(c.sig == "_fsm" for c in self.m.blf.chunks)
        return bool(self._content_dirty() or o.force_reencode or fsm_drop or self._rewrite_hash())

    def _check_shape(self):
        if self.m.shape == "other" and self._will_change():
            self.err(self.errors_global, "E_CONTAINER_SHAPE", self.m.blf.layout_text())

    def _check_limit(self, new_objects, deleted):
        limit = self.options.max_objects
        after = self.m.occupied - len(deleted) + len(new_objects)
        if after > limit:
            self.err(self.errors_global, "E_TOO_MANY", after, limit, after - limit, limit)

    def _check_capacity(self):
        p = self.p
        try:
            end = planned_end_bits(p)
        except EncodeError as exc:
            raise InternalError("A planned slot cannot be packed (library bug): %s" % exc)
        needed = end
        if end <= STREAM_BITS:
            tail = p.tail
            room = STREAM_BITS - end
            if tail.nbits > room and tail.slice(room, tail.nbits).to_int() != 0:
                needed = end + tail.nbits
        if needed > STREAM_BITS:
            self.err(self.errors_capacity, "E_CAPACITY", needed)

    # --- steps 10 to 13 ----------------------------------------------------------------------
    def _diff_sorted(self):
        """The diff in report order: the claimed slots by slot, then removed, added and not-imported slots (each by slot).
        That is the order the steps append them in, so nothing needs sorting."""
        return list(self.diff)

    def _append_notes(self):
        budget = self.stats.get('native_budget')
        if budget:
            self.warnings.append(V.make('I_NATIVE_BUDGET', budget['spent'], budget['maximum']))
        else:
            self.warnings.append(V.make("I_BUDGET"))
        self.warnings.append(V.make("I_PALETTE", self.m.fixed.palette_crc))
        self.warnings.append(V.make("I_UNVERIFIED"))

    def _finish(self):
        m, p, o = self.m, self.p, self.options
        if o.fsm_policy == "DROP":
            p.drop_fsm()
        flavour = self._flavour_override()
        force = bool(o.force_reencode) or (self._rewrite_hash() and not self._content_dirty())
        diff = self._diff_sorted()
        if not (p.dirty or force):
            data = self.template                                        # passthrough: the template's own bytes
            self.stats.update({"mode": "passthrough", "end_bit": m.end_bit, "L": m.stream_length,
                               "hash_flavour": hashing.flavour_label(m.flavour)})
        else:
            rendered = p.render(force=force, flavour=flavour)
            data = rendered.data
            self.warnings.extend(rendered.issues)
            self.stats["mode"] = "forced" if force else "patched"
            self._verify(data)
        self._append_notes()
        return ExportResult(True, data, diff, [], self.warnings, self.stats)

    def _verify(self, data):
        """Invariant I2 (5.10 step 12): re-parse the output and compare it with the plan. ``InternalError`` on a violation."""
        m, p = self.m, self.p
        hyp = p.hypothesis
        flt = {"type19": hyp.type19, "axis_bits": list(hyp.axis_bits), "guid": hyp.guid}
        try:
            again = MapVariant.from_bytes(data, ReadOptions(strict=True, hypothesis_filter=flt))
        except MvarError as exc:
            raise InternalError("The exported bytes could not be read back (library bug): %s" % exc)

        def fail(what):
            raise InternalError("The exported bytes do not match the plan (library bug): %s." % what)

        if again.hypothesis != hyp:
            fail("the layout hypothesis changed")
        if not _same_except_file_length(m.header.raw, again.header.raw) or again.fixed.raw != p.fixed.raw \
                or again.labels.raw != m.labels.raw or again.guid != m.guid:
            fail("a part of the stream that is never edited changed")
        if [q.as_tuple() for q in again.quotas] != [q.as_tuple() for q in p.quotas]:
            fail("the quota rows differ from the plan")
        for i in range(SLOT_COUNT):
            planned = p.slots[i].snapshot()
            if again.slots[i].snapshot() != planned:
                fail("slot %d does not decode to the planned values" % i)
            if planned == m.slots[i].snapshot() and again.slots[i].snapshot() != m.slots[i].snapshot():
                fail("untouched slot %d changed" % i)
        if again.end_bit != planned_end_bits(p):
            fail("the stream ends at bit %d, expected %d" % (again.end_bit, planned_end_bits(p)))
        if again.blf.shape in ("plain4", "plain4+fsm"):
            # the patched and the forced serialisation must agree, but only for a template that a forced re-encode reproduces: a
            # template with a wrong `_eof` value or `chdr` length keeps it in a patched save and is repaired by a forced one
            if self._template_is_canonical() and again.to_bytes(force=True) != data:
                fail("a forced re-encode of the output differs from the output")
        elif again.blf.shape in ("cmp4", "cmp4+fsm"):                    # only an unchanged _cmp wrapper survives (fsm_policy = DROP)
            if self._content_dirty() or again.to_bytes(force=False) != data:
                fail("a _cmp wrapper was kept although the content changed")
        else:
            fail("the container shape is %s" % again.blf.shape)
        for obj, index, type_id, cached, rotated in self.processed:
            problem = self._request_mismatch(again.record_for(again.slots[index]), obj, type_id, cached, rotated)
            if problem:
                fail("slot %d (%s): %s" % (index, obj.name, problem))
        self.stats.update({"end_bit": again.end_bit, "L": again.stream_length,
                           "hash_flavour": hashing.flavour_label(again.flavour)})

    def _template_is_canonical(self):
        """True for a plain-shaped template that a forced re-encode reproduces byte for byte (SPEC 2.11)."""
        return self.m.blf.shape in ("plain4", "plain4+fsm") and self.m.to_bytes(force=True) == self.template

    def _request_mismatch(self, rec, obj, type_id, cached, rotated):
        """First difference between a decoded record and what the object asked for (within quantisation), or ``None``."""
        b = self.m.fixed.bounds
        axes = self.m.hypothesis.axis_bits
        for k in range(3):
            if abs(rec.position[k] - obj.position[k]) > codecs.pos_tolerance(axes[k], b[2 * k], b[2 * k + 1]) + 1e-9:
                return "position axis %d is %r, asked for %r" % (k, rec.position[k], obj.position[k])
        if type_id is not None and rec.type_id != type_id:
            return "type id 0x%04X, asked for 0x%04X" % (rec.type_id, type_id)
        if cached is not None and rec.cached_type != cached:
            return "class %d, expected %d" % (rec.cached_type, cached)
        if rotated:
            if catalog.compatible(self.m):
                if V.angle_between(rec.up, obj.up) > 0.006 or V.angle_between(rec.forward, obj.forward) > 0.006:
                    return 'rotation does not match the requested native pose'
            else:
                wanted = V.yaw_of(obj.forward)
                got = V.yaw_of(rec.forward)
                delta = abs((got - wanted + math.pi) % (2 * math.pi) - math.pi)
                if rec.orientation_kind != "vertical" or delta > codecs.ANGLE_STEP + 1e-9:
                    return "rotation does not match the requested yaw"
        pairs = (("spawn_sequence", rec.spawn_sequence, obj.spawn_sequence), ("spawn_time", rec.spawn_time, obj.spawn_time),
                 ("label_index", rec.label_index, obj.label_index), ("color", rec.color, obj.color),
                 ("shape", rec.shape, obj.shape), ("symmetry", rec.symmetry, obj.symmetry),
                 ("place_at_start", rec.place_at_start, bool(obj.place_at_start)),
                 ("game_specific", rec.game_specific, bool(obj.game_specific)),
                 ("physics", V.physics_norm(rec.physics), V.physics_norm(obj.physics)),
                 ("other_a", rec.other_a, obj.other_a), ("other_b", rec.other_b, obj.other_b))
        for label, got, wanted in pairs:
            if got != wanted:
                return "%s is %r, asked for %r" % (label, got, wanted)
        if self._team_changed(obj.team, rec.team):
            return "team is %r, asked for %r" % (rec.team, obj.team)
        shape = rec.shape
        if shape:
            decoded = {1: [rec.width], 2: [rec.width, rec.top, rec.bottom], 3: [rec.width, rec.length, rec.top, rec.bottom]}[shape]
            for want, got in zip(_dim_values(obj, shape), decoded):
                if codecs.dim_encode(want) != codecs.dim_encode(got):
                    return "a shape dimension is %r, asked for %r" % (got, want)
        return None


def export_map_variant(template: bytes, objects: Sequence, options) -> ExportResult:
    """Patch ``template`` with ``objects`` and return an ``api.ExportResult`` (SPEC 5.10, 6.4).

    Stateless: the template is parsed strictly, nothing touches the file system. Every problem is collected; a refusal
    returns ``ok = False`` and ``data = None``. If nothing changed (no moved, edited, added or removed object, no
    forced re-encode, no ``_fsm`` drop, no different hash recipe) the result is the template's own bytes.
    """
    return _Export(template, objects, options).run()
