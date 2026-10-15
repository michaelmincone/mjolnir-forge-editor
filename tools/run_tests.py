#!/usr/bin/env python3
"""Test driver for the pure-Python tests (SPEC 9.2, DEC-9.3).

    /usr/bin/python3 -I tools/run_tests.py [--samples] [--only SUBSTR ...] [-v] [--fixtures-dir DIR]
    <blender python3.13> -I tools/run_tests.py ...        # same suite on Python 3.13

Discovers ``tests/unit/test_*.py`` with ``unittest`` (no pytest dependency on the system Python).
``tests/`` is never a package and never on ``sys.path``: every test module inserts ``Addon/``
itself, and this driver inserts only ``tests/unit`` (for the shared helpers).

Options
  --samples          T1 needs the real game-variant sample files. Without the flag a missing sample
                     folder SKIPS T1 with a loud notice; with the flag it is a failure. The folders
                     are the two known ones or ``$MJOLNIR_SAMPLES``; the files are never copied.
  --only SUBSTR ...  run only tests whose id contains one of the substrings (``--only blf_real``)
  -v                 verbose (one line per test)
  --fixtures-dir DIR where generated fixtures are written (exported as ``MJOLNIR_FIXTURES_DIR``);
                     default a fresh temp directory. A directory inside the repository is refused:
                     fixtures are generated at test time and never written into the tree.
  --tests-dir DIR    discover tests somewhere else (the driver's own tests use this)

The whole run is wrapped in the "originals untouched" check U-21: before the first test the driver
records ``(path, size, mtime_ns, sha256)`` of the sample files and of every ``*.bin``/``*.mvar`` in
the protected folders (``tests/unit/helpers_snapshot.py``); after the last test it records them
again; any difference fails the run and names the file.

Exit status: 0 all green, 1 a test failed / samples touched / nothing matched / samples required but
missing, 2 usage error.
"""
import argparse
import os
import shutil
import sys
import tempfile
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_UNIT = os.path.join(REPO, "tests", "unit")
sys.path.insert(0, TESTS_UNIT)

import helpers_snapshot  # noqa: E402  (tests/unit/helpers_snapshot.py)


def _iter_tests(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            for sub in _iter_tests(item):
                yield sub
        else:
            yield item


def _select(suite, substrings):
    """Keep tests whose id contains a substring; import failures are always kept (never hide them)."""
    chosen = unittest.TestSuite()
    for test in _iter_tests(suite):
        if not substrings or type(test).__name__ == "_FailedTest" or any(s in test.id() for s in substrings):
            chosen.addTest(test)
    return chosen


def _inside_repo(path):
    real = os.path.realpath(path)
    root = os.path.realpath(REPO)
    return real == root or real.startswith(root + os.sep)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--samples", action="store_true", help="the real sample files are required (T1)")
    ap.add_argument("--only", nargs="+", metavar="SUBSTR", help="run only tests whose id contains a substring")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--fixtures-dir", metavar="DIR")
    ap.add_argument("--tests-dir", metavar="DIR", default=TESTS_UNIT)
    args = ap.parse_args(argv)

    if args.fixtures_dir and _inside_repo(args.fixtures_dir):
        print("run_tests: refusing --fixtures-dir %s: it is inside the repository" % args.fixtures_dir, file=sys.stderr)
        return 2

    import zlib
    print("python %s (zlib %s) on %s" % (sys.version.split()[0], zlib.ZLIB_VERSION, sys.platform))

    samples = helpers_snapshot.sample_bin_files()
    if not samples:
        if args.samples:
            print("run_tests: --samples was given but no sample *.bin files were found in %s or $MJOLNIR_SAMPLES"
                  % ", ".join(helpers_snapshot.KNOWN_SAMPLE_DIRS), file=sys.stderr)
            return 1
        print("=" * 78)
        print("NOTICE: no real sample files found; T1 (real game-variant files) will be SKIPPED.")
        print("        Use --samples to make that a failure. Folders looked at:")
        for folder in helpers_snapshot.KNOWN_SAMPLE_DIRS:
            print("          " + os.path.expanduser(folder))
        print("=" * 78)
    else:
        print("samples: %d *.bin file(s) in %d folder(s)" % (len(samples), len(helpers_snapshot.sample_dirs())))
    if args.samples:
        os.environ["MJOLNIR_REQUIRE_SAMPLES"] = "1"
    else:
        os.environ.pop("MJOLNIR_REQUIRE_SAMPLES", None)

    own_fixtures = None
    if args.fixtures_dir:
        os.makedirs(args.fixtures_dir, exist_ok=True)
        os.environ["MJOLNIR_FIXTURES_DIR"] = os.path.abspath(args.fixtures_dir)
    else:
        own_fixtures = tempfile.mkdtemp(prefix="mjolnir-fixtures-")
        os.environ["MJOLNIR_FIXTURES_DIR"] = own_fixtures

    tests_dir = os.path.abspath(args.tests_dir)
    loader = unittest.TestLoader()
    suite = _select(loader.discover(tests_dir, pattern="test_*.py", top_level_dir=tests_dir), args.only)
    count = suite.countTestCases()
    if count == 0:
        print("run_tests: no tests matched%s in %s" % (" --only " + " ".join(args.only) if args.only else "", tests_dir),
              file=sys.stderr)
        if own_fixtures:
            shutil.rmtree(own_fixtures, ignore_errors=True)
        return 1

    before = helpers_snapshot.take_snapshot()
    started = time.time()
    runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=2 if args.verbose else 1)
    result = runner.run(suite)
    elapsed = time.time() - started
    after = helpers_snapshot.take_snapshot()

    if result.skipped:
        print("")
        print("SKIPPED (%d):" % len(result.skipped))
        for test, reason in result.skipped:
            print("  %s: %s" % (test.id(), reason))
    touched = helpers_snapshot.compare_snapshots(before, after)
    status = 0 if result.wasSuccessful() else 1
    if touched:
        status = 1
        print("")
        print("FAILED U-21: the sample / protected files changed during the run (%d):" % len(touched))
        for line in touched:
            print("  " + line)
    else:
        print("U-21: %d sample / protected file(s) unchanged by this run" % len(before))

    if own_fixtures:
        shutil.rmtree(own_fixtures, ignore_errors=True)
    print("")
    print("RESULT: %s (%d tests, %d failures, %d errors, %d skipped, %.1fs)"
          % ("PASS" if status == 0 else "FAIL", result.testsRun, len(result.failures), len(result.errors),
             len(result.skipped), elapsed))
    return status


if __name__ == "__main__":
    sys.exit(main())
