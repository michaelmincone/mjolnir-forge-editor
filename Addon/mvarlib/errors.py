"""Exception hierarchy of ``mvarlib`` (SPEC section 6.2).

FROZEN at G0 together with ``api.py`` ("interface freeze v1": the SHA-256 of both files is
recorded in ``tests/golden/interface_sha256.json`` and ``NOTES.md``; test U-22 fails when either
file changes). This module imports nothing from the package, so ``api.py`` can re-export every
class without an import cycle. Pure Python 3.9 to 3.13, standard library only, no ``bpy``.

Hierarchy::

    MvarError(Exception)
     +-- FormatError                  the input is not a supported map variant
     |    +-- BlfFormatError          container: not blf, bad tiling, truncated, bad _cmp, bad stored length
     |    +-- UnsupportedVariantError not a map variant, mvar size != 0x7028, body version not in {31, 32},
     |    |                           known non-Reach chunk version, content type
     |    +-- DesyncError             no hypothesis accepted; .diagnostics = per-hypothesis first failure
     |    +-- AmbiguousLayoutError    several hypotheses accepted with different decodes; .candidates
     |    +-- OutOfBoundsPositionError in_bounds == 0 at slot N (.slot)
     +-- DecodeError                  a field value is invalid (up-code face > 5, ...)
     +-- EncodeError                  a value cannot be represented (dimension > 200, position outside bounds, ...)
     +-- CapacityError                the stream would exceed 0x7000 bytes
     +-- HashError                    internal hash/flavour failure
     +-- ValidationError              export refused; .issues = List[Issue] (all problems, not just the first)
     +-- PathPolicyError              output path forbidden (SPEC 2.13)
     +-- InternalError                invariant I1/I2 violated: a library bug, never a user error

Every message is a complete sentence a user can act on; none contains a traceback. The extra
attributes default to empty values, so every class can also be built from a message alone (which
keeps instances picklable and copyable).
"""

__all__ = [
    "MvarError", "FormatError", "BlfFormatError", "UnsupportedVariantError", "DesyncError",
    "AmbiguousLayoutError", "OutOfBoundsPositionError", "DecodeError", "EncodeError", "CapacityError",
    "HashError", "ValidationError", "PathPolicyError", "InternalError",
]


class MvarError(Exception):
    """Base class of every error raised on purpose by ``mvarlib``."""


class FormatError(MvarError):
    """The input is not a supported map variant."""


class BlfFormatError(FormatError):
    """Container problem: not a BLF file, blocks do not tile, truncated, bad ``_cmp``, bad stored length."""


class UnsupportedVariantError(FormatError):
    """Not a map variant, wrong ``mvar`` size, unsupported body or chunk version, wrong content type."""


class DesyncError(FormatError):
    """No hypothesis gave an accepted walk.

    ``diagnostics`` holds one entry per hypothesis (first failing check, slot index, bit position).
    """

    def __init__(self, message="", diagnostics=None):
        super().__init__(message)
        self.diagnostics = list(diagnostics) if diagnostics else []


class AmbiguousLayoutError(FormatError):
    """Several hypotheses were accepted and decode differently.

    ``candidates`` lists them (for each: its ``end`` bit and the first differing slot).
    """

    def __init__(self, message="", candidates=None):
        super().__init__(message)
        self.candidates = list(candidates) if candidates else []


class OutOfBoundsPositionError(FormatError):
    """A present slot has ``in_bounds == 0``; ``slot`` is its index (None when unknown)."""

    def __init__(self, message="", slot=None):
        super().__init__(message)
        self.slot = slot


class DecodeError(MvarError):
    """A field value is invalid and cannot be decoded (for example an up-axis code with face > 5)."""


class EncodeError(MvarError):
    """A value cannot be represented in the file (dimension above 200, position outside the bounds, ...)."""


class CapacityError(MvarError):
    """The bit stream would exceed the 0x7000-byte capacity of the ``mvar`` block."""


class HashError(MvarError):
    """Internal hash or flavour failure."""


class ValidationError(MvarError):
    """Export refused.

    ``issues`` is a plain list of ``api.Issue`` objects: all problems, not just the first. When no
    message is given one is built from the first issue.
    """

    def __init__(self, message="", issues=None):
        issues = list(issues) if issues else []
        if not message and issues:
            first = getattr(issues[0], "message", None) or str(issues[0])
            message = "Export refused: %d problem(s); first: %s" % (len(issues), first)
        super().__init__(message)
        self.issues = issues


class PathPolicyError(MvarError):
    """The output path is forbidden (same file as a source, or inside a protected folder)."""


class InternalError(MvarError):
    """Invariant I1/I2 violated: a library bug, never a user error."""
