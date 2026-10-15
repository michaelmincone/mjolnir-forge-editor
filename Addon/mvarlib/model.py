"""The map variant model: parse, views, passthrough and forced serialisation (SPEC 5.1, 5.2, 6.3, 3.11; gate G3).

:class:`MapVariant` is built by :meth:`MapVariant.from_bytes`: the container is parsed (``blf``), the body
is walked with the hypothesis search of ``walk`` and the accepted walk becomes the model. Every part keeps its
raw bit range (header, fixed body, label table, GUID block, each slot, tail), so

* an unmodified model returns the **original bytes** from :meth:`to_bytes` (passthrough, also the ``_cmp``
  wrapper, ``_fsm``, unknown blocks and a trailer after ``_eof``);
* ``to_bytes(force=True)`` rebuilds every derivable part: every slot is re-packed from its raw integers, the
  quota rows are re-written, then ``L``, the embedded file length, the hash, ``_eof`` and the ``chdr`` length
  are recomputed by the container (SPEC 2.11). For the shapes ``plain4`` / ``plain4+fsm`` this equals the
  input; for the ``cmp`` shapes it is the expanded form (DEC-2.6);
* a model with a changed slot or quota row (the edits of gate G5) is written in *patched* mode: clean slots
  are copied from their raw bits, changed slots are re-packed, the rest of the stream is shifted.

Invariant I1 (every slot re-packs to its own bits) is asserted for all 651 slots at parse time; a violation
is an ``InternalError``.

Pure Python 3.9 to 3.13, standard library only, relative imports only.
"""
import copy
import hashlib
from typing import List, Optional, Tuple

from . import blf as blf_mod
from . import codecs, hashing, tables, walk as walk_mod
from .api import Issue, MapInfo, ObjectRecord
from .bitio import BitReader, BitString, BitWriter
from .errors import CapacityError, DesyncError, InternalError, UnsupportedVariantError
from .labels import LabelTable
from .slot import SLOT_COUNT, Slot
from .ugc_header import UgcHeader, compare_chdr_header, parse_chdr
from .walk import BodyFixed, Hypothesis, Quota, STREAM_BITS, STREAM_BYTES

__all__ = ["MapVariant", "BodyFixed", "Quota", "type_name_for", "SOFT_WARNINGS"]

# soft check name -> (issue code, message with one %d for the count)
SOFT_WARNINGS = {
    "tail_nonzero": ("W_TAIL_NONZERO", "The unused part of the bit stream after the quota table is not all zero; it is kept unchanged (%d)."),
    "pad_bits_nonzero": ("W_PAD_BITS_NONZERO", "The padding bits after the quota table are not zero; they are kept unchanged (%d)."),
    "label_length_mismatch": ("W_LABEL_LENGTH_MISMATCH", "The inflated label buffer is not as long as its stored data length (%d)."),
    "label_text_undecodable": ("W_LABEL_TEXT_UNDECODABLE", "%d label text(s) could not be decoded."),
    "quota_min_above_max": ("W_QUOTA_MIN_ABOVE_MAX", "%d quota row(s) have a minimum above their maximum."),
    "up_dead_zone": ("W_UP_DEAD_ZONE", "%d object(s) have an up-axis code in the unused part of the code range."),
    "team_above_9": ("W_TEAM_ABOVE_9", "%d object(s) have a team value above 9."),
}
AXIS_NAMES = ("x", "y", "z")


def type_name_for(map_name: Optional[str], folder: Optional[int], item: Optional[int]) -> Tuple[int, str, bool]:
    """``(type_id, display name, stock)`` of a folder/item pair on a map.

    ``type_id`` is ``(folder << 8) | item`` or -1 when either is absent; the name is ``"Unknown (0x%04X)"``
    for an id this map's stock table does not know and ``"Unknown (no type)"`` when there is no id.
    """
    if folder is None or item is None:
        return -1, "Unknown (no type)", False
    type_id = (folder << 8) | item
    name = tables.object_name_for_id(map_name, type_id) if map_name else None
    if name is None:
        return type_id, "Unknown (0x%04X)" % type_id, False
    return type_id, name, True


class MapVariant(object):
    """A parsed Halo: Reach map variant (SPEC 5.1). Build one with :meth:`from_bytes`."""

    def __init__(self):
        self.name = ""
        self.blf = None                  # type: Optional[blf_mod.BlfFile]
        self.chunk = None                # the mvar Chunk of ``blf``
        self.chdr = None                 # parse_chdr() dict, or None
        self.header = None               # type: Optional[UgcHeader]
        self.fixed = None                # type: Optional[BodyFixed]
        self.labels = None               # type: Optional[LabelTable]
        self.guid = None                 # type: Optional[BitString]
        self.slots = []                  # type: List[Slot]
        self.quotas = []                 # type: List[Quota]
        self.tail = None                 # type: Optional[BitString]
        self.hypothesis = None           # type: Optional[Hypothesis]
        self.type19_status = "undetermined"
        self.guid_contradicts_version = False
        self.length_class = None
        self.end_bit = 0
        self.lenient = False             # True: only a lenient walk fitted; never export from such a model
        self.reports = []                # HypothesisReport list of the selection
        self.soft = {}                   # soft check counts (3.10 rule 4)
        self.warnings = []               # type: List[Issue]
        self.template_sha256 = ""
        self._quota_baseline = []

    # --- construction ------------------------------------------------------------------------
    @classmethod
    def from_bytes(cls, data: bytes, options=None, name: str = "") -> "MapVariant":
        """Parse ``data``. Raises the errors of SPEC 6.2 / 7.2 (``BlfFormatError``, ``UnsupportedVariantError``,
        ``FormatError``, ``DesyncError``, ``AmbiguousLayoutError``, ``OutOfBoundsPositionError``)."""
        blf = blf_mod.parse(data)
        chunk = blf.find("mvar")
        if chunk is None:
            if blf.find("mpvr") is not None:
                raise UnsupportedVariantError("This is a game variant (block 'mpvr'), not a map variant. "
                                              "Use File > Import for map variants only.")
            raise UnsupportedVariantError("No map variant block ('mvar') was found; blocks present: %s." % blf.layout_text())
        m = cls()
        m.name = name
        m.blf = blf
        m.chunk = chunk
        m.template_sha256 = hashlib.sha256(blf.original).hexdigest()
        stream = chunk.stream
        stored = 0 if chunk.zero_length else chunk.stored_length
        strict = getattr(options, "strict", True) if options is not None else True
        try:
            hyp, res, reports = walk_mod.choose(stream, stored, chunk.version, options)
        except DesyncError:
            if strict:
                raise
            hyp, res, reports = walk_mod.choose(stream, stored, chunk.version, options, lenient=True)
            m.lenient = True
        m._adopt(res, hyp, reports)
        m._check_repack()
        m._collect_warnings()
        return m

    def _adopt(self, res, hyp, reports):
        prefix = res.prefix
        self.header = prefix.header
        self.fixed = prefix.fixed
        self.labels = prefix.labels
        self.guid = res.guid
        self.slots = res.slots
        self.quotas = res.quotas
        self.hypothesis = hyp
        self.type19_status = res.type19_status
        self.guid_contradicts_version = res.guid_contradicts_version
        self.length_class = res.length_class
        self.end_bit = res.end_bit
        self.reports = reports
        self.soft = dict(res.soft)
        stream = prefix.stream
        bounds = len(stream) * 8
        r = BitReader(stream)
        for index, slot in enumerate(self.slots):
            a = res.slot_starts[index]
            b = res.slot_starts[index + 1] if index + 1 < SLOT_COUNT else res.slots_end
            slot.freeze(r.slice(a, b))
        self.tail = r.slice(res.end_bit, bounds)
        self._quota_baseline = [q.as_tuple() for q in self.quotas]
        chdr_chunk = self.blf.find("chdr")
        try:
            self.chdr = parse_chdr(chdr_chunk.raw) if chdr_chunk is not None else None
        except Exception:                                  # a damaged chdr is only worth a warning
            self.chdr = None

    def _check_repack(self):
        """Invariant I1: every slot packs to exactly the bits it was read from."""
        rule, axes = self.hypothesis.type19, self.hypothesis.axis_bits
        for slot in self.slots:
            if slot.to_bits(rule, axes) != slot.raw:
                raise InternalError("Slot %d does not re-pack to the bits it was read from (library bug)." % slot.index)

    # --- derived facts -----------------------------------------------------------------------
    @property
    def map_id(self):
        return self.header.map_id

    @property
    def map_name(self):
        return tables.map_name_for_id(self.header.map_id)

    @property
    def version(self):
        return self.fixed.version

    @property
    def bounds(self):
        return self.fixed.bounds

    @property
    def axes(self):
        return self.hypothesis.axis_bits

    @property
    def type19_rule(self):
        return self.hypothesis.type19

    @property
    def flavour(self):
        return self.chunk.flavour

    @property
    def shape(self):
        return self.blf.shape

    @property
    def occupied(self):
        return sum(1 for s in self.slots if s.present)

    def present_slots(self) -> List[Slot]:
        return [s for s in self.slots if s.present]

    def free_slots(self) -> List[int]:
        return [s.index for s in self.slots if not s.present]

    @property
    def stream_length(self):
        """Stored stream length ``L`` as found (0 for the four-zero-bytes class)."""
        return 0 if self.chunk.zero_length else self.chunk.stored_length

    @property
    def dirty(self):
        """True when a slot, a quota row or the container has been changed since parsing."""
        if self.blf.dirty:
            return True
        if [q.as_tuple() for q in self.quotas] != self._quota_baseline:
            return True
        return any(s.is_dirty for s in self.slots)

    def drop_fsm(self):
        """``fsm_policy = DROP``: remove the trailing ``_fsm`` block; counts as a modification."""
        self.blf.drop_fsm()

    def copy(self) -> "MapVariant":
        """Deep copy (for planning edits without touching the original model)."""
        return copy.deepcopy(self)

    def _collect_warnings(self):
        out = []
        blf = self.blf
        out.extend(blf.warnings)
        if self.chunk.version != self.fixed.version:
            out.append(Issue("W_VERSION_MISMATCH", "warning", "The map variant block has chunk version %d but its body says "
                             "version %d." % (self.chunk.version, self.fixed.version)))
        if self.guid_contradicts_version:
            out.append(Issue("W_GUID_VERSION_MISMATCH", "warning",
                             "This map variant says it has version %d but the 128-bit block that versions 32 and above "
                             "carry is %s; it was read that way because only that reading fits."
                             % (self.fixed.version, "present" if self.hypothesis.guid else "missing")))
        bounds = self.fixed.bounds
        for k in range(3):
            if bounds[2 * k] == bounds[2 * k + 1]:
                out.append(Issue("W_ZERO_RANGE_AXIS", "warning",
                                 "The map bounds have no extent on the %s axis; positions on that axis cannot be changed."
                                 % AXIS_NAMES[k]))
        eof = blf.chunks[blf.eof_index]
        real_length = eof.offset + eof.size
        if self.header.file_length != real_length:
            out.append(Issue("W_FILE_LENGTH_MISMATCH", "warning",
                             "The file length stored in the map variant header (%d) differs from the length through the "
                             "end-of-file block (%d)." % (self.header.file_length, real_length)))
        if self.fixed.map_id_2 != self.header.map_id:
            out.append(Issue("W_MAP_ID_MISMATCH", "warning",
                             "The map id in the body (%d) differs from the map id in the header (%d)."
                             % (self.fixed.map_id_2, self.header.map_id)))
        if self.chdr is not None:
            for sentence in compare_chdr_header(self.chdr, self.header):
                if sentence.startswith("file length"):
                    continue                           # judged above against the real length (a cmp/fsm/trailer file differs by design)
                out.append(Issue("W_CHDR_MISMATCH", "warning", "The content header (chdr) and the map variant header disagree: " + sentence))
        else:
            out.append(Issue("W_CHDR_MISSING", "warning", "The file has no readable content header (chdr) block."))
        map_name = self.map_name
        unresolved = 0
        for s in self.slots:
            if s.present:
                _, _, stock = type_name_for(map_name, s.folder, s.item)
                if not stock:
                    unresolved += 1
        if unresolved:
            self.soft["object_id_not_in_stock_table"] = unresolved
        if map_name is None:
            out.append(Issue("W_MAP_UNKNOWN", "warning",
                             "Map id %d (0x%X) is not one of the 20 stock Halo: Reach maps this tool knows; objects are "
                             "shown by id and export is limited to stock maps." % (self.header.map_id, self.header.map_id)))
        elif unresolved:
            out.append(Issue("W_UNKNOWN_OBJECT_IDS", "warning",
                             "%d object(s) have an id that is not in the stock object table of %s; they are shown as "
                             "Unknown (0x....)." % (unresolved, map_name)))
        for key, (code, text) in SOFT_WARNINGS.items():
            count = self.soft.get(key, 0)
            if count:
                out.append(Issue(code, "warning", text % count))
        if self.lenient:
            out.append(Issue("W_LENIENT_PARSE", "warning", "This map variant only fits when two unverified plausibility "
                             "checks are switched off; it must not be used for export."))
        self.warnings = out

    # --- views -------------------------------------------------------------------------------
    def info(self) -> MapInfo:
        """The ``MapInfo`` of SPEC 6.4."""
        map_name = self.map_name
        return MapInfo(
            map_id=self.header.map_id, map_name=map_name, is_stock_map=map_name is not None, bounds=tuple(self.fixed.bounds),
            quota_count=self.fixed.quota_count, version=self.fixed.version, title=self.header.title_text,
            description=self.header.description_text, labels=self.labels.texts(), label_present=self.labels.present_flags,
            occupied=self.occupied, shape=self.blf.shape, template_sha256=self.template_sha256,
            hash_flavour=hashing.flavour_label(self.flavour), palette_crc=self.fixed.palette_crc,
            max_budget_raw=self.fixed.max_budget, spent_budget_raw=self.fixed.spent_budget,
            hypothesis={"type19": self.type19_status, "axis_bits": list(self.hypothesis.axis_bits),
                        "guid": self.hypothesis.guid, "length_class": self.length_class},
            warnings=list(self.warnings))

    def record_for(self, slot: Slot) -> ObjectRecord:
        """The ``ObjectRecord`` view of one present slot (SPEC 3.11)."""
        mn_mx = self.fixed.bounds
        bits = self.hypothesis.axis_bits
        position = tuple(codecs.pos_decode(slot.pos[k], bits[k], mn_mx[2 * k], mn_mx[2 * k + 1]) for k in range(3))
        forward, up = codecs.reconstruct_orientation(slot.up_global, slot.up_code, slot.angle)
        type_id, type_name, stock = type_name_for(self.map_name, slot.folder, slot.item)
        d = [codecs.dim_decode(v) for v in slot.dims]
        width = length = top = bottom = 0.0
        if slot.shape == 1:
            width = d[0]
        elif slot.shape == 2:
            width, top, bottom = d[0], d[1], d[2]
        elif slot.shape == 3:
            width, length, top, bottom = d[0], d[1], d[2], d[3]
        view = codecs.placement_view(slot.placement)
        ct = slot.cached_type
        other_a = other_b = 0
        if ct == 1:
            other_a = slot.extra[0]
        elif 12 <= ct <= 14:
            other_a, other_b = slot.extra[0], slot.extra[1]
        elif ct == 19:
            if self.hypothesis.type19 == "plain8":
                other_a = slot.extra[0] - 1
            else:
                other_a = -1 if slot.extra[0] == 1 else slot.extra[1]
        raw = slot.raw
        return ObjectRecord(
            slot=slot.index, folder=-1 if slot.folder is None else slot.folder, item=-1 if slot.item is None else slot.item,
            type_id=type_id, type_name=type_name, stock=stock, position=position, forward=forward, up=up,
            orientation_kind="vertical" if slot.up_global else "tilted", parent_slot=slot.parent_raw - 1,
            shape=slot.shape, width=width, length=length, top=top, bottom=bottom, spawn_sequence=slot.spawn_seq,
            spawn_time=slot.respawn, cached_type=ct, label_index=-1 if slot.label is None else slot.label,
            placement=slot.placement, physics=view.physics, symmetry=view.symmetry, place_at_start=view.place_at_start,
            game_specific=view.game_specific, team=codecs.team_view(slot.team_raw), color=codecs.color_view(slot.color),
            other_a=other_a, other_b=other_b, flags2=slot.flags2,
            raw=raw.data if raw is not None else b"", raw_bits=raw.nbits if raw is not None else 0)

    def objects(self) -> List[ObjectRecord]:
        """The occupied slots in slot order as ``ObjectRecord``s."""
        return [self.record_for(s) for s in self.slots if s.present]

    def spans(self, fields: bool = False) -> List[Tuple[str, int, int]]:
        """Ordered ``(name, start_bit, end_bit)`` of every part of the stream (SPEC 5.9), computed from the
        current model: ``header``, each fixed field as ``body.<name>``, ``labels``, ``guid``, ``slot_<i>``,
        ``quota_<i>``, ``tail``. With ``fields=True`` every field of a present slot follows its ``slot_<i>``
        entry as ``slot_<i>.<field>``."""
        out = []
        pos = 0
        out.append(("header", 0, self.header.raw.nbits))
        pos = self.header.raw.nbits
        for name, a, b in self.fixed.field_spans():
            out.append(("body." + name, pos + a, pos + b))
        pos += self.fixed.raw.nbits
        out.append(("labels", pos, pos + self.labels.raw.nbits))
        pos += self.labels.raw.nbits
        if self.guid is not None:
            out.append(("guid", pos, pos + self.guid.nbits))
            pos += self.guid.nbits
        rule, axes = self.hypothesis.type19, self.hypothesis.axis_bits
        for s in self.slots:
            n = s.bit_length(rule, axes)
            out.append(("slot_%d" % s.index, pos, pos + n))
            if fields and s.present:
                for name, a, b in s.field_spans(rule, axes):
                    out.append(("slot_%d.%s" % (s.index, name), pos + a, pos + b))
            pos += n
        for i, q in enumerate(self.quotas):
            out.append(("quota_%d" % i, pos, pos + walk_mod.QUOTA_ROW_BITS))
            pos += walk_mod.QUOTA_ROW_BITS
        out.append(("tail", pos, STREAM_BITS))
        return out

    def locate_bit(self, bit: int) -> str:
        """Name of the span that contains stream bit ``bit`` (for the first-difference report)."""
        for name, a, b in self.spans():
            if a <= bit < b:
                return name
        return "beyond the stream"

    # --- serialisation -----------------------------------------------------------------------
    def build_stream(self, force: bool = False) -> Tuple[BitWriter, int]:
        """The bit stream of the current model: ``(writer, end_bit)``.

        Clean slots are copied from their raw bits unless ``force``; changed (or forced) slots are re-packed
        from their raw integers. The tail is re-appended after the quota rows, shifted with them. Raises
        ``CapacityError`` when the stream would exceed the capacity (or a non-zero tail bit would be pushed
        past it).
        """
        rule, axes = self.hypothesis.type19, self.hypothesis.axis_bits
        w = BitWriter()
        w.write_bitstring(self.header.raw)
        w.write_bitstring(self.fixed.raw)
        w.write_bitstring(self.labels.raw)
        if self.guid is not None:
            w.write_bitstring(self.guid)
        for s in self.slots:
            if not force and s.raw is not None and not s.is_dirty:
                w.write_bitstring(s.raw)
            else:
                s.pack(w, rule, axes)
        if len(self.quotas) != self.fixed.quota_count:
            raise InternalError("The model holds %d quota rows but the body says %d." % (len(self.quotas), self.fixed.quota_count))
        for q in self.quotas:
            w.write(q.minimum, 8)
            w.write(q.maximum, 8)
            w.write(q.placed, 8)
        end = w.pos
        if end > STREAM_BITS:
            raise CapacityError("The edited map variant needs %d bits; it can hold at most %s."
                                % (end, format(STREAM_BITS, ",")))
        tail = self.tail
        room = STREAM_BITS - end
        if tail.nbits > room:
            lost = tail.slice(room, tail.nbits)
            if lost.to_int() != 0:
                raise CapacityError("The edited map variant needs %d bits for its data and extra stream bytes; it can hold at "
                                    "most %s." % (end + tail.nbits, format(STREAM_BITS, ",")))
            tail = tail.slice(0, room)
        w.write_bitstring(tail)
        return w, end

    def length_for(self, end_bit: int) -> int:
        """The stored length ``L`` to write for a stream that ends at ``end_bit`` (the template's class, SPEC 2.12)."""
        if self.length_class == "capacity":
            return STREAM_BYTES
        if self.length_class == "zero":
            return 0
        return (end_bit + 7) // 8

    def render(self, force: bool = False, flavour: Optional[hashing.HashFlavour] = None):
        """Serialise; returns ``blf.Rendered`` (``.data`` bytes and ``.issues`` the writer raised)."""
        if not force and not self.dirty:
            return blf_mod.Rendered(self.blf.to_bytes(force=False), [])
        if self.lenient:
            raise InternalError("A model read leniently cannot be written (library bug: export must refuse it).")
        w, end = self.build_stream(force)
        length = self.length_for(end)
        stream = w.getvalue(STREAM_BYTES)
        container = copy.deepcopy(self.blf)
        chunk = container.find("mvar")
        if stream != chunk.stream or length != self.stream_length:
            chunk.set_stream(stream, length)           # a real change: the container reports W_FSM_STALE, W_TRAILER_KEPT, ...
        return container.render(force=force, stream_length={"mvar": length}, flavour=flavour)

    def to_bytes(self, force: bool = False, flavour: Optional[hashing.HashFlavour] = None) -> bytes:
        """The file bytes. Unmodified and not forced: the input bytes. ``force=True``: full re-encode (SPEC 5.2)."""
        return self.render(force=force, flavour=flavour).data
