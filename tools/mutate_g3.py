#!/usr/bin/env python3
"""Mutation check of the G3 tests (proof that U-05, U-07 to U-10, U-14, U-16 and T3-real bite).

    python3 -I tools/mutate_g3.py [--python PATH] [--list] [NAME_SUBSTRING ...]

Copies ``Addon/mvarlib``, the tools, the fixture builder, the golden data and the G3 tests into a fresh temporary
directory (never inside the repository), then applies ONE source mutation at a time (a changed field width, a
wrong rounding, a dropped hard check, a swapped hypothesis order, a lost re-stamp ...), runs the G3 tests against
the mutated copy with ``tools/run_tests.py --samples`` and reports whether the tests KILLED the mutant (a test
failed) or it SURVIVED. The real sources and the sample files (including the real map variant) are only read.
Exit status: 0 when every mutant that is not marked equivalent was killed, 1 otherwise, 2 when the unmutated
baseline is not green.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CORE = ["test_codecs_golden", "test_fixtures_read", "test_roundtrip_forced", "test_hypotheses", "test_container_variants",
        "test_plain", "test_real_mvar"]
CODEC = ["test_codecs_golden", "test_fixtures_read", "test_real_mvar"]
CLI = ["test_cli"]
G3_TESTS = ("helpers_snapshot.py", "helpers_real.py", "helpers_fixtures.py", "helpers_g3.py", "helpers_container.py",
            "test_codecs_golden.py", "test_fixtures_read.py", "test_roundtrip_forced.py", "test_hypotheses.py",
            "test_container_variants.py", "test_plain.py", "test_real_mvar.py", "test_cli.py", "test_oracle_js.py")

# Mutants that cannot change any observable result (reason next to each).
EQUIVALENT = (
    # invariant I1 makes a clean slot's raw bits and its re-packed bits identical (asserted for all 651 slots at parse time and
    # tested in TestSlotRepack), so copying raw bits in a forced rebuild changes no output byte; the forced path's job
    # (re-stamping lengths, L, hash, _eof) is exercised separately
    "model: forced rebuild copies clean slots",
    # the second range computation (float32 of the difference) never produces a triple the first one lacks on any fixture
    # or on the real file, so dropping it changes nothing observable here; it stays because the spec lists it (4.1)
    "codecs: axis hypotheses without the float32 range computation",
)

# (name, file relative to Addon/mvarlib, old text (must occur exactly once), new text, --only substrings)
MUTANTS = [
    # --- codecs ------------------------------------------------------------------------------
    ("codecs: position decode without the half cell", "codecs.py", "    return (q + 0.5) * pos_cell(bits, mn, mx) + mn",
     "    return q * pos_cell(bits, mn, mx) + mn", CODEC),
    ("codecs: position encode rounds instead of floors", "codecs.py", "int(math.floor((v - mn) / cell))",
     "int(round((v - mn) / cell))", CODEC),
    ("codecs: position encode clamps instead of refusing", "codecs.py", "    if not (v == v and mn <= v < mx):\n        raise EncodeError(\"The position %r is outside the map bounds [%r, %r).\" % (v, mn, mx))\n",
     "    v = min(max(v, mn), mx - 1e-9)\n", CODEC),
    ("codecs: shape dimension first step", "codecs.py", "return (v - 1) * 0.0977517142892 + 0.0488758571446",
     "return (v - 1) * 0.0977517142892 + 0.0488", CODEC),
    ("codecs: shape dimension encode off by one", "codecs.py", "x * 2046.0 / 200.0 + 1.0", "x * 2046.0 / 200.0 + 0.0", CODEC),
    ("codecs: angle decode without the half step", "codecs.py", "return (raw + 0.5) * ANGLE_STEP - math.pi",
     "return raw * ANGLE_STEP - math.pi", CODEC),
    ("codecs: up code uses 417 as the cell divisor", "codecs.py", "cu = (2 * u + 1) / 416.0 - 1.0", "cu = (2 * u + 1) / 417.0 - 1.0", CODEC),
    ("codecs: up code stride", "codecs.py", "UP_STRIDE = 174762 ", "UP_STRIDE = 174763 ", CODEC),
    ("codecs: up face 3 sign", "codecs.py", "        vec = (-1.0, cu, cv)", "        vec = (1.0, cu, cv)", CODEC),
    ("codecs: trunc9999 fudge", "codecs.py", "TRUNC_FUDGE = 0.9999", "TRUNC_FUDGE = 0.5", CODEC),
    ("codecs: axis bits ceil becomes floor", "codecs.py", "    return max(0, int(math.ceil(x)))", "    return max(0, int(math.floor(x)))", CODEC),
    ("codecs: axis hypotheses without the float32 range computation", "codecs.py", "    for ranges in (doubles, singles):",
     "    for ranges in (doubles,):", CODEC),
    ("codecs: symmetry bits swapped", "codecs.py", "PlacementView((byte >> 6) & 3, (byte >> 2) & 3,",
     "PlacementView((byte >> 6) & 3, ((byte >> 3) & 1) | (((byte >> 2) & 1) << 1),", CODEC),
    ("codecs: place_at_start polarity", "codecs.py", "not (byte & 0x10), bool(byte & 0x20))", "bool(byte & 0x10), bool(byte & 0x20))", CODEC),
    ("codecs: team view", "codecs.py", "    return raw - 1\n\n\ndef team_raw", "    return raw\n\n\ndef team_raw", CODEC),
    ("codecs: vertical orientation forward", "codecs.py", "return (ct, st, 0.0), (0.0, 0.0, 1.0)", "return (st, ct, 0.0), (0.0, 0.0, 1.0)", CODEC),
    # --- labels ------------------------------------------------------------------------------
    ("labels: offset width", "labels.py", "OFFSET_BITS = 12", "OFFSET_BITS = 11", CORE),
    ("labels: compressed size width", "labels.py", "COMP_SIZE_BITS = 13", "COMP_SIZE_BITS = 12", CORE),
    ("labels: count limit", "labels.py", "    if count > MAX_COUNT:\n        raise LabelError(\"The label table claims", "    if count > MAX_COUNT + 1:\n        raise LabelError(\"The label table claims", CORE),
    ("labels: text runs to the buffer end instead of the NUL", "labels.py", "        end = self.buffer.find(b\"\\x00\", offset)\n        if end < 0:\n            end = len(self.buffer)",
     "        end = len(self.buffer)", CORE),
    ("labels: compressed prefix skipped wrongly", "labels.py", "out = inflater.decompress(blob[4:], _MAX_INFLATED + 1)", "out = inflater.decompress(blob[3:], _MAX_INFLATED + 1)", CORE),
    # --- slot --------------------------------------------------------------------------------
    ("slot: flags2 width", "slot.py", "    s.flags2 = r.read(2)", "    s.flags2 = r.read(3)", CORE),
    ("slot: parent width", "slot.py", "    s.parent_raw = r.read(10)", "    s.parent_raw = r.read(9)", CORE),
    ("slot: parent limit", "slot.py", "PARENT_RAW_MAX = 651", "PARENT_RAW_MAX = 650", CORE),
    ("slot: spawn sequence unsigned", "slot.py", "    s.spawn_seq = r.read_signed(8)", "    s.spawn_seq = r.read(8)", CORE),
    ("slot: shape 2 has two dimensions", "slot.py", "SHAPE_DIM_COUNT = {0: 0, 1: 1, 2: 3, 3: 4}", "SHAPE_DIM_COUNT = {0: 0, 1: 1, 2: 2, 3: 4}", CORE),
    ("slot: type 19 flag8 stores the wrong none", "slot.py", "s.extra = [1, 0] if flag else [0, r.read(8)]", "s.extra = [0, 0] if flag else [0, r.read(8)]", CORE),
    ("slot: type 19 plain8 width", "slot.py", "            s.extra = [r.read(8)]\n        else:\n            flag = r.read(1)", "            s.extra = [r.read(7)]\n        else:\n            flag = r.read(1)", CORE),
    ("slot: teleporter extras", "slot.py", "    elif 12 <= ct <= 14:\n        s.extra = [r.read(5), r.read(5)]", "    elif 12 <= ct <= 13:\n        s.extra = [r.read(5), r.read(5)]", CORE),
    ("slot: weapon clips width", "slot.py", "    if ct == 1:\n        s.extra = [r.read(8)]", "    if ct == 1:\n        s.extra = [r.read(7)]", CORE),
    ("slot: colour width", "slot.py", "        s.color = r.read(3)", "        s.color = r.read(4)", CORE),
    ("slot: up dead zone threshold", "slot.py", "elif (s.up_code % UP_STRIDE) // UP_N > 416:", "elif (s.up_code % UP_STRIDE) // UP_N > 417:", CORE),
    ("slot: up code face check", "slot.py", "        if s.up_code > UP_CODE_MAX_VALID:", "        if s.up_code > UP_CODE_MAX_VALID + 4:", CORE),
    ("slot: folder check against the quota count", "slot.py", "        if s.folder >= ctx.quota_count and not ctx.lenient:", "        if False:", CORE),
    ("slot: label index check", "slot.py", "        if s.label >= len(ctx.label_present):", "        if s.label > len(ctx.label_present):", CORE),
    ("slot: absent label entry check", "slot.py", "        elif not ctx.label_present[s.label] and not ctx.lenient:", "        elif False:", CORE),
    ("slot: pack bit length of the colour", "slot.py", "        n += 1 if self.color is None else 4\n", "        n += 1 if self.color is None else 3\n", CORE),
    ("slot: field span name", "slot.py", "        add(\"parent\", 10)", "        add(\"parent\", 9)", CORE),
    ("slot: pack writes the team in 4 bits as 5", "slot.py", "        w.write(self.team_raw, 4)", "        w.write(self.team_raw, 5)", CORE),
    # --- walk --------------------------------------------------------------------------------
    ("walk: length class uses floor", "walk.py", "    if L == (end_bit + 7) // 8:", "    if L == end_bit // 8:", CORE),
    ("walk: capacity class removed", "walk.py", "    if L == STREAM_BYTES:\n        return \"capacity\"", "    if False:\n        return \"capacity\"", CORE),
    ("walk: quota count limit", "walk.py", "QUOTA_COUNT_MAX = 256", "QUOTA_COUNT_MAX = 257", CORE),
    ("walk: body versions", "walk.py", "SUPPORTED_BODY_VERSIONS = (31, 32)", "SUPPORTED_BODY_VERSIONS = (31,)", CORE),
    ("walk: GUID value order", "walk.py", "    for guid in (implied, not implied):", "    for guid in (False, True):", CORE),
    ("walk: type 19 preference order", "walk.py", "TYPE19_PREFERENCE = (\"flag8\", \"plain8\")", "TYPE19_PREFERENCE = (\"plain8\", \"flag8\")", CORE),
    ("walk: out-of-bounds needs only one hypothesis", "walk.py", "if len(main) > 0 and len(reasons) == 1 and main[0].reason == \"oob\" and main[0].slot is not None:",
     "if False:", CORE),
    ("walk: ambiguity is ignored", "walk.py", "    if len(distinct) > 1:\n        cands = []", "    if False:\n        cands = []", CORE),
    ("walk: type 19 status is always the first rule", "walk.py", "    result.type19_status = \"undetermined\" if len(rules_equal) > 1 else first.type19",
     "    result.type19_status = first.type19", CORE),
    ("walk: the GUID mismatch flag is lost", "walk.py", "    result.guid_contradicts_version = mismatch", "    result.guid_contradicts_version = False", CORE),
    ("walk: content type is not checked", "walk.py", "    if header.content_type != CONTENT_TYPE_MAP_VARIANT:", "    if False:", CORE),
    ("walk: bounds order is not checked", "walk.py", "or mn > mx:", "or False:", CORE),
    ("walk: the other GUID value is never tried", "walk.py", "        group = accepted_of(not implied)\n        mismatch = bool(group)", "        group = []\n        mismatch = False", CORE),
    ("walk: tail soft check removed", "walk.py", "    if any(stream[tail_first:]):\n        soft[\"tail_nonzero\"] = 1", "    if False:\n        soft[\"tail_nonzero\"] = 1", CORE),
    ("walk: slot start bookkeeping", "walk.py", "            starts.append(r.pos)\n            slots.append(read_slot(r, index, ctx))", "            slots.append(read_slot(r, index, ctx))\n            starts.append(r.pos)", CORE),
    # --- model -------------------------------------------------------------------------------
    ("model: capacity class length", "model.py", "        if self.length_class == \"capacity\":\n            return STREAM_BYTES", "        if self.length_class == \"capacity\":\n            return (end_bit + 7) // 8", CORE),
    ("model: zero class length", "model.py", "        if self.length_class == \"zero\":\n            return 0", "        if self.length_class == \"zero\":\n            return (end_bit + 7) // 8", CORE),
    ("model: the tail is dropped on rebuild", "model.py", "        w.write_bitstring(tail)\n        return w, end", "        return w, end", CORE),
    ("model: parent slot", "model.py", "orientation_kind=\"vertical\" if slot.up_global else \"tilted\", parent_slot=slot.parent_raw - 1,",
     "orientation_kind=\"vertical\" if slot.up_global else \"tilted\", parent_slot=slot.parent_raw,", CORE),
    ("model: quota changes are not dirty", "model.py", "        if [q.as_tuple() for q in self.quotas] != self._quota_baseline:\n            return True\n", "", CORE),
    ("model: edits are not applied", "model.py", "        if stream != chunk.stream or length != self.stream_length:", "        if False:", CORE),
    ("model: forced rebuild copies clean slots", "model.py", "            if not force and s.raw is not None and not s.is_dirty:", "            if s.raw is not None and not s.is_dirty:", CORE),
    ("model: tail shifts wrongly", "model.py", "        room = STREAM_BITS - end\n", "        room = STREAM_BITS - end - 1\n", CORE),
    ("model: objects use the wrong team", "model.py", "game_specific=view.game_specific, team=codecs.team_view(slot.team_raw),", "game_specific=view.game_specific, team=slot.team_raw,", CORE),
    ("model: type 19 other_a under flag8", "model.py", "                other_a = -1 if slot.extra[0] == 1 else slot.extra[1]", "                other_a = slot.extra[1]", CORE),
    ("model: unresolved ids are counted as stock", "model.py", "    if name is None:\n        return type_id, \"Unknown (0x%04X)\" % type_id, False", "    if name is None:\n        return type_id, \"Unknown (0x%04X)\" % type_id, True", CORE),
    # --- plain -------------------------------------------------------------------------------
    ("plain: the trailer is not written", "plain.py", "            \"trailer_hex\": blf.trailer.hex() if blf.trailer else None,", "            \"trailer_hex\": None,", CORE),
    ("plain: the tail is never written", "plain.py", "        \"tail_hex\": \"\" if tail_zero else tail.data.hex(),", "        \"tail_hex\": \"\",", CORE),
    ("plain: hash recipe is not kept", "plain.py", "    flavour = hashing.HashFlavour(hash_info.get(\"length_endian\", \">\"), hash_info.get(\"recipe\", \"salted_be32\"))",
     "    flavour = hashing.HashFlavour(\">\", \"salted_be32\")", CORE),
    # --- report / tools ----------------------------------------------------------------------
    ("report: a failed self-check exits 0", "report.py", "        report.exit_code = EXIT_SELFCHECK\n        report.failure = \"self-check failed:", "        report.exit_code = EXIT_OK\n        report.failure = \"self-check failed:", CLI),
    ("report: a desync exits 2", "report.py", "    if isinstance(exc, (DesyncError, AmbiguousLayoutError, OutOfBoundsPositionError, FormatError)):\n        return EXIT_DECODE, str(exc)",
     "    if isinstance(exc, (DesyncError, AmbiguousLayoutError, OutOfBoundsPositionError, FormatError)):\n        return EXIT_NOT_MAP, str(exc)", CLI),
    ("report: the repository tree is not protected", "report.py", "        if real == root or real.startswith(root + os.sep):", "        if False:", CLI),
    ("report: strings are not omitted", "report.py", "\"title\": h.title_text if strings else OMITTED,", "\"title\": h.title_text,", CLI),
    # --- io (the new protected default) ------------------------------------------------------
    ("io: the real sample folder is not protected", "io.py", "    \"~/Local_Documents/Halo-MCC/forge/real-mvar-samples\",\n", "", CORE + CLI),
]


def prepare(sandbox):
    os.makedirs(os.path.join(sandbox, "tests", "unit"))
    os.makedirs(os.path.join(sandbox, "tools"))
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(os.path.join(REPO, "Addon", "mvarlib"), os.path.join(sandbox, "Addon", "mvarlib"), ignore=ignore)
    shutil.copytree(os.path.join(REPO, "tests", "fixturebuilder"), os.path.join(sandbox, "tests", "fixturebuilder"), ignore=ignore)
    shutil.copytree(os.path.join(REPO, "tests", "golden"), os.path.join(sandbox, "tests", "golden"), ignore=ignore)
    shutil.copytree(os.path.join(REPO, "docs", "mvar", "reference"), os.path.join(sandbox, "docs", "mvar", "reference"), ignore=ignore)
    for name in G3_TESTS:
        shutil.copy(os.path.join(REPO, "tests", "unit", name), os.path.join(sandbox, "tests", "unit", name))
    for name in ("run_tests.py", "verify_mvar.py", "dump_mvar.py"):
        shutil.copy(os.path.join(REPO, "tools", name), os.path.join(sandbox, "tools", name))


def run(python, sandbox, only):
    cmd = [python, "-I", os.path.join(sandbox, "tools", "run_tests.py"), "--samples", "--only"] + list(only)
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, cwd=sandbox)
    return proc.returncode, proc.stdout


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("names", nargs="*")
    args = ap.parse_args(argv)
    chosen = [m for m in MUTANTS if not args.names or any(n in m[0] for n in args.names)]
    if args.list:
        for m in chosen:
            print(m[0])
        return 0
    sandbox = tempfile.mkdtemp(prefix="mjolnir-mutate-g3-")
    try:
        prepare(sandbox)
        code, out = run(args.python, sandbox, CORE + CLI)
        if code != 0:
            print("baseline is not green:\n" + out[-3000:])
            return 2
        survivors = []
        killed = 0
        for name, rel, old, new, only in chosen:
            path = os.path.join(sandbox, "Addon", "mvarlib", rel)
            with open(path, "r", encoding="utf-8") as fh:
                source = fh.read()
            if source.count(old) != 1:
                print("PATTERN  %-70s (%d occurrences of the old text in %s)" % (name, source.count(old), rel))
                survivors.append(name)
                continue
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(source.replace(old, new))
            code, out = run(args.python, sandbox, only)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(source)
            if code != 0:
                killed += 1
                print("killed   %s" % name)
            elif name in EQUIVALENT:
                print("equiv    %s" % name)
            else:
                print("SURVIVED %s" % name)
                survivors.append(name)
        print("")
        print("%d mutants: %d killed, %d equivalent, %d survivors"
              % (len(chosen), killed, sum(1 for m in chosen if m[0] in EQUIVALENT and m[0] not in survivors), len(survivors)))
        return 1 if survivors else 0
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
