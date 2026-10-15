"""U-09 (SPEC 9.3, tier T2): the hypothesis search of SPEC 3.10 and the read-time refusals of 7.2.

* type 19: ``flag8`` and ``plain8`` fixtures decode under their own rule and are rejected under the wrong one;
  a file without a type-19 object reports ``undetermined``;
* axis rounding: the two threshold fixtures give two axis hypotheses and the end-of-walk check picks the right one;
* ``AmbiguousLayoutError`` (a crafted file that two readings both accept), ``DesyncError`` with per-hypothesis
  diagnostics, ``OutOfBoundsPositionError`` (all hypotheses of the version-implied GUID value fail at one slot) versus a
  single wrong hypothesis meeting an out-of-bounds record (no error);
* every hard plausibility check (quota count, label table, folder, label index and entry, parent link, up-code
  face) and what ``ReadOptions(strict=False)`` does about the two unsourced ones;
* GUID: a v32 file without the 128 bits and a v31 file with them are both read with ``W_GUID_VERSION_MISMATCH``, and
  an accepted version-implied value wins over the other one;
* wrong version, wrong size, content type, truncated stream, invalid L, chunk versions.

Special files are made with the independent builder from modified copies of the committed fixture specs.
"""
import copy
import os
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import helpers_g3 as g3  # noqa: E402

from mvarlib import api, blf, errors, walk  # noqa: E402
from mvarlib.model import MapVariant  # noqa: E402

build, selfcheck = g3.build_modules()


def variant(base, mutate):
    """Bytes of the committed spec ``base`` after ``mutate(spec)`` (built by the independent builder)."""
    spec = copy.deepcopy(g3.spec(base))
    spec.pop("expect", None)
    mutate(spec)
    return build.build(spec).data


def hyp_key(report):
    h = report.hypothesis
    return (h.type19, tuple(h.axis_bits), h.guid)


class TestType19Rule(unittest.TestCase):
    def test_flag8_file_is_read_under_flag8_and_plain8_is_rejected(self):
        m = g3.model("type19_flag8")
        self.assertEqual((m.hypothesis.type19, m.type19_status), ("flag8", "flag8"))
        by_key = dict((hyp_key(r), r) for r in m.reports)
        self.assertTrue(by_key[("flag8", (20, 21, 19), False)].accepted)
        wrong = by_key[("plain8", (20, 21, 19), False)]
        self.assertFalse(wrong.accepted)
        self.assertEqual((wrong.reason, wrong.slot), ("oob", 101))             # the builder's expectation, too
        self.assertEqual(sum(1 for s in m.slots if s.present and s.cached_type == 19), 5)

    def test_plain8_file_is_read_under_plain8_and_flag8_is_rejected(self):
        m = g3.model("type19_plain8")
        self.assertEqual((m.hypothesis.type19, m.type19_status), ("plain8", "plain8"))
        by_key = dict((hyp_key(r), r) for r in m.reports)
        wrong = by_key[("flag8", (20, 21, 19), False)]
        self.assertFalse(wrong.accepted)
        self.assertEqual((wrong.reason, wrong.slot), ("oob", 102))

    def test_forcing_the_wrong_rule_refuses_the_file(self):
        for name, wrong, slot in (("type19_flag8", "plain8", 101), ("type19_plain8", "flag8", 102)):
            with self.subTest(name):
                opts = api.ReadOptions(hypothesis_filter={"type19": wrong})
                with self.assertRaises(errors.OutOfBoundsPositionError) as cm:
                    api.load_map_variant(g3.data(name), name, opts)
                self.assertEqual(cm.exception.slot, slot)
                ok = api.load_map_variant(g3.data(name), name, api.ReadOptions(hypothesis_filter={"type19": "flag8" if wrong == "plain8" else "plain8"}))
                self.assertEqual(ok.info.hypothesis["type19"], "flag8" if wrong == "plain8" else "plain8")

    def test_a_file_without_type19_reports_undetermined(self):
        for name in ("w1_minimal", "holes", "full650"):
            with self.subTest(name):
                m = g3.model(name)
                self.assertEqual(m.type19_status, "undetermined")
                self.assertEqual(m.hypothesis.type19, "flag8")                     # preference order
                accepted = set(hyp_key(r)[0] for r in m.reports if r.accepted and not r.hypothesis.guid)
                self.assertEqual(accepted, set(["flag8", "plain8"]))
                self.assertEqual(api.load_map_variant(g3.data(name)).info.hypothesis["type19"], "undetermined")

    def test_the_filter_selects_hypotheses(self):
        m = MapVariant.from_bytes(g3.data("w1_minimal"), api.ReadOptions(hypothesis_filter={"type19": "plain8"}))
        self.assertEqual(m.hypothesis.type19, "plain8")
        self.assertEqual(len(m.reports), 2)                                          # plain8 x the two GUID values
        with self.assertRaises(errors.DesyncError):
            MapVariant.from_bytes(g3.data("w1_minimal"), api.ReadOptions(hypothesis_filter={"type19": "nonsense"}))
        m = MapVariant.from_bytes(g3.data("w1_minimal"), api.ReadOptions(hypothesis_filter={"guid": False, "axis_bits": [20, 21, 19]}))
        self.assertEqual(len(m.reports), 2)

    def test_hypothesis_order_and_count(self):
        prefix = walk.read_prefix(blf.parse(g3.data("w1_minimal")).find("mvar").stream)
        hyps = walk.build_hypotheses(prefix)
        self.assertEqual([(h.type19, h.guid) for h in hyps],
                         [("flag8", False), ("plain8", False), ("flag8", True), ("plain8", True)])        # v31: no GUID first
        prefix32 = walk.read_prefix(blf.parse(g3.data("v32")).find("mvar").stream)
        self.assertEqual([(h.type19, h.guid) for h in walk.build_hypotheses(prefix32)],
                         [("flag8", True), ("plain8", True), ("flag8", False), ("plain8", False)])         # v32: GUID first


class TestAxisRounding(unittest.TestCase):
    def test_threshold_fixtures_have_two_axis_hypotheses(self):
        for name in ("axis_threshold", "axis_threshold_f32"):
            with self.subTest(name):
                m = g3.model(name)
                prefix = walk.read_prefix(m.chunk.stream)
                triples = [h.axis_bits for h in walk.build_hypotheses(prefix) if h.type19 == "flag8" and not h.guid]
                self.assertEqual(len(triples), 2)
                self.assertEqual(sorted(t[0] for t in triples), [20, 21])
                self.assertEqual(m.hypothesis.axis_bits, (20, 21, 19))
                other = [r for r in m.reports if r.hypothesis.axis_bits != (20, 21, 19) and not r.hypothesis.guid]
                self.assertTrue(other)
                self.assertTrue(all(not r.accepted for r in other))
                self.assertEqual(len(m.reports), 8)

    def test_forcing_the_other_triple_fails(self):
        for name in ("axis_threshold", "axis_threshold_f32"):
            with self.subTest(name):
                with self.assertRaises(errors.MvarError):
                    api.load_map_variant(g3.data(name), name, api.ReadOptions(hypothesis_filter={"axis_bits": [21, 21, 19]}))

    def test_minority_variant_is_found_only_by_trying_all_variants(self):
        # axis_threshold_f32 is written with the ceil_f32 reading while ceil and trunc9999 say 21: a reader that only
        # knew the first variant would fail on it
        m = g3.model("axis_threshold_f32")
        self.assertEqual(m.hypothesis.axis_bits[0], 20)
        from mvarlib import codecs
        bounds = m.fixed.bounds
        doubles, singles = codecs.axis_ranges(bounds)
        self.assertEqual(codecs.axis_bits_ceil(doubles[0]), 21)
        self.assertEqual(codecs.axis_bits_ceil_f32(singles[0]), 20)


class TestAmbiguity(unittest.TestCase):
    @staticmethod
    def crafted():
        """A plain8 file whose last type-19 object is read just as validly under flag8 (the end test passes for both)."""
        def mutate(spec):
            spec["layout"]["type19"] = "plain8"
            spec["slots"] = [
                {"index": 2, "folder": 61, "item": 0, "pos": [1, 2, 3], "color": 3, "label": None, "shape": 3, "dims": [100, 100, 100, 100]},
                {"index": 5, "folder": 61, "item": None, "pos": [10, 20, 30], "cached_type": 19, "extra": [128], "color": 0, "label": None},
            ]
            spec["quotas"] = {"rows": {}}
        return variant("w1_minimal", mutate)

    def test_two_valid_readings_with_different_decodes_are_refused(self):
        data = self.crafted()
        with self.assertRaises(errors.AmbiguousLayoutError) as cm:
            api.load_map_variant(data)
        exc = cm.exception
        self.assertEqual(len(exc.candidates), 2)
        rules = sorted(c["hypothesis"]["type19"] for c in exc.candidates)
        self.assertEqual(rules, ["flag8", "plain8"])
        ends = sorted(c["end_bit"] for c in exc.candidates)
        self.assertEqual(ends[1] - ends[0], 7)                                  # flag8 consumes 7 bits less than plain8
        self.assertTrue(all("first_differing_slot" in c for c in exc.candidates))
        self.assertTrue(str(exc).startswith("This map variant can be read 2 different ways that all look valid (they first differ at slot "))
        self.assertTrue(str(exc).endswith("Run tools/verify_mvar.py for details."))

    def test_each_reading_alone_loads(self):
        data = self.crafted()
        for rule in ("flag8", "plain8"):
            with self.subTest(rule):
                m = MapVariant.from_bytes(data, api.ReadOptions(hypothesis_filter={"type19": rule, "guid": False}))
                self.assertEqual(m.hypothesis.type19, rule)
                self.assertEqual(m.type19_status, rule)
        plain8 = MapVariant.from_bytes(data, api.ReadOptions(hypothesis_filter={"type19": "plain8"}))
        self.assertEqual(plain8.slots[5].extra, [128])
        flag8 = MapVariant.from_bytes(data, api.ReadOptions(hypothesis_filter={"type19": "flag8"}))
        self.assertEqual(flag8.slots[5].extra, [1, 0])

    def test_verify_report_shows_both_accepted_hypotheses(self):
        from mvarlib import report
        rep = report.build_report(self.crafted())
        self.assertEqual(rep.exit_code, report.EXIT_DECODE)
        rows = rep.facts["walk"]["table"]
        self.assertEqual([r["accepted"] for r in rows if not r["hypothesis"]["guid"]], [True, True])
        self.assertEqual(rep.facts["walk"]["error"]["type"], "AmbiguousLayoutError")


class TestDesyncAndOutOfBounds(unittest.TestCase):
    def test_desync_carries_one_diagnostic_per_hypothesis(self):
        with self.assertRaises(errors.DesyncError) as cm:
            api.load_map_variant(g3.data("desync_length"))
        diag = cm.exception.diagnostics
        self.assertEqual(len(diag), 4)
        by = dict(((d["hypothesis"]["type19"], d["hypothesis"]["guid"]), d) for d in diag)
        self.assertEqual(by[("flag8", False)]["reason"], "length")
        self.assertEqual(by[("flag8", False)]["end_bit"], None)
        self.assertEqual(by[("flag8", False)]["bit"], 4970)
        self.assertIn("stored length is 625", by[("flag8", False)]["detail"])
        self.assertEqual(by[("plain8", True)]["reason"], "folder")
        for d in diag:
            self.assertFalse(d["accepted"])
            self.assertIn("axis_bits", d["hypothesis"])

    def test_out_of_bounds_is_reported_when_every_hypothesis_of_the_version_value_fails_at_one_slot(self):
        with self.assertRaises(errors.OutOfBoundsPositionError) as cm:
            api.load_map_variant(g3.data("oob"))
        self.assertEqual(cm.exception.slot, 5)

    def test_one_wrong_hypothesis_meeting_an_oob_record_is_not_an_error(self):
        m = g3.model("type19_flag8")
        rejected = [r for r in m.reports if r.reason == "oob"]
        self.assertTrue(rejected)
        self.assertTrue(m.occupied > 0)

    def test_out_of_bounds_under_different_slots_is_a_desync(self):
        data = variant("type19_flag8", lambda spec: spec["slots"][1].update({"in_bounds": 0}))
        with self.assertRaises(errors.MvarError) as cm:
            api.load_map_variant(data)
        self.assertIsInstance(cm.exception, (errors.OutOfBoundsPositionError, errors.DesyncError))

    def test_the_stream_overrun_is_a_rejection_not_a_crash(self):
        m = g3.model("near_full")
        guid_true = [r for r in m.reports if r.hypothesis.guid]
        self.assertTrue(all(not r.accepted for r in guid_true))


class TestHardChecks(unittest.TestCase):
    def reasons(self, data):
        with self.assertRaises(errors.DesyncError) as cm:
            api.load_map_variant(data)
        return cm.exception, set(d["reason"] for d in cm.exception.diagnostics if not d["hypothesis"] or not d["hypothesis"]["guid"])

    def test_folder_must_be_below_the_quota_count(self):
        data = variant("w1_minimal", lambda s: s["slots"][0].update({"folder": 200}))
        exc, reasons = self.reasons(data)
        self.assertEqual(reasons, set(["folder"]))
        self.assertTrue(any(d["detail"].count("200") for d in exc.diagnostics))

    def test_label_index_must_be_below_the_label_count(self):
        data = variant("w1_minimal", lambda s: s["slots"][0].update({"label": 200}))
        exc, reasons = self.reasons(data)
        self.assertEqual(reasons, set(["label"]))

    def test_label_entry_must_be_present(self):
        def mutate(spec):
            spec["labels"] = {"strings": ["SCALE", None, "Spawn"], "compressed": False}
            spec["slots"][0]["label"] = 1
        exc, reasons = self.reasons(variant("w1_minimal", mutate))
        self.assertEqual(reasons, set(["label"]))

    def test_parent_link_is_at_most_651(self):
        exc, reasons = self.reasons(variant("w1_minimal", lambda s: s["slots"][0].update({"parent_raw": 700})))
        self.assertEqual(reasons, set(["parent"]))
        ok = variant("w1_minimal", lambda s: s["slots"][0].update({"parent_raw": 651}))
        self.assertEqual(api.load_map_variant(ok).objects[0].parent_slot, 650)               # 651 is allowed (slot 650 + 1)

    def test_up_code_face_is_at_most_5(self):
        exc, reasons = self.reasons(variant("w1_minimal", lambda s: s["slots"][2].update({"up_code": 1048572})))
        self.assertEqual(reasons, set(["upface"]))
        ok = variant("w1_minimal", lambda s: s["slots"][2].update({"up_code": 1048571}))
        m = MapVariant.from_bytes(ok)
        self.assertEqual(m.soft.get("up_dead_zone"), 1)                                    # a dead-zone code is only a warning

    def test_the_up_code_dead_zone_starts_at_u_417(self):
        for code, dead in ((173888, 0), (173889, 1), (1048571, 1), (436468, 0)):
            with self.subTest(code=code):
                m = MapVariant.from_bytes(variant("w1_minimal", lambda s: s["slots"][2].update({"up_code": code})))
                self.assertEqual(m.soft.get("up_dead_zone", 0), dead)

    def test_quota_count_is_at_most_256(self):
        def mutate(spec):
            spec["body"]["quota_count"] = 257
        exc, reasons = self.reasons(variant("w1_minimal", mutate))
        self.assertEqual(reasons, set(["quota_count"]))
        self.assertIn("quota count 257", str(exc.diagnostics[0]["detail"]))
        def ok256(spec):
            spec["body"]["quota_count"] = 256
        self.assertEqual(MapVariant.from_bytes(variant("w1_minimal", ok256)).fixed.quota_count, 256)

    def test_label_count_is_at_most_256(self):
        def mutate(spec):
            spec["labels"] = {"offsets": [0] * 257, "buffer_hex": "00", "compressed": False}
            spec["slots"][0]["label"] = None
            spec["slots"][1]["label"] = None
            spec["slots"][2]["label"] = None
        exc, reasons = self.reasons(variant("w1_minimal", mutate))
        self.assertEqual(reasons, set(["labels"]))
        def ok(spec):
            spec["labels"] = {"offsets": [0] * 256, "buffer_hex": "00", "compressed": False}
        self.assertEqual(MapVariant.from_bytes(variant("w1_minimal", ok)).labels.count, 256)

    def test_a_compressed_label_block_must_inflate(self):
        def mutate(spec):
            comp = bytearray(bytes.fromhex(spec["labels"]["comp_hex"]))
            comp[10] ^= 0xFF
            comp[11] ^= 0xFF
            spec["labels"]["comp_hex"] = bytes(comp).hex()
        exc, reasons = self.reasons(variant("labels_compressed", mutate))
        self.assertEqual(reasons, set(["labels"]))

    def test_bounds_must_be_finite_and_ordered(self):
        from mvarlib import bitio
        base = g3.data("w1_minimal")
        stream_bit = (0x2F0 + 36) * 8
        for bounds in ([float("nan"), 240.0, -345.0, 345.0, -70.0, 70.0], [-240.0, float("inf"), -345.0, 345.0, -70.0, 70.0],
                       [-240.0, 240.0, 345.0, -345.0, -70.0, 70.0], [-240.0, 240.0, -345.0, 345.0, 70.0, -70.0]):
            with self.subTest(bounds=bounds):
                buf = bytearray(base)                                  # the hash no longer matches; only the bounds matter here
                for k, value in enumerate(bounds):
                    bitio.patch_bits(buf, stream_bit + 1255 + 115 + 32 * k, 32, struct.unpack(">I", struct.pack(">f", value))[0])
                with self.assertRaises(errors.FormatError) as cm:
                    api.load_map_variant(bytes(buf))
                self.assertTrue(str(cm.exception).startswith("The map bounds are not valid (axis "), str(cm.exception))
                self.assertIs(type(cm.exception), errors.FormatError)

    def test_equal_bounds_are_accepted_with_a_warning(self):
        m = g3.model("extremes")
        self.assertEqual([w.code for w in m.warnings].count("W_ZERO_RANGE_AXIS"), 1)

    def test_soft_checks_never_reject(self):
        def mutate(spec):
            spec["quotas"]["rows"]["61"] = [5, 2, 7]           # minimum above maximum, placed differs from the slot count
            spec["slots"][0]["team_raw"] = 12                   # a team value above 9
        m = MapVariant.from_bytes(variant("w1_minimal", mutate))
        self.assertEqual(m.soft.get("quota_min_above_max"), 1)
        self.assertEqual(m.soft.get("quota_placed_differs"), 1)          # row 61 says 7 placed, one slot is there
        self.assertEqual(m.soft.get("team_above_9"), 1)
        codes = [w.code for w in m.warnings]
        self.assertIn("W_QUOTA_MIN_ABOVE_MAX", codes)
        self.assertIn("W_TEAM_ABOVE_9", codes)

    def test_the_two_unsourced_checks_are_flagged_and_lenient_reading_accepts(self):
        data = variant("w1_minimal", lambda s: s["slots"][0].update({"folder": 200}))
        with self.assertRaises(errors.DesyncError):
            MapVariant.from_bytes(data, api.ReadOptions(strict=True))
        m = MapVariant.from_bytes(data, api.ReadOptions(strict=False))
        self.assertTrue(m.lenient)
        self.assertIn("W_LENIENT_PARSE", [w.code for w in m.warnings])
        self.assertEqual(m.to_bytes(force=False), data)                          # an unmodified lenient model is still passthrough
        with self.assertRaises(errors.InternalError):
            m.to_bytes(force=True)                                    # but nothing is ever built from a lenient parse
        from mvarlib import report
        rep = report.build_report(data)
        flagged = [r for r in rep.facts["walk"]["table"] if not r["hypothesis"]["guid"]]
        self.assertTrue(all(r.get("unsourced_only") for r in flagged))
        lenient = report.build_report(data, lenient=True)
        self.assertTrue(all(r["accepted"] for r in lenient.facts["walk"]["table"] if not r["hypothesis"]["guid"]))
        self.assertEqual(lenient.exit_code, report.EXIT_DECODE)          # the library still refuses it: lenient only shows the walk

    def test_strict_false_does_not_rescue_a_real_desync(self):
        with self.assertRaises(errors.DesyncError):
            MapVariant.from_bytes(g3.data("desync_length"), api.ReadOptions(strict=False))


class TestGuidHypothesis(unittest.TestCase):
    def test_mismatching_fixtures_are_read_with_a_warning(self):
        for name, guid in (("guid_v32_absent", False), ("guid_v31_present", True)):
            with self.subTest(name):
                res = api.load_map_variant(g3.data(name))
                self.assertIn("W_GUID_VERSION_MISMATCH", [w.code for w in res.warnings])
                self.assertEqual(res.info.hypothesis["guid"], guid)

    def test_the_wrong_value_would_not_have_been_accepted(self):
        for name in ("guid_v32_absent", "guid_v31_present"):
            m = g3.model(name)
            other = [r for r in m.reports if r.hypothesis.guid != m.hypothesis.guid]
            self.assertTrue(other)
            self.assertTrue(all(not r.accepted for r in other))

    def empty_capacity_map(self, version):
        def mutate(spec):
            spec["slots"] = []
            spec["quotas"] = {"rows": {}}
            spec["container"]["length"] = {"endian": ">", "mode": "capacity", "value": None}
            spec["container"]["mvar"]["version"] = version
            spec["body"]["version"] = version
            spec["guid"] = {"present": version >= 32, "hex": "00" * 16 if version >= 32 else None}
        return variant("v32" if version >= 32 else "w1_minimal", mutate)

    def test_an_accepted_version_implied_value_wins_without_ambiguity(self):
        for version in (31, 32):
            with self.subTest(version):
                data = self.empty_capacity_map(version)
                m = MapVariant.from_bytes(data)
                self.assertEqual(m.length_class, "capacity")
                self.assertEqual(m.hypothesis.guid, version >= 32)
                self.assertFalse(m.guid_contradicts_version)
                self.assertNotIn("W_GUID_VERSION_MISMATCH", [w.code for w in m.warnings])
                accepted_guid_values = set(r.hypothesis.guid for r in m.reports if r.accepted)
                self.assertEqual(accepted_guid_values, set([True, False]))          # both values fit; the version decides


class TestContainerRefusals(unittest.TestCase):
    def test_wrong_version_size_content_type(self):
        for name, text in (("bad_version", "body version is 30"), ("bad_size", "size 0x7030"), ("bad_content_type", "content type is 6")):
            with self.subTest(name):
                with self.assertRaises(errors.UnsupportedVariantError) as cm:
                    api.load_map_variant(g3.data(name))
                self.assertIn(text, str(cm.exception))

    def test_truncated_file(self):
        with self.assertRaises(errors.BlfFormatError):
            api.load_map_variant(g3.data("truncated"))
        with self.assertRaises(errors.BlfFormatError):
            api.load_map_variant(g3.data("w1_minimal")[:100])

    def test_invalid_stored_length(self):
        data = bytearray(g3.data("w1_minimal"))
        data[0x2F0 + 32:0x2F0 + 36] = b"\xff\xff\xff\xff"
        with self.assertRaises(errors.BlfFormatError) as cm:
            api.load_map_variant(bytes(data))
        self.assertEqual(str(cm.exception), "The stored stream length bytes FF FF FF FF are not a valid length (maximum 0x7000).")

    def test_stored_length_zero_is_the_zero_class(self):
        data = bytearray(g3.data("w1_minimal"))
        data[0x2F0 + 32:0x2F0 + 36] = bytes(4)
        m = MapVariant.from_bytes(bytes(data))          # the hash no longer matches: flavour unknown, still readable
        self.assertEqual(m.length_class, "zero")
        self.assertEqual(m.to_bytes(force=False), bytes(data))

    def test_stored_length_that_disagrees_with_the_walk(self):
        data = bytearray(g3.data("w1_minimal"))
        data[0x2F0 + 32:0x2F0 + 36] = struct.pack(">I", 700)
        with self.assertRaises(errors.DesyncError):
            api.load_map_variant(bytes(data))

    def test_chunk_versions(self):
        for version in (12, 13, 14, 50, 51):
            data = bytearray(g3.data("w1_minimal"))
            data[0x2F0 + 8:0x2F0 + 10] = struct.pack(">H", version)
            with self.subTest(version):
                with self.assertRaises(errors.UnsupportedVariantError) as cm:
                    api.load_map_variant(bytes(data))
                self.assertIn("chunk version %d" % version, str(cm.exception))
        data = bytearray(g3.data("w1_minimal"))
        data[0x2F0 + 8:0x2F0 + 10] = struct.pack(">H", 33)
        res = api.load_map_variant(bytes(data))
        codes = [w.code for w in res.warnings]
        self.assertIn("W_CHUNK_VERSION_UNEXPECTED", codes)
        self.assertIn("W_VERSION_MISMATCH", codes)
        data[0x2F0 + 8:0x2F0 + 10] = struct.pack(">H", 32)                   # chunk 32, body 31: only a mismatch warning
        codes = [w.code for w in api.load_map_variant(bytes(data)).warnings]
        self.assertIn("W_VERSION_MISMATCH", codes)
        self.assertNotIn("W_CHUNK_VERSION_UNEXPECTED", codes)

    def test_no_mvar_block(self):
        with self.assertRaises(errors.UnsupportedVariantError) as cm:
            api.load_map_variant(self.container_without_payload())
        self.assertTrue(str(cm.exception).startswith("No map variant block ('mvar') was found; blocks present: "))

    @staticmethod
    def container_without_payload():
        def blk(sig, version, flags, body):
            return struct.pack(">4sIHH", sig, 12 + len(body), version, flags) + body
        data = blk(b"_blf", 1, 2, bytes(36)) + blk(b"chdr", 10, 2, bytes(0x2C0 - 12))
        offset = len(data)
        return data + blk(b"_eof", 1, 1, struct.pack(">I", offset) + b"\x00")

    def test_game_variants_are_refused_with_the_7_2_sentence(self):
        import helpers_real
        samples = helpers_real.distinct_samples(helpers_real.load_samples())
        for s in samples:
            with self.subTest(s.name):
                with self.assertRaises(errors.UnsupportedVariantError) as cm:
                    api.load_map_variant(s.data)
                self.assertEqual(str(cm.exception), "This is a game variant (block 'mpvr'), not a map variant. Use File > Import for map variants only.")


class TestRobustness(unittest.TestCase):
    """Corrupted input must raise only library errors, and the report must never raise (a seeded mini fuzz)."""

    def corruptions(self, base, rnd, count, span):
        for _ in range(count):
            data = bytearray(base)
            mode = rnd.choice(["flip_stream", "flip_any", "byte_stream", "truncate"])
            if mode == "flip_stream":
                for _ in range(rnd.choice([1, 1, 2, 5])):
                    data[0x2F0 + 36 + rnd.randrange(span)] ^= 1 << rnd.randrange(8)
            elif mode == "flip_any":
                data[rnd.randrange(len(data))] ^= 1 << rnd.randrange(8)
            elif mode == "byte_stream":
                data[0x2F0 + 36 + rnd.randrange(min(span, 4000))] = rnd.randrange(256)
            else:
                data = data[:rnd.randrange(len(data))]
            yield bytes(data)

    def test_load_raises_only_library_errors(self):
        import random
        rnd = random.Random(20261010)
        outcomes = {}
        for name in ("w1_minimal", "holes", "labels_compressed", "type19_flag8", "v32", "extremes", "cmp", "fsm"):
            for data in self.corruptions(g3.data(name), rnd, 40, 0x7000):
                try:
                    res = api.load_map_variant(data)
                    outcomes["ok"] = outcomes.get("ok", 0) + 1
                    self.assertEqual(MapVariant.from_bytes(data).to_bytes(force=False), data)           # whatever loads is passthrough-exact
                    self.assertEqual(res.info.occupied, len(res.objects))
                except errors.MvarError as exc:
                    outcomes[type(exc).__name__] = outcomes.get(type(exc).__name__, 0) + 1
                    self.assertTrue(str(exc))
        self.assertGreater(len(outcomes), 2)                                               # the corruptions reach several kinds of error

    def test_the_report_never_raises(self):
        import random
        from mvarlib import report
        rnd = random.Random(7)
        for data in self.corruptions(g3.data("w1_minimal"), rnd, 25, 0x7000):
            rep = report.build_report(data)
            text = report.format_report(rep)
            self.assertIn("verify_mvar report", text)
            self.assertIn(rep.exit_code, (0, 1, 2, 3))
            if rep.exit_code:
                self.assertTrue(rep.failure)


if __name__ == "__main__":
    unittest.main()
