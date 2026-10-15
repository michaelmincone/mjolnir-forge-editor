"""U-16, ``reencode_mvar`` part (SPEC 6.7, 9.3, 9.5 rung H; gate G5).

``tools/reencode_mvar.py IN OUT [--force] [--hash-recipe NAME] [--zero-hash] [--corrupt-hash]`` writes the passthrough copy,
the forced re-encode (a self-test: for the plain shapes it must equal the input), or a hash probe. It writes only through
``mvarlib.io.write_atomic``: never onto its input (also through a symlink), never into a protected folder, never inside the
repository's working tree, and a failed self-test writes nothing.

The tool runs as a subprocess (``python -I``) on fixtures written into a private temp directory. The protected-folder refusal is
exercised in this process with the existing mechanism (``mvarlib.io.DEFAULT_PROTECTED``) pointed at a temp folder, so no real
folder is ever written to even if the policy were broken.
"""
import contextlib
import hashlib
import importlib.util
import io as stdio
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import helpers_g5 as h  # noqa: E402

from mvarlib import io as mio  # noqa: E402
from mvarlib.model import MapVariant  # noqa: E402

REPO = h.REPO
TOOL = os.path.join(REPO, "tools", "reencode_mvar.py")


def run(*args):
    proc = subprocess.run([sys.executable, "-I", TOOL] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")


class ReencodeCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="mjolnir-reencode-")
        cls.files = {}
        for name in ("w1_minimal", "plain_le32", "zero_hash", "cmp", "cmp_expanded", "fsm", "le_length", "desync_length", "length_capacity"):
            path = os.path.join(cls.tmp, name + ".mvar")
            with open(path, "wb") as fh:
                fh.write(h.g3.data(name))
            cls.files[name] = path

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def out(self, name):
        path = os.path.join(self.tmp, name)
        if os.path.exists(path):
            os.remove(path)
        return path

    def read(self, path):
        with open(path, "rb") as fh:
            return fh.read()


class TestModes(ReencodeCase):
    def test_default_is_the_passthrough_copy(self):
        out = self.out("copy.mvar")
        code, stdout, stderr = run(self.files["w1_minimal"], out)
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(self.read(out), h.g3.data("w1_minimal"))
        self.assertIn("passthrough copy", stdout)
        self.assertIn("identical", stdout)

    def test_force_equals_the_input_for_plain_shapes(self):
        for name in ("w1_minimal", "plain_le32", "zero_hash", "fsm", "le_length", "length_capacity"):
            with self.subTest(name):
                out = self.out("forced.mvar")
                code, stdout, stderr = run(self.files[name], out, "--force")
                self.assertEqual((code, stderr), (0, ""))
                self.assertEqual(self.read(out), h.g3.data(name))
                self.assertIn("forced re-encode", stdout)

    def test_force_of_a_cmp_input_is_the_expanded_form(self):
        out = self.out("expanded.mvar")
        code, stdout, stderr = run(self.files["cmp"], out, "--force")
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(self.read(out), h.g3.data("cmp_expanded"))
        self.assertIn("differs from the input", stdout)

    def test_the_default_copy_of_a_cmp_input_is_the_wrapper(self):
        out = self.out("wrapper.mvar")
        self.assertEqual(run(self.files["cmp"], out)[0], 0)
        self.assertEqual(self.read(out), h.g3.data("cmp"))

    def test_hash_recipe_rewrites_only_the_sha1(self):
        out = self.out("probe.mvar")
        code, stdout, stderr = run(self.files["w1_minimal"], out, "--hash-recipe", "plain_le32")
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(self.read(out), h.g3.data("plain_le32"))
        out = self.out("probe2.mvar")
        self.assertEqual(run(self.files["plain_le32"], out, "--hash-recipe", "salted_be32")[0], 0)
        self.assertEqual(self.read(out), h.g3.data("w1_minimal"))
        _b, selfcheck = h.build_modules()
        data = h.g3.data("w1_minimal")
        for recipe in ("salted_le32", "plain_be32", "data_only"):
            out = self.out("probe3.mvar")
            self.assertEqual(run(self.files["w1_minimal"], out, "--hash-recipe", recipe)[0], 0)
            result = self.read(out)
            self.assertEqual(result[h.HASH_AT:h.HASH_AT + 20], selfcheck.digest(recipe, h.stream_bytes(data), 622), recipe)
            self.assertEqual([i for i in range(len(data)) if data[i] != result[i] and not h.HASH_AT <= i < h.HASH_AT + 20], [])

    def test_the_length_byte_order_is_kept_for_a_recipe_probe(self):
        out = self.out("probe_le.mvar")
        self.assertEqual(run(self.files["le_length"], out, "--hash-recipe", "plain_le32")[0], 0)
        result = self.read(out)
        self.assertEqual(result[h.LENGTH_AT:h.LENGTH_AT + 4], struct.pack("<I", 622))

    def test_zero_hash(self):
        out = self.out("zero.mvar")
        code, stdout, stderr = run(self.files["w1_minimal"], out, "--zero-hash")
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(self.read(out), h.g3.data("zero_hash"))
        self.assertEqual(self.read(out)[h.HASH_AT:h.HASH_AT + 20], bytes(20))

    def test_corrupt_hash_flips_the_sha1_and_nothing_else(self):
        out = self.out("corrupt.mvar")
        code, stdout, stderr = run(self.files["w1_minimal"], out, "--corrupt-hash")
        self.assertEqual((code, stderr), (0, ""))
        data, result = h.g3.data("w1_minimal"), self.read(out)
        diff = [i for i in range(len(data)) if data[i] != result[i]]
        self.assertEqual(diff, [h.HASH_AT])
        self.assertEqual(result[h.HASH_AT], data[h.HASH_AT] ^ 0xFF)
        self.assertIsNone(MapVariant.from_bytes(result).flavour, "no recipe matches any more")
        out = self.out("corrupt_zero.mvar")
        self.assertEqual(run(self.files["zero_hash"], out, "--corrupt-hash")[0], 0)
        self.assertNotEqual(self.read(out)[h.HASH_AT:h.HASH_AT + 20], bytes(20), "a zero hash becomes a non-zero one")

    def test_corrupt_hash_of_a_cmp_input_is_the_expanded_form_with_a_bad_hash(self):
        out = self.out("corrupt_cmp.mvar")
        self.assertEqual(run(self.files["cmp"], out, "--corrupt-hash")[0], 0)
        result, expanded = self.read(out), h.g3.data("cmp_expanded")
        self.assertEqual([i for i in range(len(expanded)) if expanded[i] != result[i]], [h.HASH_AT])

    def test_the_inputs_are_never_touched(self):
        before = dict((name, self.read(path)) for name, path in self.files.items())
        for options in ([], ["--force"], ["--zero-hash"], ["--corrupt-hash"], ["--hash-recipe", "data_only"]):
            run(self.files["w1_minimal"], self.out("any.mvar"), *options)
        for name, path in self.files.items():
            self.assertEqual(self.read(path), before[name], name)


class TestRefusals(ReencodeCase):
    def test_choosing_two_hash_options_is_a_usage_error(self):
        out = self.out("two.mvar")
        for options in (["--zero-hash", "--corrupt-hash"], ["--hash-recipe", "plain_le32", "--zero-hash"],
                        ["--hash-recipe", "plain_le32", "--corrupt-hash"]):
            code, stdout, stderr = run(self.files["w1_minimal"], out, *options)
            self.assertEqual(code, 2, options)
            self.assertIn("at most one", stderr)
            self.assertFalse(os.path.exists(out))

    def test_a_bad_recipe_or_missing_arguments_are_usage_errors(self):
        self.assertEqual(run(self.files["w1_minimal"], self.out("x.mvar"), "--hash-recipe", "md5")[0], 2)
        self.assertEqual(run(self.files["w1_minimal"])[0], 2)
        self.assertEqual(run()[0], 2)

    def test_out_equal_to_in_is_refused_also_through_a_symlink(self):
        src = self.files["w1_minimal"]
        before = self.read(src)
        code, stdout, stderr = run(src, src)
        self.assertEqual(code, 2)
        self.assertIn("Refusing to overwrite the file this map was imported from", stderr)
        link = os.path.join(self.tmp, "link.mvar")
        if os.path.lexists(link):
            os.remove(link)
        os.symlink(src, link)
        code, stdout, stderr = run(src, link)
        self.assertEqual(code, 2)
        self.assertIn("Refusing", stderr)
        self.assertEqual(self.read(src), before)
        self.assertTrue(os.path.islink(link))
        hard = os.path.join(self.tmp, "hard.mvar")
        if os.path.exists(hard):
            os.remove(hard)
        os.link(src, hard)
        self.assertEqual(run(src, hard)[0], 2)
        self.assertEqual(self.read(src), before)

    def test_the_path_check_comes_before_the_input_is_read(self):
        """OUT equal to an input that is not even a map variant is still the path refusal, not a parse error."""
        junk = os.path.join(self.tmp, "junk_same.bin")
        with open(junk, "wb") as fh:
            fh.write(b"not a map variant " * 4)
        code, stdout, stderr = run(junk, junk)
        self.assertEqual(code, 2)
        self.assertIn("Refusing to overwrite the file this map was imported from", stderr)
        with open(junk, "rb") as fh:
            self.assertEqual(fh.read(), b"not a map variant " * 4)

    def test_out_inside_the_repository_is_refused_and_nothing_is_created(self):
        cases = [os.path.join(REPO, "tests", "unit", "reencode_should_not_exist.mvar"),
                 os.path.join(REPO, "scratch", "reencode_should_not_exist.mvar"),
                 os.path.join(REPO, "reencode_should_not_exist.mvar")]
        for target in cases:
            with self.subTest(target):
                code, stdout, stderr = run(self.files["w1_minimal"], target)
                self.assertEqual(code, 2)
                self.assertIn("inside the repository working tree", stderr)
                self.assertFalse(os.path.exists(target))
        self.assertFalse(os.path.isdir(os.path.join(REPO, "scratch")) and os.listdir(os.path.join(REPO, "scratch")))

    def test_out_in_a_protected_folder_is_refused(self):
        spec = importlib.util.spec_from_file_location("reencode_under_test", TOOL)
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        protected = os.path.join(self.tmp, "protected")
        os.makedirs(protected, exist_ok=True)
        target = os.path.join(protected, "probe.mvar")
        with mock.patch.object(mio, "DEFAULT_PROTECTED", (protected,)):
            err, out = stdio.StringIO(), stdio.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
                code = tool.main([self.files["w1_minimal"], target])
            self.assertEqual(code, 2)
            self.assertIn("Refusing to write into the protected folder", err.getvalue())
            self.assertFalse(os.path.exists(target))
            ok_target = os.path.join(self.tmp, "fine.mvar")
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
                self.assertEqual(tool.main([self.files["w1_minimal"], ok_target]), 0)
            self.assertEqual(self.read(ok_target), h.g3.data("w1_minimal"))

    def test_the_real_protected_folders_are_in_force_without_patching(self):
        folder = os.path.expanduser("~/Local_Documents/Halo-MCC/variant-tool/test-samples")
        if not os.path.isdir(folder):
            self.skipTest("the sample folder is absent")
        existing = sorted(n for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n)))
        if not existing:
            self.skipTest("the sample folder is empty")
        below_a_file = os.path.join(folder, existing[0], "reencode_should_not_exist.mvar")     # cannot be created even if the policy broke
        code, stdout, stderr = run(self.files["w1_minimal"], below_a_file)
        self.assertEqual(code, 2)
        self.assertIn("Refusing to write into the protected folder", stderr)

    def test_a_game_variant_and_garbage_are_exit_2(self):
        import helpers_real
        sample = helpers_real.distinct_samples(helpers_real.load_samples())[0]
        code, stdout, stderr = run(sample.path, self.out("game.mvar"))
        self.assertEqual(code, 2)
        self.assertIn("This is a game variant", stderr)
        junk = os.path.join(self.tmp, "junk.bin")
        with open(junk, "wb") as fh:
            fh.write(b"not a blf file at all " * 5)
        self.assertEqual(run(junk, self.out("junk.mvar"))[0], 2)
        self.assertEqual(run(os.path.join(self.tmp, "missing.mvar"), self.out("m.mvar"))[0], 2)
        self.assertFalse(os.path.exists(self.out("game.mvar")))

    def test_an_undecodable_map_variant_is_exit_1(self):
        out = self.out("desync.mvar")
        code, stdout, stderr = run(self.files["desync_length"], out)
        self.assertEqual(code, 1)
        self.assertIn("Could not read this map variant", stderr)
        self.assertFalse(os.path.exists(out))

    def test_a_failed_self_test_writes_nothing_and_exits_3(self):
        """A wrong `_eof` value is repaired by a forced re-encode, so the forced file differs from the input: the self-test fails."""
        data = bytearray(h.g3.data("w1_minimal"))
        data[0x7318 + 12:0x7318 + 16] = struct.pack(">I", 0x7319)
        broken = os.path.join(self.tmp, "bad_eof.mvar")
        with open(broken, "wb") as fh:
            fh.write(bytes(data))
        out = self.out("never.mvar")
        code, stdout, stderr = run(broken, out, "--force")
        self.assertEqual(code, 3)
        self.assertIn("SELF-TEST FAILED", stderr)
        self.assertIn("nothing was written", stderr)
        self.assertFalse(os.path.exists(out))
        code, stdout, stderr = run(broken, out)                                  # the passthrough copy has no self-test and no repair
        self.assertEqual(code, 0)
        self.assertEqual(self.read(out), bytes(data))


class TestReadsOnlyThroughTheLibrary(unittest.TestCase):
    def test_the_tool_has_no_other_writer(self):
        with open(TOOL, "r", encoding="utf-8") as fh:
            source = fh.read()
        self.assertIn("write_atomic", source)
        for banned in ("open(args.output", "shutil.copy", "os.rename", "os.replace(", ".write_bytes(", "\"wb\""):
            self.assertNotIn(banned, source)


if __name__ == "__main__":
    unittest.main()
