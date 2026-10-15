"""U-23 (SPEC 9.1, 9.3, optional third oracle): run Cobb's own JS parser (``map_variant_mvar.js``) on synthetic
fixtures and compare header fields, bounds, labels, budget words and slot folder / item / position / shape / dimensions
/ spawn fields with the library.

The JS file is GPLv3 and is neither copied nor vendored: the test loads it, read-only, from its original place
(``~/Local_Documents/Halo-MCC/variant-tool/ReachVariantTool/html/src``, or ``$MJOLNIR_RVT_HTML_SRC``) into a ``node`` ``vm`` context. The test is
skipped when ``node`` or the JS files are missing or cannot be run. It catches implementation slips only, never a wrong
single-source claim of the spec (the JS prototype and the spec share their sources).

Known limits of the JS prototype that this test works around (recorded in docs/mvar/notes/G3.md): the quota table
loop tests ``this.unk2B2`` (a typo for ``unk02B2``), so the JS reads no quota rows at all and they cannot be compared;
the campaign / firefight header tails test ``this.gameMode`` (undefined) and are never read; only version 31 exists
(no GUID block); cached type 19 is always the ``plain8`` rule; an absent folder leaves ``objectSubcat`` undefined.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import helpers_g3 as g3  # noqa: E402

JS_SRC = os.environ.get("MJOLNIR_RVT_HTML_SRC") or os.path.expanduser("~/Local_Documents/Halo-MCC/variant-tool/ReachVariantTool/html/src")
NODE = shutil.which("node")

HARNESS = r"""
const fs = require('fs'), vm = require('vm'), path = require('path');
const src = process.argv[2], file = process.argv[3];
const files = ['third-party/pako/pako.js', 'utils.js', 'enums-and-flags.js', 'bitstream.js', 'bitnumber.js',
               'variant-content-author.js', 'raw/map_variant_mvar.js'];
let code = files.map(f => fs.readFileSync(path.join(src, f), 'utf8')).join('\n;\n');
const buf = fs.readFileSync(file);
const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
code += `
;(function () {
  const stream = new Bitstream(__ab);
  stream.skipBytes(0x2F0);
  const mv = new MapVariant(stream);
  const objs = [];
  mv.forgeObjects.forEach((o, i) => {
    if (!o.loaded) return;
    const u = o.unk30 || {};
    objs.push({slot: i, flags2: o.unk00, folder: o.objectSubcat, item: o.objectType,
      position: [o.position.x, o.position.y, o.position.z], parentMinus1: o.unk2C, shape: u.unk10,
      dims: [u.unk00, u.unk04, u.unk08, u.unk0C], spawnSequence: u.spawnSequence, respawnTime: u.respawnTime,
      cachedType: u.unk13, label: u.forgeLabelIndex, placement: u.unk16, teamMinus1: u.unk17, color: u.team,
      extra: [u.unk18, u.unk19]});
  });
  return JSON.stringify({
    header: {type: mv.header.type, fileLength: mv.header.fileLength, activity: mv.header.activity,
      gameMode: mv.header.gameMode, engine: mv.header.engine, mapID: mv.header.mapID,
      category: mv.header.engineCategoryIndex, title: mv.header.title, description: mv.header.description,
      createdBy: mv.header.createdBy.author, modifiedBy: mv.header.modifiedBy.author},
    version: mv.unk02B0, checksum: mv.unk02DC, crc: mv.unk02E0, quotaCount: mv.unk02B2, mapID2: mv.unk02B4,
    builtIn: mv.unk02D9, builtFromXml: mv.unk02DA, bounds: mv.boundingBox, budget: [mv.unk02D0, mv.unk02D4],
    labels: mv.forgeLabels.strings.map(s => s.content), labelOffsets: mv.forgeLabels.strings.map(s => s.offset),
    dataLength: mv.forgeLabels.dataLength, objects: objs, quotas: mv.unkD630.slice(0, 82).map(q => [q.unk00, q.unk01, q.unk02])
  }, (k, v) => typeof v === 'bigint' ? v.toString() : v);
})()`;
const sandbox = {__ab: ab, console: {log() {}, warn() {}, assert() {}, error() {}}};
sandbox.window = sandbox; sandbox.self = sandbox; sandbox.global = sandbox;
vm.createContext(sandbox);
process.stdout.write(vm.runInContext(code, sandbox));
"""

_cache = {}


class OracleCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if NODE is None:
            raise unittest.SkipTest("U-23 skipped: node is not installed")
        if not os.path.isfile(os.path.join(JS_SRC, "raw", "map_variant_mvar.js")):
            raise unittest.SkipTest("U-23 skipped: Cobb's map_variant_mvar.js is not at %s" % JS_SRC)
        cls.tmp = tempfile.mkdtemp(prefix="mjolnir-oracle-")
        cls.harness = os.path.join(cls.tmp, "harness.js")
        with open(cls.harness, "w") as fh:
            fh.write(HARNESS)
        try:
            cls.run_oracle("w1_minimal")
        except Exception as exc:
            shutil.rmtree(cls.tmp, ignore_errors=True)
            raise unittest.SkipTest("U-23 skipped: the JS parser cannot be run here (%s)" % str(exc)[:200])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, "tmp", ""), ignore_errors=True)

    @classmethod
    def run_oracle(cls, name):
        if name in _cache:
            return _cache[name]
        path = os.path.join(cls.tmp, name + ".mvar")
        with open(path, "wb") as fh:
            fh.write(g3.data(name))
        proc = subprocess.run([NODE, cls.harness, JS_SRC, path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", "replace")[-300:])
        _cache[name] = json.loads(proc.stdout.decode("utf-8"))
        return _cache[name]


def same(a, b, tol=1e-9):
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


class TestAgainstTheJsParser(OracleCase):
    COMMON = ("w1_minimal", "holes", "labels_compressed", "labels_uncompressed", "axes_16_17_18", "axes_19_20_21",
              "axes_22_23_22", "zero_labels", "hdr_long_text", "hdr_min_text", "extremes", "plain_le32", "trailer")

    def check(self, name):
        js = self.run_oracle(name)
        m = g3.model(name)
        h = m.header
        self.assertEqual((js["header"]["type"], js["header"]["fileLength"], js["header"]["activity"], js["header"]["gameMode"],
                          js["header"]["engine"], js["header"]["mapID"], js["header"]["category"]),
                         (h.content_type, h.file_length, h.activity, h.game_mode, h.engine, h.map_id, h.engine_category))
        self.assertEqual((js["header"]["title"], js["header"]["description"]), (h.title_text, h.description_text))
        self.assertEqual((js["header"]["createdBy"], js["header"]["modifiedBy"]), (h.created_by.name_text, h.modified_by.name_text))
        f = m.fixed
        self.assertEqual((js["version"], js["checksum"] & 0xFFFFFFFF, js["crc"] & 0xFFFFFFFF, js["quotaCount"], js["mapID2"], js["builtIn"],
                          js["builtFromXml"]), (f.version, f.checksum, f.palette_crc, f.quota_count, f.map_id_2, f.built_in, f.built_from_xml))
        b = f.bounds
        for k, axis in enumerate("xyz"):
            self.assertEqual((js["bounds"][axis]["min"], js["bounds"][axis]["max"]), (b[2 * k], b[2 * k + 1]))
        self.assertEqual(js["budget"], [f.max_budget, f.spent_budget])
        self.assertEqual(len(js["labels"]), m.labels.count)
        for i in range(m.labels.count):
            if m.labels.entries[i] is not None:
                self.assertEqual(js["labels"][i], m.labels.text(i), "label %d" % i)
                self.assertEqual(js["labelOffsets"][i], m.labels.entries[i])
        recs = dict((o.slot, o) for o in m.objects())
        self.assertEqual([o["slot"] for o in js["objects"]], sorted(recs))
        for o in js["objects"]:
            s = m.slots[o["slot"]]
            r = recs[o["slot"]]
            tag = "%s slot %d" % (name, s.index)
            self.assertEqual(o["flags2"], s.flags2, tag)
            if s.folder is not None:
                self.assertEqual(o["folder"], s.folder, tag)
            self.assertEqual(o["item"], 255 if s.item is None else s.item, tag)
            for k in range(3):
                self.assertTrue(same(o["position"][k], r.position[k]), "%s axis %d: %r vs %r" % (tag, k, o["position"][k], r.position[k]))
            self.assertEqual(o["parentMinus1"], r.parent_slot, tag)
            self.assertEqual(o["shape"], s.shape, tag)
            expected_dims = {0: [], 1: [r.width], 2: [r.width, r.top, r.bottom], 3: [r.width, r.length, r.top, r.bottom]}[s.shape]
            js_dims = {0: [], 1: [o["dims"][0]], 2: [o["dims"][0], o["dims"][2], o["dims"][3]], 3: o["dims"]}[s.shape]
            for have, want in zip(js_dims, expected_dims):
                self.assertTrue(same(have, want, 1e-9), "%s dims %r vs %r" % (tag, js_dims, expected_dims))
            self.assertEqual(o["spawnSequence"], s.spawn_seq & 0xFF, tag)
            self.assertEqual(o["respawnTime"], s.respawn, tag)
            self.assertEqual(o["cachedType"], s.cached_type, tag)
            self.assertEqual(o["label"], -1 if s.label is None else s.label, tag)
            self.assertEqual(o["placement"], s.placement, tag)
            self.assertEqual(o["teamMinus1"], s.team_raw - 1, tag)
            self.assertEqual(o["color"], -1 if s.color is None else s.color, tag)
            if s.cached_type == 1:
                self.assertEqual(o["extra"][0], s.extra[0], tag)
            elif 12 <= s.cached_type <= 14:
                self.assertEqual(o["extra"], s.extra, tag)

    def test_w1(self):
        self.check("w1_minimal")

    def test_every_comparable_fixture(self):
        for name in self.COMMON:
            with self.subTest(name):
                self.check(name)

    def test_type19_plain8_rule_matches_the_js_reading(self):
        js = self.run_oracle("type19_plain8")
        m = g3.model("type19_plain8")
        self.assertEqual(m.hypothesis.type19, "plain8")
        seen = 0
        for o in js["objects"]:
            s = m.slots[o["slot"]]
            self.check_one_type19(o, s)
            seen += s.cached_type == 19
        self.assertEqual(seen, 5)
        for o in js["objects"]:
            s = m.slots[o["slot"]]
            for k in range(3):
                self.assertTrue(same(o["position"][k], m.record_for(s).position[k]))

    def check_one_type19(self, o, s):
        self.assertEqual(o["cachedType"], s.cached_type)
        if s.cached_type == 19:
            self.assertEqual(o["extra"][0], s.extra[0] - 1)

    def test_the_js_reads_no_quota_rows_because_of_its_own_typo(self):
        # unk2B2 vs unk02B2: the JS loop `i < this.unk2B2` never runs, so this oracle cannot check quota rows; the
        # library's quota rows are checked against the builder in U-07 instead.
        js = self.run_oracle("w1_minimal")
        self.assertTrue(all(row == [0, 0, 0] for row in js["quotas"]))
        self.assertTrue(any(q.as_tuple() != (0, 0, 0) for q in g3.model("w1_minimal").quotas))

    def test_the_js_does_not_know_version_32(self):
        # the JS has no GUID branch: on a v32 file its slots come out wrong, the library reads them
        m = g3.model("v32")
        self.assertEqual(m.hypothesis.guid, True)
        try:
            js = self.run_oracle("v32")
        except Exception:
            return                                                   # the JS may simply fail on the shifted bits
        mine = sorted(s.index for s in m.slots if s.present)
        self.assertNotEqual([o["slot"] for o in js["objects"]], mine)


if __name__ == "__main__":
    unittest.main()
