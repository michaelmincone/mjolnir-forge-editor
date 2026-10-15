"""Sample-folder discovery and "originals untouched" snapshots (SPEC 9.2 DEC-9.3, test U-21).

Used by ``tools/run_tests.py`` (around the whole run) and by ``test_samples_untouched.py``.
Standard library only, Python 3.9 to 3.13. Nothing here ever opens a file for writing.

Scope of a snapshot (decision recorded in NOTES.md, G0):

* every regular file, recursively, in the two known sample folders
  (``~/Local_Documents/Halo-MCC/variant-tool/test-samples`` and ``~/Local_Documents/Halo-MCC/variant-tool/ReachVariantTool-core-library/macos/Fixtures``)
  and in every folder of ``$MJOLNIR_SAMPLES`` (an ``os.pathsep``-separated list);
* every ``*.bin`` and ``*.mvar`` file, recursively, anywhere inside the protected folders of
  SPEC 2.13 (build, ``.git`` and cache folders are skipped), so that nothing can be written
  *into* a protected folder unnoticed.

Each file is recorded as ``(size, mtime_ns, sha256)``. The rest of ``ReachVariantTool-core-library``
(about 5,000 files, 900 MB, with its own build directory under active development) is deliberately
not part of the snapshot: hashing it would be slow and any concurrent build would fail the run.
"""
import hashlib
import os

KNOWN_SAMPLE_DIRS = (
    "~/Local_Documents/Halo-MCC/variant-tool/test-samples",
    "~/Local_Documents/Halo-MCC/variant-tool/ReachVariantTool-core-library/macos/Fixtures",
)
PROTECTED_ROOTS = (
    "~/Local_Documents/Halo-MCC/variant-tool/test-samples",
    "~/Local_Documents/Halo-MCC/variant-tool/ReachVariantTool-core-library",
    "~/Local_Documents/Halo-MCC/forge/real-mvar-samples",       # the one real map variant (G3); *.mvar files are snapshotted
)
SKIP_DIRS = frozenset([".git", ".build", "build", "DerivedData", "__pycache__", "node_modules", ".swiftpm"])
PROTECTED_EXTENSIONS = (".bin", ".mvar")


def sample_dirs(environ=None):
    """Existing sample folders: the two known ones plus ``$MJOLNIR_SAMPLES`` (never copied)."""
    environ = os.environ if environ is None else environ
    candidates = [os.path.expanduser(p) for p in KNOWN_SAMPLE_DIRS]
    extra = environ.get("MJOLNIR_SAMPLES", "")
    candidates += [os.path.expanduser(p) for p in extra.split(os.pathsep) if p]
    seen = []
    for path in candidates:
        if os.path.isdir(path) and path not in seen:
            seen.append(path)
    return seen


def sample_bin_files(environ=None):
    """Sorted paths of every ``*.bin`` directly or indirectly inside the sample folders."""
    found = []
    for folder in sample_dirs(environ):
        for path in _walk_files(folder, skip_dirs=frozenset()):
            if path.lower().endswith(".bin"):
                found.append(path)
    return sorted(set(found))


def protected_roots(environ=None):
    environ = os.environ if environ is None else environ
    extra = environ.get("MJOLNIR_PROTECTED", "")
    roots = [os.path.expanduser(p) for p in PROTECTED_ROOTS]
    roots += [os.path.expanduser(p) for p in extra.split(os.pathsep) if p]
    return [r for r in roots if os.path.isdir(r)]


def _walk_files(folder, skip_dirs):
    for root, dirs, files in os.walk(folder, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in skip_dirs)
        for name in sorted(files):
            path = os.path.join(root, name)
            if os.path.isfile(path) and not os.path.islink(path):
                yield path


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:                     # read only
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _record(path):
    try:
        st = os.stat(path)
        return (st.st_size, st.st_mtime_ns, _sha256(path))
    except OSError as exc:
        return ("unreadable", str(exc.errno), "")


def take_snapshot(environ=None):
    """``{path: (size, mtime_ns, sha256)}`` for the scope described in the module docstring."""
    paths = set()
    for folder in sample_dirs(environ):
        paths.update(_walk_files(folder, skip_dirs=frozenset()))
    for root in protected_roots(environ):
        for path in _walk_files(root, skip_dirs=SKIP_DIRS):
            if path.lower().endswith(PROTECTED_EXTENSIONS):
                paths.add(path)
    return dict((p, _record(p)) for p in sorted(paths))


def compare_snapshots(before, after):
    """Human-readable differences between two snapshots (empty list = untouched)."""
    problems = []
    for path in sorted(set(before) | set(after)):
        if path not in after:
            problems.append("DELETED   %s" % path)
        elif path not in before:
            problems.append("CREATED   %s" % path)
        elif before[path] != after[path]:
            b, a = before[path], after[path]
            what = []
            if b[0] != a[0]:
                what.append("size %s -> %s" % (b[0], a[0]))
            if b[2] != a[2]:
                what.append("sha256 %s... -> %s..." % (b[2][:12], a[2][:12]))
            if b[1] != a[1]:
                what.append("mtime changed")
            problems.append("MODIFIED  %s (%s)" % (path, ", ".join(what)))
    return problems
