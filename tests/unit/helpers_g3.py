"""Shared helpers of the G3 tests (read path, forced round trip, hypotheses, plain form, CLI).

* ``data(name)`` builds a fixture of the independent builder (``tests/fixturebuilder``) once per process and
  returns its bytes; ``spec(name)`` is the committed spec JSON (with its ``expect`` block); ``declared(name)``
  is the builder's fully normalised declared model.
* ``model(name)`` parses a fixture with ``mvarlib`` (cached; treat the result as read-only, use ``.copy()``).
* ``REAL_MVAR`` is the one real map variant (read-only original); ``real_data()`` reads it in place.

Fixtures are held in memory only; nothing is written. Python 3.9 to 3.13, standard library only.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for _path in (HERE, os.path.join(REPO, "Addon")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import helpers_fixtures as hf  # noqa: E402

REAL_MVAR = os.path.expanduser("~/Local_Documents/Halo-MCC/forge/real-mvar-samples/0aaaf8c7-5ae6-43ba-bb4d-37c987f5e8b8.mvar")

_data = {}
_models = {}


def build_modules():
    return hf.modules()


def names():
    return hf.all_names()


def spec(name):
    build, _ = hf.modules()
    return build.load_spec(name)


def declared(name):
    build, _ = hf.modules()
    return build.normalise(spec(name))


def positive_names():
    return [n for n in names() if spec(n)["role"] == "positive"]


def negative_names():
    return [n for n in names() if spec(n)["role"] == "negative"]


def data(name):
    if name not in _data:
        _data[name] = hf.fixture_bytes(name)
    return _data[name]


def model(name):
    from mvarlib.model import MapVariant
    if name not in _models:
        _models[name] = MapVariant.from_bytes(data(name))
    return _models[name]


def real_available():
    return os.path.isfile(REAL_MVAR)


def real_data():
    """The real map variant, read in place (opened ``rb`` only)."""
    with open(REAL_MVAR, "rb") as handle:
        return handle.read()
