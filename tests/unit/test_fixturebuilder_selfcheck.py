"""U-20 (SPEC 9.3, 11 G2): the independent fixture builder agrees with its own walker, with W1's golden numbers and with the spec.

* the builder reproduces W1 (Appendix C) byte for byte: SHA-256 of both hash flavours, stored SHA-1, L, end bit, section starts,
  slot bit ranges, the edits E1/E2/E2b/E3 and the header goldens of C.4 -- the numbers are taken from ``tests/golden/w1_reference.json``
  and, when the spec file is present, re-parsed from ``docs/mvar/SPEC-mvar.md`` and compared with that JSON;
* every committed fixture spec: JSON == catalogue, builds deterministically to the SHA-256 recorded in ``fixture_sha256.json`` (identical
  on every Python), is decoded by the separately written walker to exactly the declared values, hypothesis tables as stored;
* negative fixtures are refused by the walker with the exception the catalogue names;
* ``cmp`` / ``cmp_fsm`` expand (derived here without the builder) to the golden ``*_expanded`` files;
* the golden codec vectors equal a fresh computation and the numbers printed in the spec;
* the builder imports nothing from ``Addon`` / ``mvarlib`` (the scan of U-17 does the same on the real directory) and writes
  fixtures only into temporary directories.
"""
import ast
import hashlib
import importlib
import json
import math
import os
import re
import sys
import tempfile
import unittest
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import helpers_fixtures as hf  # noqa: E402

REPO = hf.REPO
GOLDEN = os.path.join(REPO, "tests", "golden")
SPEC_MD = os.path.join(REPO, "docs", "mvar", "SPEC-mvar.md")

build, selfcheck = hf.modules()
bits = sys.modules["fixturebuilder.bits"]
consts = sys.modules["fixturebuilder.consts"]
catalogue = importlib.import_module("fixturebuilder.catalogue")

REQUIRED_FIXTURES = (
    "w1_minimal", "holes", "extremes", "zero_labels", "labels_uncompressed", "labels_compressed", "v32", "cmp", "fsm", "cmp_fsm",
    "plain_le32", "le_length", "eof_le", "type19_flag8", "type19_plain8", "axis_threshold", "near_full", "full650", "over650",
    "unknown_map", "zero_hash", "guid_v32_absent", "guid_v31_present", "trailer", "hdr_hopper", "hdr_campaign", "hdr_firefight",
    "hdr_long_text", "hdr_min_text", "cmp_expanded", "cmp_fsm_expanded", "w1_E1", "w1_E2", "w1_E2b", "w1_E3",
    "bad_version", "bad_size", "oob", "desync_length", "truncated", "bad_content_type", "chunk_version_50", "chunk_version_13",
    "bounds_inverted",
)


def load_json(*parts):
    with open(os.path.join(GOLDEN, *parts), "r", encoding="utf-8") as fh:
        return json.load(fh)


def spec_text():
    if not os.path.exists(SPEC_MD):
        return None
    with open(SPEC_MD, "r", encoding="utf-8") as fh:
        return fh.read()


ALL_SPECS = None


def committed_specs():
    global ALL_SPECS
    if ALL_SPECS is None:
        ALL_SPECS = {n: build.load_spec(n) for n in build.spec_names()}
    return ALL_SPECS


BUILT = {}


def built(name):
    if name not in BUILT:
        BUILT[name] = build.build(committed_specs()[name])
    return BUILT[name]


# =====================================================================================================
class TestIndependence(unittest.TestCase):
    MODULES = ("__init__.py", "bits.py", "consts.py", "build.py", "catalogue.py", "selfcheck.py")

    def test_the_package_has_the_deliverable_modules(self):
        names = sorted(f for f in os.listdir(hf.BUILDER) if f.endswith(".py"))
        for required in ("__init__.py", "bits.py", "consts.py", "build.py", "selfcheck.py"):
            self.assertIn(required, names)
        self.assertEqual(names, sorted(self.MODULES))

    def test_no_module_imports_the_library_or_the_addon(self):
        forbidden = ("mvarlib", "Addon", "provider", "bpy")
        for name in self.MODULES:
            path = os.path.join(hf.BUILDER, name)
            with open(path, "r", encoding="utf-8") as fh:
                source = fh.read()
            tree = ast.parse(source, filename=path)
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    mods = [node.module or ""]
                    mods += [a.name for a in node.names]
                for mod in mods:
                    self.assertNotIn(mod.split(".")[0], forbidden, "%s:%d imports %s" % (name, node.lineno, mod))
            self.assertNotRegex(source, r"\.\.\s*/\s*Addon", name)
            self.assertNotRegex(source, r"(import_module|__import__)\s*\(\s*['\"](mvarlib|Addon)", name)

    def test_only_standard_library_modules_are_imported(self):
        allowed = {"argparse", "copy", "hashlib", "json", "math", "os", "re", "struct", "sys", "zlib", "fixturebuilder"}
        for name in self.MODULES:
            with open(os.path.join(hf.BUILDER, name), "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        self.assertIn(a.name.split(".")[0], allowed, "%s imports %s" % (name, a.name))
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    self.assertIn((node.module or "").split(".")[0], allowed, "%s imports from %s" % (name, node.module))


# =====================================================================================================
class TestBitPrimitives(unittest.TestCase):
    def test_writer_matches_a_string_model(self):
        import random
        rng = random.Random(20)
        for _ in range(60):
            w, text = bits.BitWriter(), ""
            for _ in range(rng.randint(1, 40)):
                n = rng.randint(0, 40)
                v = rng.getrandbits(n) if n else 0
                w.put(v, n)
                text += format(v, "0%db" % n) if n else ""
            self.assertEqual(w.to_bitstring(), text)
            total = (len(text) + 7) // 8 + rng.randint(0, 3)
            expect = int(text.ljust(8 * total, "0") or "0", 2).to_bytes(total, "big") if total else b""
            self.assertEqual(w.getbytes(total), expect)

    def test_writer_never_masks(self):
        w = bits.BitWriter()
        for bad in ((4, 2), (-1, 3), (1, 0), (2 ** 64, 64)):
            with self.assertRaises(ValueError):
                w.put(*bad)
        with self.assertRaises(ValueError):
            w.put_signed(128, 8)
        with self.assertRaises(ValueError):
            w.put_signed(-129, 8)
        with self.assertRaises(ValueError):
            w.put(True, 1)
        w.put_signed(-128, 8)
        w.put_signed(127, 8)
        self.assertEqual(w.getbytes(2), b"\x80\x7f")

    def test_reader_round_trips_the_writer_at_any_alignment(self):
        import random
        rng = random.Random(21)
        for _ in range(40):
            w = bits.BitWriter()
            fields = []
            for _ in range(rng.randint(1, 30)):
                n = rng.randint(0, 33)
                v = rng.getrandbits(n) if n else 0
                fields.append((v, n))
                w.put(v, n)
            r = bits.BitSource(w.getbytes((w.nbits + 7) // 8 + 1))
            for v, n in fields:
                self.assertEqual(r.u(n), v)
            self.assertEqual(r.pos, w.nbits)

    def test_reader_signed_and_overrun(self):
        r = bits.BitSource(b"\xfb\x00", 12)
        self.assertEqual(r.s(8), -5)
        self.assertEqual(r.u(4), 0)
        with self.assertRaises(bits.BitOverrun):
            r.u(1)

    def test_adler32_and_stored_zlib_are_valid(self):
        for data in (b"", b"a", bytes(range(256)) * 300, bytes(65535), bytes(65536), os.urandom(70000)):
            self.assertEqual(bits.adler32(data), zlib.adler32(data) & 0xFFFFFFFF)
            stream = bits.zlib_stored(data)
            self.assertEqual(zlib.decompress(stream), data)
            self.assertEqual(len(stream), bits.zlib_stored_length(len(data)))

    def test_canonical_json_round_trips_and_is_stable(self):
        obj = {"b": [1, 2, 3], "a": {"z": None, "y": [], "x": {}}, "c": [{"k": 1.5}, {"k": "text"}], "d": list(range(80)), "e": "caf\u00e9"}
        text = bits.dumps_json(obj)
        self.assertEqual(json.loads(text), obj)
        self.assertEqual(text, bits.dumps_json(json.loads(text)))
        self.assertTrue(text.endswith("}\n"))
        self.assertTrue(all(len(line) <= 112 for line in text.splitlines()))
        self.assertLess(text.index('"a"'), text.index('"b"'))

    def test_float32_helpers(self):
        self.assertEqual(bits.f32_bits(-240.0), 0xC3700000)
        self.assertEqual(bits.bits_f32(0x3C088889), 0.008333333767950535)
        self.assertEqual(bits.f32_round(0.1), 0.10000000149011612)


# =====================================================================================================
class TestW1Golden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ref = load_json("w1_reference.json")

    def test_w1_reference_equals_the_numbers_printed_in_the_spec(self):
        text = spec_text()
        if text is None:
            self.skipTest("docs/mvar/SPEC-mvar.md not found")
        self.assertEqual(selfcheck.parse_spec_appendix_c(text), self.ref)

    def test_w1_geometry(self):
        b = built("w1_minimal")
        ref = self.ref
        self.assertEqual(len(b.data), ref["file_length"])
        self.assertEqual(b.info["end_bit"], ref["section_starts"]["end"])
        self.assertEqual(b.info["L"], ref["L"])
        self.assertEqual(b.info["axis_bits"], ref["axis_bits"])
        self.assertEqual(b.info["sections"]["header"], ref["section_starts"]["header"])
        self.assertEqual(b.info["sections"]["body_fixed"], ref["section_starts"]["body_fixed"])
        self.assertEqual(b.info["sections"]["labels"], ref["section_starts"]["labels"])
        self.assertEqual(b.info["sections"]["slots"], ref["section_starts"]["slots"])
        self.assertEqual(b.info["sections"]["quotas"], ref["section_starts"]["quotas"])
        for slot, (lo, hi) in ref["slot_ranges"].items():
            if slot == "0":
                self.assertNotIn(0, b.info["slot_ranges"])                      # slot 0 is absent: exactly one bit
                self.assertEqual((lo, hi), (ref["section_starts"]["slots"], ref["section_starts"]["slots"] + 1))
            else:
                self.assertEqual(list(b.info["slot_ranges"][int(slot)]), [lo, hi])
        for slot, nbits in ref["slot_bits"].items():
            lo, hi = b.info["slot_ranges"][int(slot)]
            self.assertEqual(hi - lo, nbits)
        self.assertEqual(ref["quota_table"], [b.info["sections"]["quotas"], b.info["sections"]["end"]])
        self.assertEqual(ref["quota_table"][1] - ref["quota_table"][0], ref["quota_rows"] * 24)

    def test_both_hash_flavours(self):
        for recipe, row in self.ref["flavours"].items():
            b = built(row["fixture"])
            self.assertEqual(b.info["stored_hash"], row["stored_sha1"], recipe)
            self.assertEqual(b.sha256, row["file_sha256"], recipe)
            self.assertEqual(b.info["L"], self.ref["L"])

    def test_golden_edits(self):
        for name, row in self.ref["edits"].items():
            b = built(row["fixture"])
            self.assertEqual(b.info["end_bit"], row["end_bit"], name)
            self.assertEqual(b.info["L"], row["L"], name)
            self.assertEqual(b.info["stored_hash"], row["stored_sha1"], name)
            self.assertEqual(b.sha256, row["file_sha256"], name)

    def test_edit_bit_differences_follow_the_spec(self):
        base, e1, e2, e3 = (built(n) for n in ("w1_minimal", "w1_E1", "w1_E2", "w1_E3"))
        sbase = base.data[0x314:0x314 + 0x7000]
        # E1: only the 20 x-bits of slot 1 (plus the 20 hash bytes) change, L and end are unchanged
        diff = int.from_bytes(sbase, "big") ^ int.from_bytes(e1.data[0x314:0x314 + 0x7000], "big")
        total = 8 * 0x7000
        first = total - diff.bit_length()
        last = total - ((diff & -diff).bit_length() - 1)
        x_start = base.info["slot_field_spans"][1][[n for n, _, _ in base.info["slot_field_spans"][1]].index("pos_x")][1]
        self.assertGreaterEqual(first, x_start)
        self.assertLessEqual(last, x_start + 20)
        self.assertEqual(base.data[:0x2F0 + 12], e1.data[:0x2F0 + 12])
        self.assertEqual(e1.info["end_bit"], base.info["end_bit"])
        # E2 adds 140 bits, E3 removes 192
        self.assertEqual(e2.info["end_bit"] - base.info["end_bit"], 140)
        self.assertEqual(e3.info["end_bit"] - base.info["end_bit"], -192)

    def test_header_goldens(self):
        for name, row in self.ref["headers"].items():
            b = built(row["fixture"])
            self.assertEqual(b.info["header_end"], row["header_end"], name)
            self.assertEqual(b.info["end_bit"], row["end_bit"], name)
            self.assertEqual(b.info["L"], row["L"], name)
            self.assertEqual(b.info["stored_hash"], row["stored_sha1"], name)

    def test_expected_sizes(self):
        self.assertEqual(consts.PLAIN_FILE_LENGTH, 29481)
        self.assertEqual(consts.PLAIN_FILE_LENGTH, 0x7329)
        self.assertEqual(consts.EOF_OFFSET, 0x7318)
        b = built("w1_minimal")
        self.assertEqual(int.from_bytes(b.data[0x7318 + 12:0x7318 + 16], "big"), 0x7318)
        self.assertEqual(b.data[0x2F0:0x2F4], b"mvar")
        self.assertEqual(int.from_bytes(b.data[0x2F0 + 4:0x2F0 + 8], "big"), 0x7028)
        self.assertEqual(int.from_bytes(b.data[0x2F0 + 32:0x2F0 + 36], "big"), 622)


# =====================================================================================================
class TestSpecFilesAndDeterminism(unittest.TestCase):
    def test_all_required_fixtures_exist(self):
        have = set(build.spec_names())
        for name in REQUIRED_FIXTURES:
            self.assertIn(name, have)

    def test_committed_json_equals_the_catalogue(self):
        cat = catalogue.all_specs()
        self.assertEqual(sorted(s["name"] for s in cat), build.spec_names())
        for spec in cat:
            path = os.path.join(build.SPECS_DIR, spec["name"] + ".json")
            with open(path, "r", encoding="utf-8") as fh:
                self.assertEqual(fh.read(), build.dumps_json(spec), spec["name"])

    def test_sha256_file_matches_every_build_on_every_interpreter(self):
        rec = load_json("fixture_sha256.json")
        self.assertEqual(rec["schema"], build.SHA_SCHEMA)
        self.assertEqual(sorted(rec["files"]), build.spec_names())
        for name in build.spec_names():
            b = built(name)
            self.assertEqual(rec["files"][name]["sha256"], b.sha256, name)
            self.assertEqual(rec["files"][name]["size"], len(b.data), name)

    def test_a_second_run_is_identical(self):
        with tempfile.TemporaryDirectory(prefix="mjolnir-fx-a-") as a, tempfile.TemporaryDirectory(prefix="mjolnir-fx-b-") as b:
            first = build.build_all(a)
            second = build.build_all(b)
            self.assertEqual(sorted(first), sorted(second))
            rec = load_json("fixture_sha256.json")["files"]
            for name in first:
                with open(first[name], "rb") as f1, open(second[name], "rb") as f2:
                    d1, d2 = f1.read(), f2.read()
                self.assertEqual(d1, d2, name)
                self.assertEqual(hashlib.sha256(d1).hexdigest(), rec[name]["sha256"], name)

    def test_no_fixture_file_is_written_inside_the_repository(self):
        with self.assertRaises(build.FixtureError):
            build.build_all(os.path.join(REPO, "tests", "fx_should_not_exist"))
        self.assertFalse(os.path.exists(os.path.join(REPO, "tests", "fx_should_not_exist")))
        self.assertFalse(hf.inside_repo(hf.fixtures_dir()))
        p = hf.fixture_path("w1_minimal")
        self.assertFalse(hf.inside_repo(p))
        with open(p, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), load_json("w1_reference.json")["flavours"]["salted_be32"]["file_sha256"])

    def test_no_game_file_extension_or_magic_in_golden_data(self):
        for root, dirs, files in os.walk(GOLDEN):
            for f in files:
                self.assertTrue(f.endswith(".json"), f)
                with open(os.path.join(root, f), "rb") as fh:
                    self.assertNotEqual(fh.read(4), b"_blf")

    def test_the_catalogue_is_free_of_stray_keys(self):
        for name, spec in committed_specs().items():
            self.assertEqual(spec["schema"], consts.SCHEMA_SPEC)
            self.assertEqual(spec["name"], name)
            self.assertIn(spec["role"], ("positive", "negative"))
            self.assertIn("expect", spec)


# =====================================================================================================
class TestWalkerAgreesWithBuilder(unittest.TestCase):
    def positives(self):
        return [n for n, s in committed_specs().items() if s["role"] == "positive"]

    def negatives(self):
        return [n for n, s in committed_specs().items() if s["role"] == "negative"]

    def test_every_positive_fixture_decodes_to_the_declared_values(self):
        for name in self.positives():
            b = built(name)
            res = selfcheck.read(b.data)
            self.assertEqual(res["outcome"], "ok", name)
            self.assertEqual(selfcheck.compare(res, b.model, b.info), [], name)
            self.assertEqual(selfcheck.check_chdr(b.data, res), [], name)

    def test_the_stored_expectations_equal_a_fresh_analysis(self):
        for name, spec in committed_specs().items():
            self.assertEqual(spec["expect"], json.loads(json.dumps(selfcheck.analyse(built(name).data))), name)

    def test_negative_fixtures_are_refused_as_catalogued(self):
        wanted = {"bad_version": "UnsupportedVariantError", "bad_size": "UnsupportedVariantError", "oob": "OutOfBoundsPositionError",
                  "desync_length": "DesyncError", "truncated": "BlfFormatError", "bad_content_type": "UnsupportedVariantError",
                  "chunk_version_50": "UnsupportedVariantError", "chunk_version_13": "UnsupportedVariantError",
                  "bounds_inverted": "FormatError"}
        self.assertEqual(sorted(self.negatives()), sorted(wanted))
        for name, kind in wanted.items():
            res = selfcheck.read(built(name).data)
            self.assertEqual(res["outcome"], "error", name)
            self.assertEqual(res["error"], kind, name)
            self.assertEqual(committed_specs()[name]["expect_error"], kind)

    def test_oob_slot_and_message(self):
        res = selfcheck.read(built("oob").data)
        self.assertEqual(res["slot"], 5)
        # every hypothesis of the version-implied GUID reading fails at slot 5; the other reading fails elsewhere (see notes G2, 3.10)
        self.assertTrue(all(e["reason"] == "oob" and e["slot"] == 5 for e in res["table"] if not e["guid"]))
        self.assertFalse(res["oob_all_hypotheses_same_slot"])

    def test_designed_rejections_hold_with_and_without_the_unsourced_checks(self):
        seen = 0
        for name, spec in committed_specs().items():
            design = spec.get("design")
            if not design:
                continue
            for core in (False, True):
                exp = selfcheck.analyse(built(name).data, core_only=core)
                for want in design["must_reject"]:
                    rows = [r for r in exp["hypotheses"] if all(r.get(k) == v for k, v in want.items())]
                    self.assertTrue(rows, (name, want))
                    for row in rows:
                        self.assertFalse(row["accepted"], (name, core, row))
                        seen += 1
        self.assertGreater(seen, 6)

    def test_type19_rules(self):
        for rule in ("flag8", "plain8"):
            exp = committed_specs()["type19_" + rule]["expect"]
            self.assertEqual(exp["type19_status"], rule)
            self.assertEqual(exp["hypothesis"]["type19"], rule)
            self.assertEqual([h["type19"] for h in exp["accepted_hypotheses"]], [rule])
        for name in ("w1_minimal", "holes", "extremes"):
            self.assertEqual(committed_specs()[name]["expect"]["type19_status"], "undetermined")
            self.assertEqual(len(committed_specs()[name]["expect"]["accepted_hypotheses"]), 2)

    def test_axis_threshold_fixtures_have_two_axis_hypotheses(self):
        for name in ("axis_threshold", "axis_threshold_f32"):
            exp = committed_specs()[name]["expect"]
            triples = sorted(set(tuple(h["axis_bits"]) for h in exp["hypotheses"]))
            self.assertEqual(triples, [(20, 21, 19), (21, 21, 19)], name)
            self.assertEqual(exp["hypothesis"]["axis_bits"], [20, 21, 19])
            self.assertEqual({tuple(h["axis_bits"]) for h in exp["accepted_hypotheses"]}, {(20, 21, 19)})
        # the two spec ranges really sit on the two thresholds of SPEC 4.1
        b = committed_specs()["axis_threshold"]["body"]["bounds"]
        self.assertAlmostEqual(b[1] - b[0], (2.0 ** 20) * (0.00833333333 / 32 * 2), delta=1e-9)
        b = committed_specs()["axis_threshold_f32"]["body"]["bounds"]
        self.assertEqual(b[1] - b[0], bits.f32_round((2.0 ** 20) * 0.0005208333604969084))

    def test_guid_fixtures(self):
        absent = committed_specs()["guid_v32_absent"]["expect"]
        present = committed_specs()["guid_v31_present"]["expect"]
        self.assertEqual(absent["hypothesis"]["guid"], False)
        self.assertEqual(present["hypothesis"]["guid"], True)
        for exp in (absent, present):
            self.assertTrue(exp["guid_contradicts_version"])
            self.assertIn("W_GUID_VERSION_MISMATCH", exp["read_warnings"])
        v32 = committed_specs()["v32"]["expect"]
        self.assertTrue(v32["hypothesis"]["guid"])
        self.assertFalse(v32["guid_contradicts_version"])
        self.assertEqual(v32["end_bit"] - committed_specs()["w1_minimal"]["expect"]["end_bit"], 128)

    def test_container_variants(self):
        want = {"cmp": ("cmp4", ">", "salted_be32"), "fsm": ("plain4+fsm", ">", "salted_be32"), "cmp_fsm": ("cmp4+fsm", ">", "salted_be32"),
                "trailer": ("other", ">", "salted_be32"), "plain_le32": ("plain4", ">", "plain_le32"),
                "le_length": ("plain4", "<", "salted_be32"), "zero_hash": ("plain4", ">", "zero"), "eof_le": ("plain4", ">", "salted_be32")}
        for name, (shape, endian, recipe) in want.items():
            exp = committed_specs()[name]["expect"]
            self.assertEqual(exp["shape"], shape, name)
            self.assertEqual(exp["flavour"], {"length_endian": endian, "recipe": recipe}, name)
        self.assertEqual(committed_specs()["eof_le"]["expect"]["eof_endian"], "<")
        cap = committed_specs()["length_capacity"]["expect"]
        self.assertEqual((cap["length"], cap["length_class"]), (0x7000, "capacity"))
        self.assertEqual(committed_specs()["w1_minimal"]["expect"]["length_class"], "ceil_end")
        self.assertEqual(committed_specs()["w1_minimal"]["expect"]["eof_endian"], ">")

    def test_extremes_and_zero_range_axis(self):
        exp = committed_specs()["extremes"]["expect"]
        self.assertEqual(exp["hypothesis"]["axis_bits"], [23, 15, 0])
        self.assertIn("W_ZERO_RANGE_AXIS", exp["read_warnings"])
        m = built("extremes").model
        values = lambda key: sorted(set(s[key] for s in m["slots"].values() if s[key] is not None))
        self.assertTrue({-128, 127} <= set(values("spawn_seq")))
        self.assertTrue({0, 9} <= set(values("team_raw")))
        self.assertTrue({0, 651} <= set(values("parent_raw")))
        self.assertIn(255, [s["label"] for s in m["slots"].values()])
        self.assertEqual(m["labels"]["count"], 256)
        self.assertIn(255, values("folder"))
        self.assertIn(31, values("item"))
        self.assertIn(31, values("cached_type"))
        self.assertTrue({0, 16383} <= set(values("angle")))
        self.assertTrue({0, 0x7FF} <= set(d for s in m["slots"].values() if s["shape"] == 3 for d in s["dims"]))
        self.assertIn(7, [s["color"] for s in m["slots"].values()])
        self.assertIn(None, [s["color"] for s in m["slots"].values()])
        xs = [s["pos"][0] for s in m["slots"].values()]
        ys = [s["pos"][1] for s in m["slots"].values()]
        self.assertTrue({0, (1 << 23) - 1} <= set(xs))
        self.assertTrue({0, (1 << 15) - 1} <= set(ys))
        self.assertTrue(all(s["pos"][2] == 0 for s in m["slots"].values()))

    def test_axis_width_family_covers_15_to_23(self):
        widths = set()
        for name in ("extremes", "axes_16_17_18", "axes_19_20_21", "axes_22_23_22"):
            widths.update(committed_specs()[name]["expect"]["hypothesis"]["axis_bits"])
        self.assertTrue(set(range(15, 24)) <= widths, sorted(widths))
        for name in ("axes_16_17_18", "axes_19_20_21", "axes_22_23_22"):
            m = built(name).model
            for k, w in enumerate(m["layout"]["axis_bits"]):
                column = {s["pos"][k] for s in m["slots"].values()}
                self.assertIn((1 << w) - 1, column, (name, k))
                self.assertIn(0, column, (name, k))

    def test_capacity_and_count_fixtures(self):
        self.assertEqual(committed_specs()["full650"]["expect"]["present_slots"].__len__(), 650)
        self.assertEqual(committed_specs()["over650"]["expect"]["present_slots"].__len__(), 651)
        nf = committed_specs()["near_full"]["expect"]
        self.assertTrue(0 < nf["free_bits"] <= 107)
        self.assertLessEqual(nf["length"], 0x7000)
        self.assertLess(nf["free_bits"], 140)                 # a 141-bit slot cannot be added
        self.assertEqual(len(nf["present_slots"]), 640)
        for name in ("full650", "over650"):
            rows = built(name).model["quotas"]
            for folder in (70, 71, 72, 73):
                self.assertEqual(rows[folder][:2], [0, 255])
                self.assertEqual(rows[folder][2], sum(1 for s in built(name).model["slots"].values() if s["folder"] == folder))

    def test_capacity_needs_a_label_buffer_above_4096_bytes(self):
        import copy
        spec = copy.deepcopy(committed_specs()["near_full"])
        spec["labels"]["pad_to"] = 4096                       # RVT's maximum buffer
        spec["slots_gen"]["skip"] = []                        # all 651 slots, each of the largest kind (235 bits)
        spec["quotas"] = {"rows": {}}
        info = build.build(spec).info
        self.assertEqual(info["present_count"], 651)
        self.assertEqual(info["end_bit"], 200570)
        self.assertGreater(info["free_bits"], 28000)
        nf = committed_specs()["near_full"]
        self.assertGreater(nf["labels"]["pad_to"], 4096)

    def test_label_tables(self):
        self.assertEqual(committed_specs()["zero_labels"]["expect"]["label_texts"], [])
        self.assertEqual(committed_specs()["labels_uncompressed"]["expect"]["label_texts"],
                         ["Gamma", None, "Alpha", "Beta", "", "Beta"])
        comp = built("labels_compressed").model["labels"]
        self.assertTrue(comp["compressed"])
        self.assertGreaterEqual(len(comp["buffer"]), 0x80)
        self.assertEqual(zlib.decompress(comp["comp"]), comp["buffer"])
        self.assertEqual(committed_specs()["labels_compressed"]["expect"]["label_texts"], catalogue.LABELS_COMPRESSED_STRINGS)

    def test_header_widths_follow_the_formula_of_spec_3_2(self):
        def end(n_c, n_m, t, d, extra):
            return 341 + (129 + 8 * n_c) + (129 + 8 * n_m) + 16 * t + 16 * d + extra
        self.assertEqual(end(2, 2, 11, 28, 0), 1255)          # W1: names "A" + NUL (2 bytes), title 10 chars + NUL, description 27 + NUL
        self.assertEqual(end(2, 2, 11, 28, 16), 1271)
        self.assertEqual(end(2, 2, 11, 28, 52), 1307)
        self.assertEqual(end(2, 2, 11, 28, 34), 1289)
        self.assertEqual(end(16, 16, 128, 128, 0), 4951)
        self.assertEqual(end(1, 1, 1, 1, 0), 647)

    def test_unknown_map_id(self):
        m = built("unknown_map").model
        self.assertEqual(m["header"]["map_id"], 0xFFFFFFFF)
        self.assertEqual(m["body"]["map_id_2"], 0xFFFFFFFF)
        raw = built("unknown_map").data
        self.assertEqual(int.from_bytes(raw[0x30 + 0x3C:0x30 + 0x40], "little"), 0xFFFFFFFF)


# =====================================================================================================
class TestCmpExpansion(unittest.TestCase):
    def test_wrapper_layout(self):
        b = built("cmp")
        data = b.data
        self.assertEqual(data[0x30 + 0x2C0:0x30 + 0x2C0 + 4], b"_cmp")
        size = int.from_bytes(data[0x2F0 + 4:0x2F0 + 8], "big")
        self.assertEqual(size, 12 + 1 + 4 + bits.zlib_stored_length(0x7028))
        self.assertEqual(data[0x2F0 + 12], 0)                                           # compression type 0 = zlib
        self.assertEqual(int.from_bytes(data[0x2F0 + 13:0x2F0 + 17], "big"), 0x7028)    # uncompressed size
        inner = zlib.decompress(data[0x2F0 + 17:0x2F0 + size])
        self.assertEqual(len(inner), 0x7028)
        self.assertEqual(inner[:4], b"mvar")
        self.assertEqual(b.info["file_length"], 0x30 + 0x2C0 + size + 0x11)
        self.assertNotEqual(b.info["file_length"], consts.PLAIN_FILE_LENGTH)           # the re-stamp is really exercised

    def test_expansion_equals_the_golden_expanded_files(self):
        for src, golden in (("cmp", "cmp_expanded"), ("cmp_fsm", "cmp_fsm_expanded")):
            expanded = selfcheck.expand_cmp(built(src).data)
            self.assertEqual(expanded, built(golden).data, golden)
            extra = consts.FSM["size"] if "fsm" in golden else 0
            self.assertEqual(len(built(golden).data), consts.PLAIN_FILE_LENGTH + extra)
            self.assertEqual(built(golden).info["file_length"], consts.PLAIN_FILE_LENGTH)

    def test_cmp_and_plain_content_are_the_same_map(self):
        a = selfcheck.read(built("cmp").data)["decoded"]
        b = selfcheck.read(built("w1_minimal").data)["decoded"]
        self.assertEqual(a["slots"], b["slots"])
        self.assertEqual(a["labels"], b["labels"])
        self.assertEqual(a["quotas"], b["quotas"])
        self.assertNotEqual(a["header"]["file_length"], b["header"]["file_length"])

    def test_fsm_is_not_counted_in_the_file_length(self):
        data = built("fsm").data
        self.assertEqual(len(data), consts.PLAIN_FILE_LENGTH + consts.FSM["size"])
        self.assertEqual(data[consts.PLAIN_FILE_LENGTH:consts.PLAIN_FILE_LENGTH + 4], b"_fsm")
        self.assertEqual(built("fsm").info["file_length"], consts.PLAIN_FILE_LENGTH)
        self.assertEqual(built("cmp_fsm").data[-consts.FSM["size"]:], built("cmp_fsm_expanded").data[-consts.FSM["size"]:])


# =====================================================================================================
class TestGoldenCodecVectors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vec = load_json("codec_vectors.json")

    def test_file_equals_a_fresh_computation(self):
        self.assertEqual(json.loads(json.dumps(selfcheck.compute_codec_vectors())), self.vec)

    def test_computation_agrees_with_the_spec_numbers(self):
        selfcheck.compute_codec_vectors()                        # raises AssertionError naming any disagreement

    def test_the_builders_own_axis_functions_agree(self):
        for row in self.vec["axis_bits"]:
            for variant in ("ceil", "trunc9999", "ceil_f32"):
                self.assertEqual([build.axis_bits_one(r, variant) for r in row["ranges"]], row[variant], (row["id"], variant))

    def test_documented_anchor_values(self):
        by_id = {r["id"]: r for r in self.vec["axis_bits"]}
        self.assertEqual(by_id["G-AX-1"]["ceil"], [21, 21, 21])
        self.assertEqual(by_id["G-AX-2"]["ceil"], [20, 21, 19])
        self.assertEqual(by_id["G-AX-4"]["ceil"], [16, 17, 0])
        for k in range(15, 23):
            row = by_id["G-AX-3/k=%d" % k]
            self.assertEqual((row["ceil"][0], row["trunc9999"][0], row["ceil_f32"][0]), (k, k + 1, k))
            row = by_id["G-AX-6/k=%d" % k]
            self.assertEqual((row["ceil"][0], row["trunc9999"][0], row["ceil_f32"][0]), (k + 1, k + 1, k))
        shapes = {r["code"]: r["expect"] for r in self.vec["shape_decode"]}
        self.assertEqual(shapes[0], 0.0)
        self.assertEqual(shapes[0x7FF], 200.0)
        enc = {r["value"]: r["expect"] for r in self.vec["shape_encode"]}
        self.assertEqual((enc[0.0], enc[200.0]), (0, 0x7FF))
        self.assertTrue(self.vec["shape_round_trip_all_2048"])
        ang = {r["theta_text"]: r["expect"] for r in self.vec["angle_encode"]}
        self.assertEqual(ang, {"0.0": 8192, "pi/2": 12288, "-pi/2": 4096, "pi": 16383, "-pi": 0})
        ids = {r["id"]: r for r in self.vec["ids"]}
        self.assertEqual((ids["G-ID-1"]["folder"], ids["G-ID-1"]["item"]), (71, 8))
        self.assertEqual(ids["G-ID-3/location_name"]["folder"], 144)
        self.assertEqual(self.vec["sizes"]["plain_file_length"], 0x7329)
        self.assertEqual(self.vec["sizes"]["stream_file_offset"], 0x314)
        self.assertEqual(self.vec["sizes"]["capacity_bits"], 229376)

    def test_hash_vectors_agree_between_builder_and_walker(self):
        d = self.vec["hashes"]
        data = bytes.fromhex(d["data_hex"])
        for recipe, digest in d["digests"].items():
            self.assertEqual(selfcheck.digest(recipe, data, d["L"]).hex(), digest)
            self.assertEqual(build.hash_digest(recipe, data, d["L"]).hex(), digest)
        self.assertEqual(build.hash_digest("zero", data, 10), bytes(20))
        self.assertEqual(d["salt34_hex"], consts.SALT34.hex())

    def test_numbers_printed_in_the_spec_text(self):
        text = spec_text()
        if text is None:
            self.skipTest("docs/mvar/SPEC-mvar.md not found")
        # 2.7 hash vectors
        for recipe, digest in self.vec["hashes"]["digests"].items():
            self.assertIn("`%s` = `%s`" % (recipe, digest), text)
        # G-UP table rows: | code | face, u, v | (x, y, z) |
        for row in self.vec["up_decode"]:
            m = re.search(r"\| %d \| %d, %d, %d \| \(([-\d.]+), ([-\d.]+), ([-\d.]+)\)" % (row["code"], row["face"], row["u"], row["v"]), text)
            self.assertIsNotNone(m, row["id"])
            for got, want in zip(row["expect"], [float(g) for g in m.groups()]):
                self.assertAlmostEqual(got, want, delta=1e-6, msg=row["id"])
        # G-SH decode list
        for row in self.vec["shape_decode"]:
            if row["code"] in (0, 0x7FF):
                continue
            m = re.search(r"`dim_decode\(%d\) = ([\d.]+)`" % row["code"], text)
            self.assertIsNotNone(m, row["id"])
            self.assertAlmostEqual(row["expect"], float(m.group(1)), delta=1e-12)
        # G-ANG
        for row in self.vec["angle_decode"]:
            m = re.search(r"`angle_decode\(%d\) = ([-\d.e]+)`" % row["raw"], text)
            self.assertIsNotNone(m, row["id"])
            self.assertAlmostEqual(row["expect"], float(m.group(1)), delta=1e-12)
        # G-POS-1 row: 0.000244140625 / 0.000732421875 / 1023.999755859375
        m = re.search(r"\| G-POS-1 \| 0\.\.1024, 21 \| 0 / 1 / 2,097,151 \| ([\d.]+) / ([\d.]+) / ([\d.]+)", text)
        self.assertIsNotNone(m)
        pos = {r["q"]: r["expect"] for r in self.vec["pos"] if r["id"].startswith("G-POS-1/")}
        for q, g in zip((0, 1, 2097151), m.groups()):
            self.assertAlmostEqual(pos[q], float(g), delta=1e-12)
        # G-AX-2 and the sizes in G-SZ
        self.assertIn("480, 690, 140", text)
        self.assertIn("29,481", text)

    def test_up_decode_matches_the_closed_form_constants(self):
        stride = (1 << 20) // 6
        self.assertEqual(stride, 174762)
        self.assertEqual(math.isqrt(stride) - 1, 417)
        self.assertEqual(consts.UP_STRIDE, stride)
        self.assertEqual(consts.UP_N, 417)
        with self.assertRaises(ValueError):
            selfcheck.up_decode(1048572)
        vec, face, u, v = selfcheck.up_decode(1048571)
        self.assertEqual((face, u, v), (5, 419, 38))


# =====================================================================================================
class TestBuilderRefusals(unittest.TestCase):
    """The builder refuses descriptions it cannot encode (it never masks a value)."""

    def spec(self):
        import copy
        return copy.deepcopy(committed_specs()["w1_minimal"])

    def test_value_too_wide(self):
        s = self.spec()
        s["slots"][0]["pos"][0] = 1 << 20                 # x has 20 bits
        with self.assertRaises(ValueError):
            build.build(s)

    def test_wrong_dims_for_shape(self):
        s = self.spec()
        s["slots"][1]["dims"] = [1, 2]
        with self.assertRaises(build.FixtureError):
            build.build(s)

    def test_extras_for_a_type_without_extras(self):
        s = self.spec()
        s["slots"][0]["extra"] = [1]
        with self.assertRaises(build.FixtureError):
            build.build(s)

    def test_unknown_key_and_bad_shape(self):
        s = self.spec()
        s["slots"][0]["colour"] = 1
        with self.assertRaises(build.FixtureError):
            build.normalise(s)
        s = self.spec()
        s["container"]["shape"] = "plain5"
        with self.assertRaises(build.FixtureError):
            build.normalise(s)

    def test_stream_over_capacity_is_refused(self):
        s = self.spec()
        catalogue.set_header_text(s, long_text=True)
        s["labels"] = {"strings": ["x"] * 256, "compressed": False, "pad_to": 8191}
        s["slots_gen"] = {"kind": "bulk", "style": "max", "start": 0, "stop": 651, "seed": 1, "folders": list(range(80)), "items": [0],
                          "labels": [0]}   # 651 slots of 235 bits, a 256-entry table with an 8191-byte buffer and the longest header
        s["slots"] = []
        s["body"]["bounds"] = [-2500.0, 2500.0, -2500.0, 2500.0, -2500.0, 2500.0]
        s["body"]["quota_count"] = 256
        with self.assertRaises(build.FixtureError):
            build.build(s)


if __name__ == "__main__":
    unittest.main()
