"""Shared access to the independent fixture builder (G2) for the unit tests and the Blender tests.

``tests/`` is never a package and never on ``sys.path`` (SPEC 9.3).  This helper loads ``tests/fixturebuilder`` as the
top-level package ``fixturebuilder`` straight from its file, so a test needs no path change::

    import helpers_fixtures as hf
    fb = hf.load()                                  # the package
    build, selfcheck = hf.modules()                 # the two modules most tests use
    data = hf.fixture_bytes("w1_minimal")           # bytes, built in memory
    path = hf.fixture_path("w1_minimal")            # the file, written into the temp fixtures directory

Fixtures are written only into ``$MJOLNIR_FIXTURES_DIR`` (set by ``tools/run_tests.py``; a fresh temp directory otherwise),
never into the repository; a directory inside the repository is refused.
"""
import atexit
import importlib
import importlib.util
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TESTS = os.path.join(REPO, "tests")
BUILDER = os.path.join(TESTS, "fixturebuilder")

_own_dir = []


def load():
    """The ``fixturebuilder`` package (imported once, from tests/fixturebuilder)."""
    if "fixturebuilder" in sys.modules:
        return sys.modules["fixturebuilder"]
    spec = importlib.util.spec_from_file_location("fixturebuilder", os.path.join(BUILDER, "__init__.py"),
                                                  submodule_search_locations=[BUILDER])
    module = importlib.util.module_from_spec(spec)
    sys.modules["fixturebuilder"] = module
    spec.loader.exec_module(module)
    return module


def modules():
    """(build, selfcheck) modules of the builder."""
    load()
    return importlib.import_module("fixturebuilder.build"), importlib.import_module("fixturebuilder.selfcheck")


def inside_repo(path):
    real = os.path.realpath(path)
    root = os.path.realpath(REPO)
    return real == root or real.startswith(root + os.sep)


def fixtures_dir():
    """Where fixture files are written: ``$MJOLNIR_FIXTURES_DIR`` or a private temp directory (removed at exit)."""
    env = os.environ.get("MJOLNIR_FIXTURES_DIR")
    if env:
        if inside_repo(env):
            raise RuntimeError("MJOLNIR_FIXTURES_DIR is inside the repository: " + env)
        os.makedirs(env, exist_ok=True)
        return env
    if not _own_dir:
        path = tempfile.mkdtemp(prefix="mjolnir-fixtures-")
        _own_dir.append(path)
        atexit.register(shutil.rmtree, path, True)
    return _own_dir[0]


def fixture_bytes(name):
    """Build the committed spec ``name`` in memory."""
    build, _ = modules()
    return build.build(build.load_spec(name)).data


def fixture_path(name):
    """Write fixture ``name`` into the fixtures directory (once per name) and return its path."""
    build, _ = modules()
    out = fixtures_dir()
    path = os.path.join(out, name + ".mvar")
    if not os.path.exists(path):
        with open(path, "wb") as fh:
            fh.write(build.build(build.load_spec(name)).data)
    return path


def all_names():
    build, _ = modules()
    return build.spec_names()
