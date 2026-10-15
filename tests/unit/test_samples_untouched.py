"""U-21 (SPEC 9.3, 9.8 row 6): the original sample files are never touched.

``tools/run_tests.py`` records ``(path, size, mtime_ns, sha256)`` of every sample file and of every
``*.bin``/``*.mvar`` in the protected folders before the first test and again after the last one
(``helpers_snapshot.py``); any difference fails the run and names the file. This module proves
that mechanism, in a temp directory (a planted "sample" folder through ``$MJOLNIR_SAMPLES``), and
checks the real folders for stability. It never opens a real sample for writing.
"""
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
RUNNER = os.path.join(REPO, "tools", "run_tests.py")
sys.path.insert(0, HERE)

import helpers_snapshot as snap  # noqa: E402


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


class TestSnapshotMechanism(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = os.path.realpath(self._tmp.name)
        self.samples = os.path.join(self.tmp, "samples")
        self.protected = os.path.join(self.tmp, "protected")
        write(os.path.join(self.samples, "a.bin"), b"AAAA")
        write(os.path.join(self.samples, "sub", "b.bin"), b"BBBB")
        write(os.path.join(self.protected, "deep", "c.bin"), b"CCCC")
        write(os.path.join(self.protected, "readme.txt"), b"text is not in scope")
        write(os.path.join(self.protected, "build", "d.bin"), b"skipped dir")
        self.env = {"MJOLNIR_SAMPLES": self.samples, "MJOLNIR_PROTECTED": self.protected}

    def tearDown(self):
        self._tmp.cleanup()

    def take(self):
        return snap.take_snapshot(self.env)

    def test_scope(self):
        shot = self.take()
        self.assertIn(os.path.join(self.samples, "a.bin"), shot)
        self.assertIn(os.path.join(self.samples, "sub", "b.bin"), shot)
        self.assertIn(os.path.join(self.protected, "deep", "c.bin"), shot)
        self.assertNotIn(os.path.join(self.protected, "readme.txt"), shot)
        self.assertNotIn(os.path.join(self.protected, "build", "d.bin"), shot)
        size, mtime, digest = shot[os.path.join(self.samples, "a.bin")]
        self.assertEqual(size, 4)
        self.assertEqual(digest, "63c1dd951ffedf6f7fd968ad4efa39b8ed584f162f46e715114ee184f8de9201")

    def test_unchanged_snapshots_compare_equal(self):
        self.assertEqual(snap.compare_snapshots(self.take(), self.take()), [])

    def test_modification_with_same_size_and_restored_mtime_is_still_caught(self):
        target = os.path.join(self.samples, "a.bin")
        before = self.take()
        st = os.stat(target)
        write(target, b"ZZZZ")
        os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns))
        problems = snap.compare_snapshots(before, self.take())
        self.assertEqual(len(problems), 1)
        self.assertIn("MODIFIED", problems[0])
        self.assertIn(target, problems[0])
        self.assertIn("sha256", problems[0])

    def test_creation_deletion_and_mtime_changes_are_caught(self):
        before = self.take()
        write(os.path.join(self.samples, "new_mjolnir.mvar"), b"x")
        write(os.path.join(self.protected, "deep", "out.mvar"), b"x")
        os.remove(os.path.join(self.samples, "sub", "b.bin"))
        os.utime(os.path.join(self.protected, "deep", "c.bin"), ns=(1, 1))
        problems = snap.compare_snapshots(before, self.take())
        joined = "\n".join(problems)
        self.assertIn("CREATED   " + os.path.join(self.samples, "new_mjolnir.mvar"), joined)
        self.assertIn("CREATED   " + os.path.join(self.protected, "deep", "out.mvar"), joined)
        self.assertIn("DELETED   " + os.path.join(self.samples, "sub", "b.bin"), joined)
        self.assertIn("MODIFIED  " + os.path.join(self.protected, "deep", "c.bin"), joined)
        self.assertEqual(len(problems), 4, joined)

    def test_sample_discovery(self):
        self.assertEqual(snap.sample_bin_files(self.env),
                         sorted(snap.sample_bin_files(self.env)))
        found = snap.sample_bin_files({"MJOLNIR_SAMPLES": self.samples})
        self.assertIn(os.path.join(self.samples, "a.bin"), found)
        self.assertIn(os.path.join(self.samples, "sub", "b.bin"), found)
        multi = snap.sample_dirs({"MJOLNIR_SAMPLES": self.samples + os.pathsep + os.path.join(self.tmp, "nope")})
        self.assertIn(self.samples, multi)
        self.assertNotIn(os.path.join(self.tmp, "nope"), multi)


class TestRealFolders(unittest.TestCase):
    def test_snapshot_of_the_real_folders_is_stable_and_read_only(self):
        first = snap.take_snapshot()
        second = snap.take_snapshot()
        self.assertEqual(snap.compare_snapshots(first, second), [])
        for path in first:
            self.assertTrue(os.path.isfile(path))

    def test_known_sample_folders_are_what_the_spec_names(self):
        home = os.path.expanduser("~")
        self.assertEqual([os.path.expanduser(p) for p in snap.KNOWN_SAMPLE_DIRS],
                         [os.path.join(home, "Local_Documents", "Halo-MCC", "variant-tool", "test-samples"),
                          os.path.join(home, "Local_Documents", "Halo-MCC", "variant-tool", "ReachVariantTool-core-library", "macos", "Fixtures")])


MUTATOR = textwrap.dedent('''
    import os, unittest

    class TestMutator(unittest.TestCase):
        def test_touch_the_planted_sample(self):
            path = os.path.join(os.environ["MJOLNIR_SAMPLES"], "victim.bin")
            with open(path, "ab") as fh:
                fh.write(b"tampered")

    class TestHarmless(unittest.TestCase):
        def test_passes(self):
            self.assertTrue(True)
''')
HARMLESS = textwrap.dedent('''
    import unittest

    class TestHarmless(unittest.TestCase):
        def test_passes(self):
            self.assertTrue(True)

        def test_skips_loudly(self):
            self.skipTest("NOTICE: demonstration skip reason")
''')


class TestRunnerWrapsTheRunInTheCheck(unittest.TestCase):
    """End to end: a test that appends to a planted sample makes tools/run_tests.py fail and name the file."""

    def run_runner(self, tests_dir, samples_dir, *extra):
        env = dict(os.environ)
        env["MJOLNIR_SAMPLES"] = samples_dir
        return subprocess.run([sys.executable, "-I", RUNNER, "--tests-dir", tests_dir] + list(extra), env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)

    def test_runner_fails_and_names_the_touched_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            samples = os.path.join(tmp, "samples")
            tests = os.path.join(tmp, "tests")
            write(os.path.join(samples, "victim.bin"), b"original sample bytes")
            write(os.path.join(tests, "test_mutator.py"), MUTATOR.encode())
            result = self.run_runner(tests, samples, "--only", "Mutator")
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("FAILED U-21", result.stdout)
            self.assertIn("MODIFIED  " + os.path.join(samples, "victim.bin"), result.stdout)
            self.assertIn("RESULT: FAIL", result.stdout)

    def test_runner_is_green_and_reports_skips_loudly_when_nothing_is_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            samples = os.path.join(tmp, "samples")
            tests = os.path.join(tmp, "tests")
            write(os.path.join(samples, "victim.bin"), b"original sample bytes")
            write(os.path.join(tests, "test_harmless.py"), HARMLESS.encode())
            result = self.run_runner(tests, samples)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("unchanged by this run", result.stdout)
            self.assertIn("SKIPPED (1):", result.stdout)
            self.assertIn("NOTICE: demonstration skip reason", result.stdout)
            self.assertIn("RESULT: PASS", result.stdout)
            with open(os.path.join(samples, "victim.bin"), "rb") as fh:
                self.assertEqual(fh.read(), b"original sample bytes")

    def test_nothing_matched_is_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tests = os.path.join(tmp, "tests")
            write(os.path.join(tests, "test_harmless.py"), HARMLESS.encode())
            result = self.run_runner(tests, tmp, "--only", "no_such_test")
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("no tests matched", result.stdout)

    def test_fixtures_dir_inside_the_repo_is_refused(self):
        result = subprocess.run([sys.executable, "-I", RUNNER, "--fixtures-dir", os.path.join(REPO, "scratch", "fx"),
                                 "--only", "no_such_test"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                universal_newlines=True)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("inside the repository", result.stdout)
        self.assertFalse(os.path.exists(os.path.join(REPO, "scratch")))

    def test_samples_flag_without_samples_is_a_failure_and_without_the_flag_a_loud_notice(self):
        with tempfile.TemporaryDirectory() as tmp:
            tests = os.path.join(tmp, "tests")
            write(os.path.join(tests, "test_harmless.py"), HARMLESS.encode())
            env = dict(os.environ, HOME=tmp)               # no ~/Local_Documents under this HOME
            env.pop("MJOLNIR_SAMPLES", None)
            base = [sys.executable, "-I", RUNNER, "--tests-dir", tests]
            strict = subprocess.run(base + ["--samples"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    universal_newlines=True)
            self.assertEqual(strict.returncode, 1, strict.stdout)
            self.assertIn("--samples was given but no sample", strict.stdout)
            lax = subprocess.run(base, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
            self.assertEqual(lax.returncode, 0, lax.stdout)
            self.assertIn("NOTICE: no real sample files found; T1", lax.stdout)


if __name__ == "__main__":
    unittest.main()
