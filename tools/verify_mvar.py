#!/usr/bin/env python3
"""T3 tool (SPEC 6.7, 9.1): decode a real Halo: Reach map variant and print a readable report.

    python3 -I tools/verify_mvar.py FILE [FILE ...] [--json OUT.json] [--no-strings] [--lenient]

The file is only ever opened for reading. The report has the nine sections of SPEC 6.7: container, hash
candidates and stored length, header, body (bounds, axis bits, budget words, labels), the hypothesis table of
the walk (type 19 rule x axis bits x GUID block) with the first failure of every rejected hypothesis, slots
(histograms, unresolved object ids, placement bytes, parent links, orientation statistics), quota rows, tail and
padding, and the self-checks (slot repack identity, label re-encode, unmodified and forced round trip, plain
round trip). Nothing from the file is written anywhere except with ``--json OUT.json``, which goes through
``mvarlib.io.write_atomic`` and is refused inside the repository tree.

Options
  --json OUT      also write the facts as JSON (one file: its facts; several files: {"files": [...]})
  --no-strings    omit titles, descriptions, author names and label texts from the text and the JSON
  --lenient       switch off the two unsourced plausibility checks (folder below the quota count; label entry
                  present) in the hypothesis table, to see whether one of them is what rejects a real file.
                  The library never imports or exports from such a parse.

Exit status: 0 all good; 1 the body does not decode (desync, ambiguous layout, out-of-bounds record, format
error); 2 usage or I/O trouble, or the file is not a map variant (a game variant still gets its container
report); 3 the body decoded but a self-check failed. With several files the largest status wins. Every
non-zero exit ends with one line ``VERIFY FAILED: <reason>``.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "Addon"))

from mvarlib import io as mio  # noqa: E402
from mvarlib import report as rep  # noqa: E402
from mvarlib.api import ReadOptions  # noqa: E402
from mvarlib.errors import MvarError  # noqa: E402

MAX_BYTES = 8 << 20


def main(argv=None):
    ap = argparse.ArgumentParser(prog="verify_mvar", description="Decode report for a Halo: Reach map variant (SPEC 6.7).")
    ap.add_argument("files", nargs="+", metavar="FILE")
    ap.add_argument("--json", metavar="OUT", help="also write the facts as JSON (refused inside the repository tree)")
    ap.add_argument("--no-strings", action="store_true", help="omit titles, descriptions, author names and label texts")
    ap.add_argument("--lenient", action="store_true", help="show the walk with the two unsourced plausibility checks off")
    ap.add_argument("--force-selfcheck-failure", metavar="NAME", help=argparse.SUPPRESS)      # testing hook: makes one self-check fail
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code not in (0, None) else 0
    worst = 0
    worst_reason = None
    all_facts = []
    options = ReadOptions(strict=not args.lenient)
    for path in args.files:
        try:
            data = mio.read_file(path, MAX_BYTES)
        except (OSError, MvarError) as exc:
            print("verify_mvar: cannot read %s: %s" % (path, exc))
            code, reason = 2, "cannot read %s: %s" % (path, exc)
        else:
            report = rep.build_report(data, options, name=os.path.basename(path), include_strings=not args.no_strings,
                                      lenient=args.lenient, inject_failure=args.force_selfcheck_failure)
            print(rep.format_report(report))
            print("")
            all_facts.append(report.facts)
            code, reason = report.exit_code, report.failure
        if code > worst:
            worst, worst_reason = code, reason
    if args.json:
        payload = all_facts[0] if len(all_facts) == 1 else {"files": all_facts}
        try:
            rep.write_output_file(args.json, json.dumps(payload, indent=1, sort_keys=True, default=str) + "\n",
                                  source_paths=args.files, repo_root=REPO)
            print("wrote %s" % args.json)
        except (OSError, MvarError) as exc:
            print("verify_mvar: cannot write %s: %s" % (args.json, exc))
            if worst < 2:
                worst, worst_reason = 2, "cannot write %s: %s" % (args.json, exc)
    if worst:
        print("VERIFY FAILED: %s" % worst_reason)
    return worst


if __name__ == "__main__":
    sys.exit(main())
