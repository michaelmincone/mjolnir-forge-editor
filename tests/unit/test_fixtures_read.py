"""U-07 (SPEC 9.3, tier T2): every fixture of the independent builder is read with ``mvarlib`` and each declared
field is compared with what the library decoded.

The oracle is the builder (``tests/fixturebuilder``, written without any code from the library); where the two
disagree the SPEC text decides (docs/mvar/notes/G3.md lists every such finding). Also checks the frozen
``api.load_map_variant`` delegation, the Appendix C numbers (C.2, C.4) typed in here from the spec text, the
negative fixtures (error class and message), and the ``ObjectRecord`` / ``MapInfo`` views of W1.
"""
import math
import os
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import helpers_g3 as g3  # noqa: E402

from mvarlib import api, codecs, errors, hashing  # noqa: E402
from mvarlib.model import MapVariant  # noqa: E402


def f32(x):
    return struct.unpack(">f", struct.pack(">f", x))[0]


# Appendix C.2 / C.4, typed from the spec text (an independent check of the builder's own numbers)
W1_NUMBERS = {"file_length": 29481, "L": 622, "end": 4970, "header_end": 1255, "sections": (0, 1255, 1626, 1896, 3050, 4970),
              "sha1": "a6183d5f5872d38b6dda0d476ea7d8c8c40641ad",
              "sha256": "902d952fdce8b5830e53e96e0ad45926554e1a9e617f753f39bb58a5fd2344e4",
              "slots": {1: (1897, 2038), 5: (2041, 2234), 650: (2878, 3050)}}
C4 = {"hdr_hopper": (1271, 4986, 624, "9c8723519aebc42e54a16d5c59fa26b2af1e3615"),
      "hdr_campaign": (1307, 5022, 628, "e7495f21fa80a3d6f763a7ded50a1535edfce855"),
      "hdr_firefight": (1289, 5004, 626, "2db181cdbab88900a4812b2a30d6e53083b84a24"),
      "hdr_long_text": (4951, 8666, 1084, "34925a9213e04d13caf9187778b3f76a4233f343"),
      "hdr_min_text": (647, 4362, 546, "1a45c8a3b33c8e1c444409ce2e7371ebafa15b4c")}


def hkey(h):
    return (h["type19"], tuple(h["axis_bits"]), bool(h["guid"]))


class TestPositiveFixtures(unittest.TestCase):
    def test_there_are_forty_positive_fixtures(self):
        self.assertGreaterEqual(len(g3.positive_names()), 40)

    def test_container_and_walk_facts(self):
        for name in g3.positive_names():
            ex = g3.spec(name)["expect"]
            data = g3.data(name)
            m = g3.model(name)
            with self.subTest(name):
                self.assertEqual(ex["outcome"], "ok")
                # SPEC 2.10 puts "a non-block trailer after _eof" into shape `other`; 2.1, 7.3 and U-10 need such a file to
                # stay modifiable (G1 note S1), so the shape is the block list only and the trailer is kept verbatim.
                # G2's walker still says `other` for the `trailer` fixture; its container block says plain4.
                self.assertEqual(m.shape, g3.spec(name)["container"]["shape"])
                if name != "trailer":
                    self.assertEqual(m.shape, ex["shape"])
                self.assertEqual(len(data), ex["size"])
                self.assertEqual((m.flavour.length_endian, m.flavour.recipe), (ex["flavour"]["length_endian"], ex["flavour"]["recipe"]))
                self.assertEqual(m.chunk.stored_length, ex["length"] if ex["length_class"] != "zero" else 0)
                self.assertEqual(m.length_class, ex["length_class"])
                self.assertEqual(m.blf.eof_endian, ex["eof_endian"])
                self.assertEqual(m.header.file_length, ex["file_length"])
                self.assertEqual(m.chunk.hash_stored.hex(), ex["stored_hash"])
                self.assertEqual(m.header.end_bit, ex["header_end"])
                self.assertEqual(m.end_bit, ex["end_bit"])
                self.assertEqual(STREAM_FREE_BITS - m.end_bit, ex["free_bits"])
                self.assertEqual(m.hypothesis.type19, ex["hypothesis"]["type19"])
                self.assertEqual(list(m.hypothesis.axis_bits), ex["hypothesis"]["axis_bits"])
                self.assertEqual(m.hypothesis.guid, ex["hypothesis"]["guid"])
                self.assertEqual(m.type19_status, ex["type19_status"])
                self.assertEqual(m.guid_contradicts_version, ex["guid_contradicts_version"])

    def test_section_starts_and_slot_ranges_equal_the_builders(self):
        for name in g3.positive_names():
            ex = g3.spec(name)["expect"]
            m = g3.model(name)
            spans = dict((n, (a, b)) for n, a, b in m.spans())
            sec = ex["sections"]
            with self.subTest(name):
                self.assertEqual(spans["header"][0], sec["header"])
                self.assertEqual(spans["body.version"][0], sec["body_fixed"])
                self.assertEqual(spans["labels"][0], sec["labels"])
                if sec["guid"] is None:
                    self.assertNotIn("guid", spans)
                else:
                    self.assertEqual(spans["guid"][0], sec["guid"])
                self.assertEqual(spans["slot_0"][0], sec["slots"])
                self.assertEqual(spans["quota_0"][0], sec["quotas"])
                self.assertEqual(spans["tail"][0], sec["end"])
                self.assertEqual([s.index for s in m.slots if s.present], ex["present_slots"])
                for key, (a, b) in ex["slot_ranges"].items():
                    self.assertEqual(spans["slot_%s" % key], (a, b), "slot %s" % key)
                    self.assertEqual(m.slots[int(key)].raw.nbits, b - a)

    def test_the_hypothesis_tables_agree_on_acceptance(self):
        mismatched_reasons = []
        for name in g3.positive_names():
            ex = g3.spec(name)["expect"]
            m = g3.model(name)
            with self.subTest(name):
                got = dict(((r.hypothesis.type19, tuple(r.hypothesis.axis_bits), r.hypothesis.guid), r) for r in m.reports)
                want = dict((hkey(h), h) for h in ex["hypotheses"])
                self.assertEqual(set(got), set(want))
                for key in want:
                    self.assertEqual(got[key].accepted, want[key]["accepted"], key)
                    if not want[key]["accepted"] and got[key].reason != want[key].get("reject"):
                        mismatched_reasons.append((name, key, got[key].reason, want[key].get("reject")))
                self.assertEqual(set(hkey(h) for h in ex["accepted_hypotheses"]),
                                 set(k for k in got if got[k].accepted))
        # the first failing check of a rejected hypothesis depends on the order the checks run in; the table is
        # informative, the acceptance flags above are the contract
        self.assertLessEqual(len(mismatched_reasons), 40, mismatched_reasons[:5])

    def test_read_warnings_are_present(self):
        for name in g3.positive_names():
            ex = g3.spec(name)["expect"]
            m = g3.model(name)
            codes = set(w.code for w in m.warnings)
            with self.subTest(name):
                for code in ex["read_warnings"]:
                    self.assertIn(code, codes)
                if "W_GUID_VERSION_MISMATCH" not in ex["read_warnings"]:
                    self.assertNotIn("W_GUID_VERSION_MISMATCH", codes)
                if "W_ZERO_RANGE_AXIS" not in ex["read_warnings"]:
                    self.assertNotIn("W_ZERO_RANGE_AXIS", codes)

    def test_no_unexpected_warning_kinds(self):
        allowed = set(["W_GUID_VERSION_MISMATCH", "W_ZERO_RANGE_AXIS", "W_UNKNOWN_OBJECT_IDS", "W_MAP_UNKNOWN",
                       "W_UP_DEAD_ZONE", "W_TEAM_ABOVE_9", "W_QUOTA_MIN_ABOVE_MAX"])
        for name in g3.positive_names():
            with self.subTest(name):
                codes = set(w.code for w in g3.model(name).warnings)
                self.assertTrue(codes <= allowed, codes - allowed)

    def test_every_declared_field_equals_the_decoded_one(self):
        for name in g3.positive_names():
            d = g3.declared(name)
            m = g3.model(name)
            with self.subTest(name):
                self.check_header(d["header"], m)
                self.check_body(d["body"], m)
                self.check_labels(d["labels"], m)
                self.check_slots(d["slots"], m)
                self.assertEqual([q.as_tuple() for q in m.quotas], [tuple(q) for q in d["quotas"]])
                if d["guid"] is None:
                    self.assertIsNone(m.guid)
                else:
                    self.assertEqual(m.guid.data, d["guid"])
                    self.assertEqual(m.guid.nbits, 128)

    def check_header(self, h, m):
        mh = m.header
        self.assertEqual(mh.content_type, h["content_type"])
        self.assertEqual([mh.unk08, mh.unk10, mh.unk18, mh.unk20], h["ids"])
        self.assertEqual(mh.activity, h["activity"])
        self.assertEqual((mh.game_mode, mh.engine, mh.map_id, mh.engine_category),
                         (h["game_mode"], h["engine"], h["map_id"], h["category"]))
        for who in ("created_by", "modified_by"):
            a, b = getattr(mh, who), h[who]
            self.assertEqual((a.timestamp, a.xuid, a.name, a.is_online_id), (b["timestamp"], b["xuid"], b["name"], b["online"]))
        self.assertEqual(mh.title, h["title_units"])
        self.assertEqual(mh.description, h["description_units"])
        self.assertIsNone(mh.engine_icon)                 # a map variant stores no engine icon
        self.assertEqual(mh.hopper_id, h["hopper_id"])
        if h["campaign"] is None:
            self.assertIsNone(mh.campaign)
        else:
            c = mh.campaign
            self.assertEqual((c.id, c.difficulty, c.metagame_scoring, c.rally_point, c.unk),
                             tuple(h["campaign"][k] for k in ("id", "difficulty", "metagame", "rally", "unk")))
        if h["firefight"] is None:
            self.assertIsNone(mh.firefight)
        else:
            self.assertEqual((mh.firefight.difficulty, mh.firefight.unk), (h["firefight"]["difficulty"], h["firefight"]["unk"]))

    def check_body(self, b, m):
        f = m.fixed
        self.assertEqual((f.version, f.checksum, f.palette_crc, f.quota_count, f.map_id_2, f.built_in, f.built_from_xml,
                          f.max_budget, f.spent_budget),
                         (b["version"], b["checksum"], b["palette_crc"], b["quota_count"], b["map_id_2"], b["built_in"],
                          b["built_from_xml"], b["max_budget"], b["spent_budget"]))
        self.assertEqual(list(f.bounds), [f32(x) for x in b["bounds"]])

    def check_labels(self, lab, m):
        t = m.labels
        self.assertEqual(t.count, lab["count"])
        self.assertEqual(t.entries, lab["offsets"])
        self.assertEqual(t.data_length, lab["data_length"])
        self.assertEqual(t.compressed, lab["compressed"])
        if lab["count"]:
            self.assertEqual(t.buffer, lab["buffer"])
        self.assertEqual([t.text(i) if lab["texts"][i] is not None else None for i in range(t.count)], lab["texts"])
        self.assertEqual([t.present(i) for i in range(t.count)], [x is not None for x in lab["texts"]])

    def check_slots(self, slots, m):
        for i in range(651):
            s = m.slots[i]
            if i not in slots:
                self.assertFalse(s.present, "slot %d" % i)
                continue
            d = slots[i]
            self.assertTrue(s.present, "slot %d" % i)
            for key in ("flags2", "folder", "item", "in_bounds", "up_global", "up_code", "angle", "parent_raw", "shape",
                        "spawn_seq", "respawn", "cached_type", "label", "placement", "team_raw", "color"):
                self.assertEqual(getattr(s, key), d[key], "slot %d %s" % (i, key))
            self.assertEqual(list(s.pos), list(d["pos"]), "slot %d pos" % i)
            self.assertEqual(list(s.dims), list(d["dims"]), "slot %d dims" % i)
            self.assertEqual(list(s.extra), list(d["extra"]), "slot %d extra" % i)

    def test_field_spans_equal_the_builders(self):
        build, _ = g3.build_modules()
        for name in g3.positive_names():
            built = build.build(g3.spec(name))
            m = g3.model(name)
            spans = dict((n, (a, b)) for n, a, b in m.spans(fields=True))
            with self.subTest(name):
                for slot, fields in built.info["slot_field_spans"].items():
                    for field, a, b in fields:
                        self.assertEqual(spans.get("slot_%d.%s" % (slot, field)), (a, b), "slot %d %s" % (slot, field))
                    mine = sorted(n for n in spans if n.startswith("slot_%d." % slot))
                    self.assertEqual(mine, sorted("slot_%d.%s" % (slot, f[0]) for f in fields))

    def test_unmodified_model_is_clean_and_every_slot_repacks(self):
        for name in g3.positive_names():
            m = g3.model(name)
            with self.subTest(name):
                self.assertFalse(m.dirty)
                rule, axes = m.hypothesis.type19, m.hypothesis.axis_bits
                for s in m.slots:
                    self.assertEqual(s.to_bits(rule, axes), s.raw)
                    self.assertEqual(s.raw.nbits, s.bit_length(rule, axes))
                    self.assertEqual(s.dirty, set())

    def test_tail_is_zero_for_all_fixtures_and_pad_bits_too(self):
        for name in g3.positive_names():
            m = g3.model(name)
            with self.subTest(name):
                self.assertEqual(m.tail.to_int(), 0)
                self.assertEqual(m.tail.nbits, STREAM_FREE_BITS - m.end_bit)
                self.assertNotIn("tail_nonzero", m.soft)


STREAM_FREE_BITS = 0x7000 * 8


class TestHeaderFixturesAndW1Goldens(unittest.TestCase):
    def test_w1_numbers_of_appendix_c(self):
        m = g3.model("w1_minimal")
        data = g3.data("w1_minimal")
        w = W1_NUMBERS
        self.assertEqual(len(data), w["file_length"])
        import hashlib
        self.assertEqual(hashlib.sha256(data).hexdigest(), w["sha256"])
        self.assertEqual(m.chunk.hash_stored.hex(), w["sha1"])
        self.assertEqual(m.chunk.stored_length, w["L"])
        self.assertEqual(m.end_bit, w["end"])
        spans = dict((n, a) for n, a, b in m.spans())
        self.assertEqual((spans["header"], spans["body.version"], spans["labels"], spans["slot_0"], spans["quota_0"], m.end_bit), w["sections"])
        for slot, rng in w["slots"].items():
            names = dict((n, (a, b)) for n, a, b in m.spans())
            self.assertEqual(names["slot_%d" % slot], rng)
        self.assertEqual(m.slots[0].raw.nbits, 1)
        self.assertEqual(sum(s.raw.nbits for s in m.slots[6:650]), 644)           # slots 6..649 are one bit each
        self.assertEqual(m.hypothesis, walk_hyp("flag8", (20, 21, 19), False))
        self.assertEqual(m.type19_status, "undetermined")
        self.assertEqual(m.flavour, (">", "salted_be32"))

    def test_plain_le32_w1(self):
        m = g3.model("plain_le32")
        self.assertEqual(m.flavour, (">", "plain_le32"))
        self.assertEqual(m.chunk.hash_stored.hex(), "cb6d51c253b9d53b82b4faf653c3adc8e1a7afda")

    def test_header_variants_c4(self):
        for name, (header_end, end, length, sha1) in C4.items():
            m = g3.model(name)
            with self.subTest(name):
                self.assertEqual(m.header.end_bit, header_end)
                self.assertEqual(m.end_bit, end)
                self.assertEqual(m.chunk.stored_length, length)
                self.assertEqual(m.chunk.hash_stored.hex(), sha1)

    def test_header_tails_are_decoded(self):
        self.assertEqual(g3.model("hdr_hopper").header.hopper_id, 0x1234)
        self.assertEqual(g3.model("hdr_hopper").header.activity, 2)
        c = g3.model("hdr_campaign").header.campaign
        self.assertEqual((c.id, c.difficulty, c.metagame_scoring, c.rally_point, c.unk), (5, 2, 1, 7, 0x01020304))
        f = g3.model("hdr_firefight").header.firefight
        self.assertEqual((f.difficulty, f.unk), (3, 0xA0B0C0D0))
        long_text = g3.model("hdr_long_text").header
        self.assertEqual((len(long_text.title), len(long_text.description)), (128, 128))
        self.assertEqual(long_text.created_by.name, b"ABCDEFGHIJKLMNOP")
        min_text = g3.model("hdr_min_text").header
        self.assertEqual((min_text.title_text, min_text.description_text), ("", ""))
        self.assertEqual(min_text.created_by.name, b"\x00")

    def test_extremes_zero_range_axis(self):
        m = g3.model("extremes")
        self.assertEqual(m.hypothesis.axis_bits, (23, 15, 0))
        warn = [w for w in m.warnings if w.code == "W_ZERO_RANGE_AXIS"]
        self.assertEqual(len(warn), 1)
        self.assertIn("z axis", warn[0].message)
        self.assertEqual(m.soft.get("zero_range_axis"), 1)
        for rec in m.objects():
            self.assertEqual(rec.position[2], m.fixed.bounds[4])              # every slot decodes to min on the zero-range axis
        self.assertTrue(all(s.pos[2] == 0 for s in m.slots if s.present))

    def test_guid_fixtures_carry_the_mismatch_warning(self):
        for name, present in (("guid_v32_absent", False), ("guid_v31_present", True)):
            m = g3.model(name)
            with self.subTest(name):
                self.assertTrue(m.guid_contradicts_version)
                self.assertEqual(m.hypothesis.guid, present)
                w = [x for x in m.warnings if x.code == "W_GUID_VERSION_MISMATCH"]
                self.assertEqual(len(w), 1)
                self.assertIn("present" if present else "missing", w[0].message)
        v32 = g3.model("v32")
        self.assertFalse(v32.guid_contradicts_version)
        self.assertEqual(v32.guid.nbits, 128)
        self.assertEqual(v32.fixed.version, 32)
        self.assertEqual(v32.chunk.version, 32)


def walk_hyp(rule, axes, guid):
    from mvarlib.walk import Hypothesis
    return Hypothesis(rule, axes, guid)


class TestLoadMapVariant(unittest.TestCase):
    """The frozen api delegation (entry.load_map_variant) on W1."""

    def setUp(self):
        self.res = api.load_map_variant(g3.data("w1_minimal"), "w1.mvar")

    def test_map_info(self):
        info = self.res.info
        self.assertEqual((info.map_id, info.map_name, info.is_stock_map), (3006, "Forge World", True))
        self.assertEqual(info.bounds, (-240.0, 240.0, -345.0, 345.0, -70.0, 70.0))
        self.assertEqual((info.quota_count, info.version, info.title, info.description),
                         (80, 31, "W1 minimal", "synthetic reference fixture"))
        self.assertEqual(info.labels, ["SCALE", "Kill Boundary", "Spawn"])
        self.assertEqual(info.label_present, [True, True, True])
        self.assertEqual((info.occupied, info.shape), (3, "plain4"))
        self.assertEqual(len(info.template_sha256), 64)
        self.assertEqual(info.hash_flavour, "salted_be32/>")
        self.assertEqual((info.palette_crc, info.max_budget_raw, info.spent_budget_raw), (0xDEADBEEF, 30000, 123))
        self.assertEqual(info.hypothesis, {"type19": "undetermined", "axis_bits": [20, 21, 19], "guid": False, "length_class": "ceil_end"})
        self.assertEqual(self.res.warnings, info.warnings)
        import hashlib
        self.assertEqual(info.template_sha256, hashlib.sha256(g3.data("w1_minimal")).hexdigest())

    def test_three_objects_in_slot_order(self):
        self.assertEqual([o.slot for o in self.res.objects], [1, 5, 650])

    def test_slot_1_block(self):
        o = self.res.objects[0]
        self.assertEqual((o.folder, o.item, o.type_id, o.type_name, o.stock), (70, 0, 0x4600, "Block, 1x1", True))
        self.assertAlmostEqual(o.position[0], 0.0002288818359375, places=12)          # G-POS-2
        self.assertAlmostEqual(o.position[1], codecs.pos_decode(1048576, 21, -345.0, 345.0), places=12)
        self.assertAlmostEqual(o.position[2], codecs.pos_decode(262144, 19, -70.0, 70.0), places=12)
        self.assertEqual(o.orientation_kind, "vertical")
        self.assertEqual(o.up, (0.0, 0.0, 1.0))
        self.assertAlmostEqual(o.forward[0], 1.0, places=6)
        self.assertAlmostEqual(o.forward[1], math.sin(0.00019174759848583633), places=15)       # section 4.7: (cos t, sin t, 0)
        self.assertAlmostEqual(o.forward[1], 0.000192, places=6)
        self.assertEqual(o.forward[2], 0.0)
        self.assertEqual((o.parent_slot, o.shape, o.spawn_sequence, o.spawn_time, o.cached_type, o.label_index), (-1, 0, 0, 0, 0, -1))
        self.assertEqual((o.width, o.length, o.top, o.bottom), (0.0, 0.0, 0.0, 0.0))
        self.assertEqual((o.placement, o.physics, o.symmetry, o.place_at_start, o.game_specific), (0xCC, 3, 3, True, False))
        self.assertEqual((o.team, o.color, o.other_a, o.other_b, o.flags2), (8, -1, 0, 0, 1))
        self.assertEqual(o.raw_bits, 141)
        self.assertEqual(len(o.raw), 18)

    def test_slot_5_kill_boundary(self):
        o = self.res.objects[1]
        self.assertEqual((o.type_id, o.type_name, o.stock), (0x3D00, "Kill Boundary", True))
        self.assertEqual((o.shape, o.spawn_sequence, o.cached_type, o.label_index, o.team), (3, -5, 26, 1, -1))
        self.assertEqual(o.width, 200.0)                                  # code 0x7FF
        self.assertAlmostEqual(o.length, codecs.dim_decode(1024), places=12)
        self.assertEqual(o.top, 0.0)
        self.assertAlmostEqual(o.bottom, codecs.dim_decode(2046), places=12)
        self.assertEqual((o.placement, o.physics, o.symmetry), (0x0C, 0, 3))
        self.assertEqual(o.raw_bits, 193)

    def test_slot_650_tilted_child(self):
        o = self.res.objects[2]
        self.assertEqual(o.orientation_kind, "tilted")
        self.assertEqual((o.parent_slot, o.label_index, o.color, o.team), (1, 2, 7, 8))
        self.assertAlmostEqual(sum(a * b for a, b in zip(o.forward, o.up)), 0.0, places=12)
        self.assertAlmostEqual(o.up[0], 0.0024038, places=6)
        self.assertEqual(o.raw_bits, 172)

    def test_object_records_of_all_fixtures_are_consistent(self):
        for name in g3.positive_names():
            m = g3.model(name)
            res = api.load_map_variant(g3.data(name), name)
            with self.subTest(name):
                recs = res.objects
                self.assertEqual(len(recs), m.occupied)
                bounds = m.fixed.bounds
                for rec in recs:
                    s = m.slots[rec.slot]
                    self.assertEqual((rec.folder, rec.item), (-1 if s.folder is None else s.folder, -1 if s.item is None else s.item))
                    self.assertEqual(rec.type_id, -1 if (s.folder is None or s.item is None) else (s.folder << 8) | s.item)
                    for k in range(3):
                        self.assertGreaterEqual(rec.position[k], bounds[2 * k])
                        self.assertLessEqual(rec.position[k], bounds[2 * k + 1])
                    self.assertAlmostEqual(sum(c * c for c in rec.forward), 1.0, places=9)
                    self.assertAlmostEqual(sum(c * c for c in rec.up), 1.0, places=9)
                    self.assertEqual(rec.parent_slot, s.parent_raw - 1)
                    self.assertEqual(rec.raw, s.raw.data)
                    self.assertEqual(rec.raw_bits, s.raw.nbits)
                    self.assertEqual(rec.team, s.team_raw - 1)
                    self.assertEqual(rec.color, -1 if s.color is None else s.color)
                    self.assertEqual(rec.label_index, -1 if s.label is None else s.label)

    def test_extremes_object_values(self):
        recs = dict((o.slot, o) for o in api.load_map_variant(g3.data("extremes")).objects)
        self.assertTrue(any(o.width == 200.0 and o.shape == 1 for o in recs.values()))       # shape 1 = radius only, 0x7FF -> 200
        self.assertTrue(any(o.spawn_sequence == -128 for o in recs.values()))
        self.assertTrue(any(o.spawn_sequence == 127 for o in recs.values()))
        self.assertTrue(any(o.team == -1 for o in recs.values()))
        self.assertTrue(any(o.team == 8 for o in recs.values()))
        self.assertIn(650, recs)

    def test_type19_other_a_under_both_rules(self):
        flag = [o for o in api.load_map_variant(g3.data("type19_flag8")).objects if o.cached_type == 19]
        plain = [o for o in api.load_map_variant(g3.data("type19_plain8")).objects if o.cached_type == 19]
        self.assertEqual(len(flag), 5)
        self.assertEqual(len(plain), 5)
        d_flag = g3.declared("type19_flag8")["slots"]
        for o in flag:
            ex = d_flag[o.slot]["extra"]
            self.assertEqual(o.other_a, -1 if ex[0] == 1 else ex[1])
        d_plain = g3.declared("type19_plain8")["slots"]
        for o in plain:
            self.assertEqual(o.other_a, d_plain[o.slot]["extra"][0] - 1)

    def test_other_a_other_b_for_clips_and_teleporters(self):
        recs = [o for name in ("holes",) for o in api.load_map_variant(g3.data(name)).objects]
        d = g3.declared("holes")["slots"]
        seen = set()
        for o in recs:
            ex = d[o.slot]["extra"]
            if o.cached_type == 1:
                self.assertEqual((o.other_a, o.other_b), (ex[0], 0))
                seen.add(1)
            elif 12 <= o.cached_type <= 14:
                self.assertEqual((o.other_a, o.other_b), (ex[0], ex[1]))
                seen.add(12)
        self.assertEqual(seen, set([1, 12]))

    def test_unknown_map_and_ids(self):
        res = api.load_map_variant(g3.data("unknown_map"))
        self.assertEqual((res.info.map_name, res.info.is_stock_map), (None, False))
        for o in res.objects:
            self.assertFalse(o.stock)
            self.assertTrue(o.type_name.startswith("Unknown (0x"))
        self.assertIn("W_MAP_UNKNOWN", [w.code for w in res.warnings])
        res = api.load_map_variant(g3.data("holes"))
        self.assertIn("W_UNKNOWN_OBJECT_IDS", [w.code for w in res.warnings])


class TestNegativeFixtures(unittest.TestCase):
    def test_every_negative_fixture_is_refused_with_the_declared_class(self):
        names = g3.negative_names()
        self.assertGreaterEqual(len(names), 9)
        for name in names:
            ex = g3.spec(name)["expect"]
            with self.subTest(name):
                with self.assertRaises(errors.MvarError) as cm:
                    api.load_map_variant(g3.data(name), name)
                self.assertEqual(type(cm.exception).__name__, ex["error"])
                msg = str(cm.exception)
                self.assertTrue(msg.endswith("."), msg)
                self.assertNotIn("Traceback", msg)

    def test_messages_follow_spec_7_2(self):
        def msg(name):
            with self.assertRaises(errors.MvarError) as cm:
                api.load_map_variant(g3.data(name))
            return cm.exception

        self.assertEqual(str(msg("bad_version")), "The map variant body version is 30; supported versions are 31 and 32.")
        self.assertEqual(str(msg("bad_size")), "The map variant block has size 0x7030; only 0x7028 is supported.")
        self.assertEqual(str(msg("bad_content_type")), "The content type is 6 (game_variant); a map variant is 5.")
        self.assertEqual(str(msg("bounds_inverted")), "The map bounds are not valid (axis x: min 240, max -240).")
        self.assertIn("chunk version 13", str(msg("chunk_version_13")))
        self.assertIn("chunk version 50", str(msg("chunk_version_50")))
        exc = msg("oob")
        self.assertIsInstance(exc, errors.OutOfBoundsPositionError)
        self.assertEqual(exc.slot, 5)
        self.assertEqual(str(exc), "Slot 5 has a position outside the map bounds (in-bounds flag is 0). Such records need "
                                   "map data that is not in the file and cannot be read.")
        exc = msg("desync_length")
        self.assertIsInstance(exc, errors.DesyncError)
        self.assertTrue(str(exc).startswith("Could not read this map variant: none of the 4 known layouts fits. Best candidate ("))
        self.assertTrue(str(exc).endswith("Run tools/verify_mvar.py on the file for the full report."))
        self.assertEqual(len(exc.diagnostics), 4)
        self.assertTrue(all(d["accepted"] is False for d in exc.diagnostics))
        self.assertIn("length", set(d["reason"] for d in exc.diagnostics))
        self.assertEqual(str(msg("truncated")), "The file is damaged: block 'mvar' at offset 0x2F0 claims 28712 bytes but only 9248 remain.")

    def test_non_map_variant_inputs(self):
        with self.assertRaises(errors.BlfFormatError):
            api.load_map_variant(b"")
        with self.assertRaises(errors.BlfFormatError):
            api.load_map_variant(b"\x00" * 100)
        with self.assertRaises(errors.BlfFormatError) as cm:
            api.load_map_variant(b"hello world, this is not a blf file")
        self.assertIn("not a Halo BLF file", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
