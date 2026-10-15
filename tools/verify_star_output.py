#!/usr/bin/env python3
"""Independent check of a finished block-star file against the map variant it was built from (S1, NOTES.md D10 / D11).

    python3 -I tools/verify_star_output.py TEMPLATE.mvar OUTPUT.mvar [--block "Block, 1x1"] [--shape pixel39 --center X,Y,Z]
                                           [--footprint W,D,H] [--preview] [--json]

Both files are only opened for reading. The star tool (``tools/build_star_mvar.py``) already checks its own output; this
command repeats the checks that matter from the other side, so that "the star file is right" does not rest on the
code that wrote it. It uses the independent walker of the fixture builder (``tests/blender/real_data.py``, which does
not import ``mvarlib``) for everything about bits, spans, quota rows and the hash, plain ``hashlib``, and the library's
reader only for names and world positions. Every line is ``[PASS]``, ``[FAIL]`` or ``[INFO]``; the exit status is 0 only
when no line failed (2 for a usage or I/O problem):

* the file has the template's length; the 29,911 bytes after ``_eof`` (or however many the template has) are identical;
  every byte outside the SHA-1, the stored length and the bit stream is identical;
* the SHA-1 is ``SHA1(LE32(L) || stream[:L])`` (the flavour of the template, found by the walker) and the length is stored
  in the template's byte order;
* header, fixed body and labels decode identically; every slot of the template decodes identically AND occupies exactly
  the same stream bits as before (the original slots are bit-identical);
* the new slots are N blocks of the given type, Fixed (placement byte 0x4C), neutral team, no colour, class 0, in bounds,
  a quarter-turn yaw, vertical, inside ``[min, max)`` of every axis; the objects total at most 650;
* only the block's quota row changed, from ``(min, max, placed)`` to ``(min, max', placed + N)`` with ``max' = max(max,
  placed + N)``; the bits that differ in the stream are only the new records, the freed absent bits and that row;
* with ``--shape`` and ``--center``: the decoded positions are the star of that design, centred there, within the
  quantisation step (the decoded positions, not the positions Blender held).

``--preview`` prints the ASCII picture of the decoded blocks (front view, top is up); ``--json`` prints the decoded
positions as JSON (for the Blender render of the preview image) and nothing else.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
import struct
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import star_layout as sl  # noqa: E402

MAX_BYTES = 8 << 20
BLOCK_PLACEMENT_FIXED = 0x4C              # 0x0C + physics Fixed (bits 6-7 = 1), the byte of the template's one fixed object
QUOTA_BITS = 24                            # minimum, maximum, placed: 8 bits each
DEFAULT_FOOTPRINT = (1.0182, 1.0182, 1.0)
MAX_OBJECTS = 650


class Check(object):
    def __init__(self, status, name, detail=""):
        self.status, self.name, self.detail = status, name, detail

    def line(self):
        return "[%s] %s%s" % (self.status, self.name, (": " + self.detail) if self.detail else "")


def load_walker():
    """``tests/blender/real_data.py`` by path: the independent decoder, bit-diff helpers and SHA-1 recipe."""
    path = os.path.join(REPO, "tests", "blender", "real_data.py")
    spec = importlib.util.spec_from_file_location("real_data_for_verify_star_output", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_only(path):
    if os.path.getsize(path) > MAX_BYTES:
        raise ValueError("%s is larger than %d bytes" % (path, MAX_BYTES))
    with open(path, "rb") as fh:
        return fh.read()


def library_records(data, name):
    sys.path.insert(0, os.path.join(REPO, "Addon"))
    from mvarlib import entry                                                  # noqa: E402
    return entry.load_map_variant(data, name)


def ascii_preview(positions, footprint, on="#", off="."):
    """Front view of block positions: rows from the top, columns left (-X) to right. ``?`` marks a block that is not on the lattice."""
    if not positions:
        return []
    x0 = min(p[0] for p in positions)
    z0 = min(p[2] for p in positions)
    cells = {}
    odd = []
    for p in positions:
        fx, fz = (p[0] - x0) / footprint.width, (p[2] - z0) / footprint.height
        ix, iz = int(round(fx)), int(round(fz))
        if abs(fx - ix) > 0.1 or abs(fz - iz) > 0.1:
            odd.append((ix, iz))
        cells[(ix, iz)] = True
    nx = max(c[0] for c in cells) + 1
    nz = max(c[1] for c in cells) + 1
    rows = []
    for iz in range(nz - 1, -1, -1):
        rows.append("".join(("?" if (ix, iz) in odd else on) if (ix, iz) in cells else off for ix in range(nx)))
    return rows


def _bits(data):
    return int.from_bytes(data, "big")


def check(template, output, block_name="Block, 1x1", footprint=None, shape=None, centre=None):
    """``(checks, info)``; ``info`` carries the decoded block positions and counts (for the preview and the render)."""
    rd = load_walker()
    footprint = footprint or sl.Footprint(*DEFAULT_FOOTPRINT)
    checks = []
    block_row = -1
    lo = hi = None

    def add(ok, name, detail=""):
        checks.append(Check("PASS" if ok else "FAIL", name, detail))

    def info_line(name, detail):
        checks.append(Check("INFO", name, detail))

    # --- the container, without any decoder ---------------------------------------------------------------------
    add(len(output) == len(template), "file length unchanged", "%d bytes (template %d)" % (len(output), len(template)))
    hash_at, length_at, stream_at, stream_end = rd.HASH_AT, rd.LENGTH_AT, rd.STREAM_AT, rd.STREAM_END
    eof_end = None
    pos = 0
    while pos + 12 <= len(template):                                           # block walk: where does the trailer start
        size = struct.unpack(">I", template[pos + 4:pos + 8])[0]
        sig = template[pos:pos + 4]
        if size < 12 or pos + size > len(template):
            break
        pos += size
        if sig == b"_eof":
            eof_end = pos
            break
    if eof_end is None:
        add(False, "template blocks", "no _eof block found: not a plain map variant")
    else:
        trailer_t, trailer_o = template[eof_end:], output[eof_end:]
        add(trailer_t == trailer_o and len(output) == len(template), "trailer preserved",
            "%d bytes after _eof identical (%s)" % (len(trailer_t), "all zero" if not any(trailer_t) else "not all zero"))
    outside_a = template[:hash_at] + template[hash_at + 20:length_at] + template[length_at + 4:stream_at] + template[stream_end:]
    outside_b = output[:hash_at] + output[hash_at + 20:length_at] + output[length_at + 4:stream_at] + output[stream_end:]
    add(outside_a == outside_b, "every byte outside the SHA-1, the stored length and the bit stream is identical",
        "%d bytes compared" % len(outside_a))
    length_t, length_o = struct.unpack(">I", template[length_at:length_at + 4])[0], struct.unpack(">I", output[length_at:length_at + 4])[0]
    add(1 <= length_o <= 0x7000 and 1 <= length_t <= 0x7000, "stored length is big-endian like the template's",
        "template L=%d, output L=%d" % (length_t, length_o))
    for label, data, length in (("template", template, length_t), ("output", output, length_o)):
        expected = hashlib.sha1(struct.pack("<I", length) + data[stream_at:stream_at + length]).digest()
        add(expected == data[hash_at:hash_at + 20], "SHA-1 of the %s is SHA1(LE32(L) || stream[:L])" % label,
            "plain_le32, L=%d, %s" % (length, expected.hex()))

    # --- the independent walker ---------------------------------------------------------------------------------
    try:
        res_t, res_o = rd.read_result(template), rd.read_result(output)
        dec_t, dec_o = res_t["decoded"], res_o["decoded"]
    except Exception as exc:                                                    # a file the walker refuses
        add(False, "independent walker", "%s: %s" % (type(exc).__name__, exc))
        return checks, {"positions": [], "slots": [], "footprint": footprint, "bounds": None, "lo": None, "hi": None}
    add(res_t["outcome"] == "ok" and res_o["outcome"] == "ok", "independent walker accepts both files",
        "template %s, output %s" % (res_t["outcome"], res_o["outcome"]))
    add(res_t["flavour"] == res_o["flavour"], "hash flavour reproduced", "%s (template) / %s (output)" % (
        res_t["flavour"], res_o["flavour"]))
    add(rd.decode_summary(dec_t) == rd.decode_summary(dec_o), "header, fixed body, labels and GUID block decode identically",
        "map id %s, title and bounds included" % dec_o["header"].get("map_id"))

    old_slots, new_slots = sorted(dec_t["slots"]), sorted(set(dec_o["slots"]) - set(dec_t["slots"]))
    gone = sorted(set(dec_t["slots"]) - set(dec_o["slots"]))
    add(not gone, "no object of the template was removed", "%d removed" % len(gone))
    differing = [s for s in old_slots if s in dec_o["slots"] and dec_o["slots"][s] != dec_t["slots"][s]]
    add(not differing, "every slot of the template decodes identically", "%d of %d slots identical" % (
        len(old_slots) - len(differing), len(old_slots)))
    moved_ranges = [s for s in old_slots if s in dec_o["slot_ranges"] and dec_o["slot_ranges"][s] != dec_t["slot_ranges"][s]]
    add(not moved_ranges, "every slot of the template keeps its place in the bit stream", "%d of %d slot ranges identical" % (
        len(old_slots) - len(moved_ranges), len(old_slots)))
    first_new = min((dec_o["slot_ranges"][s][0] for s in new_slots), default=None)
    bits_t, bits_o = rd.stream_bits(template), rd.stream_bits(output)
    if first_new is None:
        info_line("new slots", "none")
    else:
        add(bits_t[:first_new] == bits_o[:first_new], "the stream is bit-identical up to the first new slot",
            "%d bits (the whole header, body, labels and the %d original slot records)" % (first_new, len(old_slots)))

    # --- the new blocks -----------------------------------------------------------------------------------------
    n = len(new_slots)
    sys.path.insert(0, os.path.join(REPO, "Addon"))
    from mvarlib import tables                                                  # noqa: E402
    map_id = dec_o["header"].get("map_id")
    map_name = tables.map_name_for_id(map_id)
    wanted_id = tables.object_id_for_name(map_name, block_name) if map_name else None
    ids = set((dec_o["slots"][s]["folder"] << 8) | dec_o["slots"][s]["item"] for s in new_slots)
    add(n > 0 and ids == set([wanted_id]), "new slots are %d x '%s'" % (n, block_name),
        "type ids %s (stock id of '%s' on %s: %s)" % (sorted("0x%04X" % i for i in ids), block_name, map_name,
                                                      "0x%04X" % wanted_id if wanted_id is not None else "unknown"))
    add(map_name is not None and tables.is_stock_object(map_name, wanted_id) if wanted_id is not None else False,
        "the block is a stock object of the map's own palette", "%s on %s" % (block_name, map_name))
    fixed = [s for s in new_slots if dec_o["slots"][s]["placement"] != BLOCK_PLACEMENT_FIXED]
    add(not fixed, "all new blocks are Fixed (placement byte 0x%02X)" % BLOCK_PLACEMENT_FIXED, "%d not fixed" % len(fixed))
    odd = [s for s in new_slots if not (dec_o["slots"][s]["team_raw"] == 9 and dec_o["slots"][s]["color"] is None
                                         and dec_o["slots"][s]["cached_type"] == 0 and dec_o["slots"][s]["flags2"] == 1
                                         and dec_o["slots"][s]["in_bounds"] == 1 and dec_o["slots"][s]["label"] is None
                                         and dec_o["slots"][s]["shape"] == 0 and dec_o["slots"][s]["spawn_seq"] == 0
                                         and dec_o["slots"][s]["respawn"] == 0 and dec_o["slots"][s]["parent_raw"] == 0)]
    add(not odd, "new blocks carry the neutral defaults (team neutral, no colour, class 0, no label, no shape, no parent)",
        "%d differ" % len(odd))
    turned = [s for s in new_slots if dec_o["slots"][s]["up_global"] != 1 or dec_o["slots"][s]["angle"] % 4096 != 0]
    add(not turned, "new blocks are vertical with a yaw that is a quarter turn", "yaw codes %s" % sorted(
        set(dec_o["slots"][s]["angle"] for s in new_slots)))
    occupied = len(dec_o["slots"])
    add(occupied <= MAX_OBJECTS and occupied == len(old_slots) + n, "object count within the normal Forge limit",
        "%d objects (template %d + %d new), limit %d" % (occupied, len(old_slots), n, MAX_OBJECTS))

    # --- positions, from the bits ---------------------------------------------------------------------------------
    bounds = dec_o["body"]["bounds"]
    axis_bits = res_o["hypothesis"]["axis_bits"]
    positions = []
    for s in new_slots:
        cells = dec_o["slots"][s]["pos"]
        positions.append(tuple(rd_pos(cells[a], axis_bits[a], bounds[2 * a], bounds[2 * a + 1]) for a in range(3)))
    inside = all(bounds[2 * a] <= p[a] < bounds[2 * a + 1] for p in positions for a in range(3))
    add(inside, "all block positions lie inside the map bounds", "bounds %s" % (bounds,))
    # the template's objects, from the library, for the distance numbers in the report
    if positions:
        lo = tuple(min(p[a] for p in positions) - (footprint.width, footprint.depth, footprint.height)[a] / 2.0 for a in range(3))
        hi = tuple(max(p[a] for p in positions) + (footprint.width, footprint.depth, footprint.height)[a] / 2.0 for a in range(3))
        info_line("star box", "x %.3f to %.3f, y %.3f to %.3f, z %.3f to %.3f (%.3f x %.3f x %.3f)" % (
            lo[0], hi[0], lo[1], hi[1], lo[2], hi[2], hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]))
        step = max((bounds[2 * a + 1] - bounds[2 * a]) / float(1 << axis_bits[a]) for a in range(3))
        overlaps, deepest = _overlaps(positions, footprint, 2.0 * step)
        add(overlaps == 0, "no two star blocks overlap (beyond the position step)",
            "%d pair(s) overlap by more than two position steps (%.5f); the deepest overlap of any pair is %.5f, "
            "a rounding of the file's own position step %.5f" % (overlaps, 2.0 * step, deepest, step))
        if shape and centre:
            cells_wanted = sl.named_shape(shape)
            wanted = sl.cell_positions(cells_wanted, footprint, centre)
            cell = max((bounds[2 * a + 1] - bounds[2 * a]) / float(1 << axis_bits[a]) for a in range(3))
            tol = 2.0 * cell + 1.0e-3
            match = sl.match_positions(wanted, positions, tol)
            add(match.ok, "the decoded blocks are the star '%s' centred at (%.3f, %.3f, %.3f)" % ((shape,) + tuple(centre)),
                "%d of %d matched within %.4f; largest error %.5f, %.5f, %.5f (one position step is %.5f)" % (
                    len(match.pairs), len(wanted), tol, match.worst[0], match.worst[1], match.worst[2], cell))

    # --- the quota rows and the rest of the stream ------------------------------------------------------------------
    q_t, q_o = dec_t["quotas"], dec_o["quotas"]
    rows = [i for i in range(len(q_t)) if q_t[i] != q_o[i]]
    if n:
        block_row = wanted_id >> 8 if wanted_id is not None else -1
        expect = [q_t[block_row][0], max(q_t[block_row][1], q_t[block_row][2] + n), q_t[block_row][2] + n] if block_row >= 0 else None
        add(rows == [block_row] and q_o[block_row] == expect, "only the block's quota row changed",
            "row %d: %s -> %s (maximum raised from %d to %d: UNVERIFIED in game, option D11)" % (
                block_row, q_t[block_row], q_o[block_row], q_t[block_row][1], q_o[block_row][1]))
    else:
        add(not rows, "no quota row changed", "%d rows changed" % len(rows))
    sections_t, sections_o = dec_t["sections"], dec_o["sections"]
    qs_t, qs_o = sections_t["quotas"], sections_o["quotas"]
    qlen = QUOTA_BITS * len(q_t)
    quotas_same_except_row = True
    if n and block_row >= 0:
        for i in range(len(q_t)):
            if i == block_row:
                continue
            a = bits_t[qs_t + i * QUOTA_BITS:qs_t + (i + 1) * QUOTA_BITS]
            b = bits_o[qs_o + i * QUOTA_BITS:qs_o + (i + 1) * QUOTA_BITS]
            if a != b:
                quotas_same_except_row = False
        row_t = bits_t[qs_t + block_row * QUOTA_BITS:qs_t + (block_row + 1) * QUOTA_BITS]
        row_o = bits_o[qs_o + block_row * QUOTA_BITS:qs_o + (block_row + 1) * QUOTA_BITS]
        add(quotas_same_except_row and row_t[:8] == row_o[:8], "the other %d quota rows and the block row's minimum are bit-identical" % (
            len(q_t) - 1), "%d quota bits compared" % qlen)
    add(not dec_o["tail_nonzero"] and not dec_t["tail_nonzero"], "all bits after the quota table are zero in both files",
        "stream ends at bit %d (template %d)" % (sections_o["end"], sections_t["end"]))
    tail_t = bits_t[sections_t["end"]:]
    tail_o = bits_o[sections_o["end"]:]
    add(not any(c == "1" for c in tail_t) and not any(c == "1" for c in tail_o), "the unused bits of the 229,376-bit stream are zero",
        "%d / %d tail bits" % (len(tail_t), len(tail_o)))
    return checks, {"positions": positions, "slots": new_slots, "footprint": footprint, "bounds": bounds,
                    "lo": lo, "hi": hi}


def rd_pos(q, nbits, mn, mx):
    """Decoded world value of a position cell (SPEC 4.1: the centre of the cell)."""
    return (q + 0.5) * ((mx - mn) / float(1 << nbits)) + mn


def _overlaps(positions, footprint, tol):
    """``(pairs overlapping by more than tol, deepest overlap of any pair)``.

    Two blocks overlap when their centres are closer than one block size on every axis; the depth is the smallest
    of those three margins. Decoded positions are rounded to the file's position step, so touching neighbours show a
    depth of up to one step; only a depth beyond ``tol`` counts.
    """
    size = (footprint.width, footprint.depth, footprint.height)
    count = 0
    deepest = 0.0
    for i in range(len(positions)):
        for j in range(i + 1, len(positions)):
            margins = [size[a] - abs(positions[i][a] - positions[j][a]) for a in range(3)]
            if all(m > 0 for m in margins):
                depth = min(margins)
                deepest = max(deepest, depth)
                if depth > tol:
                    count += 1
    return count, deepest


def parse_centre(text):
    parts = [p.strip() for p in str(text).split(",")]
    if len(parts) != 3:
        raise ValueError("--center needs three comma-separated numbers")
    return tuple(float(p) for p in parts)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="verify_star_output", description="Independent check of a block-star map variant (S1).")
    ap.add_argument("template", metavar="TEMPLATE.mvar")
    ap.add_argument("output", metavar="OUTPUT.mvar")
    ap.add_argument("--block", default="Block, 1x1")
    ap.add_argument("--shape", choices=sl.shape_names(), default=None)
    ap.add_argument("--center", default=None, metavar="X,Y,Z")
    ap.add_argument("--footprint", default=",".join("%g" % v for v in DEFAULT_FOOTPRINT), metavar="W,D,H")
    ap.add_argument("--preview", action="store_true", help="also print the ASCII picture of the decoded blocks")
    ap.add_argument("--json", action="store_true", help="print only the decoded block positions as JSON")
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code not in (0, None) else 0
    try:
        parts = [float(p) for p in args.footprint.split(",")]
        if len(parts) != 3:
            raise ValueError("--footprint needs three comma-separated numbers")
        footprint = sl.Footprint(*parts)
        centre = parse_centre(args.center) if args.center else None
        if bool(args.shape) != bool(centre):
            raise ValueError("--shape and --center go together")
        template, output = read_only(args.template), read_only(args.output)
    except (ValueError, OSError, sl.LayoutError) as exc:
        print("verify_star_output: %s" % exc)
        return 2
    checks, info = check(template, output, args.block, footprint, args.shape, centre)
    if args.json:
        print(json.dumps({"block": args.block, "footprint": [footprint.width, footprint.depth, footprint.height],
                          "slots": info["slots"], "positions": [list(p) for p in info["positions"]],
                          "bounds": list(info.get("bounds") or [])}, indent=1))
        return 0 if not any(c.status == "FAIL" for c in checks) else 1
    print("template : %s (%d bytes, sha256 %s)" % (args.template, len(template), hashlib.sha256(template).hexdigest()))
    print("output   : %s (%d bytes, sha256 %s)" % (args.output, len(output), hashlib.sha256(output).hexdigest()))
    for c in checks:
        print(c.line())
    if args.preview and info["positions"]:
        print("")
        print("front view of the decoded blocks (top is up, left is -X; one '#' per block):")
        for row in ascii_preview(info["positions"], footprint):
            print("  " + row)
    failed = [c for c in checks if c.status == "FAIL"]
    print("")
    print("RESULT: %s" % ("OK (%d checks passed)" % len([c for c in checks if c.status == "PASS"]) if not failed
                          else "FAILED (%d of %d checks failed)" % (len(failed), len([c for c in checks if c.status != "INFO"]))))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
