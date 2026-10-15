"""Independent fixture builder for the T2 tests (SPEC 9.1, DEC-9.2, section 11 G2).

A second, separately written implementation of the map-variant file format: its own big-integer bit writer
(``bits``), literal tables copied from the spec (``consts``), a table-driven builder (``build``), the fixture
catalogue (``catalogue``) and an independent walker used to check the builder (``selfcheck``).

Nothing in this package imports the library under test; a unit test scans every module here for that.
Import it with ``tests/`` on ``sys.path``::

    import fixturebuilder
    from fixturebuilder import build, selfcheck
"""

__all__ = ["bits", "consts", "build", "catalogue", "selfcheck"]
