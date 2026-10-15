#!/usr/bin/env python3
"""Write a re-encoded copy of a map variant, or a hash PROBE file (SPEC 6.7, 9.5 rung H).

    python3 -I tools/reencode_mvar.py IN OUT [--force] [--hash-recipe NAME] [--zero-hash] [--corrupt-hash]

  (no option)        the passthrough copy: OUT holds exactly the bytes of IN (a pipeline control)
  --force            the forced re-encode: every slot is re-packed, every length and the hash are recomputed. For the
                     plain shapes (``plain4``, ``plain4+fsm``) the result must equal IN byte for byte; that is the
                     self-test. If it does not, nothing is written and the first differing byte is reported (exit 3).
                     For a ``_cmp`` input the expanded plain form is written (nothing to compare)
  --hash-recipe NAME rewrite the SHA-1 with another recipe (plain_le32, salted_be32, salted_le32, plain_be32,
                     data_only); everything else is the forced re-encode
  --zero-hash        write 20 zero bytes as the SHA-1 (the all-zero class)
  --corrupt-hash     keep every byte of IN except that the SHA-1 is deliberately wrong (the first byte is inverted,
                     so it matches no recipe); the probe of ladder rung H: if MCC still loads it, the hash is not checked

The probe files let the owner find out, with one MCC load each, whether the game checks the SHA-1 at all and which
recipe it wants. Work on copies; the output always gets a new name.

OUT is written only through ``mvarlib.io.write_atomic`` (temp file, fsync, re-read, ``os.replace``): it is refused when it
resolves to IN (also through a symlink or a hard link), lies in a protected folder (the sample folders), or lies inside
this repository's working tree (derived map data must not be committed, DEC-6.1). IN is only opened for reading.

Exit status: 0 written; 1 IN is a map variant that does not decode; 2 usage, I/O, a refused path, or IN is not a map
variant; 3 the self-test failed (nothing written).
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "Addon"))

from mvarlib import hashing  # noqa: E402
from mvarlib import io as mio  # noqa: E402
from mvarlib.errors import (AmbiguousLayoutError, BlfFormatError, DesyncError, FormatError, MvarError,  # noqa: E402
                            OutOfBoundsPositionError, PathPolicyError)
from mvarlib.model import MapVariant  # noqa: E402

MAX_BYTES = 8 << 20
EXIT_OK, EXIT_DECODE, EXIT_USAGE, EXIT_SELFTEST = 0, 1, 2, 3


def inside_repo(path):
    real = os.path.realpath(os.path.expanduser(os.fspath(path)))
    root = os.path.realpath(REPO)
    return real == root or real.startswith(root + os.sep)


def first_difference(a, b):
    """Index of the first differing byte of two byte strings (the shorter one's length when one is a prefix), or -1."""
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            return i
    return -1 if len(a) == len(b) else min(len(a), len(b))


def corrupt_hash(model, data):
    """``data`` with the stored SHA-1 deliberately wrong: the first hash byte inverted (everything else untouched)."""
    spec = model.chunk.spec
    offset = model.chunk.offset + spec.hash_off
    out = bytearray(data)
    out[offset] ^= 0xFF
    return bytes(out)


def build_output(model, data, args):
    """``(output bytes, description)`` for the requested mode; ``None`` bytes when the self-test fails."""
    endian = model.chunk.length_endian or ">"
    if args.corrupt_hash:
        base = model.to_bytes(force=model.chunk.cmp is not None)         # a _cmp input is expanded first: the plain form has a hash field
        return corrupt_hash(model, base), "the input with a deliberately corrupted SHA-1"
    if args.zero_hash:
        return model.to_bytes(force=True, flavour=hashing.HashFlavour(endian, hashing.ZERO)), "forced re-encode with an all-zero SHA-1"
    if args.hash_recipe:
        return (model.to_bytes(force=True, flavour=hashing.HashFlavour(endian, args.hash_recipe)),
                "forced re-encode with the SHA-1 recipe %s (length byte order %s)" % (args.hash_recipe, "big" if endian == ">" else "little"))
    if args.force:
        out = model.to_bytes(force=True)
        return out, "forced re-encode"
    return model.to_bytes(force=False), "passthrough copy"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="reencode_mvar", description="Write a re-encoded copy of a map variant or a hash probe file.")
    ap.add_argument("input", metavar="IN")
    ap.add_argument("output", metavar="OUT")
    ap.add_argument("--force", action="store_true", help="forced re-encode (must equal IN for the plain shapes)")
    ap.add_argument("--hash-recipe", metavar="NAME", choices=hashing.RECIPES, help="recompute the SHA-1 with this recipe")
    ap.add_argument("--zero-hash", action="store_true", help="write 20 zero bytes as the SHA-1")
    ap.add_argument("--corrupt-hash", action="store_true", help="write a deliberately wrong SHA-1")
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return EXIT_USAGE if exc.code not in (0, None) else EXIT_OK
    chosen = [bool(args.hash_recipe), args.zero_hash, args.corrupt_hash]
    if sum(chosen) > 1:
        print("reencode_mvar: choose at most one of --hash-recipe, --zero-hash and --corrupt-hash", file=sys.stderr)
        return EXIT_USAGE
    if inside_repo(args.output):
        print("reencode_mvar: Refusing to write %s: it is inside the repository working tree (%s); derived map data must "
              "not be kept there." % (args.output, os.path.realpath(REPO)), file=sys.stderr)
        return EXIT_USAGE
    issue = mio.check_output_path(args.output, [args.input])
    if issue is not None:
        print("reencode_mvar: %s" % issue.message, file=sys.stderr)
        return EXIT_USAGE
    try:
        data = mio.read_file(args.input, MAX_BYTES)
    except (OSError, MvarError) as exc:
        print("reencode_mvar: cannot read %s: %s" % (args.input, exc), file=sys.stderr)
        return EXIT_USAGE
    try:
        model = MapVariant.from_bytes(data, None, os.path.basename(args.input))
    except (DesyncError, AmbiguousLayoutError, OutOfBoundsPositionError) as exc:
        print("reencode_mvar: %s" % exc, file=sys.stderr)
        return EXIT_DECODE
    except FormatError as exc:
        print("reencode_mvar: %s" % exc, file=sys.stderr)
        return EXIT_USAGE if isinstance(exc, BlfFormatError) or "game variant" in str(exc) or "No map variant" in str(exc) else EXIT_DECODE
    except MvarError as exc:
        print("reencode_mvar: %s" % exc, file=sys.stderr)
        return EXIT_DECODE
    try:
        out, what = build_output(model, data, args)
    except MvarError as exc:
        print("reencode_mvar: %s" % exc, file=sys.stderr)
        return EXIT_DECODE
    if args.force and not (args.hash_recipe or args.zero_hash or args.corrupt_hash) and model.shape in ("plain4", "plain4+fsm"):
        if out != data:
            at = first_difference(data, out)
            stream_start = model.chunk.offset + model.chunk.spec.stream_off
            where = ("stream part %s" % model.locate_bit((at - stream_start) * 8)) if at >= stream_start else "the container"
            print("reencode_mvar: SELF-TEST FAILED: the forced re-encode differs from the input (first difference at byte %d, "
                  "%s); nothing was written." % (at, where), file=sys.stderr)
            return EXIT_SELFTEST
    try:
        MapVariant.from_bytes(out)                                   # whatever is written must itself decode
    except MvarError as exc:
        print("reencode_mvar: the output would not decode (%s); nothing was written." % exc, file=sys.stderr)
        return EXIT_SELFTEST

    def verify(written):
        MapVariant.from_bytes(written)

    try:
        mio.write_atomic(args.output, out, [args.input], None, verify=verify)
    except (OSError, PathPolicyError) as exc:
        print("reencode_mvar: %s" % exc, file=sys.stderr)
        return EXIT_USAGE
    print("wrote %s (%d bytes): %s; input %d bytes, %s" % (args.output, len(out), what, len(data),
                                                           "identical" if out == data else "differs from the input"))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
