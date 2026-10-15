"""One object slot of the map variant: raw integer fields, read, exact re-pack, per-field spans (SPEC 3.6, 3.8, 5.1).

A :class:`Slot` keeps every field of the record as the raw integer that is stored in the file (binding
decision B): floats are views computed elsewhere. ``pack`` re-emits the record from those integers, so a
slot that was read and not changed packs to exactly the bits it was read from (invariant I1, asserted for
all 651 slots by the model). A slot carries ``raw`` (the original bit range, ``None`` for a slot created in
memory) and ``baseline`` (a frozen copy of every field at parse time); ``dirty`` is computed from the
difference, so setting a field back to its old value makes the slot clean again.

Record layout (SPEC 3.6; widths in bits)::

    present 1 | flags2 2 | folder_absent 1 [folder 8] | item_absent 1 [item 5] | in_bounds 1 |
    pos_x bx | pos_y by | pos_z bz | up_global 1 [up_code 20] | angle 14 | parent 10 |
    shape 2 [dims 11 each: 0, 1, 3 or 4] | spawn_seq 8 (signed) | respawn 8 | cached_type 5 |
    label_absent 1 [label 8] | placement 8 | team 4 | color_absent 1 [color 3] | extras (by cached type)

``folder_absent``, ``item_absent``, ``label_absent`` and ``color_absent`` use 1 = none. Extras: cached type 1
has 8 bits; 12, 13 and 14 have 5 + 5; type 19 is DISPUTED (3.8): rule ``plain8`` stores 8 bits (index + 1,
0 = none), rule ``flag8`` stores a flag bit (1 = none) and 8 more bits only when the flag is 0.

Pure Python 3.9 to 3.13, standard library only, relative imports only.
"""
import copy
from typing import List, Optional, Tuple

from .bitio import BitReader, BitString, BitWriter
from .codecs import UP_CODE_MAX_VALID, UP_N, UP_STRIDE
from .errors import DecodeError, EncodeError

__all__ = ["Slot", "SlotContext", "WalkReject", "read_slot", "SLOT_COUNT", "SHAPE_DIM_COUNT", "SNAPSHOT_FIELDS",
           "PARENT_RAW_MAX", "TYPE19_RULES", "extra_layout"]

SLOT_COUNT = 651
SHAPE_DIM_COUNT = {0: 0, 1: 1, 2: 3, 3: 4}
PARENT_RAW_MAX = 651
TYPE19_RULES = ("flag8", "plain8")
SNAPSHOT_FIELDS = ("present", "flags2", "folder", "item", "in_bounds", "pos", "up_global", "up_code", "angle",
                   "parent_raw", "shape", "dims", "spawn_seq", "respawn", "cached_type", "label", "placement",
                   "team_raw", "color", "extra")


class WalkReject(DecodeError):
    """A hypothesis' walk failed a hard check (SPEC 3.10). ``reason`` is one of the codes below.

    ``oob`` (in_bounds == 0), ``parent``, ``folder``, ``label``, ``upface``, ``overrun``, ``length``,
    ``quota_count``, ``labels`` (the label table itself), ``bounds``. ``slot`` and ``bit`` say where.
    ``unsourced`` marks the two checks that have no primary source (3.10 rule 3: folder below quota_count and
    label entry present).
    """

    def __init__(self, reason, message="", slot=None, bit=None, unsourced=False):
        super().__init__(message or reason)
        self.reason = reason
        self.slot = slot
        self.bit = bit
        self.unsourced = unsourced


def extra_layout(cached_type, rule):
    """Widths of the extra fields of a slot with this cached type: a list of ints, or ``'type19'`` markers.

    ``[]`` for most types, ``[8]`` for 1, ``[5, 5]`` for 12 to 14; type 19 depends on ``rule``:
    ``plain8`` -> ``[8]``, ``flag8`` -> ``[1, 8]`` with the second only present when the flag is 0.
    """
    if cached_type == 1:
        return [8]
    if 12 <= cached_type <= 14:
        return [5, 5]
    if cached_type == 19:
        return [8] if rule == "plain8" else [1, 8]
    return []


class SlotContext(object):
    """What :func:`read_slot` needs from the walk, and where it reports problems.

    ``axes`` are the three position bit widths, ``rule`` the type-19 rule. ``quota_count`` and
    ``label_present`` (list of bools, one per label entry) feed the hard checks of 3.10 rule 3.
    ``lenient`` switches off the two unsourced checks. ``stop`` makes the first violation raise
    :class:`WalkReject`; with ``stop=False`` violations are collected in ``violations`` and the walk goes on
    (diagnostics for ``verify_mvar``). ``soft`` counts the soft checks of 3.10 rule 4.
    """

    def __init__(self, axes, rule, quota_count, label_present, lenient=False, stop=True):
        self.axes = tuple(axes)
        self.rule = rule
        self.quota_count = quota_count
        self.label_present = list(label_present)
        self.lenient = lenient
        self.stop = stop
        self.violations = []          # [(reason, slot, bit, detail, unsourced)]
        self.soft = {}                # soft check name -> count

    def violate(self, reason, slot, bit, detail, unsourced=False):
        self.violations.append((reason, slot, bit, detail, unsourced))
        if self.stop:
            raise WalkReject(reason, detail, slot, bit, unsourced)

    def count(self, name, amount=1):
        self.soft[name] = self.soft.get(name, 0) + amount


class Slot(object):
    """One of the 651 object slots (SPEC 5.1). Absent slots are ``Slot(i, False)`` and pack to one 0 bit."""

    def __init__(self, index: int, present: bool = False) -> None:
        self.index = index
        self.present = present
        self.flags2 = 0
        self.folder = None                  # None = absent bit set
        self.item = None
        self.in_bounds = 1
        self.pos = [0, 0, 0]                # raw cell indices
        self.up_global = 1
        self.up_code = None                 # only when up_global == 0
        self.angle = 0
        self.parent_raw = 0                 # stored = parent slot + 1, 0 = none
        self.shape = 0
        self.dims = []                      # raw 11-bit codes
        self.spawn_seq = 0                  # signed
        self.respawn = 0
        self.cached_type = 0
        self.label = None
        self.placement = 0
        self.team_raw = 0
        self.color = None
        self.extra = []                     # see the module docstring
        self.raw = None                     # Optional[BitString]: the original bits (None for a created slot)
        self.baseline = None                # frozen snapshot at parse time (None for a created slot)

    # --- identity / change tracking ----------------------------------------------------------
    def snapshot(self) -> Tuple:
        """Frozen tuple of every raw field (``SNAPSHOT_FIELDS`` order); ``(False,)`` for an absent slot."""
        if not self.present:
            return (False,)
        return (True, self.flags2, self.folder, self.item, self.in_bounds, tuple(self.pos), self.up_global,
                self.up_code, self.angle, self.parent_raw, self.shape, tuple(self.dims), self.spawn_seq,
                self.respawn, self.cached_type, self.label, self.placement, self.team_raw, self.color,
                tuple(self.extra))

    def freeze(self, raw: Optional[BitString]) -> None:
        """Attach the original bit range and take the baseline snapshot (done once, at parse time)."""
        self.raw = raw
        self.baseline = self.snapshot()

    @property
    def dirty(self):
        """Names of the fields that differ from the baseline (``{'*'}`` for a slot created in memory)."""
        if self.baseline is None:
            return set(["*"])
        now = self.snapshot()
        if now == self.baseline:
            return set()
        if len(now) != len(self.baseline):            # present <-> absent
            return set(["present"])
        return set(name for name, a, b in zip(SNAPSHOT_FIELDS, now, self.baseline) if a != b)

    @property
    def is_dirty(self):
        return self.baseline is None or self.snapshot() != self.baseline

    def copy(self) -> "Slot":
        out = copy.copy(self)
        out.pos = list(self.pos)
        out.dims = list(self.dims)
        out.extra = list(self.extra)
        return out

    # --- layout ------------------------------------------------------------------------------
    def _check_consistent(self, rule):
        """Refuse (``EncodeError``) a slot whose fields cannot be written back."""
        if self.shape not in SHAPE_DIM_COUNT:
            raise EncodeError("Slot %d: shape %r is not 0 to 3." % (self.index, self.shape))
        if len(self.dims) != SHAPE_DIM_COUNT[self.shape]:
            raise EncodeError("Slot %d: shape %d needs %d dimension(s), has %d."
                              % (self.index, self.shape, SHAPE_DIM_COUNT[self.shape], len(self.dims)))
        if self.up_global and self.up_code is not None:
            raise EncodeError("Slot %d: up_global is set but an up code is given." % self.index)
        if not self.up_global and self.up_code is None:
            raise EncodeError("Slot %d: up_global is clear but there is no up code." % self.index)
        ct = self.cached_type
        if ct == 19:
            if rule == "plain8":
                if len(self.extra) != 1:
                    raise EncodeError("Slot %d: a type-19 object under plain8 needs extra [stored]." % self.index)
            else:
                if len(self.extra) != 2 or self.extra[0] not in (0, 1) or (self.extra[0] == 1 and self.extra[1] != 0):
                    raise EncodeError("Slot %d: a type-19 object under flag8 needs extra [flag, index] "
                                      "(index 0 when the flag is 1)." % self.index)
        elif len(self.extra) != len(extra_layout(ct, rule)):
            raise EncodeError("Slot %d: cached type %d takes %d extra value(s), has %d."
                              % (self.index, ct, len(extra_layout(ct, rule)), len(self.extra)))

    def pack(self, w: BitWriter, rule: str, axes: Tuple[int, int, int]) -> None:
        """Write the record. ``EncodeError`` if a field does not fit its width or the fields disagree."""
        if not self.present:
            w.write(0, 1)
            return
        self._check_consistent(rule)
        w.write(1, 1)
        w.write(self.flags2, 2)
        if self.folder is None:
            w.write(1, 1)
        else:
            w.write(0, 1)
            w.write(self.folder, 8)
        if self.item is None:
            w.write(1, 1)
        else:
            w.write(0, 1)
            w.write(self.item, 5)
        w.write(self.in_bounds, 1)
        for k in range(3):
            w.write(self.pos[k], axes[k])
        if self.up_global:
            w.write(1, 1)
        else:
            w.write(0, 1)
            w.write(self.up_code, 20)
        w.write(self.angle, 14)
        w.write(self.parent_raw, 10)
        w.write(self.shape, 2)
        for d in self.dims:
            w.write(d, 11)
        w.write_signed(self.spawn_seq, 8)
        w.write(self.respawn, 8)
        w.write(self.cached_type, 5)
        if self.label is None:
            w.write(1, 1)
        else:
            w.write(0, 1)
            w.write(self.label, 8)
        w.write(self.placement, 8)
        w.write(self.team_raw, 4)
        if self.color is None:
            w.write(1, 1)
        else:
            w.write(0, 1)
            w.write(self.color, 3)
        ct = self.cached_type
        if ct == 19:
            if rule == "plain8":
                w.write(self.extra[0], 8)
            else:
                w.write(self.extra[0], 1)
                if self.extra[0] == 0:
                    w.write(self.extra[1], 8)
        else:
            for value, width in zip(self.extra, extra_layout(ct, rule)):
                w.write(value, width)

    def to_bits(self, rule: str, axes: Tuple[int, int, int]) -> BitString:
        """The record as a BitString (re-packed from the raw integers)."""
        w = BitWriter()
        self.pack(w, rule, axes)
        return w.getbits()

    def bit_length(self, rule: str, axes: Tuple[int, int, int]) -> int:
        """Width of the record in bits."""
        if not self.present:
            return 1
        self._check_consistent(rule)
        n = 1 + 2
        n += 1 if self.folder is None else 9
        n += 1 if self.item is None else 6
        n += 1 + axes[0] + axes[1] + axes[2]
        n += 1 if self.up_global else 21
        n += 14 + 10 + 2 + 11 * len(self.dims) + 8 + 8 + 5
        n += 1 if self.label is None else 9
        n += 8 + 4
        n += 1 if self.color is None else 4
        ct = self.cached_type
        if ct == 19 and rule == "flag8":
            n += 1 if self.extra[0] == 1 else 9
        else:
            n += sum(extra_layout(ct, rule))
        return n

    def field_spans(self, rule: str, axes: Tuple[int, int, int]) -> List[Tuple[str, int, int]]:
        """``[(field, start, end), ...]`` relative to the start of the record (names as in SPEC 3.6).

        The names are ``present, flags2, folder_absent, folder, item_absent, item, in_bounds, pos_x, pos_y,
        pos_z, up_global, up_code, angle, parent, shape, dims, spawn_seq, respawn, cached_type,
        label_absent, label, placement, team, color_absent, color, extras``; an optional value that is
        absent has no span of its own.
        """
        spans = []
        pos = [0]

        def add(name, width):
            spans.append((name, pos[0], pos[0] + width))
            pos[0] += width

        add("present", 1)
        if not self.present:
            return spans
        add("flags2", 2)
        add("folder_absent", 1)
        if self.folder is not None:
            add("folder", 8)
        add("item_absent", 1)
        if self.item is not None:
            add("item", 5)
        add("in_bounds", 1)
        for k, axis in enumerate("xyz"):
            add("pos_" + axis, axes[k])
        add("up_global", 1)
        if not self.up_global:
            add("up_code", 20)
        add("angle", 14)
        add("parent", 10)
        add("shape", 2)
        add("dims", 11 * len(self.dims))
        add("spawn_seq", 8)
        add("respawn", 8)
        add("cached_type", 5)
        add("label_absent", 1)
        if self.label is not None:
            add("label", 8)
        add("placement", 8)
        add("team", 4)
        add("color_absent", 1)
        if self.color is not None:
            add("color", 3)
        total = self.bit_length(rule, axes)
        spans.append(("extras", pos[0], total))
        return spans

    def __repr__(self):
        if not self.present:
            return "Slot(%d, absent)" % self.index
        return "Slot(%d, folder=%r, item=%r, pos=%r, cached_type=%d)" % (self.index, self.folder, self.item,
                                                                         self.pos, self.cached_type)


def read_slot(r: BitReader, index: int, ctx: SlotContext) -> Slot:
    """Read slot ``index`` at the reader's position (SPEC 3.6) and apply the hard checks of 3.10 rule 3.

    Violations go to ``ctx`` (it raises :class:`WalkReject` when ``ctx.stop``). A reader overrun is a
    ``BitOverrun`` and is turned into a rejection by the caller. The returned slot has no ``raw`` /
    ``baseline`` yet (the model attaches them for the accepted walk only).
    """
    if not r.read(1):
        return Slot(index, False)
    s = Slot(index, True)
    s.flags2 = r.read(2)
    if not r.read(1):
        mark = r.pos
        s.folder = r.read(8)
        if s.folder >= ctx.quota_count and not ctx.lenient:
            ctx.violate("folder", index, mark, "slot %d: folder %d is not below the quota count %d"
                        % (index, s.folder, ctx.quota_count), True)
    if not r.read(1):
        s.item = r.read(5)
    mark = r.pos
    s.in_bounds = r.read(1)
    if not s.in_bounds:
        ctx.violate("oob", index, mark, "slot %d: in-bounds flag is 0" % index)
    axes = ctx.axes
    cells = [r.read(axes[0]), r.read(axes[1]), r.read(axes[2])]
    s.pos = cells
    for k in range(3):
        if cells[k] == 0 or cells[k] == (1 << axes[k]) - 1:
            ctx.count("pos_at_range_extreme")
            break
    if r.read(1):
        s.up_global = 1
    else:
        s.up_global = 0
        mark = r.pos
        s.up_code = r.read(20)
        if s.up_code > UP_CODE_MAX_VALID:
            ctx.violate("upface", index, mark, "slot %d: up code %d has cube face %d (above 5)"
                        % (index, s.up_code, s.up_code // UP_STRIDE))
        elif (s.up_code % UP_STRIDE) // UP_N > 416:
            ctx.count("up_dead_zone")
    s.angle = r.read(14)
    mark = r.pos
    s.parent_raw = r.read(10)
    if s.parent_raw > PARENT_RAW_MAX:
        ctx.violate("parent", index, mark, "slot %d: parent link %d is above %d" % (index, s.parent_raw, PARENT_RAW_MAX))
    s.shape = r.read(2)
    s.dims = [r.read(11) for _ in range(SHAPE_DIM_COUNT[s.shape])]
    s.spawn_seq = r.read_signed(8)
    s.respawn = r.read(8)
    s.cached_type = r.read(5)
    if not r.read(1):
        mark = r.pos
        s.label = r.read(8)
        if s.label >= len(ctx.label_present):
            ctx.violate("label", index, mark, "slot %d: label index %d is not below the label count %d"
                        % (index, s.label, len(ctx.label_present)))
        elif not ctx.label_present[s.label] and not ctx.lenient:
            ctx.violate("label", index, mark, "slot %d: label index %d names an absent label entry" % (index, s.label), True)
    s.placement = r.read(8)
    s.team_raw = r.read(4)
    if s.team_raw > 9:
        ctx.count("team_above_9")
    if not r.read(1):
        s.color = r.read(3)
    ct = s.cached_type
    if ct == 1:
        s.extra = [r.read(8)]
    elif 12 <= ct <= 14:
        s.extra = [r.read(5), r.read(5)]
    elif ct == 19:
        if ctx.rule == "plain8":
            s.extra = [r.read(8)]
        else:
            flag = r.read(1)
            s.extra = [1, 0] if flag else [0, r.read(8)]
    return s
