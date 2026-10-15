#!/usr/bin/env python3
"""Print or save the plain (JSON) form of a map variant, its slots or its bit spans (SPEC 6.6, 6.7).

    python3 -I tools/dump_mvar.py FILE [--plain OUT.json] [--slots] [--spans]

  (no option)       print the plain form as JSON on standard output
  --plain OUT.json  save the plain form instead (through ``mvarlib.io.write_atomic``; refused when OUT lies inside
                    the repository working tree, in a protected folder, or is the input file: derived map data must
                    not be committed, DEC-6.1)
  --slots           print one line per occupied slot
  --spans           print the bit span of every part of the stream (header, body fields, labels, GUID, slots, quota
                    rows, tail), with the fields of each occupied slot

The input is only opened for reading. Exit status: 0 ok; 1 the body does not decode; 2 usage or I/O trouble or
the file is not a map variant.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "Addon"))

from mvarlib import io as mio  # noqa: E402
from mvarlib import plain  # noqa: E402
from mvarlib import report as rep  # noqa: E402
from mvarlib.errors import (AmbiguousLayoutError, BlfFormatError, DesyncError, FormatError, MvarError,  # noqa: E402
                            OutOfBoundsPositionError, PathPolicyError)
from mvarlib.model import MapVariant  # noqa: E402

MAX_BYTES = 8 << 20


def slot_lines(model):
    lines = ["slot  folder item  type                              cached place flags2 team color  pos (raw cells)"]
    for rec in model.objects():
        s = model.slots[rec.slot]
        lines.append("%4d  %6s %4s  %-32s  %6d 0x%02X  %6d %4d %5s  %s"
                     % (s.index, s.folder, s.item, rec.type_name[:32], s.cached_type, s.placement, s.flags2, s.team_raw,
                        s.color, s.pos))
    return lines


def span_lines(model):
    lines = ["%-28s %8s %8s %6s" % ("part", "start", "end", "bits")]
    for name, a, b in model.spans(fields=True):
        lines.append("%-28s %8d %8d %6d" % (name, a, b, b - a))
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dump_mvar", description="Print or save the plain form of a Halo: Reach map variant.")
    ap.add_argument("file", metavar="FILE")
    ap.add_argument("--plain", metavar="OUT", help="save the plain JSON form (refused inside the repository tree)")
    ap.add_argument("--slots", action="store_true", help="print one line per occupied slot")
    ap.add_argument("--spans", action="store_true", help="print the bit span of every part of the stream")
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code not in (0, None) else 0
    try:
        data = mio.read_file(args.file, MAX_BYTES)
    except (OSError, MvarError) as exc:
        print("dump_mvar: cannot read %s: %s" % (args.file, exc), file=sys.stderr)
        return 2
    try:
        model = MapVariant.from_bytes(data, None, os.path.basename(args.file))
    except (DesyncError, AmbiguousLayoutError, OutOfBoundsPositionError) as exc:
        print("dump_mvar: %s" % exc, file=sys.stderr)
        return 1
    except FormatError as exc:
        print("dump_mvar: %s" % exc, file=sys.stderr)
        return 2 if isinstance(exc, BlfFormatError) or "game variant" in str(exc) or "No map variant" in str(exc) else 1
    except MvarError as exc:
        print("dump_mvar: %s" % exc, file=sys.stderr)
        return 1
    printed = False
    if args.slots:
        print("\n".join(slot_lines(model)))
        printed = True
    if args.spans:
        print("\n".join(span_lines(model)))
        printed = True
    if args.plain:
        text = json.dumps(plain.to_plain(model), indent=1, sort_keys=True) + "\n"
        try:
            rep.write_output_file(args.plain, text, source_paths=[args.file], repo_root=REPO)
        except (OSError, PathPolicyError) as exc:
            print("dump_mvar: %s" % exc, file=sys.stderr)
            return 2
        print("wrote %s" % args.plain)
    elif not printed:
        print(json.dumps(plain.to_plain(model), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
