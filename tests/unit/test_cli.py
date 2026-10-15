"""U-16 (SPEC 9.3, 6.7, tier T2/T3): the command-line tools ``verify_mvar`` and ``dump_mvar``.

``verify_mvar`` exit codes: 0 on W1, 1 on a desynchronised fixture, 2 on a game variant (the container report is
printed) and on garbage or a missing file, 3 when a self-check is forced to fail; every non-zero exit ends with one
``VERIFY FAILED: <reason>`` line. ``dump_mvar`` and ``verify_mvar --json`` write only through ``write_atomic`` and
refuse any output path inside the repository working tree (``scratch/`` included), inside a protected folder, a
symlink to the input and the input itself. (``reencode_mvar`` belongs to gate G5 and is tested there.)

The tools run in child processes with the interpreter of the test run; fixtures are written to a private temp
directory outside the repository.
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

REPO = g3.REPO
VERIFY = os.path.join(REPO, "tools", "verify_mvar.py")
DUMP = os.path.join(REPO, "tools", "dump_mvar.py")


def below_a_file(folder):
    """A path that lies inside ``folder`` but below one of its existing files (so nothing can ever be created there)."""
    if not os.path.isdir(folder):
        return None
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return os.path.join(path, "dump_should_not_exist.json")
    return None


def run(tool, *args):
    proc = subprocess.run([sys.executable, "-I", tool] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")


class CliCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="mjolnir-cli-")
        cls.files = {}
        for name in ("w1_minimal", "desync_length", "cmp", "holes", "trailer", "type19_flag8"):
            path = os.path.join(cls.tmp, name + ".mvar")
            with open(path, "wb") as fh:
                fh.write(g3.data(name))
            cls.files[name] = path

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


class TestVerifyExitCodes(CliCase):
    def test_exit_0_on_w1_and_all_sections_are_printed(self):
        code, out, err = run(VERIFY, self.files["w1_minimal"])
        self.assertEqual((code, err), (0, ""))
        for heading in ("1. CONTAINER", "2. HASH AND STORED LENGTH", "3. HEADER", "4. BODY", "5. WALK", "6. SLOTS", "7. QUOTAS",
                        "8. TAIL AND PADDING", "9. SELF-CHECKS"):
            self.assertIn(heading, out)
        self.assertIn("slot repack identity: 651/651", out)
        self.assertIn("label re-encode identical: yes", out)
        self.assertIn("unmodified to_bytes() == input: yes", out)
        self.assertIn("to_bytes(force=True) == input: yes", out)
        self.assertIn("plain round trip identical: yes", out)
        self.assertIn("detected flavour: salted_be32/>", out)
        self.assertIn("Forge World", out)
        self.assertIn("RESULT: ok", out)
        self.assertNotIn("VERIFY FAILED", out)

    def test_exit_0_for_cmp_and_trailer_and_the_other_decodable_shapes(self):
        for name in ("cmp", "holes", "trailer", "type19_flag8"):
            with self.subTest(name):
                code, out, err = run(VERIFY, self.files[name])
                self.assertEqual((code, err), (0, ""), out[-400:])
        code, out, _ = run(VERIFY, self.files["cmp"])
        self.assertIn("_cmp", out)
        self.assertIn("expanded plain form", out)

    def test_exit_1_on_a_desynchronised_fixture(self):
        code, out, err = run(VERIFY, self.files["desync_length"])
        self.assertEqual(code, 1)
        self.assertEqual(out.rstrip().splitlines()[-1].split(":")[0], "VERIFY FAILED")
        self.assertIn("none of the 4 known layouts fits", out)
        self.assertIn("the walk ends at bit 4970", out)
        self.assertIn("5. WALK", out)

    def test_exit_2_on_a_game_variant_and_the_container_report_is_printed(self):
        import helpers_real
        sample = helpers_real.distinct_samples(helpers_real.load_samples())[0]
        code, out, err = run(VERIFY, sample.path)
        self.assertEqual(code, 2)
        self.assertIn("1. CONTAINER", out)
        self.assertIn("mpvr", out)
        self.assertIn("2. HASH AND STORED LENGTH", out)
        self.assertIn("salted_be32/<", out)
        self.assertEqual(out.rstrip().splitlines()[-1], "VERIFY FAILED: This is a game variant (block 'mpvr'), not a map variant. "
                                                       "Use File > Import for map variants only.")

    def test_exit_2_on_garbage_and_missing_files(self):
        garbage = os.path.join(self.tmp, "garbage.bin")
        with open(garbage, "wb") as fh:
            fh.write(b"this is not a halo file at all, just text\n" * 5)
        code, out, err = run(VERIFY, garbage)
        self.assertEqual(code, 2)
        self.assertTrue(out.rstrip().splitlines()[-1].startswith("VERIFY FAILED: "))
        code, out, err = run(VERIFY, os.path.join(self.tmp, "does-not-exist.mvar"))
        self.assertEqual(code, 2)
        self.assertIn("cannot read", out)
        self.assertTrue(out.rstrip().splitlines()[-1].startswith("VERIFY FAILED: cannot read"))
        empty = os.path.join(self.tmp, "empty.mvar")
        open(empty, "wb").close()
        self.assertEqual(run(VERIFY, empty)[0], 2)
        code, out, err = run(VERIFY)                                   # usage error
        self.assertEqual(code, 2)

    def test_exit_3_when_a_self_check_fails(self):
        for name in ("slot_repack", "passthrough", "forced", "plain_round_trip"):
            with self.subTest(name):
                code, out, err = run(VERIFY, "--force-selfcheck-failure", name, self.files["w1_minimal"])
                self.assertEqual(code, 3)
                self.assertIn("[FAIL]", out)
                self.assertTrue(out.rstrip().splitlines()[-1].startswith("VERIFY FAILED: self-check failed: "))

    def test_several_files_give_the_worst_code(self):
        code, out, err = run(VERIFY, self.files["w1_minimal"], self.files["desync_length"])
        self.assertEqual(code, 1)
        self.assertEqual(out.count("verify_mvar report:"), 2)
        code, out, err = run(VERIFY, self.files["desync_length"], os.path.join(self.tmp, "missing.mvar"), self.files["w1_minimal"])
        self.assertEqual(code, 2)

    def test_no_strings_omits_the_texts(self):
        code, out, err = run(VERIFY, "--no-strings", self.files["w1_minimal"])
        self.assertEqual(code, 0)
        self.assertNotIn("W1 minimal", out)
        self.assertNotIn("Kill Boundary", out.replace("Kill Boundary  26", ""))        # the object type name is a table name, not file text
        self.assertNotIn("synthetic reference fixture", out)
        self.assertIn("<omitted>", out)

    def test_lenient_shows_the_walk_with_the_unsourced_checks_off(self):
        import copy
        build, _ = g3.build_modules()
        spec = copy.deepcopy(g3.spec("w1_minimal"))
        spec.pop("expect", None)
        spec["slots"][0]["folder"] = 200
        path = os.path.join(self.tmp, "folder200.mvar")
        with open(path, "wb") as fh:
            fh.write(build.build(spec).data)
        code, out, err = run(VERIFY, path)
        self.assertEqual(code, 1)
        self.assertIn("[rejected only by an unsourced check]", out)
        code2, out2, _ = run(VERIFY, "--lenient", path)
        self.assertEqual(code2, 1)                                  # the library would still refuse it
        self.assertIn("only fits with the two unverified plausibility checks switched off", out2)

    def test_the_input_is_never_modified(self):
        path = self.files["w1_minimal"]
        before = open(path, "rb").read()
        mtime = os.stat(path).st_mtime_ns
        run(VERIFY, path)
        run(DUMP, path)
        self.assertEqual(open(path, "rb").read(), before)
        self.assertEqual(os.stat(path).st_mtime_ns, mtime)


class TestJsonOutput(CliCase):
    def test_json_is_written_through_write_atomic(self):
        out_path = os.path.join(self.tmp, "report.json")
        code, out, err = run(VERIFY, "--json", out_path, self.files["w1_minimal"])
        self.assertEqual(code, 0, out)
        facts = json.load(open(out_path))
        self.assertEqual(facts["header"]["map_id"], 3006)
        self.assertEqual(facts["slots"]["occupied"], 3)
        self.assertEqual(facts["walk"]["selected"]["end_bit"], 4970)
        self.assertEqual(facts["result"]["status"], "ok")
        self.assertEqual([c["ok"] for c in facts["selfchecks"]], [True, None, True, True, True])
        self.assertEqual(sorted(os.listdir(self.tmp)).count("report.json"), 1)
        self.assertFalse([n for n in os.listdir(self.tmp) if ".tmp-" in n])

    def test_json_without_strings(self):
        out_path = os.path.join(self.tmp, "nostrings.json")
        code, out, err = run(VERIFY, "--no-strings", "--json", out_path, self.files["w1_minimal"])
        self.assertEqual(code, 0)
        text = open(out_path).read()
        self.assertNotIn("W1 minimal", text)
        self.assertNotIn("synthetic reference fixture", text)

    def test_json_for_several_files(self):
        out_path = os.path.join(self.tmp, "several.json")
        code, out, err = run(VERIFY, "--json", out_path, self.files["w1_minimal"], self.files["holes"])
        self.assertEqual(code, 0)
        self.assertEqual(len(json.load(open(out_path))["files"]), 2)

    def test_json_refused_inside_the_repo_or_over_the_input(self):
        target = os.path.join(REPO, "scratch", "verify_report_should_not_exist.json")
        code, out, err = run(VERIFY, "--json", target, self.files["w1_minimal"])
        self.assertEqual(code, 2)
        self.assertIn("inside the repository working tree", out)
        self.assertFalse(os.path.exists(target))
        self.assertFalse(os.path.exists(os.path.dirname(target)) and os.listdir(os.path.dirname(target)))
        before = open(self.files["w1_minimal"], "rb").read()
        code, out, err = run(VERIFY, "--json", self.files["w1_minimal"], self.files["w1_minimal"])
        self.assertEqual(code, 2)
        self.assertEqual(open(self.files["w1_minimal"], "rb").read(), before)


class TestDump(CliCase):
    def test_default_prints_the_plain_json(self):
        code, out, err = run(DUMP, self.files["w1_minimal"])
        self.assertEqual((code, err), (0, ""))
        d = json.loads(out)
        self.assertEqual(d["schema"], "mvarlib.plain/1")
        self.assertEqual([s["index"] for s in d["slots"]], [1, 5, 650])

    def test_plain_file_is_written_and_round_trips(self):
        out_path = os.path.join(self.tmp, "w1.json")
        code, out, err = run(DUMP, self.files["w1_minimal"], "--plain", out_path)
        self.assertEqual(code, 0, err)
        sys.path.insert(0, os.path.join(REPO, "Addon"))
        from mvarlib import plain
        m = plain.from_plain(json.load(open(out_path)))
        self.assertEqual(m.to_bytes(force=True), g3.data("w1_minimal"))

    def test_slots_and_spans(self):
        code, out, err = run(DUMP, self.files["w1_minimal"], "--slots")
        self.assertEqual(code, 0)
        lines = out.strip().splitlines()
        self.assertEqual(len(lines), 4)
        self.assertIn("Block, 1x1", lines[1])
        self.assertIn("Kill Boundary", lines[2])
        code, out, err = run(DUMP, self.files["w1_minimal"], "--spans")
        self.assertEqual(code, 0)
        self.assertIn("header", out)
        self.assertIn("slot_5.dims", out)
        self.assertIn("quota_79", out)

    def test_exit_codes(self):
        self.assertEqual(run(DUMP, self.files["desync_length"])[0], 1)
        self.assertEqual(run(DUMP, os.path.join(self.tmp, "missing.mvar"))[0], 2)
        import helpers_real
        sample = helpers_real.distinct_samples(helpers_real.load_samples())[0]
        self.assertEqual(run(DUMP, sample.path)[0], 2)
        self.assertEqual(run(DUMP)[0], 2)

    def test_output_paths_are_refused(self):
        src = self.files["w1_minimal"]
        before = open(src, "rb").read()
        link = os.path.join(self.tmp, "link.json")
        os.symlink(src, link)
        cases = [
            ("inside the repo", os.path.join(REPO, "tests", "unit", "dump_should_not_exist.json")),
            ("scratch dir of the repo", os.path.join(REPO, "scratch", "dump_should_not_exist.json")),
            ("repo root", os.path.join(REPO, "dump_should_not_exist.json")),
            ("symlink to the input", link),
            ("the input itself", src),
        ]
        # The protected folders are the owner's real folders: a target is chosen BELOW an existing file of the folder, so
        # that even a broken policy could not create anything there (it would fail on the file used as a directory).
        for label, folder in (("protected samples", "~/Local_Documents/Halo-MCC/variant-tool/test-samples"),
                              ("protected real map", "~/Local_Documents/Halo-MCC/forge/real-mvar-samples")):
            below = below_a_file(os.path.expanduser(folder))
            if below:
                cases.append((label, below))
        for label, target in cases:
            with self.subTest(label):
                code, out, err = run(DUMP, src, "--plain", target)
                self.assertEqual(code, 2, (out, err))
                self.assertIn("Refusing", err)
                if label not in ("symlink to the input", "the input itself"):
                    self.assertFalse(os.path.exists(target), target)
        self.assertEqual(open(src, "rb").read(), before)
        self.assertTrue(os.path.islink(link))
        self.assertEqual(os.path.realpath(link), os.path.realpath(src))
        self.assertFalse(os.path.exists(os.path.join(REPO, "scratch")) and os.listdir(os.path.join(REPO, "scratch")))


if __name__ == "__main__":
    unittest.main()
