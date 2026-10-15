"""Shared helpers for the tier-T1 tests: the real Reach game-variant sample files (SPEC 9.1, 9.2, 9.3).

* The samples are found in the two known folders or in ``$MJOLNIR_SAMPLES`` (``helpers_snapshot``),
  are opened ``rb`` only through :func:`open_sample` (test U-21 relies on that) and are never copied.
* Without the ``--samples`` flag a missing sample folder SKIPS the T1 tests with a loud notice; with
  the flag (``MJOLNIR_REQUIRE_SAMPLES=1``) it is a failure, and so is finding fewer than the 8 paths /
  5 distinct contents the spec describes.
* :class:`PassLog` collects the ``PASS <file> <sha256[:16]>`` lines of acceptance row 1 (SPEC 9.8) and
  prints them once the test class is done, so the lines are not glued to unittest's progress dots.

Python 3.9 to 3.13, standard library only.
"""
import hashlib
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for _path in (HERE, os.path.join(REPO, "Addon")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import helpers_snapshot  # noqa: E402  (tests/unit/helpers_snapshot.py)

EXPECTED_PATHS = 8
EXPECTED_DISTINCT = 5


class Sample(object):
    """One real sample file: ``path``, its ``data`` (bytes) and ``sha16`` (first 16 hex digits of the SHA-256)."""

    def __init__(self, path, data):
        self.path = path
        self.data = data
        self.sha256 = hashlib.sha256(data).hexdigest()
        self.sha16 = self.sha256[:16]

    @property
    def name(self):
        return os.path.basename(self.path)

    def __repr__(self):
        return "Sample(%s, %d bytes, %s)" % (self.path, len(self.data), self.sha16)


def require_samples():
    """True when ``--samples`` (or ``MJOLNIR_REQUIRE_SAMPLES=1``) made the real files mandatory."""
    return os.environ.get("MJOLNIR_REQUIRE_SAMPLES") == "1"


def open_sample(path):
    """The only way a test opens a sample file: read-only, binary."""
    return open(path, "rb")


def read_sample(path):
    with open_sample(path) as handle:
        return handle.read()


def load_samples():
    """All sample files as :class:`Sample` objects, sorted by path.

    Raises ``unittest.SkipTest`` (loudly) when there are none and they are not required, and fails
    when they are required but fewer than the 8 paths / 5 distinct contents of the spec exist.
    """
    paths = helpers_snapshot.sample_bin_files()
    if not paths:
        if require_samples():
            raise AssertionError("--samples was given but no real sample *.bin files were found in %s or $MJOLNIR_SAMPLES"
                                 % ", ".join(helpers_snapshot.KNOWN_SAMPLE_DIRS))
        raise unittest.SkipTest("NOTICE: no real sample files found; this T1 test is SKIPPED (use --samples to make it a failure)")
    samples = [Sample(path, read_sample(path)) for path in paths]
    if require_samples():
        distinct = len(set(s.sha256 for s in samples))
        if len(samples) < EXPECTED_PATHS or distinct < EXPECTED_DISTINCT:
            raise AssertionError("expected at least %d sample paths with %d distinct contents, found %d paths and %d distinct"
                                 % (EXPECTED_PATHS, EXPECTED_DISTINCT, len(samples), distinct))
    return samples


def distinct_samples(samples):
    """One sample per distinct content (the first path in sorted order)."""
    seen = set()
    out = []
    for sample in samples:
        if sample.sha256 not in seen:
            seen.add(sample.sha256)
            out.append(sample)
    return out


class PassLog(object):
    """Collects ``PASS <file> <sha256[:16]>`` lines and prints them when the test class finishes."""

    def __init__(self, label):
        self.label = label
        self.lines = []

    def add(self, sample):
        self.lines.append("PASS %s %s" % (sample.path, sample.sha16))

    def flush(self):
        if not self.lines:
            return
        out = sys.stdout
        out.write("\n")
        for line in self.lines:
            out.write(line + "\n")
        out.write("%s: %d file(s) passed every clause\n" % (self.label, len(self.lines)))
        out.flush()
        self.lines = []
