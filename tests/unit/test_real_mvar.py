"""T3-real (SPEC 9.1, NOTES.md D9): the one real Halo: Reach map variant, ``0aaaf8c7-...mvar`` ("Headstrong", Breakneck).

The file is a read-only original outside the repository (``~/Local_Documents/Halo-MCC/forge/real-mvar-samples``); this test opens it
``rb`` in place, never copies it into the repository and never writes next to it. Rebuilds and edits happen in memory;
the only files written (the CLI checks) go to a private temp directory. Without the file the whole module is SKIPPED
with a loud notice. The numbers pinned here were read off the real file by the decoder and cross-checked in several
independent ways (see docs/mvar/notes/G3.md and real_mvar_0aaaf8c7.md): the walk ends at exactly the stored length,
the header agrees with ``chdr``, ``placed`` equals the number of present slots in all 82 quota rows, and every one of
the 610 object ids resolves in the Breakneck stock table.
"""
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import helpers_g3 as g3  # noqa: E402

from mvarlib import api, hashing, labels, plain, tables  # noqa: E402
from mvarlib.model import MapVariant  # noqa: E402

REAL_SHA256 = "e514a53b61977a897ac9dbf7225085aa01b5b255f3c8079b5938ef87579bb254"
VERIFY = os.path.join(g3.REPO, "tools", "verify_mvar.py")
DUMP = os.path.join(g3.REPO, "tools", "dump_mvar.py")


def require_real():
    if not g3.real_available():
        sys.stderr.write("\n" + "=" * 78 + "\nNOTICE: the real map variant %s is absent;\n"
                         "        T3-real (test_real_mvar) is SKIPPED, not passed.\n" % g3.REAL_MVAR + "=" * 78 + "\n")
        raise unittest.SkipTest("NOTICE: the real map variant is absent (%s); T3-real is skipped" % g3.REAL_MVAR)


class RealCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_real()
        cls.data = g3.real_data()
        cls.sha_before = hashlib.sha256(cls.data).hexdigest()
        cls.model = MapVariant.from_bytes(cls.data, None, "real")

    @classmethod
    def tearDownClass(cls):
        with open(g3.REAL_MVAR, "rb") as handle:
            after = hashlib.sha256(handle.read()).hexdigest()
        assert after == cls.sha_before, "the real sample changed during the test"


class TestContainer(RealCase):
    def test_the_file_is_the_recorded_original(self):
        self.assertEqual(len(self.data), 59392)
        self.assertEqual(self.sha_before, REAL_SHA256)

    def test_shape_plain4_plus_a_zero_trailer(self):
        m = self.model
        self.assertEqual(m.shape, "plain4")
        self.assertEqual([c.sig for c in m.blf.chunks], ["_blf", "chdr", "mvar", "_eof"])
        self.assertEqual(len(m.blf.trailer), 29911)
        self.assertEqual(m.blf.trailer, bytes(29911))
        self.assertEqual(m.blf.chunks[m.blf.eof_index].offset + m.blf.chunks[m.blf.eof_index].size, 29481)
        self.assertEqual((m.chunk.version, m.chunk.flags, m.chunk.size), (31, 1, 0x7028))
        self.assertEqual(m.blf.eof_endian, ">")
        self.assertTrue(m.blf.eof_value_ok)

    def test_flavour_and_hash_reproduce(self):
        m = self.model
        self.assertEqual(m.flavour, (">", "plain_le32"))
        self.assertEqual(m.chunk.length_endian, ">")
        self.assertEqual(m.chunk.stored_length, 13311)
        self.assertEqual(m.chunk.length_raw, bytes.fromhex("000033ff"))
        stream = self.data[0x2F0 + 36:0x2F0 + 36 + 13311]
        digest = hashlib.sha1(struct.pack("<I", 13311) + stream).digest()           # computed here, not by the library
        self.assertEqual(digest.hex(), "b41f6cb0fabe27fc9b22a607c0a9c9ca51c344e3")
        self.assertEqual(m.chunk.hash_stored, digest)
        self.assertEqual(hashing.compute(m.flavour, m.chunk.stream, 13311), digest)
        for cand in m.chunk.analysis.candidates:                                   # no other recipe matches
            self.assertEqual(cand[3], cand[1] == "plain_le32", cand)

    def test_passthrough_and_forced_rebuild_equal_the_input(self):
        self.assertEqual(self.model.to_bytes(force=False), self.data)
        forced = self.model.render(force=True)
        self.assertEqual(forced.data, self.data)                                    # the 29,911-byte trailer verbatim as well
        self.assertEqual(forced.issues, [])
        self.assertEqual(self.model.blf.to_bytes(force=True, stream_length={"mvar": 13311}), self.data)

    def test_only_the_expected_bytes_are_ever_derived(self):
        # re-stamping from the recorded facts: the hash and L fields of a forced rebuild are the stored ones
        forced = self.model.to_bytes(force=True)
        self.assertEqual(forced[0x2F0 + 12:0x2F0 + 36], self.data[0x2F0 + 12:0x2F0 + 36])
        self.assertEqual(forced[0x7318:0x7329], self.data[0x7318:0x7329])


class TestWalk(RealCase):
    def test_full_walk_acceptance(self):
        m = self.model
        self.assertEqual(m.hypothesis.axis_bits, (23, 23, 23))
        self.assertEqual((m.hypothesis.type19, m.type19_status, m.hypothesis.guid), ("flag8", "undetermined", False))
        self.assertFalse(m.guid_contradicts_version)
        self.assertFalse(m.lenient)
        self.assertEqual(m.length_class, "ceil_end")
        self.assertEqual(m.end_bit, 106487)
        self.assertEqual((m.end_bit + 7) // 8, 13311)                               # the file's own stored length
        self.assertEqual(len(m.slots), 651)
        self.assertEqual(m.occupied, 610)
        self.assertEqual(len(m.free_slots()), 41)
        self.assertEqual(len(m.quotas), 82)
        self.assertEqual(m.fixed.quota_count, 82)
        self.assertEqual(m.soft, {})                                                # not one soft-check finding at all
        self.assertEqual(m.tail.to_int(), 0)
        self.assertEqual(m.tail.nbits, 0x7000 * 8 - 106487)

    def test_every_hypothesis_but_one_group_is_rejected(self):
        accepted = [r for r in self.model.reports if r.accepted]
        self.assertEqual(sorted((r.hypothesis.type19, r.hypothesis.guid) for r in accepted), [("flag8", False), ("plain8", False)])
        rejected = [r for r in self.model.reports if not r.accepted]
        self.assertEqual(len(rejected), 2)
        self.assertTrue(all(r.hypothesis.guid for r in rejected))                   # the 128-bit GUID reading desynchronises
        self.assertTrue(all(r.reason == "oob" for r in rejected))

    def test_there_is_no_type19_object_and_no_parent_link(self):
        slots = self.model.present_slots()
        self.assertEqual([s.index for s in slots if s.cached_type == 19], [])
        self.assertEqual([s.index for s in slots if s.parent_raw], [])              # so the parent encoding stays unverified

    def test_the_walk_is_independent_of_the_other_axis_variants(self):
        from mvarlib import codecs
        self.assertEqual(codecs.axis_bit_hypotheses(self.model.fixed.bounds), [(23, 23, 23)])      # one triple: the rounding variants agree

    def test_load_map_variant_through_the_api(self):
        res = api.load_map_variant(self.data, "real")
        info = res.info
        self.assertEqual((info.map_id, info.map_name, info.is_stock_map), (10050, "Breakneck", True))
        self.assertEqual((info.title, info.description), ("Headstrong", "A heavier Headlong."))
        self.assertEqual((info.quota_count, info.version, info.occupied, info.shape), (82, 31, 610, "plain4"))
        self.assertEqual(info.hash_flavour, "plain_le32/>")
        self.assertEqual(info.hypothesis, {"type19": "undetermined", "axis_bits": [23, 23, 23], "guid": False, "length_class": "ceil_end"})
        self.assertEqual(info.bounds, (-20000.0, 20000.0, -20000.0, 20000.0, -20000.0, 20000.0))
        self.assertEqual((info.palette_crc, info.max_budget_raw, info.spent_budget_raw), (0xE1DE4A26, 10000, 3885))
        self.assertEqual(len(info.labels), 21)
        self.assertEqual(info.label_present, [True] * 21)
        self.assertEqual(info.template_sha256, REAL_SHA256)
        self.assertEqual(len(res.objects), 610)
        self.assertEqual(info.warnings, [])                                         # a clean real file: no warning at all
        self.assertEqual(res.warnings, [])


class TestHeader(RealCase):
    def test_header_and_chdr_agree_with_the_task_facts(self):
        h = self.model.header
        self.assertEqual(h.content_type, 5)
        self.assertEqual(h.file_length, 29481)
        self.assertEqual(h.map_id, 10050)
        self.assertEqual(h.title_text, "Headstrong")
        self.assertEqual(h.description_text, "A heavier Headlong.")
        self.assertEqual((h.activity, h.game_mode, h.engine, h.engine_category), (4, 3, 0, 255))
        self.assertEqual(h.end_bit, 1327)
        self.assertEqual(h.created_by.timestamp, 1284422400)
        self.assertEqual(h.modified_by.timestamp, 1329462626)
        self.assertIsNone(h.hopper_id)
        self.assertIsNone(h.campaign)
        self.assertIsNone(h.firefight)
        c = self.model.chdr
        self.assertEqual((c["content_type"], c["file_length"], c["map_id"], c["title"], c["description"]),
                         (5, 29481, 10050, "Headstrong", "A heavier Headlong."))
        self.assertEqual(self.model.fixed.map_id_2, 10050)
        from mvarlib.ugc_header import compare_chdr_header
        self.assertEqual(compare_chdr_header(c, h, extended=True), [])             # every field of the extended comparison agrees

    def test_body_fixed_fields(self):
        f = self.model.fixed
        self.assertEqual((f.version, f.checksum, f.palette_crc, f.quota_count, f.built_in, f.built_from_xml),
                         (31, 0xFFFFFFFF, 0xE1DE4A26, 82, 0, 0))
        self.assertEqual((f.max_budget, f.spent_budget), (10000, 3885))
        self.assertEqual(f.raw.nbits, 371)

    def test_label_table(self):
        t = self.model.labels
        self.assertEqual((t.count, t.compressed, t.data_length, len(t.buffer), len(t.comp_bytes)), (21, True, 225, 225, 145))
        self.assertTrue(t.inflated_length_matches)
        self.assertEqual(t.entries[0], 0)
        self.assertEqual(t.undecodable(), [])
        reencoded = labels.encode_label_table(t.entries, t.buffer, True, None, t.data_length)
        self.assertEqual(reencoded, t.raw)                                          # zlib reproduces the stored block bit for bit
        used = set(s.label for s in self.model.present_slots() if s.label is not None)
        self.assertTrue(used and all(0 <= i < 21 for i in used))


class TestSlotsAndRecords(RealCase):
    def test_every_slot_repacks_identically(self):
        rule, axes = self.model.hypothesis.type19, self.model.hypothesis.axis_bits
        for s in self.model.slots:
            self.assertEqual(s.to_bits(rule, axes), s.raw, "slot %d" % s.index)
            self.assertEqual(s.bit_length(rule, axes), s.raw.nbits)

    def test_object_records_are_sane(self):
        m = self.model
        quota_count = m.fixed.quota_count
        bounds = m.fixed.bounds
        res = api.load_map_variant(self.data)
        non_stock = [o for o in res.objects if not o.stock]
        self.assertEqual(non_stock, [])                                             # all 610 ids resolve in the Breakneck table
        for o in res.objects:
            self.assertGreaterEqual(o.folder, 0)
            self.assertLess(o.folder, quota_count)
            self.assertTrue(0 <= o.item <= 31)
            self.assertEqual(o.type_id, (o.folder << 8) | o.item)
            self.assertEqual(tables.object_name_for_id("Breakneck", o.type_id), o.type_name)
            for k in range(3):
                self.assertGreaterEqual(o.position[k], bounds[2 * k])
                self.assertLess(o.position[k], bounds[2 * k + 1])
            self.assertAlmostEqual(sum(c * c for c in o.forward), 1.0, places=9)
            self.assertAlmostEqual(sum(c * c for c in o.up), 1.0, places=9)
            self.assertAlmostEqual(sum(a * b for a, b in zip(o.forward, o.up)), 0.0, places=9)
            self.assertEqual(o.parent_slot, -1)
            self.assertEqual(o.flags2, 1)
            self.assertIn(o.shape, (0, 2, 3))
            self.assertGreaterEqual(o.label_index, -1)
            self.assertLess(o.label_index, 21)
            self.assertEqual(o.color, -1)
            self.assertTrue(-1 <= o.team <= 8)
            self.assertEqual(o.raw_bits, m.slots[o.slot].raw.nbits)
            self.assertEqual(o.raw, m.slots[o.slot].raw.data)

    def test_positions_lie_in_a_small_part_of_the_huge_bounds(self):
        recs = api.load_map_variant(self.data).objects
        xs = [o.position[0] for o in recs]
        ys = [o.position[1] for o in recs]
        zs = [o.position[2] for o in recs]
        self.assertGreater(min(xs), -40.0)
        self.assertLess(max(xs), 40.0)
        self.assertGreater(min(ys), -40.0)
        self.assertLess(max(ys), 40.0)
        self.assertGreater(min(zs), 0.0)
        self.assertLess(max(zs), 30.0)

    def test_type_and_kind_counts(self):
        res = api.load_map_variant(self.data)
        by_name = {}
        for o in res.objects:
            by_name[o.type_name] = by_name.get(o.type_name, 0) + 1
        self.assertEqual(by_name["Respawn Point"], 248)
        self.assertEqual(by_name["Initial Spawn"], 108)
        self.assertEqual(by_name["Flag Stand"], 47)
        self.assertEqual(by_name["Hill Marker"], 25)
        self.assertEqual([n for n in by_name if "Block" in n], [])                 # NO Block object exists in this map variant
        self.assertEqual(sum(by_name.values()), 610)

    def test_cached_type_is_a_function_of_the_object_type(self):
        seen = {}
        for o in api.load_map_variant(self.data).objects:
            seen.setdefault(o.type_id, set()).add(o.cached_type)
        self.assertTrue(all(len(v) == 1 for v in seen.values()), dict((k, v) for k, v in seen.items() if len(v) > 1))
        by_folder = {}
        for tid, cts in seen.items():
            by_folder.setdefault(tid >> 8, set()).update(cts)
        self.assertEqual([f for f, cts in by_folder.items() if len(cts) > 1], [36])         # Sender / Receiver Node (13 and 14)

    def test_quota_placed_equals_the_number_of_present_slots_in_every_row(self):
        counts = {}
        for s in self.model.present_slots():
            counts[s.folder] = counts.get(s.folder, 0) + 1
        for i, q in enumerate(self.model.quotas):
            self.assertEqual(q.placed, counts.get(i, 0), "row %d" % i)
            self.assertEqual(q.minimum, 0)
            self.assertLessEqual(q.placed, q.maximum)
        self.assertEqual(sum(q.placed for q in self.model.quotas), 610)

    def test_quota_rows_of_the_block_folders_are_all_zero(self):
        # the star deliverable needs blocks: every Block folder of Breakneck has maximum 0 in this template
        block_rows = set(tid >> 8 for tid, _, name in tables.stock_objects("Breakneck") if name.startswith("Block"))
        self.assertEqual(sorted(block_rows), [63] + list(range(70, 81)))
        for row in block_rows:
            self.assertEqual(self.model.quotas[row].as_tuple(), (0, 0, 0), "row %d" % row)
        headroom = [(i, q.as_tuple()) for i, q in enumerate(self.model.quotas) if q.maximum > q.placed]
        self.assertEqual(headroom, [(4, (0, 3, 2)), (6, (0, 3, 2)), (7, (0, 2, 1))])

    def test_the_placement_byte_histogram(self):
        hist = {}
        for s in self.model.present_slots():
            hist[s.placement] = hist.get(s.placement, 0) + 1
        self.assertEqual(hist, {0x0C: 315, 0x2C: 139, 0xEC: 87, 0xCC: 58, 0xCE: 4, 0x04: 2, 0x08: 2, 0x6C: 1, 0x4C: 1, 0x4E: 1})

    def test_the_angle_codec_shows_round_values(self):
        raws = {}
        for s in self.model.present_slots():
            if s.up_global:
                raws[s.angle] = raws.get(s.angle, 0) + 1
        self.assertEqual(max(raws, key=raws.get), 8192)                           # angle 0 is the most common code
        self.assertGreaterEqual(raws[8192], 90)
        self.assertGreaterEqual(raws[4096], 25)                                   # -90 degrees
        self.assertEqual(sum(1 for s in self.model.present_slots() if s.up_global), 403)


class TestPlainAndEdits(RealCase):
    def test_plain_round_trip(self):
        d = json.loads(json.dumps(plain.to_plain(self.model)))
        again = plain.from_plain(d)
        self.assertEqual(again.to_bytes(force=True), self.data)                     # including the trailer
        self.assertEqual(len(d["slots"]), 610)
        self.assertEqual(d["container"]["hash"], {"length_endian": ">", "recipe": "plain_le32"})
        self.assertEqual(len(d["container"]["trailer_hex"]), 2 * 29911)

    def test_moving_one_object_changes_exactly_its_x_cells_and_the_hash(self):
        m = self.model.copy()
        target = m.present_slots()[100]
        spans = dict((n, (a, b)) for n, a, b in m.spans(fields=True))
        a, b = spans["slot_%d.pos_x" % target.index]
        target.pos[0] += 1000
        out = m.to_bytes(force=False)
        stream = 0x2F0 + 36
        old = self.data
        diff_bits = []
        for i in range(0x7000):
            x = old[stream + i] ^ out[stream + i]
            if x:
                for bit in range(8):
                    if x & (0x80 >> bit):
                        diff_bits.append(i * 8 + bit)
        self.assertTrue(diff_bits)
        self.assertTrue(all(a <= bit < b for bit in diff_bits), (a, b, diff_bits[:5]))
        outside = [i for i in range(len(old)) if old[i] != out[i] and not (0x2F0 + 12 <= i < 0x2F0 + 32) and not (stream <= i < stream + 0x7000)]
        self.assertEqual(outside, [])                                              # nothing outside the hash and the stream
        again = MapVariant.from_bytes(out)
        self.assertEqual(again.end_bit, 106487)
        self.assertEqual(again.chunk.stored_length, 13311)
        self.assertEqual(again.flavour, (">", "plain_le32"))
        digest = hashlib.sha1(struct.pack("<I", 13311) + out[stream:stream + 13311]).digest()
        self.assertEqual(out[0x2F0 + 12:0x2F0 + 32], digest)                       # recomputed with the file's own recipe
        self.assertEqual(out[29481:], bytes(29911))
        self.assertEqual(again.slots[target.index].pos[0], target.pos[0])

    def test_deleting_and_adding_objects_resizes_the_stream_consistently(self):
        m = self.model.copy()
        gone = [s for s in m.present_slots() if s.cached_type == 26][0]               # a kill boundary
        bits = gone.raw.nbits
        folder = gone.folder
        gone.present = False
        m.quotas[folder].placed -= 1
        out = m.to_bytes(force=False)
        again = MapVariant.from_bytes(out)
        self.assertEqual(again.end_bit, 106487 - (bits - 1))
        self.assertEqual(again.chunk.stored_length, (again.end_bit + 7) // 8)
        self.assertEqual(again.occupied, 609)
        self.assertEqual(out[29481:], bytes(29911))
        stream = 0x2F0 + 36
        digest = hashlib.sha1(struct.pack("<I", again.chunk.stored_length) + out[stream:stream + again.chunk.stored_length]).digest()
        self.assertEqual(out[0x2F0 + 12:0x2F0 + 32], digest)
        # add a Rocket Launcher (row 4 has headroom 1) as a copy of the existing one at a new position
        m2 = self.model.copy()
        src = [s for s in m2.present_slots() if s.folder == 4][0]
        free = m2.free_slots()[0]
        new = src.copy()
        new.index = free
        new.baseline = None
        new.raw = None
        new.pos = [src.pos[0] + 300, src.pos[1], src.pos[2]]
        m2.slots[free] = new
        m2.quotas[4].placed = 3
        out2 = m2.to_bytes(force=False)
        again2 = MapVariant.from_bytes(out2)
        self.assertEqual(again2.occupied, 611)
        self.assertEqual(again2.end_bit, 106487 + new.bit_length(again2.hypothesis.type19, again2.hypothesis.axis_bits) - 1)
        self.assertEqual(again2.quotas[4].as_tuple(), (0, 3, 3))
        self.assertEqual(again2.slots[free].snapshot(), new.snapshot())
        for s in self.model.slots:
            if s.index != free:
                self.assertEqual(again2.slots[s.index].snapshot(), s.snapshot())
        self.assertEqual(again2.to_bytes(force=True), out2)


class TestCommandLineOnTheRealFile(RealCase):
    def run_tool(self, tool, *args):
        proc = subprocess.run([sys.executable, "-I", tool] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
        return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")

    def test_verify_mvar_exits_0_and_prints_the_decode(self):
        code, out, err = self.run_tool(VERIFY, g3.REAL_MVAR)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("Headstrong", out)
        self.assertIn("map id 10050 (0x2742) = Breakneck", out)
        self.assertIn("detected flavour: plain_le32/>", out)
        self.assertIn("end bit 106487 (ceil 13311 bytes)", out)
        self.assertIn("occupied 610 of 651", out)
        self.assertIn("slot repack identity: 651/651", out)
        self.assertIn("to_bytes(force=True) == input: yes", out)
        self.assertIn("RESULT: ok", out)

    def test_dump_to_a_temp_dir(self):
        tmp = tempfile.mkdtemp(prefix="mjolnir-real-")
        try:
            out_path = os.path.join(tmp, "real.json")
            code, out, err = self.run_tool(DUMP, g3.REAL_MVAR, "--plain", out_path)           # the original is the INPUT only
            self.assertEqual((code, err), (0, ""))
            again = plain.from_plain(json.load(open(out_path)))
            self.assertEqual(again.to_bytes(force=True), self.data)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(hashlib.sha256(open(g3.REAL_MVAR, "rb").read()).hexdigest(), REAL_SHA256)

    def test_the_protected_folder_refusals_use_a_temp_copy_and_never_the_original_path(self):
        """The refusals of ``dump_mvar`` are exercised against a COPY placed inside a temp 'protected' folder.

        The protection is configured through the existing mechanism of ``mvarlib.io`` (``DEFAULT_PROTECTED``, which
        ``check_output_path`` reads on every call) in this process, so no tool is ever aimed at the original file as an output
        target: if the policy were broken, only a throw-away copy could be damaged. The original is read once, as the source of
        the copy.
        """
        import contextlib
        import importlib.util
        import io as stdio
        from unittest import mock
        from mvarlib import io as mio
        spec = importlib.util.spec_from_file_location("dump_mvar_under_test", DUMP)
        dump = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dump)
        tmp = tempfile.mkdtemp(prefix="mjolnir-real-protected-")
        try:
            protected = os.path.join(tmp, "protected")
            outside = os.path.join(tmp, "outside")
            os.makedirs(protected)
            os.makedirs(outside)
            copy = os.path.join(protected, "copy.mvar")
            with open(copy, "wb") as fh:
                fh.write(self.data)
            link = os.path.join(outside, "link.json")
            os.symlink(copy, link)
            protected_target = os.path.join(protected, "dump.json")
            elsewhere = os.path.join(outside, "dump.json")
            with mock.patch.object(mio, "DEFAULT_PROTECTED", (protected,)):
                self.assertEqual(mio.default_protected_dirs(), [protected])
                cases = [("a new file in the protected folder", protected_target, 2, True),
                         ("the input itself", copy, 2, True),
                         ("a symlink to the input", link, 2, True),
                         ("a folder outside the protected one", elsewhere, 0, False)]
                for label, target, expected, refused in cases:
                    with self.subTest(label):
                        err, out = stdio.StringIO(), stdio.StringIO()
                        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
                            code = dump.main([copy, "--plain", target])
                        self.assertEqual(code, expected, (out.getvalue(), err.getvalue()))
                        if refused:
                            self.assertIn("Refusing", err.getvalue())
                self.assertFalse(os.path.exists(protected_target), "nothing was created in the protected folder")
                self.assertEqual(open(copy, "rb").read(), self.data, "the copy is untouched")
                self.assertTrue(os.path.islink(link))
                self.assertTrue(os.path.exists(elsewhere), "the control case wrote its dump outside the protected folder")
                self.assertEqual(plain.from_plain(json.load(open(elsewhere))).to_bytes(force=True), self.data)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(hashlib.sha256(open(g3.REAL_MVAR, "rb").read()).hexdigest(), REAL_SHA256)

    def test_the_default_protected_set_contains_the_sample_folder(self):
        from mvarlib import io as mio
        folder = os.path.expanduser("~/Local_Documents/Halo-MCC/forge/real-mvar-samples")
        self.assertIn(folder, mio.default_protected_dirs())
        issue = mio.check_output_path(os.path.join(folder, "anything.mvar"))
        self.assertEqual(issue.code, "E_PATH_PROTECTED")
        issue = mio.check_output_path(g3.REAL_MVAR + ".new", [g3.REAL_MVAR])
        self.assertEqual(issue.code, "E_PATH_PROTECTED")


class TestJsOracleOnTheRealFile(RealCase):
    def test_the_javascript_prototype_decodes_the_same_objects(self):
        import test_oracle_js as oracle
        if oracle.NODE is None or not os.path.isfile(os.path.join(oracle.JS_SRC, "raw", "map_variant_mvar.js")):
            self.skipTest("node or Cobb's JS parser is not available")
        tmp = tempfile.mkdtemp(prefix="mjolnir-oracle-real-")
        try:
            harness = os.path.join(tmp, "harness.js")
            with open(harness, "w") as fh:
                fh.write(oracle.HARNESS)
            proc = subprocess.run([oracle.NODE, harness, oracle.JS_SRC, g3.REAL_MVAR], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  timeout=180)                                      # the JS reads the original in place
            if proc.returncode != 0:
                self.skipTest("the JS parser could not be run: %s" % proc.stderr.decode("utf-8", "replace")[-200:])
            js = json.loads(proc.stdout.decode("utf-8"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        m = self.model
        self.assertEqual((js["header"]["mapID"], js["header"]["title"], js["header"]["description"]), (10050, "Headstrong", "A heavier Headlong."))
        self.assertEqual((js["version"], js["quotaCount"], js["budget"]), (31, 82, [10000, 3885]))
        self.assertEqual(js["labels"], m.labels.texts())
        recs = dict((o.slot, o) for o in m.objects())
        self.assertEqual([o["slot"] for o in js["objects"]], sorted(recs))
        for o in js["objects"]:
            s = m.slots[o["slot"]]
            r = recs[o["slot"]]
            self.assertEqual((o["folder"], o["item"], o["shape"], o["cachedType"], o["placement"], o["teamMinus1"]),
                             (s.folder, s.item, s.shape, s.cached_type, s.placement, s.team_raw - 1), "slot %d" % s.index)
            for k in range(3):
                self.assertAlmostEqual(o["position"][k], r.position[k], places=9)
            self.assertEqual(o["label"], -1 if s.label is None else s.label)
            self.assertEqual(o["spawnSequence"], s.spawn_seq & 0xFF)
            self.assertEqual(o["respawnTime"], s.respawn)


if __name__ == "__main__":
    unittest.main()
