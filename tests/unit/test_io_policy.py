"""U-18 (SPEC 9.3, 2.13): the output path policy of mvarlib.io.

Every write in this module happens inside a temp directory. The real protected folders
(``~/Local_Documents/Halo-MCC/variant-tool/test-samples`` ...) are only ever passed to ``check_output_path``, which
does no I/O; nothing here can write into them even if the policy were broken, because writes use
an explicit ``protected`` list that points into the temp directory.
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "Addon"))

from mvarlib import io as mio  # noqa: E402
from mvarlib.api import Issue  # noqa: E402
from mvarlib.errors import FormatError, InternalError, PathPolicyError  # noqa: E402


def write(path, data=b"original"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def read(path):
    with open(path, "rb") as fh:
        return fh.read()


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = os.path.realpath(self._tmp.name)
        self.src = os.path.join(self.tmp, "samples", "in.mvar")
        write(self.src, b"SOURCE BYTES")
        self.protected_dir = os.path.join(self.tmp, "protected")
        os.makedirs(self.protected_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def listing(self, folder=None):
        return sorted(os.listdir(folder or self.tmp))


class TestCheckOutputPath(Base):
    def test_same_file_is_refused_with_the_documented_text(self):
        issue = mio.check_output_path(self.src, [self.src], protected=[])
        self.assertIsInstance(issue, Issue)
        self.assertEqual((issue.code, issue.severity), ("E_PATH_SAME_AS_SOURCE", "error"))
        self.assertEqual(issue.message, "Refusing to overwrite the file this map was imported from (%s). "
                                        "Choose a different name." % self.src)

    def test_same_file_through_a_target_symlink(self):
        link = os.path.join(self.tmp, "out", "link.mvar")
        os.makedirs(os.path.dirname(link))
        os.symlink(self.src, link)
        issue = mio.check_output_path(link, [self.src], protected=[])
        self.assertEqual(issue.code, "E_PATH_SAME_AS_SOURCE")

    def test_same_file_through_a_source_symlink(self):
        link = os.path.join(self.tmp, "out", "srclink.mvar")
        os.makedirs(os.path.dirname(link))
        os.symlink(self.src, link)
        self.assertEqual(mio.check_output_path(self.src, [link], protected=[]).code, "E_PATH_SAME_AS_SOURCE")

    def test_same_file_through_a_hard_link(self):
        hard = os.path.join(self.tmp, "out", "hard.mvar")
        os.makedirs(os.path.dirname(hard))
        os.link(self.src, hard)
        self.assertEqual(mio.check_output_path(hard, [self.src], protected=[]).code, "E_PATH_SAME_AS_SOURCE")

    def test_same_file_with_dot_segments_and_relative_paths(self):
        tricky = os.path.join(self.tmp, "samples", "..", "samples", ".", "in.mvar")
        self.assertEqual(mio.check_output_path(tricky, [self.src], protected=[]).code, "E_PATH_SAME_AS_SOURCE")
        cwd = os.getcwd()
        try:
            os.chdir(os.path.join(self.tmp, "samples"))
            self.assertEqual(mio.check_output_path("in.mvar", [self.src], protected=[]).code, "E_PATH_SAME_AS_SOURCE")
        finally:
            os.chdir(cwd)

    def test_different_file_next_to_the_source_is_fine(self):
        other = os.path.join(self.tmp, "samples", "in_mjolnir.mvar")
        self.assertIsNone(mio.check_output_path(other, [self.src], protected=[]))

    def test_empty_and_missing_sources_are_ignored(self):
        out = os.path.join(self.tmp, "o.mvar")
        self.assertIsNone(mio.check_output_path(out, ["", None, os.path.join(self.tmp, "does-not-exist.mvar")], protected=[]))
        self.assertIsNone(mio.check_output_path(out, (), protected=[]))

    def test_protected_folder_direct_and_nested(self):
        for rel in ("x.mvar", os.path.join("a", "b", "c.mvar")):
            target = os.path.join(self.protected_dir, rel)
            issue = mio.check_output_path(target, [], protected=[self.protected_dir])
            self.assertEqual(issue.code, "E_PATH_PROTECTED", rel)
            self.assertEqual(issue.message, "Refusing to write into the protected folder %s." % self.protected_dir)

    def test_protected_check_follows_symlinked_folders(self):
        alias = os.path.join(self.tmp, "alias")
        os.symlink(self.protected_dir, alias)
        issue = mio.check_output_path(os.path.join(alias, "x.mvar"), [], protected=[self.protected_dir])
        self.assertEqual(issue.code, "E_PATH_PROTECTED")
        issue = mio.check_output_path(os.path.join(self.tmp, "x.mvar"), [], protected=[alias])
        self.assertIsNone(issue)
        issue = mio.check_output_path(os.path.join(self.protected_dir, "x.mvar"), [], protected=[alias])
        self.assertEqual(issue.code, "E_PATH_PROTECTED")

    def test_symlink_pointing_into_a_protected_folder(self):
        link = os.path.join(self.tmp, "out", "sneaky.mvar")
        os.makedirs(os.path.dirname(link))
        os.symlink(os.path.join(self.protected_dir, "target.mvar"), link)           # dangling on purpose
        self.assertEqual(mio.check_output_path(link, [], protected=[self.protected_dir]).code, "E_PATH_PROTECTED")

    def test_sibling_with_a_common_prefix_is_not_protected(self):
        sibling = self.protected_dir + "-not"
        os.makedirs(sibling)
        self.assertIsNone(mio.check_output_path(os.path.join(sibling, "x.mvar"), [], protected=[self.protected_dir]))

    def test_the_defaults_are_the_three_named_folders(self):
        home = os.path.expanduser("~")
        self.assertEqual(mio.default_protected_dirs(),
                         [os.path.join(home, "Local_Documents", "Halo-MCC", "variant-tool", "test-samples"),
                          os.path.join(home, "Local_Documents", "Halo-MCC", "variant-tool", "ReachVariantTool-core-library"),
                          os.path.join(home, "Local_Documents", "Halo-MCC", "forge", "real-mvar-samples")])
        for folder in mio.default_protected_dirs():           # no I/O: the target is only checked, never created
            target = os.path.join(folder, "macos", "Fixtures", "anything_mjolnir.mvar")
            self.assertEqual(mio.check_output_path(target).code, "E_PATH_PROTECTED")
            self.assertEqual(mio.check_output_path(target, protected=None).code, "E_PATH_PROTECTED")
            self.assertIsNone(mio.check_output_path(target, protected=[]))          # explicit empty list: nothing protected
        self.assertIsNone(mio.check_output_path(os.path.join(self.tmp, "fine.mvar")))

    def test_same_source_check_comes_first(self):
        issue = mio.check_output_path(self.src, [self.src], protected=[os.path.dirname(self.src)])
        self.assertEqual(issue.code, "E_PATH_SAME_AS_SOURCE")


class TestWriteAtomic(Base):
    def test_writes_exact_bytes_and_leaves_nothing_else(self):
        out = os.path.join(self.tmp, "out", "result.mvar")
        mio.write_atomic(out, b"\x00\x01payload\xff", [self.src], [self.protected_dir])
        self.assertEqual(read(out), b"\x00\x01payload\xff")
        self.assertEqual(self.listing(os.path.dirname(out)), ["result.mvar"])
        self.assertEqual(read(self.src), b"SOURCE BYTES")

    def test_accepts_bytearray_and_memoryview_rejects_str(self):
        out = os.path.join(self.tmp, "o.mvar")
        mio.write_atomic(out, bytearray(b"abc"), protected=[])
        self.assertEqual(read(out), b"abc")
        mio.write_atomic(out, memoryview(b"xyz"), protected=[])
        self.assertEqual(read(out), b"xyz")
        with self.assertRaises(TypeError):
            mio.write_atomic(out, "text", protected=[])
        self.assertEqual(read(out), b"xyz")

    def test_refuses_the_source_even_through_a_symlink_and_leaves_it_untouched(self):
        link = os.path.join(self.tmp, "out", "link.mvar")
        os.makedirs(os.path.dirname(link))
        os.symlink(self.src, link)
        for target in (self.src, link):
            with self.assertRaises(PathPolicyError) as cm:
                mio.write_atomic(target, b"overwrite!", [self.src], [self.protected_dir])
            self.assertIn("Refusing to overwrite the file this map was imported from", str(cm.exception))
        self.assertEqual(read(self.src), b"SOURCE BYTES")
        self.assertEqual(self.listing(os.path.dirname(self.src)), ["in.mvar"])
        self.assertTrue(os.path.islink(link))

    def test_refuses_a_hard_link_to_the_source(self):
        hard = os.path.join(self.tmp, "out", "hard.mvar")
        os.makedirs(os.path.dirname(hard))
        os.link(self.src, hard)
        with self.assertRaises(PathPolicyError):
            mio.write_atomic(hard, b"overwrite!", [self.src], [])
        self.assertEqual(read(self.src), b"SOURCE BYTES")
        self.assertEqual(read(hard), b"SOURCE BYTES")

    def test_refuses_a_protected_folder_before_touching_anything(self):
        target = os.path.join(self.protected_dir, "new", "deep", "x.mvar")
        with self.assertRaises(PathPolicyError) as cm:
            mio.write_atomic(target, b"nope", [], [self.protected_dir])
        self.assertIn("Refusing to write into the protected folder", str(cm.exception))
        self.assertEqual(os.listdir(self.protected_dir), [])               # not even the new/deep folders were created

    def test_creates_no_backup_and_replaces_atomically(self):
        out = os.path.join(self.tmp, "out", "result.mvar")
        write(out, b"OLD CONTENT")
        neighbour = os.path.join(self.tmp, "out", "neighbour.mvar")
        write(neighbour, b"NEIGHBOUR")
        mio.write_atomic(out, b"NEW CONTENT", [self.src], [])
        self.assertEqual(read(out), b"NEW CONTENT")
        self.assertEqual(read(neighbour), b"NEIGHBOUR")
        self.assertEqual(self.listing(os.path.dirname(out)), ["neighbour.mvar", "result.mvar"])   # no .bak, no .tmp-*
        self.assertFalse([n for n in os.listdir(os.path.dirname(out)) if n.endswith(".bak") or ".tmp-" in n])

    def test_uses_a_temp_file_in_the_same_directory_with_the_pid(self):
        out = os.path.join(self.tmp, "out", "result.mvar")
        seen = {}

        def verify(data):
            seen["listing"] = sorted(os.listdir(os.path.dirname(out)))
            seen["data"] = data
            return True

        mio.write_atomic(out, b"abc", verify=verify)
        self.assertEqual(seen["listing"], ["result.mvar.tmp-%d" % os.getpid()])
        self.assertEqual(seen["data"], b"abc")
        self.assertEqual(self.listing(os.path.dirname(out)), ["result.mvar"])

    def test_failed_verify_leaves_nothing_behind_and_keeps_the_old_target(self):
        out = os.path.join(self.tmp, "out", "result.mvar")
        write(out, b"OLD CONTENT")

        def bad_verify(data):
            raise ValueError("re-parse failed")

        with self.assertRaises(ValueError):
            mio.write_atomic(out, b"NEW CONTENT", verify=bad_verify)
        self.assertEqual(read(out), b"OLD CONTENT")
        self.assertEqual(self.listing(os.path.dirname(out)), ["result.mvar"])

        with self.assertRaises(InternalError):
            mio.write_atomic(out, b"NEW CONTENT", verify=lambda data: False)
        self.assertEqual(read(out), b"OLD CONTENT")
        self.assertEqual(self.listing(os.path.dirname(out)), ["result.mvar"])

    def test_failed_verify_on_a_new_target_creates_no_file(self):
        out = os.path.join(self.tmp, "out", "never.mvar")

        def bad_verify(data):
            raise RuntimeError("no")

        with self.assertRaises(RuntimeError):
            mio.write_atomic(out, b"x", verify=bad_verify)
        self.assertEqual(self.listing(os.path.dirname(out)), [])

    def test_an_existing_temp_name_is_never_overwritten(self):
        out = os.path.join(self.tmp, "out", "result.mvar")
        stale = out + ".tmp-%d" % os.getpid()
        write(stale, b"STALE FROM ANOTHER RUN")
        mio.write_atomic(out, b"fresh")
        self.assertEqual(read(out), b"fresh")
        self.assertEqual(read(stale), b"STALE FROM ANOTHER RUN")

    def test_folder_target_is_refused(self):
        folder = os.path.join(self.tmp, "a_folder")
        os.makedirs(folder)
        with self.assertRaises(PathPolicyError):
            mio.write_atomic(folder, b"x", protected=[])
        self.assertEqual(os.listdir(folder), [])

    def test_missing_parent_folder_is_created_unless_disabled(self):
        out = os.path.join(self.tmp, "Mjolnir Exports", "x_mjolnir.mvar")
        with self.assertRaises(FileNotFoundError):
            mio.write_atomic(out, b"x", protected=[], make_dirs=False)
        self.assertFalse(os.path.exists(os.path.dirname(out)))
        mio.write_atomic(out, b"x", protected=[])
        self.assertEqual(read(out), b"x")

    def test_a_symlink_target_is_replaced_not_followed(self):
        elsewhere = os.path.join(self.tmp, "elsewhere", "precious.mvar")
        write(elsewhere, b"PRECIOUS")
        link = os.path.join(self.tmp, "out", "link.mvar")
        os.makedirs(os.path.dirname(link))
        os.symlink(elsewhere, link)
        mio.write_atomic(link, b"new", [self.src], [self.protected_dir])
        self.assertEqual(read(elsewhere), b"PRECIOUS")
        self.assertFalse(os.path.islink(link))
        self.assertEqual(read(link), b"new")

    def test_case_insensitive_volume_alias_of_the_source(self):
        upper = os.path.join(self.tmp, "samples", "IN.MVAR")
        if not os.path.exists(upper):
            self.skipTest("this volume is case sensitive")
        with self.assertRaises(PathPolicyError):
            mio.write_atomic(upper, b"overwrite!", [self.src], [])
        self.assertEqual(read(self.src), b"SOURCE BYTES")


class TestReadAndDefaults(Base):
    def test_read_file_reads_binary_and_limits_size(self):
        self.assertEqual(mio.read_file(self.src), b"SOURCE BYTES")
        self.assertEqual(mio.read_file(self.src, max_bytes=12), b"SOURCE BYTES")
        with self.assertRaises(FormatError):
            mio.read_file(self.src, max_bytes=11)
        with self.assertRaises(FileNotFoundError):
            mio.read_file(os.path.join(self.tmp, "nope.mvar"))

    def test_read_file_does_not_modify_the_file(self):
        before = os.stat(self.src)
        mio.read_file(self.src)
        after = os.stat(self.src)
        self.assertEqual((before.st_size, before.st_mtime_ns), (after.st_size, after.st_mtime_ns))

    def test_default_output_name_is_next_to_the_source(self):
        out = mio.default_output_path(self.src, protected=[self.protected_dir])
        self.assertEqual(out, os.path.join(os.path.dirname(self.src), "in_mjolnir.mvar"))
        self.assertIsNone(mio.check_output_path(out, [self.src], [self.protected_dir]))

    def test_default_output_name_falls_back_when_the_source_folder_is_protected(self):
        src = os.path.join(self.protected_dir, "map.mvar")
        fallback = os.path.join(self.tmp, "Exports")
        out = mio.default_output_path(src, protected=[self.protected_dir], fallback_dir=fallback)
        self.assertEqual(out, os.path.join(fallback, "map_mjolnir.mvar"))
        self.assertIsNone(mio.check_output_path(out, [src], [self.protected_dir]))
        self.assertTrue(mio.default_output_path(src, protected=[self.protected_dir]).endswith(
            os.path.join("Documents", "Mjolnir Exports", "map_mjolnir.mvar")))


if __name__ == "__main__":
    unittest.main()
