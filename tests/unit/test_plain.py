"""U-14 (SPEC 9.3, 6.6, tier T2): the plain-dict / JSON form.

* ``to_plain`` output is JSON-safe (``json.dumps`` without a ``default``), lists only present slots, writes 64-bit values
  and byte strings as hex strings and carries the raw ranges;
* ``from_plain(to_plain(m)).to_bytes(force=True)`` equals the input for the plain shapes (the golden expanded file for
  the ``cmp`` shapes) for every fixture, also after a trip through JSON text;
* ``from_plain`` of a hand-written minimal dict builds a readable file, with a ``chdr`` that agrees with the header.
"""
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import helpers_g3 as g3  # noqa: E402

from mvarlib import api, errors, plain  # noqa: E402
from mvarlib.model import MapVariant  # noqa: E402


class TestToPlain(unittest.TestCase):
    def setUp(self):
        self.m = g3.model("w1_minimal")
        self.d = plain.to_plain(self.m)

    def test_json_safe_and_keyed_as_in_the_spec(self):
        text = json.dumps(self.d)                                   # no default=: every value is a plain JSON type
        self.assertEqual(json.loads(text), self.d)
        self.assertEqual(self.d["schema"], "mvarlib.plain/1")
        for key in ("container", "header", "body", "labels", "layout", "slots", "quotas", "tail_hex", "views"):
            self.assertIn(key, self.d)
        self.assertEqual([c["sig"] for c in self.d["container"]["chunks"]], ["_blf", "chdr", "mvar", "_eof"])
        self.assertEqual(self.d["container"]["shape"], "plain4")
        self.assertEqual(self.d["container"]["hash"], {"length_endian": ">", "recipe": "salted_be32"})
        self.assertEqual(self.d["container"]["length_class"], "ceil_end")
        self.assertEqual(self.d["container"]["eof_endian"], ">")
        self.assertIsNone(self.d["container"]["trailer_hex"])

    def test_only_present_slots_are_listed(self):
        self.assertEqual([s["index"] for s in self.d["slots"]], [1, 5, 650])
        s1 = self.d["slots"][0]
        self.assertEqual((s1["folder"], s1["item"], s1["pos"], s1["up_global"], s1["up_code"], s1["angle"], s1["placement"]),
                         (70, 0, [524288, 1048576, 262144], 1, None, 8192, 204))
        s5 = self.d["slots"][1]
        self.assertEqual((s5["shape"], s5["dims"], s5["spawn_seq"], s5["cached_type"], s5["label"]), (3, [2047, 1024, 0, 2046], -5, 26, 1))
        s650 = self.d["slots"][2]
        self.assertEqual((s650["up_global"], s650["up_code"], s650["parent_raw"], s650["color"]), (0, 436468, 2, 7))

    def test_hex_fields(self):
        h = self.d["header"]
        self.assertEqual(h["ids"], ["0x0123456789ABCDEF", "0x0F1E2D3C4B5A6978", "0x1122334455667788", "0x0000000000000000"])
        self.assertEqual(h["created_by"]["xuid"], "0x0000000000000000")
        self.assertEqual(h["created_by"]["name_hex"], "4100")
        self.assertEqual((h["title"], h["description"]), ("W1 minimal", "synthetic reference fixture"))
        self.assertEqual(h["raw_bits"], 1255)
        self.assertEqual(len(h["raw_hex"]), 2 * 157)               # 1255 bits padded to 157 bytes
        b = self.d["body"]
        self.assertEqual((b["checksum"], b["palette_crc"]), ("0xFFFFFFFF", "0xDEADBEEF"))
        self.assertEqual(b["bounds_hex"], ["c3700000", "43700000", "c3ac8000", "43ac8000", "c28c0000", "428c0000"])
        self.assertIsNone(b["guid_hex"])
        lab = self.d["labels"]
        self.assertEqual((lab["entries"], lab["data_length"], lab["compressed"]), ([0, 6, 20], 26, False))
        self.assertEqual(bytes.fromhex(lab["buffer_hex"]), b"SCALE\x00Kill Boundary\x00Spawn\x00")
        self.assertIsNone(lab["comp_hex"])
        self.assertEqual(self.d["layout"], {"type19": "flag8", "axis_bits": [20, 21, 19], "guid": False})
        self.assertEqual(self.d["tail_hex"], "")                    # an all-zero tail is not written out
        self.assertEqual(self.d["tail_bits"], 0x7000 * 8 - 4970)
        self.assertEqual(self.d["quotas"][61], [0, 1, 1])
        self.assertEqual(self.d["quotas"][70], [0, 16, 2])
        self.assertEqual(len(self.d["quotas"]), 80)

    def test_views_are_informative_and_ignored(self):
        v = self.d["views"]
        self.assertEqual(v["map_name"], "Forge World")
        self.assertEqual([o["slot"] for o in v["objects"]], [1, 5, 650])
        changed = copy.deepcopy(self.d)
        changed["views"] = {"note": "garbage"}
        self.assertEqual(plain.from_plain(changed).to_bytes(force=True), g3.data("w1_minimal"))

    def test_compressed_labels_and_guid_and_cmp_info(self):
        d = plain.to_plain(g3.model("labels_compressed"))
        self.assertTrue(d["labels"]["compressed"])
        self.assertTrue(d["labels"]["comp_hex"].startswith("0000" ))            # the u32 BE uncompressed size prefix (281 = 0x119)
        self.assertEqual(bytes.fromhex(d["labels"]["comp_hex"])[4:6], b"\x78\xda")
        d = plain.to_plain(g3.model("v32"))
        self.assertEqual(len(d["body"]["guid_hex"]), 32)
        self.assertTrue(d["layout"]["guid"])
        d = plain.to_plain(g3.model("cmp"))
        self.assertEqual(d["container"]["shape"], "cmp4")
        self.assertEqual(d["container"]["cmp"], {"ctype": 0, "usize": 0x7028})
        d = plain.to_plain(g3.model("trailer"))
        self.assertEqual(d["container"]["trailer_hex"], "00" * 512)
        d = plain.to_plain(g3.model("fsm"))
        self.assertEqual([c["sig"] for c in d["container"]["chunks"]][-1], "_fsm")

    def test_nonzero_tail_is_written_out(self):
        data = bytearray(g3.data("w1_minimal"))
        data[0x2F0 + 36 + 700] = 0x5A
        d = plain.to_plain(MapVariant.from_bytes(bytes(data)))
        self.assertNotEqual(d["tail_hex"], "")
        self.assertEqual(plain.from_plain(d).to_bytes(force=True), bytes(data))


class TestFromPlain(unittest.TestCase):
    def test_json_round_trip_of_every_fixture(self):
        for name in g3.positive_names():
            with self.subTest(name):
                text = json.dumps(plain.to_plain(g3.model(name)), sort_keys=True)
                m2 = plain.from_plain(json.loads(text))
                expected = g3.data(name + "_expanded") if g3.spec(name)["container"]["shape"].startswith("cmp") else g3.data(name)
                self.assertEqual(m2.to_bytes(force=True), expected)
                self.assertEqual(m2.to_bytes(force=False), expected)
                self.assertEqual(plain.to_plain(m2)["slots"], plain.to_plain(g3.model(name))["slots"])

    def test_plain_form_is_stable(self):
        a = json.dumps(plain.to_plain(g3.model("holes")), sort_keys=True)
        b = json.dumps(plain.to_plain(plain.from_plain(json.loads(a))), sort_keys=True)
        self.assertEqual(a, b)

    def test_hand_written_minimal_dict(self):
        d = {
            "schema": "mvarlib.plain/1",
            "header": {"content_type_raw": 6, "map_id": 3006, "game_mode": 4, "engine": 1, "title": "Hand", "description": "made by hand",
                       "created_by": {"name_hex": "4100"}, "modified_by": {"name_hex": "4100"}},
            "body": {"version": 31, "quota_count": 4, "palette_crc": "0x12345678", "bounds": [-100.0, 100.0, -100.0, 100.0, -50.0, 50.0]},
            "labels": {"entries": [0, None], "buffer_hex": "686900"},
            "slots": [{"index": 3, "folder": 1, "item": 0, "pos": [10, 20, 30], "label": 0, "cached_type": 1, "extra": [4]}],
            "quotas": [[0, 0, 0], [0, 5, 1], [0, 0, 0], [0, 0, 0]],
        }
        m = plain.from_plain(d)
        data = m.to_bytes(force=False)
        self.assertEqual(len(data), 29481)
        res = api.load_map_variant(data)
        self.assertEqual(res.info.map_id, 3006)
        self.assertEqual((res.info.title, res.info.description), ("Hand", "made by hand"))
        self.assertEqual(res.info.labels, ["hi", ""])
        self.assertEqual(res.info.label_present, [True, False])
        self.assertEqual((res.info.quota_count, res.info.palette_crc, res.info.version), (4, 0x12345678, 31))
        self.assertEqual(res.info.bounds, (-100.0, 100.0, -100.0, 100.0, -50.0, 50.0))
        self.assertEqual(len(res.objects), 1)
        o = res.objects[0]
        self.assertEqual((o.slot, o.folder, o.item, o.label_index, o.cached_type, o.other_a), (3, 1, 0, 0, 1, 4))
        self.assertEqual(res.info.hash_flavour, "salted_be32/>")
        codes = [w.code for w in res.warnings]
        self.assertNotIn("W_CHDR_MISMATCH", codes)
        self.assertNotIn("W_FILE_LENGTH_MISMATCH", codes)
        self.assertEqual(MapVariant.from_bytes(data).to_bytes(force=True), data)
        self.assertEqual(m.to_bytes(force=True), data)

    def test_defaults_for_an_almost_empty_dict(self):
        m = plain.from_plain({"schema": "mvarlib.plain/1"})
        self.assertEqual(m.occupied, 0)
        self.assertEqual(m.fixed.quota_count, 0)
        self.assertEqual(m.to_bytes(force=True), m.to_bytes(force=False))

    def test_refusals(self):
        with self.assertRaises(errors.EncodeError):
            plain.from_plain({"schema": "nope/1"})
        d = plain.to_plain(g3.model("w1_minimal"))
        bad = copy.deepcopy(d)
        bad["quotas"] = bad["quotas"][:5]
        with self.assertRaises(errors.EncodeError):
            plain.from_plain(bad)
        bad = copy.deepcopy(d)
        bad["slots"][0]["pos"][0] = 1 << 20                       # does not fit 20 bits
        with self.assertRaises(errors.EncodeError):
            plain.from_plain(bad)
        bad = copy.deepcopy(d)
        bad["slots"][0]["index"] = 700
        with self.assertRaises(errors.EncodeError):
            plain.from_plain(bad)
        bad = copy.deepcopy(d)
        bad["body"]["guid_hex"] = "00" * 5
        with self.assertRaises(errors.EncodeError):
            plain.from_plain(bad)

    def test_header_from_fields_when_there_is_no_raw_range(self):
        d = plain.to_plain(g3.model("hdr_campaign"))
        del d["header"]["raw_hex"]
        del d["header"]["raw_bits"]
        m = plain.from_plain(d)
        self.assertEqual(m.header.campaign.unk, 0x01020304)
        self.assertEqual(m.header.raw.nbits, 1307)
        d2 = plain.to_plain(g3.model("hdr_hopper"))
        del d2["header"]["raw_hex"]
        del d2["header"]["raw_bits"]
        self.assertEqual(plain.from_plain(d2).header.hopper_id, 0x1234)
        d3 = plain.to_plain(g3.model("hdr_firefight"))
        del d3["header"]["raw_hex"]
        del d3["header"]["raw_bits"]
        self.assertEqual(plain.from_plain(d3).header.firefight.unk, 0xA0B0C0D0)


if __name__ == "__main__":
    unittest.main()
