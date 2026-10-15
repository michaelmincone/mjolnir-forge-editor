"""The body walk: prefix, hypotheses, acceptance, selection (SPEC 3.2 to 3.10; gate G3).

A *hypothesis* is a tuple ``(type19_rule, axis_bits_triple, guid_present)`` (3.10). The part of the stream
before the slots (UGC header, fixed body fields, label table) does not depend on it and is read once
(:func:`read_prefix`); every hypothesis then walks ``[GUID] + 651 slots + quota rows`` and is *accepted* only
when

1. no read overruns the 0x7000-byte stream and no present slot has ``in_bounds == 0``;
2. the stored length agrees: ``ceil(end / 8) == L`` (class ``ceil_end``), or ``L == 0x7000`` (class
   ``capacity``), or the stored bytes are ``00 00 00 00`` (class ``zero``, passed in as ``L == 0``);
3. the hard plausibility checks hold (``quota_count <= 256``, label count, label index and entry present,
   folder below ``quota_count``, ``parent_raw <= 651``, up-code face at most 5, finite ordered bounds);

the soft checks of rule 4 only produce counts. The selection rule (DEC-3.10) is applied to one GUID value
at a time, the one implied by the body version first.

The unsourced checks (label entry present, folder below ``quota_count``) can be switched off with
``lenient=True`` (``verify_mvar --lenient``); no export is ever built from a lenient parse.

Pure Python 3.9 to 3.13, standard library only, relative imports only.
"""
import math
import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple

from . import codecs
from .bitio import BitOverrun, BitReader, get_bits
from .errors import AmbiguousLayoutError, DesyncError, FormatError, OutOfBoundsPositionError, UnsupportedVariantError
from .labels import LabelError, LabelTable, read_label_table
from .slot import SLOT_COUNT, Slot, SlotContext, WalkReject, read_slot
from .ugc_header import CONTENT_TYPE_MAP_VARIANT, CONTENT_TYPE_NAMES, UgcHeader, read_header

__all__ = ["Hypothesis", "BodyFixed", "Quota", "Prefix", "WalkResult", "HypothesisReport", "read_prefix", "build_hypotheses",
           "walk_hypothesis", "walk_stream", "choose", "diagnose", "length_class", "BODY_FIXED_BITS", "QUOTA_ROW_BITS",
           "STREAM_BITS", "GUID_BITS", "SUPPORTED_BODY_VERSIONS", "QUOTA_COUNT_MAX"]

BODY_FIXED_BITS = 371
QUOTA_ROW_BITS = 24
GUID_BITS = 128
STREAM_BYTES = 0x7000
STREAM_BITS = STREAM_BYTES * 8
SUPPORTED_BODY_VERSIONS = (31, 32)
QUOTA_COUNT_MAX = 256
TYPE19_PREFERENCE = ("flag8", "plain8")
AXIS_NAMES = "xyz"


@dataclass(frozen=True)
class Hypothesis:
    """``(type19_rule, axis_bits, guid_present)`` (SPEC 6.3)."""
    type19: str
    axis_bits: Tuple[int, int, int]
    guid: bool

    def label(self):
        return "type19=%s axes=%d/%d/%d guid=%s" % (self.type19, self.axis_bits[0], self.axis_bits[1], self.axis_bits[2],
                                                     "yes" if self.guid else "no")

    def as_dict(self):
        return {"type19": self.type19, "axis_bits": list(self.axis_bits), "guid": self.guid}


class BodyFixed(object):
    """The fixed body fields (SPEC 3.3, 371 bits) as raw integers plus their raw bit range."""
    FIELDS = (("version", 8), ("checksum", 32), ("palette_crc", 32), ("quota_count", 9), ("map_id_2", 32),
              ("built_in", 1), ("built_from_xml", 1))

    def __init__(self, version, checksum, palette_crc, quota_count, map_id_2, built_in, built_from_xml, bounds_raw,
                 max_budget, spent_budget, raw=None, start_bit=0):
        self.version = version
        self.checksum = checksum
        self.palette_crc = palette_crc
        self.quota_count = quota_count
        self.map_id_2 = map_id_2
        self.built_in = built_in
        self.built_from_xml = built_from_xml
        self.bounds_raw = tuple(bounds_raw)           # 6 x u32: xmin, xmax, ymin, ymax, zmin, zmax (float32 bit patterns)
        self.max_budget = max_budget
        self.spent_budget = spent_budget
        self.raw = raw
        self.start_bit = start_bit

    @property
    def bounds(self):
        """The six bounds as Python floats (exactly the float32 values)."""
        return tuple(struct.unpack(">f", struct.pack(">I", v))[0] for v in self.bounds_raw)

    def field_spans(self):
        """``[(name, start, end), ...]`` relative to the start of the fixed body."""
        spans = []
        pos = 0
        for name, width in self.FIELDS:
            spans.append((name, pos, pos + width))
            pos += width
        for name in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax"):
            spans.append(("bounds_" + name, pos, pos + 32))
            pos += 32
        spans.append(("max_budget", pos, pos + 32))
        spans.append(("spent_budget", pos + 32, pos + 64))
        return spans


class Quota(object):
    """One quota row: ``minimum``, ``maximum``, ``placed`` (u8 each; SPEC 3.7)."""

    def __init__(self, minimum, maximum, placed):
        self.minimum = minimum
        self.maximum = maximum
        self.placed = placed

    def as_tuple(self):
        return (self.minimum, self.maximum, self.placed)

    def __eq__(self, other):
        return isinstance(other, Quota) and self.as_tuple() == other.as_tuple()

    def __hash__(self):
        return hash(self.as_tuple())

    def __repr__(self):
        return "Quota(%d, %d, %d)" % self.as_tuple()


class Prefix(object):
    """The hypothesis-independent start of the stream: header, fixed body, label table.

    ``failure`` is a :class:`WalkReject` when the label table or ``quota_count`` is unusable (every
    hypothesis would fail the same way); ``labels`` is then ``None`` for a label failure.
    """

    def __init__(self, stream):
        self.stream = stream
        self.header = None                     # type: Optional[UgcHeader]
        self.fixed = None                      # type: Optional[BodyFixed]
        self.labels = None                     # type: Optional[LabelTable]
        self.failure = None                    # type: Optional[WalkReject]
        self.body_start = 0                    # E_h
        self.labels_start = 0                  # E_b
        self.labels_end = 0

    @property
    def version(self):
        return self.fixed.version

    @property
    def guid_implied(self):
        return self.fixed.version >= 32


def _axis_name(index):
    return AXIS_NAMES[index]


def read_prefix(stream: bytes) -> Prefix:
    """Read header, fixed body and label table (the part every hypothesis shares).

    Raises ``UnsupportedVariantError`` for a content type other than a map variant and for a body version
    outside {31, 32}, and ``FormatError`` for unusable bounds (SPEC 7.2). A bad label table or a
    ``quota_count`` above 256 is recorded in ``Prefix.failure`` instead (it is a hard-check violation that
    every hypothesis shares).
    """
    prefix = Prefix(stream)
    r = BitReader(stream)
    header = read_header(r)
    prefix.header = header
    if header.content_type != CONTENT_TYPE_MAP_VARIANT:
        raise UnsupportedVariantError("The content type is %d (%s); a map variant is %d."
                                      % (header.content_type, CONTENT_TYPE_NAMES.get(header.content_type, "unknown"),
                                         CONTENT_TYPE_MAP_VARIANT))
    prefix.body_start = r.pos
    version = r.read(8)
    if version not in SUPPORTED_BODY_VERSIONS:
        raise UnsupportedVariantError("The map variant body version is %d; supported versions are 31 and 32." % version)
    checksum = r.read(32)
    palette_crc = r.read(32)
    quota_count = r.read(9)
    map_id_2 = r.read(32)
    built_in = r.read(1)
    built_from_xml = r.read(1)
    bounds_raw = [r.read(32) for _ in range(6)]
    max_budget = r.read(32)
    spent_budget = r.read(32)
    fixed = BodyFixed(version, checksum, palette_crc, quota_count, map_id_2, built_in, built_from_xml, bounds_raw,
                      max_budget, spent_budget, r.slice(prefix.body_start, r.pos), prefix.body_start)
    prefix.fixed = fixed
    prefix.labels_start = r.pos
    bounds = fixed.bounds
    for axis in range(3):
        mn, mx = bounds[2 * axis], bounds[2 * axis + 1]
        if not (math.isfinite(mn) and math.isfinite(mx)) or mn > mx:
            raise FormatError("The map bounds are not valid (axis %s: min %g, max %g)." % (_axis_name(axis), mn, mx))
    if quota_count > QUOTA_COUNT_MAX:
        prefix.failure = WalkReject("quota_count", "the quota count %d is above %d" % (quota_count, QUOTA_COUNT_MAX), None,
                                    prefix.body_start + 72)
        return prefix
    try:
        prefix.labels = read_label_table(r)
    except LabelError as exc:
        prefix.failure = WalkReject("labels", str(exc), None, exc.bit if exc.bit is not None else prefix.labels_start)
        return prefix
    except BitOverrun as exc:
        prefix.failure = WalkReject("overrun", "the label table runs past the end of the stream (%s)" % exc, None,
                                    prefix.labels_start)
        return prefix
    prefix.labels_end = r.pos
    return prefix


def build_hypotheses(prefix: Prefix, options=None) -> List[Hypothesis]:
    """All hypotheses for this prefix in preference order: GUID value implied by the version first, then
    type 19 ``flag8`` before ``plain8``, then the axis triples in first-seen order (primary ``ceil`` first)."""
    triples = codecs.axis_bit_hypotheses(prefix.fixed.bounds)
    implied = prefix.guid_implied
    out = []
    for guid in (implied, not implied):
        for rule in TYPE19_PREFERENCE:
            for triple in triples:
                out.append(Hypothesis(rule, triple, guid))
    flt = getattr(options, "hypothesis_filter", None) if options is not None else None
    if flt:
        def keep(h):
            if "type19" in flt and flt["type19"] != h.type19:
                return False
            if "guid" in flt and bool(flt["guid"]) != h.guid:
                return False
            if "axis_bits" in flt and tuple(flt["axis_bits"]) != tuple(h.axis_bits):
                return False
            return True
        out = [h for h in out if keep(h)]
    return out


def length_class(end_bit: int, L: int) -> Optional[str]:
    """Class of the stored length against the walk's end (SPEC 2.12): ``ceil_end``, ``capacity``, ``zero`` or ``None``.

    ``L == 0`` stands for the four stored zero bytes.
    """
    if L == 0:
        return "zero"
    if L == (end_bit + 7) // 8:
        return "ceil_end"
    if L == STREAM_BYTES:
        return "capacity"
    return None


class WalkResult(object):
    """What one hypothesis' walk produced (accepted or not, see ``HypothesisReport``)."""

    def __init__(self, hypothesis, prefix):
        self.hypothesis = hypothesis
        self.prefix = prefix
        self.guid = None                       # type: Optional[BitString]
        self.slots = []                        # type: List[Slot]
        self.slot_starts = []                  # bit offset of each slot (651 entries) ...
        self.slots_end = 0                     # ... and where the last slot ends
        self.quotas = []                       # type: List[Quota]
        self.quota_start = 0
        self.end_bit = 0                       # bit after the last quota row
        self.length_class = None
        self.soft = {}                         # soft check name -> count (3.10 rule 4)
        self.violations = []                   # [(reason, slot, bit, detail, unsourced)] (diagnostic walks only)
        self.completed = False                 # the walk reached the end of the quota table
        self.type19_status = "undetermined"
        self.guid_contradicts_version = False
        self.lenient = False

    @property
    def present_slots(self):
        return [s for s in self.slots if s.present]

    def fingerprint(self):
        """Everything two walks must share to count as the same decode (SPEC DEC-3.10)."""
        guid = self.guid.to_int() if self.guid is not None else None
        return (self.end_bit, guid, tuple(s.snapshot() for s in self.slots), tuple(q.as_tuple() for q in self.quotas))

    @property
    def suspicion(self):
        return sum(self.soft.values())


def _walk(prefix: Prefix, L: int, hyp: Hypothesis, lenient: bool, stop: bool) -> WalkResult:
    """Walk one hypothesis. With ``stop`` the first hard violation raises :class:`WalkReject`; without it
    violations are collected in ``WalkResult.violations`` and the walk goes on as far as it can (a reader
    overrun ends the walk with ``completed`` false)."""
    result = WalkResult(hyp, prefix)
    result.lenient = lenient
    r = BitReader(prefix.stream)
    r.set_bitpos(prefix.labels_end)
    ctx = SlotContext(hyp.axis_bits, hyp.type19, prefix.fixed.quota_count, prefix.labels.present_flags, lenient, stop)
    result.violations = ctx.violations
    result.soft = ctx.soft
    stage = "guid"
    index = None
    try:
        if hyp.guid:
            result.guid = r.read_bitstring(GUID_BITS)
        stage = "slot"
        slots = result.slots
        starts = result.slot_starts
        for index in range(SLOT_COUNT):
            starts.append(r.pos)
            slots.append(read_slot(r, index, ctx))
        result.slots_end = r.pos
        result.quota_start = r.pos
        stage = "quota"
        for index in range(prefix.fixed.quota_count):
            result.quotas.append(Quota(r.read(8), r.read(8), r.read(8)))
    except BitOverrun as exc:
        slot = index if stage == "slot" else None
        where = {"guid": "the GUID block", "slot": "slot %s" % index, "quota": "quota row %s" % index}[stage]
        bit = exc.pos if exc.pos is not None else r.pos
        detail = "the stream ends inside %s (a read of %s bits at bit %s does not fit)" % (where, exc.requested, bit)
        if stop:
            raise WalkReject("overrun", detail, slot, bit)
        ctx.violations.append(("overrun", slot, bit, detail, False))
        return result
    result.end_bit = r.pos
    result.completed = True
    _soft_checks(result)
    result.length_class = length_class(result.end_bit, L)
    if result.length_class is None:
        ctx.violate("length", None, result.end_bit,
                    "the walk ends at bit %d (ceil(end/8) = %d) but the stored length is %d"
                    % (result.end_bit, (result.end_bit + 7) // 8, L))
    return result


def _soft_checks(result: WalkResult) -> None:
    """The soft checks of 3.10 rule 4 that need only the walk and the prefix (counts, never rejections)."""
    soft = result.soft
    prefix = result.prefix
    end = result.end_bit
    stream = prefix.stream
    nbits = len(stream) * 8
    pad_end = min(nbits, ((end + 7) // 8) * 8)
    if pad_end > end:
        if get_bits(stream, end, pad_end - end):
            soft["pad_bits_nonzero"] = 1
    tail_first = pad_end // 8
    if any(stream[tail_first:]):
        soft["tail_nonzero"] = 1
    if not prefix.labels.inflated_length_matches:
        soft["label_length_mismatch"] = 1
    bad_text = len(prefix.labels.undecodable())
    if bad_text:
        soft["label_text_undecodable"] = bad_text
    bounds = prefix.fixed.bounds
    zero_axes = sum(1 for k in range(3) if bounds[2 * k] == bounds[2 * k + 1])
    if zero_axes:
        soft["zero_range_axis"] = zero_axes
    inverted = sum(1 for q in result.quotas if q.minimum > q.maximum)
    if inverted:
        soft["quota_min_above_max"] = inverted
    counts = {}
    for s in result.slots:
        if s.present and s.folder is not None:
            counts[s.folder] = counts.get(s.folder, 0) + 1
    mismatch = 0
    for index, q in enumerate(result.quotas):
        if q.placed != counts.get(index, 0):
            mismatch += 1
    if mismatch:
        soft["quota_placed_differs"] = mismatch


class HypothesisReport(object):
    """Outcome of one hypothesis, for the diagnostics of ``DesyncError`` and ``verify_mvar``."""

    def __init__(self, hypothesis):
        self.hypothesis = hypothesis
        self.accepted = False
        self.reason = None                     # first failing check (see WalkReject) or None
        self.slot = None
        self.bit = None
        self.detail = ""
        self.unsourced = False                 # the failing check is one of the two without a primary source
        self.unsourced_only = False            # ... and the walk is accepted once those checks are off
        self.end_bit = None                    # where the walk ended (if it got that far)
        self.length_class = None
        self.soft = {}
        self.progress = (-1, 0)                # (slots read, bit) when the walk stopped: larger = further

    def as_dict(self):
        out = {"hypothesis": self.hypothesis.as_dict(), "accepted": self.accepted, "reason": self.reason,
               "slot": self.slot, "bit": self.bit, "detail": self.detail, "end_bit": self.end_bit,
               "length_class": self.length_class, "unsourced_only": self.unsourced_only, "soft": dict(self.soft)}
        return out


def walk_hypothesis(prefix: Prefix, L: int, hyp: Hypothesis, lenient: bool = False):
    """Strict walk of one hypothesis. Returns ``(WalkResult, HypothesisReport)``; the result is ``None`` when rejected."""
    report = HypothesisReport(hyp)
    try:
        result = _walk(prefix, L, hyp, lenient, True)
    except WalkReject as exc:
        report.reason = exc.reason
        report.slot = exc.slot
        report.bit = exc.bit
        report.detail = str(exc)
        report.unsourced = exc.unsourced
        report.progress = (exc.slot if exc.slot is not None else SLOT_COUNT + 1, exc.bit if exc.bit is not None else 0)
        return None, report
    report.accepted = True
    report.end_bit = result.end_bit
    report.length_class = result.length_class
    report.soft = dict(result.soft)
    report.progress = (SLOT_COUNT + 2, result.end_bit)
    return result, report


def diagnose(prefix: Prefix, L: int, hyp: Hypothesis, lenient: bool = False) -> WalkResult:
    """A non-stopping walk for diagnostics: every hard violation is collected and the walk continues as far as the stream allows.

    ``completed`` is true when the quota table was reached; ``violations`` lists every problem as
    ``(reason, slot, bit, detail, unsourced)``. Never use it to build a model.
    """
    return _walk(prefix, L, hyp, lenient, False)


def walk_stream(stream: bytes, L: int, hyp: Hypothesis, spec=None) -> WalkResult:
    """Walk one hypothesis over a raw stream: header, body, labels, [GUID], 651 slots, quota rows (SPEC 6.3).

    ``WalkReject`` (a ``DecodeError``) on overrun, out-of-bounds record or any hard check; the usual
    ``UnsupportedVariantError`` / ``FormatError`` from :func:`read_prefix`. ``spec`` is accepted for
    signature compatibility with the contract and unused.
    """
    prefix = read_prefix(stream)
    if prefix.failure is not None:
        raise prefix.failure
    return _walk(prefix, L, hyp, False, True)


def _first_difference(a: WalkResult, b: WalkResult):
    """Index of the first slot where two walks differ, or -1 (then the quota rows / end / GUID differ)."""
    for x, y in zip(a.slots, b.slots):
        if x.snapshot() != y.snapshot():
            return x.index
    return -1


def _failure_summary(reports: List[HypothesisReport]) -> str:
    best = max(reports, key=lambda rep: rep.progress)
    where = "slot %d, " % best.slot if best.slot is not None else ""
    return "Best candidate (%s) fails at %sbit %s: %s" % (best.hypothesis.label(), where,
                                                          best.bit if best.bit is not None else "?", best.detail)


def choose(stream: bytes, L: int, version_hint: Optional[int] = None, options=None, lenient: bool = False,
           prefix: Optional[Prefix] = None):
    """Pick the hypothesis (SPEC 3.10, DEC-3.10). Returns ``(Hypothesis, WalkResult, List[HypothesisReport])``.

    ``L`` is the stored stream length (0 = the four zero bytes). ``version_hint`` (the ``mvar`` chunk
    version) is accepted for the contract of SPEC 6.3 and not used here: the GUID hypothesis is ordered by the
    *body* version read from the stream (3.3), and the model compares the two versions for ``W_VERSION_MISMATCH``.
    ``options`` may carry ``hypothesis_filter``. With ``lenient`` the two unsourced checks are off (diagnostics,
    never exported).

    Raises ``UnsupportedVariantError`` / ``FormatError`` from the prefix, ``OutOfBoundsPositionError`` when
    every hypothesis of the version-implied GUID value is rejected for an out-of-bounds record at the same
    slot, ``AmbiguousLayoutError`` when several hypotheses are accepted with different decodes, and
    ``DesyncError`` (with ``diagnostics``) when none is accepted.
    """
    if prefix is None:
        prefix = read_prefix(stream)
    if prefix.failure is not None:
        failure = prefix.failure
        diag = [{"hypothesis": None, "accepted": False, "reason": failure.reason, "slot": failure.slot,
                 "bit": failure.bit, "detail": str(failure)}]
        raise DesyncError("Could not read this map variant: %s (bit %s). Run tools/verify_mvar.py on the file for the "
                          "full report." % (failure, failure.bit), diag)
    hyps = build_hypotheses(prefix, options)
    if not hyps:
        raise DesyncError("Could not read this map variant: no layout hypothesis is left to try.", [])
    implied = prefix.guid_implied
    reports = []
    walks = {}
    for hyp in hyps:
        result, report = walk_hypothesis(prefix, L, hyp, lenient)
        reports.append(report)
        if result is not None:
            walks[hyp] = result
    if not lenient:                                              # flag a hypothesis rejected only by an unsourced check
        for report in reports:
            if not report.accepted and report.unsourced:
                retry, _ = walk_hypothesis(prefix, L, report.hypothesis, True)
                report.unsourced_only = retry is not None

    def accepted_of(guid):
        return [h for h in hyps if h.guid == guid and h in walks]

    group = accepted_of(implied)
    mismatch = False
    if not group:
        group = accepted_of(not implied)
        mismatch = bool(group)
    if not group:
        main = [rep for rep in reports if rep.hypothesis.guid == implied]
        reasons = set((rep.reason, rep.slot) for rep in main)
        if len(main) > 0 and len(reasons) == 1 and main[0].reason == "oob" and main[0].slot is not None:
            slot = main[0].slot
            raise OutOfBoundsPositionError("Slot %d has a position outside the map bounds (in-bounds flag is 0). Such "
                                           "records need map data that is not in the file and cannot be read." % slot, slot)
        raise DesyncError("Could not read this map variant: none of the %d known layouts fits. %s. Run "
                          "tools/verify_mvar.py on the file for the full report." % (len(hyps), _failure_summary(reports)),
                          [rep.as_dict() for rep in reports])
    first = group[0]
    base = walks[first]
    prints = {}
    distinct = []
    for hyp in group:
        key = walks[hyp].fingerprint()
        if key not in prints:
            prints[key] = hyp
            distinct.append(hyp)
    if len(distinct) > 1:
        cands = []
        for hyp in distinct:
            w = walks[hyp]
            cands.append({"hypothesis": hyp.as_dict(), "end_bit": w.end_bit, "first_differing_slot": _first_difference(base, w)})
        first_slot = max(c["first_differing_slot"] for c in cands)
        raise AmbiguousLayoutError("This map variant can be read %d different ways that all look valid (they first differ at "
                                   "slot %d). Run tools/verify_mvar.py for details." % (len(distinct), first_slot), cands)
    result = base
    prints_base_key = base.fingerprint()
    rules_equal = set(h.type19 for h in group if walks[h].fingerprint() == prints_base_key)
    result.type19_status = "undetermined" if len(rules_equal) > 1 else first.type19
    result.guid_contradicts_version = mismatch
    return first, result, reports
