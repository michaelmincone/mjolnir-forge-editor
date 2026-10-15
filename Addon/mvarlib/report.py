"""Decode report for ``tools/verify_mvar.py`` (SPEC 6.5, 6.7, tier T3; gate G3).

``build_report(data, options)`` decodes one file and collects every fact of the nine report sections of
SPEC 6.7 (container, hash, header, body, walk, slots, quotas, tail and padding, self-checks) into a JSON-safe
``Report.facts`` dict plus an exit code; ``format_report(report)`` prints it as readable text. Nothing here
writes a file and nothing here keeps game data: a report holds numbers, ids and (unless ``include_strings`` is
off) the file's own title, description, author names and label texts.

Exit codes (SPEC 6.7): ``0`` all good; ``1`` the body does not decode (desync, ambiguous layout, out-of-bounds
record, format error); ``2`` the file is not a map variant, or I/O / usage trouble (a game variant still gets
its container report); ``3`` the body decoded but a self-check failed. A non-zero exit has a
``failure`` sentence that the tool prints as ``VERIFY FAILED: <reason>`` on its last line.

Pure Python 3.9 to 3.13, standard library only, relative imports only.
"""
import hashlib
import json
import os
from typing import Optional

from . import blf as blf_mod
from . import codecs, hashing, plain, tables, walk as walk_mod
from .errors import (AmbiguousLayoutError, BlfFormatError, DesyncError, FormatError, MvarError, OutOfBoundsPositionError,
                     PathPolicyError, UnsupportedVariantError)
from .labels import encode_label_table
from .model import MapVariant, type_name_for
from .slot import SLOT_COUNT
from .ugc_header import CONTENT_TYPE_NAMES, GAME_MODE_NAMES, compare_chdr_header, parse_chdr

__all__ = ["Report", "build_report", "format_report", "report_json", "EXIT_OK", "EXIT_DECODE", "EXIT_NOT_MAP", "EXIT_SELFCHECK",
           "write_output_file", "SELF_CHECK_NAMES"]

EXIT_OK = 0
EXIT_DECODE = 1
EXIT_NOT_MAP = 2
EXIT_SELFCHECK = 3
SELF_CHECK_NAMES = ("slot_repack", "label_reencode", "passthrough", "forced", "plain_round_trip")
OMITTED = "<omitted>"
MAX_LISTED = 40


class Report(object):
    """A decoded report: ``facts`` (JSON-safe), ``exit_code``, ``failure`` (sentence or ``None``)."""

    def __init__(self):
        self.facts = {}
        self.exit_code = EXIT_OK
        self.failure = None
        self.model = None                 # the MapVariant when the body decoded
        self.include_strings = True

    @property
    def ok(self):
        return self.exit_code == EXIT_OK


def _hex(data):
    return bytes(data).hex()


def _hist(counter, key=None):
    """Sorted ``[[key, count], ...]`` (most frequent first, then by key)."""
    items = sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))
    return [[k, v] for k, v in items]


def _bump(counter, key):
    counter[key] = counter.get(key, 0) + 1


# ---------------------------------------------------------------------------------------------
# facts: container, hash, header, body
# ---------------------------------------------------------------------------------------------
def _container_facts(data, blf):
    chunks = []
    for c in blf.chunks:
        chunks.append({"sig": c.sig, "offset": c.offset, "size": c.size, "version": c.version, "flags": c.flags,
                       "cmp": c.cmp is not None})
    eof = blf.chunks[blf.eof_index]
    return {"file_size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "blocks": chunks, "shape": blf.shape,
            "tiles_through_eof": eof.offset + eof.size, "trailer_bytes": len(blf.trailer),
            "trailer_all_zero": (not any(blf.trailer)) if blf.trailer else None,
            "eof_value": int.from_bytes(eof.raw[12:16], "big") if len(eof.raw) >= 16 else None,
            "eof_endian": blf.eof_endian, "eof_value_matches_offset": blf.eof_value_ok, "eof_offset": eof.offset,
            "warnings": [w.code for w in blf.warnings]}


def _scan_container_facts(data):
    """Container facts for a file the strict parser refuses (tolerant block scan)."""
    return {"file_size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "blocks": [{"sig": s, "offset": o, "size": z, "version": v, "flags": f, "cmp": False}
                       for s, o, z, v, f in blf_mod.scan_blocks(data)], "shape": None}


def _hash_facts(chunk):
    a = chunk.analysis
    return {"stored_hash": _hex(a.stored_hash), "length_raw": _hex(a.length_raw), "length_endian": a.length_endian,
            "stored_length": a.stored_length, "zero_length": a.zero_length, "hash_length": a.hash_length,
            "candidates": [{"length_endian": e, "recipe": r, "L": L, "match": bool(m)} for e, r, L, m in a.candidates],
            "flavour": hashing.flavour_label(a.flavour) if a.flavour is not None else None,
            "flavour_pair": list(a.flavour.as_tuple()) if a.flavour is not None else None,
            "enforcement": "unknown (this tool writes a correct hash for the detected recipe; whether MCC checks it is not documented)"}


def _author_facts(a, strings):
    return {"timestamp": a.timestamp, "xuid": "0x%016X" % a.xuid, "name": a.name_text if strings else OMITTED,
            "online_id": a.is_online_id}


def _header_facts(prefix, blf, chdr_chunk, strings):
    h = prefix.header
    map_name = tables.map_name_for_id(h.map_id)
    out = {"content_type": h.content_type, "content_type_name": CONTENT_TYPE_NAMES.get(h.content_type, "unknown"),
           "file_length": h.file_length, "ids": ["0x%016X" % v for v in (h.unk08, h.unk10, h.unk18, h.unk20)],
           "activity": h.activity, "game_mode": h.game_mode, "game_mode_name": GAME_MODE_NAMES.get(h.game_mode, "unknown"),
           "engine": h.engine, "map_id": h.map_id, "map_name": map_name, "category": h.engine_category,
           "created_by": _author_facts(h.created_by, strings), "modified_by": _author_facts(h.modified_by, strings),
           "title": h.title_text if strings else OMITTED, "description": h.description_text if strings else OMITTED,
           "hopper_id": h.hopper_id, "has_campaign_tail": h.campaign is not None, "has_firefight_tail": h.firefight is not None,
           "end_bit": h.end_bit}
    eof = blf.chunks[blf.eof_index]
    out["file_length_matches_real_length"] = h.file_length == eof.offset + eof.size
    chdr_diffs = None
    if chdr_chunk is not None:
        try:
            chdr = parse_chdr(chdr_chunk.raw)
            chdr_diffs = [d for d in compare_chdr_header(chdr, h) if not d.startswith("file length")]
            out["chdr"] = {"content_type": chdr["content_type"], "file_length": chdr["file_length"], "map_id": chdr["map_id"],
                           "title": chdr["title"] if strings else OMITTED,
                           "description": chdr["description"] if strings else OMITTED,
                           "file_length_matches_real_length": chdr["file_length"] == eof.offset + eof.size}
        except MvarError as exc:
            chdr_diffs = ["the chdr block could not be parsed: %s" % exc]
    out["chdr_disagreements"] = chdr_diffs
    return out


def _body_facts(prefix, strings, version_chunk):
    f = prefix.fixed
    bounds = f.bounds
    doubles, singles = codecs.axis_ranges(bounds)
    triples = codecs.axis_bit_hypotheses(bounds)
    variant_triples = {}
    for name, func in (("ceil", codecs.axis_bits_ceil), ("trunc9999", codecs.axis_bits_trunc), ("ceil_f32", codecs.axis_bits_ceil_f32)):
        variant_triples[name] = [[func(r) for r in doubles], [func(r) for r in singles]]
    out = {"version": f.version, "chunk_version": version_chunk, "checksum": "0x%08X" % f.checksum, "palette_crc": "0x%08X" % f.palette_crc,
           "quota_count": f.quota_count, "map_id_copy": f.map_id_2, "built_in": f.built_in, "built_from_xml": f.built_from_xml,
           "bounds": list(bounds), "bounds_raw": ["0x%08X" % v for v in f.bounds_raw],
           "ranges_double": list(doubles), "ranges_f32": list(singles), "axis_triples": [list(t) for t in triples],
           "axis_variants": variant_triples, "axis_ambiguous": len(triples) > 1,
           "max_budget_raw": f.max_budget, "spent_budget_raw": f.spent_budget,
           "max_budget_as_float": _as_float(f.max_budget), "spent_budget_as_float": _as_float(f.spent_budget)}
    lab = prefix.labels
    if lab is not None:
        out["labels"] = {"count": lab.count, "data_length": lab.data_length, "buffer_bytes": len(lab.buffer), "compressed": lab.compressed,
                         "compressed_bytes": len(lab.comp_bytes) if lab.comp_bytes is not None else None,
                         "present": sum(1 for e in lab.entries if e is not None), "bits": lab.raw.nbits,
                         "inflated_length_matches": lab.inflated_length_matches,
                         "texts": [lab.text(i) if strings else OMITTED for i in range(lab.count)],
                         "offsets": list(lab.entries), "start_bit": lab.start_bit, "end_bit": lab.end_bit}
    return out


def _as_float(raw):
    import struct
    return struct.unpack(">f", struct.pack(">I", raw))[0]


# ---------------------------------------------------------------------------------------------
# facts: the hypothesis table
# ---------------------------------------------------------------------------------------------
def _hypothesis_table(prefix, L, lenient):
    """One row per hypothesis: strict verdict plus a non-stopping diagnostic walk."""
    rows = []
    for hyp in walk_mod.build_hypotheses(prefix):
        result, report = walk_mod.walk_hypothesis(prefix, L, hyp, lenient)
        row = report.as_dict()
        row["ceil_end_bytes"] = (report.end_bit + 7) // 8 if report.end_bit is not None else None
        row["unsourced"] = report.unsourced
        row["suspicion"] = sum(report.soft.values()) if report.soft else 0
        diag = walk_mod.diagnose(prefix, L, hyp, lenient)
        row["diag"] = {"completed": diag.completed, "end_bit": diag.end_bit if diag.completed else None,
                       "present_slots": len(diag.present_slots), "slots_read": len(diag.slots),
                       "violation_count": len(diag.violations),
                       "first_violations": [{"reason": v[0], "slot": v[1], "bit": v[2], "detail": v[3], "unsourced": v[4]}
                                            for v in diag.violations[:8]]}
        rows.append(row)
    # flag rows rejected only by one of the two unsourced checks
    if not lenient:
        for row in rows:
            if not row["accepted"] and row.get("unsourced"):
                retry, _ = walk_mod.walk_hypothesis(prefix, L, walk_mod.Hypothesis(row["hypothesis"]["type19"],
                                                                                  tuple(row["hypothesis"]["axis_bits"]),
                                                                                  row["hypothesis"]["guid"]), True)
                row["unsourced_only"] = retry is not None
    return rows


# ---------------------------------------------------------------------------------------------
# facts: slots, quotas, tail
# ---------------------------------------------------------------------------------------------
def _slot_facts(model, strings):
    map_name = model.map_name
    present = model.present_slots()
    by_folder = {}
    by_pair = {}
    types = {}
    cached = {}
    cached_per_folder = {}
    placement = {}
    teams = {}
    colors = {}
    shapes = {}
    label_use = {}
    flags2 = {}
    dangling = valid = 0
    unresolved = {}
    extremes = 0
    dots = []
    type19 = 0
    for s in present:
        _bump(by_folder, s.folder)
        pair = (s.folder, s.item)
        _bump(by_pair, pair)
        type_id, name, stock = type_name_for(map_name, s.folder, s.item)
        if not stock:
            _bump(unresolved, pair)
        key = (s.folder, s.item, name if stock else "Unknown", s.cached_type, s.placement, s.flags2, s.team_raw,
               -1 if s.color is None else s.color)
        _bump(types, key)
        _bump(cached, s.cached_type)
        cached_per_folder.setdefault(s.folder, set()).add(s.cached_type)
        _bump(placement, s.placement)
        _bump(teams, s.team_raw)
        _bump(colors, -1 if s.color is None else s.color)
        _bump(shapes, s.shape)
        _bump(flags2, s.flags2)
        if s.label is not None:
            _bump(label_use, s.label)
        if s.parent_raw:
            if 0 <= s.parent_raw - 1 < SLOT_COUNT and model.slots[s.parent_raw - 1].present:
                valid += 1
            else:
                dangling += 1
        if s.cached_type == 19:
            type19 += 1
        bits = model.axes
        for k in range(3):
            if s.pos[k] == 0 or s.pos[k] == (1 << bits[k]) - 1:
                extremes += 1
                break
        forward, up = codecs.reconstruct_orientation(s.up_global, s.up_code, s.angle)
        dots.append(abs(sum(a * b for a, b in zip(forward, up))))
    positions = [model.record_for(s).position for s in present]
    mins = [min(p[k] for p in positions) for k in range(3)] if positions else None
    maxs = [max(p[k] for p in positions) for k in range(3)] if positions else None
    named = by_pair_names(model, by_pair)
    blocks = sorted([{"folder": k[0], "item": k[1], "type_name": k[2], "count": v} for k, v in named.items()
                     if "block" in k[2].lower()], key=lambda r: -r["count"])
    out = {
        "occupied": len(present), "free": SLOT_COUNT - len(present),
        "per_folder": _hist(by_folder),
        "type_table": [{"folder": k[0], "item": k[1], "type_name": k[2], "cached_type": k[3], "placement": k[4],
                        "flags2": k[5], "team_raw": k[6], "color": k[7], "count": v}
                       for k, v in sorted(types.items(), key=lambda kv: (-kv[1], kv[0][0] if kv[0][0] is not None else -1,
                                                                         kv[0][1] if kv[0][1] is not None else -1))],
        "unresolved_pairs": [{"folder": k[0], "item": k[1], "type_id": ((k[0] << 8) | k[1]) if k[0] is not None and k[1] is not None else None,
                              "count": v} for k, v in sorted(unresolved.items(), key=lambda kv: -kv[1])],
        "cached_type_histogram": _hist(cached),
        "folders_with_several_cached_types": sum(1 for v in cached_per_folder.values() if len(v) > 1),
        "placement_histogram": [["0x%02X" % k, v] for k, v in _hist(placement)],
        "flags2_histogram": _hist(flags2), "team_raw_histogram": _hist(teams), "color_histogram": _hist(colors),
        "shape_histogram": _hist(shapes), "label_use": _hist(label_use) if strings else OMITTED,
        "parent_links": {"valid": valid, "dangling": dangling},
        "type19_objects": type19, "type19_rule": model.type19_status,
        "out_of_bounds_records": sum(1 for s in present if not s.in_bounds),
        "positions_at_range_extreme": extremes,
        "position_min": mins, "position_max": maxs,
        "orientation_vertical": sum(1 for s in present if s.up_global), "orientation_tilted": sum(1 for s in present if not s.up_global),
        "forward_dot_up_max": max(dots) if dots else 0.0,
        "forward_dot_up_over_1e6": sum(1 for d in dots if d > 1e-6),
        "block_objects": blocks,
        "free_slot_numbers_first": model.free_slots()[:16],
    }
    return out


def by_pair_names(model, by_pair):
    """``{(folder, item, type_name): count}`` (helper for the block listing)."""
    out = {}
    for (folder, item), n in by_pair.items():
        out[(folder, item, type_name_for(model.map_name, folder, item)[1])] = n
    return out


def _quota_facts(model):
    counts = {}
    for s in model.present_slots():
        if s.folder is not None:
            _bump(counts, s.folder)
    rows = []
    differ = 0
    inverted = 0
    nonzero = 0
    for i, q in enumerate(model.quotas):
        present = counts.get(i, 0)
        if q.placed != present:
            differ += 1
        if q.minimum > q.maximum:
            inverted += 1
        if q.maximum or q.placed or q.minimum:
            nonzero += 1
            rows.append({"folder": i, "minimum": q.minimum, "maximum": q.maximum, "placed": q.placed, "present_slots": present})
    map_name = model.map_name
    folder_names = {}
    if map_name:
        for type_id, _, display in tables.stock_objects(map_name):
            folder_names.setdefault(type_id >> 8, []).append(display)
    headroom = [{"folder": i, "minimum": q.minimum, "maximum": q.maximum, "placed": q.placed,
                 "name": (folder_names.get(i) or ["?"])[0]} for i, q in enumerate(model.quotas) if q.maximum > q.placed]
    block_rows = [{"folder": i, "minimum": model.quotas[i].minimum, "maximum": model.quotas[i].maximum,
                   "placed": model.quotas[i].placed, "name": names[0]}
                  for i, names in sorted(folder_names.items())
                  if i < len(model.quotas) and any(n.startswith("Block") for n in names)]
    return {"rows": len(model.quotas), "nonzero_rows": nonzero, "listed": rows, "placed_differs_from_slot_count": differ,
            "min_above_max": inverted, "headroom_rows": headroom, "block_rows": block_rows,
            "slots_in_folder_without_row": sorted(f for f in counts if f >= len(model.quotas))}


def _tail_facts(model):
    stream_bits = walk_mod.STREAM_BITS
    pad_end = min(stream_bits, ((model.end_bit + 7) // 8) * 8)
    return {"end_bit": model.end_bit, "ceil_end_bytes": (model.end_bit + 7) // 8, "stored_length": model.stream_length,
            "length_class": model.length_class, "tail_bits": model.tail.nbits, "tail_all_zero": model.tail.to_int() == 0,
            "pad_bits": pad_end - model.end_bit, "pad_bits_zero": "pad_bits_nonzero" not in model.soft,
            "free_bits": stream_bits - model.end_bit, "capacity_bits": stream_bits}


# ---------------------------------------------------------------------------------------------
# self checks
# ---------------------------------------------------------------------------------------------
def _first_difference(model, expected, got):
    """Where two file images first differ: the container byte, and for the bit stream the section and bit."""
    n = min(len(expected), len(got))
    for i in range(n):
        if expected[i] != got[i]:
            break
    else:
        i = n
    text = "first differing byte at offset 0x%X (expected %s, got %s)" % (
        i, "%02X" % expected[i] if i < len(expected) else "end", "%02X" % got[i] if i < len(got) else "end")
    chunk = model.chunk
    start = chunk.offset + chunk.spec.stream_off
    end = start + chunk.spec.stream_capacity
    if start <= i < end:
        a = expected[start:end]
        b = got[start:end]
        for k in range(min(len(a), len(b))):
            if a[k] != b[k]:
                x = a[k] ^ b[k]
                bit = k * 8 + (8 - x.bit_length())
                text += "; stream bit %d lies in section '%s'" % (bit, model.locate_bit(bit))
                break
    return text


def _self_checks(model, data, inject):
    checks = []

    def add(name, ok, detail, informational=False):
        if inject == name and ok is not None:
            ok, detail = False, "FORCED FAILURE (testing hook): " + detail
        checks.append({"name": name, "ok": ok, "detail": detail, "informational": informational})

    rule, axes = model.hypothesis.type19, model.hypothesis.axis_bits
    good = sum(1 for s in model.slots if s.to_bits(rule, axes) == s.raw)
    add("slot_repack", good == SLOT_COUNT, "slot repack identity: %d/%d" % (good, SLOT_COUNT))
    t = model.labels
    fresh = encode_label_table(t.entries, t.buffer, t.compressed, None, t.data_length)
    kept = encode_label_table(t.entries, t.buffer, t.compressed, t.comp_bytes, t.data_length)
    add("label_reencode", None, "label re-encode identical: %s (with the stored compressed block: %s; a difference only means the "
        "local zlib compresses differently)" % ("yes" if fresh == t.raw else "no", "yes" if kept == t.raw else "NO"), True)
    if kept != t.raw:
        checks[-1]["ok"] = False
        checks[-1]["informational"] = False
    add("passthrough", model.to_bytes(force=False) == data, "unmodified to_bytes() == input: %s" % ("yes" if model.to_bytes(force=False) == data else "NO"))
    if model.lenient:
        add("forced", None, "to_bytes(force=True) is not attempted for a lenient parse (it is never written)", True)
        return checks
    try:
        forced = model.to_bytes(force=True)
    except MvarError as exc:
        add("forced", False, "to_bytes(force=True) raised %s: %s" % (type(exc).__name__, exc))
        return checks
    if model.blf.shape.startswith("cmp"):
        again = MapVariant.from_bytes(forced)
        same = (again.to_bytes(force=False) == forced and again.to_bytes(force=True) == forced and
                [s.snapshot() for s in again.slots] == [s.snapshot() for s in model.slots] and
                [q.as_tuple() for q in again.quotas] == [q.as_tuple() for q in model.quotas])
        add("forced", same, "to_bytes(force=True) of a _cmp file is the expanded plain form (DEC-2.6); it re-parses to the same "
            "slots, labels and quotas: %s" % ("yes" if same else "NO"))
    else:
        same = forced == data
        add("forced", same, "to_bytes(force=True) == input: %s" % ("yes" if same else "NO (%s)" % _first_difference(model, data, forced)))
    try:
        again = plain.from_plain(json.loads(json.dumps(plain.to_plain(model))))
        same = again.to_bytes(force=True) == forced
        add("plain_round_trip", same, "plain round trip identical: %s" % ("yes" if same else "NO"))
    except MvarError as exc:
        add("plain_round_trip", False, "plain round trip failed: %s" % exc)
    return checks


# ---------------------------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------------------------
def _classify(exc):
    """Exit code and sentence for an exception raised while reading."""
    if isinstance(exc, BlfFormatError) and ("not a Halo BLF file" in str(exc) or "too short" in str(exc)):
        return EXIT_NOT_MAP, str(exc)
    if isinstance(exc, UnsupportedVariantError):
        text = str(exc)
        if "game variant" in text or "No map variant block" in text or text.startswith("The content type is"):
            return EXIT_NOT_MAP, text
        return EXIT_DECODE, text
    if isinstance(exc, (DesyncError, AmbiguousLayoutError, OutOfBoundsPositionError, FormatError)):
        return EXIT_DECODE, str(exc)
    return EXIT_DECODE, str(exc)


def build_report(data: bytes, options=None, name: str = "", include_strings: bool = True, lenient: bool = False,
                 inject_failure: Optional[str] = None) -> Report:
    """Decode ``data`` and collect the report. Never raises for a bad file (the failure is in the report)."""
    report = Report()
    report.include_strings = include_strings
    facts = report.facts
    facts["file"] = {"name": name if include_strings else OMITTED, "size": len(data)}
    try:
        blf = blf_mod.parse(data)
    except MvarError as exc:
        facts["container"] = _scan_container_facts(data)
        report.exit_code, report.failure = _classify(exc)
        if report.exit_code == EXIT_DECODE:
            report.exit_code = EXIT_NOT_MAP            # a file that is not even a valid block file is not a map variant
        facts["result"] = {"status": "container_error", "message": str(exc)}
        return report
    facts["container"] = _container_facts(data, blf)
    chunk = blf.find("mvar")
    if chunk is None:
        facts["container"]["payload"] = None
        if blf.find("mpvr") is not None:
            msg = "This is a game variant (block 'mpvr'), not a map variant. Use File > Import for map variants only."
            payload = blf.find("mpvr")
            facts["hash"] = _hash_facts(payload)
        else:
            msg = "No map variant block ('mvar') was found; blocks present: %s." % blf.layout_text()
        report.exit_code, report.failure = EXIT_NOT_MAP, msg
        facts["result"] = {"status": "not_a_map_variant", "message": msg}
        return report
    facts["container"]["payload"] = "mvar"
    facts["hash"] = _hash_facts(chunk)
    stored = 0 if chunk.zero_length else chunk.stored_length
    stream = chunk.stream
    # --- prefix: header, fixed body, labels (independent of the hypothesis) ---------------------
    try:
        prefix = walk_mod.read_prefix(stream)
    except MvarError as exc:
        report.exit_code, report.failure = _classify(exc)
        facts["result"] = {"status": "prefix_error", "message": str(exc)}
        return report
    chdr_chunk = blf.find("chdr")
    facts["header"] = _header_facts(prefix, blf, chdr_chunk, include_strings)
    facts["body"] = _body_facts(prefix, include_strings, chunk.version)
    if prefix.failure is not None:
        report.exit_code, report.failure = EXIT_DECODE, "Could not read this map variant: %s (bit %s)." % (prefix.failure, prefix.failure.bit)
        facts["walk"] = {"table": [], "prefix_failure": {"reason": prefix.failure.reason, "bit": prefix.failure.bit,
                                                         "detail": str(prefix.failure)}, "selected": None}
        facts["result"] = {"status": "prefix_failure", "message": report.failure}
        return report
    # --- the hypothesis table -------------------------------------------------------------------
    table = _hypothesis_table(prefix, stored, lenient)
    walk_facts = {"table": table, "stored_length": stored, "stored_length_class_note": "0 stands for the four stored zero bytes",
                  "version_implied_guid": prefix.guid_implied, "lenient": lenient, "selected": None}
    facts["walk"] = walk_facts
    # --- the model ------------------------------------------------------------------------------
    try:
        model = MapVariant.from_bytes(data, options, name)
    except MvarError as exc:
        report.exit_code, report.failure = _classify(exc)
        walk_facts["error"] = {"type": type(exc).__name__, "message": str(exc)}
        if isinstance(exc, DesyncError) and exc.diagnostics:
            walk_facts["diagnostics"] = exc.diagnostics
        if isinstance(exc, AmbiguousLayoutError):
            walk_facts["candidates"] = exc.candidates
        if isinstance(exc, OutOfBoundsPositionError):
            walk_facts["oob_slot"] = exc.slot
        facts["result"] = {"status": "decode_error", "message": str(exc)}
        return report
    report.model = model
    h = model.hypothesis
    walk_facts["selected"] = {"hypothesis": h.as_dict(), "type19_status": model.type19_status, "length_class": model.length_class,
                              "end_bit": model.end_bit, "ceil_end_bytes": (model.end_bit + 7) // 8,
                              "guid_contradicts_version": model.guid_contradicts_version,
                              "suspicion": sum(model.soft.values()), "soft_checks": dict(model.soft), "lenient": model.lenient}
    facts["warnings"] = [{"code": w.code, "severity": w.severity, "message": w.message} for w in model.warnings]
    try:
        facts["slots"] = _slot_facts(model, include_strings)
        facts["quotas"] = _quota_facts(model)
        facts["tail"] = _tail_facts(model)
        facts["selfchecks"] = _self_checks(model, data, inject_failure)
    except MvarError as exc:                               # a library bug (InternalError, ...): report it, never a traceback
        report.exit_code = EXIT_SELFCHECK
        report.failure = "internal error while building the report: %s: %s" % (type(exc).__name__, exc)
        facts["result"] = {"status": "internal_error", "message": report.failure}
        return report
    failed = [c for c in facts["selfchecks"] if c["ok"] is False]
    facts["result"] = {"status": "ok" if not failed else "selfcheck_failed", "message": ""}
    if model.lenient:
        report.exit_code = EXIT_DECODE
        report.failure = "The map variant only fits with the two unverified plausibility checks switched off; it would be refused."
        facts["result"] = {"status": "lenient_only", "message": report.failure}
    elif failed:
        report.exit_code = EXIT_SELFCHECK
        report.failure = "self-check failed: %s" % "; ".join(c["detail"] for c in failed)
        facts["result"]["message"] = report.failure
    return report


# ---------------------------------------------------------------------------------------------
# text
# ---------------------------------------------------------------------------------------------
def _yn(flag):
    return "yes" if flag else "no"


def _tab(rows, indent="  "):
    """Left-aligned table text from rows of strings."""
    if not rows:
        return ""
    widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    lines = []
    for r in rows:
        lines.append(indent + "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)).rstrip())
    return "\n".join(lines)


def _fmt_float(x):
    return "%.9g" % x


def format_report(report: Report) -> str:
    """The report as readable text (the nine sections of SPEC 6.7)."""
    f = report.facts
    out = []
    add = out.append
    add("=" * 78)
    add("verify_mvar report: %s (%d bytes)" % (f["file"]["name"], f["file"]["size"]))
    add("=" * 78)
    c = f.get("container")
    add("")
    add("1. CONTAINER")
    if c is not None:
        add("  file size %d bytes, sha256 %s" % (c["file_size"], c["sha256"]))
        rows = [["block", "offset", "size", "version", "flags", ""]]
        for b in c["blocks"]:
            rows.append([b["sig"], "0x%X" % b["offset"], "0x%X" % b["size"], b["version"], b["flags"], "(from _cmp)" if b.get("cmp") else ""])
        add(_tab(rows))
        add("  shape: %s" % c.get("shape"))
        if "tiles_through_eof" in c:
            add("  blocks tile the file through _eof: %d bytes; trailer after _eof: %d bytes%s"
                % (c["tiles_through_eof"], c["trailer_bytes"], " (all zero)" if c.get("trailer_all_zero") else ""))
            add("  _eof value 0x%X, byte order %s, equals the _eof block's own offset (0x%X): %s"
                % (c["eof_value"], "big-endian" if c["eof_endian"] == ">" else "little-endian", c["eof_offset"], _yn(c["eof_value_matches_offset"])))
    hs = f.get("hash")
    if hs is not None:
        add("")
        add("2. HASH AND STORED LENGTH")
        add("  stored SHA-1 %s" % hs["stored_hash"])
        add("  stored length bytes %s -> %s, byte order %s%s" % (
            hs["length_raw"], hs["stored_length"], "big-endian" if hs["length_endian"] == ">" else "little-endian",
            " (four zero bytes: effective length 0 or 0x7000)" if hs["zero_length"] else ""))
        rows = [["length order", "recipe", "L", "match"]]
        for cand in hs["candidates"]:
            rows.append(["big" if cand["length_endian"] == ">" else "little", cand["recipe"], cand["L"], _yn(cand["match"])])
        add(_tab(rows))
        add("  detected flavour: %s" % (hs["flavour"] or "none (no candidate matches the stored hash)"))
        add("  hash enforcement by MCC: %s" % hs["enforcement"])
    h = f.get("header")
    if h is not None:
        add("")
        add("3. HEADER (bit form inside the stream)")
        add("  content type %d (%s); file length %d (%s the real length through _eof)"
            % (h["content_type"], h["content_type_name"], h["file_length"], "equals" if h["file_length_matches_real_length"] else "DIFFERS FROM"))
        add("  ids %s" % ", ".join(h["ids"]))
        add("  activity %d, game mode %d (%s), engine %d, category %d" % (h["activity"], h["game_mode"], h["game_mode_name"], h["engine"], h["category"]))
        add("  map id %d (0x%X) = %s" % (h["map_id"], h["map_id"], h["map_name"] or "not a known stock map"))
        for who in ("created_by", "modified_by"):
            a = h[who]
            add("  %s: timestamp %d, xuid %s, name %r, online id flag %d" % (who, a["timestamp"], a["xuid"], a["name"], a["online_id"]))
        add("  title %r" % h["title"])
        add("  description %r" % h["description"])
        add("  header ends at bit %d (hopper id %s, campaign tail %s, firefight tail %s)"
            % (h["end_bit"], h["hopper_id"], _yn(h["has_campaign_tail"]), _yn(h["has_firefight_tail"])))
        if h.get("chdr"):
            ch = h["chdr"]
            add("  chdr: content type %d, file length %d, map id %d, title %r, description %r"
                % (ch["content_type"], ch["file_length"], ch["map_id"], ch["title"], ch["description"]))
        if h.get("chdr_disagreements") is None:
            add("  chdr agreement: no chdr block")
        elif h["chdr_disagreements"]:
            add("  chdr agreement: DISAGREES")
            for line in h["chdr_disagreements"]:
                add("    - " + line)
        else:
            add("  chdr agreement: yes (content type, map id, title, description)")
    b = f.get("body")
    if b is not None:
        add("")
        add("4. BODY")
        add("  body version %d (mvar chunk version %d); checksum %s; palette CRC %s" % (b["version"], b["chunk_version"], b["checksum"], b["palette_crc"]))
        add("  quota count %d; map id copy %d; built_in %d; built_from_xml %d" % (b["quota_count"], b["map_id_copy"], b["built_in"], b["built_from_xml"]))
        bb = b["bounds"]
        add("  bounds x %s .. %s, y %s .. %s, z %s .. %s" % tuple(_fmt_float(v) for v in bb))
        add("  ranges (double) %s; (float32) %s" % (", ".join(_fmt_float(v) for v in b["ranges_double"]), ", ".join(_fmt_float(v) for v in b["ranges_f32"])))
        add("  axis bits by rounding variant (double range / float32 range): %s" % "; ".join(
            "%s %s / %s" % (k, "/".join(str(x) for x in v[0]), "/".join(str(x) for x in v[1])) for k, v in sorted(b["axis_variants"].items())))
        add("  distinct axis triples: %s%s" % (", ".join("/".join(str(x) for x in t) for t in b["axis_triples"]),
                                               "  (AMBIGUOUS: the walk decides)" if b["axis_ambiguous"] else ""))
        add("  budget words: max 0x%08X (%d; as float %s), spent 0x%08X (%d; as float %s)"
            % (b["max_budget_raw"], b["max_budget_raw"], _fmt_float(b["max_budget_as_float"]), b["spent_budget_raw"], b["spent_budget_raw"],
               _fmt_float(b["spent_budget_as_float"])))
        lab = b.get("labels")
        if lab is not None:
            add("  label table: %d entries (%d present), data length %d, buffer %d bytes, %s%s, %d bits, bits %d..%d"
                % (lab["count"], lab["present"], lab["data_length"], lab["buffer_bytes"], "compressed" if lab["compressed"] else "uncompressed",
                   " (%d bytes stored)" % lab["compressed_bytes"] if lab["compressed"] else "", lab["bits"], lab["start_bit"], lab["end_bit"]))
            for i, text in enumerate(lab["texts"][:MAX_LISTED]):
                add("    label %d: offset %s text %r" % (i, lab["offsets"][i], text))
            if lab["count"] > MAX_LISTED:
                add("    ... %d more labels" % (lab["count"] - MAX_LISTED))
    w = f.get("walk")
    if w is not None:
        add("")
        add("5. WALK (hypotheses: type 19 rule x axis bits x GUID block)")
        pf = w.get("prefix_failure")
        if pf:
            add("  the walk cannot start: %s (reason %s, bit %s)" % (pf["detail"], pf["reason"], pf["bit"]))
        rows = [["#", "type19", "axis bits", "guid", "accepted", "end bit", "ceil(end/8)", "vs L=%s" % w.get("stored_length"), "first failure"]]
        for i, r in enumerate(w["table"]):
            hy = r["hypothesis"]
            fail = ""
            if not r["accepted"]:
                fail = "%s%s%s: %s" % (r["reason"], " at slot %s" % r["slot"] if r["slot"] is not None else "",
                                       " bit %s" % r["bit"] if r["bit"] is not None else "",
                                       r["detail"])
                if r.get("unsourced_only"):
                    fail += "  [rejected only by an unsourced check]"
            rows.append([i, hy["type19"], "/".join(str(x) for x in hy["axis_bits"]), _yn(hy["guid"]), _yn(r["accepted"]),
                         r["end_bit"] if r["end_bit"] is not None else "-", r["ceil_end_bytes"] if r["ceil_end_bytes"] is not None else "-",
                         r["length_class"] or ("-" if r["end_bit"] is None else "no match"), fail])
        add(_tab(rows))
        for i, r in enumerate(w["table"]):
            d = r.get("diag")
            if d is not None and not r["accepted"]:
                add("  hypothesis %d continued past its violations: %d violation(s), %d slot(s) read, %d present, %s" % (
                    i, d["violation_count"], d["slots_read"], d["present_slots"],
                    "ended at bit %s" % d["end_bit"] if d["completed"] else "did not reach the quota table"))
                for v in d["first_violations"][:4]:
                    add("      - %s at slot %s bit %s: %s" % (v["reason"], v["slot"], v["bit"], v["detail"]))
        if w.get("error"):
            add("  RESULT: %s: %s" % (w["error"]["type"], w["error"]["message"]))
        sel = w.get("selected")
        if sel:
            hy = sel["hypothesis"]
            add("  selected: type 19 rule %s (%s), axis bits %s, GUID block %s; stored length class %s; end bit %d (ceil %d bytes)"
                % (hy["type19"], sel["type19_status"], "/".join(str(x) for x in hy["axis_bits"]), _yn(hy["guid"]), sel["length_class"],
                   sel["end_bit"], sel["ceil_end_bytes"]))
            if sel["guid_contradicts_version"]:
                add("  NOTE: the GUID block contradicts the body version (W_GUID_VERSION_MISMATCH)")
            add("  soft-check suspicion count %d %s" % (sel["suspicion"], json.dumps(sel["soft_checks"], sort_keys=True)))
    ws = f.get("warnings")
    if ws:
        add("  warnings:")
        for x in ws:
            add("    %s: %s" % (x["code"], x["message"]))
    s = f.get("slots")
    if s is not None:
        add("")
        add("6. SLOTS")
        add("  occupied %d of %d (free %d); parent links: %d valid, %d dangling; out-of-bounds records %d"
            % (s["occupied"], SLOT_COUNT, s["free"], s["parent_links"]["valid"], s["parent_links"]["dangling"], s["out_of_bounds_records"]))
        add("  objects per folder: %s" % ", ".join("%s:%d" % (k, v) for k, v in s["per_folder"][:MAX_LISTED]))
        add("  distinct folders with several cached types: %d" % s["folders_with_several_cached_types"])
        add("  cached types: %s" % ", ".join("%s:%d" % (k, v) for k, v in s["cached_type_histogram"]))
        add("  placement bytes: %s" % ", ".join("%s:%d" % (k, v) for k, v in s["placement_histogram"]))
        add("  flags2: %s; team raw: %s; colour: %s; shape: %s" % (
            ", ".join("%s:%d" % tuple(x) for x in s["flags2_histogram"]), ", ".join("%s:%d" % tuple(x) for x in s["team_raw_histogram"]),
            ", ".join("%s:%d" % tuple(x) for x in s["color_histogram"]), ", ".join("%s:%d" % tuple(x) for x in s["shape_histogram"])))
        add("  type-19 objects: %d (rule: %s); positions at a range extreme: %d; vertical %d, tilted %d"
            % (s["type19_objects"], s["type19_rule"], s["positions_at_range_extreme"], s["orientation_vertical"], s["orientation_tilted"]))
        if s["position_min"]:
            add("  position range x %s..%s y %s..%s z %s..%s" % tuple(_fmt_float(v) for pair in zip(s["position_min"], s["position_max"]) for v in pair))
        add("  forward.up orthogonality: max |dot| %.3g, %d over 1e-6" % (s["forward_dot_up_max"], s["forward_dot_up_over_1e6"]))
        if s["unresolved_pairs"]:
            add("  (folder, item) pairs NOT in this map's stock table: %s" % ", ".join(
                "0x%04X x%d" % (p["type_id"], p["count"]) if p["type_id"] is not None else "none x%d" % p["count"] for p in s["unresolved_pairs"][:MAX_LISTED]))
        else:
            add("  every (folder, item) pair resolves in this map's stock table")
        rows = [["folder", "item", "type", "cached", "place", "flags2", "team", "color", "count"]]
        for t in s["type_table"][:MAX_LISTED]:
            rows.append([t["folder"], t["item"], t["type_name"], t["cached_type"], "0x%02X" % t["placement"], t["flags2"], t["team_raw"], t["color"], t["count"]])
        add("  object kinds (folder, item, name, cached type, placement byte, flags2, team raw, colour):")
        add(_tab(rows, "    "))
        if len(s["type_table"]) > MAX_LISTED:
            add("    ... %d more kinds" % (len(s["type_table"]) - MAX_LISTED))
        if s["block_objects"]:
            add("  block-like objects: %s" % ", ".join("%s (folder %s item %s) x%d" % (r["type_name"], r["folder"], r["item"], r["count"]) for r in s["block_objects"]))
        else:
            add("  block-like objects: none")
    q = f.get("quotas")
    if q is not None:
        add("")
        add("7. QUOTAS")
        add("  %d rows; %d with a non-zero value; placed differs from the number of present slots in %d row(s); minimum above maximum in %d row(s)"
            % (q["rows"], q["nonzero_rows"], q["placed_differs_from_slot_count"], q["min_above_max"]))
        rows = [["folder", "min", "max", "placed", "slots"]]
        for r in q["listed"][:MAX_LISTED * 2]:
            rows.append([r["folder"], r["minimum"], r["maximum"], r["placed"], r["present_slots"]])
        add(_tab(rows))
        if len(q["listed"]) > MAX_LISTED * 2:
            add("    ... %d more rows" % (len(q["listed"]) - MAX_LISTED * 2))
        if q["slots_in_folder_without_row"]:
            add("  folders used by slots but without a quota row: %s" % q["slots_in_folder_without_row"])
        if q["headroom_rows"]:
            add("  rows with room to add objects (maximum above placed): %s" % ", ".join(
                "%d %s (max %d, placed %d)" % (r["folder"], r["name"], r["maximum"], r["placed"]) for r in q["headroom_rows"][:MAX_LISTED]))
        else:
            add("  rows with room to add objects (maximum above placed): none")
        if q["block_rows"]:
            add("  Block folders (quota rows): %s" % ", ".join(
                "%d %s (%d, %d, %d)" % (r["folder"], r["name"], r["minimum"], r["maximum"], r["placed"]) for r in q["block_rows"]))
    t = f.get("tail")
    if t is not None:
        add("")
        add("8. TAIL AND PADDING")
        add("  stream ends at bit %d (ceil %d bytes; stored length %d, class %s); free %d of %d bits"
            % (t["end_bit"], t["ceil_end_bytes"], t["stored_length"], t["length_class"], t["free_bits"], t["capacity_bits"]))
        add("  tail %d bits, all zero: %s; pad bits %d, zero: %s" % (t["tail_bits"], _yn(t["tail_all_zero"]), t["pad_bits"], _yn(t["pad_bits_zero"])))
    sc = f.get("selfchecks")
    if sc is not None:
        add("")
        add("9. SELF-CHECKS")
        for item in sc:
            mark = "ok  " if item["ok"] else ("info" if item["ok"] is None else "FAIL")
            add("  [%s] %s" % (mark, item["detail"]))
    add("")
    res = f.get("result", {})
    add("RESULT: %s%s" % (res.get("status", "?"), " - " + res["message"] if res.get("message") else ""))
    return "\n".join(out)


def report_json(report: Report) -> str:
    """The facts as pretty JSON text (sorted keys, stable output)."""
    return json.dumps(report.facts, indent=1, sort_keys=True, default=str)


def write_output_file(target, text, source_paths=(), repo_root=None):
    """Write a tool's output file through ``mvarlib.io.write_atomic`` and refuse anything inside the repo tree.

    ``PathPolicyError`` if ``target`` resolves inside ``repo_root`` (derived map data must not be committed,
    DEC-6.1), is the same file as a source, or lies in a protected folder.
    """
    from . import io as mio
    if repo_root:
        real = os.path.realpath(os.path.expanduser(target))
        root = os.path.realpath(repo_root)
        if real == root or real.startswith(root + os.sep):
            raise PathPolicyError("Refusing to write %s: it is inside the repository working tree (%s); derived map data must "
                                  "not be kept there." % (target, root))
    mio.write_atomic(target, text.encode("utf-8"), source_paths)
