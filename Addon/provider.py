"""The only door from the Blender glue to the library (SPEC 8.1, cross-gate contract of section 11).

The glue (``mjolnir.py``, ``io_ops.py``, ``palette.py``, ``state.py``) imports ``mvarlib`` through
this module and nothing else::

    P = provider.get_provider()
    result = P.load_map_variant(data, name)
    obj = P.ExportObject(name=..., ...)          # never import the api types directly
    except P.MvarError: ...                      # error classes are re-exported by the provider

The provider is a module-like namespace carrying the names of ``mvarlib.api`` (``REQUIRED_NAMES``).
The production default is the add-on's own ``mvarlib.api`` module; tests inject
``tests/stubs/stub_mvarlib.py`` with :func:`set_provider`. Inside Blender the real library is
``<extension>.mvarlib`` while the stub imports the repository copy as ``mvarlib``: two module
identities, which is why the glue builds every api object through ``P`` and never uses
``isinstance`` on api types.

This file is importable both as a package member (``<extension>.provider``, inside Blender) and as
a top-level module (``import provider`` with ``Addon/`` on ``sys.path``, in the tests). It does
nothing at import time (no ``bpy`` access, no file or network I/O).
"""

# The names every provider must carry: exactly ``mvarlib.api.__all__`` (checked by a unit test).
REQUIRED_NAMES = (
    "Vec3", "Bounds", "Issue", "MapInfo", "ObjectRecord", "LoadResult", "ExportObject", "ExportOptions",
    "DiffEntry", "ExportResult", "ReadOptions", "load_map_variant", "export_map_variant",
    "map_name_for_id", "stock_object_names", "palette_tree", "check_output_path", "write_atomic",
    "MvarError", "FormatError", "BlfFormatError", "UnsupportedVariantError", "DesyncError",
    "AmbiguousLayoutError", "OutOfBoundsPositionError", "DecodeError", "EncodeError", "CapacityError",
    "HashError", "ValidationError", "PathPolicyError", "InternalError",
)

_provider = None


def _default_provider():
    """The add-on's own ``mvarlib.api`` module (package member inside Blender, top-level in tests)."""
    if __package__:
        from .mvarlib import api
    else:
        from mvarlib import api
    return api


def _default_tables():
    """The add-on's own ``mvarlib.tables`` (the stock tables are data, the same whichever provider is active)."""
    if __package__:
        from .mvarlib import tables
    else:
        from mvarlib import tables
    return tables


def object_folder(map_name, name):
    """Palette folder (``id >> 8``) of the stock object ``name`` on ``map_name``, or ``None`` when it is not a stock name.

    An OPTIONAL helper of the glue, not part of the frozen api (so ``REQUIRED_NAMES`` is unchanged): the Add menu
    needs it to leave out the entries whose folder lies beyond the quota count of the loaded template (SPEC 8.6
    per-map filter, G5 defect 12: such an object can never be exported to that file, ``E_FOLDER_RANGE``). A provider
    may offer ``object_id_for_name(map_name, name)`` itself; otherwise the add-on's own tables answer.
    """
    lookup = getattr(get_provider(), "object_id_for_name", None) or _default_tables().object_id_for_name
    object_id = lookup(map_name, name)
    return None if object_id is None else (int(object_id) >> 8)


def missing_names(candidate):
    """Names of ``REQUIRED_NAMES`` that ``candidate`` does not carry."""
    return [n for n in REQUIRED_NAMES if not hasattr(candidate, n)]


def get_provider():
    """The active provider (the real ``mvarlib.api`` unless :func:`set_provider` replaced it)."""
    global _provider
    if _provider is None:
        _provider = _default_provider()
    return _provider


def set_provider(provider):
    """Install ``provider`` (``None`` restores the default). Returns the previously active provider.

    Raises ``TypeError`` listing the missing names when the candidate does not carry the whole api.
    """
    global _provider
    previous = _provider
    if provider is not None:
        missing = missing_names(provider)
        if missing:
            raise TypeError("provider is missing required names: %s" % ", ".join(missing))
    _provider = provider
    return previous if previous is not None else _default_provider()
